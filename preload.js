const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Legado
  printSilent: (url) => ipcRenderer.invoke('print-silent', url, null),
  // Usado pelo PDV
  getPrinters: () => ipcRenderer.invoke('get-printers'),
  printRaw:    (url, printer) => ipcRenderer.invoke('print-silent', url, printer),
});

window.addEventListener('DOMContentLoaded', () => {
  document.title = 'Vendix';
});
