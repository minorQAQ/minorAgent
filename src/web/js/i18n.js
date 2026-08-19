// i18n.js -- 多语言系统（中文 / English）

const LANG_KEY = "minor_language";

export const LANGS = {
  "zh-CN": {
    name: "中文",
    // 通用
    app_title: "多模态Agent",
    sidebar_sessions: "会话",
    sidebar_hint_edit: "在此管理文档文件，支持拖拽和引用。",
    new_session: "新建会话",
    edit_mode: "Edit",
    chat_mode: "Chat",
    send: "发送",
    pause: "暂停",
    clear: "清空",
    output_mode: "输出模式",
    text_mode: "文字模式",
    voice_mode: "语音模式",
    agent_mode: "Agent 模式",
    auto_input: "自动语音输入",
    input_placeholder: "输入消息或添加附件，Enter 发送（Shift+Enter 换行）",
    settings: "系统配置",
    // 设置
    tab_agent: "Agent",
    tab_tool: "工具",
    tab_env: "环境变量",
    tab_skills: "Skills",
    tab_gui: "GUI设置",
    tab_theme: "主题/语言",
    theme_label: "主题",
    lang_label: "语言",
    theme_restart_note: "主题即时生效，语言需刷新页面。",
    // Edit
    edit_open_folder: "打开文件夹",
    edit_empty_title: "打开文件开始编辑",
    edit_empty_hint: "点击左侧打开文件夹，或将文件拖入此区域",
    edit_tree_empty: "打开文件夹或拖入文件开始编辑",
    edit_new_file: "新建文件",
    edit_new_folder: "新建文件夹",
    // 文件操作
    file_rename: "重命名",
    file_copy: "复制",
    file_cut: "剪切",
    file_paste: "粘贴",
    file_duplicate: "复制副本",
    file_delete: "删除",
    file_close: "关闭文件",
    file_undo_delete: "撤销删除",
    file_remove_workspace: "从工作区移除",
    file_paste_here: "粘贴到此",
    file_new_file: "新建文件",
    file_new_folder: "新建文件夹",
    file_rename_folder: "重命名文件夹",
    file_delete_folder: "删除文件夹",
    // Toast
    toast_copied: "已复制到剪贴板",
    toast_cut: "已剪切到剪贴板",
    toast_pasted: "已粘贴",
    toast_duplicated: "已创建副本",
    toast_moved: "文件已移动",
    toast_folder_created: "文件夹已创建",
    toast_file_exists: "文件已存在",
    toast_folder_exists: "文件夹已存在",
    toast_no_supported: "文件夹中没有支持的文件类型",
    toast_unsupported: "不支持的文件类型",
    toast_folder_opened: "已打开文件夹，共 {n} 个文件",
    toast_file_opened: "已打开：{name}",
    toast_snapshot_saved: "文档快照已保存",
    toast_undo: "已回退到上一步",
    toast_no_undo: "没有可回退的步骤",
    toast_agent_done: "Agent 执行完成",
    toast_agent_error: "错误: {msg}",
    // 确认
    confirm_delete_folder: '确认删除文件夹 "{name}" 及其所有内容？',
    new_file_prompt: "输入新文件名：",
    new_folder_prompt: "输入新文件夹名：",
    // 预览附件
    upload_attachment: "上传附件",
    // 连接错误
    connect_error: "无法连接服务",
    connect_error_desc: '请从 Agent 目录执行：<code>uvicorn web.server:app --reload --host 127.0.0.1 --port 8765</code>，并保证 PYTHONPATH 包含 <code>src</code>。',
    // 侧栏
    collapse_sidebar: "收起侧栏",
    expand_sidebar: "展开侧栏",
  },
  "en-US": {
    name: "English",
    app_title: "Multimodal Agent",
    sidebar_sessions: "Sessions",
    sidebar_hint_edit: "Manage document files here. Drag & drop supported.",
    new_session: "New Session",
    edit_mode: "Edit",
    chat_mode: "Chat",
    send: "Send",
    pause: "Pause",
    clear: "Clear",
    output_mode: "Output",
    text_mode: "Text",
    voice_mode: "Voice",
    agent_mode: "Agent Mode",
    auto_input: "Auto Input",
    input_placeholder: "Type a message or add attachments, Enter to send (Shift+Enter for newline)",
    settings: "Settings",
    tab_agent: "Agent",
    tab_tool: "Tools",
    tab_env: "Env",
    tab_skills: "Skills",
    tab_gui: "GUI",
    tab_theme: "Theme/Lang",
    theme_label: "Theme",
    lang_label: "Language",
    theme_restart_note: "Theme applies instantly. Language requires page refresh.",
    edit_open_folder: "Open Folder",
    edit_empty_title: "Open a file to start editing",
    edit_empty_hint: "Click Open Folder on the left, or drag files here",
    edit_tree_empty: "Open a folder or drag files to start",
    edit_new_file: "New File",
    edit_new_folder: "New Folder",
    file_rename: "Rename",
    file_copy: "Copy",
    file_cut: "Cut",
    file_paste: "Paste",
    file_duplicate: "Duplicate",
    file_delete: "Delete",
    file_close: "Close",
    file_undo_delete: "Undo Delete",
    file_remove_workspace: "Remove from Workspace",
    file_paste_here: "Paste Here",
    file_new_file: "New File",
    file_new_folder: "New Folder",
    file_rename_folder: "Rename Folder",
    file_delete_folder: "Delete Folder",
    toast_copied: "Copied to clipboard",
    toast_cut: "Cut to clipboard",
    toast_pasted: "Pasted",
    toast_duplicated: "Duplicate created",
    toast_moved: "File moved",
    toast_folder_created: "Folder created",
    toast_file_exists: "File already exists",
    toast_folder_exists: "Folder already exists",
    toast_no_supported: "No supported files in folder",
    toast_unsupported: "Unsupported file type",
    toast_folder_opened: "Folder opened, {n} files total",
    toast_file_opened: "Opened: {name}",
    toast_snapshot_saved: "Snapshot saved",
    toast_undo: "Undone to previous step",
    toast_no_undo: "Nothing to undo",
    toast_agent_done: "Agent execution complete",
    toast_agent_error: "Error: {msg}",
    confirm_delete_folder: 'Confirm delete folder "{name}" and all contents?',
    new_file_prompt: "Enter new file name:",
    new_folder_prompt: "Enter new folder name:",
    upload_attachment: "Upload",
    connect_error: "Cannot connect to server",
    connect_error_desc: 'Run from Agent directory: <code>uvicorn web.server:app --reload --host 127.0.0.1 --port 8765</code>, with PYTHONPATH including <code>src</code>.',
    collapse_sidebar: "Collapse Sidebar",
    expand_sidebar: "Expand Sidebar",
  }
};

