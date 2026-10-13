"""Companion backend: loopback-only HTTP server that wires together the swappable parts in config.json.

  LLM (reasoning model)  -> companion/llm.py
  Voice (text-to-speech) -> companion/tts.py
  Hearing (speech-to-text) -> companion/stt.py
  Screen awareness       -> companion/screen.py
"""
import atexit
from datetime import datetime
import json
import logging
import os
import re
import sqlite3
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from companion import config as cfg, llm, stt, tts
from companion.config import ROOT
from companion import screen

WEB = ROOT / 'web'
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
logging.basicConfig(filename=DATA / 'server.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
DB = DATA / 'chat.sqlite3'
PORT = 8765
APP_ID = 'anime-companion'
EMOTIONS = ('neutral', 'happy', 'excited', 'sad', 'angry', 'surprised', 'shy', 'thinking')
chat_lock = threading.Lock()
cfg.load_env()

with sqlite3.connect(DB) as db:
    db.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created REAL)')
    if 'note' not in [row[1] for row in db.execute('PRAGMA table_info(messages)')]:
        db.execute('ALTER TABLE messages ADD COLUMN note TEXT')


def history(limit=100):
    with sqlite3.connect(DB) as db:
        rows = db.execute('SELECT role, content, note FROM messages ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [{'role': r, 'content': c, 'note': n} for r, c, n in reversed(rows)]


def save_message(role, content, note=None):
    with sqlite3.connect(DB) as db:
        db.execute('INSERT INTO messages(role, content, created, note) VALUES(?,?,?,?)',
                   (role, content, time.time(), note))


class Component:
    """One swappable part (llm / voice / hearing): loads the active preset in the background."""

    def __init__(self, section, factory):
        self.section, self.factory = section, factory
        self.impl, self.state, self.detail, self.preset_name, self.needs_key = None, 'loading', '', '', None
        self.lock = threading.Lock()

    def load(self):
        threading.Thread(target=self._load, daemon=True, name=f'load-{self.section}').start()

    def _load(self):
        with self.lock:
            self.state, self.detail, self.needs_key = 'loading', '', None
            old, self.impl = self.impl, None
            if old and hasattr(old, 'stop'):
                old.stop()
            try:
                self.preset_name, preset = cfg.active_preset(cfg.load(), self.section)
                impl = self.factory(preset)
                impl.start()
                self.impl, self.state = impl, 'ready'
                if hasattr(impl, 'prime'):
                    prime_soon()
            except cfg.MissingKey as e:
                self.state, self.detail, self.needs_key = 'needs_key', str(e), e.env_name
            except Exception as e:
                logging.exception('%s startup failed', self.section)
                self.state, self.detail = 'error', str(e)

    def get(self):
        if self.state != 'ready' or not self.impl:
            names = {'llm': 'The reasoning model', 'voice': 'The voice', 'hearing': 'Speech recognition'}
            raise Unavailable(f'{names[self.section]} is not ready: {self.detail or self.state}')
        return self.impl

    def status(self):
        return {'state': self.state, 'detail': self.detail, 'preset': self.preset_name, 'needs_key': self.needs_key}

    def stop(self):
        if self.impl and hasattr(self.impl, 'stop'):
            self.impl.stop()


class Unavailable(RuntimeError):
    pass


COMPONENTS = {'llm': Component('llm', llm.create), 'voice': Component('voice', tts.create),
              'hearing': Component('hearing', stt.create)}
tracker = screen.Tracker()
proactive_memory = {'fingerprint': None, 'label': None}


def cleanup():
    for component in COMPONENTS.values():
        component.stop()


atexit.register(cleanup)


def avatars():
    return json.loads((WEB / 'models/avatars.json').read_text(encoding='utf-8'))


def character_name(conf):
    if conf['character'].get('name'):
        return conf['character']['name']
    return avatars().get(conf['avatar']['active'], {}).get('name', 'Companion')


def system_prompt(conf, model):
    name = character_name(conf)
    text = (ROOT / conf['character'].get('personality_file', 'personality.md')).read_text(encoding='utf-8')
    parts = [text.replace('{name}', name)]
    mode = conf['screen']['mode']
    if mode == 'off':
        parts.append('You cannot see the user\'s screen right now (they turned it off in Settings).')
    elif model.vision:
        parts.append('You can see the user\'s PC: you may be shown a screenshot of the window they are using. '
                     'React to it naturally like a friend sitting next to them. Never read out passwords, '
                     'private messages or personal data you might see.')
        if mode == 'tool':
            parts.append('Use the look_at_screen tool whenever the user refers to what they are doing or seeing.')
    else:
        parts.append('You can\'t see images with the current model, but you may be told the title of the window '
                     'the user is using.')
    parts.append('The user\'s newest message starts with a note in parentheses from the app (the time, and the window '
                 'they have open). The user did not write it; only bring it up when it is relevant.')
    if conf['character'].get('emotion_tags', True):
        parts.append('Start every reply with exactly one emotion tag from: ' + ', '.join(f'[{e}]' for e in EMOTIONS) +
                     '. It controls your face and is not spoken. Example: "[excited] No way, you beat that boss?!"')
    return '\n\n'.join(parts)


def situation(conf):
    """What changes from message to message (time, active window). It goes with the new message, not into the
    system prompt, so the prompt's beginning stays identical and a local model can reuse its cached work."""
    parts = [datetime.now().strftime('%a %d %b %Y, %H:%M')]
    if conf['screen']['mode'] != 'off' and conf['screen'].get('share_window_title', True):
        window = tracker.current()
        if window:  # kept short: every token here is read before each reply
            title = window[0] if len(window[0]) <= 60 else window[0][:57] + '...'
            parts.append(f'user\'s window: {window[1]} — "{title}"')
    return '(' + '; '.join(parts) + ')\n'


def context(conf):
    limit = max(2, conf['memory'].get('context_messages', 30))
    step = max(2, limit // 2)
    with sqlite3.connect(DB) as db:
        total = db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        # Forget old messages a chunk at a time, not one per turn, so the history's start rarely changes
        # (a change makes a local model re-read the whole conversation).
        drop = -(-max(0, total - limit) // step) * step
        rows = db.execute('SELECT role, content, note FROM messages ORDER BY id LIMIT -1 OFFSET ?', (drop,)).fetchall()
    return [{'role': r, 'content': c + (f' [{n}]' if n else '')} for r, c, n in rows]


priming = threading.Lock()


def prime_soon():
    """Let a local model read the conversation in the background, so the next reply only reads the new message."""
    def run():
        if not priming.acquire(blocking=False):
            return
        try:
            model = COMPONENTS['llm'].impl
            if model is not None and hasattr(model, 'prime'):
                conf = cfg.load()
                started = time.time()
                model.prime(system_prompt(conf, model), context(conf))
                logging.info('Primed the local model in %.1fs', time.time() - started)
        except Exception:
            logging.warning('Priming the local model failed', exc_info=True)
        finally:
            priming.release()
    threading.Thread(target=run, daemon=True, name='prime').start()


def split_emotion(reply):
    reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.S).strip()
    emotion = 'neutral'
    match = re.match(r'^\s*\[(\w+)\]\s*', reply)
    if match:
        emotion = match.group(1).lower() if match.group(1).lower() in EMOTIONS else 'neutral'
        reply = reply[match.end():]
    reply = re.sub(r'\[(?:' + '|'.join(EMOTIONS) + r')\]\s*', '', reply, flags=re.I).strip()
    return reply, emotion


def capture(conf):
    return tracker.capture(conf['screen'].get('max_width', 1280), conf['screen'].get('jpeg_quality', 70))


class ReplyStream:
    """Passes streamed reply text to `send` as events; the leading [emotion] tag becomes its own event."""

    def __init__(self, send):
        self.send, self.head, self.started = send, '', False

    def __call__(self, delta):
        if self.started:
            return self.send({'delta': delta})
        self.head += delta
        head = self.head.lstrip()
        if not head or (head.startswith('[') and ']' not in head and len(head) < 24):
            return  # wait until we know whether it starts with a tag
        self.started = True
        match = re.match(r'\[(\w+)\]\s*', head)
        if match:
            emotion = match.group(1).lower()
            self.send({'emotion': emotion if emotion in EMOTIONS else 'neutral'})
            head = head[match.end():]
        if head:
            self.send({'delta': head})


def converse(text, force_look=False, on_text=None):
    conf = cfg.load()
    model = COMPONENTS['llm'].get()
    mode = conf['screen']['mode']
    messages = context(conf)
    user = {'role': 'user', 'content': situation(conf) + text}
    shot, look = None, None
    if force_look or mode == 'always':
        shot = capture(conf)
        if shot.image and model.vision:
            user['images'] = [shot.image]
            user['content'] += f'\n\n(Attached: screenshot of my current window, {shot.label()}.)'
        else:
            user['content'] += f'\n\n({shot.tool_text()})'
    elif mode == 'tool':
        def look():
            nonlocal shot
            shot = capture(conf)
            return shot
    messages.append(user)
    reply, tool_shot = model.reply(system_prompt(conf, model), messages, look, on_text)
    shot = shot or tool_shot
    reply, emotion = split_emotion(reply)
    if not reply:
        raise RuntimeError('The model returned an empty reply.')
    note = f'looked at: {shot.label()}' if shot and shot.image else None
    save_message('user', text, note)
    save_message('assistant', reply)
    prime_soon()
    return {'text': reply, 'emotion': emotion, 'looked': shot.label() if shot and shot.image else None}


def glance():
    """Proactive: peek at the screen and maybe say something, without the user asking."""
    conf = cfg.load()
    if conf['screen']['mode'] == 'off':
        return {'skip': True, 'reason': 'screen awareness is off'}
    model = COMPONENTS['llm'].get()
    if not model.vision:
        return {'skip': True, 'reason': 'the current model cannot see images'}
    shot = capture(conf)
    if not shot.image:
        return {'skip': True, 'reason': shot.note}
    fp = screen.fingerprint(shot.image)
    if proactive_memory['label'] == shot.label() and screen.similar(fp, proactive_memory['fingerprint']):
        return {'skip': True, 'reason': 'nothing changed'}
    proactive_memory.update(fingerprint=fp, label=shot.label())
    messages = context(conf)
    messages.append({'role': 'user', 'images': [shot.image], 'content': situation(conf) +
                     f'(Automatic glance — the user did not say anything. This is their screen right now: {shot.label()}. '
                     'If there is something fun, interesting or genuinely helpful to say about it, say ONE short line in '
                     'character. If not, or if it looks private (passwords, banking, personal chats), reply exactly [skip].)'})
    reply, _ = model.reply(system_prompt(conf, model), messages, None)
    if '[skip]' in reply.lower() or not reply.strip():
        return {'skip': True, 'reason': 'nothing worth saying'}
    reply, emotion = split_emotion(reply)
    save_message('assistant', reply, f'said unprompted while looking at: {shot.label()}')
    prime_soon()
    return {'text': reply, 'emotion': emotion, 'looked': shot.label()}


def public_config():
    conf = cfg.load()
    sections = {}
    keys = {}
    for section in ('llm', 'voice', 'hearing'):
        presets = []
        for name, p in conf[section]['presets'].items():
            env = p.get('api_key_env')
            if env:
                keys[env] = bool(os.environ.get(env))
            presets.append({'name': name, 'label': p.get('label', name), 'key': env})
        sections[section] = {'active': conf[section]['active'], 'presets': presets}
    return {
        'character': {'name': character_name(conf)},
        'avatar': conf['avatar']['active'],
        'avatars': {k: v for k, v in avatars().items() if not k.startswith('_')},
        'sections': sections,
        'voice_speed': conf['voice'].get('speed', 1.0),
        'screen': {k: v for k, v in conf['screen'].items() if not k.startswith('_')},
        'keys': keys,
        'ui': conf.get('ui', {}),
        'desktop': conf.get('desktop', {}),
    }


def update_config(payload):
    conf = cfg.load()
    reload = []
    for section in ('llm', 'voice', 'hearing'):
        name = payload.get(section)
        if name is not None:
            if name not in conf[section]['presets']:
                raise ValueError(f'Unknown {section} preset: {name}')
            if conf[section]['active'] != name:
                conf[section]['active'] = name
                reload.append(section)
    if 'avatar' in payload:
        if payload['avatar'] not in avatars():
            raise ValueError('Unknown avatar.')
        conf['avatar']['active'] = payload['avatar']
    if 'voice_speed' in payload:
        conf['voice']['speed'] = max(0.7, min(1.4, float(payload['voice_speed'])))
    if 'character_name' in payload:
        conf['character']['name'] = str(payload['character_name'])[:40].strip()
    for key, kind in (('mode', str), ('proactive', bool), ('proactive_interval_seconds', int)):
        if key in payload.get('screen', {}):
            value = kind(payload['screen'][key])
            if key == 'mode' and value not in ('off', 'tool', 'always'):
                raise ValueError('Screen mode must be off, tool or always.')
            if key == 'proactive_interval_seconds':
                value = max(20, min(3600, value))
            conf['screen'][key] = value
    cfg.save(conf)
    for section in reload:
        COMPONENTS[section].load()
    prime_soon()  # the system prompt may have changed (name, screen mode)
    return public_config()


def set_key(payload):
    name, value = payload.get('name', ''), payload.get('value', '').strip()
    conf = cfg.load()
    allowed = {p.get('api_key_env') for s in ('llm', 'voice', 'hearing') for p in conf[s]['presets'].values()}
    if name not in allowed - {None}:
        raise ValueError('That key is not used by any preset.')
    if '\n' in value or len(value) > 400:
        raise ValueError('That does not look like an API key.')
    cfg.set_env_key(name, value)
    for section, component in COMPONENTS.items():
        if cfg.active_preset(conf, section)[1].get('api_key_env') == name:
            component.load()
    return public_config()


def clean_for_speech(text):
    text, _ = split_emotion(text)
    text = re.sub(r'\*[^*]*\*', '', text)
    text = re.sub(r'https?://\S+', 'this link', text)
    text = re.sub('[\U0001F000-\U0001FAFF☀-➿️‍]', '', text)  # emojis
    return text.replace('#', '').replace('`', '').strip()


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.json': 'application/json',
                      '.moc3': 'application/octet-stream', '.js': 'text/javascript'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def allowed(self):
        hosts = {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}
        origin = self.headers.get('Origin')
        return self.headers.get('Host') in hosts and (origin is None or origin in {f'http://{h}' for h in hosts})

    def respond(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        if not self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_GET(self):
        if not self.allowed():
            return self.respond({'error': 'Local access only.'}, 403)
        if self.path == '/api/status':
            window = tracker.current()
            return self.respond({'app': APP_ID, **{k: c.status() for k, c in COMPONENTS.items()},
                                 'window': f'{window[1]} — {window[0]}' if window else None})
        if self.path == '/api/history':
            return self.respond({'messages': [{'role': m['role'], 'content': m['content']} for m in history()]})
        if self.path == '/api/config':
            return self.respond(public_config())
        if self.path.startswith('/api/pi/'):
            # Only the pi process we started knows this token.
            if self.headers.get('X-Companion-Token') != llm.PiAgent.bridge['token']:
                return self.respond({'error': 'Forbidden'}, 403)
            if self.path == '/api/pi/system':
                return self.respond({'system': llm.PiAgent.bridge['system']})
            if self.path == '/api/pi/look':
                return self.respond(llm.PiAgent.bridge_look())
        if self.path.startswith('/api/'):
            return self.respond({'error': 'Not found'}, 404)
        return super().do_GET()

    def do_POST(self):
        if not self.allowed():
            return self.respond({'error': 'Local access only.'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 0 or length > 12_000_000:
                return self.respond({'error': 'Request too large.'}, 413)
            raw = self.rfile.read(length) if length else b''
            if self.path == '/api/transcribe':
                if not raw:
                    return self.respond({'error': 'Empty recording.'}, 400)
                text = COMPONENTS['hearing'].get().transcribe(raw, self.headers.get('X-Audio-Type', ''))
                return self.respond({'text': text})
            payload = json.loads(raw or b'{}')
            route = {'/api/chat': self.chat, '/api/proactive': self.proactive, '/api/speech': self.speech,
                     '/api/config': lambda p: self.respond(update_config(p)),
                     '/api/keys': lambda p: self.respond(set_key(p)),
                     '/api/clear': self.clear, '/api/shutdown': self.shutdown}.get(self.path)
            if not route:
                return self.respond({'error': 'Not found'}, 404)
            return route(payload)
        except Unavailable as e:
            self.respond({'error': str(e)}, 503)
        except (ValueError, TypeError, KeyError) as e:
            self.respond({'error': f'Invalid request: {e}'}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logging.exception('Request failed: %s', self.path)
            self.respond({'error': str(e) or 'Something failed. See data/server.log.'}, 500)

    def chat(self, payload):
        text = payload.get('text', '')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return self.respond({'error': 'Send a message between 1 and 4,000 characters.'}, 400)
        if not chat_lock.acquire(blocking=False):
            return self.respond({'error': 'Still thinking about the last message. One sec!'}, 409)
        try:
            if payload.get('stream'):
                return self.chat_stream(text.strip(), bool(payload.get('look')))
            return self.respond(converse(text.strip(), bool(payload.get('look'))))
        finally:
            chat_lock.release()

    def chat_stream(self, text, look):
        """Newline-delimited JSON events while the reply is written: {"emotion"}, {"delta"}..., then {"done", ...}."""
        COMPONENTS['llm'].get()  # not ready -> a normal error response instead of a stream
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        connected = True

        def send(event):
            nonlocal connected
            if not connected:
                return
            try:
                self.wfile.write(json.dumps(event, ensure_ascii=False).encode('utf-8') + b'\n')
                self.wfile.flush()
            except OSError:
                connected = False  # the page went away; still finish so the reply is saved

        try:
            result = converse(text, look, ReplyStream(send))
        except Exception as e:
            if not isinstance(e, Unavailable):
                logging.exception('Request failed: /api/chat (stream)')
            return send({'error': str(e) or 'Something failed. See data/server.log.'})
        send({'done': True, **result})

    def proactive(self, payload):
        if not chat_lock.acquire(blocking=False):
            return self.respond({'skip': True, 'reason': 'busy'})
        try:
            return self.respond(glance())
        finally:
            chat_lock.release()

    def speech(self, payload):
        text = clean_for_speech(payload.get('text', ''))
        if not text or len(text) > 4000:
            return self.respond({'error': 'Nothing to say out loud.'}, 400)
        speed = cfg.load()['voice'].get('speed', 1.0)
        mime, chunks = COMPONENTS['voice'].get().stream(text, speed)
        first = next(chunks, b'')  # a failure before any audio still gets a normal error response
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(first)
        try:
            for chunk in chunks:  # the page starts playing while the rest arrives
                self.wfile.write(chunk)
        except OSError:
            pass
        except Exception:
            logging.exception('Voice failed partway through')

    def clear(self, payload):
        if not chat_lock.acquire(blocking=False):
            return self.respond({'error': 'Wait for the current reply before clearing chat.'}, 409)
        try:
            with sqlite3.connect(DB) as db:
                db.execute('DELETE FROM messages')
            prime_soon()
            return self.respond({'ok': True})
        finally:
            chat_lock.release()

    def shutdown(self, payload):
        self.respond({'ok': True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


if __name__ == '__main__':
    httpd = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    for component in COMPONENTS.values():
        component.load()
    logging.info('Companion starting on loopback port %s', PORT)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        cleanup()
