// pending.js -- 人工请求决策提交（卡片渲染在 pending-overlay.js，数据源为 live snapshot）

import { $ } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

/**
 * 提交一个等待中的人工请求的决策。
 *
 * 阻塞式交互模型下，本函数只负责把答案交给后端：
 * 后端写入等待注册表并唤醒阻塞中的工具，图在后台线程自然继续；
 * 浮窗由下一次 live snapshot 自动移除，最终结果由
 * /api/chat/complete 或 /api/chat/stream 返回——无需重渲染消息、
 * 无需重启 live 流、更不会清空已积累的工具调用列表。
 */
async function handleHumanAction(requestId, decision, instruction, card) {
  if (!requestId || state.sending) return;
  state.sending = true;  // 本轮仍在后台运行，保持发送按钮禁用
  const sendBtn = $("sendBtn");
  if (sendBtn) sendBtn.disabled = true;
  if (card) card.classList.add("pending-action-card--resolved");

  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("approval_id", requestId);
  fd.append("decision", decision);
  fd.append("instruction", instruction || "");

  await api("/api/human-action", { method: "POST", body: fd });
  // 注意：不恢复 state.sending——本轮任务尚未结束，按钮状态由 sendChat 完成时统一恢复
}

export {
  handleHumanAction,
};
