// doc-tree.js -- 文档树组件（文件浏览/重命名/移动/复制粘贴/拖拽/删除/新增）

import { $, escapeHtml, showToast } from './utils.js';
import { showConfirm, showPrompt } from './dialog.js';
import { state } from './state.js';

// 支持的文件扩展名映射
const DOC_EXT_MAP = {
  ".txt": "plain_text", ".json": "plain_text", ".md": "plain_text", ".cpp": "plain_text",
  ".c": "plain_text", ".py": "plain_text", ".m": "plain_text", ".java": "plain_text", ".html": "plain_text",
  ".svg": "plain_text", ".css": "plain_text", ".js": "plain_text", ".ts": "plain_text",
  ".xml": "plain_text", ".yaml": "plain_text", ".yml": "plain_text", ".toml": "plain_text",
  ".docx": "docx", ".pptx": "pptx", ".pdf": "pdf", ".csv": "tabular", ".xlsx": "tabular", ".xls": "tabular",
};
const IMAGE_EXT = new Set([".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"]);

function getFileType(name) {
  const dot = (name || "").toLowerCase().lastIndexOf(".");
  if (dot < 0) return "plain_text";
  const e = name.toLowerCase().slice(dot);
  if (IMAGE_EXT.has(e)) return "image";
  return DOC_EXT_MAP[e] || "plain_text";
}

function getFileIcon(name) {
  const t = getFileType(name);
  const map = { plain_text: "\u{1F4C4}", docx: "\u{1F4D8}", pptx: "\u{1F4CA}", pdf: "\u{1F4D5}", tabular: "\u{1F4CA}", image: "\u{1F5BC}" };
  return map[t] || "\u{1F4C4}";
}

// ---- clipboard ----
let _clipboard = null; // { type: 'copy'|'cut', file: {...} }

// ---- 防重复引用 ----
let renderDocTabsFn = null;
let loadDocContentFn = null;
let showEmptyEditorFn = null;
let updateLineNumbersFn = null;
let openFilePreviewFn = null;
let openFileAsTextFn = null;
export function setDocTreeDeps(deps) {
  renderDocTabsFn = deps.renderDocTabs;
  loadDocContentFn = deps.loadDocContent;
  showEmptyEditorFn = deps.showEmptyEditor;
  updateLineNumbersFn = deps.updateLineNumbers;
  openFilePreviewFn = deps.openFilePreview;
  openFileAsTextFn = deps.openFileAsText;
}

const docTree = $("docTree");
let currentContextMenu = null;

function removeContextMenu() {
  if (currentContextMenu) { currentContextMenu.remove(); currentContextMenu = null; }
}

// ============ 渲染 ============

export function renderDocTree() {
  if (!docTree) return;
  docTree.innerHTML = "";
  removeContextMenu();
  if (!state.docFiles || !state.docFiles.length) {
    docTree.innerHTML = '<div class="doc-tree-empty">打开文件夹或拖入文件开始编辑</div>';
    return;
  }
  const root = buildHierarchy(state.docFiles);
  renderLevel(docTree, root, 0);

  // 右键空白处：新建文件/文件夹
  docTree.addEventListener("contextmenu", (e) => {
    // 只在点击空白区域（非文件/文件夹元素）时显示
    const target = e.target;
    if (target === docTree || target.classList.contains("doc-tree-empty")) {
      e.preventDefault();
      showBlankSpaceMenu(e.clientX, e.clientY);
    }
  });
}

function buildHierarchy(files) {
  const root = { children: {}, files: [] };
  files.forEach((f) => {
    const parts = f.path.replace(/\\/g, "/").split("/").filter(Boolean);
    let cur = root;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cur.children[parts[i]]) cur.children[parts[i]] = { children: {}, files: [] };
      cur = cur.children[parts[i]];
    }
    cur.files.push({ ...f, baseName: parts.length > 0 ? parts[parts.length - 1] : (f.name || f.path) });
  });
  // 如果设置了根文件夹名，将整棵树包裹在一个根节点下
  if (state._docRootName) {
    return { children: { [state._docRootName]: root }, files: [] };
  }
  return root;
}

