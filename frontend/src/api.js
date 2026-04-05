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

export const mergeTemplate = async (templateId, data, isDirectValues = false) => {
  const formData = new FormData()
  formData.append('template_id', templateId)

  if (isDirectValues) {
    // Send field values as JSON
    formData.append('field_values', JSON.stringify(data))
  } else {
    // Send context text for Gemini extraction
    formData.append('context', data)
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

export const updateTemplate = async (templateId, fields, editorHtml) => {
  const formData = new FormData()
  formData.append('template_id', templateId)
  formData.append('fields', JSON.stringify(fields))
  formData.append('editor_html', editorHtml)

  const response = await axios.post(`${API_BASE}/update-template`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}
