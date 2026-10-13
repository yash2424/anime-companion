const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  setIgnoreMouse: ignore => ipcRenderer.send('ignore-mouse', ignore),
  dragStart: () => ipcRenderer.send('drag-start'),
  dragEnd: () => ipcRenderer.send('drag-end'),
  resizeBy: factor => ipcRenderer.send('resize-by', factor),
  openPanel: () => ipcRenderer.send('open-panel'),
  hide: () => ipcRenderer.send('hide'),
  quit: () => ipcRenderer.send('quit'),
  focus: () => ipcRenderer.send('focus'),
  onHotkey: callback => ipcRenderer.on('hotkey', (e, action) => callback(action)),
});
