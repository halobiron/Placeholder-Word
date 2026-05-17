"""
Batch Update Models for Universal DOCX Operations

Defines Pydantic models for all operation types that can be executed
in a single batch update transaction.

Pattern: Discriminated Union with strict validation per operation type
"""

from typing import List, Literal, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


# =============================================================================
# BASE OPERATION MODEL
# =============================================================================

class BaseOperation(BaseModel):
    """Base model for all operations with common fields"""
    type: str
    description: Optional[str] = Field(None, description="Optional description of this operation")


# =============================================================================
# PLACEHOLDER OPERATIONS
# =============================================================================

class RenamePlaceholderOp(BaseOperation):
    """
    Rename an existing placeholder to a new name

    Example:
        {"type": "rename_placeholder", "old_name": "ho_ten", "new_name": "ten_day_du"}
    """
    type: Literal["rename_placeholder"] = "rename_placeholder"
    old_name: str = Field(..., description="Current placeholder name")
    new_name: str = Field(..., description="New placeholder name")
    occurrence_index: Optional[int] = Field(
        None,
        ge=0,
        description="0-based occurrence index among placeholders sharing old_name; omit to rename all matches"
    )


class DeletePlaceholderOp(BaseOperation):
    """
    Delete a placeholder completely WITHOUT restoring original text

    This is TRUE DELETION - removes the MERGEFIELD entirely.

    Example:
        {"type": "delete_placeholder", "field_name": "dia_chi"}
    """
    type: Literal["delete_placeholder"] = "delete_placeholder"
    field_name: str = Field(..., description="Placeholder name to delete")


class AddPlaceholderOp(BaseOperation):
    """
    Add a placeholder at a specific position relative to block content

    Example:
        {"type": "add_placeholder", "block_index": 5, "field_name": "email",
         "position": "right"}
    """
    type: Literal["add_placeholder"] = "add_placeholder"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    field_name: str = Field(..., description="Name for new placeholder")
    position: Literal["left", "right", "new_line"] = Field("right", description="Where to insert")
    inherit_format: bool = Field(True, description="Inherit formatting from surrounding text")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


class AddPlaceholderByOffsetOp(BaseOperation):
    """
    Add a placeholder at a specific character offset within a paragraph

    Example:
        {"type": "add_placeholder_by_offset", "block_index": 10,
         "offset": 25, "field_name": "so_dien_thoai"}
    """
    type: Literal["add_placeholder_by_offset"] = "add_placeholder_by_offset"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    offset: int = Field(..., ge=0, description="Character offset in paragraph")
    field_name: str = Field(..., description="Name for new placeholder")
    inherit_format: bool = Field(True, description="Inherit formatting from surrounding text")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


# =============================================================================
# TEXT OPERATIONS
# =============================================================================

class UpdateTextOp(BaseOperation):
    """
    Update text content in a block while preserving formatting

    Uses fuzzy matching to find and replace text.

    Example:
        {"type": "update_text", "block_index": 5,
         "old_text": "Hello world", "new_text": "Hello Vietnam"}
    """
    type: Literal["update_text"] = "update_text"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    old_text: str = Field(..., description="Original text (for fuzzy matching)")
    new_text: str = Field(..., description="New text to replace with (empty string for deletion)")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


class DeleteTextRangeOp(BaseOperation):
    """
    Delete a specific range of text within a paragraph

    Example:
        {"type": "delete_text_range", "block_index": 3,
         "start_offset": 10, "end_offset": 25}
    """
    type: Literal["delete_text_range"] = "delete_text_range"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    start_offset: int = Field(..., ge=0, description="Start character offset")
    end_offset: int = Field(..., gt=0, description="End character offset")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


# =============================================================================
# FORMATTING OPERATIONS
# =============================================================================

class FormatTextOp(BaseOperation):
    """
    Apply character formatting to selected text

    format_config can include:
    - bold, italic, underline (bool)
    - strikethrough, subscript, superscript (bool)
    - color (hex, e.g., "FF0000")
    - highlight (hex or null)
    - fontSize (int, points)
    - fontName (str)

    Example:
        {"type": "format_text", "block_index": 5, "selected_text": "Hello",
         "format_config": {"bold": true, "color": "FF0000", "fontSize": 14}}
    """
    type: Literal["format_text"] = "format_text"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    selected_text: str = Field(..., description="Text to format")
    format_config: Dict[str, Any] = Field(..., description="Formatting options to apply")
    start_offset: Optional[int] = Field(None, ge=0, description="Start offset for precise targeting")
    end_offset: Optional[int] = Field(None, gt=0, description="End offset for precise targeting")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


class FormatParagraphOp(BaseOperation):
    """
    Apply paragraph formatting

    paragraph_format can include:
    - alignment (left/center/right/justify/distribute)
    - lineSpacing (float)
    - spaceBefore, spaceAfter (int, points)
    - firstLineIndent (int, points)
    - widowControl, keepTogether, keepWithNext (bool)

    Example:
        {"type": "format_paragraph", "block_index": 5,
         "paragraph_format": {"alignment": "center", "spaceAfter": 12}}
    """
    type: Literal["format_paragraph"] = "format_paragraph"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    paragraph_format: Dict[str, Any] = Field(..., description="Paragraph formatting options")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within table cell")


