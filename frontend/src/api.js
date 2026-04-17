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

export const analyzeTemplate = async (templateId) => {
  const formData = new FormData()
  formData.append('template_id', templateId)

  const response = await axios.post(`${API_BASE}/analyze-template`, formData, {
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

export const getTemplateInfo = async (templateId) => {
  const response = await axios.get(`${API_BASE}/template-info/${templateId}`)
  return response.data
}

export const mergeTemplate = async (templateId, data, isDirectValues = false, activeFields = null) => {
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

export const updateTemplate = async (templateId, renameMap, editorHtml) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('rename_map', JSON.stringify(renameMap))
  formData.append('editor_html', editorHtml)

  const response = await axios.post(`${API_BASE}/update-template`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addPlaceholder = async (templateId, blockIndex, fieldName, position = 'right', cellIndex = null, paraInCell = null) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('block_index', blockIndex)
  formData.append('field_name', fieldName)
  formData.append('position', position)
  if (cellIndex !== null) {
    formData.append('cell_index', cellIndex)
  }
  if (paraInCell !== null) {
    formData.append('para_in_cell', paraInCell)
  }

  const response = await axios.post(`${API_BASE}/add-placeholder`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
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

// New API functions for enhanced editing
export const editSelection = async (templateId, editData) => {
  console.log('=== editSelection called ===')
  console.log('editData:', editData)

  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('edit_type', editData.type)
  formData.append('selected_text', editData.selectedText)

  // Send blockIndex if available for precise editing
  if (editData.blockIndex !== undefined && editData.blockIndex !== null) {
    formData.append('paragraph_index', editData.blockIndex)
  }

  // Handle different edit types
  if (editData.type === 'text' && editData.newText) {
    formData.append('new_text', editData.newText)
  } else if (editData.type === 'format' && editData.format) {
    // Separate text-level and paragraph-level formatting
    const { alignment, ...textFormat } = editData.format

    // If alignment is set, include it in paragraph_format
    let paragraphFormat = editData.paragraphFormat || {}
    if (alignment !== undefined && alignment !== 'left') {
      paragraphFormat.alignment = alignment
    }

    console.log('format_config (text-level):', textFormat)
    formData.append('format_config', JSON.stringify(textFormat))

    // Include paragraph formatting if provided
    if (Object.keys(paragraphFormat).length > 0) {
      formData.append('paragraph_format', JSON.stringify(paragraphFormat))
    }
  } else if (editData.type === 'both') {
    // Send both new_text and format_config
    if (editData.newText) {
      formData.append('new_text', editData.newText)
    }
    if (editData.format) {
      // Separate text-level and paragraph-level formatting
      const { alignment, ...textFormat } = editData.format

      // If alignment is set, include it in paragraph_format
      let paragraphFormat = editData.paragraphFormat || {}
      if (alignment !== undefined && alignment !== 'left') {
        paragraphFormat.alignment = alignment
      }

      formData.append('format_config', JSON.stringify(textFormat))
    }

    // Include paragraph formatting if provided
    if (editData.paragraphFormat && Object.keys(editData.paragraphFormat).length > 0) {
      formData.append('paragraph_format', JSON.stringify(editData.paragraphFormat))
    }
  }

  const response = await axios.post(`${API_BASE}/edit-selection`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addContent = async (templateId, addData) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('add_type', addData.type)
  formData.append('position', addData.position)
  formData.append('inherit_format', addData.inheritFormat ? 'true' : 'false')

  if (addData.content) {
    formData.append('content', addData.content)
  }

  if (addData.fieldName) {
    formData.append('field_name', addData.fieldName)
  }

  if (addData.file) {
    formData.append('file', addData.file)
  }

  if (addData.format) {
    formData.append('format_config', JSON.stringify(addData.format))
  }

  const response = await axios.post(`${API_BASE}/add-content`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const updateTextInTemplate = async (templateId, { blockIndex, oldText, newText, editType = 'text' }) => {
  // Validate blockIndex before making the request
  if (isNaN(blockIndex) || blockIndex === null || blockIndex === undefined) {
    throw new Error(`Invalid blockIndex: ${blockIndex}`)
  }

  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('block_index', blockIndex)
  formData.append('old_text', oldText)
  formData.append('new_text', newText)
  formData.append('edit_type', editType)

  const response = await axios.post(`${API_BASE}/update-text`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const refreshTemplateInfo = async (templateId) => {
  const response = await axios.get(`${API_BASE}/template-info/${templateId}`)
  return response.data
}

export const getSelectionFormat = async (templateId, selectedText, blockIndex) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('selected_text', selectedText)
  if (blockIndex !== null && blockIndex !== undefined) {
    formData.append('block_index', blockIndex)
  }

  const response = await axios.post(`${API_BASE}/get-selection-format`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addTableRow = async (templateId, tableIndex, rowIndex, position = 'below') => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('table_index', tableIndex)
  if (rowIndex !== null && rowIndex !== undefined) {
    formData.append('row_index', rowIndex)
  }
  formData.append('position', position)

  const response = await axios.post(`${API_BASE}/add-table-row`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const deleteTableRow = async (templateId, tableIndex, rowIndex) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('table_index', tableIndex)
  formData.append('row_index', rowIndex)

  const response = await axios.post(`${API_BASE}/delete-table-row`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addTableColumn = async (templateId, tableIndex, colIndex, position = 'right') => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('table_index', tableIndex)
  if (colIndex !== null && colIndex !== undefined) {
    formData.append('col_index', colIndex)
  }
  formData.append('position', position)

  const response = await axios.post(`${API_BASE}/add-table-column`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const deleteTableColumn = async (templateId, tableIndex, colIndex) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('table_index', tableIndex)
  formData.append('col_index', colIndex)

  const response = await axios.post(`${API_BASE}/delete-table-column`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const formatTableCell = async (templateId, tableIndex, rowIndex, colIndex, formatOptions) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('table_index', tableIndex)
  formData.append('row_index', rowIndex)
  formData.append('col_index', colIndex)
  formData.append('format_options', JSON.stringify(formatOptions))

  const response = await axios.post(`${API_BASE}/format-table-cell`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const addParagraph = async (templateId, blockIndex, position = 'after', text = '', tableIndex = null, rowIndex = null, colIndex = null, paraInCell = null) => {
  const formData = new FormData()
  formData.append('template_id', templateId)

  if (blockIndex !== null && blockIndex !== undefined) {
    formData.append('block_index', blockIndex)
  }

  formData.append('position', position)

  if (text) {
    formData.append('text', text)
  }

  if (tableIndex !== null && tableIndex !== undefined) {
    formData.append('table_index', tableIndex)
  }

  if (rowIndex !== null && rowIndex !== undefined) {
    formData.append('row_index', rowIndex)
  }

  if (colIndex !== null && colIndex !== undefined) {
    formData.append('col_index', colIndex)
  }

  if (paraInCell !== null && paraInCell !== undefined) {
    formData.append('para_in_cell', paraInCell)
  }

  const response = await axios.post(`${API_BASE}/add-paragraph`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const deleteParagraph = async (templateId, blockIndex, tableIndex = null, rowIndex = null, colIndex = null, paraInCell = null) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('block_index', blockIndex)

  if (tableIndex !== null && tableIndex !== undefined) {
    formData.append('table_index', tableIndex)
  }

  if (rowIndex !== null && rowIndex !== undefined) {
    formData.append('row_index', rowIndex)
  }

  if (colIndex !== null && colIndex !== undefined) {
    formData.append('col_index', colIndex)
  }

  if (paraInCell !== null && paraInCell !== undefined) {
    formData.append('para_in_cell', paraInCell)
  }

  const response = await axios.post(`${API_BASE}/delete-paragraph`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export const deleteMultipleParagraphs = async (templateId, blocks) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('blocks', JSON.stringify(blocks))

  const response = await axios.post(`${API_BASE}/delete-multiple-paragraphs`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}
