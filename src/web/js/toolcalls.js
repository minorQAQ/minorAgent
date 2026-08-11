// toolcalls.js -- 工具调用 / think面板 渲染（新版：无框单行 + 状态圆圈 + 图标 + 展开折叠 + 计时）

import { escapeHtml, showToast } from './utils.js';
import { state } from './state.js';
import { api } from './api.js';

/* ===== 工具图标与参数映射表 ===== */
const TOOL_META = {
  doc_tool: { icon: null, dynamicIcon: true },             // 按 action 选 写/读/删除.svg
  todo_list: { icon: '/image/todolist.svg' },
  browser_control: { icon: '/image/控制.svg' },
  software_control: { icon: '/image/控制.svg' },
  terminal_execute: { icon: '/image/终端.svg' },
  email: { icon: '/image/邮件.svg' },
  image_gen: { icon: '/image/图片生成.svg' },
  skill_router: { icon: '/image/skill.svg' },
  web_search: { icon: '/image/web.svg' },
  sendfile: { icon: '/image/sendfile.svg' },
  gui_tool: { icon: '/image/gui.svg' },
  rag: { icon: '/image/rag.svg' },
  human_interaction: { icon: '/image/人为干预.svg' },
  call_subagent: { icon: '/image/人机交互.svg', defaultExpanded: true },
  agent_call: { icon: '/image/人机交互.svg', defaultExpanded: true },
  date_query: { icon: '/image/时钟.svg', noParam: true },
  cron_manager: { icon: '/image/时钟.svg' },
  text2sql: { icon: '/image/SQL.svg' },
  hard_excel_read: { icon: '/image/Excel.svg' },
  excel2sql: { icon: '/image/SQL.svg' },
};
// 工具动作→中文标签映射（统一根据参数在图标右侧显示不同汉字）
const CRON_ACTION_LABEL = { list: '查看任务', get: '查看任务', create: '新增任务', update: '修改任务', delete: '删除任务' };
const DOC_ACTION_ICON = { read: '/image/读.svg', create: '/image/写.svg', update: '/image/写.svg', delete: '/image/删除.svg' };
const DOC_ACTION_LABEL = { read: '查看文档', create: '创建文档', update: '修改文档', delete: '删除文档' };
const TEXT2SQL_ACTION_LABEL = { list_tables: '查看库结构', describe: '查看表结构', query: '查询', execute: '增删改' };
const BROWSER_ACTION_LABEL = { open: '打开浏览器', close: '关闭浏览器' };
const SOFTWARE_ACTION_LABEL = { open: '打开软件', close: '关闭软件', force_close: '强制关闭' };
const MAIL_ACTION_LABEL = { send: '发送邮件', read: '读取邮件' };
const RAG_ACTION_LABEL = { query: '查询知识库', add_document: '添加文档', clear: '清空来源', list_sources: '列出来源' };
const HUMAN_INTERACTION_LABEL = { information: '请求信息', selection: '选择确认' };
// 无 action 参数工具的通用中文标签（getToolLabel 回退用）
const TOOL_DISPLAY_NAMES = {
  web_search: '联网搜索',
  terminal_execute: '终端执行',
  image_gen: '图片生成',
  sendfile: '发送文件',
  skill_router: '技能加载',
  gui: 'GUI操作',
  date_query: '日期查询',
  todo_list: '任务管理',
  todolist: '任务管理',
  hard_excel_read: '读取Excel',
  excel2sql: '表格数据入库',
};

/* ===== 工具元信息辅助 ===== */
function normalizeToolName(name) {
  const n = String(name || "").trim();
  if (n === "call_subagent" || n === "agent_call") return n;
  if (n === "send_file") return "sendfile";
  return n;
}

function getToolIcon(call) {
  const name = normalizeToolName(call.name);
  const meta = TOOL_META[name];
  if (!meta) return null;
  if (meta.dynamicIcon && name === "doc_tool") {
    const action = (call.args && call.args.action) || "read";
    return DOC_ACTION_ICON[action] || DOC_ACTION_ICON.read;
  }
  return meta.icon || null;
}

function getToolLabel(call) {
  const name = normalizeToolName(call.name);
  const args = call.args || {};
  if (name === "doc_tool") {
    const action = args.action || "read";
    return DOC_ACTION_LABEL[action] || "查看文档";
  }
  if (name === "call_subagent" || name === "agent_call") {
    const sub = args.agent_name || "";
    return sub ? `子Agent: ${sub}` : "子Agent";
  }
  if (name === "cron_manager") {
    const action = args.action || "list";
    return CRON_ACTION_LABEL[action] || "定时任务";
  }
  if (name === "text2sql") {
    const action = args.action || "query";
    return TEXT2SQL_ACTION_LABEL[action] || "数据库";
  }
  if (name === "browser_control") {
    const action = args.action || "open";
    return BROWSER_ACTION_LABEL[action] || "浏览器";
  }
  if (name === "software_control") {
    const action = args.action || "open";
    return SOFTWARE_ACTION_LABEL[action] || "软件控制";
  }
  if (name === "mail_tool" || name === "email") {
    const action = args.action || "send";
    return MAIL_ACTION_LABEL[action] || "邮件";
  }
  if (name === "rag_tool" || name === "rag") {
    const action = args.action_type || "query";
    return RAG_ACTION_LABEL[action] || "知识库";
  }
  if (name === "human_interaction") {
    const type = args.interaction_type || "information";
    return HUMAN_INTERACTION_LABEL[type] || "人为干预";
  }
  if (name === "hard_excel_read") {
    const s = args.sheet || (args.sheets && args.sheets.length ? `${args.sheets.length}个sheet` : "");
    return s ? `读取Excel: ${s}` : "读取Excel";
  }
  if (name === "excel2sql") {
    const dry = args.dry_run === "true";
    const tbl = args.target_table || "";
    if (tbl) return dry ? `预览入库: ${tbl}` : `入库: ${tbl}`;
    return dry ? "预览入库" : "数据入库";
  }
  return TOOL_DISPLAY_NAMES[name] || name;
}

