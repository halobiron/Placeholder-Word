import { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import FileUpload from './components/FileUpload'
import EditPopup from './components/EditPopup'
import { mergeTemplate, getPreview, suggestPlaceholders, applySuggestions, addPlaceholderByPosition, addPlaceholderByOffset, suggestFieldName, editSelection, updateTextInTemplate, getSelectionFormat, addTableRow, deleteTableRow, addTableColumn, deleteTableColumn, formatTableCell, getCellFormat, addParagraph, deleteParagraph, deleteMultipleParagraphs, addTableAtCursor, addImageAtCursor, addHyperlink, batchUpdate } from './api'

function App() {
  const [step, setStep] = useState('upload') // upload, preview, preview_result, download
  const [templateId, setTemplateId] = useState(null)
  const [editorHtml, setEditorHtml] = useState(null)
  const [fields, setFields] = useState([])
  const [fieldValues, setFieldValues] = useState({}) // Direct value editing
  const [context, setContext] = useState('')
  const [resultId, setResultId] = useState(null)
  const [previewHtml, setPreviewHtml] = useState(null) // Preview of merged result
  const [merging, setMerging] = useState(false)
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

  // Warning message for mid-paragraph clicks
  const [paragraphWarning, setParagraphWarning] = useState(null)

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
  const buildOperationsFromChanges = (oldHtml, newHtml, oldFields, newFields) => {
    const operations = []

    // =======================================================================
    // 1. DETECT PLACEHOLDER CHANGES
    // =======================================================================

    // Find deleted fields (fields in old but not in new)
    const deletedFields = oldFields.filter(f => !newFields.includes(f))

    // Add delete operations for deleted placeholders
    deletedFields.forEach(fieldName => {
      operations.push({
        type: 'delete_placeholder',
        field_name: fieldName
      })
      console.log(`[BUILD OP] Delete placeholder: ${fieldName}`)
    })

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

      // Check if there are placeholders in this block that were deleted
      // If placeholders were deleted, don't add update_text operation
      // (the delete_placeholder operation will handle it)
      const oldPlaceholders = oldBlock ? oldBlock.querySelectorAll('.mail-merge-placeholder') : []
      const newPlaceholders = newBlock ? newBlock.querySelectorAll('.mail-merge-placeholder') : []

      const placeholderDeleted = oldPlaceholders.length > newPlaceholders.length

      // Add text update operation only if:
      // - Text actually changed
      // - No placeholders were deleted (avoid conflict)
      if (oldText !== newText && !placeholderDeleted) {
        operations.push({
          type: 'update_text',
          block_index: i,
          old_text: oldText,
          new_text: newText
        })
        console.log(`[BUILD OP] Update text block ${i}: "${oldText.substring(0, 30)}..." → "${newText.substring(0, 30)}..."`)
      }
    }

    console.log(`[BUILD OP] Total operations built: ${operations.length}`)
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
              newText: newText
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

  // Rename placeholder using Batch Update API
  const renameField = async (oldName, newName) => {
    console.log('[renameField] ========== RENAME STARTED ==========')
    console.log('[renameField] oldName:', oldName)
    console.log('[renameField] newName:', newName)
    console.log('[renameField] current fields:', fields)

    const editor = document.getElementById('document-editor')
    if (!editor) {
      console.error('[renameField] ❌ Editor not found')
      return
    }

    // Store current state for rollback
    const oldHtml = editorHtml
    const oldFields = extractFields(editor.innerHTML)

    console.log('[renameField] Stored state for rollback:', {
      oldFieldsCount: oldFields.length
    })

    // Update UI immediately
    const placeholders = editor.querySelectorAll('.mail-merge-placeholder')
    console.log('[renameField] Found placeholders in editor:', placeholders.length)

    let updatedCount = 0
    placeholders.forEach(span => {
      if (span.getAttribute('data-field') === oldName) {
        console.log('[renameField] Updating placeholder:', {
          oldField: span.getAttribute('data-field'),
          oldText: span.textContent,
          newField: newName
        })
        span.setAttribute('data-field', newName)
        span.textContent = `«${newName}»`
        updatedCount++
      }
    })

    console.log('[renameField] Updated', updatedCount, 'placeholders in UI')

    const newHtml = editor.innerHTML
    setEditorHtml(newHtml)

    try {
      // Use batchUpdate for rename operation
      const operations = [
        {
          type: 'rename_placeholder',
          old_name: oldName,
          new_name: newName
        }
      ]

      console.log('[renameField] Calling batchUpdate with operations:', operations)

      const result = await batchUpdate(templateId, operations, false, true)

      console.log('[renameField] Batch update result:', {
        success: result.success,
        total_operations: result.total_operations,
        successful: result.successful,
        failed: result.failed,
        field_count: result.field_count,
        fields: result.fields
      })

      // Update state from backend response
      setFields(result.fields || extractFields(newHtml))
      setError(`✅ Đã đổi tên «${oldName}» → «${newName}»`)
      setTimeout(() => setError(null), 2000)

      console.log('[renameField] ✅ Rename completed successfully')
    } catch (err) {
      console.error('[renameField] ❌ RENAME FAILED:', err)
      console.error('[renameField] Error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status
      })

      setError('⚠️ Đổi tên thất bại: ' + (err.response?.data?.detail || err.message))

      // Rollback UI on failure
      console.log('[renameField] Rolling back UI changes...')
      editor.querySelectorAll('.mail-merge-placeholder').forEach(span => {
        if (span.getAttribute('data-field') === newName) {
          span.setAttribute('data-field', oldName)
          span.textContent = `«${oldName}»`
        }
      })
      setEditorHtml(oldHtml)
      setFields(oldFields)
      console.log('[renameField] Rollback completed')

      setTimeout(() => setError(null), 3000)
    }

    console.log('[renameField] ========== RENAME FINISHED ==========')
  }

  // Delete placeholder using Batch Update API
  const deleteField = async (fieldName) => {
    console.log('[deleteField] ========== DELETION STARTED ==========')
    console.log('[deleteField] fieldName:', fieldName)
    console.log('[deleteField] current fields:', fields)

    const editor = document.getElementById('document-editor')
    if (!editor) {
      console.error('[deleteField] ❌ Editor not found')
      return
    }

    // Store current state for rollback
    const oldHtml = editorHtml
    const oldFields = [...fields]

    console.log('[deleteField] Stored state for rollback:', {
      oldFieldsCount: oldFields.length
    })

    try {
      // Replace each matching span with its original text
      const placeholders = editor.querySelectorAll(`.mail-merge-placeholder[data-field="${fieldName}"]`)
      console.log('[deleteField] Found placeholders to remove:', placeholders.length)

      placeholders.forEach(span => {
        const originalText = span.getAttribute('data-original') || ''
        console.log('[deleteField] Removing placeholder:', {
          fieldName,
          originalText: originalText.substring(0, 50)
        })
        span.outerHTML = originalText
      })

      const newHtml = editor.innerHTML
      const newFields = extractFields(newHtml)

      console.log('[deleteField] Fields after removal:', {
        before: oldFields,
        after: newFields,
        removed: oldFields.filter(f => !newFields.includes(f))
      })

      // Build operations list using batch update helper
      const operations = buildOperationsFromChanges(oldHtml, newHtml, oldFields, newFields)

      console.log('[deleteField] Built operations:', operations)

      if (operations.length === 0) {
        console.warn('[deleteField] ⚠️ No operations to execute')
        return
      }

      console.log(`[deleteField] Calling batchUpdate with ${operations.length} operations`)

      // Execute batch update
      const result = await batchUpdate(templateId, operations, false, true)

      console.log('[deleteField] Batch update result:', {
        success: result.success,
        total_operations: result.total_operations,
        successful: result.successful,
        failed: result.failed,
        field_count: result.field_count
      })

      if (result.success) {
        // Update local state after successful server update
                updateEditorHtmlWithPreservation(result.html_preview, result.fields)
                setError(`✅ Đã xóa «${fieldName}»`)
        setTimeout(() => setError(null), 2000)

        console.log('[deleteField] ✅ Deletion completed successfully')
      } else {
        throw new Error(result.message || 'Batch update failed')
      }

    } catch (err) {
      console.error('[deleteField] ❌ DELETION FAILED:', err)
      console.error('[deleteField] Error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status
      })

      setError('⚠️ Xóa placeholder thất bại: ' + (err.response?.data?.detail || err.message))

      // Rollback UI changes
      console.log('[deleteField] Rolling back UI changes...')
      editor.innerHTML = oldHtml
      updateEditorHtmlWithPreservation(oldHtml, oldFields)
            console.log('[deleteField] Rollback completed')

      setTimeout(() => setError(null), 3000)
    }

    console.log('[deleteField] ========== DELETION FINISHED ==========')
  }

  // Handle upload complete
  const handleUploadComplete = (data) => {
    setTemplateId(data.templateId)
    setEditorHtml(data.previewHtml)
    setFields(data.fields)
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

      // Update editor with result from applySuggestions (no extra API call needed)
      setEditorHtml(result.html_preview)
      setFields(result.updated_fields)
      
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
          const response = await getSelectionFormat(templateId, selectedText, blockIndex)
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

      // Call API with block_index and offset
      const response = await fetch(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/add-page-break-at-cursor`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          template_id: templateId,
          block_index: blockIndex,
          offset: offset
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
                <div className="p-4 border rounded-lg bg-blue-50 border-blue-200">
                  <div className="flex justify-between items-start gap-4">
                    <div className="flex-1">
                      <p className="text-sm font-semibold mb-2">
                        {`✅ ${fields.length} placeholder:`}
                      </p>
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
                                  className={`text-xs px-2 py-0.5 rounded border ${editedPosition !== s.position ? 'border-yellow-400 bg-yellow-50' : 'border-transparent bg-transparent'} ${editedPosition === 'left'
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
                            // Get block index using the same method as other operations
                            const blockIndex = getCurrentBlockIndex()
                            if (blockIndex === null) {
                              setError('⚠️ Không tìm thấy block index. Đảm bảo cursor nằm trong paragraph!')
                              setTimeout(() => setError(null), 2000)
                              return
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
                        className={`px-3 py-1.5 text-white rounded-lg text-sm font-medium transition-colors ${copiedFormat
                          ? 'bg-indigo-500 hover:bg-indigo-600'
                          : 'bg-gray-300 cursor-not-allowed'
                          }`}
                        title="Paste định dạng đã copy vào văn bản đang chọn"
                      >
                        🎨 Paste Format
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
                      <button
                        onClick={handleAddPageBreak}
                        className="ml-2 px-3 py-1 bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors text-sm"
                        title="Thêm ngắt trang tại vị trí cursor (Ctrl+Enter trong Word)"
                      >
                        📄 Ngắt Trang
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
                            onClick={handleOpenCellFormatDialog}
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
                            // NEW: Detect cursor position to show warning or determine 'before'/'after'
                            const currentBlockElement = cellParagraph || editedBlock
                            const cursorPosition = getCursorPositionInParagraph(range, currentBlockElement)

                            console.log('[DEBUG] Cursor position in paragraph:', cursorPosition)

                            // Show warning if cursor is in middle of non-empty paragraph
                            if (cursorPosition === 'middle') {
                              setParagraphWarning('⚠️ Không thể tạo đoạn mới từ giữa văn bản!\n\nWorkaround: (1) Click vào đầu hoặc cuối đoạn, nhấn Enter để thêm đoạn mới, (2) Cut nội dung muốn tách, (3) Paste vào đoạn mới.')
                              setTimeout(() => setParagraphWarning(null), 8000)
                              return // Stop processing
                            }

                            // Determine parameters for addParagraph API
                            let params = {
                              position: cursorPosition === 'start' ? 'before' : 'after',
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

                            // CRITICAL FIX: Save scroll position and cursor info before API call
                            const editor = document.getElementById('document-editor')
                            const savedScrollTop = editor?.scrollTop || 0
                            const savedScrollLeft = editor?.scrollLeft || 0
                            console.log('[DEBUG] Saved scroll position:', { scrollTop: savedScrollTop, scrollLeft: savedScrollLeft })

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
                            
                            // CRITICAL FIX: Restore scroll position and set cursor after HTML update
                            // Use setTimeout to ensure DOM is updated
                            setTimeout(() => {
                              const updatedEditor = document.getElementById('document-editor')
                              if (updatedEditor) {
                                // Restore scroll position
                                updatedEditor.scrollTop = savedScrollTop
                                updatedEditor.scrollLeft = savedScrollLeft
                                console.log('[DEBUG] Restored scroll position:', { scrollTop: savedScrollTop, scrollLeft: savedScrollLeft })

                                // Try to find and set cursor to the new paragraph
                                // The new paragraph should be after the block we just edited
                                // For regular paragraphs: find block with index = params.blockIndex + 1
                                // For table cells: find cell paragraph with paraInCell = params.paraInCell + 1
                                let cursorTarget = null
                                if (params.tableIndex !== undefined && params.rowIndex !== undefined && params.colIndex !== undefined) {
                                  cursorTarget = {
                                    blockIndex: params.blockIndex,
                                    paraInCell: (params.paraInCell || 0) + 1,
                                    tableIndex: params.tableIndex,
                                    rowIndex: params.rowIndex,
                                    colIndex: params.colIndex
                                  }
                                } else {
                                  cursorTarget = {
                                    blockIndex: params.blockIndex + 1
                                  }
                                }

                                const targetSelector = getCursorTargetSelector(cursorTarget)
                                const targetBlock = updatedEditor.querySelector(targetSelector)
                                if (targetBlock) {
                                  setCaretAtRenderedOffset(targetBlock, 0)
                                  console.log('[DEBUG] Set cursor to new paragraph:', targetSelector)
                                } else {
                                  console.log('[DEBUG] Could not find new paragraph with selector:', targetSelector)
                                }
                              }
                            }, 0)  // Run in next tick after DOM update

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

                        const singleBlockSelection = !range.collapsed
                          ? getSingleBlockSelectionContext(range)
                          : null

                        if (
                          singleBlockSelection &&
                          !Number.isNaN(singleBlockSelection.blockIndex) &&
                          selectionTouchesPlaceholder(range, singleBlockSelection.targetElement)
                        ) {
                          e.preventDefault()

                          try {
                            const offsets = calculateSelectionOffsets(range, singleBlockSelection.targetElement)
                            if (!offsets || offsets.endOffset <= offsets.startOffset) {
                              console.warn('[DELETE RANGE] Invalid offsets for placeholder-aware deletion:', {
                                selectionText: selection.toString(),
                                offsets,
                                context: singleBlockSelection
                              })
                              return
                            }

                            const operation = {
                              type: 'delete_text_range',
                              block_index: singleBlockSelection.blockIndex,
                              start_offset: offsets.startOffset,
                              end_offset: offsets.endOffset,
                              ...(singleBlockSelection.paraInCell !== undefined && {
                                para_in_cell: singleBlockSelection.paraInCell
                              })
                            }

                            console.log('[DELETE RANGE] Placeholder-aware deletion:', {
                              key: e.key,
                              selectionText: selection.toString(),
                              operation,
                              context: singleBlockSelection
                            })

                            const result = await batchUpdate(templateId, [operation], false, true)
                            updateEditorHtmlWithPreservation(
                              result.html_preview,
                              result.fields,
                              {
                                ...singleBlockSelection,
                                offset: offsets.startOffset
                              }
                            )
                            setError('✅ Đã xóa đoạn chứa placeholder!')
                            setTimeout(() => setError(null), 2000)
                            return
                          } catch (err) {
                            console.error('[DELETE RANGE] Placeholder-aware deletion failed:', err)
                            setError('⚠️ Xóa đoạn chứa placeholder thất bại: ' + (err.response?.data?.detail || err.message))
                            setTimeout(() => setError(null), 4000)
                            return
                          }
                        }

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
                                      const blockText = block.textContent || ''
                                      const blockInfo = {
                                        type: 'table_cell',
                                        blockIndex: parseInt(cellBlock.getAttribute('data-block-index')),
                                        paraInCell: parseInt(block.getAttribute('data-para-in-cell')),
                                        tableIndex: parseInt(cellBlock.getAttribute('data-table-index') || '0'),
                                        rowIndex: parseInt(cellBlock.getAttribute('data-row')),
                                        colIndex: parseInt(cellBlock.getAttribute('data-col')),
                                        text: blockText?.trim() || ''
                                      }

                                      // Calculate offset if selection is partial
                                      if (range.startContainer !== range.endContainer ||
                                        range.startOffset !== range.endOffset) {
                                        try {
                                          // Calculate start offset relative to block text
                                          const beforeRange = document.createRange()
                                          beforeRange.setStartBefore(block.firstChild || block)
                                          beforeRange.setEnd(range.startContainer, range.startOffset)

                                          const startOffset = beforeRange.toString().length

                                          // Calculate end offset
                                          const afterRange = document.createRange()
                                          afterRange.setStartBefore(block.firstChild || block)
                                          afterRange.setEnd(range.endContainer, range.endOffset)

                                          const endOffset = afterRange.toString().length

                                          // Check if selection is partial (not the entire block)
                                          if (startOffset > 0 || endOffset < blockText.length) {
                                            blockInfo.startOffset = startOffset
                                            blockInfo.endOffset = endOffset
                                          }
                                        } catch (e) {
                                          console.warn('Could not calculate offset for block:', e)
                                        }
                                      }

                                      blocks.push(blockInfo)
                                    }
                                  } else if (block.hasAttribute('data-block-index')) {
                                    // Regular paragraph block
                                    const blockText = block.textContent || ''
                                    const blockInfo = {
                                      type: 'paragraph',
                                      blockIndex: parseInt(block.getAttribute('data-block-index')),
                                      text: blockText?.trim() || ''
                                    }

                                    // Calculate offset if selection is partial
                                    if (range.startContainer !== range.endContainer ||
                                      range.startOffset !== range.endOffset) {
                                      try {
                                        // Calculate start offset relative to block text
                                        const beforeRange = document.createRange()
                                        beforeRange.setStartBefore(block.firstChild || block)
                                        beforeRange.setEnd(range.startContainer, range.startOffset)

                                        const startOffset = beforeRange.toString().length

                                        // Calculate end offset
                                        const afterRange = document.createRange()
                                        afterRange.setStartBefore(block.firstChild || block)
                                        afterRange.setEnd(range.endContainer, range.endOffset)

                                        const endOffset = afterRange.toString().length

                                        // Check if selection is partial (not the entire block)
                                        if (startOffset > 0 || endOffset < blockText.length) {
                                          blockInfo.startOffset = startOffset
                                          blockInfo.endOffset = endOffset
                                        }
                                      } catch (e) {
                                        console.warn('Could not calculate offset for block:', e)
                                      }
                                    }

                                    blocks.push(blockInfo)
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
                                  const data = {
                                    block_index: block.blockIndex,
                                    table_index: block.tableIndex,
                                    row_index: block.rowIndex,
                                    col_index: block.colIndex,
                                    para_in_cell: block.paraInCell
                                  }
                                  // Add offset if it's a partial deletion
                                  if (block.startOffset !== undefined && block.endOffset !== undefined) {
                                    data.start_offset = block.startOffset
                                    data.end_offset = block.endOffset
                                  }
                                  return data
                                } else {
                                  const data = {
                                    block_index: block.blockIndex
                                  }
                                  // Add offset if it's a partial deletion
                                  if (block.startOffset !== undefined && block.endOffset !== undefined) {
                                    data.start_offset = block.startOffset
                                    data.end_offset = block.endOffset
                                  }
                                  return data
                                }
                              })

                              console.log('[DEBUG] Deleting multiple paragraphs:', blocksData)

                              // Call API to delete multiple paragraphs
                              const result = await deleteMultipleParagraphs(
                                templateId,
                                blocksData
                              )

                              // Update UI with new HTML preview
                              updateEditorHtmlWithPreservation(result.html_preview, result.fields)  // ✅ Uses helper
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

                            updateEditorHtmlWithPreservation(result.html_preview, result.fields)  // ✅ Uses helper
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
                    const deletedFields = fields.filter(f => !newFields.includes(f))
                    let textChangeInfo = null // Track text changes for batch processing

                    // Update fields state
                    if (newFields.length !== fields.length || JSON.stringify(newFields) !== JSON.stringify(fields)) {
                      setFields(newFields)
                    }

                    // Handle regular text edits (debounced)
                    const selection = window.getSelection()
                    if (selection.rangeCount > 0 && deletedFields.length === 0) {
                      const range = selection.getRangeAt(0)
                      const startElement = range.startContainer.nodeType === Node.TEXT_NODE
                        ? range.startContainer.parentElement
                        : range.startContainer

                      const cellParagraph = startElement?.closest('.cell-paragraph')
                      const editedBlock = startElement?.closest('[data-block-index]')

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

                          let skipTextUpdates = false // Skip text updates if structure changed significantly
                          let lastUpdateResponse = null // Store response from last update-text call

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
                                const response = await updateTextInTemplate(templateId, {
                                  blockIndex: cellBlockIndex,
                                  oldText: deletedText,
                                  newText: '' // Empty to delete
                                })

                                // Store response for final update
                                lastUpdateResponse = response.data

                                console.log('[DEBUG] Successfully deleted paragraph', deletedParaIndex)
                                needsRefresh = true
                              } catch (err) {
                                console.error('[DEBUG] Failed to delete paragraph:', err)
                              }
                            }

                            // CRITICAL: After deletions, use response from backend to get correct HTML with preserved alignment
                            if (lastUpdateResponse) {
                              console.log('[DEBUG] Updating with response from backend after paragraph deletions')

                              // Save scroll position before updating
                              const editor = document.getElementById('document-editor')
                              const savedScrollTop = editor ? editor.scrollTop : 0
                              const savedScrollLeft = editor ? editor.scrollLeft : 0

                              console.log('[DEBUG] Saved positions:', { scrollTop: savedScrollTop, scrollLeft: savedScrollLeft })

                              // Update with response from backend
                              updateEditorHtmlWithPreservation(lastUpdateResponse.html_preview, lastUpdateResponse.fields)
                              skipTextUpdates = true // Skip individual text updates to avoid conflicts

                              // Restore scroll position after update
                              setTimeout(() => {
                                const editorAfter = document.getElementById('document-editor')
                                if (editorAfter) {
                                  editorAfter.scrollTop = savedScrollTop
                                  editorAfter.scrollLeft = savedScrollLeft
                                  console.log('[DEBUG] Restored scroll position:', { scrollTop: editorAfter.scrollTop, scrollLeft: editorAfter.scrollLeft })
                                }
                              }, 100) // Wait for update to complete
                            }
                          }

                          // Get text from specific paragraph in cell
                          // Only process if we didn't just do a batch structure update
                          if (!skipTextUpdates) {
                            const originalText = getTextFromCellParagraph(editorHtml, cellBlockIndex, paraInCell)
                            const newText = getTextFromCellParagraph(newHtml, cellBlockIndex, paraInCell)

                            console.log('[TEXT + PLACEHOLDER] Table cell text comparison:', {
                              originalText: originalText.substring(0, 50),
                              newText: newText.substring(0, 50),
                              changed: originalText !== newText,
                              deletedFields: deletedFields.length
                            })

                            // Store text change info for batch processing with placeholder deletion
                            if (originalText !== newText) {
                              textChangeInfo = {
                                blockIndex: cellBlockIndex,
                                originalText,
                                newText,
                                paraInCell
                              }
                              console.log('[TEXT + PLACEHOLDER] Stored table cell text change info for batch processing')
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

                        console.log('[TEXT + PLACEHOLDER] Text changed:', {
                          originalText: originalText.substring(0, 50),
                          newText: newText.substring(0, 50),
                          changed: originalText !== newText,
                          deletedFields: deletedFields
                        })

                        // Store text change info for batch processing with placeholder deletion
                        if (originalText !== newText) {
                          textChangeInfo = { blockIndex, originalText, newText }
                          console.log('[TEXT + PLACEHOLDER] Stored text change info for batch processing')
                        }
                      }
                    }

                    // Handle placeholder deletion AND text changes using Batch Update API
                    if (deletedFields.length > 0) {
                      try {
                        console.log('[DELETE PLACEHOLDERS] ========== DELETION STARTED ==========')
                        console.log('[DELETE PLACEHOLDERS] deletedFields:', deletedFields)
                        console.log('[DELETE PLACEHOLDERS] current fields:', fields)
                        console.log('[DELETE PLACEHOLDERS] new fields:', newFields)
                        console.log('[DELETE PLACEHOLDERS] textChangeInfo:', textChangeInfo)

                        // Build operations: delete placeholders AND update text if changed
                        const operations = []

                        // Add text update operation first if text changed
                        if (textChangeInfo) {
                          console.log('[DELETE PLACEHOLDERS] Adding text update operation:', textChangeInfo)
                          operations.push({
                            type: 'update_text',
                            block_index: textChangeInfo.blockIndex,
                            old_text: textChangeInfo.originalText,
                            new_text: textChangeInfo.newText,
                            ...(textChangeInfo.paraInCell !== undefined && { para_in_cell: textChangeInfo.paraInCell })
                          })
                        }

                        // Add delete operations for each deleted field
                        deletedFields.forEach(fieldName => {
                          operations.push({
                            type: 'delete_placeholder',
                            field_name: fieldName
                          })
                        })

                        console.log('[DELETE PLACEHOLDERS] Combined operations:', operations)
                        console.log('[DELETE PLACEHOLDERS] Calling batchUpdate with operations:', operations)
                        console.log('[DELETE PLACEHOLDERS] templateId:', templateId)

                        // Use batchUpdate for deletion + text update
                        const result = await batchUpdate(templateId, operations, false, true)

                        console.log('[DELETE PLACEHOLDERS] Batch update result:', result)
                        console.log('[DELETE PLACEHOLDERS] Remaining fields:', result.fields)

                        // Always trust backend preview after placeholder deletion.
                        // Otherwise export/preview can drift when the DOM changed locally
                        // but the DOCX only deleted the field.
                        console.log('[DELETE PLACEHOLDERS] Syncing editor with backend html_preview')
                        updateEditorHtmlWithPreservation(result.html_preview, result.fields || newFields)
                        
                        // Show success message with field details
                        const deletedList = deletedFields.map(f => `«${f}»`).join(', ')
                        setError(`✅ Đã xóa ${deletedFields.length} placeholder: ${deletedList}`)
                        setTimeout(() => setError(null), 3000)

                        console.log('[DELETE PLACEHOLDERS] ========== DELETION COMPLETED ==========')
                      } catch (err) {
                        console.error('[DELETE PLACEHOLDERS] ❌ FAILED:', err)
                        console.error('[DELETE PLACEHOLDERS] Error details:', {
                          message: err.message,
                          response: err.response?.data,
                          status: err.response?.status
                        })
                        setError('⚠️ Xóa placeholder thất bại: ' + (err.response?.data?.detail || err.message))
                        setTimeout(() => setError(null), 4000)

                        // Rollback - refresh template to restore state
                        console.log('[DELETE PLACEHOLDERS] Rolling back - refreshing template...')
                        try {
                          const previewData = await getPreview(templateId)
                          setEditorHtml(previewData.html_preview)
                          setFields(previewData.fields)
                          console.log('[DELETE PLACEHOLDERS] Rollback completed')
                        } catch (rollbackErr) {
                          console.error('[DELETE PLACEHOLDERS] Rollback failed:', rollbackErr)
                        }
                      }
                    }

                    // Handle text-only changes (no placeholder deletion)
                    if (deletedFields.length === 0 && textChangeInfo) {
                      console.log('[TEXT UPDATE] Processing text-only change:', textChangeInfo)

                      // Debounce text updates to avoid excessive API calls
                      if (window.textUpdateTimeout) {
                        clearTimeout(window.textUpdateTimeout)
                      }

                      window.textUpdateTimeout = setTimeout(async () => {
                        try {
                          console.log('[TEXT UPDATE] Sending to backend:', textChangeInfo)

                          const response = await updateTextInTemplate(templateId, {
                            blockIndex: textChangeInfo.blockIndex,
                            oldText: textChangeInfo.originalText,
                            newText: textChangeInfo.newText
                          })

                          console.log('[TEXT UPDATE] Backend response:', response)

                          // CRITICAL FIX: Update editorHtml to sync with file
                          // But preserve cursor position to avoid disrupting user typing
                          if (response.html_preview) {
                            // Save cursor position
                            const selection = window.getSelection()
                            const range = selection.rangeCount > 0 ? selection.getRangeAt(0) : null

                            // Get the current block element
                            const currentBlock = document.querySelector(`[data-block-index="${textChangeInfo.blockIndex}"]`)

                            // Update editorHtml
                            setEditorHtml(response.html_preview)

                            // Restore cursor after DOM update
                            setTimeout(() => {
                              if (range && currentBlock) {
                                try {
                                  selection.removeAllRanges()
                                  selection.addRange(range)
                                } catch (e) {
                                  console.log('[TEXT UPDATE] Could not restore cursor:', e)
                                }
                              }
                            }, 0)
                          }

                          if (response.fields) {
                            setFields(response.fields)
                          }
                          
                          console.log('[TEXT UPDATE] Successfully synced with cursor preserved')
                        } catch (err) {
                          console.error('[TEXT UPDATE] Failed:', err)
                          // Don't show error for text updates - they happen frequently
                          // Just log it and let user continue editing
                        }
                      }, 800) // 800ms debounce
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
                {paragraphWarning && (
                  <div className="mt-3 p-3 bg-yellow-50 text-yellow-800 border border-yellow-200 rounded-lg text-sm animate-pulse">
                    <div className="flex items-start gap-2">
                      <span className="text-lg">⚠️</span>
                      <div>
                        <div className="font-semibold">Hướng dẫn:</div>
                        <div>{paragraphWarning}</div>
                      </div>
                    </div>
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
                    onChange={(e) => setCellFormatOptions({ ...cellFormatOptions, background_color: e.target.value })}
                    className="h-10 w-20 border border-gray-300 rounded cursor-pointer"
                  />
                  <input
                    type="text"
                    value={cellFormatOptions.background_color}
                    onChange={(e) => setCellFormatOptions({ ...cellFormatOptions, background_color: e.target.value })}
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
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'left', vertical_align: 'top' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'top'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Trên-Trái"
                  >
                    ⬉ Top-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'center', vertical_align: 'top' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'top'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Trên-Giữa"
                  >
                    ⬆ Top-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'right', vertical_align: 'top' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'top'
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
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'left', vertical_align: 'center' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'center'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Giữa-Trái"
                  >
                    ⬅ Mid-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'center', vertical_align: 'center' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'center'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Giữa-Giữa"
                  >
                    ⌧ Mid-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'right', vertical_align: 'center' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'center'
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
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'left', vertical_align: 'bottom' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'left' && cellFormatOptions.vertical_align === 'bottom'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Dưới-Trái"
                  >
                    ⬋ Bot-Left
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'center', vertical_align: 'bottom' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'center' && cellFormatOptions.vertical_align === 'bottom'
                      ? 'bg-indigo-500 text-white border-indigo-600'
                      : 'bg-gray-50 hover:bg-gray-100 border-gray-300'
                      }`}
                    title="Dưới-Giữa"
                  >
                    ⬇ Bot-Center
                  </button>
                  <button
                    type="button"
                    onClick={() => setCellFormatOptions({ ...cellFormatOptions, horizontal_align: 'right', vertical_align: 'bottom' })}
                    className={`p-3 border rounded-lg text-xs font-medium transition-all ${cellFormatOptions.horizontal_align === 'right' && cellFormatOptions.vertical_align === 'bottom'
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
                  onChange={(e) => setHyperlinkData({ ...hyperlinkData, url: e.target.value })}
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
