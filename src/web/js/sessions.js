// sessions.js -- 会话管理（支持重命名、按项删除）

import { $, showToast } from './utils.js';
import { showConfirm, showPrompt } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';
import { clearPendingOverlay } from './pending-overlay.js';
import { refreshTokens } from './token-ring.js';

let renderSessionsFnRef = null;
let renderMessagesFn = null;
let renderAttachmentChipsFn = null;
let clearTodoOverlayFn = null;

export function setSessionDeps(deps) {
  renderSessionsFnRef = deps.renderSessions || renderSessions;
  renderMessagesFn = deps.renderMessages;
  renderAttachmentChipsFn = deps.renderAttachmentChips;
  clearTodoOverlayFn = deps.clearTodoOverlay;
}

const sessionList = $("sessionList");
const fileInput = $("fileInput");

// 已折叠的工作区路径集合（点击工作区卡片展开/折叠其会话列表）
const _collapsedWs = new Set();

// ---------- 会话显示名称（localStorage） ----------
const SESSION_NAMES_KEY = "minor_session_names";

function loadSessionNames() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_NAMES_KEY) || "{}");
  } catch { return {}; }
}

function saveSessionNames(names) {
  localStorage.setItem(SESSION_NAMES_KEY, JSON.stringify(names));
}

function getSessionDisplayName(id) {
  const names = loadSessionNames();
  return names[id] || id;
}

function setSessionDisplayName(id, name) {
  const names = loadSessionNames();
  if (name && name.trim() && name.trim() !== id) {
    names[id] = name.trim();
  } else {
    delete names[id];
  }
  saveSessionNames(names);
}

// ---------- 工作区分组 ----------
function wsBasename(path) {
  const parts = String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path || "默认工作空间";
}

/** 把会话列表按工作区归组：[{key, path, name, sessions:[...]}]。
    只渲染有会话的工作区卡片（无会话时不显示空卡片）；未归属/已移除工作区的会话
    直接置顶显示（无"默认工作区"卡片）。 */
function buildWorkspaceGroups() {
  const byWs = {};
  const unassigned = [];
  for (const id of state.sessions) {
    const ws = state.sessionWorkspaces[id] || "";
    if (!ws || !(state.workspaceList || []).includes(ws)) {
      unassigned.push(id); // 未归属或工作区已移除 → 置顶
    } else {
      (byWs[ws] = byWs[ws] || []).push(id);
    }
  }
  const groups = [];
  if (unassigned.length) {
    groups.push({ key: "__unassigned__", path: "", name: "", sessions: unassigned, plain: true });
  }
  for (const ws of state.workspaceList || []) {
    if (!(byWs[ws] || []).length) continue; // 空会话的工作区不渲染卡片
    groups.push({ key: ws, path: ws, name: wsBasename(ws), sessions: byWs[ws] });
  }
  return groups;
}

/** 顶栏工作区 chip 跟随当前会话：切换/新建/删除会话后，显示其所属工作区；
    并同步"选择工作区开始对话"引导态（无工作区或无会话时显示输入区加号）。 */
function syncWorkspaceChip() {
  const ws = (state.sessionWorkspaces || {})[state.sessionId];
  if (ws) {
    // 被禁止的目录（如桌面）不作为工作区：视为未归属会话，清空工作区 chip
    const norm = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
    if ((state.forbiddenWorkspaces || []).map(norm).includes(norm(ws))) {
      state.workspacePath = "";
    } else {
      state.workspacePath = ws;
    }
  }
  import('./workspace.js').then((m) => m.updateTopBarWorkspace()).catch(() => {});
  // 右栏文件树跟随会话工作区：右栏打开且根目录不是该工作区时，重新打开
  if (ws && state.workspacePath) {
    const appRoot = document.getElementById("app");
    const rightPanelOpen = appRoot && appRoot.classList.contains("right-panel-open");
    if (rightPanelOpen && state._docRootPath !== ws) {
      import('./edit-mode.js').then((m) => m.openFolder(ws)).catch(() => {});
    }
  }
}