function renderLevel(container, node, level, parentPath = '') {
  if (!state._docTreeFolders) state._docTreeFolders = {};

  // 文件夹
  Object.keys(node.children).sort((a, b) => a.localeCompare(b, void 0, { numeric: true })).forEach((name) => {
    // 计算文件夹完整相对路径（根文件夹路径为空字符串）
    const isRootFolder = (parentPath === '' && name === state._docRootName);
    const folderPath = isRootFolder ? '' : (parentPath ? parentPath + '/' + name : name);
    // 默认折叠：只有显式设为 true 才展开
    const expanded = state._docTreeFolders[name] === true;
    const div = document.createElement("div");
    div.className = "doc-tree-folder";
    div.style.setProperty("--level", level);
    div.setAttribute("data-folder", name);
    div.setAttribute("data-folder-path", folderPath);
    div.draggable = true;
    div.innerHTML = `<span class="doc-tree-icon">${expanded ? '\u{1F4C2}' : '\u{1F4C1}'}</span><span class="doc-tree-name">${escapeHtml(name)}</span>`;

    div.addEventListener("click", () => {
      state._docTreeFolders[name] = !state._docTreeFolders[name];
      renderDocTree();
    });
    div.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      showFolderMenu(e.clientX, e.clientY, name, div);
    });

    // 拖拽：文件夹可被拖拽到输入区（设置 doc-path + doc-folder 标记）
    div.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData('application/doc-path', folderPath);
      e.dataTransfer.setData('application/doc-folder', '1');
      e.dataTransfer.setData('text/plain', name);
      e.dataTransfer.effectAllowed = 'copy';
      div.classList.add("doc-tree-folder--dragging");
    });
    div.addEventListener("dragend", () => div.classList.remove("doc-tree-folder--dragging"));

    // 拖拽：文件夹作为目标（仅接收内部文件移入）
    div.addEventListener("dragover", (e) => {
      // 仅允许内部拖拽（application/doc-path），拒绝外部文件
      if (!Array.from(e.dataTransfer.types).includes('application/doc-path')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      div.classList.add("doc-tree-folder--drop-target");
    });
    div.addEventListener("dragleave", () => div.classList.remove("doc-tree-folder--drop-target"));
    div.addEventListener("drop", (e) => {
      e.preventDefault();
      div.classList.remove("doc-tree-folder--drop-target");
      const srcPath = e.dataTransfer.getData("application/doc-path");
      const isFolderDrag = e.dataTransfer.getData("application/doc-folder") === '1';
      if (srcPath && !isFolderDrag && !srcPath.startsWith(name + "/")) {
        moveFileIntoFolder(srcPath, name);
      }
    });

    container.appendChild(div);
    if (expanded) renderLevel(container, node.children[name], level + 1, folderPath);
  });

  // 文件
  node.files.sort((a, b) => a.baseName.localeCompare(b.baseName, void 0, { numeric: true })).forEach((f) => {
    const div = document.createElement("div");
    div.className = "doc-tree-file";
    div.style.setProperty("--level", level);
    div.setAttribute("data-path", f.path);
    // git 状态着色：untracked→绿(新增) / modified→橙 / deleted→橙+删除线
    const gState = state.gitStatus[f.path];
    div.draggable = gState !== "deleted";

    if (gState === "untracked") div.classList.add("doc-tree-file--new");
    else if (gState === "modified") div.classList.add("doc-tree-file--modified");
    else if (gState === "deleted") div.classList.add("doc-tree-file--deleted");
    if (state.activeDocFile === f.path) div.classList.add("doc-tree-file--active");

    const ft = getFileType(f.baseName);
    div.innerHTML = `<span class="doc-tree-icon doc-tree-icon--${ft}">${getFileIcon(f.baseName)}</span><span class="doc-tree-name">${escapeHtml(f.baseName)}</span>`;

    // ---- 拖拽：拖动文件 ----
    div.addEventListener("dragstart", (e) => {
      if (state.gitStatus[f.path] === "deleted") { e.preventDefault(); return; }
      e.dataTransfer.setData("application/doc-path", f.path);
      e.dataTransfer.setData("text/plain", f.path);
      e.dataTransfer.effectAllowed = "copyMove";
      div.classList.add("doc-tree-file--dragging");
    });
    div.addEventListener("dragend", () => div.classList.remove("doc-tree-file--dragging"));

    // ---- 拖拽：作为目标（仅接收内部文件移入） ----
    div.addEventListener("dragover", (e) => {
      // 仅允许内部拖拽（application/doc-path），拒绝外部文件
      if (!Array.from(e.dataTransfer.types).includes('application/doc-path')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      div.classList.add("doc-tree-file--drop-target");
    });
    div.addEventListener("dragleave", () => div.classList.remove("doc-tree-file--drop-target"));
    div.addEventListener("drop", (e) => {
      e.preventDefault();
      div.classList.remove("doc-tree-file--drop-target");
      const srcPath = e.dataTransfer.getData("application/doc-path");
      if (srcPath && srcPath !== f.path) {
        moveFileIntoFolder(srcPath, f.path);
      }
    });

    div.addEventListener("click", () => {
      if (state.gitStatus[f.path] === "deleted") return;
      // 外部删除的文件仍可打开查看（会显示 banner）
      openDocFile(f);
    });
    div.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      showFileMenu(e.clientX, e.clientY, f);
    });
    container.appendChild(div);
  });
}

