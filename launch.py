"""Silent Windows launcher; double-click "Start Companion.vbs".

Starts the server (if it isn't running) and then the desktop overlay, or the browser page when
config.json has "ui": {"mode": "browser"}. Pass --browser to force the browser page.
"""
from pathlib import Path
import ctypes
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'
ELECTRON = ROOT / 'desktop/node_modules/electron/dist/electron.exe'


def alive():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + '/api/status', timeout=2) as response:
            return json.load(response).get('app') == 'anime-companion'
    except Exception:
        return False


def fail(message):
    ctypes.windll.user32.MessageBoxW(0, message, 'Companion', 16)


def main():
    (ROOT / 'data').mkdir(exist_ok=True)
    log = (ROOT / 'data/launcher.log').open('ab')
    if not alive():
        subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT,
                         stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(40):
            if alive():
                break
            time.sleep(0.75)
        else:
            return fail('The companion could not start. Check data/launcher.log and data/server.log.')
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    mode = 'browser' if '--browser' in sys.argv else config.get('ui', {}).get('mode', 'desktop')
    if mode == 'desktop' and ELECTRON.exists():
        subprocess.Popen([str(ELECTRON), str(ROOT / 'desktop')], cwd=ROOT / 'desktop', stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        if mode == 'desktop':
            fail('The desktop app is not installed (desktop/node_modules/electron). Opening the browser version.')
        webbrowser.open(URL)


if __name__ == '__main__':
    main()