/** 渲染单个会话项（工作区分组内使用） */
function renderSessionItem(id) {
  const displayName = getSessionDisplayName(id);
  const isActive = id === state.sessionId;

  const li = document.createElement("li");
  li.className = "session-item" + (isActive ? " active" : "");
  li.setAttribute("role", "option");
  li.setAttribute("aria-selected", isActive ? "true" : "false");

  // 会话图标（文档按钮样式，随主题着色）
  const icon = document.createElement("span");
  icon.className = "session-item-icon";
  li.appendChild(icon);

  const nameSpan = document.createElement("span");
  nameSpan.className = "session-item-name";
  nameSpan.textContent = displayName;
  nameSpan.title = `ID: ${id}`;
  nameSpan.addEventListener("click", (e) => {
    e.stopPropagation();
    selectSession(id);
  });

  const actionsDiv = document.createElement("span");
  actionsDiv.className = "session-item-actions";

  const editBtn = document.createElement("button");
  editBtn.className = "session-item-action-btn";
  editBtn.title = "重命名";
  editBtn.innerHTML = '<img src="/image/编辑.svg" alt="编辑" width="16" height="16" />';
  editBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    renameSession(id);
  });

  const delBtn = document.createElement("button");
  delBtn.className = "session-item-action-btn danger";
  delBtn.title = "删除";
  delBtn.innerHTML = '<img src="/image/删除.svg" alt="删除" width="16" height="16" />';
  delBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteSessionItem(id);
  });

  actionsDiv.appendChild(editBtn);
  actionsDiv.appendChild(delBtn);

  li.appendChild(nameSpan);
  li.appendChild(actionsDiv);
  return li;
}

// ---------- 渲染 ----------
export function renderSessions() {
  if (!sessionList) return;
  sessionList.innerHTML = "";
  const groups = buildWorkspaceGroups();

  for (const group of groups) {
    const groupLi = document.createElement("li");
    groupLi.className = "ws-group";

    // 未归属会话：置顶直接显示，无工作区卡片
    if (group.plain) {
      const inner = document.createElement("ul");
      inner.className = "ws-group-sessions ws-group-sessions--plain";
      group.sessions.forEach((id) => inner.appendChild(renderSessionItem(id)));
      groupLi.appendChild(inner);
      sessionList.appendChild(groupLi);
      continue;
    }

    // 工作区卡片：点击展开/折叠该工作区的会话列表；操作按钮 hover 时出现
    const card = document.createElement("div");
    card.className = "ws-card";
    card.title = group.path;

    // 资源管理器按钮：恒显于名称最左侧（不在 hover 隐藏的 actions 内）
    const explorerBtn = document.createElement("button");
    explorerBtn.type = "button";
    explorerBtn.className = "ws-card-explorer";
    explorerBtn.title = "在资源管理器中打开";
    explorerBtn.innerHTML = '<img src="/image/文件夹.svg" alt="打开" />';
    explorerBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (window.electronAPI?.openInExplorer) {
        window.electronAPI.openInExplorer(group.path);
      } else {
        showToast("非桌面环境，无法打开资源管理器");
      }
    });
    card.appendChild(explorerBtn);

    const nameSpan = document.createElement("span");
    nameSpan.className = "ws-card-name";
    nameSpan.textContent = group.name;
    nameSpan.title = group.path;
    card.appendChild(nameSpan);

    const actions = document.createElement("span");
    actions.className = "ws-card-actions";

    // 新增会话（归属该工作区）
    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "ws-card-action";
    newBtn.title = "新增会话";
    newBtn.innerHTML = '<img src="/image/新增会话.svg" alt="新增会话" />';
    newBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await newSession(group.path);
    });
    actions.appendChild(newBtn);

    // 从列表移除（删除按钮；确认弹窗与级联删除会话见 workspace.js removeWorkspace）
    const delWsBtn = document.createElement("button");
    delWsBtn.type = "button";
    delWsBtn.className = "ws-card-action";
    delWsBtn.title = "从列表移除";
    delWsBtn.innerHTML = '<img src="/image/删除.svg" alt="移除" />';
    delWsBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const m = await import('./workspace.js');
      await m.removeWorkspace(group.path);
    });
    actions.appendChild(delWsBtn);

    card.appendChild(actions);
    groupLi.appendChild(card);

    // 组内会话（缩进对齐卡片名称）；无会话时给出提示
    const inner = document.createElement("ul");
    inner.className = "ws-group-sessions";
    if (group.sessions.length === 0) {
      const empty = document.createElement("li");
      empty.className = "ws-group-empty";
      empty.textContent = "暂无会话";
      inner.appendChild(empty);
    } else {
      group.sessions.forEach((id) => inner.appendChild(renderSessionItem(id)));
      // 卡片点击：展开/折叠会话列表
      if (_collapsedWs.has(group.path)) {
        inner.hidden = true;
      }
      card.addEventListener("click", () => {
        const nowCollapsed = !_collapsedWs.has(group.path);
        if (nowCollapsed) {
          _collapsedWs.add(group.path);
        } else {
          _collapsedWs.delete(group.path);
        }
        inner.hidden = nowCollapsed;
      });
    }
    groupLi.appendChild(inner);

    sessionList.appendChild(groupLi);
  }
}