# =============================================================================
# STRUCTURAL OPERATIONS
# =============================================================================

class AddParagraphOp(BaseOperation):
    """
    Add a new paragraph

    Example (after block):
        {"type": "add_paragraph", "block_index": 5, "position": "after", "text": "New content"}

    Example (split at cursor - NEW):
        {"type": "add_paragraph", "block_index": 5, "offset": 10, "text": ""}

    Example (in table cell):
        {"type": "add_paragraph", "table_index": 0, "row_index": 1, "col_index": 2,
         "text": "Cell content", "para_in_cell": 0}
    """
    type: Literal["add_paragraph"] = "add_paragraph"
    block_index: Optional[int] = Field(None, ge=0, description="Block index (for after/before)")
    position: Literal["after", "before", "end"] = Field("after", description="Where to insert")
    text: str = Field("", description="Text content for new paragraph")
    table_index: Optional[int] = Field(None, ge=0, description="Table index")
    row_index: Optional[int] = Field(None, ge=0, description="Row index")
    col_index: Optional[int] = Field(None, ge=0, description="Column index")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within cell")
    offset: Optional[int] = Field(None, ge=0, description="Cursor offset to split paragraph at (NEW)")


class DeleteParagraphOp(BaseOperation):
    """
    Delete a single paragraph

    Example:
        {"type": "delete_paragraph", "block_index": 10}
    """
    type: Literal["delete_paragraph"] = "delete_paragraph"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    table_index: Optional[int] = Field(None, ge=0, description="Table index")
    row_index: Optional[int] = Field(None, ge=0, description="Row index")
    col_index: Optional[int] = Field(None, ge=0, description="Column index")
    para_in_cell: Optional[int] = Field(None, ge=0, description="Paragraph index within cell")


class DeleteMultipleParagraphsOp(BaseOperation):
    """
    Delete multiple paragraphs or text ranges

    Each block in blocks list:
    - block_index (required): Block index
    - start_offset, end_offset (optional): Delete partial text range
    - table_index, row_index, col_index, para_in_cell (optional): For table cells

    Example:
        {"type": "delete_multiple_paragraphs",
         "blocks": [
           {"block_index": 5},  # Delete entire paragraph
           {"block_index": 10, "start_offset": 5, "end_offset": 15}  # Delete range
         ]}
    """
    type: Literal["delete_multiple_paragraphs"] = "delete_multiple_paragraphs"
    blocks: List[Dict[str, Any]] = Field(..., description="List of blocks to delete")


class AddPageBreakOp(BaseOperation):
    """
    Add page break at cursor position (split paragraph at offset)

    Example:
        {"type": "add_page_break", "block_index": 3, "offset": 25}
    """
    type: Literal["add_page_break"] = "add_page_break"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    offset: int = Field(..., ge=0, description="Character offset to split at")


# =============================================================================
# TABLE OPERATIONS
# =============================================================================

class AddTableRowOp(BaseOperation):
    """
    Add a new row to a table

    Example:
        {"type": "add_table_row", "table_index": 0, "row_index": 2, "position": "below"}
    """
    type: Literal["add_table_row"] = "add_table_row"
    table_index: int = Field(..., ge=0, description="Table index")
    row_index: Optional[int] = Field(None, ge=0, description="Row index (None = add at end)")
    position: Literal["above", "below"] = Field("below", description="Insert position")


class DeleteTableRowOp(BaseOperation):
    """
    Delete a row from a table

    Example:
        {"type": "delete_table_row", "table_index": 0, "row_index": 3}
    """
    type: Literal["delete_table_row"] = "delete_table_row"
    table_index: int = Field(..., ge=0, description="Table index")
    row_index: int = Field(..., ge=0, description="Row index to delete")


class AddTableColumnOp(BaseOperation):
    """
    Add a new column to a table

    Example:
        {"type": "add_table_column", "table_index": 0, "col_index": 1, "position": "right"}
    """
    type: Literal["add_table_column"] = "add_table_column"
    table_index: int = Field(..., ge=0, description="Table index")
    col_index: Optional[int] = Field(None, ge=0, description="Column index (None = add at end)")
    position: Literal["left", "right"] = Field("right", description="Insert position")


class DeleteTableColumnOp(BaseOperation):
    """
    Delete a column from a table

    Example:
        {"type": "delete_table_column", "table_index": 0, "col_index": 2}
    """
    type: Literal["delete_table_column"] = "delete_table_column"
    table_index: int = Field(..., ge=0, description="Table index")
    col_index: int = Field(..., ge=0, description="Column index to delete")


