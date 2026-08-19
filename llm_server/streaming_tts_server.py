#!/usr/bin/env python3
"""
VoxCPM 流式 TTS 服务 —— 按句分块合成，SSE 流式推送 PCM 音频。

使用 OpenBMB VoxCPM 模型（Whispera 同款），无需 Genie TTS。
配合前端 Web Audio API 实现边合成边播放，无需保存音频文件。

启动方式:
    python streaming_tts_server.py --port 8902 --model-path ./models/VoxCPM
"""

import os
import sys
import json
import base64
import time
import threading
import argparse
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# 抑制 PyTorch weight_norm 弃用警告（来自 voxcpm 内部）
warnings.filterwarnings("ignore", message=".*weight_norm.*deprecated.*")

# ======================== 配置区域 ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 启用 TF32 加速（Ampere+ GPU）
import torch
torch.set_float32_matmul_precision("high")

# 确保 torchaudio 已安装（VoxCPM 参考音频需要）
try:
    import torchaudio  # noqa: F401
except ImportError:
    pass  # 无参考音频时可选

# 默认参数（可通过命令行覆盖）
DEFAULT_MODEL_PATH = os.path.join(BASE_DIR, "models", "VoxCPM1__5")
DEFAULT_PORT = 8902
DEFAULT_MODEL_NAME = "VoxCPM1.5"   # 默认服务模型名（校验请求 body.model 用）
DEFAULT_API_KEY = ""               # 默认空：不校验 API Key（任意值放行）

# 参考音频（用于统一音色，同一人物说的一段话 + 对应文本）
# 如果配置了这对参数，所有合成都会克隆该音色，各句音色保持一致
DEFAULT_PROMPT_WAV = os.path.join(BASE_DIR, "reference_audio.wav")
DEFAULT_PROMPT_TEXT = "日子缓缓前行，不必急于追赶，照顾好自己的心情，认真过好当下的每一刻就足够了。"

# 音频质量参数
DEFAULT_CFG_VALUE = 1.5          # 音色贴合度 (1.0~3.0)，越高越贴近参考音频但可能不自然
DEFAULT_INFERENCE_STEPS = 15     # 推理步数 (4~30)，越高音质越好但越慢
# =========================================================

# 请求级取消标志
_cancel_flags: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()

# 当前活跃请求 ID（新请求到达时自动取消旧请求）
_current_request_id: str | None = None
_current_req_lock = threading.Lock()

# 模型锁（VoxCPM 只允许单线程使用，新请求取消旧请求后等待锁释放）
_model_lock = threading.Lock()


def set_cancel(request_id: str) -> None:
    with _cancel_lock:
        evt = _cancel_flags.get(request_id)
        if evt is None:
            evt = threading.Event()
            _cancel_flags[request_id] = evt
        evt.set()


def is_cancelled(request_id: str) -> bool:
    with _cancel_lock:
        evt = _cancel_flags.get(request_id)
        return evt is not None and evt.is_set()


def cancel_current_and_set(new_request_id: str) -> str | None:
    """取消当前活跃请求并注册新请求 ID，返回被取消的旧请求 ID。"""
    global _current_request_id
    with _current_req_lock:
        old = _current_request_id
        _current_request_id = new_request_id
    if old and old != new_request_id:
        set_cancel(old)
        # 若旧请求持有模型锁，强制释放以让新请求立即获取
        try:
            if _model_lock.locked():
                _model_lock.release()
        except RuntimeError:
            pass
        print(f"[VoxCPM TTS] 打断旧请求 {old}，开始新请求 {new_request_id}")
    return old


# Lazy-loaded model singleton
_model = None
_singleton_lock = threading.Lock()
_model_sample_rate = 24000


