import { useState, useEffect } from 'react'
import FileUpload from './components/FileUpload'
import { mergeTemplate, getPreview, updateTemplate, analyzeTemplate, applySuggestions, getTemplateInfo, addPlaceholder, suggestFieldName } from './api'

function App() {
  const [step, setStep] = useState('upload') // upload, preview, preview_result, download
  const [templateId, setTemplateId] = useState(null)
  const [editorHtml, setEditorHtml] = useState(null)
  const [fields, setFields] = useState([])
  const [originalFields, setOriginalFields] = useState([]) // Track original fields from template
  const [fieldValues, setFieldValues] = useState({}) // Direct value editing
  const [context, setContext] = useState('')
  const [resultId, setResultId] = useState(null)
  const [previewHtml, setPreviewHtml] = useState(null) // Preview of merged result
  const [merging, setMerging] = useState(false)
  const [templateNeedsUpdate, setTemplateNeedsUpdate] = useState(false) // Track if template was modified
  const [renameMap, setRenameMap] = useState({}) // Track oldName -> currentName mapping
  const [error, setError] = useState(null)
  const [suggestions, setSuggestions] = useState([]) // AI suggestions for missing placeholders
  const [analyzing, setAnalyzing] = useState(false) // AI analysis in progress
  const [selectedSuggestions, setSelectedSuggestions] = useState([]) // Suggestions user wants to apply
  const [isAddMode, setIsAddMode] = useState(false) // Manual add placeholder mode
  const [selectedBlockIndex, setSelectedBlockIndex] = useState(null) // Selected block for adding placeholder
  const [selectedCellIndex, setSelectedCellIndex] = useState(null) // Selected cell index within table (for table cells)
  const [selectedTableBlockIndex, setSelectedTableBlockIndex] = useState(null) // Table block index when cell is selected
  const [selectedParaInCell, setSelectedParaInCell] = useState(null) // Selected paragraph index within cell (for table cell paragraphs)
  const [newFieldName, setNewFieldName] = useState('') // New placeholder name
  const [newFieldPosition, setNewFieldPosition] = useState('right') // Position for new placeholder (left/right/new_line)
  const [editedSuggestions, setEditedSuggestions] = useState({}) // Track user edits for suggestions: {block_index-suggested_name-position: {suggested_name: string, position: string}}

  // Extract placeholders from HTML
  const extractFields = (html) => {
    if (!html) return []
    const regex = /«([^»]+)»/g
    const found = new Set()
    let match
    while ((match = regex.exec(html)) !== null) {
      found.add(match[1].trim())
    }
    return Array.from(found)
  }

  // Attach click handlers to placeholders for rename
  useEffect(() => {
    const editor = document.getElementById('document-editor')
    if (!editor || !editorHtml) return

    // Remove old handlers first
    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      span.onclick = null
    })

    // Attach new handlers
    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      const fieldName = span.getAttribute('data-field')
      span.onclick = (e) => {
        e.preventDefault()
        e.stopPropagation()

        // If in add mode, don't rename - show message
        if (isAddMode) {
          setError('Thoát chế độ thêm placeholder trước khi đổi tên')
          return
        }

        const newName = prompt('Đổi tên placeholder:', fieldName)
        if (newName?.trim() && newName.trim() !== fieldName) {
          renameField(fieldName, newName.trim())
        }
      }
    })

    // Add click handlers for block selection in add mode
    if (isAddMode) {
      // First, remove existing handlers
      editor.querySelectorAll('[data-block-index], [data-cell-index]').forEach(element => {
        element.onclick = null
        element.style.cursor = ''
        element.style.outline = ''
      })

      // Handle block-level clicks (paragraphs, tables)
      // Allow clicking on empty lines too (data-block-index="-1")
      editor.querySelectorAll('[data-block-index]:not([data-cell-index])').forEach(element => {
        const blockIndex = parseInt(element.getAttribute('data-block-index'))
        const blockType = element.getAttribute('data-type')

        // Skip empty paragraphs that are not in tables
        // But allow selecting empty paragraphs within tables
        if (blockIndex === -1 && !element.closest('[data-cell-index]')) {
          element.style.cursor = 'default'
          return
        }

        element.style.cursor = 'crosshair'
        element.onclick = (e) => {
          e.preventDefault()
          e.stopPropagation()

          const blockIndex = parseInt(element.getAttribute('data-block-index'))
          const blockType = element.getAttribute('data-type')

          setSelectedBlockIndex(blockIndex)
          setSelectedCellIndex(null) // Reset cell index when selecting block
          setSelectedTableBlockIndex(null)
          setSelectedParaInCell(null) // Reset paragraph index

          // Highlight selected block
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          setError(`Đã chọn ${blockType === 'table' ? 'bảng' : 'đoạn'} #${blockIndex}. Nhập tên placeholder và nhấn "Thêm".`)
        }
      })

      // Handle cell-level clicks within tables
      // Also handle paragraph-level clicks within table cells for more precise targeting
      editor.querySelectorAll('[data-block-index][data-type="table_cell"]').forEach(element => {
        element.style.cursor = 'crosshair'
        element.onclick = (e) => {
          e.preventDefault()
          e.stopPropagation()

          const cellBlockIndex = parseInt(element.getAttribute('data-block-index'))
          const row = parseInt(element.getAttribute('data-row'))
          const col = parseInt(element.getAttribute('data-col'))

          setSelectedBlockIndex(cellBlockIndex) // Each cell now has its own block_index
          setSelectedCellIndex(null) // No need for cell_index anymore
          setSelectedTableBlockIndex(null)
          setSelectedParaInCell(null) // Reset paragraph index when clicking whole cell

          // Highlight selected cell
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          setError(`Đã chọn ô [${row},${col}]. Nhập tên placeholder và nhấn "Thêm".`)
        }
      })

      // Handle paragraph-level clicks within table cells (for empty lines)
      editor.querySelectorAll('.cell-paragraph').forEach(element => {
        element.style.cursor = 'crosshair'
        element.onclick = (e) => {
          e.preventDefault()
          e.stopPropagation()

          const cellBlockIndex = parseInt(element.getAttribute('data-cell-block-index'))
          const paraInCell = parseInt(element.getAttribute('data-para-in-cell'))

          setSelectedBlockIndex(cellBlockIndex) // Each cell has its own block_index
          setSelectedCellIndex(null) // No need for cell_index anymore
          setSelectedTableBlockIndex(null)
          setSelectedParaInCell(paraInCell) // Set paragraph index within cell

          // Highlight selected paragraph
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          setError(`Đã chọn dòng #${paraInCell}. Nhập tên placeholder và nhấn "Thêm".`)
        }
      })
    } else {
      // Remove highlight and handlers when not in add mode
      editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(element => {
        element.style.cursor = ''
        element.style.outline = ''
        element.onclick = null
      })
    }
  }, [editorHtml, step, isAddMode]) // Add isAddMode dependency

  // Auto-suggest field name when block is selected
  useEffect(() => {
    const autoSuggestFieldName = async () => {
      // Only auto-suggest when in add mode and a block is selected
      if (!isAddMode || selectedBlockIndex === null || !templateId) {
        return
      }

      try {
        setError('⏳ Đang phân tích để gợi ý tên placeholder...')
        const result = await suggestFieldName(templateId, selectedBlockIndex, selectedParaInCell)

        if (result.success && result.field_name) {
          setNewFieldName(result.field_name)
          setError(`✅ Đã chọn vị trí #${selectedBlockIndex}${selectedParaInCell !== null ? ` (dòng #${selectedParaInCell})` : ''}. Tên gợi ý: "${result.field_name}"`)
        }
      } catch (err) {
        console.error('Failed to suggest field name:', err)
        setError(`⚠️ Không thể gợi ý tên tự động. Vui lòng nhập tên thủ công.`)
      }
    }

    autoSuggestFieldName()
  }, [selectedBlockIndex, selectedParaInCell, isAddMode, templateId])

  // Rename placeholder
  const renameField = (oldName, newName) => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      if (span.getAttribute('data-field') === oldName) {
        span.setAttribute('data-field', newName)
        span.textContent = `«${newName}»`
      }
    })

    const newMap = { ...renameMap }
    for (const original in newMap) {
      if (newMap[original] === oldName) {
        newMap[original] = newName
      }
    }
    setRenameMap(newMap)

    const newHtml = editor.innerHTML
    setEditorHtml(newHtml)
    setFields(extractFields(newHtml))
    setTemplateNeedsUpdate(true) // Mark template as modified
  }

  // Delete placeholder
  const deleteField = async (fieldName) => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    // Store current state for rollback
    const oldHtml = editorHtml
    const oldFields = [...fields]
    const oldRenameMap = { ...renameMap }

    try {
      // Replace each matching span with its original text
      editor.querySelectorAll(`.mail-merge-placeholder[data-field="${fieldName}"]`).forEach(span => {
        const originalText = span.getAttribute('data-original') || ''
        span.outerHTML = originalText
      })

      const newMap = { ...renameMap }
      for (const original in newMap) {
        if (newMap[original] === fieldName) {
          newMap[original] = null // marked as deleted
        }
      }

      const newHtml = editor.innerHTML

      // IMPORTANT: Call updateTemplate FIRST before updating state
      // This ensures deletion is saved to DOCX before UI changes
      await updateTemplate(templateId, newMap, newHtml)

      // Only update local state after successful server update
      setRenameMap(newMap)
      setEditorHtml(newHtml)
      setFields(extractFields(newHtml))
      setTemplateNeedsUpdate(false) // Reset flag since we just updated

    } catch (err) {
      console.error('Failed to update template after deletion:', err)
      setError('Xóa placeholder thất bại. Thao tác đã được hoàn tác.')

      // Rollback UI changes
      editor.innerHTML = oldHtml
      setEditorHtml(oldHtml)
      setFields(oldFields)
      setRenameMap(oldRenameMap)

      setTimeout(() => setError(null), 3000)
    }
  }

  // Handle upload complete
  const handleUploadComplete = (data) => {
    setTemplateId(data.templateId)
    setEditorHtml(data.previewHtml)
    setFields(data.fields)
    setOriginalFields(data.fields) // Store original fields

    // Initialize renameMap mapping original fields to themselves
    const initMap = {}
    data.fields.forEach(f => initMap[f] = f)
    setRenameMap(initMap)

    setTemplateNeedsUpdate(false) // Reset update flag
    setStep('preview')
  }

  // Handle merge
  const handleMerge = async () => {
    // Check if we have direct values OR context
    const hasDirectValues = Object.values(fieldValues).some(v => v?.trim())
    const hasContext = context.trim()

    if (!hasDirectValues && !hasContext) {
      setError('Vui lòng điền giá trị cho placeholders hoặc nhập đoạn văn bản')
      return
    }

    setMerging(true)
    setError(null)

    try {
      // Update template if fields were modified (renamed/added/deleted)
      if (templateNeedsUpdate) {
        console.log('Updating template with modified fields...')
        await updateTemplate(templateId, renameMap, editorHtml)
        console.log('Template updated successfully')
        setTemplateNeedsUpdate(false)
      }

      // Use direct values if available, otherwise use context
      const data = hasDirectValues ? fieldValues : context
      const result = await mergeTemplate(templateId, data, hasDirectValues, fields)
      setResultId(result.result_id)

      // Fetch preview
      try {
        const previewData = await getPreview(result.result_id)
        setPreviewHtml(previewData.html_preview)
        setStep('preview_result')
      } catch (previewErr) {
        console.warn('Preview fetch failed, skipping preview:', previewErr)
        setStep('download')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Merge thất bại')
    } finally {
      setMerging(false)
    }
  }

  // AI Analysis for missing placeholders
  const handleAIAnalyze = async () => {
    if (!templateId) return

    setAnalyzing(true)
    setError(null)

    try {
      const result = await analyzeTemplate(templateId)
      setSuggestions(result.suggestions || [])
      setSelectedSuggestions([]) // Reset selection
    } catch (err) {
      setError(err.response?.data?.detail || 'AI phân tích thất bại. Kiểm tra GEMINI_API_KEY.')
    } finally {
      setAnalyzing(false)
    }
  }

  // Apply AI suggestions
  const handleApplySuggestions = async () => {
    if (!templateId || selectedSuggestions.length === 0) return

    setAnalyzing(true)
    setError(null)

    try {
      // Apply edits to selected suggestions before sending
      const editedSuggestionsToApply = selectedSuggestions.map(s => {
        const uniqueId = `${s.block_index}-${s.suggested_name}-${s.position}`
        const edits = editedSuggestions[uniqueId]
        return {
          ...s,
          suggested_name: edits?.suggested_name || s.suggested_name,
          position: edits?.position || s.position
        }
      })

      const result = await applySuggestions(templateId, editedSuggestionsToApply)

      // Reload template to get updated fields
      const templateInfo = await getTemplateInfo(templateId)
      setEditorHtml(templateInfo.html_preview)
      setFields(templateInfo.fields)
      setOriginalFields(templateInfo.fields)

      // Clear suggestions and edits after successful apply
      setSuggestions([])
      setSelectedSuggestions([])
      setEditedSuggestions({})

      // Show success message
      setError(`✅ Đã thêm thành công ${result.successful} placeholder!`)
      setTimeout(() => setError(null), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Áp dụng suggestions thất bại')
    } finally {
      setAnalyzing(false)
    }
  }

  // Update suggestion edit
  const updateSuggestionEdit = (suggestion, field, value) => {
    const uniqueId = `${suggestion.block_index}-${suggestion.suggested_name}-${suggestion.position}`
    setEditedSuggestions(prev => ({
      ...prev,
      [uniqueId]: {
        ...prev[uniqueId],
        [field]: value
      }
    }))
  }

  // Get edited suggestion (with user edits applied)
  const getEditedSuggestion = (suggestion) => {
    const uniqueId = `${suggestion.block_index}-${suggestion.suggested_name}-${suggestion.position}`
    const edits = editedSuggestions[uniqueId]
    return {
      ...suggestion,
      suggested_name: edits?.suggested_name || suggestion.suggested_name,
      position: edits?.position || suggestion.position
    }
  }

  // Toggle suggestion selection
  const toggleSuggestion = (suggestion) => {
    // Use unique identifier: block_index + suggested_name + position
    // This handles multiple suggestions in the same block (e.g., table cells)
    const uniqueId = `${suggestion.block_index}-${suggestion.suggested_name}-${suggestion.position}`
    const editedSuggestion = getEditedSuggestion(suggestion)

    const index = selectedSuggestions.findIndex(s =>
      `${s.block_index}-${s.suggested_name}-${s.position}` === uniqueId
    )
    if (index >= 0) {
      setSelectedSuggestions(prev => prev.filter((_, i) => i !== index))
    } else {
      setSelectedSuggestions(prev => [...prev, editedSuggestion])
    }
  }

  // Handle manual placeholder addition
  const handleAddPlaceholder = async () => {
    if (!templateId || selectedBlockIndex === null) {
      setError('Vui lòng chọn vị trí để thêm placeholder')
      return
    }

    if (!newFieldName.trim()) {
      setError('Vui lòng nhập tên placeholder')
      return
    }

    setAnalyzing(true)
    setError(null)

    try {
      const result = await addPlaceholder(
        templateId,
        selectedBlockIndex,
        newFieldName.trim(),
        newFieldPosition,
        null, // No need for cell_index anymore (each cell has its own block_index)
        selectedParaInCell // Pass paragraph index within cell for precise targeting
      )

      // Update UI with new data
      setEditorHtml(result.html_preview)
      setFields(result.updated_fields)
      setOriginalFields(result.updated_fields)

      // Reset add mode
      setIsAddMode(false)
      setSelectedBlockIndex(null)
      setSelectedCellIndex(null)
      setSelectedTableBlockIndex(null)
      setSelectedParaInCell(null)
      setNewFieldName('')
      setNewFieldPosition('right')

      // Show success message
      setError(`✅ Đã thêm placeholder «${result.field_name}» thành công!`)
      setTimeout(() => setError(null), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Thêm placeholder thất bại')
    } finally {
      setAnalyzing(false)
    }
  }

  // Cancel add mode
  const handleCancelAddMode = () => {
    setIsAddMode(false)
    setSelectedBlockIndex(null)
    setSelectedCellIndex(null)
    setSelectedTableBlockIndex(null)
    setSelectedParaInCell(null)
    setNewFieldName('')
    setNewFieldPosition('inline')
    setError(null)

    // Remove highlights
    const editor = document.getElementById('document-editor')
    if (editor) {
      editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
        el.style.outline = ''
      })
    }
  }

  // Reset
  const handleReset = () => {
    setStep('upload')
    setTemplateId(null)
    setEditorHtml(null)
    setFields([])
    setFieldValues({})
    setContext('')
    setResultId(null)
    setPreviewHtml(null)
    setError(null)
    setEditedSuggestions({}) // Clear suggestion edits
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 py-8 px-4">
      <div className="max-w-4xl mx-auto">
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Hệ Thống Mail Merge</h1>
          <p className="text-gray-600">Chuyển đổi Word và điền dữ liệu tự động</p>
        </header>

        <div className="bg-white rounded-lg shadow-lg p-8">
          {step === 'upload' && (
            <FileUpload onComplete={handleUploadComplete} />
          )}

          {step === 'preview' && (
            <div className="space-y-6">
              <div className="text-center">
                <h2 className="text-2xl font-bold text-gray-900 mb-2">Bước 2: Xem và Chỉnh Sửa</h2>
                <p className="text-gray-600">Kiểm tra placeholders và điền dữ liệu merge</p>
              </div>

              {fields.length > 0 && (
                <div className={`p-4 border rounded-lg ${templateNeedsUpdate ? 'bg-orange-50 border-orange-300' : 'bg-blue-50 border-blue-200'}`}>
                  <div className="flex justify-between items-start gap-4">
                    <div className="flex-1">
                      <p className="text-sm font-semibold mb-2">
                        {templateNeedsUpdate ? '⚠️ Template đã chỉnh sửa' : `✅ ${fields.length} placeholder:`}
                      </p>
                      {templateNeedsUpdate && (
                        <p className="text-xs text-orange-700 mb-2">
                          Các thay đổi sẽ được lưu vào template khi merge.
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-2">
                        {fields.map((f, i) => (
                          <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-white border border-blue-300 rounded text-xs font-mono">
                            <span>«{f}»</span>
                            <button
                              onClick={() => deleteField(f)}
                              className="text-red-500 hover:text-red-700 font-bold"
                              title="Xóa"
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* AI Analysis Section */}
              <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                <div className="flex justify-between items-center mb-3">
                  <div>
                    <p className="text-sm font-semibold text-purple-900">
                      🤖 AI Phân tích - Tìm placeholder bị thiếu
                    </p>
                    <p className="text-xs text-purple-700">
                      Gemini sẽ phân tích tài liệu và gợi ý các placeholder cần thêm
                    </p>
                  </div>
                  <button
                    onClick={handleAIAnalyze}
                    disabled={analyzing}
                    className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg disabled:opacity-50 text-sm font-medium"
                  >
                    {analyzing ? '⏳ Đang phân tích...' : '🔍 Phân tích'}
                  </button>
                </div>

                {/* Manual Add Placeholder Section */}
                <div className="mt-4 pt-4 border-t border-purple-200">
                  <div className="flex justify-between items-center mb-3">
                    <div>
                      <p className="text-sm font-semibold text-purple-900">
                        ✏️ Thêm Placeholder Thủ Công
                      </p>
                      <p className="text-xs text-purple-700">
                        Click vào vị trí trong tài liệu để thêm placeholder mới
                      </p>
                    </div>
                    {!isAddMode ? (
                      <button
                        onClick={() => setIsAddMode(true)}
                        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium"
                      >
                        ➕ Thêm Placeholder
                      </button>
                    ) : (
                      <button
                        onClick={handleCancelAddMode}
                        className="px-4 py-2 bg-gray-500 hover:bg-gray-600 text-white rounded-lg text-sm font-medium"
                      >
                        ✕ Hủy
                      </button>
                    )}
                  </div>

                  {isAddMode && (
                    <div className="mt-3 p-3 bg-white border border-purple-300 rounded-lg">
                      {selectedBlockIndex === null ? (
                        <p className="text-sm text-gray-600">
                          👆 Click vào vị trí trong tài liệu bên dưới để chọn nơi thêm placeholder
                        </p>
                      ) : (
                        <div className="space-y-3">
                          <p className="text-sm text-green-700 font-semibold">
                            {selectedParaInCell !== null
                              ? `✓ Đã chọn dòng #${selectedParaInCell} trong ô #${selectedCellIndex} của bảng #${selectedTableBlockIndex}`
                              : selectedCellIndex !== null
                                ? `✓ Đã chọn ô #${selectedCellIndex} trong bảng #${selectedTableBlockIndex}`
                                : `✓ Đã chọn vị trí #${selectedBlockIndex}`
                            }
                          </p>

                          <div>
                            <label className="text-xs font-semibold text-gray-700 block mb-1">
                              Tên placeholder: <span className="text-green-600">(✨ Đã tự động gợi ý từ nội dung)</span>
                            </label>
                            <input
                              type="text"
                              value={newFieldName}
                              onChange={(e) => setNewFieldName(e.target.value)}
                              placeholder="ten_placeholder"
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                            />
                          </div>

                          <div>
                            <label className="text-xs font-semibold text-gray-700 block mb-1">
                              Vị trí chèn:
                            </label>
                            <select
                              value={newFieldPosition}
                              onChange={(e) => setNewFieldPosition(e.target.value)}
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                            >
                              <option value="left">⬅️ Trước text</option>
                              <option value="right">➡️ Sau text</option>
                              <option value="new_line">⬇️ Xuống dòng</option>
                            </select>
                          </div>

                          <button
                            onClick={handleAddPlaceholder}
                            disabled={analyzing || !newFieldName.trim()}
                            className="w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                          >
                            {analyzing ? '⏳ Đang thêm...' : '✓ Thêm Placeholder'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Suggestions Display */}
              {suggestions.length > 0 && (
                <div className="mt-4 p-3 bg-white border border-purple-300 rounded-lg">
                  <div className="flex justify-between items-center mb-2">
                    <p className="text-sm font-semibold text-purple-900">
                      Gợi ý ({suggestions.length}):
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setSelectedSuggestions(suggestions)}
                        className="px-3 py-1 bg-purple-100 hover:bg-purple-200 text-purple-700 rounded text-xs"
                      >
                        Chọn tất cả
                      </button>
                      <button
                        onClick={() => setSelectedSuggestions([])}
                        className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded text-xs"
                      >
                        Bỏ chọn
                      </button>
                    </div>
                  </div>

                  <div className="space-y-2 max-h-60 overflow-y-auto">
                    {suggestions.map((s, idx) => {
                      const uniqueId = `${s.block_index}-${s.suggested_name}-${s.position}`
                      const edits = editedSuggestions[uniqueId] || {}
                      const editedName = edits.suggested_name || s.suggested_name
                      const editedPosition = edits.position || s.position

                      const isSelected = selectedSuggestions.some(sel =>
                        `${sel.block_index}-${sel.suggested_name}-${sel.position}` === uniqueId
                      )
                      return (
                        <div
                          key={idx}
                          className={`p-2 border rounded transition-colors ${isSelected
                              ? 'bg-purple-100 border-purple-400'
                              : 'bg-gray-50 border-gray-200 hover:bg-gray-100'
                            }`}
                        >
                          <div className="flex items-start gap-2">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSuggestion(s)}
                              className="mt-1"
                            />
                            <div className="flex-1">
                              {/* Editable name and position */}
                              <div className="flex items-center gap-2 flex-wrap">
                                {/* Editable name */}
                                <div className="flex items-center gap-1">
                                  <span className="font-mono text-sm">«</span>
                                  <input
                                    type="text"
                                    value={editedName}
                                    onChange={(e) => updateSuggestionEdit(s, 'suggested_name', e.target.value)}
                                    onClick={(e) => e.stopPropagation()}
                                    className={`font-mono text-sm font-semibold border rounded px-1 ${editedName !== s.suggested_name ? 'border-yellow-400 bg-yellow-50' : 'border-transparent bg-transparent'}`}
                                    style={{ width: `${Math.max(editedName.length * 8, 80)}px` }}
                                  />
                                  <span className="font-mono text-sm">»</span>
                                  {editedName !== s.suggested_name && (
                                    <span className="text-xs text-yellow-600">✏️</span>
                                  )}
                                </div>

                                {/* Editable position */}
                                <select
                                  value={editedPosition}
                                  onChange={(e) => updateSuggestionEdit(s, 'position', e.target.value)}
                                  onClick={(e) => e.stopPropagation()}
                                  className={`text-xs px-2 py-0.5 rounded border ${editedPosition !== s.position ? 'border-yellow-400 bg-yellow-50' : 'border-transparent bg-transparent'} ${
                                    editedPosition === 'left'
                                      ? 'bg-blue-100 text-blue-700'
                                      : editedPosition === 'right'
                                        ? 'bg-purple-100 text-purple-700'
                                        : 'bg-orange-100 text-orange-700'
                                  }`}
                                >
                                  <option value="left">⬅️ Trước text</option>
                                  <option value="right">➡️ Sau text</option>
                                  <option value="new_line">⬇️ Xuống dòng</option>
                                </select>

                                {/* Confidence badge */}
                                <span className={`px-2 py-0.5 rounded text-xs ${s.confidence === 'high'
                                    ? 'bg-green-100 text-green-700'
                                    : s.confidence === 'medium'
                                      ? 'bg-yellow-100 text-yellow-700'
                                      : 'bg-gray-100 text-gray-700'
                                  }`}>
                                  {s.confidence}
                                </span>

                                {/* Field type badge */}
                                <span className="px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-700">
                                  {s.field_type}
                                </span>
                              </div>

                              {/* Context with surrounding info */}
                              <div className="mt-2 p-2 bg-gray-50 rounded text-xs">
                                {s.before_context && s.before_context.length > 0 && (
                                  <div className="text-gray-500 mb-1">
                                    <span className="font-semibold">Trước:</span> {s.before_context.join(' ← ')}
                                  </div>
                                )}
                                <div className="font-semibold text-gray-700 my-1">
                                  → {s.context.substring(0, 80)}{s.context.length > 80 ? '...' : ''}
                                </div>
                                {s.after_context && s.after_context.length > 0 && (
                                  <div className="text-gray-500 mt-1">
                                    <span className="font-semibold">Sau:</span> {s.after_context.join(' → ')}
                                  </div>
                                )}
                              </div>

                              <p className="text-xs text-gray-500 mt-1">
                                {s.reason}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {selectedSuggestions.length > 0 && (
                    <div className="mt-3 pt-3 border-t">
                      <button
                        onClick={handleApplySuggestions}
                        disabled={analyzing}
                        className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg disabled:opacity-50 font-medium"
                      >
                        {analyzing
                          ? '⏳ Đang áp dụng...'
                          : `✓ Áp dụng ${selectedSuggestions.length} gợi ý`}
                      </button>
                    </div>
                  )}
                </div>
              )}

              <div>
                <div className="flex justify-between items-center mb-2">
                  <h3 className="text-lg font-semibold">Tài liệu</h3>
                </div>
                <div
                  id="document-editor"
                  contentEditable
                  className="border border-gray-300 rounded-lg p-6 bg-white min-h-[400px] overflow-auto focus:ring-2 focus:ring-blue-500"
                  style={{ maxHeight: '600px' }}
                  suppressContentEditableWarning={true}
                  onInput={async (e) => {
                    const newHtml = e.target.innerHTML
                    const newFields = extractFields(newHtml)

                    // Check if any placeholders were deleted
                    const deletedFields = fields.filter(f => !newFields.includes(f))

                    setEditorHtml(newHtml)
                    setFields(newFields)

                    // If placeholders were deleted, update template immediately
                    if (deletedFields.length > 0) {
                      try {
                        // Update renameMap to mark deleted fields
                        const newMap = { ...renameMap }
                        deletedFields.forEach(fieldName => {
                          for (const original in newMap) {
                            if (newMap[original] === fieldName) {
                              newMap[original] = null // marked as deleted
                            }
                          }
                        })

                        // Save to server
                        await updateTemplate(templateId, newMap, newHtml)
                        setRenameMap(newMap)
                        setTemplateNeedsUpdate(false)

                        // Show success message
                        setError(`✅ Đã xóa ${deletedFields.length} placeholder`)
                        setTimeout(() => setError(null), 2000)
                      } catch (err) {
                        console.error('Failed to update template after deletion:', err)
                        setError('⚠️ Xóa placeholder thất bại. Thay đổi chưa được lưu.')
                        setTimeout(() => setError(null), 3000)
                      }
                    }
                  }}
                  dangerouslySetInnerHTML={{ __html: editorHtml }}
                />
                <p className="text-xs text-gray-500 mt-2">
                  💡 Click vào placeholder để đổi tên. Click "➕ Thêm Placeholder" để thêm placeholder thủ công vào vị trí bất kỳ.
                </p>
              </div>

              <div className="border-t pt-6">
                <h3 className="text-lg font-semibold mb-3">Điền Dữ Liệu Merge</h3>

                {/* Direct value editing */}
                {fields.length > 0 && (
                  <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                    <p className="text-sm font-semibold text-yellow-900 mb-3">
                      📝 Cách 1: Điền trực tiếp giá trị cho từng placeholder
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {fields.map((field) => (
                        <div key={field} className="flex items-center gap-2">
                          <label className="text-xs font-mono text-gray-700 w-1/2 truncate" title={field}>
                            «{field}»:
                          </label>
                          <input
                            type="text"
                            value={fieldValues[field] || ''}
                            onChange={(e) => setFieldValues(prev => ({
                              ...prev,
                              [field]: e.target.value
                            }))}
                            placeholder="Giá trị..."
                            className="flex-1 px-2 py-1 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Context-based extraction (Gemini) */}
                <div className="mb-4">
                  <p className="text-sm text-gray-600 mb-3">
                    💡 Hoặc nhập đoạn văn bản để Gemini tự động trích xuất dữ liệu:
                  </p>
                  <textarea
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    placeholder="Ví dụ: Tôi tên là Nguyễn Văn A, sinh ngày 01/01/1990, số CMND 123456789, sống tại Hà Nội..."
                    className="w-full h-24 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>

                {error && (
                  <div className="mt-3 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
                    {error}
                  </div>
                )}
                <div className="flex gap-3 mt-4">
                  <button
                    onClick={() => setStep('upload')}
                    disabled={merging}
                    className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg disabled:opacity-50"
                  >
                    ← Quay lại
                  </button>
                  <button
                    onClick={handleMerge}
                    disabled={merging || (!Object.values(fieldValues).some(v => v?.trim()) && !context.trim())}
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    {merging ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>Đang xử lý...</span>
                      </>
                    ) : (
                      <span>Merge & Download →</span>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}

          {step === 'download' && (
            <div className="text-center space-y-6">
              <div className="p-6 bg-green-50 rounded-lg">
                <div className="text-6xl mb-4">✅</div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">Merge Hoàn Thành!</h2>
                <p className="text-gray-600">Tài liệu đã được điền dữ liệu thành công</p>
              </div>
              <div className="flex gap-3 justify-center">
                <a
                  href={`http://localhost:8000/download/${resultId}`}
                  download
                  className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
                >
                  📥 Tải Xuống
                </a>
                <button
                  onClick={handleReset}
                  className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg"
                >
                  🔄 Bắt Đầu Lại
                </button>
              </div>
            </div>
          )}

          {step === 'preview_result' && previewHtml && (
            <div className="space-y-6">
              <div className="text-center">
                <h2 className="text-2xl font-bold text-gray-900 mb-2">Xem Kết Quả Trước Khi Tải</h2>
                <p className="text-gray-600">Kiểm tra dữ liệu đã điền vào tài liệu</p>
              </div>

              <div className="border border-gray-300 rounded-lg p-6 bg-white max-h-[500px] overflow-auto">
                <div
                  dangerouslySetInnerHTML={{ __html: previewHtml }}
                  className="prose prose-sm max-w-none"
                />
              </div>

              <div className="flex gap-3 justify-center">
                <button
                  onClick={() => setStep('download')}
                  className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
                >
                  ✓ OK, Tải Xuống
                </button>
                <button
                  onClick={() => {
                    setStep('preview')
                    // Clear field values when going back to re-enter data
                    setFieldValues({})
                  }}
                  className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg"
                >
                  ← Sửa Dữ Liệu
                </button>
                <button
                  onClick={handleReset}
                  className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg"
                >
                  🔄 Bắt Đầu Lại
                </button>
              </div>
            </div>
          )}
        </div>

        <footer className="text-center mt-8 text-sm text-gray-500">
          <p>Mail Merge Placeholder System v1.0.0</p>
        </footer>

        <style>{`
          .mail-merge-placeholder {
            background: linear-gradient(120deg, #a8edea 0%, #fed6e3 100%);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            color: #1e3a5f;
            border: 2px solid #4a90d9;
            cursor: pointer;
            user-select: none;
            display: inline-block;
          }
          .mail-merge-placeholder:hover {
            transform: scale(1.05);
            box-shadow: 0 2px 8px rgba(74, 144, 217, 0.3);
          }
          /* Cell paragraphs - ensure each line is separate */
          .cell-paragraph {
            display: block;
            min-height: 1.2em;
            margin: 4px 0;
            padding: 2px;
            border-radius: 2px;
            transition: background-color 0.2s;
          }
          .cell-paragraph:hover {
            background-color: rgba(139, 92, 246, 0.1);
          }
          .cell-paragraph[outline] {
            background-color: rgba(139, 92, 246, 0.2);
          }
          /* Table cells styling */
          .docx-table td p,
          .docx-table th p {
            margin: 4px 0;
            line-height: 1.4;
          }
        `}</style>
      </div>
    </div>
  )
}

export default App
