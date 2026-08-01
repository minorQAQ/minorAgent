# LLM 推理服务

为 [minor Agent](../README.md) 提供本地化推理后端，包含 **6 个独立服务**，均跑在 GPU 服务器上，通过 OpenAI 兼容 / 自定义 HTTP API 暴露。可整体部署，也可按需启用。

## 服务总览

| 服务 | 端口 | 模型 | 启动脚本 | Python 服务端 | 关键端点 |
|------|:----:|------|----------|---------------|----------|
| **LLM** | 8900 | Qwen3.6-35B-A3B-FP8 | `start_llm.sh` | vLLM 内置 | `/v1/chat/completions` |
| **ASR** | 8901 | Qwen3-ASR-1.7B | `start_asr.sh` | vLLM 内置 | `/v1/chat/completions` |
| **TTS** | 8902 | VoxCPM 1.5 / 2 | `start_streaming_tts.sh` | `streaming_tts_server.py` | `/stream_tts` |
| **RAG** | 8903 | Embedding-0.6B + Reranker-4B | `start_rag_server.sh` | `rag_server.py` | `/embed` `/rerank` |
| **Image Gen** | 8904 | Z-Image-Turbo | `start_image_gen.sh` | `image_gen_server.py` | `/generate` |

> 所有脚本 / Python 文件均通过 `os.path.dirname(__file__)` 与 `${SCRIPT_DIR}` 动态定位模型路径，**目录整体迁移无需改代码**。

---

## 一、部署流程

### 1. 上传到服务器

```bash
scp -P <SSH_PORT> -r Agent/llm_server/* <user>@<your-gpu-server>:~/llm_server/
ssh -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -p <SSH_PORT> <user>@<your-gpu-server>
```

### 2. 服务器环境

```bash
cd ~/llm_server
chmod +x *.sh

# HuggingFace 镜像加速（国内必需）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_ENABLE_XET=0
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
echo 'export HF_HUB_ENABLE_XET=0' >> ~/.bashrc

python3 -m venv myenv && source myenv/bin/activate

# 一次性安装全部依赖
pip install vllm modelscope transformers fastapi uvicorn torch numpy torchaudio soundfile \
            bitsandbytes huggingface_hub voxcpm diffusers
sudo apt update && sudo apt install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev \
            libavdevice-dev libavfilter-dev libswscale-dev libswresample-dev
```

### 3. 下载模型

所有模型统一存放 `~/llm_server/models/`：

| 模型 | 命令 |
|------|------|
| Qwen3.6-35B-A3B-FP8 (LLM) | `modelscope download --model Qwen/Qwen3.6-35B-A3B-FP8 --local_dir ./models/Qwen/Qwen3___6-35B-A3B-FP8` |
| Qwen3-ASR-1.7B | `modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir ./models/Qwen/Qwen3-ASR-1.7B` |
| Qwen3-Embedding-0.6B | `modelscope download --model Qwen/Qwen3-Embedding-0.6B --local_dir ./models/Qwen/Qwen3-Embedding-0___6B` |
| Qwen3-Reranker-4B | `modelscope download --model Qwen/Qwen3-Reranker-4B --local_dir ./models/Qwen/Qwen3-Reranker-4B` |
| VoxCPM 1.5 (推荐) | `modelscope download --model OpenBMB/VoxCPM1.5 --local_dir ./models/VoxCPM1__5` |
| VoxCPM 2 (音质更佳) | `modelscope download --model OpenBMB/VoxCPM2 --local_dir ./models/VoxCPM2` |
| Z-Image-Turbo | `modelscope download --model Tongyi-MAI/Z-Image-Turbo --local_dir ./models/Tongyi-MAI/Z-Image-Turbo` |

完成后目录结构：

```
~/llm_server/models/
├── Qwen/
│   ├── Qwen3___6-35B-A3B-FP8/      # LLM
│   ├── Qwen3-ASR-1.7B/             # ASR
│   ├── Qwen3-Embedding-0___6B/     # Embedding
│   └── Qwen3-Reranker-4B/          # Reranker
├── VoxCPM1__5/                     # TTS
└── Tongyi-MAI/Z-Image-Turbo/       # Image Gen
```