// ============ 右键菜单 ============
function showFileMenu(x, y, file) {
  removeContextMenu();
  const menu = document.createElement("div");
  menu.className = "doc-context-menu";
  menu.style.left = x + "px";
  menu.style.top = y + "px";

  if (file.status === "deleted" || file.status === "externally_deleted") {
    addMenuItem(menu, "\u{21A9} 撤销删除", () => { undoDeleteFile(file.path); });
    addMenuItem(menu, "\u{1F5D1} 从工作区移除", () => { removeFileFromWorkspace(file.path); }, true);
  } else {
    addMenuItem(menu, "\u{270F} 重命名", () => { startRenameFile(file.path); });
    addMenuItem(menu, "\u{1F4CB} 复制", () => { _clipboard = { type: "copy", file: { ...file } }; showToast("已复制到剪贴板"); });
    addMenuItem(menu, "\u{2702} 剪切", () => { _clipboard = { type: "cut", file: { ...file } }; showToast("已剪切到剪贴板"); });
    if (_clipboard && _clipboard.file && _clipboard.file.path !== file.path) {
      addMenuItem(menu, "\u{1F4CE} 粘贴", () => { pasteFile(file.path); });
    }
    addMenuItem(menu, "\u{1F4C4} 复制副本", () => { duplicateFile(file.path); });
    // 引用
    addMenuItem(menu, "---", null);
    addMenuItem(menu, "\u{1F517} 引用", () => {
      import('./edit-mode.js').then(m => m.addDocRef(file.path)).catch(() => {});
    });
    // 文件属性
    addMenuItem(menu, "---", null);
    addMenuItem(menu, "\u{2139} 属性", () => { showFileProperties(file); });
    // HTML 右键：预览/文本编辑（SVG 已按普通文本文件处理，不再显示特殊菜单项）
    const isHtml = file.name.toLowerCase().endsWith(".html") || file.name.toLowerCase().endsWith(".htm");
    if (isHtml) {
      addMenuItem(menu, "---", null);
      addMenuItem(menu, "👁 预览", () => { openFilePreview(file.path); });
      addMenuItem(menu, "📝 文本编辑", () => { openFileAsText(file.path); });
    }
    addMenuItem(menu, "---", null);
    addMenuItem(menu, "\u{1F5D1} 删除", () => { markFileDeleted(file.path); }, true);
  }

  document.body.appendChild(menu);
  currentContextMenu = menu;
  bindMenuClose(menu);
}

function showFolderMenu(x, y, folderName, folderEl) {
  removeContextMenu();
  const menu = document.createElement("div");
  menu.className = "doc-context-menu";
  menu.style.left = x + "px";
  menu.style.top = y + "px";

  addMenuItem(menu, "\u{1F4C4} 新建文件", () => { createNewFileInFolder(folderName); });
  addMenuItem(menu, "\u{1F4C2} 新建子文件夹", () => { createNewFolderInFolder(folderName); });
  if (_clipboard && _clipboard.file) {
    addMenuItem(menu, "\u{1F4CE} 粘贴到此", () => { pasteIntoFolder(folderName); });
  }
  addMenuItem(menu, "---", null);
  addMenuItem(menu, "\u{270F} 重命名文件夹", () => { startRenameFolder(folderName); });
  addMenuItem(menu, "---", null);
  addMenuItem(menu, "\u{2139} 属性", () => { showFolderProperties(folderName); });
  addMenuItem(menu, "---", null);
  addMenuItem(menu, "\u{1F5D1} 删除文件夹", () => { deleteFolder(folderName); }, true);

  document.body.appendChild(menu);
  currentContextMenu = menu;
  bindMenuClose(menu);
}

