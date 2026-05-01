import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export const convertDocx = async (file) => {
  const formData = new FormData()
  formData.append('file', file)

  const response = await axios.post(`${API_BASE}/convert`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const suggestPlaceholders = async (templateId) => {
  const formData = new FormData()
  formData.append('template_id', templateId)

  const response = await axios.post(`${API_BASE}/suggest-placeholders`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const applySuggestions = async (templateId, suggestions) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('suggestions', JSON.stringify(suggestions))

  const response = await axios.post(`${API_BASE}/apply-suggestions`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const mergeTemplate = async (
  templateId,
  data,
  isDirectValues = false,
  activeFields = null,
  lockedFields = null
) => {
  const formData = new FormData()
  formData.append('template_id', templateId)

  if (isDirectValues) {
    // Send field values as JSON
    formData.append('field_values', JSON.stringify(data))
  } else {
    // Send context text for Gemini extraction
    formData.append('context', data)
  }

  if (activeFields) {
    formData.append('active_fields', JSON.stringify(activeFields))
  }

  if (lockedFields) {
    formData.append('locked_fields', JSON.stringify(lockedFields))
  }

  const response = await axios.post(`${API_BASE}/merge`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const downloadFile = (fileId) => {
  window.location.href = `${API_BASE}/download/${fileId}`
}

export const getPreview = async (resultId) => {
  const response = await axios.get(`${API_BASE}/preview/${resultId}`)
  return response.data
}

export const addPlaceholderByPosition = async (templateId, blockIndex, fieldName, position = 'right', cellIndex = null, paraInCell = null) => {
  return await batchUpdate(templateId, [{
    type: 'add_placeholder',
    block_index: blockIndex,
    field_name: fieldName,
    position: position,
    inherit_format: true
  }])
}

export const addPlaceholderByOffset = async (templateId, blockIndex, offset, fieldName, inheritFormat = true, paraInCell = null) => {
  return await batchUpdate(templateId, [{
    type: 'add_placeholder_by_offset',
    block_index: blockIndex,
    offset: offset,
    field_name: fieldName,
    inherit_format: inheritFormat
  }])
}

export const suggestFieldName = async (templateId, blockIndex, paraInCell = null) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('block_index', blockIndex)
  if (paraInCell !== null) {
    formData.append('para_in_cell', paraInCell)
  }

  const response = await axios.post(`${API_BASE}/suggest-field-name`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

// Apply formatting to selected text - using batch-update
export const editSelection = async (templateId, editData) => {
  // blockIndex is required for precise editing
  if (editData.blockIndex === undefined || editData.blockIndex === null) {
    throw new Error('blockIndex is required for editing')
  }

  // Process formatting
  if (!editData.format) {
    throw new Error('format is required')
  }

  // Separate text-level and paragraph-level formatting
  const { alignment, ...textFormat } = editData.format

  // If alignment is set, include it in paragraph_format
  let paragraphFormat = editData.paragraphFormat || {}
  if (alignment !== undefined && alignment !== 'left') {
    paragraphFormat.alignment = alignment
  }

  // Build operations array
  const operations = []

  // Add format_text operation if text formatting is provided
  if (Object.keys(textFormat).length > 0) {
    operations.push({
      type: 'format_text',
      block_index: editData.blockIndex,
      selected_text: editData.selectedText,
      start_offset: editData.startOffset,
      end_offset: editData.endOffset,
      para_in_cell: editData.paraInCell,
      format_config: textFormat
    })
  }

  // Add format_paragraph operation if paragraph formatting is provided
  if (Object.keys(paragraphFormat).length > 0) {
    operations.push({
      type: 'format_paragraph',
      block_index: editData.blockIndex,
      paragraph_format: paragraphFormat
    })
  }

  if (operations.length === 0) {
    throw new Error('No formatting to apply')
  }

  return await batchUpdate(templateId, operations)
}

export const updateTextInTemplate = async (templateId, { blockIndex, oldText, newText, paraInCell = null }) => {
  // Validate blockIndex before making the request
  if (isNaN(blockIndex) || blockIndex === null || blockIndex === undefined) {
    throw new Error(`Invalid blockIndex: ${blockIndex}`)
  }

  const operation = {
    type: 'update_text',
    block_index: blockIndex,
    old_text: oldText || '',
    new_text: newText || ''
  }

  if (paraInCell !== null && paraInCell !== undefined) {
    operation.para_in_cell = paraInCell
  }

  return await batchUpdate(templateId, [operation])
}

export const getSelectionFormat = async (templateId, selectedText, blockIndex, offset = null, endOffset = null, paraInCell = null) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('selected_text', selectedText)
  if (blockIndex !== null && blockIndex !== undefined) {
    formData.append('block_index', blockIndex)
  }
  // CRITICAL: Send offset information for precise format detection
  // This fixes bug where duplicate words always get format from first occurrence
  if (offset !== null && offset !== undefined) {
    formData.append('offset', offset)
  }
  if (endOffset !== null && endOffset !== undefined) {
    formData.append('end_offset', endOffset)
  }
  if (paraInCell !== null && paraInCell !== undefined) {
    formData.append('para_in_cell', paraInCell)
  }

  const response = await axios.post(`${API_BASE}/get-selection-format`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

/**
 * Table Operations - Implemented via batch_update for consistency
 */

export const addTableRow = async (templateId, tableIndex, rowIndex, position = 'below') => {
  return await batchUpdate(templateId, [{
    type: 'add_table_row',
    table_index: tableIndex,
    row_index: rowIndex,
    position: position
  }])
}

export const deleteTableRow = async (templateId, tableIndex, rowIndex) => {
  return await batchUpdate(templateId, [{
    type: 'delete_table_row',
    table_index: tableIndex,
    row_index: rowIndex
  }])
}

export const addTableColumn = async (templateId, tableIndex, colIndex, position = 'right') => {
  return await batchUpdate(templateId, [{
    type: 'add_table_column',
    table_index: tableIndex,
    col_index: colIndex,
    position: position
  }])
}

export const deleteTableColumn = async (templateId, tableIndex, colIndex) => {
  return await batchUpdate(templateId, [{
    type: 'delete_table_column',
    table_index: tableIndex,
    col_index: colIndex
  }])
}

export const formatTableCell = async (templateId, tableIndex, rowIndex, colIndex, formatOptions) => {
  return await batchUpdate(templateId, [{
    type: 'format_table_cell',
    table_index: tableIndex,
    row_index: rowIndex,
    col_index: colIndex,
    format_options: formatOptions
  }])
}

export const getCellFormat = async (templateId, tableIndex, rowIndex, colIndex) => {
  const response = await axios.get(`${API_BASE}/get-cell-format`, {
    params: {
      template_id: templateId,
      table_index: tableIndex,
      row_index: rowIndex,
      col_index: colIndex
    }
  })
  return response.data
}

export const addParagraph = async (templateId, blockIndex, position = 'after', text = '', tableIndex = null, rowIndex = null, colIndex = null, paraInCell = null) => {
  return await batchUpdate(templateId, [{
    type: 'add_paragraph',
    block_index: blockIndex,
    position: position,
    text: text,
    table_index: tableIndex,
    row_index: rowIndex,
    col_index: colIndex,
    para_in_cell: paraInCell
  }])
}

export const deleteParagraph = async (templateId, blockIndex, tableIndex = null, rowIndex = null, colIndex = null, paraInCell = null) => {
  return await batchUpdate(templateId, [{
    type: 'delete_paragraph',
    block_index: blockIndex,
    table_index: tableIndex,
    row_index: rowIndex,
    col_index: colIndex,
    para_in_cell: paraInCell
  }])
}

export const addTableAtCursor = async (templateId, blockIndex, offset, rows = 3, cols = 3) => {
  return await batchUpdate(templateId, [{
    type: 'add_table_at_cursor',
    block_index: blockIndex,
    offset: offset,
    rows: rows,
    cols: cols
  }])
}

export const addImageAtCursor = async (templateId, blockIndex, offset, imageFile, width = 4.0) => {
  // Keep using the dedicated endpoint because it handles file upload
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('block_index', blockIndex)
  formData.append('offset', offset)
  formData.append('width', width)
  formData.append('image', imageFile)

  const response = await axios.post(`${API_BASE}/add-image-at-cursor`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addHyperlink = async (templateId, blockIndex, startOffset, endOffset, url) => {
  return await batchUpdate(templateId, [{
    type: 'add_hyperlink',
    block_index: blockIndex,
    start_offset: startOffset,
    end_offset: endOffset,
    url: url
  }])
}

/**
 * Batch Update API - Execute multiple operations in a single atomic transaction

 * This universal endpoint handles ALL DOCX editing operations:
 * - Placeholder operations: rename, delete, add
 * - Text operations: update, delete range
 * - Formatting operations: format text, format paragraph
 * - Structural operations: add/delete paragraphs, page breaks
 * - Table operations: add/delete rows/columns, format cells, add tables
 * - Image operations: add images
 * - Hyperlink operations: add hyperlinks
 *
 * @param {string} templateId - Template identifier
 * @param {Array} operations - List of operations to execute
 * @param {boolean} validateOnly - If true, only validate without executing
 * @param {boolean} stopOnError - If true, stop on first error; if false, continue
 * @returns {Promise<Object>} Batch update result with fields and HTML preview
 *
 * @example
 * // Rename and delete placeholders
 * const result = await batchUpdate(templateId, [
 *   { type: 'rename_placeholder', old_name: 'ho_ten', new_name: 'ten_day_du', occurrence_index: 0 },
 *   { type: 'delete_placeholder', field_name: 'dia_chi_cu' }
 * ])
 *
 * @example
 * // Update text and format
 * const result = await batchUpdate(templateId, [
 *   { type: 'update_text', block_index: 5, old_text: 'Hello', new_text: 'Hi' },
 *   { type: 'format_text', block_index: 5, selected_text: 'Important',
 *     format_config: { bold: true, color: 'FF0000' } }
 * ])
 *
 * @example
 * // Add table row and format cell
 * const result = await batchUpdate(templateId, [
 *   { type: 'add_table_row', table_index: 0, row_index: 2, position: 'below' },
 *   { type: 'format_table_cell', table_index: 0, row_index: 1, col_index: 2,
 *     format_options: { background_color: 'FFFF00', horizontal_align: 'center' } }
 * ])
 */
export const batchUpdate = async (
  templateId,
  operations,
  validateOnly = false,
  stopOnError = true
) => {
  const response = await axios.post(`${API_BASE}/batch-update`, {
    template_id: templateId,
    operations: operations,
    validate_only: validateOnly,
    stop_on_error: stopOnError
  }, {
    headers: {
      'Content-Type': 'application/json',
    },
  })
  return response.data
}
