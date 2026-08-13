// themes.js -- 主题管理系统（10 个预设 + CSS 变量注入）

import { api } from './api.js';

const DARK_SURFACE = {
  "--surface": "rgba(30,30,35,0.94)",
  "--surface-hover": "rgba(255,255,255,0.06)",
  "--bg-tertiary": "rgba(148,163,184,0.06)",
  "--text-tertiary": "#64748b",
  "--border": "rgba(148,163,184,0.15)",
  "--divider": "rgba(148,163,184,0.1)",
  "--overlay-bg": "rgba(8,8,16,0.55)",
  "--titlebar-bg": "#111118",
  "--shadow": "rgba(0,0,0,0.5)",
  "--scrollbar-thumb": "rgba(148,163,184,0.2)",
  "--scrollbar-track": "transparent",
  "--danger": "#ef4444",
  "--danger-hover": "#f87171",
  "--danger-bg": "rgba(239,68,68,0.12)",
  "--success": "#22c55e",
  "--success-bg": "rgba(34,197,94,0.12)",
  "--warning": "#f59e0b",
  "--warning-bg": "rgba(245,158,11,0.12)",
};

const LIGHT_SURFACE = {
  "--surface": "rgba(255,255,255,0.94)",
  "--surface-hover": "rgba(0,0,0,0.04)",
  "--bg-tertiary": "rgba(0,0,0,0.04)",
  "--text-tertiary": "#94a3b8",
  "--border": "rgba(0,0,0,0.1)",
  "--divider": "rgba(0,0,0,0.08)",
  "--overlay-bg": "rgba(0,0,0,0.18)",
  "--titlebar-bg": "#e8e8ec",
  "--shadow": "rgba(0,0,0,0.15)",
  "--scrollbar-thumb": "rgba(0,0,0,0.15)",
  "--scrollbar-track": "transparent",
  "--danger": "#dc2626",
  "--danger-hover": "#b91c1c",
  "--danger-bg": "rgba(220,38,38,0.08)",
  "--success": "#16a34a",
  "--success-bg": "rgba(22,163,74,0.08)",
  "--warning": "#ca8a04",
  "--warning-bg": "rgba(202,138,4,0.08)",
};

