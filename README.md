# Anime companion

A Live2D anime girl who lives on your desktop. She talks with a reasoning model, speaks with a voice you choose, hears you through your microphone, and can see the window you're working in.

## Start

- **Start Companion.vbs**: starts everything and puts her on your desktop (a transparent, always-on-top window).
- **Open in Browser.vbs**: the same companion as a full web page instead.

Her brain defaults to **your ChatGPT subscription through pi** (no API key needed). pi is installed natively on Windows and already logged in. If that login ever expires, run `pi` in PowerShell and type `/login`. To use an API key instead, pick another brain in **Chat history & settings** (hover over her → speech-bubble icon, or right-click the tray icon) and paste the key under **API keys**.

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
| **Brain** (`llm`) | `pi-chatgpt-luna` (default, ChatGPT subscription via pi), `pi-chatgpt-sol`, `gpt-6-luna` / `gpt-6-sol` (OpenAI API key), `gemini` (Gemini API key, free tier), `claude-sonnet`, `openrouter` (any model), `ollama` (local), `local-qwen` (offline) | `companion/llm.py`, `companion/pi_bridge.ts` |
| **Voice** (`voice`) | `edge-ana` (default, free youthful US girl), `edge-maisie` (UK girl), `elevenlabs` (your designed voice), `openai-tts`, `piper-lessac` (offline, old voice) | `companion/tts.py` |
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

The `pi-*` brains run the [pi coding agent](https://pi.dev) in the background (RPC mode) and use whatever login pi has. Here that's `openai-codex`, i.e. your ChatGPT plan. All of pi's own tools, skills and extensions are switched off for this. It only loads `companion/pi_bridge.ts`, which gives the model the companion's personality and the `look_at_screen` tool. To use another pi login, copy a `pi-*` preset and change `pi_provider` / `model` (see `pi --list-models`).

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