function getToolArgsText(call) {
  const name = normalizeToolName(call.name);
  const args = call.args || {};
  if (name === "doc_tool") {
    // doc 只展示文件名（basename），不展示 action 与完整参数
    const fp = args.file_path || args.path || "";
    return fp ? fp.replace(/\\/g, "/").split("/").pop() : "";
  }
  if (name === "call_subagent" || name === "agent_call") {
    const task = args.task_description || "";
    return task ? String(task).slice(0, 120) : "";
  }
  if (name === "cron_manager") {
    const taskName = args.name || "";
    return taskName ? String(taskName) : (args.action || "");
  }
  if (name === "text2sql") {
    if (args.table) return String(args.table);
    if (args.sql) return String(args.sql).slice(0, 120);
    return args.action || "";
  }
  if (name === "browser_control") {
    return args.url ? String(args.url).slice(0, 120) : "";
  }
  if (name === "software_control") {
    return args.software_name ? String(args.software_name) : "";
  }
  if (name === "mail_tool" || name === "email") {
    if (args.action === "send" && args.subject) return String(args.subject).slice(0, 120);
    return "";
  }
  if (name === "rag_tool" || name === "rag") {
    return args.query || args.source_name || args.source_path || "";
  }
  if (name === "human_interaction") {
    return args.message || args.question || "";
  }
  if (name === "web_search") {
    return args.query ? String(args.query).slice(0, 120) : "";
  }
  if (name === "terminal_execute") {
    return args.command ? String(args.command).slice(0, 120) : "";
  }
  if (name === "image_gen") {
    return args.prompt ? String(args.prompt).slice(0, 120) : "";
  }
  if (name === "skill_router") {
    return args.query ? String(args.query).slice(0, 120) : "";
  }
  if (name === "hard_excel_read") {
    const fp = args.file_path || "";
    return fp ? fp.replace(/\\/g, "/").split("/").pop() : "";
  }
  if (name === "excel2sql") {
    return args.target_database && args.target_table
      ? `${args.target_database}.${args.target_table}`
      : (args.target_table || args.target_database || "");
  }
  if (name === "sendfile") {
    const fp = args.file_path || "";
    return fp ? fp.replace(/\\/g, "/").split("/").pop() : "";
  }
  // 其他工具：展示参数 JSON 摘要
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  return JSON.stringify(args);
}

function getToolFileBasename(call) {
  const args = call.args || {};
  const fp = args.file_path || args.path || "";
  return fp ? fp.replace(/\\/g, "/").split("/").pop() : "";
}

/* ===== 计时辅助 ===== */
function formatDuration(seconds) {
  const n = Math.max(0, Number(seconds) || 0);
  if (n < 1) {
    // 亚秒级显示毫秒
    const ms = Math.round(n * 1000);
    return `${ms}ms`;
  }
  if (n < 60) {
    // 1-60秒：显示整数秒
    return `${Math.floor(n)}s`;
  }
  if (n < 3600) {
    // 1-60分钟：显示分+秒
    const m = Math.floor(n / 60);
    const s = Math.floor(n % 60);
    return `${m}m${s}s`;
  }
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = Math.floor(n % 60);
  return `${h}h${m}m${s}s`;
}

function getToolCallsTotalDuration(toolCalls) {
  if (!toolCalls || !toolCalls.length) return 0;
  const timestamps = toolCalls.map((c) => Number(c.timestamp)).filter((t) => Number.isFinite(t) && t > 0);
  const endedAts = toolCalls.map((c) => Number(c.ended_at)).filter((t) => Number.isFinite(t) && t > 0);
  if (!timestamps.length) return 0;
  const start = Math.min(...timestamps);
  const end = endedAts.length ? Math.max(...endedAts) : Math.max(...timestamps);
  return Math.max(0, end - start);
}

/* ===== 从工具文件 URL 中提取文件名 ===== */
function _extractToolFileName(url) {
  if (!url) return "文件";
  try {
    const u = new URL(url, window.location.origin);
    const pathParam = u.searchParams.get("path");
    if (pathParam) {
      const name = pathParam.replace(/\\/g, "/").split("/").pop();
      if (name) return decodeURIComponent(name);
    }
  } catch { /* fallback */ }
  const clean = url.split("?")[0];
  const name = clean.replace(/\\/g, "/").split("/").pop();
  return name ? decodeURIComponent(name) : "文件";
}