function showBlankSpaceMenu(x, y) {
  removeContextMenu();
  const menu = document.createElement("div");
  menu.className = "doc-context-menu";
  menu.style.left = x + "px";
  menu.style.top = y + "px";

  addMenuItem(menu, "\u{1F4C4} 新建文件", () => { createNewRootFile(); });
  addMenuItem(menu, "\u{1F4C2} 新建文件夹", () => { createNewRootFolder(); });
  if (_clipboard && _clipboard.file) {
    addMenuItem(menu, "\u{1F4CE} 粘贴", () => { pasteFileAtRoot(); });
  }

  document.body.appendChild(menu);
  currentContextMenu = menu;
  bindMenuClose(menu);
}

function addMenuItem(menu, label, handler, danger) {
  if (label === "---") {
    const sep = document.createElement("div");
    sep.className = "doc-context-menu-sep";
    menu.appendChild(sep);
    return;
  }
  const item = document.createElement("div");
  item.className = "doc-context-menu-item" + (danger ? " doc-context-menu-item--danger" : "");
  item.textContent = label;
  if (handler) item.addEventListener("click", () => { handler(); removeContextMenu(); });
  menu.appendChild(item);
}

function bindMenuClose(menu) {
  const h = (e) => {
    if (!menu.contains(e.target)) { removeContextMenu(); document.removeEventListener("click", h); }
  };
  setTimeout(() => document.addEventListener("click", h), 0);
}

// ============ 文件操作 ============

/** 打开文档 */
function openDocFile(file) {
  if (!file || file.status === "deleted") return;
  state.activeDocFile = file.path;
  if (!state.docOpenTabs) state.docOpenTabs = [];
  if (!state.docOpenTabs.find((t) => t.path === file.path)) {
    state.docOpenTabs.push({ path: file.path, name: file.name || file.baseName, modified: file.status === "modified" });
  }
  state.activeDocTab = file.path;
  renderDocTree();
  if (renderDocTabsFn) renderDocTabsFn();
  if (loadDocContentFn) loadDocContentFn(file.path);
}

/** 关闭文档 */
function closeDocFile(filePath) {
  if (!state.docOpenTabs) return;
  state.docOpenTabs = state.docOpenTabs.filter((t) => t.path !== filePath);
  if (state.activeDocTab === filePath) state.activeDocTab = state.docOpenTabs[0]?.path || null;
  if (state.activeDocFile === filePath) state.activeDocFile = state.docOpenTabs[0]?.path || null;
  renderDocTree();
  if (renderDocTabsFn) renderDocTabsFn();
  state.activeDocFile ? (loadDocContentFn && loadDocContentFn(state.activeDocFile)) : (showEmptyEditorFn && showEmptyEditorFn());
}

/** 重命名文件（内联编辑） */
function startRenameFile(filePath) {
  const fileEl = docTree.querySelector(`.doc-tree-file[data-path="${CSS.escape(filePath)}"]`);
  if (!fileEl) return;
  const nameSpan = fileEl.querySelector(".doc-tree-name");
  const oldName = nameSpan.textContent;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "doc-tree-rename-input";
  input.value = oldName;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();

  const commit = () => {
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      const dir = filePath.replace(/[/\\][^/\\]*$/, "");
      const newPath = dir ? dir + "/" + newName : newName;
      renameDocFile(filePath, newPath, newName);
    }
    renderDocTree();
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.blur(); } if (e.key === "Escape") { input.value = oldName; input.blur(); } });
}

function startRenameFolder(folderName) {
  const folderEl = docTree.querySelector(`.doc-tree-folder[data-folder="${CSS.escape(folderName)}"]`);
  if (!folderEl) return;
  const nameSpan = folderEl.querySelector(".doc-tree-name");
  const oldName = nameSpan.textContent;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "doc-tree-rename-input";
  input.value = oldName;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();

  const commit = () => {
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      renameFolder(oldName, newName);
    }
    renderDocTree();
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.blur(); } if (e.key === "Escape") { input.value = oldName; input.blur(); } });
}

