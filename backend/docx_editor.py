"""
DocxFullEditor - Edit mọi thứ trong DOCX mà vẫn giữ nguyên formatting
Hỗ trợ: text edit, format changes, add content, delete content, tables, images
"""
import re
import copy
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
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

    def get_table_cell_paragraphs(self, block_index: int) -> list:
        """
        Get all paragraphs in a table cell

        Args:
            block_index: Block index of the table cell (from HTML preview)

        Returns:
            List of paragraph objects in the cell, or None if not found
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

        # Return all paragraphs in the cell
        return list(target_cell.paragraphs)

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

    def _iterate_runs(self):
        """Yield all runs with context from all paragraphs"""
        for paragraph in self._iterate_paragraphs_in_doc_order():
            for run in paragraph.runs:
                yield run, paragraph

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
        text_segments = []
        current_pos = 0

        # Process paragraph element children in order
        for child in paragraph._element:
            tag_name = child.tag.split('}')[1] if '}' in child.tag else child.tag

            if tag_name == 'r':
                # Regular run
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
                # MERGEFIELD field
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

        full_text = "".join(seg['text'] for seg in text_segments)
        return full_text, text_segments

    def _handle_empty_replacement(
        self,
        new_text: str,
        paragraph_index: int,
        reason: str
    ) -> bool:
        """
        Handle replacement when old_text is empty/whitespace-only.

        Args:
            new_text: Text to insert (or empty/None to clear)
            paragraph_index: Target paragraph index
            reason: Debug reason string

        Returns:
            True if handled, False otherwise
        """
        print(f"[DEBUG] {reason}")

        if paragraph_index is None:
            return False

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx == paragraph_index:
                if new_text and new_text.strip():
                    if paragraph.runs:
                        paragraph.runs[0].text = new_text
                    else:
                        paragraph.add_run(new_text)
                    print(f"[DEBUG] Inserted new_text into paragraph {paragraph_index}: '{new_text}'")
                else:
                    for run in paragraph.runs:
                        run.text = ""
                    print(f"[DEBUG] Cleared paragraph {paragraph_index}")
                return True

        return False

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

        # Debug: Show what we're looking for
        print(f"[REPLACE] ===== TEXT REPLACE START =====")
        print(f"[REPLACE] Paragraph: {paragraph_index}")
        print(f"[REPLACE] Old text (request): '{old_text[:100]}{'...' if len(old_text) > 100 else ''}'")
        print(f"[REPLACE] New text (request): '{new_text[:100]}{'...' if len(new_text) > 100 else ''}'")
        print(f"[REPLACE] Searching for: '{search_text_normalized[:100]}{'...' if len(search_text_normalized) > 100 else ''}'")

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
                # CRITICAL FIX: Partial match causes text injection bug!
                # MUST match exact text to avoid corrupting document
                # Try fuzzy match with placeholders removed
                import re
                # Remove placeholders for comparison
                old_no_fields = re.sub(r'«[^»]+»', '', search_text_normalized).strip()
                full_no_fields = re.sub(r'«[^»]+»', '', full_text_normalized).strip()

                print(f"[REPLACE] Not found - trying without placeholders")
                print(f"[REPLACE]   Old (no fields): '{old_no_fields[:100]}{'...' if len(old_no_fields) > 100 else ''}'")
                print(f"[REPLACE]   Full (no fields): '{full_no_fields[:100]}{'...' if len(full_no_fields) > 100 else ''}'")

                if old_no_fields and old_no_fields in full_no_fields:
                    # Found match without placeholders - use this
                    search_text_normalized = old_no_fields
                    print(f"[REPLACE] ✓ Match found without placeholders: '{search_text_normalized[:100]}{'...' if len(search_text_normalized) > 100 else ''}'")
                else:
                    # No match at all - skip this paragraph
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
                # Parse old_text to separate regular text from placeholders
                # Pattern: regular text + optional placeholder
                import re
                placeholder_pattern = r'«([^»]+)»'
                placeholders_in_old = re.findall(placeholder_pattern, old_text)

                if placeholders_in_old:
                    print(f"[REPLACE] Placeholders in old_text: {placeholders_in_old}")
                    # Check if old_text is JUST text before a placeholder (most common case)
                    # Example: "Nay tôi có nguyện vọng được ly hôn với «duoc_ly_hon_voi»"
                    # User wants to change to: "Nay tôi KHÔNG có nguyện vọng được ly hôn với «duoc_ly_hon_voi»"
                    # In this case, only replace the text BEFORE the placeholder

                    # Split old_text at first placeholder
                    parts = re.split(placeholder_pattern, old_text, 1)
                    if len(parts) >= 2:
                        text_before_placeholder = parts[0]
                        placeholder_name = parts[1]

                        # Check if new_text has the same placeholder at the end
                        new_parts = re.split(placeholder_pattern, new_text, 1)
                        if len(new_parts) >= 2 and new_parts[1] == placeholder_name:
                            # This is the common case: editing text BEFORE placeholder
                            new_text_before = new_parts[0]

                            print(f"[REPLACE] Edit before '{placeholder_name}': '{text_before_placeholder}' -> '{new_text_before}'")

                            # Find the first non-field segment (text before placeholder)
                            for seg in target_segments:
                                if not seg['is_field']:
                                    # This is the text segment before the placeholder
                                    element = seg['element']
                                    if element.tag.split('}')[1] == 'r':
                                        t_elements = element.findall(f"{self.w_ns}t")
                                        if t_elements:
                                            t_elem = t_elements[0]
                                            # Replace the text
                                            t_elem.text = new_text_before
                                            print(f"[REPLACE] ✓ Success (before placeholder)")
                                            return True

                            # If we get here, couldn't find non-field segment
                            print(f"[REPLACE] ✗ Failed: no non-field segment")
                            return False

                # FALL-THROUGH: User wants to remove/change placeholder
                # Use minimax pattern: replace in first non-field run, clear others
                print(f"[REPLACE] Placeholder change detected, using minimax pattern")

                # Step 1: Find first non-field segment
                first_non_field_seg = None
                for seg in target_segments:
                    if not seg['is_field']:
                        first_non_field_seg = seg
                        break

                if not first_non_field_seg:
                    print(f"[REPLACE] ✗ Failed: no non-field segment found")
                    return False

                # Step 2: Clear all non-field segments except first
                for seg in target_segments:
                    if not seg['is_field'] and seg != first_non_field_seg:
                        element = seg['element']
                        if element.tag.split('}')[1] == 'r':
                            t_elements = element.findall(f"{self.w_ns}t")
                            for t_elem in t_elements:
                                t_elem.text = ""

                # Step 3: Replace text in first non-field segment (preserve its formatting)
                element = first_non_field_seg['element']
                if element.tag.split('}')[1] == 'r':
                    t_elements = element.findall(f"{self.w_ns}t")
                    if t_elements:
                        t_elem = t_elements[0]
                        seg_start = first_non_field_seg['start_pos']
                        pos_in_seg = max(0, start_idx - seg_start)

                        original_text = t_elem.text if t_elem.text else ""
                        # CRITICAL FIX: Preserve text after replaced position
                        seg_end_pos = end_idx - seg_start
                        t_elem.text = original_text[:pos_in_seg] + new_text + (original_text[seg_end_pos:] if seg_end_pos <= len(original_text) else "")

                        print(f"[REPLACE] ✓ Success (placeholder changed)")
                        return True

                print(f"[REPLACE] ✗ Failed: could not modify first segment")
                return False

            # Perform replacement
            # Build new text by replacing only in non-field segments
            new_full_text = full_text[:start_idx] + new_text + full_text[end_idx:]

            # CRITICAL FIX: Reconstruct paragraph with new text, preserving MERGEFIELDs
            # Strategy: Replace text segment by segment, preserving fields
            replacement_done = False

            if len(target_segments) == 1 and not target_segments[0]['is_field']:
                # Simple case: single run, no field involved
                seg = target_segments[0]
                element = seg['element']

                # Calculate position within the segment
                seg_start = seg['start_pos']
                pos_in_seg = start_idx - seg_start

                # Find end position within segment
                seg_end_pos = end_idx - seg_start
                if seg_end_pos > len(seg['text']):
                    seg_end_pos = len(seg['text'])

                # Get the w:r element
                r_element = element
                if r_element.tag.split('}')[1] == 'r':
                    # Find w:t elements and replace text
                    t_elements = r_element.findall(f"{self.w_ns}t")
                    if t_elements:
                        # Simple case: replace in first w:t
                        t_elem = t_elements[0]
                        if t_elem.text:
                            t_elem.text = t_elem.text[:pos_in_seg] + new_text + t_elem.text[seg_end_pos:]
                            replacement_done = True
                            print(f"[REPLACE] ✓ Success (single run)")
                            print(f"[REPLACE] ===== TEXT REPLACE END (SUCCESS) =====")
                            return True  # ✅ CRITICAL FIX: Return immediately!
            else:
                # Complex case: multiple segments or includes fields
                # Strategy: Clear target non-field segments and insert new text in first one
                first_non_field_seg = None
                for seg in target_segments:
                    if not seg['is_field']:
                        if first_non_field_seg is None:
                            first_non_field_seg = seg
                        else:
                            # Clear this segment
                            element = seg['element']
                            if element.tag.split('}')[1] == 'r':
                                t_elements = element.findall(f"{self.w_ns}t")
                                for t_elem in t_elements:
                                    t_elem.text = ""

                if first_non_field_seg:
                    # Insert new text in first non-field segment
                    element = first_non_field_seg['element']
                    if element.tag.split('}')[1] == 'r':
                        t_elements = element.findall(f"{self.w_ns}t")
                        if t_elements:
                            t_elem = t_elements[0]

                            # Calculate position
                            seg_start = first_non_field_seg['start_pos']
                            pos_in_seg = start_idx - seg_start
                            if pos_in_seg < 0:
                                pos_in_seg = 0

                            # Replace with new text
                            original_text = t_elem.text if t_elem.text else ""
                            # CRITICAL FIX: Calculate seg_end_pos to preserve text after
                            seg_end_pos = end_idx - seg_start
                            t_elem.text = original_text[:pos_in_seg] + new_text + (original_text[seg_end_pos:] if seg_end_pos <= len(original_text) else "")
                            replacement_done = True
                            print(f"[REPLACE] ✓ Success (multiple segments)")
                            print(f"[REPLACE] ===== TEXT REPLACE END (SUCCESS) =====")
                            return True

            print(f"[REPLACE] ✗ No replacement done - replacement_done=False")
            print(f"[REPLACE] ===== TEXT REPLACE END (FAILED) =====")
            return False

        print(f"[REPLACE] ✗ No matching paragraph found")
        print(f"[REPLACE] ===== TEXT REPLACE END (NOT FOUND) =====")
        return False

    def _extract_all_text_runs(self, paragraph: Paragraph) -> list:
        """
        Extract all text runs from a paragraph, including those inside hyperlinks.

        In DOCX, hyperlinks (w:hyperlink) contain runs (w:r) with text.
        The standard paragraph.runs property doesn't include these hyperlink runs.

        Args:
            paragraph: Paragraph object

        Returns:
            List of dicts with keys:
                - run: Run object
                - text: str (run text)
                - is_hyperlink: bool (True if run is inside a hyperlink)
                - hyperlink_url: str or None (URL if is_hyperlink is True)
                - start_offset: int (character offset in paragraph text)
                - end_offset: int (end character offset in paragraph text)
        """
        from docx.text.run import Run

        all_runs = []
        char_offset = 0
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        # First, collect all runs including those in hyperlinks
        for child in paragraph._element:
            tag_name = child.tag.split('}')[1] if '}' in child.tag else child.tag

            if tag_name == 'r':
                # Regular run - create Run object directly from CT_R element
                run = Run(child, paragraph)
                run_text = run.text or ""
                all_runs.append({
                    'run': run,
                    'text': run_text,
                    'is_hyperlink': False,
                    'hyperlink_url': None,
                    'start_offset': char_offset,
                    'end_offset': char_offset + len(run_text),
                    'element': child
                })
                char_offset += len(run_text)

            elif tag_name == 'hyperlink':
                # Hyperlink element - extract runs inside it
                r_id = child.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                hyperlink_url = ""

                # Get URL from relationship
                if r_id and r_id in self.doc.part.rels:
                    rel = self.doc.part.rels[r_id]
                    hyperlink_url = rel._target if hasattr(rel, '_target') else ""

                # Process runs inside hyperlink
                for hc_child in child:
                    hc_tag = hc_child.tag.split('}')[1] if '}' in hc_child.tag else hc_child.tag
                    if hc_tag == 'r':
                        # Create Run object directly from CT_R element within hyperlink
                        run = Run(hc_child, paragraph)
                        run_text = run.text or ""
                        all_runs.append({
                            'run': run,
                            'text': run_text,
                            'is_hyperlink': True,
                            'hyperlink_url': hyperlink_url,
                            'start_offset': char_offset,
                            'end_offset': char_offset + len(run_text),
                            'element': hc_child,
                            'hyperlink_element': child
                        })
                        char_offset += len(run_text)

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
        NOW SUPPORTS formatting text inside hyperlinks

        Args:
            text: Text to format
            paragraph_index: Index of paragraph containing the text
            bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size: Format options
            all_caps: All caps formatting
            start_offset: Start character offset for precise targeting (optional, for duplicate words)
            end_offset: End character offset for precise targeting (optional, for duplicate words)

        Returns:
            True if found and formatted, False otherwise
        """
        import re

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx != paragraph_index:
                continue

            # Use new helper to extract ALL runs including hyperlinks
            all_runs = self._extract_all_text_runs(paragraph)
            full_text = "".join(run_info['text'] for run_info in all_runs)

            # DEBUG: Log paragraph details for troubleshooting
            print(f"[DEBUG] apply_format_at_position:")
            print(f"  p_idx={p_idx}, text='{full_text[:80]}...'")
            print(f"  full_text length={len(full_text)}")
            print(f"  provided offsets: start_offset={start_offset}, end_offset={end_offset}")
            print(f"  searching for text='{text}'")

            # CRITICAL FIX: Use offset-based targeting when provided
            # This fixes bug where duplicate words always format the first occurrence
            if start_offset is not None and end_offset is not None:
                # Validate that offsets are within bounds of this paragraph's text
                # This handles table cells where offsets might be calculated from full cell text
                if start_offset >= 0 and end_offset <= len(full_text) and start_offset < end_offset:
                    start_idx = start_offset
                    end_idx = end_offset
                    print(f"[DEBUG] Using provided offsets (valid): start_idx={start_idx}, end_idx={end_idx}")
                else:
                    # Offsets are out of bounds for this paragraph
                    # This happens in table cells where frontend calculates offset from full cell text
                    # but backend processes each paragraph separately
                    print(f"[DEBUG] Provided offsets out of bounds for this paragraph")
                    print(f"[DEBUG] start_offset={start_offset}, end_offset={end_offset}, paragraph_len={len(full_text)}")

                    # Try text-based search in this paragraph first
                    start_idx = full_text.find(text)
                    if start_idx != -1:
                        end_idx = start_idx + len(text)
                        print(f"[DEBUG] Found text in this paragraph at start_idx={start_idx}")
                    else:
                        # Text not found in this paragraph
                        # Check if we're in a table cell and need to search other paragraphs in the same cell
                        print(f"[DEBUG] Text not found in this paragraph, checking for table cell context")

                        # Try to find the text using normalized search
                        search_text_normalized = re.sub(r'\s+', ' ', text.strip())
                        full_text_normalized = re.sub(r'\s+', ' ', full_text.strip())

                        if search_text_normalized in full_text_normalized:
                            # Found with normalized search
                            start_idx_normalized = full_text_normalized.find(search_text_normalized)
                            end_idx_normalized = start_idx_normalized + len(search_text_normalized)

                            # Build position mapping from normalized to original
                            norm_to_orig = []
                            norm_pos = 0
                            for orig_idx, char in enumerate(full_text):
                                if not char.isspace():
                                    norm_to_orig.append((norm_pos, orig_idx))
                                    norm_pos += 1

                            if start_idx_normalized < len(norm_to_orig):
                                start_idx = norm_to_orig[start_idx_normalized][1]
                                if end_idx_normalized <= len(norm_to_orig):
                                    end_idx = norm_to_orig[end_idx_normalized - 1][1] + 1
                                else:
                                    end_idx = start_idx + len(text)
                                print(f"[DEBUG] Found with normalized search at start_idx={start_idx}")
                            else:
                                return False
                        else:
                            print(f"[DEBUG] Text not found in this paragraph at all, returning False")
                            return False
            else:
                # Original search-based logic (for backward compatibility)
                # Try direct search first (most accurate)
                start_idx = full_text.find(text)
                if start_idx == -1:
                    # Fallback: try normalized search for fuzzy matching
                    search_text_normalized = re.sub(r'\s+', ' ', text.strip())
                    full_text_normalized = re.sub(r'\s+', ' ', full_text.strip())

                    if search_text_normalized not in full_text_normalized:
                        return False

                    # Map normalized position back to original text position
                    start_idx_normalized = full_text_normalized.find(search_text_normalized)
                    end_idx_normalized = start_idx_normalized + len(search_text_normalized)

                    # Build position mapping from normalized to original
                    norm_to_orig = []
                    norm_pos = 0
                    orig_pos = 0

                    for orig_idx, char in enumerate(full_text):
                        if not char.isspace():
                            norm_to_orig.append((norm_pos, orig_idx))
                            norm_pos += 1
                        orig_pos += 1

                    # Find original position from normalized position
                    if start_idx_normalized < len(norm_to_orig):
                        start_idx = norm_to_orig[start_idx_normalized][1]
                        if end_idx_normalized <= len(norm_to_orig):
                            end_idx = norm_to_orig[end_idx_normalized - 1][1] + 1
                        else:
                            end_idx = start_idx + len(text)
                    else:
                        return False
                else:
                    end_idx = start_idx + len(text)

            # Tìm runs chứa text cần format (including hyperlinks)
            runs_to_format = []

            for r_idx, run_info in enumerate(all_runs):
                run_start = run_info['start_offset']
                run_end = run_info['end_offset']

                # Check if this run overlaps with target text
                if run_end > start_idx and run_start < end_idx:
                    overlap_start = max(start_idx, run_start)
                    overlap_end = min(end_idx, run_end)

                    text_to_format = run_info['text'][overlap_start - run_start:overlap_end - run_start]

                    runs_to_format.append({
                        'run': run_info['run'],
                        'r_idx': r_idx,  # Add run index for backward compatibility
                        'run_info': run_info,  # Store full run_info for hyperlink handling
                        'run_start': run_start,
                        'run_end': run_end,
                        'overlap_start': overlap_start,
                        'overlap_end': overlap_end,
                        'text_to_format': text_to_format
                    })

            if not runs_to_format:
                continue

            # Check if any runs are inside hyperlinks - need special handling
            has_hyperlinks = any(rf['run_info']['is_hyperlink'] for rf in runs_to_format)

            if has_hyperlinks:
                # Handle hyperlink formatting separately to preserve hyperlink structure
                self._format_hyperlink_text(
                    paragraph,
                    runs_to_format,
                    bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size,
                    all_caps
                )
            else:
                # Regular formatting for non-hyperlink text
                self._format_text_in_runs(
                    paragraph,
                    runs_to_format,
                    bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size,
                    all_caps
                )
            return True

        return False

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

        # Process runs in reverse order to maintain indices
        for run_info in reversed(runs_to_format):
            run = run_info['run']
            r_idx = run_info['r_idx']
            overlap_start = run_info['overlap_start']
            overlap_end = run_info['overlap_end']
            run_start = run_info['run_start']
            run_end = run_info['run_end']

            text_before = run.text[:overlap_start - run_start]
            text_to_format = run.text[overlap_start - run_start:overlap_end - run_start]
            text_after = run.text[overlap_end - run_start:]

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

            # Determine which properties will be explicitly set
            skip_props = []
            if bold is not None:
                skip_props.append('b')
            if italic is not None:
                skip_props.append('i')
            if underline is not None:
                skip_props.append('u')

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
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

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
        for hl_id, hl_group in hyperlink_groups.items():
            hl_element = hl_group['hyperlink_element']
            group_runs = hl_group['runs']

            for run_data in group_runs:
                run = run_data['run']
                overlap_start = run_data['overlap_start']
                overlap_end = run_data['overlap_end']
                run_start = run_data['run_start']
                run_end = run_data['run_end']

                # Calculate text segments
                text_before = run.text[:overlap_start - run_start]
                text_to_format = run.text[overlap_start - run_start:overlap_end - run_start]
                text_after = run.text[overlap_end - run_start:]

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

                # Determine which properties will be explicitly set
                skip_props = []
                if bold is not None:
                    skip_props.append('b')
                if italic is not None:
                    skip_props.append('i')
                if underline is not None:
                    skip_props.append('u')

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
        from docx.oxml import OxmlElement

        # Create run element
        new_run = OxmlElement('w:r')

        # Copy format properties
        if rpr_element is not None:
            new_rpr = copy.deepcopy(rpr_element)

            # Remove skipped properties
            if skip_props:
                for prop in skip_props:
                    for child in new_rpr.findall(f'{self.w_ns}{prop}'):
                        new_rpr.remove(child)

            new_run.append(new_rpr)

        # Add text
        new_t = OxmlElement('w:t')
        new_t.set(qn('xml:space'), 'preserve')
        new_t.text = text
        new_run.append(new_t)

        # Insert into hyperlink element
        hyperlink_element.insert(insert_offset, new_run)

        # Return a minimal Run wrapper for _apply_format_to_run
        # Note: This is a simplified wrapper, sufficient for format application
        class SimpleRun:
            def __init__(self, element):
                self._element = element
                self.text = text

        return SimpleRun(new_run)


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
        if rpr_element is not None:
            new_rpr = new_run._r.get_or_add_rPr()

            # Properties to skip when copying (default: none)
            if skip_props is None:
                skip_props = []

            # Copy children except skipped properties
            for child in rpr_element:
                # Skip if this property tag is in skip_props
                prop_tag = child.tag.replace(f'{self.w_ns}', '')
                if prop_tag not in skip_props:
                    # Deep copy to avoid reference issues
                    child_copy = copy.deepcopy(child)
                    new_rpr.append(child_copy)

        return new_run

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

        # Handle bold - remove element when False, set when True
        if bold is not None:
            bold_elem = rpr.find(f'{self.w_ns}b')
            if bold:
                if bold_elem is None:
                    bold_elem = rpr.makeelement(f'{self.w_ns}b')
                    rpr.append(bold_elem)
                bold_elem.set(f'{self.w_ns}val', '1')
            else:
                # Remove bold element entirely when False
                if bold_elem is not None:
                    rpr.remove(bold_elem)

        # Handle italic - remove element when False, set when True
        if italic is not None:
            italic_elem = rpr.find(f'{self.w_ns}i')
            if italic:
                if italic_elem is None:
                    italic_elem = rpr.makeelement(f'{self.w_ns}i')
                    rpr.append(italic_elem)
                italic_elem.set(f'{self.w_ns}val', '1')
            else:
                # Remove italic element entirely when False
                if italic_elem is not None:
                    rpr.remove(italic_elem)

        # Handle underline - remove element when False, set when True
        if underline is not None:
            underline_elem = rpr.find(f'{self.w_ns}u')
            if underline:
                if underline_elem is None:
                    underline_elem = rpr.makeelement(f'{self.w_ns}u')
                    rpr.append(underline_elem)
                underline_elem.set(f'{self.w_ns}val', 'single')
            else:
                # Remove underline element entirely when False
                if underline_elem is not None:
                    rpr.remove(underline_elem)

        # Handle strikethrough - remove element when False, set when True
        if strikethrough is not None:
            strike_elem = rpr.find(f'{self.w_ns}strike')
            if strikethrough:
                if strike_elem is None:
                    strike_elem = rpr.makeelement(f'{self.w_ns}strike')
                    rpr.append(strike_elem)
                strike_elem.set(f'{self.w_ns}val', '1')
            else:
                # Remove strike element entirely when False
                if strike_elem is not None:
                    rpr.remove(strike_elem)

        # Handle vertical alignment (subscript/superscript) - mutually exclusive
        # Remove old element first if setting any vertical alignment
        if (subscript or superscript) and (subscript is not None or superscript is not None):
            # Remove existing vertAlign element
            existing_vertAlign = rpr.find(f'{self.w_ns}vertAlign')
            if existing_vertAlign is not None:
                rpr.remove(existing_vertAlign)

            # Create new vertAlign element based on which one is True
            if subscript and not superscript:
                vertAlign_elem = rpr.makeelement(f'{self.w_ns}vertAlign')
                rpr.append(vertAlign_elem)
                vertAlign_elem.set(f'{self.w_ns}val', 'subscript')
            elif superscript and not subscript:
                vertAlign_elem = rpr.makeelement(f'{self.w_ns}vertAlign')
                rpr.append(vertAlign_elem)
                vertAlign_elem.set(f'{self.w_ns}val', 'superscript')
            # If both True or both False, do nothing (no vertical alignment)
        elif subscript is False or superscript is False:
            # Explicitly remove vertAlign if explicitly set to False
            existing_vertAlign = rpr.find(f'{self.w_ns}vertAlign')
            if existing_vertAlign is not None:
                rpr.remove(existing_vertAlign)

        # Handle color
        if color:
            color_elem = rpr.find(f'{self.w_ns}color')
            if color_elem is None:
                color_elem = rpr.makeelement(f'{self.w_ns}color')
                rpr.append(color_elem)

            # Parse color directly to hex string
            if color.startswith("#"):
                # Hex color - just strip the # and convert to uppercase
                color_hex = color.lstrip("#").upper()
            elif color.startswith("rgb"):
                # RGB format - parse to hex
                import re
                rgb_match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', color)
                if rgb_match:
                    r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
                    color_hex = f'{r:02X}{g:02X}{b:02X}'
                else:
                    color_hex = "000000"
            else:
                # Named color - use _parse_color to get RGBColor, then extract hex
                rgb = self._parse_color(color)
                # RGBColor is a tuple-like object, convert to hex
                color_hex = f'{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}'

            color_elem.set(f'{self.w_ns}val', color_hex)

        # Handle highlight (skip white/transparent as it means "no highlight")
        if highlight and highlight.lower() != '#ffffff' and highlight.lower() != '#fff':
            shd_elem = rpr.find(f'{self.w_ns}shd')
            if shd_elem is None:
                shd_elem = rpr.makeelement(f'{self.w_ns}shd')
                rpr.append(shd_elem)
            shd_elem.set(f'{self.w_ns}fill', self._parse_highlight_color(highlight))
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

        # Handle all caps - remove element when False, set when True
        if all_caps is not None:
            caps_elem = rpr.find(f'{self.w_ns}caps')
            if all_caps:
                if caps_elem is None:
                    caps_elem = rpr.makeelement(f'{self.w_ns}caps')
                    rpr.append(caps_elem)
                caps_elem.set(f'{self.w_ns}val', '1')
            else:
                # Remove caps element entirely when False
                if caps_elem is not None:
                    rpr.remove(caps_elem)

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

    def _handle_trailing_spaces_alignment(self, paragraph, original_alignment):
        """
        Handle trailing spaces for right alignment (Word's special formatting)
        Word uses "justify" + trailing spaces to create right-aligned text
        Convert to "right" alignment + right indent for proper display
        """
        # Get paragraph text after formatting
        paragraph_text = "".join(run.text for run in paragraph.runs)

        # Check for trailing spaces
        has_trailing_spaces = len(paragraph_text) > 0 and paragraph_text[-1] in ' \t'

        if has_trailing_spaces and original_alignment == WD_PARAGRAPH_ALIGNMENT.JUSTIFY:
            # Count trailing spaces
            trailing_space_count = len(paragraph_text) - len(paragraph_text.rstrip(' \t'))

            # Convert to right alignment
            paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT

            # Add right indent based on trailing space count
            # Calibration: each space ≈ 15 twips (0.75pt) for standard fonts
            # 84 spaces ≈ 1260 twips (0.88 inch) ≈ right margin effect
            right_indent_twips = trailing_space_count * 15

            # Set right indent
            current_right_indent = paragraph.paragraph_format.right_indent
            new_right_indent = Twips(right_indent_twips)

            paragraph.paragraph_format.right_indent = (
                current_right_indent + new_right_indent
                if current_right_indent is not None
                else new_right_indent
            )

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
        alignment_map = {
            "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
            "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
            "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
            "justify": WD_PARAGRAPH_ALIGNMENT.JUSTIFY
        }

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if p_idx != paragraph_index:
                continue

            # Apply alignment
            if alignment and alignment in alignment_map:
                paragraph.alignment = alignment_map[alignment]

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

    def apply_paragraph_format_by_text(self, text: str, **kwargs):
        """
        Apply paragraph formatting đến paragraph chứa text

        Wrapper function đơn giản cho apply_paragraph_formatting
        Tự động tìm paragraph index từ text content

        Args:
            text: Text content để tìm paragraph
            **kwargs: Same params as apply_paragraph_formatting
                    (alignment, line_spacing, space_before, space_after, first_line_indent)

        Returns:
            True nếu thành công, False nếu không tìm thấy paragraph
        """
        for idx, para in enumerate(self._iterate_paragraphs_in_doc_order()):
            if text in para.text:
                return self.apply_paragraph_formatting(paragraph_index=idx, **kwargs)
        return False

    # ===== TEXT EDITING (Giữ format) =====

    def replace_text_keep_format(self, old_text: str, new_text: str):
        """
        Thay text nhưng giữ nguyên format
        Handle text bị split và fuzzy match

        Args:
            old_text: Text cần tìm (có thể khác biệt nhỏ với DOCX)
            new_text: Text thay thế
        """
        search_text_normalized = self._normalize_text(old_text)

        for paragraph in self._iterate_paragraphs_in_doc_order():
            full_text = "".join(run.text for run in paragraph.runs)
            full_text_normalized = self._normalize_text(full_text)

            if search_text_normalized in full_text_normalized:
                start_idx = full_text_normalized.find(search_text_normalized)
                if start_idx == -1:
                    continue

                # Find which runs contain the text
                char_count = 0
                target_runs = []
                end_idx = start_idx + len(search_text_normalized)

                for run in paragraph.runs:
                    run_start = char_count
                    run_end = char_count + len(run.text)

                    if run_end > start_idx and run_start < end_idx:
                        target_runs.append(run)

                    char_count += len(run.text)

                # Replace text in target runs
                if not target_runs:
                    continue

                first_run = target_runs[0]

                run_text_normalized = self._normalize_text(first_run.text)

                if search_text_normalized in run_text_normalized:
                    first_run.text = first_run.text.replace(search_text_normalized, new_text, 1)
                elif search_text_normalized[0:30] in run_text_normalized:
                    # Partial match - find and replace
                    for i in range(len(first_run.text)):
                        segment = first_run.text[i:i+len(search_text_normalized)]
                        segment_normalized = self._normalize_text(segment)
                        if (segment_normalized == search_text_normalized or
                            self._normalize_text(search_text_normalized[0:len(segment_normalized)]) in segment_normalized):
                            first_run.text = first_run.text[:i] + new_text + first_run.text[i+len(segment):]
                            for run in target_runs[1:]:
                                run.text = ""
                            break

    def replace_text_advanced(
        self,
        old_text: str,
        new_text: str,
        match_case: bool = False,
        whole_word: bool = False,
        use_regex: bool = False
    ):
        """Find và replace nâng cao, giữ format"""
        if not old_text:
            return

        for run, _ in self._iterate_runs():
            if old_text not in run.text:
                continue

            if use_regex:
                pattern = re.compile(old_text)
                if pattern.search(run.text):
                    run.text = pattern.sub(new_text, run.text)

            elif whole_word:
                pattern = r'\b' + re.escape(old_text) + r'\b'
                if match_case:
                    pattern = r'(?<!\w)' + re.escape(old_text) + r'(?!\w)'
                else:
                    pattern = r'(?<!\w)' + re.escape(old_text) + r'(?!\w)'

                if re.search(pattern, run.text):
                    flags = 0 if match_case else re.IGNORECASE
                    run.text = re.sub(pattern, new_text, run.text, flags=flags)

            else:
                if match_case:
                    if old_text in run.text:
                        run.text = run.text.replace(old_text, new_text)
                else:
                    if old_text.lower() in run.text.lower():
                        idx = run.text.lower().find(old_text.lower())
                        if idx != -1:
                            run.text = run.text[:idx] + new_text + run.text[idx + len(old_text):]

    # ===== FORMATTING =====

    def apply_format_to_text(
        self,
        text: str,
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
        paragraph_index: int = None
    ):
        """
        Apply formatting cho text cụ thể
        Hỗ trợ fuzzy match và multi-paragraph selection

        Args:
            text: Text cần format (có thể chứa \n\n cho multi-paragraph)
            bold: True/False/None (None = không đổi)
            italic: True/False/None
            underline: True/False/None
            strikethrough: True/False/None
            subscript: True/False/None
            superscript: True/False/None
            color: Màu sắc (hex or named color)
            highlight: Highlight color
            font_name: Tên font
            font_size: Cỡ chữ (points)
            paragraph_index: Chỉ format text tại paragraph này (None = format tất cả)
        """
        import re

        # Handle multi-paragraph selection (split by \n\n)
        text_parts = [t.strip() for t in text.split('\n\n') if t.strip()]

        if len(text_parts) > 1:
            # Multi-paragraph: apply format to each part separately
            for text_part in text_parts:
                self._apply_format_to_single_text(text_part, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size, paragraph_index)
        else:
            # Single paragraph
            self._apply_format_to_single_text(text, bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size, paragraph_index)

    def _apply_format_to_single_text(
        self,
        text: str,
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
        paragraph_index: int = None
    ):
        """Helper: apply format to single text segment

        Args:
            text: Text cần format
            bold, italic, underline, strikethrough, subscript, superscript, color, highlight, font_name, font_size: Format options
            paragraph_index: Chỉ format text tại paragraph này (None = format tất cả)
        """
        search_text_normalized = self._normalize_text(text)

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            # Skip if paragraph_index is specified and doesn't match
            if paragraph_index is not None and p_idx != paragraph_index:
                continue

            para_text = "".join(run.text for run in paragraph.runs)
            para_text_normalized = self._normalize_text(para_text)

            if (search_text_normalized not in para_text_normalized and
                search_text_normalized[0:50] not in para_text_normalized):
                continue

            for run in paragraph.runs:
                run_normalized = self._normalize_text(run.text)
                if (search_text_normalized not in run_normalized and
                    search_text_normalized[0:30] not in run_normalized):
                    continue

                # Use _apply_format_to_run for consistent formatting (supports hex highlight colors)
                self._apply_format_to_run(run, bold, italic, underline, strikethrough, color, highlight, font_name, font_size)

    # ===== DELETE CONTENT =====

    def delete_text(self, text: str):
        """Xóa text khỏi document"""
        self.replace_text_keep_format(text, "")

    def delete_paragraph_containing(self, text: str):
        """Xóa entire paragraph chứa text"""
        paragraphs_to_delete = []

        # Find paragraphs to delete
        for i, paragraph in enumerate(self.doc.paragraphs):
            if text in paragraph.text:
                paragraphs_to_delete.append(i)

        # Delete in reverse order to maintain indices
        for index in reversed(paragraphs_to_delete):
            p_element = self.doc.paragraphs[index]._element
            p_element.getparent().remove(p_element)

    # ===== ADD CONTENT =====

    def add_text_after(self, target_text: str, new_text: str, inherit_format: bool = True):
        """
        Thêm text sau target text

        Args:
            target_text: Text đích (thêm sau text này)
            new_text: Text mới cần thêm
            inherit_format: True = kế thừa format của target, False = dùng format mặc định
        """
        for run, _ in self._iterate_runs():
            if target_text in run.text:
                run.text = run.text.replace(target_text, target_text + new_text)
                return True
        return False

    def add_text_before(self, target_text: str, new_text: str, inherit_format: bool = True):
        """Thêm text trước target text"""
        for run, _ in self._iterate_runs():
            if target_text in run.text:
                run.text = run.text.replace(target_text, new_text + target_text)
                return True
        return False

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
            w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

            # Extract full text and segments (similar to _extract_paragraph_full_text)
            text_segments = []
            current_pos = 0

            # Process paragraph element children in order
            for child in paragraph._element:
                tag_name = child.tag.split('}')[1] if '}' in child.tag else child.tag

                if tag_name == 'r':
                    # Regular run
                    run_text = "".join(t.text for t in child.findall(f"{w_ns}t") if t.text)
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
                    # MERGEFIELD field
                    instr = child.get(f"{w_ns}instr", "")
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
                    element = seg['element']
                    run_text = seg['text']

                    # Calculate intersection with delete range
                    seg_start = seg['start_pos']
                    seg_end = seg['end_pos']

                    # Calculate how much to delete from this run
                    delete_start = max(start_offset - seg_start, 0)
                    delete_end = min(end_offset - seg_start, len(run_text))

                    if delete_end <= delete_start:
                        # No overlap (shouldn't happen given our intersection check)
                        continue

                    # Modify run text: keep text before and after the deletion
                    new_text = run_text[:delete_start] + run_text[delete_end:]

                    # Find all w:t elements in this run and update the first one
                    t_elements = element.findall(f"{w_ns}t")
                    if t_elements:
                        t_elements[0].text = new_text
                        deleted_any = True

            # Clean up empty runs after deletion
            if deleted_any:
                self._remove_empty_runs(paragraph)

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
        Xóa hoàn toàn placeholder KHÔNG restore text gốc từ \z switch

        Đây là TRUE DELETION - xóa cả field MERGEFIELD và wrapper runs,
        không restore lại text gốc như update-template endpoint.

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
                for para in self.doc.paragraphs:
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

    def insert_paragraph_after(self, target_paragraph, text: str = ""):
        """
        Thêm paragraph mới sau một paragraph cụ thể

        Args:
            target_paragraph: Paragraph object để thêm mới sau nó
            text: Nội dung text cho paragraph mới

        Returns:
            Paragraph object mới được tạo
        """
        print(f"[DEBUG] insert_paragraph_after called: text={repr(text[:50])}")

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

        # Insert new paragraph sau target paragraph
        parent_index = list(parent).index(target_p_element)
        parent.insert(parent_index + 1, new_p)

        # Convert to Paragraph object
        from docx.text.paragraph import Paragraph
        new_para = Paragraph(new_p, self.doc)

        print(f"[DEBUG] New paragraph inserted after target")
        return new_para

    def insert_paragraph_before(self, target_paragraph, text: str = ""):
        """
        Thêm paragraph mới trước một paragraph cụ thể

        Args:
            target_paragraph: Paragraph object để thêm mới trước nó
            text: Nội dung text cho paragraph mới

        Returns:
            Paragraph object mới được tạo
        """
        print(f"[DEBUG] insert_paragraph_before called: text={repr(text[:50])}")

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

        # Insert new paragraph TRƯỚC target paragraph (không +1)
        parent_index = list(parent).index(target_p_element)
        parent.insert(parent_index, new_p)

        # Convert to Paragraph object
        from docx.text.paragraph import Paragraph
        new_para = Paragraph(new_p, self.doc)

        print(f"[DEBUG] New paragraph inserted before target")
        return new_para

    def add_paragraph_in_table_cell(
        self,
        table_index: int,
        row_index: int,
        col_index: int,
        text: str = "",
        after_para_index: int = None
    ):
        """
        Thêm paragraph mới vào table cell

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

            if after_para_index is not None and after_para_index < len(cell.paragraphs):
                # Thêm sau một paragraph cụ thể trong cell
                target_para = cell.paragraphs[after_para_index]
                target_p_element = target_para._p
                parent = target_p_element.getparent()

                # Tạo new paragraph element
                new_p = OxmlElement('w:p')

                # Copy paragraph properties từ target paragraph
                pPr = target_p_element.find(f"{self.w_ns}pPr")
                if pPr is not None:
                    new_p.append(copy.deepcopy(pPr))

                # Copy run properties từ target paragraph
                source_run_props = None
                source_run_for_debug = None
                if target_para.runs:
                    for run in reversed(target_para.runs):
                        if run.text and run.text.strip():
                            run_element = run._element
                            rPr = run_element.find(f"{self.w_ns}rPr")
                            if rPr is not None:
                                source_run_props = rPr
                                source_run_for_debug = run
                                print(f"[DEBUG] Found source run props in cell: font={run.font.name}, size={run.font.size}")
                            break

                # TẠO RUN LUÔN - kể cả khi text rỗng
                new_r = OxmlElement('w:r')

                # Copy run properties if available
                if source_run_props is not None:
                    new_r.append(copy.deepcopy(source_run_props))
                    print(f"[DEBUG] Copied run props to new run in cell")
                else:
                    print(f"[DEBUG] No source run props in cell, using default")

                # Tạo text element - có thể rỗng
                new_t = OxmlElement('w:t')
                new_t.set(qn('xml:space'), 'preserve')
                new_t.text = text
                new_r.append(new_t)
                new_p.append(new_r)

                # Insert new paragraph sau target paragraph
                parent_index = list(parent).index(target_p_element)
                parent.insert(parent_index + 1, new_p)
            else:
                # Thêm vào cuối cell - kế thừa format từ paragraph cuối cùng
                last_para = None
                for para in cell.paragraphs:
                    if para.text.strip():
                        last_para = para

                if text:
                    new_para = cell.add_paragraph(text)
                else:
                    new_para = cell.add_paragraph()

                # Inherit formatting from last paragraph
                if last_para:
                    new_para.alignment = last_para.alignment
                    new_para.paragraph_format.space_before = last_para.paragraph_format.space_before
                    new_para.paragraph_format.space_after = last_para.paragraph_format.space_after
                    new_para.paragraph_format.line_spacing = last_para.paragraph_format.line_spacing

                    if last_para.runs:
                        source_run = None
                        for run in reversed(last_para.runs):
                            if run.text and run.text.strip():
                                source_run = run
                                break

                        if not source_run and last_para.runs:
                            source_run = last_para.runs[0]

                        if source_run:
                            for new_run in new_para.runs:
                                self._copy_run_formatting(source_run, new_run)
                            print(f"[DEBUG] Copied formatting from last paragraph in cell")

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

        # Validate inputs
        if paragraph_index < 0:
            raise ValueError(f"Invalid paragraph_index: {paragraph_index} (must be >= 0)")
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset} (must be >= 0)")
        if not field_name or not field_name.strip():
            raise ValueError("Field name cannot be empty")

        # Find target paragraph
        target_para = None
        total_paragraphs = 0
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            total_paragraphs += 1
            if p_idx == paragraph_index:
                target_para = paragraph
                break

        if not target_para:
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        print(f"[DEBUG] Target paragraph found: index={paragraph_index}")
        print(f"[DEBUG] Paragraph runs count: {len(target_para.runs)}")
        print(f"[DEBUG] Paragraph text: {repr(target_para.text[:100] if target_para.text else '')}")

        # Build text with run mapping
        run_text_map = []  # [(run, start_offset, end_offset, text)]
        current_offset = 0

        for run in target_para.runs:
            if run.text:
                text_len = len(run.text)
                run_text_map.append({
                    'run': run,
                    'start': current_offset,
                    'end': current_offset + text_len,
                    'text': run.text
                })
                current_offset += text_len

        # Find which run contains the offset
        target_run_info = None
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)

        for run_info in run_text_map:
            if run_info['start'] <= offset <= run_info['end']:
                target_run_info = run_info
                break

        # Handle empty paragraph or no valid run found
        if not target_run_info:
            para_text = target_para.text
            para_preview = para_text[:50] + "..." if len(para_text) > 50 else para_text

            print(f"[DEBUG] No target run found. Paragraph text length: {total_text_length}, offset: {offset}")
            print(f"[DEBUG] Paragraph runs count: {len(target_para.runs)}")

            # Special case: Empty paragraph - always insert at beginning, regardless of offset
            # Auto-correct offset to 0 for empty paragraphs
            if total_text_length == 0:
                if offset != 0:
                    print(f"[DEBUG] WARNING: Offset {offset} is invalid for empty paragraph, auto-correcting to 0")
                    offset = 0
                print(f"[DEBUG] Empty paragraph {paragraph_index}, inserting placeholder at beginning")

                # Create placeholder text
                placeholder_text = f"«{field_name}»"

                # Get paragraph element
                p_element = target_para._p
                print(f"[DEBUG] Paragraph element: {p_element.tag}")

                # Store current paragraph alignment before any changes
                # Read alignment from XML directly to avoid object property issues
                current_alignment = None
                try:
                    # Try to read from paragraph property (w:pPr/w:jc)
                    pPr = p_element.find(f"{self.w_ns}pPr")
                    if pPr is not None:
                        jc = pPr.find(f"{self.w_ns}jc")
                        if jc is not None:
                            jc_val = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                            alignment_map = {
                                "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
                                "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
                                "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
                                "both": WD_PARAGRAPH_ALIGNMENT.JUSTIFY
                            }
                            current_alignment = alignment_map.get(jc_val)
                            print(f"[DEBUG] Read alignment from XML: {jc_val} -> {current_alignment}")
                except Exception as e:
                    print(f"[DEBUG] Could not read alignment from XML: {e}")

                # Fallback to object property if XML reading failed
                if current_alignment is None:
                    current_alignment = target_para.alignment
                    print(f"[DEBUG] Using object alignment property: {current_alignment}")

                # Try to find format from previous paragraph in document
                original_rpr = None
                original_alignment = None
                try:
                    # Look for previous paragraph with format
                    # CRITICAL FIX: Compare by _element, not object identity!
                    # Paragraph() creates new objects each time, so .index() fails
                    all_paras = list(self._iterate_paragraphs_in_doc_order())
                    current_idx = None
                    for idx, para in enumerate(all_paras):
                        if para._element == target_para._element:
                            current_idx = idx
                            break

                    if current_idx is not None:
                        print(f"[DEBUG] Current paragraph index: {current_idx}, total paragraphs: {len(all_paras)}")

                        if current_idx > 0:
                            prev_para = all_paras[current_idx - 1]
                            print(f"[DEBUG] Previous paragraph has {len(prev_para.runs)} runs")
                            # Find first run with format in previous paragraph
                            for run in prev_para.runs:
                                rpr = run._r.get_or_add_rPr()
                                if rpr is not None and len(list(rpr)) > 0:
                                    original_rpr = rpr
                                    print(f"[DEBUG] Using format from previous paragraph")
                                    break
                            # Also get alignment from previous paragraph
                            if prev_para.alignment is not None:
                                original_alignment = prev_para.alignment
                                print(f"[DEBUG] Using alignment from previous paragraph: {original_alignment}")
                    else:
                        print(f"[DEBUG] Could not find current paragraph in iterator")
                except Exception as e:
                    print(f"[DEBUG] Could not get format from previous paragraph: {e}")

                # If no format found, use default
                if original_rpr is None:
                    # Create default format
                    from docx.oxml import parse_xml
                    default_rpr_xml = '<w:rPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
                    original_rpr = parse_xml(default_rpr_xml)
                    print(f"[DEBUG] Using default format")

                # Create placeholder with MERGEFIELD structure
                placeholder_run = self._create_run_with_format(target_para, original_rpr, placeholder_text)
                print(f"[DEBUG] Created placeholder run: {placeholder_run.text}")

                # Convert to MERGEFIELD structure
                fld = OxmlElement('w:fldSimple')
                fld.set(qn('w:instr'), f' MERGEFIELD {field_name} \\* MERGEFORMAT \\z "" ')
                print(f"[DEBUG] Created fldSimple element")

                # Move the run element into fldSimple
                fld.append(placeholder_run._element)
                print(f"[DEBUG] Appended run to fldSimple")

                # Insert at the beginning of paragraph
                p_element.insert(0, fld)
                print(f"[DEBUG] Inserted fldSimple at position 0")

                # IMPORTANT: Preserve paragraph alignment
                # Priority: current alignment > same cell alignment > previous paragraph alignment > default (left)

                # If current paragraph has no alignment, try to find from same cell
                if current_alignment is None:
                    print(f"[DEBUG] Current paragraph has no alignment, looking in same cell...")
                    try:
                        # Find all paragraphs in the same table cell
                        # Get parent cell from paragraph element
                        # In Word XML: w:tbl/w:tr/w:tc/w:p
                        # We need to find the parent w:tc element
                        parent_tc = None
                        current = p_element
                        while current is not None:
                            if current.tag == f"{self.w_ns}tc":
                                parent_tc = current
                                break
                            current = current.getparent()

                        if parent_tc is not None:
                            print(f"[DEBUG] Found parent cell element")
                            # Find all paragraphs in this cell
                            cell_paras = parent_tc.findall(f"{self.w_ns}p")
                            print(f"[DEBUG] Cell has {len(cell_paras)} paragraphs")

                            # Look for first paragraph with alignment in this cell
                            for cell_para_xml in cell_paras:
                                if cell_para_xml == p_element:
                                    continue  # Skip current paragraph
                                cell_pPr = cell_para_xml.find(f"{self.w_ns}pPr")
                                if cell_pPr is not None:
                                    cell_jc = cell_pPr.find(f"{self.w_ns}jc")
                                    if cell_jc is not None:
                                        cell_jc_val = cell_jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                                        alignment_map = {
                                            "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
                                            "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
                                            "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
                                            "both": WD_PARAGRAPH_ALIGNMENT.JUSTIFY
                                        }
                                        cell_alignment = alignment_map.get(cell_jc_val)
                                        if cell_alignment is not None:
                                            original_alignment = cell_alignment
                                            print(f"[DEBUG] Found alignment in same cell: {cell_jc_val} -> {cell_alignment}")
                                            break
                    except Exception as e:
                        print(f"[DEBUG] Could not find alignment in same cell: {e}")

                final_alignment = current_alignment if current_alignment is not None else original_alignment
                if final_alignment is not None:
                    target_para.alignment = final_alignment
                    print(f"[DEBUG] Set paragraph alignment to: {final_alignment}")
                else:
                    print(f"[DEBUG] No alignment to set, using default")

                print(f"[DEBUG] Successfully inserted placeholder into empty paragraph")
                return True  # Early return for empty paragraph case

            # Non-zero offset in empty paragraph or other error cases
            raise RuntimeError(
                f"Offset {offset} not found in paragraph {paragraph_index}. "
                f"Paragraph text length: {total_text_length}, "
                f"Valid range: 0-{total_text_length}, "
                f"Text preview: '{para_preview}'"
            )

        # Get original format from target run
        target_run = target_run_info['run']
        original_rpr = target_run._r.get_or_add_rPr()

        # Calculate split position within the run
        split_pos = offset - target_run_info['start']
        text_before = target_run.text[:split_pos]
        text_after = target_run.text[split_pos:]

        # Create placeholder text
        placeholder_text = f"«{field_name}»"

        # Get paragraph element
        p_element = target_para._p
        run_element = target_run._element
        insert_index = list(p_element).index(run_element)

        # Store paragraph alignment before modification
        paragraph_alignment = target_para.alignment
        print(f"[DEBUG] Storing paragraph alignment: {paragraph_alignment}")

        # Find nearest format source (prefer text_before, then look for previous non-placeholder run)
        original_rpr = target_run._r.get_or_add_rPr()

        # If text_before is empty or is just whitespace, try to find format from previous run
        # Skip placeholder runs (runs with «...» format)
        if (not text_before or not text_before.strip()) and inherit_format:
            print(f"[DEBUG] text_before is empty/whitespace, looking for previous run format...")
            for i in range(len(run_text_map) - 1, -1, -1):
                prev_run_info = run_text_map[i]
                if prev_run_info['run'] == target_run:
                    continue

                # Check if this run contains placeholder markers
                run_text = prev_run_info['text'] or ''
                is_placeholder = '«' in run_text and '»' in run_text

                # Prefer non-placeholder runs with actual text content
                if not is_placeholder and run_text.strip():
                    prev_rpr = prev_run_info['run']._r.get_or_add_rPr()
                    if prev_rpr is not None and len(list(prev_rpr)) > 0:
                        original_rpr = prev_rpr
                        print(f"[DEBUG] Using format from previous non-placeholder run: {run_text[:30]}...")
                        break
                elif is_placeholder:
                    print(f"[DEBUG] Skipping placeholder run: {run_text[:30]}...")

        # Remove original run
        target_run.text = ""
        p_element.remove(run_element)

        try:
            # Insert text_before (keep original format)
            if text_before:
                new_run = self._create_run_with_format(target_para, original_rpr, text_before)
                p_element.insert(insert_index, new_run._element)
                insert_index += 1

            # Insert placeholder with MERGEFIELD structure
            # Use _create_run_with_format to properly inherit format from nearest text
            placeholder_run = self._create_run_with_format(target_para, original_rpr, placeholder_text)

            # Convert to MERGEFIELD structure
            fld = OxmlElement('w:fldSimple')
            fld.set(qn('w:instr'), f' MERGEFIELD {field_name} \\* MERGEFORMAT \\z "" ')

            # Move the run element into fldSimple
            fld.append(placeholder_run._element)

            # Insert placeholder
            p_element.insert(insert_index, fld)
            insert_index += 1

            # Insert text_after (keep original format)
            if text_after:
                new_run = self._create_run_with_format(target_para, original_rpr, text_after)
                p_element.insert(insert_index, new_run._element)

            # IMPORTANT: Restore paragraph alignment after modification
            # This ensures placeholder inherits the paragraph's alignment (center, right, etc.)
            if paragraph_alignment is not None:
                target_para.alignment = paragraph_alignment
                print(f"[DEBUG] Restored paragraph alignment to: {paragraph_alignment}")

        except Exception as e:
            raise RuntimeError(
                f"Failed to insert placeholder structure at offset {offset}: {type(e).__name__}: {str(e)}"
            )

        print(f"[SUCCESS] Inserted placeholder «{field_name}» at offset {offset} in paragraph {paragraph_index}")
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

        # Find target paragraph
        target_para = None
        total_paragraphs = 0
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            total_paragraphs += 1
            if p_idx == paragraph_index:
                target_para = paragraph
                break

        if not target_para:
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        # Build run text map (similar to insert_placeholder_at_offset)
        run_text_map = []
        current_offset = 0

        for run in target_para.runs:
            if run.text:
                text_len = len(run.text)
                run_text_map.append({
                    'run': run,
                    'start': current_offset,
                    'end': current_offset + text_len,
                    'text': run.text
                })
                current_offset += text_len

        # Find which run contains the offset
        target_run_info = None
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)

        # Special case: Empty paragraph
        if total_text_length == 0:
            # For empty paragraphs, only offset 0 is valid
            if offset != 0:
                print(f"[WARN] Offset {offset} requested for empty paragraph {paragraph_index}. Using offset 0 instead.")
                offset = 0

            # Create a new run for the empty paragraph
            if len(target_para.runs) == 0:
                # Paragraph has no runs at all, create one
                new_run = target_para.add_run("")
                target_run_info = {
                    'run': new_run,
                    'start': 0,
                    'end': 0,
                    'text': ''
                }
            else:
                # Use the first (empty) run
                target_run_info = {
                    'run': target_para.runs[0],
                    'start': 0,
                    'end': 0,
                    'text': target_para.runs[0].text or ''
                }
        else:
            # Normal case: Find run containing offset
            for run_info in run_text_map:
                if run_info['start'] <= offset <= run_info['end']:
                    target_run_info = run_info
                    break

            if not target_run_info:
                para_text = target_para.text
                para_preview = para_text[:50] + "..." if len(para_text) > 50 else para_text
                raise RuntimeError(
                    f"Offset {offset} not found in paragraph {paragraph_index}. "
                    f"Paragraph text length: {total_text_length}, "
                    f"Valid range: 0-{total_text_length}, "
                    f"Text preview: '{para_preview}'"
                )

        # Get original format from target run
        target_run = target_run_info['run']
        original_rpr = target_run._r.get_or_add_rPr()

        # Calculate split position within the run
        split_pos = offset - target_run_info['start']
        text_before = target_run.text[:split_pos]
        text_after = target_run.text[split_pos:]

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
        print(f"[DEBUG] add_page_break_at_cursor called: block_index={block_index}, offset={offset}")

        # Build block index map if not exists
        self._build_block_index_map()

        # Get paragraph from block index
        if block_index not in self._block_to_para_index_map:
            print(f"[ERROR] Block index {block_index} not found in map")
            return False

        block_info = self._block_to_para_index_map[block_index]
        if block_info['type'] != 'paragraph':
            print(f"[ERROR] Block {block_index} is not a paragraph")
            return False

        source_para = block_info['paragraph']
        source_element = source_para._element

        print(f"[DEBUG] Found paragraph: '{source_para.text[:50]}...'")

        # Get plain text without placeholders for offset calculation
        plain_text = source_para.text
        print(f"[DEBUG] Plain text length: {len(plain_text)}, offset: {offset}")

        # Validate offset
        if offset < 0 or offset > len(plain_text):
            print(f"[ERROR] Offset {offset} out of range [0, {len(plain_text)}]")
            return False

        # If offset is at beginning, insert page break before this paragraph
        if offset == 0:
            print(f"[DEBUG] Offset at beginning, inserting page break before paragraph")
            break_para = self.doc.add_paragraph()
            break_run = break_para.add_run()
            break_run.add_break(WD_BREAK.PAGE)

            # Move page break BEFORE this paragraph (not after!)
            source_element.addprevious(break_para._element)

            # CRITICAL FIX: Rebuild block index map after modifying document structure
            self._block_to_para_index_map = None
            self._build_block_index_map()

            return True

        # If offset is at end (after last character), insert page break after this paragraph
        if offset >= len(plain_text):
            print(f"[DEBUG] Offset at end ({offset} >= {len(plain_text)}), inserting page break at end of paragraph")
            break_run = source_para.add_run()
            break_run.add_break(WD_BREAK.PAGE)

            # CRITICAL FIX: Rebuild block index map after modifying document structure
            self._block_to_para_index_map = None
            self._build_block_index_map()

            return True

        # Split paragraph at offset using lxml (minimax-docx best practice)
        print(f"[DEBUG] Splitting paragraph at offset {offset}")

        # Calculate position in runs
        current_offset = 0
        split_run_index = None
        split_within_run = None

        for i, run in enumerate(source_para.runs):
            run_text = run.text if run.text else ""
            run_length = len(run_text)

            if current_offset + run_length >= offset:
                split_run_index = i
                split_within_run = offset - current_offset
                break

            current_offset += run_length

        if split_run_index is None:
            print(f"[ERROR] Could not find split position")
            return False

        print(f"[DEBUG] Split at run {split_run_index}, within run offset: {split_within_run}")

        # Split the run at position
        target_run = source_para.runs[split_run_index]
        original_text = target_run.text

        if original_text:
            before_text = original_text[:split_within_run]
            after_text = original_text[split_within_run:]

            # Modify original run to contain only "before" part
            target_run.text = before_text

            # Create new paragraph for "after" part
            after_para_element = copy.deepcopy(source_element)

            # Clear runs in after paragraph and rebuild with "after" content
            after_para = Paragraph(after_para_element, self.doc)
            for run in after_para.runs:
                run._element.getparent().remove(run._element)

            # Add split run and remaining runs to after paragraph
            if after_text:
                new_run = after_para.add_run(after_text)
                # Copy formatting from original run
                self._copy_run_formatting(target_run, new_run)

            # Add remaining runs from source paragraph
            for i in range(split_run_index + 1, len(source_para.runs)):
                original_run = source_para.runs[i]
                new_run = after_para.add_run(original_run.text)
                self._copy_run_formatting(original_run, new_run)

            # Remove split and remaining runs from source paragraph
            runs_to_remove = list(source_para.runs)[split_run_index + 1:]
            for run in runs_to_remove:
                run._element.getparent().remove(run._element)

            # Insert page break run at end of source paragraph
            break_run = source_para.add_run()
            break_run.add_break(WD_BREAK.PAGE)

            # Insert after paragraph after source paragraph
            source_element.addnext(after_para_element)

            print(f"[DEBUG] Paragraph split successfully")

            # CRITICAL FIX: Rebuild block index map after modifying document structure
            # This ensures subsequent operations use correct block → paragraph mapping
            self._block_to_para_index_map = None  # Clear cached map
            self._build_block_index_map()  # Rebuild with new structure

            return True
        else:
            print(f"[ERROR] Target run has no text")
            return False

    def add_image(self, image_path: str, position: str = "end", after_text: str = None, width: float = 4.0):
        """
        Thêm hình ảnh

        Args:
            image_path: Đường dẫn tới file ảnh
            position: "end", "after:text"
            after_text: Text đích
            width: Chiều rộng (inches)
        """
        print(f"[DEBUG] add_image called: position={position}, width={width}")

        if position == "end":
            # Get last paragraph to inherit formatting
            last_para = None
            for para in self.doc.paragraphs:
                if para.text.strip():
                    last_para = para

            # Create paragraph with image
            image_para = self.doc.add_paragraph()
            image_para.add_picture(image_path, width=Inches(width))

            # Inherit formatting from last paragraph
            if last_para:
                image_para.alignment = last_para.alignment
                image_para.paragraph_format.space_before = last_para.paragraph_format.space_before
                image_para.paragraph_format.space_after = last_para.paragraph_format.space_after
                image_para.paragraph_format.line_spacing = last_para.paragraph_format.line_spacing

                if last_para.runs:
                    source_run = None
                    for run in reversed(last_para.runs):
                        if run.text and run.text.strip():
                            source_run = run
                            break

                    if not source_run and last_para.runs:
                        source_run = last_para.runs[0]

                    if source_run:
                        for new_run in image_para.runs:
                            self._copy_run_formatting(source_run, new_run)
                        print(f"[DEBUG] Copied formatting for image paragraph")

        elif position.startswith("after:"):
            target_text = position.split("after:")[1].strip()
            for i, paragraph in enumerate(self.doc.paragraphs):
                if target_text in paragraph.text:
                    print(f"[DEBUG] Found target paragraph for image at index {i}")

                    if i < len(self.doc.paragraphs) - 1:
                        # Add to next paragraph
                        next_para = self.doc.paragraphs[i + 1]
                        next_para.add_picture(image_path, width=Inches(width))
                        print(f"[DEBUG] Added image to next paragraph")
                    else:
                        # Add new paragraph with image, inheriting from current
                        new_para = self.doc.add_paragraph()
                        new_para.add_picture(image_path, width=Inches(width))

                        # Inherit formatting from current paragraph
                        new_para.alignment = paragraph.alignment
                        new_para.paragraph_format.space_before = paragraph.paragraph_format.space_before
                        new_para.paragraph_format.space_after = paragraph.paragraph_format.space_after
                        new_para.paragraph_format.line_spacing = paragraph.paragraph_format.line_spacing

                        if paragraph.runs:
                            source_run = None
                            for run in reversed(paragraph.runs):
                                if run.text and run.text.strip():
                                    source_run = run
                                    break

                            if not source_run and paragraph.runs:
                                source_run = paragraph.runs[0]

                            if source_run:
                                for new_run in new_para.runs:
                                    self._copy_run_formatting(source_run, new_run)
                                print(f"[DEBUG] Copied formatting for new image paragraph")

                    return True
        return False

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

        # Find target paragraph
        target_para = None
        total_paragraphs = 0
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            total_paragraphs += 1
            if p_idx == paragraph_index:
                target_para = paragraph
                break

        if not target_para:
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        # Build run text map (similar to insert_placeholder_at_offset)
        run_text_map = []
        current_offset = 0

        for run in target_para.runs:
            if run.text:
                text_len = len(run.text)
                run_text_map.append({
                    'run': run,
                    'start': current_offset,
                    'end': current_offset + text_len,
                    'text': run.text
                })
                current_offset += text_len

        # Find which run contains the offset
        target_run_info = None
        total_text_length = sum(run_info['end'] - run_info['start'] for run_info in run_text_map)

        # Special case: empty paragraph - create a new run
        if total_text_length == 0:
            if offset == 0:
                # Empty paragraph, offset 0 is valid - create a new run
                target_run = target_para.add_run("")
                target_run_info = {
                    'run': target_run,
                    'start': 0,
                    'end': 0,
                    'text': ''
                }
                text_before = ""
                text_after = ""
            else:
                raise RuntimeError(
                    f"Offset {offset} not found in empty paragraph {paragraph_index}. "
                    f"Valid range: 0-0"
                )
        else:
            # Non-empty paragraph - find the run containing offset
            for run_info in run_text_map:
                if run_info['start'] <= offset <= run_info['end']:
                    target_run_info = run_info
                    break

            if not target_run_info:
                para_text = target_para.text
                para_preview = para_text[:50] + "..." if len(para_text) > 50 else para_text
                raise RuntimeError(
                    f"Offset {offset} not found in paragraph {paragraph_index}. "
                    f"Paragraph text length: {total_text_length}, "
                    f"Valid range: 0-{total_text_length}, "
                    f"Text preview: '{para_preview}'"
                )

        # Get original format from target run
        target_run = target_run_info['run']
        original_rpr = target_run._r.get_or_add_rPr()

        # Calculate split position and text_before/after (only for non-empty case)
        if total_text_length > 0:
            # Calculate split position within the run
            split_pos = offset - target_run_info['start']
            text_before = target_run.text[:split_pos]
            text_after = target_run.text[split_pos:]

            # Update original run to only contain text_before
            target_run.text = text_before

        # Find the document body
        doc_element = self.doc._element.body
        p_element = target_para._p

        # Find the index of the paragraph element in body
        para_index_in_doc = list(doc_element).index(p_element)

        # Create new paragraph for image (AFTER target paragraph)
        image_paragraph = self.doc.add_paragraph()

        # Copy paragraph-level formatting from target paragraph
        image_paragraph.alignment = target_para.alignment
        image_paragraph.paragraph_format.space_before = target_para.paragraph_format.space_before
        image_paragraph.paragraph_format.space_after = target_para.paragraph_format.space_after
        image_paragraph.paragraph_format.line_spacing = target_para.paragraph_format.line_spacing

        # Add picture to the new paragraph
        try:
            image_run = image_paragraph.add_run()
            image_run.add_picture(image_path, width=Inches(width))

            # Copy run formatting from target paragraph if available
            if target_para.runs:
                source_run = None
                for run in reversed(target_para.runs):
                    if run.text and run.text.strip():
                        source_run = run
                        break

                if not source_run and target_para.runs:
                    source_run = target_para.runs[0]

                if source_run:
                    # Find the run that contains the picture (it's the first run we just added)
                    for run in image_paragraph.runs:
                        if run != image_run:  # Don't copy to the image run itself
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

            # Copy paragraph-level formatting from target paragraph
            text_paragraph.alignment = target_para.alignment
            text_paragraph.paragraph_format.space_before = target_para.paragraph_format.space_before
            text_paragraph.paragraph_format.space_after = target_para.paragraph_format.space_after
            text_paragraph.paragraph_format.line_spacing = target_para.paragraph_format.line_spacing

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

    def edit_table_cell(
        self,
        table_index: int,
        row_index: int,
        col_index: int,
        new_text: str
    ):
        """Edit text trong table cell"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        if row_index >= len(table.rows):
            return False

        row = table.rows[row_index]
        if col_index >= len(row.cells):
            return False

        cell = row.cells[col_index]

        # Tìm paragraph đầu tiên có run
        for paragraph in cell.paragraphs:
            if len(paragraph.runs) > 0:
                # Found a run, update its text
                paragraph.runs[0].text = new_text
                return True
            else:
                # Paragraph exists but has no runs (edge case)
                # Add a new run with the text

                r = OxmlElement('w:r')
                t = OxmlElement('w:t')
                t.set(qn('xml:space'), 'preserve')
                t.text = new_text
                r.append(t)
                paragraph._element.append(r)
                return True

        # No paragraphs found (shouldn't happen with properly formatted cells)
        return False

    def add_table_row(self, table_index: int):
        """Thêm row vào table"""
        if table_index >= len(self.doc.tables):
            return False

        table = self.doc.tables[table_index]
        table.add_row()
        return True

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
            # Lấy hoặc tạo tcPr (table cell properties)
            tc_pr = cell._element.get_or_add_tcPr()

            # Background color
            if 'background_color' in format_options:
                bg_color = format_options['background_color']
                if bg_color and bg_color != 'auto':

                    # Tạo hoặc cập nhật shd element (shading)
                    shd = tc_pr.find(qn('w:shd'))
                    if shd is None:
                        shd = OxmlElement('w:shd')
                        tc_pr.append(shd)

                    # Parse màu hex
                    if bg_color.startswith('#'):
                        hex_color = bg_color.lstrip('#')
                        shd.set(qn('w:fill'), hex_color)
                    else:
                        shd.set(qn('w:fill'), bg_color)

            # Vertical alignment
            if 'vertical_align' in format_options:
                v_align = format_options['vertical_align']
                if v_align in ['top', 'center', 'bottom']:


                    # Tạo hoặc cập nhật vAlign element
                    v_align_element = tc_pr.find(qn('w:vAlign'))
                    if v_align_element is None:
                        v_align_element = OxmlElement('w:vAlign')
                        tc_pr.append(v_align_element)

                    v_align_element.set(qn('w:val'), v_align)

            # Horizontal alignment (NEW)
            if 'horizontal_align' in format_options:
                h_align = format_options['horizontal_align']
                if h_align in ['left', 'center', 'right']:

                    # Map alignment string to WD_PARAGRAPH_ALIGNMENT enum
                    alignment_map = {
                        'left': WD_PARAGRAPH_ALIGNMENT.LEFT,
                        'center': WD_PARAGRAPH_ALIGNMENT.CENTER,
                        'right': WD_PARAGRAPH_ALIGNMENT.RIGHT
                    }

                    alignment_value = alignment_map.get(h_align)
                    if alignment_value is not None:
                        # Apply horizontal alignment to ALL paragraphs in the cell
                        for para in cell.paragraphs:
                            para.alignment = alignment_value

            # Borders (optional)
            if 'borders' in format_options:
                borders = format_options['borders']
                self._apply_cell_borders(tc_pr, borders)

            return True

        except Exception as e:
            print(f"Error formatting cell: {str(e)}")
            return False

    def _apply_cell_borders(self, tc_pr, borders: dict):
        """Apply borders to table cell"""
        # Tạo hoặc lấy tcBorders element
        tc_borders = tc_pr.find(qn('w:tcBorders'))
        if tc_borders is None:
            tc_borders = OxmlElement('w:tcBorders')
            tc_pr.append(tc_borders)

        # Áp dụng border cho từng phía
        for side in ['top', 'bottom', 'left', 'right']:
            if side in borders:
                border_config = borders[side]

                # Tạo border element
                border = OxmlElement(f'w:{side}')

                # Border style
                border_style = border_config.get('style', 'single')
                border.set(qn('w:val'), border_style)

                # Border size (in eighth points)
                border_size = border_config.get('size', 4)
                border.set(qn('w:sz'), str(border_size))

                # Border color
                border_color = border_config.get('color', 'auto')
                if border_color.startswith('#'):
                    border_color = border_color.lstrip('#')
                border.set(qn('w:color'), border_color)

                # Thêm hoặc replace border
                existing_border = tc_borders.find(qn(f'w:{side}'))
                if existing_border is not None:
                    tc_borders.replace(existing_border, border)
                else:
                    tc_borders.append(border)

    # ===== UTILITY FUNCTIONS =====

    def _parse_color(self, color: str) -> RGBColor:
        """Parse color string to RGBColor"""
        if color.startswith("#"):
            # Hex color
            hex_color = color.lstrip("#")
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            return RGBColor(*rgb)
        elif color.startswith("rgb"):
            # RGB color format: rgb(r, g, b) or rgba(r, g, b, a)
            import re
            rgb_match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', color)
            if rgb_match:
                r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
                return RGBColor(r, g, b)
            else:
                # If RGB parsing fails, default to black
                return RGBColor(0, 0, 0)
        else:
            # Named color
            color_map = {
                "red": RGBColor(255, 0, 0),
                "green": RGBColor(0, 255, 0),
                "blue": RGBColor(0, 0, 255),
                "yellow": RGBColor(255, 255, 0),
                "orange": RGBColor(255, 165, 0),
                "purple": RGBColor(128, 0, 128),
                "black": RGBColor(0, 0, 0),
                "white": RGBColor(255, 255, 255),
                "gray": RGBColor(128, 128, 128),
            }
            return color_map.get(color.lower(), RGBColor(0, 0, 0))

    def _parse_highlight_color(self, color: str) -> str:
        """Parse highlight color to WD_COLOR or hex value

        Args:
            color: Color as hex (e.g., "#ffffff", "#FFFF00") or name (e.g., "yellow")

        Returns:
            WD_COLOR constant or hex color string
        """
        # Handle named colors
        color_map = {
            "yellow": "YELLOW",
            "red": "RED",
            "blue": "BLUE",
            "green": "GREEN",
            "orange": "ORANGE",
            "gray": "GRAY",
            "#ffff00": "YELLOW",
            "#ff0000": "RED",
            "#0000ff": "BLUE",
            "#00ff00": "GREEN",
            "#ffa500": "ORANGE",
            "#808080": "GRAY",
        }

        # Normalize input
        color_lower = color.lower().strip()

        # Check if it's a named color or known hex
        if color_lower in color_map:
            return color_map[color_lower]

        # Handle hex colors - convert to uppercase and remove #
        if color_lower.startswith("#"):
            hex_color = color_lower[1:].upper()

            # Word supports limited highlight colors, but we can try to use shd fill instead
            # For custom colors, we should use shd element with fill attribute
            # Return the hex color for use with shd element
            return hex_color

        # Fallback for unknown colors
        return color_map.get(color_lower, "YELLOW")

    def find_text_occurrences(self, text: str) -> List[Dict]:
        """
        Tìm tất cả occurrences của text trong document

        Returns:
            List of {paragraph_index, run_index, text, context}
        """
        occurrences = []

        for p_idx, paragraph in enumerate(self.doc.paragraphs):
            for r_idx, run in enumerate(paragraph.runs):
                if text in run.text:
                    occurrences.append({
                        "paragraph_index": p_idx,
                        "run_index": r_idx,
                        "text": run.text,
                        "context": paragraph.text
                    })

        # Tables
        for t_idx, table in enumerate(self.doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    for p_idx, paragraph in enumerate(cell.paragraphs):
                        for r_idx, run in enumerate(paragraph.runs):
                            if text in run.text:
                                occurrences.append({
                                    "table_index": t_idx,
                                    "row_index": row_idx,
                                    "cell_index": cell_idx,
                                    "paragraph_index": p_idx,
                                    "run_index": r_idx,
                                    "text": run.text,
                                    "context": paragraph.text
                                })

        return occurrences

    # ===== SAVE =====

    def save(self, output_path: str = None):
        """Lưu document"""
        if output_path is None:
            output_path = self.doc_path
        self.doc.save(output_path)
        return output_path

    def save_copy(self, output_path: str):
        """Lưu bản copy (giữ nguyên original)"""
        self.doc.save(output_path)
        return output_path

    # ===== FORMAT EXTRACTION =====

    def get_format_at_position(
        self,
        text: str,
        paragraph_index: int = None
    ) -> Optional[Dict]:
        """
        Extract formatting information for text at a specific position
        NOW SUPPORTS extracting format from hyperlink text

        Args:
            text: Text to extract format from
            paragraph_index: Index of paragraph containing the text (optional, for precision)

        Returns:
            Dict with format info or None if not found:
            {
                'bold': bool,
                'italic': bool,
                'underline': str (none/single/double/dotted/dash/dashDot/dashDotDot/double/wave),
                'color': str (hex, e.g., 'FF0000'),
                'highlight': str (hex, e.g., 'FFFF00'),
                'font_size': int (points, e.g., 12),
                'font_name': str,
                'superscript': bool,
                'subscript': bool
            }
        """
        # Normalize search text for matching
        search_text_normalized = self._normalize_text(text)

        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            if paragraph_index is not None and p_idx != paragraph_index:
                continue

            # Use new helper to extract ALL runs including hyperlinks
            all_runs = self._extract_all_text_runs(paragraph)
            full_text = "".join(run_info['text'] for run_info in all_runs)
            full_text_normalized = self._normalize_text(full_text)

            if search_text_normalized not in full_text_normalized:
                continue

            # Find position in normalized text
            start_idx_normalized = full_text_normalized.find(search_text_normalized)
            if start_idx_normalized == -1:
                continue

            end_idx_normalized = start_idx_normalized + len(search_text_normalized)

            # Map normalized position back to original text position
            # by counting non-whitespace characters
            char_count = 0
            non_ws_count = 0
            start_idx_original = None
            end_idx_original = None

            for char in full_text:
                if char.isspace():
                    # Whitespace character - skip counting but increment char_count
                    pass
                else:
                    # Non-whitespace character
                    if start_idx_original is None and non_ws_count == start_idx_normalized:
                        start_idx_original = char_count
                    if non_ws_count == end_idx_normalized - 1:
                        end_idx_original = char_count + 1
                        break
                    non_ws_count += 1
                char_count += 1

            # If end_idx_original is still None, set it to the end of the text
            if end_idx_original is None and start_idx_original is not None:
                end_idx_original = len(full_text)

            # Fallback: if mapping failed, try direct search in original text
            if start_idx_original is None or end_idx_original is None:
                start_idx_original = full_text.find(text)
                if start_idx_original != -1:
                    end_idx_original = start_idx_original + len(text)
                else:
                    # Try finding the search text in the runs directly
                    for run_info in all_runs:
                        if search_text_normalized in self._normalize_text(run_info['text']):
                            return self._extract_run_format(run_info['run'])
                    continue

            # Find runs containing the text using original positions
            formats_found = []

            for run_info in all_runs:
                run_start = run_info['start_offset']
                run_end = run_info['end_offset']

                # Check if this run overlaps with the target text range
                if run_end > start_idx_original and run_start < end_idx_original:
                    # This run contains part of the target text
                    # Only extract format from runs that have actual text content
                    if run_info['text'].strip():
                        format_info = self._extract_run_format(run_info['run'])
                        formats_found.append(format_info)

            if formats_found:
                # Return format from the first non-empty run with actual content
                for fmt in formats_found:
                    if fmt:
                        return fmt

                return formats_found[0]

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
        target_para = None
        total_paragraphs = 0
        for p_idx, paragraph in enumerate(self._iterate_paragraphs_in_doc_order()):
            total_paragraphs += 1
            if p_idx == paragraph_index:
                target_para = paragraph
                break

        if not target_para:
            raise RuntimeError(f"Paragraph {paragraph_index} not found (document has {total_paragraphs} paragraphs)")

        # Build run text map
        run_text_map = []
        current_offset = 0
        for run in target_para.runs:
            run_text = run.text
            if run_text:
                run_text_map.append({
                    'run': run,
                    'start': current_offset,
                    'end': current_offset + len(run_text),
                    'text': run_text
                })
                current_offset += len(run_text)

        # Find all runs that overlap with selection [start_offset, end_offset]
        affected_runs = []
        for run_info in run_text_map:
            if run_info['end'] > start_offset and run_info['start'] < end_offset:
                affected_runs.append(run_info)

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
        for i, run_info in enumerate(reversed(affected_runs)):
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

            # Get current position in paragraph (before modifications)
            run_elements = list(p_element.findall(qn('w:r')))
            try:
                run_index = run_elements.index(run._element)
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
                before_run = OxmlElement('w:r')

                # Copy original formatting
                if original_rpr is not None:
                    before_rpr = copy.deepcopy(original_rpr)
                    before_run.append(before_rpr)

                # Add before text
                before_t = OxmlElement('w:t')
                before_t.set(qn('xml:space'), 'preserve')
                before_t.text = before_text
                before_run.append(before_t)

                # Insert before hyperlink
                p_element.insert(insert_offset, before_run)
                insert_offset += 1

            # 2. Insert hyperlink with selected text
            hyperlink = OxmlElement('w:hyperlink')
            hyperlink.set(qn('r:id'), r_id)

            # Create run for hyperlink text with original formatting + hyperlink style
            hyperlink_run = OxmlElement('w:r')

            # Copy original formatting
            if original_rpr is not None:
                hyperlink_rpr = copy.deepcopy(original_rpr)

                # Add hyperlink style (blue and underlined)
                color = OxmlElement('w:color')
                color.set(qn('w:val'), '0000FF')
                hyperlink_rpr.append(color)

                underline = OxmlElement('w:u')
                underline.set(qn('w:val'), 'single')
                hyperlink_rpr.append(underline)

                hyperlink_run.append(hyperlink_rpr)
            else:
                # No original formatting, add basic hyperlink style
                hyperlink_rpr = OxmlElement('w:rPr')

                color = OxmlElement('w:color')
                color.set(qn('w:val'), '0000FF')
                hyperlink_rpr.append(color)

                underline = OxmlElement('w:u')
                underline.set(qn('w:val'), 'single')
                hyperlink_rpr.append(underline)

                hyperlink_run.append(hyperlink_rpr)

            # Add selected text
            t = OxmlElement('w:t')
            t.set(qn('xml:space'), 'preserve')
            t.text = selected_text
            hyperlink_run.append(t)

            hyperlink.append(hyperlink_run)

            # Insert hyperlink
            p_element.insert(insert_offset, hyperlink)
            insert_offset += 1

            # 3. Insert "after" text run (if not empty)
            if after_text:
                after_run = OxmlElement('w:r')

                # Copy original formatting
                if original_rpr is not None:
                    after_rpr = copy.deepcopy(original_rpr)
                    after_run.append(after_rpr)

                # Add after text
                after_t = OxmlElement('w:t')
                after_t.set(qn('xml:space'), 'preserve')
                after_t.text = after_text
                after_run.append(after_t)

                # Insert after hyperlink
                p_element.insert(insert_offset, after_run)

        return True