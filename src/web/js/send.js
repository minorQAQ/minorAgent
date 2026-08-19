// send.js -- 发送消息 / 暂停任务

import { $, inferUploadKind, buildOptimisticUserContent, revokeBlobUrlStack, showToast } from './utils.js';
import { showConfirm } from './dialog.js';
import { api, streamApi } from './api.js';
import { startPollLiveToolCalls } from './toolcalls.js';
import { state } from './state.js';
import { clearPendingOverlay } from './pending-overlay.js';
import { renderVoiceTranscribingPlaceholder } from './chat-render.js';

let renderSessionsFn = null;
let renderMessagesFn = null;
let renderMessagesIncrementalFn = null;
let renderAttachmentChipsFn = null;
let appendThinkingIndicatorFn = null;
let injectLiveToolCallsFn = null;
let clearTodoOverlayFn = null;
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
  renderMessagesIncrementalFn = deps.renderMessagesIncremental || null;
  renderAttachmentChipsFn = deps.renderAttachmentChips;
  appendThinkingIndicatorFn = deps.appendThinkingIndicator;
  injectLiveToolCallsFn = deps.injectLiveToolCalls;
  clearTodoOverlayFn = deps.clearTodoOverlay;
  streamAssistantMessageFn = deps.streamAssistantMessage;
  onSendStartFn = deps.onSendStart;
}

/** 运行期渲染：优先增量（只 append 新增消息，保证速度与连续性），
 *  无增量渲染器时回退全量。非运行态的查看/切换仍走全量重渲染。 */
function _renderRuntime(messages) {
  if (renderMessagesIncrementalFn) {
    renderMessagesIncrementalFn(messages);
  } else if (renderMessagesFn) {
    renderMessagesFn(messages);
  }
}

const textInput = $("textInput");
const fileInput = $("fileInput");
const sendBtn = $("sendBtn");

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

/** 将待发送的聊天区引用（用户引用）拼接为注入给 agent 的文本 */
function buildQuotesText() {
  const quotes = (state.pendingRefs || []).filter((r) => r && r.type === "quote" && r.text && r.text.trim());
  if (quotes.length === 0) return "";
  return quotes.map((q) => "【用户引用】\n" + q.text.trim()).join("\n\n");
}

/** 将待发送的文件/文件夹引用（拖拽产生的 @file:/@folder:）拼接为注入给 agent 的绝对路径文本 */
function buildRefsText() {
  const refs = (state.pendingRefs || []).filter((r) => r && r.type !== "quote" && (r.path || r.isFolder));
  if (refs.length === 0) return "";
  const root = state._docRootPath ? state._docRootPath.replace(/\\/g, "/").replace(/\/$/, "") : "";
  return refs.map((ref) => {
    // 外部引用路径已是绝对路径（统一为正斜杠），工作区引用需拼接 root
    const absPath = ref.isExternal
      ? String(ref.path || "").replace(/\\/g, "/")
      : (root + "/" + ref.path);
    const prefix = ref.isFolder ? "@folder:" : "@file:";
    const linePart = ref.startLine ? ` L${ref.startLine}-L${ref.endLine}` : "";
    return `${prefix}${absPath}${linePart}`;
  }).join("\n");
}

/** 清除已发送的引用（pendingRefs 与 pendingFiles 中的 ref/quote 条目） */
function clearQuoteRefs() {
  state.pendingRefs = (state.pendingRefs || []).filter((r) => r && r.type !== "quote");
  state.pendingFiles = state.pendingFiles.filter((f) => !(f && f.__isRef && f.type === "ref/quote"));
}

/** 清除已发送的文件/文件夹引用（仅清理 @file:/@folder:，保留用户引用） */
function clearFileRefs() {
  state.pendingRefs = (state.pendingRefs || []).filter((r) => r && r.type === "quote");
  state.pendingFiles = state.pendingFiles.filter((f) => !(f && f.__isRef && f.type !== "ref/quote"));
}

