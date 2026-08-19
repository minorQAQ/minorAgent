#!/usr/bin/env bash
set -euo pipefail

# 自动获取脚本所在目录
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/myenv"
MODEL_DIR="${SCRIPT_DIR}/models/Qwen/Qwen3-ASR-1.7B"
HOST_PORT="${HOST_PORT:-8901}"
# 鉴权与模型名校验：SERVER_API_KEY 为空时 vLLM 不校验 API Key（任意值放行）
SERVER_API_KEY="${SERVER_API_KEY:-}"
SERVER_MODELNAME="${SERVER_MODELNAME:-Qwen3-ASR-1.7B}"

# 激活虚拟环境
source "${VENV_DIR}/bin/activate"

# 检查端口占用
if lsof -i "tcp:${HOST_PORT}" -t >/dev/null 2>&1; then
  echo "Port ${HOST_PORT} already in use" >&2
  exit 1
fi

echo "Starting vLLM server on port ${HOST_PORT} ..."
echo "Model path: ${MODEL_DIR}"
echo "Served model name: ${SERVER_MODELNAME}"
if [ -n "${SERVER_API_KEY}" ]; then
  echo "API Key 校验已启用"
fi

# 进入脚本目录
cd "${SCRIPT_DIR}"

# 设置环境变量
export VLLM_USE_MODELSCOPE=true
export MODELSCOPE_DOWNLOAD_MODE=local
export MODELSCOPE_HUB_ENABLE_FILE_CHECK=false
export MODELSCOPE_CACHE="${SCRIPT_DIR}/models"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 固定使用 GPU 0（多 GPU 服务器上所有模型共用一张卡）
export CUDA_VISIBLE_DEVICES=3

# 启动 vLLM 服务
ASR_ARGS=(
  --port "${HOST_PORT}"
  --host 0.0.0.0
  --quantization fp8
  --dtype auto
  --kv-cache-dtype fp8
  --max-model-len 16384
  --allowed-local-media-path /
  --tensor-parallel-size 1
  --gpu-memory-utilization 0.15
  --max-num-batched-tokens 4096
  --served-model-name "${SERVER_MODELNAME}"
)
# API Key 为空时不传 --api-key（vLLM 默认放行任意值）
if [ -n "${SERVER_API_KEY}" ]; then
  ASR_ARGS+=(--api-key "${SERVER_API_KEY}")
fi
vllm serve "${MODEL_DIR}" "${ASR_ARGS[@]}"
