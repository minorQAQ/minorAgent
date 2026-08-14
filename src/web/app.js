// app.js -- 主入口：导入所有模块，绑定 DOM 事件
// ES 模块重构版：原单文件 3800+ 行已拆分为 js/ 目录下各司其职的小模块

import { $, escapeHtml, inferUploadKind, buildOptimisticUserContent, revokeBlobUrlStack, showToast, dedupePendingFiles } from './js/utils.js';
import { api } from './js/api.js';
import { state } from './js/state.js';

// ---- 音频 / 麦克风 ----
import { toggleMicRecording } from './js/audio.js';
import { setRenderAttachmentChips as audioSetRenderChips } from './js/audio.js';

// ---- 聊天渲染 ----
import {
  renderMessages, renderMessage, renderAttachmentChips, scrollChatToBottom,
  appendThinkingIndicator, streamAssistantMessage,
  renderAudioBubble, addTextQuote, initChatQuoteMenu,
} from './js/chat-render.js';
import { setRenderPersistentToolCalls } from './js/chat-render.js';

// ---- 工具调用 / think ----
import { injectLiveToolCalls, setLiveUiDeps } from './js/toolcalls.js';
import { setRenderAudioBubble as toolcallsSetAudioBubble } from './js/toolcalls.js';

// ---- 人工确认浮窗 ----
import { updatePendingOverlay, clearPendingOverlay } from './js/pending-overlay.js';

// ---- 会话管理 ----
import { renderSessions, bootstrap } from './js/sessions.js';
import { setSessionDeps } from './js/sessions.js';

// ---- 发送消息 ----
import { sendChat, handlePauseClick } from './js/send.js';
import { setSendDeps } from './js/send.js';

// ---- Todo ----
import { updateTodoOverlayFromRecords, clearTodoOverlay } from './js/todo.js';

// ---- Token 活跃度卡 / 分时段标语 ----
import { initUsageCard, refreshUsageCard } from './js/usage-stats.js';
import { getSlogan } from './js/welcome-slogans.js';

// ---- 布局 / 背景 ----
import {
  setSidebarCollapsed, setDrawerOpen, closeDrawerIfMobile,
} from './js/layout.js';

// ---- 设置面板 ----
import { setRenderSkills } from './js/settings.js';

// ---- Skills ----
import { renderSkills, bindSkillEditorEvents, bindImportMenu } from './js/skills.js';

// ---- Edit 模式 ----
import { initEditMode, sendEditChat, switchToMode, acceptAllModifications, rejectAllModifications, getDocModifications, getCurrentTaskModifications, renderDocTabs, loadDocContent, setCronModeHooks } from './js/edit-mode.js';

// ---- Cron 定时任务模式 ----
import { initCronMode, enterCronMode, leaveCronMode, sendCronChat, abortCronTask, isCronRunning } from './js/cron.js';

// ---- 文件预览 ----
import { bindFilePreviewEvents, closeFilePreview } from './js/file-preview.js';

// ---- 操作图标按钮栏 ----
import { initActionBar, deactivateAllActionPanels, setActionBadge } from './js/action-bar.js';

// ---- 文档修改面板 ----
import { toggleDocModPanel, setDocModifications } from './js/doc-mod-panel.js';

// ---- 统一回撤 ----
import { rollbackChat, setRollbackDeps } from './js/rollback.js';
import { setRollbackChatFn } from './js/chat-render.js';

// ---- 文档快照 ----
import { saveDocSnapshot, undoDocSnapshot, getDocSnapshots, setDocContent, getDocContent, renderDocTree } from './js/doc-tree.js';

// ---- 主题 & 语言 ----
import { initTheme } from './js/themes.js';
import { initI18n } from './js/i18n.js';

// ---- Token 环形指示器（替代原进度条）----
import { initTokenRing, refreshTokens, stopTokenPolling } from './js/token-ring.js';

// ---- 工作空间 ----
import { initWorkspace, bindWorkspaceEvents } from './js/workspace.js';

// ---- 工作空间访问模式 ----
import { initAccessMode, bindAccessModeEvents } from './js/access-mode.js';

// ---- 思考模式档位 ----
import { initThinkLevel, bindThinkModeEvents } from './js/think-level.js';

// ===== 连线：注入跨模块依赖 =====
// toolcalls 的持久化渲染由 setRenderPersistentToolCalls 注入
import { renderPersistentToolCalls } from './js/toolcalls.js';
setRenderPersistentToolCalls(renderPersistentToolCalls);
toolcallsSetAudioBubble(renderAudioBubble);

