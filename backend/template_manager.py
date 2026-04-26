"""
Mail Merge Processor - Uses SmartMailMergeConverter for Vietnamese forms
"""
import uuid
import re
from pathlib import Path
from typing import Dict
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
import copy
from smart_mail_merge_converter import PLACEHOLDER_PATTERN, SmartMailMergeConverter
from gemini_client import GeminiClient
from docx_editor import DocxFullEditor


class MailMergeProcessor:
    """Convert .docx to Mail Merge template using SmartMailMergeConverter"""

    def __init__(self, gemini_api_key: str = None, timeout: int = 30):
        """Initialize processor

        Args:
            gemini_api_key: Gemini API key for smart field naming (optional)
            timeout: Not used, kept for backward compatibility
        """
        self.w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        self.gemini_client = GeminiClient(gemini_api_key) if gemini_api_key else None

    def _extract_xml_text(self, element) -> str:
        """Extract and normalize all text nodes from a Word XML element."""
        if element is None:
            return ""

        text_parts = []
        for t in element.findall(f".//{self.w_ns}t"):
            if t.text:
                text_parts.append(t.text)
        return "".join(text_parts).strip()

    def _build_block_candidates(self, doc: Document) -> list:
        """Build a stable block list that matches structured extraction order."""
        candidates = []
        current_index = 0

        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                para = Paragraph(child, doc)
                text = self._extract_xml_text(child)

                candidates.append({
                    "type": "paragraph",
                    "index": current_index,
                    "text": text if text else "[EMPTY LINE]",
                    "para": para,
                    "is_empty": not text,
                })
                current_index += 1

            elif isinstance(child, CT_Tbl):
                table = Table(child, doc)
                table_has_content = False

                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        cell_text = "".join(
                            self._extract_xml_text(para._p) for para in cell.paragraphs
                        ).strip()

                        if cell_text:
                            table_has_content = True

                        candidates.append({
                            "type": "table_cell",
                            "index": current_index,
                            "text": cell_text if cell_text else "[EMPTY CELL]",
                            "table": table,
                            "row": row_idx,
                            "col": cell_idx,
                            "cell": cell,
                            "is_empty": not cell_text,
                        })
                        current_index += 1

                if table_has_content:
                    all_cells_text = []
                    for row in table.rows:
                        row_cells = []
                        for cell in row.cells:
                            cell_text = "".join(
                                self._extract_xml_text(para._p) for para in cell.paragraphs
                            ).strip()
                            row_cells.append(cell_text)
                        all_cells_text.append(row_cells)

                    table_text = "\n".join(
                        [" | ".join(row) for row in all_cells_text if any(cell.strip() for cell in row)]
                    )
                    candidates.append({
                        "type": "table_summary",
                        "index": current_index,
                        "text": table_text,
                        "table": table,
                    })
                    current_index += 1

        return candidates

    def _add_neighbor_context(self, blocks: list, window: int = 2) -> None:
        """Attach before/after context snippets to each block in-place."""
        for i, block in enumerate(blocks):
            block["before_context"] = [blocks[j]["text"][:50] for j in range(max(0, i - window), i)]
            block["after_context"] = [blocks[j]["text"][:50] for j in range(i + 1, min(len(blocks), i + window + 1))]

    def _word_border_to_css(self, border) -> str:
        """Convert a Word border element to a CSS border declaration.

        Returns:
            CSS border string, "__NONE__" when the border is explicitly disabled,
            or None when no border element is present.
        """
        if border is None:
            return None

        border_val = border.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "single")
        if border_val in ["none", "nil", ""]:
            return "__NONE__"

        border_style_map = {
            "single": "solid",
            "double": "double",
            "dashed": "dashed",
            "dotted": "dotted",
            "dashSmallGap": "dashed",
            "dotDash": "dashed",
            "dotDotDash": "dotted",
            "thick": "solid",
        }
        css_style = border_style_map.get(border_val, "solid")

        border_sz = border.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}sz", "4")
        try:
            css_width = max(1, int(border_sz) // 6) if border_sz else 1
        except (TypeError, ValueError):
            css_width = 1

        border_color = border.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}color", "000000")
        if border_color and not border_color.startswith("#"):
            border_color = f"#{border_color}"

        return f"{css_width}px {css_style} {border_color or '#000000'}"

    def _get_table_borders(self, table) -> Dict[str, object]:
        """Extract tblBorders from a table, if present."""
        table_borders = {}
        try:
            tbl_pr = table._element.find(f"{self.w_ns}tblPr")
            if tbl_pr is None:
                return table_borders

            tbl_borders = tbl_pr.find(f"{self.w_ns}tblBorders")
            if tbl_borders is None:
                return table_borders

            for side in ["top", "bottom", "left", "right", "insideH", "insideV"]:
                border = tbl_borders.find(f"{self.w_ns}{side}")
                if border is not None:
                    table_borders[side] = border
        except Exception as e:
            print(f"[_get_table_borders] Error extracting table borders: {e}")

        return table_borders

    def _get_cell_border_css(
        self,
        tc_pr,
        table_borders: Dict[str, object],
        side: str,
        row_idx: int,
        col_idx: int,
        last_row_idx: int,
        last_col_idx: int,
    ) -> str:
        """Resolve the effective border for one cell side."""
        tc_borders = tc_pr.find(f"{self.w_ns}tcBorders") if tc_pr is not None else None
        if tc_borders is not None:
            direct_border = tc_borders.find(f"{self.w_ns}{side}")
            css_border = self._word_border_to_css(direct_border)
            if css_border == "__NONE__":
                return "none"
            if css_border:
                return css_border

        table_border = None
        if side == "top":
            table_border = table_borders.get("top") if row_idx == 0 else table_borders.get("insideH")
        elif side == "bottom":
            table_border = table_borders.get("bottom") if row_idx == last_row_idx else table_borders.get("insideH")
        elif side == "left":
            table_border = table_borders.get("left") if col_idx == 0 else table_borders.get("insideV")
        elif side == "right":
            table_border = table_borders.get("right") if col_idx == last_col_idx else table_borders.get("insideV")

        res = self._word_border_to_css(table_border)
        return "none" if res == "__NONE__" else res

    def _calculate_rowspan(self, table, start_row_idx: int, col_idx: int) -> int:
        """Calculate rowspan for a vertically merged cell.

        Counts how many consecutive rows have vMerge="continue" at the same column
        starting from the row after start_row_idx.

        Args:
            table: docx Table object
            start_row_idx: Row index where vMerge="restart" is found
            col_idx: Column index of the merged cell

        Returns:
            Number of rows spanned (minimum 1)
        """
        rowspan = 1
        total_rows = len(table.rows)

        for row_idx in range(start_row_idx + 1, total_rows):
            if row_idx >= total_rows:
                break
            row = table.rows[row_idx]
            cell, _, _ = self._find_row_cell_at_column(row, col_idx)
            try:
                if cell is not None:
                    tcPr = cell._element.find(f"{self.w_ns}tcPr")
                    if tcPr is not None:
                        vmerge_elem = tcPr.find(f"{self.w_ns}vMerge")
                        if vmerge_elem is not None:
                            vmerge_val = vmerge_elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "continue")
                            if vmerge_val == "continue":
                                rowspan += 1
                            else:
                                # Found "restart" or no vMerge, vertical merge ends
                                break
                        else:
                            # No vMerge element, vertical merge ends
                            break
                    else:
                        # No tcPr, vertical merge ends
                        break
                else:
                    # Column index out of range
                    break
            except Exception as e:
                print(f"[_calculate_rowspan] Error checking row {row_idx}: {e}")
                break

        return rowspan

    def _iter_xml_row_cells(self, row):
        """Yield actual XML cells in a row without python-docx merge expansion."""
        return [_Cell(tc, row) for tc in row._tr.tc_lst]

    def _get_cell_grid_span(self, cell) -> int:
        tcPr = cell._element.find(f"{self.w_ns}tcPr")
        if tcPr is None:
            return 1

        grid_span_elem = tcPr.find(f"{self.w_ns}gridSpan")
        if grid_span_elem is None:
            return 1

        grid_span_val = grid_span_elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
        if not grid_span_val:
            return 1

        try:
            return max(1, int(grid_span_val))
        except (TypeError, ValueError):
            return 1

    def _find_row_cell_at_column(self, row, logical_col_idx: int):
        """Resolve a logical column index to the backing XML cell in that row."""
        current_col = 0
        for cell in self._iter_xml_row_cells(row):
            colspan = self._get_cell_grid_span(cell)
            if current_col <= logical_col_idx < current_col + colspan:
                return cell, current_col, colspan
            current_col += colspan
        return None, None, None

    def _get_vertical_merge_value(self, cell):
        tcPr = cell._element.find(f"{self.w_ns}tcPr")
        if tcPr is None:
            return None

        vmerge_elem = tcPr.find(f"{self.w_ns}vMerge")
        if vmerge_elem is None:
            return None

        return vmerge_elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "continue")

    def _iter_visible_table_cells(self, table):
        """Yield visible table cells with logical column and merge metadata."""
        for row_idx, row in enumerate(table.rows):
            logical_col_idx = 0
            for cell_idx, cell in enumerate(self._iter_xml_row_cells(row)):
                colspan = self._get_cell_grid_span(cell)
                vmerge_val = self._get_vertical_merge_value(cell)
                if vmerge_val == "continue":
                    logical_col_idx += colspan
                    continue

                rowspan = self._calculate_rowspan(table, row_idx, logical_col_idx) if vmerge_val == "restart" else 1
                yield {
                    "row_idx": row_idx,
                    "row": row,
                    "cell_idx": cell_idx,
                    "cell": cell,
                    "col_idx": logical_col_idx,
                    "colspan": colspan,
                    "rowspan": rowspan,
                }
                logical_col_idx += colspan

    def _get_row_style(self, row, row_idx: int) -> str:
        row_style = ""
        try:
            trPr = row._element.find(f"{self.w_ns}trPr")
            if trPr is None:
                return row_style

            tr_height = trPr.find(f"{self.w_ns}trHeight")
            if tr_height is None:
                return row_style

            h_val = tr_height.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
            if not h_val:
                return row_style

            h_rule = trPr.find(f"{self.w_ns}hRule")
            h_rule_val = h_rule.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") if h_rule is not None else None
            height_px = int(h_val) / 15

            if h_rule_val == "exact":
                row_style += f" height: {height_px}px;"
                print(f"[_process_table_to_html] Row {row_idx} exact height: {h_val} twips ≈ {height_px}px")
            else:
                row_style += f" min-height: {height_px}px;"
                label = "min-height" if h_rule_val == "atLeast" else "auto height"
                print(f"[_process_table_to_html] Row {row_idx} {label}: {h_val} twips ≈ {height_px}px")
        except Exception as e:
            print(f"[_process_table_to_html] Error extracting row {row_idx} height: {e}")
        return row_style

    def _build_table_cell_paragraphs_html(self, cell, col_idx: int, block_index: int):
        cell_text_parts = []
        cell_paragraphs_html = []

        for para_index, para in enumerate(cell.paragraphs):
            text_from_xml = "".join(
                t.text for t in para._p.findall(f".//{self.w_ns}t") if t.text
            )
            if text_from_xml:
                cell_text_parts.append(text_from_xml)

            para_content = "".join(self._process_xml_element_to_html(child) for child in para._p)
            para_metadata = f'data-para-in-cell="{para_index}" data-cell="{col_idx}" data-cell-block-index="{block_index}"'

            pPr = para._p.find(f"{self.w_ns}pPr")
            indent_styles = self._extract_paragraph_indentation_styles(pPr)
            jc = pPr.find(f"{self.w_ns}jc") if pPr is not None else None
            jc_val = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "left") if jc is not None else "left"
            css_align = {
                "left": "left",
                "center": "center",
                "right": "right",
                "both": "justify",
            }.get(jc_val, "left")

            if not para_content.strip():
                para_style_parts = [
                    "min-height: 1.2em",
                    "margin: 2px 0",
                    f"text-align: {css_align}",
                    "cursor: crosshair",
                ]
                if indent_styles:
                    para_style_parts.extend(indent_styles)
                para_style = "; ".join(para_style_parts) + ";"
                print(f"[_process_table_to_html] Empty Para[{para_index}] horizontal-align: {css_align} (PRESERVED)")
                cell_paragraphs_html.append(
                    f'<p {para_metadata} class="cell-paragraph" style="{para_style}" title="Click để thêm placeholder">&nbsp;</p>'
                )
                continue

            para_style_parts = ["margin: 2px 0"]
            if css_align != "left":
                para_style_parts.append(f"text-align: {css_align}")
            if indent_styles:
                para_style_parts.extend(indent_styles)

            text_content = re.sub(r'<[^>]+>', '', para_content)
            if text_content and (text_content[0] in ' \t\n' or text_content[-1] in ' \t\n'):
                para_style_parts.append("white-space: pre-wrap")

            para_style = "; ".join(para_style_parts) + ";"
            print(f"[_process_table_to_html] Para[{para_index}] horizontal-align: {css_align}")
            cell_paragraphs_html.append(
                f'<p {para_metadata} class="cell-paragraph" style="{para_style}">{para_content}</p>'
            )

        cell_text = "".join(cell_text_parts).strip()
        return "".join(cell_paragraphs_html) if cell_paragraphs_html else "&nbsp;", cell_text

    def _build_table_cell_style(
        self,
        cell,
        row_idx: int,
        cell_idx: int,
        col_idx: int,
        column_widths,
        table_borders,
        last_row_idx: int,
        last_col_idx: int,
    ) -> str:
        cell_style = "padding: 5px; font-weight: normal; font-style: normal; text-decoration: none; text-align: left;"

        if column_widths and col_idx < len(column_widths):
            cell_style += f" width: {column_widths[col_idx]};"

        try:
            tcPr = cell._element.find(f"{self.w_ns}tcPr")
            if tcPr is None:
                return cell_style

            shd = tcPr.find(f"{self.w_ns}shd")
            if shd is not None:
                fill = shd.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}fill")
                if fill and fill != "auto":
                    cell_style += f" background-color: #{fill};"
                    print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}] background: #{fill}")

            v_align = tcPr.find(f"{self.w_ns}vAlign")
            if v_align is not None:
                v_align_val = v_align.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "top")
                css_v_align = {"top": "top", "center": "middle", "bottom": "bottom"}.get(v_align_val, "top")
                cell_style += f" vertical-align: {css_v_align};"
                print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}] vertical-align: {css_v_align}")

            for side in ["top", "bottom", "left", "right"]:
                css_border = self._get_cell_border_css(
                    tcPr,
                    table_borders,
                    side,
                    row_idx,
                    cell_idx,
                    last_row_idx,
                    last_col_idx,
                )
                if css_border:
                    cell_style += f" border-{side}: {css_border};"
                    print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}] border-{side}: {css_border}")
        except Exception as e:
            print(f"[_process_table_to_html] Error extracting cell formatting: {e}")

        return cell_style

    def convert_to_mail_merge(self, docx_path: str, output_path: str = None, auto_fill_tables: bool = True) -> Dict:
        """Convert .docx to Mail Merge template using SmartMailMergeConverter

        Args:
            docx_path: Path to input .docx file
            output_path: Path to save template (optional)
            auto_fill_tables: Auto-fill placeholders in empty table cells (default: True)

        Returns:
            Dict with template_id, fields, and HTML preview
        """
        # Generate output path if not provided
        if output_path is None:
            template_id = str(uuid.uuid4())
            base_dir = Path(__file__).parent
            output_dir = base_dir / "uploads" / "templates"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{template_id}.docx"
        else:
            output_path = Path(output_path)
            template_id = output_path.stem

        try:
            # Step 1: Use SmartMailMergeConverter to create basic placeholders
            print("=== STEP 1: Creating basic placeholders ===")
            converter = SmartMailMergeConverter(docx_path)
            fields = converter.convert(str(output_path), auto_fill_tables=auto_fill_tables)

            # Step 2: Use Gemini to suggest better names (if API key provided)
            if self.gemini_client and fields:
                print("\n=== STEP 2: Using Gemini to suggest better field names ===")
                try:
                    # Extract structured content with placeholders
                    structured_content = self.extract_structured_content(str(output_path))

                    # Get rename suggestions from Gemini
                    rename_map = self.gemini_client.suggest_better_field_names(
                        structured_content=structured_content,
                        current_fields=fields
                    )

                    # Apply renames if any
                    if rename_map:
                        print(f"\n=== STEP 3: Applying {len(rename_map)} renames ===")
                        success = self.rename_placeholders_in_docx(str(output_path), rename_map)

                        if success:
                            # Update field names
                            new_fields = [rename_map.get(f, f) for f in fields]
                            print(f"Updated fields: {new_fields}")
                            fields = new_fields

                except Exception as e:
                    print(f"Gemini rename failed, using basic names: {e}")
                    # Continue with basic names

            # Step 4: Generate HTML preview from converted template
            html_preview = self._generate_html_preview(str(output_path))

            return {
                "template_id": template_id,
                "fields": fields,
                "field_count": len(fields),
                "html_preview": html_preview,
                "method": "smart_converter_with_gemini" if self.gemini_client else "smart_converter",
                "note": "Full XML surgical injection with Vietnamese support" + (" + Gemini smart naming" if self.gemini_client else "")
            }

        except Exception as e:
            raise RuntimeError(f"Conversion failed: {str(e)}")

    def _generate_html_preview(self, docx_path: str) -> str:
        """Generate HTML preview with highlighted placeholders and preserved document order

        IMPORTANT: Must use same empty-check logic as inject_placeholder_at_location
        to ensure block_index consistency between HTML preview and injection
        """
        try:
            doc = Document(docx_path)
            self.doc = doc  # Store for image extraction
            html_parts = []
            block_index = 0  # Track block index for click-to-add functionality
            table_index = 0  # Track table index for table operations

            print("=== GENERATING HTML PREVIEW ===")
            print(f"[DEBUG] Document has {len(doc.tables)} tables total")
            print(f"[DEBUG] Document has {len(doc.part.rels)} relationships")

            # Count images
            image_count = 0
            for rId, rel in doc.part.rels.items():
                if 'image' in rel.target_ref:
                    image_count += 1
            print(f"[DEBUG] Document has {image_count} images")

            # Use body children directly to preserve document order
            # IMPORTANT: Use same logic as inject_placeholder_at_location for consistency
            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)
                    text = self._extract_xml_text(child)

                    # Check if paragraph has images (drawing elements)
                    has_images = len(child.findall(f".//{self.w_ns}drawing")) > 0
                    if has_images:
                        print(f"[DEBUG] Paragraph #{block_index} has {len(child.findall(f'.//{self.w_ns}drawing'))} drawing(s)")

                    # Process ALL paragraphs (including empty ones) to preserve document structure
                    # Empty lines ARE selectable for adding placeholders
                    # This preserves visual layout while maintaining index consistency
                    # Paragraphs with images are NOT empty even if they have no text
                    if text or has_images:
                        html = self._process_para_to_html(para, block_index, is_empty=False)
                        html_parts.append(html)
                        block_index += 1
                    else:
                        # Empty paragraph - render with block_index (selectable for adding placeholders)
                        html = self._process_para_to_html(para, block_index, is_empty=True)
                        html_parts.append(html)
                        block_index += 1

                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    current_table_index = table_index  # Store current table index
                    table_index += 1  # Increment for next table
                    table_has_content = False

                    print(f"[DEBUG] Processing TABLE #{current_table_index} with {len(table.rows)} rows, {len(table.columns)} columns")

                    # Track starting block index for this table (for first cell)
                    table_start_block_index = block_index

                    # Process each cell as a separate block (matching extract_structured_content logic)
                    # CRITICAL FIX: Increment block_index for ALL cells (including empty ones)
                    # This matches _process_table_to_html and _build_block_index_map behavior
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                            # Extract cell text to check if it has content
                            cell_text = "".join(
                                self._extract_xml_text(para._p) for para in cell.paragraphs
                            ).strip()

                            if cell_text:
                                table_has_content = True
                            # CRITICAL FIX: Increment block_index for ALL cells, not just non-empty ones
                            # This ensures consistency with _process_table_to_html and _build_block_index_map
                            block_index += 1

                    # CRITICAL FIX: Always render table, even if empty!
                    # New tables added by user will be empty initially but should still be visible
                    # Use the starting block index for the table (first cell's block_index)
                    html = self._process_table_to_html(table, table_start_block_index, current_table_index)
                    html_parts.append(html)
                    if table_has_content:
                        # Keep block indices aligned with extract/inject, even though the summary is not rendered.
                        block_index += 1
                    print(f"[DEBUG] Added table HTML to preview, table {current_table_index}, has_content: {table_has_content}, HTML length: {len(html)}")

            print(f"=== TOTAL BLOCKS IN HTML PREVIEW: {block_index} ===")

            return "\n".join(html_parts)
            
        except Exception as e:
            import traceback
            return f'''
            <div class="error" style="padding: 20px; background-color: #fee; border: 1px solid #fcc; border-radius: 4px; color: #c33;">
                <h3>Lỗi chuyển đổi DOCX</h3>
                <p>Không thể chuyển đổi tài liệu sang HTML.</p>
                <pre style="background: #fff; padding: 10px; border-radius: 4px; overflow: auto;">{str(e)}\n{traceback.format_exc()}</pre>
            </div>
            '''

    def extract_structured_content(self, docx_path: str) -> list:
        """Extract structured content from DOCX for Gemini analysis

        Args:
            docx_path: Path to .docx file

        Returns:
            List of content blocks with text and metadata
        """
        try:
            doc = Document(docx_path)
            content_blocks = []

            print("=== EXTRACTING STRUCTURED CONTENT ===")

            # Use body children to preserve document order
            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)
                    text = self._extract_xml_text(child)

                    # Include ALL paragraphs (both empty and non-empty) for accurate indexing
                    # This allows adding placeholders to empty lines
                    content_blocks.append({
                        "type": "paragraph",
                        "text": text if text else "[EMPTY LINE]",
                        "style": para.style.name if para.style else "Normal",
                        "docx_index": len(content_blocks),  # CRITICAL FIX: Use block index, not table index
                        "is_empty": not text
                    })
                    print(f"[{len(content_blocks)-1}] {text[:80] if text else '[EMPTY]'}...")
                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    table_has_content = False

                    # Process each cell as a separate content block to enable precise targeting
                    # CRITICAL FIX: Process ALL cells (including empty ones) for consistency
                    # This matches _generate_html_preview and _build_block_index_map behavior
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                            cell_text = "".join(
                                self._extract_xml_text(para._p) for para in cell.paragraphs
                            ).strip()

                            if cell_text:
                                table_has_content = True

                            content_blocks.append({
                                "type": "table_cell",
                                "text": cell_text if cell_text else "",
                                "table_row": row_idx,
                                "table_col": cell_idx,
                                "docx_index": len(content_blocks),
                                "table_context": f"Row {row_idx}, Col {cell_idx}",
                                "is_empty": not cell_text
                            })

                            if cell_text:
                                print(f"[{len(content_blocks)-1}] TABLE_CELL[{row_idx},{cell_idx}]: {cell_text[:60]}...")
                            else:
                                print(f"[{len(content_blocks)-1}] TABLE_CELL[{row_idx},{cell_idx}]: [EMPTY]")

                    # Only add table as a block if it has content (for backward compatibility)
                    if table_has_content:
                        # Create a summary block for the entire table
                        all_cells = []
                        for row in table.rows:
                            row_cells = []
                            for cell in row.cells:
                                cell_text = ""
                                for para in cell.paragraphs:
                                    for t in para._p.findall(f".//{self.w_ns}t"):
                                        if t.text:
                                            cell_text += t.text
                                row_cells.append(cell_text.strip())
                            all_cells.append(row_cells)

                        # Format table as readable text for summary
                        table_text = "\n".join([" | ".join(row) for row in all_cells if any(cell.strip() for cell in row)])
                        content_blocks.append({
                            "type": "table_summary",
                            "text": table_text,
                            "rows": len(table.rows),
                            "cols": len(table.rows[0].cells) if table.rows else 0,
                            "docx_index": len(content_blocks)
                        })
                        print(f"[{len(content_blocks)-1}] TABLE_SUMMARY: {table_text[:80]}...")

            print(f"=== TOTAL BLOCKS: {len(content_blocks)} ===")

            # Add surrounding context for each block to help disambiguate similar content
            self._add_neighbor_context(content_blocks)

            return content_blocks

        except Exception as e:
            print(f"Error extracting structured content: {e}")
            return []

    def extract_text_from_block_with_fallback(
        self,
        structured_content: list,
        block_index: int,
        para_in_cell: int = None
    ) -> str:
        """Extract text from a block, falling back to previous meaningful blocks if empty

        Args:
            structured_content: List of content blocks from extract_structured_content
            block_index: Target block index to extract text from
            para_in_cell: Optional paragraph index within cell (for table cells)

        Returns:
            Extracted text string, or empty string if no meaningful text found
        """
        if not structured_content or block_index < 0 or block_index >= len(structured_content):
            return ""

        target_block = structured_content[block_index]
        text = target_block.get("text", "")
        block_type = target_block.get("type", "paragraph")

        print(f"[extract_text] block_index={block_index}, block_type={block_type}, para_in_cell={para_in_cell}")
        print(f"[extract_text] Full block text: {repr(text[:100])}")

        # If it's a table cell and para_in_cell is specified, extract that specific paragraph
        if para_in_cell is not None and block_type == "table_cell":
            # Split text by newlines and get the specific paragraph
            paragraphs = text.split("\n")
            print(f"[extract_text] Table cell has {len(paragraphs)} paragraphs")
            if 0 <= para_in_cell < len(paragraphs):
                text = paragraphs[para_in_cell].strip()
                print(f"[extract_text] Extracted paragraph #{para_in_cell}: {repr(text[:100])}")
            else:
                print(f"[extract_text] para_in_cell {para_in_cell} >= {len(paragraphs)}, returning empty")
                text = ""

        # Check if meaningful (not just dots/underscores)
        def has_content(t: str) -> bool:
            return bool(re.sub(r'[\s._]+', '', t))

        if has_content(text):
            print(f"→ Found text: {text[:60]}...")
            return text

        # Fallback: search backwards - BUT NOT for table cells!
        # Table cells have their own context, don't fallback to other cells
        if para_in_cell is not None and target_block.get("type") == "table_cell":
            print(f"→ Table cell paragraph #{para_in_cell} is empty, not falling back to other cells")
            # Try to find context within the same cell (other paragraphs)
            cell_text = target_block.get("text", "")
            all_paras = cell_text.split("\n")
            # Look for the first non-empty paragraph in the same cell
            for i, p in enumerate(all_paras):
                if has_content(p.strip()):
                    print(f"→ Found context in same cell, paragraph #{i}: {p[:60]}...")
                    return p.strip()
            print("→ No meaningful text found in this cell")
            return ""

        # Fallback for non-table blocks
        print(f"→ Block empty, searching backwards...")
        for i in range(block_index - 1, -1, -1):
            candidate_text = structured_content[i].get("text", "")
            if has_content(candidate_text):
                print(f"→ Found in block #{i}: {candidate_text[:60]}...")
                return candidate_text

        print("→ No meaningful text found")
        return ""

    def generate_smart_field_name(
        self,
        text: str,
        structured_content: list = None,
        block_index: int = None
    ) -> str:
        """Generate a smart field name from text, with optional Gemini refinement

        Args:
            text: Source text to extract field name from
            structured_content: Optional full content for context
            block_index: Optional target block index for additional context

        Returns:
            Generated field name in snake_case
        """
        if not text:
            return "field"


        # Remove special chars but keep Vietnamese letters
        text = re.sub(r'[^\w\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]', ' ', text)

        # Convert to snake_case
        base_name = text.lower().strip()
        base_name = re.sub(r'\s+', '_', base_name)
        base_name = re.sub(r'(_lưu|_ghi_chú|_note)?$', '', base_name)
        base_name = base_name[:30].strip('_')
        base_name = re.sub(r'_+', '_', base_name)

        if not base_name:
            base_name = "field"

        print(f"→ Base field name: {base_name}")

        # Step 2: Use Gemini to refine if available (shorter prompt)
        if self.gemini_client and structured_content and block_index is not None:
            try:
                target_block = structured_content[block_index] if 0 <= block_index < len(structured_content) else None
                if not target_block:
                    return base_name

                # Simplified prompt - focus on result
                prompt = f"""Tối ưu tên trường tiếng Việt (snake_case, không dấu):

Base: {base_name}
Context: {target_block.get('text', '')[:50]}

Trả về JSON: {{"suggested_name": "<tên>", "reason": "<lý do>"}}

JSON:"""

                response = self.gemini_client.model.generate_content(prompt)
                suggestion = self.gemini_client.parse_gemini_json_response(response.text)
                suggested_name = suggestion.get("suggested_name", base_name)

                if suggested_name and suggested_name != base_name:
                    print(f"→ Gemini refined: {base_name} → {suggested_name}")
                    return suggested_name

            except Exception as e:
                print(f"→ Gemini refinement failed: {e}")

        return base_name

    def inject_placeholder_at_location(
        self,
        docx_path: str,
        block_index: int,
        placeholder_name: str,
        context_hint: str = "",
        before_context: list = None,
        after_context: list = None,
        position: str = "right",
        cell_index: int = None,
        para_in_cell: int = None,
        insert_after: str = None
    ) -> bool:
        """Inject a placeholder at a specific location in DOCX

        Args:
            docx_path: Path to DOCX file
            block_index: Index of content block (from Gemini analysis)
            placeholder_name: Name for the new placeholder
            context_hint: Text hint to find exact location
            before_context: List of text before the target block
            after_context: List of text after the target block
            position: Where to insert (left=before, right=after, new_line, inline)
            cell_index: Optional cell index within a table for precise cell targeting
            para_in_cell: Optional paragraph index within cell for specific paragraph targeting
            insert_after: Text to insert after (required for position='inline')

        Returns:
            True if successful, False otherwise
        """
        if before_context is None:
            before_context = []
        if after_context is None:
            after_context = []

        print(f"=== INJECT POSITION: {position} ===")

        try:
            editor = DocxFullEditor(docx_path)
            doc = editor.doc

            print(f"=== INJECT PLACEHOLDER: LOOKING FOR BLOCK_INDEX {block_index} ===")
            print(f"Context hint: {context_hint[:100] if context_hint else 'None'}...")
            print(f"Before context: {before_context}")
            print(f"After context: {after_context}")

            candidates = self._build_block_candidates(doc)
            self._add_neighbor_context(candidates)

            for candidate in candidates:
                print(f"[Injection] Block {candidate['index']}: {candidate['text'][:60]}...")

            print(f"=== INJECTION: TOTAL CANDIDATES: {len(candidates)} ===")

            # Find best match using the block_index returned by Gemini
            best_match = next((candidate for candidate in candidates if candidate["index"] == block_index), None)

            if best_match:
                print(f"✓ DIRECT INDEX MATCH: [{best_match['index']}] ({best_match['type']})")
                print(f"  Text: {best_match['text'][:60]}...")

                if best_match["type"] == "table_cell":
                    print(f"  Cell location: [{best_match.get('row', '?')},{best_match.get('col', '?')}]")

            # Fail closed if the verified block index does not match any current candidate.
            # Context similarity is intentionally not used here because it can select the wrong location.

            if best_match:
                print(f"→ INJECTING at index {best_match['index']}: {best_match['text'][:50]}...")
                print(f"  Position: {position}")
                if best_match['type'] == 'paragraph':
                    if position == "inline":
                        if not insert_after:
                            print("✗ INLINE injection requires insert_after text")
                            return False
                        if self._inject_inline_placeholder_via_offset(
                            editor,
                            best_match['para'],
                            editor.get_paragraph_index_from_block(block_index),
                            placeholder_name,
                            insert_after,
                        ):
                            editor.save(docx_path)
                            print(f"✓ INJECTION SUCCESSFUL")
                            return True
                    elif self._inject_placeholder_in_paragraph(best_match['para'], placeholder_name, context_hint, position, insert_after):
                        editor.save(docx_path)
                        print(f"✓ INJECTION SUCCESSFUL")
                        return True
                elif best_match['type'] == 'table_cell':
                    # For table_cell type, we have direct cell reference
                    cell = best_match['cell']
                    print(f"  Target: TABLE_CELL[{best_match['row']},{best_match['col']}]")

                    # Inject into first paragraph of the cell (or specific para if provided)
                    target_para = None
                    if para_in_cell is not None and para_in_cell < len(cell.paragraphs):
                        target_para = cell.paragraphs[para_in_cell]
                        print(f"  Targeting paragraph {para_in_cell} in cell")
                    elif cell.paragraphs:
                        target_para = cell.paragraphs[0]
                        print(f"  Targeting first paragraph in cell")

                    if target_para:
                        if position == "inline":
                            if not insert_after:
                                print("✗ INLINE injection requires insert_after text")
                                return False
                            paragraph_index = None
                            if para_in_cell is not None:
                                paragraph_index = editor.get_table_cell_paragraph_index(block_index, para_in_cell)
                            else:
                                paragraph_index = editor.get_table_cell_paragraph_index(block_index, 0)

                            if self._inject_inline_placeholder_via_offset(
                                editor,
                                target_para,
                                paragraph_index,
                                placeholder_name,
                                insert_after,
                                cell,
                            ):
                                tc_pr = cell._element.get_or_add_tcPr()
                                v_align = tc_pr.find(qn('w:vAlign'))
                                if v_align is None:
                                    v_align = OxmlElement('w:vAlign')
                                    tc_pr.append(v_align)
                                v_align.set(qn('w:val'), 'center')

                                editor.save(docx_path)
                                print(f"✓ INJECTION SUCCESSFUL")
                                return True

                        elif self._inject_placeholder_in_paragraph(target_para, placeholder_name, context_hint, position, insert_after):
                            # Set vertical alignment to center for table cell
                            tc_pr = cell._element.get_or_add_tcPr()
                            v_align = tc_pr.find(qn('w:vAlign'))
                            if v_align is None:
                                v_align = OxmlElement('w:vAlign')
                                tc_pr.append(v_align)
                            v_align.set(qn('w:val'), 'center')

                            editor.save(docx_path)
                            print(f"✓ INJECTION SUCCESSFUL")
                            return True
                    else:
                        print(f"✗ Target cell has no paragraphs")
                        return False
                else:
                    # For table_summary or legacy table type, use existing logic
                    if self._inject_placeholder_in_table(best_match['table'], placeholder_name, context_hint, position, cell_index, para_in_cell, insert_after):
                        editor.save(docx_path)
                        print(f"✓ INJECTION SUCCESSFUL")
                        return True

            print(f"✗ NO MATCH FOUND for block_index {block_index}")
            return False

        except Exception as e:
            print(f"Error injecting placeholder: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _inject_inline_placeholder_via_offset(
        self,
        editor: DocxFullEditor,
        paragraph,
        paragraph_index: int,
        placeholder_name: str,
        insert_after: str,
        cell=None
    ) -> bool:
        """Inject placeholder inline by reusing DocxFullEditor offset insertion."""
        try:
            if paragraph is None or paragraph_index is None:
                print("  ✗ Unable to resolve target paragraph for inline injection")
                return False

            para_text = paragraph.text if paragraph else ""
            print(f"\n[INLINE INJECTION VIA OFFSET]")
            print(f"  Placeholder: '{placeholder_name}'")
            print(f"  Insert after: '{insert_after}'")
            print(f"  Paragraph index: {paragraph_index}")
            print(f"  Current paragraph: '{para_text}'")

            search_idx = para_text.find(insert_after)
            if search_idx == -1:
                print(f"  ✗ Could not find '{insert_after}' in paragraph")
                return False

            offset = search_idx + len(insert_after)
            print(f"  → Found '{insert_after}' at index {search_idx}, offset {offset}")

            if not editor.insert_placeholder_at_offset(paragraph_index, offset, placeholder_name):
                print("  ✗ Offset-based inline insertion failed")
                return False

            if cell is not None:
                tc_pr = cell._element.get_or_add_tcPr()
                v_align = tc_pr.find(qn('w:vAlign'))
                if v_align is None:
                    v_align = OxmlElement('w:vAlign')
                    tc_pr.append(v_align)
                v_align.set(qn('w:val'), 'center')

            print(f"  ✓ Injected inline after '{insert_after}' via offset\n")
            return True

        except Exception as e:
            print(f"[INLINE INJECTION VIA OFFSET] ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _inject_placeholder_in_paragraph(
        self,
        paragraph,
        placeholder_name: str,
        context_hint: str,
        position: str = "right",
        insert_after: str = None
    ) -> bool:
        """Inject placeholder into paragraph at best location using MERGEFIELD XML

        Args:
            paragraph: docx paragraph object
            placeholder_name: Name for the placeholder
            context_hint: Text hint for finding location
            position: Where to insert (left=before, right=after, new_line, inline)
            insert_after: Text to insert after (required for position='inline')
        """

        try:
            # Log context ban đầu
            para_text = paragraph.text if paragraph else ""
            print(f"\n[INJECT PLACEHOLDER IN PARAGRAPH]")
            print(f"  Placeholder: '{placeholder_name}'")
            print(f"  Position: {position}")
            print(f"  Context hint: '{context_hint}'")
            print(f"  Current paragraph: '{para_text}'")

            # Inline insertion is routed through the offset-based adapter in
            # inject_placeholder_at_location() to keep one implementation path.
            if position == "inline":
                print("  ✗ Inline insertion must be handled by the offset-based adapter")
                return False

            text_runs = []
            for run in paragraph.runs:
                if run.text:
                    text_runs.append(run)

            if not text_runs:
                # Add new run with placeholder using MERGEFIELD structure
                print(f"  → No text runs found, adding placeholder with empty original text")
                self._add_mergefield_placeholder(paragraph, placeholder_name, "", position)
                return True

            # Look for pattern match in context_hint or last run
            last_run = text_runs[-1]
            original_text = last_run.text

            # Reuse the same placeholder detection rules as the main converter.
            end_match = PLACEHOLDER_PATTERN.search(original_text)
            if end_match and end_match.end() == len(original_text):
                # Extract the pattern to use as original text
                match = end_match
                original_pattern = match.group(1) if match else "..."

                print(f"  → Found pattern '{original_pattern}' at end, removing and adding placeholder")

                # Remove pattern from run text
                last_run.text = original_text[:match.start()]
                print(f"  → Removed pattern from run text: '{last_run.text}'")

                # Add MERGEFIELD placeholder
                self._add_mergefield_placeholder(paragraph, placeholder_name, original_pattern, position)
                return True
            else:
                # Append placeholder at end with empty original
                print(f"  → No pattern found at end, adding placeholder with empty original text")
                self._add_mergefield_placeholder(paragraph, placeholder_name, "", position)

                # Log kết quả cuối cùng
                final_text = paragraph.text
                print(f"[INJECT PLACEHOLDER IN PARAGRAPH] Final result: '{final_text}'")
                print(f"✓ Placeholder injection completed successfully\n")
                return True

        except Exception as e:
            print(f"[INJECT PLACEHOLDER IN PARAGRAPH] ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _add_mergefield_placeholder(
        self,
        paragraph,
        placeholder_name: str,
        original_text: str,
        position: str = "right"
    ):
        """Add a MERGEFIELD placeholder to paragraph using proper XML structure

        Args:
            paragraph: docx paragraph object
            placeholder_name: Name for the merge field
            original_text: Original text to preserve in \\z switch
            position: Where to insert (left=before text, right=after text, new_line)
        """

        # Get paragraph element
        p_element = paragraph._p

        # Log trạng thái trước khi chèn
        para_text_before = paragraph.text
        print(f"\n[INSERT PLACEHOLDER] Position: {position}")
        print(f"  Before insert: '{para_text_before}'")
        print(f"  Placeholder name: '{placeholder_name}'")
        print(f"  Original text: '{original_text}'")

        # Create fldSimple element (MERGEFIELD)
        fld = OxmlElement('w:fldSimple')
        fld.set(qn('w:instr'), f' MERGEFIELD {placeholder_name} \\* MERGEFORMAT \\z "{original_text}" ')

        # Create run element with style
        run = OxmlElement('w:r')

        # Try to get style from existing runs in paragraph
        rPr = None
        for r in p_element.findall(f"{self.w_ns}r"):
            rPrCandidate = r.find(f"{self.w_ns}rPr")
            if rPrCandidate is not None:
                rPr = rPrCandidate
                break

        # Copy style if found
        if rPr is not None:
            import copy
            run.append(copy.deepcopy(rPr))

        # Create text element with «name» format
        t = OxmlElement('w:t')
        if ' ' in (placeholder_name[0], placeholder_name[-1]):
            t.set(qn('xml:space'), 'preserve')
        t.text = f"«{placeholder_name}»"
        run.append(t)
        fld.append(run)

        # Handle different positions
        if position == "new_line":
            # Create a new paragraph with same indentation as current paragraph
            # This ensures the new line aligns properly with the selected line
            self._add_new_paragraph_with_placeholder(paragraph, placeholder_name, fld)
        elif position == "left":
            # Insert at the beginning of paragraph
            p_element.insert(0, fld)
        else:  # right (default)
            # Append fldSimple to end of paragraph
            p_element.append(fld)

        # Log trạng thái sau khi chèn
        print(f"  After insert: '{paragraph.text}'")
        print(f"  ✓ Placeholder '{placeholder_name}' inserted successfully")

    def _add_new_paragraph_with_placeholder(
        self,
        original_paragraph,
        placeholder_name: str,
        fld_element
    ):
        """Create a new paragraph with same indentation and add placeholder

        Args:
            original_paragraph: Original paragraph to copy indentation from
            placeholder_name: Name for the merge field
            fld_element: The fldSimple element containing the placeholder
        """
        original_p_element = original_paragraph._p

        # Read the paragraph text once and reuse it for logging and spacing checks.
        original_text_content = "".join(
            t.text for t in original_p_element.findall(f".//{self.w_ns}t") if t.text
        )
        print(f"  [NEW LINE] Original paragraph: '{original_text_content}'")
        print(f"  [NEW LINE] Creating new paragraph with placeholder '{placeholder_name}'")

        # Get the parent element (could be body or cell)
        parent = original_p_element.getparent()

        # Create new paragraph
        new_p = OxmlElement('w:p')

        # Count leading spaces
        leading_spaces = len(original_text_content) - len(original_text_content.lstrip(' \t'))
        has_leading_spaces = leading_spaces > 0

        # Copy paragraph properties from original paragraph (indentation, alignment, etc.)
        pPr = original_p_element.find(f"{self.w_ns}pPr")
        if pPr is not None:
            new_p.append(copy.deepcopy(pPr))
            print(f"  [new_line] Copied indentation from original paragraph")
        else:
            # Create basic pPr if none exists
            new_pPr = OxmlElement('w:pPr')
            new_p.append(new_pPr)

        # IMPORTANT: After copying pPr, handle alignment and right indent when there are leading spaces
        # This matches HTML preview behavior: align="both" + leading spaces → right alignment
        # This ensures DOCX output matches HTML preview
        new_pPr = new_p.find(f"{self.w_ns}pPr")
        if new_pPr is not None:
            # Check current alignment
            jc = new_pPr.find(f"{self.w_ns}jc")
            current_align = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") if jc is not None else None

            # Convert "both" alignment to "right" when there are leading spaces
            # This matches HTML preview logic exactly
            if current_align == "both" and has_leading_spaces:
                if jc is not None:
                    jc.set(qn('w:val'), 'right')
                else:
                    new_jc = OxmlElement('w:jc')
                    new_jc.set(qn('w:val'), 'right')
                    new_pPr.append(new_jc)
                print(f"  [new_line] Changed alignment from 'both' to 'right' to match HTML preview")

        # Add right indent when there are leading spaces
        # This creates partial right alignment (keeps some space from right edge)
        if new_pPr is not None and has_leading_spaces:
            # Calculate right indent in twips (1 twip = 1/20 point)
            # Calibrated: matches HTML preview margin-right behavior
            right_indent_twips = int(leading_spaces * 20)

            # Get or create ind element
            ind = new_pPr.find(f"{self.w_ns}ind")
            if ind is not None:
                # Update existing right indent
                current_right = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}right")
                if current_right:
                    # Add to existing right indent
                    new_right = int(current_right) + right_indent_twips
                    ind.set(qn('w:right'), str(new_right))
                else:
                    # Set new right indent
                    ind.set(qn('w:right'), str(right_indent_twips))
            else:
                # Create new ind element with right indent
                new_ind = OxmlElement('w:ind')
                new_ind.set(qn('w:right'), str(right_indent_twips))
                new_pPr.append(new_ind)

            print(f"  [new_line] Added right indent: {right_indent_twips} twips to match HTML preview")

        if leading_spaces > 0:
            # Add a run with leading spaces to match original indentation
            spaces_run = OxmlElement('w:r')
            spaces_t = OxmlElement('w:t')
            spaces_t.set(qn('xml:space'), 'preserve')
            spaces_t.text = ' ' * leading_spaces
            spaces_run.append(spaces_t)
            new_p.append(spaces_run)
            print(f"  [new_line] Added {leading_spaces} leading spaces to match original indentation")

        # Add the placeholder field to the new paragraph
        new_p.append(fld_element)

        # Insert new paragraph after the original paragraph
        parent_index = list(parent).index(original_p_element)
        parent.insert(parent_index + 1, new_p)

        # Log kết quả
        new_paragraph_text = ""
        for t in new_p.findall(f".//{self.w_ns}t"):
            if t.text:
                new_paragraph_text += t.text
        print(f"  [new_line] Created new paragraph with placeholder after original")
        print(f"  [NEW LINE] New paragraph content: '{new_paragraph_text}'")
        print(f"  ✓ NEW LINE creation completed successfully")

    def _inject_placeholder_in_table(
        self,
        table,
        placeholder_name: str,
        context_hint: str,
        position: str = "right",
        cell_index: int = None,
        para_in_cell: int = None,
        insert_after: str = None
    ) -> bool:
        """Inject placeholder into table cell at best location or specific cell

        Args:
            table: docx Table object
            placeholder_name: Name for the placeholder
            context_hint: Text hint for finding best match (used if cell_index is None)
            position: Where to insert (left=before, right=after, new_line, inline)
            cell_index: Optional specific cell index to target directly
            para_in_cell: Optional specific paragraph index within cell to target directly
            insert_after: Text to insert after (required for position='inline')

        Returns:
            True if successful, False otherwise
        """
        import re

        # If cell_index is provided, target that specific cell directly
        if cell_index is not None:
            print(f"=== TABLE INJECTION - DIRECT CELL TARGETING ===")
            print(f"Target cell index: {cell_index}, para_in_cell: {para_in_cell}")

            # Flatten table cells to find the specific cell
            current_cell_index = 0
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    if current_cell_index == cell_index:
                        # Found the target cell
                        print(f"✓ Found target cell at row {row_idx}, col {cell_idx}")

                        # If para_in_cell is specified, target that specific paragraph
                        if para_in_cell is not None and para_in_cell < len(cell.paragraphs):
                            print(f"✓ Targeting paragraph {para_in_cell} in cell (total: {len(cell.paragraphs)} paras)")
                            return self._inject_placeholder_in_paragraph(
                                cell.paragraphs[para_in_cell], placeholder_name, context_hint, position, insert_after
                            )
                        else:
                            # Inject into first paragraph (default behavior)
                            if para_in_cell is not None:
                                print(f"⚠️ Warning: para_in_cell {para_in_cell} >= cell paragraph count {len(cell.paragraphs)}, using first paragraph")
                            if cell.paragraphs:
                                return self._inject_placeholder_in_paragraph(
                                    cell.paragraphs[0], placeholder_name, context_hint, position, insert_after
                                )
                            else:
                                print(f"✗ Target cell has no paragraphs")
                                return False
                    current_cell_index += 1

            print(f"✗ Cell index {cell_index} not found in table")
            return False

        # Original logic: Parse table context hint and find best matching cell
        # Parse table context hint (format: "Cell1 | Cell2 | Cell3 | ...")
        # When extracting table, we join cells with " | "
        # We need to find which cell matches best with context_hint
        table_cells_text = []
        if context_hint and " | " in context_hint:
            # Table context hint is concatenated with " | "
            table_cells_text = [cell.strip() for cell in context_hint.split(" | ")]
        elif context_hint:
            # Single cell or no separator
            table_cells_text = [context_hint.strip()]

        print(f"=== TABLE INJECTION ===")
        print(f"Placeholder: {placeholder_name}")
        print(f"Context hint: {context_hint[:100] if context_hint else 'None'}...")
        print(f"Parsed cells: {len(table_cells_text)}")

        # Extract keywords from placeholder_name for better matching
        # E.g., "chu_ky_truong_phong" → ["chu", "ky", "truong", "phong"]
        placeholder_keywords = set(placeholder_name.lower().split('_'))
        print(f"Placeholder keywords: {placeholder_keywords}")

        # Find best matching cell based on placeholder_name and context
        best_match = None
        best_score = 0

        for row_idx, row in enumerate(table.rows):
            for cell_idx, cell in enumerate(row.cells):
                for para in cell.paragraphs:
                    # Extract text from XML
                    text_from_xml = ""
                    for t in para._p.findall(f".//{self.w_ns}t"):
                        if t.text:
                            text_from_xml += t.text
                    cell_text = text_from_xml.strip()

                    if not cell_text:
                        continue

                    print(f"  Cell[{row_idx},{cell_idx}]: {cell_text[:50]}...")

                    # Calculate similarity with each parsed cell text
                    for parsed_cell_text in table_cells_text:
                        # Word overlap similarity
                        hint_words = set(re.findall(r'\w+', parsed_cell_text.lower()))
                        text_words = set(re.findall(r'\w+', cell_text.lower()))

                        if hint_words and text_words:
                            overlap = len(hint_words & text_words)
                            base_score = overlap / len(hint_words) if hint_words else 0

                            # BONUS: If placeholder keywords match with cell text
                            keyword_bonus = 0
                            cell_words_lower = set(re.findall(r'\w+', cell_text.lower()))
                            keyword_overlap = placeholder_keywords & cell_words_lower
                            if keyword_overlap:
                                keyword_bonus = len(keyword_overlap) * 0.2  # 20% bonus per matching keyword
                                print(f"    Keyword bonus: +{keyword_bonus:.2f} (matched: {keyword_overlap})")

                            total_score = base_score + keyword_bonus

                            print(f"    Score: {total_score:.2f} (base: {base_score:.2f} + bonus: {keyword_bonus:.2f}) (vs '{parsed_cell_text[:30]}...')")

                            if total_score > best_score:
                                best_score = total_score
                                best_match = para
                                print(f"    → New best match! Score: {total_score:.2f}")

        # Inject into best matching cell
        if best_match:
            print(f"✓ Injecting into best match cell (score: {best_score:.2f})")
            return self._inject_placeholder_in_paragraph(best_match, placeholder_name, context_hint, position, insert_after)

        print(f"✗ No matching cell found")
        return False

    def _extract_paragraph_indentation_styles(self, pPr) -> list:
        """Map Word paragraph indentation settings to CSS styles."""
        styles = []
        if pPr is None:
            return styles

        ind = pPr.find(f"{self.w_ns}ind")
        if ind is None:
            return styles

        left = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}left")
        if left:
            styles.append(f"margin-left: {int(left) / 20}pt")

        right = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}right")
        if right:
            styles.append(f"margin-right: {int(right) / 20}pt")

        first_line = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}firstLine")
        hanging = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}hanging")

        if first_line:
            styles.append(f"text-indent: {int(first_line) / 20}pt")
        elif hanging:
            styles.append(f"text-indent: -{int(hanging) / 20}pt")

        return styles

    def _get_run_style_text(self, rPr) -> str:
        """Map Word XML styles to CSS properties"""
        if rPr is None:
            return ""

        styles = []

        if rPr.find(f"{self.w_ns}b") is not None:
            styles.append("font-weight: bold")
        if rPr.find(f"{self.w_ns}i") is not None:
            styles.append("font-style: italic")

        decorations = []
        if rPr.find(f"{self.w_ns}u") is not None:
            decorations.append("underline")
        if rPr.find(f"{self.w_ns}strike") is not None:
            decorations.append("line-through")
        if decorations:
            styles.append(f"text-decoration: {' '.join(decorations)}")

        sz = rPr.find(f"{self.w_ns}sz")
        if sz is not None:
            val = sz.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
            if val:
                styles.append(f"font-size: {int(val) / 2}pt")

        color = rPr.find(f"{self.w_ns}color")
        if color is not None:
            val = color.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
            if val and val != "auto" and len(val) == 6:
                styles.append(f"color: #{val}")

        shd = rPr.find(f"{self.w_ns}shd")
        if shd is not None:
            fill = shd.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}fill")
            if fill and fill != "auto":
                styles.append(f"background-color: #{fill}")

        rFonts = rPr.find(f"{self.w_ns}rFonts")
        if rFonts is not None:
            ascii_font = rFonts.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}ascii")
            if ascii_font:
                styles.append(f"font-family: '{ascii_font}', Calibri, Arial, sans-serif")

        caps = rPr.find(f"{self.w_ns}caps")
        if caps is not None:
            styles.append("text-transform: uppercase")

        vertAlign = rPr.find(f"{self.w_ns}vertAlign")
        if vertAlign is not None:
            val = vertAlign.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "")
            if val == "superscript":
                styles.append("vertical-align: super")
                styles.append("font-size: smaller")
            elif val == "subscript":
                styles.append("vertical-align: sub")
                styles.append("font-size: smaller")

        return "; ".join(styles)

    def rename_placeholders_in_docx(
        self,
        docx_path: str,
        rename_map: dict
    ) -> bool:
        """Đổi tên placeholder trong DOCX file

        Args:
            docx_path: Path đến DOCX file
            rename_map: Dict mapping old_name -> new_name

        Returns:
            True nếu thành công, False nếu thất bại
        """

        if not rename_map:
            print("No renames needed")
            return True

        try:
            doc = Document(docx_path)
            rename_count = 0

            print(f"=== RENAMING PLACEHOLDERS ===")
            print(f"Rename map: {rename_map}")

            # Xử lý tất cả paragraphs trong body
            for para_idx, para in enumerate(doc.paragraphs):
                para_text = para.text
                print(f"\n[PARAGRAPH {para_idx}] Before rename: '{para_text}'")

                for fldSimple in para._p.findall(f"{self.w_ns}fldSimple"):
                    instr = fldSimple.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")

                    # Tên field hiện tại trong instr: MERGEFIELD field_name ...
                    import re
                    match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                    if match:
                        old_name = match.group(1)
                        if old_name in rename_map:
                            new_name = rename_map[old_name]

                            # Cập nhật instr attribute
                            new_instr = re.sub(r'MERGEFIELD\s+\S+', f'MERGEFIELD {new_name}', instr)
                            new_instr = re.sub(r'«.*?»', f'«{new_name}»', new_instr)
                            fldSimple.set(qn('w:instr'), new_instr)

                            # Cập nhật text trong w:r/w:t
                            for r in fldSimple.findall(f"{self.w_ns}r"):
                                for t in r.findall(f"{self.w_ns}t"):
                                    if t.text and f"«{old_name}»" in t.text:
                                        t.text = f"«{new_name}»"
                                        print(f"  ✓ Renamed: {old_name} → {new_name}")
                                        rename_count += 1

                # Log trạng thái sau khi rename
                para_text_after = para.text
                print(f"[PARAGRAPH {para_idx}] After rename: '{para_text_after}'")

            # Xử lý tables
            for table_idx, table in enumerate(doc.tables):
                print(f"\n[TABLE {table_idx}] Processing table with {len(table.rows)} rows")
                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        print(f"[TABLE {table_idx}][ROW {row_idx}][CELL {cell_idx}] Processing cell")
                        for para_idx, para in enumerate(cell.paragraphs):
                            para_text = para.text
                            print(f"  [PARAGRAPH {para_idx}] Before rename: '{para_text}'")

                            for fldSimple in para._p.findall(f"{self.w_ns}fldSimple"):
                                instr = fldSimple.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")

                                import re
                                match = re.search(r'MERGEFIELD\s+(\S+)', instr)
                                if match:
                                    old_name = match.group(1)
                                    if old_name in rename_map:
                                        new_name = rename_map[old_name]

                                        new_instr = re.sub(r'MERGEFIELD\s+\S+', f'MERGEFIELD {new_name}', instr)
                                        new_instr = re.sub(r'«.*?»', f'«{new_name}»', new_instr)
                                        fldSimple.set(qn('w:instr'), new_instr)

                                        for r in fldSimple.findall(f"{self.w_ns}r"):
                                            for t in r.findall(f"{self.w_ns}t"):
                                                if t.text and f"«{old_name}»" in t.text:
                                                    t.text = f"«{new_name}»"
                                                    print(f"    ✓ Renamed (table): {old_name} → {new_name}")
                                                    rename_count += 1

                            # Log trạng thái sau khi rename
                            para_text_after = para.text
                            print(f"  [PARAGRAPH {para_idx}] After rename: '{para_text_after}'")

            print(f"=== TOTAL RENAMED: {rename_count} placeholders ===")

            # Save file
            doc.save(docx_path)
            print(f"File saved: {docx_path}")

            return True

        except Exception as e:
            import traceback
            print(f"Error renaming placeholders: {e}")
            print(traceback.format_exc())
            return False

    def _process_xml_element_to_html(self, element) -> str:
        """Thực hiện xử lý XML element để lấy html"""
        import re
        import base64
        if element is None:
            return ""

        tag_name = element.tag.split('}')[1] if '}' in element.tag else element.tag

        if tag_name == 'hyperlink':
            # Handle hyperlink elements - extract URL and render as HTML anchor
            # Get relationship ID to find the actual URL
            r_id = element.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')

            hyperlink_url = ""
            if r_id and hasattr(self, 'doc') and self.doc and r_id in self.doc.part.rels:
                rel = self.doc.part.rels[r_id]
                hyperlink_url = rel._target if hasattr(rel, '_target') else ""

            # Process all runs inside the hyperlink
            hyperlink_content = "".join(self._process_xml_element_to_html(child) for child in element)

            # If we have a URL, wrap in anchor tag, otherwise return content as-is
            if hyperlink_url:
                return f'<a href="{hyperlink_url}" style="color: #0000EE; text-decoration: underline;" data-is-hyperlink="true">{hyperlink_content}</a>'
            else:
                return hyperlink_content

        elif tag_name == 'r':
            text_parts = []
            image_html = []
            rPr = element.find(f"{self.w_ns}rPr")
            style_text = self._get_run_style_text(rPr)

            for child in element:
                c_tag = child.tag.split('}')[1] if '}' in child.tag else child.tag
                if c_tag == 't' and child.text:
                    text_parts.append(child.text)
                elif c_tag == 'tab':
                    text_parts.append("                              ")
                elif c_tag == 'br':
                    text_parts.append("<br>")
                elif c_tag == 'drawing':
                    # Extract image from drawing element
                    img_html = self._extract_image_from_element(child)
                    if img_html:
                        image_html.append(img_html)
                        print(f"[DEBUG] Found image in drawing element")

            text = "".join(text_parts)

            # Combine text and images
            result_parts = []
            if text:
                def highlight_placeholder(match):
                    field_name = match.group(1).strip()
                    return f'<span class="mail-merge-placeholder" data-field="{field_name}" contenteditable="false" style="{style_text}">«{field_name}»</span>'

                text_with_highlights = re.sub(r'«([^»]+)»', highlight_placeholder, text)
                if style_text and "mail-merge-placeholder" not in text_with_highlights:
                    result_parts.append(f'<span style="{style_text}">{text_with_highlights}</span>')
                else:
                    result_parts.append(text_with_highlights)

            # Add images
            result_parts.extend(image_html)

            if not result_parts:
                return ""

            return "".join(result_parts)

        elif tag_name == 'fldSimple':
            instr = element.get(f"{self.w_ns}instr", "")
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            field_name = match.group(1) if match else "unknown"
            z_match = re.search(r'\\z\s*"([^"]*)"', instr)
            field_original = z_match.group(1) if z_match else ""

            nested_r = element.find(f"{self.w_ns}r")
            style_text = ""
            actual_text = ""
            if nested_r is not None:
                style_text = self._get_run_style_text(nested_r.find(f"{self.w_ns}rPr"))
                actual_text = "".join(t.text for t in nested_r.findall(f"{self.w_ns}t") if t.text)

            if actual_text and not re.match(r'^«[^»]+»$', actual_text):
                return f'<span style="{style_text}">{actual_text}</span>'
            return f'<span class="mail-merge-placeholder" data-field="{field_name}" data-original="{field_original}" contenteditable="false" style="{style_text}">«{field_name}»</span>'

        # Recursive process children
        return "".join(self._process_xml_element_to_html(child) for child in element)

    def _extract_image_from_element(self, element) -> str:
        """Extract image from drawing/pic element and convert to base64 HTML img tag

        Args:
            element: XML element containing drawing/pic

        Returns:
            HTML img tag with base64 data or empty string
        """
        import base64

        try:
            # Find blip element (contains image reference)
            for elem in element.iter():
                tag_name = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
                if tag_name == 'blip':
                    embed = elem.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    if embed and hasattr(self, 'doc') and self.doc and embed in self.doc.part.rels:
                        image_part = self.doc.part.rels[embed].target_part
                        image_data = image_part.blob
                        content_type = image_part.content_type

                        # Convert to base64
                        b64_data = base64.b64encode(image_data).decode('utf-8')
                        data_uri = f"data:{content_type};base64,{b64_data}"

                        print(f"[DEBUG] Extracted image: {content_type}, {len(image_data)} bytes")

                        # Try to get width from extent element (wordprocessingDrawing namespace)
                        width_percent = None

                        # Try wp:extent first (wordprocessingDrawing namespace)
                        extent = element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent')
                        if extent is None:
                            # Fallback to main namespace
                            extent = element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}extent')

                        if extent is not None:
                            cx = extent.get('cx')
                            if cx:
                                # Calculate width as percentage of page width
                                # Letter width = 8.5 inches = 7772400 EMU
                                # A4 width = 8.27 inches = 7560288 EMU
                                # Use Letter as default (most common)
                                page_width_emu = 7772400  # 8.5 inches
                                image_width_emu = int(cx)

                                ratio = image_width_emu / page_width_emu
                                width_percent = ratio * 100

                                print(f"[DEBUG] Image size: cx={cx} EMU, {width_percent:.1f}% of page width")

                        style_attr = f'width: {width_percent:.1f}%;' if width_percent else 'max-width: 100%;'

                        return f'<img src="{data_uri}" style="{style_attr}" alt="embedded image" />'

            print("[DEBUG] No blip element found in drawing")
            return ""

        except Exception as e:
            print(f"[ERROR] Failed to extract image: {e}")
            import traceback
            print(traceback.format_exc())
            return ""

    def _process_para_to_html(self, para, block_index: int, is_empty: bool = False) -> str:
        """Xử lý Paragraph thành thẻ p hoặc h1/h2/h3 với block_index metadata

        Args:
            para: Paragraph object
            block_index: Index of content block
            is_empty: Whether this is an empty paragraph (for styling)
        """
        import re
        jc = para._p.find(f"{self.w_ns}pPr/{self.w_ns}jc")
        align = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") if jc is not None else "left"

        # Extract text content to check for leading/trailing spaces BEFORE mapping alignment
        # This is critical because Word uses "both" + leading/trailing spaces for partial right alignment
        text_from_xml = "".join(
            t.text for t in para._p.findall(f".//{self.w_ns}t") if t.text
        )

        has_leading_spaces = len(text_from_xml) > 0 and text_from_xml[0] in ' \t'
        has_trailing_spaces = len(text_from_xml) > 0 and text_from_xml[-1] in ' \t'

        # Remove the hardcoded margin-right percentage calculation.
        # Since we're using `white-space: pre-wrap` + `justify/left`, the spaces themselves
        # naturally push the text accurately just like in standard document flow.
        margin_right = ""

        # Map alignment: "both" + leading/trailing spaces → "right" (Word's partial right alignment trick)
        # This fixes HTML preview where "justify" doesn't work like Word's "both" with spaces
        # NOTE: We keep "justify" as "justify" but handle leading spaces properly with white-space: pre-wrap
        align_map = {"center": "center", "right": "right", "both": "justify"}
        alignment = align_map.get(align, "left")

        # Removed override that forced alignment to "right" when spaces were present.
        # This was causing "leaking" to the left because spaces were added AFTER right-aligning.

        style_name = para.style.name if para.style else "Normal"
        tag = "h1" if "Heading 1" in style_name else "h2" if "Heading 2" in style_name else "h3" if "Heading 3" in style_name else "p"

        # Extract paragraph formatting
        pPr = para._p.find(f"{self.w_ns}pPr")
        para_styles = []

        if pPr is not None:
            # Line spacing (w:spacing)
            spacing = pPr.find(f"{self.w_ns}spacing")
            if spacing is not None:
                line_rule = spacing.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}lineRule")
                line_val = spacing.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}line")

                if line_val:
                    if line_rule == "auto":
                        # Line spacing in twips (1/20 pt)
                        line_spacing_pt = int(line_val) / 240  # Convert to line value (1.0 = single, 2.0 = double)
                        para_styles.append(f"line-height: {line_spacing_pt}")
                    elif line_rule == "atLeast":
                        # Minimum line spacing in twips
                        min_spacing_pt = int(line_val) / 20
                        para_styles.append(f"min-height: {min_spacing_pt}pt")
                    else:
                        # Exact line spacing in twips
                        exact_spacing_pt = int(line_val) / 20
                        para_styles.append(f"line-height: {exact_spacing_pt}pt")

                # Space before (in twips)
                before = spacing.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}before")
                if before:
                    space_before_pt = int(before) / 20
                    para_styles.append(f"margin-top: {space_before_pt}pt")

                # Space after (in twips)
                after = spacing.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}after")
                if after:
                    space_after_pt = int(after) / 20
                    para_styles.append(f"margin-bottom: {space_after_pt}pt")

            para_styles.extend(self._extract_paragraph_indentation_styles(pPr))

        # Check for page breaks in this paragraph
        has_page_break = False
        for br in para._p.findall(f".//{self.w_ns}br"):
            br_type = br.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}type")
            if br_type == "page":
                has_page_break = True
                break

        content = "".join(self._process_xml_element_to_html(child) for child in para._p)
        if is_empty or not content.strip():
            # Empty paragraph - preserve for visual layout, selectable for adding placeholders
            cursor_style = "cursor: crosshair;" if block_index >= 0 else "cursor: default;"

            # FIX: Use empty content with CSS min-height instead of &nbsp;
            # This prevents non-breaking space from appearing when users type in empty paragraphs
            # The min-height: 1.2em + display: block ensures the paragraph is visible and clickable
            empty_content = ""

            # Check if this empty paragraph has a page break
            if has_page_break:
                # Empty paragraph WITH page break - show visual indicator
                return '<p data-block-index="{0}" data-type="paragraph" data-page-break="{1}" data-empty="true" class="docx-empty-para page-break-para" style="min-height: 1.2em; margin: 5px 0; padding: 0; {2}" title="Ngắt trang (Page Break)">{3}</p>'.format(
                    block_index, str(has_page_break).lower(), cursor_style, empty_content
                ) + '''
                <div class="page-break-indicator" contenteditable="false" style="
                    margin: 20px 0 !important;
                    padding: 10px !important;
                    border-top: 2px dashed #666 !important;
                    border-bottom: 2px dashed #666 !important;
                    text-align: center !important;
                    color: #666 !important;
                    font-size: 12px !important;
                    font-style: italic !important;
                    background-color: #f9f9f9 !important;
                    user-select: none !important;
                    -webkit-user-select: none !important;
                    -moz-user-select: none !important;
                    -ms-user-select: none !important;
                    pointer-events: none !important;
                    cursor: default !important;
                " title="Ngắt trang (Page Break) - Không thể chỉnh sửa">
                    📄 Ngắt trang
                </div>
                '''
            else:
                # Regular empty paragraph - NO &nbsp; to prevent spacing issues when typing
                return '<p data-block-index="{0}" data-type="paragraph" data-page-break="{1}" data-empty="true" class="docx-empty-para" style="min-height: 1.2em; margin: 5px 0; padding: 0; {2}" title="Click để thêm placeholder">{3}</p>'.format(
                    block_index, str(has_page_break).lower(), cursor_style, empty_content
                )

        align_style = f"text-align: {alignment};" if alignment != "left" else ""
        align_style += margin_right  # Add margin-right if calculated

        # Add paragraph formatting styles
        if para_styles:
            align_style += "; ".join(para_styles) + ";"

        # Preserve leading/trailing whitespace by adding white-space: pre-wrap when needed
        # This fixes issue where leading spaces used for right-alignment are collapsed in HTML
        # Check the actual text content (stripping HTML tags) to detect leading/trailing spaces
        text_content = re.sub(r'<[^>]+>', '', content)
        if text_content and (text_content[0] in ' \t\n' or text_content[-1] in ' \t\n'):
            align_style += " white-space: pre-wrap;"

        # Build paragraph HTML
        para_html = '<{0} data-block-index="{1}" data-type="paragraph" data-page-break="{2}" style="{3}">{4}</{0}>'.format(
            tag, block_index, str(has_page_break).lower(), align_style, content
        )

        # Add visual page break indicator if this paragraph has a page break
        if has_page_break:
            page_break_indicator = '''
            <div class="page-break-indicator" contenteditable="false" style="
                margin: 20px 0 !important;
                padding: 10px !important;
                border-top: 2px dashed #666 !important;
                border-bottom: 2px dashed #666 !important;
                text-align: center !important;
                color: #666 !important;
                font-size: 12px !important;
                font-style: italic !important;
                background-color: #f9f9f9 !important;
                user-select: none !important;
                -webkit-user-select: none !important;
                -moz-user-select: none !important;
                -ms-user-select: none !important;
                pointer-events: none !important;
                cursor: default !important;
            " title="Ngắt trang (Page Break) - Không thể chỉnh sửa">
                📄 Ngắt trang
            </div>
            '''
            para_html += page_break_indicator

        return para_html

    def _process_table_to_html(self, table, block_index: int, table_index: int) -> str:
        """Xử lý Table thành thẻ table html với block_index metadata cho từng ô

        Args:
            table: docx Table object
            block_index: Starting block index for first cell in table
            table_index: Index of this table in the document

        Returns:
            HTML string for the entire table
        """
        print(f"[_process_table_to_html] START Processing table {table_index} with {len(table.rows)} rows, {len(table.columns)} columns")
        table_html = ['<div style="overflow-x: auto; max-width: 100%;"><table class="docx-table" data-type="table" style="border-collapse: collapse; width: auto; max-width: 100%; table-layout: auto; margin: 10px 0;">']

        # Extract column widths from tblGrid to set proper cell proportions
        column_widths = []
        try:
            tbl_grid = table._element.find(f"{self.w_ns}tblGrid")
            if tbl_grid is not None:
                grid_cols = tbl_grid.findall(f"{self.w_ns}gridCol")
                total_width = 0
                widths = []
                for col in grid_cols:
                    w_val = col.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}w")
                    if w_val:
                        width = int(w_val)
                        widths.append(width)
                        total_width += width

                # Calculate percentages
                if total_width > 0 and widths:
                    for width in widths:
                        percentage = (width / total_width) * 100
                        column_widths.append(f"{percentage:.2f}%")
                    print(f"[_process_table_to_html] Column widths from tblGrid: {column_widths}")
        except Exception as e:
            print(f"[_process_table_to_html] Error extracting column widths: {e}")

        current_cell_block_index = block_index
        cells_processed = 0
        table_borders = self._get_table_borders(table)
        last_row_idx = len(table.rows) - 1
        last_col_idx = len(table.columns) - 1
        cells_by_row = {}
        for cell_data in self._iter_visible_table_cells(table):
            cells_by_row.setdefault(cell_data["row_idx"], []).append(cell_data)

        for row_idx, row in enumerate(table.rows):
            table_html.append(f'<tr style="{self._get_row_style(row, row_idx)}">')
            for cell_data in cells_by_row.get(row_idx, []):
                cell = cell_data["cell"]
                col_idx = cell_data["col_idx"]
                colspan = cell_data["colspan"]
                rowspan = cell_data["rowspan"]

                if colspan > 1:
                    print(f"[_process_table_to_html] Cell[{row_idx},{col_idx}] horizontal merge: colspan={colspan}")
                if rowspan > 1:
                    print(f"[_process_table_to_html] Cell[{row_idx},{col_idx}] vertical merge: rowspan={rowspan}")

                cell_content, cell_text = self._build_table_cell_paragraphs_html(
                    cell,
                    col_idx,
                    current_cell_block_index,
                )
                print(f"[_process_table_to_html] Cell[{row_idx},{col_idx}]: text=\"{cell_text[:30] if cell_text else '(empty)'}\", has_content={bool(cell_text)}")

                cell_style = self._build_table_cell_style(
                    cell,
                    row_idx,
                    cell_data["cell_idx"],
                    col_idx,
                    column_widths,
                    table_borders,
                    last_row_idx,
                    last_col_idx,
                )

                colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
                table_html.append(
                    '<td{0}{1} data-block-index="{2}" data-type="table_cell" data-table-index="{3}" data-row="{4}" data-col="{5}" style="{6}">{7}</td>'.format(
                        colspan_attr,
                        rowspan_attr,
                        current_cell_block_index,
                        table_index,
                        row_idx,
                        col_idx,
                        cell_style,
                        cell_content,
                    )
                )

                current_cell_block_index += 1
                cells_processed += 1

            table_html.append('</tr>')
        table_html.append('</table></div>')
        html_result = "\n".join(table_html)
        print(f"[_process_table_to_html] END Processed {cells_processed} cells, HTML length: {len(html_result)}")
        print(f"[_process_table_to_html] HTML preview: {html_result[:200]}...")
        return html_result

