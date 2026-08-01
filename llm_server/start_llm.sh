#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/myenv"
HOST_PORT="${HOST_PORT:-8900}"
MODEL_DIR="${SCRIPT_DIR}/models/Qwen/Qwen3___6-35B-A3B-FP8"

# 激活虚拟环境
source "${VENV_DIR}/bin/activate"

# 检查端口占用
if lsof -i "tcp:${HOST_PORT}" -t >/dev/null 2>&1; then
  echo "Port ${HOST_PORT} already in use" >&2
  exit 1
fi

echo "Starting vLLM server on port ${HOST_PORT} ..."
echo "Model path: ${MODEL_DIR}"

# 设置环境变量
export VLLM_USE_MODELSCOPE=true
export MODELSCOPE_DOWNLOAD_MODE=local
export MODELSCOPE_HUB_ENABLE_FILE_CHECK=false
export MODELSCOPE_CACHE="${SCRIPT_DIR}/models"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export CUDA_VISIBLE_DEVICES=3

# 启动 vLLM 服务
vllm serve "${MODEL_DIR}" \
  --port "${HOST_PORT}" \
  --host 0.0.0.0 \
  --tensor-parallel-size 1 \
  --max-model-len 262144 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}' \
  --enable-prefix-caching \
  --max_num_batched_tokens 4096 \
  --max_num_seqs 8 \
  --kv-cache-dtype fp8_e4m3 \
  --chat-template "${SCRIPT_DIR}/chat_template.jinja" \
  --safetensors-load-strategy eager \
  --served-model-name Qwen/Qwen3.6-35B-A3B-FP8
