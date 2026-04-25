"""
DocxFullEditor - Edit mọi thứ trong DOCX mà vẫn giữ nguyên formatting
Hỗ trợ: text edit, format changes, add content, delete content, tables, images
"""
import re
import copy
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from lxml.etree import _Element as Element
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Twips
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree


# Alignment mappings - centralized to avoid duplication
ALIGNMENT_STRING_TO_ENUM = {
    "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
    "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
    "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
    "justify": WD_PARAGRAPH_ALIGNMENT.JUSTIFY,
    "both": WD_PARAGRAPH_ALIGNMENT.JUSTIFY,  # XML value for justify in w:jc/@w:val
}

ALIGNMENT_ENUM_TO_STRING = {
    WD_PARAGRAPH_ALIGNMENT.LEFT: 'left',
    WD_PARAGRAPH_ALIGNMENT.CENTER: 'center',
    WD_PARAGRAPH_ALIGNMENT.RIGHT: 'right',
    WD_PARAGRAPH_ALIGNMENT.JUSTIFY: 'justify',
    WD_PARAGRAPH_ALIGNMENT.DISTRIBUTE: 'justify',
}


class DocxFullEditor:
    """
    Edit DOCX trực tiếp, giữ nguyên formatting
    Không qua HTML conversion → Không mất format
    """

    def __init__(self, docx_path: str):
        self.doc_path = docx_path
        self.doc = Document(docx_path)
        self.w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        self._block_to_para_index_map = None

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for comparison by handling special whitespace and punctuation characters.

        This method ensures that text comparison works correctly even when the text contains:
        - Non-breaking spaces (\u00a0)
        - Various space characters (em-space, en-space, thin-space, etc.)
        - Unicode ellipsis and other special punctuation
        - Manual line breaks and paragraph breaks

        Args:
            text: Text to normalize

        Returns:
            Normalized text with special whitespace converted to regular spaces
            and special punctuation converted to ASCII equivalents
        """
        # Replace various whitespace characters with regular space
        # \u00a0 = non-breaking space, \u2002 = en-space, \u2003 = em-space
        # \u2009 = thin-space, \u200a = hair-space, \u200b = zero-width space
        # \u202f = narrow no-break space, \u205f = medium mathematical space
        # \u2028 = line separator, \u2029 = paragraph separator
        normalized = re.sub(r'[\s\u00a0\u2002\u2003\u2009\u200a\u200b\u202f\u205f\u2028\u2029]+', ' ', text)

        # Normalize ellipsis and other special punctuation
        # \u2026 = ellipsis (…), \u2025 = two dot leader (‥)
        normalized = normalized.replace('\u2026', '...')  # Replace … with ...
        normalized = normalized.replace('\u2025', '..')   # Replace ‥ with ..

        return normalized.strip()

    def _normalize_without_fields(self, text: str) -> str:
        """Normalize text and remove placeholders for comparison."""
        normalized = self._normalize_text(text)
        return re.sub(r'«[^»]+»', '', normalized).strip()

    def _modify_segment_text(self, seg: dict, mode: str, text: str = "", start_idx: int = None, end_idx: int = None, success_msg: str = None) -> bool:
        """
        Modify text within a document segment.
        Modes:
        - "clear": Clears all text
        - "set": Replaces the first text element's content
        - "replace": Replaces a specific range in the first text element
        """
        element = seg.get('element')
        if element is None or element.tag.split('}')[1] != 'r':
            return False

        t_elements = element.findall(f"{self.w_ns}t")
        if not t_elements:
            return False

        if mode == "clear":
            for t_elem in t_elements:
                t_elem.text = ""
            return True

        if mode == "set":
            t_elements[0].text = text
            return True

        if mode == "replace" and start_idx is not None and end_idx is not None:
            t_elem = t_elements[0]
            original_text = t_elem.text if t_elem.text else ""
            seg_start = seg['start_pos']
            # Calculate relative positions within segment
            pos_start_in_seg = max(0, start_idx - seg_start)
            pos_end_in_seg = end_idx - seg_start

            # Replace text using safe slicing
            t_elem.text = original_text[:pos_start_in_seg] + text + original_text[pos_end_in_seg:]
            if success_msg:
                print(f"[REPLACE] ✓ {success_msg}")
            return True

        return False

    def _validate_placeholder_structure(self, old_parts: list, new_parts: list) -> bool:
        """Check if placeholder structure matches between old and new text."""
        if len(old_parts) != len(new_parts):
            return False
        old_placeholders = old_parts[1::2]
        new_placeholders = new_parts[1::2]
        return old_placeholders == new_placeholders

    def _replace_text_in_segments(self, target_segments: list, start_idx: int,
                                   end_idx: int, new_text: str,
                                   success_msg: str = "Success (text replaced)") -> bool:
        """
        Unified text replacement for segments (simple or placeholder change cases).
        Handle simple case: single or multiple non-field segments.
        Clears all segments after the first, then replaces the first segment.
        """
        first_non_field_seg = None
        for seg in target_segments:
            if not seg['is_field']:
                if first_non_field_seg is None:
                    first_non_field_seg = seg
                else:
                    self._modify_segment_text(seg, "clear")

        if not first_non_field_seg:
            return False

        return self._modify_segment_text(first_non_field_seg, "replace",
                                         text=new_text, start_idx=start_idx,
                                         end_idx=end_idx, success_msg=success_msg)

    def _get_segment_rpr(self, seg: dict):
        """Get run properties element from a text or merge-field segment."""
        element = seg.get('element')
        if element is None:
            return None

        tag_name = element.tag.split('}')[1] if '}' in element.tag else element.tag
        if tag_name == 'r':
            return element.find(f"{self.w_ns}rPr")
        if tag_name == 'fldSimple':
            nested_r = element.find(f"{self.w_ns}r")
            if nested_r is not None:
                return nested_r.find(f"{self.w_ns}rPr")
        return None

    def _insert_text_segment(self, paragraph: Paragraph, insert_index: int,
                             text: str, format_sources: list) -> None:
        """Insert a new text run at a specific XML index while preserving nearby format."""
        if not text:
            return

        rpr_element = None
        for source in format_sources:
            if source is None:
                continue
            rpr_element = self._get_segment_rpr(source)
            if rpr_element is not None:
                break

        new_run = self._create_run_with_format(paragraph, rpr_element, text)
        paragraph._element.remove(new_run._element)
        paragraph._element.insert(insert_index, new_run._element)

    def _replace_text_between_placeholders(self, paragraph: Paragraph, target_segments: list,
                                            old_parts: list, new_parts: list,
                                            start_idx: int) -> bool:
        """Replace text between placeholders while preserving placeholder structure."""
        field_segments = [seg for seg in target_segments if seg['is_field']]
        text_part_to_seg = {}
        text_part_idx = 0

        for seg in target_segments:
            if not seg['is_field']:
                text_part_to_seg[text_part_idx] = seg
            else:
                text_part_idx += 1

        total_text_parts = (len(old_parts) + 1) // 2
        for text_part_idx in range(total_text_parts):
            part_idx = text_part_idx * 2
            if part_idx >= len(old_parts) or part_idx >= len(new_parts):
                continue

            old_part = old_parts[part_idx]
            new_part = new_parts[part_idx]
            existing_seg = text_part_to_seg.get(text_part_idx)

            if existing_seg is not None:
                if old_part != new_part:
                    if self._modify_segment_text(existing_seg, "set", text=new_part):
                        print(f"[REPLACE] ✓ Updated text part {text_part_idx}: '{old_part}' -> '{new_part}'")
                continue

            if not new_part:
                continue

            if text_part_idx == 0:
                anchor_seg = target_segments[0]
                insert_index = list(paragraph._element).index(anchor_seg['element'])
                format_sources = [anchor_seg]
            else:
                previous_field = field_segments[text_part_idx - 1]
                previous_field_index = list(paragraph._element).index(previous_field['element'])
                insert_index = previous_field_index + 1
                next_field = field_segments[text_part_idx] if text_part_idx < len(field_segments) else None
                format_sources = [
                    text_part_to_seg.get(text_part_idx - 1),
                    previous_field,
                    next_field
                ]

            self._insert_text_segment(paragraph, insert_index, new_part, format_sources)
            print(f"[REPLACE] ✓ Inserted missing text part {text_part_idx}: '{new_part}'")

        print(f"[REPLACE] ✓ Success (text between placeholders)")
        return True

    def _build_block_index_map(self):
        """
        Build mapping from block_index (HTML preview) to paragraph_index (DOCX)

        Uses EXACTLY the same logic as template_manager.py _generate_html_preview
        to ensure block_index consistency between HTML preview and editing.

        Iteration order: doc.element.body.iterchildren() (document order)
        """
        if self._block_to_para_index_map is not None:
            return


        self._block_to_para_index_map = {}
        block_index = 0

        # Build map using EXACTLY the same logic as _generate_html_preview
        # Use body children directly to preserve document order
        for child in self.doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                para = Paragraph(child, self.doc)

                # Extract text from XML to match _generate_html_preview logic
                text_from_xml = ""
                for t in child.findall(f".//{self.w_ns}t"):
                    if t.text:
                        text_from_xml += t.text
                text = text_from_xml.strip()

                # Process ALL paragraphs (including empty ones) like _generate_html_preview
                # Store reference to paragraph object instead of index
                self._block_to_para_index_map[block_index] = {
                    'type': 'paragraph',
                    'paragraph': para,  # Store paragraph object directly
                    'table_context': None
                }
                block_index += 1

            elif isinstance(child, CT_Tbl):
                table = Table(child, self.doc)

                # Process each cell as a separate block (matching _generate_html_preview logic)
                # CRITICAL FIX: Map ALL cells (including empty ones) to match HTML preview behavior
                # HTML preview increments block_index for ALL cells, so we must do the same
                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        # Extract cell text to check if it has content
                        cell_text = ""
                        for para in cell.paragraphs:
                            for t in para._p.findall(f".//{self.w_ns}t"):
                                if t.text:
                                    cell_text += t.text
                        is_empty = not cell_text.strip()

                        # Determine paragraph and empty status
                        para = cell.paragraphs[0] if cell.paragraphs else None

                        # Map ALL cells (including empty ones) to match HTML preview
                        self._block_to_para_index_map[block_index] = {
                            'type': 'table_cell',
                            'paragraph': para,
                            'table_context': f"Row {row_idx}, Col {cell_idx}",
                            'row': row_idx,
                            'col': cell_idx,
                            'is_empty': is_empty if para else True
                        }
                        block_index += 1

    def get_table_cell_paragraph_index(self, block_index: int, para_in_cell: int) -> int:
        """
        Get paragraph_index for a specific paragraph within a table cell

        Args:
            block_index: Block index of the table cell (from HTML preview)
            para_in_cell: Paragraph index within the cell (0-based)

        Returns:
            Paragraph index in document order, or None if not found
        """
        self._build_block_index_map()

        if block_index not in self._block_to_para_index_map:
            return None

        block_data = self._block_to_para_index_map[block_index]

        if block_data['type'] != 'table_cell':
            return None

        # Get cell location from block data
        row_idx = block_data['row']
        col_idx = block_data['col']

        # Find the specific table and cell
        target_cell = None
        for table in self.doc.tables:
            if row_idx < len(table.rows) and col_idx < len(table.rows[row_idx].cells):
                target_cell = table.rows[row_idx].cells[col_idx]
                break

        if not target_cell:
            return None

        # Check if para_in_cell is valid
        if para_in_cell >= len(target_cell.paragraphs):
            return None

        # Find the specific paragraph in document order
        target_paragraph = target_cell.paragraphs[para_in_cell]

        for idx, para in enumerate(self._iterate_paragraphs_in_doc_order()):
            if para._element == target_paragraph._element:
                return idx

        return None

    def get_paragraph_index_from_block(self, block_index: int) -> int:
        """
        Get paragraph_index from block_index (HTML preview)

        Args:
            block_index: Block index from HTML preview

        Returns:
            Paragraph index in document order (matching _generate_html_preview),
            or None if not found
        """
        self._build_block_index_map()

        if block_index not in self._block_to_para_index_map:
            return None

        block_data = self._block_to_para_index_map[block_index]
        target_paragraph = block_data['paragraph']

        # Use the same iteration logic to find the index
        for idx, para in enumerate(self._iterate_paragraphs_in_doc_order()):
            if para._element == target_paragraph._element:
                return idx

        return None

    # ===== HELPER METHODS =====

    def _iterate_paragraphs_in_doc_order(self):
        """
        Yield paragraphs in document order (matching _generate_html_preview logic)

        Uses doc.element.body.iterchildren() to preserve exact document structure.
        CRITICAL FIX: Yield ALL paragraphs including those in table cells
        to properly support text editing in any paragraph.
        """

        for child in self.doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                para = Paragraph(child, self.doc)
                yield para
            elif isinstance(child, CT_Tbl):
                table = Table(child, self.doc)
                # Process ALL paragraphs in ALL cells
                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        # Yield ALL paragraphs from each cell (not just the first one)
                        if cell.paragraphs:
                            for para in cell.paragraphs:
                                yield para
                        # else: cell has no paragraphs (shouldn't happen with properly formatted cells)

    def _collect_paragraph_text_segments(self, paragraph: Paragraph) -> list:
        """
        Collect ordered text segments from a paragraph, including MERGEFIELD placeholders.

        This is the shared core for text extraction and deletion logic.
        """
        text_segments = []
        current_pos = 0

        for child in paragraph._element:
            tag_name = child.tag.split('}')[1] if '}' in child.tag else child.tag

            if tag_name == 'r':
                run_text = "".join(t.text for t in child.findall(f"{self.w_ns}t") if t.text)
                if run_text:
                    text_segments.append({
                        'text': run_text,
                        'is_field': False,
                        'element': child,
                        'start_pos': current_pos,
                        'end_pos': current_pos + len(run_text)
                    })
                    current_pos += len(run_text)

            elif tag_name == 'fldSimple':
                instr = child.get(f"{self.w_ns}instr", "")
                match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                if match:
                    field_name = match.group(1)
                    field_text = f"«{field_name}»"
                    text_segments.append({
                        'text': field_text,
                        'is_field': True,
                        'element': child,
                        'field_name': field_name,
                        'start_pos': current_pos,
                        'end_pos': current_pos + len(field_text)
                    })
                    current_pos += len(field_text)

        return text_segments

    # ===== POSITION-BASED EDITING =====

    def _extract_paragraph_full_text(self, paragraph: Paragraph) -> tuple:
        """
        Extract full text from paragraph including MERGEFIELD placeholders

        Returns:
            Tuple of (full_text, text_segments) where:
            - full_text: Complete text with placeholders
            - text_segments: List of dicts with keys:
                - text: str (segment text)
                - is_field: bool (True if MERGEFIELD)
                - element: XML element (for editing)
                - start_pos: int (start position in full_text)
                - end_pos: int (end position in full_text)
        """
        text_segments = self._collect_paragraph_text_segments(paragraph)
        full_text = "".join(seg['text'] for seg in text_segments)
        return full_text, text_segments

    def _handle_empty_replacement(
        self,
        new_text: str,
        paragraph_index: int,
        reason: str
    ) -> bool:
        """Handle replacement when old_text is empty/whitespace-only."""
        print(f"[DEBUG] {reason}")

        if paragraph_index is None:
            return False

        # Find target paragraph
        paragraph = next(
            (p for i, p in enumerate(self._iterate_paragraphs_in_doc_order()) if i == paragraph_index),
            None
        )
        if not paragraph:
            return False

        # Insert or clear text
        if new_text and new_text.strip():
            clean_text = new_text.lstrip('\xa0')

            if paragraph.runs:
                paragraph.runs[0].text = clean_text
            else:
                # Use XML directly to avoid python-docx adding non-breaking space
                r = OxmlElement('w:r')
                t = OxmlElement('w:t')
                t.set(qn('xml:space'), 'preserve')
                t.text = clean_text
                r.append(t)
                paragraph._element.append(r)

            print(f"[DEBUG] Inserted new_text into paragraph {paragraph_index}: '{new_text}'")
        else:
            for run in paragraph.runs:
                run.text = ""
            print(f"[DEBUG] Cleared paragraph {paragraph_index}")

        return True

    def replace_text_at_position(
        self,
        old_text: str,
        new_text: str,
        paragraph_index: int = None,
        run_index: int = None
    ):
        """
        Replace text at a specific position only

        CRITICAL FIX: Now properly handles MERGEFIELD placeholders to avoid duplication.
        Preserves paragraph formatting during text replacement.

        Args:
            old_text: Text to find
            new_text: Replacement text
            paragraph_index: Index of paragraph (from all paragraphs iterator)
            run_index: Index of run within paragraph (optional, for more precision)

        Returns:
            True if found and replaced, False otherwise
        """
        # Special case: Deleting empty paragraph (old_text is empty or whitespace-only)
        # CRITICAL FIX: Check old_text BEFORE normalization to handle &nbsp; and spaces correctly
        if old_text is None or (isinstance(old_text, str) and not old_text.strip()):
            return self._handle_empty_replacement(
                new_text, paragraph_index,
                f"Handling empty/whitespace old_text: repr(old_text)={repr(old_text)}"
            )

        # Check if normalized text is empty (happens with &nbsp;, multiple spaces, etc.)
        search_text_normalized = self._normalize_text(old_text)
        if not search_text_normalized:
            return self._handle_empty_replacement(
                new_text, paragraph_index,
                f"Normalized text is empty, treating as deletion: repr(old_text)={repr(old_text)}"
            )

        # When paragraph_index is specified, concatenate adjacent paragraphs
        # to handle text that spans multiple paragraphs
        if paragraph_index is not None:
            # Collect paragraphs in range [paragraph_index, paragraph_index + 3]
            paragraphs_to_search = []
            for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
                if paragraph_index <= p_idx <= paragraph_index + 3:
                    paragraphs_to_search.append((p_idx, paragraph))

            # Concatenate all paragraphs in range
            combined_text = ""
            combined_paragraphs = []
            for p_idx, paragraph in paragraphs_to_search:
                para_text = "".join(run.text for run in paragraph.runs)
                combined_text += para_text
                combined_paragraphs.append((p_idx, paragraph, para_text))

            combined_text_normalized = self._normalize_text(combined_text)

            if search_text_normalized in combined_text_normalized:
                print(f"[REPLACE] Found across paragraphs {paragraph_index}-{paragraph_index + 3}")
                # Find which paragraph contains the start of the text
                for p_idx, paragraph, para_text in combined_paragraphs:
                    para_text_normalized = self._normalize_text(para_text)
                    if search_text_normalized[:50] in para_text_normalized:  # First 50 chars
                        paragraph_index = p_idx
                        break

        # Continue with normal search using updated paragraph_index
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            # If paragraph_index is specified, only process that paragraph
            if paragraph_index is not None and p_idx != paragraph_index:
                continue

            # CRITICAL FIX: Use new method to extract full text including MERGEFIELDs
            full_text, text_segments = self._extract_paragraph_full_text(paragraph)
            full_text_normalized = self._normalize_text(full_text)

            # Log what's in the paragraph
            print(f"[REPLACE] Paragraph content: '{full_text_normalized[:100]}{'...' if len(full_text_normalized) > 100 else ''}'")

            if search_text_normalized not in full_text_normalized:
                # CRITICAL FIX: Try fuzzy match with placeholders removed
                old_no_fields = self._normalize_without_fields(old_text)
                full_no_fields = self._normalize_without_fields(full_text)

                print(f"[REPLACE] Not found - trying without placeholders")
                print(f"[REPLACE]   Old (no fields): '{old_no_fields[:100]}{'...' if len(old_no_fields) > 100 else ''}'")
                print(f"[REPLACE]   Full (no fields): '{full_no_fields[:100]}{'...' if len(full_no_fields) > 100 else ''}'")

                if old_no_fields and old_no_fields in full_no_fields:
                    search_text_normalized = old_no_fields
                    print(f"[REPLACE] ✓ Match found without placeholders: '{search_text_normalized[:100]}{'...' if len(search_text_normalized) > 100 else ''}'")
                else:
                    print(f"[REPLACE] ✗ NO MATCH - skipping paragraph {p_idx}")
                    continue

            # Find position of text to replace
            start_idx = full_text_normalized.find(search_text_normalized)
            if start_idx == -1:
                print(f"[REPLACE] ✗ Could not find position in normalized text")
                continue

            end_idx = start_idx + len(search_text_normalized)

            print(f"[REPLACE] ✓ Found at position {start_idx}-{end_idx} (length: {len(search_text_normalized)})")
            # CRITICAL FIX: Find which segments contain the text to replace
            target_segments = []
            for seg in text_segments:
                seg_start = seg['start_pos']
                seg_end = seg['end_pos']

                # Check if this segment overlaps with the text to replace
                if seg_end > start_idx and seg_start < end_idx:
                    target_segments.append(seg)

            if not target_segments:
                print(f"[REPLACE] ✗ No target segments found")
                continue

            # Count field vs non-field segments
            field_count = sum(1 for seg in target_segments if seg['is_field'])
            print(f"[REPLACE] Target: {len(target_segments)} segments ({field_count} fields, {len(target_segments) - field_count} text)")

            # CRITICAL FIX: Handle MERGEFIELD properly during replacement
            # We need to identify which parts of old_text are placeholders and which are regular text
            has_field_in_target = any(seg['is_field'] for seg in target_segments)

            if has_field_in_target:
                placeholder_pattern = r'«([^»]+)»'
                old_parts = re.split(placeholder_pattern, old_text)
                new_parts = re.split(placeholder_pattern, new_text)

                # Validate placeholder structure
                if self._validate_placeholder_structure(old_parts, new_parts):
                    print(f"[REPLACE] Placeholders match: {old_parts[1::2]}")
                    return self._replace_text_between_placeholders(paragraph, target_segments, old_parts, new_parts, start_idx)
                else:
                    print(f"[REPLACE] Warning: Placeholder structure differs")
                    print(f"[REPLACE]   Old placeholders: {re.findall(placeholder_pattern, old_text)}")
                    print(f"[REPLACE]   New placeholders: {re.findall(placeholder_pattern, new_text)}")
                    print(f"[REPLACE] Placeholder change detected, using minimax pattern")
                    return self._replace_text_in_segments(target_segments, start_idx, end_idx, new_text,
                                                          success_msg="Success (placeholder changed)")

            # Perform replacement - simple case (no fields in target)
            if self._replace_text_in_segments(target_segments, start_idx, end_idx, new_text,
                                              success_msg="Success (single/multiple segments)"):
                print(f"[REPLACE] ===== TEXT REPLACE END (SUCCESS) =====")
                return True

            print(f"[REPLACE] ✗ No replacement done - replacement failed")
            print(f"[REPLACE] ===== TEXT REPLACE END (FAILED) =====")
            return False

        print(f"[REPLACE] ✗ No matching paragraph found")
        print(f"[REPLACE] ===== TEXT REPLACE END (NOT FOUND) =====")
        return False

    def _extract_all_text_runs(self, paragraph: Paragraph) -> list:
        """
        Extract all text runs from a paragraph, including those inside hyperlinks and merge fields.

        In DOCX, hyperlinks (w:hyperlink) contain runs (w:r) with text.
        Merge fields (w:fldSimple) also contain runs (w:r) with text.
        The standard paragraph.runs property doesn't include these hyperlink or merge field runs.

        Args:
            paragraph: Paragraph object

        Returns:
            List of dicts with keys:
                - run: Run object
                - text: str (run text)
                - is_hyperlink: bool (True if run is inside a hyperlink)
                - hyperlink_url: str or None (URL if is_hyperlink is True)
                - is_merge_field: bool (True if run is inside a merge field/fldSimple)
                - start_offset: int (character offset in paragraph text)
                - end_offset: int (end character offset in paragraph text)
        """
        from docx.text.run import Run

        all_runs = []
        char_offset = 0
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        def _add_run(r_elem, parent_elem, is_hyperlink=False, hyperlink_url=None,
                     is_merge_field=False, merge_field_element=None):
            """Helper: add run entry to all_runs list."""
            run = Run(r_elem, paragraph)
            run_text = run.text or ""
            entry = {
                'run': run,
                'text': run_text,
                'is_hyperlink': is_hyperlink,
                'hyperlink_url': hyperlink_url,
                'is_merge_field': is_merge_field,
                'start_offset': char_offset,
                'end_offset': char_offset + len(run_text),
                'element': r_elem,
            }
            if is_hyperlink:
                entry['hyperlink_element'] = parent_elem
            if is_merge_field:
                entry['merge_field_element'] = merge_field_element
            all_runs.append(entry)
            return len(run_text)

        # First, collect all runs including those in hyperlinks and merge fields
        for child in paragraph._element:
            tag_name = child.tag.split('}')[1] if '}' in child.tag else child.tag

            if tag_name == 'r':
                # Regular run
                char_offset += _add_run(child, child)

            elif tag_name == 'hyperlink':
                # Hyperlink element - extract runs inside it
                r_id = child.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                hyperlink_url = ""
                if r_id and r_id in self.doc.part.rels:
                    rel = self.doc.part.rels[r_id]
                    hyperlink_url = rel._target if hasattr(rel, '_target') else ""

                for hc_child in child:
                    hc_tag = hc_child.tag.split('}')[1] if '}' in hc_child.tag else hc_child.tag
                    if hc_tag == 'r':
                        char_offset += _add_run(hc_child, child, is_hyperlink=True,
                                                hyperlink_url=hyperlink_url)

            elif tag_name == 'fldSimple':
                # Merge field element (w:fldSimple) - extract run inside it
                for mf_child in child:
                    mf_tag = mf_child.tag.split('}')[1] if '}' in mf_child.tag else mf_child.tag
                    if mf_tag == 'r':
                        char_offset += _add_run(mf_child, child, is_merge_field=True,
                                                merge_field_element=child)

        return all_runs

    def apply_format_at_position(
        self,
        text: str,
        paragraph_index: int,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        subscript: bool = None,
        superscript: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None,
        all_caps: bool = None,
        start_offset: int = None,
        end_offset: int = None
    ):
        """
        Apply formatting to text at a specific paragraph position
        Splits runs if needed to format only the target text, not the entire run
        Supports formatting text inside hyperlinks

        Args:
            text: Text to format
            paragraph_index: Index of paragraph containing the text
            bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size: Format options
            all_caps: All caps formatting
            start_offset: Start character offset (REQUIRED - no fallback for safety)
            end_offset: End character offset (REQUIRED - no fallback for safety)

        Returns:
            True if found and formatted, False if offsets invalid/missing
        """
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx != paragraph_index:
                continue

            all_runs = self._extract_all_text_runs(paragraph)
            full_text = "".join(run_info['text'] for run_info in all_runs)

            print(f"[DEBUG] apply_format_at_position: p_idx={p_idx}, len={len(full_text)}, offsets={start_offset}-{end_offset}, text='{text}'")

            # CRITICAL: Offsets are REQUIRED for precise formatting
            # No fallback to text search - it can format wrong occurrence of duplicate text
            if start_offset is None or end_offset is None:
                print(f"[ERROR] Offsets not provided - cannot format safely")
                return False

            # Validate offsets
            if not (0 <= start_offset < end_offset <= len(full_text)):
                print(f"[ERROR] Invalid offsets: {start_offset}-{end_offset}, text_len={len(full_text)}")
                return False

            start_idx, end_idx = start_offset, end_offset
            print(f"[DEBUG] Using offsets: start_idx={start_idx}, end_idx={end_idx}")

            # Find runs that overlap with target text
            runs_to_format = []
            for r_idx, run_info in enumerate(all_runs):
                run_start, run_end = run_info['start_offset'], run_info['end_offset']

                if run_end > start_idx and run_start < end_idx:
                    overlap_start = max(start_idx, run_start)
                    overlap_end = min(end_idx, run_end)
                    text_to_format = run_info['text'][overlap_start - run_start:overlap_end - run_start]

                    runs_to_format.append({
                        'run': run_info['run'],
                        'r_idx': r_idx,
                        'run_info': run_info,
                        'run_start': run_start,
                        'run_end': run_end,
                        'overlap_start': overlap_start,
                        'overlap_end': overlap_end,
                        'text_to_format': text_to_format
                    })

            if not runs_to_format:
                continue

            # Dispatch formatting based on hyperlink presence
            has_hyperlinks = any(rf['run_info']['is_hyperlink'] for rf in runs_to_format)
            format_method = self._format_hyperlink_text if has_hyperlinks else self._format_text_in_runs

            format_method(
                paragraph, runs_to_format,
                bold, italic, underline, strikethrough, subscript, superscript,
                color, highlight, font_name, font_size, all_caps
            )
            return True

        return False

    def _calculate_text_segments(self, run, overlap_start: int, overlap_end: int, run_start: int, run_end: int) -> tuple:
        """
        Calculate text segments for run splitting (3 parts)

        Returns:
            (text_before, text_to_format, text_after)
        """
        text_before = run.text[:overlap_start - run_start]
        text_to_format = run.text[overlap_start - run_start:overlap_end - run_start]
        text_after = run.text[overlap_end - run_start:]
        return text_before, text_to_format, text_after

    def _split_run_at_offset(self, run, offset: int, run_start: int) -> tuple:
        """
        Split run text at a global offset position (2 parts)

        Use when inserting something at a specific position (placeholder, table, image).

        Args:
            run: The run to split
            offset: Global offset position in paragraph
            run_start: Start position of this run in paragraph

        Returns:
            (text_before, text_after)
        """
        split_pos = offset - run_start
        text_before = run.text[:split_pos]
        text_after = run.text[split_pos:]
        return text_before, text_after

    def _find_paragraph_by_index(self, paragraph_index: int):
        """
        Find paragraph by index using document order iterator.

        Reused in: insert_placeholder_at_offset, add_table_at_cursor

        Args:
            paragraph_index: Index of paragraph (from all paragraphs iterator)

        Returns:
            Paragraph object or None if not found
        """
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx == paragraph_index:
                return paragraph
        return None

    def _build_run_text_map(self, paragraph) -> List[Dict]:
        """
        Build mapping of runs to their text positions in paragraph.

        Reused in: insert_placeholder_at_offset, add_table_at_cursor

        Args:
            paragraph: Paragraph object

        Returns:
            List of dicts with keys: run, start, end, text
        """
        run_text_map = []
        current_offset = 0
        for run in paragraph.runs:
            if run.text:
                text_len = len(run.text)
                run_text_map.append({
                    'run': run,
                    'start': current_offset,
                    'end': current_offset + text_len,
                    'text': run.text
                })
                current_offset += text_len
        return run_text_map

    def _find_run_at_offset(self, run_text_map: List[Dict], offset: int) -> Optional[Dict]:
        """
        Find which run contains the given offset.

        Args:
            run_text_map: List from _build_run_text_map
            offset: Character offset to find

        Returns:
            Run info dict or None
        """
        for run_info in run_text_map:
            if run_info['start'] <= offset <= run_info['end']:
                return run_info
        return None

    def _read_alignment_from_xml(self, p_element) -> Optional[WD_PARAGRAPH_ALIGNMENT]:
        """
        Read paragraph alignment directly from XML (avoids object property issues).

        Reused in: empty paragraph case, same cell alignment search

        Args:
            p_element: Paragraph XML element

        Returns:
            WD_PARAGRAPH_ALIGNMENT or None
        """
        try:
            pPr = p_element.find(f"{self.w_ns}pPr")
            if pPr is not None:
                jc = pPr.find(f"{self.w_ns}jc")
                if jc is not None:
                    jc_val = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    return ALIGNMENT_STRING_TO_ENUM.get(jc_val)
        except Exception:
            pass
        return None

    def _find_alignment_in_same_cell(self, p_element) -> Optional[WD_PARAGRAPH_ALIGNMENT]:
        """
        Find alignment from another paragraph in the same table cell.

        Args:
            p_element: Current paragraph XML element

        Returns:
            WD_PARAGRAPH_ALIGNMENT or None
        """
        try:
            parent_tc = None
            current = p_element
            while current is not None:
                if current.tag == f"{self.w_ns}tc":
                    parent_tc = current
                    break
                current = current.getparent()

            if parent_tc is not None:
                cell_paras = parent_tc.findall(f"{self.w_ns}p")
                for cell_para_xml in cell_paras:
                    if cell_para_xml == p_element:
                        continue
                    alignment = self._read_alignment_from_xml(cell_para_xml)
                    if alignment is not None:
                        return alignment
        except Exception:
            pass
        return None

    def _get_format_from_previous_paragraph(self, target_para) -> tuple:
        """
        Get run format and alignment from previous paragraph in document.

        Args:
            target_para: Current paragraph object

        Returns:
            (rpr_element, alignment) tuple
        """
        original_rpr = None
        original_alignment = None
        try:
            all_paras = list(self._iterate_paragraphs_in_doc_order())
            current_idx = None
            for idx, para in enumerate(all_paras):
                if para._element == target_para._element:
                    current_idx = idx
                    break

            if current_idx is not None and current_idx > 0:
                prev_para = all_paras[current_idx - 1]
                for run in prev_para.runs:
                    rpr = run._r.get_or_add_rPr()
                    if rpr is not None and len(list(rpr)) > 0:
                        original_rpr = rpr
                        break
                if prev_para.alignment is not None:
                    original_alignment = prev_para.alignment
        except Exception:
            pass

        return original_rpr, original_alignment

    def _get_format_from_previous_run(self, run_text_map: List[Dict], target_run) -> Optional[Element]:
        """
        Find format from previous non-placeholder run.

        Args:
            run_text_map: List from _build_run_text_map
            target_run: Current run to skip when searching

        Returns:
            rpr element or None
        """
        for i in range(len(run_text_map) - 1, -1, -1):
            prev_run_info = run_text_map[i]
            if prev_run_info['run'] == target_run:
                continue

            run_text = prev_run_info['text'] or ''
            is_placeholder = '«' in run_text and '»' in run_text

            if not is_placeholder and run_text.strip():
                prev_rpr = prev_run_info['run']._r.get_or_add_rPr()
                if prev_rpr is not None and len(list(prev_rpr)) > 0:
                    return prev_rpr
        return None

    def _insert_placeholder_to_empty_paragraph(
        self, target_para, p_element, field_name: str, paragraph_index: int
    ) -> bool:
        """
        Handle placeholder insertion into empty paragraph.

        Args:
            target_para: Empty paragraph object
            p_element: Paragraph XML element
            field_name: Merge field name
            paragraph_index: For debug logging

        Returns:
            True if successful
        """
        from docx.oxml import parse_xml

        placeholder_text = f"«{field_name}»"

        # Read current alignment
        current_alignment = self._read_alignment_from_xml(p_element)
        if current_alignment is None:
            current_alignment = target_para.alignment

        # Get format from previous paragraph or use default
        original_rpr, original_alignment = self._get_format_from_previous_paragraph(target_para)

        if original_rpr is None:
            default_rpr_xml = '<w:rPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
            original_rpr = parse_xml(default_rpr_xml)

        # Create placeholder with MERGEFIELD structure
        placeholder_run = self._create_run_with_format(target_para, original_rpr, placeholder_text)
        fld = OxmlElement('w:fldSimple')
        fld.set(qn('w:instr'), f' MERGEFIELD {field_name} \\* MERGEFORMAT \\z "" ')
        fld.append(placeholder_run._element)
        p_element.insert(0, fld)

        # Set final alignment priority: current > same cell > previous > default
        if current_alignment is None:
            current_alignment = self._find_alignment_in_same_cell(p_element)

        final_alignment = current_alignment if current_alignment is not None else original_alignment
        if final_alignment is not None:
            target_para.alignment = final_alignment

        return True

    def _handle_boolean_formats(self, bold=None, italic=None, underline=None,
                                strikethrough=None, all_caps=None, *, rpr=None):
        """
        Handle boolean format properties - either return skip props or apply to rpr

        Args:
            rpr: If provided, apply formats to rpr. If None, return list of tags to skip (keyword-only)

        Returns:
            List of property tags to skip (when rpr is None)
        """
        formats = [
            ('b', bold),
            ('i', italic),
            ('u', underline, 'single'),
            ('strike', strikethrough),
            ('caps', all_caps),
        ]

        skip_props = []
        for spec in formats:
            tag = spec[0]
            value = spec[1]
            if value is not None:
                if rpr is not None:
                    attr_value = spec[2] if len(spec) > 2 else '1'
                    self._toggle_boolean_format(rpr, tag, value, attr_value=attr_value)
                else:
                    skip_props.append(tag)
        return skip_props

    def _format_text_in_runs(
        self,
        paragraph,
        runs_to_format: List[Dict],
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        subscript: bool = None,
        superscript: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None,
        all_caps: bool = None
    ):
        """
        Split runs và apply formatting chỉ cho text cần format
        PRESERVES paragraph-level formatting (alignment, indents, tabs)

        Args:
            paragraph: Paragraph object
            runs_to_format: List of run info dicts from apply_format_at_position
            bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size: Format options
            all_caps: All caps formatting
        """
        # CRITICAL: Preserve paragraph-level formatting before splitting runs
        # This prevents loss of alignment, indents, tabs used for right-alignment tricks
        paragraph_alignment = paragraph.alignment
        paragraph_format = paragraph.paragraph_format

        skip_props = self._handle_boolean_formats(bold, italic, underline)

        # Process runs in reverse order to maintain indices
        for run_info in reversed(runs_to_format):
            run = run_info['run']
            r_idx = run_info['r_idx']
            overlap_start = run_info['overlap_start']
            overlap_end = run_info['overlap_end']
            run_start = run_info['run_start']
            run_end = run_info['run_end']

            text_before, text_to_format, text_after = self._calculate_text_segments(run, overlap_start, overlap_end, run_start, run_end)

            # Case 1: Toàn bộ run cần format → chỉ apply format
            if not text_before and not text_after:
                self._apply_format_to_run(run, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size)
                continue

            # Case 2: Cần split run

            # Get original format properties
            original_rpr = run._r.get_or_add_rPr()

            # Xóa text gốc
            run.text = ""

            insert_index = list(paragraph._element).index(run._element)

            # Chèn text_before (nếu có) - keep all original format
            if text_before:
                new_run = self._create_run_with_format(paragraph, original_rpr, text_before)
                paragraph._element.insert(insert_index, new_run._element)
                insert_index += 1

            # Chèn text_to_format với format mới - skip properties that will be set
            if text_to_format:
                formatted_run = self._create_run_with_format(paragraph, original_rpr, text_to_format, skip_props=skip_props)
                self._apply_format_to_run(formatted_run, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size, all_caps)
                paragraph._element.insert(insert_index, formatted_run._element)
                insert_index += 1

            # Chèn text_after (nếu có) - keep all original format
            if text_after:
                new_run = self._create_run_with_format(paragraph, original_rpr, text_after)
                paragraph._element.insert(insert_index, new_run._element)

            # Xóa run gốc
            paragraph._element.remove(run._element)

        # CRITICAL: Restore paragraph-level formatting after splitting runs
        self._restore_paragraph_formatting(paragraph, paragraph_alignment, paragraph_format)

    def _format_hyperlink_text(
        self,
        paragraph,
        runs_to_format: List[Dict],
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        subscript: bool = None,
        superscript: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None,
        all_caps: bool = None
    ):
        """
        Format text inside hyperlinks while preserving hyperlink structure

        CRITICAL: This method preserves the w:hyperlink element wrapper while modifying
        the formatting of runs inside it. This is essential because breaking the hyperlink
        structure would remove the link itself.

        Args:
            paragraph: Paragraph object
            runs_to_format: List of run info dicts (must include hyperlink metadata)
            bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size: Format options
            all_caps: All caps formatting
        """
        skip_props = self._handle_boolean_formats(bold, italic, underline)

        # Group runs by hyperlink element
        hyperlink_groups = {}
        for run_info in runs_to_format:
            run_data = run_info['run_info']
            if run_data['is_hyperlink']:
                hl_element = run_data['hyperlink_element']
                if id(hl_element) not in hyperlink_groups:
                    hyperlink_groups[id(hl_element)] = {
                        'hyperlink_element': hl_element,
                        'runs': []
                    }
                hyperlink_groups[id(hl_element)]['runs'].append(run_info)

        # Process each hyperlink group
        for hl_group in hyperlink_groups.values():
            hl_element = hl_group['hyperlink_element']
            group_runs = hl_group['runs']

            for run_data in group_runs:
                run = run_data['run']
                overlap_start = run_data['overlap_start']
                overlap_end = run_data['overlap_end']
                run_start = run_data['run_start']
                run_end = run_data['run_end']

                # Calculate text segments using helper
                text_before, text_to_format, text_after = self._calculate_text_segments(run, overlap_start, overlap_end, run_start, run_end)

                # Get original run formatting
                original_rpr = run._element.find(qn('w:rPr'))

                # Get position in hyperlink element
                run_elements = list(hl_element.findall(qn('w:r')))
                try:
                    run_index = run_elements.index(run._element)
                except ValueError:
                    continue

                # Case 1: Entire run needs formatting
                if not text_before and not text_after:
                    # Just apply formatting to the existing run
                    self._apply_format_to_run(run, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size, all_caps)
                    continue

                # Case 2: Need to split the run
                insert_offset = run_index

                # Remove original run
                hl_element.remove(run._element)

                # Insert before_text (keep original format)
                if text_before:
                    before_run = self._create_run_in_hyperlink(hl_element, original_rpr, text_before, insert_offset)
                    insert_offset += 1

                # Insert text_to_format with new formatting
                if text_to_format:
                    formatted_run = self._create_run_in_hyperlink(hl_element, original_rpr, text_to_format, insert_offset, skip_props=skip_props)
                    self._apply_format_to_run(formatted_run, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size, all_caps)
                    insert_offset += 1

                # Insert after_text (keep original format)
                if text_after:
                    after_run = self._create_run_in_hyperlink(hl_element, original_rpr, text_after, insert_offset)
                    # No increment needed for last insert

    def _create_run_in_hyperlink(self, hyperlink_element, rpr_element, text: str, insert_offset: int, skip_props: list = None):
        """
        Create a new run inside a hyperlink element

        Args:
            hyperlink_element: w:hyperlink XML element
            rpr_element: RunProperties element to copy format from
            text: Text for the new run
            insert_offset: Position to insert the run
            skip_props: Properties to skip when copying

        Returns:
            New Run object (not yet added to paragraph, just XML element created)
        """
        new_run = self._create_run_element(text, rpr_element, skip_props=skip_props)

        # Insert into hyperlink element
        hyperlink_element.insert(insert_offset, new_run)

        # Return a minimal Run wrapper for _apply_format_to_run
        # Note: This is a simplified wrapper, sufficient for format application
        class SimpleRun:
            def __init__(self, element):
                self._element = element
                self.text = text

            @property
            def _r(self):
                return self._element

        return SimpleRun(new_run)


    def _copy_run_rpr(self, rpr_element, skip_props: list = None):
        """Clone run properties while optionally removing specific properties."""
        if rpr_element is None:
            return None

        new_rpr = copy.deepcopy(rpr_element)
        if skip_props:
            for prop in skip_props:
                for child in list(new_rpr.findall(f'{self.w_ns}{prop}')):
                    new_rpr.remove(child)
        return new_rpr


    def _append_rpr_children(self, target_rpr, source_rpr, skip_props: list = None):
        """Copy run-property children from source to target."""
        if source_rpr is None:
            return

        skip_props = skip_props or []
        for child in source_rpr:
            prop_tag = child.tag.replace(f'{self.w_ns}', '')
            if prop_tag in skip_props:
                continue
            target_rpr.append(copy.deepcopy(child))


    def _create_run_element(self, text: str, rpr_element=None, skip_props: list = None):
        """Create a raw w:r element with preserved formatting and text."""
        new_run = OxmlElement('w:r')
        new_rpr = self._copy_run_rpr(rpr_element, skip_props=skip_props)
        if new_rpr is not None:
            new_run.append(new_rpr)

        new_t = OxmlElement('w:t')
        new_t.set(qn('xml:space'), 'preserve')
        new_t.text = text
        new_run.append(new_t)
        return new_run


    def _create_run_with_format(self, paragraph, rpr_element, text: str, skip_props: list = None):
        """
        Tạo run mới với format từ rpr_element

        Args:
            paragraph: Paragraph object
            rpr_element: RunProperties element để copy format
            text: Text cho run mới
            skip_props: List of properties to skip (e.g., ['b', 'i', 'u'] for bold, italic, underline)

        Returns:
            New Run object
        """
        new_run = paragraph.add_run(text)

        # Copy format properties, excluding specified ones
        new_rpr = new_run._r.get_or_add_rPr()
        self._append_rpr_children(new_rpr, rpr_element, skip_props=skip_props)

        return new_run


    def _apply_hyperlink_style(self, rpr_element):
        """Force hyperlink styling onto an rPr element."""
        if rpr_element is None:
            rpr_element = OxmlElement('w:rPr')

        for tag_name, value in (('color', '0000FF'), ('u', 'single')):
            existing = rpr_element.find(f'{self.w_ns}{tag_name}')
            if existing is not None:
                rpr_element.remove(existing)

            elem = OxmlElement(f'w:{tag_name}')
            elem.set(qn('w:val'), value)
            rpr_element.append(elem)

        return rpr_element

    def _toggle_boolean_format(self, rpr, tag_name: str, value: bool, attr_value: str = '1'):
        """
        Toggle boolean format properties (bold, italic, underline, strikethrough, all_caps)

        Args:
            rpr: Run properties element
            tag_name: XML tag name (e.g., 'b', 'i', 'u', 'strike', 'caps')
            value: True to set, False to remove
            attr_value: Value to set when True (default '1', but 'single' for underline)
        """
        elem = rpr.find(f'{self.w_ns}{tag_name}')
        if value:
            if elem is None:
                elem = rpr.makeelement(f'{self.w_ns}{tag_name}')
                rpr.append(elem)
            elem.set(f'{self.w_ns}val', attr_value)
        else:
            if elem is not None:
                rpr.remove(elem)

    def _apply_format_to_run(
        self,
        run,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        subscript: bool = None,
        superscript: bool = None,
        color: str = None,
        highlight: str = None,
        font_name: str = None,
        font_size: int = None,
        all_caps: bool = None
    ):
        """Apply formatting to a run - handles removing format when set to False"""
        rpr = run._r.get_or_add_rPr()

        # Handle boolean formats
        self._handle_boolean_formats(bold, italic, underline, strikethrough, all_caps, rpr=rpr)

        # Handle vertical alignment (subscript/superscript) - mutually exclusive
        # Determine desired value: subscript wins if both True, otherwise remove
        valignment = None
        if subscript and not superscript:
            valignment = 'subscript'
        elif superscript and not subscript:
            valignment = 'superscript'

        # Always remove existing first, then add new if needed
        existing = rpr.find(f'{self.w_ns}vertAlign')
        if existing is not None:
            rpr.remove(existing)

        if valignment:
            elem = rpr.makeelement(f'{self.w_ns}vertAlign')
            elem.set(f'{self.w_ns}val', valignment)
            rpr.append(elem)

        # Handle color (frontend always sends hex: #RRGGBB)
        if color:
            color_elem = rpr.find(f'{self.w_ns}color')
            if color_elem is None:
                color_elem = rpr.makeelement(f'{self.w_ns}color')
                rpr.append(color_elem)
            # Strip # and convert to uppercase for DOCX format
            color_hex = color.lstrip('#').upper()
            color_elem.set(f'{self.w_ns}val', color_hex)

        # Handle highlight (skip white/transparent as it means "no highlight")
        if highlight and highlight.lower() != '#ffffff' and highlight.lower() != '#fff':
            shd_elem = rpr.find(f'{self.w_ns}shd')
            if shd_elem is None:
                shd_elem = rpr.makeelement(f'{self.w_ns}shd')
                rpr.append(shd_elem)
            shd_elem.set(f'{self.w_ns}fill', highlight.lstrip('#').upper())
        elif not highlight or highlight.lower() in ['#ffffff', '#fff']:
            # Remove highlight if explicitly set to white/none
            shd_elem = rpr.find(f'{self.w_ns}shd')
            if shd_elem is not None:
                rpr.remove(shd_elem)

        # Handle font name
        if font_name:
            rfonts_elem = rpr.find(f'{self.w_ns}rFonts')
            if rfonts_elem is None:
                rfonts_elem = rpr.makeelement(f'{self.w_ns}rFonts')
                rpr.append(rfonts_elem)
            rfonts_elem.set(f'{self.w_ns}ascii', font_name)
            rfonts_elem.set(f'{self.w_ns}hAnsi', font_name)

        # Handle font size
        if font_size:
            sz_elem = rpr.find(f'{self.w_ns}sz')
            if sz_elem is None:
                sz_elem = rpr.makeelement(f'{self.w_ns}sz')
                rpr.append(sz_elem)
            sz_elem.set(f'{self.w_ns}val', str(font_size * 2))  # Stored in half-points

    def _restore_paragraph_formatting(self, paragraph, alignment, paragraph_format):
        """Restore paragraph-level formatting after splitting runs"""
        if alignment is not None:
            paragraph.alignment = alignment

        # Restore all paragraph properties if not None
        props_to_restore = [
            ('space_before', paragraph_format.space_before),
            ('space_after', paragraph_format.space_after),
            ('line_spacing', paragraph_format.line_spacing),
            ('first_line_indent', paragraph_format.first_line_indent),
            ('left_indent', paragraph_format.left_indent),
            ('right_indent', paragraph_format.right_indent)
        ]

        for prop_name, value in props_to_restore:
            if value is not None:
                setattr(paragraph.paragraph_format, prop_name, value)

    def apply_paragraph_formatting(
        self,
        paragraph_index: int,
        line_spacing: float = None,
        space_before: int = None,
        space_after: int = None,
        first_line_indent: int = None,
        alignment: str = None
    ):
        """
        Apply paragraph-level formatting to a specific paragraph

        Args:
            paragraph_index: Index of paragraph to format
            line_spacing: Line spacing (single=1.0, double=2.0, 1.5=1.5)
            space_before: Space before paragraph in points
            space_after: Space after paragraph in points
            first_line_indent: First line indent in points
            alignment: "left", "center", "right", "justify"

        Returns:
            True if found and formatted, False otherwise
        """
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx != paragraph_index:
                continue

            # Apply alignment
            if alignment:
                alignment_value = ALIGNMENT_STRING_TO_ENUM.get(alignment)
                if alignment_value is not None:
                    paragraph.alignment = alignment_value

            # Apply line spacing
            if line_spacing is not None:
                paragraph.paragraph_format.line_spacing = line_spacing

            # Apply space before
            if space_before is not None:
                paragraph.paragraph_format.space_before = Pt(space_before)

            # Apply space after
            if space_after is not None:
                paragraph.paragraph_format.space_after = Pt(space_after)

            # Apply first line indent
            if first_line_indent is not None:
                paragraph.paragraph_format.first_line_indent = Pt(first_line_indent)

            return True

        return False

    # ===== DELETE CONTENT =====

    def _copy_run_formatting(self, source_run, target_run):
        """
        Copy run-level formatting from source run to target run.

        Copies: font name, size, bold, italic, underline, color, etc.

        Args:
            source_run: Run to copy formatting from
            target_run: Run to apply formatting to
        """
        try:
            # Copy font properties
            if source_run.font.name:
                target_run.font.name = source_run.font.name

            if source_run.font.size:
                target_run.font.size = source_run.font.size

            target_run.font.bold = source_run.font.bold
            target_run.font.italic = source_run.font.italic
            target_run.font.underline = source_run.font.underline

            if source_run.font.color and source_run.font.color.rgb:
                target_run.font.color.rgb = source_run.font.color.rgb

            if source_run.font.highlight_color:
                target_run.font.highlight_color = source_run.font.highlight_color

            # Copy other font properties
            if source_run.font.strike:
                target_run.font.strike = source_run.font.strike
            if source_run.font.double_strike:
                target_run.font.double_strike = source_run.font.double_strike
            if source_run.font.subscript:
                target_run.font.subscript = source_run.font.subscript
            if source_run.font.superscript:
                target_run.font.superscript = source_run.font.superscript

            print(f"[DEBUG] Copied run formatting: font={source_run.font.name}, size={source_run.font.size}, bold={source_run.font.bold}")
        except Exception as e:
            print(f"[DEBUG] Error copying run formatting: {e}")

    def _copy_paragraph_format(self, source, target):
        """Copy paragraph-level formatting from source to target."""
        target.alignment = source.alignment
        target.paragraph_format.space_before = source.paragraph_format.space_before
        target.paragraph_format.space_after = source.paragraph_format.space_after
        target.paragraph_format.line_spacing = source.paragraph_format.line_spacing

    def delete_text_range(self, paragraph, start_offset: int, end_offset: int):
        """
        Xóa một phần của text trong paragraph dựa trên offset

        CRITICAL FIX: Now properly handles MERGEFIELD placeholders (fldSimple elements).
        When a placeholder is fully or partially within the delete range, it will be removed.

        Args:
            paragraph: Paragraph object cần xóa text
            start_offset: Vị trí bắt đầu (character offset)
            end_offset: Vị trí kết thúc (character offset)

        Returns:
            True nếu thành công, False nếu thất bại
        """
        try:
            text_segments = self._collect_paragraph_text_segments(paragraph)

            full_text_before = "".join(seg['text'] for seg in text_segments)
            print(
                f"[DELETE_TEXT_RANGE] Request start={start_offset} end={end_offset} "
                f"paragraph='{full_text_before}'"
            )
            print(
                "[DELETE_TEXT_RANGE] Segments: "
                + str([
                    {
                        'text': seg['text'],
                        'is_field': seg['is_field'],
                        'field_name': seg.get('field_name'),
                        'start_pos': seg['start_pos'],
                        'end_pos': seg['end_pos']
                    }
                    for seg in text_segments
                ])
            )

            # Find which segments intersect with delete range
            segments_to_delete = []
            for seg in text_segments:
                # Check if this segment intersects with delete range
                if seg['end_pos'] > start_offset and seg['start_pos'] < end_offset:
                    segments_to_delete.append(seg)

            if not segments_to_delete:
                return False

            # Process segments to delete
            deleted_any = False

            for seg in segments_to_delete:
                if seg['is_field']:
                    # This is a MERGEFIELD placeholder - remove it completely
                    # We can't partially delete a placeholder, so if any part of it is in range, remove all
                    element = seg['element']
                    parent = element.getparent()
                    if parent is not None:
                        parent.remove(element)
                        deleted_any = True
                        print(f"[DELETE_TEXT_RANGE] Removed placeholder '{seg['field_name']}' at offset {seg['start_pos']}-{seg['end_pos']}")
                else:
                    # This is a regular run - modify its text
                    if self._modify_segment_text(seg, "replace", text="", start_idx=start_offset, end_idx=end_offset):
                        deleted_any = True

            # Clean up empty runs after deletion
            if deleted_any:
                self._remove_empty_runs(paragraph)
                full_text_after, _ = self._extract_paragraph_full_text(paragraph)
                print(f"[DELETE_TEXT_RANGE] Result paragraph='{full_text_after}'")

            return deleted_any

        except Exception as e:
            print(f"Error deleting text range: {e}")
            import traceback
            traceback.print_exc()
            return False

    def delete_paragraph(self, paragraph):
        """
        Xóa hoàn toàn một paragraph khỏi document

        Args:
            paragraph: Paragraph object cần xóa

        Returns:
            True nếu thành công, False nếu thất bại
        """
        try:
            # Lấy paragraph element
            p_element = paragraph._element
            parent = p_element.getparent()

            if parent is not None:
                # Xóa paragraph element khỏi parent
                parent.remove(p_element)
                return True

            return False
        except Exception as e:
            print(f"Error deleting paragraph: {e}")
            return False

    def delete_placeholder(self, field_name: str) -> bool:
        """
        Xóa hoàn toàn placeholder KHÔNG restore text gốc

        Đây là TRUE DELETION - xóa cả field MERGEFIELD và wrapper runs.

        Args:
            field_name: Tên placeholder cần xóa (ví dụ: "ho_ten", "dia_chi")

        Returns:
            True nếu xóa thành công, False nếu không tìm thấy placeholder
        """
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        deleted = False

        try:
            # Tìm tất cả MERGEFIELD với tên cần xóa
            for fld in self.doc.element.iter(f"{w_ns}fldSimple"):
                instr = fld.get(f"{w_ns}instr", "")

                # Check nếu đây là MERGEFIELD với tên cần xóa
                # Pattern: MERGEFIELD field_name \* MERGEFORMAT \z "original_text"
                match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                if match and match.group(1) == field_name:
                    # Lấy parent element (paragraph hoặc table cell)
                    parent = fld.getparent()

                    if parent is not None:
                        # Xóa hoàn toàn field (KHÔNG restore từ \z)
                        parent.remove(fld)
                        deleted = True
                        print(f"[DELETE] Removed placeholder '{field_name}' completely")

            if deleted:
                # Clean up empty runs left behind after field deletion
                # Điều này đảm bảo không có runs rỗng gây lỗi DOCX
                for para in self._iterate_paragraphs_in_doc_order():
                    self._remove_empty_runs(para)

                print(f"[SUCCESS] Placeholder '{field_name}' deleted successfully")
            else:
                print(f"[WARNING] Placeholder '{field_name}' not found in document")

            return deleted

        except Exception as e:
            print(f"[ERROR] Failed to delete placeholder '{field_name}': {e}")
            return False

    def rename_placeholder(self, old_name: str, new_name: str) -> bool:
        """
        Đổi tên placeholder (MERGEFIELD)

        Args:
            old_name: Tên placeholder cũ
            new_name: Tên placeholder mới

        Returns:
            True nếu thành công, False nếu thất bại
        """
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        renamed = False

        try:
            for fld in self.doc.element.iter(f"{w_ns}fldSimple"):
                instr = fld.get(f"{w_ns}instr", "")
                match = re.search(r'MERGEFIELD\s+(\S+)', instr)

                if match and match.group(1) == old_name:
                    # Giữ nguyên phần \z "original_text"
                    z_match = re.search(r'\\z\s*"([^"]*)"', instr)
                    z_part = f' \\z "{z_match.group(1)}"' if z_match else ""

                    # Update instruction với tên mới
                    new_instr = f' MERGEFIELD {new_name} \\* MERGEFORMAT{z_part} '
                    fld.set(f"{w_ns}instr", new_instr)

                    # Update display text
                    for t in fld.iter(f"{w_ns}t"):
                        t.text = f"«{new_name}»"

                    renamed = True
                    print(f"[RENAME] '{old_name}' → '{new_name}'")

            return renamed

        except Exception as e:
            print(f"[ERROR] Failed to rename placeholder '{old_name}': {e}")
            return False

    def insert_paragraph(self, target_paragraph, text: str = "", position: str = "after"):
        """
        Thêm paragraph mới trước hoặc sau một paragraph cụ thể

        Args:
            target_paragraph: Paragraph object để thêm mới
            text: Nội dung text cho paragraph mới
            position: "after" (sau) hoặc "before" (trước)

        Returns:
            Paragraph object mới được tạo
        """
        if position not in ("after", "before"):
            raise ValueError('position phải là "after" hoặc "before"')

        print(f"[DEBUG] insert_paragraph called: position={position}, text={repr(text[:50])}")

        # Lấy paragraph element
        target_p_element = target_paragraph._p
        parent = target_p_element.getparent()

        # Tạo new paragraph element
        new_p = OxmlElement('w:p')

        # Copy paragraph properties từ target paragraph (indentation, alignment, etc.)
        pPr = target_p_element.find(f"{self.w_ns}pPr")
        if pPr is not None:
            new_p.append(copy.deepcopy(pPr))
            print(f"[DEBUG] Copied paragraph properties from target")

        # Copy run properties (rPr) from target paragraph if it has runs
        source_run_props = None
        if target_paragraph.runs:
            # Find the last non-empty run to copy formatting from
            for run in reversed(target_paragraph.runs):
                if run.text and run.text.strip():
                    run_element = run._element
                    rPr = run_element.find(f"{self.w_ns}rPr")
                    if rPr is not None:
                        source_run_props = rPr
                        print(f"[DEBUG] Found source run properties: font={run.font.name}, size={run.font.size}")
                    break

        # TẠO RUN LUÔN - kể cả khi text rỗng (quan trọng!)
        # Phải tạo run với formatting ngay từ đầu để khi thêm text sau sẽ kế thừa đúng
        new_r = OxmlElement('w:r')

        # Copy run properties if available
        if source_run_props is not None:
            new_r.append(copy.deepcopy(source_run_props))
            print(f"[DEBUG] Copied run properties to new run")
        else:
            print(f"[DEBUG] No source run props found, using default")

        # Tạo text element - có thể rỗng
        new_t = OxmlElement('w:t')
        new_t.set(qn('xml:space'), 'preserve')
        new_t.text = text
        new_r.append(new_t)
        new_p.append(new_r)

        # Insert tại vị trí phù hợp
        parent_index = list(parent).index(target_p_element)
        insert_index = parent_index + 1 if position == "after" else parent_index
        parent.insert(insert_index, new_p)

        # Convert to Paragraph object
        from docx.text.paragraph import Paragraph
        new_para = Paragraph(new_p, self.doc)

        print(f"[DEBUG] New paragraph inserted {position} target")
        return new_para

    def insert_paragraph_after(self, target_paragraph, text: str = ""):
        """
        Wrapper: Thêm paragraph mới sau một paragraph cụ thể
        """
        return self.insert_paragraph(target_paragraph, text, "after")

    def insert_paragraph_before(self, target_paragraph, text: str = ""):
        """
        Wrapper: Thêm paragraph mới trước một paragraph cụ thể
        """
        return self.insert_paragraph(target_paragraph, text, "before")

    def add_paragraph_in_table_cell(
        self,
        table_index: int,
        row_index: int,
        col_index: int,
        text: str = "",
        after_para_index: int = None
    ):
        """
        Thêm paragraph mới vào table cell.
        Dùng chung logic với insert_paragraph().

        Args:
            table_index: Index của table
            row_index: Row index trong table
            col_index: Column index trong table
            text: Nội dung text cho paragraph mới
            after_para_index: Thêm sau paragraph index nào trong cell (None = thêm cuối)

        Returns:
            True nếu thành công, False nếu thất bại
        """
        print(f"[DEBUG] add_paragraph_in_table_cell called: table={table_index}, row={row_index}, col={col_index}, text={repr(text[:50])}")

        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if row_index >= len(table.rows):
            return False

        row = table.rows[row_index]
        if col_index >= len(row.cells):
            return False

        cell = row.cells[col_index]

        try:
            # Tìm target paragraph
            if after_para_index is not None and after_para_index < len(cell.paragraphs):
                target_para = cell.paragraphs[after_para_index]
            else:
                # Thêm cuối cell = thêm sau paragraph cuối cùng
                if not cell.paragraphs:
                    # Cell rỗng, tạo paragraph đầu tiên
                    if text:
                        cell.add_paragraph(text)
                    else:
                        cell.add_paragraph()
                    return True
                target_para = cell.paragraphs[-1]

            # Dùng chung logic với insert_paragraph
            self.insert_paragraph(target_para, text, "after")
            return True

        except Exception as e:
            print(f"Error adding paragraph in table cell: {e}")
            return False

    def insert_placeholder_at_offset(
        self,
        paragraph_index: int,
        offset: int,
        field_name: str,
        inherit_format: bool = True
    ):
        """
        Insert placeholder at specific character offset within paragraph
        Splits runs at offset and inserts placeholder using MERGEFIELD structure

        Args:
            paragraph_index: Index of paragraph (from all paragraphs iterator)
            offset: Character offset within paragraph text
            field_name: Name for the merge field
            inherit_format: Whether to inherit format from surrounding text

        Returns:
            True if successful

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If operation fails
        """
        if paragraph_index < 0:
            raise ValueError(f"Invalid paragraph_index: {paragraph_index} (must be >= 0)")
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset} (must be >= 0)")
        if not field_name or not field_name.strip():
            raise ValueError("Field name cannot be empty")

        target_para = self._find_paragraph_by_index(paragraph_index)
        if not target_para:
            total_paragraphs = sum(1 for _ in self._iterate_paragraphs_in_doc_order())
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        run_text_map = self._build_run_text_map(target_para)
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)
        target_run_info = self._find_run_at_offset(run_text_map, offset)

        # Handle empty paragraph
        if not target_run_info:
            if total_text_length == 0:
                p_element = target_para._p
                return self._insert_placeholder_to_empty_paragraph(target_para, p_element, field_name, paragraph_index)
            para_preview = target_para.text[:50] + "..." if len(target_para.text) > 50 else target_para.text
            raise RuntimeError(
                f"Offset {offset} not found in paragraph {paragraph_index}. "
                f"Paragraph text length: {total_text_length}, "
                f"Valid range: 0-{total_text_length}, "
                f"Text preview: '{para_preview}'"
            )

        # Normal case: split run and insert placeholder
        target_run = target_run_info['run']
        text_before, text_after = self._split_run_at_offset(target_run, offset, target_run_info['start'])
        placeholder_text = f"«{field_name}»"

        p_element = target_para._p
        run_element = target_run._element
        insert_index = list(p_element).index(run_element)
        paragraph_alignment = target_para.alignment

        # Get format: prefer target run, or previous non-placeholder run if text_before is empty
        original_rpr = target_run._r.get_or_add_rPr()
        if (not text_before or not text_before.strip()) and inherit_format:
            prev_rpr = self._get_format_from_previous_run(run_text_map, target_run)
            if prev_rpr is not None:
                original_rpr = prev_rpr

        # Remove original run and insert new structure
        target_run.text = ""
        p_element.remove(run_element)

        try:
            if text_before:
                new_run = self._create_run_with_format(target_para, original_rpr, text_before)
                p_element.insert(insert_index, new_run._element)
                insert_index += 1

            placeholder_run = self._create_run_with_format(target_para, original_rpr, placeholder_text)
            fld = OxmlElement('w:fldSimple')
            fld.set(qn('w:instr'), f' MERGEFIELD {field_name} \\* MERGEFORMAT \\z "" ')
            fld.append(placeholder_run._element)
            p_element.insert(insert_index, fld)
            insert_index += 1

            if text_after:
                new_run = self._create_run_with_format(target_para, original_rpr, text_after)
                p_element.insert(insert_index, new_run._element)

            if paragraph_alignment is not None:
                target_para.alignment = paragraph_alignment

        except Exception as e:
            raise RuntimeError(
                f"Failed to insert placeholder structure at offset {offset}: {type(e).__name__}: {str(e)}"
            )

        return True

    def add_table_at_cursor(
        self,
        paragraph_index: int,
        offset: int,
        rows: int,
        cols: int
    ):
        """
        Insert table at exact cursor position within paragraph

        Strategy:
        1. Split paragraph at offset → 2 parts
        2. Insert table between parts
        3. Text after offset → new paragraph after table

        Args:
            paragraph_index: Index of paragraph (from all paragraphs iterator)
            offset: Character offset within paragraph text
            rows: Number of rows for new table
            cols: Number of columns for new table

        Returns:
            True if successful

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If operation fails
        """

        # Validate inputs
        if paragraph_index < 0:
            raise ValueError(f"Invalid paragraph_index: {paragraph_index} (must be >= 0)")
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset} (must be >= 0)")
        if rows < 1 or rows > 20:
            raise ValueError(f"Invalid rows: {rows} (must be 1-20)")
        if cols < 1 or cols > 10:
            raise ValueError(f"Invalid cols: {cols} (must be 1-10)")

        target_para = self._find_paragraph_by_index(paragraph_index)
        if not target_para:
            total_paragraphs = sum(1 for _ in self._iterate_paragraphs_in_doc_order())
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        run_text_map = self._build_run_text_map(target_para)
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)
        target_run_info = self._find_run_at_offset(run_text_map, offset)

        # Special case: Empty paragraph
        if total_text_length == 0:
            if offset != 0:
                print(f"[WARN] Offset {offset} requested for empty paragraph {paragraph_index}. Using offset 0 instead.")
                offset = 0

            if len(target_para.runs) == 0:
                new_run = target_para.add_run("")
                target_run_info = {'run': new_run, 'start': 0, 'end': 0, 'text': ''}
            else:
                target_run_info = {
                    'run': target_para.runs[0],
                    'start': 0,
                    'end': 0,
                    'text': target_para.runs[0].text or ''
                }

        if not target_run_info:
            para_preview = target_para.text[:50] + "..." if len(target_para.text) > 50 else target_para.text
            raise RuntimeError(
                f"Offset {offset} not found in paragraph {paragraph_index}. "
                f"Paragraph text length: {total_text_length}, "
                f"Valid range: 0-{total_text_length}, "
                f"Text preview: '{para_preview}'"
            )

        target_run = target_run_info['run']
        original_rpr = target_run._r.get_or_add_rPr()
        text_before, text_after = self._split_run_at_offset(target_run, offset, target_run_info['start'])

        # Update original run to only contain text_before
        target_run.text = text_before

        # Create table with simple borders
        table = self.doc.add_table(rows=rows, cols=cols)
        self._format_simple_table(table)

        # Get paragraph element and its parent
        p_element = target_para._p
        parent = p_element.getparent()

        # Find the index of the paragraph element in parent
        para_index_in_parent = list(parent).index(p_element)

        # Get the table element we just created
        table_element = table._element

        # Insert table element after the paragraph
        parent.insert(para_index_in_parent + 1, table_element)

        # Create new paragraph for text_after (AFTER table)
        if text_after.strip():
            new_p = OxmlElement('w:p')

            # Copy paragraph properties from target paragraph
            pPr = p_element.find(f"{self.w_ns}pPr")
            if pPr is not None:
                new_p.append(copy.deepcopy(pPr))

            # Create run with text_after, preserving original formatting
            new_r = OxmlElement('w:r')
            new_rPr = new_r.find(f"{self.w_ns}rPr")
            if new_rPr is None:
                new_rPr = OxmlElement('w:rPr')
                new_r.append(new_rPr)

            # Copy run properties from original run
            if original_rpr is not None:
                new_rPr.append(copy.deepcopy(original_rpr))

            # Create text element
            new_t = OxmlElement('w:t')
            new_t.set(qn('xml:space'), 'preserve')
            new_t.text = text_after
            new_r.append(new_t)
            new_p.append(new_r)

            # Insert new paragraph after table
            # Find table element index again (it may have shifted)
            table_index_in_parent = list(parent).index(table_element)
            parent.insert(table_index_in_parent + 1, new_p)

        # Clean up empty runs
        self._remove_empty_runs(target_para)

        # IMPORTANT: Invalidate block index map to force rebuild
        # This ensures the new table will be included in HTML preview
        self._block_to_para_index_map = None

        return True

    def _format_simple_table(self, table):
        """
        Apply simple border formatting to table

        Args:
            table: docx table object
        """

        # Set table borders
        tbl_pr = table._element.tblPr
        if tbl_pr is None:
            tbl_pr = OxmlElement('w:tblPr')
            table._element.insert(0, tbl_pr)

        tbl_borders = OxmlElement('w:tblBorders')

        for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')  # 4 half-points = 2pt
            border.set(qn('w:space'), '0')
            border.set(qn('w:color'), '000000')
            tbl_borders.append(border)

        tbl_pr.append(tbl_borders)

        # Set table width to full page width (6.5 inches = standard A4 width)
        table.width = Inches(6.5)

        # Distribute column widths evenly across table width
        # Each column gets equal share of table width
        num_cols = len(table.columns)
        if num_cols > 0:
            column_width = Inches(6.5) / num_cols
            for row in table.rows:
                for cell in row.cells:
                    # Set each cell to equal column width
                    cell.width = column_width

    def _remove_empty_runs(self, paragraph):
        """
        Remove empty runs from paragraph

        Args:
            paragraph: docx paragraph object
        """
        p_element = paragraph._p
        runs_to_remove = []

        for run in paragraph.runs:
            if not run.text or not run.text.strip():
                runs_to_remove.append(run)

        for run in runs_to_remove:
            run_element = run._element
            run_element.getparent().remove(run_element)

    def add_page_break_at_cursor(self, block_index: int, offset: int):
        """
        Thêm ngắt trang TẠI VỊ TRÍ CURSOR (split paragraph tại offset)

        Args:
            block_index: Block index từ HTML preview
            offset: Character offset trong paragraph (đã loại placeholders)

        Returns:
            True nếu thành công, False nếu thất bại
        """
        self._build_block_index_map()

        if block_index not in self._block_to_para_index_map:
            print(f"[ERROR] Block index {block_index} not found in map")
            return False

        block_info = self._block_to_para_index_map[block_index]
        if block_info['type'] != 'paragraph':
            print(f"[ERROR] Block {block_index} is not a paragraph")
            return False

        source_para = block_info['paragraph']
        source_element = source_para._element

        # Get plain text and validate offset
        plain_text = source_para.text
        if offset < 0 or offset > len(plain_text):
            print(f"[ERROR] Offset {offset} out of range [0, {len(plain_text)}]")
            return False

        # Special case: offset at beginning
        if offset == 0:
            break_para = self.doc.add_paragraph()
            break_para.add_run().add_break(WD_BREAK.PAGE)
            source_element.addprevious(break_para._element)
            self._block_to_para_index_map = None
            self._build_block_index_map()
            return True

        # Special case: offset at end
        if offset >= len(plain_text):
            source_para.add_run().add_break(WD_BREAK.PAGE)
            self._block_to_para_index_map = None
            self._build_block_index_map()
            return True

        # Split paragraph at offset (reuse helper functions like add_table_at_cursor)
        run_text_map = self._build_run_text_map(source_para)
        target_run_info = self._find_run_at_offset(run_text_map, offset)

        if not target_run_info:
            print(f"[ERROR] Could not find run at offset {offset}")
            return False

        target_run = target_run_info['run']
        text_before, text_after = self._split_run_at_offset(
            target_run, offset, target_run_info['start']
        )

        # Update original run to only contain text_before
        target_run.text = text_before

        # Create after paragraph for text_after (deep copy to preserve formatting)
        after_para_element = copy.deepcopy(source_element)
        after_para = Paragraph(after_para_element, self.doc)

        # Clear runs in after paragraph and rebuild
        for run in after_para.runs:
            run._element.getparent().remove(run._element)

        # Add text_after to after paragraph
        if text_after:
            new_run = after_para.add_run(text_after)
            self._copy_run_formatting(target_run, new_run)

        # Add remaining runs from source paragraph
        run_index = next(i for i, r in enumerate(source_para.runs) if r._element == target_run._element)
        for i in range(run_index + 1, len(source_para.runs)):
            original_run = source_para.runs[i]
            new_run = after_para.add_run(original_run.text)
            self._copy_run_formatting(original_run, new_run)

        # Remove remaining runs from source paragraph
        for run in list(source_para.runs)[run_index + 1:]:
            run._element.getparent().remove(run._element)

        # Insert page break and after paragraph
        source_para.add_run().add_break(WD_BREAK.PAGE)
        source_element.addnext(after_para_element)

        # Rebuild block index map after modifying document structure
        self._block_to_para_index_map = None
        self._build_block_index_map()

        return True

    def add_image_at_cursor(
        self,
        paragraph_index: int,
        offset: int,
        image_path: str,
        width: float = 4.0
    ):
        """
        Insert image at exact cursor position within paragraph

        Strategy:
        1. Find paragraph and run containing offset
        2. Split run at offset
        3. Insert image between text parts
        4. Text after offset → new paragraph after image

        Args:
            paragraph_index: Index of paragraph (from all paragraphs iterator)
            offset: Character offset within paragraph text
            image_path: Path to image file
            width: Image width in inches

        Returns:
            True if successful

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If operation fails
        """

        # Validate inputs
        if paragraph_index < 0:
            raise ValueError(f"Invalid paragraph_index: {paragraph_index} (must be >= 0)")
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset} (must be >= 0)")
        if not image_path or not Path(image_path).exists():
            raise ValueError(f"Image file not found: {image_path}")
        if width < 1.0 or width > 8.0:
            raise ValueError(f"Invalid width: {width} (must be 1.0-8.0 inches)")

        # Reuse helper functions (same as add_table_at_cursor)
        target_para = self._find_paragraph_by_index(paragraph_index)
        if not target_para:
            total_paragraphs = sum(1 for _ in self._iterate_paragraphs_in_doc_order())
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        run_text_map = self._build_run_text_map(target_para)
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)
        target_run_info = self._find_run_at_offset(run_text_map, offset)

        # Special case: Empty paragraph (same logic as add_table_at_cursor)
        if total_text_length == 0:
            if offset != 0:
                print(f"[WARN] Offset {offset} requested for empty paragraph {paragraph_index}. Using offset 0 instead.")
                offset = 0

            if len(target_para.runs) == 0:
                new_run = target_para.add_run("")
                target_run_info = {'run': new_run, 'start': 0, 'end': 0, 'text': ''}
            else:
                target_run_info = {
                    'run': target_para.runs[0],
                    'start': 0,
                    'end': 0,
                    'text': target_para.runs[0].text or ''
                }

        if not target_run_info:
            para_preview = target_para.text[:50] + "..." if len(target_para.text) > 50 else target_para.text
            raise RuntimeError(
                f"Offset {offset} not found in paragraph {paragraph_index}. "
                f"Paragraph text length: {total_text_length}, "
                f"Valid range: 0-{total_text_length}, "
                f"Text preview: '{para_preview}'"
            )

        target_run = target_run_info['run']
        original_rpr = target_run._r.get_or_add_rPr()
        text_before, text_after = self._split_run_at_offset(target_run, offset, target_run_info['start'])
        target_run.text = text_before

        # Find the document body
        doc_element = self.doc._element.body
        p_element = target_para._p

        # Find the index of the paragraph element in body
        para_index_in_doc = list(doc_element).index(p_element)

        # Create new paragraph for image (AFTER target paragraph)
        image_paragraph = self.doc.add_paragraph()
        self._copy_paragraph_format(target_para, image_paragraph)

        # Add picture to the new paragraph
        try:
            image_run = image_paragraph.add_run()
            image_run.add_picture(image_path, width=Inches(width))

            # Copy run formatting from target paragraph if available
            source_run = next((r for r in target_para.runs if r.text and r.text.strip()), target_para.runs[0] if target_para.runs else None)
            if source_run:
                for run in image_paragraph.runs:
                    if run != image_run:
                        self._copy_run_formatting(source_run, run)
        except Exception as e:
            # Clean up - remove the paragraph we just added
            image_p_element = image_paragraph._element
            image_p_element.getparent().remove(image_p_element)
            raise RuntimeError(f"Failed to insert image: {str(e)}")

        # Move the image paragraph to right after target paragraph
        image_p_element = image_paragraph._element
        doc_element.remove(image_p_element)
        doc_element.insert(para_index_in_doc + 1, image_p_element)

        # Create new paragraph for text_after (AFTER image paragraph)
        if text_after.strip():
            text_paragraph = self.doc.add_paragraph()
            self._copy_paragraph_format(target_para, text_paragraph)
            new_run = text_paragraph.add_run(text_after)

            # Copy formatting from original run
            if original_rpr is not None:
                new_run._element.get_or_add_rPr()
                new_run._element.rPr.append(copy.deepcopy(original_rpr))

            # Move the text paragraph to right after image paragraph
            text_p_element = text_paragraph._element
            doc_element.remove(text_p_element)

            # Find image paragraph index again (it may have shifted)
            image_p_index = list(doc_element).index(image_p_element)
            doc_element.insert(image_p_index + 1, text_p_element)

        # Clean up empty runs
        self._remove_empty_runs(target_para)

        # IMPORTANT: Invalidate block index map to force rebuild
        self._block_to_para_index_map = None

        return True

    # ===== TABLE EDITING =====

    def delete_table_row(self, table_index: int, row_index: int):
        """Xóa row khỏi table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if row_index >= len(table.rows) or row_index < 0:
            return False

        # Không cho xóa row cuối cùng (table phải có ít nhất 1 row)
        if len(table.rows) <= 1:
            return False

        # Xóa row bằng cách lấy element và remove
        table_element = table._element
        row_element = table.rows[row_index]._element
        table_element.remove(row_element)
        return True

    def insert_table_row(self, table_index: int, row_index: int):
        """Chèn row mới vào vị trí cụ thể trong table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if row_index < 0 or row_index > len(table.rows):
            return False

        # Thêm row ở cuối trước
        new_row = table.add_row()

        # Nếu row_index không phải là cuối cùng, di chuyển row đến vị trí đúng
        if row_index < len(table.rows) - 1:
            row_element = new_row._element
            target_row_element = table.rows[row_index]._element
            target_row_element.addprevious(row_element)

        return True

    def delete_table_column(self, table_index: int, col_index: int):
        """Xóa column khỏi table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if col_index < 0:
            return False

        # Kiểm tra column có tồn tại
        if len(table.rows) > 0 and col_index >= len(table.rows[0].cells):
            return False

        # Không cho xóa column cuối cùng (table phải có ít nhất 1 column)
        if len(table.rows) > 0 and len(table.rows[0].cells) <= 1:
            return False

        # Xóa từng cell trong column VÀ update table grid
        for row in table.rows:
            if col_index < len(row.cells):
                cell_element = row.cells[col_index]._element
                cell_element.getparent().remove(cell_element)

        # Update table grid để remove gridCol tương ứng
        tbl = table._element
        tblGrid = tbl.find(qn('w:tblGrid'))

        if tblGrid is not None:
            gridCols = tblGrid.findall(qn('w:gridCol'))
            if col_index < len(gridCols):
                gridCol_to_remove = gridCols[col_index]
                tblGrid.remove(gridCol_to_remove)

        return True

    def insert_table_column(self, table_index: int, col_index: int):
        """Chèn column mới vào vị trí cụ thể trong table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if col_index < 0:
            return False

        # Kiểm tra column có tồn tại
        if len(table.rows) > 0 and col_index > len(table.rows[0].cells):
            return False

        # Python-docx không hỗ trợ trực tiếp add column
        # Cách giải quyết: tạo table mới với cấu trúc cập nhật

        # Lưu số columns cũ
        old_col_count = len(table.columns)
        new_col_count = old_col_count + 1

        # Thêm cell vào mỗi row
        for row in table.rows:
            # Tạo tc element (table cell)
            tc = OxmlElement('w:tc')

            # Tạo tcPr (table cell properties)
            tcPr = OxmlElement('w:tcPr')

            # Tạo tcW (table cell width) - auto width
            tcW = OxmlElement('w:tcW')
            tcW.set(qn('w:type'), 'auto')
            tcPr.append(tcW)

            # Tạo vAlign (vertical alignment) - center để text nằm giữa ô
            vAlign = OxmlElement('w:vAlign')
            vAlign.set(qn('w:val'), 'center')
            tcPr.append(vAlign)

            tc.append(tcPr)

            # Tạo multiple paragraphs để user có thể click vào từng dòng riêng lẻ
            # Tương tự như ô gốc có 6 paragraphs (1 text + 4 empty + 1 text)
            for para_idx in range(6):
                # Tạo p element (paragraph)
                p = OxmlElement('w:p')
                p.set(qn('w:rsidR'), '00D9489C')
                p.set(qn('w:rsidRDefault'), '00D9489C')

                # Tạo pPr (paragraph properties)
                pPr = OxmlElement('w:pPr')
                p.append(pPr)

                # Chỉ paragraph đầu tiên có Run/Text để có thể nhập liệu
                # Các paragraph khác để trống để user có thể click vào từng dòng
                if para_idx == 0:
                    # CRITICAL FIX: Tạo Run và Text node để ô có thể nhận nội dung
                    # Không có Run/Text → ô trống và không thể edit
                    r = OxmlElement('w:r')
                    t = OxmlElement('w:t')
                    t.set(qn('xml:space'), 'preserve')
                    t.text = ""  # Empty text initially, but can be filled later
                    r.append(t)
                    p.append(r)

                tc.append(p)

            # Chèn cell vào vị trí cụ thể
            if col_index >= len(row.cells):
                # Thêm vào cuối row
                row._element.append(tc)
            else:
                # Chèn trước cell tại col_index
                target_cell = row.cells[col_index]._element
                target_cell.addprevious(tc)

        # Update table grid để include column mới
        tbl = table._element
        tblGrid = tbl.find(qn('w:tblGrid'))

        if tblGrid is not None:
            # Tạo gridCol mới với auto width
            gridCol = OxmlElement('w:gridCol')
            gridCol.set(qn('w:w'), '2310')  # Default width

            # Chèn gridCol vào vị trí col_index
            if col_index >= len(tblGrid):
                tblGrid.append(gridCol)
            else:
                gridCols = tblGrid.findall(qn('w:gridCol'))
                if col_index < len(gridCols):
                    gridCols[col_index].addprevious(gridCol)
                else:
                    tblGrid.append(gridCol)

        return True

    # ===== CELL FORMATTING HELPERS =====

    def _validate_and_get_cell(self, table_index: int, row_index: int, col_index: int):
        """Validate indices and return cell. Returns None if invalid."""
        if table_index >= len(self.doc.tables):
            return None
        table = self.doc.tables[table_index]
        if row_index >= len(table.rows):
            return None
        row = table.rows[row_index]
        if col_index >= len(row.cells):
            return None
        return row.cells[col_index]

    def _word_border_to_format(self, border) -> Optional[dict]:
        """Convert a Word border element into the format payload used by the UI."""
        if border is None:
            return None

        border_val = border.get(qn('w:val'), 'single')
        if border_val in ['none', 'nil', '']:
            return {'style': 'none', 'size': 0, 'color': '#000000'}

        border_size_raw = border.get(qn('w:sz'), '4')
        try:
            border_size = int(border_size_raw)
        except (TypeError, ValueError):
            border_size = 4

        border_color = border.get(qn('w:color'), '000000')
        return {
            'style': border_val,
            'size': border_size,
            'color': f'#{border_color}' if border_color and not border_color.startswith('#') else border_color or '#000000'
        }

    def _get_table_borders(self, table_obj) -> dict:
        """Extract table-level borders from tblPr."""
        table_borders = {}
        try:
            tbl_pr = table_obj._element.find(qn('w:tblPr'))
            if tbl_pr is None:
                return table_borders

            tbl_borders = tbl_pr.find(qn('w:tblBorders'))
            if tbl_borders is None:
                return table_borders

            for side in ['top', 'bottom', 'left', 'right', 'insideH', 'insideV']:
                border = tbl_borders.find(qn(f'w:{side}'))
                if border is not None:
                    table_borders[side] = border
        except Exception as e:
            print(f"Error extracting table borders: {e}")

        return table_borders

    def _get_effective_border(self, tc_pr, table_borders, side, row_idx, col_idx, last_row_idx, last_col_idx):
        """Resolve effective border for one cell side."""
        tc_borders = tc_pr.find(qn('w:tcBorders')) if tc_pr is not None else None
        if tc_borders is not None:
            direct_border = tc_borders.find(qn(f'w:{side}'))
            direct_format = self._word_border_to_format(direct_border)
            if direct_format is not None:
                return direct_format

        # Fallback to table borders
        table_border = None
        if side == 'top':
            table_border = table_borders.get('top') if row_idx == 0 else table_borders.get('insideH')
        elif side == 'bottom':
            table_border = table_borders.get('bottom') if row_idx == last_row_idx else table_borders.get('insideH')
        elif side == 'left':
            table_border = table_borders.get('left') if col_idx == 0 else table_borders.get('insideV')
        elif side == 'right':
            table_border = table_borders.get('right') if col_idx == last_col_idx else table_borders.get('insideV')

        return self._word_border_to_format(table_border)

    def _get_default_cell_format(self) -> dict:
        """Return default cell format structure."""
        return {
            'background_color': '#ffffff',
            'vertical_align': 'top',
            'horizontal_align': 'left',
            'borders': {
                'top': {'style': 'none', 'size': 0, 'color': '#000000'},
                'bottom': {'style': 'none', 'size': 0, 'color': '#000000'},
                'left': {'style': 'none', 'size': 0, 'color': '#000000'},
                'right': {'style': 'none', 'size': 0, 'color': '#000000'}
            }
        }

    # ===== PUBLIC CELL FORMATTING METHODS =====

    def format_table_cell(
        self,
        table_index: int,
        row_index: int,
        col_index: int,
        format_options: dict
    ):
        """Format table cell (background color, vertical alignment, horizontal alignment, borders)

        Supports 9 alignment options (3 horizontal × 3 vertical):
        - Horizontal: left, center, right
        - Vertical: top, center, bottom
        """
        cell = self._validate_and_get_cell(table_index, row_index, col_index)
        if cell is None:
            return False

        try:
            tc_pr = cell._element.get_or_add_tcPr()

            # Background color
            if 'background_color' in format_options:
                bg_color = format_options['background_color']
                if bg_color and bg_color != 'auto':
                    shd = tc_pr.find(qn('w:shd'))
                    if shd is None:
                        shd = OxmlElement('w:shd')
                        tc_pr.append(shd)
                    shd.set(qn('w:fill'), bg_color.lstrip('#'))

            # Vertical alignment
            if 'vertical_align' in format_options:
                v_align = format_options['vertical_align']
                if v_align in ['top', 'center', 'bottom']:
                    v_align_element = tc_pr.find(qn('w:vAlign'))
                    if v_align_element is None:
                        v_align_element = OxmlElement('w:vAlign')
                        tc_pr.append(v_align_element)
                    v_align_element.set(qn('w:val'), v_align)

            # Horizontal alignment
            if 'horizontal_align' in format_options:
                h_align = format_options['horizontal_align']
                alignment_value = ALIGNMENT_STRING_TO_ENUM.get(h_align)
                if alignment_value is not None:
                    for para in cell.paragraphs:
                        para.alignment = alignment_value

            # Borders
            if 'borders' in format_options:
                self._apply_cell_borders(tc_pr, format_options['borders'])

            return True

        except Exception as e:
            print(f"Error formatting cell: {str(e)}")
            return False

    def _apply_cell_borders(self, tc_pr, borders: dict):
        """Apply borders to table cell.

        Supports styles: none (remove), single, double, dashed, dotted
        """
        tc_borders = tc_pr.find(qn('w:tcBorders'))
        if tc_borders is None:
            tc_borders = OxmlElement('w:tcBorders')
            tc_pr.append(tc_borders)

        for side in ['top', 'bottom', 'left', 'right']:
            if side not in borders:
                continue

            border_config = borders[side]
            border_style = border_config.get('style', 'single')

            # Remove border if style is "none"
            if border_style in ('none', ''):
                existing_border = tc_borders.find(qn(f'w:{side}'))
                if existing_border is not None:
                    tc_borders.remove(existing_border)
                continue

            # Create/update border element
            border = OxmlElement(f'w:{side}')
            border.set(qn('w:val'), border_style)
            border.set(qn('w:sz'), str(border_config.get('size', 4)))
            border.set(qn('w:color'), border_config.get('color', 'auto').lstrip('#'))

            existing_border = tc_borders.find(qn(f'w:{side}'))
            if existing_border is not None:
                tc_borders.replace(existing_border, border)
            else:
                tc_borders.append(border)

    def get_cell_format(self, table_index: int, row_index: int, col_index: int) -> dict:
        """Get current formatting of a table cell.

        Returns:
            dict with keys: background_color, vertical_align, horizontal_align, borders
        """
        cell = self._validate_and_get_cell(table_index, row_index, col_index)
        if cell is None:
            return None

        table = self.doc.tables[table_index]
        format_info = self._get_default_cell_format()

        try:
            tc_pr = cell._element.find(qn('w:tcPr'))
            if tc_pr is not None:
                # Background color from shd element
                shd = tc_pr.find(qn('w:shd'))
                if shd is not None:
                    fill = shd.get(qn('w:fill'))
                    if fill and fill != 'auto':
                        format_info['background_color'] = f'#{fill}' if fill and not fill.startswith('#') else fill or '#000000'

                # Vertical alignment from vAlign element
                v_align = tc_pr.find(qn('w:vAlign'))
                if v_align is not None:
                    v_align_val = v_align.get(qn('w:val'), 'top')
                    if v_align_val in ['top', 'center', 'bottom']:
                        format_info['vertical_align'] = v_align_val

                # Resolve borders
                table_borders = self._get_table_borders(table)
                last_row_idx = len(table.rows) - 1
                last_col_idx = len(table.columns) - 1

                for side in ['top', 'bottom', 'left', 'right']:
                    effective_border = self._get_effective_border(
                        tc_pr, table_borders, side,
                        row_index, col_index, last_row_idx, last_col_idx
                    )
                    if effective_border is not None:
                        format_info['borders'][side] = effective_border

            # Horizontal alignment from first paragraph (paragraph property, not cell)
            if cell.paragraphs:
                first_para = cell.paragraphs[0]
                if first_para.alignment is not None:
                    format_info['horizontal_align'] = ALIGNMENT_ENUM_TO_STRING.get(
                        first_para.alignment, 'left'
                    )

            return format_info

        except Exception as e:
            print(f"Error getting cell format: {str(e)}")
            return format_info

    # ===== SAVE =====

    def save(self, output_path: str = None):
        """Lưu document"""
        if output_path is None:
            output_path = self.doc_path
        self.doc.save(output_path)
        return output_path

    # ===== FORMAT EXTRACTION =====

    def get_format(
        self,
        paragraph_index: int = None,
        offset: int = None,
        end_offset: int = None,
        para_in_cell: int = None
    ) -> Optional[Dict]:
        """
        Extract formatting information using offset within paragraph.

        Args:
            paragraph_index: Index of paragraph containing the text
            offset: Starting character offset within the paragraph
            end_offset: Ending character offset within the paragraph
            para_in_cell: Paragraph index within table cell (optional)

        Returns:
            Dict with format info or None if not found
        """
        if offset is None or paragraph_index is None:
            return None

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx != paragraph_index:
                continue

            all_runs = self._extract_all_text_runs(paragraph)
            formats_found = []

            for run_info in all_runs:
                run_start = run_info['start_offset']
                run_end = run_info['end_offset']

                if end_offset is not None:
                    if run_end > offset and run_start < end_offset:
                        if run_info['text'].strip():
                            format_info = self._extract_run_format(run_info['run'])
                            formats_found.append(format_info)
                else:
                    if run_start <= offset < run_end:
                        if run_info['text'].strip():
                            format_info = self._extract_run_format(run_info['run'])
                            formats_found.append(format_info)
                            break

            if formats_found:
                for fmt in formats_found:
                    if fmt:
                        return fmt
                return formats_found[0]

            break

        return None

    def _extract_run_format(self, run) -> Optional[Dict]:
        """
        Extract formatting from a single run

        Args:
            run: python-docx Run object

        Returns:
            Dict with format info
        """
        from docx.oxml import OxmlElement

        format_info = {
            'bold': False,
            'italic': False,
            'underline': 'none',
            'strikethrough': False,
            'color': '000000',  # Default black
            'highlight': None,
            'font_size': 12,  # Default 12pt
            'font_name': 'Times New Roman',
            'superscript': False,
            'subscript': False
        }

        try:
            # Access run properties directly via XML
            rpr = run._r.get_or_add_rPr()

            # Bold
            bold_elem = rpr.find(f'{self.w_ns}b')
            if bold_elem is not None:
                val = bold_elem.get(f'{self.w_ns}val', '1')
                format_info['bold'] = val != '0'

            # Italic
            italic_elem = rpr.find(f'{self.w_ns}i')
            if italic_elem is not None:
                val = italic_elem.get(f'{self.w_ns}val', '1')
                format_info['italic'] = val != '0'

            # Underline
            underline_elem = rpr.find(f'{self.w_ns}u')
            if underline_elem is not None:
                format_info['underline'] = underline_elem.get(f'{self.w_ns}val', 'single')

            # Strikethrough
            strike_elem = rpr.find(f'{self.w_ns}strike')
            if strike_elem is not None:
                val = strike_elem.get(f'{self.w_ns}val', '1')
                format_info['strikethrough'] = val != '0'

            # Color
            color_elem = rpr.find(f'{self.w_ns}color')
            if color_elem is not None:
                color_val = color_elem.get(f'{self.w_ns}val', '000000')
                # Handle theme colors
                if color_val.startswith('themeColor'):
                    format_info['color'] = '000000'
                else:
                    format_info['color'] = color_val

            # Highlight/Shading
            shd_elem = rpr.find(f'{self.w_ns}shd')
            if shd_elem is not None:
                fill_val = shd_elem.get(f'{self.w_ns}fill', None)
                if fill_val and fill_val != 'auto':
                    format_info['highlight'] = fill_val

            # Font size (stored in half-points)
            sz_elem = rpr.find(f'{self.w_ns}sz')
            if sz_elem is not None:
                size_val = sz_elem.get(f'{self.w_ns}val', '24')
                try:
                    format_info['font_size'] = int(size_val) // 2  # Convert to points
                except (ValueError, TypeError):
                    format_info['font_size'] = 12

            # Font name
            rfonts_elem = rpr.find(f'{self.w_ns}rFonts')
            if rfonts_elem is not None:
                # Try ASCII font first, then HAnsi (High ANSI), then CS (Complex Script)
                font_name = (
                    rfonts_elem.get(f'{self.w_ns}ascii', None) or
                    rfonts_elem.get(f'{self.w_ns}hAnsi', None) or
                    rfonts_elem.get(f'{self.w_ns}cs', None)
                )
                if font_name:
                    format_info['font_name'] = font_name

            # Vertical alignment (superscript/subscript)
            vertAlign_elem = rpr.find(f'{self.w_ns}vertAlign')
            if vertAlign_elem is not None:
                val = vertAlign_elem.get(f'{self.w_ns}val', '')
                if val == 'superscript':
                    format_info['superscript'] = True
                elif val == 'subscript':
                    format_info['subscript'] = True

        except Exception as e:
            print(f"Error extracting run format: {e}")

        return format_info

    def add_hyperlink(self, paragraph_index: int, start_offset: int, end_offset: int, url: str) -> bool:
        """
        Apply hyperlink formatting to selected text range
        Similar to text formatting (bold, italic) but creates hyperlink element

        Args:
            paragraph_index: Index of paragraph (from all paragraphs iterator)
            start_offset: Start character offset within paragraph text
            end_offset: End character offset within paragraph text
            url: Target URL

        Returns:
            True if successful

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If operation fails
        """

        # Validate inputs
        if paragraph_index < 0:
            raise ValueError(f"Invalid paragraph_index: {paragraph_index} (must be >= 0)")
        if start_offset < 0 or end_offset < 0:
            raise ValueError(f"Invalid offsets: start={start_offset}, end={end_offset} (must be >= 0)")
        if start_offset >= end_offset:
            raise ValueError(f"Invalid range: start={start_offset} must be < end={end_offset}")
        if not url or not url.strip():
            raise ValueError("URL cannot be empty")

        # Find target paragraph
        target_para = self._find_paragraph_by_index(paragraph_index)
        if not target_para:
            total_paragraphs = sum(1 for _ in self._iterate_paragraphs_in_doc_order())
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        # Build run text map
        run_text_map = self._build_run_text_map(target_para)

        # Find all runs that overlap with selection [start_offset, end_offset]
        affected_runs = [
            run_info for run_info in run_text_map
            if run_info['end'] > start_offset and run_info['start'] < end_offset
        ]

        if not affected_runs:
            raise RuntimeError(f"Selection range [{start_offset}, {end_offset}] not found in paragraph {paragraph_index}")

        # Get paragraph element for relationship addition
        p_element = target_para._element
        document_part = self.doc.part

        # Add relationship for hyperlink ONCE (shared by all hyperlink elements)
        r_id = document_part.relate_to(url,
                                       "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                                       is_external=True)

        # Process each affected run in reverse order to maintain insertion positions
        for run_info in reversed(affected_runs):
            run = run_info['run']
            run_start = run_info['start']
            run_end = run_info['end']
            run_text = run_info['text']

            # Calculate overlap with selection
            overlap_start = max(start_offset, run_start)
            overlap_end = min(end_offset, run_end)

            if overlap_start >= overlap_end:
                continue

            # Calculate position within this run
            start_in_run = overlap_start - run_start
            end_in_run = overlap_end - run_start

            # Extract text parts
            before_text = run_text[:start_in_run]
            selected_text = run_text[start_in_run:end_in_run]
            after_text = run_text[end_in_run:]

            # Get original run formatting
            original_rpr = run._element.find(qn('w:rPr'))

            # Get current position in the full paragraph child list.
            # IMPORTANT: w:pPr must remain before any run/hyperlink children.
            # Using only the run index would insert before w:pPr when the target
            # run is the first text child in a formatted paragraph.
            child_elements = list(p_element)
            try:
                run_index = child_elements.index(run._element)
            except ValueError:
                # Run not found in paragraph, skip this iteration
                continue

            # Strategy: Replace the run with [before_text] + [hyperlink] + [after_text]
            # Remove original run
            p_element.remove(run._element)

            # Insert offset to track current position
            insert_offset = run_index

            # 1. Insert "before" text run (if not empty)
            if before_text:
                before_run = self._create_run_element(before_text, original_rpr)

                # Insert before hyperlink
                p_element.insert(insert_offset, before_run)
                insert_offset += 1

            # 2. Insert hyperlink with selected text
            hyperlink = OxmlElement('w:hyperlink')
            hyperlink.set(qn('r:id'), r_id)

            # Create run for hyperlink text with original formatting + hyperlink style
            hyperlink_rpr = self._apply_hyperlink_style(self._copy_run_rpr(original_rpr))
            hyperlink_run = self._create_run_element(selected_text, hyperlink_rpr, skip_props=None)

            hyperlink.append(hyperlink_run)

            # Insert hyperlink
            p_element.insert(insert_offset, hyperlink)
            insert_offset += 1

            # 3. Insert "after" text run (if not empty)
            if after_text:
                after_run = self._create_run_element(after_text, original_rpr)

                # Insert after hyperlink
                p_element.insert(insert_offset, after_run)

        return True