// ---------- 重命名 ----------
async function renameSession(id) {
  const currentName = getSessionDisplayName(id);
  const newName = await showPrompt("输入新名称（留空则恢复为 ID）", currentName === id ? "" : currentName);
  if (newName === null) return; // 用户取消

  setSessionDisplayName(id, newName);
  renderSessions();
}

// ---------- 按项删除 ----------
async function deleteSessionItem(id) {
  if (!id) return;
  const displayName = getSessionDisplayName(id);
  if (!await showConfirm(`确认删除会话「${displayName}」吗？该会话的所有记录和文件都将被永久删除。`)) return;

  const deletingSessionId = id;
  const fd = new FormData();
  fd.append("session_id", id);
  const data = await api("/api/sessions/delete", { method: "POST", body: fd });

  // 如果删除的是当前会话，切换到服务端返回的新会话
  if (id === state.sessionId) {
    state.sessionId = data.sessionId;
    applySessionThinkingLevel(data);
    if (renderMessagesFn) renderMessagesFn(data.messages || []);
    // 清理当前会话的 UI 状态
    state.pendingFiles.length = 0;
    if (fileInput) fileInput.value = "";
    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();
    if (renderAttachmentChipsFn) renderAttachmentChipsFn();
  }
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []).filter((sid) => sid !== deletingSessionId));
  if (data.session_workspaces) state.sessionWorkspaces = data.session_workspaces;
  syncWorkspaceChip();

  renderSessions();

  // 清理 localStorage 中的名称记录
  const names = loadSessionNames();
  if (names[deletingSessionId]) {
    delete names[deletingSessionId];
    saveSessionNames(names);
  }

  // close drawer on mobile
  const _ar4 = $("app");
  if (_ar4 && _ar4.classList.contains("is-mobile")) _ar4.classList.remove("drawer-open");
}

// ---------- 会话级思考档位同步 ----------
// 各会话独立保存 THINKING_LEVEL（session_meta.json），切换/新建/删除会话时
// 用服务端返回的 thinking_level 同步滑条 UI。
function applySessionThinkingLevel(data) {
  if (!data || !data.thinking_level) return;
  if (state.thinkingLevel === data.thinking_level) return;
  state.thinkingLevel = data.thinking_level;
  import('./think-level.js').then((m) => m.syncThinkLevelUI()).catch(() => {});
}

// ---------- 启动 ----------
// 工作区列表增删/切换后重渲染分组
window.addEventListener("workspaces-changed", () => renderSessions());

export async function bootstrap() {
  const data = await api("/api/bootstrap");
  state.sessionId = data.sessionId;
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  state.sessionWorkspaces = data.session_workspaces || {};
  state.currentTokens = data.tokens || 0;
  applySessionThinkingLevel(data);
  syncWorkspaceChip();
  if (renderSessionsFnRef) renderSessionsFnRef();
  if (renderMessagesFn) renderMessagesFn(data.messages);
  // 恢复会话级全局 todo 状态（启动时展示该会话已有的 todo 计划）
  try {
    const { restoreTodoFromMessages } = await import('./notify-strip.js');
    restoreTodoFromMessages(data.messages || []);
  } catch { /* ignore */ }
  // 设置居中状态
  const msgs = data.messages || [];
  import('../app.js').then((m) => m.setComposerCentered(msgs.length === 0));
}

async function selectSession(id) {
  if (!id || id === state.sessionId) return;
  if (state.sending) return;  // Agent 运行中禁止切换会话
  const data = await api(`/api/sessions/${encodeURIComponent(id)}/messages`);
  await applySessionData(data);
}

/**
 * 应用一次会话数据（sessionId / sessions / messages / tokens）并刷新界面。
 * 供「分支」等创建新会话后直接跳转使用。
 */
