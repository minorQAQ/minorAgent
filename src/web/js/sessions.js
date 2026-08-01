// sessions.js -- 会话管理（支持重命名、按项删除）

import { $ } from './utils.js';
import { showConfirm, showPrompt } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';
import { updatePendingOverlay, clearPendingOverlay } from './pending-overlay.js';
import { refreshTokens } from './token-bar.js';

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

// ---------- 渲染 ----------
export function renderSessions() {
  if (!sessionList) return;
  sessionList.innerHTML = "";
  state.sessions.forEach((id) => {
    const displayName = getSessionDisplayName(id);
    const isActive = id === state.sessionId;

    const li = document.createElement("li");
    li.className = "session-item" + (isActive ? " active" : "");
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", isActive ? "true" : "false");

    // 名称区域（点击切换会话）
    const nameSpan = document.createElement("span");
    nameSpan.className = "session-item-name";
    nameSpan.textContent = displayName;
    nameSpan.title = `ID: ${id}`;
    nameSpan.addEventListener("click", (e) => {
      e.stopPropagation();
      selectSession(id);
    });

    // 操作图标区域（hover 显示）
    const actionsDiv = document.createElement("span");
    actionsDiv.className = "session-item-actions";

    // 编辑图标
    const editBtn = document.createElement("button");
    editBtn.className = "session-item-action-btn";
    editBtn.title = "重命名";
    editBtn.innerHTML = '<img src="/image/编辑.svg" alt="编辑" width="16" height="16" />';
    editBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      renameSession(id);
    });

    // 删除图标
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
    sessionList.appendChild(li);
  });
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
    if (renderMessagesFn) renderMessagesFn(data.messages || []);
    // 清理当前会话的 UI 状态
    state.pendingFiles.length = 0;
    if (fileInput) fileInput.value = "";
    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();
    if (renderAttachmentChipsFn) renderAttachmentChipsFn();
    updatePendingOverlay(data.pending_actions || null);
  }
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []).filter((sid) => sid !== deletingSessionId));

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

// ---------- 启动 ----------
export async function bootstrap() {
  const data = await api("/api/bootstrap");
  state.sessionId = data.sessionId;
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  state.currentTokens = data.tokens || 0;
  if (renderSessionsFnRef) renderSessionsFnRef();
  if (renderMessagesFn) renderMessagesFn(data.messages);
  updatePendingOverlay(data.pending_actions || null);
  // 设置居中状态
  const msgs = data.messages || [];
  import('../app.js').then((m) => m.setComposerCentered(msgs.length === 0));
}

async function selectSession(id) {
  if (!id || id === state.sessionId) return;
  if (state.sending) return;  // Agent 运行中禁止切换会话
  const data = await api(`/api/sessions/${encodeURIComponent(id)}/messages`);
  state.sessionId = data.sessionId;
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  state.currentTokens = data.tokens || 0;
  if (clearTodoOverlayFn) clearTodoOverlayFn();
  clearPendingOverlay();
  if (renderSessionsFnRef) renderSessionsFnRef();
  if (renderMessagesFn) renderMessagesFn(data.messages);
  updatePendingOverlay(data.pending_actions || null);
  refreshTokens();
  // 设置居中状态
  const msgs = data.messages || [];
  import('../app.js').then((m) => m.setComposerCentered(msgs.length === 0));
  const _ar = $("app");
  if (_ar && _ar.classList.contains("is-mobile")) _ar.classList.remove("drawer-open");
}

let _creatingSession = false;

async function newSession() {
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
  if (cm) { cm.innerHTML = ""; cm.hidden = true; cm.style.display = "none"; }
  if (cp) { cp.hidden = false; }

  const data = await api("/api/sessions/new", { method: "POST" });
  state.sessionId = data.sessionId;
  state.sessions.length = 0;
  state.sessions.push(...(data.sessions || []));
  state.currentTokens = 0;
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
