"""
Smart Mail Merge Converter - Full implementation per INSTRUCTIONS.md
Handles Vietnamese forms with XML surgical injection, offset mapping, and smart field naming
"""
import re
import unicodedata
import copy
from lxml import etree
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Treat placeholder-like dot runs broadly:
# - ASCII dot/underscore runs need at least 2 chars
# - Unicode ellipsis/dot-leader chars count as a placeholder by themselves
# - Mixed runs such as "...…‥⋯..." stay a single placeholder
# - Dots separated by spaces: ". . . ." or ". . . . . . ."
# - Pattern: (dot followed by optional spaces) repeated 2+ times, must contain at least 2 dots/underscores
PLACEHOLDER_PATTERN = re.compile(r'([._…‥⋯]*[…‥⋯][._…‥⋯]*|(?:[._]\s*){2,}|[□■]+)')


class SmartMailMergeConverter:
    """Convert Vietnamese .docx forms to Mail Merge templates with intelligent field naming"""

    def __init__(self, doc_path):
        """Initialize converter with document

        Args:
            doc_path: Path to input .docx file
        """
        self.doc = Document(doc_path)
        self.used_labels = {}   # base_label -> count of times used
        self.all_field_names = []  # ordered list of all generated field names (incl. _2, _3)
        self.last_section_label = "field"
        self.last_meaningful_text = "field"
        # Namespace chuẩn cho Word
        self.w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def _slugify(self, text):
        """Chuyển đổi tiếng Việt có dấu thành snake_case không dấu, tối đa 4 từ

        Args:
            text: Vietnamese text with accents

        Returns:
            Snake_case string or None
        """
        if not text or not text.strip():
            return None

        # Loại bỏ nhiễu: (nếu có), (ghi rõ...), các ký tự đặc biệt
        text = re.sub(r'\(.*?\)|[:\-–—\._…□■]', ' ', text)

        # Xử lý chữ đ/Đ đặc biệt trước khi normalize
        text = text.replace('đ', 'd').replace('Đ', 'D')

        # Bình thường hóa tiếng Việt
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        words = re.findall(r'\w+', text.lower())

        # Lấy tối đa 4 từ quan trọng ở cuối (sát với placeholder nhất)
        slug = "_".join(words[-4:]) if len(words) > 4 else "_".join(words)
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
        """Xử lý paragraph: inject Mail Merge field với định dạng chính xác"""
        p_element, pattern = paragraph._p, PLACEHOLDER_PATTERN
        if not pattern.search(paragraph.text): return

        # Map định dạng và thu thập text
        full_text, offset_map = "", []
        for run in paragraph.runs:
            rPr = run.element.find(f"{self.w_ns}rPr")
            for char in run.text:
                full_text += char
                offset_map.append(rPr)

        # Phân mảnh paragraph
        segments, last_idx = [], 0
        for match in pattern.finditer(full_text):
            s, e = match.start(), match.end()
            if s > last_idx: segments.append(('text', full_text[last_idx:s], last_idx))
            segments.append(('field', full_text[s:e], s))
            last_idx = e
        if last_idx < len(full_text): segments.append(('text', full_text[last_idx:], last_idx))

        # Rebuild XML
        for r in p_element.findall(f"{self.w_ns}r"): p_element.remove(r)

        for kind, content, offset in segments:
            original_rPr = offset_map[offset] if offset < len(offset_map) else None
            if kind == 'text':
                run = OxmlElement('w:r')
                if original_rPr is not None: run.append(copy.deepcopy(original_rPr))
                t = OxmlElement('w:t')
                # Preserve whitespace at start OR end (handles tabs, spaces, etc.)
                if content and (content[0].isspace() or (len(content) > 1 and content[-1].isspace())):
                    t.set(qn('xml:space'), 'preserve')
                t.text = content
                run.append(t)
                p_element.append(run)
            else:
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

    def _is_header_row(self, row):
        """Detect nếu row là header row

        Args:
            row: Table row object

        Returns:
            True nếu row là header row
        """
        # Check row đầu tiên của table
        if row._element.getparent().index(row._element) == 0:
            return True

        # Check nếu cell nào đó có bold text hoặc background color
        for cell in row.cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    if run.bold:
                        return True
                    # Check shading/background color
                    rPr = run.element.find(f"{self.w_ns}rPr")
                    if rPr is not None:
                        shd = rPr.find(f"{self.w_ns}shd")
                        if shd is not None and shd.get(f"{{{self.w_ns}}}fill") != "auto":
                            return True

        return False

    def _get_header_text(self, cell):
        """Extract text từ header cell, xử lý merged cells

        Args:
            cell: Table cell object

        Returns:
            Header text or None
        """
        text = cell.text.strip()
        if text:
            return text

        # For merged cells, check if this cell is part of a merge
        tc = cell._element
        tcPr = tc.find(f"{self.w_ns}tcPr")
        if tcPr is not None:
            # Check if this is a continuation of a merged cell (no content)
            vMerge = tcPr.find(f"{self.w_ns}vMerge")
            if vMerge is not None and vMerge.get(f"{{{self.w_ns}}}val") == "continue":
                return None  # This cell is part of a merge, find the parent
        return text if text else None

    def _find_header_for_column(self, table, row_idx, cell_idx):
        """Tìm header text cho một cột cụ thể

        Args:
            table: Table object
            row_idx: Row index hiện tại
            cell_idx: Cell index hiện tại

        Returns:
            Header text hoặc None
        """
        # Duyệt từ trên xuống để tìm header
        for r in range(row_idx):
            row = table.rows[r]
            if self._is_header_row(row):
                # Handle merged cells - check if this cell aligns with our column
                current_col = 0
                for c, cell in enumerate(row.cells):
                    # Check grid span for horizontal merge
                    tc = cell._element
                    tcPr = tc.find(f"{self.w_ns}tcPr")
                    grid_span = 1
                    if tcPr is not None:
                        gridSpan = tcPr.find(f"{self.w_ns}gridSpan")
                        if gridSpan is not None:
                            grid_span = int(gridSpan.get(f"{{{self.w_ns}}}val", 1))

                    if current_col <= cell_idx < current_col + grid_span:
                        header_text = self._get_header_text(cell)
                        if header_text:
                            return header_text

                    # Check if this cell continues from above (vertical merge)
                    if tcPr is not None:
                        vMerge = tcPr.find(f"{self.w_ns}vMerge")
                        if vMerge is not None and vMerge.get(f"{{{self.w_ns}}}val") == "continue":
                            # This cell is merged vertically, skip it
                            pass

                    current_col += grid_span

        return None

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
        """Xử lý bảng: detect header và auto-fill placeholder vào empty cells

        Args:
            table: Table object
        """
        if len(table.rows) <= 1:
            return  # Table chỉ có header, không có data rows

        # Find header row index
        header_row_idx = None
        for idx, row in enumerate(table.rows):
            if self._is_header_row(row):
                header_row_idx = idx
                break

        if header_row_idx is None:
            header_row_idx = 0  # Assume first row is header

        # Process data rows
        for row_idx in range(header_row_idx + 1, len(table.rows)):
            row = table.rows[row_idx]

            for cell_idx, cell in enumerate(row.cells):
                if self._is_cell_empty(cell):
                    # Find header text cho column này
                    header_text = self._find_header_for_column(table, row_idx, cell_idx)

                    if header_text:
                        # Slugify header text để làm field name
                        field_name = self._slugify(header_text)
                        if field_name:
                            self._insert_field_in_cell(cell, field_name)
                            print(f"  → Auto-fill: «{field_name}» (from header: '{header_text}')")

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
