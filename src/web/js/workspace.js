// workspace.js -- 工作空间选择器
// 工作空间列表统一从后端 workspace_config.json 读写，不再使用 localStorage

import { $, showToast } from './utils.js';
import { showConfirm } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';

let _dropdownOpen = false;
let _addingWorkspace = false;

/** 初始化工作空间数据 */
export async function initWorkspace() {
  // 从后端加载当前选中的工作空间和默认值（列表也由后端 workspace_config.json 提供）
  try {
    const data = await api("/api/workspace");
    state.workspacePath = data.current || "";
    state.workspaceDefault = data.default || "";
    state.workspaceList = data.list || [];
    state.forbiddenWorkspaces = data.forbidden || [];
  } catch { /* ignore */ }
  // 顶栏工作区 chip 跟随当前会话：会话归属工作区优先（含启动时的会话）
  const sessWs = (state.sessionWorkspaces || {})[state.sessionId];
  if (sessWs) state.workspacePath = sessWs;
  updateWsBtnState();
  updateTopBarWorkspace();
  // 启动时 bootstrap 先于本函数渲染会话列表，彼时 workspaceList 尚为空，
  // 列表会退化为无卡片平铺；加载完成后通知重渲染以按工作区分组。
  window.dispatchEvent(new CustomEvent("workspaces-changed"));
}

/** 更新顶栏工作区 chip（选中工作区后显示：文件夹图标 + 名称） */
export function updateTopBarWorkspace() {
  const chip = $("mainHeaderWs");
  if (!chip) return;
  const nameEl = $("mainHeaderWsName");
  if (!state.workspacePath) {
    chip.hidden = true;
    syncComposerStartState();
    return;
  }
  const parts = state.workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/);
  if (nameEl) nameEl.textContent = parts[parts.length - 1] || state.workspacePath;
  chip.title = state.workspacePath;
  chip.hidden = false;
  syncComposerStartState();
}

/** 同步"选择工作区开始对话"引导态：
    无工作区或无任何会话时，输入框内出现可悬停的虚线遮罩（点击选择工作区）。 */
export function syncComposerStartState() {
  const composer = document.querySelector(".composer");
  const overlay = $("composerEmptyOverlay");
  if (!composer) return;
  const showPlus = !state.workspacePath || state.sessions.length === 0;
  composer.classList.toggle("composer--no-workspace", showPlus);
  if (overlay) overlay.hidden = !showPlus;
}

/** 更新按钮激活状态 */
function updateWsBtnState() {
  const btn = $("wsBtn");
  if (!btn) return;
  if (state.workspacePath) {
    btn.classList.add("is-active");
    const parts = state.workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/);
    btn.title = state.workspacePath;
    btn.setAttribute("aria-label", `工作空间: ${parts[parts.length - 1]}`);
  } else {
    btn.classList.remove("is-active");
    btn.title = "选择工作空间（当前使用默认）";
    btn.setAttribute("aria-label", "选择工作空间");
  }
}

/** 切换下拉框 */
function toggleDropdown() {
  if (_dropdownOpen) {
    closeDropdown();
  } else {
    openDropdown();
  }
}

/** 打开下拉框 */
async function openDropdown() {
  const dd = $("wsDropdown");
  if (!dd) return;
  // 刷新：从后端获取最新当前选中和列表
  try {
    const data = await api("/api/workspace");
    state.workspacePath = data.current || "";
    state.workspaceDefault = data.default || "";
    state.workspaceList = data.list || [];
    state.forbiddenWorkspaces = data.forbidden || [];
  } catch { /* ignore */ }
  // 欢迎区（居中态）向下展开，否则向上展开
  const composer = document.querySelector(".composer");
  if (composer && composer.classList.contains("composer--centered")) {
    dd.classList.add("ws-dropdown--down");
  } else {
    dd.classList.remove("ws-dropdown--down");
  }
  renderDropdown();
  dd.hidden = false;
  _dropdownOpen = true;
  updateWsBtnState();
  setTimeout(() => {
    document.addEventListener("click", onOutsideClick, { once: true });
  }, 0);
}

