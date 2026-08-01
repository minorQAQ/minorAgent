// edit-mode.js -- 文件管理模式（重构版）
// 保留: 文件树渲染、文档修改追踪、外部变更处理、快捷键、拖拽引用
// 移除: Monaco 编辑器、标签页、Agent 面板

import { $, escapeHtml, showToast, dedupePendingFiles } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';
import {
  readTextFile, readBinaryFile, writeTextFile, listDir, getFileUrl,
  pickFolder, watchDir, onFileChanged, copyExternalFile, writeFromBuffer, deleteFile
} from './electron-api.js';
import {
  renderPersistentToolCalls, renderToolCallRow, formatDuration, getToolCallsTotalDuration,
} from './toolcalls.js';
import { renderDocTree, setDocTreeDeps } from './doc-tree.js';
import { openFilePreview, closeFilePreview } from './file-preview.js';
import { setDocModifications } from './doc-mod-panel.js';

// ===== DOM 引用 =====
const modeEditBtn = $("modeEditBtn");
const modeChatBtn = $("modeChatBtn");
const modeCronBtn = $("modeCronBtn");
const chatPanel = $("chatPanel");
const sessionListWrap = $("sessionListWrap");
const docTreeWrap = $("docTreeWrap");
const cronListWrap = $("cronListWrap");
const docTree = $("docTree");
const sidebarHint = document.querySelector(".sidebar-hint");

// ===== 文档修改状态 =====
let docModifications = {};
let currentTaskModifications = [];
let _externalChanges = {};
let _fsChangeTimer = null;
let _fsApplying = false;

// 预览相关
const IMG_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico']);
const ALL_TEXT_EXTS = new Set(['.txt', '.json', '.md', '.py', '.js', '.ts', '.css', '.xml', '.yaml', '.yml',
  '.toml', '.csv', '.log', '.env', '.ini', '.cfg', '.sh', '.bat', '.ps1', '.sql', '.r', '.go', '.rs',
  '.rb', '.php', '.swift', '.kt', '.scala', '.cpp', '.c', '.h', '.java', '.m', '.html', '.htm', '.svg']);