// live snapshot 驱动人工确认浮窗与 Todo 浮窗（toolcalls 收到快照后回调）
setLiveUiDeps({
  updatePendingOverlay,
  updateTodoOverlayFromRecords,
});

// sessions 需要 renderMessages, renderAttachmentChips, clearTodoOverlay
setSessionDeps({
  renderMessages,
  renderAttachmentChips,
  clearTodoOverlay,
});

// send 需要 sessions/chat/todo/toolcalls 的函数
setSendDeps({
  renderSessions,
  renderMessages,
  renderAttachmentChips,
  appendThinkingIndicator,
  injectLiveToolCalls,
  clearTodoOverlay,
  streamAssistantMessage,
  onSendStart: () => setComposerCentered(false),
});

// audio 需要 renderAttachmentChips
audioSetRenderChips(renderAttachmentChips);

// settings 需要 renderSkills
setRenderSkills(renderSkills);

// chat-render 需要 rollbackChat 函数
setRollbackChatFn(rollbackChat);

// rollback 需要 UI 渲染函数
setRollbackDeps({
  renderMessages,
  renderSessions,
  renderAttachmentChips,
  clearTodoOverlay,
  undoDocSnapshot,
  getDocSnapshots,
  saveDocSnapshot,
  setDocContent,
  getDocContent,
  renderDocTree,
  renderDocTabs,
  loadDocContent,
  setComposerCentered,
});

// ===== Composer 居中/底部动画逻辑 =====
let _welcomeLeavingTimer = null;  // 欢迎区上滑退出的隐藏定时器（防竞态）

export function setComposerCentered(centered) {
  const composer = document.querySelector(".composer");
  const chatPlaceholder = document.getElementById("chatPlaceholder");
  const chatMessages = document.getElementById("chatMessages");
  const mainContentWrap = document.getElementById("mainContentWrap");
  const welcomeView = document.getElementById("welcomeView");
  if (!composer) return;

  if (centered) {
    if (_welcomeLeavingTimer) { clearTimeout(_welcomeLeavingTimer); _welcomeLeavingTimer = null; }
    composer.classList.add("composer--centered");
    composer.classList.remove("composer--bottom");
    if (chatPlaceholder) chatPlaceholder.style.display = "none";
    if (mainContentWrap) mainContentWrap.classList.add("main-content-wrap--collapsed");
    if (welcomeView) {
      welcomeView.hidden = false;
      welcomeView.classList.remove("welcome-view--leaving");
      // 强制 reflow 后加 --visible，确保从隐藏基态淡入（transition 生效）
      void welcomeView.offsetWidth;
      welcomeView.classList.add("welcome-view--visible");
      renderRecentFolders();
      startClock();
      // 分时段随机欢迎标语
      const sloganEl = document.getElementById("welcomeSlogan");
      if (sloganEl) sloganEl.textContent = getSlogan();
      // 刷新 Token 活跃度卡（矩阵/柱状图，保持当前视图）
      refreshUsageCard();
    }
  } else {
    composer.classList.remove("composer--centered");
    composer.classList.add("composer--bottom");
    if (chatPlaceholder) chatPlaceholder.style.display = "";
    if (mainContentWrap) mainContentWrap.classList.remove("main-content-wrap--collapsed");
    if (welcomeView) {
      // 欢迎区上滑淡出让位（而非瞬间隐藏导致整页重排、输入框跳动），动画结束后再隐藏
      if (!welcomeView.classList.contains("welcome-view--leaving")) {
        welcomeView.classList.remove("welcome-view--visible");
        welcomeView.classList.add("welcome-view--leaving");
        _welcomeLeavingTimer = setTimeout(() => {
          _welcomeLeavingTimer = null;
          welcomeView.hidden = true;
          welcomeView.classList.remove("welcome-view--leaving");
        }, 350);
      }
    }
    stopClock();
    if (chatMessages && chatMessages.children.length === 0) {
      if (chatPlaceholder) chatPlaceholder.hidden = false;
    }
  }
}

// ===== 最近文件夹（统一读写后端 workspace_config.json）=====

export async function addRecentFolder(folderPath) {
  if (!folderPath) return;
  try {
    const { api } = await import('./js/api.js');
    await api("/api/workspace/add", {
      method: "POST",
      body: JSON.stringify({ path: folderPath }),
    });
  } catch {}
}

