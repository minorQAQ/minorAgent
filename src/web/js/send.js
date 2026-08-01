// send.js -- 发送消息 / 暂停任务

import { $, inferUploadKind, buildOptimisticUserContent, revokeBlobUrlStack, showToast } from './utils.js';
import { showConfirm } from './dialog.js';
import { api, streamApi } from './api.js';
import { startPollLiveToolCalls } from './toolcalls.js';
import { state } from './state.js';
import { updatePendingOverlay, clearPendingOverlay } from './pending-overlay.js';
import { renderVoiceTranscribingPlaceholder } from './chat-render.js';

let renderSessionsFn = null;
let renderMessagesFn = null;
let renderAttachmentChipsFn = null;
let appendThinkingIndicatorFn = null;
let injectLiveToolCallsFn = null;
let updateTodoOverlayFn = null;
let clearTodoOverlayFn = null;
let showPendingActionInThinkingFn = null;
let streamAssistantMessageFn = null;
let onSendStartFn = null;
let _audioAbort = null;  // 音频流的独立 AbortController，供打断用

/** 清理思考气泡：停止内部计时器后移除 DOM */
function _cleanupTypingEl(el) {
  if (!el) return;
  const wrap = el.querySelector(".tool-call-list-wrap");
  if (wrap && typeof wrap._stopTimer === "function") wrap._stopTimer();
  if (el.parentNode) el.remove();
}
let _audioGeneration = 0;  // 递增计数器，旧回调检测到不匹配后自动忽略
let _sendGeneration = 0;  // 递增计数器，防止旧 sendChat 的 finally/catch 污染共享状态

// ======================== 流式 TTS Web Audio 播放 ========================

/** 全局播放上下文 */
let _ttsContext = null;

function _ensureTtsContext(sampleRate) {
  if (!_ttsContext || _ttsContext.sampleRate !== sampleRate) {
    if (_ttsContext) {
      try { _ttsContext.close(); } catch { /* ignore */ }
    }
    _ttsContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
  }
  if (_ttsContext.state === "suspended") {
    _ttsContext.resume();
  }
  return _ttsContext;
}

function _stopAllTtsPlayback() {
  if (_ttsContext) {
    try { _ttsContext.close(); } catch { /* ignore */ }
    _ttsContext = null;
  }
}

/**
 * 播放 PCM f32le base64 音频块
 * @param {AudioContext} ctx
 * @param {string} b64Data - base64 编码的 f32le 数据
 * @param {number} sampleRate
 * @param {number} startTime - 从何时开始播放（AudioContext.currentTime）
 * @returns {number} 该块的时长（秒）
 */
function _playPcmChunk(ctx, b64Data, sampleRate, startTime) {
  const raw = Uint8Array.from(atob(b64Data), c => c.charCodeAt(0));
  const float32 = new Float32Array(raw.buffer);
  const buffer = ctx.createBuffer(1, float32.length, sampleRate);
  buffer.getChannelData(0).set(float32);

  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  const s = Math.max(startTime, ctx.currentTime + 0.01);
  source.start(s);
  return float32.length / sampleRate;
}

export function setSendDeps(deps) {
  renderSessionsFn = deps.renderSessions;
  renderMessagesFn = deps.renderMessages;
  renderAttachmentChipsFn = deps.renderAttachmentChips;
  appendThinkingIndicatorFn = deps.appendThinkingIndicator;
  injectLiveToolCallsFn = deps.injectLiveToolCalls;
  updateTodoOverlayFn = deps.updateTodoOverlay;
  clearTodoOverlayFn = deps.clearTodoOverlay;
  showPendingActionInThinkingFn = deps.showPendingActionInThinking;
  streamAssistantMessageFn = deps.streamAssistantMessage;
  onSendStartFn = deps.onSendStart;
}

const textInput = $("textInput");
const fileInput = $("fileInput");
const sendBtn = $("sendBtn");
const outputModeTrigger = $("outputModeTrigger");
const agentModeTrigger = $("agentModeTrigger");

function setSendBtnPauseMode(pauseMode) {
  const btn = sendBtn || $("sendBtn");
  if (!btn) return;
  if (pauseMode) {
    btn.classList.add("btn-pause");
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="2" width="4" height="12" rx="1"/><rect x="9" y="2" width="4" height="12" rx="1"/></svg>';
  } else {
    btn.classList.remove("btn-pause");
    btn.innerHTML = '<img src="/image/发送.svg" alt="" aria-hidden="true" class="send-btn-icon" />';
  }
}

