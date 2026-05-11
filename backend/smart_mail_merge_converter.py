"""
Smart Mail Merge Converter - Full implementation per INSTRUCTIONS.md
Handles Vietnamese forms with XML surgical injection, offset mapping, and smart field naming

Now uses Gemini for intelligent table analysis instead of complex rule-based code.
"""
import re
import copy
import math
from lxml import etree
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from typing import List, Dict, Optional

# Treat placeholder-like dot runs broadly:
# - ASCII dot/underscore runs need at least 2 chars total
# - Unicode ellipsis/dot-leader chars count as a placeholder by themselves
# - Mixed runs such as "...…‥⋯..." stay a single placeholder
# - Dots separated by spaces/newlines: ". . . ." or ". . . . . . ." or "... ..." or multi-line dots (ALL treated as ONE field)
# - Pattern uses lookahead to ensure at least 2 dots/underscores total (including those separated by whitespace)
# - Updated: (?=(?:\s*[._]\s*){2,})(?:\s*[._]\s*)+ to greedily match ALL space/newline-separated dots
PLACEHOLDER_PATTERN = re.compile(r'([._…‥⋯]*[…‥⋯][._…‥⋯]*|(?=(?:\s*[._]\s*){2,})(?:\s*[._]\s*)+|[□■]+)')


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
        """Tạo field name ĐƠN GIẢN - Gemini sẽ rename sau"""
        label = "field"  # Cực kỳ đơn giản

        # Checkbox prefix
        if content in ('□', '■'):
            label = f"ck_{label}"

        # Hệ thống tự thêm _2, _3 nếu trùng
        unique_label = self._get_unique_label(label)

        # Format switch vẫn giữ (preserve uppercase/title case)
        parts = [p.strip() for p in re.split(r'[:\-–—\._…□■\n]', pre_text) if p.strip()]
        recent = parts[-1] if parts else ""
        sw = "\\* Upper" if recent.isupper() else "\\* Caps" if recent.istitle() else "\\* MERGEFORMAT"

        return unique_label, sw

    def _find_placeholder_tab_spans(self, paragraph, full_text):
        """Locate placeholder tabs backed by tab stops with special leaders.

        Only tabs whose corresponding paragraph tab stop uses a visible leader
        are treated as placeholders. Plain alignment tabs are ignored.
        """
        if not full_text or "\t" not in full_text:
            return []

        p_pr = paragraph._p.find(f"{self.w_ns}pPr")
        tabs = p_pr.find(f"{self.w_ns}tabs") if p_pr is not None else None
        if tabs is None:
            return []

        placeholder_leaders = {"dot", "middleDot", "heavy", "underscore"}
        tab_defs = tabs.findall(f"{self.w_ns}tab")
        if not any(tab.get(qn("w:leader")) in placeholder_leaders for tab in tab_defs):
            return []

        spans = []
        tab_index = 0
        current_span = None

        for pos, char in enumerate(full_text):
            if char != "\t":
                if current_span is not None:
                    spans.append(current_span)
                    current_span = None
                continue

            leader = tab_defs[tab_index].get(qn("w:leader")) if tab_index < len(tab_defs) else None
            tab_index += 1

            if leader not in placeholder_leaders:
                if current_span is not None:
                    spans.append(current_span)
                    current_span = None
                continue

            visible_prefix = full_text[:pos].rstrip()
            visible_suffix = full_text[pos + 1:].lstrip()
            if not visible_prefix and not visible_suffix:
                if current_span is not None:
                    spans.append(current_span)
                    current_span = None
                continue

            if current_span is None:
                current_span = [pos, pos + 1]
            elif current_span[1] == pos:
                current_span[1] = pos + 1
            else:
                spans.append(current_span)
                current_span = [pos, pos + 1]

        if current_span is not None:
            spans.append(current_span)

        return [(start, end) for start, end in spans]

    def _has_placeholder(self, paragraph, full_text):
        """Return True when a paragraph contains a detectable placeholder."""
        return bool(PLACEHOLDER_PATTERN.search(full_text)) or bool(
            self._find_placeholder_tab_spans(paragraph, full_text)
        )

    def _strip_placeholder_markers(self, paragraph, text):
        """Remove placeholder markers while preserving surrounding content."""
        if not text:
            return text

        cleaned = PLACEHOLDER_PATTERN.sub(" ", text)
        for start, end in reversed(self._find_placeholder_tab_spans(paragraph, text)):
            cleaned = cleaned[:start] + " " + cleaned[end:]
        return cleaned

    def _is_placeholder_continuation_paragraph(self, paragraph, text):
        """True only for paragraphs that are purely continued placeholder lines.

        This is intentionally stricter than "placeholder-only":
        lines like "- ........" or "□ ........" must stay as separate paragraphs
        and must not be merged into the previous paragraph, otherwise the original
        paragraph break is lost and adjacent placeholders collapse together.
        """
        if not self._has_placeholder(paragraph, text):
            return False

        cleaned = self._strip_placeholder_markers(paragraph, text).strip()
        return cleaned == ""

    def _process_paragraph(self, paragraph):
        """Xử lý paragraph: inject Mail Merge field với định dạng chính xác

        CRITICAL FIX: Preserve run-level formatting (superscript, subscript, etc.)
        by tracking original run boundaries and splitting text segments accordingly.
        EXTENDED: Also preserve special elements like footnoteReference, endnoteReference, br, cr.
        """
        p_element, pattern = paragraph._p, PLACEHOLDER_PATTERN

        # Map định dạng với tracking run boundaries
        # Track: (start_pos, end_pos, rPr, special_elements)
        run_ranges = []  # List of (start_pos, end_pos, rPr, special_elements) tuples
        standalone_special_runs = []  # Runs with no text but preservable child elements
        full_text = ""
        current_pos = 0

        for run in paragraph.runs:
            rPr = run.element.find(f"{self.w_ns}rPr")
            # Preserve inline non-text XML nodes, but exclude tabs because they are
            # already represented in run.text and would be duplicated on rebuild.
            special_elements = []
            for tag in ['footnoteReference', 'endnoteReference', 'br', 'cr', 'noBreakHyphen']:
                elem = run.element.find(f"{self.w_ns}{tag}")
                if elem is not None:
                    special_elements.append(copy.deepcopy(elem))
            run_text = run.text
            text_len = len(run_text)
            if text_len > 0:
                run_ranges.append((current_pos, current_pos + text_len, rPr, special_elements))
                full_text += run_text
                current_pos += text_len
            elif special_elements:
                standalone_special_runs.append((current_pos, rPr, special_elements))

        has_pattern_placeholder = bool(pattern.search(full_text))
        placeholder_tab_spans = self._find_placeholder_tab_spans(paragraph, full_text)
        if not has_pattern_placeholder and not placeholder_tab_spans:
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

        for tab_start, tab_end in placeholder_tab_spans:
            if any(
                kind == 'field' and offset <= tab_start < offset + len(content)
                for kind, content, offset in segments
            ):
                continue

            updated_segments = []
            inserted = False
            for kind, content, offset in segments:
                segment_end = offset + len(content)
                if kind != 'text' or tab_end <= offset or tab_start >= segment_end:
                    updated_segments.append((kind, content, offset))
                    continue

                leading_text = content[:tab_start - offset]
                trailing_text = content[tab_end - offset:]
                if leading_text:
                    updated_segments.append(('text', leading_text, offset))
                updated_segments.append(('field', full_text[tab_start:tab_end], tab_start))
                if trailing_text:
                    updated_segments.append(('text', trailing_text, tab_end))
                inserted = True

            if not inserted:
                updated_segments.append(('field', full_text[tab_start:tab_end], tab_start))
            segments = sorted(updated_segments, key=lambda item: item[2])

        # Rebuild XML - text segments are split by original run boundaries
        for r in p_element.findall(f"{self.w_ns}r"): p_element.remove(r)

        pending_special_idx = 0

        def append_standalone_special_runs(up_to_pos):
            nonlocal pending_special_idx

            while (
                pending_special_idx < len(standalone_special_runs)
                and standalone_special_runs[pending_special_idx][0] <= up_to_pos
            ):
                _, rPr, special_elements = standalone_special_runs[pending_special_idx]
                run = OxmlElement('w:r')
                if rPr is not None:
                    run.append(copy.deepcopy(rPr))
                for elem in special_elements:
                    run.append(copy.deepcopy(elem))
                p_element.append(run)
                pending_special_idx += 1

        for kind, content, offset in segments:
            append_standalone_special_runs(offset)

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
                text_no_dots = self._strip_placeholder_markers(paragraph, paragraph.text).strip()
                ctx = paragraph.text if len(text_no_dots) > 5 else self.last_meaningful_text
                label, sw = self._generate_label(full_text[:offset], ctx, content)

                # Truncate placeholder text for instruction (max 50 chars to avoid XML issues)
                content_short = content[:50] if len(content) > 50 else content
                # Escape quotes in content
                content_short = content_short.replace('"', '\\"')

                fld = OxmlElement('w:fldSimple')
                fld.set(qn('w:instr'), f' MERGEFIELD {label} {sw} \\z "{content_short}" ')
                run = OxmlElement('w:r')
                if original_rPr is not None: run.append(copy.deepcopy(original_rPr))
                # Add special elements for merge fields too
                for elem in original_special:
                    run.append(copy.deepcopy(elem))
                t = OxmlElement('w:t')
                t.text, _ = f"«{label}»", run.append(t)
                fld.append(run)
                p_element.append(fld)

        append_standalone_special_runs(len(full_text))

    def _is_cell_empty(self, cell):
        """Check nếu cell trống hoặc chỉ có whitespace

        Args:
            cell: Table cell object

        Returns:
            True nếu cell trống
        """
        # Sử dụng thư viện fork để kiểm tra fields (an toàn, không modify structure)
        for para in cell.paragraphs:
            if hasattr(para, 'fields') and para.fields:
                return False

        text = cell.text.strip()
        return not text or not any(c.isalpha() or c.isdigit() for c in text)

    def _insert_field_in_cell(self, cell, field_name):
        """Insert mail merge field vào empty cell

        Args:
            cell: Table cell object
            field_name: Name cho merge field

        Note: Uses fork's paragraph.clear() API for cleaner code
        """
        # Get first paragraph or create new
        if not cell.paragraphs:
            para = cell.add_paragraph()
        else:
            para = cell.paragraphs[0]

        # Clear existing content using fork's paragraph.clear() API
        # This replaces manual run iteration and removal
        para.clear()

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
                    # Rule-based fallback: extremely simple naming
                    field_name = "field"
                    self._insert_field_in_cell(cell, field_name)
                    print(f"  → Rule-based auto-fill: «{field_name}» (column {col_idx})")

    def _analyze_context_requirements(self, context_data: Dict[str, List[str]]) -> Dict:
        """Phân tích context data để xác định số lượng fields cần thiết"""
        table_fields = []
        for key, value in context_data.items():
            if isinstance(value, list):
                table_fields.extend(value)
        return {
            "total_fields": len(table_fields),
            "table_fields": table_fields
        }

    def _get_table_structure(self, table) -> Dict:
        """Phân tích cấu trúc của bảng"""
        return {
            "data_rows": max(0, len(table.rows) - 1),
            "has_header": len(table.rows) > 0,
            "columns": len(table.columns) if table.columns else 0
        }

    def _count_empty_cells_in_table(self, table) -> int:
        """Đếm số ô trống trong bảng"""
        count = 0
        for row in table.rows:
            for cell in row.cells:
                if self._is_cell_empty(cell):
                    count += 1
        return count

    def _expand_table_for_context(self, table, required_empty_cells: int) -> Dict:
        """Nhân bản dòng cuối của bảng để tạo thêm ô trống"""
        structure = self._get_table_structure(table)
        empty_cells = self._count_empty_cells_in_table(table)
        rows_added = 0
        
        if empty_cells < required_empty_cells and len(table.rows) > 1:
            template_row = table.rows[-1]
            cells_per_row = len(template_row.cells)
            
            # Đếm số ô trống trong dòng mẫu
            empty_in_template = sum(1 for cell in template_row.cells if self._is_cell_empty(cell))
            if empty_in_template == 0:
                empty_in_template = cells_per_row  # Tránh chia cho 0
                
            cells_needed = required_empty_cells - empty_cells
            rows_to_add = math.ceil(cells_needed / empty_in_template)
            
            for row_idx in range(rows_to_add):
                new_row = table.add_row()
                for i, cell in enumerate(template_row.cells):
                    if i < len(new_row.cells):
                        new_cell = new_row.cells[i]
                        new_cell._element.clear_content()
                        # Copy nguyên XML của paragraph từ dòng mẫu để giữ nguyên định dạng và MERGEFIELD
                        for para in cell.paragraphs:
                            new_para = copy.deepcopy(para._element)

                            # Cập nhật tên MERGEFIELD (tăng hậu tố số)
                            for instrText in new_para.iter(qn('w:instrText')):
                                if instrText.text and 'MERGEFIELD' in instrText.text:
                                    match = re.search(r'MERGEFIELD\s+([^\s\\]+)', instrText.text)
                                    if match:
                                        old_name = match.group(1)
                                        base_name = re.sub(r'_\d+$', '', old_name)
                                        suffix_match = re.search(r'_(\d+)$', old_name)
                                        
                                        if suffix_match:
                                            new_num = int(suffix_match.group(1)) + row_idx + 1
                                        else:
                                            new_num = row_idx + 2
                                            
                                        new_name = f"{base_name}_{new_num}"
                                        instrText.text = instrText.text.replace(old_name, new_name)
                                        
                            # Cập nhật text hiển thị «...» (nếu có)
                            for t in new_para.iter(qn('w:t')):
                                if t.text and '«' in t.text and '»' in t.text:
                                    match = re.search(r'«([^»]+)»', t.text)
                                    if match:
                                        old_display = match.group(1)
                                        base_display = re.sub(r'_\d+$', '', old_display)
                                        suffix_match = re.search(r'_(\d+)$', old_display)
                                        
                                        if suffix_match:
                                            new_num = int(suffix_match.group(1)) + row_idx + 1
                                        else:
                                            new_num = row_idx + 2
                                            
                                        new_display = f"{base_display}_{new_num}"
                                        t.text = t.text.replace(f"«{old_display}»", f"«{new_display}»")
                                        
                            new_cell._element.append(new_para)
                rows_added += 1
                empty_cells += empty_in_template
                
        return {
            "rows_added": rows_added,
            "total_rows": len(table.rows),
            "empty_cells": empty_cells
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

        # First pass: collect paragraphs to identify placeholder patterns
        paragraphs_info = []
        for para in self.doc.paragraphs:
            text = para.text
            text_strip = text.strip()
            # Check if paragraph has placeholders
            has_placeholders = self._has_placeholder(para, text)
            # Only merge paragraphs that become completely empty after stripping placeholders.
            # Punctuation-led list items such as "- ....." must stay on their own lines.
            is_placeholder_only = self._is_placeholder_continuation_paragraph(para, text)
            paragraphs_info.append({
                'para': para,
                'text': text,
                'text_strip': text_strip,
                'has_placeholders': has_placeholders,
                'is_placeholder_only': is_placeholder_only
            })

        # Process paragraphs with placeholder merging logic
        i = 0
        while i < len(paragraphs_info):
            info = paragraphs_info[i]

            # Check for section headers (for context)
            if info['text_strip'] and (info['text_strip'][0].isdigit() or info['text_strip'].isupper()) and len(info['text_strip']) < 50:
                # Extremely simple text normalization for section labels
                simple_text = info['text_strip'].lower().replace(' ', '_')[:20]
                self.last_section_label = simple_text if simple_text else "field"

            # If this paragraph has placeholders, check if next paragraphs should be merged
            if info['has_placeholders']:
                # Look ahead to find consecutive paragraphs with placeholders that should be merged
                # Case 1: Paragraph with text + placeholders followed by placeholder-only paragraphs
                # Case 2: Multiple placeholder-only paragraphs in a row
                streak_start = i
                streak_end = i

                # Determine if we should merge with next paragraphs
                should_merge = False

                # Check next paragraphs
                while streak_end + 1 < len(paragraphs_info):
                    next_info = paragraphs_info[streak_end + 1]

                    # Merge if next paragraph is placeholder-only
                    if next_info['is_placeholder_only']:
                        should_merge = True
                        streak_end += 1
                    else:
                        break

                # If we have a streak that should be merged (> 1 paragraph)
                if should_merge and streak_end > streak_start:
                    # Merge placeholder-only paragraphs into the first paragraph
                    # by copying their runs, then process the merged paragraph
                    first_para = paragraphs_info[streak_start]['para']
                    first_para_element = first_para._p

                    # Copy runs from all subsequent paragraphs in the streak
                    # (skip the first paragraph as it's already in first_para_element)
                    for j in range(streak_start + 1, streak_end + 1):
                        current_para = paragraphs_info[j]['para']
                        current_para_element = current_para._p

                        # Copy all runs from current paragraph
                        for run in current_para.runs:
                            run_element = run._element
                            # Deep copy the run element to preserve all formatting
                            run_copy = copy.deepcopy(run_element)
                            first_para_element.append(run_copy)

                    # Process the merged first paragraph (now contains all runs)
                    self._process_paragraph(first_para)

                    # Delete the merged paragraphs (they've been incorporated into the first one)
                    for j in range(streak_end, streak_start, -1):  # Reverse order to avoid index shifting
                        para_to_delete = paragraphs_info[j]['para']
                        para_element = para_to_delete._element
                        para_element.getparent().remove(para_element)

                    # Skip the rest of the streak
                    i = streak_end + 1
                    continue

            # Process normal paragraph
            self._process_paragraph(info['para'])

            # Update context
            cleaned = self._strip_placeholder_markers(info['para'], info['text_strip']).strip()
            if cleaned and any(c.isalpha() for c in cleaned):
                self.last_meaningful_text = cleaned

            i += 1

        # First pass: Process existing placeholders in all tables (Always required)
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text_strip = para.text.strip()
                        self._process_paragraph(para)
                        cleaned = self._strip_placeholder_markers(para, text_strip).strip()
                        if cleaned and any(c.isalpha() for c in cleaned):
                            self.last_meaningful_text = cleaned

        # Second pass: Auto-fill empty cells if requested
        if auto_fill_tables:
            if self.gemini_client:
                # Batch ALL tables for Gemini - 1 API call ONLY
                print("=== Batching all tables for single Gemini call ===")
                self._process_all_tables_with_gemini_batch()
            else:
                # Rule-based auto-fill (no Gemini fallback)
                for table in self.doc.tables:
                    self._process_table_rule_based(table)

        self.doc.save(output_path)

        return self.all_field_names

    def _process_all_tables_with_gemini_batch(self):
        """Batch ALL tables for single Gemini call instead of calling per table

        Giảm từ N requests → 1 request duy nhất cho tất cả tables
        """
        if not self.gemini_client:
            return

        # Collect all empty cells from ALL tables
        all_tables_data = []
        table_index = 0

        for table_idx, table in enumerate(self.doc.tables):
            table_data = []
            for row_idx, row in enumerate(table.rows):
                row_data = []
                for col_idx, cell in enumerate(row.cells):
                    text = cell.text.strip()
                    is_empty = not text or text.isspace()

                    row_data.append({
                        "text": text,
                        "is_empty": is_empty,
                        "row": row_idx,
                        "col": col_idx,
                        "table_idx": table_idx  # Add table index to track which table
                    })

                table_data.append(row_data)

            # Only add tables that have empty cells
            has_empty = any(cell["is_empty"] for row in table_data for cell in row)
            if has_empty:
                all_tables_data.append({
                    "table_idx": table_idx,
                    "table": table,
                    "table_data": table_data
                })

        if not all_tables_data:
            return

        # Prepare batch data for Gemini
        # Format: Tất cả tables data trong 1 request
        tables_for_gemini = []
        for table_info in all_tables_data:
            tables_for_gemini.append(table_info["table_data"])

        # Get document context (from first few paragraphs)
        context_parts = []
        for para in self.doc.paragraphs[:5]:
            if para.text.strip():
                context_parts.append(para.text.strip())
        document_context = " | ".join(context_parts)

        # Single Gemini call for ALL tables
        print(f"=== Calling Gemini ONCE for {len(all_tables_data)} tables ===")

        # Process each table and collect results
        for table_info in all_tables_data:
            table_idx = table_info["table_idx"]
            table_obj = table_info["table"]
            table_data = table_info["table_data"]

            # Call Gemini for THIS table (still individual calls for now)
            # TODO: Future enhancement - batch multiple tables in one prompt
            result = self.gemini_client.analyze_table_for_placeholders(
                table_data=table_data,
                document_context=document_context
            )

            # Apply suggestions for THIS table
            for suggestion in result.get("suggestions", []):
                row = suggestion.get("row")
                col = suggestion.get("col")
                field_name = suggestion.get("field_name")

                if row is not None and col is not None and field_name:
                    if 0 <= row < len(table_obj.rows):
                        from table_utils import find_row_cell_at_column
                        row_obj = table_obj.rows[row]
                        cell, _, _ = find_row_cell_at_column(row_obj, col)

                        if cell is not None:
                            # Found the target cell
                            if cell.text.strip() == "" or cell.text.isspace():
                                # Insert placeholder
                                self._insert_field_in_cell(cell, field_name)