async function renderRecentFolders() {
  const wrap = document.getElementById("recentFoldersWrap");
  const list = document.getElementById("recentFoldersList");
  if (!wrap || !list) return;
  try {
    const { api } = await import('./js/api.js');
    const data = await api("/api/workspace");
    const folders = data.list || [];
    if (folders.length === 0) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    list.innerHTML = "";
    folders.forEach((fp, i) => {
      const li = document.createElement("li");
      li.className = "recent-folder-item";
      li.title = fp;
      const icon = document.createElement("img");
      icon.src = "/image/文件夹.svg";
      icon.className = "recent-folder-icon";
      icon.alt = "";
      const name = document.createElement("span");
      name.className = "recent-folder-name";
      // 取最后一段路径名
      const parts = fp.replace(/[\\/]+$/, "").split(/[\\/]/);
      name.textContent = parts[parts.length - 1] || fp;
      li.appendChild(icon);
      li.appendChild(name);
      li.addEventListener("click", () => {
        openFolderFromRecent(fp);
      });
      // 重新触发动画
      li.style.animation = "none";
      void li.offsetWidth;
      li.style.animation = "";
      li.style.animationDelay = `${0.4 + i * 0.08}s`;
      list.appendChild(li);
    });
  } catch {
    wrap.hidden = true;
  }
}

function openFolderFromRecent(folderPath) {
  // 切换到 Edit 模式并打开文件夹
  const modeEditBtn = document.getElementById('modeEditBtn');
  // 切换模式
  import('./js/edit-mode.js').then((m) => {
    m.switchToMode("edit");
    // 打开文件夹
    if (m.openFolder) {
      m.openFolder(folderPath);
    }
  }).catch(() => {
    showToast("无法打开文件夹，可能已被删除");
  });
  // 取消居中
  setComposerCentered(false);
}

async function loadNickname() {
  const greeting = document.getElementById("welcomeGreeting");
  if (!greeting) return;
  try {
    const data = await api("/api/config/env");
    const env = data.env || {};
    const nickname = env.USER_NICKNAME || data.USER_NICKNAME || "";
    if (nickname) {
      greeting.textContent = `欢迎您，${nickname}`;
    }
  } catch {
    // keep default
  }
}

let _clockTimer = null;

function startClock() {
  const el = document.getElementById("welcomeClock");
  if (!el) return;
  tickClock(el);
  if (_clockTimer) clearInterval(_clockTimer);
  _clockTimer = setInterval(() => tickClock(el), 1000);
}

function stopClock() {
  if (_clockTimer) { clearInterval(_clockTimer); _clockTimer = null; }
}

function tickClock(el) {
  const now = new Date();
  const y = now.getFullYear();
  const mo = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  const h = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  const s = String(now.getSeconds()).padStart(2, "0");
  el.textContent = `${y}年${mo}月${d}日 ${h}:${mi}:${s}`;
}

async function populateModelSelect() {
  const trigger = $("modelTrigger");
  const panel = $("modelPanel");
  if (!trigger || !panel) return;
  try {
    const data = await api("/api/config/env");
    const models = data.models || [];
    const currentVal = state.selectedModelId;
    panel.innerHTML = "";
    let autoSelect = !currentVal && models.length > 0;
    models.forEach((m, idx) => {
      const item = document.createElement("div");
      item.className = "inline-drop-item";
      item.dataset.value = m.id;
      item.textContent = m.name || m.model || m.id;
      if (m.id === currentVal || (autoSelect && idx === 0)) {
        item.classList.add("is-selected");
        state.selectedModelId = m.id;
        trigger.textContent = m.name || m.model || m.id;
        trigger.dataset.value = m.id;
      }
      item.addEventListener("click", () => onModelChange(item, m.id));
      panel.appendChild(item);
    });
    if (!trigger.dataset.value && models.length > 0) {
      trigger.dataset.value = models[0].id;
      trigger.textContent = models[0].name || models[0].model || models[0].id;
    }
  } catch {
    // 静默失败
  }
}
export const refreshModelSelect = populateModelSelect;

async function onModelChange(item, modelId) {
  const panel = $("modelPanel");
  const trigger = $("modelTrigger");
  if (!panel || !trigger) return;

  // 更新选中态
  panel.querySelectorAll(".inline-drop-item").forEach(el => el.classList.remove("is-selected"));
  item.classList.add("is-selected");
  trigger.textContent = item.textContent;
  trigger.dataset.value = modelId;
  state.selectedModelId = modelId;
  closeAllDropdowns();

  // 同步更新所有 agent 的 llm_model_id
  try {
    const { api } = await import('./js/api.js');
    const agentRes = await api("/api/config/agents");
    const agents = (agentRes.agents || []).map((a) => ({ ...a, llm_model_id: modelId }));
    await api("/api/config/agents", { method: "POST", body: JSON.stringify({ agents }) });
    await api("/api/config/reload", { method: "POST", body: JSON.stringify({}) });
  } catch {
    // 静默失败
  }
}

