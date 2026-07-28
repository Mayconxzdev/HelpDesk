const { contextBridge, ipcRenderer } = require('electron');

const subscribe = (channel, callback) => {
  if (typeof callback !== 'function') return () => {};
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};

contextBridge.exposeInMainWorld('electronAPI', Object.freeze({
  openFolder: (folderPath) => ipcRenderer.send('open-folder', String(folderPath || '')),
  setBadge: (count) => ipcRenderer.send('set-badge', Number(count) || 0),
  setUnreadState: (hasUnread) => ipcRenderer.send('set-unread-state', Boolean(hasUnread)),
  showPopup: (data) => ipcRenderer.send('show-popup', data || {}),
  showNotification: (data) => ipcRenderer.send('show-notification', data || {}),
  startUpdate: (url) => ipcRenderer.send('start-update', String(url || '')),
  getAppVersion: () => ipcRenderer.sendSync('get-app-version'),
  onUpdateProgress: (callback) => subscribe('update-progress', callback),
  onUpdateError: (callback) => subscribe('update-error', callback),
  onCallFeedback: (callback) => subscribe('send-call-feedback', callback),
  onNotificationClicked: (callback) => subscribe('notification-clicked', callback),
}));
