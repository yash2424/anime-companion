// Dev helper (renders a page offscreen and saves a PNG; never shows a window or plays sound):
//   SNAP="<url> <out.png> [width] [height] [waitMs]" [SNAP_JS="script run before capture"] electron --no-sandbox snap.js
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const [url, out, width = '1400', height = '900', wait = '6000'] = (process.env.SNAP || '').split(' ');
const log = (...args) => { try { process.stdout.write(args.join(' ') + '\n'); } catch {} };
setTimeout(() => app.exit(2), +wait + 90000);  // hard stop, so nothing is ever left running
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: +width, height: +height, show: false,
    webPreferences: { offscreen: true, backgroundThrottling: false } });
  win.webContents.setAudioMuted(true);
  win.webContents.setFrameRate(10);
  let frame = null;
  win.webContents.on('paint', (event, dirty, image) => { frame = image; });
  win.webContents.on('console-message', e => log('[page]', e.message ?? ''));
  await win.loadURL(url);
  await new Promise(r => setTimeout(r, +wait));
  if (process.env.SNAP_JS) {
    await win.webContents.executeJavaScript(process.env.SNAP_JS);
    frame = null; await new Promise(r => setTimeout(r, 1500));
  }
  if (frame) { fs.writeFileSync(out, frame.toPNG()); log('saved', out); } else log('no frame painted');
  app.exit(0);
});
