'use strict';
// Model picker. Grid mode shows everyone full-body on one shared canvas; ?focus=<id> shows one model big.
(async () => {
  const { getJSON, postJSON, Stage, Avatar, Speaker } = Companion;
  const $ = id => document.getElementById(id);
  const showError = m => { $('error').textContent = m; $('error').hidden = !m; };
  let config = await getJSON('/api/config');
  const ids = Object.keys(config.avatars);
  const focus = new URLSearchParams(location.search).get('focus');
  let speaking = null;
  const speaker = new Speaker({ onEnd: () => { speaking = null; } });

  for (const p of config.sections.voice.presets) $('voice').add(new Option(p.label, p.name, false, p.name === config.sections.voice.active));
  $('voice').onchange = async () => {
    try { config = await postJSON('/api/config', { voice: $('voice').value }); showError(''); } catch (e) { showError(e.message); }
  };

  function makeCard(id, def, { big = false } = {}) {
    const card = document.createElement('article');
    card.className = 'card' + (big ? ' big' : '');
    card.innerHTML = `<div class="view"><div></div><span class="loading">Loading…</span></div>
      <div class="info"><h3><span></span><small></small></h3><p></p>
      <div class="actions"><button class="hi">Say hi ♪</button>${big ? '<button class="frame">Full body</button>' : '<a class="zoom" href="?focus=' + id + '">Close-up</a>'}<button class="choose">Choose</button></div>
      <div class="credit"></div></div>`;
    card.querySelector('h3 span').textContent = def.name;
    card.querySelector('p').textContent = def.blurb || '';
    card.querySelector('.credit').textContent = def.credit || '';
    return card;
  }
  function markCurrent(cards) {
    for (const c of cards) {
      c.card.classList.toggle('active', c.id === config.avatar);
      c.card.querySelector('h3 small').textContent = c.id === config.avatar ? 'CURRENT' : '';
    }
  }
  function wire(entry, cards) {
    const { id, def, avatar, card } = entry;
    avatar.mouthLevel = () => (speaking === id ? speaker.level() : 0);
    card.querySelector('.view').onclick = () => avatar.model && avatar.react();
    card.querySelector('.hi').onclick = async () => {
      try {
        speaker.stop(); speaking = id; avatar.emotion('happy');
        await speaker.speak(`Hi hi! I'm ${def.name}! Wanna hang out with me today? I promise I'm super fun!`);
      } catch (e) { showError(e.message); }
    };
    card.querySelector('.choose').onclick = async () => {
      try {
        config = await postJSON('/api/config', { avatar: id });
        markCurrent(cards);
        Companion.channel?.postMessage({ type: 'config' });
        showError('');
      } catch (e) { showError(e.message); }
    };
    avatar.load(entry.frame(def))
      .then(() => card.querySelector('.loading').remove())
      .catch(e => { card.querySelector('.loading').textContent = `Couldn't load: ${e.message}`; });
  }

  if (focus && config.avatars[focus]) {
    document.body.classList.add('focus-mode');
    const def = config.avatars[focus];
    const index = ids.indexOf(focus);
    $('prev').href = '?focus=' + ids[(index + ids.length - 1) % ids.length];
    $('next').href = '?focus=' + ids[(index + 1) % ids.length];
    const card = makeCard(focus, def, { big: true });
    $('grid').appendChild(card);
    let closeUp = true;
    const avatar = new Avatar(card.querySelector('.view>div'), { fps: 30 });
    const entry = { id: focus, def, avatar, card, frame: d => ({ ...d, zoom: closeUp ? d.zoom : 1 }) };
    card.querySelector('.frame').onclick = e => {
      closeUp = !closeUp; e.target.textContent = closeUp ? 'Full body' : 'Close-up';
      avatar.def = entry.frame(def); avatar.fit();
    };
    wire(entry, [entry]); markCurrent([entry]);
    return;
  }

  const stage = new Stage($('stage'), { fps: 24 });
  const cards = [];
  // The shared canvas ignores the mouse (so cards stay clickable); aim the models' eyes by hand.
  addEventListener('pointermove', e => {
    const o = stage.mount.getBoundingClientRect();
    for (const c of cards) c.avatar.model?.focus(e.clientX - o.left, e.clientY - o.top);
  });
  for (const [id, def] of Object.entries(config.avatars)) {
    const card = makeCard(id, def);
    $('grid').appendChild(card);
    const entry = { id, def, card, avatar: new Avatar(card.querySelector('.view>div'), { stage }), frame: d => ({ ...d, zoom: 1 }) };
    cards.push(entry);
    wire(entry, cards);
  }
  markCurrent(cards);
})();
