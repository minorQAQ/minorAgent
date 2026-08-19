#!/usr/bin/env bash
set -euo pipefail

# ---------- 配置 ----------
HOST_PORT="${HOST_PORT:-8902}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# VoxCPM 模型路径（可覆盖）
VOXCPM_MODEL_PATH="${VOXCPM_MODEL_PATH:-${SCRIPT_DIR}/models/VoxCPM1__5}"
# 鉴权与模型名校验：SERVER_API_KEY / SERVER_MODELNAME 为空时服务端不校验（任意值放行）
SERVER_API_KEY="${SERVER_API_KEY:-}"
SERVER_MODELNAME="${SERVER_MODELNAME:-VoxCPM1.5}"

# ---------- Python 虚拟环境 ----------
if [ -f "${SCRIPT_DIR}/../myenv/bin/activate" ]; then
  source "${SCRIPT_DIR}/../myenv/bin/activate"
elif [ -f "${SCRIPT_DIR}/../../myenv/bin/activate" ]; then
  source "${SCRIPT_DIR}/../../myenv/bin/activate"
fi

# ---------- 可选 CUDA 设备隔离 ----------
CUDA_DEV="${CUDA_VISIBLE_DEVICES:-3}"
export CUDA_VISIBLE_DEVICES="${CUDA_DEV}"

echo "[VoxCPM TTS] 启动流式 TTS 服务 (端口=${HOST_PORT}, CUDA=${CUDA_DEV})"
echo "[VoxCPM TTS] 模型路径: ${VOXCPM_MODEL_PATH}"
echo "[VoxCPM TTS] 服务模型名: ${SERVER_MODELNAME}"
if [ -n "${SERVER_API_KEY}" ]; then
  echo "[VoxCPM TTS] API Key 校验已启用"
fi
cd "${SCRIPT_DIR}"
exec python streaming_tts_server.py \
  --port "${HOST_PORT}" \
  --model-path "${VOXCPM_MODEL_PATH}" \
  --model-name "${SERVER_MODELNAME}" \
  --api-key "${SERVER_API_KEY}"