function isSupportedFile(name) {
  const ext = (name || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  if (dot < 0) return false;
  const e = ext.substring(dot);
  return IMG_EXTS.has(e) || e === '.svg' || ALL_TEXT_EXTS.has(e) || e === '.pdf' || e === '.pptx'
    || e === '.xlsx' || e === '.xls' || e === '.docx' || e === '.doc' || e === '.ppt';
}

function isPreviewableImage(name) {
  const ext = (name || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && IMG_EXTS.has(ext.substring(dot));
}

function isPreviewableHtml(name) {
  return (name || '').toLowerCase().endsWith('.html') || (name || '').toLowerCase().endsWith('.htm');
}

const BINARY_EXTS = new Set([
  '.exe','.dll','.so','.dylib','.bin','.dat','.zip','.rar','.7z','.tar','.gz','.bz2','.xz',
  '.png','.jpg','.jpeg','.gif','.bmp','.ico','.webp','.tiff','.tif','.psd','.ai','.eps',
  '.mp3','.wav','.flac','.ogg','.m4a','.aac','.wma','.aiff',
  '.mp4','.avi','.mkv','.mov','.wmv','.flv','.webm','.m4v',
  '.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx',
  '.ttf','.otf','.woff','.woff2','.eot',
  '.db','.sqlite','.sqlite3','.mdb',
  '.iso','.dmg','.img','.vmdk',
  '.class','.jar','.war','.pyc','.pyo','.pyd',
  '.o','.obj','.lib','.a','.wasm',
]);
function isBinaryFile(name) {
  const lower = (name || '').toLowerCase();
  const dot = lower.lastIndexOf('.');
  return dot >= 0 && BINARY_EXTS.has(lower.substring(dot));
}

// ===== 模式切换 =====
export function switchToMode(mode) {
  state.mode = mode;
  if (mode === "edit") {
    state.editMode = true;
    modeChatBtn?.classList.remove("active");
    modeEditBtn?.classList.add("active");
    modeCronBtn?.classList.remove("active");
    // 编辑模式只影响左侧栏：显示文件树，隐藏会话列表与定时任务列表；聊天区域保持不变
    sessionListWrap?.classList.add("mode-hidden");
    cronListWrap?.classList.add("mode-hidden");
    if (sidebarHint) sidebarHint.classList.add("mode-hidden");
    docTreeWrap?.classList.remove("mode-hidden");
    _onLeaveCron();
  } else if (mode === "cron") {
    state.editMode = false;
    modeChatBtn?.classList.remove("active");
    modeEditBtn?.classList.remove("active");
    modeCronBtn?.classList.add("active");
    chatPanel?.classList.remove("mode-hidden");
    sessionListWrap?.classList.add("mode-hidden");
    docTreeWrap?.classList.add("mode-hidden");
    if (sidebarHint) sidebarHint.classList.add("mode-hidden");
    cronListWrap?.classList.remove("mode-hidden");
    closeFilePreview();
    _onEnterCron();
  } else {
    // chat 模式
    state.editMode = false;
    modeChatBtn?.classList.add("active");
    modeEditBtn?.classList.remove("active");
    modeCronBtn?.classList.remove("active");
    chatPanel?.classList.remove("mode-hidden");
    sessionListWrap?.classList.remove("mode-hidden");
    if (sidebarHint) sidebarHint.classList.remove("mode-hidden");
    docTreeWrap?.classList.add("mode-hidden");
    cronListWrap?.classList.add("mode-hidden");
    closeFilePreview();
    _onLeaveCron();
  }
}

// ===== Cron 模式进入/离开钩子（由 app.js 注入，避免循环依赖） =====
let _onEnterCronFn = null;
let _onLeaveCronFn = null;
export function setCronModeHooks({ onEnter, onLeave } = {}) {
  _onEnterCronFn = onEnter || null;
  _onLeaveCronFn = onLeave || null;
}
function _onEnterCron() {
  try { _onEnterCronFn && _onEnterCronFn(); } catch { /* ignore */ }
}
function _onLeaveCron() {
  try { _onLeaveCronFn && _onLeaveCronFn(); } catch { /* ignore */ }
}

// ===== 打开文件夹 =====
export async function autoOpenWorkspace() {
  if (!window.electronAPI) return;
  try {
    const data = await api("/api/workspace");
    const current = data.current || "";
    const defaultPath = data.default || "";
    const rootPath = current || defaultPath;
    if (rootPath) {
      await openFolder(rootPath);
    }
  } catch { /* ignore */ }
}

export async function openFolder(folderPath) {
  try {
    let rootPath = (typeof folderPath === "string" && folderPath) ? folderPath : null;
    if (!rootPath) {
      rootPath = await pickFolder();
    }
    if (!rootPath) return;

    state._docRootPath = rootPath;
    state._docRootName = rootPath.split(/[/\\]/).pop() || rootPath;

    try {
      const { addRecentFolder } = await import('../app.js');
      await addRecentFolder(rootPath);
    } catch {}

    if (!state._docTreeFolders) state._docTreeFolders = {};
    state._docTreeFolders[state._docRootName] = true;

    const listRes = await listDir(rootPath, 10);
    const files = listRes.files || [];
    const supportedFiles = files.filter((f) => !f.is_dir && isSupportedFile(f.name));
    // 去重：按 path 去重
    const seen = new Set();
    const uniqueFiles = [];
    for (const f of supportedFiles) {
      if (seen.has(f.path)) continue;
      seen.add(f.path);
      // 规范化路径：去掉 rootPath 前缀，确保相对路径，统一用 /
      let relPath = f.path.replace(/\\/g, "/");
      const normalizedRoot = rootPath.replace(/\\/g, "/").replace(/\/$/, "");
      if (relPath.startsWith(normalizedRoot + "/")) {
        relPath = relPath.substring(normalizedRoot.length + 1);
      }
      uniqueFiles.push({ ...f, path: relPath });
    }
    state.docFiles = [];
    state.docOpenTabs = [];
    docModifications = {};
    currentTaskModifications = [];
    _externalChanges = {};

    for (const f of uniqueFiles) {
      state.docFiles.push({ path: f.path, name: f.name, status: "original", size: f.size });
    }

    renderDocTree();
    renderDocTabs && renderDocTabs();

    if (state.docFiles.length > 0) {
      state.activeDocFile = state.docFiles[0].path;
      state.activeDocTab = state.docFiles[0].path;
      state.docOpenTabs = [{ path: state.docFiles[0].path, name: state.docFiles[0].name, modified: false }];
      renderDocTabs && renderDocTabs();
    }

    if (window.electronAPI) {
      watchDir(rootPath).then(() => {
        onFileChanged(handleFsChange);
      }).catch(() => {});
    }
  } catch (e) {
    showToast("打开文件夹失败: " + (e.message || e));
  }
}

export function showOpenButtons() {
  const snapDir = _snapDir();
  if (snapDir) {
    try { deleteFile(snapDir, ''); } catch {}
  }
  state._docRootPath = null;
  state._docRootName = null;
  state.docFiles = [];
  state.docOpenTabs = [];
  docModifications = {};
  currentTaskModifications = [];
  _externalChanges = {};
  _snapshots = [];
  _turnCounter = 0;
  _acceptedBaselines = {};
  renderDocTree();
  renderDocTabs && renderDocTabs();
}

// ===== 标签页（保留用于打开状态追踪） =====
export function renderDocTabs() {
  // 简化为无标签栏 - 文件点击直接预览
}

// ===== 文件点击预览 =====
export async function loadDocContent(filePath) {
  if (!state._docRootPath) return;
  const fileName = filePath.split(/[/\\]/).pop() || filePath;
  const status = docModifications[filePath]?.type || "";

  try {
    if (isPreviewableImage(fileName)) {
      const res = await readBinaryFile(filePath, state._docRootPath);
      if (res && res.status === 'ok' && res.data) {
        const dataUrl = `data:${res.mime || 'image/png'};base64,${res.data}`;
        const { showImagePreview } = await import('./toolcalls.js');
        showImagePreview(dataUrl);
      }
    } else if (isPreviewableHtml(fileName)) {
      const res = await readTextFile(filePath, state._docRootPath);
      if (res && res.status === 'ok') {
        openFilePreview(filePath, fileName, res.content || '',
          { status, onDownload: () => downloadFile(filePath, fileName) });
      }
    } else if (isBinaryFile(fileName)) {
      showToast('二进制文件不支持在线查看', 'warning');
    } else {
      const res = await readTextFile(filePath, state._docRootPath);
      if (res && res.status === 'ok') {
        openFilePreview(filePath, fileName, res.content || '',
          { status, onDownload: () => downloadFile(filePath, fileName) });
      } else {
        openFilePreview(filePath, fileName, '(无法读取文件)',
          { status, onDownload: () => downloadFile(filePath, fileName) });
      }
    }
  } catch {
    openFilePreview(filePath, fileName, '(加载失败)',
      { status, onDownload: () => downloadFile(filePath, fileName) });
  }
}

/** 以纯文本模式打开文件（供右键"文本编辑"使用） */
export async function openFileAsText(filePath) {
  if (!state._docRootPath) return;
  const fileName = filePath.split(/[/\\]/).pop() || filePath;
  if (isBinaryFile(fileName)) {
    showToast('二进制文件不支持在线查看', 'warning');
    return;
  }
  const status = docModifications[filePath]?.type || "";
  try {
    const res = await readTextFile(filePath, state._docRootPath);
    if (res && res.status === 'ok') {
      openFilePreview(filePath, fileName, res.content || '',
        { status, onDownload: () => downloadFile(filePath, fileName), asText: true });
    } else {
      openFilePreview(filePath, fileName, '(无法读取文件)',
        { status, onDownload: () => downloadFile(filePath, fileName) });
    }
  } catch {
    openFilePreview(filePath, fileName, '(加载失败)',
      { status, onDownload: () => downloadFile(filePath, fileName) });
  }
}

async function downloadFile(filePath, fileName) {
  try {
    if (isPreviewableImage(fileName)) {
      const res = await readBinaryFile(filePath, state._docRootPath);
      if (res && res.status === 'ok' && res.data) {
        const url = `data:${res.mime || 'image/png'};base64,${res.data}`;
        const a = document.createElement('a');
        a.href = url; a.download = fileName;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
      }
    } else {
      const res = await readTextFile(filePath, state._docRootPath);
      if (res && res.status === 'ok') {
        const blob = new Blob([res.content || ''], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = fileName;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    }
  } catch { /* ignore */ }
}

// ===== 快照系统（类 Git，持久化到磁盘）=====
// 目录结构: {snapshots_base}/{workspace_key}/
//   ├── _accepted/       # 接受基线
//   ├── turn_1/          # 第一轮快照
//   └── turn_2/          # 第二轮快照
// snapshots_base 由后端 /api/workspace 返回，默认为 workspace/.minor_snapshots
let _snapshots = []; // [{ turn: N, rootPath, timestamp, files: Map<path, {content, size, isBinary}> }]
let _turnCounter = 0;
let _acceptedBaselines = {}; // { path: { content, snapshotIdx } }

function _workspaceKey() {
  if (!state._docRootPath) return null;
  return state._docRootPath.replace(/[/\\]$/, '')
    .replace(/^[A-Za-z]:/, '')
    .replace(/[/\\:]/g, '_')
    .replace(/^_+/, '');
}

function _snapDir() {
  if (!state._docRootPath) return null;
  const wsKey = _workspaceKey();
  if (!wsKey) return null;
  const base = window.__minorSnapBase
    || (state._docRootPath.replace(/[/\\]$/, '') + '/.minor_snapshots');
  return base + '/' + wsKey;
}

function _turnDir(turn) { return _snapDir() + '/turn_' + turn; }
function _acceptDir() { return _snapDir() + '/_accepted'; }

/** 由外部设置快照基础目录（在 initWorkspace 中调用） */
export function setSnapBaseDir(baseDir) {
  window.__minorSnapBase = baseDir.replace(/\\/g, '/').replace(/\/$/, '');
}

/** 删除快照目录中的文件 */
async function _deleteSnapFile(relPath, srcDirRel) {
  const rootPath = state._docRootPath;
  const srcRel = srcDirRel.replace(rootPath.replace(/[/\\]$/, ''), '').replace(/^[/\\]+/, '') + '/' + relPath.replace(/\\/g, '/');
  try { await deleteFile(srcRel, rootPath); } catch {}
}

/** 复制文件（文本或二进制）到目标路径，目标路径相对于 workspace */
async function _copyFileTo(relPath, targetDirRel) {
  const rootPath = state._docRootPath;
  const tgtRel = targetDirRel.replace(rootPath.replace(/[/\\]$/, ''), '').replace(/^[/\\]+/, '') + '/' + relPath.replace(/\\/g, '/');
  try {
    // Try text first
    const text = await readTextFile(relPath, rootPath);
    await writeTextFile(tgtRel, text, rootPath);
    return { content: text, isBinary: false };
  } catch {
    // Binary
    try {
      const bin = await readBinaryFile(relPath, rootPath);
      if (bin && bin.base64) {
        // writeFromBuffer takes (parentDir, fileName, base64)
        const parentDir = tgtRel.substring(0, tgtRel.lastIndexOf('/'));
        const fileName = relPath.replace(/\\/g, '/').split('/').pop();
        await writeFromBuffer(parentDir, fileName, bin.base64);
        return { content: bin, isBinary: true };
      }
    } catch {}
  }
  return null;
}

/** 恢复文件（从源目录复制到 workspace）*/
async function _restoreFile(relPath, srcDirRel) {
  const rootPath = state._docRootPath;
  const srcRel = srcDirRel.replace(rootPath.replace(/[/\\]$/, ''), '').replace(/^[/\\]+/, '') + '/' + relPath.replace(/\\/g, '/');
  try {
    // Try text
    const text = await readTextFile(srcRel, rootPath);
    await writeTextFile(relPath, text, rootPath);
    return true;
  } catch {
    // Try binary
    try {
      const bin = await readBinaryFile(srcRel, rootPath);
      if (bin && bin.base64) {
        const parentDir = relPath.replace(/\\/g, '/').split('/').slice(0, -1).join('/') || '.';
        const fileName = relPath.replace(/\\/g, '/').split('/').pop();
        await writeFromBuffer(parentDir, fileName, bin.base64);
        return true;
      }
    } catch {}
  }
  return false;
}

/** 删除某文件在所有快照中的备份（接受或撤销时清理） */
async function _purgeFileFromSnapshots(relPath) {
  for (const s of _snapshots) {
    s.files.delete(relPath);
    await _deleteSnapFile(relPath, _turnDir(s.turn));
  }
  // Also delete from accepted baselines
  await _deleteSnapFile(relPath, _acceptDir());
}

/** 删除某个 turn 目录 */
async function _deleteTurnDir(turn) {
  const dir = _turnDir(turn);
  try { await deleteFile(dir, ''); } catch {}
}

/** 保存任务前快照（含完整文件内容，持久化到磁盘） */
export async function snapshotFilesForTask() {
  if (!state._docRootPath) return;
  const rootPath = state._docRootPath;
  const files = new Map();
  const turn = ++_turnCounter;
  const tDir = _turnDir(turn);

  for (const f of state.docFiles) {
    const result = await _copyFileTo(f.path, tDir);
    if (result) {
      files.set(f.path, { content: result.content, size: f.size, isBinary: result.isBinary });
    } else {
      files.set(f.path, { content: null, size: f.size, isBinary: false });
    }
  }

  _snapshots.push({
    turn,
    rootPath,
    timestamp: Date.now(),
    files,
  });

  // 首次快照时初始化接受基线（保存到磁盘）
  if (_snapshots.length === 1) {
    for (const [fp, info] of files) {
      await _copyFileTo(fp, _acceptDir());
      _acceptedBaselines[fp] = { content: info.content, snapshotIdx: 0, isBinary: info.isBinary };
    }
  }
}

/** 任务结束后对比快照，将Agent产生的变更记录到docModifications */
export function detectTaskFileChanges() {
  if (_snapshots.length === 0 || !state._docRootPath) return;

  const preSnap = _snapshots[_snapshots.length - 1];
  const preMap = preSnap.files;
  const curMap = new Map(state.docFiles.map(f => [f.path, f]));
  let changed = false;

  for (const [fp, f] of curMap) {
    const pre = preMap.get(fp);
    if (!pre) {
      // 新文件
      docModifications[fp] = { original: "", current: f.path, type: "new", snapshotIdx: preSnap.turn };
      if (!currentTaskModifications.includes(fp)) currentTaskModifications.push(fp);
      changed = true;
    } else if (pre.size !== f.size) {
      // 内容被修改
      docModifications[fp] = { original: pre.content || f.path, current: f.path, type: "modified", snapshotIdx: preSnap.turn, oldContent: pre.content };
      if (!currentTaskModifications.includes(fp)) currentTaskModifications.push(fp);
      changed = true;
    }
  }
  for (const [fp] of preMap) {
    if (!curMap.has(fp)) {
      // 被删除
      const preInfo = preMap.get(fp);
      docModifications[fp] = { original: preInfo.content || fp, current: "", type: "deleted", snapshotIdx: preSnap.turn, oldContent: preInfo.content };
      if (!currentTaskModifications.includes(fp)) currentTaskModifications.push(fp);
      changed = true;
    }
  }

  if (changed) {
    setDocModifications(docModifications);
    renderDocTree();
    try { import('./doc-mod-panel.js').then(m => { m.setDocModifications(docModifications); m.renderDocModPanel(); }); } catch {}
  }
}

/** 计算两个文本内容的行级 diff（返回简化差异列表） */
export function computeLineDiff(oldText, newText) {
  if (oldText == null || newText == null) return null;
  const oldLines = (oldText || '').split('\n');
  const newLines = (newText || '').split('\n');
  return _lineDiff(oldLines, newLines);
}

function _lineDiff(oldLines, newLines) {
  // 回溯 LCS
  const m = oldLines.length, n = newLines.length;
  // 对短文本使用简单 diff
  if (m === 0 && n === 0) return [];
  if (m === 0) return [{ type: 'add', startLine: 1, endLine: n, lines: newLines }];
  if (n === 0) return [{ type: 'remove', startLine: 1, endLine: m, lines: oldLines }];

  // LCS 矩阵
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // 回溯
  const diffs = [];
  let i = m, j = n;
  const tempOps = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      tempOps.unshift({ type: 'keep', oldLine: i, newLine: j });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      tempOps.unshift({ type: 'add', newLine: j, line: newLines[j - 1] });
      j--;
    } else {
      tempOps.unshift({ type: 'remove', oldLine: i, line: oldLines[i - 1] });
      i--;
    }
  }

  // 合并相邻的同类型差异
  for (const op of tempOps) {
    if (op.type === 'keep') continue;
    const last = diffs[diffs.length - 1];
    if (last && last.type === op.type) {
      if (op.type === 'add') {
        last.endLine = op.newLine;
        last.lines.push(op.line);
      } else {
        last.endLine = op.oldLine;
        last.lines.push(op.line);
      }
    } else {
      if (op.type === 'add') {
        diffs.push({ type: 'add', startLine: op.newLine, endLine: op.newLine, lines: [op.line] });
      } else {
        diffs.push({ type: 'remove', startLine: op.oldLine, endLine: op.oldLine, lines: [op.line] });
      }
    }
  }

  return diffs;
}

/** 接受单个文件的修改（更新接受基线，持久化，清理快照）*/
export async function acceptFileModification(filePath) {
  const rootPath = state._docRootPath;
  if (!rootPath) return;

  const mod = docModifications[filePath];
  if (!mod) return;

  if (mod.type === 'deleted') {
    // 接受删除 → 从修改列表和接受基线中移除
    delete docModifications[filePath];
    delete _acceptedBaselines[filePath];
    await _deleteSnapFile(filePath, _acceptDir());
  } else {
    // 接受新增/修改 → 更新磁盘上的接受基线
    const result = await _copyFileTo(filePath, _acceptDir());
    _acceptedBaselines[filePath] = {
      content: result ? result.content : null,
      snapshotIdx: _snapshots.length,
      isBinary: result ? result.isBinary : false
    };
    delete docModifications[filePath];
  }

  // 清理该文件在所有快照中的备份
  await _purgeFileFromSnapshots(filePath);

  currentTaskModifications = currentTaskModifications.filter(f => f !== filePath);
  setDocModifications(docModifications);
  renderDocTree();
}

/** 撤销单个文件的修改（回到接受基线，从磁盘恢复，支持二进制）*/
export async function rejectFileModification(filePath) {
  const rootPath = state._docRootPath;
  if (!rootPath) return;

  const mod = docModifications[filePath];
  if (!mod) return;

  if (mod.type === 'deleted') {
    // 撤销删除 → 从接受基线恢复文件
    await _restoreFile(filePath, _acceptDir());
  } else if (mod.type === 'new') {
    // 撤销新增 → 删除文件
    try { await deleteFile(filePath, rootPath); } catch {}
  } else {
    // 撤销修改 → 从接受基线恢复文件
    await _restoreFile(filePath, _acceptDir());
  }

  // 清理该文件在所有快照中的备份
  await _purgeFileFromSnapshots(filePath);

  delete docModifications[filePath];
  currentTaskModifications = currentTaskModifications.filter(f => f !== filePath);
  setDocModifications(docModifications);
  renderDocTree();

  // 刷新文件列表
  setTimeout(() => openFolder(rootPath), 500);
}

// 向后兼容导出
export function getDocModifications() { return docModifications; }
export function getCurrentTaskModifications() { return currentTaskModifications; }
export async function acceptAllModifications() {
  for (const fp of Object.keys(docModifications)) await acceptFileModification(fp);
}
export async function rejectAllModifications() {
  for (const fp of Object.keys(docModifications)) await rejectFileModification(fp);
}

// ===== 外部文件变更（实时自动刷新，类似 VS Code） =====
function handleFsChange(events) {
  if (_fsChangeTimer) clearTimeout(_fsChangeTimer);
  _fsChangeTimer = setTimeout(() => applyFsChanges(events), 300);
}

async function applyFsChanges(events) {
  if (_fsApplying || !state._docRootPath) return;
  _fsApplying = true;
  try {
    const rootPath = state._docRootPath;
    const listRes = await listDir(rootPath, 10);
    const currentFiles = (listRes.files || []).filter((f) => !f.is_dir && isSupportedFile(f.name));
    const currentMap = new Map(currentFiles.map((f) => [f.path, f]));

    const existingMap = new Map(state.docFiles.map((f) => [f.path, f]));
    const existingNames = new Set(existingMap.keys());
    const currentNames = new Set(currentMap.keys());

    let changed = false;

    // 检测新增和修改的文件
    for (const [fp, f] of currentMap) {
      if (!existingNames.has(fp)) {
        _externalChanges[fp] = { type: 'externally_added', name: f.name, size: f.size };
        changed = true;
      } else {
        const old = existingMap.get(fp);
        // 检测文件大小变化（即内容被外部修改）
        if (old.size !== f.size) {
          _externalChanges[fp] = { type: 'externally_modified', name: f.name, size: f.size, oldSize: old.size };
          changed = true;
        }
      }
    }

    // 检测删除的文件
    for (const fp of existingNames) {
      if (!currentNames.has(fp)) {
        _externalChanges[fp] = { type: 'externally_deleted', name: existingMap.get(fp).name };
        changed = true;
      }
    }

    if (changed) {
      state.docFiles = currentFiles;
      renderDocTree();
      // 同步外部变更到文档修改面板
      const extMods = {};
      for (const [fp, ec] of Object.entries(_externalChanges)) {
        extMods[fp] = { original: fp, current: fp, type: ec.type === 'externally_added' ? 'new' : ec.type === 'externally_modified' ? 'modified' : 'deleted' };
      }
      setDocModifications({ ...docModifications, ...extMods });
      try { import('./doc-mod-panel.js').then(m => m.renderDocModPanel()); } catch {}
    }
  } finally {
    _fsApplying = false;
  }
}

export function clearExternalChange(filePath) {
  delete _externalChanges[filePath];
  renderDocTree();
  setDocModifications(docModifications);
  try { import('./doc-mod-panel.js').then(m => m.renderDocModPanel()); } catch {}
}

// ===== 拖拽引用 =====
export function initDocReferences() {
  // 文件树元素拖拽到输入框
  if (docTree) {
    docTree.addEventListener('dragstart', (e) => {
      const item = e.target.closest('[data-file-path]');
      if (!item) return;
      const filePath = item.dataset.filePath;
      // 用专用 mime type 传递路径，避免和 text/plain 冲突
      e.dataTransfer.setData('application/doc-path', filePath);
      e.dataTransfer.effectAllowed = 'copy';
    });
  }

  // 输入区接收拖入
  setupInputDropHandler();
}

function setupInputDropHandler() {
  // 拖放目标设为整个 composer 输入区域，不只是 textarea
  const composerInput = document.querySelector('.composer-input-shell');
  const target = composerInput || $('textInput');
  if (!target) return;

  target.addEventListener('dragover', (e) => {
    const types = Array.from(e.dataTransfer.types);
    // 接受应用内文件/文件夹引用拖拽 或 外部文件拖拽
    if (types.includes('application/doc-path') || types.includes('Files')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    }
  });

  target.addEventListener('drop', async (e) => {
    e.preventDefault();

    // 1. 内部拖拽（doc-tree 文件/文件夹引用）
    // app.js 检测到 application/doc-path 也会 return，无需 stopPropagation
    if (Array.from(e.dataTransfer.types).includes('application/doc-path')) {
      const docPath = e.dataTransfer.getData('application/doc-path');
      const isFolder = e.dataTransfer.getData('application/doc-folder') === '1';
      if (isFolder) {
        addFolderRef(docPath);
      } else {
        addDocRef(docPath);
      }
      return;
    }

    // 2. 聊天区图片/文件拖拽 — 交给 app.js 处理（不 stopPropagation，让事件冒泡）
    if (e.dataTransfer.types.includes('application/x-chat-image') ||
        e.dataTransfer.types.includes('application/x-chat-file')) {
      return;
    }

    // 3. 外部拖拽（文件/文件夹）
    // stopPropagation 防止 app.js 递归展开文件夹内所有文件
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      e.stopPropagation();
      const items = Array.from(e.dataTransfer.items);
      // 先收集所有 entry，判断是否包含文件夹
      const allEntries = [];
      for (const item of items) {
        if (item.kind !== 'file') continue;
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        const file = item.getAsFile();
        allEntries.push({ entry, file });
      }
      const hasDirectory = allEntries.some(({ entry }) => entry && entry.isDirectory);

      if (hasDirectory) {
        // 有文件夹时：只处理文件夹项，跳过文件项（避免展开文件夹内容）
        for (const { entry, file } of allEntries) {
          if (entry && entry.isDirectory) {
            const folderPath = (file && file.path) ? file.path : '';
            const folderName = entry.name || (file ? file.name : '文件夹');
            addExternalFolderRef(folderPath, folderName);
          }
        }
      } else {
        // 无文件夹：图片作为普通 File 上传（HumanMessage image_url），非图片作为 @file: 引用
        // Electron 拖入的 File 带 path（绝对路径）且已包含二进制内容；无 path 时回退为普通上传
        let needFallback = false;
        for (const { file } of allEntries) {
          if (!file) continue;
          if (_isImageName(file.name)) {
            // 图片：直接作为普通文件上传（File 已含二进制内容）
            state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
            needFallback = true;
          } else if (file.path) {
            // 非图片：作为 @file: 绝对路径引用
            addExternalDocRef(file.path, file.name);
          } else {
            state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
            needFallback = true;
          }
        }
        if (needFallback) {
          import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
        }
      }

      if (allEntries.length > 0) {
        import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
      }
      return;
    }

    // 4. 回退：dataTransfer.files（无 items 时）— 图片作为普通 File 上传，非图片作为 @file: 引用
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      e.stopPropagation();
      const files = Array.from(e.dataTransfer.files);
      let needFallback = false;
      for (const file of files) {
        if (_isImageName(file.name)) {
          // 图片：直接作为普通文件上传
          state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
          needFallback = true;
        } else if (file.path) {
          // 非图片：作为 @file: 绝对路径引用
          addExternalDocRef(file.path, file.name);
        } else {
          state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
          needFallback = true;
        }
      }
      if (files.length > 0) {
        import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
      }
    }
  });
}

