"""Reasoning-model providers. Add a new one by writing a class with reply() and registering it in PROVIDERS.

Messages are plain dicts: {'role': 'user'|'assistant', 'content': str, 'images': [jpeg_base64, ...]}.
`look` is an optional callable that captures the user's current window; when given (and the model has
vision) the model receives a `look_at_screen` tool it may call on its own.
"""
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import threading
import time

from . import config as cfg
from .config import ROOT
from .net import request_json, stream_events, ApiError

LOOK_TOOL_NAME = 'look_at_screen'
LOOK_TOOL_DESCRIPTION = (
    "Take a screenshot of the window the user currently has open on their PC (never the companion itself). "
    "Call this whenever the user refers to what they are doing, watching, reading, playing or working on, "
    "asks for help with something on screen, or says things like 'look', 'see this', 'what do you think of this'.")


class ChatModel:
    vision = False

    def __init__(self, preset):
        self.preset = preset
        self.vision = bool(preset.get('vision', False))

    def start(self):
        """Validate settings / start local engines. Raise to report an error."""

    def stop(self):
        pass

    def describe(self):
        return self.preset.get('model', '?')


class OpenAICompatible(ChatModel):
    """OpenAI Chat Completions format: OpenAI, OpenRouter, Groq, Gemini, Ollama, LM Studio, llama.cpp..."""

    def start(self):
        cfg.api_key(self.preset)  # raises MissingKey early so Settings can show it

    def _url(self):
        return self.preset.get('base_url', 'https://api.openai.com/v1').rstrip('/') + '/chat/completions'

    def _headers(self):
        headers = dict(self.preset.get('headers', {}))
        key = cfg.api_key(self.preset)
        if key:
            headers['Authorization'] = f'Bearer {key}'
        return headers

    @staticmethod
    def _image_part(b64, detail):
        return {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64, 'detail': detail}}

    def _convert(self, m):
        images = m.get('images') if self.vision else None
        if not images:
            return {'role': m['role'], 'content': m['content']}
        detail = self.preset.get('image_detail', 'auto')
        return {'role': m['role'], 'content': [{'type': 'text', 'text': m['content']}] +
                [self._image_part(b, detail) for b in images]}

    def _call(self, messages, tools=None, tool_choice=None, on_text=None):
        body = {'model': self.preset['model'], 'messages': messages, 'stream': bool(on_text)}
        body.update(self.preset.get('params', {}))
        if tools:
            body['tools'] = tools
            if tool_choice:
                body['tool_choice'] = tool_choice
        timeout = self.preset.get('timeout', 120)
        if on_text:
            return self._stream(body, timeout, on_text)
        result = request_json(self._url(), body, self._headers(), timeout=timeout)
        if 'choices' not in result or not result['choices']:
            raise ApiError(f'Unexpected reply from {self.describe()}: {str(result)[:300]}')
        return result['choices'][0]['message']

    def _stream(self, body, timeout, on_text):
        """Streams the reply, passing text on as it arrives; returns it shaped like a non-streamed message."""
        content, calls = [], {}
        for event in stream_events(self._url(), body, self._headers(), timeout=timeout):
            if event.get('error'):
                error = event['error']
                raise ApiError(f'{self.describe()}: {error.get("message", error) if isinstance(error, dict) else error}')
            for choice in event.get('choices') or []:
                delta = choice.get('delta') or {}
                if delta.get('content'):
                    content.append(delta['content'])
                    on_text(delta['content'])
                for call in delta.get('tool_calls') or []:
                    slot = calls.setdefault(call.get('index', 0),
                                            {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                    slot['id'] = call.get('id') or slot['id']
                    function = call.get('function') or {}
                    slot['function']['name'] += function.get('name') or ''
                    slot['function']['arguments'] += function.get('arguments') or ''
        return {'content': ''.join(content), 'tool_calls': [calls[i] for i in sorted(calls)]}

    def reply(self, system, messages, look=None, on_text=None):
        msgs = [{'role': 'system', 'content': system}] + [self._convert(m) for m in messages]
        tools = None
        if look and self.vision:
            tools = [{'type': 'function', 'function': {
                'name': LOOK_TOOL_NAME, 'description': LOOK_TOOL_DESCRIPTION,
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}]
        message = self._call(msgs, tools, on_text=on_text)
        calls = message.get('tool_calls') or []
        if not calls:
            return message.get('content') or '', None
        shot = look()
        msgs.append({'role': 'assistant', 'content': message.get('content') or None, 'tool_calls': calls})
        for call in calls:
            msgs.append({'role': 'tool', 'tool_call_id': call['id'],
                         'content': shot.tool_text() if shot else 'Screenshot failed.'})
        if shot and shot.image:
            # Chat Completions tool results are text-only, so the picture follows as a user message.
            msgs.append(self._convert({'role': 'user', 'content': '(Screenshot from look_at_screen)',
                                       'images': [shot.image]}))
        before = message.get('content') or ''
        if on_text and before:
            on_text(' ')
        message = self._call(msgs, tools, tool_choice='none', on_text=on_text)
        return (before + ' ' + (message.get('content') or '')).strip(), shot


class Anthropic(ChatModel):
    def start(self):
        cfg.api_key(self.preset)

    def _headers(self):
        return {'x-api-key': cfg.api_key(self.preset), 'anthropic-version': '2023-06-01'}

    def _convert(self, m):
        images = m.get('images') if self.vision else None
        if not images:
            return {'role': m['role'], 'content': m['content']}
        return {'role': m['role'], 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': b}} for b in images
        ] + [{'type': 'text', 'text': m['content']}]}

    @staticmethod
    def _normalize(msgs):
        """The Messages API needs a user turn first and alternating roles."""
        out = []
        for m in msgs:
            if out and out[-1]['role'] == m['role'] and isinstance(m['content'], str) and isinstance(out[-1]['content'], str):
                out[-1] = {'role': m['role'], 'content': out[-1]['content'] + '\n\n' + m['content']}
            else:
                out.append(m)
        while out and out[0]['role'] != 'user':
            out.pop(0)
        return out

    def _call(self, system, msgs, tools=None):
        body = {'model': self.preset['model'], 'system': system, 'messages': msgs, 'max_tokens': 1024}
        body.update(self.preset.get('params', {}))
        if tools:
            body['tools'] = tools
        url = self.preset.get('base_url', 'https://api.anthropic.com/v1').rstrip('/') + '/messages'
        return request_json(url, body, self._headers(), timeout=self.preset.get('timeout', 120))

    @staticmethod
    def _text(result):
        return ''.join(b.get('text', '') for b in result.get('content', []) if b.get('type') == 'text')

    def reply(self, system, messages, look=None, on_text=None):
        text, shot = self._reply(system, messages, look)
        if on_text and text:
            on_text(text)  # not streamed yet: the whole reply arrives at once
        return text, shot

    def _reply(self, system, messages, look):
        msgs = self._normalize([self._convert(m) for m in messages])
        tools = None
        if look and self.vision:
            tools = [{'name': LOOK_TOOL_NAME, 'description': LOOK_TOOL_DESCRIPTION,
                      'input_schema': {'type': 'object', 'properties': {}}}]
        result = self._call(system, msgs, tools)
        uses = [b for b in result.get('content', []) if b.get('type') == 'tool_use']
        if not uses:
            return self._text(result), None
        shot = look()
        msgs.append({'role': 'assistant', 'content': result['content']})
        results = []
        for use in uses:
            content = [{'type': 'text', 'text': shot.tool_text() if shot else 'Screenshot failed.'}]
            if shot and shot.image:
                content.insert(0, {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': shot.image}})
            results.append({'type': 'tool_result', 'tool_use_id': use['id'], 'content': content})
        msgs.append({'role': 'user', 'content': results})
        return self._text(self._call(system, msgs, tools)), shot


class LlamaCpp(OpenAICompatible):
    """Runs a local GGUF model with the bundled llama.cpp server (no internet, no key)."""
    process = None

    def _url(self):
        return f'http://127.0.0.1:{self.preset.get("port", 8766)}/v1/chat/completions'

    def _headers(self):
        return {}

    def describe(self):
        return self.preset.get('model_path', 'local model')

    def start(self):
        binary = next((ROOT / 'runtime').rglob('llama-server.exe'), None)
        if not binary:
            raise RuntimeError('runtime/llama-server.exe is missing.')
        port = str(self.preset.get('port', 8766))
        args = [str(binary), '-m', str(ROOT / self.preset['model_path']), '--host', '127.0.0.1', '--port', port,
                '-c', str(self.preset.get('context', 4096)), '-t', str(self.preset.get('threads', 4)),
                '-np', '1', '-ngl', str(self.preset.get('gpu_layers', 0)), '--offline', '--jinja',
                '--no-webui', '--alias', 'local'] + [str(a) for a in self.preset.get('extra_args', [])]
        self.preset['model'] = 'local'
        with (ROOT / 'data/llama.log').open('ab') as log:
            self.process = subprocess.Popen(args, cwd=binary.parent, stdout=log, stderr=log,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(180):
            if self.process.poll() is not None:
                raise RuntimeError('Local chat engine stopped. See data/llama.log.')
            try:
                if request_json(f'http://127.0.0.1:{port}/health', timeout=2).get('status') == 'ok':
                    return
            except (ApiError, OSError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError('Local chat model took too long to start.')

    def prime(self, system, messages):
        """Read the conversation so far ahead of time. llama.cpp keeps it cached, so the next reply only has to
        process the new message instead of the whole system prompt + history (seconds vs. tens of seconds on CPU)."""
        msgs = ([{'role': 'system', 'content': system}] + [self._convert(m) for m in messages] +
                [{'role': 'user', 'content': '.'}])
        body = {'model': self.preset['model'], 'messages': msgs, 'stream': False}
        body.update(self.preset.get('params', {}))
        body['max_tokens'] = 1
        request_json(self._url(), body, timeout=self.preset.get('timeout', 120))

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class PiAgent(ChatModel):
    """Uses a subscription login (e.g. ChatGPT Plus/Pro via "openai-codex") through the pi coding agent.

    One pi process stays running in RPC mode with all tools/extensions/skills off except companion/pi_bridge.ts,
    which fetches the system prompt for each reply and provides look_at_screen (both via /api/pi/* on our server).
    Log in once inside pi itself (`pi`, then /login). Unofficial: it relies on the provider tolerating
    subscription use in third-party tools.
    """
    bridge = {'token': secrets.token_hex(16), 'system': '', 'look': None, 'shot': None}

    def __init__(self, preset):
        super().__init__(preset)
        self.process, self.records, self.lock = None, queue.Queue(), threading.Lock()

    def describe(self):
        return f'pi {self.preset.get("pi_provider")}/{self.preset.get("model")}'

    def _command(self):
        home = Path.home()
        node = self.preset.get('node') or str(Path(os.environ.get('LOCALAPPDATA', '')) / 'pi-node/current/node.exe')
        launcher = self.preset.get('launcher') or str(home / '.pi/agent/bin/pi-launcher.js')
        if not Path(node).exists():
            node = shutil.which('node') or node
        if not Path(launcher).exists():
            raise RuntimeError('pi is not installed on Windows (~/.pi/agent/bin/pi-launcher.js is missing).')
        return [node, launcher, '--mode', 'rpc', '--no-session', '--offline',
                '--provider', self.preset.get('pi_provider', 'openai-codex'), '--model', self.preset['model'],
                '--thinking', self.preset.get('thinking', 'low'),
                '--no-extensions', '--no-skills', '--no-context-files', '--no-prompt-templates', '--no-themes',
                '--no-tools', '--tools', 'look_at_screen', '-e', str(ROOT / 'companion/pi_bridge.ts')]

    def start(self):
        # Prefer IPv6: some networks (e.g. certain campus Wi-Fi) only reach OpenAI/Cloudflare over IPv6.
        env = dict(os.environ, COMPANION_PI_TOKEN=self.bridge['token'], COMPANION_URL='http://127.0.0.1:8765',
                   NODE_OPTIONS=('--dns-result-order=ipv6first ' + os.environ.get('NODE_OPTIONS', '')).strip())
        log = (ROOT / 'data/pi.log').open('ab')
        self.process = subprocess.Popen(self._command(), cwd=str(ROOT / 'data'), env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        log.close()
        threading.Thread(target=self._read, args=(self.process,), daemon=True, name='pi-reader').start()
        state = self._command_response({'type': 'get_state'}, timeout=60)
        if not state.get('success'):
            raise RuntimeError(f'pi did not start: {state.get("error")}')

    def _read(self, process):
        for line in iter(process.stdout.readline, b''):
            try:
                self.records.put(json.loads(line.rstrip(b'\r\n')))
            except ValueError:
                pass
        self.records.put({'type': '_exit'})

    def _send(self, record):
        self.process.stdin.write(json.dumps(record).encode('utf-8') + b'\n')
        self.process.stdin.flush()

    def _next(self, deadline):
        try:
            record = self.records.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            raise ApiError('pi did not answer in time.') from None
        if record.get('type') == '_exit':
            raise ApiError('pi stopped unexpectedly. See data/pi.log.')
        return record

    def _command_response(self, record, timeout=30):
        record['id'] = secrets.token_hex(4)
        self._send(record)
        deadline = time.time() + timeout
        while True:
            reply = self._next(deadline)
            if reply.get('type') == 'response' and reply.get('id') == record['id']:
                return reply

    @staticmethod
    def _transcript(messages):
        lines = []
        for m in messages[:-1]:
            lines.append(('User: ' if m['role'] == 'user' else 'You: ') + m['content'])
        current = messages[-1]['content']
        if not lines:
            return current
        return ('Conversation so far (you are "You"):\n' + '\n'.join(lines) +
                '\n\nThe user now says:\n' + current)

    NETWORK_ERRORS = ('fetch failed', 'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED', 'socket hang up')

    def reply(self, system, messages, look=None, on_text=None):
        try:
            return self._reply(system, messages, look, on_text)
        except ApiError as e:
            if not any(n in str(e) for n in self.NETWORK_ERRORS):
                raise
            logging.warning('pi network error, retrying once: %s', e)
        try:
            return self._reply(system, messages, look, on_text)
        except ApiError as e:
            if any(n in str(e) for n in self.NETWORK_ERRORS):
                raise ApiError("Couldn't reach ChatGPT — the internet connection seems to have dropped. "
                               'Check your Wi-Fi and try again.') from None
            raise

    def _reply(self, system, messages, look=None, on_text=None):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                self.start()
            self.bridge.update(system=system, look=look, shot=None)
            while not self.records.empty():
                self.records.get_nowait()
            self._command_response({'type': 'new_session'})
            prompt = {'type': 'prompt', 'message': self._transcript(messages)}
            images = messages[-1].get('images') if self.vision else None
            if images:
                prompt['images'] = [{'type': 'image', 'data': b, 'mimeType': 'image/jpeg'} for b in images]
            response = self._command_response(prompt)
            if not response.get('success'):
                raise ApiError(f'pi rejected the message: {response.get("error")}')
            deadline, final, texts = time.time() + self.preset.get('timeout', 120), None, []
            while True:
                record = self._next(deadline)
                if record.get('type') == 'message_update' and on_text:
                    update = record.get('assistantMessageEvent') or {}
                    if update.get('type') == 'text_delta' and update.get('delta'):
                        on_text(update['delta'])
                elif record.get('type') == 'message_end' and record['message'].get('role') == 'assistant':
                    final = record['message']
                    text = ''.join(b.get('text', '') for b in final.get('content', []) if b.get('type') == 'text')
                    if text.strip():
                        texts.append(text.strip())
                        if on_text:
                            on_text(' ')  # separates text said before and after a look_at_screen call
                elif record.get('type') == 'agent_settled':
                    break
            if not final:
                raise ApiError('pi returned no reply.')
            if final.get('stopReason') == 'error':
                raise ApiError(f'pi: {final.get("errorMessage") or "the model call failed"}')
            return ' '.join(texts), self.bridge['shot']

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
        self.process = None

    @classmethod
    def bridge_look(cls):
        """Called by the server when pi's look_at_screen tool runs."""
        if not cls.bridge['look']:
            return {'text': 'Looking at the screen is not available right now.'}
        shot = cls.bridge['look']()
        cls.bridge['shot'] = shot
        return {'text': shot.tool_text(), 'image': shot.image}


PROVIDERS = {'openai': OpenAICompatible, 'anthropic': Anthropic, 'llama_cpp': LlamaCpp, 'pi': PiAgent}


def create(preset):
    provider = preset.get('provider')
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown LLM provider "{provider}". Known: {", ".join(PROVIDERS)}')
    logging.info('LLM provider %s (%s)', provider, preset.get('model') or preset.get('model_path'))
    return PROVIDERS[provider](preset)
