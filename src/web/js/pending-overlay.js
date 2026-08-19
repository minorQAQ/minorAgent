// pending-overlay.js -- 人机交互 / 工具审查（通知条版）
//
// 原浮窗实现已迁移至 notify-strip.js：
// 等待中的 human_requests 以输入区上方通知条展示（标题 + 计数 chip），
// 点击展开为卡片（人机交互：内容/选项/输入 + 继续/确认；审查：同意/拒绝），
// 多项时左右箭头切换。本文件保留导出签名以兼容既有调用点。

import {
  updatePendingStrip,
  clearPendingStrip,
  saveStripSession,
} from './notify-strip.js';

/** live snapshot 驱动入口：human_requests 数组出现即渲染，应答后随快照消失。 */
function updatePendingOverlay(pendingActions) {
  updatePendingStrip(pendingActions);
}

/** 清除当前会话的 pending 通知条（仅 pending，不影响 todo；先持久化到会话快照）。 */
function clearPendingOverlay() {
  saveStripSession();
  clearPendingStrip();
}

/** 兼容旧接口：通知条模式下无独立浮窗可切换。 */
function togglePendingOverlay() {}

/** 兼容旧接口：通知条模式下无双浮窗布局需要调整。 */
function updateOverlayLayout() {}

/** 兼容旧接口：通知条由 notify-strip 构建。 */
function buildPendingOverlay() {
  return null;
}

export {
  buildPendingOverlay,
  updatePendingOverlay,
  clearPendingOverlay,
  togglePendingOverlay,
  updateOverlayLayout,
};