export async function applySessionData(data) {
  if (!data) return;
  // 记录旧会话键（切换前保存其通知条状态，避免被存到新键下）
  const oldSessionId = state.sessionId;
  // sessionId 为空表示无任何会话（工作区级联删除后）：渲染空引导态
  state.sessionId = data.sessionId || "";
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  if (data.session_workspaces) state.sessionWorkspaces = data.session_workspaces;
  state.currentTokens = data.tokens || 0;
  applySessionThinkingLevel(data);
  syncWorkspaceChip();
  // 通知条会话级切换：保存旧会话状态 → 恢复目标会话的 todo/pending
  try {
    const { switchStripSession, restoreTodoFromMessages } = await import('./notify-strip.js');
    switchStripSession("chat:" + (state.sessionId || ""), "chat:" + oldSessionId);
    // 从历史消息回溯会话级全局 todo 状态（跨轮次保持，重新加载后仍可见）
    restoreTodoFromMessages(data.messages || []);
  } catch { /* ignore */ }
  if (renderSessionsFnRef) renderSessionsFnRef();
  if (renderMessagesFn) renderMessagesFn(data.messages || []);
  refreshTokens();
  // 设置居中状态
  const msgs = data.messages || [];
  import('../app.js').then((m) => m.setComposerCentered(msgs.length === 0));
  const _ar = $("app");
  if (_ar && _ar.classList.contains("is-mobile")) _ar.classList.remove("drawer-open");
}

let _creatingSession = false;

async function newSession(workspace) {
  // 防止并发调用
  if (_creatingSession) return;
  if (state.sending) return;  // Agent 运行中禁止新建会话
  _creatingSession = true;
  try {
  // 中止正在执行的 Agent 任务，防止其回调覆盖新会话
  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }
  state.sending = false;
  // 重置发送按钮状态
  const sendBtn = document.getElementById("sendBtn");
  if (sendBtn) {
    sendBtn.classList.remove("btn-pause");
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<img src="/image/发送.svg" alt="" aria-hidden="true" class="send-btn-icon" />';
  }

  // 立即清空聊天区域并将 sessionId 置空，
  // 这样 sendChat 的 abort catch 中 state.sessionId !== sessionIdAtStart 必为 true，
  // 不会在 await 期间把旧消息重新渲染到已清空的聊天区
  state.lastRenderedMessages.length = 0;
  state.sessionId = "";
  const cm = document.getElementById("chatMessages");
  const cp = document.getElementById("chatPlaceholder");
  if (cm) {
    cm.innerHTML = ""; cm.hidden = true; cm.style.display = "none";
    // 同步增量渲染跟踪状态，避免硬清空后计数不一致
    cm._renderedMessages = null;
    cm._renderedCount = 0;
  }
  if (cp) { cp.hidden = false; }

  const fd = new FormData();
  if (workspace) fd.append("workspace", workspace);
  const data = await api("/api/sessions/new", { method: "POST", body: fd });
  state.sessionId = data.sessionId;
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  if (data.session_workspaces) state.sessionWorkspaces = data.session_workspaces;
  state.currentTokens = 0;
  applySessionThinkingLevel(data);
  syncWorkspaceChip();
  state.pendingFiles.length = 0;
  if (fileInput) fileInput.value = "";
  if (clearTodoOverlayFn) clearTodoOverlayFn();
  clearPendingOverlay();
  if (renderSessionsFnRef) renderSessionsFnRef();
  if (renderAttachmentChipsFn) renderAttachmentChipsFn();
  if (renderMessagesFn) renderMessagesFn(data.messages || []);
  // 新会话设为居中状态
  import('../app.js').then((m) => m.setComposerCentered(true));
  const _ar2 = $("app");
  if (_ar2 && _ar2.classList.contains("is-mobile")) _ar2.classList.remove("drawer-open");
  } finally {
    _creatingSession = false;
  }
}

// 保留旧 deleteSession() 兼容性（删除当前活跃会话）
async function deleteSession() {
  if (!state.sessionId) return;
  await deleteSessionItem(state.sessionId);
}

async function clearChat() {
  if (!state.sessionId) return;
  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  const data = await api("/api/sessions/clear", { method: "POST", body: fd });
  if (renderMessagesFn) renderMessagesFn(data.messages);
}

export { newSession, deleteSession, clearChat };