/** 判断文件名是否为图片（与后端 IMAGE_FILE_EXTENSIONS 对齐：png/jpg/jpeg/bmp/gif/webp/ico） */
function _isImageName(name) {
  const ext = (name || '').toLowerCase();
  return /\.(png|jpe?g|gif|webp|bmp|ico)$/.test(ext);
}

/** 读取工作区内图片文件二进制，构造为 File 并加入 pendingFiles（作为普通图片上传，HumanMessage image_url） */
async function _addImageFileAsUpload(relPath, fileName) {
  const rootPath = state._docRootPath;
  if (!rootPath) {
    showToast('请先打开工作区');
    return;
  }
  const name = fileName || relPath.split(/[/\\]/).pop() || relPath;
  try {
    const res = await readBinaryFile(relPath, rootPath);
    if (!res || res.status !== 'ok' || !res.data) {
      showToast('图片读取失败：' + name);
      return;
    }
    const bytes = Uint8Array.from(atob(res.data), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: res.mime || 'image/png' });
    const file = new File([blob], name, { type: blob.type });
    state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
    import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
  } catch (e) {
    showToast('图片读取失败：' + (e.message || e));
  }
}

/** 添加一个文档引用 chip
 * 图片（无行号引用）：读取二进制作为普通图片 File 上传（HumanMessage image_url），不生成 @file: 文本。
 * 非图片或带行号引用：作为 @file:path [Lx-Ly] 文本引用，只给 agent 绝对路径。
 */
