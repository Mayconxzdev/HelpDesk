const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  Notification,
  session,
  shell,
  Tray,
} = require('electron');
const fs = require('fs');
const path = require('path');
const {
  isAllowedExternalUrl,
  isAllowedPath,
  parseList,
  parseServerUrl,
} = require('./security');

const SERVER_URL = parseServerUrl(process.env.HELPDESK_SERVER_URL || 'http://127.0.0.1:5000');
const ALLOWED_PATHS = parseList(process.env.HELPDESK_ALLOWED_PATHS || '');
const UPDATE_HOSTS = String(process.env.HELPDESK_UPDATE_HOSTS || 'github.com,objects.githubusercontent.com')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean);

let mainWindow;
let tray;
let isQuitting = false;

app.setAppUserModelId('dev.maycon.helpdesk');

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    title: 'HelpDesk & IT Operations',
    icon: path.join(__dirname, 'icon.ico'),
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      preload: path.join(__dirname, 'preload.js'),
      partition: 'persist:helpdesk',
      backgroundThrottling: false,
    },
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (new URL(targetUrl).origin !== SERVER_URL.origin) event.preventDefault();
  });

  mainWindow.loadURL(SERVER_URL.toString()).catch((error) => {
    dialog.showErrorBox(
      'Servidor não encontrado',
      `Não foi possível conectar em ${SERVER_URL.origin}.
${error.message}`,
    );
  });
}

function createTray() {
  if (tray) return;
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'icon.ico')));
  tray.setToolTip('HelpDesk & IT Operations');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Abrir', click: () => mainWindow?.show() },
    { type: 'separator' },
    {
      label: 'Sair',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]));
  tray.on('double-click', () => mainWindow?.show());
}

function configurePermissions() {
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const requestingUrl = details?.requestingUrl || webContents.getURL() || '';
    let sameOrigin = false;
    try { sameOrigin = new URL(requestingUrl).origin === SERVER_URL.origin; } catch { sameOrigin = false; }
    callback(permission === 'media' && sameOrigin);
  });
}

ipcMain.on('get-app-version', (event) => { event.returnValue = app.getVersion(); });
ipcMain.on('set-unread-state', (_event, hasUnread) => {
  if (!tray) return;
  const iconPath = hasUnread ? 'icon_unread.png' : 'icon.ico';
  tray.setImage(nativeImage.createFromPath(path.join(__dirname, iconPath)));
  mainWindow?.flashFrame(Boolean(hasUnread));
});
ipcMain.on('set-badge', (_event, data) => {
  if (!mainWindow) return;
  if (process.platform === 'darwin') app.setBadgeCount(Number(data) || 0);
  else if (!data) mainWindow.setOverlayIcon(null, '');
});
ipcMain.on('show-notification', (_event, data = {}) => {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title: String(data.title || 'HelpDesk').slice(0, 120),
    body: String(data.body || '').slice(0, 500),
  });
  notification.on('click', () => {
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.webContents.send('notification-clicked', String(data.tag || ''));
  });
  notification.show();
});
ipcMain.on('show-popup', async (_event, data = {}) => {
  const caller = String(data.callerName || 'Um integrante da equipe').slice(0, 100);
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'warning',
    title: 'Convocação urgente',
    message: `${caller} solicita sua presença no chat.`,
    buttons: ['Abrir chat', 'Ignorar'],
    defaultId: 0,
    cancelId: 1,
  });
  if (result.response === 0) {
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.webContents.send('send-call-feedback', { to: String(data.callerUser || '') });
  }
});
ipcMain.on('open-folder', async (_event, folderPath) => {
  if (!isAllowedPath(folderPath, ALLOWED_PATHS) || !fs.existsSync(folderPath)) {
    dialog.showErrorBox('Caminho bloqueado', 'O diretório não pertence à lista permitida.');
    return;
  }
  const error = await shell.openPath(folderPath);
  if (error) dialog.showErrorBox('Erro ao abrir pasta', error);
});
ipcMain.on('start-update', async (event, url) => {
  if (!isAllowedExternalUrl(url, UPDATE_HOSTS)) {
    event.reply('update-error', 'URL de atualização não autorizada.');
    return;
  }
  await shell.openExternal(url);
  event.reply('update-progress', 1);
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();
else {
  app.on('second-instance', () => {
    if (mainWindow?.isMinimized()) mainWindow.restore();
    mainWindow?.show();
    mainWindow?.focus();
  });
  app.whenReady().then(() => {
    configurePermissions();
    createWindow();
    createTray();
    if (process.env.HELPDESK_AUTO_START === 'true') {
      app.setLoginItemSettings({ openAtLogin: true, path: app.getPath('exe') });
    }
  });
}

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
  else mainWindow?.show();
});
app.on('before-quit', () => { isQuitting = true; });
app.on('window-all-closed', () => {
  if (process.platform === 'darwin') app.quit();
});
