// action-bar.js -- 操作按钮栏（兼容层）
//
// 原实现：composer 内静态 todo/pending 按钮 + 徽章，互斥 toggle 浮窗。
// 现已迁移：todo/人机交互改为输入区上方通知条（notify-strip.js），
// 按钮由通知条左侧按钮点击后动态生成于输入区，浮窗已移除。
// 本文件保留导出签名（initActionBar / deactivateAllActionPanels / setActionBadge）
// 为空实现，避免既有 import 报错；后续可安全移除对它的引用。

/** 原按钮已不存在于静态 DOM，无需绑定事件。回调保留签名以兼容调用方。 */
export function initActionBar(callbacks = {}) {
  // no-op
}

/** 原互斥面板概念已废弃（通知条各自独立显隐）。 */
export function deactivateAllActionPanels() {
  // no-op
}

/** 徽章机制已由通知条自身的计数 chip 取代。 */
export function setActionBadge(name, show) {
  // no-op
}