export async function addDocRef(filePath, lineStart, lineEnd) {
  if (!filePath) return;
  const fileName = filePath.split(/[/\\]/).pop() || filePath;

  // 图片且无行号引用 → 作为普通图片上传
  if (_isImageName(fileName) && !lineStart) {
    // 防重复：若已作为普通文件或引用存在则跳过
    const exists = state.pendingFiles.some((f) =>
      (f.__isRef && f.refPath === filePath) || (!f.__isRef && f.name === fileName)
    );
    if (exists) return;
    await _addImageFileAsUpload(filePath, fileName);
    return;
  }

  // 非图片或带行号引用 → 作为 @file: 文本引用
  if (state.pendingRefs.some((r) => r.path === filePath)) return;
  const ref = {
    path: filePath,
    name: fileName,
    startLine: lineStart || null,
    endLine: lineEnd || null,
  };
  state.pendingRefs.push(ref);
  // 同步到 pendingFiles（统一渲染），用 __isRef 标记区分
  state.pendingFiles.push({
    __isRef: true,
    refPath: filePath,
    refName: fileName + (lineStart ? ` L${lineStart}-L${lineEnd}` : ''),
    type: 'ref/file',
    name: fileName,
  });
  import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
}

/** 添加工作区文件夹引用 chip（路径相对于 workspace root） */
export function addFolderRef(folderPath) {
  // 防重复
  if (state.pendingRefs.some((r) => r.isFolder && r.path === folderPath)) return;
  const folderName = folderPath
    ? folderPath.split(/[/\\]/).pop()
    : (state._docRootName || 'workspace');
  const ref = {
    path: folderPath,
    name: folderName,
    isFolder: true,
  };
  state.pendingRefs.push(ref);
  state.pendingFiles.push({
    __isRef: true,
    refPath: folderPath,
    refName: folderName,
    type: 'ref/folder',
    name: folderName,
    isFolder: true,
  });
  import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
}