/* ===== 图片浮窗预览（保留） ===== */
function showImagePreview(imgSrc) {
  const existing = document.querySelector('.img-preview-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'img-preview-overlay';

  const container = document.createElement('div');
  container.className = 'img-preview-container';

  const img = document.createElement('img');
  img.className = 'img-preview-img';
  img.src = imgSrc;
  img.alt = '图片预览';
  container.appendChild(img);

  const toolbar = document.createElement('div');
  toolbar.className = 'img-preview-toolbar';

  const dlBtn = document.createElement('button');
  dlBtn.className = 'img-preview-btn img-preview-btn--download';
  dlBtn.innerHTML = `<img src="/image/%E4%B8%8B%E8%BD%BD.svg" alt="" /> 下载`;
  dlBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const a = document.createElement('a');
    a.href = imgSrc;
    a.download = imgSrc.split('/').pop().split('?')[0] || 'image';
    a.click();
  });
  toolbar.appendChild(dlBtn);

  // 修改按钮：进入画板编辑，确定后作为新图像替换原图
  const editBtn = document.createElement('button');
  editBtn.className = 'img-preview-btn img-preview-btn--edit';
  editBtn.innerHTML = `✎ 修改`;
  editBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    // 通过 DOM 上的 _pendingIdx 推断原图在 pendingFiles 中的索引
    let originalIdx = -1;
    let originalName = 'image';
    try {
      const thumbs = document.querySelectorAll('.input-inline-img-thumb-wrap img.input-inline-img-thumb');
      for (const t of thumbs) {
        if (t.src === imgSrc || t._blobUrl === imgSrc) {
          if (typeof t._pendingIdx === 'number') originalIdx = t._pendingIdx;
          if (t.title) originalName = t.title;
          break;
        }
      }
    } catch {}
    import('./canvas-editor.js').then((m) => {
      m.openCanvasEditor({
        mode: 'edit',
        imageSrc: imgSrc,
        originalIdx,
        originalName,
      });
    }).catch((err) => {
      console.error('画板加载失败', err);
    });
  });
  toolbar.appendChild(editBtn);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'img-preview-btn img-preview-btn--close';
  closeBtn.textContent = '关闭';
  closeBtn.addEventListener('click', (e) => { e.stopPropagation(); overlay.remove(); });
  toolbar.appendChild(closeBtn);

  container.appendChild(toolbar);
  overlay.appendChild(container);
  overlay.addEventListener('click', () => overlay.remove());
  container.addEventListener('click', (e) => e.stopPropagation());

  const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
}

/* ===== 文件下载弹窗（保留） ===== */
function showFileDownloadDialog(fileUrl, fileName, fileSize) {
  const existing = document.querySelector('.file-dl-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'file-dl-overlay';
  const box = document.createElement('div');
  box.className = 'file-dl-box';

  const icon = document.createElement('div');
  icon.className = 'file-dl-icon';
  const ext = (fileName || '').split('.').pop()?.toLowerCase();
  const iconMap = {
    pdf: '\u{1F4C4}', doc: '\u{1F4DD}', docx: '\u{1F4DD}', xls: '\u{1F4CA}', xlsx: '\u{1F4CA}',
    ppt: '\u{1F4CA}', pptx: '\u{1F4CA}', zip: '\u{1F4E6}', rar: '\u{1F4E6}', '7z': '\u{1F4E6}',
    mp3: '\u{1F3B5}', wav: '\u{1F3B5}', mp4: '\u{1F3AC}', py: '\u{1F40D}',
    js: '\u{1F4C4}', ts: '\u{1F4C4}', html: '\u{1F310}', css: '\u{1F3A8}',
    json: '\u{1F4CB}', txt: '\u{1F4C4}', md: '\u{1F4DD}',
  };
  icon.textContent = iconMap[ext] || '\u{1F4CE}';
  box.appendChild(icon);

  const nameEl = document.createElement('div');
  nameEl.className = 'file-dl-name';
  nameEl.textContent = fileName || '未知文件';
  box.appendChild(nameEl);

  const meta = document.createElement('div');
  meta.className = 'file-dl-meta';
  if (fileSize != null) {
    const s = Number(fileSize);
    meta.textContent = s > 1048576 ? `${(s / 1048576).toFixed(1)} MB` : s > 1024 ? `${(s / 1024).toFixed(1)} KB` : `${s} B`;
  }
  box.appendChild(meta);

  const actions = document.createElement('div');
  actions.className = 'file-dl-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'dialog-btn dialog-btn--cancel';
  cancelBtn.textContent = '取消';
  cancelBtn.addEventListener('click', () => overlay.remove());
  actions.appendChild(cancelBtn);
  const dlBtn = document.createElement('button');
  dlBtn.className = 'dialog-btn dialog-btn--ok';
  dlBtn.textContent = '下载';
  dlBtn.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = fileUrl;
    a.download = fileName || '';
    a.click();
    overlay.remove();
  });
  actions.appendChild(dlBtn);
  box.appendChild(actions);
  overlay.appendChild(box);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
}

/* ===== 文件预览浮窗（统一使用 file-preview 组件） ===== */
// 支持内容预览的扩展名白名单：图片/SVG/文本/代码。其余一律下载。
const PREVIEW_EXTS = new Set([
  // 文本/代码
  'txt', 'json', 'md', 'py', 'js', 'ts', 'css', 'xml', 'yaml', 'yml', 'toml',
  'csv', 'log', 'env', 'ini', 'cfg', 'sh', 'bat', 'ps1', 'sql', 'r', 'go', 'rs', 'rb',
  'php', 'swift', 'kt', 'scala', 'cpp', 'c', 'h', 'java', 'm', 'html', 'htm',
  // 矢量图
  'svg',
]);

async function showFilePreviewDialog(fileUrl, fileName) {
  const ext = (fileName || '').split('.').pop()?.toLowerCase();
  const isImg = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext);

  // 图片直接用 showImagePreview
  if (isImg) {
    showImagePreview(fileUrl);
    return;
  }

  // 不在白名单的（xlsx/xls/docx/pptx/pdf/zip 等）直接下载
  if (!PREVIEW_EXTS.has(ext)) {
    showFileDownloadDialog(fileUrl, fileName);
    return;
  }

  try {
    const resp = await fetch(fileUrl);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const content = await resp.text();

    const { openFilePreview } = await import('./file-preview.js');
    openFilePreview(fileUrl, fileName, content, {
      onDownload: () => {
        const a = document.createElement('a');
        a.href = fileUrl;
        a.download = fileName || '';
        a.click();
      }
    });
  } catch (e) {
    // 加载失败：仍用统一预览显示错误信息
    const { openFilePreview } = await import('./file-preview.js');
    openFilePreview(fileUrl, fileName, '文件加载失败：' + (e.message || e));
  }
}

