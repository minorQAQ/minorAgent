// electron-api.js — 文件操作适配层（桌面版）
// 所有文件系统操作通过此模块统一调用

const _api = window.electronAPI;
if (_api) { document.body.classList.add('is-electron'); }

// ===== 路径工具 =====
function ensureAbsPath(filePath, rootPath) {
  if (!filePath) return filePath;
  // 已是绝对路径（Windows 盘符 / Unix 根 / UNC）直接返回，避免错误拼接 root
  if (/^[A-Za-z]:[\\/]/.test(filePath) || filePath.startsWith('/') || filePath.startsWith('\\')) {
    return filePath;
  }
  if (!rootPath) return filePath;
  const root = rootPath.replace(/\\/g, '/').replace(/\/$/, '');
  return root + '/' + filePath;
}

// ===== 文件读写 =====

/** 读取文本文件 */
export async function readTextFile(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.readFile(absPath);
}

/** 写入文本文件 */
export async function writeTextFile(filePath, content, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.writeFile(absPath, content);
}

/** 列出目录（递归） */
export async function listDir(dirPath, depth = 10) {
  return _api.readDir(dirPath, depth);
}

/** 读取二进制文件（图片等），返回 base64 + mime */
export async function readBinaryFile(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.readBinaryFile(absPath);
}

/** 获取文件原始 URL（图片/HTML/PDF 预览用） */
export function getFileUrl(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  // Electron 下使用 file:// 协议直接加载本地文件
  return 'file:///' + absPath.replace(/\\/g, '/').replace(/^\//, '');
}

/** 获取文件 stat 信息 */
export async function statFile(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.stat(absPath);
}

/** 检查文件/目录是否存在 */
export async function fileExists(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.exists(absPath);
}

// ===== 文件操作 =====

/** 重命名/移动文件 */
export async function renameFile(oldPath, newPath, rootPath) {
  const oldAbs = ensureAbsPath(oldPath, rootPath);
  const newAbs = ensureAbsPath(newPath, rootPath);
  return _api.rename(oldAbs, newAbs);
}

/** 删除文件/目录 */
export async function deleteFile(filePath, rootPath) {
  const absPath = ensureAbsPath(filePath, rootPath);
  return _api.deleteFile(absPath);
}

/** 创建目录 */
export async function mkdir(dirPath, rootPath) {
  const absPath = ensureAbsPath(dirPath, rootPath);
  return _api.mkdir(absPath);
}

/** 将外部文件复制到目标目录 */
export async function copyExternalFile(srcPath, destDir) {
  return _api.copyFile(srcPath, destDir);
}

/** 将 base64 内容写入目标目录（用于拖拽导入） */
export async function writeFromBuffer(destDir, fileName, base64Data) {
  return _api.writeFromBuffer(destDir, fileName, base64Data);
}

// ===== 对话框 =====

/** 弹出文件夹选择器 */
export async function pickFolder() {
  const result = await _api.pickFolder();
  if (result.canceled) return null;
  return result.path;
}

/** 弹出文件选择器 */
export async function openFileDialog() {
  return _api.openFile();
}

/** 弹出保存对话框 */
export async function saveFileDialog(defaultPath) {
  return _api.saveFile(defaultPath);
}

// ===== 文件系统监听 =====
/** 开始监听目录变化 */
export async function watchDir(dirPath) {
  return _api.watchDir(dirPath);
}

/** 停止监听 */
export async function unwatchDir() {
  return _api.unwatchDir();
}

/** 监听文件变化事件 */
export function onFileChanged(cb) {
  _api.onFileChanged(cb);
}

// ===== 默认导出 =====
export default {
  readTextFile,
  readBinaryFile,
  writeTextFile,
  listDir,
  getFileUrl,
  statFile,
  fileExists,
  renameFile,
  deleteFile,
  mkdir,
  pickFolder,
  openFileDialog,
  saveFileDialog,
};
