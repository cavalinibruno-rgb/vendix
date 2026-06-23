const { app, BrowserWindow, shell, Menu, ipcMain } = require('electron');
const path = require('path');

const VENDIX_URL = 'https://vendix-production-5c8b.up.railway.app';

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    icon: path.join(__dirname, 'assets', 'icon.png'),
    title: 'Vendix',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
    show: false,
  });

  // Tela de loading enquanto carrega
  win.loadFile(path.join(__dirname, 'assets', 'loading.html'));

  // Após carregar o loading, abre o Vendix
  win.webContents.once('did-finish-load', () => {
    win.loadURL(VENDIX_URL + '/login');
  });

  win.once('ready-to-show', () => {
    win.show();
  });

  // Links externos abrem no navegador padrão
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Remove o menu nativo
  Menu.setApplicationMenu(null);
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// Impressão silenciosa: cria janela oculta, carrega URL e imprime sem diálogo
ipcMain.on('print-silent', (event, url) => {
  const printWin = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  printWin.loadURL(url);
  printWin.webContents.once('did-finish-load', () => {
    printWin.webContents.print({ silent: true, printBackground: false }, () => {
      printWin.close();
    });
  });
});
