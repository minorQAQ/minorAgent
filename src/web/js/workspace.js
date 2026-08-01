// workspace.js -- 工作空间选择器
// 工作空间列表统一从后端 workspace_config.json 读写，不再使用 localStorage

import { $, showToast } from './utils.js';
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
    // 设置快照存储基础目录
    if (data.snapshots_base) {
      try {
        const { setSnapBaseDir } = await import('./edit-mode.js');
        setSnapBaseDir(data.snapshots_base);
      } catch {}
    }
  } catch { /* ignore */ }
  updateWsBtnState();
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

/** 选择工作空间 */
async function selectWorkspace(path) {
  try {
    const data = await api("/api/workspace/select", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    state.workspacePath = data.current || "";
    updateWsBtnState();
    closeDropdown();
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

/** 添加工作空间（打开系统文件夹选择器） */
async function addWorkspace() {
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

    // 重新渲染下拉列表
    renderDropdown();
  } finally {
    _addingWorkspace = false;
  }
}

/** 从列表移除工作空间 */
async function removeWorkspace(path) {
  try {
    const data = await api("/api/workspace/remove", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    state.workspaceList = data.list || [];
    state.workspacePath = data.current || "";
  } catch (e) {
    showToast(e.message || String(e));
  }

  renderDropdown();
  updateWsBtnState();
}

/** 绑定事件 */
export function bindWorkspaceEvents() {
  const wsBtn = $("wsBtn");
  const wsAddBtn = $("wsAddBtn");

  if (wsBtn) {
    wsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleDropdown();
    });
  }

  if (wsAddBtn) {
    wsAddBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      addWorkspace();
    });
  }
}
