'use strict';
// Shared pieces used by the browser page, the desktop overlay and the model gallery.
const Companion = (() => {
  async function api(path, data, { raw = false, headers = {} } = {}) {
    const options = data === undefined ? {} : {
      method: 'POST',
      headers: { 'Content-Type': raw ? 'application/octet-stream' : 'application/json', ...headers },
      body: raw ? data : JSON.stringify(data),
    };
    const response = await fetch(path, options);
    if (!response.ok) {
      let body; try { body = await response.json(); } catch {}
      throw new Error(body?.error || `Request failed (${response.status}).`);
    }
    return response;
  }
  const getJSON = async path => (await api(path)).json();
  const postJSON = async (path, data) => (await api(path, data)).json();

  // ---------- Live2D avatar ----------
  const MOUTH_FALLBACKS = ['ParamMouthOpenY', 'PARAM_MOUTH_OPEN_Y', 'ParamA'];
  // The Cubism renderer keeps global WebGL state, so a page may only have ONE canvas. Several avatars on one
  // page (the gallery) share a Stage and are positioned over their own mount elements. Live2D ignores PIXI
  // masks and scissors, so shared avatars must be framed to fit inside their mount.
  class Stage {
    constructor(mount, { fps = 30 } = {}) {
      this.mount = mount;
      this.app = new PIXI.Application({ backgroundAlpha: 0, antialias: true, resizeTo: mount,
        resolution: Math.min(window.devicePixelRatio || 1, 2), autoDensity: true });
      this.app.ticker.maxFPS = fps;
      mount.appendChild(this.app.view);
      new ResizeObserver(() => this.app.resize()).observe(mount);
    }
  }
  class Avatar {
    constructor(mount, { fps = 30, stage, onTap } = {}) {
      this.mount = mount; this.onTap = onTap;
      this.mouthLevel = () => 0;
      this.shared = !!stage;
      this.stage = stage || new Stage(mount, { fps });
      this.app = this.stage.app;
      this.holder = new PIXI.Container();
      this.app.stage.addChild(this.holder);
      new ResizeObserver(() => this.fit()).observe(mount);
    }
    async load(def) {
      if (!window.Live2DCubismCore || !window.PIXI?.live2d) throw new Error('Live2D runtime could not load.');
      PIXI.live2d.config.sound = false;  // some sample motions carry their own Japanese voice clips
      const model = await PIXI.live2d.Live2DModel.from('/' + def.model, { autoInteract: true });
      if (this.model) { this.holder.removeChild(this.model); this.model.destroy(); }
      this.def = def; this.model = model;
      this.holder.addChild(model);
      model.anchor.set(0.5, 0);
      this.size = { width: model.width, height: model.height };
      const core = model.internalModel.coreModel;
      const ids = [def.mouth, ...MOUTH_FALLBACKS].filter(Boolean);
      this.mouthId = ids.find(id => core.getParameterIndex(id) >= 0);
      // Apply lip sync after motions/physics, right before the core computes the mesh.
      const update = core.update.bind(core);
      let smooth = 0;
      core.update = (...args) => {
        const level = this.mouthLevel();
        smooth += (level - smooth) * (level > smooth ? 0.6 : 0.3);
        if (this.mouthId && smooth > 0.01) core.setParameterValueById(this.mouthId, Math.min(1, smooth));
        return update(...args);
      };
      model.on('hit', () => { this.react(); this.onTap?.(); });
      this.fit();
      return model;
    }
    fit() {
      if (!this.model) return;
      const w = this.mount.clientWidth, h = this.mount.clientHeight;
      if (!w || !h) return;
      let x0 = 0, y0 = 0;
      if (this.shared) {
        const r = this.mount.getBoundingClientRect(), o = this.stage.mount.getBoundingClientRect();
        x0 = r.left - o.left; y0 = r.top - o.top;
      } else this.app.renderer.resize(w, h);
      const zoom = this.def.zoom || 1;
      const scale = Math.min(w / this.size.width, h / this.size.height) * zoom;
      this.model.scale.set(scale);
      const shown = this.size.height * scale;
      // Zoomed-in models are cropped at the waist; full-size ones stand on the bottom edge.
      const top = zoom > 1.05 ? -(this.def.y || 0) * shown : h - shown;
      this.model.position.set(x0 + w / 2, y0 + top);
    }
    bounds() { return this.model?.getBounds(); }
    motionGroups() { return Object.keys(this.model?.internalModel.motionManager.definitions || {}); }
    react() {
      const groups = this.motionGroups();
      const group = ['Tap', 'TapBody', 'Flick', 'FlickUp'].find(g => groups.includes(g));
      if (group) this.model.motion(group, undefined, 2);
      this.emotion('happy');
    }
    emotion(name) {
      if (!this.model) return;
      const entry = this.def.emotions?.[name];
      clearTimeout(this.resetTimer);
      if (!entry) return;
      if (entry.expression) this.model.expression(entry.expression);
      if (entry.motion) this.model.motion(entry.motion[0], entry.motion[1], 3);
      if (name !== 'neutral') this.resetTimer = setTimeout(() => this.emotion('neutral'), 15000);
    }
    destroy() { if (!this.shared) this.app.destroy(true, { children: true }); }
  }

  // ---------- Voice playback with lip-sync level ----------
  // speak(text) says one thing. For a reply that is still being written: begin(), then say(sentence) for each
  // sentence as it arrives (its audio is fetched right away, while earlier sentences play), then end().
  class Speaker {
    constructor({ onStart, onEnd } = {}) {
      this.onStart = onStart; this.onEnd = onEnd; this.generation = 0; this.queue = [];
      addEventListener('pointerdown', () => { if (this.ctx?.state !== 'running') this.prepare().catch(() => {}); });
    }
    async prepare() {
      this.ctx ||= new AudioContext();
      if (this.ctx.state === 'running') return;
      // Browsers keep audio off until the page has been clicked; resume() would wait for that forever.
      await Promise.race([this.ctx.resume(), new Promise(resolve => setTimeout(resolve, 1000))]);
      if (this.ctx.state !== 'running') throw new Error('Click anywhere on the page to turn her voice on.');
    }
    level() {
      if (!this.analyser || !this.playing) return 0;
      this.analyser.getByteTimeDomainData(this.samples);
      let sum = 0;
      for (const x of this.samples) sum += ((x - 128) / 128) ** 2;
      return Math.min(1, Math.sqrt(sum / this.samples.length) * 6);
    }
    stop() {
      this.generation++;
      this.queue = []; this.closed = true;
      this.interrupt?.(); this.wake?.();
      if (this.playing) { this.playing = false; this.onEnd?.(); }
    }
    begin() {
      this.stop();
      this.closed = false;
      this.done = this.run(this.generation);
      this.done.catch(() => {});
      return this.done;
    }
    say(text) {
      if (this.closed || !/[\p{L}\p{N}]/u.test(text)) return;  // nothing speakable (e.g. just an emoji)
      // fetch + Web Audio rather than <audio>: Chrome postpones loading <audio> in background tabs.
      const audio = api('/api/speech', { text }).then(r => r.arrayBuffer());
      audio.catch(() => {});
      this.queue.push(audio); this.wake?.();
    }
    end() { this.closed = true; this.wake?.(); return this.done || Promise.resolve(); }
    speak(text) { this.begin(); this.say(text); return this.end(); }
    async run(generation) {
      try {
        await this.prepare();
        while (generation === this.generation) {
          if (!this.queue.length) {
            if (this.closed) break;
            await new Promise(resolve => { this.wake = resolve; });
            continue;
          }
          const buffer = await this.ctx.decodeAudioData(await this.queue.shift());
          if (generation !== this.generation) return;
          await this.play(buffer);
        }
      } catch (e) {
        if (generation === this.generation) this.stop();
        throw e;
      }
      if (generation === this.generation && this.playing) { this.playing = false; this.onEnd?.(); }
    }
    play(buffer) {
      if (!this.analyser) {
        this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = 512;
        this.samples = new Uint8Array(this.analyser.fftSize);
        this.analyser.connect(this.ctx.destination);
      }
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.analyser);
      return new Promise(resolve => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true; this.interrupt = null; source.onended = null;
          try { source.stop(); } catch {}
          source.disconnect(); resolve();
        };
        this.interrupt = finish;
        source.onended = finish;
        source.start();
        if (!this.playing) { this.playing = true; this.onStart?.(); }
      });
    }
  }

  // ---------- Chat: the reply streams in, and is spoken a sentence at a time while the rest is written ----------
  const EMOTION_TAG = /\[(?:neutral|happy|excited|sad|angry|surprised|shy|thinking)\]\s*/gi;
  const SENTENCE_END = /[.!?…~]+["'”’)\]]*\s+/g;
  const CLAUSE_END = /[,;:—–]\s+/g;
  async function chat(payload, { onEmotion, onText, speaker } = {}) {
    const response = await api('/api/chat', { ...payload, stream: true });
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '', text = '', unspoken = '', result = null, speech = null;
    const sayReady = () => {
      let cut = 0;
      for (const m of unspoken.matchAll(SENTENCE_END)) cut = m.index + m[0].length;
      // In a long sentence, start on the first part (up to a comma) instead of leaving a silent gap.
      if (!cut && unspoken.length > 50) for (const m of unspoken.matchAll(CLAUSE_END)) if (m.index > 20) cut = m.index + m[0].length;
      if (!cut) return;
      if (!speech) speech = speaker.begin();
      speaker.say(unspoken.slice(0, cut)); unspoken = unspoken.slice(cut);
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const lines = buffer.split('\n'); buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.error) throw new Error(event.error);
          if (event.emotion) onEmotion?.(event.emotion);
          if (event.delta) {
            text += event.delta; onText?.(text.replace(EMOTION_TAG, '').trim());
            if (speaker) { unspoken += event.delta; sayReady(); }
          }
          if (event.done) result = event;
        }
      }
      if (!result) throw new Error('The reply was cut off. Try again?');
    } catch (e) { if (speech) speaker.stop(); throw e; }
    if (speaker && unspoken.trim()) { if (!speech) speech = speaker.begin(); speaker.say(unspoken); }
    return { ...result, speech: speech ? speaker.end() : null };
  }

  // ---------- Microphone: click to start, click again to send ----------
  class Mic {
    constructor({ onState, maxSeconds = 45 } = {}) { this.onState = onState; this.maxSeconds = maxSeconds; this.recording = false; }
    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
      this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : {});
      this.chunks = [];
      this.recorder.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
      this.done = new Promise(resolve => { this.recorder.onstop = resolve; });
      this.recorder.start();
      this.recording = true; this.onState?.('recording');
      this.timer = setTimeout(() => this.recorder.state === 'recording' && this.recorder.stop(), this.maxSeconds * 1000);
    }
    // Stops recording and returns the transcript.
    async finish() {
      if (this.recorder.state === 'recording') this.recorder.stop();
      await this.done;
      clearTimeout(this.timer);
      this.stream.getTracks().forEach(t => t.stop());
      this.recording = false; this.onState?.('transcribing');
      try {
        const type = this.recorder.mimeType || 'audio/webm';
        const result = await (await api('/api/transcribe', new Blob(this.chunks, { type }),
          { raw: true, headers: { 'X-Audio-Type': type } })).json();
        return result.text.trim();
      } finally { this.onState?.('idle'); }
    }
    cancel() {
      clearTimeout(this.timer);
      if (this.recorder?.state === 'recording') this.recorder.stop();
      this.stream?.getTracks().forEach(t => t.stop());
      this.recording = false; this.onState?.('idle');
    }
    micError(e) {
      return e.name === 'NotAllowedError' ? 'Microphone access is blocked. Allow it for this app, or type instead.'
        : `Microphone unavailable: ${e.message}`;
    }
  }

  // ---------- Proactive glances ----------
  function proactiveLoop(getConfig, isIdle, onReply) {
    let last = Date.now();
    setInterval(async () => {
      const screen = getConfig()?.screen;
      if (!screen?.proactive || screen.mode === 'off' || !isIdle()) return;
      if (Date.now() - last < screen.proactive_interval_seconds * 1000) return;
      last = Date.now();
      try {
        const result = await postJSON('/api/proactive', {});
        if (!result.skip) onReply(result);
      } catch {}
    }, 5000);
  }

  // Tabs/windows of the same app talk to each other (desktop overlay <-> chat panel).
  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('companion') : null;

  return { api, getJSON, postJSON, chat, Stage, Avatar, Speaker, Mic, proactiveLoop, channel };
})();