/** 添加外部文件夹引用 chip（路径为绝对路径） */
export function addExternalFolderRef(absolutePath, folderName) {
  if (!absolutePath && !folderName) return;
  // 防重复
  if (state.pendingRefs.some((r) => r.isFolder && r.path === absolutePath)) return;
  const ref = {
    path: absolutePath || '',
    name: folderName || '文件夹',
    isFolder: true,
    isExternal: true,
  };
  state.pendingRefs.push(ref);
  state.pendingFiles.push({
    __isRef: true,
    refPath: absolutePath || '',
    refName: folderName || '文件夹',
    type: 'ref/folder',
    name: folderName || '文件夹',
    isFolder: true,
    isExternal: true,
  });
  import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
}

/** 添加外部文件引用 chip（绝对路径）
 * 图片：读取二进制作为普通图片 File 上传（HumanMessage image_url）。
 * 非图片：作为 @file:abspath 文本引用，只给 agent 绝对路径不读内容。
 */
export async function addExternalDocRef(absolutePath, fileName) {
  if (!absolutePath) return;
  const name = fileName || absolutePath.split(/[/\\]/).pop() || absolutePath;

  // 图片 → 读取二进制作为普通图片上传
  if (_isImageName(name)) {
    const exists = state.pendingFiles.some((f) =>
      (f.__isRef && f.refPath === absolutePath) || (!f.__isRef && f.name === name)
    );
    if (exists) return;
    await _addExternalImageAsUpload(absolutePath, name);
    return;
  }

  // 非图片 → 作为 @file: 文本引用
  if (state.pendingRefs.some((r) => r.path === absolutePath)) return;
  const ref = {
    path: absolutePath,
    name: name,
    isExternal: true,
  };
  state.pendingRefs.push(ref);
  state.pendingFiles.push({
    __isRef: true,
    refPath: absolutePath,
    refName: name,
    type: 'ref/file',
    name: name,
    isExternal: true,
  });
  import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
}

