// audio.js -- 麦克风录音（录制完成后自动发送）

import { $, showToast } from './utils.js';
import { state } from './state.js';

let renderAttachmentChipsFn = null;
export function setRenderAttachmentChips(fn) { renderAttachmentChipsFn = fn; }

const micBtn = $("micBtn");

function stopRecorderStream() {
  if (!state.recorderStream) return;
  state.recorderStream.getTracks().forEach((track) => {
    try { track.stop(); } catch { /* ignore */ }
  });
  state.recorderStream = null;
}

function setRecordingUi(recording) {
  if (!micBtn) return;
  micBtn.classList.toggle("is-recording", recording);
  micBtn.setAttribute("aria-pressed", recording ? "true" : "false");

  if (recording) {
    micBtn.title = "停止录音";
    micBtn.setAttribute("aria-label", "停止录音");
  } else {
    micBtn.title = micBtn.disabled ? "语音转文字（ASR）服务不可用" : "使用麦克风录音";
    micBtn.setAttribute("aria-label", "使用麦克风录音");
  }
}

function inferRecordedExtension(mimeType) {
  const mt = String(mimeType || "").toLowerCase();
  if (mt.includes("wav")) return ".wav";
  if (mt.includes("mpeg")) return ".mp3";
  if (mt.includes("mp4") || mt.includes("mpeg4")) return ".m4a";
  if (mt.includes("ogg")) return ".ogg";
  if (mt.includes("webm")) return ".webm";
  return ".wav";
}

function buildRecordedAudioFile(blob, mimeType) {
  const ext = inferRecordedExtension(mimeType || blob.type);
  const normalizedType = mimeType || blob.type || (ext === ".wav" ? "audio/wav" : "audio/webm");
  const file = new File([blob], `microphone${ext}`, { type: normalizedType });
  // 标记为语音输入（区别于上传的音频文件）：发送时走 voice_input 字段并阻塞 ASR 转文本
  file.__voiceInput = true;
  return file;
}

async function stopMicRecording() {
  if (!state.mediaRecorder) return;
  const recorder = state.mediaRecorder;
  const stopped = new Promise((resolve, reject) => {
    recorder.addEventListener("stop", () => {
      try {
        const blob = new Blob(state.recordedChunks, { type: state.recordingMimeType || recorder.mimeType || "audio/webm" });
        state.pendingFiles = state.pendingFiles.concat(buildRecordedAudioFile(blob, state.recordingMimeType || recorder.mimeType));
        if (renderAttachmentChipsFn) renderAttachmentChipsFn();
        resolve();
      } catch (err) {
        reject(err);
      } finally {
        state.recordedChunks = [];
        state.recordingMimeType = "";
        state.mediaRecorder = null;
        stopRecorderStream();
        setRecordingUi(false);
      }
    }, { once: true });
    recorder.addEventListener("error", (event) => {
      state.recordedChunks = [];
      state.recordingMimeType = "";
      state.mediaRecorder = null;
      stopRecorderStream();
      setRecordingUi(false);
      reject(event.error || new Error("录音失败"));
    }, { once: true });
  });
  recorder.stop();
  await stopped;
}

async function startMicRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new Error("当前浏览器不支持麦克风录音");
  }
  if (state.sending) return;

  // 语音转文字依赖 ASR 服务：先检查连通性，不通则提示并中止录音
  try {
    const { api } = await import('./api.js');
    const st = await api("/api/services/status");
    if (!st || !st.asr || !st.asr.ok) {
      showToast("语音转文字（ASR）服务不可用，无法录音");
      return;
    }
  } catch {
    showToast("无法检测语音转文字（ASR）服务状态");
    return;
  }

  const preferredTypes = [
    "audio/wav",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/ogg",
    "audio/webm;codecs=opus",
    "audio/webm",
  ];
  const supportedType = preferredTypes.find((type) => {
    try { return MediaRecorder.isTypeSupported(type); } catch { return false; }
  }) || "";

  state.recorderStream = await navigator.mediaDevices.getUserMedia({ audio: true });

  state.recordedChunks = [];
  state.recordingMimeType = supportedType;
  state.mediaRecorder = supportedType
    ? new MediaRecorder(state.recorderStream, { mimeType: supportedType })
    : new MediaRecorder(state.recorderStream);
  state.recordingMimeType = state.mediaRecorder.mimeType || supportedType;

  state.mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      state.recordedChunks.push(event.data);
    }
  });
  state.mediaRecorder.start();
  setRecordingUi(true);
}

async function toggleMicRecording() {
  if (!micBtn) return;
  // 防止连点：正在发送中 或 按钮已禁用时忽略
  if (state.sending || micBtn.disabled) return;
  micBtn.disabled = true;
  try {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      await stopMicRecording();
      // 录音完成后自动发送（根据当前模式选择发送函数）
      if (state.pendingFiles.length > 0 && !state.sending) {
        if (state.editMode) {
          const { sendEditChat } = await import('./edit-mode.js');
          await sendEditChat();
        } else {
          const { sendChat } = await import('./send.js');
          await sendChat();
          const { refreshTokens } = await import('./token-ring.js');
          refreshTokens();
        }
      }
    } else {
      await startMicRecording();
      micBtn.disabled = false;  // 开始录音成功后立即可用（供停止用）
      return;
    }
  } finally {
    // 仅在非录音状态时恢复按钮；sendChat/sendEditChat 完成后由各自负责恢复 micBtn
    if (!state.mediaRecorder || state.mediaRecorder.state !== "recording") {
      micBtn.disabled = false;
    }
  }
}

export {
  stopRecorderStream,
  setRecordingUi,
  inferRecordedExtension, buildRecordedAudioFile,
  stopMicRecording, startMicRecording, toggleMicRecording,
};
