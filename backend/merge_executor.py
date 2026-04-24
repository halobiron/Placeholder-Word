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
from lxml import etree
import copy

RESULT_DIR = Path(__file__).parent / "uploads" / "results"


class MergeExecutor:
    """Execute mail merge operations with formatting preservation"""

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
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        # Find all fldSimple elements in the entire document (including tables, headers, footers)
        flds = [f for f in doc.element.iter(f"{w_ns}fldSimple") if "MERGEFIELD" in f.get(f"{w_ns}instr", "")]

        for fld in flds:
            instr = fld.get(f"{w_ns}instr", "")
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if not match:
                continue

            field_name = match.group(1)

            z_match = re.search(r'\\z\s*"([^"]*)"', instr)
            original_text = z_match.group(1) if z_match else ""

            # Locked fields behave like empty values so they fall back to the
            # original placeholder text captured in the template.
            if field_name in locked_fields:
                replacement = original_text
            else:
                # Get replacement value, fallback to original_text if empty
                replacement = data.get(field_name, "")

            if replacement is None or str(replacement).strip() == "":
                replacement = original_text
            else:
                # Apply Word format switches
                if re.search(r'\\\*\s*Upper', instr, re.IGNORECASE):
                    replacement = str(replacement).upper()
                elif re.search(r'\\\*\s*Caps', instr, re.IGNORECASE):
                    replacement = str(replacement).title()

            # Create new run with replacement value
            new_run = OxmlElement('w:r')
            nested_run = fld.find(f"{w_ns}r")
            if nested_run is not None:
                rPr = nested_run.find(f"{w_ns}rPr")
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
        """Get list of fields in template using global element scan"""
        try:
            doc = Document(template_path)
            w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            fields = []
            
            for fld in doc.element.iter(f"{w_ns}fldSimple"):
                instr = fld.get(f"{w_ns}instr", "")
                if "MERGEFIELD" not in instr:
                    continue
                match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                if match:
                    field_name = match.group(1)
                    if field_name not in fields:
                        fields.append(field_name)
            
            return fields

        except Exception as e:
            raise ValueError(f"Failed to read template: {e}")
