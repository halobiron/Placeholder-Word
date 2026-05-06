"""
Table navigation utilities for DOCX tables with merged cells.

Shared between MailMergeProcessor (template_manager) and DocxFullEditor (docx_editor)
to avoid duplicating lxml traversal logic that python-docx doesn't support.
"""
from __future__ import annotations

from typing import Generator

from docx.table import _Cell

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def iter_xml_row_cells(row) -> list[_Cell]:
    """Return actual XML cells in a row without python-docx merge expansion."""
    return [_Cell(tc, row) for tc in row._tr.tc_lst]


def get_cell_grid_span(cell) -> int:
    """Return the gridSpan value for a cell (how many logical columns it occupies)."""
    tcPr = cell._element.find(f"{W_NS}tcPr")
    if tcPr is None:
        return 1

    grid_span_elem = tcPr.find(f"{W_NS}gridSpan")
    if grid_span_elem is None:
        return 1

    grid_span_val = grid_span_elem.get(f"{W_NS}val")
    if not grid_span_val:
        return 1

    try:
        return max(1, int(grid_span_val))
    except (TypeError, ValueError):
        return 1


def find_row_cell_at_column(row, logical_col_idx: int):
    """Resolve a logical column index to the backing XML cell in that row.

    Returns:
        (cell, start_col, colspan) or (None, None, None) if not found.
    """
    current_col = 0
    for cell in iter_xml_row_cells(row):
        colspan = get_cell_grid_span(cell)
        if current_col <= logical_col_idx < current_col + colspan:
            return cell, current_col, colspan
        current_col += colspan
    return None, None, None


def get_vertical_merge_value(cell) -> str | None:
    """Return the vMerge value for a cell: 'restart', 'continue', or None."""
    tcPr = cell._element.find(f"{W_NS}tcPr")
    if tcPr is None:
        return None

    vmerge_elem = tcPr.find(f"{W_NS}vMerge")
    if vmerge_elem is None:
        return None

    return vmerge_elem.get(f"{W_NS}val", "continue")


def calculate_rowspan(table, start_row_idx: int, col_idx: int) -> int:
    """Count how many consecutive rows a vertically merged cell spans.

    Args:
        table: docx Table object
        start_row_idx: Row index where vMerge="restart" is found
        col_idx: Logical column index of the merged cell

    Returns:
        Number of rows spanned (minimum 1).
    """
    rowspan = 1
    total_rows = len(table.rows)

    for row_idx in range(start_row_idx + 1, total_rows):
        if row_idx >= total_rows:
            break
        row = table.rows[row_idx]
        cell, _, _ = find_row_cell_at_column(row, col_idx)
        try:
            if cell is not None:
                tcPr = cell._element.find(f"{W_NS}tcPr")
                if tcPr is not None:
                    vmerge_elem = tcPr.find(f"{W_NS}vMerge")
                    if vmerge_elem is not None:
                        vmerge_val = vmerge_elem.get(f"{W_NS}val", "continue")
                        if vmerge_val == "continue":
                            rowspan += 1
                        else:
                            break
                    else:
                        break
                else:
                    break
            else:
                break
        except Exception:
            break

    return rowspan


def iter_visible_table_cells(table) -> Generator[tuple[int, int, _Cell, int, int], None, None]:
    """Yield visible table cells skipping vertically-merged continuations.

    Yields:
        (row_idx, logical_col_idx, cell, colspan, rowspan)
    """
    for row_idx, row in enumerate(table.rows):
        logical_col_idx = 0
        for cell in iter_xml_row_cells(row):
            colspan = get_cell_grid_span(cell)
            vmerge_val = get_vertical_merge_value(cell)
            if vmerge_val == "continue":
                logical_col_idx += colspan
                continue

            rowspan = calculate_rowspan(table, row_idx, logical_col_idx) if vmerge_val == "restart" else 1
            yield (row_idx, logical_col_idx, cell, colspan, rowspan)
            logical_col_idx += colspan
