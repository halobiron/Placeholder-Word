"""
Batch Operations Handler

Provides validation and execution functions for batch update operations.
This module serves as the bridge between the API endpoint and DocxFullEditor.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from docx_editor import DocxFullEditor
from batch_update_models import Operation

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def map_camel_to_snake(format_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map camelCase keys to snake_case for Python function parameters"""
    format_mapping = {
        'fontSize': 'font_size', 'fontName': 'font_name', 'allCaps': 'all_caps',
        'lineSpacing': 'line_spacing', 'spaceBefore': 'space_before',
        'spaceAfter': 'space_after', 'firstLineIndent': 'first_line_indent',
        'alignment': 'alignment'
    }
    return {format_mapping.get(k, k): v for k, v in format_data.items()}


def get_current_fields(editor: DocxFullEditor) -> List[str]:
    """Get list of current mergefield names from template"""
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    current_fields = []
    for fld in editor.doc.element.iter(f"{w_ns}fldSimple"):
        instr = fld.get(f"{w_ns}instr", "")
        match = re.search(r'MERGEFIELD\s+(\S+)', instr)
        if match:
            current_fields.append(match.group(1))
    return current_fields


def validate_block_index(editor: DocxFullEditor, block_index: int) -> Optional[int]:
    """Validate and convert block_index to paragraph_index"""
    para_index = editor.get_paragraph_index_from_block(block_index)
    if para_index is None:
        raise ValueError(f"Invalid block_index: {block_index}")
    return para_index


def validate_table_coordinates(editor: DocxFullEditor, table_index: int,
                               row_index: Optional[int] = None,
                               col_index: Optional[int] = None) -> None:
    """Validate table coordinates"""
    if table_index >= len(editor.doc.tables):
        raise ValueError(f"Invalid table_index: {table_index}")

    table = editor.doc.tables[table_index]
    if row_index is not None and row_index >= len(table.rows):
        raise ValueError(f"Invalid row_index: {row_index}")
    if col_index is not None:
        row = table.rows[row_index] if row_index is not None else table.rows[0]
        if col_index >= len(row.cells):
            raise ValueError(f"Invalid col_index: {col_index}")


def get_paragraph_at_index(editor: DocxFullEditor, para_index: int):
    """Get paragraph object at given index"""
    for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
        if idx == para_index:
            return para
    return None


# =============================================================================
# VALIDATION
# =============================================================================

def validate_operation(editor: DocxFullEditor, op: Operation) -> None:
    """Validate a single operation before execution"""
    current_fields = get_current_fields(editor)

    if op.type in ("rename_placeholder", "delete_placeholder", "add_placeholder",
                   "add_placeholder_by_offset"):
        _validate_placeholder_op(editor, op, current_fields)
    elif op.type in ("update_text", "delete_text_range"):
        _validate_text_op(editor, op)
    elif op.type in ("format_text", "format_paragraph"):
        _validate_format_op(editor, op)
    elif op.type in ("add_paragraph", "delete_paragraph", "delete_multiple_paragraphs",
                     "add_page_break", "add_table_at_cursor", "add_image_at_cursor",
                     "add_hyperlink"):
        _validate_structural_op(editor, op)
    elif op.type in ("add_table_row", "delete_table_row", "add_table_column",
                     "delete_table_column", "format_table_cell"):
        _validate_table_op(editor, op)


def _validate_placeholder_op(editor: DocxFullEditor, op: Operation,
                             current_fields: List[str]) -> None:
    """Validate placeholder operations with fuzzy matching"""
    # Helper: try exact match first, then try without numeric suffix
    def find_field(name: str) -> str | None:
        if name in current_fields:
            return name
        # Try removing _2, _3, etc. suffixes
        base_name = re.sub(r'_\d+$', '', name)
        if base_name in current_fields:
            return base_name
        return None

    if op.type == "rename_placeholder":
        old_match = find_field(op.old_name)
        if not old_match:
            raise ValueError(f"Field '{op.old_name}' không tồn tại")
        if op.new_name in current_fields and op.new_name != op.old_name:
            raise ValueError(f"Field '{op.new_name}' đã tồn tại")

    elif op.type == "delete_placeholder":
        field_match = find_field(op.field_name)
        if not field_match:
            raise ValueError(f"Field '{op.field_name}' không tồn tại")
        # Log mapping for debugging (actual fix happens in execute)
        if field_match != op.field_name:
            logger.info(f"Field name mapping: {op.field_name} -> {field_match}")

    elif op.type in ("add_placeholder", "add_placeholder_by_offset"):
        if op.block_index >= len(list(editor.doc.paragraphs)):
            raise ValueError(f"Invalid block_index: {op.block_index}")
        if op.field_name in current_fields:
            raise ValueError(f"Field '{op.field_name}' đã tồn tại")


