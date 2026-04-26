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

    def get_template_field_metadata(self, template_path: str) -> list[dict]:
        """Get ordered field metadata from template for better extraction prompts.

        Returns minimal context without redundant paragraph_text since
        prev_text + field + next_text provides sufficient context for AI.
        """
        try:
            doc = Document(template_path)
        except Exception as e:
            raise ValueError(f"Failed to read template metadata: {e}")

        metadata = []
        for fld, instr, field_name in self._iter_merge_fields(doc):
            z_match = re.search(r'\\z\s*"([^"]*)"', instr)
            prev_text = ""
            next_text = ""

            if fld.getprevious() is not None:
                prev_text = "".join(
                    child.text
                    for child in fld.getprevious().iter()
                    if child.tag == f"{self.W_NS}t" and child.text
                ).strip()
            if fld.getnext() is not None:
                next_text = "".join(
                    child.text
                    for child in fld.getnext().iter()
                    if child.tag == f"{self.W_NS}t" and child.text
                ).strip()

            metadata.append(
                {
                    "field_name": field_name,
                    "original_placeholder": z_match.group(1) if z_match else "",
                    "context_before": prev_text,
                    "context_after": next_text,
                }
            )

        return metadata

    def execute_merge(
        self,
        template_path: str,
        data: Dict[str, str],
        locked_fields: set[str] | None = None
    ) -> str:
        """Execute mail merge with provided data while preserving formatting"""
        template_path = Path(template_path)
        if not template_path.exists():
            raise ValueError(f"Template not found: {template_path}")

        try:
            doc = Document(str(template_path))
        except Exception as e:
            raise ValueError(f"Failed to load template: {e}")

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

        Locked fields are treated as empty values so they resolve back to the
        original placeholder text stored in the field's ``\\z`` switch instead of
        leaving raw MERGEFIELD markup behind.
        """
        # Find all fldSimple elements in the entire document (including tables, headers, footers)
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
                # Get replacement value
                replacement = data.get(field_name, "")
                
                # Logic đặc biệt cho Checkbox: Nếu field bắt đầu bằng "ck_" và có giá trị "x" hoặc tương đương
                if field_name.startswith("ck_"):
                    # Coi x, X, 1, true là đã chọn
                    is_checked = str(replacement).lower().strip() in ('x', '1', 'true', 'checked', 'v')
                    replacement = "☑" if is_checked else "☐"

            if replacement is None or (str(replacement).strip() == "" and not field_name.startswith("ck_")):
                replacement = original_text
            else:
                prev_text = ""
                next_text = ""
                prev_node = fld.getprevious().find(f".//{self.W_NS}t") if fld.getprevious() is not None else None
                next_node = fld.getnext().find(f".//{self.W_NS}t") if fld.getnext() is not None else None

                if prev_node is not None and prev_node.text:
                    prev_text = re.sub(r'[._…]+$', '', prev_node.text)
                    if prev_text != prev_node.text:
                        prev_node.text = prev_text
                if next_node is not None and next_node.text:
                    next_text = re.sub(r'^[._…]+', '', next_node.text)
                    if next_text != next_node.text:
                        next_node.text = next_text

                replacement = str(replacement).strip()

                # Auto-add spacing for adjacent text (Vietnamese-aware)
                if prev_text and not prev_text[-1].isspace() and re.search(r'[A-Za-zÀ-ỹ]$', prev_text) and re.match(r'[\wÀ-ỹ]', replacement):
                    replacement = f" {replacement}"
                if next_text and not next_text[0].isspace() and re.match(r'[\wÀ-ỹ]', next_text) and re.search(r'[\wÀ-ỹ]$', replacement):
                    replacement = f"{replacement} "

                # Apply Word format switches
                if re.search(r'\\\*\s*Upper', instr, re.IGNORECASE):
                    replacement = str(replacement).upper()
                elif re.search(r'\\\*\s*Caps', instr, re.IGNORECASE):
                    replacement = str(replacement).title()

            # Create new run with replacement value
            new_run = OxmlElement('w:r')
            nested_run = fld.find(f"{self.W_NS}r")
            if nested_run is not None:
                rPr = nested_run.find(f"{self.W_NS}rPr")
                if rPr is not None:
                    new_run.append(copy.deepcopy(rPr))

            # Add text with space preservation
            t = OxmlElement('w:t')
            replacement_str = str(replacement)

            # Preserve leading/trailing whitespace by setting xml:space
            if replacement_str != replacement_str.strip():
                t.set(qn('xml:space'), 'preserve')

            t.text = replacement_str
            new_run.append(t)

            # Surgical replacement
            fld.getparent().replace(fld, new_run)

    def get_template_fields(self, template_path: str) -> list:
        """Get ordered field names from template."""
        return [item["field_name"] for item in self.get_template_field_metadata(template_path)]