export const THEMES = {
  "vscode-dark": {
    name: "VS Code Dark",
    dark: true,
    root: {
      "--text": "#d4d4d4",
      "--muted": "#808080",
      "--accent": "#007acc",
      "--accent-hover": "#1a8ad4",
      "--bubble-user": "rgba(38,79,120,0.55)",
      "--bubble-assistant": "rgba(45,45,45,0.7)",
      "--bubble-audio-only": "rgba(45,45,45,0.3)",
      "--audio-accent": "#14b8a6",
      "--radius": "14px",
      "--bg-dof": "0px",
      "--bg-vignette": "0.55",
      ...DARK_SURFACE,
    },
    edit: {
      "--edit-bg": "#1e1e1e",
      "--edit-tab-bg": "#252526",
      "--edit-tab-active-bg": "#1e1e1e",
      "--edit-tab-border": "#3c3c3c",
      "--edit-text": "#d4d4d4",
      "--edit-line-num": "#858585",
      "--edit-line-num-bg": "#1e1e1e",
      "--edit-line-num-border": "#333333",
      "--edit-selection": "rgba(38,79,120,0.7)",
      "--edit-toolcall-bg": "#2d2d2d",
      "--edit-step-border": "#2d2d2d",
      "--edit-tree-text": "#d4d4d4",
      "--edit-tree-hover": "rgba(255,255,255,0.15)",
      "--edit-tab-text": "#969696",
      "--edit-tab-active-text": "#ffffff",
      "--edit-empty-text": "#6a6a6a",
      "--sidebar-bg": "transparent",
      "--sidebar-border": "rgba(148,163,184,0.35)",
      "--sidebar-text": "#d4d4d4",
    }
  },

  "vscode-light": {
    name: "VS Code Light",
    dark: false,
    root: {
      "--text": "#1e1e1e",
      "--muted": "#6e6e6e",
      "--accent": "#005fb8",
      "--accent-hover": "#0070d6",
      "--bubble-user": "rgba(0,95,184,0.12)",
      "--bubble-assistant": "rgba(255,255,255,0.8)",
      "--bubble-audio-only": "rgba(255,255,255,0.5)",
      "--audio-accent": "#0e7490",
      "--bg-dof": "0px",
      "--bg-vignette": "0.15",
      ...LIGHT_SURFACE,
    },
    edit: {
      "--edit-bg": "#ffffff",
      "--edit-tab-bg": "#f3f3f3",
      "--edit-tab-active-bg": "#ffffff",
      "--edit-tab-border": "#d4d4d4",
      "--edit-text": "#1e1e1e",
      "--edit-line-num": "#999999",
      "--edit-line-num-bg": "#ffffff",
      "--edit-line-num-border": "#e8e8e8",
      "--edit-selection": "rgba(0,95,184,0.25)",
      "--edit-toolcall-bg": "#f0f0f0",
      "--edit-step-border": "#e8e8e8",
      "--edit-tree-text": "#1e1e1e",
      "--edit-tree-hover": "rgba(0,0,0,0.06)",
      "--edit-tab-text": "#6e6e6e",
      "--edit-tab-active-text": "#1e1e1e",
      "--edit-empty-text": "#999999",
      "--sidebar-bg": "#f3f3f3",
      "--sidebar-border": "rgba(0,0,0,0.12)",
      "--sidebar-text": "#1e1e1e",
    }
  },

  "solarized-light": {
    name: "Solarized Light",
    dark: false,
    root: {
      "--text": "#586e75",
      "--muted": "#839496",
      "--accent": "#268bd2",
      "--accent-hover": "#2aa0e8",
      "--bubble-user": "rgba(38,139,210,0.12)",
      "--bubble-assistant": "rgba(253,246,227,0.8)",
      "--bubble-audio-only": "rgba(253,246,227,0.5)",
      "--audio-accent": "#2aa198",
      "--bg-dof": "0px",
      "--bg-vignette": "0.1",
      ...LIGHT_SURFACE,
      "--surface": "rgba(253,246,227,0.94)",
      "--titlebar-bg": "#eee8d5",
    },
    edit: {
      "--edit-bg": "#fdf6e3",
      "--edit-tab-bg": "#eee8d5",
      "--edit-tab-active-bg": "#fdf6e3",
      "--edit-tab-border": "#d3cbb7",
      "--edit-text": "#586e75",
      "--edit-line-num": "#93a1a1",
      "--edit-line-num-bg": "#fdf6e3",
      "--edit-line-num-border": "#eee8d5",
      "--edit-selection": "rgba(38,139,210,0.18)",
      "--edit-toolcall-bg": "#eee8d5",
      "--edit-step-border": "#eee8d5",
      "--edit-tree-text": "#586e75",
      "--edit-tree-hover": "rgba(0,0,0,0.05)",
      "--edit-tab-text": "#839496",
      "--edit-tab-active-text": "#586e75",
      "--edit-empty-text": "#93a1a1",
      "--sidebar-bg": "#eee8d5",
      "--sidebar-border": "rgba(147,161,161,0.3)",
      "--sidebar-text": "#586e75",
    }
  },

  "github-light": {
    name: "GitHub Light",
    dark: false,
    root: {
      "--text": "#24292e",
      "--muted": "#6a737d",
      "--accent": "#0366d6",
      "--accent-hover": "#0550b2",
      "--bubble-user": "rgba(3,102,214,0.1)",
      "--bubble-assistant": "rgba(255,255,255,0.85)",
      "--bubble-audio-only": "rgba(255,255,255,0.5)",
      "--audio-accent": "#22863a",
      "--bg-dof": "0px",
      "--bg-vignette": "0.1",
      ...LIGHT_SURFACE,
      "--surface": "rgba(255,255,255,0.94)",
      "--titlebar-bg": "#f6f8fa",
    },
    edit: {
      "--edit-bg": "#ffffff",
      "--edit-tab-bg": "#f6f8fa",
      "--edit-tab-active-bg": "#ffffff",
      "--edit-tab-border": "#e1e4e8",
      "--edit-text": "#24292e",
      "--edit-line-num": "#959da5",
      "--edit-line-num-bg": "#ffffff",
      "--edit-line-num-border": "#eaecef",
      "--edit-selection": "rgba(3,102,214,0.18)",
      "--edit-toolcall-bg": "#f6f8fa",
      "--edit-step-border": "#eaecef",
      "--edit-tree-text": "#24292e",
      "--edit-tree-hover": "rgba(0,0,0,0.04)",
      "--edit-tab-text": "#6a737d",
      "--edit-tab-active-text": "#24292e",
      "--edit-empty-text": "#959da5",
      "--sidebar-bg": "#f6f8fa",
      "--sidebar-border": "rgba(27,31,35,0.12)",
      "--sidebar-text": "#24292e",
    }
  },

  // ===== 新增主题 =====

  "cyber-neon": {
    name: "赛博终端・霓虹青",
    dark: true,
    root: {
      "--text": "#c9d1d9",
      "--muted": "#6e7681",
      "--accent": "#00f0ff",
      "--accent-hover": "#5ff8ff",
      "--bubble-user": "rgba(0,240,255,0.16)",
      "--bubble-assistant": "rgba(20,28,40,0.7)",
      "--bubble-audio-only": "rgba(20,28,40,0.3)",
      "--audio-accent": "#00f0ff",
      "--radius": "12px",
      "--bg-dof": "3px",
      "--bg-vignette": "0.6",
      "--surface": "rgba(10,14,20,0.94)",
      "--surface-hover": "rgba(0,240,255,0.06)",
      "--border": "rgba(0,240,255,0.18)",
      "--overlay-bg": "rgba(0,8,16,0.6)",
      "--titlebar-bg": "#060a10",
      "--danger": "#ff477e",
      "--danger-hover": "#ff6b9d",
      "--danger-bg": "rgba(255,71,126,0.15)",
      "--success": "#00e5ff",
      "--success-bg": "rgba(0,229,255,0.15)",
      "--warning": "#ffb347",
      "--warning-bg": "rgba(255,179,71,0.15)",
    },
    edit: {
      "--edit-bg": "#0a0e14",
      "--edit-tab-bg": "#0f1620",
      "--edit-tab-active-bg": "#0a0e14",
      "--edit-tab-border": "#1c2632",
      "--edit-text": "#c9d1d9",
      "--edit-line-num": "#4a5a6a",
      "--edit-line-num-bg": "#0a0e14",
      "--edit-line-num-border": "#161c24",
      "--edit-selection": "rgba(0,240,255,0.28)",
      "--edit-toolcall-bg": "#0f1620",
      "--edit-step-border": "#1c2632",
      "--edit-tree-text": "#c9d1d9",
      "--edit-tree-hover": "rgba(0,240,255,0.08)",
      "--edit-tab-text": "#6e7681",
      "--edit-tab-active-text": "#c9d1d9",
      "--edit-empty-text": "#4a5a6a",
      "--sidebar-bg": "transparent",
      "--sidebar-border": "rgba(0,240,255,0.18)",
      "--sidebar-text": "#c9d1d9",
    }
  },

  "deep-space-indigo": {
    name: "理性深空・靛蓝紫",
    dark: true,
    root: {
      "--text": "#e2e8f0",
      "--muted": "#8b90b8",
      "--accent": "#7c83ff",
      "--accent-hover": "#9aa0ff",
      "--bubble-user": "rgba(124,131,255,0.18)",
      "--bubble-assistant": "rgba(30,30,50,0.72)",
      "--bubble-audio-only": "rgba(30,30,50,0.3)",
      "--audio-accent": "#a78bfa",
      "--radius": "14px",
      "--bg-dof": "2px",
      "--bg-vignette": "0.55",
      "--surface": "rgba(22,22,38,0.95)",
      "--surface-hover": "rgba(124,131,255,0.07)",
      "--border": "rgba(124,131,255,0.16)",
      "--overlay-bg": "rgba(10,10,22,0.6)",
      "--titlebar-bg": "#12121f",
      "--danger": "#f472b6",
      "--danger-hover": "#f9a8d4",
      "--danger-bg": "rgba(244,114,182,0.15)",
      "--success": "#a78bfa",
      "--success-bg": "rgba(167,139,250,0.15)",
      "--warning": "#fbbf24",
      "--warning-bg": "rgba(251,191,36,0.15)",
    },
    edit: {
      "--edit-bg": "#16162a",
      "--edit-tab-bg": "#1d1d36",
      "--edit-tab-active-bg": "#16162a",
      "--edit-tab-border": "#2a2a48",
      "--edit-text": "#e2e8f0",
      "--edit-line-num": "#6b7099",
      "--edit-line-num-bg": "#16162a",
      "--edit-line-num-border": "#2a2a48",
      "--edit-selection": "rgba(124,131,255,0.3)",
      "--edit-toolcall-bg": "#1d1d36",
      "--edit-step-border": "#2a2a48",
      "--edit-tree-text": "#e2e8f0",
      "--edit-tree-hover": "rgba(124,131,255,0.08)",
      "--edit-tab-text": "#8b90b8",
      "--edit-tab-active-text": "#e2e8f0",
      "--edit-empty-text": "#6b7099",
      "--sidebar-bg": "transparent",
      "--sidebar-border": "rgba(124,131,255,0.2)",
      "--sidebar-text": "#e2e8f0",
    }
  },

  "warm-terracotta": {
    name: "暖调编辑・赤陶土",
    dark: false,
    root: {
      "--text": "#4a3528",
      "--muted": "#8a6f5c",
      "--accent": "#c8553d",
      "--accent-hover": "#d9664a",
      "--bubble-user": "rgba(200,85,61,0.12)",
      "--bubble-assistant": "rgba(255,250,243,0.8)",
      "--bubble-audio-only": "rgba(255,250,243,0.5)",
      "--audio-accent": "#c8553d",
      "--radius": "12px",
      "--bg-dof": "0px",
      "--bg-vignette": "0.12",
      "--surface": "rgba(253,247,240,0.95)",
      "--surface-hover": "rgba(200,85,61,0.06)",
      "--border": "rgba(200,85,61,0.18)",
      "--overlay-bg": "rgba(120,80,60,0.18)",
      "--titlebar-bg": "#f3e9da",
    },
    edit: {
      "--edit-bg": "#fdf7f0",
      "--edit-tab-bg": "#f3e9da",
      "--edit-tab-active-bg": "#fdf7f0",
      "--edit-tab-border": "#e0d0bc",
      "--edit-text": "#4a3528",
      "--edit-line-num": "#b09a86",
      "--edit-line-num-bg": "#fdf7f0",
      "--edit-line-num-border": "#ece0cd",
      "--edit-selection": "rgba(200,85,61,0.2)",
      "--edit-toolcall-bg": "#f3e9da",
      "--edit-step-border": "#ece0cd",
      "--edit-tree-text": "#4a3528",
      "--edit-tree-hover": "rgba(200,85,61,0.06)",
      "--edit-tab-text": "#8a6f5c",
      "--edit-tab-active-text": "#4a3528",
      "--edit-empty-text": "#b09a86",
      "--sidebar-bg": "#f3e9da",
      "--sidebar-border": "rgba(200,85,61,0.18)",
      "--sidebar-text": "#4a3528",
    }
  },

  "pixel-gold": {
    name: "像素史诗・金币黄",
    dark: true,
    root: {
      "--text": "#f5e6c8",
      "--muted": "#a8945c",
      "--accent": "#ffc83d",
      "--accent-hover": "#ffd966",
      "--bubble-user": "rgba(255,200,61,0.16)",
      "--bubble-assistant": "rgba(40,32,18,0.74)",
      "--bubble-audio-only": "rgba(40,32,18,0.3)",
      "--audio-accent": "#ffc83d",
      "--radius": "8px",
      "--bg-dof": "4px",
      "--bg-vignette": "0.58",
      "--surface": "rgba(26,20,12,0.95)",
      "--surface-hover": "rgba(255,200,61,0.07)",
      "--border": "rgba(255,200,61,0.18)",
      "--overlay-bg": "rgba(16,12,6,0.6)",
      "--titlebar-bg": "#14100a",
      "--danger": "#ff8c00",
      "--danger-hover": "#ffa940",
      "--danger-bg": "rgba(255,140,0,0.15)",
      "--success": "#d4af37",
      "--success-bg": "rgba(212,175,55,0.15)",
      "--warning": "#ff6b35",
      "--warning-bg": "rgba(255,107,53,0.15)",
    },
    edit: {
      "--edit-bg": "#1a140c",
      "--edit-tab-bg": "#241c10",
      "--edit-tab-active-bg": "#1a140c",
      "--edit-tab-border": "#3a2e18",
      "--edit-text": "#f5e6c8",
      "--edit-line-num": "#8a7444",
      "--edit-line-num-bg": "#1a140c",
      "--edit-line-num-border": "#3a2e18",
      "--edit-selection": "rgba(255,200,61,0.26)",
      "--edit-toolcall-bg": "#241c10",
      "--edit-step-border": "#3a2e18",
      "--edit-tree-text": "#f5e6c8",
      "--edit-tree-hover": "rgba(255,200,61,0.08)",
      "--edit-tab-text": "#a8945c",
      "--edit-tab-active-text": "#f5e6c8",
      "--edit-empty-text": "#8a7444",
      "--sidebar-bg": "transparent",
      "--sidebar-border": "rgba(255,200,61,0.18)",
      "--sidebar-text": "#f5e6c8",
    }
  },

  "neo-brutalist": {
    name: "新野兽派・黑白撞",
    dark: false,
    root: {
      "--text": "#000000",
      "--muted": "#555555",
      "--accent": "#111111",
      "--accent-hover": "#000000",
      "--bubble-user": "rgba(0,0,0,0.06)",
      "--bubble-assistant": "rgba(255,255,255,0.9)",
      "--bubble-audio-only": "rgba(255,255,255,0.6)",
      "--audio-accent": "#111111",
      "--radius": "4px",
      "--bg-dof": "0px",
      "--bg-vignette": "0",
      "--surface": "rgba(255,255,255,0.97)",
      "--surface-hover": "rgba(0,0,0,0.05)",
      "--border": "#000000",
      "--overlay-bg": "rgba(0,0,0,0.25)",
      "--titlebar-bg": "#ffffff",
    },
    edit: {
      "--edit-bg": "#ffffff",
      "--edit-tab-bg": "#f0f0f0",
      "--edit-tab-active-bg": "#ffffff",
      "--edit-tab-border": "#000000",
      "--edit-text": "#000000",
      "--edit-line-num": "#999999",
      "--edit-line-num-bg": "#ffffff",
      "--edit-line-num-border": "#000000",
      "--edit-selection": "rgba(0,0,0,0.12)",
      "--edit-toolcall-bg": "#f0f0f0",
      "--edit-step-border": "#000000",
      "--edit-tree-text": "#000000",
      "--edit-tree-hover": "rgba(0,0,0,0.06)",
      "--edit-tab-text": "#555555",
      "--edit-tab-active-text": "#000000",
      "--edit-empty-text": "#999999",
      "--sidebar-bg": "#f0f0f0",
      "--sidebar-border": "#000000",
      "--sidebar-text": "#000000",
    }
  },

  "glassmorphism-aurora": {
    name: "玻璃拟态・极光紫",
    dark: false,
    root: {
      "--text": "#2d2440",
      "--muted": "#6b5e8a",
      "--accent": "#9d4edd",
      "--accent-hover": "#b065f0",
      "--bubble-user": "rgba(157,78,221,0.14)",
      "--bubble-assistant": "rgba(255,255,255,0.6)",
      "--bubble-audio-only": "rgba(255,255,255,0.4)",
      "--audio-accent": "#9d4edd",
      "--radius": "16px",
      "--bg-dof": "6px",
      "--bg-vignette": "0.2",
      "--surface": "rgba(255,255,255,0.55)",
      "--surface-hover": "rgba(157,78,221,0.08)",
      "--border": "rgba(157,78,221,0.2)",
      "--overlay-bg": "rgba(80,40,120,0.18)",
      "--titlebar-bg": "rgba(240,230,250,0.8)",
    },
    edit: {
      "--edit-bg": "rgba(250,245,255,0.7)",
      "--edit-tab-bg": "rgba(240,230,250,0.6)",
      "--edit-tab-active-bg": "rgba(250,245,255,0.7)",
      "--edit-tab-border": "rgba(157,78,221,0.2)",
      "--edit-text": "#2d2440",
      "--edit-line-num": "#9d8ab8",
      "--edit-line-num-bg": "rgba(250,245,255,0.5)",
      "--edit-line-num-border": "rgba(157,78,221,0.15)",
      "--edit-selection": "rgba(157,78,221,0.2)",
      "--edit-toolcall-bg": "rgba(240,230,250,0.6)",
      "--edit-step-border": "rgba(157,78,221,0.15)",
      "--edit-tree-text": "#2d2440",
      "--edit-tree-hover": "rgba(157,78,221,0.08)",
      "--edit-tab-text": "#6b5e8a",
      "--edit-tab-active-text": "#2d2440",
      "--edit-empty-text": "#9d8ab8",
      "--sidebar-bg": "rgba(240,230,250,0.5)",
      "--sidebar-border": "rgba(157,78,221,0.2)",
      "--sidebar-text": "#2d2440",
    }
  },

  "beige-cream": {
    name: "米杏色+奶油绿",
    dark: false,
    root: {
      "--text": "#3d4a3a",
      "--muted": "#7a8a76",
      "--accent": "#7fa67a",
      "--accent-hover": "#94bb8e",
      "--bubble-user": "rgba(127,166,122,0.14)",
      "--bubble-assistant": "rgba(255,252,243,0.8)",
      "--bubble-audio-only": "rgba(255,252,243,0.5)",
      "--audio-accent": "#7fa67a",
      "--radius": "14px",
      "--bg-dof": "0px",
      "--bg-vignette": "0.12",
      "--surface": "rgba(250,245,232,0.95)",
      "--surface-hover": "rgba(127,166,122,0.08)",
      "--border": "rgba(127,166,122,0.2)",
      "--overlay-bg": "rgba(120,110,80,0.16)",
      "--titlebar-bg": "#ede5d0",
    },
    edit: {
      "--edit-bg": "#faf5e8",
      "--edit-tab-bg": "#ede5d0",
      "--edit-tab-active-bg": "#faf5e8",
      "--edit-tab-border": "#d8ceae",
      "--edit-text": "#3d4a3a",
      "--edit-line-num": "#a89e80",
      "--edit-line-num-bg": "#faf5e8",
      "--edit-line-num-border": "#e0d6bc",
      "--edit-selection": "rgba(127,166,122,0.2)",
      "--edit-toolcall-bg": "#ede5d0",
      "--edit-step-border": "#e0d6bc",
      "--edit-tree-text": "#3d4a3a",
      "--edit-tree-hover": "rgba(127,166,122,0.08)",
      "--edit-tab-text": "#7a8a76",
      "--edit-tab-active-text": "#3d4a3a",
      "--edit-empty-text": "#a89e80",
      "--sidebar-bg": "#ede5d0",
      "--sidebar-border": "rgba(127,166,122,0.2)",
      "--sidebar-text": "#3d4a3a",
    }
  },

  "khaki-klein": {
    name: "卡其加克莱因蓝",
    dark: false,
    root: {
      "--text": "#2b2b2b",
      "--muted": "#6b6b5a",
      "--accent": "#002fa7",
      "--accent-hover": "#0a3fb8",
      "--bubble-user": "rgba(0,47,167,0.1)",
      "--bubble-assistant": "rgba(252,250,240,0.8)",
      "--bubble-audio-only": "rgba(252,250,240,0.5)",
      "--audio-accent": "#002fa7",
      "--radius": "12px",
      "--bg-dof": "0px",
      "--bg-vignette": "0.14",
      "--surface": "rgba(245,241,224,0.95)",
      "--surface-hover": "rgba(0,47,167,0.06)",
      "--border": "rgba(0,47,167,0.2)",
      "--overlay-bg": "rgba(60,55,40,0.18)",
      "--titlebar-bg": "#e8e4d0",
    },
    edit: {
      "--edit-bg": "#f5f1e0",
      "--edit-tab-bg": "#e8e4d0",
      "--edit-tab-active-bg": "#f5f1e0",
      "--edit-tab-border": "#cfc8a8",
      "--edit-text": "#2b2b2b",
      "--edit-line-num": "#9a947a",
      "--edit-line-num-bg": "#f5f1e0",
      "--edit-line-num-border": "#ddd5b8",
      "--edit-selection": "rgba(0,47,167,0.18)",
      "--edit-toolcall-bg": "#e8e4d0",
      "--edit-step-border": "#ddd5b8",
      "--edit-tree-text": "#2b2b2b",
      "--edit-tree-hover": "rgba(0,47,167,0.06)",
      "--edit-tab-text": "#6b6b5a",
      "--edit-tab-active-text": "#2b2b2b",
      "--edit-empty-text": "#9a947a",
      "--sidebar-bg": "#e8e4d0",
      "--sidebar-border": "rgba(0,47,167,0.2)",
      "--sidebar-text": "#2b2b2b",
    }
  },
};

