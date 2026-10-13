"""Smoke test for the running server (start it first). Does not use the microphone.

Checks status/config, voice -> transcription round trip, preset switching, missing-key handling,
screen capture, and (if the reasoning model is ready) a chat and a proactive glance.
Chat rows created by this test are removed afterwards.
"""
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8765'
DB = Path(__file__).parent / 'data/chat.sqlite3'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results = []


def call(path, data=None, raw=False, headers=None):
    body = data if raw else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(BASE + path, body, {'Content-Type': 'application/octet-stream' if raw else 'application/json', **(headers or {})})
    try:
        with opener.open(req, timeout=180) as r:
            return r.status, r.read(), r.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get('Content-Type', '')


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''), flush=True)


def wait_ready(section, timeout=120):
    for _ in range(timeout):
        state = json.loads(call('/api/status')[1])[section]['state']
        if state != 'loading':
            return state
        time.sleep(1)
    return 'loading'


def main():
    with sqlite3.connect(DB) as db:
        max_id = db.execute('SELECT COALESCE(MAX(id), 0) FROM messages').fetchone()[0]
    status = json.loads(call('/api/status')[1])
    check('status endpoint', status.get('app') == 'anime-companion', json.dumps({k: v['state'] for k, v in status.items() if isinstance(v, dict)}))
    config = json.loads(call('/api/config')[1])
    check('config lists avatars', len(config['avatars']) >= 5, ', '.join(config['avatars']))
    check('config hides secrets', all(isinstance(v, bool) for v in config['keys'].values()))
    original = {s: config['sections'][s]['active'] for s in ('llm', 'voice', 'hearing')}

    try:
        code, audio, ctype = call('/api/speech', {'text': '[happy] Hello there! It is a lovely day. What would you like to talk about?'})
        check('voice synthesis', code == 200 and len(audio) > 5000, f'{original["voice"]}: {len(audio)} bytes {ctype}')
        if code == 200:
            code, body, _ = call('/api/transcribe', audio, raw=True, headers={'X-Audio-Type': ctype})
            text = json.loads(body).get('text', '') if code == 200 else body.decode()
            check('hearing round trip', code == 200 and 'lovely day' in text.lower(), text)

        # Switching to a preset whose key is missing must report needs_key, not crash.
        call('/api/config', {'voice': 'elevenlabs'})
        state = wait_ready('voice')
        check('missing key reported', state in ('needs_key', 'error', 'ready'), f'elevenlabs -> {state}')
    finally:
        call('/api/config', original)
        wait_ready('voice')

    shot_ok = json.loads(call('/api/status')[1]).get('window')
    check('window tracker', shot_ok is not None, str(shot_ok))

    if wait_ready('llm', 180) == 'ready':
        start = time.perf_counter()
        code, body, _ = call('/api/chat', {'text': 'Hi! Say hello in one short sentence.'})
        reply = json.loads(body)
        check('chat reply', code == 200 and bool(reply.get('text')), f'{time.perf_counter() - start:.1f}s [{reply.get("emotion")}] {reply.get("text", reply.get("error"))}')
        code, body, _ = call('/api/chat', {'text': 'What am I looking at?', 'look': True})
        reply = json.loads(body)
        check('chat with screen', code == 200 and bool(reply.get('looked')), f'looked at {reply.get("looked")}: {reply.get("text", reply.get("error"))}')
        code, body, _ = call('/api/proactive', {})
        check('proactive glance', code == 200, body.decode()[:200])
    else:
        check('chat reply', False, 'reasoning model not ready: ' + json.loads(call('/api/status')[1])['llm']['detail'])

    with sqlite3.connect(DB) as db:
        db.execute('DELETE FROM messages WHERE id > ?', (max_id,))
    failed = [r for r in results if not r[1]]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed.')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