/** 关闭下拉框 */
function closeDropdown() {
  const dd = $("wsDropdown");
  if (dd) dd.hidden = true;
  _dropdownOpen = false;
  document.removeEventListener("click", onOutsideClick);
}

function onOutsideClick(e) {
  const wrap = $("wsBtnWrap");
  if (wrap && !wrap.contains(e.target)) {
    closeDropdown();
  } else {
    setTimeout(() => {
      document.addEventListener("click", onOutsideClick, { once: true });
    }, 0);
  }
}

/** 渲染下拉列表 */
function renderDropdown() {
  const list = $("wsDropdownList");
  if (!list) return;

  list.innerHTML = "";

  // 判断当前选中是否就是默认工作空间（path 为空 或 path 与默认路径一致）
  const defaultPath = (state.workspaceDefault || "").replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase();
  const currentNorm = (state.workspacePath || "").replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase();
  const isUsingDefault = !state.workspacePath || currentNorm === defaultPath;

  // 默认项
  const defaultItem = document.createElement("div");
  defaultItem.className = "ws-dropdown-item ws-dropdown-item--default" +
    (isUsingDefault ? " is-selected" : "");
  defaultItem.innerHTML = `
    <img src="/image/文件夹.svg" alt="" class="ws-dropdown-item-icon" />
    <span class="ws-dropdown-item-name">默认工作空间</span>
  `;
  defaultItem.title = state.workspaceDefault || "使用 env_config.json 中配置的默认工作空间";
  defaultItem.addEventListener("click", () => selectWorkspace(""));
  list.appendChild(defaultItem);

  // 最近打开文件夹（过滤掉与默认工作空间重复的条目）
  const folders = state.workspaceList;
  const filtered = folders.filter((fp) => {
    const norm = (fp || "").replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase();
    return norm !== defaultPath;
  });
  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "ws-dropdown-item";
    empty.style.cssText = "color:#94a3b8;font-size:0.78rem;cursor:default;";
    empty.textContent = "暂无最近文件夹";
    list.appendChild(empty);
  } else {
    filtered.forEach((fp) => {
      const parts = fp.replace(/[\\/]+$/, "").split(/[\\/]/);
      const name = parts[parts.length - 1] || fp;

      const item = document.createElement("div");
      item.className = "ws-dropdown-item" +
        (fp === state.workspacePath ? " is-selected" : "");
      item.title = fp;

      const icon = document.createElement("img");
      icon.src = "/image/文件夹.svg";
      icon.alt = "";
      icon.className = "ws-dropdown-item-icon";

      const span = document.createElement("span");
      span.className = "ws-dropdown-item-name";
      span.textContent = name;

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "ws-dropdown-item-delete";
      delBtn.title = "从列表移除";
      delBtn.innerHTML = '<img src="/image/删除.svg" alt="删除" />';
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        removeWorkspace(fp);
      });

      item.appendChild(icon);
      item.appendChild(span);
      item.appendChild(delBtn);
      item.addEventListener("click", () => selectWorkspace(fp));
      list.appendChild(item);
    });
  }
}

/** 该工作区下无会话时自动新增一个（仅在"添加工作区"完成后调用） */
async function ensureSessionForWorkspace(path) {
  if (!path) return;
  try {
    const has = Object.values(state.sessionWorkspaces || {}).some((ws) => ws === path);
    if (has) return;
    const { newSession } = await import('./sessions.js');
    await newSession(path);
  } catch { /* ignore */ }
}