function renameDocFile(oldPath, newPath, newName) {
  const files = state.docFiles || [];
  const file = files.find((f) => f.path === oldPath);
  if (file) { file.path = newPath; file.name = newName; file.status = "modified"; }
  // 更新内容映射
  const oldContent = docContents[oldPath];
  if (oldContent !== undefined) { docContents[newPath] = oldContent; delete docContents[oldPath]; }
  // 更新标签页
  if (state.docOpenTabs) {
    const tab = state.docOpenTabs.find((t) => t.path === oldPath);
    if (tab) { tab.path = newPath; tab.name = newName; }
  }
  if (state.activeDocFile === oldPath) state.activeDocFile = newPath;
  if (state.activeDocTab === oldPath) state.activeDocTab = newPath;
}

function renameFolder(oldName, newName) {
  const files = state.docFiles || [];
  const prefix = oldName + "/";
  files.forEach((f) => {
    if (f.path.startsWith(prefix)) {
      const newPath = newName + "/" + f.path.slice(prefix.length);
      renameDocFile(f.path, newPath, f.name);
    }
  });
  // 更新 _docTreeFolders
  if (state._docTreeFolders && state._docTreeFolders[oldName] !== undefined) {
    state._docTreeFolders[newName] = state._docTreeFolders[oldName];
    delete state._docTreeFolders[oldName];
  }
}

/** 标记删除（仅标记，不删磁盘文件；撤销删除即可恢复） */
async function markFileDeleted(filePath) {
  const file = (state.docFiles || []).find((f) => f.path === filePath);
  if (file) file.status = "deleted";
  closeDocFile(filePath);
  // 不在此处删磁盘文件——撤销删除可恢复
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  if (renderDocTabsFn) renderDocTabsFn();
}

/** 撤销删除 */
function undoDeleteFile(filePath) {
  const file = (state.docFiles || []).find((f) => f.path === filePath);
  if (file) file.status = "original";  // 恢复为原始状态，而非 modified
  // 清除外部变更记录
  import('./edit-mode.js').then(m => {
    if (m.clearExternalChange) m.clearExternalChange(filePath);
  }).catch(() => {});
  renderDocTree();
}

/** 从工作区彻底移除（移入回收站） */
function removeFileFromWorkspace(filePath) {
  state.docFiles = (state.docFiles || []).filter((f) => f.path !== filePath);
  if (state.docOpenTabs) state.docOpenTabs = state.docOpenTabs.filter((t) => t.path !== filePath);
  if (state.activeDocFile === filePath) {
    state.activeDocFile = state.docOpenTabs?.[0]?.path || null;
    state.activeDocTab = state.activeDocFile;
  }
  // 实际删除磁盘文件（移入回收站）
  if (window.electronAPI && state._docRootPath) {
    import('./electron-api.js').then(m => m.deleteFile(filePath, state._docRootPath)).catch(() => {});
  }
  // 清除外部变更记录
  import('./edit-mode.js').then(m => {
    if (m.clearExternalChange) m.clearExternalChange(filePath);
  }).catch(() => {});
  // 工作区清空后显示打开按钮
  if (!state.docFiles || state.docFiles.length === 0) {
    import('./edit-mode.js').then(m => m.showOpenButtons());
  }
  renderDocTree();
  if (renderDocTabsFn) renderDocTabsFn();
}

/** 复制/剪切 → 粘贴 */
function pasteFile(targetPath) {
  if (!_clipboard || !_clipboard.file) return;
  const src = _clipboard.file;
  const dir = targetPath.replace(/[/\\][^/\\]*$/, "");
  const ext = src.baseName.includes(".") ? src.baseName.slice(src.baseName.lastIndexOf(".")) : "";
  const base = src.baseName.replace(ext, "");
  let newPath = dir ? dir + "/" + base + ext : base + ext;

  // 避免重名
  let counter = 1;
  while ((state.docFiles || []).find((f) => f.path === newPath)) {
    newPath = dir ? dir + "/" + base + "_" + counter + ext : base + "_" + counter + ext;
    counter++;
  }

  const content = docContents[src.path] || "";
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path: newPath, name: newPath.split(/[/\\]/).pop(), status: "new" });
  docContents[newPath] = content;

  if (_clipboard.type === "cut") {
    markFileDeleted(src.path);
    _clipboard = null;
  }

  renderDocTree();
  showToast("已粘贴");
}

