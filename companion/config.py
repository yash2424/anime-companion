"""Settings live in config.json; secrets (API keys) live in .env next to it."""
import copy
import json
import os
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / 'config.json'
ENV_FILE = ROOT / '.env'
_lock = threading.Lock()
_env_from_file = set()


def load_env():
    """Read KEY=value lines from .env into os.environ (file values win over stale ones it set before)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key not in os.environ or key in _env_from_file:
            os.environ[key] = value
            _env_from_file.add(key)


def set_env_key(name, value):
    """Create or replace one KEY=value line in .env and apply it immediately."""
    lines = ENV_FILE.read_text(encoding='utf-8').splitlines() if ENV_FILE.exists() else []
    lines = [l for l in lines if not l.strip().startswith(name + '=')]
    if value:
        lines.append(f'{name}={value}')
        os.environ[name] = value
        _env_from_file.add(name)
    else:
        os.environ.pop(name, None)
    ENV_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def load():
    with _lock:
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))


def save(config):
    with _lock:
        tmp = CONFIG_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        tmp.replace(CONFIG_FILE)


def active_preset(config, section):
    """Return (name, preset dict) for the active preset of llm / voice / hearing."""
    block = config[section]
    name = block['active']
    if name not in block['presets']:
        raise KeyError(f'config.json: {section}.active is "{name}", but no preset has that name.')
    return name, copy.deepcopy(block['presets'][name])


def api_key(preset):
    env_name = preset.get('api_key_env')
    if not env_name:
        return None
    key = os.environ.get(env_name, '').strip()
    if not key:
        raise MissingKey(env_name)
    return key


class MissingKey(RuntimeError):
    def __init__(self, env_name):
        super().__init__(f'{env_name} is not set. Add it in Settings → API keys (or in the .env file).')
        self.env_name = env_name
