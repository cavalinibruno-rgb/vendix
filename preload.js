const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  printSilent: (url) => ipcRenderer.send('print-silent', url),
});

window.addEventListener('DOMContentLoaded', () => {
  document.title = 'Vendix';
});