class FormatTableCellOp(BaseOperation):
    """
    Format a table cell (background color, alignment, borders)

    format_options can include:
    - background_color (hex, e.g., "FFFF00" or "#FFFF00")
    - horizontal_align (left/center/right)
    - vertical_align (top/center/bottom)
    - borders (dict with top/bottom/left/right keys):
        Each border has: style (none/single/double/dashed/dotted), size (0-96), color (hex)
        Example: {"top": {"style": "single", "size": 4, "color": "#000000"}, ...}

    Example:
        {"type": "format_table_cell", "table_index": 0, "row_index": 1, "col_index": 2,
         "format_options": {"background_color": "FFFF00", "horizontal_align": "center",
          "borders": {"top": {"style": "single", "size": 4, "color": "#000000"}}}}
    """
    type: Literal["format_table_cell"] = "format_table_cell"
    table_index: int = Field(..., ge=0, description="Table index")
    row_index: int = Field(..., ge=0, description="Row index")
    col_index: int = Field(..., ge=0, description="Column index")
    format_options: Dict[str, Any] = Field(..., description="Cell formatting options")


class AddTableAtCursorOp(BaseOperation):
    """
    Add a new table at cursor position

    Example:
        {"type": "add_table_at_cursor", "block_index": 5, "offset": 10, "rows": 3, "cols": 4}
    """
    type: Literal["add_table_at_cursor"] = "add_table_at_cursor"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    offset: int = Field(..., ge=0, description="Character offset in paragraph")
    rows: int = Field(3, ge=1, le=20, description="Number of rows")
    cols: int = Field(3, ge=1, le=10, description="Number of columns")


class AddImageAtCursorOp(BaseOperation):
    """
    Add an image at cursor position

    Example:
        {"type": "add_image_at_cursor", "block_index": 5, "offset": 10,
         "image_path": "/uploads/photo.jpg", "width": 3.5}
    """
    type: Literal["add_image_at_cursor"] = "add_image_at_cursor"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    offset: int = Field(..., ge=0, description="Character offset in paragraph")
    image_path: str = Field(..., description="Path to image file")
    width: float = Field(4.0, ge=1.0, le=8.0, description="Image width in inches")


# =============================================================================
# HYPERLINK OPERATIONS
# =============================================================================

class AddHyperlinkOp(BaseOperation):
    """
    Add hyperlink to selected text range

    Example:
        {"type": "add_hyperlink", "block_index": 5,
         "start_offset": 10, "end_offset": 25, "url": "https://example.com"}
    """
    type: Literal["add_hyperlink"] = "add_hyperlink"
    block_index: int = Field(..., ge=0, description="Block index from HTML preview")
    start_offset: int = Field(..., ge=0, description="Start character offset")
    end_offset: int = Field(..., gt=0, description="End character offset")
    url: str = Field(..., description="Target URL")


# =============================================================================
# OPERATION UNION TYPE
# =============================================================================

Operation = Union[
    # Placeholder operations
    RenamePlaceholderOp,
    DeletePlaceholderOp,
    AddPlaceholderOp,
    AddPlaceholderByOffsetOp,
    # Text operations
    UpdateTextOp,
    DeleteTextRangeOp,
    # Formatting operations
    FormatTextOp,
    FormatParagraphOp,
    # Structural operations
    AddParagraphOp,
    DeleteParagraphOp,
    DeleteMultipleParagraphsOp,
    AddPageBreakOp,
    # Table operations
    AddTableRowOp,
    DeleteTableRowOp,
    AddTableColumnOp,
    DeleteTableColumnOp,
    FormatTableCellOp,
    AddTableAtCursorOp,
    # Image operations
    AddImageAtCursorOp,
    # Hyperlink operations
    AddHyperlinkOp,
]


# =============================================================================
# BATCH UPDATE REQUEST MODEL
# =============================================================================

class BatchUpdateRequest(BaseModel):
    """
    Request model for batch update endpoint

    Executes multiple operations in a single atomic transaction:
    - Validate all operations first
    - Execute all operations sequentially
    - Single file save at the end
    - Rollback on error if stop_on_error=True
    """
    template_id: str = Field(..., description="Template identifier")
    operations: List[Operation] = Field(..., min_items=1, description="List of operations to execute")
    validate_only: bool = Field(False, description="If True, only validate without executing")
    stop_on_error: bool = Field(True, description="If True, stop on first error; if False, continue")

    class Config:
        json_schema_extra = {
            "example": {
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "operations": [
                    {
                        "type": "rename_placeholder",
                        "old_name": "ho_ten",
                        "new_name": "ten_day_du"
                    },
                    {
                        "type": "delete_placeholder",
                        "field_name": "dia_chi_cu"
                    },
                    {
                        "type": "update_text",
                        "block_index": 5,
                        "old_text": "Xin chào",
                        "new_text": "Xin chào rất nhiều"
                    },
                    {
                        "type": "format_text",
                        "block_index": 10,
                        "selected_text": "Important",
                        "format_config": {"bold": True, "color": "FF0000"}
                    }
                ],
                "validate_only": False,
                "stop_on_error": True
            }
        }


# =============================================================================
# BATCH UPDATE RESPONSE MODEL
# =============================================================================

class BatchUpdateResponse(BaseModel):
    """Response model for batch update endpoint"""
    template_id: str
    success: bool
    total_operations: int
    successful: int
    failed: int
    operation_results: List[Dict[str, Any]]
    validation_errors: List[str] = []
    execution_errors: List[str] = []
    fields: List[str] = []
    field_count: int = 0
    html_preview: str = ""