/* ===== 用户文件卡片（共享：用户输入文件 + sendfile 返回文件） ===== */
function renderUserFileCard(fileUrl, fileName, options = {}) {
  const card = document.createElement("div");
  card.className = "user-file-card";

  const icon = document.createElement("img");
  icon.className = "user-file-card-icon";
  icon.src = "/image/\u6587\u6863\u6309\u94AE.svg";   // 文档按钮.svg
  icon.alt = "\u6587\u4EF6";

  const info = document.createElement("div");
  info.className = "user-file-card-info";

  const nameEl = document.createElement("span");
  nameEl.className = "user-file-name";
  const safeName = fileName || "附件";
  nameEl.textContent = safeName;
  nameEl.title = safeName;

  const extEl = document.createElement("span");
  extEl.className = "user-file-ext";
  const dotIdx = safeName.lastIndexOf(".");
  extEl.textContent = dotIdx >= 0 ? safeName.slice(dotIdx + 1).toLowerCase() : "file";

  info.appendChild(nameEl);
  info.appendChild(extEl);
  card.appendChild(icon);
  card.appendChild(info);

  card.addEventListener("click", (e) => {
    e.stopPropagation();
    if (options.preview !== false) {
      showFilePreviewDialog(fileUrl, safeName);
    } else {
      showFileDownloadDialog(fileUrl, safeName);
    }
  });

  // 拖拽支持：拖到输入区可重新引用该文件
  card.draggable = true;
  card.addEventListener("dragstart", (e) => {
    e.dataTransfer.clearData();
    e.dataTransfer.setData("application/x-chat-file", fileUrl);
    e.dataTransfer.setData("text/plain", safeName);
    e.dataTransfer.effectAllowed = "copy";
  });

  return card;
}

/* ===== 横向滚动行辅助：滚轮转 scrollLeft + 溢出渐变遮罩 ===== */
function attachHorizontalScroll(el) {
  if (!el || el._hcBound) return;
  el._hcBound = true;
  el.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    }
  }, { passive: false });
  const update = () => {
    el.classList.toggle("user-media-row--overflow", el.scrollWidth > el.clientWidth + 2);
  };
  el.addEventListener("scroll", update, { passive: true });
  // 延迟一次以等待内容布局
  requestAnimationFrame(update);
  setTimeout(update, 100);
}

/* ===== 单条工具调用行渲染 =====
 * options.disableExpand: 禁用普通工具的展开（edit 模式用）；agentcall 仍可展开嵌套
 */
// 去除子 Agent 返回值的前缀行（如 "[子Agent: xxx] 执行结果:"），仅保留实际结果文本
function _stripSubAgentResultPrefix(text) {
  const s = String(text || "");
  const nl = s.indexOf("\n");
  if (nl > 0) {
    const firstLine = s.slice(0, nl);
    if (firstLine.includes("执行结果") || firstLine.includes("执行出错")) {
      return s.slice(nl + 1);
    }
  }
  return s;
}

/* 子 Agent 返回值可折叠行（图标「回复.svg」+ 标签 + 展开详情） */
function _renderSubReplyRow(rawText) {
  const text = _stripSubAgentResultPrefix(rawText);
  const isEmpty = !text.trim();

  const row = document.createElement("div");
  row.className = "sub-reply-row" + (isEmpty ? "" : " sub-reply-row--expanded");

  const icon = document.createElement("img");
  icon.className = "sub-reply-row-icon";
  icon.src = "/image/回复.svg";
  icon.alt = "";
  icon.title = isEmpty ? "" : "点击展开/折叠返回值";
  row.appendChild(icon);

  const label = document.createElement("span");
  label.className = "sub-reply-row-label";
  label.textContent = "子Agent回复";
  row.appendChild(label);

  const detail = document.createElement("div");
  detail.className = "sub-reply-row-detail";
  detail.textContent = text;
  row.appendChild(detail);

  if (!isEmpty) {
    const toggle = () => row.classList.toggle("sub-reply-row--expanded");
    icon.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
    label.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  }

  return row;
}

