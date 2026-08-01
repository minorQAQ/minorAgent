#!/usr/bin/env bash
set -euo pipefail

# 自动获取脚本所在目录
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/myenv}"
HOST_PORT="${HOST_PORT:-8903}"

# 激活虚拟环境
source "${VENV_DIR}/bin/activate"

# 检查端口占用
if lsof -i "tcp:${HOST_PORT}" -t >/dev/null 2>&1; then
  echo "Port ${HOST_PORT} already in use" >&2
  exit 1
fi

echo "Starting Qwen3 RAG server on port ${HOST_PORT} ..."

# 进入脚本目录
cd "${SCRIPT_DIR}"

# 离线模式设置（确保已下载模型，不从远程拉取）
export MODELSCOPE_DOWNLOAD_MODE=local
export MODELSCOPE_HUB_ENABLE_FILE_CHECK=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 指定 modelscope 的缓存目录（如果你的模型保存在此路径下）
# 根据你的下载路径调整，或将其设置为环境变量覆盖
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-${SCRIPT_DIR}/models}"

# 固定使用 GPU 0（多 GPU 服务器上所有模型共用一张卡）
export CUDA_VISIBLE_DEVICES=3

# 启动 FastAPI 服务
uvicorn rag_server:app \
  --host 0.0.0.0 \
  --port "${HOST_PORT}" \
  --workers 1
