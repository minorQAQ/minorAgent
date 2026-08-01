"""流式 TTS 客户端：连接 streaming_tts_server，通过 SSE 获取音频块。"""

from __future__ import annotations

import json
import base64
import threading
from typing import Generator
from dataclasses import dataclass

import requests


@dataclass
class TTSEvent:
    """TTS 流事件。"""
    type: str          # audio.start | audio.chunk | audio.done | audio.error | audio.cancelled
    request_id: str
    index: int = 0
    num_samples: int = 0
    sample_rate: int = 24000
    data: bytes | None = None       # PCM f32le 原始字节
    message: str = ""


class StreamingTTSClient:
    """流式 TTS 客户端 —— 连接 streaming_tts_server 的 SSE 端点。"""

    def __init__(self, base_url: str = "http://localhost:8902"):
        self.base_url = base_url.rstrip("/")

    def stream_tts(self, text: str, request_id: str = "") -> Generator[TTSEvent, None, None]:
        """流式合成语音，返回 TTSEvent 生成器。

        输入:
            text: 待合成的完整文本。
            request_id: 唯一请求 ID，用于取消。

        输出:
            TTSEvent 生成器，按序产出 audio.start / audio.chunk / audio.done。
        """
        resp = requests.post(
            f"{self.base_url}/stream_tts",
            json={"text": text, "request_id": request_id},
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload_str = line[len("data: "):]
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                continue

            event_type = payload.get("type", "")
            evt = TTSEvent(
                type=event_type,
                request_id=payload.get("request_id", request_id),
                index=payload.get("index", 0),
                num_samples=payload.get("num_samples", 0),
                sample_rate=payload.get("sample_rate", 24000),
                data=_decode_pcm_b64(payload.get("data")),
                message=payload.get("message", ""),
            )
            yield evt

    def cancel_tts(self, request_id: str) -> bool:
        """取消指定请求的 TTS 合成。"""
        try:
            resp = requests.post(
                f"{self.base_url}/cancel_tts",
                json={"request_id": request_id},
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False


def _decode_pcm_b64(b64_data: str | None) -> bytes | None:
    if not b64_data:
        return None
    try:
        return base64.b64decode(b64_data)
    except Exception:
        return None