/** 读取外部（绝对路径）图片二进制，构造为 File 并加入 pendingFiles */
async function _addExternalImageAsUpload(absolutePath, fileName) {
  try {
    const { readBinaryFile: _readBinary } = await import('./electron-api.js');
    const res = await _readBinary(absolutePath, null);
    if (!res || res.status !== 'ok' || !res.data) {
      showToast('图片读取失败：' + fileName);
      return;
    }
    const bytes = Uint8Array.from(atob(res.data), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: res.mime || 'image/png' });
    const file = new File([blob], fileName, { type: blob.type });
    state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
    import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
  } catch (e) {
    showToast('图片读取失败：' + (e.message || e));
  }
}

/** 清除所有引用 chip */
export function clearRefChips() {
  state.pendingRefs = [];
  state.pendingFiles = state.pendingFiles.filter((f) => !f.__isRef);
  import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
}

/** 将 pendingRefs 转为发送给 AI 的文本引用 */
function _refsToText() {
  if (!state.pendingRefs.length) return '';
  const root = state._docRootPath ? state._docRootPath.replace(/\\/g, '/').replace(/\/$/, '') : '';
  return state.pendingRefs.map((ref) => {
    // 外部引用路径已是绝对路径（统一为正斜杠），工作区引用需拼接 root
    const absPath = ref.isExternal
      ? String(ref.path || '').replace(/\\/g, '/')
      : (root + '/' + ref.path);
    const prefix = ref.isFolder ? '@folder:' : '@file:';
    const linePart = ref.startLine ? ` L${ref.startLine}-L${ref.endLine}` : '';
    return `${prefix}${absPath}${linePart}`;
  }).join('\n');
}

