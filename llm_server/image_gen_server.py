#!/usr/bin/env python3
"""
Z-Image-Turbo 图像生成服务 —— FastAPI 封装。

使用 Tongyi-MAI/Z-Image-Turbo 模型（基于 Diffusers），默认 1024×1024 输出。

启动方式:
    python image_gen_server.py --port 8904
"""

import os
import sys
import json
import base64
import time
import argparse
import warnings
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from io import BytesIO

import torch

# ======================== 配置区域 ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8904
DEFAULT_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
DEFAULT_MODEL_NAME = "Z-Image-Turbo"   # 默认服务模型名（校验请求 body.model 用）
DEFAULT_API_KEY = ""                   # 默认空：不校验 API Key（任意值放行）

# 本地模型路径：优先读环境变量 LOCAL_MODEL_DIR，未设置则回退到远程 ID
LOCAL_MODEL_DIR = os.environ.get("LOCAL_MODEL_DIR", "")
MODEL_PATH = LOCAL_MODEL_DIR if LOCAL_MODEL_DIR and os.path.isdir(LOCAL_MODEL_DIR) else DEFAULT_MODEL_ID

# GPU 选择：CUDA_VISIBLE_DEVICES 或环境变量 SPECIFIC_GPU
SPECIFIC_GPU = os.environ.get("SPECIFIC_GPU", "")
if SPECIFIC_GPU:
    os.environ["CUDA_VISIBLE_DEVICES"] = SPECIFIC_GPU
    print(f"[Z-Image] 已设置 CUDA_VISIBLE_DEVICES={SPECIFIC_GPU}")

# 兼容性：将前导 warnings 移到 torch 导入后
warnings.filterwarnings("ignore", category=FutureWarning)


# ======================== FastAPI ========================
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response

# 服务参数（--api-key / --model-name）：
# api_key 为空：不校验（任意值放行）；model_name 为空：不校验请求 model 字段
_model_args: dict = {"api_key": "", "model_name": ""}


def _check_api_key(request: Request):
    """校验请求 API Key：服务未配置 key（空）时放行任意值；否则校验 Authorization / X-API-Key。

    校验失败抛出 HTTP 401。
    """
    api_key = _model_args.get("api_key", "")
    if not api_key:
        return
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        provided = header[len("Bearer "):].strip()
    else:
        provided = request.headers.get("X-API-Key", "").strip()
    if provided != api_key:
        raise HTTPException(status_code=401, detail="API Key 无效或缺失")


def _check_model_name(body: dict):
    """校验请求 modelname：服务未配置模型名（空）时放行任意值；否则要求 body.model 匹配。

    校验失败抛出 HTTP 400。
    """
    model_name = _model_args.get("model_name", "")
    if not model_name:
        return
    if str(body.get("model") or "").strip() != model_name:
        raise HTTPException(status_code=400, detail=f"模型名不匹配: 期望 '{model_name}'，收到 '{body.get('model') or ''}'")

# Lazy-loaded pipeline singleton
_pipe = None
_pipe_lock = threading.Lock()
_device: str | None = None


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_pipe():
    """延迟加载 Z-Image pipeline（线程安全）。
    使用 Diffusers DiffusionPipeline + trust_remote_code 加载模型仓库中的自定义 ZImagePipeline。
    """
    global _pipe, _device
    if _pipe is not None:
        return _pipe, _device

    with _pipe_lock:
        if _pipe is not None:
            return _pipe, _device

        from diffusers import DiffusionPipeline

        _device = _get_device()
        load_kwargs = {
            "torch_dtype": torch.bfloat16 if _device == "cuda" else torch.float32,
            "low_cpu_mem_usage": False,
            "trust_remote_code": True,
        }
        # 本地路径时跳过在线检查
        if LOCAL_MODEL_DIR and os.path.isdir(LOCAL_MODEL_DIR):
            load_kwargs["local_files_only"] = True

        print(f"[Z-Image] 加载模型: {MODEL_PATH}，设备: {_device}")
        _pipe = DiffusionPipeline.from_pretrained(MODEL_PATH, **load_kwargs)
        _pipe.to(_device)
        print(f"[Z-Image] 模型加载成功")
        return _pipe, _device


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Z-Image] 服务启动中，端口: {_model_args.get('port', DEFAULT_PORT)}")
    # 启动时预加载模型
    try:
        _get_pipe()
    except Exception as e:
        print(f"[Z-Image] 模型预加载失败（将在首次请求时重试）: {e}")
    yield
    print("[Z-Image] 服务关闭")


