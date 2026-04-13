import { useState } from 'react'

function EditPopup({ selectedText, onSubmit, onClose }) {
  const [newText, setNewText] = useState(selectedText?.text || '')
  const [format, setFormat] = useState({
    bold: false,
    italic: false,
    underline: false,
    color: '#000000',
    fontSize: 12,
    fontName: 'Times New Roman'
  })
  const [submitting, setSubmitting] = useState(false)
  const [action, setAction] = useState('edit') // edit, delete

  const handleSubmit = async (submitAction) => {
    setSubmitting(true)

    try {
      let data = {}

      if (submitAction === 'delete') {
        data = {
          type: 'delete',
          selectedText: selectedText?.text
        }
      } else if (newText !== selectedText?.text) {
        data = {
          type: 'text',
          selectedText: selectedText?.text,
          newText: newText
        }
      } else {
        data = {
          type: 'format',
          selectedText: selectedText?.text,
          format: format
        }
      }

      await onSubmit(data)
      onClose()
    } catch (error) {
      console.error('Edit failed:', error)
      alert('Cập nhật thất bại: ' + error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-4 right-4 bg-white shadow-lg rounded-lg p-4 w-[500px] z-50 max-h-[80vh] overflow-y-auto">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-bold text-lg">Chỉnh sửa</h3>
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
          {selectedText?.text}
        </div>
      </div>

      {/* Text editor */}
      <div className="mb-3">
        <label className="block text-sm font-medium mb-1 text-gray-700">
          Sửa nội dung:
        </label>
        <textarea
          value={newText}
          onChange={(e) => setNewText(e.target.value)}
          className="w-full border rounded p-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          rows={3}
          placeholder="Nhập nội dung mới..."
        />
      </div>

      {/* Format options - compact */}
      <div className="mb-3">
        <label className="block text-sm font-medium mb-1 text-gray-700">
          Định dạng:
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.bold}
              onChange={(e) => setFormat({ ...format, bold: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Đậm</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.italic}
              onChange={(e) => setFormat({ ...format, italic: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Nghiêng</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={format.underline}
              onChange={(e) => setFormat({ ...format, underline: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm">Gạch chân</span>
          </label>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-600">Màu:</span>
            <input
              type="color"
              value={format.color}
              onChange={(e) => setFormat({ ...format, color: e.target.value })}
              className="w-8 h-6 rounded cursor-pointer"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-600">Cỡ:</span>
            <input
              type="number"
              value={format.fontSize}
              onChange={(e) => setFormat({ ...format, fontSize: parseInt(e.target.value) })}
              className="w-16 border rounded px-2 py-1 text-sm"
              min={8}
              max={72}
            />
          </div>

          <select
            value={format.fontName}
            onChange={(e) => setFormat({ ...format, fontName: e.target.value })}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="Times New Roman">Times New Roman</option>
            <option value="Arial">Arial</option>
            <option value="Calibri">Calibri</option>
          </select>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => handleSubmit('edit')}
          disabled={submitting}
          className="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium text-sm"
        >
          {submitting ? 'Đang xử lý...' : 'Lưu thay đổi'}
        </button>
        <button
          onClick={() => handleSubmit('delete')}
          disabled={submitting}
          className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium text-sm"
        >
          Xóa
        </button>
        <button
          onClick={onClose}
          className="bg-gray-200 text-gray-700 px-4 py-2 rounded hover:bg-gray-300 transition-colors font-medium text-sm"
        >
          Hủy
        </button>
      </div>
    </div>
  )
}

export default EditPopup