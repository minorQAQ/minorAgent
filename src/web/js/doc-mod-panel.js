// doc-mod-panel.js -- 文档修改面板：展示会话中所有修改/新增/删除的文件
// 每个文件右侧有 ✓（保留/接受）和 ✕（撤销/拒绝）按钮

import { $, escapeHtml, showToast } from './utils.js';

function _updateBadge(show) {
  try {
    import('./action-bar.js').then(m => m.setActionBadge('doc', show));
  } catch {}
}

/** 文档修改列表，格式: { filePath: { original, current, type: 'new'|'modified'|'deleted' } } */
let _modifications = {};

/**
 * 更新文档修改数据
 * @param {object} mods - 修改对象
 */
export function setDocModifications(mods) {
  _modifications = mods || {};
  _updateBadge(Object.keys(_modifications).length > 0);
}

/**
 * 渲染文档修改面板
 */
export function renderDocModPanel() {
  const list = $('docModList');
  const actions = $('docModActions');
  if (!list || !actions) return;

  const entries = Object.entries(_modifications);
  if (entries.length === 0) {
    list.innerHTML = '<div style="padding:1rem;color:#94a3b8;font-size:0.82rem;text-align:center;">暂无文档变更</div>';
    actions.hidden = true;
    return;
  }

  actions.hidden = false;
  list.innerHTML = '';

  entries.forEach(async ([filePath, mod]) => {
    const item = document.createElement('div');
    item.className = `doc-mod-item doc-mod-item--${mod.type}`;
    item.dataset.file = filePath;

    const infoDiv = document.createElement('div');
    infoDiv.className = 'doc-mod-item-info';

    const typeLabel = document.createElement('span');
    typeLabel.className = 'doc-mod-item-tag';
    typeLabel.textContent = mod.type === 'new' ? '新增' : mod.type === 'modified' ? '修改' : '删除';
    if (mod.snapshotIdx) typeLabel.title = '第 ' + mod.snapshotIdx + ' 步变更';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'doc-mod-item-name';
    const parts = filePath.replace(/[\\/]+$/, '').split(/[\\/]/);
    nameSpan.textContent = parts[parts.length - 1] || filePath;
    nameSpan.title = filePath;

    infoDiv.appendChild(typeLabel);
    infoDiv.appendChild(nameSpan);

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'doc-mod-item-actions';

    const acceptBtn = document.createElement('button');
    acceptBtn.className = 'doc-mod-accept';
    acceptBtn.innerHTML = '&#x2713;';
    acceptBtn.title = '保留修改';
    acceptBtn.addEventListener('click', () => acceptModification(filePath));

    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'doc-mod-reject';
    rejectBtn.innerHTML = '&#x2715;';
    rejectBtn.title = '撤销修改';
    rejectBtn.addEventListener('click', () => rejectModification(filePath));

    actionsDiv.appendChild(acceptBtn);
    actionsDiv.appendChild(rejectBtn);

    item.appendChild(infoDiv);
    item.appendChild(actionsDiv);

    // 如果有旧内容，计算并显示行级 diff
    // - modified: 新旧内容行级 diff（新增/修改行黄色，删除行红色）
    // - deleted: 整个旧内容按删除行（红色）展示
    if ((mod.type === 'modified' || mod.type === 'deleted') && mod.oldContent != null) {
      const diffDiv = document.createElement('div');
      diffDiv.className = 'doc-mod-item-diff';
      diffDiv.hidden = true;
      item.appendChild(diffDiv);

      item.style.cursor = 'pointer';
      item.addEventListener('click', async (ev) => {
        if (ev.target.closest('.doc-mod-accept, .doc-mod-reject')) return;
        if (diffDiv.hidden) {
          try {
            const { computeLineDiff } = await import('./edit-mode.js');
            let diffs;
            if (mod.type === 'deleted') {
              // 删除文件：文件已不存在，整个旧内容按删除行（红色）展示
              const oldLines = String(mod.oldContent || '').split('\n');
              diffs = oldLines.length > 0
                ? [{ type: 'remove', startLine: 1, endLine: oldLines.length, lines: oldLines }]
                : [];
            } else {
              // 修改文件：读取当前内容并与旧内容做行级 diff
              const rootPath = (await import('./state.js')).state._docRootPath;
              const { readTextFile } = await import('./electron-api.js');
              const currentContent = await readTextFile(filePath, rootPath);
              diffs = computeLineDiff(mod.oldContent, currentContent) || [];
            }
            diffDiv.innerHTML = diffs.map(d => {
              const cls = d.type === 'add' ? 'diff-add' : 'diff-remove';
              const info = d.type === 'add'
                ? `+${d.startLine}${d.endLine !== d.startLine ? '-' + d.endLine : ''}`
                : `-${d.startLine}${d.endLine !== d.startLine ? '-' + d.endLine : ''}`;
              return `<div class="diff-line ${cls}"><span class="diff-ln">${info}</span><span class="diff-text">${escapeHtml(d.lines.join('\n'))}</span></div>`;
            }).join('') || '<div class="diff-line">无差异</div>';
            diffDiv.hidden = false;
          } catch { diffDiv.innerHTML = '<div class="diff-line">无法加载差异</div>'; diffDiv.hidden = false; }
        } else {
          diffDiv.hidden = true;
        }
      });
    }

    list.appendChild(item);
  });
}