async function sendChat() {
  if (!state.sessionId || state.sending) return;
  const myGen = ++_sendGeneration;  // 标记本次 sendChat，防止旧实例的 finally/catch 污染状态
  const trimmed = (textInput || {}).value ? textInput.value.trim() : "";
  // 拖拽的文件/文件夹引用：以 @file:/@folder: 绝对路径形式并入发送文本（agent 收到路径本身）
  const refsText = buildRefsText();
  // 聊天区引用：以「用户引用」形式并入发送文本（agent 收到的内容为具体文字并注明来源）
  const quotesText = buildQuotesText();
  const effectiveText = [trimmed, refsText, quotesText].filter(Boolean).join("\n\n");
  const savedQuotes = (state.pendingRefs || []).filter((r) => r && r.type === "quote");
  const savedFileRefs = (state.pendingRefs || []).filter((r) => r && r.type !== "quote");
  if (!effectiveText && state.pendingFiles.length === 0) return;
  // 强制选择工作区：无工作区不允许开始对话（会话按工作区组织）
  if (!state.workspacePath) {
    showToast("请先选择工作区再开始对话（点击左侧栏「新增工作区」或顶栏文件夹图标）", "warning");
    try {
      const { switchToMode } = await import('./edit-mode.js');
      switchToMode("chat");
    } catch { /* ignore */ }
    return;
  }
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
      const optimisticContent = buildOptimisticUserContent(effectiveText, fileParts);
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
      const optimisticContent = buildOptimisticUserContent(effectiveText, fileParts);
      if (optimisticContent != null && renderMessagesFn) {
        renderMessagesFn([...priorMessages, { role: "user", content: optimisticContent }]);
      }
    }
    if (textInput) textInput.value = "";
    state.pendingFiles.length = 0;
    clearQuoteRefs();
    clearFileRefs();
    if (fileInput) fileInput.value = "";
    if (renderAttachmentChipsFn) renderAttachmentChipsFn();
  } else if (effectiveText) {
    // 纯文本/引用消息：立即乐观渲染用户消息，避免等待 API /start 响应
    if (renderMessagesFn) {
      renderMessagesFn([...priorMessages, { role: "user", content: effectiveText }]);
    }
    if (textInput) textInput.value = "";
    clearQuoteRefs();
    clearFileRefs();
  }

  state.abortController = new AbortController();
  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("text", effectiveText);
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
      clearQuoteRefs();
      clearFileRefs();
      if (fileInput) fileInput.value = "";
      if (renderAttachmentChipsFn) renderAttachmentChipsFn();
    }
    if (renderSessionsFn) renderSessionsFn();
    const _isVoice = state.outputMode === "voice";
    // 语音模式下只追加用户消息气泡（保留旧消息），完整列表等流式 text 事件再刷新
    // 但若已通过乐观渲染显示了用户消息（含语音输入占位），则重新渲染全部消息以替换占位
    if (_isVoice && renderMessagesFn && !hadOptimisticMedia) {
      const startMsgs = startData.messages || [];
      const userMsg = startMsgs[startMsgs.length - 1];
      if (userMsg && userMsg.role === "user") {
        const current = (state.lastRenderedMessages || []).slice();
        current.push(userMsg);
        _renderRuntime(current);
      }
    } else if (renderMessagesFn) {
      // 包括：文本模式、或语音输出模式但有乐观渲染/语音输入占位需要替换
      // 运行期增量渲染：乐观渲染已包含历史 + 用户消息时只 append 差异
      _renderRuntime(startData.messages || []);
    }
    revokeBlobUrlStack(blobUrls);
    // 移除旧思考气泡（停止计时器后移除），避免双份
    // 仅清理 chat 容器内的 typing 气泡；cron 容器有独立 typingEl，双模式并行时不可误删
    const _chatContainer = $("chatMessages");
    if (_chatContainer) {
      _chatContainer.querySelectorAll('.msg-typing').forEach(el => _cleanupTypingEl(el));
    }
    typingEl = appendThinkingIndicatorFn ? appendThinkingIndicatorFn() : null;

    // Reset tool call expansion state
    state.liveToolCallExpanded = false;
    state.thinkExpanded = false;

    // 新轮次开始：仅清空上一轮遗留的人机交互/审查请求（其注册表随轮次结束失效），
    // 不清空 todo——todo 是会话级全局状态，跨轮次保持（新 todo_list 到达时自动替换）
    clearPendingOverlay();

    // 启动实时工具调用与反思轮询（snapshot 同时驱动人工请求浮窗与 Todo 浮窗）
    const stopToolPoll = startPollLiveToolCalls(state.sessionId, typingEl, injectLiveToolCallsFn);

    const fd2 = new FormData();
    fd2.append("session_id", state.sessionId);
    fd2.append("output_type", state.outputMode || "text");
    // agent/plan 模式由思考档位派生（low/xhigh/ultra→agent，high/max→plan）
    const { getAgentModeFromLevel } = await import('./think-level.js');
    fd2.append("agent_mode", getAgentModeFromLevel(state.thinkingLevel));
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
            const msgs = event.messages || [];
            const last = msgs[msgs.length - 1];

            if (last && last.role === "assistant") {
              const head = msgs.slice(0, -1);
              _renderRuntime(head);
              // 同步 lastRenderedMessages 为完整消息列表，确保后续打断时 assistant 消息不丢失
              state.lastRenderedMessages.length = 0;
              state.lastRenderedMessages.push(...JSON.parse(JSON.stringify(msgs)));
              revokeBlobUrlStack(blobUrls);
              if (streamAssistantMessageFn) streamAssistantMessageFn(last);
            } else {
              _renderRuntime(msgs);
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

            stopToolPoll();
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
      // 阻塞等待轮次完成（期间人机交互浮窗与工具列表由 live snapshot 驱动）；
      // 响应返回即本轮已结束，不存在待确认项
      const done = await api("/api/chat/complete", { method: "POST", body: fd2, signal: state.abortController.signal });

      if (state.sessionId !== sessionIdAtStart) {
        stopToolPoll();
        return;
      }

      stopToolPoll();

      state.sessionId = done.sessionId;
      state.sessions.length = 0;
      state.sessions.push(...(done.sessions || []));
      if (renderSessionsFn) renderSessionsFn();

      const messages = done.messages || [];
      const last = messages[messages.length - 1];
      if (typingEl) _cleanupTypingEl(typingEl);
      typingEl = null;
      if (last && last.role === "assistant") {
        const head = messages.slice(0, -1);
        // 增量渲染：head 与已渲染内容一致时零重建，仅由 streamAssistantMessage 追加末条
        _renderRuntime(head);
        revokeBlobUrlStack(blobUrls);
        if (streamAssistantMessageFn) await streamAssistantMessageFn(last);
      } else {
        _renderRuntime(messages);
        revokeBlobUrlStack(blobUrls);
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
    // 发送失败：恢复被清除的引用 chips（引用已并入文本并清空，失败时补回）
    if (savedQuotes.length > 0) {
      state.pendingRefs.push(...savedQuotes);
      const haveRefs = new Set(
        state.pendingFiles.filter((f) => f && f.__isRef && f.type === "ref/quote").map((f) => f.refPath)
      );
      savedFiles.forEach((f) => {
        if (f && f.__isRef && f.type === "ref/quote" && !haveRefs.has(f.refPath)) {
          state.pendingFiles.push(f);
        }
      });
    }
    if (savedFileRefs.length > 0) {
      // 补回文件/文件夹引用（@file:/@folder:），避免失败后引用丢失
      const haveFileRefs = new Set(state.pendingFiles.filter((f) => f && f.__isRef && f.type !== "ref/quote").map((f) => f.refPath));
      savedFileRefs.forEach((f) => {
        if (!haveFileRefs.has(f.refPath)) state.pendingFiles.push(f);
      });
      state.pendingRefs.push(...savedFileRefs);
    }
    if (savedQuotes.length > 0 || savedFileRefs.length > 0) {
      if (renderAttachmentChipsFn) renderAttachmentChipsFn();
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
    setSendBtnPauseMode(false);
    const fBtn = sendBtn || $("sendBtn");
    if (fBtn) fBtn.disabled = false;
    // 文件变更由 git 状态着色（/api/workspace/git-status）驱动，此处无需检测
  }
}

export { sendChat, handlePauseClick, setSendBtnPauseMode };