function pasteIntoFolder(folderName) {
  if (!_clipboard || !_clipboard.file) return;
  const src = _clipboard.file;
  const newPath = folderName + "/" + src.baseName;
  const content = docContents[src.path] || "";
  if (!(state.docFiles || []).find((f) => f.path === newPath)) {
    state.docFiles = state.docFiles || [];
    state.docFiles.push({ path: newPath, name: src.baseName, status: "new" });
    docContents[newPath] = content;
  }
  if (_clipboard.type === "cut") { markFileDeleted(src.path); _clipboard = null; }
  renderDocTree();
  showToast("已粘贴");
}

/** 粘贴到根目录 */
function pasteFileAtRoot() {
  if (!_clipboard || !_clipboard.file) return;
  const src = _clipboard.file;
  const content = docContents[src.path] || "";
  let newPath = src.baseName;
  let counter = 1;
  while ((state.docFiles || []).find((f) => f.path === newPath)) {
    const ext = src.baseName.includes(".") ? src.baseName.slice(src.baseName.lastIndexOf(".")) : "";
    const base = src.baseName.replace(ext, "");
    newPath = base + "_" + counter + ext;
    counter++;
  }
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path: newPath, name: src.baseName, status: "new" });
  docContents[newPath] = content;
  if (_clipboard.type === "cut") { markFileDeleted(src.path); _clipboard = null; }
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  showToast("已粘贴");
}

// ===== 快捷键操作（供 edit-mode.js 调用） =====

/** Ctrl+C：复制当前选中的文件 */
export function copySelectedFile() {
  const fp = state.activeDocFile;
  if (!fp) return;
  const file = (state.docFiles || []).find(f => f.path === fp);
  if (!file || file.status === "deleted" || file.status === "externally_deleted") return;
  _clipboard = { file, type: "copy" };
  showToast(`已复制：${file.baseName || file.name}`);
}

/** Ctrl+X：剪切当前选中的文件 */
export function cutSelectedFile() {
  const fp = state.activeDocFile;
  if (!fp) return;
  const file = (state.docFiles || []).find(f => f.path === fp);
  if (!file || file.status === "deleted" || file.status === "externally_deleted") return;
  _clipboard = { file, type: "cut" };
  showToast(`已剪切：${file.baseName || file.name}`);
}

/** Ctrl+V：粘贴到选中文件所在目录或根目录 */
export function pasteToSelected() {
  if (!_clipboard || !_clipboard.file) return;
  const fp = state.activeDocFile;
  if (fp) {
    const file = (state.docFiles || []).find(f => f.path === fp);
    if (file) {
      // 粘贴到选中文件的父目录
      const parentDir = fp.replace(/[/\\][^/\\]*$/, "");
      if (parentDir) {
        pasteIntoFolder(parentDir);
      } else {
        pasteFileAtRoot();
      }
      return;
    }
  }
  pasteFileAtRoot();
}

/** F2：重命名当前选中的文件 */
export function renameSelectedFile() {
  const fp = state.activeDocFile;
  if (!fp) return;
  const file = (state.docFiles || []).find(f => f.path === fp);
  if (!file || file.status === "deleted") return;
  startRenameFile(fp);
}

/** 复制副本 */
function duplicateFile(filePath) {
  const file = (state.docFiles || []).find((f) => f.path === filePath);
  if (!file) return;
  const ext = file.baseName.includes(".") ? file.baseName.slice(file.baseName.lastIndexOf(".")) : "";
  const base = file.baseName.replace(ext, "");
  const dir = filePath.replace(/[/\\][^/\\]*$/, "");
  let newPath = dir ? dir + "/" + base + "_copy" + ext : base + "_copy" + ext;
  let counter = 1;
  while ((state.docFiles || []).find((f) => f.path === newPath)) {
    newPath = dir ? dir + "/" + base + "_copy" + counter + ext : base + "_copy" + counter + ext;
    counter++;
  }
  const content = docContents[filePath] || "";
  state.docFiles.push({ path: newPath, name: newPath.split(/[/\\]/).pop(), status: "new" });
  docContents[newPath] = content;
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  showToast("已创建副本");
}