function renderToolCallRow(call, options = {}) {
  const name = normalizeToolName(call.name);
  const meta = TOOL_META[name] || {};
  const isSubAgentCall = (name === "call_subagent" || name === "agent_call");
  const isNoParam = !!meta.noParam;
  const isRunning = call.status !== "done";
  const defaultExpanded = !!meta.defaultExpanded || !!options.defaultExpanded;
  const disableExpand = !!options.disableExpand;
  // edit 模式下普通工具不可展开，但 agentcall 仍可展开嵌套
  const canExpand = disableExpand
    ? isSubAgentCall
    : (!isNoParam || isSubAgentCall);

  const row = document.createElement("div");
  row.className = "tool-call-row" + (isRunning ? " tool-call-row--running" : " tool-call-row--done") + (defaultExpanded ? " tool-call-row--expanded" : "");

  // 图标（运行中橙黄，结束绿色；点击展开/折叠）
  const iconPath = getToolIcon(call);
  if (iconPath) {
    const icon = document.createElement("img");
    icon.className = "tc-icon" + (isRunning ? " tc-icon--running" : " tc-icon--done");
    icon.src = iconPath;
    icon.alt = "";
    row.appendChild(icon);
  }

  // 名称
  const nameEl = document.createElement("span");
  nameEl.className = "tc-name";
  nameEl.textContent = getToolLabel(call);
  row.appendChild(nameEl);

  // 参数文本（横向滚动容器）
  const argsText = getToolArgsText(call);
  if (argsText && !isNoParam) {
    const argsScroll = document.createElement("div");
    argsScroll.className = "tc-args-scroll";
    const argsSpan = document.createElement("span");
    argsSpan.className = "tc-args-text";
    argsSpan.textContent = argsText;
    argsScroll.appendChild(argsSpan);
    attachHorizontalScroll(argsScroll);
    row.appendChild(argsScroll);
  }

  // 无参数工具：结果居中显示
  if (isNoParam && call.result_text) {
    const resultInline = document.createElement("span");
    resultInline.className = "tc-result-inline";
    resultInline.textContent = String(call.result_text).slice(0, 200);
    row.appendChild(resultInline);
  }

  // 详情容器（展开时显示在行下方）
  let detailEl = null;
  if (canExpand) {
    detailEl = document.createElement("div");
    detailEl.className = "tc-detail";
  }

  // 点击图标展开/折叠详情
  if (detailEl) {
    const icon = row.querySelector(".tc-icon");
    if (icon) {
      icon.style.cursor = "pointer";
      icon.title = isRunning ? "点击折叠" : "点击展开工具返回值";
      icon.addEventListener("click", (e) => {
        e.stopPropagation();
        const nowExpanded = row.classList.toggle("tool-call-row--expanded");
        // 展开后若详情在可视区外，滚动到可见位置（block:nearest 已可见时不滚动）
        if (nowExpanded) detailEl.scrollIntoView({ block: "nearest" });
      });
    }
  }

  // 构建详情内容
  if (detailEl) {
    if (isSubAgentCall) {
      const subCalls = Array.isArray(call.sub_tool_calls) ? call.sub_tool_calls : [];

      if (subCalls.length > 0) {
        const nest = document.createElement("div");
        nest.className = "tc-agent-nest";
        let subThinkIndex = 0;
        subCalls.forEach((sub) => {
          // 子 Agent 思考穿插在子工具调用之前（复用 renderThinkRow，与主 Agent 一致）
          if (sub.thinking) {
            subThinkIndex++;
            nest.appendChild(renderThinkRow(sub.thinking, { index: subThinkIndex }));
          }
          const subRow = renderToolCallRow(sub, { defaultExpanded: false });
          nest.appendChild(subRow.row);
          if (subRow.detail) nest.appendChild(subRow.detail);
        });

        // 子 Agent 返回值：可折叠行（图标 + 标签 + 展开详情），
        // 放在 tc-agent-nest 内与子工具调用对齐
        if (call.result_text) {
          nest.appendChild(_renderSubReplyRow(call.result_text));
        }

        detailEl.appendChild(nest);
      } else {
        if (isRunning) {
          // 运行中且尚无子工具调用记录
          const empty = document.createElement("div");
          empty.style.cssText = "font-size:0.7rem;color:var(--muted,#94a3b8);padding:0.2rem 0;";
          empty.textContent = "子Agent 执行中...";
          detailEl.appendChild(empty);
        } else if (call.result_text) {
          // 无子工具调用记录但有返回值
          detailEl.appendChild(_renderSubReplyRow(call.result_text));
        }
      }
    }

    // 文字结果
    if (call.result_text && !isSubAgentCall) {
      const textEl = document.createElement("div");
      textEl.className = "tc-detail-text";
      textEl.textContent = call.result_text;
      detailEl.appendChild(textEl);
    }

    // 图片结果（image_gen / 截图等）
    const imageUrls = Array.isArray(call.result_images) ? call.result_images.filter(Boolean) : [];
    if (imageUrls.length > 0 && !isSubAgentCall) {
      const imgWrap = document.createElement("div");
      imgWrap.className = "tc-detail-images";
      imageUrls.forEach((url) => {
        const img = document.createElement("img");
        img.className = "tc-detail-img";
        img.src = url;
        img.alt = "工具返回图片";
        img.loading = "lazy";
        img.addEventListener("click", (e) => { e.stopPropagation(); showImagePreview(url); });
        imgWrap.appendChild(img);
      });
      attachHorizontalScroll(imgWrap);
      detailEl.appendChild(imgWrap);
    }

    // sendfile 返回的文件/文件夹 → 优先用 result_file_info（正确文件名）
    const fileInfos = Array.isArray(call.result_file_info) ? call.result_file_info : [];
    if (fileInfos.length > 0 && !isSubAgentCall) {
      const fileWrap = document.createElement("div");
      fileWrap.className = "tc-detail-files";
      fileInfos.forEach((fi) => {
        if (fi && fi.file_path && fi.file_name) {
          if (fi.file_type === "folder") {
            // 文件夹卡片
            const card = document.createElement("div");
            card.className = "user-file-card user-folder-card";
            card.innerHTML = `<img class="user-file-card-icon" src="/image/\u6587\u4EF6\u5939.svg" alt="" /><div class="user-file-card-info"><span class="user-file-name" title="${escapeHtml(fi.file_path)}">${escapeHtml(fi.file_name)}</span><span class="user-file-ext">folder</span></div>`;
            fileWrap.appendChild(card);
          } else {
            const apiUrl = `/api/tool-file?path=${encodeURIComponent(fi.file_path)}&session=${encodeURIComponent(call.turn_id || '')}`;
            const card = renderUserFileCard(apiUrl, fi.file_name);
            fileWrap.appendChild(card);
          }
        }
      });
      attachHorizontalScroll(fileWrap);
      detailEl.appendChild(fileWrap);
    } else {
      const downloadFiles = call.result_download_files || [];
      if (downloadFiles.length > 0 && !isSubAgentCall) {
        const fileWrap = document.createElement("div");
        fileWrap.className = "tc-detail-files";
        downloadFiles.forEach((fileUrl) => {
          const fname = _extractToolFileName(fileUrl);
          const card = renderUserFileCard(fileUrl, fname);
          fileWrap.appendChild(card);
        });
        attachHorizontalScroll(fileWrap);
        detailEl.appendChild(fileWrap);
      }
    }

    // 无内容回退：工具已完成但无返回值时显示简略文本
    if (!isRunning && detailEl.children.length === 0 && !isSubAgentCall) {
      const fallback = document.createElement("div");
      fallback.className = "tc-detail-text";
      fallback.style.color = "var(--muted, #94a3b8)";
      fallback.style.fontStyle = "italic";
      fallback.textContent = "工具执行完成";
      detailEl.appendChild(fallback);
    }
  }

  return { row, detail: detailEl };
}

