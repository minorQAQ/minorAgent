// terminal.js -- 内置 PowerShell 终端（原生管道，多标签）
// 主进程 spawn powershell.exe，stdin/stdout 经 IPC 桥接；前端自绘终端 UI。
// 面板折叠不 kill（仅隐藏）；标签 x 单个 kill；右上角 x 确认后 kill 全部。
// 颜色全部映射主题 CSS 变量，随主题变化。

import { $, showToast } from './utils.js';
import { showConfirm } from './dialog.js';
import { state } from './state.js';

/** 终端实例：{ id(主进程), title, cwd, pane, outEl, alive } */
let terminals = [];
let activeId = null;
let _dockVisible = false;

// ---------- ANSI 解析（CSI SGR 颜色 → 主题色 class；其余控制序列忽略） ----------
const ANSI_FG = {
  '0': '', '30': 't-fg-muted', '31': 't-fg-danger', '32': 't-fg-success',
  '33': 't-fg-warning', '34': 't-fg-accent', '35': 't-fg-purple', '36': 't-fg-cyan',
  '37': '', '90': 't-fg-muted', '91': 't-fg-danger', '92': 't-fg-success',
  '93': 't-fg-warning', '94': 't-fg-accent', '95': 't-fg-purple', '96': 't-fg-cyan', '97': '',
};
const ANSI_BG = {
  '40': 't-bg-dark', '41': 't-bg-danger', '42': 't-bg-success', '43': 't-bg-warning',
  '44': 't-bg-accent', '47': '',
};

/** 把含 ANSI 序列的文本转为安全的 HTML 片段（SGR 颜色映射，其他 CSI 忽略） */
export function ansiToHtml(text) {
  let html = '';
  let i = 0;
  let curCls = '';
  const n = text.length;
  while (i < n) {
    const ch = text[i];
    if (ch === '\x1b' && text[i + 1] === '[') {
      // CSI: \x1b[ ... 最终字符（A-Z 或 @-~）
      let j = i + 2;
      while (j < n && !/[A-Za-z@-~]/.test(text[j])) j++;
      if (j < n) {
        const params = text.slice(i + 2, j);
        const final = text[j];
        if (final === 'm') {
          // SGR：最后一个参数决定样式
          const codes = params.split(';').filter(Boolean);
          const last = codes[codes.length - 1] || '0';
          if (last === '0') {
            curCls = '';
          } else if (ANSI_FG[last] !== undefined) {
            curCls = ANSI_FG[last];
          } else if (ANSI_BG[last] !== undefined) {
            curCls = ANSI_BG[last];
          } else {
            // 亮度/其他：忽略
          }
        }
        // 其余 CSI（光标移动等）忽略
        i = j + 1;
        continue;
      }
      i += 1;
      continue;
    }
    if (ch === '\r') {
      i += 1;
      continue; // \r\n 中的 \r 忽略，单独 \r 不处理（简化）
    }
    if (ch === '\n') {
      html += '</span>\n';
      curCls = ''; // 换行后颜色状态简化重置（避免跨行 span 混乱）
      i += 1;
      continue;
    }
    const esc = ch === '&' ? '&amp;' : ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : ch;
    html += curCls ? `<span class="${curCls}">${esc}</span>` : esc;
    i += 1;
  }
  if (curCls) html += '</span>';
  return html;
}

// ---------- 终端实例管理 ----------
function currentCwd() {
  const p = state.workspacePath || state.workspaceDefault;
  return p || '';
}

function wsName() {
  const p = state.workspacePath || state.workspaceDefault;
  if (!p) return 'workspace';
  const parts = p.replace(/[\\/]+$/, '').split(/[\\/]/);
  return parts[parts.length - 1] || 'workspace';
}

function ensureElectron() {
  if (!window.electronAPI?.spawnTerminal) {
    showToast('终端仅桌面版（Electron）可用');
    return false;
  }
  return true;
}

