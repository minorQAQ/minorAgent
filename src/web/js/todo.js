// todo.js -- Todo List（通知条版）
//
// 原浮窗实现已迁移至 notify-strip.js：
// todo 数据从 live snapshot 的 tool_calls 派生（todo_list 工具调用），
// 以输入区上方通知条形式展示（最新步骤 + 计数 chip，可展开完整列表）。
// 本文件保留导出签名以兼容既有依赖注入（setLiveUiDeps / clearTodoOverlay）。

import {
  updateTodoStrip,
  clearTodoStrip,
  saveStripSession,
} from './notify-strip.js';

/** 从 live 工具调用记录派生 Todo 通知条数据。
 * @param {Array} toolCalls - live snapshot 的 tool_calls 数组 */
function updateTodoOverlayFromRecords(toolCalls) {
  updateTodoStrip(toolCalls);
}

/** 清空 todo 通知条（仅 todo，不影响人机交互条）。 */
function clearTodoOverlay() {
  saveStripSession();
  clearTodoStrip();
}

/** 兼容旧接口：通知条模式下无需构建独立 overlay。 */
function buildTodoListOverlay() {
  return null;
}

function updateTodoOverlay() {
  // 通知条由 updateTodoStrip 驱动，此接口保留为空实现以兼容旧调用点
}

export { buildTodoListOverlay, updateTodoOverlay, updateTodoOverlayFromRecords, clearTodoOverlay };
