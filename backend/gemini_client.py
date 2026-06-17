"""
Gemini Client for text extraction and document analysis
Used for extracting data from context and analyzing document structure
"""
import json
import logging
import re
import urllib.error
import urllib.request
from google import genai
from typing import Any

# Lazy load torch only when fine-tuned model is used
torch = None

# Tắt các log info lặp lại từ google_genai và httpx
logging.getLogger('google_genai.models').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)


class GeminiClient:
    """Simple client for Gemini API - text extraction and analysis"""
    FULL_CONTEXT_PAGE_THRESHOLD = 5
    FINETUNED_RENAME_BATCH_CHAR_LIMIT = 2400
    DEFAULT_RENAME_BATCH_CHAR_LIMIT = 12000

    @staticmethod
    def _resolve_finetuned_load_config(torch_module):
        """Choose a single-device load strategy compatible with PEFT adapter loading."""
        if torch_module.cuda.is_available():
            return {"device": "cuda", "dtype": torch_module.float16}

        mps = getattr(torch_module.backends, "mps", None)
        if mps and mps.is_available():
            return {"device": "mps", "dtype": torch_module.float16}

        return {"device": "cpu", "dtype": torch_module.float32}

    def __init__(
        self,
        api_key: str | None = None,
        provider: str = "gemini",
        model_name: str | None = None,
        ollama_base_url: str = "http://localhost:11434",
        finetuned_path: str | None = None,
        finetuned_base_model: str | None = None,
    ):
        """Initialize Gemini client

        Args:
            api_key: Gemini API key
            provider: AI provider (gemini, ollama, finetuned)
            model_name: Model name for gemini/ollama
            ollama_base_url: Ollama server URL
            finetuned_path: Path to fine-tuned model adapter (for finetuned provider)
            finetuned_base_model: Base model name for fine-tuned model (e.g., Qwen/Qwen2.5-0.5B-Instruct)
        """
        self.provider = (provider or "gemini").strip().lower()
        self.ollama_base_url = (ollama_base_url or "http://localhost:11434").rstrip("/")
        self.client = None
        self.model = None
        self.finetuned_model = None
        self.finetuned_tokenizer = None

        if self.provider == "finetuned":
            if not finetuned_path:
                raise ValueError("FINETUNED_PATH not configured. Please set it in .env file")
            if not finetuned_base_model:
                raise ValueError("FINETUNED_BASE_MODEL not configured. Please set it in .env file")

            # Load fine-tuned model
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                import torch
                from peft import PeftModel

                logging.info(f"Loading fine-tuned model from: {finetuned_path}")
                logging.info(f"Base model: {finetuned_base_model}")
                load_config = self._resolve_finetuned_load_config(torch)
                logging.info(
                    "Fine-tuned model load target: %s (%s)",
                    load_config["device"],
                    load_config["dtype"],
                )

                # Load tokenizer
                print("Loading tokenizer...")
                self.finetuned_tokenizer = AutoTokenizer.from_pretrained(
                    finetuned_base_model,
                    trust_remote_code=True
                )
                if self.finetuned_tokenizer.pad_token_id is None:
                    eos_token = self.finetuned_tokenizer.eos_token
                    if not isinstance(eos_token, str):
                        eos_token_id = self.finetuned_tokenizer.eos_token_id
                        if isinstance(eos_token_id, int):
                            eos_token = self.finetuned_tokenizer.convert_ids_to_tokens(eos_token_id)
                    if isinstance(eos_token, str):
                        self.finetuned_tokenizer.pad_token = eos_token
                    else:
                        self.finetuned_tokenizer.add_special_tokens({"pad_token": "<|pad|>"})
                logging.info("Tokenizer loaded")

                # Load base model with LoRA adapter
                print("Loading base model (this may take 30-60 seconds)...")
                self.finetuned_model = AutoModelForCausalLM.from_pretrained(
                    finetuned_base_model,
                    torch_dtype=load_config["dtype"],
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )
                self.finetuned_model.to(load_config["device"])
                if len(self.finetuned_tokenizer) > self.finetuned_model.get_input_embeddings().num_embeddings:
                    self.finetuned_model.resize_token_embeddings(len(self.finetuned_tokenizer))
                logging.info("Base model loaded")

                # Load LoRA adapter
                print("Loading LoRA adapter...")
                self.finetuned_model = PeftModel.from_pretrained(
                    self.finetuned_model,
                    finetuned_path
                )
                self.finetuned_model.to(load_config["device"])
                logging.info("LoRA adapter loaded")

                self.finetuned_model.eval()
                self.model_name = f"{finetuned_base_model}+{finetuned_path}"
                print(f"✅ Fine-tuned model loaded successfully!")
                logging.info("Fine-tuned model loaded successfully")

            except ImportError as e:
                raise ValueError(
                    f"transformers or peft not installed. Install with: pip install transformers peft torch"
                ) from e
            except Exception as e:
                raise ValueError(f"Failed to load fine-tuned model: {e}") from e

        elif self.provider == "ollama":
            if not (model_name and str(model_name).strip()):
                raise ValueError("AI model is not configured. Set OLLAMA_MODEL in .env")
            self.model_name = str(model_name).strip()

        elif self.provider == "gemini":
            if not (model_name and str(model_name).strip()):
                raise ValueError("AI model is not configured. Set GEMINI_MODEL in .env")
            if not bool(api_key and api_key != "your_gemini_api_key_here"):
                raise ValueError("GEMINI_API_KEY not configured. Please set it in .env file")
            self.client = genai.Client(api_key=api_key)
            self.model_name = str(model_name).strip()

        else:
            raise ValueError(f"Unsupported AI provider: {provider}")

        self._usage_total = self._empty_usage()
        self.last_usage = self._empty_usage()
        self._torch = None  # Will be imported when needed

    def _get_torch(self):
        """Lazy import torch to avoid loading it unnecessarily"""
        if self._torch is None:
            import torch
            self._torch = torch
        return self._torch

    @staticmethod
    def _empty_usage() -> dict[str, int]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def _usage_value(source: Any, *names: str) -> int:
        for name in names:
            val = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
            try:
                if val is not None:
                    return int(val)
            except (TypeError, ValueError):
                pass
        return 0

    def _record_usage(self, response: Any) -> dict:
        if not response:
            return self._empty_usage()

        meta = getattr(response, "usage_metadata", None) or (response.get("usage_metadata") if isinstance(response, dict) else None)

        usage = {
            "prompt_tokens": self._usage_value(meta, "prompt_token_count", "prompt_tokens"),
            "completion_tokens": self._usage_value(
                meta, "candidates_token_count", "candidate_token_count", "output_token_count", "completion_tokens"
            ),
            "total_tokens": self._usage_value(meta, "total_token_count", "total_tokens"),
        }

        usage["total_tokens"] = usage["total_tokens"] or (usage["prompt_tokens"] + usage["completion_tokens"])
        self.last_usage = usage

        for key in self._usage_total:
            self._usage_total[key] += usage.get(key, 0)

        return usage

    def generate_content(self, prompt: str, **_kwargs) -> Any:
        """Generate content using the selected provider.

        Kept compatible with the old google-genai `model.generate_content(prompt)`
        call shape used in template_manager.
        """
        if self.provider == "finetuned":
            return self._generate_finetuned(prompt)
        if self.provider == "ollama":
            return self._generate_ollama(prompt)

        return self.client.models.generate_content(model=self.model_name, contents=prompt)

    def _generate_ollama(self, prompt: str) -> Any:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        request = urllib.request.Request(
            f"{self.ollama_base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed at {self.ollama_base_url}: {exc}") from exc

        class OllamaResponse:
            pass

        result = OllamaResponse()
        result.text = body.get("response", "")
        result.usage_metadata = {
            "prompt_token_count": int(body.get("prompt_eval_count") or 0),
            "candidates_token_count": int(body.get("eval_count") or 0),
            "total_token_count": int(body.get("prompt_eval_count") or 0) + int(body.get("eval_count") or 0),
        }
        return result

    def _generate_finetuned(self, prompt: str) -> Any:
        """Generate content using fine-tuned model"""
        try:
            # Format prompt for Qwen model - use direct text instead of chat template
            # Qwen3 uses chat format but we can also use direct text
            text_prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

            # Tokenize input. Keep the end of the prompt because it contains
            # the required JSON schema and assistant marker. The default right
            # truncation can cut those off and makes the model continue the
            # document context instead of answering with JSON.
            previous_truncation_side = self.finetuned_tokenizer.truncation_side
            self.finetuned_tokenizer.truncation_side = "left"
            try:
                inputs = self.finetuned_tokenizer(
                    text_prompt,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=2048,
                ).to(self.finetuned_model.device)
            finally:
                self.finetuned_tokenizer.truncation_side = previous_truncation_side

            input_ids = inputs["input_ids"]
            attention_mask = inputs["attention_mask"]

            # Generate with optimized settings
            torch = self._get_torch()
            with torch.no_grad():
                im_end_token_id = self.finetuned_tokenizer.convert_tokens_to_ids("<|im_end|>")
                eos_token_ids = [self.finetuned_tokenizer.eos_token_id]
                if isinstance(im_end_token_id, int) and im_end_token_id >= 0:
                    eos_token_ids.append(im_end_token_id)

                outputs = self.finetuned_model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=768,
                    do_sample=False,
                    pad_token_id=self.finetuned_tokenizer.pad_token_id,
                    eos_token_id=eos_token_ids,
                    use_cache=True,  # Enable KV cache for faster generation
                )

            # Decode response
            response_text = self.finetuned_tokenizer.decode(
                outputs[0][input_ids.shape[1]:],
                skip_special_tokens=True
            ).strip()

            # Some chat-tuned local models may still echo role markers or a part
            # of the prompt. Keep only the assistant completion when possible.
            if "<|im_start|>assistant" in response_text:
                response_text = response_text.rsplit("<|im_start|>assistant", 1)[-1]
            if "<|im_end|>" in response_text:
                response_text = response_text.split("<|im_end|>", 1)[0]
            response_text = response_text.strip()

            # Calculate approximate token counts
            prompt_tokens = input_ids.shape[1]
            completion_tokens = outputs.shape[1] - input_ids.shape[1]
            total_tokens = prompt_tokens + completion_tokens

            class FinetunedResponse:
                pass

            result = FinetunedResponse()
            result.text = response_text
            result.usage_metadata = {
                "prompt_token_count": prompt_tokens,
                "candidates_token_count": completion_tokens,
                "total_token_count": total_tokens,
            }
            return result

        except Exception as e:
            logging.error(f"Fine-tuned model generation error: {e}")
            raise RuntimeError(f"Fine-tuned model generation failed: {e}") from e

    def get_usage_summary(self) -> dict:
        """Return cumulative Gemini usage for this client instance."""
        return dict(self._usage_total)

    def reset_usage(self) -> None:
        """Reset cumulative and last usage counters."""
        self._usage_total = self._empty_usage()
        self.last_usage = self._empty_usage()

    @staticmethod
    def _slugify(text):
        """Chuyển đổi tiếng Việt có dấu thành snake_case không dấu

        Args:
            text: Vietnamese text with accents

        Returns:
            Snake_case string or None
        """
        import unicodedata
        import re
        if not text or not text.strip():
            return None

        # Loại bỏ nhiễu: (ghi rõ...), nhưng giữ lại %, ( ) trong context hợp lý
        text = re.sub(r'\(ghi rõ.*?\)', ' ', text, flags=re.IGNORECASE)
        # Giữ lại các ký tự quan trọng: %, VND, USD
        text = re.sub(r'[:\-–—\._…□]', ' ', text)

        # Xử lý chữ đ/Đ đặc biệt trước khi normalize
        text = text.replace('đ', 'd').replace('Đ', 'D')

        # Bình thường hóa tiếng Việt
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')

        # Tìm tất cả words và các token quan trọng (VND, USD, %)
        words = re.findall(r'\w+|%|VND|USD|EUR|GBP|JPY', text.lower())

        # Lấy tất cả các từ (tối đa 10 để tránh quá dài)
        slug = "_".join(words[-10:]) if len(words) > 10 else "_".join(words)

        # Clean up: loại bỏ dấu _ ở đầu/cuối và _ liên tiếp
        slug = re.sub(r'^_+|_+$', '', slug)
        slug = re.sub(r'_+', '_', slug)

        return slug if slug else None

    @staticmethod
    def parse_gemini_json_response(response_text: str) -> dict:
        """Parse JSON from Gemini response, extract JSON block from text."""
        result = (response_text or "").strip()

        # Prefer complete JSON objects that actually contain the expected key.
        # Fine-tuned/local models can echo prompt/context before the answer, so
        # first '{' ... last '}' is unsafe when the echoed prompt contains JSON
        # examples or document text.
        decoder = json.JSONDecoder()
        parsed_objects = []
        for match in re.finditer(r'\{', result):
            try:
                parsed, _ = decoder.raw_decode(result[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                parsed_objects.append(parsed)

        for parsed in reversed(parsed_objects):
            if "renames" in parsed or "suggestions" in parsed or "fields" in parsed:
                return parsed
        if parsed_objects:
            return parsed_objects[-1]

        # Find JSON block between { and }
        json_start = result.find('{')
        json_end = result.rfind('}') + 1

        if json_start >= 0 and json_end > json_start:
            result = result[json_start:json_end]
        else:
            # Fallback: strip markdown fences
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

        try:
            parsed = json.loads(result.strip())
            return parsed
        except json.JSONDecodeError as e:
            print(f"=== JSON PARSE FAILED: {e} ===")
            print(f"=== Raw text to parse: {result[:500]} ===")
            return {}

    @staticmethod
    def _normalize_field_name(value: str) -> str:
        """Return the bare MERGEFIELD name from AI/output placeholder text."""
        if not value:
            return ""

        value = str(value).strip()
        placeholder_match = re.fullmatch(r'[«<]\s*([^»>]+?)\s*[»>]', value)
        if placeholder_match:
            value = placeholder_match.group(1)

        value = value.strip().strip('"\'`')
        mergefield_match = re.search(r'MERGEFIELD\s+([^\s\\]+)', value, flags=re.IGNORECASE)
        if mergefield_match:
            value = mergefield_match.group(1)

        return value.strip().strip('«»<>"\'`')

    def _detect_location_date_line_renames(
        self,
        structured_content: list,
        current_fields: list,
    ) -> dict:
        """Force stable names for Vietnamese place/date signature lines.

        Pattern handled:
            «dia_diem», ngày «ngay» tháng «thang» năm «nam»
        """
        forced = {}
        current_field_set = set(current_fields)
        pattern = re.compile(
            r'«(?P<dia>[^»]+)»\s*,\s*ngày\s*«(?P<ngay>[^»]+)»\s*tháng\s*«(?P<thang>[^»]+)»\s*năm\s*«(?P<nam>[^»]+)»',
            re.IGNORECASE,
        )

        for block in structured_content:
            text = (block.get("text") or "").strip()
            if not text:
                continue

            match = pattern.search(text)
            if not match:
                continue

            rename_targets = {
                match.group("dia"): "dia_diem_lam_don",
                match.group("ngay"): "ngay_lam_don",
                match.group("thang"): "thang_lam_don",
                match.group("nam"): "nam_lam_don",
            }

            for old_name, new_name in rename_targets.items():
                if old_name in current_field_set and old_name != new_name:
                    forced[old_name] = new_name

        return forced

    def _get_document_page_count(self, structured_content: list) -> int | None:
        for block in structured_content or []:
            page_count = block.get("document_page_count")
            if page_count:
                try:
                    return int(page_count)
                except (TypeError, ValueError):
                    return None
        return None

    def _build_section_outline(self, structured_content: list) -> str:
        headings = []
        seen = set()
        for block in structured_content or []:
            heading = (block.get("nearest_heading") or block.get("section_heading") or "").strip()
            if heading and heading not in seen:
                seen.add(heading)
                headings.append(heading)
        return "\n".join(f"- {heading}" for heading in headings[:80])

    def _build_full_document_context(self, structured_content: list) -> str:
        lines = []
        for i, block in enumerate(structured_content or []):
            text = (block.get("text") or "").replace("\n", " ").strip()
            if text:
                lines.append(f"[{i}] {text}")
        return "\n".join(lines)

    def _build_field_context_infos(
        self,
        structured_content: list,
        current_fields: list,
        forced_renames: dict,
    ) -> list[str]:
        field_infos = []

        for i, block in enumerate(structured_content or []):
            text = block.get("text", "")
            if not text:
                continue

            block_fields = [
                field for field in current_fields
                if field not in forced_renames and f"«{field}»" in text
            ]
            if not block_fields:
                continue

            block_type = block.get("type", "paragraph")
            section = block.get("nearest_heading") or block.get("section_heading") or "preamble"
            before = " | ".join(item[:35] for item in block.get("before_context", [])[-1:])
            after = " | ".join(item[:35] for item in block.get("after_context", [])[:1])
            text_snippet = text.replace("\n", " ")[:180]

            fields_text = ", ".join(f"«{field}»" for field in block_fields)
            info = (
                f"Fields:[{fields_text}] | block={i} | {block_type} | "
                f"Section:[{section}] | Text:[{text_snippet}]"
            )
            if block_type == "table_cell":
                info += f" | Row:{block.get('table_row')} Col:{block.get('table_col')}"
            else:
                info += f" | Truoc:[{before}] Sau:[{after}]"

            field_infos.append(info)

        return field_infos

    @staticmethod
    def _extract_fields_from_context_info(info: str) -> list[str]:
        """Extract placeholder names from a compact context line."""
        return [field.strip() for field in re.findall(r'«([^»]+)»', info or "") if field.strip()]

    def _chunk_field_context_infos(self, field_infos: list[str]) -> list[list[str]]:
        """Split rename context into smaller batches so all placeholders reach the model."""
        if not field_infos:
            return []

        char_limit = (
            self.FINETUNED_RENAME_BATCH_CHAR_LIMIT
            if self.provider == "finetuned"
            else self.DEFAULT_RENAME_BATCH_CHAR_LIMIT
        )

        chunks = []
        current_chunk = []
        current_length = 0

        for info in field_infos:
            info_length = len(info) + 1
            if current_chunk and current_length + info_length > char_limit:
                chunks.append(current_chunk)
                current_chunk = []
                current_length = 0

            current_chunk.append(info)
            current_length += info_length

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def extract_data_from_context(
        self,
        context: str,
        template_fields: list,
        full_template_text: str,
        document_page_count: int | None = None,
        current_values: dict | None = None,
    ) -> dict:
        """Extract field values by having Gemini read ENTIRE template at once

        KHÔNG CẦN metadata context nhỏ nữa - Gemini đọc full template và tự
        xác định vị trí từng field. Tiết kiệm 60%+ tokens.

        Args:
            context: Full text containing data
            template_fields: List of field names to extract
            full_template_text: FULL template text - Gemini dùng để tìm vị trí field

        Returns:
            Dictionary mapping field names to extracted values
        """
        if not template_fields:
            return {}

        use_full_context = not document_page_count or document_page_count <= self.FULL_CONTEXT_PAGE_THRESHOLD
        template_context_label = (
            "TEMPLATE ĐẦY ĐỦ"
            if use_full_context
            else "TEMPLATE CONTEXT RÚT GỌN THEO FIELD/SECTION"
        )

        # SIMPLE list of field names - Gemini tự tìm vị trí từ template context
        fields_text = "\n".join([f"- «{field}»" for field in template_fields])
        current_values_block = ""
        if current_values is not None:
            current_values_for_fields = {
                field: str(current_values.get(field, "") or "")
                for field in template_fields
            }
            current_values_json = json.dumps(current_values_for_fields, ensure_ascii=False, indent=2)
            current_values_block = f"""
---

GIÁ TRỊ ĐANG CÓ TRƯỚC TIN NHẮN NÀY:
{current_values_json}

GHI CHÚ KHI ĐÂY LÀ TIN NHẮN ĐÍNH CHÍNH/BỔ SUNG:
- Vẫn phải đọc toàn bộ template context và xét TẤT CẢ fields liên quan đến tin nhắn mới.
- Nếu tin nhắn mới cho thấy một người/vai trò thay đổi, hãy cập nhật cả các field định danh liên quan trong đúng bối cảnh, không chỉ field mô tả nguyện vọng/nội dung.
- Ví dụ: tin mới "bà Nguyễn Thị B có nguyện vọng trực tiếp nuôi con" có thể cần cập nhật cả nguyen_vong_nuoi_con và ho_ten_nguoi_bi_kien nếu template context cho thấy bà B là người bị kiện.
- Nếu field đã có giá trị và tin nhắn chỉ sửa một phần của giá trị đó, trả về giá trị cuối cùng đầy đủ sau khi sửa, giữ các chi tiết cũ không bị nhắc tới.
- Ví dụ: đang có con_chung_thong_tin = "Nguyễn Văn C, sinh ngày 22/2/2026"; tin mới "tên con chung chính xác là Lê Văn T" thì trả về "Lê Văn T, sinh ngày 22/2/2026", không được làm mất ngày sinh.
"""

        # Build prompt - use full template only for small documents.
        prompt = f"""Bạn là chuyên gia điền mẫu văn bản tiếng Việt.

Strategy: {"full_document" if use_full_context else "compact_heading_context"}.
Số trang lưu trong DOCX: {document_page_count or "unknown"}.

{template_context_label} (Gemini tự tìm vị trí từng field trong đây):
{full_template_text}

---

DANH SÁCH FIELD CẦN ĐIỀN:
{fields_text}

{current_values_block}

---

VĂN BẢN CHỨA DỮ LIỆU:
{context}

---

⚠️ QUAN TRỌNG NHẤT - TUYỆT ĐỐI KHÔNG BỊA THÔNG TIN:
- CHỈ được lấy thông tin CÓ TRONG "VĂN BẢN CHỨA DỮ LIỆU"; nếu có mục "GIÁ TRỊ ĐANG CÓ" thì được giữ lại chi tiết cũ từ đó khi tin nhắn mới chỉ sửa một phần
- KHÔNG ĐƯỢC suy luận, đoán mò, hay tạo ra thông tin KHÔNG CÓ trong context
- Nếu context KHÔNG có thông tin mới cho field → PHẢI trả về "" (chuỗi rỗng), trừ trường hợp cần trả về giá trị đầy đủ để giữ chi tiết cũ khi sửa một phần
- Nếu context chỉ có một phần thông tin → CHỈ lấy phần đó, không bịa phần còn lại

VÍ DỤ VỀ VIỆC TRỞ VỀ RỖNG:
- Context: "Nguyễn Văn A, sinh năm 1990"
- Fields: ho_ten, ngay_sinh, dia_chi, cmnd
- Kết quả ĐÚNG: {{"ho_ten": "Nguyễn Văn A", "ngay_sinh": "1990", "dia_chi": "", "cmnd": ""}}
- Kết quả SAI: {{"ho_ten": "Nguyễn Văn A", "ngay_sinh": "1990", "dia_chi": "Hà Nội", "cmnd": "123456"}} ← BỊA!

YÊU CẦU:
1. Đọc template context được cung cấp → hiểu MỖI field nằm ở đâu
2. Phân tích context → điền TẤT CẢ fields cùng lúc
3. Trả về JSON: {{"field1": "value1", "field2": "value2", ...}}

QUY TẮC:
- Giữ nguyên tên trường chính xác
- Không tìm thấy trong context → chuỗi rỗng ""
- KHÔNG lặp lại text đã có trong template:
  * "Kính gửi: TÒA ÁN NHÂN DÂN «field»" + "TÒA ÁN NHÂN DÂN TP.HCM" → "TP.HCM"
  * "năm 20«field»" + "năm 2024" → "24"
  * "Diện tích: «field» m²" + "5,0 ha m²" → "5,0" (KHÔNG lặp m²)
  * "Tỷ lệ: «field» %" + "35.5%" → "35.5" (KHÔNG lặp %)

- Field trùng tên → dùng NGỮ CẢNH section/bảng để phân biệt:
  * stt ở bảng "Cổ đông" → stt_co_dong
  * stt ở bảng "Nhà đầu tư" → stt_nha_dau_tu
  * (KHÔNG dùng stt_1, stt_2 trùng tên)

- Với tài liệu dài, ưu tiên Section gần nhất trong template context. Nếu văn bản dữ liệu nhắc cụ thể một điều/mục, hãy đọc kỹ section tương ứng trước khi điền.

JSON:"""

        try:
            response = self.generate_content(prompt)
            self._record_usage(response)
            data = self.parse_gemini_json_response(response.text)

            # Ensure all fields exist
            for field in template_fields:
                if field not in data:
                    data[field] = ""

            return data

        except Exception as e:
            print(f"Gemini extraction error: {e}")
            # Fallback: empty values
            return {field: "" for field in template_fields}

    def plan_document_text_edits(self, user_request: str, structured_content: list) -> dict:
        """Ask Gemini to locate and propose text-only edits for a DOCX template.

        The returned edits are intentionally limited to existing text replacement.
        Formatting is preserved later by DocxFullEditor when it replaces text
        inside the original DOCX runs.
        """
        editable_blocks = []
        for index, block in enumerate(structured_content or []):
            block_type = block.get("type")
            if block_type not in ("paragraph", "table_cell"):
                continue

            text = (block.get("text") or "").strip()
            if not text or text == "[EMPTY LINE]":
                continue

            section = block.get("nearest_heading") or block.get("section_heading") or ""
            before = " | ".join((block.get("before_context") or [])[-2:])
            after = " | ".join((block.get("after_context") or [])[:2])

            line = (
                f"[{index}] type={block_type}"
                f" section={section!r}"
                f" text={text!r}"
            )
            if block_type == "table_cell":
                line += f" row={block.get('table_row')} col={block.get('table_col')}"
            else:
                line += f" before={before!r} after={after!r}"
            editable_blocks.append(line)

        if not editable_blocks:
            return {"edits": [], "warnings": ["Không tìm thấy block văn bản có thể sửa."]}

        document_context = "\n".join(editable_blocks[:250])

        prompt = f"""Bạn là bộ lập kế hoạch sửa nội dung DOCX tiếng Việt.

Nhiệm vụ: đọc yêu cầu người dùng, tìm đúng vị trí trong danh sách block, và trả về các thao tác THAY THẾ VĂN BẢN hiện có.

YÊU CẦU NGƯỜI DÙNG:
{user_request}

DANH SÁCH BLOCK CÓ THỂ SỬA:
{document_context}

QUY TẮC BẮT BUỘC:
- Chỉ sửa những nội dung người dùng yêu cầu rõ hoặc có thể suy ra chắc chắn từ yêu cầu.
- Không tự viết lại toàn bộ tài liệu.
- Không thêm/xóa bảng, ảnh, paragraph, placeholder hoặc định dạng.
- old_text phải là đoạn văn bản đang có trong đúng block, copy càng chính xác càng tốt.
- new_text là nội dung thay thế cho old_text.
- Nếu không chắc vị trí cần sửa, không tạo edit; thêm lý do vào warnings.
- Với nhiều vị trí giống nhau, chỉ sửa vị trí khớp ngữ cảnh yêu cầu.
- Trả về JSON thuần, không markdown.

SCHEMA:
{{
  "edits": [
    {{
      "block_index": 0,
      "old_text": "văn bản hiện tại",
      "new_text": "văn bản mới",
      "reason": "lý do chọn vị trí này"
    }}
  ],
  "warnings": ["..."]
}}

JSON:"""

        try:
            response = self.generate_content(prompt)
            self._record_usage(response)
            result = self.parse_gemini_json_response(response.text)

            valid_block_indexes = {
                i for i, block in enumerate(structured_content or [])
                if block.get("type") in ("paragraph", "table_cell")
            }
            validated = []
            for edit in result.get("edits", []):
                try:
                    block_index = int(edit.get("block_index"))
                except (TypeError, ValueError):
                    continue

                old_text = str(edit.get("old_text") or "").strip()
                new_text = str(edit.get("new_text") or "")
                if block_index not in valid_block_indexes or not old_text:
                    continue

                validated.append({
                    "block_index": block_index,
                    "old_text": old_text,
                    "new_text": new_text,
                    "reason": str(edit.get("reason") or ""),
                })

            return {
                "edits": validated,
                "warnings": [
                    str(item) for item in result.get("warnings", [])
                    if item is not None
                ],
            }
        except Exception as e:
            print(f"Gemini document edit planning error: {e}")
            return {"edits": [], "warnings": [str(e)]}

    def analyze_document_for_placeholders(
        self,
        structured_content: list,
        existing_fields: list
    ) -> dict:
        """Analyze document structure to detect missing placeholders

        Args:
            structured_content: List of content blocks with text and metadata
            existing_fields: Fields already detected by pattern matching

        Returns:
            Dict with suggested new placeholders and their locations
        """
        # Format content for Gemini with surrounding context AND highlight existing placeholders
        content_text = []
        for i, block in enumerate(structured_content):
            block_type = block.get("type", "paragraph")
            text = block.get("text", "").strip()

            # Add surrounding context for disambiguation
            before = block.get("before_context", [])
            after = block.get("after_context", [])
            heading = block.get("nearest_heading") or block.get("section_heading") or ""

            context_str = ""
            if heading:
                context_str = f" (Section: {heading})"
            if before:
                context_str += f" (Trước: {' | '.join(before)})"
            if after:
                context_str += f" (Sau: {' | '.join(after)})"

            if text:
                # Highlight existing placeholders with special markers 【«...»】
                text_marked = text
                import re
                for field in existing_fields:
                    if field in text:
                        text_marked = text_marked.replace(f"«{field}»", f"【«{field}»】✓")

                # Add special prefix for table_cell to make it clear these are individual cells
                if block_type == "table_cell":
                    row = block.get("table_row", "?")
                    col = block.get("table_col", "?")
                    content_text.append(
                        f"[block_index={i}] [TABLE_CELL - Row {row}, Col {col}]{context_str}\n{text_marked}"
                    )
                else:
                    content_text.append(f"[block_index={i}] [{block_type}]{context_str}\n{text_marked}")

        full_content = "\n\n".join(content_text)
        existing_fields_str = ", ".join(existing_fields) if existing_fields else "không có"

        prompt = f"""Bạn là chuyên gia phân tích form văn bản. Hãy phát hiện các vùng CẦN ĐIỀN THÔNG TIN bị thiếu.

NỘI DUNG TÀI LIỆU (với ngữ cảnh xung quanh):
{full_content}

CÁC PLACEHOLDER ĐÃ CÓ (được đánh dấu ✓ trong nội dung):
{existing_fields_str}

NHIỆM VỤ: TÌM CÁC VÙNG CHƯA CÓ PLACEHOLDER.

QUY TẮC QUAN TRỌNG:
- Mỗi block trong danh sách đã có `block_index` rõ ràng.
- Khi đề xuất một vùng, PHẢI trả về đúng `block_index` của block đó.
- KHÔNG tự suy luận lại bằng mô tả text nếu đã có chỉ số block.
- Chỉ chọn block có chỉ số trong danh sách đầu vào, bắt đầu từ 0.

QUAN TRỌNG - BỎ QUA VỊ TRÍ ĐÃ CÓ PLACEHOLDER:
- Nếu block đã có 【«field_name»】✓ → ĐÃ HOÀN TẤT, BỎ QUA
- CHỈ đề xuất thêm cho block KHÔNG có placeholder 【...】✓
- Ví dụ: "Người khởi kiện: 【«nguoi_khoi_kien»】✓" → ĐÃ CÓ, KHÔNG đề xuất thêm
- Ví dụ: "Người khởi kiện: ........" → CHƯA CÓ, CẦN đề xuất thêm

ĐẶC BIỆT - XỬ LÝ BẢNG (TABLE_CELL):
- Mỗi [TABLE_CELL - Row X, Col Y] là một Ô RIÊNG BIỆT trong bảng
- ĐỪNG nhầm lẫn các ô khác nhau trong cùng một bảng
- Nếu Ô A đã có placeholder 【«field»】✓, KHÔNG đề xuất lại cho Ô A
- Có thể đề xuất cho Ô B, Ô C,... nếu chúng chưa có placeholder
- Mỗi ô chỉ nên có MỘT placeholder

CÁC VÙNG CẦN TÌM:
1. Vùng khoảng trắng lớn (GAPS): Bất kỳ nơi nào có 2 hoặc nhiều hơn dấu cách liên tiếp giữa các từ mà không có dấu câu. Đây là dấu hiệu mạnh nhất của một placeholder bị thiếu (VD: "ngày  tháng", "Họ tên  địa chỉ").
2. Vùng ngày tháng (ngày ... tháng ... năm ...).
3. Vùng chứa tên người điền (tôi tên, họ và tên, signatory, etc.)
4. Vùng chứa số liệu/CMND/mã số (số, mã, ID, etc.)
5. Vùng chứa địa chỉ/đơn vị (address, company, etc.)
6. Vùng checkbox/trắc nghiệm (□, [ ], etc.)
7. Các ký tự trống truyền thống: dấu __, nhiều chấm (...), hoặc khoảng trắng bất thường giữa các nhãn dữ liệu.

QUAN TRỌNG - PHÂN TÍCH CONTEXT TRƯỚC/SAU KHI ĐỀ XUẤT TÊN:
- **BẮT BUỘC**: Khi đề xuất tên placeholder, PHẢI ĐỌC KỸ text TRƯỚC và SAU vùng cần điền
- **Nếu text SAU vùng trống** (trong ngoặc hoặc ngay sau) mô tả LOẠI giấy tờ/tài liệu:
  * Từ khóa: "tài liệu", "giấy tờ", "pháp lý", "chứng từ", "text", "type"
  * Ví dụ: "(Tài liệu về tư cách pháp lý của cá nhân)", "(Giấy tờ tùy thân)", "(Loại văn bản)"
  * Hành động: Thêm prefix `loai_` vào tên
  * Ví dụ: `loai_giay_to_phap_ly`, `loai_chung_tu_tuy_than`

- **Nếu text TRƯỚC vùng trống** là từ khóa chỉ GIÁ TRỊ:
  * Từ khóa: "số:", "mã:", "ngày cấp:", "nơi cấp:", "giá trị:"
  * Ví dụ: "số:", "mã số:", "ngày cấp:"
  * Hành động: GIỮ NGUYÊN tên (đây là giá trị, không phải loại)
  * Ví dụ: `giay_to_phap_ly_so`, `ma_so_thue`, `ngay_cap`

- **Ví dụ thực tế**:
  * Pattern: «...» (Tài liệu về tư cách pháp lý của cá nhân) số:«...»
    * Placeholder 1 (trước mô tả) → `loai_giay_to_phap_ly` (text SAU mô tả loại)
    * Placeholder 2 (sau "số:") → `giay_to_phap_ly_so` (text TRƯỚC là "số:")

VỊ TRÍ PLACEHOLDER:
- "left": Chèn TRƯỚC text (VD: "«ho_ten» Nguyễn Văn A")
- "right": Chèn SAU text (VD: "Họ tên: «ho_ten»")
- "new_line": Chèn xuống dòng mới trong cùng block (VD: "Người khởi kiện:\n«nguoi_khoi_kien»")
- "inline": Chèn GIỮA text - PHẢI cung cấp "insert_after" (VD: "Ngày 20 tháng <<thang>> năm 2024" → position: "inline", insert_after: "Ngày 20 tháng ")
  * Khi dùng "inline", PHẢI thêm "insert_after": "<text cần chèn sau đó>"
  * VD: "Họ và tên: Nguyễn Văn A" → position: "inline", insert_after: "Họ và tên: "
  * VD: "ngày  tháng 12" (có 2 spaces sau ngày) → suggested_name: "ngay_lap", position: "inline", insert_after: "ngày "

YÊU CẦU ĐẦU RA:
Trả về JSON với format sau:
{{
  "suggestions": [
    {{
      "block_index": <số nguyên của block trong danh sách đầu vào>,
      "context": "<toàn bộ text chính xác của block đó - PHẢI COPY Y NGUYÊN từ danh sách trên>",
      "before_context": [<nội dung 2 blocks trước đó để phân biệt>],
      "after_context": [<nội dung 2 blocks sau đó để phân biệt>],
      "suggested_name": "<tên trường gợi ý>",
      "field_type": "<text|date|checkbox|number>",
      "position": "<left|right|new_line|inline>",
      "insert_after": "<text cần chèn sau đó - BẮT BUỘC khi position='inline'>",
      "reason": "<lý do tại sao cần thêm>",
      "confidence": "<high|medium|low>"
    }}
  ]
}}

Chỉ trả về JSON, không có text khác."""

        try:
            response = self.generate_content(prompt)
            self._record_usage(response)
            analysis = self.parse_gemini_json_response(response.text)

            # Normalize suggestions using the explicit block_index returned by Gemini.
            # This is stricter and more accurate than re-matching by similarity.
            print("=== VALIDATING GEMINI SUGGESTIONS ===")
            validated_suggestions = []
            for suggestion in analysis.get("suggestions", []):
                raw_index = suggestion.get("block_index")

                try:
                    block_index = int(raw_index)
                except (TypeError, ValueError):
                    print(f"  → Skipping suggestion with invalid block_index: {raw_index}")
                    continue

                if block_index < 0 or block_index >= len(structured_content):
                    print(f"  → Skipping suggestion with out-of-range block_index: {block_index}")
                    continue

                block = structured_content[block_index]
                matched_text = block.get("text", "")

                print(f"  → Accepted block_index [{block_index}]: {matched_text[:60]}...")
                suggestion["block_index"] = block_index
                suggestion["context"] = matched_text
                suggestion["before_context"] = block.get("before_context", [])
                suggestion["after_context"] = block.get("after_context", [])
                validated_suggestions.append(suggestion)

            analysis["suggestions"] = validated_suggestions
            print("=== END VALIDATION ===")
            return analysis

        except Exception as e:
            print(f"Gemini analysis error: {e}")
            return {"suggestions": []}

    def suggest_better_field_names(
        self,
        structured_content: list,
        current_fields: list
    ) -> dict:
        """Phân tích placeholder và đề xuất tên tốt với context section/table

        Args:
            structured_content: List content blocks với placeholder «field_name»
            current_fields: Danh sách tên field hiện tại

        Returns:
            Dict mapping current_field_name -> better_field_name
        """
        forced_renames = self._detect_location_date_line_renames(
            structured_content,
            current_fields,
        )

        field_infos = self._build_field_context_infos(
            structured_content,
            current_fields,
            forced_renames,
        )

        if not field_infos:
            return forced_renames

        all_renames = dict(forced_renames)

        page_count = self._get_document_page_count(structured_content)
        use_full_context = not page_count or page_count <= self.FULL_CONTEXT_PAGE_THRESHOLD
        section_outline = self._build_section_outline(structured_content)
        full_document_context = self._build_full_document_context(structured_content) if use_full_context else ""

        batch_text = "\n".join(field_infos)
        estimated_tokens = len(batch_text) // 3
        strategy = "full_document" if use_full_context else "compact_heading_context"
        print(
            f"=== Field rename strategy: {strategy}, pages={page_count or 'unknown'}, "
            f"{len(field_infos)} context blocks, ~{estimated_tokens} compact tokens ==="
        )

        document_context_block = ""
        if use_full_context:
            document_context_block = f"""
TÀI LIỆU ĐẦY ĐỦ (vì tài liệu <= {self.FULL_CONTEXT_PAGE_THRESHOLD} trang):
{full_document_context}

---"""
        elif section_outline:
            document_context_block = f"""
DÀN Ý SECTION CỦA TÀI LIỆU (tài liệu dài, không đọc full để tránh tốn token):
{section_outline}

---"""

        prompt_template = """Đổi tên fields tiếng Việt không dấu, viết đầy đủ (snake_case):

Dùng strategy: {strategy}. Số trang lưu trong DOCX: {page_count}.
{document_context_block}

FIELD CONTEXT CẦN ĐỔI TÊN:
{batch_text}

QUY TẮC CƠ BẢN:
1. VIẾT ĐẦY ĐỦ, không viết tắt: ho_ten (không phải ht), ten_doanh_nghiep (không phải tdn)
2. Thêm context vào tên: ho_ten_nha_dau_tu_ca_nhan, ten_bang_nuoc_ngoai
3. Giữ nguyên prefix: ck_, ngay_, thang_, nam_
4. Max 20 ký tự, ưu tiên rõ nghĩa hơn ngắn
5. Dùng section/table context thay vì _1, _2, _3

QUY TẮC CONTEXT THEO ĐỘ DÀI TÀI LIỆU:
- Nếu có TÀI LIỆU ĐẦY ĐỦ: dùng toàn văn để hiểu bối cảnh tổng thể.
- Nếu chỉ có FIELD CONTEXT: ưu tiên Section gần nhất + Text block + Truoc/Sau; KHÔNG suy diễn từ section khác.
- Với tài liệu dài, Section gần nhất là tín hiệu phân biệt chính. Ví dụ field trong "ĐIỀU 4: QUYỀN VÀ NGHĨA VỤ CỦA B" phải mang nghĩa của Bên B, không nhầm sang Bên A ở Điều 3.

QUAN TRỌNG - PHÂN TÍCH CONTEXT TRƯỚC/SAU ĐỂ PHÂN BIỆT LOẠI vs GIÁ TRỊ:
- **BẮT BUỘC**: Khi đổi tên, PHẢI ĐỌC KỸ context text TRƯỚC và SAU placeholder
- **Nếu placeholder có text mô tả SAU nó** (trong ngoặc, ngay sau placeholder):
  * Từ khóa: "tài liệu", "giấy tờ", "pháp lý", "chứng từ", "type", "loại"
  * Ví dụ: «giay_to_phap_ly_so» (Tài liệu về tư cách pháp lý của cá nhân)
  * Hành động: Đổi tên thành `loai_giay_to_phap_ly` (thêm prefix `loai_`)
  * Lý do: Text SAU placeholder mô tả LOẠI giấy tờ, không phải số

- **Nếu placeholder có từ khóa TRƯỚC nó** chỉ GIÁ TRỊ:
  * Từ khóa: "số:", "mã:", "ngày cấp:", "nơi cấp:", "giá trị:"
  * Ví dụ: số:«giay_to_phap_ly_so», mã:«ma_so_thue»
  * Hành động: GIỮ NGUYÊN tên hoặc đổi cho rõ nghĩa hơn (KHÔNG thêm `loai_`)
  * Lý do: Text TRƯỚC placeholder chỉ đây là GIÁ TRỊ (số, mã, ngày), không phải loại

- **Ví dụ thực tế**:
  * Pattern: «giay_to_phap_ly_so» (Tài liệu về tư cách pháp lý) số:«giay_to_phap_ly_so»
    * Placeholder 1 (có text SAU mô tả loại) → `loai_giay_to_phap_ly`
    * Placeholder 2 (có "số:" TRƯỚC) → `giay_to_phap_ly_so` (GIỮ NGUYÊN)

- **Xử lý placeholder trùng tên**:
  * Nếu cùng tên nhưng context khác nhau → phân biệt bằng ý nghĩa, không phải số thứ tự
  * Ví dụ: «giay_to» (loại giấy tờ) và «giay_to» (số giấy tờ)
    * Cái đầu (có mô tả loại sau) → `loai_giay_to`
    * Cái sau (có "số:" trước) → `giay_to_so`

JSON: {{"renames": [{{"current_name": "...", "suggested_name": "..."}}]}}"""

        rename_batches = self._chunk_field_context_infos(field_infos)
        covered_fields = {
            field
            for batch in rename_batches
            for info in batch
            for field in self._extract_fields_from_context_info(info)
        }
        missing_fields = [
            field for field in current_fields
            if field not in forced_renames and field not in covered_fields
        ]

        print(
            f"=== Field rename batching: {len(rename_batches)} batch(es), "
            f"covered={len(covered_fields)}, missing={len(missing_fields)} ==="
        )
        if missing_fields:
            print(f"=== Missing fields from rename context: {missing_fields} ===")

        try:
            current_field_set = set(current_fields)
            for batch_index, batch_infos in enumerate(rename_batches, start=1):
                batch_text = "\n".join(batch_infos)
                batch_fields = {
                    field
                    for info in batch_infos
                    for field in self._extract_fields_from_context_info(info)
                }
                print(
                    f"=== Rename batch {batch_index}/{len(rename_batches)}: "
                    f"{len(batch_infos)} context blocks, {len(batch_fields)} field(s) ==="
                )

                prompt = prompt_template.format(
                    strategy=strategy,
                    page_count=page_count or "unknown",
                    document_context_block=document_context_block,
                    batch_text=batch_text,
                )

                response = self.generate_content(prompt)
                self._record_usage(response)

                print(f"=== Gemini response preview: {response.text[:500]}... ===")

                result = self.parse_gemini_json_response(response.text)
                renames_from_ai = result.get("renames", [])
                print(f"=== AI suggested {len(renames_from_ai)} renames ===")

                for item in renames_from_ai:
                    old = self._normalize_field_name(item.get("current_name", ""))
                    new = self._normalize_field_name(item.get("suggested_name", ""))

                    print(f"  Processing: {old} → {new}")

                    if old and new and old != new:
                        if old not in current_field_set:
                            print(f"    SKIP: field '{old}' not in current_fields")
                            continue
                        all_renames[old] = new
                        print(f"    ✓ ACCEPTED")
                    else:
                        print(f"    SKIP: invalid or no change")

        except Exception as e:
            print(f"Gemini error: {e}")
            import traceback
            traceback.print_exc()

        print(f"=== Total renames: {len(all_renames)} ===")
        return all_renames


    def analyze_table_for_placeholders(
        self,
        table_data: list,
        document_context: str = ""
    ) -> dict:
        """Phân tích bảng và đề xuất placeholders cho các ô trống

        Args:
            table_data: List của rows, mỗi row là list của cells
                [{text: str, is_empty: bool, row: int, col: int}, ...]
            document_context: Ngữ cảnh xung quanh bảng (optional)

        Returns:
            Dict với suggestions cho các ô cần placeholder:
            {
                "suggestions": [
                    {"row": int, "col": int, "field_name": str, "reason": str}
                ]
            }
        """
        # Format table for Gemini
        table_repr = []
        for row_data in table_data:
            row_repr = []
            for cell in row_data:
                text = cell.get("text", "")
                if text:
                    row_repr.append(f'"{text}"')
                else:
                    row_repr.append("[EMPTY]")
            table_repr.append(" | ".join(row_repr))

        table_str = "\n".join([f"Row {i}: {row}" for i, row in enumerate(table_repr)])

        prompt = f"""Bạn là chuyên gia phân tích biểu mẫu tiếng Việt.

BẢNG CẦN PHÂN TÍCH:
{table_str}

NGỮ CẢNH TÀI LIỆU:
{document_context}

NHIỆM VỤ: Xác định các ô TRỐNG cần điền placeholder và đặt tên phù hợp.

QUY TẮC QUAN TRỌNG - BẮT BUỘC:
1. **PHÁT HIỆN CONTEXT CHUNG CỦA BẢNG** trước khi đặt tên cho ô nào
   - Xem các header CỐT LỚN (merged cells, text dài) để hiểu bảng này nói về gì
   - Ví dụ: Nếu thấy header "Tên nhà đầu tư nước ngoài" → context là "nha_dau_tu_nuoc_ngoai"
   - Ví dụ: Nếu thấy header "Thông tin người lao động" → context là "nguoi_lao_dong"

2. **KẾT HỢP CONTEXT CHUNG + HEADER CỘT** cho từng placeholder
   - KHÔNG bao giờ dùng chỉ header cột đơn lẻ
   - Phải có: context_bảng + header_cột
   - Ví dụ Bảng "Nhà đầu tư nước ngoài":
     * Cột "Quốc tịch" → "quoc_tich_nha_dau_tu_nuoc_ngoai" (KHÔNG phải "quoc_tich_row_2")
     * Cột "VNĐ" → "so_von_gop_vnd_nha_dau_tu_nuoc_ngoai"
     * Cột "Tỷ lệ (%)" → "ty_le_von_nha_dau_tu_nuoc_ngoai"

3. **ƯU TIÊN HEADER GẦN NHẤT** cho sub-header cụ thể
   - Row 1 có "VNĐ" → dùng "VNĐ" thay vì "Số vốn góp" từ row 0
   - Row 1 có "Tương đương USD" → dùng đó thay vì "Số vốn góp"

4. **TUYỆT ĐỐI KHÔNG DÙNG SỐ THỨ TỤ** - CẤM BẤT KỲ suffix nào như "_row_1", "_row_2", "_1", "_2", "_3"
   - TÊN KHÔNG ĐƯỢC CHỨA SỐ ở cuối (trừ khi là phần của tên như "ngay_2", "thang_3")
   - MẶC ĐỊNH: Tên đơn giản, không có số thứ tự
   - SAU KHI TẠO TÊN: Kiểm tra lại, nếu tên có "_row_X" hoặc "_X" ở cuối thì XÓA NGAY
   - HỆ THỐNG sẽ tự động xử lý trùng lặp (thêm _2, _3 khi cần)

5. **RÚT GỌN TÊN** - không được quá dài
   - "nha_dau_tu_nuoc_ngoai" là đủ, không cần "thong_tin_nha_dau_tu_nuoc_ngoai"
   - "so_von_gop_vnd" là đủ, không cần "so_von_gop_vnd_nha_dau_tu"

VÍ DỤ ĐÚNG:
- Bảng "Nhà đầu tư nước ngoài" (chỉ 1 row data):
  Row 0: "STT" | "Tên nhà đầu tư nước ngoài" | "Quốc tịch" | "Số vốn góp" | "Số vốn góp"
  Row 1: "STT" | "Tên nhà đầu tư nước ngoài" | "Quốc tịch" | "VNĐ" | "Tương đương USD"
  Row 2: [EMPTY] | [EMPTY] | [EMPTY] | [EMPTY] | [EMPTY]

  → Context bảng: "nha_dau_tu_nuoc_ngoai"
  → Col 0: "stt_nha_dau_tu_nuoc_ngoai"  ← KHÔNG có "_row_2" hay số thứ tự
  → Col 1: "ten_nha_dau_tu_nuoc_ngoai"  ← Tên đơn giản, không đánh số
  → Col 2: "quoc_tich_nha_dau_tu_nuoc_ngoai"  ← ĐÚNG! Context rõ nghĩa
  → Col 3: "so_von_gop_vnd_nha_dau_tu_nuoc_ngoai"
  → Col 4: "so_von_gop_usd_nha_dau_tu_nuoc_ngoai"

- Bảng "Danh sách cổ đông" có 3 rows:
  Row 1: [EMPTY] | [EMPTY]  → "ten_co_dong", "so_co_phan"
  Row 2: [EMPTY] | [EMPTY]  → "ten_co_dong", "so_co_phan"  (Hệ thống sẽ tự thành "ten_co_dong_2", "so_co_phan_2")
  Row 3: [EMPTY] | [EMPTY]  → "ten_co_dong", "so_co_phan"  (Hệ thống sẽ tự thành "ten_co_dong_3", "so_co_phan_3")

  → QUAN TRỌNG: Tất cả rows đều dùng TÊN CƠ BẢN, không đánh số
  → Hệ thống _get_unique_label() sẽ tự thêm _2, _3 khi trùng lặp

ĐẶC BIỆT:
- Nếu ô trống nằm ở cột checkbox (□, [ ]) → thêm prefix "ck_"
- Nếu ô trống là ngày tháng → tên: "ngay_...", "thang_...", "nam_..."
- Nếu ô trống là số tiền/mức lương → tên: "muc_luong_...", "so_tien_..."
- KHÔNG BAO GIỜ thêm suffix "_row_X", "_1", "_2" để phân biệt row
- TẬP TRUNG vào việc tạo TÊN CÓ Ý NGHĨA từ context, để hệ thống tự xử lý trùng lặp

YÊU CẦU ĐẦU RA (JSON chỉ):
{{
  "suggestions": [
    {{"row": 1, "col": 1, "field_name": "ho_ten_nguoi_lap", "reason": "cột Họ tên, context rõ nghĩa"}},
    {{"row": 1, "col": 2, "field_name": "dia_chi_nguoi_lap", "reason": "cột Địa chỉ, không đánh số"}}
  ]
}}

NHỚ: Không bao giờ thêm số thứ tự vào tên. Hệ thống sẽ tự xử lý trùng lặp.

Chỉ trả về JSON, không có text khác."""

        try:
            response = self.generate_content(prompt)
            self._record_usage(response)
            result = self.parse_gemini_json_response(response.text)

            # Validate row/col indices
            validated = []
            num_rows = len(table_data)
            num_cols = len(table_data[0]) if table_data else 0

            for suggestion in result.get("suggestions", []):
                row = suggestion.get("row")
                col = suggestion.get("col")

                if isinstance(row, int) and isinstance(col, int):
                    if 0 <= row < num_rows and 0 <= col < num_cols:
                        validated.append(suggestion)
                    else:
                        print(f"  Skipping invalid position: row={row}, col={col}")

            return {"suggestions": validated}

        except Exception as e:
            print(f"Gemini table analysis error: {e}")
            return {"suggestions": []}
