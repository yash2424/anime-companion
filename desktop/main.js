// Desktop companion: a transparent, frameless, always-on-top window with the character, a tray icon and
// global hotkeys. The Python server (../server.py) does the thinking; this is only the body.
const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, screen, session, nativeImage, dialog } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = 'true';  // only our own local pages are loaded
const ROOT = path.resolve(__dirname, '..');
const BASE = 'http://127.0.0.1:8765';
const STATE_FILE = path.join(ROOT, 'data', 'desktop-state.json');
let overlay, panel, tray, config = {}, dragTimer, quitting = false;

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => showOverlay());

const readState = () => { try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; } };
function saveState() {
  if (!overlay) return;
  try { fs.writeFileSync(STATE_FILE, JSON.stringify({ bounds: overlay.getBounds() })); } catch {}
}

async function serverUp() {
  try { const r = await fetch(BASE + '/api/status'); return (await r.json()).app === 'anime-companion'; } catch { return false; }
}
async function ensureServer() {
  if (await serverUp()) return true;
  const python = path.join(ROOT, '.venv', 'Scripts', 'pythonw.exe');
  const log = fs.openSync(path.join(ROOT, 'data', 'launcher.log'), 'a');
  spawn(python, [path.join(ROOT, 'server.py')], { cwd: ROOT, detached: true, stdio: ['ignore', log, log], windowsHide: true }).unref();
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 750));
    if (await serverUp()) return true;
  }
  return false;
}

function createOverlay() {
  const d = config.desktop || {};
  const area = screen.getPrimaryDisplay().workArea;
  const saved = readState().bounds;
  const width = d.width || 380, height = d.height || 620;
  let bounds = { width, height, x: area.x + area.width - width - 24, y: area.y + area.height - height };
  // Only restore a saved position if it is still on some screen.
  if (saved && screen.getAllDisplays().some(s => saved.x < s.bounds.x + s.bounds.width - 50 && saved.x + saved.width > s.bounds.x + 50
      && saved.y < s.bounds.y + s.bounds.height - 50 && saved.y + saved.height > s.bounds.y + 50)) bounds = saved;
  overlay = new BrowserWindow({
    ...bounds, transparent: true, frame: false, resizable: false, hasShadow: false, skipTaskbar: true,
    alwaysOnTop: d.always_on_top !== false, backgroundColor: '#00000000', title: 'Companion · anime companion',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), backgroundThrottling: false,
      autoplayPolicy: 'no-user-gesture-required' },
  });
  if (d.always_on_top !== false) overlay.setAlwaysOnTop(true, 'floating');
  overlay.setIgnoreMouseEvents(true, { forward: true });
  overlay.loadURL(BASE + '/overlay.html');
  overlay.webContents.on('console-message', e => {
    if (e.level === 'warning' || e.level === 'error')
      fs.appendFile(path.join(ROOT, 'data', 'desktop.log'), `${new Date().toISOString()} ${e.level}: ${e.message}\n`, () => {});
  });
  overlay.on('moved', saveState);
  overlay.on('close', e => { if (!quitting) { e.preventDefault(); overlay.hide(); } });
}

function openPanel(page = '/?panel=1') {
  if (panel && !panel.isDestroyed()) {
    panel.loadURL(BASE + page); panel.show(); panel.focus(); return;
  }
  panel = new BrowserWindow({ width: 900, height: 820, title: 'Companion · anime companion', autoHideMenuBar: true,
    backgroundColor: '#f8f8f3', webPreferences: { autoplayPolicy: 'no-user-gesture-required' } });
  panel.loadURL(BASE + page);
  panel.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(BASE)) { panel.loadURL(url); return { action: 'deny' }; }
    require('electron').shell.openExternal(url); return { action: 'deny' };
  });
}

function showOverlay() { if (!overlay) return; overlay.showInactive(); }
function toggleOverlay() { if (!overlay) return; overlay.isVisible() ? overlay.hide() : showOverlay(); }