def _validate_text_op(editor: DocxFullEditor, op: Operation) -> None:
    """Validate text operations"""
    validate_block_index(editor, op.block_index)
    if op.type == "delete_text_range":
        if op.start_offset < 0 or op.end_offset <= op.start_offset:
            raise ValueError("Invalid text range offsets")


def _validate_format_op(editor: DocxFullEditor, op: Operation) -> None:
    """Validate formatting operations"""
    validate_block_index(editor, op.block_index)
    if op.type == "format_text" and not op.format_config:
        raise ValueError("format_config is required")
    elif op.type == "format_paragraph" and not op.paragraph_format:
        raise ValueError("paragraph_format is required")


def _validate_structural_op(editor: DocxFullEditor, op: Operation) -> None:
    """Validate structural operations"""
    if op.type in ("add_paragraph", "delete_paragraph"):
        if op.block_index is not None:
            validate_block_index(editor, op.block_index)
        if all(v is not None for v in [op.table_index, op.row_index, op.col_index]):
            validate_table_coordinates(editor, op.table_index, op.row_index, op.col_index)
    elif op.type == "delete_multiple_paragraphs":
        for block in op.blocks:
            if "block_index" not in block:
                raise ValueError("Each block must have block_index")
            validate_block_index(editor, block["block_index"])
            has_table_coords = any(k in block for k in ("table_index", "row_index", "col_index"))
            if has_table_coords:
                if not all(k in block for k in ("table_index", "row_index", "col_index")):
                    raise ValueError("table_index, row_index, and col_index are required together")
                if "para_in_cell" not in block or block["para_in_cell"] is None:
                    raise ValueError("para_in_cell is required for delete_multiple_paragraphs in table cells")
    elif op.type in ("add_page_break", "add_table_at_cursor",
                     "add_image_at_cursor", "add_hyperlink"):
        validate_block_index(editor, op.block_index)

    if op.type == "add_hyperlink":
        if not op.url or not op.url.strip():
            raise ValueError("URL is required")
        if not op.url.startswith(('http://', 'https://', 'mailto:')):
            raise ValueError("URL phải bắt đầu bằng http://, https://, hoặc mailto:")


def _validate_table_op(editor: DocxFullEditor, op: Operation) -> None:
    """Validate table operations"""
    validate_table_coordinates(editor, op.table_index)
    table = editor.doc.tables[op.table_index]

    if op.type == "delete_table_row" and len(table.rows) <= 1:
        raise ValueError("Không thể xóa hàng cuối cùng")
    if op.type == "delete_table_column" and len(table.rows[0].cells) <= 1:
        raise ValueError("Không thể xóa cột cuối cùng")
    if op.type == "format_table_cell" and not op.format_options:
        raise ValueError("format_options is required")


# =============================================================================
# EXECUTION HANDLERS
# =============================================================================