/** 新建一个 PowerShell 终端标签 */
export async function spawnTerminal() {
  if (!ensureElectron()) return null;
  try {
    const cwd = currentCwd();
    const { id, ok, error } = await window.electronAPI.spawnTerminal(cwd);
    if (!ok) {
      showToast('终端启动失败: ' + (error || '未知错误'));
      return null;
    }
    // 渲染标签 + 输出面板
    const tab = document.createElement('div');
    tab.className = 'term-tab';
    tab.dataset.tid = String(id);
    tab.innerHTML = `<span class="term-tab-title">PowerShell <span class="term-tab-ws">${escapeHtml(wsName())}</span></span>`;
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'term-tab-close';
    closeBtn.title = '关闭此终端（终止进程）';
    closeBtn.textContent = '\u2715';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      killTerminal(id);
    });
    tab.appendChild(closeBtn);
    tab.addEventListener('click', () => activateTerminal(id));
    // 标签插到 + 号之前，保证 [标签…][+] 在左、[×] 在右的布局
    const tabsBar = $('terminalTabs');
    const addBtn = tabsBar.querySelector('.term-tab-add');
    if (addBtn) tabsBar.insertBefore(tab, addBtn);
    else tabsBar.appendChild(tab);

    const pane = document.createElement('div');
    pane.className = 'term-pane';
    pane.dataset.tid = String(id);
    const outEl = document.createElement('div');
    outEl.className = 'term-out';
    pane.appendChild(outEl);
    $('terminalBody').appendChild(pane);

    terminals.push({ id, tab, pane, outEl, alive: true });
    activateTerminal(id);
    // 首次 spawn 时输出欢迎提示
    appendOutput(id, `PowerShell 已启动${cwd ? `（工作区: ${cwd}）` : ''}\r\n`);
    return id;
  } catch (e) {
    showToast('终端启动失败: ' + (e.message || e));
    return null;
  }
}

function getTerm(id) {
  return terminals.find((t) => t.id === id) || null;
}

function activateTerminal(id) {
  activeId = id;
  for (const t of terminals) {
    const isActive = t.id === id;
    t.tab.classList.toggle('active', isActive);
    t.pane.classList.toggle('active', isActive);
  }
  // 命令行（提示符+输入）挂载到活动面板输出末尾，观感等同真实终端的当前行
  const t = getTerm(id);
  if (!_cmdlineEl) buildCmdline(); // 兜底：initTerminal 尚未执行时按需构建
  const cl = _cmdlineEl;
  if (t && cl) {
    t.outEl.appendChild(cl);
    scrollPaneToBottom(t.pane);
  }
  const input = _cmdInput;
  if (input) {
    input.disabled = !t?.alive;
    input.focus();
  }
}

/** 滚动容器是 .term-pane（非 .term-out），输出追加后保持跟随底部 */
function scrollPaneToBottom(pane) {
  if (pane) pane.scrollTop = pane.scrollHeight;
}

function appendOutput(id, chunk) {
  const t = getTerm(id);
  if (!t) return;
  const html = ansiToHtml(chunk);
  const cl = _cmdlineEl;
  if (cl && cl.parentNode === t.outEl) {
    // 命令行保持在输出最后一行：新输出插在它之前
    cl.insertAdjacentHTML('beforebegin', html);
  } else {
    t.outEl.insertAdjacentHTML('beforeend', html);
  }
  scrollPaneToBottom(t.pane);
}

/** 单个终端关闭（kill 进程并移除标签） */
export function killTerminal(id) {
  const t = getTerm(id);
  if (!t) return;
  t.alive = false;
  try { window.electronAPI?.killTerminal(id); } catch { /* ignore */ }
  t.tab.remove();
  t.pane.remove();
  terminals = terminals.filter((x) => x.id !== id);
  if (activeId === id) {
    activeId = null;
    if (terminals.length > 0) activateTerminal(terminals[terminals.length - 1].id);
  }
  if (terminals.length === 0) {
    setDockVisible(false); // 全部关闭后隐藏面板
  }
}

/** 关闭全部终端（kill 所有进程 + 清空面板） */
export function killAllTerminals() {
  try { window.electronAPI?.killAllTerminals(); } catch { /* ignore */ }
  for (const t of terminals) {
    t.tab.remove();
    t.pane.remove();
  }
  terminals = [];
  activeId = null;
  setDockVisible(false);
}

/** 显示/折叠终端面板（不 kill，仅隐藏） */
export function setDockVisible(visible) {
  _dockVisible = !!visible;
  const dock = $('terminalDock');
  if (!dock) return;
  dock.hidden = !_dockVisible;
  if (_dockVisible && terminals.length > 0 && activeId == null) {
    activateTerminal(terminals[terminals.length - 1].id);
  }
}

/** 切换终端面板显隐；首次点击自动启动一个 PowerShell */
export function toggleTerminal() {
  if (!ensureElectron()) return;
  if (_dockVisible) {
    setDockVisible(false);
    return;
  }
  setDockVisible(true);
  if (terminals.length === 0) {
    spawnTerminal();
  } else if (activeId == null && terminals.length > 0) {
    activateTerminal(terminals[terminals.length - 1].id);
  }
}

// ---------- 输入 ----------
// 管道模式下 PowerShell 不回显提示符与命令，前端自行回显以还原真实终端观感
const _cmdHistory = [];
let _histIdx = -1; // -1 = 未在浏览历史
// 命令行元素引用：buildCmdline 构建后先处于游离态（未挂到 document），
// 不能用 getElementById 查找（查不到游离节点），必须用模块级引用持有
let _cmdlineEl = null;
let _cmdInput = null;