// ===== 清除状态 =====
export function clearEditState() {
  // 清理该工作空间对应的快照子目录
  const snapDir = _snapDir();
  if (snapDir) {
    try { deleteFile(snapDir, ''); } catch {}
  }
  docModifications = {};
  currentTaskModifications = [];
  _externalChanges = {};
  _snapshots = [];
  _turnCounter = 0;
  _acceptedBaselines = {};
  setDocModifications({});
  closeFilePreview();
  clearRefChips();
  state.docFiles = [];
  state.docOpenTabs = [];
  state._docRootPath = null;
  state._docRootName = null;
  renderDocTree();
}

// ===== 发送 Edit 消息 =====
export async function sendEditChat() {
  if (!state.sessionId || state.sending) return;
  const textInput = $('textInput');
  const trimmed = textInput ? textInput.value.trim() : "";
  const refsText = _refsToText();
  const hasInput = trimmed || state.pendingFiles.length > 0 || state.pendingRefs.length > 0;
  if (!hasInput) return;

  // 保存原始文本，以便失败时恢复
  const originalVal = textInput ? textInput.value : '';

  // 将文档引用注入 textInput
  if (refsText) {
    textInput.value = originalVal ? originalVal + '\n\n' + refsText : refsText;
  }

  try {
    const { sendChat } = await import('./send.js');
    await sendChat();
  } catch (err) {
    // 发送失败：恢复原始文本，避免下次发送时重复注入 refs
    if (textInput) textInput.value = originalVal;
    throw err;
  } finally {
    // 无论成功失败都清除引用 chip，防止重复注入
    clearRefChips();
  }
}

