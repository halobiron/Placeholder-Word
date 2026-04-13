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
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('edit_type', editData.type)
  formData.append('selected_text', editData.selectedText)

  if (editData.type === 'text' && editData.newText) {
    formData.append('new_text', editData.newText)
  }

  if (editData.type === 'format' && editData.format) {
    formData.append('format_config', JSON.stringify(editData.format))
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

export const refreshTemplateInfo = async (templateId) => {
  const response = await axios.get(`${API_BASE}/template-info/${templateId}`)
  return response.data
}
