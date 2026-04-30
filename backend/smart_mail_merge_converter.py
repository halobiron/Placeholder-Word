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
TERMINAL_TAB_PLACEHOLDER_PATTERN = re.compile(r'\t+$')


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

    def _get_special_elements(self, run_element):
        """Extract special elements from a run (footnoteReference, endnoteReference, br, cr, etc.)

        Args:
            run_element: The w:r element

        Returns:
            List of special elements that should be preserved

        NOTE: Tab elements are EXCLUDED to avoid duplication with tab characters in text
        """
        special_elements = []
        # Special elements to preserve (before text) - EXCLUDING 'tab'
        for tag in ['footnoteReference', 'endnoteReference', 'br', 'cr', 'noBreakHyphen']:
            elem = run_element.find(f"{self.w_ns}{tag}")
            if elem is not None:
                special_elements.append(copy.deepcopy(elem))
        return special_elements

    def _paragraph_has_placeholder_tab(self, paragraph, full_text):
        """Return True when a trailing tab behaves like a fill-in placeholder.

        Word often renders dotted fill areas via paragraph tab stops (`w:pPr/w:tabs`)
        plus a terminal `w:tab` run, so there may be no literal dots in the XML.
        """
        if not full_text or not TERMINAL_TAB_PLACEHOLDER_PATTERN.search(full_text):
            return False

        visible_prefix = full_text.rstrip("\t").rstrip()
        if not visible_prefix:
            return False

        has_tab_run = any(run.element.find(f"{self.w_ns}tab") is not None for run in paragraph.runs)
        if not has_tab_run:
            return False

        p_pr = paragraph._p.find(f"{self.w_ns}pPr")
        tabs = p_pr.find(f"{self.w_ns}tabs") if p_pr is not None else None
        if tabs is None:
            return visible_prefix.endswith(":")

        for tab in tabs.findall(f"{self.w_ns}tab"):
            leader = tab.get(qn("w:leader"))
            if leader in {"dot", "middleDot", "heavy", "underscore"}:
                return True

        return visible_prefix.endswith(":")

    def _process_paragraph(self, paragraph):
        """Xử lý paragraph: inject Mail Merge field với định dạng chính xác

        CRITICAL FIX: Preserve run-level formatting (superscript, subscript, etc.)
        by tracking original run boundaries and splitting text segments accordingly.
        EXTENDED: Also preserve special elements like footnoteReference, endnoteReference, tab, br.
        """
        p_element, pattern = paragraph._p, PLACEHOLDER_PATTERN

        # Map định dạng với tracking run boundaries
        # Track: (start_pos, end_pos, rPr, special_elements)
        run_ranges = []  # List of (start_pos, end_pos, rPr, special_elements) tuples
        full_text = ""
        current_pos = 0

        for run in paragraph.runs:
            rPr = run.element.find(f"{self.w_ns}rPr")
            special_elements = self._get_special_elements(run.element)
            run_text = run.text
            text_len = len(run_text)
            if text_len > 0:
                run_ranges.append((current_pos, current_pos + text_len, rPr, special_elements))
                full_text += run_text
                current_pos += text_len

        has_pattern_placeholder = bool(pattern.search(full_text))
        has_terminal_tab_placeholder = self._paragraph_has_placeholder_tab(paragraph, full_text)
        if not has_pattern_placeholder and not has_terminal_tab_placeholder:
            return

        # Helper: find which run a position belongs to
        def get_run_info_at_position(pos):
            for start, end, rPr, special_elements in run_ranges:
                if start <= pos < end:
                    return rPr, special_elements
            return None, []

        # Helper: split a text range at run boundaries to preserve formatting
        def split_text_by_runs(start_pos, end_pos):
            """Split a text range into sub-ranges that respect original run boundaries"""
            result = []  # List of (text, rPr, special_elements) tuples
            current = start_pos

            while current < end_pos:
                rPr, special_elements = get_run_info_at_position(current)

                # Find where this run ends (or where our range ends)
                run_end = None
                for r_start, r_end, _, _ in run_ranges:
                    if r_start <= current < r_end:
                        run_end = min(r_end, end_pos)
                        break

                if run_end is None:
                    run_end = end_pos

                text_segment = full_text[current:run_end]
                if text_segment:
                    # FIX: Append text segment even if rPr is None
                    # Don't skip text just because formatting info is missing
                    result.append((text_segment, rPr, special_elements))

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

        if has_terminal_tab_placeholder:
            tab_match = TERMINAL_TAB_PLACEHOLDER_PATTERN.search(full_text)
            if tab_match is not None:
                tab_start, tab_end = tab_match.span()
                if not any(
                    kind == 'field' and offset <= tab_start < offset + len(content)
                    for kind, content, offset in segments
                ):
                    if segments and segments[-1][0] == 'text' and segments[-1][2] <= tab_start:
                        text_content, text_offset = segments[-1][1], segments[-1][2]
                        leading_text = text_content[:tab_start - text_offset]
                        trailing_text = text_content[tab_end - text_offset:]
                        segments.pop()
                        if leading_text:
                            segments.append(('text', leading_text, text_offset))
                        segments.append(('field', full_text[tab_start:tab_end], tab_start))
                        if trailing_text:
                            segments.append(('text', trailing_text, tab_end))
                    else:
                        segments.append(('field', full_text[tab_start:tab_end], tab_start))
                    segments.sort(key=lambda item: item[2])

        # Rebuild XML - text segments are split by original run boundaries
        for r in p_element.findall(f"{self.w_ns}r"): p_element.remove(r)

        for kind, content, offset in segments:
            if kind == 'text':
                # Split text content by original run boundaries to preserve formatting
                text_parts = split_text_by_runs(offset, offset + len(content))

                for text_part, rPr, special_elements in text_parts:
                    run = OxmlElement('w:r')
                    if rPr is not None: run.append(copy.deepcopy(rPr))

                    # Add special elements (footnoteReference, etc.) before text
                    for elem in special_elements:
                        run.append(copy.deepcopy(elem))

                    t = OxmlElement('w:t')
                    # Preserve whitespace at start OR end (handles tabs, spaces, etc.)
                    if text_part and (text_part[0].isspace() or (len(text_part) > 1 and text_part[-1].isspace())):
                        t.set(qn('xml:space'), 'preserve')
                    t.text = text_part
                    run.append(t)
                    p_element.append(run)
            else:
                # For fields, use rPr from the first character of the matched content
                original_rPr, original_special = get_run_info_at_position(offset)
                text_no_dots = pattern.sub('', paragraph.text).strip()
                ctx = paragraph.text if len(text_no_dots) > 5 else self.last_meaningful_text
                label, sw = self._generate_label(full_text[:offset], ctx, content)
                fld = OxmlElement('w:fldSimple')
                fld.set(qn('w:instr'), f' MERGEFIELD {label} {sw} \\z "{content}" ')
                run = OxmlElement('w:r')
                if original_rPr is not None: run.append(copy.deepcopy(original_rPr))
                # Add special elements for merge fields too
                for elem in original_special:
                    run.append(copy.deepcopy(elem))
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

    def _normalize_text_for_matching(self, text):
        """Normalize text cho keyword matching (bỏ dấu, lowercase)

        Args:
            text: Text để normalize

        Returns:
            Normalized text
        """
        if not text:
            return ""

        # Xử lý chữ đ/Đ đặc biệt
        text = text.replace('đ', 'd').replace('Đ', 'D')

        # Normalize Unicode
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')

        # Lowercase và remove special chars
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)

        return text

    def _analyze_context_requirements(self, context_data):
        """Phân tích context để determine số lượng fields cần điền

        Args:
            context_data: Dict/list containing fields to fill

        Returns:
            Dict với:
                - total_fields: Tổng số fields cần
                - field_names: List tên fields
                - table_fields: Fields thuộc về table (detected by keywords)
        """
        if isinstance(context_data, list):
            return {
                "total_fields": len(context_data),
                "field_names": context_data,
                "table_fields": []
            }

        # Nếu context phức tạp với sections
        total = 0
        fields = []
        table_fields = []

        # Keywords để detect table-related sections (cả có dấu và không dấu)
        table_keywords_raw = [
            "vốn góp", "nhà đầu tư", "mục tiêu hoạt động", "vsic", "cpc",
            "số vốn", "tỷ lệ", "quốc tịch", "phương thức", "tiến độ",
            "von gop", "nha dau tu", "muc tieu hoat dong", "so von", "ty le",
            "quoc tich", "phuong thuc", "tien do"
        ]

        # Normalize keywords
        table_keywords = [self._normalize_text_for_matching(kw) for kw in table_keywords_raw]

        for section, data in context_data.items():
            if isinstance(data, list):
                section_fields = data
                total += len(section_fields)
                fields.extend(section_fields)

                # Detect nếu section liên quan đến table (normalize cả section name)
                section_normalized = self._normalize_text_for_matching(section)
                if any(kw in section_normalized for kw in table_keywords):
                    table_fields.extend(section_fields)
            elif isinstance(data, dict):
                # Nested dict structure
                for key, value in data.items():
                    if isinstance(value, list):
                        total += len(value)
                        fields.extend(value)
                        key_normalized = self._normalize_text_for_matching(key)
                        if any(kw in key_normalized for kw in table_keywords):
                            table_fields.extend(value)

        return {
            "total_fields": total,
            "field_names": fields,
            "table_fields": table_fields
        }

    def _count_empty_cells_in_table(self, table, skip_merged=True):
        """Đếm số empty cells available trong bảng

        Args:
            table: Table object
            skip_merged: If True, skip merged cells when counting

        Returns:
            Số empty cells
        """
        empty_count = 0
        merged_count = 0

        for row in table.rows:
            for cell in row.cells:
                # Check if cell is part of a merge
                if skip_merged:
                    tc = cell._element
                    tcPr = tc.find(f"{self.w_ns}tcPr")
                    if tcPr is not None:
                        # Check for vMerge (vertical merge)
                        vmerge = tcPr.find(f"{self.w_ns}vMerge")
                        # Check for gridSpan (horizontal merge)
                        gridSpan = tcPr.find(f"{self.w_ns}gridSpan")
                        if vmerge is not None or gridSpan is not None:
                            merged_count += 1
                            continue

                if self._is_cell_empty(cell):
                    empty_count += 1

        return empty_count

    def _get_table_structure(self, table):
        """Lấy cấu trúc bảng để determine columns per row

        Args:
            table: Table object

        Returns:
            Dict với:
                - header_row: Row index của header (thường là 0)
                - data_rows: Số data rows
                - columns: Số columns (trừ header)
                - has_header: Bool
        """
        if len(table.rows) == 0:
            return {"header_row": 0, "data_rows": 0, "columns": 0, "has_header": False}

        # Assume first row is header if table has > 1 rows
        has_header = len(table.rows) > 1
        header_row = 0 if has_header else -1
        data_rows = len(table.rows) - 1 if has_header else len(table.rows)

        # Count columns from first row
        columns = len(table.rows[0].cells) if table.rows else 0

        return {
            "header_row": header_row,
            "data_rows": data_rows,
            "columns": columns,
            "has_header": has_header
        }

    def _clone_table_row(self, table, template_row):
        """Clone một row trong bảng (giữ nguyên formatting)

        Args:
            table: Table object
            template_row: Row để clone (thường là row đầu tiên sau header)

        Returns:
            New row object
        """
        # XML-based deep copy để preserve formatting
        new_row_element = copy.deepcopy(template_row._element)

        # Clear content IMMEDIATELY at XML level before inserting
        # This is more reliable than docx API
        for tc in new_row_element.findall(f"{self.w_ns}tc"):
            # Remove ALL paragraphs
            for p in tc.findall(f"{self.w_ns}p"):
                tc.remove(p)

            # Create a single empty paragraph
            new_p = OxmlElement('w:p')
            new_r = OxmlElement('w:r')
            new_t = OxmlElement('w:t')
            new_t.text = ""
            new_r.append(new_t)
            new_p.append(new_r)
            tc.append(new_p)

        # CRITICAL FIX: Insert at the END of table to avoid index shifting issues
        # Get last row and insert after it
        last_row = table.rows[-1]
        last_row._element.addnext(new_row_element)

        # Force table to reindex
        table._tbl.findall(f"{self.w_ns}tr")

        # Get reference to newly added row (now at the end)
        new_row = table.rows[-1]
        return new_row

    def _expand_table_for_context(self, table, required_fields, context_hints=None):
        """Tự động thêm rows vào bảng nếu cần

        Args:
            table: Table object
            required_fields: Số fields cần điền vào table này
            context_hints: Optional dict với context về field types

        Returns:
            Dict với:
                - rows_added: Số rows đã thêm
                - total_rows: Tổng số rows sau khi expand
                - empty_cells: Số empty cells sau khi expand
        """
        structure = self._get_table_structure(table)

        if structure["data_rows"] == 0:
            # Table chỉ có header, không expand
            return {
                "rows_added": 0,
                "total_rows": len(table.rows),
                "empty_cells": 0
            }

        # Đếm empty cells hiện có
        empty_cells = self._count_empty_cells_in_table(table)

        # Nếu đã đủ chỗ, không cần thêm
        if empty_cells >= required_fields:
            return {
                "rows_added": 0,
                "total_rows": len(table.rows),
                "empty_cells": empty_cells
            }

        # Calculate rows needed based on EMPTY cells (not total slots)
        # Mỗi row mới thêm sẽ cho ra thêm N empty cells (N = số columns)
        columns = structure["columns"]
        deficit = required_fields - empty_cells

        if deficit <= 0:
            return {
                "rows_added": 0,
                "total_rows": len(table.rows),
                "empty_cells": empty_cells
            }

        # Calculate rows to add (round up)
        # Mỗi row mới thêm sẽ cho ra thêm 'columns' empty cells
        rows_to_add = (deficit // columns) + (1 if deficit % columns else 0)

        # Determine template row (first data row, right after header)
        template_row_idx = 1 if structure["has_header"] else 0
        if template_row_idx >= len(table.rows):
            template_row_idx = 0

        template_row = table.rows[template_row_idx]

        # Add new rows
        added = 0
        for _ in range(rows_to_add):
            self._clone_table_row(table, template_row)
            added += 1

        # Recount empty cells after expansion
        new_empty_cells = self._count_empty_cells_in_table(table)

        return {
            "rows_added": added,
            "total_rows": len(table.rows),
            "empty_cells": new_empty_cells
        }

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
                self._process_table_auto_fill(table)

        self.doc.save(output_path)

        return self.all_field_names