---

## 二、启动与测试

每个服务独立启动，互不依赖。所有 `start_*.sh` 支持环境变量覆盖：

| 环境变量 | 作用 | 适用脚本 |
|----------|------|----------|
| `HOST_PORT` | 服务端口 | 全部 |
| `LOCAL_MODEL_DIR` / `MODEL_PATH` / `VOXCPM_MODEL_PATH` | 模型目录 | 全部 |
| `CUDA_VISIBLE_DEVICES` | GPU 设备号 | 全部 |
| `SPECIFIC_GPU` | 单 GPU 指定（写 `CUDA_VISIBLE_DEVICES`） | image_gen / tts |

### LLM · 8900

```bash
bash start_llm.sh
# 测试
python3 test_llm.py --url http://127.0.0.1:8900            # 非流式
python3 test_llm.py --url http://127.0.0.1:8900 --stream   # 流式
```

> vLLM 加载 Qwen3.6-35B-A3B-FP8，OpenAI 兼容 API，使用 `chat_template.jinja` 格式化对话。

### ASR · 8901

```bash
bash start_asr.sh
# 测试
python3 test_asr.py --audio /path/to/audio.wav --url http://127.0.0.1:8901/v1/chat/completions
```

### TTS · 8902（流式）

```bash
bash start_streaming_tts.sh
# 测试（流式返回 wav 分块）
curl -X POST http://127.0.0.1:8902/stream_tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，这是一个流式语音合成测试。", "request_id": "test-1"}'
```

> VoxCPM 流式合成，边生成边返回 wav chunk，配合 `reference_audio.wav` 控制音色。

### RAG · 8903（Embedding + Reranker）

```bash
bash start_rag_server.sh
python3 test_rag.py
```

### Image Gen · 8904

```bash
LOCAL_MODEL_DIR=./models/Tongyi-MAI/Z-Image-Turbo SPECIFIC_GPU=3 bash start_image_gen.sh
# 测试
curl -X POST http://127.0.0.1:8904/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "一只橘猫坐在窗台上，阳光洒落", "width": 1024, "height": 1024, "return_format": "base64"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'成功:{d.get(\"success\")} 尺寸:{d.get(\"width\")}x{d.get(\"height\")} 耗时:{d.get(\"elapsed_seconds\",\"?\")}s')"
```

> Z-Image-Turbo 基于 Diffusers，**9 步推理**生成 1024×1024 图片，`return_format=base64` 直接返回内联数据。

---

## 三、本地端口映射（开发调试）

将远程端口映射到本地，用 `http://localhost:8900` 直连远程服务：

```bash
# 一次性映射全部端口
ssh -fN -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
  -L 8900:0.0.0.0:8900 -L 8901:0.0.0.0:8901 -L 8902:0.0.0.0:8902 \
  -L 8903:0.0.0.0:8903 -L 8904:0.0.0.0:8904 \
  <user>@<your-gpu-server> -p <SSH_PORT>
```

验证映射（HTTP 200 即通）：

```bash
for p in 8900 8901 8902 8903 8904; do
  curl -o /dev/null -s -w "$p: %{http_code}\n" http://localhost:$p/health
done
```

---

## 四、停止服务

```bash
for p in 8900 8901 8902 8903 8904; do kill $(lsof -t -i:$p); done
```

---

## 五、接入 Agent

在 minor Agent 配置向导（或 `env_config.json`）中填入对应地址即可启用各能力：

| Agent 能力 | 配置字段 | 示例值 |
|-----------|----------|--------|
| LLM 对话 | `models[].base_url` | `http://localhost:8900/v1` |
| 语音识别 | `ASR_BASE_URL` | `http://localhost:8901/v1` |
| 语音合成 | `STREAMING_TTS_URL` | `http://localhost:8902` |
| 知识库检索 | `RAG_BASE_URL` | `http://localhost:8903` |
| 图像生成 | （由 `image_gen` 工具读取） | `http://localhost:8904` |

> 💡 不必自建本服务，Agent 也支持任何 **OpenAI 兼容 API**（云端 Qwen / DeepSeek / OpenAI 等），填入 `base_url` + `api_key` 即可。
