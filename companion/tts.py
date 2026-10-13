"""Voice (text-to-speech) providers. Each returns (audio_bytes, mime_type).

Add a new one by writing a class with synthesize(text, speed) and registering it in PROVIDERS.
"""
import asyncio
import io
import logging
import queue
import threading
import wave

from . import config as cfg
from .config import ROOT
from .net import request


class Voice:
    def __init__(self, preset):
        self.preset = preset

    def start(self):
        pass

    def stream(self, text, speed=1.0):
        """(mime_type, iterator of audio chunks). Voices that can, send audio while the rest is still being made."""
        audio, mime = self.synthesize(text, speed)
        return mime, iter([audio])


class Piper(Voice):
    """Local, offline. Any voice from https://huggingface.co/rhasspy/piper-voices works."""
    lock = threading.Lock()

    def start(self):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(ROOT / self.preset['model_path']))

    def synthesize(self, text, speed=1.0):
        from piper import SynthesisConfig
        out = io.BytesIO()
        conf = SynthesisConfig(length_scale=self.preset.get('length_scale', 1.0) / speed,
                               speaker_id=self.preset.get('speaker_id'))
        with self.lock, wave.open(out, 'wb') as wav:
            self.voice.synthesize_wav(text, wav, syn_config=conf)
        return out.getvalue(), 'audio/wav'


class Edge(Voice):
    """Microsoft Edge online neural voices (free, no key, needs internet; unofficial endpoint)."""

    def start(self):
        import edge_tts  # noqa: F401  (fail early if the package is missing)

    def synthesize(self, text, speed=1.0):
        _, chunks = self.stream(text, speed)
        return b''.join(chunks), 'audio/mpeg'

    def stream(self, text, speed=1.0):
        import edge_tts
        rate = self.preset.get('rate_percent', 0) + round((speed - 1) * 100)
        communicate = edge_tts.Communicate(text, self.preset['voice'], rate=f'{rate:+d}%',
                                           pitch=self.preset.get('pitch', '+0Hz'))
        chunks = queue.Queue()

        async def pump():
            async for chunk in communicate.stream():
                if chunk['type'] == 'audio':
                    chunks.put(chunk['data'])

        def run():
            try:
                asyncio.run(pump())
                chunks.put(None)
            except Exception as e:
                chunks.put(e)

        def receive():
            while (item := chunks.get(timeout=60)) is not None:
                if isinstance(item, Exception):
                    raise item
                yield item
        threading.Thread(target=run, daemon=True, name='edge-tts').start()
        return 'audio/mpeg', receive()


class ElevenLabs(Voice):
    """Use a voice made with ElevenLabs Voice Design: paste its Voice ID into the preset."""

    def start(self):
        cfg.api_key(self.preset)
        if not self.preset.get('voice_id') or 'PASTE' in self.preset['voice_id']:
            raise RuntimeError('Set voice_id in the ElevenLabs preset (config.json) to your designed voice.')

    def synthesize(self, text, speed=1.0):
        settings = dict(self.preset.get('voice_settings', {}))
        settings['speed'] = max(0.7, min(1.2, settings.get('speed', 1.0) * speed))
        fmt = self.preset.get('output_format', 'mp3_44100_128')
        data, _ = request(
            f'https://api.elevenlabs.io/v1/text-to-speech/{self.preset["voice_id"]}?output_format={fmt}',
            {'text': text, 'model_id': self.preset.get('model', 'eleven_flash_v2_5'), 'voice_settings': settings},
            {'xi-api-key': cfg.api_key(self.preset), 'Accept': 'audio/mpeg'}, timeout=60)
        return data, 'audio/mpeg'


class OpenAITTS(Voice):
    """OpenAI speech; `instructions` steers tone, age and style of the voice."""

    def start(self):
        cfg.api_key(self.preset)

    def synthesize(self, text, speed=1.0):
        body = {'model': self.preset.get('model', 'gpt-4o-mini-tts'), 'voice': self.preset.get('voice', 'coral'),
                'input': text, 'response_format': 'mp3', 'speed': self.preset.get('speed', 1.0) * speed}
        if self.preset.get('instructions'):
            body['instructions'] = self.preset['instructions']
        base = self.preset.get('base_url', 'https://api.openai.com/v1').rstrip('/')
        data, _ = request(base + '/audio/speech', body,
                          {'Authorization': f'Bearer {cfg.api_key(self.preset)}'}, timeout=60)
        return data, 'audio/mpeg'


PROVIDERS = {'piper': Piper, 'edge': Edge, 'elevenlabs': ElevenLabs, 'openai': OpenAITTS}


def create(preset):
    provider = preset.get('provider')
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown voice provider "{provider}". Known: {", ".join(PROVIDERS)}')
    logging.info('Voice provider %s', provider)
    return PROVIDERS[provider](preset)