def _execute_placeholder_op(editor: DocxFullEditor, op: Operation) -> None:
    """Execute placeholder operations with fuzzy matching"""
    current_fields = get_current_fields(editor)

    # Helper for fuzzy matching
    def find_actual_name(requested_name: str) -> str:
        if requested_name in current_fields:
            return requested_name
        base_name = re.sub(r'_\d+$', '', requested_name)
        return base_name if base_name in current_fields else requested_name

    if op.type == "rename_placeholder":
        old_actual = find_actual_name(op.old_name)
        if not editor.rename_placeholder(old_actual, op.new_name, op.occurrence_index):
            raise ValueError(f"Failed to rename '{old_actual}'")

    elif op.type == "delete_placeholder":
        actual_name = find_actual_name(op.field_name)
        if actual_name != op.field_name:
            logger.info(f"Deleting actual field: {actual_name} (requested: {op.field_name})")
        if not editor.delete_placeholder(actual_name):
            raise ValueError(f"Failed to delete '{actual_name}'")

    elif op.type == "add_placeholder":
        from template_manager import MailMergeProcessor
        processor = MailMergeProcessor()
        if not processor.inject_placeholder_at_location(
            editor.doc_path, op.block_index, op.field_name,
            "", [], [], op.position, None, None
        ):
            raise ValueError(f"Failed to add '{op.field_name}'")

    elif op.type == "add_placeholder_by_offset":
        editor.insert_placeholder_at_offset(
            paragraph_index=op.block_index,
            offset=op.offset,
            field_name=op.field_name,
            inherit_format=op.inherit_format
        )


def _execute_text_op(editor: DocxFullEditor, op: Operation) -> None:
    """Execute text operations"""
    para_index = validate_block_index(editor, op.block_index)
    if op.para_in_cell is not None:
        para_index = editor.get_table_cell_paragraph_index(op.block_index, op.para_in_cell)
        if para_index is None:
            raise ValueError(f"Invalid para_in_cell")
    else:
        block_map = getattr(editor, "_block_to_para_index_map", None) or {}
        block_data = block_map.get(op.block_index)
        if block_data and block_data.get("type") == "table_cell":
            # CRITICAL FIX: Use the stored cell object directly if available
            # This works correctly with merged cells
            cell = block_data.get("cell")
            if cell is None:
                # Fallback to old method if cell object is not stored
                for table in editor.doc.tables:
                    if block_data["row"] < len(table.rows) and block_data["col"] < len(table.rows[block_data["row"]].cells):
                        cell = table.rows[block_data["row"]].cells[block_data["col"]]
                        break
            if cell is not None and len(cell.paragraphs) > 1:
                logger.warning(
                    "update_text without para_in_cell on multi-paragraph cell: block_index=%s row=%s col=%s para_count=%s",
                    op.block_index, block_data["row"], block_data["col"], len(cell.paragraphs)
                )

    if op.type == "update_text":
        logger.info(
            "Executing update_text: block_index=%s para_index=%s para_in_cell=%s old_len=%s new_len=%s",
            op.block_index, para_index, op.para_in_cell,
            len(op.old_text or ""), len(op.new_text or "")
        )
        if not editor.replace_text_at_position(op.old_text, op.new_text, para_index):
            raise ValueError(f"Failed to update text")
    elif op.type == "delete_text_range":
        logger.info(
            "Executing delete_text_range: block_index=%s para_index=%s para_in_cell=%s start=%s end=%s",
            op.block_index, para_index, op.para_in_cell, op.start_offset, op.end_offset
        )
        target_paragraph = get_paragraph_at_index(editor, para_index)
        if target_paragraph:
            if not editor.delete_text_range(target_paragraph, op.start_offset, op.end_offset):
                raise ValueError(f"Failed to delete text range")


def _execute_format_op(editor: DocxFullEditor, op: Operation) -> None:
    """Execute formatting operations"""
    para_index = validate_block_index(editor, op.block_index)
    if op.para_in_cell is not None:
        para_index = editor.get_table_cell_paragraph_index(op.block_index, op.para_in_cell)
        if para_index is None:
            raise ValueError(f"Invalid para_in_cell")

    format_kwargs = map_camel_to_snake(
        op.format_config if op.type == "format_text" else op.paragraph_format
    )

    if op.type == "format_text":
        if not editor.apply_format_at_position(
            op.selected_text,
            para_index,
            start_offset=op.start_offset,
            end_offset=op.end_offset,
            **format_kwargs
        ):
            raise ValueError(f"Failed to format text")
    else:
        if not editor.apply_paragraph_formatting(para_index, **format_kwargs):
            raise ValueError(f"Failed to format paragraph")


