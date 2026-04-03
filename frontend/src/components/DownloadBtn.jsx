import { downloadFile } from '../api'

function DownloadBtn({ fileId, onReset }) {
  const handleDownload = () => {
    downloadFile(fileId)
  }

  return (
    <div className="space-y-6">
      <div className="text-center space-y-4">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full">
          <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>

        <div>
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Hoàn thành!
          </h2>
          <p className="text-gray-600">
            Tài liệu của bạn đã sẵn sàng để tải xuống
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <button
          onClick={handleDownload}
          className="w-full px-6 py-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-3 text-lg font-medium"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          <span>Tải xuống (.docx)</span>
        </button>

        <button
          onClick={onReset}
          className="w-full px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center justify-center gap-2"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>Xử lý tài liệu khác</span>
        </button>
      </div>

      <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
        <p className="font-medium mb-2">Lưu ý:</p>
        <ul className="space-y-1 list-disc list-inside">
          <li>File được lưu ở định dạng .docx</li>
          <li>Bạn có thể mở bằng Microsoft Word, Google Docs, hoặc LibreOffice</li>
          <li>Kiểm tra kỹ nội dung trước khi sử dụng</li>
        </ul>
      </div>
    </div>
  )
}

export default DownloadBtn
