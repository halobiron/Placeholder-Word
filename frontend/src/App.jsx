import { useState, useEffect, useMemo } from 'react'
import FileUpload from './components/FileUpload'
import EditPopup from './components/EditPopup'
import { mergeTemplate, getPreview, suggestPlaceholders, applySuggestions, addPlaceholderByPosition, addPlaceholderByOffset, suggestFieldName, editSelection, updateTextInTemplate, getSelectionFormat, addTableRow, deleteTableRow, addTableColumn, deleteTableColumn, formatTableCell, getCellFormat, addParagraph, deleteParagraph, addTableAtCursor, addImageAtCursor, addHyperlink, batchUpdate, downloadFile } from './api'

function App() {
  const [step, setStep] = useState('upload') // upload, preview, preview_result
  const [templateId, setTemplateId] = useState(null)
  const [editorHtml, setEditorHtml] = useState(null)
  const [fields, setFields] = useState([])
  const [lockedFields, setLockedFields] = useState([]) // Fields kept at their original placeholder state during merge
  const [selectedField, setSelectedField] = useState(null) // Field selected for keyboard shortcuts
  const [fieldValues, setFieldValues] = useState({}) // Direct value editing
  const [context, setContext] = useState('')
  const [resultId, setResultId] = useState(null)
  const [previewHtml, setPreviewHtml] = useState(null) // Preview of merged result
  const [merging, setMerging] = useState(false)
  const [error, setError] = useState(null)
  const [suggestions, setSuggestions] = useState([]) // AI suggestions for missing placeholders
  const [analyzing, setAnalyzing] = useState(false) // AI analysis in progress
  const [selectedSuggestions, setSelectedSuggestions] = useState([]) // Suggestions user wants to apply
  const [showAISuggestionPanel, setShowAISuggestionPanel] = useState(false) // Show AI suggestion list panel
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
    horizontal_align: 'left',
    borders: {
      top: { style: 'single', size: 4, color: '#000000' },
      bottom: { style: 'single', size: 4, color: '#000000' },
      left: { style: 'single', size: 4, color: '#000000' },
      right: { style: 'single', size: 4, color: '#000000' }
    }
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
  const [showPlaceholderDropdown, setShowPlaceholderDropdown] = useState(false)

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!showPlaceholderDropdown) return
    const handleClickOutside = (e) => {
      if (!e.target.closest('.placeholder-dropdown-container')) {
        setShowPlaceholderDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showPlaceholderDropdown])

  // Warning message for mid-paragraph clicks
  const [paragraphWarning, setParagraphWarning] = useState(null)

  const unlockedFields = useMemo(
    () => fields.filter((field) => !lockedFields.includes(field)),
    [fields, lockedFields]
  )

  const getNotificationTone = (message) => {
    if (!message) return 'default'
    if (message.startsWith('⚠️')) return 'warning'
    if (message.startsWith('💡') || message.startsWith('Đã chọn') || message.startsWith('⏳') || message.startsWith('ℹ️')) return 'info'
    if (message.startsWith('✅') || (message.startsWith('Đã ') && !message.startsWith('Đã chọn'))) return 'success'
    return 'error'
  }

  const getNotificationText = (message) => {
    if (!message) return message
    return message.replace(/^[✅⚠️💡⏳ℹ️❌]\s*/, '')
  }

  const getSuggestionKey = (suggestion) => {
    return [
      suggestion.block_index ?? 'na',
      suggestion.context ?? '',
      JSON.stringify(suggestion.before_context ?? []),
      JSON.stringify(suggestion.after_context ?? []),
      suggestion.insert_after ?? ''
    ].join('::')
  }

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

  useEffect(() => {
    setLockedFields((prev) => {
      const next = prev.filter((field) => fields.includes(field))
      if (next.length === prev.length && next.every((field, index) => field === prev[index])) {
        return prev
      }
      return next
    })
  }, [fields])

  useEffect(() => {
    if (selectedField && !fields.includes(selectedField)) {
      setSelectedField(null)
    }
  }, [fields, selectedField])

  useEffect(() => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    editor.querySelectorAll('.mail-merge-placeholder').forEach((span) => {
      const fieldName = span.getAttribute('data-field')
      const isSelected = fieldName === selectedField
      const isLocked = lockedFields.includes(fieldName)

      span.classList.toggle('is-selected', isSelected)
      span.classList.toggle('is-locked', isLocked)
    })
  }, [editorHtml, selectedField, lockedFields])

  // =============================================================================
  // BATCH UPDATE HELPER: Build operations from changes
  // =============================================================================

  /**
   * Smart helper to detect changes and build batch operations list
   *
   * Analyzes differences between old and new state to determine
   * what operations are needed. Handles:
   * - Placeholder operations: rename, delete
   * - Text operations: update text content
   * - Formatting operations: (can be added later)
   *
   * @param {string} oldHtml - Previous HTML content
   * @param {string} newHtml - New HTML content after user edits
   * @param {Array} oldFields - Previous placeholder fields
   * @param {Array} newFields - New placeholder fields
   * @param {Object} oldRenameMap - Previous rename mapping
   * @returns {Array} List of operations to execute via batchUpdate
   */
  const buildOperationsFromChanges = (
    oldHtml,
    newHtml,
    oldFields,
    newFields,
    options = {}
  ) => {
    const {
      includePlaceholderDeletes = true
    } = options
    const operations = []

    // =======================================================================
    // 1. DETECT PLACEHOLDER CHANGES
    // =======================================================================

    // Find deleted fields (fields in old but not in new)
    const deletedFields = oldFields.filter(f => !newFields.includes(f))

    // =======================================================================
    // 2. DETECT TEXT CHANGES
    // =======================================================================

    // Get all blocks from both HTMLs
    const tempOld = document.createElement('div')
    tempOld.innerHTML = oldHtml
    const oldBlocks = tempOld.querySelectorAll('[data-block-index]')

    const tempNew = document.createElement('div')
    tempNew.innerHTML = newHtml
    const newBlocks = tempNew.querySelectorAll('[data-block-index]')

    // Convert to arrays for easier manipulation
    const oldBlocksArray = Array.from(oldBlocks)
    const newBlocksArray = Array.from(newBlocks)

    // Find changed blocks
    const maxBlockIndex = Math.max(
      ...oldBlocksArray.map(b => parseInt(b.getAttribute('data-block-index'))),
      ...newBlocksArray.map(b => parseInt(b.getAttribute('data-block-index')))
    )

    for (let i = 0; i <= maxBlockIndex; i++) {
      const oldBlock = oldBlocksArray.find(b => parseInt(b.getAttribute('data-block-index')) === i)
      const newBlock = newBlocksArray.find(b => parseInt(b.getAttribute('data-block-index')) === i)

      if (!oldBlock && !newBlock) continue

      const oldText = oldBlock ? getOriginalTextFromBlock(oldHtml, i) : ''
      const newText = newBlock ? getOriginalTextFromBlock(newHtml, i) : ''

      // Skip if text hasn't changed (and not just whitespace)
      if (oldText.trim() === newText.trim() && oldText.replace(/\s/g, ' ') === newText.replace(/\s/g, ' ')) {
        continue
      }

      // Check if there are placeholders in this block that were deleted.
      // Add text update operation when text actually changed.
      // Placeholder deletions are appended after text updates so the backend
      // can still resolve the paragraph text before the field is removed.
      if (oldText !== newText) {
        operations.push({
          type: 'update_text',
          block_index: i,
          old_text: oldText,
          new_text: newText
        })
      }
    }

    // Add delete operations for deleted placeholders after text updates.
    if (includePlaceholderDeletes) {
      deletedFields.forEach(fieldName => {
        operations.push({
          type: 'delete_placeholder',
          field_name: fieldName
        })
      })
    }

    return operations
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

  // Helper: Get selection context when selection stays within a single editable block
  const getSingleBlockSelectionContext = (range) => {
    const getElement = (node) => (node?.nodeType === Node.TEXT_NODE ? node.parentElement : node)

    const startElement = getElement(range.startContainer)
    const endElement = getElement(range.endContainer)
    const startBlock = startElement?.closest('[data-block-index], .cell-paragraph')
    const endBlock = endElement?.closest('[data-block-index], .cell-paragraph')

    if (!startBlock || !endBlock || startBlock !== endBlock) {
      return null
    }

    if (startBlock.classList.contains('cell-paragraph')) {
      const cellBlock = startBlock.closest('[data-block-index]')
      if (!cellBlock) return null

      return {
        targetElement: startBlock,
        blockIndex: parseInt(cellBlock.getAttribute('data-block-index')),
        paraInCell: parseInt(startBlock.getAttribute('data-para-in-cell')),
        tableIndex: parseInt(cellBlock.getAttribute('data-table-index') || '0'),
        rowIndex: parseInt(cellBlock.getAttribute('data-row')),
        colIndex: parseInt(cellBlock.getAttribute('data-col'))
      }
    }

    return {
      targetElement: startBlock,
      blockIndex: parseInt(startBlock.getAttribute('data-block-index'))
    }
  }

  // Helper: Calculate selection offsets within a block using the rendered text,
  // including placeholder labels because backend offsets count «field_name».
  const calculateSelectionOffsets = (range, targetElement) => {
    try {
      const startRange = document.createRange()
      startRange.selectNodeContents(targetElement)
      startRange.setEnd(range.startContainer, range.startOffset)

      const endRange = document.createRange()
      endRange.selectNodeContents(targetElement)
      endRange.setEnd(range.endContainer, range.endOffset)

      return {
        startOffset: startRange.toString().length,
        endOffset: endRange.toString().length
      }
    } catch (error) {
      console.error('[DELETE RANGE] Failed to calculate selection offsets:', error)
      return null
    }
  }

  // Helper: Detect whether a selection touches any placeholder span in the target block.
  const selectionTouchesPlaceholder = (range, targetElement) => {
    const placeholders = targetElement?.querySelectorAll('.mail-merge-placeholder') || []
    return Array.from(placeholders).some((placeholder) => {
      try {
        return range.intersectsNode(placeholder)
      } catch (error) {
        console.warn('[DELETE RANGE] intersectsNode failed for placeholder:', error)
        return false
      }
    })
  }

  // Helper: place caret by rendered text offset across the whole block,
  // treating placeholders as atomic non-editable nodes.
  const setCaretAtRenderedOffset = (targetBlock, desiredOffset) => {
    const range = document.createRange()
    const selection = window.getSelection()
    let currentOffset = 0

    const placeAtNodeBoundary = (node, position) => {
      if (position === 'before') {
        range.setStartBefore(node)
      } else {
        range.setStartAfter(node)
      }
      range.collapse(true)
      return true
    }

    const walkNode = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const textLength = node.textContent?.length || 0
        if (desiredOffset <= currentOffset + textLength) {
          range.setStart(node, Math.max(0, Math.min(desiredOffset - currentOffset, textLength)))
          range.collapse(true)
          return true
        }
        currentOffset += textLength
        return false
      }

      if (node.nodeType !== Node.ELEMENT_NODE) {
        return false
      }

      const isAtomicPlaceholder = node.classList?.contains('mail-merge-placeholder') ||
        node.getAttribute?.('contenteditable') === 'false'

      if (isAtomicPlaceholder) {
        const atomicLength = node.textContent?.length || 0

        if (desiredOffset <= currentOffset) {
          return placeAtNodeBoundary(node, 'before')
        }

        if (desiredOffset < currentOffset + atomicLength) {
          const relativeOffset = desiredOffset - currentOffset
          const snapAfter = relativeOffset >= atomicLength / 2
          return placeAtNodeBoundary(node, snapAfter ? 'after' : 'before')
        }

        if (desiredOffset === currentOffset + atomicLength) {
          return placeAtNodeBoundary(node, 'after')
        }

        currentOffset += atomicLength
        return false
      }

      for (const child of node.childNodes) {
        if (walkNode(child)) {
          return true
        }
      }

      return false
    }

    for (const child of targetBlock.childNodes) {
      if (walkNode(child)) {
        selection.removeAllRanges()
        selection.addRange(range)
        return true
      }
    }

    range.selectNodeContents(targetBlock)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
    return false
  }

  const getCursorTargetSelector = ({ blockIndex, paraInCell, tableIndex, rowIndex, colIndex }) => {
    if (tableIndex !== undefined && rowIndex !== undefined && colIndex !== undefined) {
      return `[data-block-index="${blockIndex}"] .cell-paragraph[data-para-in-cell="${paraInCell || 0}"]`
    }

    return `[data-block-index="${blockIndex}"]`
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

  // Helper: Detect cursor position within paragraph (start, middle, end)
  const getCursorPositionInParagraph = (range, blockElement) => {
    try {
      const plainText = blockElement.textContent.replace(/«[^»]+»/g, '') // Remove placeholders
      const plainTextTrimmed = plainText.trim()

      // Empty paragraph
      if (plainTextTrimmed.length === 0) {
        return 'empty'
      }

      // Calculate cursor offset in plain text
      const preCaretRange = range.cloneRange()
      preCaretRange.selectNodeContents(blockElement)
      preCaretRange.setEnd(range.startContainer, range.startOffset)
      const textBeforeCaret = preCaretRange.toString().replace(/«[^»]+»/g, '')
      const cursorOffset = textBeforeCaret.length

      // Check positions
      const isAtStart = cursorOffset === 0 || (textBeforeCaret.trim().length === 0 && cursorOffset > 0)
      const isAtEnd = cursorOffset >= plainTextTrimmed.length

      if (isAtStart) return 'start'
      if (isAtEnd) return 'end'
      return 'middle'
    } catch (error) {
      console.error('[ERROR] getCursorPositionInParagraph failed:', error)
      return 'unknown'
    }
  }

  // CRITICAL FIX: Helper function to update HTML while preserving scroll position and cursor
  // This SOLVES the systemic issue of scroll jumping after HTML updates
  const updateEditorHtmlWithPreservation = (newHtml, newFields, cursorTarget = null) => {
    const editor = document.getElementById('document-editor')

    // Save scroll position BEFORE HTML update
    const savedScrollTop = editor?.scrollTop || 0
    const savedScrollLeft = editor?.scrollLeft || 0

    console.log('[DEBUG] updateEditorHtmlWithPreservation - Saving scroll:', {
      scrollTop: savedScrollTop,
      scrollLeft: savedScrollLeft,
      cursorTarget
    })

    // Update HTML
    setEditorHtml(newHtml)
    setFields(newFields)

    // Restore scroll position and set cursor AFTER DOM update
    setTimeout(() => {
      const updatedEditor = document.getElementById('document-editor')
      if (!updatedEditor) {
        console.warn('[DEBUG] Editor not found after update')
        return
      }

      // Restore scroll position
      updatedEditor.scrollTop = savedScrollTop
      updatedEditor.scrollLeft = savedScrollLeft

      console.log('[DEBUG] Restored scroll position:', {
        scrollTop: updatedEditor.scrollTop,
        scrollLeft: updatedEditor.scrollLeft
      })

      // Set cursor to target if provided
      if (cursorTarget) {
        try {
          const { blockIndex, paraInCell, offset } = cursorTarget
          const targetSelector = getCursorTargetSelector(cursorTarget)
          const targetBlock = updatedEditor.querySelector(targetSelector)

          if (targetBlock) {
            const resolvedOffset = offset !== undefined ? Math.max(0, offset) : 0
            const placedInsideFlow = setCaretAtRenderedOffset(targetBlock, resolvedOffset)

            console.log('[DEBUG] Cursor set to:', {
              selector: targetSelector,
              blockIndex,
              paraInCell,
              offset: resolvedOffset,
              placedInsideFlow
            })
          } else {
            console.warn('[DEBUG] Could not find target block:', targetSelector)
          }
        } catch (error) {
          console.error('[DEBUG] Failed to set cursor:', error)
        }
      }
    }, 0)  // Run in next tick after DOM update
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
            await updateTextInTemplate(templateId, {
              blockIndex: cellBlockIndex,
              oldText: oldText,
              newText: newText,
              paraInCell
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

  // Attach click handlers to placeholders and table cells after preview refresh.
  useEffect(() => {
    const editor = document.getElementById('document-editor')
    if (!editor || !editorHtml) return

    // Add click handlers for table cells
    // In NORMAL mode: enable table editing toolbar (cell-level selection)
    // In ADD mode: DISABLE to allow cell-paragraph handlers with offset calculation

    // IMPORTANT: Clean up ALL previous cell-level event listeners first
    const tableCells = editor.querySelectorAll('[data-block-index][data-type="table_cell"]')
    tableCells.forEach(element => {
      // Clone node to remove ALL event listeners (both capture and bubble)
      const newElement = element.cloneNode(true)
      element.parentNode.replaceChild(newElement, element)
    })

    // Re-select after cloning (original elements are gone)
    const freshTableCells = editor.querySelectorAll('[data-block-index][data-type="table_cell"]')

    if (!isAddMode) {
      console.log(`[Table Debug] Found ${freshTableCells.length} table cells (normal mode)`)
      freshTableCells.forEach(element => {
        element.style.cursor = 'crosshair'

        // Use capture phase to override paragraph handlers
        element.addEventListener('click', (e) => {
          const placeholderTarget = e.target?.closest?.('.mail-merge-placeholder')
          if (placeholderTarget) {
            return
          }

          console.log(`[Table Debug] Cell click event captured (normal mode)`)

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

            setError(`Đã chọn ô [${row},${col}]. Dùng công cụ bảng để chỉnh sửa.`)
          }
        }, true) // Use capture phase
      })
    } else {
      console.log(`[Table Debug] Add mode - cell-level handlers DISABLED, using cell-paragraph handlers with offset`)
    }

    // Placeholder handlers must be attached after table-cell cloning above,
    // otherwise placeholders inside table cells lose their listeners.
    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      span.onclick = null
      span.ondblclick = null
    })

    // Single click selects the placeholder.
    // Double click keeps rename available without conflicting with the shortcut.
    editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
      const fieldName = span.getAttribute('data-field')
      span.onclick = (e) => {
        e.preventDefault()
        e.stopPropagation()

        if (isAddMode) {
          setError('Thoát chế độ thêm placeholder trước khi đổi tên')
          setTimeout(() => setError(null), 2000)
          return
        }

        setSelectedField(fieldName)
        setError(`Đã chọn «${fieldName}». Double click để đổi tên, Ctrl+Shift+L để khóa.`)
        setTimeout(() => setError(null), 1500)
      }

      span.ondblclick = (e) => {
        e.preventDefault()
        e.stopPropagation()

        if (isAddMode) {
          setError('Thoát chế độ thêm placeholder trước khi đổi tên')
          setTimeout(() => setError(null), 2000)
          return
        }

        const newName = prompt('Đổi tên placeholder:', fieldName)
        if (newName?.trim() && newName.trim() !== fieldName) {
          renameField(span, fieldName, newName.trim())
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

            // Clean up whitespace and check if empty
            const cleanedText = textWithoutPlaceholders.trim()

            // If paragraph is effectively empty (only whitespace), use offset 0
            if (cleanedText.length === 0) {
              offset = 0
              console.log('[DEBUG] Empty paragraph detected, forcing offset=0')
            } else {
              offset = textWithoutPlaceholders.length
            }

            console.log('[DEBUG] Click offset:', {
              blockIndex,
              offset,
              textBeforeCaret: textBeforeCaret.substring(0, 50) + '...',
              textWithoutPlaceholders: textWithoutPlaceholders.substring(0, 50) + '...',
              cleanedText: cleanedText.substring(0, 50) + '...'
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

      // Handle paragraph-level clicks within table cells (for offset-based insertion)
      const cellParagraphs = editor.querySelectorAll('.cell-paragraph')
      console.log(`[DEBUG] Found ${cellParagraphs.length} cell-paragraph elements in add mode`)
      cellParagraphs.forEach(element => {
        element.style.cursor = 'crosshair'
        element.onclick = (e) => {
          e.preventDefault()
          e.stopPropagation()

          const cellBlockIndex = parseInt(element.getAttribute('data-cell-block-index'))
          const paraInCell = parseInt(element.getAttribute('data-para-in-cell'))

          console.log(`[DEBUG] Cell-paragraph clicked: blockIndex=${cellBlockIndex}, paraInCell=${paraInCell}`)

          // Find parent cell to get table context
          const parentCell = element.closest('[data-type="table_cell"]')
          let tableIndex = null
          let rowIndex = null
          let colIndex = null

          if (parentCell) {
            tableIndex = parseInt(parentCell.getAttribute('data-table-index') || '0')
            rowIndex = parseInt(parentCell.getAttribute('data-row') || '0')
            colIndex = parseInt(parentCell.getAttribute('data-col') || '0')
            console.log(`[DEBUG] Parent cell context: table=${tableIndex}, row=${rowIndex}, col=${colIndex}`)
          }

          setSelectedBlockIndex(cellBlockIndex) // Each cell has its own block_index
          setSelectedCellIndex(colIndex) // Store column index for display
          setSelectedTableBlockIndex(tableIndex) // Store table index for display
          setSelectedParaInCell(paraInCell) // Set paragraph index within cell

          // Set table editing info
          setSelectedTableInfo({
            tableIndex: tableIndex,
            rowIndex: rowIndex,
            colIndex: colIndex,
            isCellSelected: false // Not selecting the whole cell, just a paragraph
          })

          // Calculate caret offset for precise insertion
          const selection = window.getSelection()
          let offset = null

          if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0)

            // Calculate offset within the paragraph, excluding placeholder characters
            const preCaretRange = range.cloneRange()
            preCaretRange.selectNodeContents(element)
            preCaretRange.setEnd(range.startContainer, range.startOffset)
            const textBeforeCaret = preCaretRange.toString()

            // Remove placeholder characters («field_name») from offset calculation
            const textWithoutPlaceholders = textBeforeCaret.replace(/«[^»]+»/g, '')

            // Clean up whitespace and check if empty
            const cleanedText = textWithoutPlaceholders.trim()

            // If paragraph is effectively empty (only whitespace), use offset 0
            if (cleanedText.length === 0) {
              offset = 0
              console.log('[DEBUG] Empty paragraph detected, forcing offset=0')
            } else {
              offset = textWithoutPlaceholders.length
            }

            console.log('[DEBUG] Cell paragraph click offset:', {
              cellBlockIndex,
              paraInCell,
              offset,
              textBeforeCaret: textBeforeCaret.substring(0, 50) + '...',
              textWithoutPlaceholders: textWithoutPlaceholders.substring(0, 50) + '...',
              cleanedText: cleanedText.substring(0, 50) + '...'
            })
          }

          setCaretOffset(offset) // Store caret offset for precise insertion

          // Highlight selected paragraph
          editor.querySelectorAll('[data-block-index], [data-cell-index], .cell-paragraph').forEach(el => {
            el.style.outline = ''
          })
          element.style.outline = '2px solid #8b5cf6'

          const offsetMsg = offset !== null ? ` (vị trí ký tự #${offset})` : ''
          const cellInfo = (tableIndex !== null && rowIndex !== null && colIndex !== null)
            ? ` trong ô [${rowIndex},${colIndex}]`
            : ''
          setError(`Đã chọn dòng #${paraInCell}${cellInfo}${offsetMsg}. Nhập tên placeholder và nhấn "Thêm".`)
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

      // Auto-scroll sidebar to top to show the form
      const sidebar = document.getElementById('right-sidebar-container')
      if (sidebar) {
        sidebar.scrollTo({ top: 0, behavior: 'smooth' })
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

  // Keyboard shortcut: Ctrl+Shift+L toggles lock for the selected placeholder
  useEffect(() => {
    const handleKeyDown = (e) => {
      const isToggleLock = (e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'l'
      if (!isToggleLock) return

      const currentField = selectedField
      const wasLocked = currentField ? lockedFields.includes(currentField) : false

      if (currentField) {
        toggleFieldLock(currentField)
        e.preventDefault()
        e.stopPropagation()
        setError(`Đã ${wasLocked ? 'mở khóa' : 'khóa'} «${currentField}»`)
        setTimeout(() => setError(null), 1500)
      }
    }

    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [selectedField, lockedFields])

  // Rename placeholder using Batch Update API
  const renameField = async (targetSpan, oldName, newName) => {
    const editor = document.getElementById('document-editor')
    if (!editor || !targetSpan) return

    // Store current state for rollback
    const oldHtml = editorHtml
    const oldFields = extractFields(editor.innerHTML)
    const oldLockedFields = [...lockedFields]
    const placeholdersWithSameName = Array.from(
      editor.querySelectorAll(`.mail-merge-placeholder[data-field="${oldName}"]`)
    )
    const occurrenceIndex = placeholdersWithSameName.indexOf(targetSpan)

    if (occurrenceIndex === -1) {
      setError('⚠️ Không xác định được placeholder cần đổi tên')
      setTimeout(() => setError(null), 3000)
      return
    }

    // Update UI immediately
    targetSpan.setAttribute('data-field', newName)
    targetSpan.textContent = `«${newName}»`

    const newHtml = editor.innerHTML
    setEditorHtml(newHtml)

    try {
      // Use batchUpdate for rename operation
      const operations = [
        {
          type: 'rename_placeholder',
          old_name: oldName,
          new_name: newName,
          occurrence_index: occurrenceIndex
        }
      ]

      const result = await batchUpdate(templateId, operations, false, true)

      // Update state from backend response
      setFields(result.fields || extractFields(newHtml))
      setSelectedField(newName)
      setLockedFields((prev) => (
        prev.includes(oldName) && !prev.includes(newName)
          ? [...prev, newName]
          : prev
      ))
      setError(`✅ Đã đổi tên «${oldName}» → «${newName}»`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Rename failed:', err)
      setError('⚠️ Đổi tên thất bại: ' + (err.response?.data?.detail || err.message))

      // Rollback UI on failure
      targetSpan.setAttribute('data-field', oldName)
      targetSpan.textContent = `«${oldName}»`
      setEditorHtml(oldHtml)
      setFields(oldFields)
      setSelectedField((prev) => (prev === newName ? oldName : prev))
      setLockedFields(oldLockedFields)

      setTimeout(() => setError(null), 3000)
    }
  }

  // Delete placeholder using Batch Update API
  const deleteField = async (fieldName) => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    // Store current state for rollback
    const oldHtml = editorHtml
    const oldFields = [...fields]
    const oldLockedFields = [...lockedFields]

    try {
      // Replace each matching span with its original text
      const placeholders = editor.querySelectorAll(`.mail-merge-placeholder[data-field="${fieldName}"]`)

      placeholders.forEach(span => {
        const originalText = span.getAttribute('data-original') || ''
        span.outerHTML = originalText
      })

      const newHtml = editor.innerHTML
      const newFields = extractFields(newHtml)

      // Build operations list using batch update helper
      const operations = buildOperationsFromChanges(oldHtml, newHtml, oldFields, newFields)

      if (operations.length === 0) return

      // Execute batch update
      const result = await batchUpdate(templateId, operations, false, true)

      if (result.success) {
        // Update local state after successful server update
        updateEditorHtmlWithPreservation(result.html_preview, result.fields)
        setSelectedField((prev) => (prev === fieldName ? null : prev))
        setLockedFields((prev) => prev.filter((field) => field !== fieldName))
        setError(`✅ Đã xóa «${fieldName}»`)
        setTimeout(() => setError(null), 2000)
      } else {
        throw new Error(result.message || 'Batch update failed')
      }

    } catch (err) {
      console.error('Deletion failed:', err)
      setError('⚠️ Xóa placeholder thất bại: ' + (err.response?.data?.detail || err.message))

      // Rollback UI changes
      updateEditorHtmlWithPreservation(oldHtml, oldFields)
      setSelectedField((prev) => (prev === fieldName ? null : prev))
      setLockedFields(oldLockedFields)

      setTimeout(() => setError(null), 3000)
    }
  }

  // Handle upload complete
  const handleUploadComplete = (data) => {
    setTemplateId(data.templateId)
    setEditorHtml(data.previewHtml)
    setFields(data.fields)
    setLockedFields([])
    setSelectedField(null)
    setStep('preview')
  }

  const toggleFieldLock = (fieldName) => {
    setLockedFields((prev) =>
      prev.includes(fieldName)
        ? prev.filter((field) => field !== fieldName)
        : [...prev, fieldName]
    )
  }

  const lockAllFields = () => {
    setLockedFields([...fields])
  }

  const unlockAllFields = () => {
    setLockedFields([])
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
      // Use direct values if available, otherwise use context
      const data = hasDirectValues ? fieldValues : context
      const activeFields = hasDirectValues ? null : unlockedFields
      const result = await mergeTemplate(
        templateId,
        data,
        hasDirectValues,
        activeFields,
        lockedFields
      )
      setResultId(result.result_id)

      // Fetch preview
      try {
        const previewData = await getPreview(result.result_id)
        setPreviewHtml(previewData.html_preview)
        setStep('preview_result')
      } catch (previewErr) {
        console.warn('Preview fetch failed, downloading directly:', previewErr)
        downloadFile(result.result_id)
        setError('✅ Xử lý thành công! Đang tải xuống...')
        setTimeout(() => {
          handleReset()
        }, 2000)
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

    setShowAISuggestionPanel(true)
    setAnalyzing(true)
    setError(null)
    setSuggestions([])
    setSelectedSuggestions([])
    setEditedSuggestions({})

    try {
      const result = await suggestPlaceholders(templateId)
      setSuggestions(result.suggestions || [])
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
        const uniqueId = s.sourceKey || getSuggestionKey(s)
        const edits = editedSuggestions[uniqueId]
        return {
          ...s,
          suggested_name: edits?.suggested_name || s.suggested_name,
          position: edits?.position || s.position
        }
      })

      const result = await applySuggestions(templateId, editedSuggestionsToApply)

      // Update editor with result from applySuggestions (no extra API call needed)
      setEditorHtml(result.html_preview)
      setFields(result.updated_fields)

      // Clear suggestions and edits after successful apply
      setSuggestions([])
      setSelectedSuggestions([])
      setEditedSuggestions({})
      setShowAISuggestionPanel(false)

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
    const uniqueId = getSuggestionKey(suggestion)
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
    const uniqueId = getSuggestionKey(suggestion)
    const edits = editedSuggestions[uniqueId]
    return {
      ...suggestion,
      suggested_name: edits?.suggested_name || suggestion.suggested_name,
      position: edits?.position || suggestion.position,
      sourceKey: uniqueId
    }
  }

  // Toggle suggestion selection
  const toggleSuggestion = (suggestion) => {
    const uniqueId = getSuggestionKey(suggestion)
    const editedSuggestion = getEditedSuggestion(suggestion)

    const index = selectedSuggestions.findIndex(s =>
      (s.sourceKey || getSuggestionKey(s)) === uniqueId
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

    console.log('[DEBUG] handleAddPlaceholder called:', {
      templateId,
      selectedBlockIndex,
      selectedParaInCell,
      caretOffset,
      newFieldName: newFieldName.trim()
    })

    try {
      let result

      // Use caret offset if available (precise insertion at click position)
      if (caretOffset !== null) {
        console.log('[DEBUG] Using caret offset for insertion:', {
          blockIndex: selectedBlockIndex,
          offset: caretOffset,
          fieldName: newFieldName.trim(),
          paraInCell: selectedParaInCell
        })
        result = await addPlaceholderByOffset(
          templateId,
          selectedBlockIndex,
          caretOffset,
          newFieldName.trim(),
          true, // inherit format
          selectedParaInCell // Pass para_in_cell for table cell paragraphs
        )
      } else {
        // Fallback to old method (left/right/new_line)
        console.log('[DEBUG] FALLBACK to position-based insertion:', {
          blockIndex: selectedBlockIndex,
          position: newFieldPosition,
          paraInCell: selectedParaInCell,
          reason: 'caretOffset is null'
        })
        result = await addPlaceholderByPosition(
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
      setFields(result.fields || result.updated_fields || [])

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
      setError(`✅ Đã thêm placeholder thành công!`)
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
    setSuggestions([])
    setSelectedSuggestions([])
    setShowAISuggestionPanel(false)
    setEditedSuggestions({}) // Clear suggestion edits
    setShowEditPopup(false)
    setSelectedTextForEdit(null)
    setCopiedFormat(null) // Clear copied format
  }

  // Handle text selection for editing
  const handleTextSelection = async () => {
    const selection = window.getSelection()
    const selectedText = selection.toString().trim()

    // Show format popup for any text selection (including text with placeholders)
    if (selectedText && !isAddMode) {
      // Get the element containing the selection
      // Handle both text nodes and element nodes
      let element = selection.anchorNode
      if (element.nodeType === Node.TEXT_NODE) {
        element = element.parentElement
      }

      // Find block_index from parent elements
      let blockIndex = null
      let currentElement = element
      let blockElement = null

      // Walk up the DOM tree to find data-block-index
      while (currentElement && currentElement.id !== 'document-editor') {
        // Check if element has data-block-index attribute
        if (currentElement instanceof Element && currentElement.hasAttribute('data-block-index')) {
          blockIndex = parseInt(currentElement.getAttribute('data-block-index'))
          blockElement = currentElement
          break
        }
        currentElement = currentElement.parentElement
      }

      // If still not found, try looking for data-cell-block-index (for table cells)
      if (blockIndex === null) {
        currentElement = element
        while (currentElement && currentElement.id !== 'document-editor') {
          if (currentElement instanceof Element && currentElement.hasAttribute('data-cell-block-index')) {
            blockIndex = parseInt(currentElement.getAttribute('data-cell-block-index'))
            blockElement = currentElement
            break
          }
          currentElement = currentElement.parentElement
        }
      }

      // If still not found, log error and don't show popup
      if (blockIndex === null) {
        console.warn('[handleTextSelection] Could not find block-index for selection:', {
          selectedText,
          element: element.outerHTML || element.textContent
        })
        return
      }

      // CRITICAL FIX: For table cells, calculate offset relative to the paragraph, not the cell
      // This fixes bug where duplicate words in table cells always format the first occurrence
      let offset = 0
      let endOffset = 0
      let paraInCell = null  // Track paragraph index within table cell

      if (blockElement) {
        const range = selection.getRangeAt(0)

        // Check if we're in a table cell (blockElement is a td/th)
        const isTableCell = blockElement.tagName === 'TD' || blockElement.tagName === 'TH'

        if (isTableCell) {
          // Find the specific paragraph containing the selection
          let paraElement = element
          while (paraElement && paraElement !== blockElement) {
            if (paraElement.tagName === 'P' && blockElement.contains(paraElement)) {
              break
            }
            paraElement = paraElement.parentElement
          }

          // Calculate paragraph index within the cell
          if (paraElement && paraElement.tagName === 'P') {
            const paras = Array.from(blockElement.querySelectorAll('p'))
            paraInCell = paras.indexOf(paraElement)

            console.log(`[DEBUG] Table cell: paraInCell=${paraInCell}, total paragraphs=${paras.length}`)

            // Calculate offset relative to this paragraph, not the entire cell
            if (paraInCell >= 0) {
              const preSelectionRange = range.cloneRange()
              preSelectionRange.selectNodeContents(paraElement)
              preSelectionRange.setEnd(range.startContainer, range.startOffset)
              offset = preSelectionRange.toString().length

              const postSelectionRange = range.cloneRange()
              postSelectionRange.selectNodeContents(paraElement)
              postSelectionRange.setEnd(range.endContainer, range.endOffset)
              endOffset = postSelectionRange.toString().length

              console.log(`[DEBUG] Calculated offset relative to paragraph: offset=${offset}, endOffset=${endOffset}`)
            } else {
              // Fallback to cell-level calculation
              const preSelectionRange = range.cloneRange()
              preSelectionRange.selectNodeContents(blockElement)
              preSelectionRange.setEnd(range.startContainer, range.startOffset)
              offset = preSelectionRange.toString().length

              const postSelectionRange = range.cloneRange()
              postSelectionRange.selectNodeContents(blockElement)
              postSelectionRange.setEnd(range.endContainer, range.endOffset)
              endOffset = postSelectionRange.toString().length

              console.log(`[DEBUG] Could not find paragraph, using cell-level offset: offset=${offset}, endOffset=${endOffset}`)
            }
          } else {
            // Fallback to cell-level calculation
            const preSelectionRange = range.cloneRange()
            preSelectionRange.selectNodeContents(blockElement)
            preSelectionRange.setEnd(range.startContainer, range.startOffset)
            offset = preSelectionRange.toString().length

            const postSelectionRange = range.cloneRange()
            postSelectionRange.selectNodeContents(blockElement)
            postSelectionRange.setEnd(range.endContainer, range.endOffset)
            endOffset = postSelectionRange.toString().length

            console.log(`[DEBUG] Not in a paragraph, using cell-level offset: offset=${offset}, endOffset=${endOffset}`)
          }
        } else {
          // Regular paragraph (not in table)
          // Get text before selection in the block
          const preSelectionRange = range.cloneRange()
          preSelectionRange.selectNodeContents(blockElement)
          preSelectionRange.setEnd(range.startContainer, range.startOffset)
          offset = preSelectionRange.toString().length

          // Get text before end of selection
          const postSelectionRange = range.cloneRange()
          postSelectionRange.selectNodeContents(blockElement)
          postSelectionRange.setEnd(range.endContainer, range.endOffset)
          endOffset = postSelectionRange.toString().length

          console.log(`[DEBUG] Regular paragraph, offset=${offset}, endOffset=${endOffset}`)
        }
      }

      // Get format from backend (extracted from DOCX, always returns hex colors)
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

      if (templateId) {
        try {
          // CRITICAL FIX: Pass offset information for precise format detection
          // This fixes bug where duplicate words always get format from first occurrence
          const response = await getSelectionFormat(templateId, selectedText, blockIndex, offset, endOffset, paraInCell)
          if (response?.format) {
            format = response.format
          }
        } catch (error) {
          console.error('Failed to get selection format from backend:', error)
          // Keep default format if backend fails
        }
      }

      setSelectedTextForEdit({
        text: selectedText,
        element: element,
        format: format,
        blockIndex: blockIndex,
        offset: offset,
        endOffset: endOffset,
        paraInCell: paraInCell  // Include paragraph index within table cell
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

  const handleAddPageBreak = async () => {
    if (!templateId) return

    try {
      // Get current cursor position
      const selection = window.getSelection()
      if (!selection.rangeCount) {
        setError('❌ Đặt cursor vào vị trí muốn ngắt trang trước!')
        setTimeout(() => setError(null), 3000)
        return
      }

      const range = selection.getRangeAt(0)
      const blockIndex = getCurrentBlockIndex()
      if (blockIndex === null) {
        setError('❌ Đặt cursor vào vị trí muốn ngắt trang trước!')
        setTimeout(() => setError(null), 3000)
        return
      }

      // Calculate offset within block (excluding placeholders)
      const offset = calculateCursorOffset(range, blockIndex)
      if (offset === null) {
        setError('❌ Không thể xác định vị trí cursor!')
        setTimeout(() => setError(null), 3000)
        return
      }

      // Call batch-update API with add_page_break operation
      const response = await fetch(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/batch-update`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          template_id: templateId,
          operations: [
            {
              type: 'add_page_break',
              block_index: blockIndex,
              offset: offset
            }
          ]
        })
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to add page break')
      }

      const result = await response.json()

      // Update UI
      setEditorHtml(result.html_preview)
      setFields(result.fields)

      // Show success message
      setError('✅ Đã thêm ngắt trang tại vị trí cursor!')
      setTimeout(() => setError(null), 3000)
    } catch (err) {
      console.error('Add page break failed:', err)
      setError('Thêm ngắt trang thất bại: ' + (err.message || err.response?.data?.detail))
      setTimeout(() => setError(null), 3000)
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

      updateEditorHtmlWithPreservation(result.html_preview, result.fields)  // ✅ Uses helper

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

      updateEditorHtmlWithPreservation(result.html_preview, result.fields)  // ✅ Uses helper

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

  const handleOpenCellFormatDialog = async () => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, rowIndex, colIndex } = selectedTableInfo

      // Load current cell format from backend
      const response = await getCellFormat(templateId, tableIndex, rowIndex, colIndex)

      if (response && response.format) {
        setCellFormatOptions(response.format)
      }

      setShowCellFormatDialog(true)
    } catch (err) {
      console.error('Load cell format failed:', err)
      // Use default values if loading fails
      setShowCellFormatDialog(true)
    }
  }

  const handleFormatTableCell = async () => {
    if (!selectedTableInfo.isCellSelected) return

    try {
      const { tableIndex, rowIndex, colIndex } = selectedTableInfo
      const result = await formatTableCell(templateId, tableIndex, rowIndex, colIndex, cellFormatOptions)

      setEditorHtml(result.html_preview)
      setFields(result.fields)

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

      setShowHyperlinkDialog(false)
      setHyperlinkData({ url: '' })
      setError(`✅ Đã thêm hyperlink vào "${hyperlinkPosition.selectedText}"!`)
      setTimeout(() => setError(null), 2000)
    } catch (err) {
      console.error('Add hyperlink failed:', err)
      setError('Thêm hyperlink thất bại: ' + (err.response?.data?.detail || err.message))
    }
  }

  // =============================================================================
  // UI COMPONENTS (INTERNAL)
  // =============================================================================

  const NotificationArea = () => {
    if (!error && !paragraphWarning) return null
    return (
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-md animate-in fade-in slide-in-from-top-4 duration-300">
        {error && (
          <div className={`p-4 rounded-2xl shadow-xl border flex items-center gap-3 backdrop-blur-md ${getNotificationTone(error) === 'success' ? 'bg-emerald-50/90 border-emerald-100 text-emerald-800' :
            getNotificationTone(error) === 'warning' ? 'bg-amber-50/90 border-amber-100 text-amber-800' :
              getNotificationTone(error) === 'info' ? 'bg-indigo-50/90 border-indigo-100 text-indigo-800 shadow-indigo-100/50' :
                'bg-rose-50/90 border-rose-100 text-rose-800'
            }`}>
            <div className="flex-1 text-sm font-bold flex items-center gap-2">
              {getNotificationTone(error) === 'success' && <span className="text-lg">✅</span>}
              {getNotificationTone(error) === 'warning' && <span className="text-lg">⚠️</span>}
              {getNotificationTone(error) === 'info' && <span className="text-lg">ℹ️</span>}
              {getNotificationTone(error) === 'error' && <span className="text-lg">🚫</span>}
              {getNotificationText(error)}
            </div>
            <button onClick={() => setError(null)} className="w-6 h-6 flex items-center justify-center rounded-full hover:bg-black/5 text-gray-400 hover:text-gray-600 transition-colors">×</button>
          </div>
        )}
        {paragraphWarning && (
          <div className="p-4 rounded-lg shadow-lg border bg-blue-50 border-blue-200 text-blue-800 flex items-start gap-3">
            <span className="text-xl">ℹ️</span>
            <div className="flex-1">
              <div className="text-sm font-bold mb-1">Hướng dẫn biên tập:</div>
              <div className="text-xs leading-relaxed">{paragraphWarning}</div>
            </div>
            <button onClick={() => setParagraphWarning(null)} className="text-gray-400 hover:text-gray-600">×</button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      <NotificationArea />

      {/* HEADER */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-40">
        <div className="max-w-[1800px] mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center text-white shadow-indigo-200 shadow-lg">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><polyline points="14 2 14 8 20 8" /></svg>
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-slate-800">Mail Merge AI</h1>
              <p className="text-[10px] uppercase tracking-wider font-bold text-slate-400">Intelligent Document Automation</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {step === 'preview' && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setStep('upload')}
                  disabled={merging}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  Thay đổi template
                </button>
                <button
                  onClick={handleMerge}
                  disabled={merging || (!Object.values(fieldValues).some(v => v?.trim()) && !context.trim())}
                  className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg shadow-md shadow-indigo-100 font-semibold text-sm flex items-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:bg-slate-300 disabled:shadow-none disabled:scale-100"
                >
                  {merging ? (
                    <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> Đang xử lý...</>
                  ) : (
                    <>Thực hiện Merge <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></svg></>
                  )}
                </button>
              </div>
            )}
            {step === 'preview_result' && (
              <button onClick={handleReset} className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm font-medium hover:bg-slate-900 transition-colors">Bắt đầu lại</button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1800px] mx-auto p-4 md:p-6">
        {/* STEP: UPLOAD */}
        {step === 'upload' && (
          <div className="max-w-2xl mx-auto mt-12">
            <div className="bg-white rounded-2xl shadow-xl shadow-slate-200 border border-slate-100 p-10 text-center">
              <div className="w-20 h-20 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto mb-6">
                <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
              </div>
              <h2 className="text-2xl font-bold text-slate-800 mb-3">Tải lên Template của bạn</h2>
              <p className="text-slate-500 mb-8 max-w-md mx-auto leading-relaxed">Hỗ trợ file Word (.docx). Hệ thống sẽ tự động nhận diện các placeholders dạng «ten_field».</p>
              <FileUpload onComplete={handleUploadComplete} />
            </div>
          </div>
        )}

        {/* STEP: PREVIEW / EDITOR */}
        {step === 'preview' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">

            {/* LEFT: EDITOR & TOOLBAR */}
            <div className="lg:col-span-8 space-y-4">
              {/* TOOLBAR */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-2 flex flex-wrap items-center gap-1 sticky top-20 z-30">
                <div className="flex items-center gap-1 border-r border-slate-100 pr-2 mr-1 relative placeholder-dropdown-container">
                  <div className="relative">
                    <button
                      onClick={() => setShowPlaceholderDropdown(!showPlaceholderDropdown)}
                      className={`p-2 rounded-lg transition-colors flex items-center gap-2 text-xs font-bold ${isAddMode ? 'bg-indigo-600 text-white' : 'hover:bg-slate-100 text-slate-600'}`}
                      title="Thêm Placeholder"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                      {isAddMode ? 'Đang thêm...' : 'Placeholder'}
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`ml-1 transition-transform ${showPlaceholderDropdown ? 'rotate-180' : ''}`}><polyline points="6 9 12 15 18 9" /></svg>
                    </button>

                    {showPlaceholderDropdown && (
                      <div className="absolute top-full left-0 mt-2 w-48 bg-white border border-slate-200 shadow-xl rounded-xl z-[50] overflow-hidden animate-in fade-in slide-in-from-top-2 duration-200">
                        <button
                          onClick={() => {
                            setIsAddMode(!isAddMode)
                            setShowPlaceholderDropdown(false)
                          }}
                          className="w-full px-4 py-3 text-left text-xs font-bold hover:bg-slate-50 flex items-center gap-3 text-slate-700 transition-colors"
                        >
                          <span className="w-6 h-6 bg-indigo-50 text-indigo-600 rounded flex items-center justify-center">✍️</span>
                          Thêm thủ công
                        </button>
                        <button
                          onClick={() => {
                            handleAIAnalyze()
                            setShowPlaceholderDropdown(false)
                          }}
                          className="w-full px-4 py-3 text-left text-xs font-bold hover:bg-slate-50 border-t border-slate-50 flex items-center gap-3 text-slate-700 transition-colors"
                        >
                          <span className="w-6 h-6 bg-purple-50 text-purple-600 rounded flex items-center justify-center">✨</span>
                          AI Suggestion
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1 border-r border-slate-100 pr-2 mr-1">
                  <button onClick={() => setShowAddImagePopup(true)} className="p-2 hover:bg-slate-100 rounded-lg text-slate-600 transition-colors" title="Thêm ảnh">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>
                  </button>
                  <button onClick={() => setShowAddTablePopup(true)} className="p-2 hover:bg-slate-100 rounded-lg text-slate-600 transition-colors" title="Thêm bảng">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="3" y1="15" x2="21" y2="15" /><line x1="9" y1="3" x2="9" y2="21" /><line x1="15" y1="3" x2="15" y2="21" /></svg>
                  </button>
                  <button onClick={handleAddPageBreak} className="p-2 hover:bg-slate-100 rounded-lg text-slate-600 transition-colors" title="Ngắt trang">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="3" y1="13" x2="21" y2="13" /></svg>
                  </button>
                </div>

                <div className="flex items-center gap-1 border-r border-slate-100 pr-2 mr-1">
                  <button
                    onClick={() => {
                      const selection = window.getSelection()
                      const selectedText = selection.toString().trim()
                      if (selectedText && selectedTextForEdit) {
                        setCopiedFormat(selectedTextForEdit.format)
                        setError('✅ Đã copy định dạng!')
                        setTimeout(() => setError(null), 2000)
                      } else {
                        setError('⚠️ Chọn văn bản để copy định dạng')
                        setTimeout(() => setError(null), 2000)
                      }
                    }}
                    className={`p-2 rounded-lg transition-colors ${copiedFormat ? 'text-indigo-600 bg-indigo-50' : 'text-slate-600 hover:bg-slate-100'}`}
                    title="Copy Format"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><rect x="8" y="2" width="8" height="4" rx="1" ry="1" /></svg>
                  </button>
                  <button
                    onClick={async () => {
                      if (!copiedFormat) return
                      const selection = window.getSelection()
                      const selectedText = selection.toString().trim()
                      if (!selectedText) { setError('⚠️ Chọn văn bản để paste format'); setTimeout(() => setError(null), 2000); return }
                      try {
                        const blockIndex = getCurrentBlockIndex()
                        if (blockIndex === null) return
                        await handleFormatApplied({ selectedText, format: copiedFormat, type: 'format', blockIndex })
                        setError('✅ Đã áp dụng định dạng!')
                        setTimeout(() => setError(null), 2000)
                      } catch (err) { setError('⚠️ Paste format thất bại'); setTimeout(() => setError(null), 3000) }
                    }}
                    disabled={!copiedFormat}
                    className={`p-2 rounded-lg transition-colors ${copiedFormat ? 'text-indigo-600 hover:bg-indigo-100' : 'text-slate-300 cursor-not-allowed'}`}
                    title="Paste Format"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v8" /><path d="m9 7 3 3 3-3" /><path d="M19 13V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3.5" /></svg>
                  </button>
                </div>

                {/* TABLE TOOLS - ONLY SHOW WHEN CELL SELECTED */}
                {selectedTableInfo.isCellSelected && (
                  <div className="flex items-center gap-1 bg-indigo-50 px-2 py-1 rounded-lg">
                    <span className="text-[10px] font-bold text-indigo-400 uppercase mr-1">Bảng</span>
                    <button onClick={() => handleAddTableRow('above')} className="p-1.5 hover:bg-white rounded text-indigo-600 transition-colors" title="Thêm hàng trên">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3h18" /><rect x="3" y="15" width="18" height="6" rx="2" /><path d="M12 9v6" /><path d="m9 12 3-3 3 3" /></svg>
                    </button>
                    <button onClick={() => handleAddTableRow('below')} className="p-1.5 hover:bg-white rounded text-indigo-600 transition-colors" title="Thêm hàng dưới">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18" /><rect x="3" y="3" width="18" height="6" rx="2" /><path d="M12 9v6" /><path d="m9 12 3 3 3-3" /></svg>
                    </button>
                    <button onClick={() => handleAddTableColumn('left')} className="p-1.5 hover:bg-white rounded text-indigo-600 transition-colors" title="Thêm cột trái">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18" /><rect x="15" y="3" width="6" height="18" rx="2" /><path d="M9 12h6" /><path d="m12 9-3 3 3 3" /></svg>
                    </button>
                    <button onClick={() => handleAddTableColumn('right')} className="p-1.5 hover:bg-white rounded text-indigo-600 transition-colors" title="Thêm cột phải">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 3v18" /><rect x="3" y="3" width="6" height="18" rx="2" /><path d="M9 12h6" /><path d="m12 9 3 3-3 3" /></svg>
                    </button>
                    <button onClick={handleOpenCellFormatDialog} className="p-1.5 hover:bg-white rounded text-indigo-600 transition-colors" title="Format ô">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z" /><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" /></svg>
                    </button>
                    <button onClick={handleDeleteTableRow} className="p-1.5 hover:bg-red-50 rounded text-red-500 transition-colors" title="Xóa hàng">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                    </button>
                  </div>
                )}
              </div>

              {/* EDITOR CONTAINER */}
              <div className="bg-slate-50 border border-slate-200 rounded-2xl shadow-sm overflow-hidden relative p-4 sm:p-8">
                {isAddMode && (
                  <div className="absolute top-0 left-0 right-0 z-20 bg-indigo-600/10 border-b border-indigo-200 backdrop-blur-sm px-4 py-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 bg-indigo-600 rounded-full animate-pulse"></div>
                      <span className="text-[10px] font-black uppercase tracking-widest text-indigo-700">Chế độ thêm: Click vào văn bản để đặt vị trí</span>
                    </div>
                    <button onClick={handleCancelAddMode} className="text-[10px] font-bold text-indigo-600 hover:text-indigo-800 underline uppercase tracking-tight">Hủy bỏ</button>
                  </div>
                )}

                <div
                  id="document-editor"

                  contentEditable
                  suppressContentEditableWarning
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
                            const currentBlockElement = cellParagraph || editedBlock
                            const cursorPosition = getCursorPositionInParagraph(range, currentBlockElement)

                            if (cursorPosition === 'middle') {
                              setParagraphWarning('⚠️ Không thể tạo đoạn mới từ giữa văn bản!')
                              setTimeout(() => setParagraphWarning(null), 5000)
                              return
                            }

                            let params = {
                              position: cursorPosition === 'start' ? 'before' : 'after',
                              text: ''
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
                                  tableIndex, rowIndex: row, colIndex: col, paraInCell
                                }
                              }
                            } else if (editedBlock) {
                              const blockIndex = parseInt(editedBlock.getAttribute('data-block-index'))
                              params = { ...params, blockIndex }
                            }

                            const editor = document.getElementById('document-editor')
                            const savedScrollTop = editor?.scrollTop || 0

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

                            setEditorHtml(result.html_preview)
                            setFields(result.fields)

                            setTimeout(() => {
                              const updatedEditor = document.getElementById('document-editor')
                              if (updatedEditor) {
                                updatedEditor.scrollTop = savedScrollTop
                                let cursorTarget = params.tableIndex !== undefined ? {
                                  blockIndex: params.blockIndex,
                                  paraInCell: (params.paraInCell || 0) + 1,
                                  tableIndex: params.tableIndex,
                                  rowIndex: params.rowIndex,
                                  colIndex: params.colIndex
                                } : { blockIndex: params.blockIndex + 1 }

                                const targetSelector = getCursorTargetSelector(cursorTarget)
                                const targetBlock = updatedEditor.querySelector(targetSelector)
                                if (targetBlock) setCaretAtRenderedOffset(targetBlock, 0)
                              }
                            }, 0)

                            setError('✅ Đã thêm dòng mới!')
                            setTimeout(() => setError(null), 2000)
                          } catch (err) {
                            setError('⚠️ Thêm dòng mới thất bại')
                          }
                        }
                      }
                    }

                    // Delete logic
                    if ((e.key === 'Delete' || e.key === 'Backspace') && !isAddMode) {
                      const selection = window.getSelection()
                      if (selection.rangeCount > 0) {
                        const range = selection.getRangeAt(0)
                        const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                          ? range.startContainer.parentElement
                          : range.startContainer
                        const cellParagraph = startElement?.closest('.cell-paragraph')
                        const editedBlock = startElement?.closest('[data-block-index]')

                        if (!range.collapsed) {
                          // Multiple blocks deletion logic could go here, but keeping it simple for now
                        } else {
                          // Handle empty paragraph deletion
                          const currentText = (cellParagraph || editedBlock)?.textContent?.trim() || ''
                          if (currentText === '' && range.startOffset === 0) {
                            e.preventDefault()
                            try {
                              let params = {}
                              if (cellParagraph) {
                                const cellBlock = cellParagraph.closest('[data-block-index]')
                                params = {
                                  blockIndex: parseInt(cellBlock.getAttribute('data-block-index')),
                                  paraInCell: parseInt(cellParagraph.getAttribute('data-para-in-cell')),
                                  tableIndex: parseInt(cellBlock.getAttribute('data-table-index') || '0'),
                                  rowIndex: parseInt(cellBlock.getAttribute('data-row')),
                                  colIndex: parseInt(cellBlock.getAttribute('data-col'))
                                }
                              } else if (editedBlock) {
                                params = { blockIndex: parseInt(editedBlock.getAttribute('data-block-index')) }
                              }
                              const result = await deleteParagraph(templateId, params.blockIndex, params.tableIndex, params.rowIndex, params.colIndex, params.paraInCell)
                              updateEditorHtmlWithPreservation(result.html_preview, result.fields)
                            } catch (err) { setError('⚠️ Xóa dòng thất bại') }
                          }
                        }
                      }
                    }
                  }}
                  onInput={async (e) => {
                    const newHtml = e.target.innerHTML
                    const newFields = extractFields(newHtml)
                    if (window.textUpdateTimeout) clearTimeout(window.textUpdateTimeout)

                    window.textUpdateTimeout = setTimeout(async () => {
                      try {
                        const operations = buildOperationsFromChanges(editorHtml, newHtml, fields, newFields, {
                          includePlaceholderDeletes: true
                        })

                        if (operations.length === 0) {
                          return
                        }

                        const result = await batchUpdate(templateId, operations, false, true)
                        updateEditorHtmlWithPreservation(result.html_preview, result.fields)

                        const hasTextUpdate = operations.some((op) => op.type === 'update_text')
                        const hasPlaceholderDelete = operations.some((op) => op.type === 'delete_placeholder')
                        if (hasTextUpdate) {
                          setError('✅ Đã cập nhật text')
                        } else if (hasPlaceholderDelete) {
                          setError('✅ Đã xóa placeholder')
                        }
                        setTimeout(() => setError(null), 2000)
                      } catch (err) {
                        console.error('Batch update failed:', err)
                        setError('⚠️ Cập nhật thất bại: ' + (err.response?.data?.detail || err.message))
                        setTimeout(() => setError(null), 3000)
                      }
                    }, 1000)
                  }}
                  className="p-8 sm:p-16 min-h-[1056px] w-full max-w-[1500px] mx-auto focus:outline-none bg-white shadow-2xl doc-editor-surface mb-8 mt-4"
                  dangerouslySetInnerHTML={{ __html: editorHtml }}
                />
              </div>
            </div>

            {/* RIGHT: SIDEBAR (DATA & AI) */}
            <div
              id="right-sidebar-container"
              className="lg:col-span-4 space-y-6 sticky top-20 self-start max-h-[calc(100vh-120px)] overflow-y-auto pr-2 custom-sidebar-scroll"
            >

              {/* MANUAL ADD FORM (WHEN IN ADD MODE) */}
              {isAddMode && selectedBlockIndex !== null && (
                <div className="bg-white border-2 border-indigo-500 rounded-2xl shadow-xl overflow-hidden animate-in slide-in-from-right-4 duration-300">
                  <div className="bg-indigo-600 px-4 py-3 flex items-center justify-between">
                    <h3 className="text-white text-xs font-black uppercase tracking-widest flex items-center gap-2">
                      <span className="text-lg">✍️</span> Chèn placeholder
                    </h3>
                    <button onClick={handleCancelAddMode} className="text-indigo-200 hover:text-white">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                    </button>
                  </div>
                  <div className="p-4 space-y-4">
                    <div className="bg-indigo-50 rounded-xl p-3 border border-indigo-100">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-indigo-400 uppercase">Vị trí đã chọn</span>
                        <span className="text-[10px] font-black text-indigo-600 bg-white px-2 py-0.5 rounded-full border border-indigo-100">BLOCK #{selectedBlockIndex}</span>
                      </div>
                      <p className="text-[10px] text-indigo-800 leading-tight italic">
                        {caretOffset !== null ? `Chèn chính xác tại ký tự #${caretOffset}` : "Chèn dựa theo vị trí tương đối"}
                      </p>
                    </div>

                    <div>
                      <label className="text-[10px] font-bold text-slate-400 uppercase mb-1 block">Tên placeholder</label>
                      <input
                        type="text"
                        autoFocus
                        value={newFieldName}
                        onChange={(e) => setNewFieldName(e.target.value)}
                        placeholder="Ví dụ: ho_ten, ngay_sinh..."
                        className="w-full px-3 py-2.5 text-sm border-2 border-slate-100 rounded-xl focus:border-indigo-500 outline-none font-bold transition-all"
                      />
                    </div>

                    {caretOffset === null && (
                      <div>
                        <label className="text-[10px] font-bold text-slate-400 uppercase mb-2 block">Căn chỉnh vị trí</label>
                        <div className="grid grid-cols-2 gap-2">
                          <button onClick={() => setNewFieldPosition('left')} className={`py-2 text-[10px] font-bold rounded-lg border-2 transition-all ${newFieldPosition === 'left' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'border-slate-50 text-slate-400 hover:bg-slate-50'}`}>TRƯỚC TEXT</button>
                          <button onClick={() => setNewFieldPosition('right')} className={`py-2 text-[10px] font-bold rounded-lg border-2 transition-all ${newFieldPosition === 'right' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'border-slate-50 text-slate-400 hover:bg-slate-50'}`}>SAU TEXT</button>
                        </div>
                      </div>
                    )}

                    <button
                      onClick={handleAddPlaceholder}
                      disabled={!newFieldName.trim() || analyzing}
                      className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-black text-xs uppercase tracking-widest shadow-lg shadow-indigo-100 transition-all active:scale-[0.98] disabled:bg-slate-200 disabled:shadow-none"
                    >
                      {analyzing ? "Đang xử lý..." : "Xác nhận chèn"}
                    </button>
                  </div>
                </div>
              )}

              {/* AI SUGGESTION PANEL */}
              {showAISuggestionPanel && (
                <div className="bg-white border-2 border-purple-500 rounded-2xl shadow-xl overflow-hidden animate-in slide-in-from-right-4 duration-300">
                  <div className="bg-purple-600 px-4 py-3 flex items-center justify-between">
                    <h3 className="text-white text-xs font-black uppercase tracking-widest flex items-center gap-2">
                      <span className="text-lg">✨</span> Gợi ý AI
                    </h3>
                    <button onClick={() => setShowAISuggestionPanel(false)} className="text-purple-200 hover:text-white">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                    </button>
                  </div>

                  <div className="p-4 space-y-3">
                    <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      <span>{suggestions.length} gợi ý</span>
                      <span>{analyzing ? 'Đang phân tích' : `${selectedSuggestions.length} đã chọn`}</span>
                    </div>

                    <div className="max-h-[320px] overflow-y-auto space-y-2 pr-1">
                      {analyzing && suggestions.length === 0 ? (
                        <div className="py-8 text-center text-slate-400">
                          <div className="w-8 h-8 rounded-full border-2 border-purple-200 border-t-purple-600 animate-spin mx-auto mb-2"></div>
                          <p className="text-sm">Đang tìm gợi ý...</p>
                        </div>
                      ) : suggestions.length === 0 ? (
                        <div className="py-6 text-center text-slate-400 text-sm">
                          Chưa có gợi ý. Hãy chạy lại AI.
                        </div>
                      ) : (
                        suggestions.map((suggestion, index) => {
                          const suggestionKey = getSuggestionKey(suggestion)
                          const editedSuggestion = getEditedSuggestion(suggestion)
                          const isSelected = selectedSuggestions.some((selected) => {
                            return (selected.sourceKey || getSuggestionKey(selected)) === suggestionKey
                          })

                          return (
                            <div
                              key={suggestionKey}
                              className={`rounded-xl border p-3 ${isSelected ? 'border-purple-300 bg-purple-50/70' : 'border-slate-100 bg-white'}`}
                            >
                              <div className="flex items-start gap-3">
                                <button
                                  type="button"
                                  onClick={() => toggleSuggestion(suggestion)}
                                  className={`mt-1 w-5 h-5 rounded border flex items-center justify-center text-[11px] ${isSelected ? 'bg-purple-600 border-purple-600 text-white' : 'bg-white border-slate-300 text-transparent'}`}
                                  aria-label="Chọn suggestion"
                                >
                                  ✓
                                </button>

                                <div className="flex-1 space-y-2">
                                  <div className="flex items-center justify-between gap-2">
                                    <div>
                                      <div className="text-xs font-bold text-slate-800">
                                        Gợi ý #{index + 1}
                                      </div>
                                      <div className="text-[10px] text-slate-400">
                                        Block #{suggestion.block_index}
                                      </div>
                                    </div>
                                    <button
                                      type="button"
                                      onClick={() => toggleSuggestion(suggestion)}
                                      className="text-[10px] font-bold uppercase tracking-wider text-purple-600"
                                    >
                                      {isSelected ? 'Bỏ chọn' : 'Chọn'}
                                    </button>
                                  </div>

                                  <div className="grid grid-cols-1 sm:grid-cols-[1fr_120px] gap-2">
                                    <input
                                      type="text"
                                      value={editedSuggestion.suggested_name || ''}
                                      onChange={(e) => updateSuggestionEdit(suggestion, 'suggested_name', e.target.value)}
                                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:border-purple-500 outline-none font-bold"
                                      placeholder="Tên placeholder"
                                    />
                                    <select
                                      value={editedSuggestion.position || 'right'}
                                      onChange={(e) => updateSuggestionEdit(suggestion, 'position', e.target.value)}
                                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:border-purple-500 outline-none bg-white"
                                    >
                                      <option value="left">left</option>
                                      <option value="right">right</option>
                                      <option value="new_line">new_line</option>
                                      <option value="inline">inline</option>
                                    </select>
                                  </div>

                                  <div className="text-[11px] text-slate-500 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100 truncate" title={suggestion.context || ''}>
                                    {suggestion.context || 'Không có context'}
                                  </div>
                                </div>
                              </div>
                            </div>
                          )
                        })
                      )}
                    </div>

                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => setSelectedSuggestions(suggestions.map((suggestion) => getEditedSuggestion(suggestion)))}
                        disabled={suggestions.length === 0 || analyzing}
                        className="flex-1 py-2 text-[10px] font-bold uppercase tracking-wider text-purple-700 hover:bg-purple-50 rounded-lg transition-colors disabled:text-slate-300 disabled:hover:bg-transparent"
                      >
                        Chọn tất cả
                      </button>
                      <button
                        onClick={() => setSelectedSuggestions([])}
                        disabled={selectedSuggestions.length === 0 || analyzing}
                        className="flex-1 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:bg-slate-100 rounded-lg transition-colors disabled:text-slate-300 disabled:hover:bg-transparent"
                      >
                        Bỏ chọn
                      </button>
                      <button
                        onClick={handleApplySuggestions}
                        disabled={selectedSuggestions.length === 0 || analyzing}
                        className="flex-[1.3] py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-black text-[10px] uppercase tracking-widest transition-all disabled:bg-slate-200"
                      >
                        {analyzing ? '...' : `Áp dụng (${selectedSuggestions.length})`}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* GEMINI AI EXTRACTION */}
              <div className="bg-indigo-900 rounded-2xl shadow-xl p-6 text-white relative overflow-hidden group">
                <div className="absolute top-0 right-0 -mr-8 -mt-8 w-32 h-32 bg-white/10 rounded-full blur-3xl group-hover:bg-white/20 transition-all duration-500"></div>
                <div className="relative z-10">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center backdrop-blur-md">
                      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" /><path d="M5 3v4" /><path d="M19 17v4" /><path d="M3 5h4" /><path d="M17 19h4" /></svg>
                    </div>
                    <h3 className="font-bold text-lg">Gemini Intelligence</h3>
                  </div>
                  <p className="text-indigo-200 text-xs mb-4 leading-relaxed">Nhập thông tin thô hoặc mô tả ngữ cảnh, Gemini sẽ tự động trích xuất và điền vào template cho bạn.</p>
                  <textarea
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    placeholder="Ví dụ: Tôi là Nguyễn Văn A, CMND 123456789, sống ở Hà Nội..."
                    className="w-full h-32 bg-white/10 border border-white/20 rounded-xl p-4 text-sm focus:bg-white/20 outline-none transition-all placeholder:text-indigo-300"
                  />
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-[10px] text-indigo-300 font-bold uppercase tracking-widest">Trích xuất tự động</span>
                    {context.trim() && (
                      <button onClick={() => setContext('')} className="text-[10px] hover:underline">Xóa sạch</button>
                    )}
                  </div>
                </div>
              </div>

              {/* FIELD LIST & MANUAL VALUES */}
              <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-100 flex items-center justify-between">
                  <h3 className="font-bold text-slate-800 flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    Dữ liệu Merge
                  </h3>
                  <span className="bg-slate-100 text-slate-500 text-[10px] font-bold px-2 py-0.5 rounded-full">{fields.length} FIELDS</span>
                </div>
                <div className="p-4 max-h-[400px] overflow-y-auto space-y-4">
                  {fields.length === 0 ? (
                    <div className="py-8 text-center">
                      <p className="text-slate-400 text-sm">Chưa phát hiện placeholder nào.</p>
                    </div>
                  ) : (
                    fields.map((field) => (
                      <div key={field} className="group">
                        <div className="flex items-center justify-between mb-1.5 px-1">
                          <label className="text-xs font-bold text-slate-500 font-mono break-all flex-1 pr-2" title={field}>«{field}»</label>
                          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button onClick={() => toggleFieldLock(field)} className={`p-1 rounded hover:bg-slate-100 ${lockedFields.includes(field) ? 'text-amber-600' : 'text-slate-400'}`} title={lockedFields.includes(field) ? "Mở khóa cho Gemini" : "Khóa với Gemini"}>
                              {lockedFields.includes(field) ? '🔒' : '🔓'}
                            </button>
                            <button onClick={() => deleteField(field)} className="p-1 rounded hover:bg-red-50 text-red-400" title="Xóa">
                              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></svg>
                            </button>
                          </div>
                        </div>
                        <input
                          type="text"
                          value={fieldValues[field] || ''}
                          onChange={(e) => setFieldValues(prev => ({ ...prev, [field]: e.target.value }))}
                          placeholder={lockedFields.includes(field) ? "Bị khóa..." : "Nhập giá trị..."}
                          disabled={lockedFields.includes(field)}
                          className={`w-full px-3 py-2 text-sm border rounded-xl transition-all outline-none ${lockedFields.includes(field) ? 'bg-slate-50 border-slate-100 text-slate-400 italic' : 'border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-50'}`}
                        />
                      </div>
                    ))
                  )}
                </div>
                <div className="p-3 bg-slate-50 border-t border-slate-100 flex gap-2">
                  <button onClick={lockAllFields} className="flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:bg-slate-200 rounded-lg transition-colors">Khóa tất cả</button>
                  <button onClick={unlockAllFields} className="flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors">Mở khóa hết</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP: PREVIEW RESULT */}
        {step === 'preview_result' && previewHtml && (
          <div className="max-w-[1600px] mx-auto space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-slate-800">Kiểm tra kết quả</h2>
                <p className="text-sm text-slate-500">Xem trước tài liệu sau khi đã điền dữ liệu</p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setStep('preview')} className="px-4 py-2 bg-white border border-slate-200 text-slate-600 rounded-lg text-sm font-bold hover:bg-slate-50 transition-colors">Quay lại sửa</button>
                <button
                  onClick={() => {
                    downloadFile(resultId);
                    setError('✅ Đang tải xuống tài liệu...');
                    setTimeout(() => setError(null), 5000);
                  }}
                  className="px-6 py-2 bg-indigo-600 text-white rounded-lg text-sm font-bold hover:bg-indigo-700 shadow-md shadow-indigo-100 transition-all"
                >
                  Xác nhận & Tải xuống
                </button>
              </div>
            </div>

            <div className="bg-slate-100 border border-slate-200 rounded-2xl shadow-sm overflow-hidden p-4 sm:p-12 flex justify-center">
              <div className="bg-white shadow-2xl p-8 sm:p-20 w-full max-w-[1200px] min-h-[1056px] overflow-x-auto">
                <div
                  dangerouslySetInnerHTML={{ __html: previewHtml }}
                  className="prose prose-slate max-w-none"
                />
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="py-12 text-center">
        <p className="text-slate-400 text-xs font-medium uppercase tracking-[0.2em]">Mail Merge AI Platform &bull; v1.0.0</p>
      </footer>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
        
        body {
          font-family: 'Plus Jakarta Sans', sans-serif;
          background-color: #f8fafc;
        }

        .doc-editor-surface {
          box-shadow: 0 0 50px rgba(0,0,0,0.02);
          transition: all 0.3s ease;
        }
        
        .doc-editor-surface:focus-within {
          box-shadow: 0 0 50px rgba(79, 70, 229, 0.05);
        }

        .mail-merge-placeholder {
          background-color: #f5f3ff;
          color: #4f46e5;
          padding: 1px 6px;
          border-radius: 6px;
          font-weight: 700;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
          font-size: 0.9em;
          border: 1.5px solid #c7d2fe;
          cursor: pointer;
          display: inline-block;
          margin: 0 2px;
          text-indent: 0;
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .mail-merge-placeholder.is-locked {
          background-color: #fffbeb;
          border-color: #fde68a;
          color: #b45309;
        }
        
        .mail-merge-placeholder.is-selected {
          border-color: #4f46e5;
          background-color: #e0e7ff;
          box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
          transform: translateY(-1px);
        }
        
        .mail-merge-placeholder:hover {
          border-color: #4f46e5;
          background-color: #eef2ff;
          transform: scale(1.05);
        }

        .cell-paragraph {
          display: block;
          min-height: 1.2em;
          margin: 2px 0;
          padding: 2px 4px;
          border-radius: 4px;
          transition: all 0.2s;
        }
        
        .cell-paragraph:hover {
          background-color: #f8fafc;
        }
        
        .docx-table {
          border-collapse: collapse;
          width: 100%;
          margin: 1.5em 0;
        }
        
        .docx-table td, .docx-table th {
          border: none;
          padding: 12px;
          vertical-align: top;
        }

        /* Customize scrollbars */
        ::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        ::-webkit-scrollbar-track {
          background: transparent;
        }
        ::-webkit-scrollbar-thumb {
          background: #e2e8f0;
          border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
          background: #cbd5e1;
        }

        .prose-slate p { margin-bottom: 1em; line-height: 1.7; }
      `}</style>

      {/* MODALS & OVERLAYS */}
      {showEditPopup && selectedTextForEdit && (
        <EditPopup
          selectedText={{ ...selectedTextForEdit, onOpenHyperlink: handleOpenHyperlinkDialog }}
          onFormatApplied={handleFormatApplied}
          onClose={() => { setShowEditPopup(false); setSelectedTextForEdit(null); }}
        />
      )}

      {showAddTablePopup && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-[60] animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl p-8 max-w-sm w-full shadow-2xl border border-slate-100 animate-in zoom-in-95 duration-200">
            <h3 className="text-xl font-bold text-slate-800 mb-2">📊 Thêm Bảng</h3>
            <p className="text-xs text-slate-500 mb-6 font-medium">Chọn kích thước bảng để chèn vào vị trí hiện tại.</p>
            <div className="grid grid-cols-2 gap-4 mb-8">
              <div>
                <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Số hàng</label>
                <input type="number" min="1" max="20" value={tableSize.rows} onChange={(e) => setTableSize({ ...tableSize, rows: parseInt(e.target.value) || 1 })} className="w-full border border-slate-200 rounded-xl px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Số cột</label>
                <input type="number" min="1" max="10" value={tableSize.cols} onChange={(e) => setTableSize({ ...tableSize, cols: parseInt(e.target.value) || 1 })} className="w-full border border-slate-200 rounded-xl px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none" />
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={handleAddTableAtCursor} className="flex-1 bg-indigo-600 text-white py-3 rounded-xl font-bold text-sm hover:bg-indigo-700 transition-colors shadow-lg shadow-indigo-100">Xác nhận</button>
              <button onClick={() => setShowAddTablePopup(false)} className="flex-1 bg-slate-100 text-slate-600 py-3 rounded-xl font-bold text-sm hover:bg-slate-200 transition-colors">Hủy</button>
            </div>
          </div>
        </div>
      )}

      {showAddImagePopup && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-[60] animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl p-8 max-w-sm w-full shadow-2xl border border-slate-100 animate-in zoom-in-95 duration-200">
            <h3 className="text-xl font-bold text-slate-800 mb-2">📷 Thêm Ảnh</h3>
            <p className="text-xs text-slate-500 mb-6 font-medium">Tải ảnh lên để chèn vào vị trí hiện tại.</p>
            <div className="space-y-6 mb-8">
              <input type="file" accept="image/*" onChange={(e) => setSelectedImageFile(e.target.files[0])} className="w-full text-xs file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-bold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 cursor-pointer" />
              <div>
                <label className="block text-[10px] font-bold text-slate-400 uppercase mb-2">Chiều rộng (inches): {imageWidth}"</label>
                <input type="range" min="1.0" max="8.0" step="0.5" value={imageWidth} onChange={(e) => setImageWidth(parseFloat(e.target.value))} className="w-full accent-indigo-600" />
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={handleAddImageAtCursor} disabled={!selectedImageFile} className="flex-1 bg-indigo-600 text-white py-3 rounded-xl font-bold text-sm hover:bg-indigo-700 disabled:bg-slate-200 transition-colors shadow-lg shadow-indigo-100">Tải lên</button>
              <button onClick={() => { setShowAddImagePopup(false); setSelectedImageFile(null); }} className="flex-1 bg-slate-100 text-slate-600 py-3 rounded-xl font-bold text-sm hover:bg-slate-200 transition-colors">Hủy</button>
            </div>
          </div>
        </div>
      )}

      {showCellFormatDialog && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-[60] animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl p-8 max-w-lg w-full shadow-2xl border border-slate-100 animate-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold text-slate-800">🎨 Định dạng ô</h3>
              <button onClick={() => setShowCellFormatDialog(false)} className="text-slate-400 hover:text-slate-600">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>

            <div className="space-y-8">
              {/* PHẦN 1: MÀU NỀN & CĂN LỀ */}
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <label className="block text-[10px] font-bold text-slate-400 uppercase mb-2">Màu nền</label>
                  <div className="flex gap-2">
                    <input type="color" value={cellFormatOptions.background_color} onChange={(e) => setCellFormatOptions({ ...cellFormatOptions, background_color: e.target.value })} className="w-10 h-10 border-0 rounded-lg cursor-pointer bg-transparent" />
                    <input type="text" value={cellFormatOptions.background_color} onChange={(e) => setCellFormatOptions({ ...cellFormatOptions, background_color: e.target.value })} className="flex-1 border border-slate-200 rounded-xl px-3 py-1 text-xs focus:ring-2 focus:ring-indigo-500 outline-none font-mono" />
                  </div>
                </div>
                <div>
                  <label className="block text-[10px] font-bold text-slate-400 uppercase mb-2">Căn lề</label>
                  <div className="grid grid-cols-3 gap-1 bg-slate-100 p-1 rounded-xl">
                    {['top', 'center', 'bottom'].map(v => ['left', 'center', 'right'].map(h => (
                      <button key={`${v}-${h}`} onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: h, vertical_align: v })} className={`aspect-square flex items-center justify-center rounded-lg border transition-all ${cellFormatOptions.vertical_align === v && cellFormatOptions.horizontal_align === h ? 'bg-white text-indigo-600 border-white shadow-sm ring-1 ring-slate-200' : 'text-slate-400 hover:bg-white/50 border-transparent'}`}>
                        <div className={`w-3 h-3 border-2 border-current rounded-sm ${h === 'left' ? 'mr-auto' : h === 'right' ? 'ml-auto' : 'mx-auto'} ${v === 'top' ? 'mb-auto' : v === 'bottom' ? 'mt-auto' : 'my-auto'}`}></div>
                      </button>
                    )))}
                  </div>
                </div>
              </div>

              {/* PHẦN 2: BORDER EDITING */}
              <div className="space-y-4">
                <label className="block text-[10px] font-bold text-slate-400 uppercase mb-3">Đường viền (Borders)</label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {Object.entries(cellFormatOptions.borders).map(([side, config]) => (
                    <div key={side} className="bg-slate-50 p-4 rounded-2xl border border-slate-100">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-[10px] font-black uppercase text-slate-500">{side === 'top' ? 'Trên' : side === 'bottom' ? 'Dưới' : side === 'left' ? 'Trái' : 'Phải'}</span>
                        <input
                          type="color"
                          value={config.color}
                          onChange={(e) => setCellFormatOptions({
                            ...cellFormatOptions,
                            borders: {
                              ...cellFormatOptions.borders,
                              [side]: { ...config, color: e.target.value }
                            }
                          })}
                          className="w-5 h-5 border-0 rounded-full cursor-pointer bg-transparent"
                        />
                      </div>
                      <div className="space-y-3">
                        <select
                          value={config.style}
                          onChange={(e) => setCellFormatOptions({
                            ...cellFormatOptions,
                            borders: {
                              ...cellFormatOptions.borders,
                              [side]: { ...config, style: e.target.value }
                            }
                          })}
                          className="w-full bg-white border border-slate-200 rounded-lg px-2 py-1.5 text-[11px] font-bold outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                          <option value="single">Nét đơn (Single)</option>
                          <option value="double">Nét đôi (Double)</option>
                          <option value="dotted">Chấm bi (Dotted)</option>
                          <option value="dashed">Nét đứt (Dashed)</option>
                          <option value="none">Không viền (None)</option>
                        </select>
                        <div className="flex items-center gap-2">
                          <input
                            type="range" min="2" max="24" step="2"
                            value={config.size}
                            onChange={(e) => setCellFormatOptions({
                              ...cellFormatOptions,
                              borders: {
                                ...cellFormatOptions.borders,
                                [side]: { ...config, size: parseInt(e.target.value) }
                              }
                            })}
                            className="flex-1 accent-indigo-600"
                          />
                          <span className="text-[10px] font-mono font-bold text-slate-400 w-8">{config.size}pt</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex gap-3 pt-6 border-t border-slate-100">
                <button onClick={handleFormatTableCell} className="flex-1 bg-indigo-600 text-white py-3 rounded-2xl font-bold text-sm hover:bg-indigo-700 transition-all shadow-xl shadow-indigo-100 hover:scale-[1.02] active:scale-[0.98]">Lưu thay đổi</button>
                <button onClick={() => setShowCellFormatDialog(false)} className="flex-1 bg-slate-100 text-slate-600 py-3 rounded-2xl font-bold text-sm hover:bg-slate-200 transition-colors">Hủy</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showHyperlinkDialog && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-[60] animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl p-8 max-w-sm w-full shadow-2xl border border-slate-100 animate-in zoom-in-95 duration-200">
            <h3 className="text-xl font-bold text-slate-800 mb-2">🔗 Chèn liên kết</h3>
            <p className="text-xs text-slate-500 mb-6 font-medium truncate">Liên kết cho: "{hyperlinkPosition.selectedText}"</p>
            <div className="mb-8">
              <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Địa chỉ URL</label>
              <input type="url" autoFocus value={hyperlinkData.url} onChange={(e) => setHyperlinkData({ ...hyperlinkData, url: e.target.value })} className="w-full border border-slate-200 rounded-xl px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none text-sm" placeholder="https://..." />
            </div>
            <div className="flex gap-3">
              <button onClick={handleAddHyperlink} className="flex-1 bg-indigo-600 text-white py-3 rounded-xl font-bold text-sm hover:bg-indigo-700 transition-colors shadow-lg shadow-indigo-100">Thêm</button>
              <button onClick={() => { setShowHyperlinkDialog(false); setHyperlinkData({ url: '' }); }} className="flex-1 bg-slate-100 text-slate-600 py-3 rounded-xl font-bold text-sm hover:bg-slate-200 transition-colors">Hủy</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
