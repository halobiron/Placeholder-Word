import { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import FileUpload from './components/FileUpload'
import EditPopup from './components/EditPopup'
import { mergeTemplate, getPreview, updateTemplate, suggestPlaceholders, applySuggestions, getTemplateInfo, addPlaceholder, addPlaceholderAtOffset, suggestFieldName, editSelection, addContent, refreshTemplateInfo, updateTextInTemplate, getSelectionFormat, addTableRow, deleteTableRow, addTableColumn, deleteTableColumn, formatTableCell, addParagraph, deleteParagraph, deleteMultipleParagraphs, addTableAtCursor, addImageAtCursor, addHyperlink } from './api'

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
  const [showAddTablePopup, setShowAddTablePopup] = useState(false) // Show add table popup
  const [tableSize, setTableSize] = useState({ rows: 3, cols: 3 }) // Default table size
  const [showAddImagePopup, setShowAddImagePopup] = useState(false) // Show add image popup
  const [imageWidth, setImageWidth] = useState(4.0) // Default image width (inches)
  const [selectedImageFile, setSelectedImageFile] = useState(null) // Selected image file
  const [selectedTableBlockIndex, setSelectedTableBlockIndex] = useState(null) // Table block index when cell is selected
  const [selectedParaInCell, setSelectedParaInCell] = useState(null) // Selected paragraph index within cell (for table cell paragraphs)
  const [newFieldName, setNewFieldName] = useState('') // New placeholder name
  const [newFieldPosition, setNewFieldPosition] = useState('right') // Position for new placeholder (left/right/new_line)
  const [caretOffset, setCaretOffset] = useState(null) // Character offset within block for precise placeholder insertion
  const [editedSuggestions, setEditedSuggestions] = useState({}) // Track user edits for suggestions: {block_index-suggested_name-position: {suggested_name: string, position: string}}

  // New states for enhanced editing
  const [showEditPopup, setShowEditPopup] = useState(false)
  const [selectedTextForEdit, setSelectedTextForEdit] = useState(null)
  const [copiedFormat, setCopiedFormat] = useState(null) // Store copied format for Format Painter

  // Table editing states
  const [selectedTableInfo, setSelectedTableInfo] = useState({
    tableIndex: null,
    rowIndex: null,
    colIndex: null,
    isCellSelected: false
  })
  const [showCellFormatDialog, setShowCellFormatDialog] = useState(false)
  const [cellFormatOptions, setCellFormatOptions] = useState({
    background_color: '#ffffff',
    vertical_align: 'top',
    horizontal_align: 'left'
  })

  // Hyperlink editing states
  const [showHyperlinkDialog, setShowHyperlinkDialog] = useState(false)
  const [hyperlinkData, setHyperlinkData] = useState({
    url: ''
  })
  const [hyperlinkPosition, setHyperlinkPosition] = useState({
    blockIndex: null,
    startOffset: null,
    endOffset: null,
    selectedText: ''
  })

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

  // Helper: Get original text from a specific block
  const getOriginalTextFromBlock = (html, blockIndex) => {
    if (!html) return ''
    const temp = document.createElement('div')
    temp.innerHTML = html
    const block = temp.querySelector(`[data-block-index="${blockIndex}"]`)
    if (!block) return ''

    // CRITICAL FIX: Preserve non-breaking spaces (&nbsp;) as \u00a0
    let text = block.textContent

    // Check if original HTML had &nbsp; and preserve it as non-breaking space
    const originalHtml = block.innerHTML
    if (originalHtml.includes('&nbsp;') || originalHtml.includes('\u00a0')) {
      // If the text is only whitespace, use non-breaking spaces
      if (text.trim() === '' && text.length > 0) {
        text = text.replace(/ /g, '\u00a0')
      }
    }

    return text
  }

  // Helper: Get current text from a specific block
  const getTextFromBlock = (html, blockIndex) => {
    if (!html) return ''
    const temp = document.createElement('div')
    temp.innerHTML = html
    const block = temp.querySelector(`[data-block-index="${blockIndex}"]`)
    if (!block) return ''

    // CRITICAL FIX: Preserve non-breaking spaces (&nbsp;) as \u00a0
    let text = block.textContent

    // Check if original HTML had &nbsp; and preserve it as non-breaking space
    const originalHtml = block.innerHTML
    if (originalHtml.includes('&nbsp;') || originalHtml.includes('\u00a0')) {
      // If the text is only whitespace, use non-breaking spaces
      if (text.trim() === '' && text.length > 0) {
        text = text.replace(/ /g, '\u00a0')
      }
    }

    return text
  }

  // Helper: Get current block index from selection
  const getCurrentBlockIndex = () => {
    const selection = window.getSelection()
    if (!selection.rangeCount) return null
    const range = selection.getRangeAt(0)

    // Handle both Text nodes and Element nodes
    let startNode = range.startContainer
    // If it's a Text node, get its parent element
    if (startNode.nodeType === Node.TEXT_NODE) {
      startNode = startNode.parentElement
    }

    // Now startNode is guaranteed to be an Element
    const editedBlock = startNode.closest('[data-block-index]')
    return editedBlock ? parseInt(editedBlock.getAttribute('data-block-index')) : null
  }

  // Helper: Calculate cursor offset within a block (excluding placeholders)
  const calculateCursorOffset = (range, blockIndex) => {
    try {
      // Find the editor element
      const editor = document.getElementById('document-editor')
      if (!editor) return null

      // Find the element with this blockIndex
      const element = editor.querySelector(`[data-block-index="${blockIndex}"]`)
      if (!element) return null

      // Calculate offset within the block, excluding placeholder characters
      const preCaretRange = range.cloneRange()
      preCaretRange.selectNodeContents(element)
      preCaretRange.setEnd(range.startContainer, range.startOffset)
      const textBeforeCaret = preCaretRange.toString()

      // Remove placeholder characters («field_name») from offset calculation
      const textWithoutPlaceholders = textBeforeCaret.replace(/«[^»]+»/g, '')
      let offset = textWithoutPlaceholders.length

      // Special case: Empty paragraph
      const plainText = element.textContent.replace(/«[^»]+»/g, '').trim()
      if (plainText.length === 0 && offset > 0) {
        console.log('[DEBUG] Empty paragraph detected, forcing offset to 0')
        offset = 0
      }

      console.log('[DEBUG] Cursor offset calculation:', {
        blockIndex,
        offset,
        textBeforeCaret: textBeforeCaret.substring(0, 50) + (textBeforeCaret.length > 50 ? '...' : ''),
        textWithoutPlaceholders: textWithoutPlaceholders.substring(0, 50) + (textWithoutPlaceholders.length > 50 ? '...' : ''),
        plainTextLength: plainText.length
      })

      return offset
    } catch (error) {
      console.error('[ERROR] calculateCursorOffset failed:', error)
      return null
    }
  }

  // Helper: Get text from a specific paragraph within a table cell
  const getTextFromCellParagraph = (html, cellBlockIndex, paraInCell) => {
    if (!html) return ''
    const temp = document.createElement('div')
    temp.innerHTML = html

    // Find the specific paragraph in the table cell
    const paragraph = temp.querySelector(`[data-cell-block-index="${cellBlockIndex}"][data-para-in-cell="${paraInCell}"]`)
    if (!paragraph) return ''

    // CRITICAL FIX: Preserve non-breaking spaces (&nbsp;) as \u00a0
    // textContent converts &nbsp; to regular space, but DOCX uses non-breaking space
    // So we need to preserve the non-breaking space character
    let text = paragraph.textContent

    // Check if original HTML had &nbsp; and preserve it as non-breaking space
    const originalHtml = paragraph.innerHTML
    if (originalHtml.includes('&nbsp;') || originalHtml.includes('\u00a0')) {
      // Replace regular spaces at positions where &nbsp; was with non-breaking spaces
      // This is a heuristic: if the text is only spaces, they were probably &nbsp;
      if (text.trim() === '' && text.length > 0) {
        // All whitespace - use non-breaking spaces
        text = text.replace(/ /g, '\u00a0')
      }
    }

    return text
  }

  // Debounced text update function
  const debouncedUpdateText = useMemo(
    () => {
      let timeoutId
      return async (blockIndex, oldText, newText) => {
        // Clear previous timeout
        if (timeoutId) clearTimeout(timeoutId)

        // Set new timeout
        timeoutId = setTimeout(async () => {
          try {
            // Validate blockIndex before making API call
            if (isNaN(blockIndex) || blockIndex === null || blockIndex === undefined) {
              console.warn('Invalid blockIndex in debouncedUpdateText, skipping API call:', blockIndex)
              return
            }

            await updateTextInTemplate(templateId, {
              blockIndex,
              oldText,
              newText,
              editType: 'text'
            })
            setError('✅ Đã cập nhật text')
            setTimeout(() => setError(null), 2000)
            // DON'T refresh HTML after text-only edits - user sees changes in real-time
            // Only refresh for placeholder operations (add/delete/rename/format)
          } catch (err) {
            console.error('Text update failed:', err)
            setError('⚠️ Cập nhật thất bại: ' + (err.response?.data?.detail || err.message))
            setTimeout(() => setError(null), 3000)
          }
        }, 1000) // 1 second debounce
      }
    },
    [templateId]
  )

  // Debounced text update function for table cell paragraphs
  const debouncedUpdateTextInCell = useMemo(
    () => {
      let timeoutId
      return async (cellBlockIndex, paraInCell, oldText, newText) => {
        // Clear previous timeout
        if (timeoutId) clearTimeout(timeoutId)

        // Set new timeout
        timeoutId = setTimeout(async () => {
          try {
            // Validate parameters before making API call
            if (isNaN(cellBlockIndex) || cellBlockIndex === null || cellBlockIndex === undefined) {
              console.warn('Invalid cellBlockIndex in debouncedUpdateTextInCell, skipping API call:', cellBlockIndex)
              return
            }
            if (isNaN(paraInCell) || paraInCell === null || paraInCell === undefined) {
              console.warn('Invalid paraInCell in debouncedUpdateTextInCell, skipping API call:', paraInCell)
              return
            }

            // Call the API with para_in_cell parameter
            const formData = new FormData()
            formData.append('template_id', templateId)
            formData.append('block_index', cellBlockIndex)
            formData.append('old_text', oldText)
            formData.append('new_text', newText)
            formData.append('edit_type', 'text')
            formData.append('para_in_cell', paraInCell)

            const response = await axios.post(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/update-text`, formData, {
              headers: {
                'Content-Type': 'multipart/form-data',
              },
            })

            setError('✅ Đã cập nhật text trong ô bảng')
            setTimeout(() => setError(null), 2000)
            // DON'T refresh HTML after text-only edits - user sees changes in real-time
          } catch (err) {
            console.error('Table cell text update failed:', err)
            setError('⚠️ Cập nhật thất bại: ' + (err.response?.data?.detail || err.message))
            setTimeout(() => setError(null), 3000)
          }
        }, 1000) // 1 second debounce
      }
    },
    [templateId]
  )

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

    // Add click handlers for table cells (ALWAYS ACTIVE, not just in add mode)
    // This enables table editing toolbar for all table cells
    // IMPORTANT: Setup AFTER paragraph handlers to override them
    const tableCells = editor.querySelectorAll('[data-block-index][data-type="table_cell"]')
    console.log(`[Table Debug] Found ${tableCells.length} table cells`)
    tableCells.forEach(element => {
      element.style.cursor = 'crosshair'

      // Use capture phase to override paragraph handlers
      element.addEventListener('click', (e) => {
        console.log(`[Table Debug] Cell click event captured`)

        // Check if click is directly on cell or its children
        const target = e.target
        const isCellOrChild = target === element || element.contains(target)

        if (isCellOrChild) {
          e.preventDefault()
          e.stopPropagation()
          e.stopImmediatePropagation() // Stop other handlers

          const cellBlockIndex = parseInt(element.getAttribute('data-block-index'))
          const tableIndex = parseInt(element.getAttribute('data-table-index') || '0')
          const row = parseInt(element.getAttribute('data-row'))
          const col = parseInt(element.getAttribute('data-col'))

          console.log(`[Table Debug] Clicked cell [${row},${col}], tableIndex: ${tableIndex}, blockIndex: ${cellBlockIndex}`)

          setSelectedBlockIndex(cellBlockIndex) // Each cell now has its own block_index
          setSelectedCellIndex(null) // No need for cell_index anymore
          setSelectedTableBlockIndex(null)
          setSelectedParaInCell(null) // Reset paragraph index when clicking whole cell

          // Set table editing info
          setSelectedTableInfo({
            tableIndex: tableIndex,
            rowIndex: row,
            colIndex: col,
            isCellSelected: true
          })

          // Highlight selected cell
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          setError(`Đã chọn ô [${row},${col}]. Nhập tên placeholder và nhấn "Thêm" hoặc dùng công cụ bảng.`)
        }
      }, true) // Use capture phase
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

          // Get caret offset for precise insertion
          const selection = window.getSelection()
          let offset = null

          if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0)

            // Calculate offset within the block, excluding placeholder characters
            // This is critical because backend expects offset based on plain DOCX text,
            // not HTML textContent which includes «field_name» placeholders
            const preCaretRange = range.cloneRange()
            preCaretRange.selectNodeContents(element)
            preCaretRange.setEnd(range.startContainer, range.startOffset)
            const textBeforeCaret = preCaretRange.toString()

            // Remove placeholder characters («field_name») from offset calculation
            // Placeholders in HTML are rendered as: «field_name» (7+ chars depending on field name)
            // But in DOCX plain text, they might be counted differently or not at all
            const textWithoutPlaceholders = textBeforeCaret.replace(/«[^»]+»/g, '')
            offset = textWithoutPlaceholders.length

            console.log('[DEBUG] Click offset:', {
              blockIndex,
              offset,
              textBeforeCaret: textBeforeCaret.substring(0, 50) + '...',
              textWithoutPlaceholders: textWithoutPlaceholders.substring(0, 50) + '...'
            })
          }

          setSelectedBlockIndex(blockIndex)
          setSelectedCellIndex(null) // Reset cell index when selecting block
          setSelectedTableBlockIndex(null)
          setSelectedParaInCell(null) // Reset paragraph index
          setCaretOffset(offset) // Store caret offset for precise insertion

          // Highlight selected block
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          const offsetMsg = offset !== null ? ` (vị trí ký tự #${offset})` : ''
          setError(`Đã chọn ${blockType === 'table' ? 'bảng' : 'đoạn'} #${blockIndex}${offsetMsg}. Nhập tên placeholder và nhấn "Thêm".`)
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

  // Handle text selection for enhanced editing (NOT in add mode)
  useEffect(() => {
    const editor = document.getElementById('document-editor')
    if (!editor || !editorHtml || isAddMode) return

    const handleMouseUp = () => {
      setTimeout(() => {
        handleTextSelection()
      }, 10)
    }

    editor.addEventListener('mouseup', handleMouseUp)

    return () => {
      editor.removeEventListener('mouseup', handleMouseUp)
    }
  }, [editorHtml, isAddMode])

  // Refresh template after text update
  useEffect(() => {
    const refreshAfterTextUpdate = async () => {
      if (templateNeedsUpdate && templateId) {
        try {
          // CRITICAL FIX: Save scroll position before refreshing
          const editor = document.getElementById('document-editor')
          const savedScrollTop = editor ? editor.scrollTop : 0
          const savedScrollLeft = editor ? editor.scrollLeft : 0

          console.log('[DEBUG] Refresh: Saved scroll position:', { scrollTop: savedScrollTop, scrollLeft: savedScrollLeft })

          const info = await getTemplateInfo(templateId)
          setEditorHtml(info.html_preview)
          setFields(info.fields)
          setTemplateNeedsUpdate(false)

          // Restore scroll position after React re-renders
          setTimeout(() => {
            const editorAfter = document.getElementById('document-editor')
            if (editorAfter) {
              editorAfter.scrollTop = savedScrollTop
              editorAfter.scrollLeft = savedScrollLeft
              console.log('[DEBUG] Refresh: Restored scroll position:', { scrollTop: editorAfter.scrollTop, scrollLeft: editorAfter.scrollLeft })
            }
          }, 0)
        } catch (err) {
          console.error('Failed to refresh template:', err)
        }
      }
    }

    refreshAfterTextUpdate()
  }, [templateNeedsUpdate, templateId])

  // Rename placeholder
  const renameField = async (oldName, newName) => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    // Get all current fields BEFORE UI update
    const currentFields = extractFields(editor.innerHTML)

    // Update renameMap: replace oldName with newName in all values
    const newMap = {}
    for (const [original, current] of Object.entries(renameMap)) {
      if (current === oldName) {
        newMap[original] = newName
      } else {
        newMap[original] = current
      }
    }

    // Update UI immediately
    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      if (span.getAttribute('data-field') === oldName) {
        span.setAttribute('data-field', newName)
        span.textContent = `«${newName}»`
      }
    })

    const newHtml = editor.innerHTML
    setEditorHtml(newHtml)
    setFields(extractFields(newHtml))
    setRenameMap(newMap)

    try {
      // Create mapping from current field names to new field names
      // This ensures ALL current fields are included, even if unchanged
      const backendMap = {}
      currentFields.forEach(field => {
        if (field === oldName) {
          backendMap[field] = newName
        } else {
          backendMap[field] = field
        }
      })

      // Save to backend IMMEDIATELY to persist rename
      await updateTemplate(templateId, backendMap, newHtml)
      setTemplateNeedsUpdate(false) // Reset flag since we just updated
      setError(`✅ Đã đổi tên «${oldName}» → «${newName}»`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Failed to rename placeholder:', err)
      setError('⚠️ Đổi tên thất bại: ' + (err.response?.data?.detail || err.message))
      // Rollback UI on failure
      editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
        if (span.getAttribute('data-field') === newName) {
          span.setAttribute('data-field', oldName)
          span.textContent = `«${oldName}»`
        }
      })
      setRenameMap(renameMap)
      setEditorHtml(editorHtml)
      setFields(extractFields(editorHtml))
      setTimeout(() => setError(null), 3000)
    }
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
      const result = await suggestPlaceholders(templateId)
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
      let result

      // Use caret offset if available (precise insertion at click position)
      if (caretOffset !== null) {
        console.log('[DEBUG] Using caret offset for insertion:', caretOffset)
        result = await addPlaceholderAtOffset(
          templateId,
          selectedBlockIndex,
          caretOffset,
          newFieldName.trim(),
          true // inherit format
        )
      } else {
        // Fallback to old method (left/right/new_line)
        result = await addPlaceholder(
          templateId,
          selectedBlockIndex,
          newFieldName.trim(),
          newFieldPosition,
          null, // No need for cell_index anymore (each cell has its own block_index)
          selectedParaInCell // Pass paragraph index within cell for precise targeting
        )
      }

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
      setCaretOffset(null) // Reset caret offset
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
    setCaretOffset(null) // Reset caret offset
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
    setShowEditPopup(false)
    setSelectedTextForEdit(null)
    setCopiedFormat(null) // Clear copied format
  }

  // Handle text selection for editing
  const handleTextSelection = async () => {
    const selection = window.getSelection()
    const selectedText = selection.toString().trim()

    // Only show format popup for regular text (not placeholders)
    if (selectedText && !isAddMode && !selectedText.includes('«')) {
      const element = selection.anchorNode.parentElement

      // Find block_index from parent elements
      let blockIndex = null
      let currentElement = element
      let blockElement = null
      while (currentElement && currentElement.id !== 'document-editor') {
        if (currentElement.hasAttribute && currentElement.hasAttribute('data-block-index')) {
          blockIndex = parseInt(currentElement.getAttribute('data-block-index'))
          blockElement = currentElement
          break
        }
        currentElement = currentElement.parentElement
      }

      // Calculate offset within block
      let offset = 0
      let endOffset = 0
      if (blockElement) {
        // Get text before selection in the block
        const range = selection.getRangeAt(0)
        const preSelectionRange = range.cloneRange()
        preSelectionRange.selectNodeContents(blockElement)
        preSelectionRange.setEnd(range.startContainer, range.startOffset)
        offset = preSelectionRange.toString().length

        // Get text before end of selection
        const postSelectionRange = range.cloneRange()
        postSelectionRange.selectNodeContents(blockElement)
        postSelectionRange.setEnd(range.endContainer, range.endOffset)
        endOffset = postSelectionRange.toString().length
      }

      // Get accurate format from DOCX backend (not from HTML computed style)
      let format = {
        bold: false,
        italic: false,
        underline: false,
        strikethrough: false,
        subscript: false,
        superscript: false,
        color: '#000000',
        fontSize: 12,
        fontName: 'Times New Roman'
      }

      try {
        if (templateId) {
          const response = await getSelectionFormat(templateId, selectedText, blockIndex)
          if (response?.format) {
            format = response.format
          }
        }
      } catch (error) {
        console.error('Failed to get selection format from backend:', error)
        // Fall back to computed style if backend fails
        const computedStyle = window.getComputedStyle(element)
        const textDecorationLine = computedStyle.textDecorationLine || ''
        format = {
          bold: computedStyle.fontWeight === '700' || computedStyle.fontWeight === 'bold',
          italic: computedStyle.fontStyle === 'italic',
          underline: textDecorationLine.includes('underline'),
          strikethrough: textDecorationLine.includes('line-through'),
          color: computedStyle.color,
          fontSize: parseInt(computedStyle.fontSize) || 12,
          fontName: computedStyle.fontFamily.split(',')[0].replace(/['"]/g, '').trim()
        }
      }

      setSelectedTextForEdit({
        text: selectedText,
        element: element,
        format: format,
        blockIndex: blockIndex,
        offset: offset,
        endOffset: endOffset
      })
      setShowEditPopup(true)
    }
  }

  // Handle format application from EditPopup
  const handleFormatApplied = async (formatData) => {
    if (!templateId) return

    try {
      const result = await editSelection(templateId, formatData)

      // Update UI
      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      setShowEditPopup(false)
      setSelectedTextForEdit(null)

      // Show success message
      setError(`✅ Đã áp dụng định dạng thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Format application failed:', err)
      setError('Áp dụng định dạng thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  // Handle add content
  const handleAddContent = async (addData) => {
    if (!templateId) return

    try {
      const result = await addContent(templateId, addData)

      // Update UI
      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      // Show success message
      setError(`✅ Đã thêm ${addData.type} thành công!`)
      setTimeout(() => setError(null), 3000)
    } catch (err) {
      console.error('Add content failed:', err)
      setError('Thêm nội dung thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  // Table operation handlers
  const handleAddTableRow = async (position = 'below') => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, rowIndex } = selectedTableInfo
      const result = await addTableRow(templateId, tableIndex, rowIndex, position)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      setError(`✅ Đã thêm row ${position === 'above' ? 'trên' : 'dưới'} thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add table row failed:', err)
      setError('Thêm row thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleDeleteTableRow = async () => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, rowIndex } = selectedTableInfo
      const result = await deleteTableRow(templateId, tableIndex, rowIndex)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      // Reset table selection after deleting
      setSelectedTableInfo({
        tableIndex: null,
        rowIndex: null,
        colIndex: null,
        isCellSelected: false
      })

      setError(`✅ Đã xóa row thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Delete table row failed:', err)
      setError('Xóa row thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleAddTableColumn = async (position = 'right') => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, colIndex } = selectedTableInfo
      const result = await addTableColumn(templateId, tableIndex, colIndex, position)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      setError(`✅ Đã thêm column ${position === 'left' ? 'trái' : 'phải'} thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add table column failed:', err)
      setError('Thêm column thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleDeleteTableColumn = async () => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, colIndex } = selectedTableInfo
      const result = await deleteTableColumn(templateId, tableIndex, colIndex)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      // Reset table selection after deleting
      setSelectedTableInfo({
        tableIndex: null,
        rowIndex: null,
        colIndex: null,
        isCellSelected: false
      })

      setError(`✅ Đã xóa column thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Delete table column failed:', err)
      setError('Xóa column thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleAddTableAtCursor = async () => {
    try {
      // Get current selection
      const selection = window.getSelection()
      if (!selection.rangeCount) {
        setError('❌ Vui lòng chọn vị trí muốn thêm bảng!')
        return
      }

      // Get cursor position info
      const blockIndex = getCurrentBlockIndex()
      if (blockIndex === null || blockIndex === -1) {
        setError('❌ Vui lòng click vào vị trí muốn thêm bảng!')
        return
      }

      // Calculate offset within block
      const range = selection.getRangeAt(0)
      const offset = calculateCursorOffset(range, blockIndex)

      if (offset === null) {
        setError('❌ Không thể xác định vị trí cursor!')
        return
      }

      console.log(`[DEBUG] Adding table at blockIndex=${blockIndex}, offset=${offset}, size=${tableSize.rows}x${tableSize.cols}`)

      const result = await addTableAtCursor(
        templateId,
        blockIndex,
        offset,
        tableSize.rows,
        tableSize.cols
      )

      console.log('[DEBUG] API result:', result)
      console.log('[DEBUG] HTML preview length:', result.html_preview?.length)
      console.log('[DEBUG] HTML preview preview:', result.html_preview?.substring(0, 500))

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)
      setTemplateNeedsUpdate(true)

      setShowAddTablePopup(false)
      setError(`✅ Đã thêm bảng ${tableSize.rows}x${tableSize.cols} thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add table at cursor failed:', err)
      setError('Thêm bảng thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleAddImageAtCursor = async () => {
    try {
      // Validate image file selected
      if (!selectedImageFile) {
        setError('❌ Vui lòng chọn ảnh muốn chèn!')
        return
      }

      // Get current selection
      const selection = window.getSelection()
      if (!selection.rangeCount) {
        setError('❌ Vui lòng chọn vị trí muốn thêm ảnh!')
        return
      }

      // Get cursor position info
      const blockIndex = getCurrentBlockIndex()
      if (blockIndex === null || blockIndex === -1) {
        setError('❌ Vui lòng click vào vị trí muốn thêm ảnh!')
        return
      }

      // Calculate offset within block
      const range = selection.getRangeAt(0)
      const offset = calculateCursorOffset(range, blockIndex)

      if (offset === null) {
        setError('❌ Không thể xác định vị trí cursor!')
        return
      }

      console.log(`[DEBUG] Adding image at blockIndex=${blockIndex}, offset=${offset}, width=${imageWidth} inches`)

      const result = await addImageAtCursor(
        templateId,
        blockIndex,
        offset,
        selectedImageFile,
        imageWidth
      )

      console.log('[DEBUG] API result:', result)
      console.log('[DEBUG] HTML preview length:', result.html_preview?.length)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)
      setTemplateNeedsUpdate(true)

      setShowAddImagePopup(false)
      setSelectedImageFile(null)
      setImageWidth(4.0) // Reset to default
      setError(`✅ Đã thêm ảnh thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add image at cursor failed:', err)
      setError('Thêm ảnh thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleFormatTableCell = async () => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, rowIndex, colIndex } = selectedTableInfo
      const result = await formatTableCell(templateId, tableIndex, rowIndex, colIndex, cellFormatOptions)

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      setShowCellFormatDialog(false)
      setError(`✅ Đã format cell thành công!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Format table cell failed:', err)
      setError('Format cell thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleOpenHyperlinkDialog = (blockIndex, startOffset, endOffset, selectedText) => {
    setHyperlinkPosition({
      blockIndex,
      startOffset,
      endOffset,
      selectedText
    })
    setHyperlinkData({ url: '' })
    setShowHyperlinkDialog(true)
  }

  const handleAddHyperlink = async () => {
    if (!hyperlinkData.url.trim()) {
      setError('Vui lòng nhập URL cho hyperlink')
      return
    }

    try {
      const result = await addHyperlink(
        templateId,
        hyperlinkPosition.blockIndex,
        hyperlinkPosition.startOffset,
        hyperlinkPosition.endOffset,
        hyperlinkData.url
      )

      setEditorHtml(result.html_preview)
      setFields(result.fields)
      setOriginalFields(result.fields)

      setShowHyperlinkDialog(false)
      setHyperlinkData({ url: '' })
      setError(`✅ Đã thêm hyperlink vào "${hyperlinkPosition.selectedText}"!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add hyperlink failed:', err)
      setError('Thêm hyperlink thất bại: ' + (err.response?.data?.detail || err.message))
    }
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
                        Click vào vị trí bất kỳ trong tài liệu để thêm placeholder mới (chèn đúng tại vị trí click)
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
                          👆 Click vào vị trí bất kỳ trong tài liệu bên dưới để chèn placeholder tại chính vị trí đó
                        </p>
                      ) : (
                        <div className="space-y-3">
                          <p className="text-sm text-green-700 font-semibold">
                            {selectedParaInCell !== null
                              ? `✓ Đã chọn dòng #${selectedParaInCell} trong ô #${selectedCellIndex} của bảng #${selectedTableBlockIndex}`
                              : selectedCellIndex !== null
                                ? `✓ Đã chọn ô #${selectedCellIndex} trong bảng #${selectedTableBlockIndex}`
                                : caretOffset !== null
                                  ? `✓ Đã chọn vị trí chính xác tại ký tự #${caretOffset} trong đoạn #${selectedBlockIndex}`
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

                          {caretOffset === null && (
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
                          )}

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

                  {/* Format indicator */}
                  {copiedFormat && (
                    <div className="bg-indigo-100 border border-indigo-300 rounded-lg px-3 py-1 text-xs text-indigo-700">
                      🎨 Format sẵn sàng! Chọn văn bản và bấm "Paste Format"
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setCopiedFormat(null)
                        }}
                        className="ml-2 text-red-500 hover:text-red-700 font-bold"
                        title="Xóa format đã copy"
                      >
                        ×
                      </button>
                    </div>
                  )}

                  {/* Enhanced editing buttons */}
                  {!isAddMode && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          const editor = document.getElementById('document-editor')
                          if (editor) {
                            editor.focus()
                            setError('💡 Chọn văn bản trong tài liệu để mở menu chỉnh sửa')
                          }
                        }}
                        className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600 font-medium"
                        title="Click để chọn text để sửa"
                      >
                        ✏️ Chỉnh sửa
                      </button>
                      <button
                        onClick={() => {
                          const selection = window.getSelection()
                          const selectedText = selection.toString().trim()

                          if (selectedText && selectedTextForEdit) {
                            // Copy format from current selection
                            setCopiedFormat(selectedTextForEdit.format)
                            setError('✅ Đã copy định dạng! Chọn văn bản khác và bấm "Paste Format"')
                            setTimeout(() => setError(null), 3000)
                          } else {
                            setError('⚠️ Chọn văn bản để copy định dạng trước')
                            setTimeout(() => setError(null), 2000)
                          }
                        }}
                        className="px-3 py-1.5 bg-purple-500 text-white rounded-lg text-sm hover:bg-purple-600 font-medium"
                        title="Copy định dạng từ văn bản đang chọn"
                      >
                        📋 Copy Format
                      </button>
                      <button
                        onClick={async () => {
                          if (!copiedFormat) {
                            setError('⚠️ Chưa có định dạng nào được copy. Bấm "Copy Format" trước!')
                            setTimeout(() => setError(null), 2000)
                            return
                          }

                          const selection = window.getSelection()
                          const selectedText = selection.toString().trim()

                          if (!selectedText) {
                            setError('⚠️ Chọn văn bản để paste định dạng!')
                            setTimeout(() => setError(null), 2000)
                            return
                          }

                          try {
                            // Get block index
                          const element = selection.anchorNode.parentElement
                          let blockIndex = null
                          let currentElement = element
                          while (currentElement && currentElement.id !== 'document-editor') {
                            if (currentElement.hasAttribute && currentElement.hasAttribute('data-block-index')) {
                              blockIndex = parseInt(currentElement.getAttribute('data-block-index'))
                              break
                            }
                            currentElement = currentElement.parentElement
                          }

                          const formatData = {
                            selectedText: selectedText,
                            format: copiedFormat,
                            type: 'format',
                            blockIndex: blockIndex
                          }

                          await handleFormatApplied(formatData)
                          setError('✅ Đã paste định dạng!')
                          setTimeout(() => setError(null), 2000)
                        } catch (err) {
                          console.error('Paste format failed:', err)
                          setError('⚠️ Paste định dạng thất bại: ' + (err.message || err))
                          setTimeout(() => setError(null), 3000)
                        }
                        }}
                        disabled={!copiedFormat}
                        className={`px-3 py-1.5 text-white rounded-lg text-sm font-medium transition-colors ${
                          copiedFormat
                            ? 'bg-indigo-500 hover:bg-indigo-600'
                            : 'bg-gray-300 cursor-not-allowed'
                        }`}
                        title="Paste định dạng đã copy vào văn bản đang chọn"
                      >
                        🎨 Paste Format
                      </button>
                      <button
                        onClick={() => handleAddContent({ type: 'placeholder', position: 'end', fieldName: prompt('Tên placeholder:') })}
                        className="ml-2 px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600 transition-colors text-sm"
                        title="Thêm placeholder"
                      >
                        ➕ Thêm
                      </button>
                      <button
                        onClick={() => setShowAddImagePopup(true)}
                        className="ml-2 px-3 py-1 bg-orange-500 text-white rounded hover:bg-orange-600 transition-colors text-sm"
                        title="Thêm ảnh tại vị trí cursor"
                      >
                        📷 Thêm Ảnh
                      </button>
                      <button
                        onClick={() => setShowAddTablePopup(true)}
                        className="ml-2 px-3 py-1 bg-purple-500 text-white rounded hover:bg-purple-600 transition-colors text-sm"
                        title="Thêm bảng mới tại vị trí cursor"
                      >
                        📊 Thêm Bảng
                      </button>
                    </div>
                  )}

                  {/* Table editing toolbar */}
                  {selectedTableInfo.isCellSelected && (
                    <div className="mt-3 p-3 bg-indigo-50 border border-indigo-200 rounded-lg">
                      <div className="text-sm font-semibold text-indigo-800 mb-2">
                        📊 Công cụ bảng - Ô [{selectedTableInfo.rowIndex}, {selectedTableInfo.colIndex}]
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {/* Row operations */}
                        <div className="flex gap-1 border-r border-indigo-300 pr-2">
                          <button
                            onClick={() => handleAddTableRow('above')}
                            className="px-2 py-1 bg-blue-500 text-white rounded text-xs hover:bg-blue-600 font-medium"
                            title="Thêm row phía trên"
                          >
                            ⬆️ Row Trên
                          </button>
                          <button
                            onClick={() => handleAddTableRow('below')}
                            className="px-2 py-1 bg-blue-500 text-white rounded text-xs hover:bg-blue-600 font-medium"
                            title="Thêm row phía dưới"
                          >
                            ⬇️ Row Dưới
                          </button>
                          <button
                            onClick={handleDeleteTableRow}
                            className="px-2 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600 font-medium"
                            title="Xóa row hiện tại"
                          >
                            🗑️ Xóa Row
                          </button>
                        </div>

                        {/* Column operations */}
                        <div className="flex gap-1 border-r border-indigo-300 pr-2">
                          <button
                            onClick={() => handleAddTableColumn('left')}
                            className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600 font-medium"
                            title="Thêm column bên trái"
                          >
                            ⬅️ Col Trái
                          </button>
                          <button
                            onClick={() => handleAddTableColumn('right')}
                            className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600 font-medium"
                            title="Thêm column bên phải"
                          >
                            ➡️ Col Phải
                          </button>
                          <button
                            onClick={handleDeleteTableColumn}
                            className="px-2 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600 font-medium"
                            title="Xóa column hiện tại"
                          >
                            🗑️ Xóa Col
                          </button>
                        </div>

                        {/* Cell formatting */}
                        <div className="flex gap-1">
                          <button
                            onClick={() => setShowCellFormatDialog(true)}
                            className="px-2 py-1 bg-purple-500 text-white rounded text-xs hover:bg-purple-600 font-medium"
                            title="Format ô (màu nền, căn lề)"
                          >
                            🎨 Format Cell
                          </button>
                          <button
                            onClick={() => setSelectedTableInfo({
                              tableIndex: null,
                              rowIndex: null,
                              colIndex: null,
                              isCellSelected: false
                            })}
                            className="px-2 py-1 bg-gray-500 text-white rounded text-xs hover:bg-gray-600 font-medium"
                            title="Bỏ chọn ô"
                          >
                            ✖️ Bỏ Chọn
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div
                  id="document-editor"
                  contentEditable
                  className="border border-gray-300 rounded-lg p-6 bg-white min-h-[400px] overflow-auto focus:ring-2 focus:ring-blue-500"
                  style={{ maxHeight: '600px' }}
                  suppressContentEditableWarning={true}
                  onKeyDown={async (e) => {
                    // Detect Enter key to create new paragraph
                    if (e.key === 'Enter' && !e.shiftKey && !isAddMode) {
                      const selection = window.getSelection()
                      if (selection.rangeCount > 0) {
                        const range = selection.getRangeAt(0)
                        const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                          ? range.startContainer.parentElement
                          : range.startContainer

                        // Check if we're in a table cell paragraph or regular block
                        const cellParagraph = startElement?.closest('.cell-paragraph')
                        const editedBlock = startElement?.closest('[data-block-index]')

                        if (cellParagraph || editedBlock) {
                          e.preventDefault()

                          try {
                            // Determine parameters for addParagraph API
                            let params = {
                              position: 'after',
                              text: ''
                            }

                            if (cellParagraph) {
                              // In table cell
                              const cellBlock = cellParagraph?.closest('[data-block-index]')
                              if (cellBlock) {
                                const cellBlockIndex = parseInt(cellBlock.getAttribute('data-block-index'))
                                const paraInCell = parseInt(cellParagraph.getAttribute('data-para-in-cell'))
                                const tableIndex = parseInt(cellBlock.getAttribute('data-table-index') || '0')
                                const row = parseInt(cellBlock.getAttribute('data-row'))
                                const col = parseInt(cellBlock.getAttribute('data-col'))

                                params = {
                                  ...params,
                                  blockIndex: cellBlockIndex,
                                  tableIndex: tableIndex,
                                  rowIndex: row,
                                  colIndex: col,
                                  paraInCell: paraInCell
                                }
                              }
                            } else if (editedBlock) {
                              // In regular block
                              const blockIndex = parseInt(editedBlock.getAttribute('data-block-index'))
                              params = {
                                ...params,
                                blockIndex: blockIndex
                              }
                            }

                            console.log('[DEBUG] Creating new paragraph with params:', params)

                            // Call API to add paragraph
                            const result = await addParagraph(
                              templateId,
                              params.blockIndex,
                              params.position,
                              params.text,
                              params.tableIndex,
                              params.rowIndex,
                              params.colIndex,
                              params.paraInCell
                            )

                            // Update UI with new HTML preview
                            setEditorHtml(result.html_preview)
                            setFields(result.fields)
                            setOriginalFields(result.fields)

                            setError('✅ Đã thêm dòng mới thành công!')
                            setTimeout(() => setError(null), 2000)

                          } catch (err) {
                            console.error('Failed to add paragraph:', err)
                            setError('⚠️ Thêm dòng mới thất bại: ' + (err.response?.data?.detail || err.message))
                            setTimeout(() => setError(null), 3000)
                          }
                        }
                      }
                    }

                    // Detect Delete/Backspace to remove characters or paragraphs
                    if ((e.key === 'Delete' || e.key === 'Backspace') && !isAddMode) {
                      const selection = window.getSelection()
                      if (selection.rangeCount > 0) {
                        const range = selection.getRangeAt(0)

                        // Check if user is selecting multiple blocks (not just text)
                        const isMultipleBlockSelection = () => {
                          // Get selection boundaries
                          const startContainer = range.startContainer
                          const endContainer = range.endContainer

                          // Get block elements for start and end
                          const startElement = startContainer.nodeType === Node.TEXT_NODE
                            ? startContainer.parentElement
                            : startContainer
                          const endElement = endContainer.nodeType === Node.TEXT_NODE
                            ? endContainer.parentElement
                            : endContainer

                          const startBlock = startElement?.closest('[data-block-index], .cell-paragraph')
                          const endBlock = endElement?.closest('[data-block-index], .cell-paragraph')

                          // If start and end are in different blocks, it's multi-block selection
                          if (startBlock && endBlock && startBlock !== endBlock) {
                            return true
                          }

                          // Check if entire block content is selected
                          if (startBlock) {
                            const blockText = startBlock.textContent
                            const selectedText = selection.toString()

                            // If entire block text is selected (or close to entire)
                            if (selectedText.length >= blockText.length * 0.9) {
                              return true
                            }
                          }

                          return false
                        }

                        // Case 1: Delete entire empty paragraph with Backspace/Delete
                        const isDeletingEmptyParagraph = () => {
                          const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                            ? range.startContainer.parentElement
                            : range.startContainer

                          const cellParagraph = startElement?.closest('.cell-paragraph')
                          const editedBlock = startElement?.closest('[data-block-index]')

                          // Get current block/paragraph text
                          let currentText = ''
                          if (cellParagraph) {
                            currentText = cellParagraph.textContent?.trim() || ''
                          } else if (editedBlock) {
                            currentText = editedBlock.textContent?.trim() || ''
                          }

                          // If block is empty and cursor is at start/end
                          const isAtStart = range.startOffset === 0 && range.endOffset === 0
                          const isAtEnd = range.startOffset === (range.startContainer.length || 0) &&
                                         range.endOffset === (range.endContainer.length || 0)

                          return currentText === '' && (isAtStart || isAtEnd)
                        }

                        // Case 2: Multiple block selection - delete all selected blocks
                        if (isMultipleBlockSelection()) {
                          e.preventDefault()

                          try {
                            // Helper function to get all blocks in selection
                            const getBlocksInSelection = () => {
                              const blocks = []
                              const editor = document.getElementById('document-editor')
                              if (!editor) return blocks

                              // Get all blocks within the selection range
                              const allBlocks = editor.querySelectorAll('[data-block-index], .cell-paragraph')

                              allBlocks.forEach(block => {
                                // Check if this block intersects with selection
                                const blockRange = document.createRange()
                                blockRange.selectNodeContents(block)

                                const intersects = range.intersectsNode(block)
                                if (intersects) {
                                  // Get block metadata
                                  if (block.classList.contains('cell-paragraph')) {
                                    // Table cell paragraph
                                    const cellBlock = block.closest('[data-block-index]')
                                    if (cellBlock) {
                                      blocks.push({
                                        type: 'table_cell',
                                        blockIndex: parseInt(cellBlock.getAttribute('data-block-index')),
                                        paraInCell: parseInt(block.getAttribute('data-para-in-cell')),
                                        tableIndex: parseInt(cellBlock.getAttribute('data-table-index') || '0'),
                                        rowIndex: parseInt(cellBlock.getAttribute('data-row')),
                                        colIndex: parseInt(cellBlock.getAttribute('data-col')),
                                        text: block.textContent?.trim() || ''
                                      })
                                    }
                                  } else if (block.hasAttribute('data-block-index')) {
                                    // Regular paragraph block
                                    blocks.push({
                                      type: 'paragraph',
                                      blockIndex: parseInt(block.getAttribute('data-block-index')),
                                      text: block.textContent?.trim() || ''
                                    })
                                  }
                                }
                              })

                              return blocks
                            }

                            const selectedBlocks = getBlocksInSelection()

                            if (selectedBlocks.length > 0) {
                              // Prepare blocks data for API
                              const blocksData = selectedBlocks.map(block => {
                                if (block.type === 'table_cell') {
                                  return {
                                    block_index: block.blockIndex,
                                    table_index: block.tableIndex,
                                    row_index: block.rowIndex,
                                    col_index: block.colIndex,
                                    para_in_cell: block.paraInCell
                                  }
                                } else {
                                  return {
                                    block_index: block.blockIndex
                                  }
                                }
                              })

                              console.log('[DEBUG] Deleting multiple paragraphs:', blocksData)

                              // Call API to delete multiple paragraphs
                              const result = await deleteMultipleParagraphs(
                                templateId,
                                blocksData
                              )

                              // Update UI with new HTML preview
                              setEditorHtml(result.html_preview)
                              setFields(result.fields)
                              setOriginalFields(result.fields)

                              setError(`✅ Đã xóa ${result.deleted_count} dòng!`)
                              setTimeout(() => setError(null), 2000)
                            }

                          } catch (err) {
                            console.error('Failed to delete paragraphs:', err)
                            setError('⚠️ Xóa dòng thất bại: ' + (err.response?.data?.detail || err.message))
                            setTimeout(() => setError(null), 3000)
                          }
                        }
                        // Case 3: Delete empty single paragraph
                        else if (isDeletingEmptyParagraph()) {
                          e.preventDefault()

                          try {
                            const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                              ? range.startContainer.parentElement
                              : range.startContainer

                            const cellParagraph = startElement?.closest('.cell-paragraph')
                            const editedBlock = startElement?.closest('[data-block-index]')

                            let params = {
                              blockIndex: null
                            }

                            if (cellParagraph) {
                              const cellBlock = cellParagraph?.closest('[data-block-index]')
                              if (cellBlock) {
                                const cellBlockIndex = parseInt(cellBlock.getAttribute('data-block-index'))
                                const paraInCell = parseInt(cellParagraph.getAttribute('data-para-in-cell'))
                                const tableIndex = parseInt(cellBlock.getAttribute('data-table-index') || '0')
                                const row = parseInt(cellBlock.getAttribute('data-row'))
                                const col = parseInt(cellBlock.getAttribute('data-col'))

                                params = {
                                  ...params,
                                  blockIndex: cellBlockIndex,
                                  tableIndex: tableIndex,
                                  rowIndex: row,
                                  colIndex: col,
                                  paraInCell: paraInCell
                                }
                              }
                            } else if (editedBlock) {
                              const blockIndex = parseInt(editedBlock.getAttribute('data-block-index'))
                              params = {
                                ...params,
                                blockIndex: blockIndex
                              }
                            }

                            console.log('[DEBUG] Deleting empty paragraph with params:', params)

                            const result = await deleteParagraph(
                              templateId,
                              params.blockIndex,
                              params.tableIndex,
                              params.rowIndex,
                              params.colIndex,
                              params.paraInCell
                            )

                            setEditorHtml(result.html_preview)
                            setFields(result.fields)
                            setOriginalFields(result.fields)

                            setError('✅ Đã xóa dòng trống!')
                            setTimeout(() => setError(null), 2000)

                          } catch (err) {
                            console.error('Failed to delete paragraph:', err)
                            setError('⚠️ Xóa dòng thất bại: ' + (err.response?.data?.detail || err.message))
                            setTimeout(() => setError(null), 3000)
                          }
                        }
                        // Case 4: Normal character deletion - let contentEditable handle it
                        // Don't preventDefault, allow normal delete behavior
                      }
                    }
                  }}
                  onInput={async (e) => {
                    const newHtml = e.target.innerHTML
                    const newFields = extractFields(newHtml)

                    // Check if any placeholders were deleted
                    const deletedFields = fields.filter(f => !newFields.includes(f))

                    // DON'T update editorHtml on every keystroke - this causes cursor jumping!
                    // contentEditable handles text changes natively
                    // Only update fields state when placeholders change
                    if (newFields.length !== fields.length || JSON.stringify(newFields) !== JSON.stringify(fields)) {
                      setFields(newFields)
                    }

                    // NEW: Detect text changes (not just placeholder deletions)
                    const selection = window.getSelection()
                    if (selection.rangeCount > 0) {
                      const range = selection.getRangeAt(0)

                      // Handle text nodes (startContainer might be text, not element)
                      const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                        ? range.startContainer.parentElement
                        : range.startContainer

                      // Check if editing within a table cell paragraph
                      const cellParagraph = startElement?.closest('.cell-paragraph')
                      const editedBlock = startElement?.closest('[data-block-index]')

                      console.log('[DEBUG] ========== Text Edit Detection ==========')
                      console.log('[DEBUG] startElement:', startElement)
                      console.log('[DEBUG] cellParagraph:', cellParagraph)
                      console.log('[DEBUG] editedBlock:', editedBlock)

                      if (cellParagraph) {
                        // Table cell paragraph editing - get block index from the containing cell
                        const cellBlock = cellParagraph?.closest('[data-block-index]')
                        console.log('[DEBUG] cellBlock:', cellBlock)

                        if (cellBlock) {
                          const cellBlockIndex = parseInt(cellBlock.getAttribute('data-block-index'))
                          const paraInCell = parseInt(cellParagraph.getAttribute('data-para-in-cell'))
                          const cellIndex = parseInt(cellParagraph.getAttribute('data-cell'))

                          console.log('[DEBUG] cellBlock attributes:', {
                            'data-block-index': cellBlock.getAttribute('data-block-index'),
                            'data-cell-block-index': cellParagraph.getAttribute('data-cell-block-index'),
                            'data-para-in-cell': cellParagraph.getAttribute('data-para-in-cell'),
                            'data-cell': cellParagraph.getAttribute('data-cell')
                          })
                          console.log('[DEBUG] Parsed values:', {
                            cellBlockIndex,
                            paraInCell,
                            cellIndex
                          })

                          // Log all paragraphs in this cell for debugging
                          const tempDiv = document.createElement('div')
                          tempDiv.innerHTML = editorHtml
                          const allCellParas = tempDiv.querySelectorAll(`[data-block-index="${cellBlockIndex}"] .cell-paragraph`)
                          console.log('[DEBUG] All paragraphs in cell', cellBlockIndex, ':')
                          allCellParas.forEach((p, i) => {
                            console.log('[DEBUG]   Para', i, ':', {
                              'data-para-in-cell': p.getAttribute('data-para-in-cell'),
                              'data-cell-block-index': p.getAttribute('data-cell-block-index'),
                              'textContent': p.textContent
                            })
                          })

                          // Validate indices before proceeding
                          if (isNaN(cellBlockIndex) || isNaN(paraInCell)) {
                            console.warn('Invalid table cell indices, skipping text update')
                            return
                          }

                          // CRITICAL FIX: Check if paragraph count in cell changed (paragraph added/deleted)
                          const tempDivOld = document.createElement('div')
                          tempDivOld.innerHTML = editorHtml
                          const oldCellParas = tempDivOld.querySelectorAll(`[data-block-index="${cellBlockIndex}"] .cell-paragraph`)

                          const tempDivNew = document.createElement('div')
                          tempDivNew.innerHTML = newHtml
                          const newCellParas = tempDivNew.querySelectorAll(`[data-block-index="${cellBlockIndex}"] .cell-paragraph`)

                          console.log('[DEBUG] Paragraph count:', {
                            old: oldCellParas.length,
                            new: newCellParas.length,
                            changed: oldCellParas.length !== newCellParas.length
                          })

                          // Track if we need to refresh after processing all changes
                          let needsRefresh = false
                          let skipTextUpdates = false // Skip text updates if structure changed significantly

                          // If paragraph count changed, user deleted/added a paragraph
                          if (oldCellParas.length !== newCellParas.length && deletedFields.length === 0) {
                            console.log('[DEBUG] Paragraph count changed - processing paragraph deletion/addition')

                            // Find which paragraphs were deleted by comparing para-in-cell indices
                            const oldIndices = Array.from(oldCellParas).map(p => parseInt(p.getAttribute('data-para-in-cell')))
                            const newIndices = Array.from(newCellParas).map(p => parseInt(p.getAttribute('data-para-in-cell')))
                            const deletedIndices = oldIndices.filter(i => !newIndices.includes(i))

                            console.log('[DEBUG] Deleted paragraph indices:', deletedIndices)

                            // Delete each deleted paragraph by clearing its content
                            for (const deletedParaIndex of deletedIndices) {
                              try {
                                // Get the text content before deletion
                                const deletedText = getTextFromCellParagraph(editorHtml, cellBlockIndex, deletedParaIndex)

                                console.log('[DEBUG] Deleting paragraph:', {
                                  cellBlockIndex,
                                  deletedParaIndex,
                                  deletedText
                                })

                                // Call backend to delete the paragraph (clear its content)
                                const formData = new FormData()
                                formData.append('template_id', templateId)
                                formData.append('block_index', cellBlockIndex)
                                formData.append('old_text', deletedText)
                                formData.append('new_text', '') // Empty to delete
                                formData.append('edit_type', 'text')
                                formData.append('para_in_cell', deletedParaIndex)

                                await axios.post(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/update-text`, formData, {
                                  headers: { 'Content-Type': 'multipart/form-data' }
                                })

                                console.log('[DEBUG] Successfully deleted paragraph', deletedParaIndex)
                                needsRefresh = true
                              } catch (err) {
                                console.error('[DEBUG] Failed to delete paragraph:', err)
                              }
                            }

                            // CRITICAL: After deletions, refresh from backend to get correct HTML with preserved alignment
                            // DON'T use newHtml from contentEditable as it may lose alignment styles
                            console.log('[DEBUG] Refreshing from backend after paragraph deletions')

                            // Save scroll position before refreshing
                            const editor = document.getElementById('document-editor')
                            const savedScrollTop = editor ? editor.scrollTop : 0
                            const savedScrollLeft = editor ? editor.scrollLeft : 0

                            console.log('[DEBUG] Saved positions:', { scrollTop: savedScrollTop, scrollLeft: savedScrollLeft })

                            // Trigger refresh from backend to get HTML with correct alignment
                            setTemplateNeedsUpdate(true)
                            skipTextUpdates = true // Skip individual text updates to avoid conflicts

                            // Restore scroll position after refresh
                            setTimeout(() => {
                              const editorAfter = document.getElementById('document-editor')
                              if (editorAfter) {
                                editorAfter.scrollTop = savedScrollTop
                                editorAfter.scrollLeft = savedScrollLeft
                                console.log('[DEBUG] Restored scroll position:', { scrollTop: editorAfter.scrollTop, scrollLeft: editorAfter.scrollLeft })
                              }
                            }, 100) // Wait for refresh to complete
                          }

                          // Get text from specific paragraph in cell
                          // Only process if we didn't just do a batch structure update
                          if (!skipTextUpdates) {
                            const originalText = getTextFromCellParagraph(editorHtml, cellBlockIndex, paraInCell)
                            const newText = getTextFromCellParagraph(newHtml, cellBlockIndex, paraInCell)

                            console.log('[DEBUG] Text comparison:', {
                              originalText,
                              newText,
                              changed: originalText !== newText
                            })

                            // Only trigger update if text actually changed
                            if (originalText !== newText && deletedFields.length === 0) {
                              console.log('[DEBUG] Calling debouncedUpdateTextInCell with:', {
                                cellBlockIndex,
                                paraInCell,
                                originalText,
                                newText
                              })
                              // For table cells, we need to use the cell's block index and para_in_cell
                              debouncedUpdateTextInCell(cellBlockIndex, paraInCell, originalText, newText)
                            } else {
                              console.log('[DEBUG] Skipping update - no change or placeholders deleted')
                            }
                          } else {
                            console.log('[DEBUG] Skipping text updates - batch structure update was done')
                          }
                        }
                      } else if (editedBlock) {
                        // Regular block editing (original logic)
                        const blockIndex = parseInt(editedBlock.getAttribute('data-block-index'))

                        // Validate blockIndex before proceeding
                        if (isNaN(blockIndex)) {
                          console.warn('Invalid blockIndex, skipping text update')
                          return
                        }

                        const originalText = getOriginalTextFromBlock(editorHtml, blockIndex)
                        const newText = getTextFromBlock(newHtml, blockIndex)

                        // Only trigger update if text actually changed (not just placeholder deletion)
                        if (originalText !== newText && deletedFields.length === 0) {
                          // Debounce to avoid excessive API calls
                          debouncedUpdateText(blockIndex, originalText, newText)
                        }
                      }
                    }

                    // Existing: Handle placeholder deletion
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

      {/* Format-only popup for text selection */}
      {showEditPopup && selectedTextForEdit && (
        <EditPopup
          selectedText={{
            ...selectedTextForEdit,
            onOpenHyperlink: handleOpenHyperlinkDialog
          }}
          onFormatApplied={handleFormatApplied}
          onClose={() => {
            setShowEditPopup(false)
            setSelectedTextForEdit(null)
          }}
        />
      )}

      {/* Add table popup */}
      {showAddTablePopup && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full shadow-xl">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-gray-900">📊 Thêm Bảng Mới</h3>
              <button
                onClick={() => setShowAddTablePopup(false)}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                ×
              </button>
            </div>

            <p className="text-sm text-gray-600 mb-4">
              Bảng sẽ được chèn tại vị trí cursor trong document
            </p>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Số hàng:
                </label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={tableSize.rows}
                  onChange={(e) => setTableSize({ ...tableSize, rows: parseInt(e.target.value) || 1 })}
                  className="w-full border border-gray-300 rounded px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Số cột:
                </label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={tableSize.cols}
                  onChange={(e) => setTableSize({ ...tableSize, cols: parseInt(e.target.value) || 1 })}
                  className="w-full border border-gray-300 rounded px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-4">
              <p className="text-sm text-blue-800">
                📐 Kích thước bảng: <strong>{tableSize.rows} × {tableSize.cols}</strong>
              </p>
              <p className="text-xs text-blue-600 mt-1">
                Click vào vị trí muốn thêm bảng trong document trước khi nhấn "Thêm bảng"
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handleAddTableAtCursor}
                className="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors font-medium"
              >
                📊 Thêm Bảng
              </button>
              <button
                onClick={() => setShowAddTablePopup(false)}
                className="bg-gray-200 text-gray-700 px-4 py-2 rounded hover:bg-gray-300 transition-colors font-medium"
              >
                Hủy
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add image popup */}
      {showAddImagePopup && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full shadow-xl">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-gray-900">📷 Thêm Ảnh</h3>
              <button
                onClick={() => {
                  setShowAddImagePopup(false)
                  setSelectedImageFile(null)
                  setImageWidth(4.0)
                }}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                ×
              </button>
            </div>

            <p className="text-sm text-gray-600 mb-4">
              Ảnh sẽ được chèn tại vị trí cursor trong document
            </p>

            {/* File upload */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Chọn ảnh:
              </label>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const file = e.target.files[0]
                  if (file) {
                    setSelectedImageFile(file)
                    console.log('[DEBUG] Selected image:', file.name, file.type, file.size)
                  }
                }}
                className="w-full border border-gray-300 rounded px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
              {selectedImageFile && (
                <div className="mt-2 text-sm text-gray-600">
                  Đã chọn: <strong>{selectedImageFile.name}</strong> ({(selectedImageFile.size / 1024).toFixed(1)} KB)
                </div>
              )}
            </div>

            {/* Width slider */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Chiều rộng ảnh: <strong>{imageWidth} inches</strong> (~{(imageWidth * 2.54).toFixed(1)} cm)
              </label>
              <input
                type="range"
                min="1.0"
                max="8.0"
                step="0.5"
                value={imageWidth}
                onChange={(e) => setImageWidth(parseFloat(e.target.value))}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>1" (2.5cm)</span>
                <span>4" (10cm)</span>
                <span>8" (20cm)</span>
              </div>
            </div>

            <div className="bg-orange-50 border border-orange-200 rounded p-3 mb-4">
              <p className="text-sm text-orange-800">
                📷 Kích thước: <strong>{imageWidth} inches</strong>
              </p>
              <p className="text-xs text-orange-600 mt-1">
                Click vào vị trí muốn thêm ảnh trong document trước khi nhấn "Thêm Ảnh"
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handleAddImageAtCursor}
                disabled={!selectedImageFile}
                className="flex-1 bg-orange-500 text-white px-4 py-2 rounded hover:bg-orange-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium"
              >
                📷 Thêm Ảnh
              </button>
              <button
                onClick={() => {
                  setShowAddImagePopup(false)
                  setSelectedImageFile(null)
                  setImageWidth(4.0)
                }}
                className="bg-gray-200 text-gray-700 px-4 py-2 rounded hover:bg-gray-300 transition-colors font-medium"
              >
                Hủy
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cell format dialog */}
      {showCellFormatDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 mb-4">🎨 Format Cell</h3>
            <p className="text-sm text-gray-600 mb-4">
              Ô đang chọn: [{selectedTableInfo.rowIndex}, {selectedTableInfo.colIndex}]
            </p>

            <div className="space-y-4">
              {/* Background color */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Màu nền:</label>
                <div className="flex gap-2 items-center">
                  <input
                    type="color"
                    value={cellFormatOptions.background_color}
                    onChange={(e) => setCellFormatOptions({...cellFormatOptions, background_color: e.target.value})}
                    className="h-10 w-20 border border-gray-300 rounded cursor-pointer"
                  />
                  <input
                    type="text"
                    value={cellFormatOptions.background_color}
                    onChange={(e) => setCellFormatOptions({...cellFormatOptions, background_color: e.target.value})}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm"
                    placeholder="#ffffff"
                  />
                </div>
              </div>

              {/* Alignment grid (3x3 = 9 options like Word) */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Căn lề (9 hướng như Word):</label>
                <div className="grid grid-cols-3 gap-2">
                  {/* Top row */}
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'left', vertical_align: 'top'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'top'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Trên-Trái"
                  >
                    ⬉ Top-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'center', vertical_align: 'top'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'top'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Trên-Giữa"
                  >
                    ⬆ Top-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'right', vertical_align: 'top'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'top'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Trên-Phải"
                  >
                    ⬈ Top-Right
                  </button>

                  {/* Middle row */}
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'left', vertical_align: 'center'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'center'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Giữa-Trái"
                  >
                    ⬅ Mid-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'center', vertical_align: 'center'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'center'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Giữa-Giữa"
                  >
                    ⌧ Mid-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'right', vertical_align: 'center'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'center'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Giữa-Phải"
                  >
                    ➡ Mid-Right
                  </button>

                  {/* Bottom row */}
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'left', vertical_align: 'bottom'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'bottom'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Dưới-Trái"
                  >
                    ⬋ Bot-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'center', vertical_align: 'bottom'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'bottom'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Dưới-Giữa"
                  >
                    ⬇ Bot-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({...cellFormatOptions, horizontal_align: 'right', vertical_align: 'bottom'})}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${
                      cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'bottom'
                        ? 'bg-indigo-500 text-white border-indigo-600'
                        : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                    }`}
                    title="Dưới-Phải"
                  >
                    ⬊ Bot-Right
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Hiện tại: {cellFormatOptions.vertical_align} - {cellFormatOptions.horizontal_align}
                </p>
              </div>

              {/* Buttons */}
              <div className="flex gap-2 pt-4">
                <button
                  onClick={handleFormatTableCell}
                  className="flex-1 px-4 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 font-medium"
                >
                  Áp Dụng
                </button>
                <button
                  onClick={() => {
                    setShowCellFormatDialog(false)
                    setCellFormatOptions({
                      background_color: '#ffffff',
                      vertical_align: 'top',
                      horizontal_align: 'left'
                    })
                  }}
                  className="flex-1 px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 font-medium"
                >
                  Hủy
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Hyperlink dialog */}
      {showHyperlinkDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 mb-4">🔗 Thêm Hyperlink</h3>
            <p className="text-sm text-gray-600 mb-4">
              Vị trí: Block {hyperlinkPosition.blockIndex}, Range [{hyperlinkPosition.startOffset}, {hyperlinkPosition.endOffset}]
            </p>

            {/* Selected text preview */}
            <div className="mb-4 p-3 bg-gray-50 rounded border border-gray-200">
              <p className="text-xs text-gray-500 mb-1">Văn bản đã chọn:</p>
              <p className="text-sm font-medium text-gray-800">"{hyperlinkPosition.selectedText}"</p>
            </div>

            <div className="space-y-4">
              {/* URL input */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">URL đích:</label>
                <input
                  type="url"
                  value={hyperlinkData.url}
                  onChange={(e) => setHyperlinkData({...hyperlinkData, url: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                  placeholder="https://example.com"
                  autoFocus
                />
              </div>

              {/* Action buttons */}
              <div className="flex gap-2 pt-4">
                <button
                  onClick={handleAddHyperlink}
                  className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
                >
                  Thêm Hyperlink
                </button>
                <button
                  onClick={() => {
                    setShowHyperlinkDialog(false)
                    setHyperlinkData({ url: '' })
                  }}
                  className="flex-1 px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 font-medium"
                >
                  Hủy
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
