import { useState, useEffect } from 'react'
import { mergeTemplate } from '../api'

function ContextForm({ templateId, fields, context: initialContext = '', onComplete, onBack }) {
  const [context, setContext] = useState(initialContext)
  const [merging, setMerging] = useState(false)
  const [error, setError] = useState(null)

  // Update context when initialContext changes
  useEffect(() => {
    if (initialContext) {
      setContext(initialContext)
    }
  }, [initialContext])

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!context.trim()) {
      setError('Vui lòng nhập dữ liệu')
      return
    }

    setMerging(true)
    setError(null)

    try {
      const result = await mergeTemplate(templateId, context)
      onComplete(result.result_id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Xử lý thất bại. Vui lòng thử lại.')
    } finally {
      setMerging(false)
    }
  }

  const exampleContext = `Tôi tên: Nguyễn Văn A
Số CMND: 123456789
Ngày sinh: 01/01/1990
Địa chỉ: Hà Nội
Lý do: Nghỉ phép năm`

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Bước 2: Nhập dữ liệu
        </h2>
        <p className="text-gray-600">
          Nhập thông tin để điền vào template
        </p>
      </div>

      {fields.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="font-semibold text-blue-900 mb-3">Các trường đã phát hiện:</p>
          <div className="flex flex-wrap gap-2">
            {fields.map(field => (
              <span
                key={field}
                className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium"
              >
                {field}
              </span>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="context" className="block text-sm font-medium text-gray-700 mb-2">
            Dữ liệu điền vào template
          </label>
          <textarea
            id="context"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder={exampleContext}
            className="w-full h-64 p-4 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            disabled={merging}
          />
          <p className="mt-2 text-sm text-gray-500">
            Nhập thông tin theo định dạng tự do. AI sẽ tự động trích xuất dữ liệu.
          </p>
        </div>

        <div className="flex gap-4">
          <button
            type="button"
            onClick={onBack}
            disabled={merging}
            className="flex-1 px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Quay lại
          </button>

          <button
            type="submit"
            disabled={merging || !context.trim()}
            className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {merging ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>Đang xử lý...</span>
              </>
            ) : (
              <>
                <span>Tạo tài liệu</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </>
            )}
          </button>
        </div>
      </form>

      {error && (
        <div className="p-4 bg-red-50 text-red-700 rounded-lg flex items-start gap-3">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}

export default ContextForm