/* ===== 持久化工具调用列表（带折叠条 + 计时） ===== */
let renderAudioBubbleFn = null;
export function setRenderAudioBubble(fn) { renderAudioBubbleFn = fn; }

/** 计算 live 模式下的实时总耗时：从轮次开始到当前时间（单条工具计时已移除） */
function _calcLiveDuration(toolCalls, turnStartedAt) {
  if (!toolCalls || !toolCalls.length) return 0;
  const now = Date.now() / 1000;
  const start = turnStartedAt ? Number(turnStartedAt) : null;
  return Math.max(0, now - (start || now));
}

/* ===== 思考行（独立可展开折叠，类似工具调用行） ===== */
function renderThinkRow(content, options = {}) {
  const isLive = !!options.live;
  const defaultExpanded = isLive || !!options.defaultExpanded;
  const index = options.index || 1;

  const row = document.createElement("div");
  row.className = "think-row" + (isLive ? " think-row--live" : " think-row--done") + (defaultExpanded ? " think-row--expanded" : "");

  // 图标（点击展开/折叠）
  const icon = document.createElement("img");
  icon.className = "think-row-icon";
  icon.src = "/image/think.svg";
  icon.alt = "";
  icon.style.cursor = "pointer";
  icon.title = "点击展开/折叠思考";
  row.appendChild(icon);

  // 标签
  const label = document.createElement("span");
  label.className = "think-row-label";
  label.textContent = "Thought #" + index;
  row.appendChild(label);

  // 详情（思考内容）
  const detail = document.createElement("div");
  detail.className = "think-row-detail";
  detail.textContent = content;

  icon.addEventListener("click", (e) => {
    e.stopPropagation();
    row.classList.toggle("think-row--expanded");
  });

  row.appendChild(detail);
  return row;
}

