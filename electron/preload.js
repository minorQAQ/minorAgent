// preload.js — 安全桥接层（桌面版）
// 暴露最小化 API 供 setup.html 和主应用使用

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,

  // ===== 文件系统 =====
  readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
  readBinaryFile: (filePath) => ipcRenderer.invoke('fs:readBinaryFile', filePath),
  writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),
  readDir: (dirPath, depth) => ipcRenderer.invoke('fs:readDir', dirPath, depth ?? 10),
  stat: (filePath) => ipcRenderer.invoke('fs:stat', filePath),
  rename: (oldPath, newPath) => ipcRenderer.invoke('fs:rename', oldPath, newPath),
  deleteFile: (filePath) => ipcRenderer.invoke('fs:delete', filePath),
  mkdir: (dirPath) => ipcRenderer.invoke('fs:mkdir', dirPath),
  exists: (filePath) => ipcRenderer.invoke('fs:exists', filePath),
  copyFile: (srcPath, destDir) => ipcRenderer.invoke('fs:copyFile', srcPath, destDir),
  writeFromBuffer: (destDir, fileName, base64Data) => ipcRenderer.invoke('fs:writeFromBuffer', destDir, fileName, base64Data),

  // ===== 对话框 =====
  pickFolder: () => ipcRenderer.invoke('dialog:openFolder'),
  openFile: () => ipcRenderer.invoke('dialog:openFile'),
  saveFile: (defaultPath) => ipcRenderer.invoke('dialog:saveFile', defaultPath),

  // ===== 系统集成 =====
  openInExplorer: (filePath) => ipcRenderer.invoke('shell:openInExplorer', filePath),

  // ===== 内置 PowerShell 终端 =====
  spawnTerminal: (cwd) => ipcRenderer.invoke('terminal:spawn', { cwd }),
  sendTerminalInput: (id, data) => ipcRenderer.send('terminal:input', { id, data }),
  killTerminal: (id) => ipcRenderer.send('terminal:kill', { id }),
  killAllTerminals: () => ipcRenderer.send('terminal:killAll'),
  onTerminalData: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on('terminal:data', handler);
    return () => ipcRenderer.removeListener('terminal:data', handler);
  },
  onTerminalExit: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on('terminal:exit', handler);
    return () => ipcRenderer.removeListener('terminal:exit', handler);
  },

  // ===== 应用信息 =====
  getAppPath: () => ipcRenderer.invoke('app:getPath'),

  // ===== 首次配置 =====
  saveConfig: (data) => ipcRenderer.invoke('save-config', data),
  launchApp: () => ipcRenderer.send('launch-app'),
  isFirstRun: () => ipcRenderer.invoke('is-first-run'),
  onSetupComplete: (cb) => {
    ipcRenderer.on('setup:complete', () => cb());
  },

  // ===== 文件系统监听 =====
  watchDir: (dirPath) => ipcRenderer.invoke('fs:watch', dirPath),
  unwatchDir: () => ipcRenderer.invoke('fs:unwatch'),
  onFileChanged: (cb) => {
    ipcRenderer.on('fs:changed', (_e, data) => cb(data));
  },

  // ===== 窗口控制（自定义标题栏） =====
  minimizeWindow: () => ipcRenderer.send('window:minimize'),
  maximizeWindow: () => ipcRenderer.send('window:maximize'),
  closeWindow: () => ipcRenderer.send('window:close'),
  onMaximizeChanged: (cb) => {
    ipcRenderer.on('window:maximized', (_e, maximized) => cb(maximized));
  },

  // ===== 配置窗口控制 =====
  setupClose: () => ipcRenderer.send('setup:close'),

  // ===== Python 环境安装 =====
  pythonDetect: () => ipcRenderer.invoke('python:detect'),
  pickPython: () => ipcRenderer.invoke('dialog:pickPython'),
  pythonSetup: (pythonPath) => ipcRenderer.invoke('python:setup', pythonPath),
  onPythonSetupProgress: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on('python:setup-progress', handler);
    return () => ipcRenderer.removeListener('python:setup-progress', handler);
  },
});
