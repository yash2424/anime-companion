# Anime companion

A Live2D anime girl who lives on your desktop. She talks with a reasoning model, speaks with a voice you choose, hears you through your microphone, and can see the window you're working in.

## Requirements

- Windows 10 or 11 (64-bit)
- [Python 3.12](https://www.python.org/downloads/) (the "py" launcher is installed with it)
- An internet connection for the one-time setup, and about 3 GB of free disk space for models and runtimes
- Optional: an API key (OpenAI, Gemini, Anthropic, OpenRouter) or the [pi](https://pi.dev) agent, for a smarter brain than the offline model

## Setup (once)

Open PowerShell in the project folder and run:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe download_assets.py
```

1. The first line creates the Python environment. It must be called `.venv` and sit in the project folder, because the launchers look for it there.
2. The second line installs the Python packages (speech recognition, offline voice and so on).
3. The third line downloads everything too large or third-party to ship: the Live2D characters, the offline chat model (Qwen3 1.7B with llama.cpp), the offline voice (Piper), the speech recognition model (Whisper) and the desktop shell (Electron). It can be run again safely and skips files it already has. You don't need `npm install`, because the script fetches Electron directly.

## Run

- **Start Companion.vbs** (double-click): starts everything and puts her on your desktop in a transparent, always-on-top window.
- **Open in Browser.vbs**: the same companion as a full web page instead.

The same from a terminal, which is handy when something goes wrong:

```powershell
.venv\Scripts\python.exe launch.py             # desktop overlay
.venv\Scripts\python.exe launch.py --browser   # web page
.venv\Scripts\python.exe server.py             # server only, then open http://127.0.0.1:8765
```

Everything runs locally on `127.0.0.1:8765`. To stop, use the tray icon → Quit, or Settings → "Close companion & release memory".

### Choosing her brain on first run

Out of the box she runs **fully offline**: the brain is **Qwen3 1.7B** (`local-qwen`) and the voice is **Piper** (`piper-lessac`), so no account or API key is needed. The offline brain is small: replies are simpler and it can't see your screen.

For a smarter companion, open **Chat history & settings** (hover over her → speech-bubble icon, or right-click the tray icon) and pick another brain, for example **Gemini** (free tier), with its key pasted under **API keys**, or a ChatGPT subscription through pi (see below). The **Edge** voices sound better than Piper and are free, but need internet.

### On the desktop

| Do this | To |
|---|---|
| Hover over her | Show the button bar (talk · type · look · chat & settings · hide) |
| Drag her | Move her anywhere |
| Click her | Poke her |
| Ctrl + mouse wheel over her | Make her bigger/smaller |
| **Ctrl+Alt+Space** | Talk: press, speak, press again to send |
| **Ctrl+Alt+T** | Type a message |
| **Ctrl+Alt+L** | "Look at my screen": she comments on the window you're using |
| **Ctrl+Alt+H** | Hide / show her |
| Tray icon (bottom-right, a little flower) | Show/hide, chat & settings, pick a character, always-on-top, reset position, quit |

Empty space around her is click-through, so she doesn't block the apps behind her. Quitting from the tray also stops the background server (change `desktop.stop_server_on_quit` to keep it running).

## Swapping parts (everything is in `config.json`)

Each swappable part has presets and an `active` value. You can pick a preset in **Settings**, or edit `active` in `config.json` and restart. To add a new option, copy a preset, rename it and edit it.

| Part | Presets included | Where the code lives |
|---|---|---|
| **Brain** (`llm`) | `pi-chatgpt-luna` (ChatGPT subscription via pi), `pi-chatgpt-sol`, `gpt-6-luna` / `gpt-6-sol` (OpenAI API key), `gemini` (Gemini API key, free tier), `claude-sonnet`, `openrouter` (any model), `ollama` (local), `local-qwen` (default, offline) | `companion/llm.py`, `companion/pi_bridge.ts` |
| **Voice** (`voice`) | `edge-ana` (free youthful US girl, needs internet), `edge-maisie` (UK girl), `elevenlabs` (your designed voice), `openai-tts`, `piper-lessac` (default, offline) | `companion/tts.py` |
| **Hearing** (`hearing`) | `local-whisper` (offline), `openai-transcribe` | `companion/stt.py` |
| **Character** (`avatar`) | `mao`, `koharu`, `tsumiki`, `hibiki`, `izumi`, `epsilon`, `kei`, `shizuku`, `zundamon`, `miara` | `web/models/avatars.json` |
| **Personality** | `personality.md` (`{name}` becomes the character's name) | — |

- Any OpenAI-compatible service (OpenAI, OpenRouter, Groq, Gemini, LM Studio, Ollama, llama.cpp) only needs a preset with `"provider": "openai"`, a `base_url`, a `model`, and `api_key_env`. Set `"vision": true` only if the model accepts images. Anything under `params` is passed straight to the API (e.g. `reasoning_effort`, `max_completion_tokens`, `temperature`).
- `gpt-6-luna` uses `reasoning_effort: "low"`. Set it to `"none"` for faster replies, or `"medium"` for smarter ones.
- **Compare characters:** Settings → "Compare all characters side by side", or tray → Pick a character. **Say hi** plays the current voice on each one, and **Choose** switches.
- **Add your own Live2D model:** put its folder (with the `.model3.json`) in `web/models/<id>/` and add an entry in `avatars.json` (name, model path, mouth parameter, framing, emotion → expression map).
- **ElevenLabs voice:** design a voice at https://elevenlabs.io/voice-design, save it, copy its Voice ID into the `elevenlabs` preset's `voice_id`, add `ELEVENLABS_API_KEY`, and pick "ElevenLabs" in Settings.

API keys live in `.env` (see `.env.example`), or you can paste them in Settings. They're never sent to the browser page, and `config.json` only stores the *names* of the keys.

## Using a subscription instead of an API key (pi)

The `pi-*` brains run the [pi coding agent](https://pi.dev) in the background (RPC mode) and use whatever login pi has. The included presets use pi's `openai-codex` login, i.e. a ChatGPT plan: install pi, run `pi` in PowerShell, type `/login`, then pick a `pi-*` brain in Settings. All of pi's own tools, skills and extensions are switched off for this. It only loads `companion/pi_bridge.ts`, which gives the model the companion's personality and the `look_at_screen` tool. To use another pi login, copy a `pi-*` preset and change `pi_provider` / `model` (see `pi --list-models`).

This is unofficial: OpenAI tolerates ChatGPT plans in third-party tools but hasn't promised to keep allowing it. If it stops working, switch to `gpt-6-luna` with an API key. **Don't** use pi's Google Gemini CLI / Antigravity logins for this: Google bans accounts that use those subscriptions in third-party tools. Use the `gemini` preset with an API key instead.

## Screen awareness ("Eyes" in Settings)

- **When relevant** (default): the model gets a `look_at_screen` tool and decides when to use it, e.g. when you say "what do you think of this?" or ask for help with something on screen. The **Look** button and Ctrl+Alt+L always make her look.
- **Always**: your current window is attached to every message (costs more tokens).
- **Off**: she never looks, and doesn't get the window title either.
- **Comment on her own** (off by default): every N seconds (only when idle, and only if the screen changed) she glances at your window. She says one line if something is worth commenting on and stays quiet otherwise.

She captures **the window you were using**, not the companion. A background tracker remembers the last foreground window that isn't hers. Screenshots are kept in memory only and never saved. With a cloud model they are sent to that provider. The chat log records which window she looked at, but never the image.

## Files

```
config.json            all switchable settings (presets)
.env                   your API keys (create via Settings or from .env.example)
personality.md         who she is
server.py              local HTTP server (127.0.0.1:8765 only) wiring it all together
companion/             llm.py · tts.py · stt.py · screen.py · config.py · net.py
web/                   index.html (full page) · overlay.html (desktop) · gallery.html (character picker) · core.js (shared)
web/models/            Live2D characters + avatars.json
desktop/               Electron shell: main.js (window, tray, hotkeys) · preload.js
verify.py              smoke test against the running server (cleans up after itself)
download_assets.py     re-downloads models, runtime and Electron from their original sources
```

## Troubleshooting

- Logs: `data/server.log` (server), `data/pi.log` (pi brain), `data/desktop.log` (overlay errors, hotkey conflicts), `data/launcher.log`, `data/llama.log` (offline model).
- "needs an API key": paste it in Settings → API keys.
- A hotkey doesn't work: another app owns it (see `data/desktop.log`); change it in `config.json` → `desktop.hotkeys`.
- Microphone blocked: Windows Settings → Privacy → Microphone → allow desktop apps.
- She's off-screen: tray → Reset position & size.
- Run `.venv\Scripts\python.exe verify.py` while she's running for a quick health check.

Characters are official Live2D sample models under the Live2D Free Material License (free for individuals and small businesses). See `web/credits.html`.
