"""
Test script for Qwen3-Omni-30B-A3B-Captioner via vLLM Chat Completions API.

Note:
    This model is an audio captioner, not a pure ASR. It generates
    detailed descriptions of audio content (speech, environment, music, etc.)
    without any text prompt. Only the audio file is sent.
    It is recommended to keep audio length <= 30 seconds for best detail.
"""

import requests
import argparse
import os
import sys
import base64
import mimetypes

DEFAULT_URL = "http://127.0.0.1:8901/v1/chat/completions"

# ----------------------------------------------------------------------
# Optional: check audio duration (requires soundfile)
# ----------------------------------------------------------------------
def get_audio_duration_sec(file_path: str) -> float:
    """Return audio duration in seconds, or -1.0 if unable to read."""
    try:
        import soundfile as sf
        info = sf.info(file_path)
        return info.duration
    except Exception:
        try:
            # Fallback using librosa (if available)
            import librosa
            return librosa.get_duration(path=file_path)
        except Exception:
            return -1.0

# ----------------------------------------------------------------------
def file_to_url(file_path: str, use_base64: bool = False) -> str:
    """Convert local file path to a URL accepted by vLLM.
    
    When the server is remote, use base64 data URL instead of file://
    since the remote server cannot access local filesystem paths.
    """
    if use_base64:
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "audio/wav"
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64_data}"
    else:
        abs_path = os.path.abspath(file_path)
        return "file://" + abs_path.replace("\\", "/")

def caption_audio(audio_path: str, server_url: str = DEFAULT_URL, use_base64: bool = False) -> str:
    """
    Send audio to the Qwen3-Omni-30B-A3B-Captioner and return its description.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Check duration (warning only, not blocking)
    duration = get_audio_duration_sec(audio_path)
    if duration > 30:
        print(
            f"⚠️  Audio length is {duration:.1f}s (>30s). "
            "The model may lose fine detail. Consider trimming to ≤30s.",
            file=sys.stderr
        )

    audio_url = file_to_url(audio_path, use_base64=use_base64)

    # The model expects NO text prompt. Only the audio input is required.
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "audio_url", "audio_url": {"url": audio_url}}
                ]
            }
        ]
    }

    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(server_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        # Extract assistant reply
        text = result["choices"][0]["message"]["content"]
        return text.strip()
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Server response: {e.response.text}", file=sys.stderr)
        raise

def main():
    parser = argparse.ArgumentParser(
        description="Test Qwen3-Omni-Captioner (audio captioning, NOT pure ASR)"
    )
    parser.add_argument("--audio", "-a", required=True,
                        help="Path to input audio file (mp3, wav, etc.)")
    parser.add_argument("--url", "-u", default=DEFAULT_URL,
                        help="vLLM chat completions endpoint")
    parser.add_argument("--output", "-o", default=None,
                        help="Output text file (if not provided, print to stdout)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed request/response info")
    parser.add_argument("--base64", "-b", action="store_true",
                        help="Send audio as base64 data URL (use when server is remote)")

    args = parser.parse_args()

    if args.verbose:
        print(f"Audio file: {args.audio}")
        print(f"Server URL: {args.url}")
        print(f"Base64 mode: {args.base64}")

    caption_text = caption_audio(args.audio, args.url, use_base64=args.base64)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(caption_text)
        print(f"Caption saved to: {args.output}")
    else:
        print(caption_text)

if __name__ == "__main__":
    main()