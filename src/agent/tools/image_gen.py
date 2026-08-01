"""
图像生成工具 —— 调用 Z-Image-Turbo 服务生成图片。

依赖:
    - Z-Image-Turbo 服务（由 llm_server/image_gen_server.py 提供）
    - env_config.json 中的 IMAGE_GEN_URL 配置
"""

from __future__ import annotations

import os
import base64
import time
from typing import Tuple, Any, Literal

import requests
from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model


def _read_config(key: str, default: str = "") -> str:
    """从 env_config.json 读取配置项。"""
    try:
        from agent.core.config_manager import load_env_config
        config = load_env_config()
        if isinstance(config, dict):
            return str(config.get(key, default))
    except Exception:
        pass
    return os.environ.get(key, default)


def _get_workspace_dir() -> str:
    """获取 workspace 绝对路径。优先使用当前选中的工作空间，回退到 env_config 配置。"""
    try:
        # 优先使用用户当前选中的工作空间
        from agent.memory.system_prompt import _current_workspace_dir
        if _current_workspace_dir and os.path.isabs(_current_workspace_dir):
            os.makedirs(_current_workspace_dir, exist_ok=True)
            return _current_workspace_dir
    except Exception:
        pass
    try:
        from agent.utils.env_utils import get_workspace_dir
        return get_workspace_dir()
    except Exception:
        return os.path.abspath("workspace")


class ImageGen(BaseTool):
    """AI 图像生成工具，通过 Z-Image-Turbo 模型将文字描述转换为图片。

    调用方式（单张）:
        image_gen(images=[{"prompt": "一只橘猫坐在窗台上", "width": 1024, "height": 1024}])

    调用方式（多张）:
        image_gen(images=[
            {"prompt": "一只橘猫坐在窗台上", "width": 1024, "height": 1024},
            {"prompt": "赛博朋克城市夜景", "width": 1024, "height": 768},
        ])
    """

    class ImageGenInput(BaseModel):
        """单张图片生成参数。"""
        prompt: str = Field(description=(
            "图像描述（正向提示词），支持中文和英文。必须极其详细：包含主体、场景、构图、光线、色彩、风格、质感、细节等。"
            "如需生成包含中文文字的图片，请使用中文编写 prompt。"
            "示例: '一只橘色的虎斑猫坐在洒满阳光的木窗台上，金色的午后光线透过薄纱窗帘，"
            "空气中飘浮着微尘，温暖的色调，浅景深，高度精细的毛发质感，舒适温馨的氛围'"
        ))
        width: int = Field(default=1024, description="图像宽度，须为64的倍数，范围[256,2048]")
        height: int = Field(default=1024, description="图像高度，须为64的倍数，范围[256,2048]")
        seed: int = Field(default=-1, description="随机种子，-1 表示随机。相同 seed+prompt 可复现结果")
        num_inference_steps: int = Field(default=9, description="推理步数，Turbo 模型建议 9（8 次 DiT forward），范围[1,50]")

    args_schema: type[BaseModel] = create_model(
        "ImageGenBatchInput",
        images=(list[ImageGenInput], Field(description="图片生成请求列表，每项包含 prompt、width、height 等参数")),
    )
    name: str = "image_gen"
    description: str = (
        "AI 图像生成工具，将文字描述转换为高质量图片。\n"
        "prompt 必须极其详细且具体：包含主体、场景、光线、色彩、质感、风格、构图等要素。\n"
        "如需图片中包含中文文字，请使用中文 prompt。\n"
        "支持一次调用生成多张图片（通过 images 列表），每张可独立指定 prompt、尺寸、种子、推理步数。\n"
        "生成的图片自动保存到 workspace 目录。\n"
        "适用场景：用户要求画图、生成图片、制作海报、设计插图等。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    def _get_url(self) -> str:
        return _read_config("IMAGE_GEN_URL", "http://localhost:8904")

    def _generate_one(self, base_url: str, inp: ImageGenInput, idx: int) -> Tuple[str, dict[str, Any]]:
        """生成单张图片，返回 (文本结果, artifact_dict)。"""
        if not inp.prompt.strip():
            return (f"[ERROR] 第{idx}张: prompt 不能为空", {})

        w, h, seed = inp.width, inp.height, inp.seed
        if w % 64 != 0 or h % 64 != 0:
            return (f"[ERROR] 第{idx}张: 宽度和高度必须为 64 的整数倍", {})
        if not (256 <= w <= 2048) or not (256 <= h <= 2048):
            return (f"[ERROR] 第{idx}张: 尺寸须在 [256, 2048] 之间", {})

        payload: dict = {
            "prompt": inp.prompt,
            "width": w,
            "height": h,
            "num_inference_steps": inp.num_inference_steps,
            "guidance_scale": 0.0,
            "seed": seed,
            "return_format": "base64",
        }

        try:
            resp = requests.post(
                f"{base_url}/generate",
                json=payload,
                timeout=300,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            return (f"[ERROR] 第{idx}张: 无法连接图像生成服务 ({base_url})", {})
        except requests.exceptions.Timeout:
            return (f"[ERROR] 第{idx}张: 图像生成超时（>5分钟）", {})
        except Exception as e:
            return (f"[ERROR] 第{idx}张: 请求失败: {e}", {})

        try:
            data = resp.json()
        except Exception:
            return (f"[ERROR] 第{idx}张: 服务返回非 JSON 响应: {resp.text[:200]}", {})

        if not data.get("success"):
            return (f"[ERROR] 第{idx}张: 图像生成失败: {data}", {})

        img_b64 = data.get("image", "")
        if not img_b64:
            return (f"[ERROR] 第{idx}张: 服务未返回图片数据", {})

        try:
            img_bytes = base64.b64decode(img_b64)
        except Exception as e:
            return (f"[ERROR] 第{idx}张: 图片解码失败: {e}", {})

        # 保存到 workspace
        ws_dir = _get_workspace_dir()
        os.makedirs(ws_dir, exist_ok=True)
        ts = int(time.time() * 1000)
        filename = f"image_gen_{idx}_{ts}.png"
        filepath = os.path.join(ws_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_bytes)

        elapsed = data.get("elapsed_seconds", "?")
        text = (
            f"[OK] 第{idx}张已生成: {filepath}\n"
            f"尺寸: {w}x{h} | 耗时: {elapsed}s\n"
        )
        return (text, {"image_bytes": img_bytes})

    def _run(
        self,
        images: list[ImageGenInput],
    ) -> Tuple[str, dict[str, Any]]:
        """批量执行图像生成，返回 (文本结果, artifact)。

        输入:
            images: 图片生成请求列表，每项可独立指定 prompt、尺寸、种子等。

        输出:
            (汇总文本, {"images": [{"image_bytes": bytes}, ...]}) — 每张图片写入 workspace 并汇总返回。
        """
        base_url = self._get_url().rstrip("/")
        texts: list[str] = []
        all_artifacts: list[dict[str, Any]] = []

        for i, inp in enumerate(images, start=1):
            t, a = self._generate_one(base_url, inp, i)
            texts.append(t)
            all_artifacts.append(a)

        summary = "\n".join(texts)
        return (summary, {"images": all_artifacts})
