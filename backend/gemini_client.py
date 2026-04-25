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
        if not bool(api_key and api_key != "your_gemini_api_key_here"):
            raise ValueError("GEMINI_API_KEY not configured. Please set it in .env file")
            
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('models/gemini-3.1-flash-lite-preview')

    @staticmethod
    def parse_gemini_json_response(response_text: str) -> dict:
        """Parse JSON text returned by Gemini, stripping markdown fences first."""
        result = (response_text or "").strip()

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
- Nếu trường nằm sau một nhãn cố định trong form, chỉ trả về phần biến đổi của dữ liệu.
- Không lặp lại tiền tố đã có sẵn trong template, ví dụ:
  - "Kính gửi: TÒA ÁN NHÂN DÂN [trường]" -> chỉ trả về phần sau "TÒA ÁN NHÂN DÂN"
  - "Ban Giám đốc Công ty: [trường]" -> chỉ trả về tên công ty, không lặp lại "Ban Giám đốc Công ty" hay "Công ty"

JSON:"""

        try:
            response = self.model.generate_content(prompt)
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
            response = self.model.generate_content(prompt)
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
3. Cấm lấy ngữ cảnh cách bởi từ 2 kí tự đặc biệt trở lên hay thiết placeholder ở gần
  * Nếu bạn thấy "ngày (trống) tháng 【«field_1»】 năm 【«field_2»】" -> field_1 PHẢI là "thang_...", field_2 PHẢI là "nam_...". KHÔNG được gán "ngay_..." cho field_1.
  * Tuyệt đối không gán nhãn "ngay_..." cho placeholder đứng sau từ "tháng" hoặc "năm".
4. Tên ngắn gọn, rõ ràng, tiếng Việt không dấu
5. Nếu 2 placeholder giống hệt nhau nhưng ở vị trí khác nhau → dùng context để phân biệt (VD: "nguoi_khoi_kien_1", "nguoi_bi_bien_2")
6. Nếu tên hiện tại ĐÃ RẤT TỐT → giữ nguyên

ĐẶC BIỆT - XỬ LÝ BẢNG (TABLE_CELL):
- Mỗi [TABLE_CELL - Row X, Col Y] là một Ô RIÊNG BIỆT
- Sử dụng vị trí (Row X, Col Y) để phân biệt các placeholder trong bảng
- Tên placeholder nên phản ánh vị trí hoặc ngữ cảnh cụ thể của ô đó
- Ví dụ: "chu_ky_truong_phong_row2_col1" cho ô ở hàng 2 cột 1

ĐẶC BIỆT - XỬ LÝ NGÀY THÁNG (QUAN TRỌNG):
- Pattern "ngày... tháng... năm..." thường có 3 placeholder, nếu có placeholder trước "ngày " thì thường là địa điểm.
- Context lấy từ text gần nhất (VD: "Từ ngày:", "Ngày sinh:", "ngày lập:")
- ĐỪNG đặt tên: ngay_1, ngay_2, ngay_3 hoặc ngay_bat_dau, ngay_2, ngay_3
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
            analysis = self.parse_gemini_json_response(response.text)

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