app = FastAPI(title="Z-Image-Turbo Gen", lifespan=lifespan)


@app.post("/generate")
async def generate_image(request: Request):
    """生成图像。

    输入 JSON:
        prompt: str            — 必填，正向提示词
        negative_prompt: str   — 可选，负向提示词
        height: int            — 可选，输出高度（默认 1024，须为 64 的倍数）
        width: int             — 可选，输出宽度（默认 1024，须为 64 的倍数）
        num_inference_steps: int — 可选，推理步数（Turbo 模型建议 9，即 8 次 DiT forward）
        guidance_scale: float  — 可选，CFG（Turbo 模型建议 0.0）
        seed: int              — 可选，随机种子（-1 表示随机）
        return_format: str     — 可选，"base64"（默认）或 "url"

    输出 JSON:
        success: bool
        image: str             — base64 编码的 PNG 或文件路径
        format: str            — "png"
        width: int
        height: int
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须为 JSON")

    # 鉴权与模型名校验
    _check_api_key(request)
    _check_model_name(body)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    height = int(body.get("height", 1024))
    width = int(body.get("width", 1024))
    steps = int(body.get("num_inference_steps", 11))
    guidance = float(body.get("guidance_scale", 0.0))
    seed = int(body.get("seed", -1))
    negative_prompt = (body.get("negative_prompt") or "").strip() or None
    return_format = (body.get("return_format") or "base64").strip().lower()

    # 参数校验
    if height % 64 != 0 or width % 64 != 0:
        raise HTTPException(status_code=400, detail="height 和 width 须为 64 的整数倍")
    if height < 256 or width < 256 or height > 2048 or width > 2048:
        raise HTTPException(status_code=400, detail="尺寸须在 [256, 2048] 之间")

    pipe, device = _get_pipe()

    generator = None
    if seed >= 0:
        generator = torch.Generator(device).manual_seed(seed)

    # 生成
    print(f"[Z-Image] 生成中: {width}x{height}, steps={steps}, prompt={prompt[:80]}...")
    t0 = time.time()
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_inference_steps=steps,
        guidance_scale=guidance,
        generator=generator,
    )
    image = result.images[0]
    elapsed = time.time() - t0
    print(f"[Z-Image] 生成完成，耗时 {elapsed:.1f}s")

    # 编码输出
    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)

    if return_format == "base64":
        img_b64 = base64.b64encode(buf.read()).decode("ascii")
        return JSONResponse({
            "success": True,
            "image": img_b64,
            "format": "png",
            "width": width,
            "height": height,
            "elapsed_seconds": round(elapsed, 2),
        })
    else:
        return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ======================== 启动入口 ========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Z-Image-Turbo Image Generation Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"服务端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL_NAME,
                        help=f"服务模型名（校验请求 body.model；默认 {DEFAULT_MODEL_NAME}，留空则不校验）")
    parser.add_argument("--api-key", type=str, default=DEFAULT_API_KEY,
                        help="API Key（校验 Authorization: Bearer <key> 或 X-API-Key；默认空=任意值放行）")
    args = parser.parse_args()

    _model_args["port"] = args.port
    _model_args["model_name"] = args.model_name
    _model_args["api_key"] = args.api_key

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
