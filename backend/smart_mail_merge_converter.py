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


class SmartMailMergeConverter:
    """Convert Vietnamese .docx forms to Mail Merge templates with intelligent field naming"""

    def __init__(self, doc_path):
        """Initialize converter with document

        Args:
            doc_path: Path to input .docx file
        """
        self.doc = Document(doc_path)
        self.used_labels = {}
        self.last_section_label = "field"
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

        # Lấy tối đa 4 từ quan trọng
        slug = "_".join(words[:4])
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
            return base_label
        else:
            self.used_labels[base_label] += 1
            return f"{base_label}_{self.used_labels[base_label]}"

    def _generate_label(self, pre_text, para_context):
        """Tạo field name và format switch dựa trên text ngay trước placeholder"""
        parts = [p.strip() for p in re.split(r'[:\-–—\._…□■\n]', pre_text) if p.strip()]
        recent = parts[-1] if parts else ""
        label = self._slugify(recent) or self._slugify(pre_text) or self._slugify(para_context) or "field"
        unique_label = self._get_unique_label(label)
        sw = "\\* Upper" if recent.isupper() else "\\* Caps" if recent.istitle() else "\\* MERGEFORMAT"
        return unique_label, sw

    def _process_paragraph(self, paragraph):
        """Xử lý paragraph: inject Mail Merge field với định dạng chính xác"""
        p_element, pattern = paragraph._p, re.compile(r'([._]{3,}|…+[._…]*)')
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
                if ' ' in (content[0], content[-1]): t.set(qn('xml:space'), 'preserve')
                t.text, _ = content, run.append(t)
                p_element.append(run)
            else:
                ctx = paragraph.text if len(paragraph.text) > 10 else self.last_section_label
                label, sw = self._generate_label(full_text[:offset], ctx)
                fld = OxmlElement('w:fldSimple')
                fld.set(qn('w:instr'), f' MERGEFIELD {label} {sw} \\z "{content}" ')
                run = OxmlElement('w:r')
                if original_rPr is not None: run.append(copy.deepcopy(original_rPr))
                t = OxmlElement('w:t')
                t.text, _ = f"«{label}»", run.append(t)
                fld.append(run)
                p_element.append(fld)

    def convert(self, output_path):
        """Duyệt toàn bộ tài liệu để thực thi chuyển đổi

        Args:
            output_path: Path to save converted document

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

        # Xử lý Table nếu có
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        self._process_paragraph(para)

        self.doc.save(output_path)
        print(f"Chuyển đổi hoàn tất! File đã lưu tại: {output_path}")

        return list(self.used_labels.keys())