def _execute_add_paragraph(editor: DocxFullEditor, op: Operation) -> None:
    """Execute add paragraph operation"""
    success = False

    if all(v is not None for v in [op.table_index, op.row_index, op.col_index]):
        success = editor.add_paragraph_in_table_cell(
            op.table_index, op.row_index, op.col_index, op.text, op.para_in_cell
        )
    elif op.block_index is not None:
        para_index = editor.get_paragraph_index_from_block(op.block_index)
        if para_index is not None:
            target_paragraph = get_paragraph_at_index(editor, para_index)
            if target_paragraph:
                if op.position == "after":
                    editor.insert_paragraph_after(target_paragraph, op.text)
                    success = True
                elif op.position == "before":
                    editor.insert_paragraph_before(target_paragraph, op.text)
                    success = True
    elif op.position == "end":
        last_para = list(editor.doc.paragraphs)[-1]
        editor.insert_paragraph_after(last_para, op.text)
        success = True

    if not success:
        raise ValueError("Failed to add paragraph")


def _execute_delete_paragraph(editor: DocxFullEditor, op: Operation) -> None:
    """Execute delete paragraph operation"""
    success = False

    if all(v is not None for v in [op.table_index, op.row_index, op.col_index]):
        table = editor.doc.tables[op.table_index]
        cell = table.rows[op.row_index].cells[op.col_index]
        if op.para_in_cell is not None and op.para_in_cell < len(cell.paragraphs):
            success = editor.delete_paragraph(cell.paragraphs[op.para_in_cell])
    else:
        para_index = editor.get_paragraph_index_from_block(op.block_index)
        if para_index is not None:
            target_paragraph = get_paragraph_at_index(editor, para_index)
            if target_paragraph:
                success = editor.delete_paragraph(target_paragraph)

    if not success:
        raise ValueError(f"Failed to delete paragraph")


def _execute_delete_multiple(editor: DocxFullEditor, op: Operation) -> None:
    """Execute delete multiple paragraphs operation"""
    deleted_count = 0

    resolved_targets = []

    for order, block_data in enumerate(op.blocks):
        try:
            start_offset = block_data.get("start_offset")
            end_offset = block_data.get("end_offset")
            is_partial = (start_offset is not None and end_offset is not None)

            if all(k in block_data for k in ["table_index", "row_index", "col_index"]):
                table = editor.doc.tables[block_data["table_index"]]
                cell = table.rows[block_data["row_index"]].cells[block_data["col_index"]]

                para_in_cell = block_data.get("para_in_cell")
                if para_in_cell is None:
                    raise ValueError("para_in_cell is required for delete_multiple_paragraphs in table cells")

                if para_in_cell < 0 or para_in_cell >= len(cell.paragraphs):
                    logger.warning(
                        "Skipping invalid table cell paragraph: table=%s row=%s col=%s para_in_cell=%s",
                        block_data["table_index"], block_data["row_index"], block_data["col_index"], para_in_cell
                    )
                    continue

                para_index = editor.get_table_cell_paragraph_index(block_data["block_index"], para_in_cell)
                if para_index is None:
                    logger.warning("Could not resolve paragraph index for block=%s para_in_cell=%s",
                                   block_data["block_index"], para_in_cell)
                    continue

                resolved_targets.append({
                    "order": order,
                    "para_index": para_index,
                    "paragraph": cell.paragraphs[para_in_cell],
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "is_partial": is_partial,
                    "source": block_data,
                })
            else:
                para_index = editor.get_paragraph_index_from_block(block_data["block_index"])
                if para_index is None:
                    continue

                target_paragraph = get_paragraph_at_index(editor, para_index)
                if not target_paragraph:
                    continue

                resolved_targets.append({
                    "order": order,
                    "para_index": para_index,
                    "paragraph": target_paragraph,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "is_partial": is_partial,
                    "source": block_data,
                })
        except Exception as e:
            logger.warning(f"Error resolving block {block_data}: {e}")
            continue

    # Delete from the end of the document backward so index shifts do not
    # invalidate later targets, especially inside the same table cell.
    resolved_targets.sort(key=lambda item: (item["para_index"], item["order"]), reverse=True)

    for target in resolved_targets:
        try:
            if target["is_partial"]:
                success = editor.delete_text_range(
                    target["paragraph"],
                    target["start_offset"],
                    target["end_offset"]
                )
            else:
                success = editor.delete_paragraph(target["paragraph"])

            if success:
                deleted_count += 1
            else:
                logger.warning("Delete failed for target: %s", target["source"])
        except Exception as e:
            logger.warning(f"Error deleting target {target['source']}: {e}")
            continue

    logger.info(f"Deleted {deleted_count} paragraphs")


