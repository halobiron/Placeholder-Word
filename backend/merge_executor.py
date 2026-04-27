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
    TBL_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def _find_ancestor_table(self, element):
        """Find the ancestor w:tbl element if element is inside a table."""
        parent = element.getparent()
        while parent is not None:
            if parent.tag == f"{self.W_NS}tbl":
                return parent
            parent = parent.getparent()
        return None

    def _get_table_header_rpr(self, tbl_element, field_cell):
        """
        Get run properties from the header cell of the column containing the field.

        Args:
            tbl_element: The w:tbl element
            field_cell: The w:tc element containing the merge field

        Returns:
            rPr element from the header cell, or None if not found
        """
        # Find all rows in the table
        rows = tbl_element.findall(f"{self.W_NS}tr")
        if len(rows) < 2:
            return None  # No header row or only one row

        # Assume first row is header
        header_row = rows[0]

        # Find the column index of the field cell
        field_row = field_cell.getparent()
        if field_row is None or field_row.tag != f"{self.W_NS}tr":
            return None

        cells_in_field_row = field_row.findall(f"{self.W_NS}tc")
        field_col_idx = None
        for idx, cell in enumerate(cells_in_field_row):
            if cell == field_cell:
                field_col_idx = idx
                break

        if field_col_idx is None:
            return None

        # Handle gridSpan for merged cells - calculate logical column index
        logical_col_idx = 0
        for idx, cell in enumerate(cells_in_field_row):
            if idx == field_col_idx:
                break
            grid_span_elem = cell.find(f"{self.W_NS}tcPr/{self.W_NS}gridSpan")
            if grid_span_elem is not None:
                span = int(grid_span_elem.get(f"{self.W_NS}val", "1"))
                logical_col_idx += span - 1
            logical_col_idx += 1

        # Find the corresponding header cell, accounting for gridSpan
        header_col_idx = 0
        target_header_cell = None
        for cell in header_row.findall(f"{self.W_NS}tc"):
            if header_col_idx == logical_col_idx:
                target_header_cell = cell
                break

            grid_span_elem = cell.find(f"{self.W_NS}tcPr/{self.W_NS}gridSpan")
            if grid_span_elem is not None:
                span = int(grid_span_elem.get(f"{self.W_NS}val", "1"))
                header_col_idx += span
            else:
                header_col_idx += 1

        if target_header_cell is None:
            return None

        # Find rPr in header cell - check paragraphs and runs
        for paragraph in target_header_cell.findall(f"{self.W_NS}p"):
            for run in paragraph.findall(f"{self.W_NS}r"):
                rpr = run.find(f"{self.W_NS}rPr")
                if rpr is not None:
                    return rpr

        return None

    def _get_field_cell(self, fld):
        """Find the w:tc element containing the merge field."""
        parent = fld.getparent()
        while parent is not None:
            if parent.tag == f"{self.W_NS}tc":
                return parent
            parent = parent.getparent()
        return None

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

            # Priority order for formatting:
            # 1. If field is in a table, use formatting from the header cell of that column
            # 2. Otherwise, use formatting from the field's own nested run
            rPr = None

            # Check if field is in a table
            tbl_element = self._find_ancestor_table(fld)
            if tbl_element is not None:
                # Get formatting from table header
                field_cell = self._get_field_cell(fld)
                if field_cell is not None:
                    rPr = self._get_table_header_rpr(tbl_element, field_cell)

            # Fallback to field's own formatting if no table formatting found
            if rPr is None:
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