let _lastSendTime = 0;
let _pausing = false;  // 防重入：防止 handlePauseClick 被并发调用导致多个确认对话框堆叠

async function handlePauseClick() {
  if (!state.sessionId || !state.sending || !state.abortController) return;
  // 防止发送后立即连击触发暂停
  if (Date.now() - _lastSendTime < 600) return;
  // 防止并发调用（例如双击导致多个 showConfirm 对话框堆叠）
  if (_pausing) return;
  _pausing = true;
  try {
    if (!await showConfirm("确认暂停当前任务？\n\n当前轮已完成的工具调用和思考将被保留，本轮以「已被用户手动暂停」结束。")) {
      _pausing = false;
      return;
    }
    // 先中断正在进行的请求，避免 sendChat 的 AbortError handler 与后续渲染产生竞态
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    // 通知后端结束本轮（保留已完成记录，追加暂停消息）
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    const data = await api("/api/chat/abort", { method: "POST", body: fd });
    state.sessionId = data.sessionId;
    state.sessions.length = 0;
    state.sessions.push(...(data.sessions || []));
    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();
    if (renderSessionsFn) renderSessionsFn();
    if (renderMessagesFn) renderMessagesFn(data.messages || []);
  } catch (e) {
    // 回退
  }
  state.sending = false;
  setSendBtnPauseMode(false);
  const pauseBtn = sendBtn || $("sendBtn");
  if (pauseBtn) pauseBtn.disabled = false;
  _pausing = false;
}

