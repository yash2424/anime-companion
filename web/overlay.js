'use strict';
// Desktop overlay: the character floats on your desktop in a transparent, always-on-top window.
// Runs inside Electron (desktop/main.js), which exposes `window.desktop` through preload.js.
(() => {
  const { getJSON, chat, Avatar, Speaker, Mic, proactiveLoop, channel } = Companion;
  const $ = id => document.getElementById(id);
  const desktop = window.desktop || { setIgnoreMouse() {}, dragStart() {}, dragEnd() {}, resizeBy() {}, openPanel() { open('/?panel=1'); }, hide() {}, quit() {}, onHotkey() {}, focus() {} };
  let config, avatar, busy = false, hideTimer, statusTimer;

  const voiceOn = () => { try { return localStorage.getItem('companion-voice') !== 'off'; } catch { return true; } };
  const name = () => config?.character.name || 'Companion';
  const broadcast = msg => channel?.postMessage({ ...msg, from: 'overlay' });

  function status(text, { error = false, ms = 0 } = {}) {
    clearTimeout(statusTimer);
    $('status').textContent = text; $('status').hidden = !text; $('status').classList.toggle('error', error);
    if (ms) statusTimer = setTimeout(() => { $('status').hidden = true; }, ms);
  }
  function bubble(text, note = '') {
    clearTimeout(hideTimer);
    $('bubbleText').textContent = text; $('bubbleNote').textContent = note;
    $('bubble').hidden = false; $('bubble').scrollTop = 0;
  }
  function hideBubbleLater(ms = 9000) { clearTimeout(hideTimer); hideTimer = setTimeout(() => { $('bubble').hidden = true; }, ms); }
  $('bubble').onclick = () => { $('bubble').hidden = true; };

  const speaker = new Speaker({ onEnd: () => hideBubbleLater() });
  const mic = new Mic({ onState: s => {
    $('talk').classList.toggle('on', s === 'recording');
    if (s === 'recording') status('Listening… press again to send');
    else if (s === 'transcribing') status('Hmm, let me hear that again…');
    else if (!busy) status('');
  } });

  async function present(result) {
    bubble(result.text, result.looked ? `◎ looked at ${result.looked}` : '');
    avatar?.emotion(result.emotion);
    if (voiceOn()) {
      try { await speaker.speak(result.text); } catch (e) { status(e.message, { error: true, ms: 6000 }); hideBubbleLater(15000); }
    } else hideBubbleLater(Math.max(6000, result.text.length * 70));
  }

  async function send(text, look = false) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; speaker.stop(); setButtons();
    status(look ? 'Taking a peek at your screen…' : `${name()} is thinking…`);
    avatar?.emotion('thinking');
    try {
      const result = await chat({ text, look }, {
        onEmotion: emotion => avatar?.emotion(emotion),
        onText: reply => { status(''); bubble(reply); },
        speaker: voiceOn() ? speaker : null,
      });
      broadcast({ type: 'message', role: 'user', text });
      broadcast({ type: 'message', role: 'assistant', text: result.text, looked: result.looked });
      bubble(result.text, result.looked ? `◎ looked at ${result.looked}` : '');
      busy = false; setButtons();
      if (result.speech) {
        try { await result.speech; } catch (e) { status(e.message, { error: true, ms: 6000 }); hideBubbleLater(15000); }
      } else hideBubbleLater(Math.max(6000, result.text.length * 70));
    } catch (e) {
      status(e.message, { error: true, ms: 8000 });
    } finally { busy = false; setButtons(); }
  }

  async function talk() {
    try {
      if (!mic.recording) { if (busy) return; speaker.stop(); await speaker.prepare(); await mic.start(); return; }
      const text = await mic.finish();
      if (text) await send(text); else status('I didn’t catch that…', { ms: 3000 });
    } catch (e) { mic.cancel(); status(e.name ? mic.micError(e) : e.message, { error: true, ms: 7000 }); }
  }
  const look = () => send('Take a look at what I’m doing!', true);
  function compose(show = true) {
    $('composer').hidden = !show; document.body.classList.toggle('composing', show);
    if (show) { desktop.focus(); setTimeout(() => $('input').focus(), 50); }
  }
  function setButtons() { for (const id of ['type', 'look']) $(id).disabled = busy; }

  $('talk').onclick = talk;
  $('look').onclick = look;
  $('type').onclick = () => compose($('composer').hidden);
  $('panel').onclick = () => desktop.openPanel();
  $('hide').onclick = () => desktop.hide();
  $('composer').onsubmit = e => { e.preventDefault(); const t = $('input').value; $('input').value = ''; compose(false); send(t); };
  $('input').onkeydown = e => { if (e.key === 'Escape') compose(false); };
  desktop.onHotkey(action => ({ talk, look, type: () => compose(true) })[action]?.());

  // ---------- click-through, hover, drag, resize ----------
  let ignoring = null, dragging = null;
  const setIgnore = v => { if (v !== ignoring) { ignoring = v; desktop.setIgnoreMouse(v); } };
  function overModel(x, y) {
    const b = avatar?.bounds();
    if (!b) return false;
    // The bounds include empty canvas around the art; shrink them a bit.
    const padX = b.width * 0.18, padTop = b.height * 0.04;
    return x > b.x + padX && x < b.x + b.width - padX && y > b.y + padTop && y < b.y + b.height;
  }
  addEventListener('mousemove', e => {
    if (dragging) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const onUi = !!el?.closest('#toolbar,#composer,#bubble');
    const stageRect = $('stage').getBoundingClientRect();
    const onModel = overModel(e.clientX - stageRect.left, e.clientY - stageRect.top);
    setIgnore(!(onUi || onModel));
    document.body.classList.toggle('hover', onUi || onModel);
  });
  document.addEventListener('mouseleave', () => { if (!dragging) { setIgnore(true); document.body.classList.remove('hover'); } });
  $('stage').addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    dragging = { x: e.screenX, y: e.screenY, moved: false };
    desktop.dragStart();
  });
  addEventListener('mousemove', e => {
    if (dragging && Math.hypot(e.screenX - dragging.x, e.screenY - dragging.y) > 4) dragging.moved = true;
  });
  addEventListener('mouseup', () => {
    if (!dragging) return;
    desktop.dragEnd();
    if (!dragging.moved) avatar?.react();
    dragging = null;
  });
  addEventListener('wheel', e => { if (e.ctrlKey) desktop.resizeBy(e.deltaY < 0 ? 1.08 : 1 / 1.08); }, { passive: true });

  // ---------- avatar & config ----------
  async function loadConfig() {
    const previous = config?.avatar;
    config = await getJSON('/api/config');
    document.title = `${name()} · anime companion`;
    if (previous === config.avatar && avatar?.model) return;
    const def = config.avatars[config.avatar];
    avatar ||= new Avatar($('stage'), { fps: 30 });
    avatar.mouthLevel = () => speaker.level();
    // On the desktop she's shown full-body unless the avatar defines its own overlay framing.
    await avatar.load({ ...def, zoom: def.overlay_zoom ?? 1, y: def.overlay_y ?? 0 });
    // autoInteract makes her eyes follow the mouse over the whole screen area of this window.
  }

  channel?.addEventListener('message', async ({ data }) => {
    if (data.from === 'overlay') return;
    if (data.type === 'config') loadConfig().catch(e => status(e.message, { error: true, ms: 6000 }));
    if (data.type === 'reply') present(data);
    if (data.type === 'speak') present({ text: data.text, emotion: 'neutral' });
    if (data.type === 'quit') desktop.quit();
  });

  async function waitForServer() {
    for (;;) {
      try { return await getJSON('/api/status'); } catch { await new Promise(r => setTimeout(r, 1000)); }
    }
  }

  async function init() {
    setIgnore(true);
    const s = await waitForServer();
    try { await loadConfig(); } catch (e) { status(`Couldn’t load the character: ${e.message}`, { error: true }); return; }
    if (s.llm.state === 'needs_key') {
      bubble(`Hi! I'm ${name()}! I need an API key before I can think. Click the speech icon below me → Settings → API keys.`);
    } else {
      bubble(`Hi hi! ${name()} is here! Hover over me for buttons, or press Ctrl+Alt+Space to talk.`);
    }
    hideBubbleLater(12000);
    proactiveLoop(() => config, () => !busy && !mic.recording && !speaker.playing, result => {
      broadcast({ type: 'message', role: 'assistant', text: result.text, looked: result.looked });
      present(result);
    });
  }
  init();
})();
