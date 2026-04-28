"""
Smart Mail Merge Converter - Full implementation per INSTRUCTIONS.md
Handles Vietnamese forms with XML surgical injection, offset mapping, and smart field naming

Now uses Gemini for intelligent table analysis instead of complex rule-based code.
"""
import re
import unicodedata
import copy
from lxml import etree
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from typing import List, Dict, Optional

# Treat placeholder-like dot runs broadly:
# - ASCII dot/underscore runs need at least 2 chars
# - Unicode ellipsis/dot-leader chars count as a placeholder by themselves
# - Mixed runs such as "...…‥⋯..." stay a single placeholder
# - Dots separated by spaces: ". . . ." or ". . . . . . ." or "... ..." (ALL treated as ONE field)
# - Pattern: dots/underscores with optional spaces between, must contain at least 2 dots/underscores total
# - Updated: (?:[._][.\s]*)*[._]+ to greedily match dots with any spaces in between
PLACEHOLDER_PATTERN = re.compile(r'([._…‥⋯]*[…‥⋯][._…‥⋯]*|(?:[._][.\s]*)*[._]{2,}|[□■]+)')


class SmartMailMergeConverter:
    """Convert Vietnamese .docx forms to Mail Merge templates with intelligent field naming"""

    def __init__(self, doc_path, gemini_api_key: Optional[str] = None):
        """Initialize converter with document

        Args:
            doc_path: Path to input .docx file
            gemini_api_key: Optional Gemini API key for intelligent table analysis
        """
        self.doc = Document(doc_path)
        self.gemini_api_key = gemini_api_key
        self._gemini_client = None
        self.used_labels = {}   # base_label -> count of times used
        self.all_field_names = []  # ordered list of all generated field names (incl. _2, _3)
        self.last_section_label = "field"
        self.last_meaningful_text = "field"
        # Namespace chuẩn cho Word
        self.w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    @property
    def gemini_client(self):
        """Lazy-load Gemini client only when needed"""
        if self._gemini_client is None and self.gemini_api_key:
            from gemini_client import GeminiClient
            try:
                self._gemini_client = GeminiClient(self.gemini_api_key)
            except ValueError:
                # API key not configured, fall back to rule-based
                pass
        return self._gemini_client

    def _slugify(self, text):
        """Chuyển đổi tiếng Việt có dấu thành snake_case không dấu, tối đa 6 từ

        Args:
            text: Vietnamese text with accents

        Returns:
            Snake_case string or None
        """
        if not text or not text.strip():
            return None

        # Loại bỏ nhiễu: (ghi rõ...), nhưng giữ lại %, ( ) trong context hợp lý
        # Dùng regex case-insensitive cho "(ghi rõ..."
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

    def _get_unique_label(self, base_label):
        """Đảm bảo tên field không bị trùng lặp

        Args:
            base_label: Base field name

        Returns:
            Unique field name (adds _2, _3, etc. if needed)
        """
        if base_label not in self.used_labels:
            self.used_labels[base_label] = 1
            result = base_label
        else:
            self.used_labels[base_label] += 1
            result = f"{base_label}_{self.used_labels[base_label]}"
        self.all_field_names.append(result)
        return result

    def _generate_label(self, pre_text, para_context, content=None):
        """Tạo field name và format switch dựa trên text ngay trước placeholder"""
        parts = [p.strip() for p in re.split(r'[:\-–—\._…□■\n]', pre_text) if p.strip()]
        recent = parts[-1] if parts else ""
        label = self._slugify(recent) or self._slugify(pre_text) or self._slugify(para_context) or "field"
        
        # Nếu placeholder gốc là checkbox, thêm tiền tố ck_ để dễ nhận diện khi merge
        if content in ('□', '■'):
            label = f"ck_{label}"
            
        unique_label = self._get_unique_label(label)
        sw = "\\* Upper" if recent.isupper() else "\\* Caps" if recent.istitle() else "\\* MERGEFORMAT"
        return unique_label, sw

    def _process_paragraph(self, paragraph):
        """Xử lý paragraph: inject Mail Merge field với định dạng chính xác

        CRITICAL FIX: Preserve run-level formatting (superscript, subscript, etc.)
        by tracking original run boundaries and splitting text segments accordingly.
        """
        p_element, pattern = paragraph._p, PLACEHOLDER_PATTERN
        if not pattern.search(paragraph.text): return

        # Map định dạng với tracking run boundaries
        # Instead of per-character map, we track: (run_index, start_pos, end_pos, rPr)
        run_ranges = []  # List of (start_pos, end_pos, rPr) tuples
        full_text = ""
        current_pos = 0

        for run in paragraph.runs:
            rPr = run.element.find(f"{self.w_ns}rPr")
            run_text = run.text
            text_len = len(run_text)
            if text_len > 0:
                run_ranges.append((current_pos, current_pos + text_len, rPr))
                full_text += run_text
                current_pos += text_len

        # Helper: find which run a position belongs to
        def get_rpr_at_position(pos):
            for start, end, rPr in run_ranges:
                if start <= pos < end:
                    return rPr
            return None

        # Helper: split a text range at run boundaries to preserve formatting
        def split_text_by_runs(start_pos, end_pos):
            """Split a text range into sub-ranges that respect original run boundaries"""
            result = []  # List of (text, rPr) tuples
            current = start_pos

            while current < end_pos:
                rPr = get_rpr_at_position(current)

                # Find where this run ends (or where our range ends)
                run_end = None
                for r_start, r_end, _ in run_ranges:
                    if r_start <= current < r_end:
                        run_end = min(r_end, end_pos)
                        break

                if run_end is None:
                    run_end = end_pos

                text_segment = full_text[current:run_end]
                if text_segment:
                    # FIX: Append text segment even if rPr is None
                    # Don't skip text just because formatting info is missing
                    result.append((text_segment, rPr))

                current = run_end

            return result

        # Phân mảnh paragraph
        segments, last_idx = [], 0
        for match in pattern.finditer(full_text):
            s, e = match.start(), match.end()
            if s > last_idx:
                # Text segment - will be split by runs later
                segments.append(('text', full_text[last_idx:s], last_idx))
            segments.append(('field', full_text[s:e], s))
            last_idx = e
        if last_idx < len(full_text):
            segments.append(('text', full_text[last_idx:], last_idx))

        # Rebuild XML - text segments are split by original run boundaries
        for r in p_element.findall(f"{self.w_ns}r"): p_element.remove(r)

        for kind, content, offset in segments:
            if kind == 'text':
                # Split text content by original run boundaries to preserve formatting
                text_parts = split_text_by_runs(offset, offset + len(content))

                for text_part, rPr in text_parts:
                    run = OxmlElement('w:r')
                    if rPr is not None: run.append(copy.deepcopy(rPr))
                    t = OxmlElement('w:t')
                    # Preserve whitespace at start OR end (handles tabs, spaces, etc.)
                    if text_part and (text_part[0].isspace() or (len(text_part) > 1 and text_part[-1].isspace())):
                        t.set(qn('xml:space'), 'preserve')
                    t.text = text_part
                    run.append(t)
                    p_element.append(run)
            else:
                # For fields, use rPr from the first character of the matched content
                original_rPr = get_rpr_at_position(offset)
                text_no_dots = pattern.sub('', paragraph.text).strip()
                ctx = paragraph.text if len(text_no_dots) > 5 else self.last_meaningful_text
                label, sw = self._generate_label(full_text[:offset], ctx, content)
                fld = OxmlElement('w:fldSimple')
                fld.set(qn('w:instr'), f' MERGEFIELD {label} {sw} \\z "{content}" ')
                run = OxmlElement('w:r')
                if original_rPr is not None: run.append(copy.deepcopy(original_rPr))
                t = OxmlElement('w:t')
                t.text, _ = f"«{label}»", run.append(t)
                fld.append(run)
                p_element.append(fld)

    def _is_cell_empty(self, cell):
        """Check nếu cell trống hoặc chỉ có whitespace

        Args:
            cell: Table cell object

        Returns:
            True nếu cell trống
        """
        # Check nếu cell đã có merge field rồi → không considered empty
        tc = cell._element
        if tc.find(f"{self.w_ns}fldSimple") is not None:
            return False
        # Check các paragraph con có merge field không
        for para in cell.paragraphs:
            if para._element.find(f"{self.w_ns}fldSimple") is not None:
                return False

        text = cell.text.strip()
        return not text or not any(c.isalpha() or c.isdigit() for c in text)

    def _insert_field_in_cell(self, cell, field_name):
        """Insert mail merge field vào empty cell

        Args:
            cell: Table cell object
            field_name: Name cho merge field
        """
        # Clear existing content
        for para in cell.paragraphs:
            for run in para.runs:
                run.text = ""

        # Get first paragraph or create new
        if not cell.paragraphs:
            para = cell.add_paragraph()
        else:
            para = cell.paragraphs[0]

        # Clear runs
        for run in para.runs:
            run._element.getparent().remove(run._element)

        # Create merge field
        unique_label = self._get_unique_label(field_name)
        p_element = para._p

        fld = OxmlElement('w:fldSimple')
        fld.set(qn('w:instr'), f' MERGEFIELD {unique_label} \\* MERGEFORMAT ')
        run = OxmlElement('w:r')
        t = OxmlElement('w:t')
        t.text = f"«{unique_label}»"
        run.append(t)
        fld.append(run)
        p_element.append(fld)

    def _process_table_auto_fill(self, table):
        """Xử lý bảng: dùng Gemini để analyze và auto-fill placeholders vào empty cells

        Args:
            table: Table object
        """
        if len(table.rows) <= 1:
            return  # Table chỉ có header, không có data rows

        # Try Gemini first if available
        if self.gemini_client:
            try:
                self._process_table_with_gemini(table)
                return
            except Exception as e:
                print(f"  → Gemini table analysis failed: {e}, falling back to rule-based")
                # Fall through to rule-based

        # Fallback: simple rule-based (simplified version)
        self._process_table_rule_based(table)

    def _process_table_with_gemini(self, table):
        """Dùng Gemini để analyze table và suggest placeholders

        Args:
            table: Table object
        """
        # Extract table data for Gemini
        table_data = []
        for row_idx, row in enumerate(table.rows):
            row_data = []
            for cell in row.cells:
                text = cell.text.strip()
                # Check if cell already has merge field or is truly empty
                is_empty = self._is_cell_empty(cell)
                row_data.append({
                    "text": text,
                    "is_empty": is_empty,
                    "row": row_idx,
                    "col": len(row_data)
                })
            table_data.append(row_data)

        # Get document context (paragraphs before/after table)
        context_parts = []
        table_element = table._element
        found_table = False

        for child in self.doc.element.body.iterchildren():
            if child == table_element:
                found_table = True
                break
            if child.tag.endswith("p"):
                para = Paragraph(child, self.doc)
                if para.text.strip():
                    context_parts.append(para.text.strip())
                    if len(context_parts) >= 2:
                        break

        document_context = " | ".join(context_parts[-2:]) if context_parts else ""

        # Ask Gemini for suggestions
        result = self.gemini_client.analyze_table_for_placeholders(
            table_data=table_data,
            document_context=document_context
        )

        # Apply suggestions
        for suggestion in result.get("suggestions", []):
            row = suggestion.get("row")
            col = suggestion.get("col")
            field_name = suggestion.get("field_name")

            if row is not None and col is not None and field_name:
                if 0 <= row < len(table.rows):
                    row_obj = table.rows[row]
                    # Handle merged cells - find actual cell at column
                    current_col = 0
                    for cell in row_obj.cells:
                        # Check grid span for merged cells
                        tc = cell._element
                        tcPr = tc.find(f"{self.w_ns}tcPr")
                        grid_span = 1
                        if tcPr is not None:
                            gridSpan = tcPr.find(f"{self.w_ns}gridSpan")
                            if gridSpan is not None:
                                grid_span = int(gridSpan.get(f"{{{self.w_ns}}}val", 1))

                        if current_col <= col < current_col + grid_span:
                            if self._is_cell_empty(cell):
                                self._insert_field_in_cell(cell, field_name)
                                reason = suggestion.get("reason", "")
                                print(f"  → Gemini auto-fill: «{field_name}» at row={row}, col={col} ({reason})")
                            break
                        current_col += grid_span

    def _process_table_rule_based(self, table):
        """Simple rule-based fallback for table auto-fill

        Args:
            table: Table object
        """
        # Assume row 0 is header
        if len(table.rows) < 2:
            return

        header_row = table.rows[0]
        header_texts = [cell.text.strip() for cell in header_row.cells]

        # Process data rows
        for row_idx in range(1, len(table.rows)):
            row = table.rows[row_idx]

            for col_idx, cell in enumerate(row.cells):
                if self._is_cell_empty(cell) and col_idx < len(header_texts):
                    header_text = header_texts[col_idx]
                    if header_text:
                        field_name = self._slugify(header_text)
                        if field_name:
                            # Add row suffix to avoid duplicates
                            field_name = f"{field_name}_row_{row_idx}"
                            self._insert_field_in_cell(cell, field_name)
                            print(f"  → Rule-based auto-fill: «{field_name}» (from header: '{header_text}')")

    def convert(self, output_path, auto_fill_tables=True):
        """Duyệt toàn bộ tài liệu để thực thi chuyển đổi

        Args:
            output_path: Path to save converted document
            auto_fill_tables: If True, auto-fill placeholders in empty table cells

        Returns:
            List of detected field names
        """
        print(f"Đang phân tích tài liệu...")

        for para in self.doc.paragraphs:
            # Kiểm tra nếu dòng này là tiêu đề mục để lưu context (Section-Based)
            text_strip = para.text.strip()
            if text_strip and (text_strip[0].isdigit() or text_strip.isupper()) and len(text_strip) < 50:
                potential_label = self._slugify(text_strip)
                if potential_label:
                    self.last_section_label = potential_label

            self._process_paragraph(para)

            # Cập nhật context text để dùng cho paragraph sau nếu cần
            cleaned = PLACEHOLDER_PATTERN.sub(' ', text_strip).strip()
            if cleaned and any(c.isalpha() for c in cleaned):
                self.last_meaningful_text = cleaned

        # Xử lý Table
        for table in self.doc.tables:
            # First pass: Process existing placeholders
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text_strip = para.text.strip()
                        self._process_paragraph(para)
                        cleaned = PLACEHOLDER_PATTERN.sub(' ', text_strip).strip()
                        if cleaned and any(c.isalpha() for c in cleaned):
                            self.last_meaningful_text = cleaned

            # Second pass: Auto-fill empty cells if enabled
            if auto_fill_tables:
                print(f"  → Đang xử lý bảng auto-fill...")
                self._process_table_auto_fill(table)

        self.doc.save(output_path)
        print(f"Chuyển đổi hoàn tất! File đã lưu tại: {output_path}")

        return self.all_field_names
