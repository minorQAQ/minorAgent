// rollback.js -- 统一回撤机制
// Chat 模式回撤：清空 todolist / 人机交互，回滚历史，恢复输入区，清理本地 JSON 记录，docSnapshots 回退

import { $, showToast } from './utils.js';
import { showConfirm } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';
import { clearPendingOverlay } from './pending-overlay.js';

// 依赖注入
let renderMessagesFn = null;
let renderSessionsFn = null;
let renderAttachmentChipsFn = null;
let clearTodoOverlayFn = null;
let undoDocSnapshotFn = null;
let getDocSnapshotsFn = null;
let saveDocSnapshotFn = null;
let setDocContentFn = null;
let getDocContentFn = null;
let renderDocTreeFn = null;
let renderDocTabsFn = null;
let loadDocContentFn = null;
let setComposerCenteredFn = null;

export function setRollbackDeps(deps) {
  renderMessagesFn = deps.renderMessages;
  renderSessionsFn = deps.renderSessions;
  renderAttachmentChipsFn = deps.renderAttachmentChips;
  clearTodoOverlayFn = deps.clearTodoOverlay;
  undoDocSnapshotFn = deps.undoDocSnapshot;
  getDocSnapshotsFn = deps.getDocSnapshots;
  saveDocSnapshotFn = deps.saveDocSnapshot;
  setDocContentFn = deps.setDocContent;
  getDocContentFn = deps.getDocContent;
  renderDocTreeFn = deps.renderDocTree;
  renderDocTabsFn = deps.renderDocTabs;
  loadDocContentFn = deps.loadDocContent;
  setComposerCenteredFn = deps.setComposerCentered;
}

// ============================================================
// Chat 模式回撤
// ============================================================

/**
 * 将聊天历史回撤到指定消息处
 * @param {number} rollbackIndex - 要回退到的消息在渲染列表中的索引（包含该消息）
 */
export async function rollbackChat(rollbackIndex) {
  // 保护：Agent 运行中不允许回撤
  if (state.sending) {
    showToast("Agent 运行中，无法回撤。请先暂停任务。");
    return;
  }
  if (!state.sessionId) {
    showToast("无当前会话");
    return;
  }

  const confirmed = await showConfirm(
    "确认回退到此消息？\n\n将清除此消息之后的所有对话历史、TodoList、人机交互内容、工具调用记录。"
  );
  if (!confirmed) return;

  try {
    // 1. 调用后端回撤 API
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    fd.append("rollback_index", rollbackIndex);
    const data = await api("/api/chat/rollback-to-message", { method: "POST", body: fd });

    // 2. 更新会话状态
    state.sessionId = data.sessionId;
    state.sessions.length = 0;
    state.sessions.push(...(data.sessions || []));

    // 3. 清除 TodoList 和 人机交互 浮窗
    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();

    // 4. 回撤文件修改（通过 docSnapshots）
    await rollbackDocSnapshots();

    // 5. 刷新视图
    if (renderSessionsFn) renderSessionsFn();
    if (renderMessagesFn) renderMessagesFn(data.messages || []);

    // 6. 恢复回撤点用户消息到输入区
    const rollbackMsg = data.rollbackMessage;
    if (rollbackMsg && rollbackMsg.role === "user") {
      restoreUserInput(rollbackMsg);
    }

    showToast("已回退到该消息");
  } catch (e) {
    showToast("回退失败: " + (e.message || "未知错误"));
  }
}

/**
 * 回退 docSnapshots，恢复到文件修改前的状态
 */
async function rollbackDocSnapshots() {
  if (!undoDocSnapshotFn || !getDocSnapshotsFn) return;
  // 如果不在 edit 模式或没有打开文件夹，跳过
  if (!state.editMode || !state._docRootPath) return;

  const snapshotsCount = (getDocSnapshotsFn() || []).length;
  if (snapshotsCount === 0) return;

  // 撤销所有待处理的快照
  let undone = 0;
  const maxUndo = snapshotsCount;
  while (undone < maxUndo && (getDocSnapshotsFn() || []).length > 0) {
    undoDocSnapshotFn();
    undone++;
  }
}

/**
 * 将回撤点的用户消息内容恢复到输入区
 */
function restoreUserInput(msg) {
  const textInput = $("textInput");
  if (!textInput) return;

  // 恢复文本
  if (typeof msg.content === "string") {
    textInput.value = msg.content;
  } else if (Array.isArray(msg.content)) {
    const textParts = msg.content
      .filter((p) => p && p.type === "text")
      .map((p) => p.text || "")
      .join("\n");
    textInput.value = textParts;
  }

  textInput.focus();
}