function registerHotkeys() {
  globalShortcut.unregisterAll();
  const keys = (config.desktop || {}).hotkeys || {};
  const failed = [];
  for (const [action, accelerator] of Object.entries(keys)) {
    if (!accelerator) continue;
    const ok = globalShortcut.register(accelerator, () => {
      if (action === 'toggle') return toggleOverlay();
      showOverlay();
      overlay.webContents.send('hotkey', action);
    });
    if (!ok) failed.push(accelerator);
  }
  return failed;
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'icon.png'));
  tray = new Tray(icon.resize({ width: 16, height: 16 }));
  tray.setToolTip('Anime companion');
  const keys = (config.desktop || {}).hotkeys || {};
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show / hide companion', accelerator: keys.toggle, click: toggleOverlay },
    { label: 'Chat history & settings', click: () => openPanel() },
    { label: 'Pick a character…', click: () => openPanel('/gallery.html') },
    { type: 'separator' },
    { label: 'Keep on top of other windows', type: 'checkbox', checked: overlay.isAlwaysOnTop(),
      click: item => overlay.setAlwaysOnTop(item.checked, 'floating') },
    { label: 'Reset position & size', click: () => { try { fs.unlinkSync(STATE_FILE); } catch {} quitting = true; overlay.destroy(); quitting = false; createOverlay(); } },
    { type: 'separator' },
    { label: 'Quit', click: quit },
  ]));
  tray.on('click', toggleOverlay);
}

async function quit() {
  quitting = true;
  if ((config.desktop || {}).stop_server_on_quit !== false) {
    try { await fetch(BASE + '/api/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch {}
  }
  app.quit();
}

ipcMain.on('ignore-mouse', (e, ignore) => overlay?.setIgnoreMouseEvents(ignore, { forward: true }));
ipcMain.on('drag-start', () => {
  clearInterval(dragTimer);
  const start = screen.getCursorScreenPoint();
  const [x, y] = overlay.getPosition();
  dragTimer = setInterval(() => {
    const p = screen.getCursorScreenPoint();
    overlay.setPosition(x + p.x - start.x, y + p.y - start.y);
  }, 10);
});
ipcMain.on('drag-end', () => { clearInterval(dragTimer); saveState(); });
ipcMain.on('resize-by', (e, factor) => {
  const b = overlay.getBounds();
  const width = Math.round(Math.max(220, Math.min(900, b.width * factor)));
  const height = Math.round(width * b.height / b.width);
  // Keep her feet where they were.
  overlay.setBounds({ x: Math.round(b.x + (b.width - width) / 2), y: b.y + b.height - height, width, height });
  saveState();
});
ipcMain.on('open-panel', () => openPanel());
ipcMain.on('hide', () => overlay.hide());
ipcMain.on('quit', quit);
ipcMain.on('focus', () => { overlay.show(); overlay.focus(); });

app.whenReady().then(async () => {
  // Allow the microphone for our own pages only.
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) =>
    callback(permission === 'media' && (details.requestingUrl || '').startsWith(BASE)));
  session.defaultSession.setPermissionCheckHandler((wc, permission, origin) => permission === 'media' && origin.startsWith(BASE));
  if (!(await ensureServer())) {
    dialog.showErrorBox('Companion', 'The companion server did not start. See data/launcher.log and data/server.log.');
    return app.quit();
  }
  try { config = await (await fetch(BASE + '/api/config')).json(); } catch {}
  createOverlay();
  buildTray();
  const failed = registerHotkeys();
  fs.appendFileSync(path.join(ROOT, 'data', 'desktop.log'),
    `${new Date().toISOString()} hotkeys: ${failed.length ? 'in use by another app: ' + failed.join(', ') : 'all registered'}\n`);
});
app.on('window-all-closed', e => e.preventDefault());
app.on('will-quit', () => globalShortcut.unregisterAll());
