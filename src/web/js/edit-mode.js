// edit-mode.js -- 文件管理模式（重构版）
// 保留: 文件树渲染、文档修改追踪、外部变更处理、快捷键、拖拽引用
// 移除: Monaco 编辑器、标签页、Agent 面板

import { $, escapeHtml, showToast, dedupePendingFiles, filterOutUnsupported, isUnsupportedFile } from './utils.js';
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

// ===== DOM 引用 =====
const modeCronToggleBtn = $("modeCronToggleBtn");
const chatPanel = $("chatPanel");
const sessionListWrap = $("sessionListWrap");
const docTreeWrap = $("docTreeWrap");
const cronListWrap = $("cronListWrap");
const docTree = $("docTree");
const sidebarHint = document.querySelector(".sidebar-hint");

// ===== 外部文件变更 =====
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

/** 二进制表格（XLSX/XLS）：由后端 /api/table/text 提取为 TSV 后按列着色预览 */
function isPreviewableTable(name) {
  const ext = (name || '').toLowerCase();
  return ext.endsWith('.xlsx') || ext.endsWith('.xls');
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
let _modeSwitchCooldown = false;

/** 同步顶栏定时任务按钮的按下状态（cron 模式按下高亮，其余复位） */
function syncModeToggleBtn() {
  if (!modeCronToggleBtn) return;
  const isCron = state.mode === "cron";
  modeCronToggleBtn.classList.toggle("is-active", isCron);
  modeCronToggleBtn.setAttribute("aria-pressed", isCron ? "true" : "false");
  modeCronToggleBtn.title = isCron ? "返回对话" : "定时任务";
}

export function switchToMode(mode) {
  // 防连点：短时间内禁止重复切换
  if (_modeSwitchCooldown) return;
  _modeSwitchCooldown = true;
  setTimeout(() => { _modeSwitchCooldown = false; }, 300);

  // Edit 已迁入右栏：模式切换只影响左侧栏（会话列表/定时任务）与右栏显隐，
  // 聊天区保持不变，Agent 运行中也可自由切换
  state.mode = mode;
  syncModeToggleBtn();
  if (mode === "edit") {
    state.editMode = true;
    // 左栏始终显示会话列表；文件树在右栏
    sessionListWrap?.classList.remove("mode-hidden");
    cronListWrap?.classList.add("mode-hidden");
    if (sidebarHint) sidebarHint.classList.remove("mode-hidden");
    setRightPanel(true);
    _onLeaveCron();
  } else if (mode === "cron") {
    state.editMode = false;
    chatPanel?.classList.remove("mode-hidden");
    sessionListWrap?.classList.add("mode-hidden");
    if (sidebarHint) sidebarHint.classList.add("mode-hidden");
    cronListWrap?.classList.remove("mode-hidden");
    setRightPanel(false);
    closeFilePreview();
    _onEnterCron();
  } else {
    // chat 模式
    state.editMode = false;
    chatPanel?.classList.remove("mode-hidden");
    sessionListWrap?.classList.remove("mode-hidden");
    if (sidebarHint) sidebarHint.classList.remove("mode-hidden");
    cronListWrap?.classList.add("mode-hidden");
    setRightPanel(false);
    closeFilePreview();
    _onLeaveCron();
  }
  // 同步回合导航条显隐（cron 模式复用聊天容器，需隐藏导航条）
  import('./turn-nav.js').then((m) => m.syncTurnNavVisibility()).catch(() => {});
}

// ===== git 状态（文件树着色：新增绿 / 修改橙 / 删除橙+删除线） =====
let _gitStatusTimer = null;

export function refreshGitStatus() {
  if (!state._docRootPath) return;
  if (_gitStatusTimer) clearTimeout(_gitStatusTimer);
  _gitStatusTimer = setTimeout(async () => {
    try {
      const rootPath = state._docRootPath;
      const data = await api(`/api/workspace/git-status?path=${encodeURIComponent(rootPath)}`);
      const map = {};
      for (const s of data.status || []) map[s.path] = s.state;
      state.gitStatus = map;
      renderDocTree();
    } catch { /* git 不可用/非仓库时静默，保持无着色 */ }
  }, 150);
}

// ===== 右栏（Edit 文件树）控制 =====
export function setRightPanel(open) {
  const appRoot = document.getElementById("app");
  if (!appRoot) return;
  appRoot.classList.toggle("right-panel-open", !!open);
  const rp = document.getElementById("rightPanel");
  if (rp) rp.setAttribute("aria-hidden", open ? "false" : "true");
  // 打开时刷新 git 状态着色
  if (open) {
    try {
      window.dispatchEvent(new CustomEvent("git-status-changed"));
    } catch { /* ignore */ }
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

    // 先校验目录存在并列出文件；文件夹被删除/不可访问时给出明确提示，避免把失效路径写入状态
    let listRes;
    try {
      listRes = await listDir(rootPath, 10);
    } catch (e) {
      showToast("打开文件夹失败: " + (e.message || e));
      return;
    }

    state._docRootPath = rootPath;
    state._docRootName = rootPath.split(/[/\\]/).pop() || rootPath;

    try {
      const { addRecentFolder } = await import('../app.js');
      await addRecentFolder(rootPath);
    } catch {}

    if (!state._docTreeFolders) state._docTreeFolders = {};
    state._docTreeFolders[state._docRootName] = true;

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
    _externalChanges = {};

    for (const f of uniqueFiles) {
      state.docFiles.push({ path: f.path, name: f.name, status: "original", size: f.size });
    }

    renderDocTree();
    renderDocTabs && renderDocTabs();
    // 打开文件夹后刷新 git 状态着色
    refreshGitStatus();

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
  state._docRootPath = null;
  state._docRootName = null;
  state.docFiles = [];
  state.docOpenTabs = [];
  _externalChanges = {};
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
          { onDownload: () => downloadFile(filePath, fileName) });
      }
    } else if (isPreviewableTable(fileName)) {
      // XLSX/XLS：后端提取为 TSV 文本，走与 CSV/TSV 一致的按列着色预览
      const absPath = (/^[A-Za-z]:[\\/]/.test(filePath) || filePath.startsWith('/') || filePath.startsWith('\\'))
        ? filePath
        : state._docRootPath.replace(/[\\/]+$/, '') + '/' + filePath.replace(/^[\\/]+/, '');
      try {
        const tsv = await api('/api/table/text?path=' + encodeURIComponent(absPath));
        openFilePreview(absPath, fileName, (tsv && tsv.content) || '',
          { onDownload: () => downloadFile(absPath, fileName) });
      } catch (e) {
        openFilePreview(absPath, fileName, '(加载失败: ' + (e.message || e) + ')',
          { onDownload: () => downloadFile(absPath, fileName) });
      }
    } else if (isBinaryFile(fileName)) {
      showToast('二进制文件不支持在线查看', 'warning');
    } else {
      const res = await readTextFile(filePath, state._docRootPath);
      if (res && res.status === 'ok') {
        openFilePreview(filePath, fileName, res.content || '',
          { onDownload: () => downloadFile(filePath, fileName) });
      } else {
        openFilePreview(filePath, fileName, '(无法读取文件)',
          { onDownload: () => downloadFile(filePath, fileName) });
      }
    }
  } catch {
    openFilePreview(filePath, fileName, '(加载失败)',
      { onDownload: () => downloadFile(filePath, fileName) });
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
  try {
    const res = await readTextFile(filePath, state._docRootPath);
    if (res && res.status === 'ok') {
      openFilePreview(filePath, fileName, res.content || '',
        { onDownload: () => downloadFile(filePath, fileName), asText: true });
    } else {
      openFilePreview(filePath, fileName, '(无法读取文件)',
        { onDownload: () => downloadFile(filePath, fileName) });
    }
  } catch {
    openFilePreview(filePath, fileName, '(加载失败)',
      { onDownload: () => downloadFile(filePath, fileName) });
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
    } else if (isBinaryFile(fileName)) {
      // 二进制文件（xlsx/docx/pdf 等）：按 base64 还原字节后下载
      const res = await readBinaryFile(filePath, state._docRootPath);
      if (res && res.status === 'ok' && res.data) {
        const bin = atob(res.data);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const blob = new Blob([bytes], { type: res.mime || 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = fileName;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
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
    }
  } finally {
    _fsApplying = false;
  }
}

export function clearExternalChange(filePath) {
  delete _externalChanges[filePath];
  renderDocTree();
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

  // 子元素间移动会成对触发 dragenter/dragleave，用计数器避免状态误清除
  let dragDepth = 0;
  const setDragState = (on) => target.classList.toggle('is-drag-attach', on);
  const isAcceptedDrag = (types) => types.includes('application/doc-path') || types.includes('Files');

  target.addEventListener('dragenter', (e) => {
    if (isAcceptedDrag(Array.from(e.dataTransfer.types))) {
      dragDepth++;
      setDragState(true);
    }
  });

  target.addEventListener('dragover', (e) => {
    const types = Array.from(e.dataTransfer.types);
    // 接受应用内文件/文件夹引用拖拽 或 外部文件拖拽
    if (types.includes('application/doc-path') || types.includes('Files')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setDragState(true);
    }
  });

  target.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setDragState(false);
  });

  target.addEventListener('drop', async (e) => {
    e.preventDefault();
    dragDepth = 0;
    setDragState(false);

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
      // 先收集所有 entry，判断是否包含文件夹（视频暂不支持，直接过滤）
      const allEntries = [];
      for (const item of items) {
        if (item.kind !== 'file') continue;
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        const file = item.getAsFile();
        allEntries.push({ entry, file });
      }
      const acceptedFiles = filterOutUnsupported(allEntries.map(({ file }) => file).filter(Boolean));
      const filteredEntries = allEntries.filter(({ file }) => !file || acceptedFiles.includes(file));
      const hasDirectory = filteredEntries.some(({ entry }) => entry && entry.isDirectory);

      if (hasDirectory) {
        // 有文件夹时：只处理文件夹项，跳过文件项（避免展开文件夹内容）
        for (const { entry, file } of filteredEntries) {
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
        for (const { file } of filteredEntries) {
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

      if (filteredEntries.length > 0) {
        import('./chat-render.js').then(m => { if (m.renderAttachmentChips) m.renderAttachmentChips(); });
      }
      return;
    }

    // 4. 回退：dataTransfer.files（无 items 时）— 图片作为普通 File 上传，非图片作为 @file: 引用
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      e.stopPropagation();
      const files = filterOutUnsupported(Array.from(e.dataTransfer.files));
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

  // 不支持的类型（视频 / 旧版 .doc / .rtf）：拒绝引用
  if (isUnsupportedFile(fileName)) {
    showToast(`暂不支持 ${fileName}（视频 / 旧版 .doc / .rtf）`);
    return;
  }

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

  // 不支持的类型（视频 / 旧版 .doc / .rtf）：拒绝引用
  if (isUnsupportedFile(name)) {
    showToast(`暂不支持 ${name}（视频 / 旧版 .doc / .rtf）`);
    return;
  }

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

// ===== 清除状态 =====
export function clearEditState() {
  _externalChanges = {};
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
  const hasInput = trimmed || state.pendingFiles.length > 0 || state.pendingRefs.length > 0;
  if (!hasInput) return;

  // 文档/文件夹引用（@file:/@folder:）由 sendChat 统一拼接为文本发送，
  // 此处无需再注入 textInput，避免 chat/edit 双份引用
  try {
    const { sendChat } = await import('./send.js');
    await sendChat();
  } catch (err) {
    throw err;
  } finally {
    // 无论成功失败都清除引用 chip，防止重复注入
    clearRefChips();
  }
}

// ===== 初始化 =====
export function initEditMode() {
  // git 状态刷新事件（回撤/右栏打开/文件操作后触发）
  window.addEventListener("git-status-changed", () => refreshGitStatus());

  // 顶栏"定时任务"按钮：cron ↔ chat 切换（Edit 模式点击同样进入 cron）
  modeCronToggleBtn?.addEventListener("click", () => {
    if (state.mode !== "cron") switchToMode("cron");
    else switchToMode("chat");
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
}
