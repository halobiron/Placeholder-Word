"""
Mail Merge Processor - Uses SmartMailMergeConverter for Vietnamese forms
"""
import uuid
import re
import json
from pathlib import Path
from typing import Dict
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table
from docx.text.paragraph import Paragraph
import copy
import re
from smart_mail_merge_converter import SmartMailMergeConverter
from gemini_client import GeminiClient


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

    def _clean_gemini_json_response(self, response_text: str) -> dict:
        """Clean Gemini JSON response by removing markdown code blocks

        Args:
            response_text: Raw response text from Gemini

        Returns:
            Parsed JSON dict, or empty dict if parsing fails
        """
        result = response_text.strip()

        # Remove markdown code blocks
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]

        try:
            return json.loads(result.strip())
        except json.JSONDecodeError:
            return {}

    def convert_to_mail_merge(self, docx_path: str, output_path: str = None) -> Dict:
        """Convert .docx to Mail Merge template using SmartMailMergeConverter

        Args:
            docx_path: Path to input .docx file
            output_path: Path to save template (optional)

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
            fields = converter.convert(str(output_path))
            print(f"Basic fields created: {fields}")

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
            child_count = 0
            table_count = 0
            para_count = 0
            for child in doc.element.body.iterchildren():
                child_count += 1
                child_type = type(child).__name__
                if isinstance(child, CT_Tbl):
                    table_count += 1
                    print(f"[DEBUG] Child #{child_count}: TABLE #{table_count} (type: {child_type})")
                elif isinstance(child, CT_P):
                    para_count += 1
                    print(f"[DEBUG] Child #{child_count}: PARAGRAPH #{para_count}")
                else:
                    print(f"[DEBUG] Child #{child_count}: UNKNOWN TYPE (type: {child_type}, isinstance CT_Tbl: {isinstance(child, CT_Tbl)}, isinstance CT_P: {isinstance(child, CT_P)})")

            print(f"[DEBUG] Total children: {child_count} (tables: {table_count}, paras: {para_count})")

            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)

                    # Extract text from XML to match inject_placeholder_at_location logic
                    text_from_xml = ""
                    for t in child.findall(f".//{self.w_ns}t"):
                        if t.text:
                            text_from_xml += t.text
                    text = text_from_xml.strip()

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
                        if text:
                            print(f"[HTML Preview] Block {block_index}: {text[:60]}...")
                        else:
                            print(f"[HTML Preview] Block {block_index}: IMAGE ONLY (no text)")
                        block_index += 1
                    else:
                        # Empty paragraph - render with block_index (selectable for adding placeholders)
                        html = self._process_para_to_html(para, block_index, is_empty=True)
                        html_parts.append(html)
                        print(f"[HTML Preview] Block {block_index}: EMPTY LINE (selectable)")
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
                    cell_index = 0
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                        # Extract cell text to check if it has content
                            cell_text = ""
                            for para in cell.paragraphs:
                                for t in para._p.findall(f".//{self.w_ns}t"):
                                    if t.text:
                                        cell_text += t.text

                            cell_text = cell_text.strip()

                            if cell_text:
                                table_has_content = True
                                print(f"[HTML Preview] Block {block_index}: TABLE_CELL[{row_idx},{cell_idx}] - {cell_text[:60]}...")

                            # CRITICAL FIX: Increment block_index for ALL cells, not just non-empty ones
                            # This ensures consistency with _process_table_to_html and _build_block_index_map
                            block_index += 1
                            cell_index += 1

                    # CRITICAL FIX: Always render table, even if empty!
                    # New tables added by user will be empty initially but should still be visible
                    # Use the starting block index for the table (first cell's block_index)
                    html = self._process_table_to_html(table, table_start_block_index, current_table_index)
                    html_parts.append(html)
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
            for idx, child in enumerate(doc.element.body.iterchildren()):
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)

                    # Extract text from XML to handle special formatting (separate runs)
                    # This fixes issue where para.text misses content from separate runs
                    # Use .// to find ALL w:t elements at any level within paragraph
                    text_from_xml = ""
                    for t in child.findall(f".//{self.w_ns}t"):
                        if t.text:
                            text_from_xml += t.text

                    text = text_from_xml.strip()

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
                            # Extract text from XML (same logic as paragraphs)
                            cell_text = ""
                            for para in cell.paragraphs:
                                for t in para._p.findall(f".//{self.w_ns}t"):
                                    if t.text:
                                        cell_text += t.text

                            cell_text = cell_text.strip()

                            # CRITICAL: Add ALL cells (including empty ones) for consistency
                            # This ensures block index is consistent across all components
                            if cell_text or not cell_text:  # Always add, regardless of content
                                if cell_text:
                                    table_has_content = True

                                # Find the first paragraph in this cell
                                para_to_use = None
                                if cell.paragraphs:
                                    para_to_use = cell.paragraphs[0]

                                # Add cell as a separate block with precise location metadata
                                content_blocks.append({
                                    "type": "table_cell",
                                    "text": cell_text if cell_text else "",  # Empty string for empty cells
                                    "table_row": row_idx,
                                    "table_col": cell_idx,
                                    "docx_index": len(content_blocks),  # CRITICAL FIX: Use block index, not table index
                                    # Store table structure context to disambiguate similar cells
                                    "table_context": f"Row {row_idx}, Col {cell_idx}",
                                    "is_empty": not cell_text  # Track if cell is empty
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
                            "docx_index": idx
                        })
                        print(f"[{len(content_blocks)-1}] TABLE_SUMMARY: {table_text[:80]}...")

            print(f"=== TOTAL BLOCKS: {len(content_blocks)} ===")

            # Add surrounding context for each block to help disambiguate similar content
            for i in range(len(content_blocks)):
                # Get 2 blocks before and after
                before = []
                after = []

                for j in range(max(0, i-2), i):
                    before.append(content_blocks[j]["text"][:50])
                for j in range(i+1, min(len(content_blocks), i+3)):
                    after.append(content_blocks[j]["text"][:50])

                content_blocks[i]["before_context"] = before
                content_blocks[i]["after_context"] = after

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

        # Step 1: Clean and create base field name from text
        # Remove common Vietnamese field markers
        text = re.sub(
            r'^(họ và tên|tên|ngày sinh|năm sinh|số cmnd|số cccd|địa chỉ|email|điện thoại|sdt|nơi sinh|quốc tịch|dân tộc|tôn giáo|nghề nghiệp|người liên hệ):\s*',
            '',
            text,
            flags=re.IGNORECASE
        )

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
                suggestion = self._clean_gemini_json_response(response.text)
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
            block_index: Index of content block (from Gemini verify step)
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
            doc = Document(docx_path)
            current_index = 0
            candidates = []

            print(f"=== INJECT PLACEHOLDER: LOOKING FOR BLOCK_INDEX {block_index} ===")
            print(f"Context hint: {context_hint[:100] if context_hint else 'None'}...")
            print(f"Before context: {before_context}")
            print(f"After context: {after_context}")

            # First pass: collect all candidates with their indices AND surrounding context
            # IMPORTANT: Use same logic as extract_structured_content - extract from XML for full text
            # Include BOTH non-empty AND empty paragraphs to allow adding placeholders to empty lines
            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)

                    # Extract text from XML to match extract_structured_content logic
                    # This ensures index consistency between analysis and injection
                    text_from_xml = ""
                    for t in child.findall(f".//{self.w_ns}t"):
                        if t.text:
                            text_from_xml += t.text
                    text = text_from_xml.strip()

                    # Include ALL paragraphs (both empty and non-empty) to match HTML preview behavior
                    # This allows users to click on empty lines to add placeholders
                    candidates.append({
                        'type': 'paragraph',
                        'index': current_index,
                        'text': text if text else "[EMPTY LINE]",
                        'para': para,
                        'is_empty': not text
                    })
                    print(f"[Injection] Block {current_index}: {text[:60] if text else '[EMPTY]'}...")
                    current_index += 1
                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    table_has_content = False

                    # Process each cell as a separate candidate (matching extract_structured_content logic)
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                            # Extract from XML to match extract_structured_content logic
                            cell_text = ""
                            for para in cell.paragraphs:
                                for t in para._p.findall(f".//{self.w_ns}t"):
                                    if t.text:
                                        cell_text += t.text

                            cell_text = cell_text.strip()

                            if cell_text:
                                table_has_content = True
                                candidates.append({
                                    'type': 'table_cell',
                                    'index': current_index,
                                    'text': cell_text,
                                    'table': table,
                                    'row': row_idx,
                                    'col': cell_idx,
                                    'cell': cell  # Store direct cell reference for precise targeting
                                })
                                print(f"[Injection] Block {current_index}: TABLE_CELL[{row_idx},{cell_idx}] - {cell_text[:50]}...")
                                current_index += 1

                    # Add table summary block for backward compatibility
                    if table_has_content:
                        all_cells_text = ""
                        for row in table.rows:
                            for cell in row.cells:
                                for para in cell.paragraphs:
                                    for t in para._p.findall(f".//{self.w_ns}t"):
                                        if t.text:
                                            all_cells_text += t.text + " "

                        candidates.append({
                            'type': 'table_summary',
                            'index': current_index,
                            'text': all_cells_text.strip(),
                            'table': table
                        })
                        print(f"[Injection] Block {current_index}: TABLE_SUMMARY - {all_cells_text[:50]}...")
                        current_index += 1

            # Add surrounding context to candidates for disambiguation
            for i in range(len(candidates)):
                before = []
                after = []

                for j in range(max(0, i-2), i):
                    before.append(candidates[j]["text"][:50])
                for j in range(i+1, min(len(candidates), i+3)):
                    after.append(candidates[j]["text"][:50])

                candidates[i]["before_context"] = before
                candidates[i]["after_context"] = after

            print(f"=== INJECTION: TOTAL CANDIDATES: {len(candidates)} ===")

            # Find best match using VERIFIED block_index from Gemini
            best_match = None

            for candidate in candidates:
                # PRIMARY: Use verified block_index directly
                if candidate['index'] == block_index:
                    best_match = candidate
                    print(f"✓ DIRECT INDEX MATCH: [{candidate['index']}] ({candidate['type']})")
                    print(f"  Text: {candidate['text'][:60]}...")

                    # For table cells, show location
                    if candidate['type'] == 'table_cell':
                        print(f"  Cell location: [{candidate.get('row', '?')},{candidate.get('col', '?')}]")

                    # VERIFY: Check if before/after context matches
                    if before_context or after_context:
                        context_match_score = self._verify_context_match(
                            candidate, before_context, after_context
                        )
                        print(f"  Context match score: {context_match_score:.2f}")

                        if context_match_score < 0.3:
                            print(f"  ⚠️ WARNING: Low context match, but using verified index anyway")
                    break

            # Fallback: If direct index match fails, use context similarity
            if not best_match and context_hint:
                print(f"⚠️ No direct index match, falling back to context similarity...")
                best_score = 0
                for candidate in candidates:
                    similarity = self._calculate_context_similarity(candidate, context_hint, candidates)
                    print(f"Similarity [{candidate['index']}]: {similarity:.2f} - {candidate['text'][:50]}...")
                    if similarity > best_score:
                        best_score = similarity
                        best_match = candidate

            if best_match:
                print(f"→ INJECTING at index {best_match['index']}: {best_match['text'][:50]}...")
                print(f"  Position: {position}")
                if best_match['type'] == 'paragraph':
                    if self._inject_placeholder_in_paragraph(best_match['para'], placeholder_name, context_hint, position, insert_after):
                        doc.save(docx_path)
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
                        if self._inject_placeholder_in_paragraph(target_para, placeholder_name, context_hint, position, insert_after):
                            # Set vertical alignment to center for table cell
                            tc_pr = cell._element.get_or_add_tcPr()
                            v_align = tc_pr.find(qn('w:vAlign'))
                            if v_align is None:
                                v_align = OxmlElement('w:vAlign')
                                tc_pr.append(v_align)
                            v_align.set(qn('w:val'), 'center')

                            doc.save(docx_path)
                            print(f"✓ INJECTION SUCCESSFUL")
                            return True
                    else:
                        print(f"✗ Target cell has no paragraphs")
                        return False
                else:
                    # For table_summary or legacy table type, use existing logic
                    if self._inject_placeholder_in_table(best_match['table'], placeholder_name, context_hint, position, cell_index, para_in_cell, insert_after):
                        doc.save(docx_path)
                        print(f"✓ INJECTION SUCCESSFUL")
                        return True

            print(f"✗ NO MATCH FOUND for block_index {block_index}")
            return False

        except Exception as e:
            print(f"Error injecting placeholder: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using word overlap

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score between 0 and 1
        """

        # Remove placeholders for comparison
        text1_clean = re.sub(r'«[^»]+»', '', text1)
        text2_clean = re.sub(r'«[^»]+»', '', text2)

        # Extract words (remove special chars, lowercase)
        words1 = set(re.findall(r'\w+', text1_clean.lower()))
        words2 = set(re.findall(r'\w+', text2_clean.lower()))

        if not words1 or not words2:
            return 0.0

        # Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    def _calculate_context_similarity(
        self,
        candidate: dict,
        context_hint: str,
        all_candidates: list
    ) -> float:
        """Calculate similarity using both text and surrounding context

        Args:
            candidate: Candidate block with text and context
            context_hint: Context text to match against
            all_candidates: All candidates for surrounding context

        Returns:
            Combined similarity score
        """

        # Base similarity on main text
        base_similarity = self._calculate_text_similarity(candidate['text'], context_hint)

        # If base similarity is low, don't bother with context
        if base_similarity < 0.3:
            return base_similarity

        # Boost score based on surrounding context uniqueness
        # Check if this candidate's context is unique among all candidates
        candidate_sig = self._get_context_signature(candidate)
        similar_contexts = 0

        for other in all_candidates:
            if other['index'] == candidate['index']:
                continue
            other_sig = self._get_context_signature(other)
            if self._signature_similarity(candidate_sig, other_sig) > 0.7:
                similar_contexts += 1

        # If this candidate has unique context, boost the score
        if similar_contexts == 0:
            return min(1.0, base_similarity * 1.2)  # 20% boost for unique context
        elif similar_contexts == 1:
            return base_similarity  # No boost if 1 similar context
        else:
            return base_similarity * 0.8  # Penalty if multiple similar contexts

    def _get_context_signature(self, candidate: dict) -> str:
        """Get a unique signature for a candidate based on surrounding context"""
        before = " | ".join(candidate.get("before_context", []))
        after = " | ".join(candidate.get("after_context", []))
        return f"[{before}] >>> [{after}]"

    def _signature_similarity(self, sig1: str, sig2: str) -> float:
        """Calculate similarity between two context signatures"""
        words1 = set(re.findall(r'\w+', sig1.lower()))
        words2 = set(re.findall(r'\w+', sig2.lower()))

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    def _verify_context_match(
        self,
        candidate: dict,
        expected_before: list,
        expected_after: list
    ) -> float:
        """Verify if candidate's context matches expected before/after context

        Args:
            candidate: Candidate block with before/after context
            expected_before: Expected before context from Gemini
            expected_after: Expected after context from Gemini

        Returns:
            Match score between 0 and 1
        """
        candidate_before = candidate.get("before_context", [])
        candidate_after = candidate.get("after_context", [])

        # Calculate similarity for before and after separately
        before_score = 0.0
        after_score = 0.0

        if expected_before and candidate_before:
            before_score = self._list_similarity(expected_before, candidate_before)

        if expected_after and candidate_after:
            after_score = self._list_similarity(expected_after, candidate_after)

        # Average score
        if expected_before and expected_after:
            return (before_score + after_score) / 2
        elif expected_before:
            return before_score
        elif expected_after:
            return after_score
        else:
            return 1.0  # No context to verify, assume perfect match

    def _list_similarity(self, list1: list, list2: list) -> float:
        """Calculate similarity between two lists of text"""

        # Convert lists to text
        text1 = " ".join(list1).lower()
        text2 = " ".join(list2).lower()

        # Extract words
        words1 = set(re.findall(r'\w+', text1))
        words2 = set(re.findall(r'\w+', text2))

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

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

            # Handle inline position - find exact location
            if position == "inline" and insert_after:
                print(f"  → Using inline injection after '{insert_after}'")
                return self._inject_inline_placeholder(paragraph, placeholder_name, insert_after)

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

            # Check if ends with dots or underscores
            if re.search(r'[._]{3,}$', original_text):
                # Extract the pattern to use as original text
                match = re.search(r'([._]{3,})$', original_text)
                original_pattern = match.group(1) if match else "..."

                print(f"  → Found pattern '{original_pattern}' at end, removing and adding placeholder")

                # Remove pattern from run text
                last_run.text = re.sub(r'[._]{3,}$', '', original_text)
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

    def _inject_inline_placeholder(
        self,
        paragraph,
        placeholder_name: str,
        insert_after: str
    ) -> bool:
        """Inject placeholder inline after specific text

        Args:
            paragraph: docx paragraph object
            placeholder_name: Name for the placeholder
            insert_after: Text to find and insert after

        Returns:
            True if successful, False otherwise
        """
        # Use body children to preserve document order
        import copy

        try:
            # Log context ban đầu
            para_text = paragraph.text if paragraph else ""
            print(f"\n[INLINE INJECTION]")
            print(f"  Placeholder: '{placeholder_name}'")
            print(f"  Insert after: '{insert_after}'")
            print(f"  Current paragraph: '{para_text}'")

            # Build full text from all runs
            full_text = ""
            run_ranges = []  # (start_idx, end_idx, run_object)

            for run in paragraph.runs:
                if run.text:
                    start = len(full_text)
                    full_text += run.text
                    end = len(full_text)
                    run_ranges.append((start, end, run))

            print(f"  → Full text built: '{full_text}'")

            # Find insert_after text
            search_idx = full_text.find(insert_after)
            if search_idx == -1:
                print(f"  ✗ Could not find '{insert_after}' in paragraph")
                return False

            print(f"  → Found '{insert_after}' at index {search_idx}")

            # Find which run contains the insertion point
            insert_point = search_idx + len(insert_after)
            target_run = None
            insert_offset = 0  # 0 = at beginning of run

            for start, end, run in run_ranges:
                if start <= insert_point <= end:
                    target_run = run
                    insert_offset = insert_point - start
                    break

            if not target_run:
                print(f"  ✗ Could not find target run for insertion")
                return False

            print(f"  → Target run found at offset {insert_offset}")

            # Get the run's style
            p_element = paragraph._p
            rPr = None
            for r in p_element.findall(f"{self.w_ns}r"):
                rPrCandidate = r.find(f"{self.w_ns}rPr")
                if rPrCandidate is not None:
                    rPr = rPrCandidate
                    break

            # Create MERGEFIELD element
            fld = OxmlElement('w:fldSimple')
            fld.set(qn('w:instr'), f' MERGEFIELD {placeholder_name} \\* MERGEFORMAT ')

            # Create run element with style
            run = OxmlElement('w:r')
            if rPr is not None:
                run.append(copy.deepcopy(rPr))

            # Create text element
            t = OxmlElement('w:t')
            if ' ' in (placeholder_name[0], placeholder_name[-1]):
                t.set(qn('xml:space'), 'preserve')
            t.text = f"«{placeholder_name}»"
            run.append(t)
            fld.append(run)

            # Split the run and insert placeholder
            original_text = target_run.text
            before_text = original_text[:insert_offset]
            after_text = original_text[insert_offset:]

            print(f"  → Splitting run: '{before_text}' + [PLACEHOLDER] + '{after_text}'")

            # Set the run's text to the part before insertion
            target_run.text = before_text

            # Find the run's XML element
            run_element = target_run._element

            # Get parent (the paragraph)
            parent = run_element.getparent()

            # Find the index of current run
            run_index = list(parent).index(run_element)

            # Insert the field after current run
            parent.insert(run_index + 1, fld)

            # If there's text after insertion, create a new run for it
            if after_text:
                new_run = OxmlElement('w:r')
                if rPr is not None:
                    new_run.append(copy.deepcopy(rPr))

                new_t = OxmlElement('w:t')
                new_t.text = after_text
                new_run.append(new_t)

                # Insert after the field
                parent.insert(run_index + 2, new_run)

            # Log kết quả
            final_text = paragraph.text
            print(f"[INLINE INJECTION] Final result: '{final_text}'")
            print(f"  ✓ Injected inline after '{insert_after}'\n")
            return True

        except Exception as e:
            print(f"[INLINE INJECTION] ✗ Error: {e}")
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
            self._add_new_paragraph_with_placeholder(paragraph, placeholder_name, original_text, fld)
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
        original_text: str,
        fld_element
    ):
        """Create a new paragraph with same indentation and add placeholder

        Args:
            original_paragraph: Original paragraph to copy indentation from
            placeholder_name: Name for the merge field
            original_text: Original text to preserve in \\z switch
            fld_element: The fldSimple element containing the placeholder
        """
        import copy

        original_p_element = original_paragraph._p

        # Log trạng thái ban đầu
        original_text_content = ""
        for t in original_p_element.findall(f".//{self.w_ns}t"):
            if t.text:
                original_text_content += t.text
        print(f"  [NEW LINE] Original paragraph: '{original_text_content}'")
        print(f"  [NEW LINE] Creating new paragraph with placeholder '{placeholder_name}'")

        # Get the parent element (could be body or cell)
        parent = original_p_element.getparent()

        # Create new paragraph
        new_p = OxmlElement('w:p')

        # Check if original paragraph has leading spaces in text
        # If so, preserve them by adding a run with spaces before the placeholder
        original_text_content = ""
        for t in original_p_element.findall(f".//{self.w_ns}t"):
            if t.text:
                original_text_content += t.text

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

    def _extract_font_style_from_paragraph(self, para) -> str:
        """
        Extract font style from paragraph's runs for empty paragraphs.

        Even when paragraph text is empty, the runs may contain font formatting
        that should be preserved in HTML preview.

        Args:
            para: Paragraph object

        Returns:
            CSS style string with font properties
        """
        font_styles = []

        # Try to get rPr from the first run in paragraph
        for run in para.runs:
            run_element = run._r
            rPr = run_element.find(f"{self.w_ns}rPr")
            if rPr is not None:
                # Extract font family
                rFonts = rPr.find(f"{self.w_ns}rFonts")
                if rFonts is not None:
                    ascii_font = rFonts.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}ascii")
                    if ascii_font:
                        font_styles.append(f"font-family: '{ascii_font}', Calibri, Arial, sans-serif")

                # Extract font size
                sz = rPr.find(f"{self.w_ns}sz")
                if sz is not None:
                    val = sz.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    if val:
                        font_size_pt = int(val) / 2  # Word uses half-points
                        font_styles.append(f"font-size: {font_size_pt}pt")

                # Extract color
                color = rPr.find(f"{self.w_ns}color")
                if color is not None:
                    val = color.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    if val and val != "auto" and len(val) == 6:
                        font_styles.append(f"color: #{val}")

                # Extract bold, italic, underline
                if rPr.find(f"{self.w_ns}b") is not None:
                    font_styles.append("font-weight: bold")
                if rPr.find(f"{self.w_ns}i") is not None:
                    font_styles.append("font-style: italic")
                if rPr.find(f"{self.w_ns}u") is not None:
                    font_styles.append("text-decoration: underline")

                # Found formatting, stop here
                if font_styles:
                    break

        return "; ".join(font_styles) + ";" if font_styles else ""

    def _get_run_style_text(self, rPr) -> str:
        """Map Word XML styles to CSS properties"""
        if rPr is None:
            return ""

        styles = []
        style_map = {
            f"{self.w_ns}b": "font-weight: bold",
            f"{self.w_ns}i": "font-style: italic",
            f"{self.w_ns}u": "text-decoration: underline",
            f"{self.w_ns}strike": "text-decoration: line-through"
        }

        for root_tag, css in style_map.items():
            if rPr.find(root_tag) is not None:
                styles.append(css)

        sz = rPr.find(f"{self.w_ns}sz")
        if sz is not None and sz.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val"):
            styles.append(f"font-size: {int(sz.get(f'{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val')) / 2}pt")

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

        # Handle all caps (w:caps) -> text-transform: uppercase
        caps = rPr.find(f"{self.w_ns}caps")
        if caps is not None:
            styles.append("text-transform: uppercase")

        # Handle vertical alignment (w:vertAlign) -> subscript/superscript
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

            # First line indent (w:ind)
            ind = pPr.find(f"{self.w_ns}ind")
            if ind is not None:
                first_line = ind.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}firstLine")
                if first_line:
                    first_line_pt = int(first_line) / 20
                    para_styles.append(f"text-indent: {first_line_pt}pt")

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
            # CRITICAL FIX: Extract font style from runs even when paragraph is empty
            font_style = self._extract_font_style_from_paragraph(para)

            cursor_style = "cursor: crosshair;" if block_index >= 0 else "cursor: default;"

            # FIX: Use empty content with CSS min-height instead of &nbsp;
            # This prevents non-breaking space from appearing when users type in empty paragraphs
            # The min-height: 1.2em + display: block ensures the paragraph is visible and clickable
            empty_content = ""

            # Check if this empty paragraph has a page break
            if has_page_break:
                # Empty paragraph WITH page break - show visual indicator
                return '<p data-block-index="{0}" data-type="paragraph" data-page-break="{1}" data-empty="true" class="docx-empty-para page-break-para" style="min-height: 1.2em; margin: 5px 0; padding: 0; {2}{3}" title="Ngắt trang (Page Break)">{4}</p>'.format(
                    block_index, str(has_page_break).lower(), cursor_style, font_style, empty_content
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
                return '<p data-block-index="{0}" data-type="paragraph" data-page-break="{1}" data-empty="true" class="docx-empty-para" style="min-height: 1.2em; margin: 5px 0; padding: 0; {2}{3}" title="Click để thêm placeholder">{4}</p>'.format(
                    block_index, str(has_page_break).lower(), cursor_style, font_style, empty_content
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
        table_html = ['<table class="docx-table" data-type="table" style="border-collapse: collapse; width: 100%; margin: 10px 0;">']

        # Track block index for each cell (matching extract_structured_content logic)
        current_cell_block_index = block_index
        cells_processed = 0

        for row_idx, row in enumerate(table.rows):
            table_html.append('<tr style="border: 1px solid #ccc;">')
            for cell_idx, cell in enumerate(row.cells):
                # Extract cell text to check if it has content
                cell_text = ""
                for para in cell.paragraphs:
                    for t in para._p.findall(f".//{self.w_ns}t"):
                        if t.text:
                            cell_text += t.text

                cell_text = cell_text.strip()
                print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}]: text=\"{cell_text[:30] if cell_text else '(empty)'}\", has_content={bool(cell_text)}")

                # ALWAYS render cells (even empty ones) to maintain table structure
                # This ensures HTML preview matches DOCX structure exactly
                cell_paragraphs_html = []
                para_index = 0  # Track paragraph index within cell for targeting

                # Process paragraphs in cell
                for para in cell.paragraphs:
                    # Extract text content to check if paragraph is empty
                    text_from_xml = ""
                    for t in para._p.findall(f".//{self.w_ns}t"):
                        if t.text:
                            text_from_xml += t.text

                    # Process paragraph content
                    para_content = "".join(self._process_xml_element_to_html(child) for child in para._p)

                    # Add metadata for each paragraph to enable precise targeting
                    para_metadata = f'data-para-in-cell="{para_index}" data-cell="{cell_idx}" data-cell-block-index="{current_cell_block_index}"'

                    if not para_content.strip():
                        # Empty paragraph in cell - preserve it but make it clickable
                        # CRITICAL FIX: Extract and preserve alignment even for empty paragraphs
                        para_style = "min-height: 1.2em; margin: 2px 0; cursor: crosshair;"

                        # Extract horizontal alignment from paragraph properties (NEW - for empty paragraphs too)
                        try:
                            pPr = para._p.find(f"{self.w_ns}pPr")
                            if pPr is not None:
                                jc = pPr.find(f"{self.w_ns}jc")
                                if jc is not None:
                                    jc_val = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "left")
                                    # Map Word alignment to CSS
                                    align_map = {
                                        "left": "left",
                                        "center": "center",
                                        "right": "right",
                                        "both": "justify"
                                    }
                                    css_align = align_map.get(jc_val, "left")
                                    para_style = f"min-height: 1.2em; margin: 2px 0; text-align: {css_align}; cursor: crosshair;"
                                    print(f"[_process_table_to_html] Empty Para[{para_index}] horizontal-align: {css_align} (PRESERVED)")
                        except Exception as e:
                            print(f"[_process_table_to_html] Error extracting empty paragraph alignment: {e}")

                        cell_paragraphs_html.append(f'<p {para_metadata} class="cell-paragraph" style="{para_style}" title="Click để thêm placeholder">&nbsp;</p>')
                    else:
                        # Non-empty paragraph - wrap in p tag with metadata
                        para_style = "margin: 2px 0;"

                        # Extract horizontal alignment from paragraph properties (NEW)
                        try:
                            pPr = para._p.find(f"{self.w_ns}pPr")
                            if pPr is not None:
                                jc = pPr.find(f"{self.w_ns}jc")
                                if jc is not None:
                                    jc_val = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "left")
                                    # Map Word alignment to CSS
                                    align_map = {
                                        "left": "left",
                                        "center": "center",
                                        "right": "right",
                                        "both": "justify"
                                    }
                                    css_align = align_map.get(jc_val, "left")
                                    para_style += f" text-align: {css_align};"
                                    print(f"[_process_table_to_html] Para[{para_index}] horizontal-align: {css_align}")
                        except Exception as e:
                            print(f"[_process_table_to_html] Error extracting paragraph alignment: {e}")

                        import re
                        text_content = re.sub(r'<[^>]+>', '', para_content)
                        if text_content and (text_content[0] in ' \t\n' or text_content[-1] in ' \t\n'):
                            para_style += " white-space: pre-wrap;"
                        cell_paragraphs_html.append(f'<p {para_metadata} class="cell-paragraph" style="{para_style}">{para_content}</p>')
                    para_index += 1

                # Create cell content (empty string if no paragraphs)
                cell_content = "".join(cell_paragraphs_html) if cell_paragraphs_html else "&nbsp;"

                tag = "th" if row_idx == 0 else "td"

                # Extract cell formatting from tcPr (table cell properties)
                cell_style = "border: 1px solid #ccc; padding: 5px;"
                try:
                    tcPr = cell._element.find(f"{self.w_ns}tcPr")
                    if tcPr is not None:
                        # Background color
                        shd = tcPr.find(f"{self.w_ns}shd")
                        if shd is not None:
                            fill = shd.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}fill")
                            if fill and fill != "auto":
                                cell_style += f" background-color: #{fill};"
                                print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}] background: #{fill}")

                        # Vertical alignment (NEW)
                        v_align = tcPr.find(f"{self.w_ns}vAlign")
                        if v_align is not None:
                            v_align_val = v_align.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val", "center")
                            # Map Word values to CSS
                            v_align_map = {"top": "top", "center": "middle", "bottom": "bottom"}
                            css_v_align = v_align_map.get(v_align_val, "middle")
                            cell_style += f" vertical-align: {css_v_align};"
                            print(f"[_process_table_to_html] Cell[{row_idx},{cell_idx}] vertical-align: {css_v_align}")
                except Exception as e:
                    print(f"[_process_table_to_html] Error extracting cell formatting: {e}")

                # Add data-block-index for this cell (matching extract_structured_content)
                table_html.append('<{0} data-block-index="{1}" data-type="table_cell" data-table-index="{4}" data-row="{2}" data-col="{3}" style="{5}">{6}</{0}>'.format(
                    tag, current_cell_block_index, row_idx, cell_idx, table_index, cell_style, cell_content
                ))

                # Increment block index for next cell
                current_cell_block_index += 1
                cells_processed += 1

            table_html.append('</tr>')
        table_html.append('</table>')
        html_result = "\n".join(table_html)
        print(f"[_process_table_to_html] END Processed {cells_processed} cells, HTML length: {len(html_result)}")
        print(f"[_process_table_to_html] HTML preview: {html_result[:200]}...")
        return html_result



