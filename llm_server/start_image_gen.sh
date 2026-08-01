#!/usr/bin/env bash
set -euo pipefail

# ---------- 配置 ----------
HOST_PORT="${HOST_PORT:-8904}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
cd "${SCRIPT_DIR}"
exec python image_gen_server.py --port "${HOST_PORT}"
