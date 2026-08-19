// pending.js -- 人工请求决策提交（卡片渲染在 pending-overlay.js，数据源为 live snapshot）

import { api } from './api.js';
import { state } from './state.js';

// 防重入：同一 approval_id 同时只允许一个提交请求（连点保护）
const _inFlight = new Set();

/**
 * 提交一个等待中的人工请求的决策。
 *
 * 阻塞式交互模型下，本函数只负责把答案交给后端：
 * 后端写入等待注册表并唤醒阻塞中的工具，图在后台线程自然继续；
 * 浮窗由下一次 live snapshot 自动移除，最终结果由
 * /api/chat/complete 或 /api/chat/stream 返回——无需重渲染消息、
 * 无需重启 live 流、更不会清空已积累的工具调用列表。
 *
 * 注意：Agent 运行期间 state.sending 恒为 true（本轮仍在后台执行），
 * 因此这里绝不能以 state.sending 作为拦截条件，否则浮窗按钮全部失效。
 *
 * @param {string} [sessionId] - 目标会话 ID。cron 模式传 task_id；
 *                               缺省时回退 state.sessionId（chat）。
 */
async function handleHumanAction(requestId, decision, instruction, card, sessionId) {
  if (!requestId || _inFlight.has(requestId)) return;
  _inFlight.add(requestId);
  try {
    const fd = new FormData();
    fd.append("session_id", sessionId || state.sessionId);
    fd.append("approval_id", requestId);
    fd.append("decision", decision);
    fd.append("instruction", instruction || "");
    await api("/api/human-action", { method: "POST", body: fd });
  } finally {
    _inFlight.delete(requestId);
  }
  // 注意：不修改 state.sending——本轮任务尚未结束，按钮状态由 sendChat 完成时统一恢复
}

export {
  handleHumanAction,
};
