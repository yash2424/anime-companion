# Companion v2 — task checklist

Legend: [x] done · [~] in progress · [ ] to do · [USER] needs you

## 1. Customizable architecture (swap anything via `config.json`)
- [x] Config loader + `.env` for API keys (`companion/config.py`)
- [x] LLM providers: OpenAI-compatible (OpenAI / OpenRouter / Ollama / LM Studio / Gemini), Anthropic, local llama.cpp
- [x] Voice (TTS) providers: ElevenLabs, OpenAI TTS, Edge neural voices, local Piper
- [x] Hearing (STT) providers: local Faster-Whisper, OpenAI transcription
- [x] Avatar registry (`web/models/avatars.json`) — swap Live2D model by name
- [x] Switch presets at runtime from Settings (LLM / voice / hearing / avatar)
- [x] Paste API keys from Settings (written to `.env`, never sent to the browser)

## 2. New character model (replace Hiyori)
- [x] Find free Live2D models (official Live2D Free Material License samples)
- [x] Download 10 girl candidates: Mao, Koharu, Tsumiki, Hibiki, Izumi, Epsilon, Kei, Shizuku, Zundamon, Miara
- [x] Verify moc3 versions are supported by bundled Cubism Core
- [x] Gallery page to compare all candidates animated side by side, "choose" button
- [x] Per-model framing, mouth param for lip sync, emotion → expression mapping
- [x] Screenshot-verify each model renders
- [ ] [USER] Pick the model

## 3. Voice
- [x] Give the voice-design website link (ElevenLabs Voice Design) + a prompt to paste
- [x] Free ready-to-use youthful voice preset in the meantime (Edge `en-US-AnaNeural`)
- [ ] [USER] Design voice → paste Voice ID + ElevenLabs key

## 4. Better reasoning model
- [x] Research "ChatGPT Luna" → GPT-6 Luna, API id `gpt-6-luna`, image input supported
- [x] OpenAI preset `gpt-6-luna` as default (Sol / Claude / local Qwen as alternates)
- [ ] [USER] Paste OpenAI API key

## 5. Desktop app (no browser) + sees your current window
- [x] Electron 44 runtime installed in `desktop/` (binary downloaded; Node 20 can't run its installer)
- [x] Transparent, frameless, always-on-top overlay window with the character
- [x] Click-through on empty areas, drag to move, remembers position/size
- [x] Tray icon (show/hide, open chat window, quit)
- [x] Global hotkeys: talk, look at screen, type, show/hide
- [x] Foreground-window tracker (ignores the companion's own windows)
- [x] Window capture (PrintWindow, fallback screen grab) → sent to vision model
- [x] `look_at_screen` tool the model can call on its own + "always attach" and "off" modes
- [x] Optional proactive comments on what you're doing (off by default)
- [x] Launcher: double-click starts server + desktop overlay (browser mode still available)

## 6. Polish & verification
- [x] Fixed: stray Electron test processes (error popup) killed; test helper now hard-exits
- [x] Fixed: sample models played their own Japanese voice clips (Hibiki/Izumi/Kei) — motion sounds muted
- [x] Removed Hiyori entirely (model list, downloader, files); removed my test messages from chat history
- [x] `verify.py` smoke test: 10/10 passing; tool-calling loop tested against local llama.cpp
- [x] Fixed: multiple WebGL canvases broke Live2D — gallery uses one shared stage
- [x] Persona prompt for a cheerful little-girl character (name follows chosen model)
- [x] Emotion tags → expressions/motions
- [x] Longer conversation memory (configurable)
- [x] Update README (how to switch LLM/voice/model, hotkeys, privacy)
- [x] Smoke tests: server endpoints, each provider without keys fails gracefully, screen capture
- [x] Launch desktop overlay and screenshot-verify it

## Waiting on you
- [ ] [USER] Pick the character (tray → Pick a character, or http://127.0.0.1:8765/gallery.html)
- [ ] [USER] Design the voice at https://elevenlabs.io/voice-design → send me the Voice ID (or paste it in config.json)
- [x] ~~Paste OpenAI API key~~ → not needed: brain now uses your ChatGPT subscription via pi
- [ ] [USER] Try the microphone once (not testable from here)
- [ ] Optional: clear the old Hiyori-era chat (4 messages) in Settings so she doesn't call herself Hiyori

## 7. Subscription login via pi (added)
- [x] Researched Gemini subscription → NOT usable (Google bans third-party use of Gemini CLI/Antigravity logins); added `gemini` API-key preset instead
- [x] Found WSL has no internet (all connections time out) → pi in WSL could never reach ChatGPT
- [x] Installed pi 0.87.1 natively on Windows (official installer) + Node 22 (`%LOCALAPPDATA%\pi-node`), both on user PATH
- [x] Copied from WSL: settings, keybindings, models-store, login (auth.json), 5 agents, 5 skills, 8 extensions, 2 packages, 5 sessions
- [x] Reinstalled extension/package dependencies natively; ported visual-tools (Chrome/Edge paths, SVG render via Chrome); pdf-reader venv (PyMuPDF); yt-dlp.exe
- [x] Removed pi from WSL (~/.pi, pi-node, pi-wsl-runtime, puppeteer Chrome cache, .bashrc PATH line; backup .bashrc.bak-before-pi-removal)
- [x] `pi` brain provider (RPC, warm process) + `pi_bridge.ts` extension (system prompt + look_at_screen tool), token-protected
- [x] Verified: 10/10 smoke tests on pi brain, ~2.4 s replies, she looks at the screen on her own
- [x] API-key and local brains untouched and still selectable
