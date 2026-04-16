import { useState, useEffect } from 'react'

function EditPopup({ selectedText, onFormatApplied, onClose }) {
  const [originalFormat, setOriginalFormat] = useState(null)
  const [format, setFormat] = useState({
    bold: false,
    italic: false,
    underline: false,
    color: '#000000',
    fontSize: 12,
    fontName: 'Times New Roman',
    allCaps: false
    // Note: alignment is not currently supported for text-level formatting
  })
  const [paragraphFormat, setParagraphFormat] = useState({
    lineSpacing: 1.0,
    spaceBefore: 0,
    spaceAfter: 0,
    firstLineIndent: 0
  })
  const [showParagraphOptions, setShowParagraphOptions] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Initialize format from selectedText when component mounts or selectedText changes
  useEffect(() => {
    if (selectedText?.format) {
      setFormat(selectedText.format)
      setOriginalFormat(selectedText.format)
    }
  }, [selectedText])

  const hasFormatChanged = () => {
    if (!originalFormat) return true // No original format, apply current format
    return (
      format.bold !== originalFormat.bold ||
      format.italic !== originalFormat.italic ||
      format.underline !== originalFormat.underline ||
      format.color !== originalFormat.color ||
      format.fontSize !== originalFormat.fontSize ||
      format.fontName !== originalFormat.fontName ||
      format.allCaps !== (originalFormat.allCaps || false)
    )
  }

  const handleApplyFormat = async () => {
    if (!hasFormatChanged() && !showParagraphOptions) {
      // No format changes, just close
      onClose()
      return
    }

    setSubmitting(true)

    try {
      const formatData = {
        selectedText: selectedText?.text,
        format: format,
        type: 'format',
        blockIndex: selectedText?.blockIndex
      }

      // Include paragraph format if options are shown
      if (showParagraphOptions) {
        formatData.paragraphFormat = paragraphFormat
      }

      await onFormatApplied(formatData)
      onClose()
    } catch (error) {
      console.error('Format application failed:', error)
      alert('Áp dụng định dạng thất bại: ' + error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-4 right-4 bg-white shadow-lg rounded-lg p-4 w-[450px] z-50 max-h-[80vh] overflow-y-auto">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-bold text-lg">Định dạng văn bản</h3>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-700 text-xl"
        >
          ×
        </button>
      </div>

      {/* Selected text preview */}
      <div className="mb-3">
        <label className="block text-sm font-medium mb-1 text-gray-700">
          Văn bản đã chọn:
        </label>
        <div className="bg-gray-100 p-2 rounded text-sm text-gray-600">
          {selectedText?.text || 'Không có văn bản nào được chọn'}
        </div>
      </div>

      {/* Format options */}
      <div className="mb-3">
        <label className="block text-sm font-medium mb-2 text-gray-700">
          Định dạng:
        </label>

        {/* Text style toggles */}
        <div className="grid grid-cols-2 gap-2 mb-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.bold}
              onChange={(e) => setFormat({ ...format, bold: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Đậm (B)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.italic}
              onChange={(e) => setFormat({ ...format, italic: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Nghiêng (I)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.underline}
              onChange={(e) => setFormat({ ...format, underline: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Gạch chân (U)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.allCaps}
              onChange={(e) => setFormat({ ...format, allCaps: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">HOA</span>
          </label>
        </div>

        {/* Color and font size */}
        <div className="grid grid-cols-2 gap-2 mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-600">Màu sắc:</span>
            <input
              type="color"
              value={format.color}
              onChange={(e) => setFormat({ ...format, color: e.target.value })}
              className="w-10 h-8 rounded cursor-pointer border"
            />
            <span className="text-xs text-gray-500">{format.color}</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-600">Cỡ chữ:</span>
            <input
              type="number"
              value={format.fontSize}
              onChange={(e) => setFormat({ ...format, fontSize: parseInt(e.target.value) || 12 })}
              className="w-16 border rounded px-2 py-1 text-sm"
              min={8}
              max={72}
            />
            <span className="text-xs text-gray-500">pt</span>
          </div>
        </div>

        {/* Font family */}
        <div className="mb-2">
          <span className="text-xs text-gray-600">Font chữ:</span>
          <select
            value={format.fontName}
            onChange={(e) => setFormat({ ...format, fontName: e.target.value })}
            className="ml-2 border rounded px-2 py-1 text-sm"
          >
            <option value="Times New Roman">Times New Roman</option>
            <option value="Arial">Arial</option>
            <option value="Calibri">Calibri</option>
            <option value="Verdana">Verdana</option>
            <option value="Georgia">Georgia</option>
          </select>
        </div>
      </div>

      {/* Paragraph Formatting - Collapsible */}
      <div className="mb-3">
        <button
          onClick={() => setShowParagraphOptions(!showParagraphOptions)}
          className="w-full flex items-center justify-between text-sm font-medium text-gray-700 hover:text-gray-900 transition-colors"
        >
          <span>📐 Định dạng đoạn văn</span>
          <span className="text-gray-500">{showParagraphOptions ? '▼' : '▶'}</span>
        </button>

        {showParagraphOptions && (
          <div className="mt-2 p-2 bg-gray-50 rounded border">
            <div className="grid grid-cols-2 gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">Giãn dòng:</span>
                <select
                  value={paragraphFormat.lineSpacing}
                  onChange={(e) => setParagraphFormat({ ...paragraphFormat, lineSpacing: parseFloat(e.target.value) })}
                  className="flex-1 border rounded px-2 py-1 text-sm"
                >
                  <option value={1.0}>1.0 (Simple)</option>
                  <option value={1.15}>1.15</option>
                  <option value={1.5}>1.5</option>
                  <option value={2.0}>2.0 (Double)</option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">Trước (pt):</span>
                <input
                  type="number"
                  value={paragraphFormat.spaceBefore}
                  onChange={(e) => setParagraphFormat({ ...paragraphFormat, spaceBefore: parseInt(e.target.value) || 0 })}
                  className="flex-1 border rounded px-2 py-1 text-sm"
                  min={0}
                  max={72}
                />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">Sau (pt):</span>
                <input
                  type="number"
                  value={paragraphFormat.spaceAfter}
                  onChange={(e) => setParagraphFormat({ ...paragraphFormat, spaceAfter: parseInt(e.target.value) || 0 })}
                  className="flex-1 border rounded px-2 py-1 text-sm"
                  min={0}
                  max={72}
                />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-600">Indent đầu (pt):</span>
                <input
                  type="number"
                  value={paragraphFormat.firstLineIndent}
                  onChange={(e) => setParagraphFormat({ ...paragraphFormat, firstLineIndent: parseInt(e.target.value) || 0 })}
                  className="flex-1 border rounded px-2 py-1 text-sm"
                  min={0}
                  max={144}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleApplyFormat}
          disabled={submitting || !hasFormatChanged()}
          className="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium text-sm"
        >
          {submitting ? 'Đang áp dụng...' : 'Áp dụng định dạng'}
        </button>
        <button
          onClick={onClose}
          className="bg-gray-200 text-gray-700 px-4 py-2 rounded hover:bg-gray-300 transition-colors font-medium text-sm"
        >
          Hủy
        </button>
      </div>

      <p className="text-xs text-gray-500 mt-2 text-center">
        💡 Text editing có thể thực hiện trực tiếp trên tài liệu
      </p>
    </div>
  )
}

export default EditPopup