def _get_model(model_path: str):
    """延迟加载 VoxCPM 模型（线程安全）。"""
    global _model, _model_sample_rate
    if _model is not None:
        return _model, _model_sample_rate

    with _singleton_lock:
        if _model is not None:
            return _model, _model_sample_rate

        if "voxcpm" not in sys.modules:
            try:
                from voxcpm import VoxCPM  # type: ignore
            except ImportError:
                raise ImportError(
                    "无法导入 voxcpm 模块。请确保 Whispera-main 项目的 "
                    "voxcpm-tts-streaming-module/src 在 sys.path 中，"
                    "或 pip install 了 voxcpm 包。"
                )

        from voxcpm import VoxCPM  # type: ignore
        mp = _resolve_model_path(model_path)
        print(f"[VoxCPM TTS] 加载模型: {mp}")
        _model = VoxCPM(
            voxcpm_model_path=mp,
            enable_denoiser=False,
            optimize=True,
        )
        _model_sample_rate = int(_model.tts_model.sample_rate)
        print(f"[VoxCPM TTS] 模型加载成功，采样率: {_model_sample_rate} Hz")
        return _model, _model_sample_rate


def _resolve_model_path(model_path: str) -> str:
    """解析模型路径：支持多种命名格式。"""
    base = Path(model_path).expanduser().resolve()
    if not base.exists():
        raise FileNotFoundError(f"VoxCPM 模型路径不存在: {base}")

    # 1. 直接就是模型目录（有 config.json）
    if (base / "config.json").is_file():
        return str(base)

    # 2. 检查常见子目录名
    for sub in ["openbmb__VoxCPM2", "openbmb__VoxCPM1.5",
                "VoxCPM2", "VoxCPM1.5", "VoxCPM1__5"]:
        candidate = base / sub
        if candidate.is_dir() and (candidate / "config.json").is_file():
            return str(candidate)

    raise FileNotFoundError(
        f"在 {base} 下未找到 VoxCPM 模型（需要包含 config.json 的子目录，"
        f"如 openbmb__VoxCPM1.5/、VoxCPM1__5/ 等）"
    )


def _build_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _check_api_key(request: Request) -> str | None:
    """校验请求 API Key：服务未配置 key（空）时放行任意值；否则校验 Authorization / X-API-Key。

    返回 None 表示通过，否则返回错误提示文本。
    """
    api_key = _model_args.get("api_key", "")
    if not api_key:
        return None
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        provided = header[len("Bearer "):].strip()
    else:
        provided = request.headers.get("X-API-Key", "").strip()
    if provided == api_key:
        return None
    return "API Key 无效或缺失"


def _check_model_name(body: dict) -> str | None:
    """校验请求 modelname：服务未配置模型名（空）时放行任意值；否则要求 body.model 匹配。

    返回 None 表示通过，否则返回错误提示文本。
    """
    model_name = _model_args.get("model_name", "")
    if not model_name:
        return None
    if str(body.get("model") or "").strip() == model_name:
        return None
    return f"模型名不匹配: 期望 '{model_name}'，收到 '{body.get('model') or ''}'"


def _stream_audio_events(text: str, request_id: str, model_path: str):
    """生成 SSE 音频流事件（同步，在独立线程中运行）。"""
    import numpy as np

    try:
        model, sample_rate = _get_model(model_path)
    except Exception as e:
        yield _build_sse({"type": "audio.error", "request_id": request_id, "message": str(e)})
        return

    # 开始
    yield _build_sse({
        "type": "audio.start",
        "request_id": request_id,
        "sample_rate": sample_rate,
        "audio_format": "pcm_f32le",
    })

    chunk_index = 0
    total_samples = 0

    # 获取模型锁（前一请求已被 cancel_current_and_set 取消，锁应已释放）
    # 短超时 + 重试，避免用户等待
    for attempt in range(3):
        if _model_lock.acquire(timeout=3):
            break
        if attempt < 2:
            print(f"[VoxCPM TTS] 等待模型锁释放... (尝试 {attempt + 1}/3)")
    else:
        yield _build_sse({"type": "audio.error", "request_id": request_id,
                          "message": "等待模型超时，请重试"})
        return
    try:
        gen = model.generate_streaming(
            text=text,
            prompt_wav_path=DEFAULT_PROMPT_WAV or None,
            prompt_text=DEFAULT_PROMPT_TEXT or None,
            cfg_value=DEFAULT_CFG_VALUE,
            inference_timesteps=DEFAULT_INFERENCE_STEPS,
            retry_badcase=False,
        )

        for audio_chunk in gen:
            if is_cancelled(request_id):
                yield _build_sse({"type": "audio.cancelled", "request_id": request_id})
                return

            arr = np.asarray(audio_chunk, dtype=np.float32).ravel()
            pcm_bytes = np.ascontiguousarray(arr, dtype=np.float32).tobytes()
            num_samples = arr.size
            total_samples += num_samples
            b64_data = base64.b64encode(pcm_bytes).decode("ascii")

            yield _build_sse({
                "type": "audio.chunk",
                "request_id": request_id,
                "index": chunk_index,
                "num_samples": num_samples,
                "sample_rate": sample_rate,
                "data": b64_data,
            })
            chunk_index += 1
    finally:
        _model_lock.release()

    yield _build_sse({
        "type": "audio.done",
        "request_id": request_id,
        "total_samples": total_samples,
        "interrupted": False,
    })


