"""
测试 Qwen3.6-35B-A3B-FP8 LLM 服务（OpenAI 兼容 API）

使用方法:
  python test_llm.py                     # 默认地址 http://127.0.0.1:8900
  python test_llm.py --url http://xxx:8900
  python test_llm.py --stream            # 流式输出
"""

import argparse
import json
import requests


def test_non_stream(base_url: str, model: str):
    """非流式请求：发送消息，打印完整返回结构"""
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己。"}
        ],
        "stream": False,
    }

    print("\n" + "=" * 80)
    print("  请求体 (Request)")
    print("=" * 80)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer <YOUR_API_KEY>"},
    )

    print("\n" + "=" * 80)
    print(f"  响应 (Response)  HTTP {resp.status_code}")
    print("=" * 80)

    if resp.status_code == 200:
        data = resp.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # 提取关键信息
        print("\n" + "-" * 80)
        print("  关键信息提取")
        print("-" * 80)
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        print(f"  model          : {data.get('model')}")
        print(f"  finish_reason  : {choice.get('finish_reason')}")
        print(f"  role           : {message.get('role')}")
        print(f"  content        : {message.get('content', '')[:200]}...")
        if message.get("tool_calls"):
            print(f"  tool_calls     : {json.dumps(message['tool_calls'], ensure_ascii=False)}")
        usage = data.get("usage", {})
        if usage:
            print(f"  prompt_tokens  : {usage.get('prompt_tokens')}")
            print(f"  completion_tokens: {usage.get('completion_tokens')}")
            print(f"  total_tokens   : {usage.get('total_tokens')}")
    else:
        print(f"Error: {resp.text}")


def test_stream(base_url: str, model: str):
    """流式请求：逐块打印输出"""
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己。"}
        ],
        "stream": True,
    }

    print("\n" + "=" * 80)
    print("  流式请求 (Stream)")
    print("=" * 80)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer <YOUR_API_KEY>"},
        stream=True,
    )

    print("\n" + "=" * 80)
    print(f"  流式响应  HTTP {resp.status_code}")
    print("=" * 80)

    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return

    full_content = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                print("\n\n[DONE]")
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    print(content, end="", flush=True)
                    full_content += content
                # 打印每个 chunk 的完整结构（首次和最后一次）
                if not full_content.strip() or content:
                    pass  # 避免刷屏，取消注释下面这行可查看每个 chunk
                    # print(f"\n[chunk] {json.dumps(chunk, ensure_ascii=False)}")
            except json.JSONDecodeError:
                print(f"\n[无法解析] {data_str}")

    print("\n\n" + "-" * 80)
    print(f"  完整内容: {full_content}")


def main():
    parser = argparse.ArgumentParser(description="测试 Qwen3.6 LLM 服务")
    parser.add_argument("--url", default="http://127.0.0.1:8900",
                        help="LLM 服务地址 (默认: http://127.0.0.1:8900)")
    parser.add_argument("--model", default="Qwen/Qwen3.6-35B-A3B-FP8",
                        help="模型名称")
    parser.add_argument("--stream", action="store_true",
                        help="使用流式输出")
    args = parser.parse_args()

    print("=" * 80)
    print("  Qwen3.6-35B-A3B-FP8 LLM 测试")
    print("=" * 80)
    print(f"  服务地址: {args.url}")
    print(f"  模型    : {args.model}")

    if args.stream:
        test_stream(args.url, args.model)
    else:
        test_non_stream(args.url, args.model)


if __name__ == "__main__":
    main()
