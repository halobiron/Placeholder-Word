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


class MergeExecutor:
    """Execute mail merge operations with formatting preservation"""

    def __init__(self, result_dir: str = None):
        """Initialize executor

        Args:
            result_dir: Directory to save merged documents
        """
        if result_dir is None:
            # Use relative path from current working directory
            self.result_dir = Path("uploads/results")
        else:
            self.result_dir = Path(result_dir)

        # Ensure directory exists
        self.result_dir.mkdir(parents=True, exist_ok=True)

    def execute_merge(self, template_path: str, data: Dict[str, str]) -> str:
        """Execute mail merge with provided data while preserving formatting

        Args:
            template_path: Path to mail merge template
            data: Dict mapping field names to values

        Returns:
            Path to merged document

        Raises:
            ValueError: If template or data is invalid
        """
        # Validate template exists
        template_path = Path(template_path)
        if not template_path.exists():
            raise ValueError(f"Template not found: {template_path}")

        # Load template with python-docx for direct XML manipulation
        try:
            doc = Document(str(template_path))
        except Exception as e:
            raise ValueError(f"Failed to load template: {e}")

        # Get required fields from template
        template_fields = self.get_template_fields(str(template_path))

        # Validate all fields are provided
        self._validate_fields(template_fields, data)

        # Execute merge with formatting preservation
        self._merge_with_formatting(doc, data)

        # Generate result path
        result_id = str(uuid.uuid4())
        result_path = self.result_dir / f"{result_id}.docx"

        # Save merged document
        doc.save(str(result_path))

        return str(result_path), result_id

    def _merge_with_formatting(self, doc: Document, data: Dict[str, str]):
        """Replace mail merge fields with values while preserving formatting

        Args:
            doc: python-docx Document object
            data: Field-value mapping

        Note:
            Replaces w:fldSimple with regular w:r containing the value,
            preserving the original formatting from w:rPr
        """
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        # Process all paragraphs
        for para in doc.paragraphs:
            self._process_paragraph_merge(para._p, data, w_ns)

        # Process all tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        self._process_paragraph_merge(para._p, data, w_ns)

    def _process_paragraph_merge(self, p_element, data: Dict[str, str], w_ns: str):
        """Process a single paragraph element to replace merge fields

        Args:
            p_element: Paragraph XML element
            data: Field-value mapping
            w_ns: Word namespace
        """
        # Find all fldSimple elements (mail merge fields)
        fldSimple_elements = []
        for elem in p_element.iter():
            if elem.tag == f"{w_ns}fldSimple":
                fldSimple_elements.append(elem)

        # Replace each fldSimple with regular run
        for fldSimple in fldSimple_elements:
            # Get field instruction
            instr = fldSimple.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")

            # Extract field name and original text from instruction
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if match:
                field_name = match.group(1)
                z_match = re.search(r'\\z\s*"([^"]*)"', instr)
                original_text = z_match.group(1) if z_match else ""

                # Get replacement value, fallback to original_text if empty
                replacement = data.get(field_name, "")
                if replacement is None or str(replacement).strip() == "":
                    replacement = original_text
                else:
                    # Apply Word format switches manually since we are replacing the field purely in XML
                    if re.search(r'\\\*\s*Upper', instr, re.IGNORECASE):
                        replacement = str(replacement).upper()
                    elif re.search(r'\\\*\s*Caps', instr, re.IGNORECASE):
                        replacement = str(replacement).title()

                # Get formatting from the nested run
                nested_run = fldSimple.find(f"{w_ns}r")
                rPr = None
                if nested_run is not None:
                    rPr = nested_run.find(f"{w_ns}rPr")

                # Create new run with replacement value
                new_run = OxmlElement('w:r')

                # Copy formatting if exists
                if rPr is not None:
                    # Deep clone rPr to preserve all formatting
                    cloned_rPr = OxmlElement('w:rPr')
                    for child in rPr:
                        cloned_rPr.append(etree.fromstring(etree.tostring(child)))
                    new_run.append(cloned_rPr)

                # Add text
                t = OxmlElement('w:t')
                t.text = replacement
                new_run.append(t)

                # Replace fldSimple with new run
                parent = p_element
                parent.replace(fldSimple, new_run)

    def _validate_fields(self, template_fields: list, data: Dict[str, str]):
        """Validate and ensure all template fields have values (use empty string if missing)

        Args:
            template_fields: List of fields in template
            data: Provided data

        Note:
            Does NOT raise errors for missing fields - fills them with empty strings
            This allows users to fill only the fields they need
        """
        # Fill missing fields with empty strings instead of raising errors
        for field in template_fields:
            if field not in data:
                data[field] = ""

    def get_template_fields(self, template_path: str) -> list:
        """Get list of fields in template

        Args:
            template_path: Path to template

        Returns:
            List of field names
        """
        try:
            doc = Document(template_path)
            fields = []
            w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

            # Scan all paragraphs for merge fields
            for para in doc.paragraphs:
                for elem in para._p.iter():
                    if elem.tag == f"{w_ns}fldSimple":
                        instr = elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")
                        match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                        if match:
                            field_name = match.group(1)
                            if field_name not in fields:
                                fields.append(field_name)

            # Scan all tables for merge fields
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            for elem in para._p.iter():
                                if elem.tag == f"{w_ns}fldSimple":
                                    instr = elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")
                                    match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                                    if match:
                                        field_name = match.group(1)
                                        if field_name not in fields:
                                            fields.append(field_name)

            return fields

        except Exception as e:
            raise ValueError(f"Failed to read template: {e}")
