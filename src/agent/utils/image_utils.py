"""图片缩放、体积控制与 OpenAI 风格多模态 image_url 片段构建。

系统定位:
    多模态输入适配层，被 ``core/llm``、``core/nodes``、``utils/agent_utils``
    调用，将本地路径或内存字节转为 LLM 可消费的 data URL 内容块。

可扩展性:
    - 可接入 WebP/AVIF 编码、按模型 token 预算动态调整 ``max_size``。
"""
import base64
import io
import os
from typing import Any
from PIL import Image

from agent.utils.env_utils import IMG_SIZE

# 小写扩展名（含点），用于判断路径是否为支持的栅格图
IMAGE_FILE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"})


def resize_image_if_needed(image_path_or_bytes: str | bytes, *, max_size: int = IMG_SIZE) -> bytes:
    """等比缩放并压缩图片，控制 base64 体积与 token 消耗。

    功能描述:
        - 超长边超过 max_size 时等比缩放（LANCZOS）
        - RGBA/LA 透明图转白底后优先输出 JPEG
        - JPEG quality=70，PNG 保留透明通道场景外的优化输出

    输入:
        image_path_or_bytes: 本地路径或原始图片字节。
        max_size: 最大边长像素，默认来自环境变量 IMG_SIZE。

    输出:
        处理后的图片二进制（JPEG 或 PNG）。

    系统定位:
        所有图片入模前的统一预处理入口。

    可扩展性:
        可按用途（vision / thumbnail）传入不同 quality 与 max_size 配置。
    """
    if isinstance(image_path_or_bytes, str):
        img = Image.open(image_path_or_bytes)
        original_format = img.format or "PNG"
    else:
        img = Image.open(io.BytesIO(image_path_or_bytes))
        original_format = img.format or "PNG"

    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
        original_format = "JPEG"
    elif img.mode == "LA":
        background = Image.new("L", img.size, 255)
        background.paste(img, mask=img.split()[-1])
        img = background

    original_width, original_height = img.size

    if original_width > max_size or original_height > max_size:
        ratio = min(max_size / original_width, max_size / original_height)
        new_width = int(original_width * ratio)
        new_height = int(original_height * ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    img_buffer = io.BytesIO()
    save_format = (original_format or "PNG").upper()
    if save_format not in ("PNG", "JPEG", "JPG"):
        save_format = "JPEG"

    if save_format in ("JPEG", "JPG"):
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(
            img_buffer,
            format="JPEG",
            quality=70,
            optimize=True,
            progressive=True,
        )
    else:
        img.save(img_buffer, format="PNG", optimize=True)
    img_buffer.seek(0)
    return img_buffer.getvalue()


def image_to_base64(image_content: str | bytes) -> str | None:
    """将图片路径或字节转为 base64 字符串。

    输入:
        image_content: 文件路径或原始字节。

    输出:
        base64 编码字符串；处理失败返回 None。

    系统定位:
        供路径类 image_url 块与简单编码场景使用。

    可扩展性:
        失败时可返回错误码或记录日志，便于排查。
    """
    try:
        processed = resize_image_if_needed(image_content)
        return base64.b64encode(processed).decode("utf-8")
    except Exception:
        return None


def _mime_from_magic(data: bytes) -> str:
    """根据文件头魔数推断图片 MIME。

    输入:
        data: 压缩后的图片字节。

    输出:
        ``image/jpeg`` | ``image/png`` | ``image/gif``；默认 jpeg。

    系统定位:
        内存字节构造 data URL 时，扩展名不可用时的回退。

    可扩展性:
        可补充 WebP、BMP 等魔数识别。
    """
    if len(data) >= 2 and data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def image_bytes_to_openai_image_url_part(
    image_bytes: bytes,
    *,
    detail: str | None = None,
) -> dict | None:
    """将内存图片字节转为 OpenAI Chat Completions 的 image_url 内容块。

    输入:
        image_bytes: 原始或已编码图片字节（如工具截屏 PNG）。
        detail: 可选，传给模型的 detail 级别（auto/low/high）。

    输出:
        ``{"type": "image_url", "image_url": {"url": "data:..."}}``；
        失败返回 None。

    系统定位:
        ``core/nodes.process_tool_artifact`` 将工具截图注入对话；
        ``core/llm`` 处理附件内嵌图片。

    可扩展性:
        可支持 URL 引用模式，避免大 base64 内联。
    """
    try:
        processed = resize_image_if_needed(image_bytes)
    except Exception:
        return None
    mime = _mime_from_magic(processed)
    b64_str = base64.b64encode(processed).decode("utf-8")
    url = f"data:{mime};base64,{b64_str}"
    image_url: dict = {"url": url}
    if detail:
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def image_path_to_openai_image_url_part(
    file_path: str,
    *,
    detail: str | None = None,
) -> dict | None:
    """从本地图片路径构造 OpenAI 风格 image_url 内容块。

    输入:
        file_path: 本地图片绝对或相对路径。
        detail: 可选 detail 级别。

    输出:
        与 ``image_bytes_to_openai_image_url_part`` 相同结构；失败 None。

    系统定位:
        ``core/llm._process_image_content`` 将用户上传图片路径转为模型输入。

    可扩展性:
        可增加文件大小上限校验、病毒扫描钩子。
    """
    try:
        processed = resize_image_if_needed(file_path)
    except Exception:
        return None
    b64_str = base64.b64encode(processed).decode("utf-8")
    mime_type = _mime_from_magic(processed)
    url = f"data:{mime_type};base64,{b64_str}"
    image_url: dict = {"url": url}
    if detail:
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}
