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

    def _generate_label(self, pre_text, paragraph_context):
        """Logic đặt tên Field thông minh dựa trên ngữ cảnh

        Priority order:
        1. Time Context (ngày, tháng, năm)
        2. Inline Context (label before colon/dash)
        3. Section-Based Context (heading name)

        Args:
            pre_text: Text immediately before placeholder
            paragraph_context: Full paragraph text for fallback

        Returns:
            Field name in snake_case
        """
        # Ưu tiên 2: Xử lý Thời gian
        time_match = re.search(r'(?i)(ngày|tháng|năm)\s*(20)?\s*$', pre_text)
        if time_match:
            return time_match.group(1).lower()

        # Ưu tiên 1: Inline Context (Trước dấu hai chấm hoặc vài từ gần nhất)
        inline_label = self._slugify(pre_text)
        if inline_label:
            return inline_label

        # Ưu tiên 3: Kế thừa Section-Based
        return self._slugify(paragraph_context) or "field"

    def _process_paragraph(self, paragraph):
        """Xử lý một paragraph: tìm placeholder và inject Mail Merge field

        Args:
            paragraph: docx paragraph object
        """
        p_element = paragraph._p
        full_text = ""
        offset_map = []  # Lưu rPr (định dạng) cho từng ký tự

        # Bước 1: Lập bản đồ Offset và thu thập Text
        for run in paragraph.runs:
            run_text = run.text
            rPr = run.element.find(f"{self.w_ns}rPr")
            for char in run_text:
                full_text += char
                offset_map.append(rPr)

        if not full_text:
            return

        # Regex tìm cụm dấu chấm (Greedy)
        placeholder_pattern = re.compile(r'([._…]{2,}(?:\s+[._…]{2,})*)')

        segments = []
        last_idx = 0

        # Bước 2: Phân mảnh Paragraph thành Text và Field
        for match in placeholder_pattern.finditer(full_text):
            start, end = match.start(), match.end()

            # Đoạn text tĩnh trước placeholder
            if start > last_idx:
                segments.append(('text', full_text[last_idx:start], last_idx))

            # Đoạn placeholder cần chuyển thành Mail Merge
            segments.append(('field', full_text[start:end], start))
            last_idx = end

        if last_idx < len(full_text):
            segments.append(('text', full_text[last_idx:], last_idx))

        # Nếu không có placeholder nào, bỏ qua
        if not any(s[0] == 'field' for s in segments):
            return

        # Bước 3: Xóa sạch nội dung cũ của Paragraph XML
        for r in p_element.findall(f"{self.w_ns}r"):
            p_element.remove(r)

        # Bước 4: Xây dựng lại XML Paragraph với "Surgical Injection"
        for kind, content, offset in segments:
            # Lấy rPr tại vị trí bắt đầu của segment để kế thừa format
            original_rPr = offset_map[offset] if offset < len(offset_map) else None

            if kind == 'text':
                new_run = OxmlElement('w:r')
                if original_rPr is not None:
                    # DEEP CLONE để preserve toàn bộ format properties
                    cloned_rPr = copy.deepcopy(original_rPr)
                    new_run.append(cloned_rPr)

                t = OxmlElement('w:t')
                if content.startswith(' ') or content.endswith(' '):
                    t.set(qn('xml:space'), 'preserve')
                t.text = content
                new_run.append(t)
                p_element.append(new_run)

            else:  # Mail Merge Field
                # Lấy ngữ cảnh từ đoạn text ngay trước đó
                pre_text = full_text[:offset]
                raw_label = self._generate_label(
                    pre_text,
                    paragraph.text if len(paragraph.text) > 10 else self.last_section_label
                )
                final_label = self._get_unique_label(raw_label)

                # Tạo cấu trúc w:fldSimple
                fld_simple = OxmlElement('w:fldSimple')
                fld_simple.set(qn('w:instr'), f' MERGEFIELD {final_label} \\* MERGEFORMAT ')

                # Bọc trong fldSimple là một run để hiển thị placeholder text
                nested_run = OxmlElement('w:r')
                if original_rPr is not None:
                    # DEEP CLONE để preserve toàn bộ format properties
                    # Dùng deepcopy để copy hoàn toàn element với tất cả properties
                    cloned_rPr = copy.deepcopy(original_rPr)
                    nested_run.append(cloned_rPr)

                t = OxmlElement('w:t')
                t.text = f"«{final_label}»"
                nested_run.append(t)
                fld_simple.append(nested_run)

                p_element.append(fld_simple)

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
