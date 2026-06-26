const { app, BrowserWindow, shell, Menu, ipcMain, dialog, net } = require('electron');
const path = require('path');
const os   = require('os');
const fs   = require('fs');
const { execSync } = require('child_process');
const { autoUpdater } = require('electron-updater');

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

  win.loadFile(path.join(__dirname, 'assets', 'loading.html'));
  win.webContents.once('did-finish-load', () => {
    win.loadURL(VENDIX_URL + '/login');
  });
  win.once('ready-to-show', () => win.show());

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  Menu.setApplicationMenu(null);
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });

  setTimeout(() => {
    autoUpdater.checkForUpdatesAndNotify();
  }, 5000);
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ── Auto-update ───────────────────────────────────────
autoUpdater.on('update-available', () => {
  dialog.showMessageBox({
    type: 'info',
    title: 'Atualização disponível',
    message: 'Uma nova versão do Vendix está disponível e será baixada em segundo plano.',
    buttons: ['OK'],
  });
});

autoUpdater.on('update-downloaded', () => {
  dialog.showMessageBox({
    type: 'info',
    title: 'Atualização pronta',
    message: 'A atualização foi baixada. O Vendix será reiniciado para instalar.',
    buttons: ['Reiniciar agora'],
  }).then(() => autoUpdater.quitAndInstall());
});

// ── Lista impressoras ─────────────────────────────────
ipcMain.handle('get-printers', async () => {
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) return [];
  try {
    const printers = await win.webContents.getPrintersAsync();
    return printers.map(p => p.name);
  } catch (e) {
    return [];
  }
});

// ── Impressão RAW ESC/POS via PowerShell P/Invoke ────
ipcMain.handle('print-raw', async (event, escposUrl, printerName) => {
  try {
    // Busca bytes ESC/POS usando a sessão do Electron (inclui cookies Flask)
    const response = await net.fetch(escposUrl);
    if (!response.ok) {
      return { ok: false, error: `Servidor retornou ${response.status} — verifique se está logado.` };
    }
    const buffer = Buffer.from(await response.arrayBuffer());

    // Salva em arquivo temporário
    const tmpFile = path.join(os.tmpdir(), `vendix_${Date.now()}.bin`);
    fs.writeFileSync(tmpFile, buffer);
    const tmpEscaped = tmpFile.replace(/\\/g, '\\\\');
    const printerEscaped = printerName.replace(/"/g, '\\"').replace(/'/g, "''");

    // Envia RAW para a impressora via P/Invoke (igual ao win32print do Windows)
    const ps = `
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class RawPrinter {
    [DllImport("winspool.Drv", EntryPoint="OpenPrinterA", SetLastError=true, CharSet=CharSet.Ansi)]
    public static extern bool OpenPrinter(string sz, out IntPtr hP, IntPtr pd);
    [DllImport("winspool.Drv", EntryPoint="ClosePrinter")]
    public static extern bool ClosePrinter(IntPtr hP);
    [DllImport("winspool.Drv", EntryPoint="StartDocPrinterA", SetLastError=true, CharSet=CharSet.Ansi)]
    public static extern bool StartDocPrinter(IntPtr hP, Int32 level, [In, MarshalAs(UnmanagedType.LPStruct)] DocInfo di);
    [DllImport("winspool.Drv", EntryPoint="EndDocPrinter")]
    public static extern bool EndDocPrinter(IntPtr hP);
    [DllImport("winspool.Drv", EntryPoint="StartPagePrinter")]
    public static extern bool StartPagePrinter(IntPtr hP);
    [DllImport("winspool.Drv", EntryPoint="EndPagePrinter")]
    public static extern bool EndPagePrinter(IntPtr hP);
    [DllImport("winspool.Drv", EntryPoint="WritePrinter", SetLastError=true)]
    public static extern bool WritePrinter(IntPtr hP, IntPtr pBytes, Int32 dwCount, out Int32 dwWritten);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)]
    public class DocInfo {
        [MarshalAs(UnmanagedType.LPStr)] public string pDocName;
        [MarshalAs(UnmanagedType.LPStr)] public string pOutputFile;
        [MarshalAs(UnmanagedType.LPStr)] public string pDataType;
    }
}
"@ -ErrorAction Stop

$bytes = [System.IO.File]::ReadAllBytes("${tmpEscaped}")
$hP = [IntPtr]::Zero
[RawPrinter]::OpenPrinter("${printerEscaped}", [ref]$hP, [IntPtr]::Zero) | Out-Null
$di = New-Object RawPrinter+DocInfo
$di.pDocName = "Vendix"
$di.pDataType = "RAW"
[RawPrinter]::StartDocPrinter($hP, 1, $di) | Out-Null
[RawPrinter]::StartPagePrinter($hP) | Out-Null
$ptr = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
[System.Runtime.InteropServices.Marshal]::Copy($bytes, 0, $ptr, $bytes.Length)
$written = 0
[RawPrinter]::WritePrinter($hP, $ptr, $bytes.Length, [ref]$written) | Out-Null
[System.Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
[RawPrinter]::EndPagePrinter($hP) | Out-Null
[RawPrinter]::EndDocPrinter($hP) | Out-Null
[RawPrinter]::ClosePrinter($hP) | Out-Null
Write-Output "OK:$written"
`;
    const result = execSync(`powershell -NoProfile -Command "${ps.replace(/\n/g, ' ')}"`, { timeout: 15000 }).toString().trim();
    try { fs.unlinkSync(tmpFile); } catch (_) {}
    return { ok: true, written: result };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});
