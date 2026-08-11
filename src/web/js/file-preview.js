// file-preview.js -- 文件浮窗预览（替代原 edit 模式下的 Monaco 编辑器）
// 点击文件树中的文件或聊天中的文件卡片时弹窗查看内容

import { $, escapeHtml } from './utils.js';

const IMG_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico']);
const HTML_EXTS = new Set(['.html', '.htm']);
const TEXT_EXTS = new Set(['.txt', '.json', '.md', '.py', '.js', '.ts', '.css', '.xml', '.yaml', '.yml', '.toml',
  '.csv', '.tsv', '.log', '.env', '.ini', '.cfg', '.sh', '.bat', '.ps1', '.sql', '.r', '.go', '.rs', '.rb',
  '.php', '.swift', '.kt', '.scala', '.cpp', '.c', '.h', '.java', '.m', '.svg']);
const TABLE_EXTS = new Set(['.csv', '.tsv', '.xlsx', '.xls']);

let _currentFilePath = null;
let _currentContent = null;

/** 判断是否为图片（非SVG） */
function isImage(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && IMG_EXTS.has(ext.substring(dot));
}

/** 判断HTML */
function isHtml(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && HTML_EXTS.has(ext.substring(dot));
}

/** 判断文本文件 */
function isTextFile(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && TEXT_EXTS.has(ext.substring(dot));
}

/** 判断表格文件（CSV/TSV 文本按列着色；XLSX/XLS 由后端提取为 TSV 后同样按列着色） */
function isTableFile(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && TABLE_EXTS.has(ext.substring(dot));
}

/**
 * 打开文件预览浮窗
 * @param {string} filePath - 文件路径
 * @param {string} fileName - 文件名
 * @param {string} content - 文件内容（文本）或 base64 data URL（图片）
 * @param {object} opts - { status: 'new'|'modified'|'deleted'|'', onDownload: fn }
 */
export function openFilePreview(filePath, fileName, content, opts = {}) {
  _currentFilePath = filePath;
  _currentContent = content;

  const overlay = $('filePreviewOverlay');
  const nameEl = $('filePreviewName');
  const statusEl = $('filePreviewStatus');
  const body = $('filePreviewBody');
  const downloadBtn = $('filePreviewDownload');

  if (!overlay || !body) return;

  // 设置文件名
  if (nameEl) nameEl.textContent = fileName || filePath;

  // 设置状态标签
  if (statusEl) {
    statusEl.className = 'file-preview-status';
    const status = opts.status || '';
    if (status) {
      statusEl.textContent = status === 'new' ? '新增' : status === 'modified' ? '已修改' : '已删除';
      statusEl.classList.add(`file-preview-status--${status}`);
    } else {
      statusEl.textContent = '';
    }
  }

  // 下载按钮
  if (downloadBtn) {
    downloadBtn.onclick = () => {
      if (opts.onDownload) {
        opts.onDownload(filePath, fileName, content);
      } else {
        _downloadFile(fileName, content);
      }
    };
  }

  // 渲染内容
  body.innerHTML = '';
  if (isImage(fileName)) {
    _renderImage(body, content, fileName);
  } else if (isHtml(fileName) && !opts.asText) {
    _renderPlainText(body, content);
  } else if (isTableFile(fileName)) {
    _renderTable(body, content, fileName);
  } else if (isTextFile(fileName)) {
    _renderPlainText(body, content);
  } else if (content && content.startsWith && content.startsWith('data:')) {
    _renderImage(body, content, fileName);
  } else {
    _renderPlainText(body, content || '(空文件)');
  }

  overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  // 点击背景关闭
  overlay.onclick = (e) => {
    if (e.target === overlay) closeFilePreview();
  };

  // ESC 关闭
  document.addEventListener('keydown', _onEscClose);
}

/** 关闭文件预览 */
export function closeFilePreview() {
  const overlay = $('filePreviewOverlay');
  if (overlay) overlay.hidden = true;
  document.body.style.overflow = '';
  document.removeEventListener('keydown', _onEscClose);
  _currentFilePath = null;
  _currentContent = null;
}

function _onEscClose(e) {
  if (e.key === 'Escape') closeFilePreview();
}

function _renderImage(body, content, fileName) {
  const img = document.createElement('img');
  img.src = content;
  img.alt = fileName;
  img.style.maxWidth = '100%';
  img.style.display = 'block';
  img.style.margin = '0 auto';
  body.appendChild(img);
}

function _renderPlainText(body, content) {
  const text = content || '';
  const lines = text.split('\n');

  const wrap = document.createElement('div');
  wrap.className = 'fp-code-wrap';

  // 行号列
  const lineNos = document.createElement('div');
  lineNos.className = 'fp-line-nos';
  for (let i = 1; i <= lines.length; i++) {
    const span = document.createElement('span');
    span.textContent = i;
    lineNos.appendChild(span);
  }

  // 代码列（每行独立 span，可精确选中）
  const codeLines = document.createElement('div');
  codeLines.className = 'fp-code-lines';
  lines.forEach((line, i) => {
    const span = document.createElement('span');
    span.setAttribute('data-line', i + 1);
    span.textContent = line || '\u00A0';
    codeLines.appendChild(span);
  });

  wrap.appendChild(lineNos);
  wrap.appendChild(codeLines);
  body.appendChild(wrap);

  // 右键菜单：引用选中行
  codeLines.addEventListener('contextmenu', (e) => _onCodeContextMenu(e));
}

// ===== 表格预览（复用 plaintext 预览 UI，不同列不同颜色） =====

