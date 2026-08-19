// user-area.js -- 左栏底部用户区：头像 / 用户名 / 邮箱 + 设置按钮
// 头像持久化在 theme_config.json（themes.js 管理），本地路径经 /api/bg-image 代理显示。

import { $ } from './utils.js';
import { api } from './api.js';
import { getAvatar, applyAvatar, setAvatar } from './themes.js';

/** 读取用户信息并渲染用户区（昵称 / 邮箱 / 头像），绑定设置按钮与头像更换 */
export async function initUserArea() {
  const nameEl = $("userName");
  const emailEl = $("userEmail");
  try {
    const data = await api("/api/config/env");
    const env = data.env || {};
    const nickname = env.USER_NICKNAME || data.USER_NICKNAME || "";
    const email = env.EMAIL_ADDRESS || "";
    if (nameEl) nameEl.textContent = nickname || "未命名用户";
    if (emailEl) {
      emailEl.textContent = email || "";
      emailEl.hidden = !email;
    }
  } catch { /* 保留默认占位 */ }

  // 无头像时字母头像依赖昵称，渲染后再应用一次
  applyAvatar(getAvatar());

  // 左栏设置按钮由 settings.js 模块加载时统一绑定（打开系统配置面板）

  // 左栏头像点击：选择本地图片替换（高亮反馈由 CSS hover/active 提供）
  const avatarBtn = $("userAvatarBtn");
  if (avatarBtn) {
    avatarBtn.addEventListener("click", () => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.onchange = () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (window.electronAPI && window.electronAPI.getFilePath) {
          // Electron 环境：直接使用文件绝对路径（代理接口读取）
          const filePath = window.electronAPI.getFilePath(file);
          if (filePath) { setAvatar(filePath); return; }
        }
        // Web 环境：读取为 data URL
        const reader = new FileReader();
        reader.onload = (e) => setAvatar(e.target && e.target.result || "");
        reader.readAsDataURL(file);
      };
      input.click();
    });
  }
}