async function sendChat() {
  if (!state.sessionId || state.sending) return;
  const myGen = ++_sendGeneration;  // 标记本次 sendChat，防止旧实例的 finally/catch 污染状态
  const trimmed = (textInput || {}).value ? textInput.value.trim() : "";
  if (!trimmed && state.pendingFiles.length === 0) return;
  // 首次发送时，输入框从居中移至底部
  if (onSendStartFn) onSendStartFn();
  _lastSendTime = Date.now();
  state.sending = true;
  const sBtn = sendBtn || $("sendBtn");
  if (sBtn) sBtn.disabled = true;
  setSendBtnPauseMode(true);

  // Agent 运行中锁定会话UI：禁止切换/新建会话，但允许切换到 edit 列表
  const nsb = $("newSessionBtn");
  if (nsb) { nsb.disabled = true; nsb.style.pointerEvents = "none"; nsb.style.opacity = "0.35"; }
  const sl = $("sessionList");
  if (sl) sl.classList.add("session-locked");

  // 任务前文件快照（不阻塞 UI 更新）
  try { const m = await import('./edit-mode.js'); m.snapshotFilesForTask(); } catch {}

  const savedTextRaw = textInput ? textInput.value : "";
  const savedFiles = state.pendingFiles.slice();
  // 分离语音输入（麦克风录音）和普通文件（含上传的音频文件），排除文件夹占位
  const voiceInputFile = savedFiles.find((f) => f.__voiceInput) || null;
  const regularFiles = savedFiles.filter((f) => !f.__voiceInput && !f.__isRef && !(f.type && f.type.startsWith("folder/")));
  const hasVoiceInput = !!voiceInputFile;
  const priorMessages = JSON.parse(JSON.stringify(state.lastRenderedMessages));
  const blobUrls = [];
  const hadOptimisticMedia = regularFiles.length > 0 || hasVoiceInput;
  let sessionIdAtStart = state.sessionId;
  // 清除上次遗留的 human interaction 状态
  state._pendingHumanAction = false;
  clearPendingOverlay();

  // 打断正在播放的音频
  _audioGeneration++;  // 使旧回调失效
  _stopAllTtsPlayback();
  if (_audioAbort) {
    _audioAbort.abort();
    _audioAbort = null;
  }

  if (hadOptimisticMedia) {
    // 构建乐观渲染内容（普通文件 + 可选文本）
    const fileParts = regularFiles.map((f) => {
      const kind = inferUploadKind(f);
      if (kind === "image" || kind === "audio") {
        const u = URL.createObjectURL(f);
        blobUrls.push(u);
        return { kind, url: u, name: f.name };
      }
      return { kind, name: f.name };
    });

    if (hasVoiceInput) {
      // 语音输入：先渲染已有消息（含普通文件 + 用户输入的文本），再追加"语音转文字中"占位
      const optimisticContent = buildOptimisticUserContent(trimmed, fileParts);
      if (renderMessagesFn) {
        if (optimisticContent != null) {
          renderMessagesFn([...priorMessages, { role: "user", content: optimisticContent }]);
        } else {
          renderMessagesFn(priorMessages);
        }
      }
      renderVoiceTranscribingPlaceholder();
    } else {
      // 仅普通文件：乐观渲染图片/文件
      const optimisticContent = buildOptimisticUserContent(trimmed, fileParts);
      if (optimisticContent != null && renderMessagesFn) {
        renderMessagesFn([...priorMessages, { role: "user", content: optimisticContent }]);
      }
    }
    if (textInput) textInput.value = "";
    state.pendingFiles.length = 0;
    if (fileInput) fileInput.value = "";
    if (renderAttachmentChipsFn) renderAttachmentChipsFn();
  } else if (trimmed) {
    // 纯文本消息：立即乐观渲染用户消息，避免等待 API /start 响应
    if (renderMessagesFn) {
      renderMessagesFn([...priorMessages, { role: "user", content: trimmed }]);
    }
    if (textInput) textInput.value = "";
  }

  state.abortController = new AbortController();
  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("text", trimmed);
  // 普通文件追加到 files 字段；语音输入单独走 voice_input 字段（后端阻塞 ASR）
  regularFiles.forEach((f) => fd.append("files", f, f.name));
  if (voiceInputFile) {
    fd.append("voice_input", voiceInputFile, voiceInputFile.name);
  }
  let typingEl = null;
  try {
    const startData = await api("/api/chat/start", { method: "POST", body: fd });

    state.sessionId = startData.sessionId;
    state.sessions.length = 0;
    state.sessions.push(...(startData.sessions || []));
    if (!hadOptimisticMedia) {
      if (textInput) textInput.value = "";
      state.pendingFiles.length = 0;
      if (fileInput) fileInput.value = "";
      if (renderAttachmentChipsFn) renderAttachmentChipsFn();
    }
    if (renderSessionsFn) renderSessionsFn();
    const _isVoice = (outputModeTrigger && outputModeTrigger.dataset.value === "voice");
    // 语音模式下只追加用户消息气泡（保留旧消息），完整列表等流式 text 事件再刷新
    // 但若已通过乐观渲染显示了用户消息（含语音输入占位），则重新渲染全部消息以替换占位
    if (_isVoice && renderMessagesFn && !hadOptimisticMedia) {
      const startMsgs = startData.messages || [];
      const userMsg = startMsgs[startMsgs.length - 1];
      if (userMsg && userMsg.role === "user") {
        const current = (state.lastRenderedMessages || []).slice();
        current.push(userMsg);
        renderMessagesFn(current);
      }
    } else if (renderMessagesFn) {
      // 包括：文本模式、或语音输出模式但有乐观渲染/语音输入占位需要替换
      renderMessagesFn(startData.messages || []);
    }
    revokeBlobUrlStack(blobUrls);
    // 移除旧思考气泡（停止计时器后移除），避免双份
    document.querySelectorAll('.msg-typing').forEach(el => _cleanupTypingEl(el));
    typingEl = appendThinkingIndicatorFn ? appendThinkingIndicatorFn() : null;

    // Reset tool call expansion state
    state.liveToolCallExpanded = false;
    state.thinkExpanded = false;

    if (clearTodoOverlayFn) clearTodoOverlayFn();
    clearPendingOverlay();

    // 启动实时工具调用与反思轮询
    const stopToolPoll = startPollLiveToolCalls(state.sessionId, typingEl, injectLiveToolCallsFn);

    // 启动 todo_list 实时轮询
    let todoPollActive = true;
    let todoPollTimer = null;
    const pollTodoList = async () => {
      if (!todoPollActive) return;
      try {
        const todoData = await api(`/api/todo-list/${encodeURIComponent(state.sessionId)}`);
        if (todoData && todoData.has_todo && todoData.data && updateTodoOverlayFn) {
          updateTodoOverlayFn(todoData.data);
        }
      } catch { /* ignore */ }
      if (todoPollActive) todoPollTimer = setTimeout(pollTodoList, 2000);
    };
    pollTodoList();

    const fd2 = new FormData();
    fd2.append("session_id", state.sessionId);
    fd2.append("output_type", outputModeTrigger ? (outputModeTrigger.dataset.value || "text") : "text");
    fd2.append("agent_mode", agentModeTrigger ? (agentModeTrigger.dataset.value || "agent") : "agent");
    if (state.selectedModelId) {
      fd2.append("model_id", state.selectedModelId);
    }
    sessionIdAtStart = state.sessionId;

    if (_isVoice) {
      // ====== 流式 TTS ======
      _stopAllTtsPlayback();
      const gen = ++_audioGeneration;  // 当前请求的 generation，旧回调检测到不匹配就忽略
      let textRendered = false;
      let streamSessionId = sessionIdAtStart;
      let streamSessions = [];
      let streamPending = [];
      let nextPlayTime = 0;
      let sampleRate = 24000;
      let ctx = null;

      // 用独立的 AbortController 控制音频流
      _audioAbort = state.abortController;

      const streamPromise = streamApi("/api/chat/stream", {
        method: "POST",
        body: fd2,
        signal: state.abortController.signal,
        onEvent: (event) => {
          if (state.sessionId !== sessionIdAtStart) return;
          if (_audioGeneration !== gen) return;  // 被新请求打断，忽略旧回调

          if (event.type === "text" && !textRendered) {
            textRendered = true;
            streamSessionId = event.sessionId || sessionIdAtStart;
            streamSessions = event.sessions || [];
            streamPending = event.pending_actions || [];
            const msgs = event.messages || [];
            const last = msgs[msgs.length - 1];

            if (last && last.role === "assistant") {
              const head = msgs.slice(0, -1);
              if (renderMessagesFn) renderMessagesFn(head);
              // 同步 lastRenderedMessages 为完整消息列表，确保后续打断时 assistant 消息不丢失
              state.lastRenderedMessages.length = 0;
              state.lastRenderedMessages.push(...JSON.parse(JSON.stringify(msgs)));
              revokeBlobUrlStack(blobUrls);
              if (streamAssistantMessageFn) streamAssistantMessageFn(last);
            } else {
              if (renderMessagesFn) renderMessagesFn(msgs);
              revokeBlobUrlStack(blobUrls);
            }

            // 文字渲染完毕，释放按钮
            state.sending = false;
            setSendBtnPauseMode(false);
            const vBtn = sendBtn || $("sendBtn");
            if (vBtn) vBtn.disabled = false;

            state.sessionId = streamSessionId;
            state.sessions.length = 0;
            state.sessions.push(...streamSessions);
            if (renderSessionsFn) renderSessionsFn();
            updatePendingOverlay(streamPending);
            if (streamPending && streamPending.length > 0) {
              state._pendingHumanAction = true;
            }

            stopToolPoll();
            todoPollActive = false;
            if (todoPollTimer) clearTimeout(todoPollTimer);
            if (typingEl) _cleanupTypingEl(typingEl);
            typingEl = null;
          }

          if (event.type === "audio.start") {
            sampleRate = event.sample_rate || 24000;
            ctx = _ensureTtsContext(sampleRate);
            nextPlayTime = ctx.currentTime;
          }
          if (event.type === "audio.chunk" && event.data) {
            if (!ctx) ctx = _ensureTtsContext(sampleRate);
            nextPlayTime += _playPcmChunk(ctx, event.data, sampleRate, nextPlayTime);
          }
          if (event.type === "audio.error") {
            _stopAllTtsPlayback();
          }
        }
      });

      try {
        await streamPromise;
      } catch (e) {
        if (_audioGeneration !== gen) {
          // 已被新请求替代，清理残留
          if (typingEl) _cleanupTypingEl(typingEl);
          return;
        }
        if (!(e && e.name === "AbortError")) {
          _stopAllTtsPlayback();
        }
      }
      if (_audioAbort === state.abortController) _audioAbort = null;

    } else {
      // ====== 普通文字模式 ======
      const done = await api("/api/chat/complete", { method: "POST", body: fd2, signal: state.abortController.signal });

      if (state.sessionId !== sessionIdAtStart) {
        stopToolPoll();
        todoPollActive = false;
        if (todoPollTimer) clearTimeout(todoPollTimer);
        return;
      }

      try {
        const todoData = await api(`/api/todo-list/${encodeURIComponent(state.sessionId)}`);
        if (todoData && todoData.has_todo && todoData.data && updateTodoOverlayFn) {
          updateTodoOverlayFn(todoData.data);
        }
      } catch { /* ignore */ }

      stopToolPoll();
      todoPollActive = false;
      if (todoPollTimer) clearTimeout(todoPollTimer);

      state.sessionId = done.sessionId;
      state.sessions.length = 0;
      state.sessions.push(...(done.sessions || []));
      if (renderSessionsFn) renderSessionsFn();

      const messages = done.messages || [];
      const last = messages[messages.length - 1];
      const hasPending = done.pending_actions && done.pending_actions.length > 0;

      if (last && last.role === "assistant" && last.meta && last.meta.pending_action && typingEl) {
        if (showPendingActionInThinkingFn) showPendingActionInThinkingFn(typingEl, last);
        updatePendingOverlay(done.pending_actions);
        typingEl = null;
      } else if (hasPending && typingEl) {
        state._pendingHumanAction = true;
        // typingEl 中已有的 live 工具调用记录保持不变（由轮询积累），
        // 不调用 injectLiveToolCallsFn 以避免清除已展示的工具调用
        updatePendingOverlay(done.pending_actions);
      } else {
        if (typingEl) _cleanupTypingEl(typingEl);
        typingEl = null;
        if (last && last.role === "assistant") {
          const head = messages.slice(0, -1);
          if (renderMessagesFn) renderMessagesFn(head);
          revokeBlobUrlStack(blobUrls);
          if (streamAssistantMessageFn) await streamAssistantMessageFn(last);
        } else {
          if (renderMessagesFn) renderMessagesFn(messages);
          revokeBlobUrlStack(blobUrls);
        }
        updatePendingOverlay(done.pending_actions);
      }
    }
  } catch (e) {
    revokeBlobUrlStack(blobUrls);
    // 已被新请求替代，静默清理，不做任何渲染
    if (_sendGeneration !== myGen) {
      if (typingEl) _cleanupTypingEl(typingEl);
      return;
    }
    // 如果会话已切换，不渲染任何内容
    if (state.sessionId !== sessionIdAtStart) {
      if (typingEl) _cleanupTypingEl(typingEl);
      return;
    }
    if (e && e.name === "AbortError") {
      // 暂停由 handlePauseClick 统一处理渲染，此处不覆盖
      return;
    } else if (hadOptimisticMedia) {
      if (textInput) textInput.value = savedTextRaw;
      state.pendingFiles.length = 0;
      state.pendingFiles.push(...savedFiles);
      if (renderAttachmentChipsFn) renderAttachmentChipsFn();
      if (renderMessagesFn) renderMessagesFn(priorMessages);
    }
    if (typingEl) _cleanupTypingEl(typingEl);
    if (!(e && e.name === "AbortError")) {
      showToast(e.message || String(e));
    }
  } finally {
    // 仅当本次 sendChat 仍是最新请求时才清理共享状态
    if (_sendGeneration !== myGen) return;
    state.sending = false;
    state.abortController = null;
    // 解锁会话UI：恢复切换/新建会话能力
    const nsb2 = $("newSessionBtn");
    if (nsb2) { nsb2.disabled = false; nsb2.style.pointerEvents = ""; nsb2.style.opacity = ""; }
    const sl2 = $("sessionList");
    if (sl2) sl2.classList.remove("session-locked");
    if (state._pendingHumanAction) {
      // 保持"暂停"文字和样式，但不禁用按钮
      const pendBtn = sendBtn || $("sendBtn");
      if (pendBtn) pendBtn.disabled = false;
    } else {
      setSendBtnPauseMode(false);
      const fBtn = sendBtn || $("sendBtn");
      if (fBtn) fBtn.disabled = false;
    }
    // 延迟检测文件变更（等待文件监听器处理完）
    setTimeout(() => {
      try { import('./edit-mode.js').then(m => m.detectTaskFileChanges()); } catch {}
    }, 1500);
  }
}

export { sendChat, handlePauseClick, setSendBtnPauseMode };
