# Fine-tune to vLLM

Luồng được cấu hình sẵn trong repo này:

1. Fine-tune bằng `LlamaFactory`
2. Export + merge adapter `mail_merge_qwen3_context_aware_lora`
3. Serve model merged bằng `vLLM`
4. Cho backend dùng `AI_PROVIDER=vllm`

## 1) Export model merged

Từ thư mục repo:

```bash
cd backend
./scripts/export-finetuned-model.sh
```

Config export nằm ở `backend/LlamaFactory/examples/mail-merge-qwen3-context-aware-export.yaml`.

Output mặc định:

```bash
backend/LlamaFactory/saves/mail_merge_qwen3_context_aware_merged
```

## 2) Chạy vLLM

Sau khi đã cài `vllm` trong môi trường Python phù hợp:

```bash
cd backend
VLLM_API_KEY=EMPTY ./scripts/serve-vllm.sh
```

Endpoint mặc định:

```bash
http://localhost:8001/v1
```

## 3) Cho app dùng model đã deploy

Sửa `backend/.env`:

```bash
AI_PROVIDER=vllm
VLLM_MODEL=mail-merge-qwen3-context-aware
VLLM_BASE_URL=http://localhost:8001/v1
VLLM_API_KEY=EMPTY
VLLM_TIMEOUT_SECONDS=420
VLLM_MAX_TOKENS=0
```

Lưu ý:

- Khi gọi qua `vLLM`, `VLLM_MODEL` nên là tên model được expose bởi server.
- Script `serve-vllm.sh` đang expose `mail-merge-qwen3-context-aware` qua `--served-model-name`.

## 4) Smoke test

```bash
cd backend
python test-vllm.py
```

## 5) Fallback local

Nếu bạn vẫn muốn test nhanh không qua server:

```bash
AI_PROVIDER=finetuned
FINETUNED_PATH=/Users/aiot/Documents/Placeholder-Word/backend/LlamaFactory/saves/mail_merge_qwen3_context_aware_lora
FINETUNED_BASE_MODEL=Qwen/Qwen3-4B-Instruct-2507
```