/** 接受单个文件修改 */
async function acceptModification(filePath) {
  try {
    const { acceptFileModification } = await import('./edit-mode.js');
    await acceptFileModification(filePath);
    // 从本地列表中移除
    delete _modifications[filePath];
    setDocModifications(_modifications);
    renderDocModPanel();
    const { renderDocTree } = await import('./edit-mode.js');
    if (renderDocTree) renderDocTree();
    showToast('已接受: ' + (filePath.replace(/[\\/]/g, '/').split('/').pop()));
  } catch (e) {
    showToast('接受修改失败: ' + (e.message || e));
  }
}

/** 撤销单个文件修改 */
async function rejectModification(filePath) {
  try {
    const { rejectFileModification } = await import('./edit-mode.js');
    await rejectFileModification(filePath);
    delete _modifications[filePath];
    setDocModifications(_modifications);
    renderDocModPanel();
    const { renderDocTree } = await import('./edit-mode.js');
    if (renderDocTree) renderDocTree();
    showToast('已撤销: ' + (filePath.replace(/[\\/]/g, '/').split('/').pop()));
  } catch (e) {
    showToast('撤销修改失败: ' + (e.message || e));
  }
}

/** 打开/关闭文档修改面板 */
export function toggleDocModPanel(show) {
  const panel = $('docModPanel');
  if (!panel) return;
  if (show) {
    setDocModifications(_modifications);
    renderDocModPanel();
  }
  panel.hidden = !show;
}

/** 关闭文档面板并同步按钮状态 */
function _closeDocPanel() {
  const panel = $('docModPanel');
  if (panel) panel.hidden = true;
  const btn = $('actionDocBtn');
  if (btn) btn.classList.remove('is-active');
  import('./action-bar.js').then(m => m.deactivateAllActionPanels()).catch(() => {});
}

/** 绑定面板事件 */
export function bindDocModEvents() {
  const closeBtn = $('docModClose');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      _closeDocPanel();
    });
  }

  const acceptAllBtn = $('docModAcceptAll');
  if (acceptAllBtn) {
    acceptAllBtn.addEventListener('click', async () => {
      try {
        const filePaths = Object.keys(_modifications);
        const { acceptFileModification } = await import('./edit-mode.js');
        for (const fp of filePaths) { await acceptFileModification(fp); }
        // 清空本地状态
        Object.keys(_modifications).forEach(k => delete _modifications[k]);
        setDocModifications(_modifications);
        renderDocModPanel();
        const { renderDocTree } = await import('./edit-mode.js');
        if (renderDocTree) renderDocTree();
        showToast('已全部接受 ' + filePaths.length + ' 个文件变更');
        _closeDocPanel();
      } catch (e) {
        showToast(e.message || String(e));
      }
    });
  }

  const rejectAllBtn = $('docModRejectAll');
  if (rejectAllBtn) {
    rejectAllBtn.addEventListener('click', async () => {
      try {
        const filePaths = Object.keys(_modifications);
        const { rejectFileModification } = await import('./edit-mode.js');
        for (const fp of filePaths) { await rejectFileModification(fp); }
        Object.keys(_modifications).forEach(k => delete _modifications[k]);
        setDocModifications(_modifications);
        renderDocModPanel();
        const { renderDocTree } = await import('./edit-mode.js');
        if (renderDocTree) renderDocTree();
        showToast('已全部撤销 ' + filePaths.length + ' 个文件变更');
        _closeDocPanel();
      } catch (e) {
        showToast(e.message || String(e));
      }
    });
  }
}
