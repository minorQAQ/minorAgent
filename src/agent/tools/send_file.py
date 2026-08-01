"""文件发送工具：向用户发送各类文件，支持图片预览、音频 ASR、文件下载。

系统定位:
    作为 Agent 可调用的工具，将本地文件发送给用户。根据文件类型：
    - 图片：前端直接展示，工具返回"已向用户发送(filepath)"
    - 音频：前端直接播放 + 自动 ASR 转文字作为工具返回值
    - 压缩包/其他文件：可下载；超过 SIZE_LIMIT 时提示发送到邮箱
"""

from __future__ import annotations

import mimetypes
import os
import pathlib
from typing import Any, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from agent.utils.agent_utils import (
    AUDIO_FILE_EXTENSIONS,
    audio_file_to_text,
)
from agent.utils.env_utils import SEND_FILE_SIZE_LIMIT
from agent.utils.image_utils import IMAGE_FILE_EXTENSIONS


def _human_readable_size(size_bytes: int) -> str:
    """将字节数转为人类可读的大小字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024 or unit == "GB":
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


class SendFileInput(BaseModel):
    file_path: str = Field(default="", description="要发送给用户的单个文件完整路径（与 file_paths 二选一）")
    file_paths: list[str] = Field(default_factory=list, description="要发送给用户的多个文件完整路径（与 file_path 二选一）")


class SendFileTool(BaseTool):
    args_schema: type[BaseModel] = SendFileInput
    name: str = "send_file"
    description: str = (
        "向用户发送文件或文件夹的工具。根据文件类型自动处理：\n"
        "- 图片(.png/.jpg/.jpeg/.bmp/.gif/.webp)：前端直接展示。\n"
        "- 音频(.wav/.mp3/.flac/.ogg/.m4a/.aac等)：前端播放 + 自动 ASR 转文字。\n"
        "- 压缩包(.zip/.rar/.7z/.tar/.gz等)和各类文件：供用户下载。\n"
        "  文件超过大小限制时，会提示用户可发送到指定邮箱。\n"
        "- 文件夹：前端展示文件夹卡片，用户可查看文件夹路径。\n"
        "工具返回值：图片/文件/文件夹类返回'已向用户发送 xxx'；音频类返回 ASR 识别文字。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    def _classify_send_file(self, file_path: str) -> str:
        """分类文件类型：image / audio / folder / other。"""
        # 文件夹优先判断
        if os.path.isdir(file_path):
            return "folder"
        ext = pathlib.Path(file_path).suffix.lower()
        # SVG 是矢量图，不按栅格图处理，走"文件"通道
        if ext == ".svg":
            return "other"
        if ext in IMAGE_FILE_EXTENSIONS:
            return "image"
        if ext in AUDIO_FILE_EXTENSIONS:
            return "audio"
        mime, _ = mimetypes.guess_type(file_path)
        if mime:
            if mime.startswith("image/"):
                return "image"
            if mime.startswith("audio/"):
                return "audio"
        return "other"

    def _run(self, file_path: str = "", file_paths: list | None = None, **kwargs) -> tuple[str, dict]:
        """发送文件/文件夹给用户。支持单文件(file_path)和多文件(file_paths)。"""
        # 收集所有文件路径
        paths: list[str] = []
        if file_path:
            paths.append(file_path)
        if file_paths:
            paths.extend(file_paths)
        if not paths:
            return ("[ERROR] 未指定要发送的文件路径", {})

        results_text: list[str] = []
        combined_artifact: dict[str, Any] = {
            "file_type": "batch",
            "items": [],
        }

        for fp in paths:
            try:
                fp = fp.strip()
                if not fp:
                    continue

                file_type = self._classify_send_file(fp)

                # 文件夹：发送文件夹路径，前端展示文件夹卡片
                if file_type == "folder":
                    if not os.path.isdir(fp):
                        results_text.append(f"[ERROR] 文件夹不存在: {fp}")
                        continue
                    folder_name = os.path.basename(fp) or fp
                    combined_artifact["items"].append({
                        "file_type": "folder",
                        "file_path": fp,
                        "file_name": folder_name,
                    })
                    results_text.append(f"已向用户发送文件夹 {folder_name}")
                    continue

                if not os.path.isfile(fp):
                    results_text.append(f"[ERROR] 文件不存在: {fp}")
                    continue

                file_name = os.path.basename(fp)

                if file_type == "image":
                    try:
                        with open(fp, "rb") as f:
                            image_bytes = f.read()
                    except Exception as e:
                        results_text.append(f"[ERROR] 无法读取图片 {file_name}: {str(e)}")
                        continue
                    combined_artifact["items"].append({
                        "file_type": "image",
                        "file_path": fp,
                        "file_name": file_name,
                        "image_bytes": image_bytes,
                    })
                    results_text.append(f"已向用户发送图片 {file_name}")

                elif file_type == "audio":
                    try:
                        asr_text = audio_file_to_text(fp)
                    except Exception as e:
                        results_text.append(f"[ERROR] ASR 失败 {file_name}: {str(e)}")
                        continue
                    combined_artifact["items"].append({
                        "file_type": "audio",
                        "file_path": fp,
                        "file_name": file_name,
                    })
                    results_text.append(asr_text)

                else:  # "other" - 文件
                    file_size = os.path.getsize(fp)
                    if file_size > SEND_FILE_SIZE_LIMIT:
                        limit_str = _human_readable_size(SEND_FILE_SIZE_LIMIT)
                        size_str = _human_readable_size(file_size)
                        results_text.append(
                            f"文件 {file_name} 大小为 {size_str}，超过了文件传输上限 {limit_str}。"
                            f"如需发送，请告知用户可将文件发送到指定邮箱。"
                        )
                        continue
                    try:
                        with open(fp, "rb") as f:
                            file_bytes = f.read()
                    except Exception as e:
                        results_text.append(f"[ERROR] 无法读取文件 {file_name}: {str(e)}")
                        continue
                    mime_type, _ = mimetypes.guess_type(fp)
                    combined_artifact["items"].append({
                        "file_type": "file",
                        "file_path": fp,
                        "file_name": file_name,
                        "file_bytes": file_bytes,
                        "file_size": file_size,
                        "mime_type": mime_type or "application/octet-stream",
                    })
                    results_text.append(f"已向用户发送文件 {file_name}")

            except Exception as e:
                results_text.append(f"[ERROR] send_file 处理 {fp} 时出错: {str(e)}")

        # 如果只有一个文件，保持原格式（向后兼容单文件返回格式）
        if len(combined_artifact["items"]) == 1:
            single = combined_artifact["items"][0]
            return ("\n".join(results_text), single)
        return ("\n".join(results_text), combined_artifact)

    async def _arun(self, **kwargs) -> tuple[str, dict]:
        import asyncio
        return await asyncio.to_thread(self._run, **kwargs)