function echoCommand(text) {
  const t = getTerm(activeId);
  if (!t) return;
  const html = `<span class="t-fg-success">PS&gt;</span> ${escapeHtml(text)}\n`;
  const cl = _cmdlineEl;
  if (cl && cl.parentNode === t.outEl) cl.insertAdjacentHTML('beforebegin', html);
  else t.outEl.insertAdjacentHTML('beforeend', html);
  scrollPaneToBottom(t.pane);
}

function sendInput() {
  const input = _cmdInput;
  const t = getTerm(activeId);
  if (!t || !t.alive || !input) return;
  const text = input.value;
  input.value = '';
  _histIdx = -1;
  if (!text) return;
  if (_cmdHistory[_cmdHistory.length - 1] !== text) _cmdHistory.push(text);
  if (_cmdHistory.length > 200) _cmdHistory.shift();
  echoCommand(text);
  try { window.electronAPI.sendTerminalInput(activeId, text + '\r'); } catch { /* ignore */ }
}

/** ↑/↓ 浏览命令历史 */
function historyNav(dir) {
  const input = _cmdInput;
  if (!input || _cmdHistory.length === 0) return;
  if (_histIdx === -1) _histIdx = _cmdHistory.length;
  _histIdx += dir;
  if (_histIdx < 0) _histIdx = 0;
  if (_histIdx >= _cmdHistory.length) { _histIdx = -1; input.value = ''; return; }
  input.value = _cmdHistory[_histIdx];
  input.setSelectionRange(input.value.length, input.value.length);
}

/** 构建命令行元素（提示符 + 输入框）；由 activateTerminal 挂到活动面板输出末尾 */
function buildCmdline() {
  if (_cmdlineEl) return;
  const row = document.createElement('div');
  row.className = 'terminal-input-row';
  row.id = 'terminalCmdline';
  const prompt = document.createElement('span');
  prompt.className = 'terminal-prompt';
  prompt.id = 'terminalPrompt';
  prompt.textContent = 'PS>';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'terminal-input';
  input.id = 'terminalInput';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.placeholder = '输入命令，Enter 执行';
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); sendInput(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); historyNav(-1); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); historyNav(1); }
  });
  row.appendChild(prompt);
  row.appendChild(input);
  // 游离态持有引用；activateTerminal 首次挂载后才进入 document
  _cmdlineEl = row;
  _cmdInput = input;
}

// ---------- 事件绑定 ----------
let _bound = false;

export function initTerminal() {
  if (_bound) return;
  _bound = true;

  // 顶栏终端按钮：由 app.js document 委托统一绑定（toggleTerminal），
  // 此处仅移除占位样式
  const termBtn = $('terminalBtn');
  if (termBtn) termBtn.classList.remove('is-placeholder');

  // 命令行（提示符 + 输入）动态构建，挂到活动面板输出末尾，随内容滚动
  buildCmdline();

  // 点击终端区域任意处直接键入（焦点落到命令行输入框）
  const termBody = $('terminalBody');
  if (termBody) {
    termBody.addEventListener('click', () => {
      const input = _cmdInput;
      if (input && !input.disabled) input.focus();
    });
  }

  // 新标签 +
  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'term-tab-add';
  addBtn.title = '新建终端';
  addBtn.textContent = '+';
  addBtn.addEventListener('click', () => spawnTerminal());
  $('terminalTabs').appendChild(addBtn);

  // 右上角关闭全部（确认浮窗）
  const dockClose = document.createElement('button');
  dockClose.type = 'button';
  dockClose.className = 'term-dock-close';
  dockClose.title = '关闭全部终端（终止所有进程）';
  dockClose.textContent = '\u2715';
  dockClose.addEventListener('click', async () => {
    const ok = await showConfirm('确定关闭全部终端吗？\n将终止所有 PowerShell 进程。');
    if (ok) killAllTerminals();
  });
  $('terminalTabs').appendChild(dockClose);

  // 主进程数据推送
  if (window.electronAPI?.onTerminalData) {
    window.electronAPI.onTerminalData(({ id, chunk }) => appendOutput(id, chunk || ''));
    window.electronAPI.onTerminalExit(({ id, code }) => {
      const t = getTerm(id);
      if (!t) return;
      t.alive = false;
      t.tab.classList.add('term-tab--dead');
      appendOutput(id, `\r\n[进程已退出，code=${code == null ? '?' : code}]（关闭标签可移除）\r\n`);
      if (activeId === id && _cmdInput) _cmdInput.disabled = true;
    });
  }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
