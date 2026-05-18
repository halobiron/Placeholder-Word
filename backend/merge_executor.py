"""
Merge Executor - Execute mail merge with data
Fills mail merge templates with provided data while preserving formatting
"""
import uuid
import re
import zipfile
import xml.etree.ElementTree as ET
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
    FULL_CONTEXT_PAGE_THRESHOLD = 5

    def _iter_merge_fields(self, doc: Document):
        for fld in doc.element.iter(f"{self.W_NS}fldSimple"):
            instr = fld.instr if hasattr(fld, 'instr') else fld.get(f"{self.W_NS}instr", "")
            if "MERGEFIELD" not in instr:
                continue
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if match:
                yield fld, instr, match.group(1)

    def get_template_fields(self, template_path: str) -> list[str]:
        """Get ordered field names from template."""
        doc = Document(template_path)
        return [field_name for _, _, field_name in self._iter_merge_fields(doc)]

    def _extract_xml_text(self, element) -> str:
        """Extract visible text from a Word XML element, including merge-field display text."""
        text_parts = []
        for child in element.iter():
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name == "t" and child.text:
                text_parts.append(child.text)
            elif tag_name == "tab":
                text_parts.append("\t")
            elif tag_name == "br":
                text_parts.append("\n")
        return "".join(text_parts).strip()

    @staticmethod
    def _is_section_heading(text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        return bool(re.match(
            r"^(điều|dieu|chương|chuong|mục|muc|phần|phan)\s+[0-9IVXLCDM]+"
            r"|^[IVXLCDM]+\.\s+\S",
            normalized,
            flags=re.IGNORECASE,
        ))

    @staticmethod
    def _extract_heading_number(text: str) -> str | None:
        match = re.match(r"^(?:điều|dieu|chương|chuong|mục|muc|phần|phan)\s+([0-9IVXLCDM]+)", (text or "").strip(), re.IGNORECASE)
        return match.group(1).lower() if match else None

    @staticmethod
    def _extract_requested_heading_numbers(context: str) -> set[str]:
        return {
            match.group(1).lower()
            for match in re.finditer(r"(?:điều|dieu|chương|chuong|mục|muc|phần|phan)\s+([0-9IVXLCDM]+)", context or "", re.IGNORECASE)
        }

    def _extract_docx_page_count(self, template_path: str) -> int | None:
        try:
            with zipfile.ZipFile(template_path) as archive:
                app_xml = archive.read("docProps/app.xml")
            root = ET.fromstring(app_xml)
            for child in root:
                if child.tag.endswith("Pages") and child.text:
                    return int(child.text)
        except Exception:
            return None
        return None

    def _extract_template_blocks(self, doc: Document) -> list[dict]:
        blocks = []
        current_heading = ""
        current_heading_number = None

        for child in doc.element.body.iterchildren():
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name not in {"p", "tbl"}:
                continue

            text = self._extract_xml_text(child)
            if not text:
                continue

            if tag_name == "p" and self._is_section_heading(text):
                current_heading = text
                current_heading_number = self._extract_heading_number(text)

            blocks.append({
                "type": "table" if tag_name == "tbl" else "paragraph",
                "text": text,
                "heading": current_heading,
                "heading_number": current_heading_number,
            })

        return blocks

    def _extract_full_template_text(self, doc: Document) -> str:
        """Extract full text content from document for context understanding."""
        return "\n".join(block["text"] for block in self._extract_template_blocks(doc)).strip()

    def _build_compact_template_context(
        self,
        doc: Document,
        template_fields: list[str],
        user_context: str,
    ) -> str:
        blocks = self._extract_template_blocks(doc)
        requested_numbers = self._extract_requested_heading_numbers(user_context)
        field_set = set(template_fields)

        section_outline = []
        seen_headings = set()
        for block in blocks:
            heading = block.get("heading")
            if heading and heading not in seen_headings:
                seen_headings.add(heading)
                section_outline.append(heading)

        selected_indices = set()
        for i, block in enumerate(blocks):
            text = block["text"]
            has_field = any(f"«{field}»" in text for field in field_set)
            requested_section = block.get("heading_number") in requested_numbers

            if has_field:
                selected_indices.update(range(max(0, i - 1), min(len(blocks), i + 2)))
            if requested_section:
                selected_indices.add(i)

        lines = ["SECTION OUTLINE:"]
        lines.extend(f"- {heading}" for heading in section_outline[:80])
        lines.append("")
        lines.append("RELEVANT TEMPLATE BLOCKS:")

        for i in sorted(selected_indices):
            block = blocks[i]
            heading = block.get("heading") or "preamble"
            lines.append(f"[{i}] Section:[{heading}] {block['text']}")

        return "\n".join(lines).strip()

    def get_template_fields_and_text(self, template_path: str, user_context: str = "") -> tuple[list[str], str, int | None]:
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
        page_count = self._extract_docx_page_count(template_path)
        if page_count and page_count > self.FULL_CONTEXT_PAGE_THRESHOLD:
            full_text = self._build_compact_template_context(doc, field_names, user_context)
        else:
            full_text = self._extract_full_template_text(doc)

        return field_names, full_text, page_count

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
        """Replace mail merge fields with values while preserving formatting.

        Manually copies rPr from the field's run to preserve bold/italic/etc formatting.
        """
        for fld, instr, field_name in self._iter_merge_fields(doc):
            # Extract original placeholder text from \z switch
            z_match = re.search(r'\\z\s*"([^"]*)"', instr)
            original_text = z_match.group(1) if z_match else ""

            # Determine replacement value
            if field_name in locked_fields:
                replacement = original_text
            else:
                replacement = data.get(field_name, "")
                if field_name.startswith("ck_"):
                    is_checked = str(replacement).lower().strip() in ('x', '1', 'true', 'checked', 'v')
                    replacement = "☑" if is_checked else "☐"

            # Fallback to original text if empty
            if replacement is None or (str(replacement).strip() == "" and not field_name.startswith("ck_")):
                replacement = original_text
            else:
                replacement = str(replacement)
                # Apply formatting switches
                if re.search(r'\\\*\s*Upper', instr, re.IGNORECASE):
                    replacement = replacement.upper()
                elif re.search(r'\\\*\s*Caps', instr, re.IGNORECASE):
                    replacement = replacement.title()

            # Create new run with COPIED formatting
            new_run = OxmlElement('w:r')

            # Copy rPr from field's existing run to preserve formatting
            if fld.r_lst and fld.r_lst[0].rPr is not None:
                new_run.append(copy.deepcopy(fld.r_lst[0].rPr))

            # Add text element
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

            # Replace fldSimple with formatted run
            fld.getparent().replace(fld, new_run)
