// dialog.js -- 自定义弹窗（替代浏览器原生 alert/confirm/prompt）
// 两端（Web + Electron）统一使用的应用内弹窗

function createOverlay() {
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay';
  return overlay;
}

function createBox(type) {
  const box = document.createElement('div');
  box.className = 'dialog-box';
  return box;
}

/**
 * 显示提示弹窗（替代 alert），用户点击"确定"后关闭。
 * @param {string} message
 * @returns {Promise<void>}
 */
export function showAlert(message) {
  return new Promise((resolve) => {
    const overlay = createOverlay();
    const box = createBox('alert');

    const msg = document.createElement('p');
    msg.className = 'dialog-message';
    msg.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'dialog-actions';

    const okBtn = document.createElement('button');
    okBtn.className = 'dialog-btn dialog-btn--ok';
    okBtn.textContent = '确定';

    actions.appendChild(okBtn);
    box.appendChild(msg);
    box.appendChild(actions);
    overlay.appendChild(box);

    const close = () => {
      try { overlay.remove(); } catch { overlay.style.display = 'none'; }
      resolve();
    };

    okBtn.addEventListener('click', (e) => { e.stopPropagation(); close(); });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape' || e.key === 'Enter') {
        document.removeEventListener('keydown', onKey);
        close();
      }
    });

    document.body.appendChild(overlay);
    okBtn.focus();
  });
}

/**
 * 确认弹窗（替代 confirm），返回用户选择。
 * @param {string} message
 * @returns {Promise<boolean>}
 */
export function showConfirm(message) {
  return new Promise((resolve) => {
    const overlay = createOverlay();
    const box = createBox('confirm');

    const msg = document.createElement('p');
    msg.className = 'dialog-message';
    msg.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'dialog-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'dialog-btn dialog-btn--cancel';
    cancelBtn.textContent = '取消';

    const okBtn = document.createElement('button');
    okBtn.className = 'dialog-btn dialog-btn--ok';
    okBtn.textContent = '确定';

    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    box.appendChild(msg);
    box.appendChild(actions);
    overlay.appendChild(box);

    const close = (result) => {
      try { overlay.remove(); } catch { overlay.style.display = 'none'; }
      resolve(result);
    };

    okBtn.addEventListener('click', (e) => { e.stopPropagation(); close(true); });
    cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); close(false); });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close(false);
    });
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', onKey);
        close(false);
      }
    });

    document.body.appendChild(overlay);
    okBtn.focus();
  });
}

/**
 * 输入弹窗（替代 prompt），返回用户输入的字符串，取消返回 null。
 * @param {string} message
 * @param {string} [defaultValue='']
 * @returns {Promise<string|null>}
 */
export function showPrompt(message, defaultValue = '') {
  return new Promise((resolve) => {
    const overlay = createOverlay();
    const box = createBox('prompt');

    const msg = document.createElement('p');
    msg.className = 'dialog-message';
    msg.textContent = message;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'dialog-input';
    input.value = defaultValue;

    const actions = document.createElement('div');
    actions.className = 'dialog-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'dialog-btn dialog-btn--cancel';
    cancelBtn.textContent = '取消';

    const okBtn = document.createElement('button');
    okBtn.className = 'dialog-btn dialog-btn--ok';
    okBtn.textContent = '确定';

    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    box.appendChild(msg);
    box.appendChild(input);
    box.appendChild(actions);
    overlay.appendChild(box);

    const close = (result) => {
      try { overlay.remove(); } catch { overlay.style.display = 'none'; }
      resolve(result);
    };

    okBtn.addEventListener('click', (e) => { e.stopPropagation(); close(input.value); });
    cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); close(null); });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close(null);
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') close(input.value);
      if (e.key === 'Escape') close(null);
    });

    document.body.appendChild(overlay);
    input.focus();
    input.select();
  });
}