// ===== 通用内联下拉框辅助 =====

/** 当前打开的下拉面板 */
let _openDropdownPanel = null;

/** 检测是否处于欢迎区居中态 */
function _isComposerCentered() {
  const composer = document.querySelector(".composer");
  return composer && composer.classList.contains("composer--centered");
}

/** 根据居中态设置下拉面板展开方向 */
function _setPanelDirection(panel) {
  if (_isComposerCentered()) {
    panel.classList.add("inline-drop-panel--down");
  } else {
    panel.classList.remove("inline-drop-panel--down");
  }
}

function closeAllDropdowns() {
  if (_openDropdownPanel) {
    _openDropdownPanel.hidden = true;
    const trigger = _openDropdownPanel._trigger;
    if (trigger) trigger.classList.remove("is-open");
    _openDropdownPanel._trigger = null;
    _openDropdownPanel = null;
  }
  document.removeEventListener("click", _onDropdownOutsideClick);
}

function _onDropdownOutsideClick(e) {
  if (_openDropdownPanel && !_openDropdownPanel.contains(e.target)) {
    const trigger = _openDropdownPanel._trigger;
    if (trigger && trigger.contains(e.target)) {
      // 点击了触发器本身，toggle 由 trigger 的 handler 处理
      setTimeout(() => document.addEventListener("click", _onDropdownOutsideClick, { once: true }), 0);
      return;
    }
    closeAllDropdowns();
  } else {
    setTimeout(() => document.addEventListener("click", _onDropdownOutsideClick, { once: true }), 0);
  }
}

/**
 * 设置内联下拉框
 * @param {string} triggerId - 触发器按钮 ID
 * @param {string} panelId - 下拉面板 ID
 * @param {function} onSelect - 选中回调 (value, itemEl)
 */
function setupInlineDropdown(triggerId, panelId, onSelect) {
  const trigger = $(triggerId);
  const panel = $(panelId);
  if (!trigger || !panel) return;

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (_openDropdownPanel === panel) {
      closeAllDropdowns();
      return;
    }
    closeAllDropdowns();
    _setPanelDirection(panel);
    panel.hidden = false;
    trigger.classList.add("is-open");
    panel._trigger = trigger;
    _openDropdownPanel = panel;
    setTimeout(() => {
      document.addEventListener("click", _onDropdownOutsideClick, { once: true });
    }, 0);
  });

  // 为已有选中项设置 trigger 文本
  const selected = panel.querySelector(".inline-drop-item.is-selected");
  if (selected) {
    trigger.textContent = selected.textContent;
    trigger.dataset.value = selected.dataset.value;
  }

  // 绑定选项点击
  panel.querySelectorAll(".inline-drop-item").forEach((item) => {
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      panel.querySelectorAll(".inline-drop-item").forEach(el => el.classList.remove("is-selected"));
      item.classList.add("is-selected");
      trigger.textContent = item.textContent;
      trigger.dataset.value = item.dataset.value;
      closeAllDropdowns();
      if (onSelect) onSelect(item.dataset.value, item);
    });
  });
}

// ===== DOM 事件绑定 =====
const menuBtn = $("menuBtn");
const collapseBtn = $("collapseBtn");
const expandBtn = $("expandBtn");
const drawerBackdrop = $("drawerBackdrop");
const sendBtn = $("sendBtn");
const micBtn = $("micBtn");
const newSessionBtn = $("newSessionBtn");
const deleteSessionBtn = $("deleteSessionBtn");
const textInput = $("textInput");
const fileInput = $("fileInput");
const appRoot = $("app");

// 文件上传监听
if (fileInput) {
  fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files || []);
    state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat(files));
    fileInput.value = "";
    renderAttachmentChips();
    if (textInput) textInput.focus();
  });
}