function renderPersistentToolCalls(toolCalls, options = {}) {
  if (!toolCalls || !toolCalls.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "tool-call-list-wrap tool-call-list-wrap--persistent";

  const totalCount = toolCalls.length;
  const totalDuration = (options.duration != null) ? options.duration : getToolCallsTotalDuration(toolCalls);
  const isLive = !!options.live;
  const turnStartedAt = options.turnStartedAt;
  const reflections = Array.isArray(options.reflections) ? options.reflections : [];

  // 折叠条
  const toggle = document.createElement("div");
  toggle.className = "tc-list-toggle";
  const toggleArrow = document.createElement("span");
  toggleArrow.className = "tc-list-toggle-arrow";
  const toggleText = document.createElement("span");
  const updateToggleText = (elapsedSec) => {
    const dur = isLive ? elapsedSec : totalDuration;
    toggleText.textContent = `调用 ${totalCount} 个工具 · 用时 ${formatDuration(dur)}`;
  };
  updateToggleText(isLive ? _calcLiveDuration(toolCalls, turnStartedAt) : totalDuration);
  toggle.appendChild(toggleArrow);
  toggle.appendChild(toggleText);

  // 计时器（live 模式：每秒刷新轮次总计时，单条工具计时已移除）
  let timerId = null;
  if (isLive) {
    timerId = setInterval(() => {
      // 更新折叠条总计：从轮次开始到当前时间
      updateToggleText(_calcLiveDuration(toolCalls, turnStartedAt));
    }, 1000);
    wrap._stopTimer = () => { if (timerId) { clearInterval(timerId); timerId = null; } };
  }

  toggle.addEventListener("click", () => {
    const expanded = wrap.classList.toggle("tool-call-list-wrap--expanded");
    // 切换 body 显隐由 CSS 控制
  });
  wrap.appendChild(toggle);

  // body 容器
  const body = document.createElement("div");
  body.className = "tc-list-toggle-body";

  // 将 reflections 渲染为思考块，按位置穿插在工具调用之间
  const reflectionMap = new Map();
  reflections.forEach((r) => {
    if (!r || !r.content) return;
    const idx = (r.between_calls != null) ? r.between_calls : -1;
    if (!reflectionMap.has(idx)) reflectionMap.set(idx, []);
    reflectionMap.get(idx).push(r.content);
  });

  let thinkIndex = 0;
  // live 模式下思考内容已通过 reflections 提供（带 between_calls 定位），
  // 此时 call.thinking 是同一份内容的冗余副本，不再重复渲染；
  // 历史模式（无 reflections）仍使用 call.thinking 作为唯一来源。
  const hasReflections = reflections.length > 0;

  toolCalls.forEach((call, ci) => {
    // 该工具调用前的思考块（between_calls 对应此位置）
    const preBlocks = reflectionMap.get(ci) || [];
    preBlocks.forEach((txt) => {
      thinkIndex++;
      body.appendChild(renderThinkRow(txt, { live: isLive, index: thinkIndex }));
    });
    // 思考记录（附属于该工具调用）—— 仅在没有 reflections 时渲染，避免重复
    if (call.thinking && !hasReflections) {
      thinkIndex++;
      body.appendChild(renderThinkRow(call.thinking, { live: isLive, index: thinkIndex }));
    }
    const { row, detail } = renderToolCallRow(call, { defaultExpanded: false, disableExpand: !!options.disableExpand });
    body.appendChild(row);
    if (detail) body.appendChild(detail);
  });

  // 末尾的未映射思考块
  const tailBlocks = reflectionMap.get(-1) || [];
  tailBlocks.forEach((txt) => {
    thinkIndex++;
    body.appendChild(renderThinkRow(txt, { live: isLive, index: thinkIndex }));
  });

  wrap.appendChild(body);
  return wrap;
}

/* ===== Live 工具调用增量更新（运行中） ===== */
function injectLiveToolCalls(typingEl, liveCalls, turnStartedAt, _reflections) {
  if (!typingEl || !liveCalls.length) return;
  const bubble = typingEl.querySelector(".msg-bubble") || typingEl;

  // 首次工具调用到达，移除三点加载动画
  const dots = bubble.querySelector(".typing-dots");
  if (dots) dots.remove();

  // 保存展开状态：记录哪些 tool-call-row 和 think-row 是展开的
  let expandedRows = new Set();
  let collapsedThinkRows = new Set();
  const oldWrap = bubble.querySelector(".tool-call-list-wrap");
  if (oldWrap) {
    oldWrap.querySelectorAll(".tool-call-row--expanded").forEach((r) => {
      const idx = Array.from(oldWrap.querySelectorAll(".tool-call-row")).indexOf(r);
      if (idx >= 0) expandedRows.add(idx);
    });
    oldWrap.querySelectorAll(".think-row").forEach((r, i) => {
      if (!r.classList.contains("think-row--expanded")) collapsedThinkRows.add(i);
    });
    if (oldWrap._stopTimer) oldWrap._stopTimer();
  }

  // 将 reflections 传给 renderPersistentToolCalls
  const newWrap = renderPersistentToolCalls(liveCalls, { live: true, reflections: _reflections, turnStartedAt: turnStartedAt });
  if (!newWrap) return;

  if (oldWrap) {
    oldWrap.replaceWith(newWrap);
  } else {
    bubble.appendChild(newWrap);
  }

  // 恢复展开状态
  if (expandedRows.size > 0 || collapsedThinkRows.size > 0) {
    const rows = newWrap.querySelectorAll(".tool-call-row");
    expandedRows.forEach((idx) => {
      if (idx < rows.length) {
        rows[idx].classList.add("tool-call-row--expanded");
      }
    });
    // 恢复思考行折叠状态（live 重建时默认展开，需回设为折叠）
    const thinkRows = newWrap.querySelectorAll(".think-row");
    thinkRows.forEach((row, i) => {
      if (collapsedThinkRows.has(i)) {
        row.classList.remove("think-row--expanded");
      }
    });
  }

  // 执行中默认展开，用户可折叠；完成后由 renderAssistantContent 控制默认折叠
  newWrap.classList.add("tool-call-list-wrap--expanded");
}

/* ===== 思考记录伪流式输出（介于工具调用之间） ===== */
function injectThinkStream(typingEl, thinkContent, options = {}) {
  if (!typingEl || !thinkContent) return;
  const bubble = typingEl.querySelector(".msg-bubble") || typingEl;

  // 如果已有 live 思考块且内容不同，将其"冻结"为普通思考块，再创建新的 live 块
  const existingLive = bubble.querySelector(".tc-think-stream--live");
  if (existingLive && existingLive.textContent !== String(thinkContent || "")) {
    // 停止旧块的动画
    if (existingLive._raf) { cancelAnimationFrame(existingLive._raf); existingLive._raf = null; }
    existingLive.classList.remove("tc-think-stream--live", "tc-think-stream--streaming");
  }

  // 创建新的 live 思考块（每次反思一个独立块，介于工具调用之间）
  let thinkBlock = bubble.querySelector(".tc-think-stream--live");
  if (!thinkBlock) {
    thinkBlock = document.createElement("div");
    thinkBlock.className = "tc-think-stream tc-think-stream--streaming tc-think-stream--live";
    // 插入到工具列表之前
    const listWrap = bubble.querySelector(".tool-call-list-wrap");
    if (listWrap) {
      bubble.insertBefore(thinkBlock, listWrap);
    } else {
      bubble.appendChild(thinkBlock);
    }
  }

  const full = String(thinkContent || "");
  const n = full.length;
  const charsPerSec = 120;
  const totalMs = Math.min(6000, Math.max(300, (n / charsPerSec) * 1000));
  const t0 = performance.now();
  let last = "";

  const cancel = () => {
    if (thinkBlock._raf) { cancelAnimationFrame(thinkBlock._raf); thinkBlock._raf = null; }
  };
  cancel();

  const frame = (now) => {
    const elapsed = now - t0;
    const p = Math.min(1, elapsed / totalMs);
    const k = Math.min(n, Math.floor(p * n));
    const snapshot = full.slice(0, k);
    if (snapshot !== last) {
      last = snapshot;
      thinkBlock.textContent = snapshot;
    }
    if (p < 1) {
      thinkBlock._raf = requestAnimationFrame(frame);
    } else {
      thinkBlock.textContent = full;
      thinkBlock.classList.remove("tc-think-stream--streaming");
      thinkBlock._raf = null;
    }
  };
  thinkBlock._raf = requestAnimationFrame(frame);
}

/* ===== 持久化思考链（兼容旧接口） ===== */
function renderPersistentThinkChain(thinkingChain) {
  if (!thinkingChain || !thinkingChain.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "think-list-wrap think-list-wrap--persistent think-list-wrap--expanded";
  thinkingChain.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "think-item";
    item.style.cursor = "pointer";
    const summary = document.createElement("div");
    summary.className = "think-item-summary";
    const summaryText = (entry.content || "").slice(0, 60).replace(/\n/g, " ");
    summary.innerHTML = `<span class="think-bullet">\u2022</span> <span class="think-label">${escapeHtml(summaryText || "思考")}</span>`;
    item.appendChild(summary);
    item._thinkContent = entry.content || "";
    item.addEventListener("click", () => {
      let detail = item.querySelector(".think-item-detail");
      if (detail) { detail.remove(); item.setAttribute("aria-expanded", "false"); return; }
      detail = document.createElement("pre");
      detail.className = "think-item-detail";
      detail.textContent = item._thinkContent;
      item.appendChild(detail);
      item.setAttribute("aria-expanded", "true");
    });
    wrap.appendChild(item);
  });
  return wrap;
}