const DEFAULT_THEME = "vscode-dark";

// 主题设置统一内存态：全部落盘到服务端 theme_config.json（不使用 localStorage）
let _settings = {
  theme: DEFAULT_THEME,
  bg_image: "",
  font_family: "",
  font_size: "",
  bg_blur: "",
  bg_vignette: "",
};
let _loadingTheme = false;  // 从服务端加载期间不写回，避免覆盖已有配置
let _persistTimer = null;

/** 防抖写回服务端 theme_config.json（仅保存用户主动修改，加载期间跳过） */
function _persistThemeConfig() {
  if (_loadingTheme) return;
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    try {
      api("/api/config/theme", {
        method: "POST",
        body: JSON.stringify({
          theme: _settings.theme,
          bg_image: _settings.bg_image,
          font_family: _settings.font_family,
          font_size: _settings.font_size,
          bg_blur: _settings.bg_blur,
          bg_vignette: _settings.bg_vignette,
        }),
      });
    } catch { /* ignore */ }
  }, 300);
}

// 字体预设
export const FONT_PRESETS = {
  "system": { name: "系统默认", family: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif' },
  "sans":   { name: "无衬线",   family: '"Inter", "PingFang SC", "Microsoft YaHei", sans-serif' },
  "serif":  { name: "衬线",     family: 'Georgia, "Noto Serif SC", "SimSun", serif' },
  "mono":   { name: "等宽",     family: '"Cascadia Code", "Fira Code", "JetBrains Mono", Consolas, monospace' },
  "zcool":  { name: "站酷快乐体", family: '"ZCOOL KuaiLe", "Microsoft YaHei", sans-serif' },
  "mashan": { name: "马山正楷",   family: '"Ma Shan Zheng", "STKaiti", "KaiTi", serif' },
  "longcang": { name: "龙藏手写", family: '"Long Cang", "STKaiti", "KaiTi", cursive' },
  "zcool-qy": { name: "站酷庆科黄油体", family: '"ZCOOL QingKe HuangYou", "Microsoft YaHei", sans-serif' },
};
export const FONT_SIZE_PRESETS = {
  "12px": "12px",
  "13px": "小 (13px)",
  "14px": "中 (14px)",
  "15px": "大 (15px)",
  "16px": "16px",
  "18px": "特大 (18px)",
  "20px": "20px",
};

export function getFontSetting(key) {
  return key === "family" ? _settings.font_family : key === "size" ? _settings.font_size : "";
}
export function setFontSetting(key, val) {
  if (key === "family") _settings.font_family = val || "";
  else if (key === "size") _settings.font_size = val || "";
  applyFontSetting(key, val);
  _persistThemeConfig();
}
export function applyFontSetting(key, val) {
  const r = document.documentElement;
  if (key === 'family') {
    r.style.setProperty('--font-family', val || FONT_PRESETS.system.family);
  } else if (key === 'size') {
    r.style.setProperty('--font-size', val || '14px');
  }
}

/** 将本地路径转为 API 代理 URL */
function localPathToUrl(localPath) {
  // base64 编码避免路径中中文/特殊字符被 URL 编码破坏
  const utf8 = unescape(encodeURIComponent(localPath));
  return `/api/bg-image?path=${btoa(utf8)}`;
}

/** 获取/设置自定义背景图 */
export function getBgImage() {
  return _settings.bg_image;
}
export function setBgImage(url) {
  _settings.bg_image = url || "";
  applyBgImage(_settings.bg_image);
  _persistThemeConfig();
}
export function applyBgImage(url) {
  const r = document.documentElement;
  const layer = document.getElementById('bgImageLayer');
  if (url) {
    // 本地绝对路径 → API 代理（浏览器安全策略禁止 HTTP 页面直接加载 file://）
    const displayUrl = /^[a-zA-Z]:[\\/]/.test(url) ? localPathToUrl(url) : url;
    r.style.setProperty('--bg-image-override', `url("${displayUrl}")`);
    // 同步更新 bgImageLayer 的内联样式，覆盖 wireBackgroundImage 设置的默认值
    if (layer) layer.style.backgroundImage = `url("${displayUrl}")`;
  } else {
    r.style.removeProperty('--bg-image-override');
    // 恢复默认背景
    if (layer) layer.style.backgroundImage = '';
  }
}

/** 获取当前保存的主题 */
export function getCurrentTheme() {
  return _settings.theme;
}

/** 应用主题到页面 */
export function applyTheme(themeId) {
  const theme = THEMES[themeId] || THEMES[DEFAULT_THEME];
  const r = document.documentElement;

  // 全局变量
  if (theme.root) {
    Object.entries(theme.root).forEach(([k, v]) => r.style.setProperty(k, v));
  }

  // Edit 模式变量
  if (theme.edit) {
    Object.entries(theme.edit).forEach(([k, v]) => r.style.setProperty(k, v));
  }

  // 更新内存态并落盘（加载期间跳过，避免覆盖服务端已有配置）
  _settings.theme = THEMES[themeId] ? themeId : DEFAULT_THEME;
  _persistThemeConfig();

  // 触发 body 类名切换（用于全局暗/亮模式判断）
  // 优先使用主题对象的 dark 字段；缺失时回退到 id 字符串推断
  const isDark = theme.dark ?? !(themeId.includes("light") || themeId.includes("solarized"));
  document.body.classList.toggle("theme-dark", isDark);
  document.body.classList.toggle("theme-light", !isDark);

  // 通知依赖主题色的组件重绘（如 Token 活跃度矩阵）
  document.dispatchEvent(new CustomEvent("theme-changed"));
}

/** 初始化：先用默认主题渲染，再从服务端 theme_config.json 恢复全部设置 */
export function initTheme() {
  _loadingTheme = true;
  applyTheme(DEFAULT_THEME);
  applyBgImage("");
  applyFontSetting("family", "");
  applyFontSetting("size", "");
  applyBgBlur("");
  applyBgVignette("");
  loadThemeConfig();  // 完成后在 finally 中解除 _loadingTheme
  return DEFAULT_THEME;
}

// ===== 背景模糊度 =====
export function getBgBlur() {
  return _settings.bg_blur;
}
export function setBgBlur(val) {
  _settings.bg_blur = val || "";
  applyBgBlur(_settings.bg_blur);
  _persistThemeConfig();
}
export function applyBgBlur(val) {
  // val 为空字符串时使用主题默认值（由 applyTheme 设置），否则覆盖
  const r = document.documentElement;
  if (val !== "" && val !== null && val !== undefined) {
    r.style.setProperty('--bg-dof', val + 'px');
  } else {
    r.style.removeProperty('--bg-dof');
  }
}

// ===== 背景暗角 =====
export function getBgVignette() {
  return _settings.bg_vignette;
}
export function setBgVignette(val) {
  _settings.bg_vignette = val || "";
  applyBgVignette(_settings.bg_vignette);
  _persistThemeConfig();
}
export function applyBgVignette(val) {
  const r = document.documentElement;
  if (val !== "" && val !== null && val !== undefined) {
    r.style.setProperty('--bg-vignette', val);
  } else {
    r.style.removeProperty('--bg-vignette');
  }
}

/** 从服务端 theme_config.json 加载主题配置并应用（不使用 localStorage） */
export async function loadThemeConfig() {
  try {
    const res = await api("/api/config/theme");
    _loadingTheme = true;
    if (res.theme && THEMES[res.theme]) {
      applyTheme(res.theme);
    }
    if (res.bg_image !== undefined) {
      _settings.bg_image = res.bg_image || "";
      applyBgImage(_settings.bg_image);
    }
    if (res.font_family !== undefined) {
      // 过滤旧版默认占位值（msjh 等非真实字体）
      const fam = (res.font_family || "").trim();
      _settings.font_family = (fam && fam !== "msjh" && fam !== "msjhbd") ? fam : "";
      applyFontSetting("family", _settings.font_family);
    }
    if (res.font_size !== undefined) {
      _settings.font_size = res.font_size || "";
      applyFontSetting("size", _settings.font_size);
    }
    if (res.bg_blur !== undefined) {
      _settings.bg_blur = res.bg_blur || "";
      applyBgBlur(_settings.bg_blur);
    }
    if (res.bg_vignette !== undefined) {
      _settings.bg_vignette = res.bg_vignette || "";
      applyBgVignette(_settings.bg_vignette);
    }
  } catch {
    // 服务端不可达：保持默认设置
  } finally {
    _loadingTheme = false;
  }
}
