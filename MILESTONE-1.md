# Milestone 1 — local Live2D companion

Delivered on 2026-09-28.

## Working

- Hiyori's original Live2D model renders with idle movement and interaction.
- Qwen3 1.7B produces real local replies. The first browser test completed in about 5.9 seconds.
- Piper generates speech locally; browser playback and amplitude-driven mouth movement were visually verified.
- Faster Whisper transcribes locally. A generated 3.45-second audio sample was correctly transcribed in about 1.14 seconds; speech generation took 0.18 seconds in that test.
- Chat is stored in a local SQLite database and loaded by the app.
- The silent VBS launcher was exercised successfully against the running app.
- The user confirmed text chat works.
- Browser reported no warning/error logs during the initial avatar check.

## Remaining hands-on check

The physical microphone has not been tested by the user. The recording button and local transcription endpoint are implemented, and the speech-to-text endpoint passed a synthetic-audio integration test. This does not establish microphone permissions, microphone quality, or real speech accuracy on this device.

## Use

Open `Start Hiyori.vbs`, or visit http://127.0.0.1:8765 while the services are running. In Settings, choose “Close companion & release memory” when finished. Browser closure alone keeps the engine running.

## Deliberately deferred

Transparent desktop overlay, custom anime voice, long-term memory, more expressive emotion control, and app automation. This milestone runs as a local browser app with an existing third-party character.

See `data/verification.json` for the audio test results and `README.md` for setup and source details.
