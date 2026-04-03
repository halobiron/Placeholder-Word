import { useState } from 'react'
import FileUpload from './components/FileUpload'
import ContextForm from './components/ContextForm'
import DownloadBtn from './components/DownloadBtn'
import TinyMCEEditor from './components/TinyMCEEditor'
import { mergeTemplate } from './api'

function App() {
  const [step, setStep] = useState('upload')
  const [fileData, setFileData] = useState({
    templateId: null,
    fields: [],
    previewHtml: null,
    previewFields: [],
    resultId: null
  })

  const [editorHtml, setEditorHtml] = useState(null)
  const [editorFields, setEditorFields] = useState([])
  const [context, setContext] = useState('')
  const [merging, setMerging] = useState(false)
  const [error, setError] = useState(null)

  const handleUploadComplete = (data) => {
    setFileData(prev => ({
      ...prev,
      templateId: data.templateId,
      fields: data.fields,
      previewHtml: data.previewHtml,
      previewFields: data.previewFields
    }))
    setEditorHtml(data.previewHtml)
    setEditorFields(data.previewFields)
    setStep('preview')
  }

  const handleMerge = async () => {
    if (!context.trim()) {
      setError('Vui lòng nhập dữ liệu để merge')
      return
    }

    setMerging(true)
    setError(null)

    try {
      const result = await mergeTemplate(fileData.templateId, context)
      setFileData(prev => ({ ...prev, resultId: result.result_id }))
      setStep('download')
    } catch (err) {
      setError(err.response?.data?.detail || 'Merge thất bại. Vui lòng thử lại.')
    } finally {
      setMerging(false)
    }
  }

  const handleMergeComplete = (resultId) => {
    setFileData(prev => ({ ...prev, resultId }))
    setStep('download')
  }

  const handleReset = () => {
    setFileData({
      templateId: null,
      fields: [],
      previewHtml: null,
      previewFields: [],
      resultId: null
    })
    setContext('')
    setError(null)
    setStep('upload')
  }

  const handlePreviewContinue = () => {
    setStep('fill')
  }

  const handleFieldDelete = (fieldName) => {
    setFileData(prev => ({
      ...prev,
      fields: prev.fields.filter(f => f !== fieldName),
      previewFields: prev.previewFields.filter(f => f !== fieldName)
    }))
  }

  const handleFieldAdd = (fieldName) => {
    setFileData(prev => {
      const newFields = [...new Set([...prev.fields, fieldName])]
      return {
        ...prev,
        fields: newFields,
        previewFields: newFields
      }
    })
    setEditorFields(prev => [...new Set([...prev, fieldName])])
  }

  const handleEditorChange = (content, currentFields) => {
    setEditorHtml(content)
    setEditorFields(currentFields)
    setFileData(prev => ({
      ...prev,
      fields: currentFields,
      previewFields: currentFields
    }))
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 py-8 px-4">
      <div className="max-w-4xl mx-auto">
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Hệ Thống Mail Merge
          </h1>
          <p className="text-gray-600">
            Chuyển đổi tài liệu Word và điền dữ liệu tự động
          </p>
        </header>

        <div className="bg-white rounded-lg shadow-lg p-8">
          {step === 'upload' && (
            <FileUpload onComplete={handleUploadComplete} />
          )}

          {step === 'preview' && (
            <div className="space-y-6">
              <div className="text-center">
                <h2 className="text-2xl font-bold text-gray-900 mb-2">
                  Bước 2: Xem trước tài liệu
                </h2>
                <p className="text-gray-600">
                  Kiểm tra các placeholder và điền dữ liệu để merge
                </p>
              </div>

              {fileData.previewFields.length > 0 && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-900">
                    <strong>Đã phát hiện {fileData.previewFields.length} placeholder:</strong>{' '}
                    {fileData.previewFields.map((f, i) => (
                      <span key={i} className="inline-block mx-1">
                        <span className="px-2 py-1 bg-white border border-blue-300 rounded text-xs font-mono">
                          «{f}»
                        </span>
                        {i < fileData.previewFields.length - 1 && ''}
                      </span>
                    ))}
                  </p>
                </div>
              )}

              <TinyMCEEditor
                html={editorHtml}
                fields={editorFields}
                onFieldDelete={handleFieldDelete}
                onFieldAdd={handleFieldAdd}
                onChange={handleEditorChange}
              />

              <div className="border-t pt-6">
                <h3 className="text-lg font-semibold mb-3">Điền dữ liệu merge</h3>
                <p className="text-sm text-gray-600 mb-3">
                  Nhập thông tin dưới dạng đoạn văn. Gemini sẽ tự động trích xuất dữ liệu và điền vào các placeholder tương ứng.
                </p>

                <textarea
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  placeholder="Ví dụ: Tôi tên là Nguyễn Văn A, sinh ngày 01/01/1990, số CMND là 123456789, đang sống tại Hà Nội..."
                  className="w-full h-32 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />

                <div className="flex gap-3 mt-4">
                  <button
                    onClick={() => setStep('upload')}
                    disabled={merging}
                    className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg transition-colors disabled:opacity-50"
                  >
                    ← Quay lại
                  </button>

                  <button
                    onClick={handleMerge}
                    disabled={merging || !context.trim()}
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    {merging ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>Đang xử lý...</span>
                      </>
                    ) : (
                      <>
                        <span>Merge & Download →</span>
                      </>
                    )}
                  </button>
                </div>
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
          )}

          {step === 'fill' && (
            <ContextForm
              templateId={fileData.templateId}
              fields={fileData.fields}
              context={context}
              onComplete={handleMergeComplete}
              onBack={() => setStep('preview')}
            />
          )}

          {step === 'download' && (
            <DownloadBtn
              fileId={fileData.resultId}
              onReset={handleReset}
            />
          )}
        </div>

        <footer className="text-center mt-8 text-sm text-gray-500">
          <p>Mail Merge Placeholder System v1.0.0</p>
        </footer>
      </div>
    </div>
  )
}

export default App
