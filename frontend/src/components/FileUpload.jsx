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
    <div className="w-full">
      <div
        {...getRootProps()}
        className={`relative border-2 border-dashed rounded-3xl p-12 text-center cursor-pointer transition-all duration-300 group
          ${isDragActive 
            ? 'border-indigo-500 bg-indigo-50/50 scale-[1.01]' 
            : 'border-slate-200 hover:border-indigo-400 hover:bg-slate-50'
          }
          ${uploading ? 'opacity-70 cursor-not-allowed pointer-events-none' : ''}
        `}
      >
        <input {...getInputProps()} />

        {uploading ? (
          <div className="space-y-6 py-4">
            <div className="relative w-20 h-20 mx-auto">
              <div className="absolute inset-0 border-4 border-indigo-100 rounded-full"></div>
              <div className="absolute inset-0 border-4 border-indigo-600 rounded-full border-t-transparent animate-spin"></div>
            </div>
            <div className="space-y-2">
              <p className="text-xl font-bold text-slate-800">Đang xử lý tài liệu...</p>
              <p className="text-sm text-slate-500">Gemini đang trích xuất cấu trúc và placeholder</p>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div className={`w-20 h-20 mx-auto rounded-2xl flex items-center justify-center transition-all duration-300
              ${isDragActive ? 'bg-indigo-600 text-white shadow-xl shadow-indigo-200' : 'bg-slate-100 text-slate-400 group-hover:bg-indigo-50 group-hover:text-indigo-500'}
            `}>
              <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
                <polyline points="14 2 14 8 20 8"/>
                <path d="M12 18v-6"/>
                <path d="m9 15 3-3 3 3"/>
              </svg>
            </div>
            
            <div>
              <p className="text-xl font-bold text-slate-800">
                {isDragActive ? 'Thả file vào đây' : 'Kéo thả Template Word'}
              </p>
              <p className="text-sm text-slate-500 mt-2">
                hoặc <span className="text-indigo-600 font-bold underline decoration-2 underline-offset-4">duyệt từ máy tính</span>
              </p>
            </div>

            <div className="pt-4 border-t border-slate-100 flex items-center justify-center gap-6">
               <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-green-500 rounded-full"></span>
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Hỗ trợ .DOCX</span>
               </div>
               <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-blue-500 rounded-full"></span>
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Tối đa 10MB</span>
               </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-6 p-4 bg-red-50 border border-red-100 text-red-700 rounded-2xl flex items-start gap-3 animate-in slide-in-from-top-2 duration-300">
          <div className="w-6 h-6 bg-red-100 rounded-lg flex items-center justify-center text-red-600 flex-shrink-0">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>
          <div>
            <p className="text-sm font-bold">Lỗi tải lên</p>
            <p className="text-xs opacity-80">{error}</p>
          </div>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      )}
    </div>
  )
}

export default FileUpload