// ===== 初始化 =====
export function initEditMode() {
  // 模式切换按钮
  modeEditBtn?.addEventListener("click", () => {
    if (!state.editMode) switchToMode("edit");
  });
  modeChatBtn?.addEventListener("click", () => {
    // 从 edit 或 cron 模式均可切回 chat
    if (state.mode !== "chat") switchToMode("chat");
  });

  // 打开文件夹 - 移除按钮，改用工作空间选择器触发

  // 文件树点击预览
  docTree?.addEventListener("click", async (e) => {
    const item = e.target.closest('[data-file-path]');
    if (!item) return;
    const filePath = item.dataset.filePath;
    if (filePath) {
      await loadDocContent(filePath);
    }
  });

  // 文件树拖拽引用
  initDocReferences();

  // 全局快捷键（Ctrl+C/X/V/F2/Delete 文件操作）
  document.addEventListener("keydown", (e) => {
    if (!state.editMode) return;
    const tag = document.activeElement?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    // 这些操作委托给 doc-tree.js
    // doc-tree.js 中已有自己的事件绑定
  }, { capture: true });

  // 文件树依赖注入
  setDocTreeDeps({
    loadDocContent,
    openFileAsText,
    externalChanges: () => _externalChanges,
  });

  // 初始化后同步到 doc-mod-panel
  try {
    import('./doc-mod-panel.js').then(m => m.bindDocModEvents());
  } catch {}
}