/** 拖拽移动：将 srcPath 文件移入 targetPath 所在目录 */
function moveFileIntoFolder(srcPath, targetPath) {
  const srcFile = (state.docFiles || []).find((f) => f.path === srcPath);
  if (!srcFile) return;
  const targetDir = targetPath.replace(/[/\\][^/\\]*$/, "");
  const newPath = targetDir ? targetDir + "/" + srcFile.baseName : srcFile.baseName;
  if (newPath === srcPath) return;

  // 避免重名
  let finalPath = newPath;
  let counter = 1;
  while ((state.docFiles || []).find((f) => f.path === finalPath && f.path !== srcPath)) {
    const ext = srcFile.baseName.includes(".") ? srcFile.baseName.slice(srcFile.baseName.lastIndexOf(".")) : "";
    const base = srcFile.baseName.replace(ext, "");
    finalPath = targetDir ? targetDir + "/" + base + "_" + counter + ext : base + "_" + counter + ext;
    counter++;
  }

  renameDocFile(srcPath, finalPath, finalPath.split(/[/\\]/).pop());
  renderDocTree();
  if (renderDocTabsFn) renderDocTabsFn();
  showToast("文件已移动");
}

/** 新建文件 */
async function createNewFileInFolder(folderName) {
  const name = await showPrompt("输入新文件名：", "untitled.txt");
  if (!name) return;
  const path = folderName + "/" + name;
  if ((state.docFiles || []).find((f) => f.path === path)) { showToast("文件已存在"); return; }
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path, name, status: "new" });
  docContents[path] = "";
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  openDocFile({ path, name, status: "new", baseName: name });
}

async function createNewFolderInFolder(folderName) {
  const name = await showPrompt("输入新文件夹名：", "new_folder");
  if (!name) return;
  // 通过创建一个占位文件来建立文件夹
  const path = folderName + "/" + name + "/.gitkeep";
  if ((state.docFiles || []).find((f) => f.path.startsWith(folderName + "/" + name + "/"))) { showToast("文件夹已存在"); return; }
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path, name: ".gitkeep", status: "new" });
  docContents[path] = "";
  // 确保文件夹展开
  if (!state._docTreeFolders) state._docTreeFolders = {};
  state._docTreeFolders[name] = true;
  state._docTreeFolders[folderName] = true;
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  showToast("文件夹已创建");
}

async function deleteFolder(folderName) {
  if (!await showConfirm(`确认删除文件夹 "${folderName}" 及其所有内容？`)) return;
  const prefix = folderName + "/";
  const files = state.docFiles || [];
  files.forEach((f) => {
    if (f.path.startsWith(prefix) || f.path === folderName) {
      f.status = "deleted";
      closeDocFile(f.path);
    }
  });
  // 实际删除磁盘文件
  if (window.electronAPI && state._docRootPath) {
    try {
      const { deleteFile } = await import('./electron-api.js');
      await deleteFile(folderName, state._docRootPath);
    } catch {}
  }
  if (state._docTreeFolders) delete state._docTreeFolders[folderName];
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  if (renderDocTabsFn) renderDocTabsFn();
}

// ============ 内容管理 ============
let docContents = {};
let docOriginalContents = {};

export function setDocContent(filePath, content) {
  docContents[filePath] = content;
  if (!(filePath in docOriginalContents)) docOriginalContents[filePath] = content;
}
export function getDocContent(filePath) { return docContents[filePath] || ""; }

// ============ 新建根级文件/文件夹 ============
export async function createNewRootFile() {
  const name = await showPrompt("输入文件名：", "untitled.txt");
  if (!name) return;
  const path = name;
  if ((state.docFiles || []).find((f) => f.path === path)) { showToast("文件已存在"); return; }
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path, name, status: "new" });
  docContents[path] = "";
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  openDocFile({ path, name, status: "new", baseName: name });
}

export async function createNewRootFolder() {
  const name = await showPrompt("输入文件夹名：", "new_folder");
  if (!name) return;
  const placeholderPath = name + "/.gitkeep";
  if ((state.docFiles || []).find((f) => f.path.startsWith(name + "/"))) { showToast("文件夹已存在"); return; }
  state.docFiles = state.docFiles || [];
  state.docFiles.push({ path: placeholderPath, name: ".gitkeep", status: "new" });
  docContents[placeholderPath] = "";
  if (!state._docTreeFolders) state._docTreeFolders = {};
  state._docTreeFolders[name] = true;
  renderDocTree();
  window.dispatchEvent(new CustomEvent("git-status-changed"));
  showToast("文件夹已创建");
}

function openFilePreview(filePath) {
  if (openFilePreviewFn) openFilePreviewFn(filePath);
}

function openFileAsText(filePath) {
  if (openFileAsTextFn) openFileAsTextFn(filePath);
}