/** 选择工作空间（仅切换工作区/打开文件树，不自动新建会话） */
export async function selectWorkspace(path) {
  try {
    const data = await api("/api/workspace/select", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    state.workspacePath = data.current || "";
    updateWsBtnState();
    updateTopBarWorkspace();
    closeDropdown();
    window.dispatchEvent(new CustomEvent("workspaces-changed"));
    // 自动切换到 Edit 模式并打开该文件夹
    // 选中具体路径时直接用该路径，选中"默认工作空间"时用 default
    const targetPath = path || state.workspaceDefault;
    if (targetPath) {
      try {
        const { switchToMode, openFolder } = await import('./edit-mode.js');
        switchToMode("edit");
        await openFolder(targetPath);
      } catch { /* ignore */ }
    }
  } catch (e) {
    showToast(e.message || String(e));
  }
}

/** 添加工作空间（打开系统文件夹选择器）—— 输入区加号"选择工作区开始对话"也走此流程 */
export async function addWorkspace() {
  if (_addingWorkspace) return;
  _addingWorkspace = true;
  try {
    let folderPath = "";
    try {
      const { pickFolder } = await import('./electron-api.js');
      folderPath = await pickFolder();
    } catch {
      // 非 Electron 环境或调用失败，回退到手动输入
    }
    if (!folderPath) {
      folderPath = prompt("请输入工作空间的绝对路径：", "");
    }
    if (!folderPath) return;
    folderPath = folderPath.trim();
    if (!folderPath) return;

    // 添加到后端 workspace_config.json
    try {
      const data = await api("/api/workspace/add", {
        method: "POST",
        body: JSON.stringify({ path: folderPath }),
      });
      state.workspaceList = data.list || [];
    } catch (e) {
      showToast(e.message || String(e));
    }

    // 自动选中
    await selectWorkspace(folderPath);

    // 仅"添加工作区"流程在添加完成后新建会话，以便立即在该工作区开始对话；
    // 普通切换工作区不自动建会话
    await ensureSessionForWorkspace(folderPath);

    // 重新渲染下拉列表
    renderDropdown();
  } finally {
    _addingWorkspace = false;
  }
}

/** 从列表移除工作空间（级联删除该工作区下的所有会话） */
export async function removeWorkspace(path) {
  if (!path) return;
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/);
  const name = parts[parts.length - 1] || path;
  const memberCount = state.sessions.filter((sid) => (state.sessionWorkspaces || {})[sid] === path).length;
  const hint = memberCount > 0 ? `该工作区下有 ${memberCount} 个会话，将一并删除。` : "";
  if (!await showConfirm(`确认移除工作区「${name}」吗？${hint}（不会删除文件夹本身）`)) return;

  // 服务端移除工作区并级联删除其下所有会话，返回最新会话列表与回退会话
  try {
    const data = await api("/api/workspace/remove", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    state.workspaceList = data.list || [];
    state.workspacePath = data.current || "";
    // 当前会话被级联删除：切换到服务端返回的回退会话（无剩余会话则为空引导态）
    if (state.sessionId && !(data.sessions || []).includes(state.sessionId)) {
      const { applySessionData } = await import('./sessions.js');
      await applySessionData(data);
      return;
    }
    // 当前会话仍存在：仅同步会话列表（被删会话消失）并重渲染
    state.sessions.length = 0;
    state.sessions.push(...(data.sessions || []));
    if (data.session_workspaces) state.sessionWorkspaces = data.session_workspaces;
  } catch (e) {
    showToast(e.message || String(e));
  }

  renderDropdown();
  updateWsBtnState();
  updateTopBarWorkspace();
  window.dispatchEvent(new CustomEvent("workspaces-changed"));
}

/** 绑定事件 */
export function bindWorkspaceEvents() {
  // 侧栏品牌区：新增工作区按钮（系统文件夹选择器）
  const brandNewWsBtn = $("brandNewWorkspaceBtn");
  if (brandNewWsBtn) {
    brandNewWsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      addWorkspace();
    });
  }

  // 顶栏工作区 chip：文件夹图标→资源管理器打开；名称→打开文件树
  const wsIcon = $("mainHeaderWsIcon");
  if (wsIcon) {
    wsIcon.addEventListener("click", (e) => {
      e.stopPropagation();
      const target = state.workspacePath || state.workspaceDefault;
      if (!target) return;
      if (window.electronAPI?.openInExplorer) {
        window.electronAPI.openInExplorer(target);
      } else {
        showToast("非桌面环境，无法打开资源管理器");
      }
    });
  }
  const wsNameEl = $("mainHeaderWsName");
  if (wsNameEl) {
    wsNameEl.addEventListener("click", async () => {
      const target = state.workspacePath || state.workspaceDefault;
      if (!target) return;
      try {
        const { switchToMode, openFolder } = await import('./edit-mode.js');
        switchToMode("edit");
        await openFolder(target);
      } catch { /* ignore */ }
    });
  }
}
