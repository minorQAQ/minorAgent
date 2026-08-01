#!/usr/bin/env python3
"""
VoxCPM 流式 TTS 测试脚本。

用法:
    python test_tts.py                        # 默认测试
    python test_tts.py --text "你好世界"       # 自定义文本
    python test_tts.py --url http://x.x.x.x:8902  # 远程服务器
    python test_tts.py --save test_output.wav # 保存为 WAV 文件
"""

import argparse
import base64
import json
import struct
import sys
import time

import requests


def main():
    parser = argparse.ArgumentParser(description="VoxCPM 流式 TTS 测试")
    parser.add_argument("--url", default="http://0.0.0.0:8902", help="TTS 服务地址")
    parser.add_argument("--text", default="你好，这是一个流式语音合成测试。今天天气不错，适合出去散步。",
                        help="测试文本")
    parser.add_argument("--save", default="", help="保存 WAV 文件路径（不指定则不保存）")
    parser.add_argument("--play", action="store_true", help="本地播放（需要 pyaudio）")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    request_id = f"test-{int(time.time() * 1000)}"

    # 1. 健康检查
    print(f"→ 健康检查 {base_url}/health ...")
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        r.raise_for_status()
        print(f"  状态: {r.json()}")
    except Exception as e:
        print(f"  ❌ 无法连接 {base_url}: {e}")
        sys.exit(1)

    # 2. 流式 TTS 请求
    print(f"→ 流式 TTS 请求: \"{args.text}\"")
    t_start = time.perf_counter()
    sample_rate = 0
    all_pcm = bytearray()
    total_samples = 0
    total_chunks = 0

    try:
        resp = requests.post(
            f"{base_url}/stream_tts",
            json={"text": args.text, "request_id": request_id},
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            payload = json.loads(line[len("data: "):])
            event_type = payload.get("type", "")

            if event_type == "audio.start":
                sample_rate = payload.get("sample_rate", 0)
                num_segments = payload.get("num_segments", 0)
                print(f"  audio.start  | 采样率={sample_rate}Hz 句数={num_segments}")

            elif event_type == "audio.chunk":
                b64_data = payload.get("data", "")
                idx = payload.get("index", 0)
                num_s = payload.get("num_samples", 0)
                if b64_data:
                    pcm = base64.b64decode(b64_data)
                    all_pcm.extend(pcm)
                    total_samples += num_s
                    total_chunks += 1
                # 进度提示
                if idx % 5 == 0 and b64_data:
                    dur = total_samples / sample_rate if sample_rate else 0
                    print(f"  audio.chunk  | #{idx} 累计={dur:.1f}s")

            elif event_type == "audio.done":
                total = payload.get("total_segments", 0)
                print(f"  audio.done   | 共{total}句 {total_samples}样本 {total_chunks}块")

            elif event_type == "audio.error":
                print(f"  ❌ audio.error: {payload.get('message', '')}")
                sys.exit(1)

            elif event_type == "audio.cancelled":
                print(f"  ⚠ audio.cancelled")
                break

            elif event_type == "done":
                pass  # 流结束

    except requests.exceptions.ConnectionError as e:
        print(f"  ❌ 连接失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ 错误: {e}")
        sys.exit(1)

    t_elapsed = time.perf_counter() - t_start
    duration = total_samples / sample_rate if sample_rate else 0
    rtf = t_elapsed / duration if duration > 0 else 0
    print(f"\n{'='*50}")
    print(f"  总耗时:     {t_elapsed:.2f}s")
    print(f"  音频时长:   {duration:.2f}s")
    print(f"  RTF:        {rtf:.2f} (越小越好，<1 表示比实时快)")
    print(f"  采样率:     {sample_rate} Hz")
    print(f"  总样本数:   {total_samples}")
    print(f"  PCM 大小:   {len(all_pcm)} bytes")
    print(f"{'='*50}")

    if not all_pcm:
        print("  ⚠ 未收到任何音频数据")
        sys.exit(1)

    # 3. 保存 WAV
    if args.save:
        _save_wav(args.save, all_pcm, sample_rate)
        print(f"→ 已保存: {args.save}")

    # 4. 本地播放
    if args.play:
        _play_pcm(all_pcm, sample_rate)


def _save_wav(filepath: str, pcm_f32: bytearray, sample_rate: int):
    """将 PCM f32le 转为 16-bit WAV 保存。"""
    import io
    import wave
    import numpy as np

    arr = np.frombuffer(pcm_f32, dtype=np.float32)
    # 转为 int16
    arr_i16 = (arr * 32767).clip(-32768, 32767).astype(np.int16)

    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr_i16.tobytes())


def _play_pcm(pcm_f32: bytearray, sample_rate: int):
    """通过 pyaudio 播放 PCM 音频。"""
    try:
        import pyaudio
        import numpy as np
    except ImportError:
        print("  ⚠ 需要安装 pyaudio: pip install pyaudio")
        return

    arr = np.frombuffer(pcm_f32, dtype=np.float32)
    arr_i16 = (arr * 32767).clip(-32768, 32767).astype(np.int16)

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        output=True,
    )
    print("→ 播放中...")
    stream.write(arr_i16.tobytes())
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("→ 播放完毕")


if __name__ == "__main__":
    main()