// 文件夹上传（右键附件按钮触发）
const folderInput = document.createElement("input");
folderInput.type = "file";
folderInput.webkitdirectory = true;
folderInput.multiple = true;
folderInput.hidden = true;
folderInput.style.display = "none";
document.body.appendChild(folderInput);
folderInput.addEventListener("change", () => {
  const files = Array.from(folderInput.files || []);
  if (files.length > 0) {
    const firstPath = files[0].webkitRelativePath || "";
    const folderName = firstPath.split("/")[0] || "文件夹";
    let newFiles = state.pendingFiles.slice();
    newFiles.push(new File([], folderName, { type: "folder/" }));
    newFiles = newFiles.concat(files);
    state.pendingFiles = dedupePendingFiles(newFiles);
    folderInput.value = "";
    renderAttachmentChips();
    if (textInput) textInput.focus();
  }
});

// 附件按钮右键 → 选择文件夹
const attachmentBtn = document.querySelector(".attachment-btn");
if (attachmentBtn) {
  attachmentBtn.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    folderInput.click();
  });
  attachmentBtn.title = "上传附件（左键选择文件，右键选择文件夹）";
}

// 输入区拖放文件/文件夹
function _setupComposerDrop() {
  const composer = document.querySelector(".composer");
  if (!composer) return;

  composer.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  });

  composer.addEventListener("dragenter", (e) => {
    e.preventDefault();
  });

  composer.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    // edit 模式内部文件拖拽（application/doc-path）由 edit-mode 处理，不重复添加
    if (e.dataTransfer.types.includes("application/doc-path")) return;

    // 聊天区选中文字拖拽 → 添加为引用（用户引用）
    if (e.dataTransfer.types.includes("application/x-chat-quote")) {
      const q = e.dataTransfer.getData("application/x-chat-quote");
      if (q && q.trim()) {
        addTextQuote(q.trim());
      }
      return;
    }

    // 聊天区图片拖拽：从自定义数据创建 File（避免浏览器生成的通用文件名）
    if (e.dataTransfer.types.includes("application/x-chat-image")) {
      const imgUrl = e.dataTransfer.getData("application/x-chat-image");
      const imgName = e.dataTransfer.getData("text/plain") || "图片";
      if (imgUrl) {
        try {
          const resp = await fetch(imgUrl);
          const blob = await resp.blob();
          const file = new File([blob], imgName, { type: blob.type || "image/png" });
          state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
          renderAttachmentChips();
          if (textInput) textInput.focus();
        } catch {
          // 回退：至少传递 URL 作为占位
        }
      }
      return;
    }

    // 聊天区文件拖拽：fetch URL 创建 File 对象
    if (e.dataTransfer.types.includes("application/x-chat-file")) {
      const fileUrl = e.dataTransfer.getData("application/x-chat-file");
      const fileName = e.dataTransfer.getData("text/plain") || "文件";
      if (fileUrl) {
        try {
          const resp = await fetch(fileUrl);
          const blob = await resp.blob();
          const file = new File([blob], fileName, { type: blob.type || "application/octet-stream" });
          state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat([file]));
          renderAttachmentChips();
          if (textInput) textInput.focus();
        } catch {
          // 静默失败
        }
      }
      return;
    }

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    const files = [];
    const folders = [];

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry && entry.isDirectory) {
        folders.push({ entry, name: entry.name });
      } else {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }

    // 递归读取文件夹内所有文件
    async function readDirEntries(dirEntry) {
      const reader = dirEntry.createReader();
      const entries = await new Promise((resolve) => {
        reader.readEntries((entries) => resolve(entries));
      });
      for (const entry of entries) {
        if (entry.isFile) {
          const file = await new Promise((resolve) => {
            entry.file((f) => resolve(f));
          });
          files.push(file);
        } else if (entry.isDirectory) {
          await readDirEntries(entry);
        }
      }
    }

    for (const folder of folders) {
      try {
        await readDirEntries(folder.entry);
      } catch {}
    }

    if (files.length > 0 || folders.length > 0) {
      // 文件夹用占位 File 对象表示（name 为文件夹名）
      folders.forEach((f) => {
        files.push(new File([], f.name, { type: "folder/" }));
      });
      state.pendingFiles = dedupePendingFiles(state.pendingFiles.concat(files));
      renderAttachmentChips();
      if (textInput) textInput.focus();
    }
  });
}
_setupComposerDrop();

// 离开页面清理
window.addEventListener("beforeunload", () => {
  if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
    try { state.mediaRecorder.stop(); } catch { /* ignore */ }
  }
});

