'use strict';
// Full chat page. In a normal browser it shows the avatar and does everything itself.
// With ?panel=1 (opened from the desktop companion) it is a chat log + settings panel, and the
// desktop overlay does the talking and animating.
(() => {
  const { api, getJSON, postJSON, chat, Avatar, Speaker, Mic, proactiveLoop, channel } = Companion;
  const $ = id => document.getElementById(id);
  const panel = new URLSearchParams(location.search).has('panel');
  let config, status = {}, avatar, busy = false;
  const LABELS = { llm: 'Reasoning model', voice: 'Voice', hearing: 'Hearing' };
  const STATE_TEXT = { ready: 'ready', loading: 'loading…', needs_key: 'needs an API key', error: 'error' };

  const voiceEnabled = $('voiceEnabled');
  try { voiceEnabled.checked = localStorage.getItem('companion-voice') !== 'off'; } catch {}
  voiceEnabled.onchange = () => {
    try { localStorage.setItem('companion-voice', voiceEnabled.checked ? 'on' : 'off'); } catch {}
    if (!voiceEnabled.checked) speaker.stop();
  };

  const error = m => { $('error').textContent = m; $('error').hidden = !m; };
  const activity = m => { $('activity').textContent = m; };
  const name = () => config?.character.name || 'Companion';
  const setState = m => { $('characterState').textContent = m; };
  const idleState = () => setState(status.llm?.state === 'ready' ? 'Here for a little chat' : 'Getting comfortable…');

  const speaker = new Speaker({
    onStart: () => { $('stopVoice').hidden = false; setState('Telling you a little something'); },
    onEnd: () => { $('stopVoice').hidden = true; if (!busy) idleState(); },
  });
  const mic = new Mic({ onState: s => {
    $('mic').classList.toggle('recording', s === 'recording');
    $('micLabel').textContent = s === 'recording' ? 'Listening · click to send' : 'Talk';
    if (s === 'recording') { activity('Recording · up to 45 seconds'); setState('You have my attention'); }
    else if (s === 'transcribing') activity('Listening back…');
    else activity('');
    updateControls();
  } });

  function updateControls() {
    const chatReady = status.llm?.state === 'ready';
    $('send').disabled = busy || mic.recording || !chatReady;
    $('look').disabled = busy || mic.recording || !chatReady;
    $('mic').disabled = busy || !chatReady || status.hearing?.state !== 'ready';
    $('clearChat').disabled = busy || mic.recording;
    document.querySelectorAll('[data-prompt]').forEach(b => b.disabled = busy || mic.recording || !chatReady);
  }

  function appendMessage(role, text, looked) {
    $('welcome')?.remove();
    const item = document.createElement('div'); item.className = `message ${role}`;
    const speakerName = document.createElement('span'); speakerName.className = 'speaker';
    speakerName.textContent = role === 'user' ? 'YOU' : name().toUpperCase();
    const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = text;
    item.append(speakerName, bubble);
    if (looked) {
      const note = document.createElement('span'); note.className = 'looked'; note.textContent = `◎ looked at ${looked}`;
      item.appendChild(note);
    }
    if (role === 'assistant') {
      const replay = document.createElement('button'); replay.className = 'replay'; replay.textContent = '↻ Hear again';
      replay.onclick = () => {
        const said = bubble.textContent;
        panel ? channel?.postMessage({ type: 'speak', text: said }) : speaker.speak(said).catch(e => error(e.message));
      };
      item.appendChild(replay);
    }
    $('chat').appendChild(item); $('chat').scrollTop = $('chat').scrollHeight;
    return item;
  }

  // `streamed`: the face and voice already followed the reply while it was being written.
  function showReply(result, streamed = false) {
    appendMessage('assistant', result.text, result.looked);
    if (panel) { const { speech, ...reply } = result; channel?.postMessage({ type: 'reply', ...reply }); return; }
    if (streamed) return;
    avatar?.emotion(result.emotion);
    if (voiceEnabled.checked) speaker.speak(result.text).catch(e => error(e.message));
  }

  async function sendMessage(text, look = false) {
    text = text.trim(); if (!text || busy || mic.recording) return;
    speaker.stop(); error(''); busy = true; updateControls();
    if (voiceEnabled.checked && !panel) speaker.prepare().catch(() => {});
    const item = appendMessage('user', text); $('message').value = '';
    activity(look ? `${name()} is taking a look…` : `${name()} is thinking…`); setState('A thought is taking shape');
    avatar?.emotion('thinking');
    let reply = null;
    try {
      const result = await chat({ text, look }, {
        onEmotion: emotion => { if (!panel) avatar?.emotion(emotion); },
        onText: t => {
          if (!reply) { activity(''); reply = appendMessage('assistant', ''); }
          reply.querySelector('.bubble').textContent = t; $('chat').scrollTop = $('chat').scrollHeight;
        },
        speaker: voiceEnabled.checked && !panel ? speaker : null,
      });
      if (panel) channel?.postMessage({ type: 'message', role: 'user', text, from: 'panel' });
      activity(''); reply?.remove(); showReply(result, !panel);
      result.speech?.catch(e => error(e.message));
    } catch (e) {
      error(e.message); activity(''); reply?.remove();
      if (!item.nextElementSibling) { $('message').value = text; item.remove(); }
    }
    finally { busy = false; updateControls(); if (!speaker.playing) idleState(); }
  }

  $('chatForm').onsubmit = e => { e.preventDefault(); sendMessage($('message').value); };
  $('message').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage($('message').value); } };
  document.querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => sendMessage(b.dataset.prompt, !!b.dataset.look));
  $('look').onclick = () => sendMessage($('message').value.trim() || 'Take a look at what I’m doing!', true);
  $('stopVoice').onclick = () => speaker.stop();
  $('mic').onclick = async () => {
    try {
      if (!mic.recording) { if (busy) return; error(''); speaker.stop(); await speaker.prepare(); await mic.start(); return; }
      busy = true; updateControls();
      const text = await mic.finish();
      busy = false;
      if (text) await sendMessage(text); else error('I didn’t catch that. Try a little closer to the mic.');
    } catch (e) { busy = false; mic.cancel(); error(e.name ? mic.micError(e) : e.message); }
    finally { updateControls(); }
  };

  // ---------- status ----------
  async function refreshStatus() {
    try {
      status = await getJSON('/api/status');
      const parts = ['llm', 'voice', 'hearing'];
      const ready = parts.every(k => status[k].state === 'ready');
      const needsKey = parts.find(k => status[k].state === 'needs_key');
      const failed = parts.find(k => status[k].state === 'error');
      $('systemStatus').textContent = ready ? 'All set' : needsKey ? `${LABELS[needsKey]} needs an API key (Settings)`
        : failed ? `${LABELS[failed]} has a problem (Settings)` : 'Loading…';
      $('componentStatus').innerHTML = '';
      for (const k of parts) {
        const row = document.createElement('div');
        row.textContent = `${LABELS[k]}: ${STATE_TEXT[status[k].state] || status[k].state}` + (status[k].detail && status[k].state !== 'ready' ? ` — ${status[k].detail}` : '');
        $('componentStatus').appendChild(row);
      }
      $('windowNote').textContent = status.window && config?.screen.mode !== 'off' ? `Seeing: ${status.window}` : 'Your own little corner';
      if (!busy && !mic.recording && !speaker.playing) idleState();
      updateControls();
    } catch { $('systemStatus').textContent = 'Companion is offline'; status = {}; updateControls(); }
  }

  // ---------- settings ----------
  function fillSelect(select, items, active) {
    select.innerHTML = '';
    for (const [value, label] of items) select.add(new Option(label, value, false, value === active));
  }
  function renderConfig() {
    document.title = `${name()} · anime companion`;
    $('brandName').textContent = name().toLowerCase();
    document.querySelectorAll('.char-name').forEach(e => e.textContent = name());
    const def = config.avatars[config.avatar];
    $('modelCredit').textContent = def?.credit || '';
    const llm = config.sections.llm.presets.find(p => p.name === config.sections.llm.active);
    $('brainBadge').textContent = llm ? llm.label.split('(')[0].trim() : '';
    $('privacyNote').textContent = config.screen.mode === 'off' ? 'Chat history stays on this computer. Screen awareness is off.'
      : 'Chat history stays on this computer. She can see the window you’re using (Settings → Eyes).';
    fillSelect($('avatarSelect'), Object.entries(config.avatars).map(([k, v]) => [k, v.name]), config.avatar);
    for (const s of ['llm', 'voice', 'hearing'])
      fillSelect($(s + 'Select'), config.sections[s].presets.map(p => [p.name, p.label]), config.sections[s].active);
    $('charName').value = config.character.name === def?.name ? '' : config.character.name;
    $('voiceSpeed').value = config.voice_speed;
    $('screenMode').value = config.screen.mode;
    $('proactive').checked = config.screen.proactive;
    $('proactiveInterval').value = config.screen.proactive_interval_seconds;
    const keys = $('keys'); keys.innerHTML = '';
    for (const [env, set] of Object.entries(config.keys)) {
      const users = ['llm', 'voice', 'hearing'].flatMap(s => config.sections[s].presets.filter(p => p.key === env).map(p => p.label.split('·')[0].trim()));
      const row = document.createElement('form'); row.className = 'key-row';
      row.innerHTML = `<label><span class="key-name"></span> <span class="key-state ${set ? 'set' : ''}">${set ? '✓ saved' : 'not set'}</span><small></small></label>
        <div><input type="password" autocomplete="off" spellcheck="false"><button class="secondary-button">Save</button></div>`;
      row.querySelector('.key-name').textContent = env;
      row.querySelector('small').textContent = 'Used by: ' + [...new Set(users)].join(', ');
      row.querySelector('input').placeholder = set ? 'Paste a new key to replace' : 'Paste key';
      row.onsubmit = async e => {
        e.preventDefault();
        try { config = await postJSON('/api/keys', { name: env, value: row.querySelector('input').value }); renderConfig(); refreshStatus(); }
        catch (err) { error(err.message); }
      };
      keys.appendChild(row);
    }
  }
  async function saveConfig(change) {
    try {
      const previousAvatar = config.avatar;
      config = await postJSON('/api/config', change);
      renderConfig(); refreshStatus();
      if (config.avatar !== previousAvatar) loadAvatar();
      channel?.postMessage({ type: 'config' });
    } catch (e) { error(e.message); }
  }
  $('avatarSelect').onchange = e => saveConfig({ avatar: e.target.value });
  $('charName').onchange = e => saveConfig({ character_name: e.target.value });
  for (const s of ['llm', 'voice', 'hearing']) $(s + 'Select').onchange = e => saveConfig({ [s]: e.target.value });
  $('voiceSpeed').onchange = e => saveConfig({ voice_speed: +e.target.value });
  $('screenMode').onchange = e => saveConfig({ screen: { mode: e.target.value } });
  $('proactive').onchange = e => saveConfig({ screen: { proactive: e.target.checked } });
  $('proactiveInterval').onchange = e => saveConfig({ screen: { proactive_interval_seconds: +e.target.value } });
  $('settingsButton').onclick = () => $('settings').showModal();
  $('closeSettings').onclick = () => $('settings').close();
  $('clearChat').onclick = async () => {
    if (!confirm('Clear the saved conversation on this computer?')) return;
    try { speaker.stop(); await api('/api/clear', {}); location.reload(); } catch (e) { error(e.message); }
  };
  $('shutdown').onclick = async () => {
    if (busy || mic.recording) { error('Finish the current message or recording first.'); $('settings').close(); return; }
    speaker.stop(); channel?.postMessage({ type: 'quit' });
    await api('/api/shutdown', {}).catch(() => {});
    $('settings').close(); $('systemStatus').textContent = 'Companion is closed'; setState('See you next time');
    activity('Run “Start Companion” to come back.');
  };

  async function loadAvatar() {
    if (panel) return;
    const def = config.avatars[config.avatar];
    try {
      avatar ||= new Avatar($('avatar'), { onTap: () => {} });
      avatar.mouthLevel = () => speaker.level();
      await avatar.load(def);
      $('avatarError').hidden = true;
    } catch (e) { $('avatarError').textContent = `Couldn’t load ${def?.name}: ${e.message}`; $('avatarError').hidden = false; }
  }

  channel?.addEventListener('message', async ({ data }) => {
    if (data.type === 'config') { const prev = config.avatar; config = await getJSON('/api/config'); renderConfig(); if (prev !== config.avatar) loadAvatar(); }
    if (data.type === 'message' && panel && data.from !== 'panel') appendMessage(data.role, data.text, data.looked);
  });

  async function init() {
    if (panel) document.body.classList.add('panel');
    updateControls();
    try { config = await getJSON('/api/config'); renderConfig(); loadAvatar(); } catch (e) { error(e.message); }
    try { const { messages } = await getJSON('/api/history'); for (const m of messages) appendMessage(m.role, m.content); } catch (e) { error(e.message); }
    refreshStatus(); setInterval(refreshStatus, 3000);
    if (!panel) proactiveLoop(() => config, () => !busy && !mic.recording && !speaker.playing && document.visibilityState === 'visible',
      result => { showReply(result); });
  }
  init();
})();