def _execute_structural_op(editor: DocxFullEditor, op: Operation) -> None:
    """Execute structural operations"""
    if op.type == "add_paragraph":
        _execute_add_paragraph(editor, op)
    elif op.type == "delete_paragraph":
        _execute_delete_paragraph(editor, op)
    elif op.type == "delete_multiple_paragraphs":
        _execute_delete_multiple(editor, op)
    elif op.type == "add_page_break":
        if not editor.add_page_break_at_cursor(op.block_index, op.offset):
            raise ValueError(f"Failed to add page break")
    elif op.type == "add_table_at_cursor":
        para_index = validate_block_index(editor, op.block_index)
        editor.add_table_at_cursor(para_index, op.offset, op.rows, op.cols)
    elif op.type == "add_image_at_cursor":
        para_index = validate_block_index(editor, op.block_index)
        editor.add_image_at_cursor(para_index, op.offset, op.image_path, op.width)
    elif op.type == "add_hyperlink":
        para_index = validate_block_index(editor, op.block_index)
        if not editor.add_hyperlink(para_index, op.start_offset, op.end_offset, op.url):
            raise ValueError(f"Failed to add hyperlink")


def _execute_table_op(editor: DocxFullEditor, op: Operation) -> None:
    """Execute table operations"""
    if op.type == "add_table_row":
        insert_index = (op.row_index + 1 if op.position == "below" else op.row_index
                        if op.row_index is not None else len(editor.doc.tables[op.table_index].rows))
        if not editor.insert_table_row(op.table_index, insert_index):
            raise ValueError(f"Failed to add table row")
    elif op.type == "delete_table_row":
        if not editor.delete_table_row(op.table_index, op.row_index):
            raise ValueError(f"Failed to delete table row")
    elif op.type == "add_table_column":
        insert_index = (op.col_index + 1 if op.position == "right" else op.col_index
                        if op.col_index is not None else len(editor.doc.tables[op.table_index].rows[0].cells))
        if not editor.insert_table_column(op.table_index, insert_index):
            raise ValueError(f"Failed to add table column")
    elif op.type == "delete_table_column":
        if not editor.delete_table_column(op.table_index, op.col_index):
            raise ValueError(f"Failed to delete table column")
    elif op.type == "format_table_cell":
        if not editor.format_table_cell(op.table_index, op.row_index, op.col_index, op.format_options):
            raise ValueError(f"Failed to format table cell")


# =============================================================================
# MAIN EXECUTION FUNCTION
# =============================================================================

def execute_operation(editor: DocxFullEditor, op: Operation) -> None:
    """Execute a single operation"""
    try:
        logger.debug(f"Executing operation type: {op.type}")

        # Dispatch to appropriate handler
        if op.type in ("rename_placeholder", "delete_placeholder",
                       "add_placeholder", "add_placeholder_by_offset"):
            _execute_placeholder_op(editor, op)
        elif op.type in ("update_text", "delete_text_range"):
            _execute_text_op(editor, op)
        elif op.type in ("format_text", "format_paragraph"):
            _execute_format_op(editor, op)
        elif op.type in ("add_paragraph", "delete_paragraph", "delete_multiple_paragraphs",
                         "add_page_break", "add_table_at_cursor", "add_image_at_cursor",
                         "add_hyperlink"):
            _execute_structural_op(editor, op)
        elif op.type in ("add_table_row", "delete_table_row", "add_table_column",
                         "delete_table_column", "format_table_cell"):
            _execute_table_op(editor, op)
        else:
            raise ValueError(f"Unknown operation type: {op.type}")

        logger.info(f"Operation '{op.type}' executed successfully")

    except Exception as e:
        logger.error(f"Failed to execute operation '{op.type}': {e}")
        raise