// 回车发送
if (textInput) {
  textInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      if (state.mode === "cron") {
        sendCronChat().catch((e) => showToast(e.message || String(e)));
      } else if (state.editMode) {
        sendEditChat().catch((e) => showToast(e.message || String(e)));
      } else {
        sendChat();
        refreshTokens();
      }
    }
  });
}

// 发送按钮
if (sendBtn) {
  sendBtn.addEventListener("click", () => {
    // Cron 模式：运行中→终止，否则→追问发送
    if (state.mode === "cron") {
      if (isCronRunning()) {
        abortCronTask().catch((e) => showToast(e.message || String(e)));
      } else {
        sendCronChat().catch((e) => showToast(e.message || String(e)));
      }
      return;
    }
    if (state.sending) {
      handlePauseClick().catch((e) => showToast(e.message || String(e)));
    } else if (state._pendingHumanAction) {
      import('./js/pending-overlay.js').then((m) => m.clearPendingOverlay());
      state._pendingHumanAction = false;
      if (sendBtn) {
        sendBtn.classList.remove("btn-pause");
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<img src="/image/发送.svg" alt="" aria-hidden="true" class="send-btn-icon" />';
      }
    } else if (state.editMode) {
      sendEditChat().catch((e) => showToast(e.message || String(e)));
    } else {
      sendChat();
      refreshTokens();
    }
  });
}

// 麦克风按钮
if (micBtn) {
  micBtn.addEventListener("click", () => toggleMicRecording().catch((e) => showToast(e.message || String(e))));
}

// 工作空间选择器
bindWorkspaceEvents();

// 文件预览事件
bindFilePreviewEvents();

// 画板按钮：打开空白画板浮窗
const canvasBtn = $('actionCanvasBtn');
if (canvasBtn) {
  canvasBtn.addEventListener('click', () => {
    import('./js/canvas-editor.js').then(m => {
      m.openCanvasEditor({ mode: 'create', width: 1536, height: 768 });
    }).catch(err => showToast('画板加载失败: ' + (err.message || err)));
  });
}

// 操作图标按钮栏
initActionBar({
  onToggleTodo: (show) => {
    if (show) {
      // 直接查 DOM 显示，不依赖异步导入
      const el = (state._currentTodoOverlay && state._currentTodoOverlay.parentNode)
        ? state._currentTodoOverlay
        : document.querySelector(".todo-list-overlay");
      if (el) el.hidden = false;
    } else {
      clearTodoOverlay();
    }
  },
  onTogglePending: (show) => {
    if (show) {
      const el = (state._currentPendingOverlay && state._currentPendingOverlay.parentNode)
        ? state._currentPendingOverlay
        : document.querySelector(".pending-overlay");
      if (el) el.hidden = false;
      // 同步布局
      import('./js/pending-overlay.js').then(m => { if (m.updateOverlayLayout) m.updateOverlayLayout(); }).catch(() => {});
    } else {
      import('./js/pending-overlay.js').then(m => m.clearPendingOverlay());
    }
  },
  onToggleDoc: (show) => {
    const mods = getDocModifications();
    setDocModifications(mods);
    toggleDocModPanel(show);
  },
});

// 工作空间访问模式（图标触发器，document 委托，含连击保护）
bindAccessModeEvents();

// 思考模式档位（图标触发器 + 渐变色滑条，document 委托）
bindThinkModeEvents();

// 文字/语音回复开关（document 委托 + 连击保护）
// 默认文字模式；切换到语音模式前先检查 TTS 服务连通性，不通则提示并保持文字模式
let _voiceToggling = false;
let _lastVoiceToggleAt = 0;

document.addEventListener("click", (e) => {
  if (!e.target.closest || !e.target.closest("#voiceToggleBtn")) return;
  toggleOutputMode();
});

async function toggleOutputMode() {
  const now = Date.now();
  if (_voiceToggling || now - _lastVoiceToggleAt < 400) return;
  _lastVoiceToggleAt = now;
  _voiceToggling = true;
  try {
    const target = state.outputMode === "voice" ? "text" : "voice";
    if (target === "voice" && !(await checkTtsService())) {
      return; // TTS 不可用：提示并保持文字模式
    }
    state.outputMode = target;
    updateVoiceToggleUi();
  } finally {
    _voiceToggling = false;
  }
}

function updateVoiceToggleUi() {
  const btn = $("voiceToggleBtn");
  if (!btn) return;
  const isVoice = state.outputMode === "voice";
  btn.classList.toggle("is-active", isVoice);
  btn.setAttribute("aria-pressed", isVoice ? "true" : "false");
  btn.title = isVoice ? "语音回复（点击切换为文字）" : "文字回复（点击切换为语音）";
}