/* ===== 旧版 think panel 兼容（保留导出，供外部调用） ===== */
function injectThinkPanel(typingEl, reflections) {
  if (!typingEl || !reflections || !reflections.length) return;
  // 新版直接用伪流式输出最新思考
  const latest = reflections[reflections.length - 1];
  if (latest && latest.content) {
    injectThinkStream(typingEl, latest.content);
  }
}

function updateThinkIndicatorText(indicator, reflections) {
  const count = reflections ? reflections.length : 0;
  if (indicator) {
    indicator.innerHTML = `<span class="think-indicator-icon">\u{1F9E0}</span> <span class="think-indicator-text">think (${count})${state.thinkExpanded ? " \u25BE" : " \u25B8"}</span>`;
  }
}

function toolCallImageUrls(call) {
  const urls = [];
  if (Array.isArray(call.result_images)) {
    call.result_images.forEach((url) => { if (typeof url === "string" && url) urls.push(url); });
  }
  return urls;
}

/* ===== SSE 触发式 live 工具调用（替代轮询） ===== */
function startPollLiveToolCalls(sessionId, typingEl, injectFn) {
  let active = true;
  let lastReflectionCount = 0;
  let collectedReflections = [];
  let turnStartedAt = null;
  let eventSource = null;
  let reconnectTimer = null;

  const handleSnapshot = (liveData) => {
    if (!active || !liveData) return;
    if (liveData.started_at && !turnStartedAt) {
      turnStartedAt = Number(liveData.started_at);
    }
    // 收集思考内容
    if (liveData.reflections && liveData.reflections.length > lastReflectionCount) {
      const newOnes = liveData.reflections.slice(lastReflectionCount);
      newOnes.forEach((r) => {
        if (r && r.content) {
          collectedReflections.push({ content: r.content, between_calls: liveData.tool_calls ? liveData.tool_calls.length : -1 });
        }
      });
      lastReflectionCount = liveData.reflections.length;
    }
    // 处理工具调用
    if (typingEl && injectFn && liveData.tool_calls && liveData.tool_calls.length > 0) {
      for (const tc of liveData.tool_calls) {
        if (tc.name === "__summarizer__" || tc.name === "summarizer") {
          if (!_shownSummarizerToasts) _shownSummarizerToasts = new Set();
          const key = tc.name + (tc.args ? JSON.stringify(tc.args) : '');
          if (!_shownSummarizerToasts.has(key)) {
            _shownSummarizerToasts.add(key);
            const action = (tc.args && tc.args.action) || "compress";
            showToast(`Agent 触发上下文压缩（${action}）`);
          }
        }
      }
      injectFn(typingEl, liveData.tool_calls, turnStartedAt, collectedReflections);
    }
  };

  const connect = () => {
    if (!active) return;
    try {
      eventSource = new EventSource(`/api/tool-calls/${encodeURIComponent(sessionId)}/stream`);
    } catch {
      // EventSource 不可用时回退轮询
      fallbackPoll();
      return;
    }
    eventSource.addEventListener("update", (e) => {
      try { handleSnapshot(JSON.parse(e.data)); } catch { /* ignore parse error */ }
    });
    eventSource.addEventListener("ping", () => { /* 心跳保活，无需处理 */ });
    eventSource.onerror = () => {
      if (eventSource) { eventSource.close(); eventSource = null; }
      if (active) {
        reconnectTimer = setTimeout(connect, 1000);
      }
    };
  };

  // 回退轮询（EventSource 不可用时）
  let pollTimer = null;
  const fallbackPoll = async () => {
    if (!active) return;
    try {
      const liveData = await api(`/api/tool-calls/${encodeURIComponent(sessionId)}/live`);
      handleSnapshot(liveData);
    } catch { /* ignore */ }
    if (active) pollTimer = setTimeout(fallbackPoll, 600);
  };

  connect();

  return () => {
    active = false;
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  };
}

export {
  injectThinkPanel, updateThinkIndicatorText,
  injectLiveToolCalls, injectThinkStream,
  toolCallImageUrls, renderPersistentToolCalls,
  renderPersistentThinkChain,
  renderToolCallRow,
  renderUserFileCard,
  attachHorizontalScroll,
  startPollLiveToolCalls,
  showImagePreview,
  showFilePreviewDialog,
  formatDuration,
  getToolCallsTotalDuration,
};
