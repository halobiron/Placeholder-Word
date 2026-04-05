"""
Mail Merge Processor - Uses SmartMailMergeConverter for Vietnamese forms
"""
import uuid
from pathlib import Path
from typing import Dict
from smart_mail_merge_converter import SmartMailMergeConverter
import mammoth


class MailMergeProcessor:
    """Convert .docx to Mail Merge template using SmartMailMergeConverter"""

    def __init__(self, gemini_api_key: str = None, timeout: int = 30):
        """Initialize processor

        Args:
            gemini_api_key: Not used, kept for backward compatibility
            timeout: Not used, kept for backward compatibility
        """
        pass  # SmartMailMergeConverter doesn't need API keys

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
            output_path = Path("backend/uploads/templates") / f"{template_id}.docx"
        else:
            output_path = Path(output_path)
            template_id = output_path.stem

        try:
            # Use SmartMailMergeConverter
            converter = SmartMailMergeConverter(docx_path)
            fields = converter.convert(str(output_path))

            # Generate HTML preview from converted template
            html_preview = self._generate_html_preview(str(output_path), fields)

            return {
                "template_id": template_id,
                "fields": fields,
                "field_count": len(fields),
                "html_preview": html_preview,
                "method": "smart_converter",
                "note": "Full XML surgical injection with Vietnamese support"
            }

        except Exception as e:
            raise RuntimeError(f"Conversion failed: {str(e)}")

    def _generate_html_preview(self, docx_path: str, fields: list) -> str:
        """Generate HTML preview with highlighted placeholders and preserved formatting

        Uses python-docx with recursive processing for nested structures (smartTag, hyperlink, etc.)

        Args:
            docx_path: Path to converted .docx template
            fields: List of detected field names

        Returns:
            HTML string with highlighted placeholders and formatting
        """
        import re
        from docx import Document

        try:
            doc = Document(docx_path)
            w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            html_parts = []

            def get_paragraph_alignment(p_element):
                """Extract paragraph alignment from w:jc"""
                jc = p_element.find(f"{w_ns}pPr/{w_ns}jc")
                if jc is not None:
                    align = jc.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    align_map = {"left": "left", "center": "center", "right": "right", "both": "justify"}
                    return align_map.get(align, "left")
                return "left"

            def get_run_style_text(rPr):
                """Extract run formatting as CSS styles"""
                styles = []
                if rPr is None:
                    return ""

                # Bold
                if rPr.find(f"{w_ns}b") is not None:
                    styles.append("font-weight: bold")

                # Italic
                if rPr.find(f"{w_ns}i") is not None:
                    styles.append("font-style: italic")

                # Underline
                u = rPr.find(f"{w_ns}u")
                if u is not None:
                    styles.append("text-decoration: underline")

                # Strike
                if rPr.find(f"{w_ns}strike") is not None:
                    styles.append("text-decoration: line-through")

                # Font size
                sz = rPr.find(f"{w_ns}sz")
                if sz is not None:
                    size_val = sz.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    if size_val:
                        pt_size = int(size_val) / 2
                        styles.append(f"font-size: {pt_size}pt")

                # Color
                color = rPr.find(f"{w_ns}color")
                if color is not None:
                    color_val = color.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val")
                    if color_val and color_val != "auto":
                        if len(color_val) == 6:
                            styles.append(f"color: #{color_val}")

                # Highlight/Background color
                shd = rPr.find(f"{w_ns}shd")
                if shd is not None:
                    fill = shd.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}fill")
                    if fill and fill != "auto":
                        styles.append(f"background-color: #{fill}")

                # Font family
                rFonts = rPr.find(f"{w_ns}rFonts")
                if rFonts is not None:
                    ascii_font = rFonts.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}ascii")
                    if ascii_font:
                        styles.append(f"font-family: '{ascii_font}', Calibri, Arial, sans-serif")

                return "; ".join(styles) if styles else ""

            def process_run(run_element):
                """Process a single run and return HTML with formatting"""
                text_parts = []

                rPr = run_element.find(f"{w_ns}rPr")
                style_text = get_run_style_text(rPr)

                # Extract text from w:t elements
                for t in run_element.findall(f"{w_ns}t"):
                    if t.text:
                        text_parts.append(t.text)

                # Check for tab
                tab = run_element.find(f"{w_ns}tab")
                if tab is not None:
                    text_parts.append("    ")

                # Check for line break
                br = run_element.find(f"{w_ns}br")
                if br is not None:
                    text_parts.append("<br>")

                text = "".join(text_parts)

                if not text:
                    return ""

                # Highlight mail merge placeholders: «FieldName»
                def highlight_placeholder(match):
                    field_name = match.group(1).strip()
                    placeholder_style = style_text if style_text else ""
                    return f'<span class="mail-merge-placeholder" data-field="{field_name}" contenteditable="false" style="{placeholder_style}">«{field_name}»</span>'

                text_with_highlights = re.sub(r'«([^»]+)»', highlight_placeholder, text)

                # Wrap with span if there's styling
                if style_text and not re.search(r'«[^»]+»', text):
                    return f'<span style="{style_text}">{text_with_highlights}</span>'
                return text_with_highlights

            def process_element(element):
                """Recursively process any XML element (handles smartTag, hyperlink, etc.)"""
                if element is None:
                    return ""

                # Get namespace
                ns = element.tag.split('}')[0] + '}' if '}' in element.tag else ''
                tag_name = element.tag.split('}')[1] if '}' in element.tag else element.tag

                # Process based on tag type
                if tag_name == 'r':
                    # Regular run
                    return process_run(element)

                elif tag_name == 'fldSimple':
                    # Mail merge field - extract from instr attribute OR nested text
                    instr = element.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")
                    match = re.search(r'MERGEFIELD\s+(\S+)', instr)

                    # Try to get field name from instr first
                    if match:
                        field_name = match.group(1)
                    else:
                        # Fallback: extract from nested w:r/w:t text
                        nested_r = element.find(f"{w_ns}r")
                        if nested_r is not None:
                            for t in nested_r.findall(f"{w_ns}t"):
                                if t.text:
                                    # Extract from «field_name» format
                                    text_match = re.search(r'«([^»]+)»', t.text)
                                    if text_match:
                                        field_name = text_match.group(1)
                                        break
                            else:
                                field_name = "unknown"
                        else:
                            field_name = "unknown"

                    # Get styling from nested run
                    nested_r = element.find(f"{w_ns}r")
                    style_text = ""
                    actual_text = ""
                    if nested_r is not None:
                        rPr = nested_r.find(f"{w_ns}rPr")
                        style_text = get_run_style_text(rPr)

                        # Get actual text content from w:t elements
                        for t in nested_r.findall(f"{w_ns}t"):
                            if t.text:
                                actual_text += t.text

                    # Check if field has been filled (actual text is not in placeholder format)
                    if actual_text and not re.match(r'^«[^»]+»$', actual_text):
                        # Field has been filled with actual value - display it
                        return f'<span style="{style_text}">{actual_text}</span>'
                    else:
                        # Still a placeholder - highlight it
                        return f'<span class="mail-merge-placeholder" data-field="{field_name}" contenteditable="false" style="{style_text}">«{field_name}»</span>'

                elif tag_name == 'smartTag' or tag_name == 'hyperlink':
                    # Nested structures - process all children recursively
                    content_parts = []
                    for child in element:
                        content_parts.append(process_element(child))
                    return "".join(content_parts)

                else:
                    # Unknown element type - try to process children
                    content_parts = []
                    for child in element:
                        content_parts.append(process_element(child))
                    return "".join(content_parts)

                return ""

            # Process paragraphs
            for para in doc.paragraphs:
                p_element = para._p
                alignment = get_paragraph_alignment(p_element)

                # Get paragraph style
                style_name = para.style.name if para.style else "Normal"

                # Determine HTML tag based on style
                if "Heading 1" in style_name:
                    tag = "h1"
                elif "Heading 2" in style_name:
                    tag = "h2"
                elif "Heading 3" in style_name:
                    tag = "h3"
                else:
                    tag = "p"

                # Process all children in document order with recursive handling
                content_parts = []
                for child in p_element:
                    result = process_element(child)
                    if result:
                        content_parts.append(result)

                content = "".join(content_parts)

                if not content.strip():
                    html_parts.append("<p>&nbsp;</p>")
                    continue

                # Build paragraph HTML with alignment
                align_style = f"text-align: {alignment};" if alignment != "left" else ""
                html_parts.append(f'<{tag} style="{align_style}">{content}</{tag}>')

            # Process tables
            for table in doc.tables:
                table_html = ['<table class="docx-table" style="border-collapse: collapse; width: 100%; margin: 10px 0;">']

                for row_idx, row in enumerate(table.rows):
                    table_html.append('<tr style="border: 1px solid #ccc;">')
                    for cell in row.cells:
                        cell_content = []
                        for para in cell.paragraphs:
                            p_element = para._p
                            content_parts = []
                            for child in p_element:
                                result = process_element(child)
                                if result:
                                    content_parts.append(result)
                            cell_content.append("".join(content_parts))

                        cell_text = "".join(cell_content)
                        tag = "th" if row_idx == 0 else "td"
                        table_html.append(f'<{tag} style="border: 1px solid #ccc; padding: 5px;">{cell_text}</{tag}>')
                    table_html.append('</tr>')

                table_html.append('</table>')
                html_parts.append("\n".join(table_html))

            return "\n".join(html_parts)

        except Exception as e:
            import traceback
            # Return error message with details
            error_html = f'''
            <div class="error" style="
                padding: 20px;
                background-color: #fee;
                border: 1px solid #fcc;
                border-radius: 4px;
                color: #c33;
            ">
                <h3>Lỗi chuyển đổi DOCX</h3>
                <p>Không thể chuyển đổi tài liệu sang HTML.</p>
                <pre style="background: #fff; padding: 10px; border-radius: 4px; overflow: auto;">{str(e)}\n{traceback.format_exc()}</pre>
            </div>
            '''
            return error_html