async function checkTtsService() {
  try {
    const st = await api("/api/services/status");
    if (st && st.tts && st.tts.ok) return true;
    showToast("语音（TTS）服务不可用，无法切换为语音模式");
  } catch {
    showToast("无法检测语音（TTS）服务状态");
  }
  return false;
}

// ===== 启动时检测 ASR / TTS 服务，决定麦克风与语音开关是否可用 =====
function applyServicesStatus(st) {
  const asrOk = !!(st && st.asr && st.asr.ok);
  const ttsOk = !!(st && st.tts && st.tts.ok);

  const mic = $("micBtn");
  if (mic) {
    mic.disabled = !asrOk;
    mic.title = asrOk ? "使用麦克风录音" : "语音转文字（ASR）服务不可用";
  }
  const voice = $("voiceToggleBtn");
  if (voice) {
    voice.disabled = !ttsOk;
    voice.title = ttsOk
      ? (state.outputMode === "voice" ? "语音回复（点击切换为文字）" : "文字回复（点击切换为语音）")
      : "语音（TTS）服务不可用";
    if (!ttsOk && state.outputMode === "voice") {
      // 启动时 TTS 不可用则回退为文字模式
      state.outputMode = "text";
      updateVoiceToggleUi();
    }
  }
}

async function initServicesStatus() {
  try {
    const st = await api("/api/services/status");
    applyServicesStatus(st);
  } catch {
    // 检测失败时不限制按钮，点击时仍有兜底检查
  }
}

// 模型选择在 populateModelSelect 中动态构建，只需绑定触发器
const modelTrigger = $("modelTrigger");
const modelPanel = $("modelPanel");
if (modelTrigger && modelPanel) {
  modelTrigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (_openDropdownPanel === modelPanel) {
      closeAllDropdowns();
      return;
    }
    closeAllDropdowns();
    _setPanelDirection(modelPanel);
    modelPanel.hidden = false;
    modelTrigger.classList.add("is-open");
    modelPanel._trigger = modelTrigger;
    _openDropdownPanel = modelPanel;
    setTimeout(() => {
      document.addEventListener("click", _onDropdownOutsideClick, { once: true });
    }, 0);
  });
}

// 新建会话按钮
if (newSessionBtn) {
  newSessionBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    handleNewSessionWithConfirm();
  });
}

async function handleNewSessionWithConfirm() {
  // Agent 运行中禁止新建会话
  if (state.sending) return;

  // 检查是否有未处理的文件变更
  let pendingMods = {};
  try {
    const { getDocModifications } = await import('./js/edit-mode.js');
    pendingMods = getDocModifications && getDocModifications() || {};
  } catch {}

  const entries = Object.values(pendingMods).filter(m => m.type !== 'original');
  if (entries.length > 0) {
    // 有未处理的变更，弹出确认弹窗
    showNewSessionConfirm(entries.length);
  } else {
    doNewSession();
  }
}

function showNewSessionConfirm(count) {
  const overlay = $('newSessionConfirm');
  const countEl = $('confirmPendingCount');
  if (!overlay) return;
  if (countEl) countEl.textContent = count;
  overlay.hidden = false;

  // 取消
  const cancelBtn = $('confirmCancel');
  cancelBtn.onclick = () => { overlay.hidden = true; };

  // 全部撤销并新建
  const rejectBtn = $('confirmRejectAll');
  rejectBtn.onclick = async () => {
    overlay.hidden = true;
    try {
      const { rejectFileModification, getDocModifications } = await import('./js/edit-mode.js');
      const mods = getDocModifications();
      for (const fp of Object.keys(mods)) {
        if (mods[fp].type !== 'original') await rejectFileModification(fp);
      }
      const { setDocModifications } = await import('./js/doc-mod-panel.js');
      setDocModifications({});
    } catch {}
    doNewSession();
  };

  // 全部接受并新建
  const acceptBtn = $('confirmAcceptAll');
  acceptBtn.onclick = async () => {
    overlay.hidden = true;
    try {
      const { acceptFileModification, getDocModifications } = await import('./js/edit-mode.js');
      const mods = getDocModifications();
      for (const fp of Object.keys(mods)) {
        if (mods[fp].type !== 'original') await acceptFileModification(fp);
      }
      const { setDocModifications } = await import('./js/doc-mod-panel.js');
      setDocModifications({});
    } catch {}
    doNewSession();
  };
}

