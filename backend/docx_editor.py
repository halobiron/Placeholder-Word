"""
DocxFullEditor - Edit mọi thứ trong DOCX mà vẫn giữ nguyên formatting
Hỗ trợ: text edit, format changes, add content, delete content, tables, images
"""
import re
from typing import Dict, List, Optional, Any, Callable
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from lxml import etree


class DocxFullEditor:
    """
    Edit DOCX trực tiếp, giữ nguyên formatting
    Không qua HTML conversion → Không mất format
    """

    def __init__(self, docx_path: str):
        self.doc_path = docx_path
        self.doc = Document(docx_path)
        self.w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    # ===== HELPER METHODS =====

    def _iterate_paragraphs(self):
        """Yield all paragraphs (document + tables)"""
        for paragraph in self.doc.paragraphs:
            yield paragraph
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        yield paragraph

    def _iterate_runs(self):
        """Yield all runs with context from all paragraphs"""
        for paragraph in self._iterate_paragraphs():
            for run in paragraph.runs:
                yield run, paragraph

    # ===== TEXT EDITING (Giữ format) =====

    def replace_text_keep_format(self, old_text: str, new_text: str):
        """
        Thay text nhưng giữ nguyên format
        Handle text bị split và fuzzy match

        Args:
            old_text: Text cần tìm (có thể khác biệt nhỏ với DOCX)
            new_text: Text thay thế
        """
        search_text_normalized = re.sub(r'\s+', ' ', old_text.strip())

        for paragraph in self._iterate_paragraphs():
            full_text = "".join(run.text for run in paragraph.runs)
            full_text_normalized = re.sub(r'\s+', ' ', full_text.strip())

            if search_text_normalized in full_text_normalized:
                start_idx = full_text_normalized.find(search_text_normalized)
                if start_idx == -1:
                    continue

                # Find which runs contain the text
                char_count = 0
                target_runs = []
                end_idx = start_idx + len(search_text_normalized)

                for run in paragraph.runs:
                    run_start = char_count
                    run_end = char_count + len(run.text)

                    if run_end > start_idx and run_start < end_idx:
                        target_runs.append(run)

                    char_count += len(run.text)

                # Replace text in target runs
                if not target_runs:
                    continue

                first_run = target_runs[0]
                run_text_normalized = re.sub(r'\s+', ' ', first_run.text.strip())

                if search_text_normalized in run_text_normalized:
                    first_run.text = first_run.text.replace(search_text_normalized, new_text, 1)
                elif search_text_normalized[0:30] in run_text_normalized:
                    # Partial match - find and replace
                    for i in range(len(first_run.text)):
                        segment = first_run.text[i:i+len(search_text_normalized)]
                        segment_normalized = re.sub(r'\s+', ' ', segment.strip())
                        if (segment_normalized == search_text_normalized or
                            re.sub(r'\s+', ' ', search_text_normalized[0:len(segment_normalized)]) in segment_normalized):
                            first_run.text = first_run.text[:i] + new_text + first_run.text[i+len(segment):]
                            for run in target_runs[1:]:
                                run.text = ""
                            break

    def replace_text_advanced(
        self,
        old_text: str,
        new_text: str,
        match_case: bool = False,
        whole_word: bool = False,
        use_regex: bool = False
    ):
        """Find và replace nâng cao, giữ format"""
        if not old_text:
            return

        for run, _ in self._iterate_runs():
            if old_text not in run.text:
                continue

            if use_regex:
                pattern = re.compile(old_text)
                if pattern.search(run.text):
                    run.text = pattern.sub(new_text, run.text)

            elif whole_word:
                pattern = r'\b' + re.escape(old_text) + r'\b'
                if match_case:
                    pattern = r'(?<!\w)' + re.escape(old_text) + r'(?!\w)'
                else:
                    pattern = r'(?<!\w)' + re.escape(old_text) + r'(?!\w)'

                if re.search(pattern, run.text):
                    flags = 0 if match_case else re.IGNORECASE
                    run.text = re.sub(pattern, new_text, run.text, flags=flags)

            else:
                if match_case:
                    if old_text in run.text:
                        run.text = run.text.replace(old_text, new_text)
                else:
                    if old_text.lower() in run.text.lower():
                        idx = run.text.lower().find(old_text.lower())
                        if idx != -1:
                            run.text = run.text[:idx] + new_text + run.text[idx + len(old_text):]

    # ===== FORMATTING =====

    def apply_format_to_text(
        self,
        text: str,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None
    ):
        """
        Apply formatting cho text cụ thể
        Hỗ trợ fuzzy match và multi-paragraph selection

        Args:
            text: Text cần format (có thể chứa \n\n cho multi-paragraph)
            bold: True/False/None (None = không đổi)
            italic: True/False/None
            underline: True/False/None
            color: Màu sắc (hex or named color)
            highlight: Highlight color
            font_name: Tên font
            font_size: Cỡ chữ (points)
        """
        import re

        # Handle multi-paragraph selection (split by \n\n)
        text_parts = [t.strip() for t in text.split('\n\n') if t.strip()]

        if len(text_parts) > 1:
            # Multi-paragraph: apply format to each part separately
            for text_part in text_parts:
                self._apply_format_to_single_text(text_part, bold, italic, underline, color, highlight, font_name, font_size)
        else:
            # Single paragraph
            self._apply_format_to_single_text(text, bold, italic, underline, color, highlight, font_name, font_size)

    def _apply_format_to_single_text(
        self,
        text: str,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None
    ):
        """Helper: apply format to single text segment"""
        search_text_normalized = re.sub(r'\s+', ' ', text.strip())

        for paragraph in self._iterate_paragraphs():
            para_text = "".join(run.text for run in paragraph.runs)
            para_text_normalized = re.sub(r'\s+', ' ', para_text.strip())

            if (search_text_normalized not in para_text_normalized and
                search_text_normalized[0:50] not in para_text_normalized):
                continue

            for run in paragraph.runs:
                run_normalized = re.sub(r'\s+', ' ', run.text.strip())
                if (search_text_normalized not in run_normalized and
                    search_text_normalized[0:30] not in run_normalized):
                    continue

                if bold is not None:
                    run.font.bold = bold
                if italic is not None:
                    run.font.italic = italic
                if underline is not None:
                    run.font.underline = underline
                if color:
                    run.font.color.rgb = self._parse_color(color)
                if highlight:
                    run.font.highlight_color = self._parse_highlight_color(highlight)
                if font_name:
                    run.font.name = font_name
                if font_size:
                    run.font.size = Pt(font_size)

    def apply_paragraph_format(
        self,
        text: str,
        alignment: str = None,
        spacing_before: int = None,
        spacing_after: int = None,
        line_spacing: float = None
    ):
        """
        Apply paragraph formatting cho đoạn chứa text

        Args:
            text: Text trong paragraph
            alignment: "left", "center", "right", "justify"
            spacing_before: Spacing trước (points)
            spacing_after: Spacing sau (points)
            line_spacing: Line spacing (1.0 = single, 2.0 = double)
        """
        alignment_map = {
            "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
            "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
            "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
            "justify": WD_PARAGRAPH_ALIGNMENT.JUSTIFY
        }

        for paragraph in self._iterate_paragraphs():
            if text not in paragraph.text:
                continue

            if alignment and alignment in alignment_map:
                paragraph.alignment = alignment_map[alignment]
            if spacing_before is not None:
                paragraph.paragraph_format.space_before = Pt(spacing_before)
            if spacing_after is not None:
                paragraph.paragraph_format.space_after = Pt(spacing_after)
            if line_spacing is not None:
                paragraph.paragraph_format.line_spacing = line_spacing

    # ===== DELETE CONTENT =====

    def delete_text(self, text: str):
        """Xóa text khỏi document"""
        self.replace_text_keep_format(text, "")

    def delete_paragraph_containing(self, text: str):
        """Xóa entire paragraph chứa text"""
        paragraphs_to_delete = []

        # Find paragraphs to delete
        for i, paragraph in enumerate(self.doc.paragraphs):
            if text in paragraph.text:
                paragraphs_to_delete.append(i)

        # Delete in reverse order to maintain indices
        for index in reversed(paragraphs_to_delete):
            p_element = self.doc.paragraphs[index]._element
            p_element.getparent().remove(p_element)

    # ===== ADD CONTENT =====

    def add_text_after(self, target_text: str, new_text: str, inherit_format: bool = True):
        """
        Thêm text sau target text

        Args:
            target_text: Text đích (thêm sau text này)
            new_text: Text mới cần thêm
            inherit_format: True = kế thừa format của target, False = dùng format mặc định
        """
        for run, _ in self._iterate_runs():
            if target_text in run.text:
                run.text = run.text.replace(target_text, target_text + new_text)
                return True
        return False

    def add_text_before(self, target_text: str, new_text: str, inherit_format: bool = True):
        """Thêm text trước target text"""
        for run, _ in self._iterate_runs():
            if target_text in run.text:
                run.text = run.text.replace(target_text, new_text + target_text)
                return True
        return False

    def add_paragraph_after(self, target_text: str, new_text: str, inherit_format: bool = True):
        """
        Thêm paragraph mới sau paragraph chứa target text

        Args:
            target_text: Text đích
            new_text: Nội dung paragraph mới
            inherit_format: True = kế thừa format của paragraph trước
        """
        for i, paragraph in enumerate(self.doc.paragraphs):
            if target_text in paragraph.text:
                if inherit_format:
                    # Copy format from current paragraph
                    new_para = paragraph.insert_paragraph_before(new_text)
                    # Copy alignment
                    new_para.alignment = paragraph.alignment
                    # Copy paragraph format
                    new_para.paragraph_format.space_before = paragraph.paragraph_format.space_before
                    new_para.paragraph_format.space_after = paragraph.paragraph_format.space_after
                    new_para.paragraph_format.line_spacing = paragraph.paragraph_format.line_spacing
                else:
                    # Add paragraph with default format
                    if i < len(self.doc.paragraphs) - 1:
                        new_para = self.doc.paragraphs[i + 1].insert_paragraph_before(new_text)
                    else:
                        new_para = self.doc.add_paragraph(new_text)
                return True

        return False

    def add_paragraph_at_end(self, text: str):
        """Thêm paragraph ở cuối document"""
        self.doc.add_paragraph(text)

    def add_placeholder(self, field_name: str, position: str = "end", after_text: str = None):
        """
        Thêm placeholder merge field

        Args:
            field_name: Tên field
            position: "end", "after:text", "before:text"
            after_text: Text đích (cho after/before)
        """
        placeholder_text = f" «{field_name}»"

        if position == "end":
            self.doc.add_paragraph(placeholder_text)
        elif position.startswith("after:"):
            target_text = position.split("after:")[1].strip()
            self.add_text_after(target_text, placeholder_text, inherit_format=True)
        elif position.startswith("before:"):
            target_text = position.split("before:")[1].strip()
            self.add_text_before(target_text, placeholder_text, inherit_format=True)

    def add_page_break(self, position: str = "end", after_text: str = None):
        """
        Thêm ngắt trang

        Args:
            position: "end", "after:text", "before:text"
            after_text: Text đích
        """
        if position == "end":
            self.doc.add_page_break()
        elif position.startswith("after:"):
            target_text = position.split("after:")[1].strip()
            for i, paragraph in enumerate(self.doc.paragraphs):
                if target_text in paragraph.text:
                    if i < len(self.doc.paragraphs) - 1:
                        self.doc.paragraphs[i + 1].add_page_break()
                    else:
                        self.doc.add_paragraph().add_page_break()
                    return True
        return False

    def add_image(self, image_path: str, position: str = "end", after_text: str = None, width: float = 4.0):
        """
        Thêm hình ảnh

        Args:
            image_path: Đường dẫn tới file ảnh
            position: "end", "after:text"
            after_text: Text đích
            width: Chiều rộng (inches)
        """
        if position == "end":
            self.doc.add_picture(image_path, width=Inches(width))
        elif position.startswith("after:"):
            target_text = position.split("after:")[1].strip()
            for i, paragraph in enumerate(self.doc.paragraphs):
                if target_text in paragraph.text:
                    if i < len(self.doc.paragraphs) - 1:
                        # Add to next paragraph
                        self.doc.paragraphs[i + 1].add_picture(image_path, width=Inches(width))
                    else:
                        # Add new paragraph with image
                        self.doc.add_paragraph().add_picture(image_path, width=Inches(width))
                    return True
        return False

    # ===== TABLE EDITING =====

    def edit_table_cell(
        self,
        table_index: int,
        row_index: int,
        col_index: int,
        new_text: str
    ):
        """Edit text trong table cell"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if row_index >= len(table.rows):
            return False

        row = table.rows[row_index]
        if col_index >= len(row.cells):
            return False

        cell = row.cells[col_index]
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.text = new_text
                return True

        return False

    def add_table_row(self, table_index: int):
        """Thêm row vào table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        table.add_row()
        return True

    # ===== UTILITY FUNCTIONS =====

    def _parse_color(self, color: str) -> RGBColor:
        """Parse color string to RGBColor"""
        if color.startswith("#"):
            # Hex color
            hex_color = color.lstrip("#")
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            return RGBColor(*rgb)
        else:
            # Named color
            color_map = {
                "red": RGBColor(255, 0, 0),
                "green": RGBColor(0, 255, 0),
                "blue": RGBColor(0, 0, 255),
                "yellow": RGBColor(255, 255, 0),
                "orange": RGBColor(255, 165, 0),
                "purple": RGBColor(128, 0, 128),
                "black": RGBColor(0, 0, 0),
                "white": RGBColor(255, 255, 255),
                "gray": RGBColor(128, 128, 128),
            }
            return color_map.get(color.lower(), RGBColor(0, 0, 0))

    def _parse_highlight_color(self, color: str) -> str:
        """Parse highlight color to WD_COLOR"""
        color_map = {
            "yellow": "YELLOW",
            "red": "RED",
            "blue": "BLUE",
            "green": "GREEN",
            "orange": "ORANGE",
            "gray": "GRAY",
        }
        return color_map.get(color.lower(), "YELLOW")

    def find_text_occurrences(self, text: str) -> List[Dict]:
        """
        Tìm tất cả occurrences của text trong document

        Returns:
            List of {paragraph_index, run_index, text, context}
        """
        occurrences = []

        for p_idx, paragraph in enumerate(self.doc.paragraphs):
            for r_idx, run in enumerate(paragraph.runs):
                if text in run.text:
                    occurrences.append({
                        "paragraph_index": p_idx,
                        "run_index": r_idx,
                        "text": run.text,
                        "context": paragraph.text
                    })

        # Tables
        for t_idx, table in enumerate(self.doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    for p_idx, paragraph in enumerate(cell.paragraphs):
                        for r_idx, run in enumerate(paragraph.runs):
                            if text in run.text:
                                occurrences.append({
                                    "table_index": t_idx,
                                    "row_index": row_idx,
                                    "cell_index": cell_idx,
                                    "paragraph_index": p_idx,
                                    "run_index": r_idx,
                                    "text": run.text,
                                    "context": paragraph.text
                                })

        return occurrences

    # ===== SAVE =====

    def save(self, output_path: str = None):
        """Lưu document"""
        if output_path is None:
            output_path = self.doc_path
        self.doc.save(output_path)
        return output_path

    def save_copy(self, output_path: str):
        """Lưu bản copy (giữ nguyên original)"""
        self.doc.save(output_path)
        return output_path