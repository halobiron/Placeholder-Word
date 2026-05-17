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


def find_row_cell_at_column(row, logical_col_idx: int):
    """Resolve a logical column index to the backing XML cell in that row.

    Returns:
        (cell, start_col, colspan) or (None, None, None) if not found.
    """
    current_col = 0
    for cell in iter_xml_row_cells(row):
        try:
            colspan = cell.grid_span
        except (AttributeError, TypeError):
            colspan = 1

        if current_col <= logical_col_idx < current_col + colspan:
            return cell, current_col, colspan
        current_col += colspan
    return None, None, None


def iter_visible_table_cells(table) -> Generator[tuple[int, int, _Cell, int, int], None, None]:
    """Yield visible table cells skipping vertically-merged continuations.

    Yields:
        (row_idx, logical_col_idx, cell, colspan, rowspan)
    """
    for row_idx, row in enumerate(table.rows):
        logical_col_idx = 0
        for cell in iter_xml_row_cells(row):
            colspan = max(1, cell.grid_span)
            vmerge_val = cell._tc.vMerge

            if vmerge_val == "continue":
                logical_col_idx += colspan
                continue

            rowspan = (cell._tc.bottom - cell._tc.top) if vmerge_val == "restart" else 1
            yield (row_idx, logical_col_idx, cell, colspan, rowspan)
            logical_col_idx += colspan