async function doNewSession() {
  // 先清理编辑状态
  try {
    const editMode = await import('./js/edit-mode.js');
    if (editMode.clearEditState) editMode.clearEditState();
  } catch {}
  // 创建新会话
  try {
    const sessions = await import('./js/sessions.js');
    await sessions.newSession();
  } catch (e) {
    showToast(e.message || String(e));
  }
  // 重新打开当前选中的工作空间（恢复文件树）
  try {
    const editMode = await import('./js/edit-mode.js');
    await editMode.autoOpenWorkspace();
  } catch {}
}

// 侧栏展开/收起
if (collapseBtn) {
  collapseBtn.addEventListener("click", () => {
    if (appRoot && appRoot.classList.contains("is-mobile")) setDrawerOpen(false);
    else setSidebarCollapsed(true);
  });
}
if (expandBtn) {
  expandBtn.addEventListener("click", () => setSidebarCollapsed(false));
}

// 移动端菜单
if (menuBtn) {
  menuBtn.addEventListener("click", () => {
    if (appRoot) setDrawerOpen(!appRoot.classList.contains("drawer-open"));
  });
}
if (drawerBackdrop) {
  drawerBackdrop.addEventListener("click", () => setDrawerOpen(false));
}

// Skills 编辑器事件绑定
bindSkillEditorEvents();
bindImportMenu();

// Edit 模式初始化
initEditMode();

// 聊天区文字引用（左键选中 + 右键引用 / 拖拽到输入区）
initChatQuoteMenu();

// Cron 模式：注入进入/离开钩子，避免 edit-mode ↔ cron 循环依赖
setCronModeHooks({ onEnter: enterCronMode, onLeave: leaveCronMode });
// Cron 模式初始化（绑定列表/弹窗事件）
initCronMode();

// Cron 模式切换按钮
const modeCronBtn = $("modeCronBtn");
modeCronBtn?.addEventListener("click", () => {
  if (state.mode !== "cron") switchToMode("cron");
});

// 启动后自动打开工作空间
import('./js/edit-mode.js').then(m => m.autoOpenWorkspace()).catch(() => {});

// ===== 自定义标题栏按钮（仅 Electron） =====
if (window.electronAPI?.minimizeWindow) {
  const tbMin = $("tbMin"), tbMax = $("tbMax"), tbClose = $("tbClose"), tbSettings = $("tbSettings");
  tbMin?.addEventListener("click", () => window.electronAPI.minimizeWindow());
  tbMax?.addEventListener("click", () => window.electronAPI.maximizeWindow());
  tbClose?.addEventListener("click", () => window.electronAPI.closeWindow());
  tbSettings?.addEventListener("click", () => {
    document.getElementById("settingsBtn")?.click();
  });
  window.electronAPI.onMaximizeChanged((maximized) => {
    if (tbMax) tbMax.innerHTML = maximized ? '\uE923' : '\uE922';
  });
}

// 主题 & 语言初始化
initTheme();
initI18n();

// ===== 启动玻璃层过渡（毛玻璃 + 中央图标） =====
// 加载完成后：图标向下滑出、毛玻璃渐变消失，露出完整应用界面
function hideAppSplash() {
  const splash = document.getElementById("appSplash");
  if (!splash || splash.classList.contains("app-splash--out")) return;
  splash.classList.add("app-splash--out");
  // 动画结束后移除覆盖层（放行对底层界面的交互）
  setTimeout(() => {
    if (splash.parentNode) splash.parentNode.removeChild(splash);
  }, 800);
}

// ===== 启动 =====
bootstrap().then(() => {
  initTokenRing();
  initUsageCard();
  populateModelSelect();
  initWorkspace();
  initAccessMode();
  initThinkLevel();
  loadNickname();
  initServicesStatus();
  hideAppSplash();
}).catch((e) => {
  const chatPlaceholder = $("chatPlaceholder");
  if (chatPlaceholder) {
    chatPlaceholder.hidden = false;
    chatPlaceholder.innerHTML = `<h3>无法连接服务</h3><p>${escapeHtml(e.message)}</p><p class="muted">请从 Agent 目录执行：<code>uvicorn web.server:app --reload --host 127.0.0.1 --port 8765</code>，并保证 PYTHONPATH 包含 <code>src</code>。</p>`;
  }
  hideAppSplash();
});

// 兜底：若前端初始化异常导致 bootstrap 永不完成，超时后强制淡出玻璃层
setTimeout(hideAppSplash, 12000);
