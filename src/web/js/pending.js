// pending.js -- 待确认决策处理（卡片渲染已迁移至 pending-overlay.js）

import { $ } from './utils.js';
import { api } from './api.js';
import { startPollLiveToolCalls } from './toolcalls.js';
import { state } from './state.js';
import { updatePendingOverlay } from './pending-overlay.js';

let renderSessionsFn = null;
let appendThinkingIndicatorFn = null;
let renderMessagesFn = null;
let streamAssistantMessageFn = null;
let injectLiveToolCallsFn = null;
let scrollChatToBottomFn = null;

export function setRenderFnDeps(deps) {
  renderSessionsFn = deps.renderSessions;
  appendThinkingIndicatorFn = deps.appendThinkingIndicator;
  renderMessagesFn = deps.renderMessages;
  streamAssistantMessageFn = deps.streamAssistantMessage;
  injectLiveToolCallsFn = deps.injectLiveToolCalls;
  scrollChatToBottomFn = deps.scrollChatToBottom;
}

async function handleHumanAction(approvalId, decision, instruction, card) {
  if (!approvalId || state.sending) return;
  state.sending = true;
  const sendBtn = $("sendBtn");
  if (sendBtn) sendBtn.disabled = true;
  if (card) card.classList.add("pending-action-card--resolved");
  const outputModeTrigger = $("outputModeTrigger");

  // 复用 sendChat 留下的现有 thinking 气泡（不删除不重建）
  const chatMessages = $("chatMessages");
  let typingEl = chatMessages ? chatMessages.querySelector(".msg-typing") : null;
  if (!typingEl) {
    // 兜底：如果没有现有气泡（如页面刷新后），创建一个新的
    typingEl = appendThinkingIndicatorFn ? appendThinkingIndicatorFn() : null;
  }

  // 将 pending 工具调用标记为完成，带上用户输入的结果
  if (typingEl && injectLiveToolCallsFn) {
    const resultText = instruction
      || (decision === "reject" ? "用户拒绝" : decision === "skip" ? "用户已跳过" : "用户已确认");
    injectLiveToolCallsFn(typingEl, [{
      name: "human_interaction",
      status: "done",
      result_text: resultText,
    }]);
  }

  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("approval_id", approvalId);
  fd.append("decision", decision);
  fd.append("instruction", instruction || "");
  fd.append("output_type", outputModeTrigger ? (outputModeTrigger.dataset.value || "text") : "text");

  const stopToolPoll = startPollLiveToolCalls(state.sessionId, typingEl, injectLiveToolCallsFn);

  try {
    const done = await api("/api/human-action", { method: "POST", body: fd });
    stopToolPoll();
    // Update state
    state.sessionId = done.sessionId;
    state.sessions.length = 0;
    state.sessions.push(...(done.sessions || []));
    if (renderSessionsFn) renderSessionsFn();
    const messages = done.messages || [];
    const last = messages[messages.length - 1];
    const hasNewPending = done.pending_actions && done.pending_actions.length > 0;

    if (last && last.role === "assistant") {
      // 最终回复：移除 thinking 气泡，渲染 assistant
      if (typingEl && typingEl.parentNode) typingEl.remove();
      typingEl = null;
      if (renderMessagesFn) renderMessagesFn(messages.slice(0, -1));
      if (streamAssistantMessageFn) await streamAssistantMessageFn(last);
    } else if (hasNewPending) {
      // 又产生了 pending：保留 thinking 气泡，更新浮窗
      // typingEl 不删除，继续用于下一次交互
    } else {
      if (typingEl && typingEl.parentNode) typingEl.remove();
      typingEl = null;
      if (renderMessagesFn) renderMessagesFn(messages);
    }
    updatePendingOverlay(done.pending_actions);
    state._pendingHumanAction = hasNewPending;
  } finally {
    if (typingEl && typingEl.parentNode && !state._pendingHumanAction) {
      typingEl.remove();
    }
    state.sending = false;
    if (!state._pendingHumanAction) {
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<img src="/image/发送.svg" alt="" aria-hidden="true" class="send-btn-icon" />';
        sendBtn.classList.remove("btn-pause");
      }
    }
  }
}

export {
  handleHumanAction,
};
