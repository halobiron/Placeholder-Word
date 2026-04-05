import { useState, useEffect } from 'react'
import FileUpload from './components/FileUpload'
import { mergeTemplate, getPreview, updateTemplate } from './api'

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
  const [error, setError] = useState(null)

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
        const newName = prompt('Đổi tên placeholder:', fieldName)
        if (newName?.trim() && newName.trim() !== fieldName) {
          renameField(fieldName, newName.trim())
        }
      }
    })
  }, [editorHtml, step]) // Add step to re-attach handlers when returning to preview

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

    const newHtml = editor.innerHTML
    setEditorHtml(newHtml)
    setFields(extractFields(newHtml))
    setTemplateNeedsUpdate(true) // Mark template as modified
  }

  // Delete placeholder
  const deleteField = (fieldName) => {
    const editor = document.getElementById('document-editor')
    if (!editor) return

    const newHtml = editor.innerHTML.replace(new RegExp(`«${fieldName}»`, 'g'), '')
    editor.innerHTML = newHtml
    setEditorHtml(newHtml)
    setFields(extractFields(newHtml))
    setTemplateNeedsUpdate(true) // Mark template as modified
  }

  // Handle upload complete
  const handleUploadComplete = (data) => {
    setTemplateId(data.templateId)
    setEditorHtml(data.previewHtml)
    setFields(data.fields)
    setOriginalFields(data.fields) // Store original fields
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
        await updateTemplate(templateId, fields, editorHtml)
        console.log('Template updated successfully')
        setTemplateNeedsUpdate(false)
      }

      // Use direct values if available, otherwise use context
      const data = hasDirectValues ? fieldValues : context
      const result = await mergeTemplate(templateId, data, hasDirectValues)
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

              <div>
                <div className="flex justify-between items-center mb-2">
                  <h3 className="text-lg font-semibold">Tài liệu</h3>
                </div>
                <div
                  id="document-editor"
                  contentEditable
                  className="border border-gray-300 rounded-lg p-6 bg-white min-h-[400px] overflow-auto focus:ring-2 focus:ring-blue-500"
                  style={{maxHeight: '600px'}}
                  suppressContentEditableWarning={true}
                  onInput={(e) => {
                    const newHtml = e.target.innerHTML
                    setEditorHtml(newHtml)
                    setFields(extractFields(newHtml))
                  }}
                  dangerouslySetInnerHTML={{ __html: editorHtml }}
                />
                <p className="text-xs text-gray-500 mt-2">
                  💡 Click vào placeholder để đổi tên. Muốn thêm placeholder mới, upload lại file .docx với dấu chấm.
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
        `}</style>
      </div>
    </div>
  )
}

export default App
