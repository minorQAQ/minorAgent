// rollback.js -- 统一回撤机制
// 回撤消息：后端删除后续 turn 并恢复会话所属工作区的 git 状态与文件，
// 前端刷新会话/消息/文件树，并把回撤点消息放回输入区。

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
 * @param {object} [options] - { skipConfirm: boolean } 跳过确认弹窗（重试等场景）
 */
export async function rollbackChat(rollbackIndex, options = {}) {
  // 保护：Agent 运行中不允许回撤
  if (state.sending) {
    showToast("Agent 运行中，无法回撤。请先暂停任务。");
    return false;
  }
  if (!state.sessionId) {
    showToast("无当前会话");
    return false;
  }

  if (!options.skipConfirm) {
    const confirmed = await showConfirm(
      "确认回退到此消息？\n\n将清除此消息之后的所有对话历史、TodoList、人机交互内容、工具调用记录；\n" +
      "若该会话关联工作区，文件系统与 git 状态也会恢复到该消息时的状态（之后的文件改动将被丢弃）。"
    );
    if (!confirmed) return false;
  }

  try {
    // 1. 调用后端回撤 API（含 git 状态与文件恢复）
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    fd.append("rollback_index", rollbackIndex);
    const data = await api("/api/chat/rollback-to-message", { method: "POST", body: fd });

    // 2. 更新会话状态
    state.sessionId = data.sessionId;
    state.sessions.length = 0;
    state.sessions.push(...(data.sessions || []));
    if (data.session_workspaces) state.sessionWorkspaces = data.session_workspaces;

    // 3. 清除 TodoList 和 人机交互 浮窗
    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();

    // 4. 文件已由后端 git 恢复：刷新文件树与打开的文件预览
    await refreshDocTreeAfterRollback();

    // 5. 刷新视图
    if (renderSessionsFn) renderSessionsFn();
    if (renderMessagesFn) renderMessagesFn(data.messages || []);

    // 6. 恢复回撤点用户消息到输入区
    const rollbackMsg = data.rollbackMessage;
    if (rollbackMsg && rollbackMsg.role === "user") {
      restoreUserInput(rollbackMsg);
    }

    showToast("已回退到该消息（文件与 git 状态已恢复）");
    return true;
  } catch (e) {
    showToast("回退失败: " + (e.message || "未知错误"));
    return false;
  }
}

/**
 * 回撤后刷新文件树与已打开文件（git 状态与文件内容由后端恢复）
 */
async function refreshDocTreeAfterRollback() {
  const rootPath = state._docRootPath;
  try {
    // 通知 doc-tree 重新拉取 git 状态并渲染
    window.dispatchEvent(new CustomEvent("git-status-changed"));
    if (renderDocTreeFn) renderDocTreeFn();
    if (renderDocTabsFn) renderDocTabsFn();
    // 重新加载当前打开的文件内容
    if (rootPath && loadDocContentFn && state.activeDocFile) {
      await loadDocContentFn(state.activeDocFile);
    }
  } catch { /* 文件树刷新失败不影响回撤主流程 */ }
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
