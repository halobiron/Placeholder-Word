"""
Gemini Client for text extraction and document analysis
Used for extracting data from context and analyzing document structure
"""
import json
import google.generativeai as genai


class GeminiClient:
    """Simple client for Gemini API - text extraction and analysis"""

    def __init__(self, api_key: str):
        """Initialize Gemini client

        Args:
            api_key: Gemini API key
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('models/gemini-3.1-flash-lite-preview')

    def extract_data_from_context(
        self,
        context: str,
        template_fields: list
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

        fields_list = "\n".join([f"- {f}" for f in template_fields])
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

JSON:"""

        try:
            response = self.model.generate_content(prompt)
            result = response.text.strip()

            # Clean up response
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            data = json.loads(result.strip())

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
                    content_text.append(f"[TABLE_CELL - Row {row}, Col {col}] #{i+1}{context_str}\n{text_marked}")
                else:
                    content_text.append(f"[{block_type}] #{i+1}{context_str}\n{text_marked}")

        full_content = "\n\n".join(content_text)
        existing_fields_str = ", ".join(existing_fields) if existing_fields else "không có"

        prompt = f"""Bạn là chuyên gia phân tích form văn bản. Hãy phát hiện các vùng CẦN ĐIỀN THÔNG TIN bị thiếu.

NỘI DUNG TÀI LIỆU (với ngữ cảnh xung quanh):
{full_content}

CÁC PLACEHOLDER ĐÃ CÓ (được đánh dấu ✓ trong nội dung):
{existing_fields_str}

NHIỆM VỤ: TÌM CÁC VÙNG CHƯA CÓ PLACEHOLDER.

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
1. Vùng chứa tên người điền (tôi tên, họ và tên, signatory, etc.)
2. Vùng chứa ngày tháng (ngày... tháng... năm, date, etc.) - QUAN TRỌNG: Pattern "ngày... tháng... năm..." cần 3 placeholder riêng biệt
3. Vùng chứa số liệu/CMND/mã số (số, mã, ID, etc.)
4. Vùng chứa địa chỉ/đơn vị (address, company, etc.)
5. Vùng checkbox/trắc nghiệm (□, [ ], etc.)
6. Các vùng trống rõ ràng khác (dấu __, nhiều chấm, khoảng trắng lớn)

QUAN TRỌNG - PATTERN NGÀY THÁNG:
- Nếu thấy pattern "ngày... tháng... năm..." hoặc "ngày... tháng... năm 20..." → TẠO 3 PLACEHOLDER RIÊNG BIỆT
- 3 placeholder này NÊN ở cùng một block hoặc liên tiếp nhau
- Đặt tên gợi ý theo dạng: ngay_<context>, thang_<context>, nam_<context>
- VD: "Từ ngày: ... tháng ... năm ..." → suggested_name: "ngay_bat_dau", "thang_bat_dau", "nam_bat_dau"
- ĐỪNG tạo 3 placeholder ngày như: ngay_1, ngay_2, ngay_3

VỊ TRÍ PLACEHOLDER:
- "left": Chèn TRƯỚC text (VD: "«ho_ten» Nguyễn Văn A")
- "right": Chèn SAU text (VD: "Họ tên: «ho_ten»")
- "new_line": Chèn xuống dòng mới trong cùng block (VD: "Người khởi kiện:\n«nguoi_khoi_kien»")

YÊU CẦU ĐẦU RA:
Trả về JSON với format sau:
{{
  "suggestions": [
    {{
      "context": "<toàn bộ text chính xác của block đó - PHẢI COPY Y NGUYÊN từ danh sách trên>",
      "before_context": [<nội dung 2 blocks trước đó để phân biệt>],
      "after_context": [<nội dung 2 blocks sau đó để phân biệt>],
      "suggested_name": "<tên trường gợi ý>",
      "field_type": "<text|date|checkbox|number>",
      "position": "<left|right|new_line>",
      "reason": "<lý do tại sao cần thêm>",
      "confidence": "<high|medium|low>"
    }}
  ]
}}

Chỉ trả về JSON, không có text khác."""

        try:
            response = self.model.generate_content(prompt)
            result = response.text.strip()

            # Clean up response
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            analysis = json.loads(result.strip())

            # Verify and enhance context matching
            print("=== VERIFYING GEMINI SUGGESTIONS ===")
            for suggestion in analysis.get("suggestions", []):
                suggested_context = suggestion.get("context", "")
                suggested_before = suggestion.get("before_context", [])
                suggested_after = suggestion.get("after_context", [])

                print(f"Suggestion: {suggested_context[:60]}...")
                print(f"  Before: {suggested_before}")
                print(f"  After: {suggested_after}")

                # Find best match using both text AND surrounding context
                best_match = None
                best_score = 0

                for i, block in enumerate(structured_content):
                    block_text = block.get("text", "")
                    block_before = block.get("before_context", [])
                    block_after = block.get("after_context", [])

                    # Calculate combined similarity
                    text_sim = self._calculate_text_similarity(block_text, suggested_context)
                    context_sim = self._calculate_context_list_similarity(
                        suggested_before, suggested_after,
                        block_before, block_after
                    )

                    # Weight: 70% text, 30% context
                    combined_score = 0.7 * text_sim + 0.3 * context_sim

                    if combined_score > best_score:
                        best_score = combined_score
                        best_match = (i, block_text, combined_score)

                if best_match:
                    idx, matched_text, score = best_match
                    print(f"  → Best match [{idx}]: {matched_text[:60]}... (score: {score:.2f})")
                    # Update with actual block data
                    suggestion["block_index"] = idx
                    suggestion["context"] = matched_text
                    suggestion["before_context"] = structured_content[idx].get("before_context", [])
                    suggestion["after_context"] = structured_content[idx].get("after_context", [])

            print("=== END VERIFICATION ===")
            return analysis

        except Exception as e:
            print(f"Gemini analysis error: {e}")
            return {"suggestions": []}

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts"""
        import re
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) if union else 0.0

    def _calculate_context_list_similarity(
        self,
        suggested_before: list,
        suggested_after: list,
        block_before: list,
        block_after: list
    ) -> float:
        """Calculate similarity between surrounding context lists"""
        import re

        # Convert lists to text for comparison
        s_before = " ".join(suggested_before).lower()
        s_after = " ".join(suggested_after).lower()
        b_before = " ".join(block_before).lower()
        b_after = " ".join(block_after).lower()

        # Extract words
        s_words = set(re.findall(r'\w+', s_before + " " + s_after))
        b_words = set(re.findall(r'\w+', b_before + " " + b_after))

        if not s_words or not b_words:
            return 0.0

        intersection = s_words & b_words
        union = s_words | b_words

        return len(intersection) / len(union) if union else 0.0

    def suggest_better_field_names(
        self,
        structured_content: list,
        current_fields: list
    ) -> dict:
        """Phân tích các placeholder hiện có và đề xuất tên tốt hơn

        Args:
            structured_content: List của content blocks với placeholder (format «field_name»)
            current_fields: Danh sách tên field hiện tại

        Returns:
            Dict mapping current_field_name -> better_field_name
        """
        # Format content để hiển thị placeholder rõ ràng
        content_with_placeholders = []
        for i, block in enumerate(structured_content):
            block_type = block.get("type", "paragraph")
            text = block.get("text", "").strip()

            # Add surrounding context
            before = block.get("before_context", [])
            after = block.get("after_context", [])

            context_str = ""
            if before:
                context_str = f" (Trước: {' | '.join(before)})"
            if after:
                context_str += f" (Sau: {' | '.join(after)})"

            if text:
                # Highlight placeholders in text
                text_marked = text
                import re
                for field in current_fields:
                    if field in text:
                        text_marked = text_marked.replace(f"«{field}»", f"【«{field}»】")

                # Add special prefix for table_cell to make it clear these are individual cells
                if block_type == "table_cell":
                    row = block.get("table_row", "?")
                    col = block.get("table_col", "?")
                    content_with_placeholders.append(f"[TABLE_CELL - Row {row}, Col {col}] #{i+1}{context_str}\n{text_marked}")
                else:
                    content_with_placeholders.append(f"[{block_type}] #{i+1}{context_str}\n{text_marked}")

        full_content = "\n\n".join(content_with_placeholders)
        fields_list = "\n".join([f"- {f}" for f in current_fields])

        prompt = f"""Bạn là chuyên gia đặt tên trường cho biểu mẫu tiếng Việt.