/** 按主题区分的列色板（暗色 / 亮色各一套，保证可读性） */
const TABLE_COLUMN_COLORS = {
  dark: ['#e06c75', '#61afef', '#98c379', '#e5c07b', '#c678dd', '#56b6c2', '#d19a66', '#f472b6', '#7f9cf5', '#4ade80'],
  light: ['#c0392b', '#2471a3', '#1e8449', '#b7950b', '#7d3c98', '#117a65', '#ca6f1e', '#a93226', '#2e86c1', '#229954'],
};

/** 判断分隔符：TSV 用 tab，CSV 用逗号，XLSX/XLS（后端已提取为 TSV）用 tab，其他按首行内容猜测 */
function _getDelimiter(fileName, content) {
  const ext = (fileName || '').toLowerCase();
  if (ext.endsWith('.tsv') || ext.endsWith('.xlsx') || ext.endsWith('.xls')) return '\t';
  if (ext.endsWith('.csv')) return ',';
  const firstLine = (content || '').split('\n')[0] || '';
  return firstLine.includes('\t') ? '\t' : ',';
}

/** 解析单行分隔符文本（支持引号包裹的字段，如 "a,b"） */
function _splitDelimited(line, delim) {
  const cells = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; }
        else inQuotes = false;
      } else cur += ch;
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === delim) {
      cells.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  return cells;
}

/** 表格预览：保留行号/选中引用交互，单元格按列着色 */
function _renderTable(body, content, fileName) {
  const text = content || '';
  const delim = _getDelimiter(fileName, text);
  const lines = text.split('\n');
  const colors = document.body.classList.contains('theme-dark') ? TABLE_COLUMN_COLORS.dark : TABLE_COLUMN_COLORS.light;

  const wrap = document.createElement('div');
  wrap.className = 'fp-code-wrap fp-table-wrap';

  // 行号列
  const lineNos = document.createElement('div');
  lineNos.className = 'fp-line-nos';
  for (let i = 1; i <= lines.length; i++) {
    const span = document.createElement('span');
    span.textContent = i;
    lineNos.appendChild(span);
  }

  // 数据列：每行一个 span，单元格按列序号着色，首行作为表头加粗
  const codeLines = document.createElement('div');
  codeLines.className = 'fp-code-lines';
  lines.forEach((line, i) => {
    const row = document.createElement('span');
    row.setAttribute('data-line', i + 1);
    const cells = _splitDelimited(line, delim);
    if (cells.length === 1 && !line.trim()) {
      row.textContent = '\u00A0';
    } else {
      cells.forEach((cell, ci) => {
        const cellEl = document.createElement('span');
        cellEl.className = 'fp-tbl-cell' + (i === 0 ? ' fp-tbl-cell--header' : '');
        cellEl.textContent = cell;
        cellEl.style.color = colors[ci % colors.length];
        row.appendChild(cellEl);
      });
    }
    codeLines.appendChild(row);
  });

  wrap.appendChild(lineNos);
  wrap.appendChild(codeLines);
  body.appendChild(wrap);

  // 右键菜单：引用选中行
  codeLines.addEventListener('contextmenu', (e) => _onCodeContextMenu(e));
}

function _onCodeContextMenu(e) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.toString().trim()) return;

  // 找到选中区域的起止行
  const range = sel.getRangeAt(0);
  const startEl = range.startContainer?.parentElement?.closest?.('[data-line]');
  const endEl = range.endContainer?.parentElement?.closest?.('[data-line]');
  if (!startEl || !endEl) return;

  const s = parseInt(startEl.getAttribute('data-line'));
  const endLine = parseInt(endEl.getAttribute('data-line'));
  if (isNaN(s) || isNaN(endLine)) return;

  const minLine = Math.min(s, endLine);
  const maxLine = Math.max(s, endLine);

  e.preventDefault();
  _showCodeRefMenu(e.clientX, e.clientY, minLine, maxLine);
}

function _showCodeRefMenu(x, y, startLine, endLine) {
  const existing = document.querySelector('.fp-context-menu');
  if (existing) existing.remove();

  const menu = document.createElement('div');
  menu.className = 'doc-context-menu fp-context-menu';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.style.position = 'fixed';
  menu.style.zIndex = '1100';

  const label = startLine === endLine ? `L${startLine}` : `L${startLine}-L${endLine}`;

  const item = document.createElement('div');
  item.className = 'doc-context-menu-item';
  item.textContent = `\u{1F517} 引用选中内容 (${label})`;
  item.addEventListener('click', () => {
    const filePath = _currentFilePath;
    if (filePath) {
      import('./edit-mode.js').then(m => m.addDocRef(filePath, startLine, endLine)).catch(() => {});
    }
    menu.remove();
    closeFilePreview();
  });
  menu.appendChild(item);

  document.body.appendChild(menu);

  const closeHandler = (ev) => {
    if (!menu.contains(ev.target)) {
      menu.remove();
      document.removeEventListener('click', closeHandler);
    }
  };
  setTimeout(() => document.addEventListener('click', closeHandler), 0);
}

function _downloadFile(fileName, content) {
  let url, type;
  if (content && content.startsWith && content.startsWith('data:')) {
    url = content;
  } else {
    const blob = new Blob([content || ''], { type: 'text/plain;charset=utf-8' });
    url = URL.createObjectURL(blob);
  }
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (!content?.startsWith?.('data:')) URL.revokeObjectURL(url);
}

/** 绑定关闭按钮 */
export function bindFilePreviewEvents() {
  const closeBtn = $('filePreviewClose');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeFilePreview);
  }
}
