"""Hearing (speech-to-text) providers. Each transcribe(audio_bytes, mime) returns text."""
import io
import logging
import threading

from . import config as cfg
from .config import ROOT
from .net import request_json, multipart


class FasterWhisper:
    """Local, offline Whisper on the CPU."""
    lock = threading.Lock()

    def __init__(self, preset):
        self.preset = preset

    def start(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(ROOT / self.preset['model_path']), device=self.preset.get('device', 'cpu'),
                                  compute_type=self.preset.get('compute_type', 'int8'),
                                  cpu_threads=self.preset.get('threads', 4), local_files_only=True)

    def transcribe(self, raw, mime):
        from faster_whisper.audio import decode_audio
        audio = decode_audio(io.BytesIO(raw), sampling_rate=16000)
        if len(audio) > 16000 * 65:
            raise ValueError('Please keep recordings under a minute.')
        with self.lock:
            segments, _ = self.model.transcribe(audio, beam_size=1, language=self.preset.get('language'),
                                                vad_filter=True, condition_on_previous_text=False)
            return ' '.join(s.text.strip() for s in segments).strip()


class OpenAITranscribe:
    def __init__(self, preset):
        self.preset = preset

    def start(self):
        cfg.api_key(self.preset)

    def transcribe(self, raw, mime):
        ext = 'webm' if 'webm' in mime else 'ogg' if 'ogg' in mime else 'wav' if 'wav' in mime else 'mp4'
        fields = {'model': self.preset.get('model', 'gpt-4o-mini-transcribe')}
        if self.preset.get('language'):
            fields['language'] = self.preset['language']
        body, ctype = multipart(fields, {'file': (f'speech.{ext}', raw, mime or 'application/octet-stream')})
        base = self.preset.get('base_url', 'https://api.openai.com/v1').rstrip('/')
        result = request_json(base + '/audio/transcriptions', body,
                              {'Authorization': f'Bearer {cfg.api_key(self.preset)}', 'Content-Type': ctype}, timeout=60)
        return result.get('text', '').strip()


PROVIDERS = {'faster_whisper': FasterWhisper, 'openai': OpenAITranscribe}


def create(preset):
    provider = preset.get('provider')
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown hearing provider "{provider}". Known: {", ".join(PROVIDERS)}')
    logging.info('Hearing provider %s', provider)
    return PROVIDERS[provider](preset)