NỘI DUNG TÀI LIỆU (với placeholder được đánh dấu 【«...»】):
{full_content}

CÁC PLACEHOLDER HIỆN CÓ:
{fields_list}

NHIỆM VỤ: Phân tích từng placeholder và đề xuất TÊN TỐT HƠN bằng tiếng Việt (không dấu, snake_case).

QUY TẮC ĐẶT TÊN:
1. Tên phải phản ánh Ý NGHĨA của trường (VD: "ho_ten", "ngay_sinh", "so_cmnd")
2. Dựa vào NGỮ CẢNH xung quanh (text trước/sau) để hiểu ý nghĩa
3. Tên ngắn gọn, rõ ràng, tiếng Việt không dấu
4. Nếu 2 placeholder giống hệt nhau nhưng ở vị trí khác nhau → dùng context để phân biệt (VD: "nguoi_khoi_kien_1", "nguoi_bi_bien_2")
5. Nếu tên hiện tại ĐÃ RẤT TỐT → giữ nguyên

ĐẶC BIỆT - XỬ LÝ BẢNG (TABLE_CELL):
- Mỗi [TABLE_CELL - Row X, Col Y] là một Ô RIÊNG BIỆT
- Sử dụng vị trí (Row X, Col Y) để phân biệt các placeholder trong bảng
- Tên placeholder nên phản ánh vị trí hoặc ngữ cảnh cụ thể của ô đó
- Ví dụ: "chu_ky_truong_phong_row2_col1" cho ô ở hàng 2 cột 1

