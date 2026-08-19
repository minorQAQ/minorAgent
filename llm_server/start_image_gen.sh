#!/usr/bin/env bash
set -euo pipefail

# ---------- 配置 ----------
HOST_PORT="${HOST_PORT:-8904}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 鉴权与模型名校验：SERVER_API_KEY / SERVER_MODELNAME 为空时服务端不校验（任意值放行）
SERVER_API_KEY="${SERVER_API_KEY:-}"
SERVER_MODELNAME="${SERVER_MODELNAME:-Z-Image-Turbo}"

# ---------- Python 虚拟环境 ----------
if [ -f "${SCRIPT_DIR}/../myenv/bin/activate" ]; then
  source "${SCRIPT_DIR}/../myenv/bin/activate"
elif [ -f "${SCRIPT_DIR}/../../myenv/bin/activate" ]; then
  source "${SCRIPT_DIR}/../../myenv/bin/activate"
fi

# ---------- 可选 CUDA 设备隔离 ----------
CUDA_DEV="${CUDA_VISIBLE_DEVICES:-}"
if [ -n "${CUDA_DEV}" ]; then
  export CUDA_VISIBLE_DEVICES="${CUDA_DEV}"
  echo "[Z-Image] CUDA_VISIBLE_DEVICES=${CUDA_DEV}"
fi

echo "[Z-Image] 启动图像生成服务 (端口=${HOST_PORT})"
echo "[Z-Image] 服务模型名: ${SERVER_MODELNAME}"
if [ -n "${SERVER_API_KEY}" ]; then
  echo "[Z-Image] API Key 校验已启用"
fi
cd "${SCRIPT_DIR}"
exec python image_gen_server.py --port "${HOST_PORT}" --model-name "${SERVER_MODELNAME}" --api-key "${SERVER_API_KEY}"