export { getFileType, getFileIcon, showFileProperties };

/** 弹出文件属性信息 */
async function showFileProperties(file) {
  if (!file) return;
  // 构造系统绝对路径
  let absPath = file.path;
  if (state._docRootPath) {
    const sep = state._docRootPath.includes("\\") ? "\\" : "/";
    absPath = state._docRootPath.replace(/\/$/, "").replace(/\\$/, "") + sep + file.path.replace(/\//g, sep);
  }

  let sizeStr = file.size != null ? formatSize(file.size) : "未知";
  let info = `文件：${file.name || file.baseName || file.path}\n\n`;
  info += `路径：${absPath}\n`;
  info += `大小：${sizeStr}\n`;
  info += `状态：${file.status || "original"}`;

  // 通过 Electron API 获取更多信息
  if (window.electronAPI && state._docRootPath) {
    try {
      const { statFile } = await import('./electron-api.js');
      // 使用系统分隔符构造绝对路径
      const sep = state._docRootPath.includes("\\") ? "\\" : "/";
      const sysPath = state._docRootPath.replace(/\/$/, "").replace(/\\$/, "") + sep + file.path.replace(/\//g, sep);
      const stat = await statFile(sysPath, null);
      if (stat && stat.exists) {
        const mtime = new Date(stat.mtime).toLocaleString();
        info += `\n修改时间：${mtime}`;
        if (stat.is_dir) info += `\n类型：文件夹`;
        else info += `\n类型：文件`;
      }
    } catch {}
  }

  const { showAlert } = await import('./dialog.js');
  await showAlert(info);
}

/** 弹出文件夹属性信息 */
async function showFolderProperties(folderName) {
  if (!folderName) return;
  let absPath = folderName;
  if (state._docRootPath) {
    const sep = state._docRootPath.includes("\\") ? "\\" : "/";
    absPath = state._docRootPath.replace(/\/$/, "").replace(/\\$/, "") + sep + folderName.replace(/\//g, sep);
  }

  let info = `文件夹：${folderName}\n\n`;
  info += `路径：${absPath}\n`;

  // 统计文件夹内文件数
  const prefix = folderName + "/";
  const fileCount = (state.docFiles || []).filter((f) => f.path.startsWith(prefix)).length;
  info += `包含文件：${fileCount} 个`;

  // 通过 Electron API 获取更多信息
  if (window.electronAPI && state._docRootPath) {
    try {
      const { statFile } = await import('./electron-api.js');
      const sep = state._docRootPath.includes("\\") ? "\\" : "/";
      const sysPath = state._docRootPath.replace(/\/$/, "").replace(/\\$/, "") + sep + folderName.replace(/\//g, sep);
      const stat = await statFile(sysPath, null);
      if (stat && stat.exists) {
        const mtime = new Date(stat.mtime).toLocaleString();
        info += `\n修改时间：${mtime}`;
        info += `\n类型：文件夹`;
      }
    } catch {}
  }

  const { showAlert } = await import('./dialog.js');
  await showAlert(info);
}

function formatSize(bytes) {
  if (bytes == null) return "未知";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(2) + " MB";
}

// ===== Delete 键快捷删除 =====
// 第一次按 Delete：标记为已删除（软删除，可撤销）
// 已经标记删除的文件再按 Delete：从工作区彻底移除（移入回收站）
document.addEventListener("keydown", function (e) {
  // 只在编辑模式下响应，且不在 input/textarea/contentEditable 中
  if (e.key !== "Delete" && e.key !== "Del") return;

  const tag = document.activeElement?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  if (document.activeElement?.isContentEditable) return;
  // 不在 Monaco 编辑器中
  if (document.activeElement?.closest(".monaco-editor")) return;

  const activeFile = state.activeDocFile;
  if (!activeFile) return;

  const file = (state.docFiles || []).find((f) => f.path === activeFile);
  if (!file) return;

  e.preventDefault();

  if (file.status === "deleted") {
    // 二次按 Delete：彻底移除
    removeFileFromWorkspace(activeFile);
    showToast("\u{1F5D1} 已从工作区移除: " + (file.name || activeFile));
  } else {
    // 第一次按 Delete：标记删除
    markFileDeleted(activeFile);
    showToast("\u{1F5D1} 已标记删除: " + (file.name || activeFile) + "  (右键移出工作区彻底移除)");
  }
});