ĐẶC BIỆT - XỬ LÝ NGÀY THÁNG (QUAN TRỌNG):
- Pattern "ngày... tháng... năm..." hoặc "ngày... tháng... năm 20..." có 3 placeholder LIÊN TIẾP
- Phải TÁCH thành 3 trường riêng: ngay_<context>, thang_<context>, nam_<context>
- Context lấy từ text gần nhất (VD: "Từ ngày:", "Ngày sinh:", "ngày lập:")
- ĐỪNG đặt tên: ngay_1, ngay_2, ngay_3 hoặc ngay_bat_dau, ngay_2, ngay_3
- VÍ DỤ:
  * "Từ ngày: «field_1» tháng «field_2» năm «field_3»" → ngay_bat_dau, thang_bat_dau, nam_bat_dau
  * "Đến ngày: «field_4» tháng «field_5» năm «field_6»" → ngay_ket_thuc, thang_ket_thuc, nam_ket_thuc
  * "[Hà Nội], ngày «field_7» tháng «field_8» năm «field_9»" → ngay_lap, thang_lap, nam_lap
  * "Ngày sinh: «field_10» tháng «field_11» năm «field_12»" → ngay_sinh, thang_sinh, nam_sinh
- Nếu có 2 trường ngày tháng giống nhau → dùng số thứ tự: ngay_bat_dau_1, thang_bat_dau_1, nam_bat_dau_1

VÍ DỤ KHÁC:
- "Họ tên: «field_1»" → "ho_ten"
- "□ Nghỉ không lương «field_2»" → "nghi_khong_luong"
- "Số CMND: «field_3»" → "so_cmnd"
- "[TABLE_CELL - Row 2, Col 1] «field_4»" → "chu_ky_nguoi_lap"

YÊU CẦU ĐẦU RA:
Trả về JSON với format sau:
{{
  "renames": [
    {{
      "current_name": "<tên placeholder hiện tại>",
      "suggested_name": "<tên mới tốt hơn>",
      "reason": "<lý do đổi tên>",
      "confidence": "<high|medium|low>"
    }}
  ]
}}

Chỉ trả về JSON, không có text khác."""

        try:
            response = self.model.generate_content(prompt)
            result = response.text.strip()

            # Clean up response
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            analysis = json.loads(result.strip())

            # Convert to mapping
            rename_map = {}
            print("=== GEMINI SUGGESTED RENAMES ===")
            for item in analysis.get("renames", []):
                current = item.get("current_name", "")
                suggested = item.get("suggested_name", "")
                reason = item.get("reason", "")

                if current and suggested and current != suggested:
                    rename_map[current] = suggested
                    print(f"{current} → {suggested}")
                    print(f"  Lý do: {reason}")
                elif current and suggested and current == suggested:
                    print(f"{current} ✓ (giữ nguyên)")

            print(f"=== TOTAL SUGGESTIONS: {len(rename_map)} ===")

            return rename_map

        except Exception as e:
            print(f"Gemini rename suggestion error: {e}")
            return {}
