#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

MODEL_PATH="${1:-/Users/aiot/Documents/Placeholder-Word/backend/LlamaFactory/saves/mail_merge_qwen3_context_aware_merged}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8001}"
API_KEY="${VLLM_API_KEY:-EMPTY}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.9}"

echo "🚀 Starting vLLM"
echo "   model: ${MODEL_PATH}"
echo "   host: ${HOST}:${PORT}"

vllm serve "${MODEL_PATH}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --api-key "${API_KEY}" \
  --served-model-name mail-merge-qwen3-context-aware \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_UTIL}"