const DEFAULT_LANG = "zh-CN";
let _currentLang = DEFAULT_LANG;

/** 获取已保存语言 */
function getLang() {
  try { return localStorage.getItem(LANG_KEY) || DEFAULT_LANG; }
  catch { return DEFAULT_LANG; }
}

/** 获取翻译文本 */
export function t(key, params) {
  const lang = _currentLang;
  const dict = LANGS[lang] || LANGS[DEFAULT_LANG];
  let text = dict[key];
  if (text === undefined) text = (LANGS[DEFAULT_LANG] || {})[key] || key;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(`{${k}}`, v);
    });
  }
  return text;
}

/** 切换语言 */
export function setLanguage(langId) {
  if (!LANGS[langId]) return;
  _currentLang = langId;
  try { localStorage.setItem(LANG_KEY, langId); } catch {}
  applyLanguage();
}

/** 应用语言到 DOM */
export function applyLanguage() {
  const lang = getLang();
  _currentLang = lang;
  document.documentElement.lang = lang;

  const map = {
    "#mainHeaderText h1": "app_title",
    "#mainHeaderText .subtitle": "app_subtitle",
    "#textInput": { attr: "placeholder", key: "input_placeholder" },
    "#openFolderBtn": "edit_open_folder",
    "#newFileBtn": "edit_new_file",
    "#newFolderBtn": "edit_new_folder",
    "#editEmptyState p:first-child": "edit_empty_title",
    ".edit-empty-hint": "edit_empty_hint",
  };

  Object.entries(map).forEach(([sel, val]) => {
    const el = document.querySelector(sel);
    if (!el) return;
    if (typeof val === "object" && val.attr) {
      el.setAttribute(val.attr, t(val.key));
    } else {
      const text = t(val);
      if (!text.includes("<")) el.textContent = text;
    }
  });

  // 设置页标题
  document.title = t("app_title");
}

/** 初始化 */
export function initI18n() {
  applyLanguage();
}
