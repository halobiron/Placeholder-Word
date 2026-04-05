import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { convertDocx } from '../api'

function FileUpload({ onComplete }) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0]

    if (!file) return

    // Validate .docx
    if (!file.name.endsWith('.docx')) {
      setError('Chỉ chấp nhận file .docx')
      return
    }

    // Validate file size (10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('File quá lớn (tối đa 10MB)')
      return
    }

    setUploading(true)
    setError(null)

    try {
      // Upload to backend for template conversion with HTML preview
      const result = await convertDocx(file)

      // Return result with HTML preview from backend
      onComplete({
        templateId: result.template_id,
        fields: result.fields,
        previewHtml: result.html_preview || '',
        previewFields: result.fields
      })
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Upload thất bại. Vui lòng thử lại.')
    } finally {
      setUploading(false)
    }
  }, [onComplete])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx']
    },
    multiple: false
  })

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Bước 1: Tải lên tài liệu
        </h2>
        <p className="text-gray-600">
          Tải lên file .docx có chứa dấu chấm hoặc gạch dưới
        </p>
      </div>

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-all
          ${isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
          ${uploading ? 'opacity-50 cursor-not-allowed' : ''}
        `}
      >
        <input {...getInputProps()} />

        {uploading ? (
          <div className="space-y-4">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
            <p className="text-lg">Đang xử lý...</p>
          </div>
        ) : (
          <div className="space-y-4">
            <svg className="w-16 h-16 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <div>
              <p className="text-lg font-medium text-gray-700">
                {isDragActive ? 'Thả file vào đây' : 'Kéo thả file vào đây'}
              </p>
              <p className="text-sm text-gray-500 mt-2">
                hoặc click để chọn file
              </p>
            </div>
            <p className="text-xs text-gray-400">
              Chỉ chấp nhận file .docx, tối đa 10MB
            </p>
          </div>
        )}
      </div>

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

export default FileUpload
