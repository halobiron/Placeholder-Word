"""
Gemini Client for text extraction and document analysis
Used for extracting data from context and analyzing document structure
"""
import json
import re
from google import genai
from typing import Any


class GeminiClient:
    """Simple client for Gemini API - text extraction and analysis"""

    def __init__(self, api_key: str):
        """Initialize Gemini client

        Args:
            api_key: Gemini API key
        """
        if not bool(api_key and api_key != "your_gemini_api_key_here"):
            raise ValueError("GEMINI_API_KEY not configured. Please set it in .env file")

        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-3.1-flash-lite-preview'
        self._usage_total = self._empty_usage()
        self.last_usage = self._empty_usage()

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
            return json.loads(result.strip())
        except json.JSONDecodeError:
            return {}

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

    def extract_data_from_context(
        self,
        context: str,
        template_fields: list,
        template_field_metadata: list | None = None,
    ) -> dict:
        """Extract field values from context text

        Args:
            context: Full text containing data
            template_fields: List of field names to extract

        Returns:
            Dictionary mapping field names to extracted values
        """
        if not template_fields:
            return {}

        if template_field_metadata:
            metadata_by_name = {
                item.get("field_name"): item for item in template_field_metadata if item.get("field_name")
            }
            fields_list = "\n".join(
                [
                    f'- {field_name} | placeholder_goc="{metadata_by_name.get(field_name, {}).get("original_placeholder", "")}" '
                    f'| truoc="{metadata_by_name.get(field_name, {}).get("context_before", "")}" '
                    f'| sau="{metadata_by_name.get(field_name, {}).get("context_after", "")}"'
                    for field_name in template_fields
                ]
            )
        else:
            fields_list = "\n".join([f"- {field_name}" for field_name in template_fields])
        prompt = f"""Bạn là chuyên gia trích xuất dữ liệu từ văn bản.

Danh sách trường cần trích xuất:
{fields_list}

Nhiệm vụ: Đọc đoạn văn bản sau và trích xuất giá trị cho từng trường. Nếu không tìm thấy, để trống.

Văn bản:
{context}

Yêu cầu:
- Chỉ trả về JSON, không có text khác
- Format: {{"field1": "value1", "field2": "value2", ...}}
- Giữ nguyên tên trường chính xác
- Nếu không tìm thấy giá trị, để chuỗi rỗng ""
- Nếu nhiều trường thuộc các phần lặp lại của cùng một mẫu đơn, hãy sử dụng ngữ cảnh, cách xưng hô để phân biệt và trả về giá trị chính xác cho từng trường.
- QUAN TRỌNG: Không lặp lại tiền tố đã có sẵn trong template. Ví dụ:
  - Template "Kính gửi: TÒA ÁN NHÂN DÂN «field»" và context có "TÒA ÁN NHÂN DÂN TP.HCM" → chỉ trả về "TP.HCM"
  - Template "năm 20«field»" và context có "năm 2024" → chỉ trả về "24" (không lặp lại "20")
  - Template "Ban Giám đốc Công ty: «field»" → chỉ trả về tên công ty, không lặp lại "Ban Giám đốc Công ty"
  - Template "Họ và tên: «field»" → chỉ trả về tên người, không lặp lại "Họ và tên:"

JSON:"""

        try:
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
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

            context_str = ""
            if before:
                context_str = f" (Trước: {' | '.join(before)})"
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
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
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

        # Format fields với context cho Gemini
        field_infos = []
        for i, block in enumerate(structured_content):
            text = block.get("text", "")
            if not text:
                continue

            # Tìm section gần nhất (I, II, III, Mục, Phần...)
            section = "unknown"
            for j in range(max(0, i-5), i):
                prev_text = structured_content[j].get("text", "")
                if re.match(r'^(I+|Mục|Phần|Chương)\s', prev_text):
                    section = self._slugify(prev_text) or "section"
                    break

            # Xử lý từng field trong block
            for field in current_fields:
                if field in forced_renames:
                    continue
                if f"«{field}»" not in text:
                    continue

                # Build context string ngắn gọn
                block_type = block.get("type", "paragraph")
                before = ' | '.join(block.get("before_context", [])[-2:])
                after = ' | '.join(block.get("after_context", [])[:2])
                text_snippet = text.replace("\n", " ")[:220]

                info = f"«{field}» | {block_type} | Section:{section}"
                if block_type == "table_cell":
                    info += f" | Row:{block.get('table_row')} Col:{block.get('table_col')} | Text:[{text_snippet}]"
                else:
                    info += f" | Text:[{text_snippet}] | Trước:[{before}] Sau:[{after}]"

                field_infos.append(info)

        if not field_infos:
            return forced_renames

        # Batch process để tránh token limit
        batch_size = 15
        all_renames = dict(forced_renames)

        for i in range(0, len(field_infos), batch_size):
            batch = field_infos[i:i+batch_size]
            batch_text = "\n".join(batch)

            prompt = f"""Đổi tên fields tiếng Việt không dấu, viết đầy đủ (snake_case):

{batch_text}

QUY TẮC CƠ BẢN:
1. VIẾT ĐẦY ĐỦ, không viết tắt: ho_ten (không phải ht), ten_doanh_nghiep (không phải tdn)
2. Thêm context vào tên: ho_ten_nha_dau_tu_ca_nhan, ten_bang_nuoc_ngoai
3. Giữ nguyên prefix: ck_, ngay_, thang_, nam_
4. Max 20 ký tự, ưu tiên rõ nghĩa hơn ngắn
5. Dùng section/table context thay vì _1, _2, _3

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

            try:
                response = self.client.models.generate_content(model=self.model_name, contents=prompt)
                self._record_usage(response)
                result = self.parse_gemini_json_response(response.text)

                for item in result.get("renames", []):
                    old = item.get("current_name", "")
                    new = item.get("suggested_name", "")
                    if old and new and old != new:
                        all_renames[old] = new
                        print(f"{old} → {new}")

            except Exception as e:
                print(f"Gemini batch error: {e}")
                continue

        print(f"=== Total renames: {len(all_renames)} ===")
        all_renames.update(forced_renames)
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
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
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
