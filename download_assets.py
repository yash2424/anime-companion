"""Download original upstream assets; run once with internet access.

This also installs the Electron desktop shell, so `npm install` is not needed.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent

def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)

def download(url, rel, sha=None):
    target = ROOT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        print('Already downloaded: ' + rel, flush=True)
        return
    print('Downloading: ' + rel, flush=True)
    temp = target.with_suffix(target.suffix + '.part')
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as response, temp.open('wb') as out:
        while block := response.read(1024 * 1024):
            out.write(block)
            digest.update(block)
    if sha and digest.hexdigest() != sha:
        raise ValueError('Checksum mismatch: ' + rel)
    temp.replace(target)
    print('Ready: ' + rel, flush=True)

# Official Live2D sample models (Free Material License): (zip, folder inside the zip, web/models/<id>)
LIVE2D_BASE = 'https://cubism.live2d.com/sample-data/bin/'
LIVE2D_MODELS = [
    ('mao_en.zip', 'runtime', 'mao'), ('koharu_haruto_ja.zip', 'koharu/runtime', 'koharu'),
    ('tsumiki_ja.zip', 'runtime', 'tsumiki'), ('hibiki_ja.zip', 'runtime', 'hibiki'),
    ('izumi_ja.zip', 'runtime', 'izumi'), ('epsilon_ja.zip', 'epsilon_pro/runtime', 'epsilon'),
    ('kei_en.zip', 'kei_basic_free/runtime', 'kei'), ('shizuku_ja.zip', 'runtime', 'shizuku'),
    ('zundamon_ja.zip', 'runtime', 'zundamon'), ('miara_en.zip', 'runtime', 'miara'),
]
ELECTRON = '44.4.5'


def extract_folder(zip_path, inner, target):
    """Copy one folder out of a zip (Live2D zips put the usable model in a 'runtime' folder)."""
    if target.exists() or not zip_path.exists():
        return
    prefix = inner.rstrip('/') + '/'
    with zipfile.ZipFile(zip_path) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            out = (target / entry.filename[len(prefix):]).resolve()
            if not out.is_relative_to(target.resolve()):
                raise ValueError('Unsafe archive path')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(entry))


def main():
    release = get_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11146')
    runtime = next(a for a in release['assets'] if 'bin-win-cpu-x64.zip' in a['name'])
    model = get_json('https://huggingface.co/api/models/Qwen/Qwen3-1.7B-GGUF/tree/main')
    weights = [a for a in model if a['path'].lower().endswith('.gguf')]
    weight = min(weights, key=lambda a: a['size'])
    jobs = [
        (runtime['browser_download_url'], 'downloads/llama.zip', runtime.get('digest', '').removeprefix('sha256:') or None),
        ('https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/' + weight['path'], 'models/chat.gguf', weight.get('lfs', {}).get('oid')),
        ('https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/browser/pixi.min.js', 'web/vendor/pixi.min.js', None),
        ('https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js', 'web/vendor/cubism4.min.js', None),
        ('https://raw.githubusercontent.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/build/libs/live2dcubismcore.min.js', 'web/vendor/live2dcubismcore.min.js', None),
        ('https://raw.githubusercontent.com/Open-LLM-VTuber/Open-LLM-VTuber/main/LICENSE-Live2D.md', 'licenses/Open-LLM-VTuber-Live2D.md', None),
        ('https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx', 'models/voice.onnx', None),
        ('https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json', 'models/voice.onnx.json', None),
        ('https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/lessac/medium/MODEL_CARD', 'licenses/voice-MODEL_CARD.txt', None),
        ('https://raw.githubusercontent.com/Live2D/CubismWebSamples/develop/NOTICE.md', 'licenses/Live2D-NOTICE.md', None),
        ('https://raw.githubusercontent.com/Live2D/CubismWebSamples/develop/LICENSE.md', 'licenses/Live2D-LICENSE.md', None),
        ('https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/LICENSE', 'licenses/pixi-live2d-LICENSE.txt', None),
        ('https://raw.githubusercontent.com/pixijs/pixijs/v6.5.10/LICENSE', 'licenses/pixi-LICENSE.txt', None),
        ('https://raw.githubusercontent.com/ggml-org/llama.cpp/b11146/LICENSE', 'licenses/llama-LICENSE.txt', None),
        ('https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/raw/main/LICENSE', 'licenses/Qwen-LICENSE.txt', None),
    ]
    for zip_name, _, _ in LIVE2D_MODELS:
        folder = zip_name.rsplit('_', 1)[0]
        jobs.append((f'{LIVE2D_BASE}{folder}/{zip_name}', 'downloads/live2d/' + zip_name, None))
    # Electron's npm installer needs Node 22+, so the binary is fetched directly.
    jobs.append((f'https://github.com/electron/electron/releases/download/v{ELECTRON}/electron-v{ELECTRON}-win32-x64.zip',
                 'downloads/electron.zip', '11c395820a5aaa8ebcc0686b476d0ac98a730274ebfbdc8cf5538a7c2815cb5d'))
    speech_files = get_json('https://huggingface.co/api/models/Systran/faster-whisper-base.en/tree/main')
    for entry in speech_files:
        if entry['path'] in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json', 'vocabulary.txt'):
            jobs.append(('https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/' + entry['path'],
                         'models/whisper/' + entry['path'], entry.get('lfs', {}).get('oid')))
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, *job) for job in jobs]
        for job, f in zip(jobs, futures):
            try:
                f.result()
            except Exception as exc:
                errors.append((job[1], str(exc)))
    if (ROOT / 'downloads/llama.zip').exists():
        dest = (ROOT / 'runtime').resolve()
        with zipfile.ZipFile(ROOT / 'downloads/llama.zip') as archive:
            for entry in archive.infolist():
                if not (dest / entry.filename).resolve().is_relative_to(dest):
                    raise ValueError('Unsafe archive path')
            archive.extractall(dest)
    for zip_name, source, target in LIVE2D_MODELS:
        extract_folder(ROOT / 'downloads/live2d' / zip_name, source, ROOT / 'web/models' / target)
    if (ROOT / 'downloads/electron.zip').exists() and not (ROOT / 'desktop/node_modules/electron/dist/electron.exe').exists():
        with zipfile.ZipFile(ROOT / 'downloads/electron.zip') as archive:
            archive.extractall(ROOT / 'desktop/node_modules/electron/dist')
        (ROOT / 'desktop/node_modules/electron/path.txt').write_text('electron.exe')
    (ROOT / 'downloads/sources.json').write_text(json.dumps(jobs, indent=2), encoding='utf-8')
    if errors:
        print(json.dumps(errors, indent=2))
        raise SystemExit(1)
    print('All assets downloaded.', flush=True)

if __name__ == '__main__':
    main()
