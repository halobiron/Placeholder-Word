"""
Merge Executor - Execute mail merge with data
Fills mail merge templates with provided data while preserving formatting
"""
import uuid
import re
from pathlib import Path
from typing import Dict
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import copy

RESULT_DIR = Path(__file__).parent / "uploads" / "results"

class MergeExecutor:
    """Execute mail merge operations with formatting preservation"""

    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def _iter_merge_fields(self, doc: Document):
        for fld in doc.element.iter(f"{self.W_NS}fldSimple"):
            instr = fld.get(f"{self.W_NS}instr", "")
            if "MERGEFIELD" not in instr:
                continue
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if match:
                yield fld, instr, match.group(1)

    def get_template_fields(self, template_path: str) -> list[str]:
        """Get ordered field names from template."""
        doc = Document(template_path)
        return [field_name for _, _, field_name in self._iter_merge_fields(doc)]

    def _extract_full_template_text(self, doc: Document) -> str:
        """Extract full text content from document for context understanding."""
        paragraphs_text = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs_text.append(text)

        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if text:
                        row_text.append(text)
                if row_text:
                    paragraphs_text.append(" | ".join(row_text))

        return "\n\n".join(paragraphs_text)

    def get_template_fields_and_text(self, template_path: str) -> tuple[list[str], str]:
        """Get field names AND full template text in ONE pass

        Tối ưu: Đọc template 1 lần duy nhất, trả về:
        - Danh sách tên field (cho Gemini)
        - Full text (cho Gemini tự tìm vị trí)

        Args:
            template_path: Path to template file

        Returns:
            Tuple of (field_names, full_template_text)
        """
        doc = Document(template_path)
        field_names = [field_name for _, _, field_name in self._iter_merge_fields(doc)]
        full_text = self._extract_full_template_text(doc)

        return field_names, full_text

    def execute_merge(
        self,
        template_path: str,
        data: Dict[str, str],
        locked_fields: set[str] | None = None
    ) -> str:
        """Execute mail merge with provided data while preserving formatting"""
        doc = Document(template_path)

        # Execute merge with formatting preservation
        self._merge_with_formatting(doc, data, locked_fields or set())

        # Generate result path
        result_id = str(uuid.uuid4())
        result_path = RESULT_DIR / f"{result_id}.docx"

        # Save merged document
        doc.save(str(result_path))

        return str(result_path), result_id

    def _merge_with_formatting(
        self,
        doc: Document,
        data: Dict[str, str],
        locked_fields: set[str]
    ):
        """Replace mail merge fields with values using the field's own formatting.

        Placeholder marker cleanup belongs to the converter stage, which already
        rewrites paragraphs/tables into clean ``fldSimple`` nodes. Merge only
        resolves values and swaps each field with a plain run that preserves the
        formatting stored inside that field.
        """
        flds = [fld for fld, _, _ in self._iter_merge_fields(doc)]

        for fld in flds:
            instr = fld.get(f"{self.W_NS}instr", "")
            field_name = re.search(r'MERGEFIELD\s+(\S+)', instr).group(1)

            z_match = re.search(r'\\z\s*"([^"]*)"', instr)
            original_text = z_match.group(1) if z_match else ""

            # Locked fields behave like empty values so they fall back to the
            # original placeholder text captured in the template.
            if field_name in locked_fields:
                replacement = original_text
            else:
                replacement = data.get(field_name, "")
                if field_name.startswith("ck_"):
                    is_checked = str(replacement).lower().strip() in ('x', '1', 'true', 'checked', 'v')
                    replacement = "☑" if is_checked else "☐"

            if replacement is None or (str(replacement).strip() == "" and not field_name.startswith("ck_")):
                replacement = original_text
            else:
                replacement = str(replacement)
                if re.search(r'\\\*\s*Upper', instr, re.IGNORECASE):
                    replacement = replacement.upper()
                elif re.search(r'\\\*\s*Caps', instr, re.IGNORECASE):
                    replacement = replacement.title()

            new_run = OxmlElement('w:r')

            rPr = None
            nested_run = fld.find(f"{self.W_NS}r")
            if nested_run is not None:
                rPr = nested_run.find(f"{self.W_NS}rPr")

            if rPr is not None:
                new_run.append(copy.deepcopy(rPr))

            t = OxmlElement('w:t')
            replacement_str = str(replacement)

            # Auto-pad spaces if adjacent to text to prevent missing spaces in merged values
            if replacement_str:
                parent = fld.getparent()
                if parent is not None:
                    try:
                        idx = parent.index(fld)
                        # Check previous sibling for missing space
                        if not replacement_str[0].isspace():
                            last_char = ""
                            for i in range(idx - 1, -1, -1):
                                prev_el = parent[i]
                                prev_texts = prev_el.findall(f".//{self.W_NS}t")
                                text_contents = [t.text for t in prev_texts if t.text]
                                if text_contents:
                                    last_char = text_contents[-1][-1]
                                    break
                            if last_char and (last_char.isalpha() or last_char in '.,:;>)]}'):
                                replacement_str = " " + replacement_str
                        
                        # Check next sibling for missing space
                        if not replacement_str[-1].isspace():
                            first_char = ""
                            for i in range(idx + 1, len(parent)):
                                next_el = parent[i]
                                next_texts = next_el.findall(f".//{self.W_NS}t")
                                text_contents = [t.text for t in next_texts if t.text]
                                if text_contents:
                                    first_char = text_contents[0][0]
                                    break
                            if first_char and (first_char.isalpha() or first_char in '<([{'):
                                replacement_str = replacement_str + " "
                    except ValueError:
                        pass

            if replacement_str != replacement_str.strip():
                t.set(qn('xml:space'), 'preserve')

            t.text = replacement_str
            new_run.append(t)

            fld.getparent().replace(fld, new_run)