# ======================== FastAPI ========================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    mp = _model_args.get("model_path", DEFAULT_MODEL_PATH)
    print(f"[VoxCPM TTS] 服务启动中，模型路径: {mp}")
    print(f"[VoxCPM TTS] 调用方式: POST /stream_tts body: {{'text': '...', 'request_id': '...'}}")
    # 启动时预加载模型（避免首次请求等待）
    try:
        _get_model(mp)
    except Exception as e:
        print(f"[VoxCPM TTS] 模型预加载失败: {e}")
    yield
    print("[VoxCPM TTS] 服务关闭")


app = FastAPI(title="VoxCPM Streaming TTS", lifespan=lifespan)


@app.post("/stream_tts")
async def stream_tts(request: Request):
    """流式 TTS 端点：接收文本，SSE 流式返回 PCM f32le 音频块。"""
    # 鉴权校验（服务配置了 API Key 时）
    auth_error = _check_api_key(request)
    if auth_error:
        return JSONResponse(status_code=401, content={"detail": auth_error})

    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)

    # 模型名校验（服务配置了模型名时）
    model_error = _check_model_name(body)
    if model_error:
        return JSONResponse(status_code=400, content={"detail": model_error})

    text = (body.get("text") or "").strip()
    request_id = body.get("request_id") or f"tts-{int(time.time() * 1000)}"

    if not text:
        return StreamingResponse(
            iter([_build_sse({"type": "audio.error", "request_id": request_id, "message": "文本为空"})]),
            media_type="text/event-stream",
        )

    # 新请求到达：自动取消当前活跃的旧请求
    cancel_current_and_set(request_id)

    return StreamingResponse(
        _stream_audio_events(text, request_id, _model_args.get("model_path", DEFAULT_MODEL_PATH)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/cancel_tts")
async def cancel_tts(request: Request):
    """取消指定 request_id 的 TTS 合成。"""
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)

    request_id = body.get("request_id", "")
    if request_id:
        set_cancel(request_id)
        return {"status": "cancelled", "request_id": request_id}
    return {"status": "error", "message": "缺少 request_id"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ======================== 启动入口 ========================
_model_args: dict = {}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VoxCPM Streaming TTS Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"服务端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--model-path", type=str, default=DEFAULT_MODEL_PATH, help="VoxCPM 模型目录")
    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL_NAME,
                        help=f"服务模型名（校验请求 body.model；默认 {DEFAULT_MODEL_NAME}，留空则不校验）")
    parser.add_argument("--api-key", type=str, default=DEFAULT_API_KEY,
                        help="API Key（校验 Authorization: Bearer <key> 或 X-API-Key；默认空=任意值放行）")
    args = parser.parse_args()

    _model_args["model_path"] = args.model_path
    _model_args["model_name"] = args.model_name
    _model_args["api_key"] = args.api_key

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
