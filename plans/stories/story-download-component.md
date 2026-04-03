# Story: Download Button Component

**ID:** story-download-component
**Epic:** Phase 2 - Frontend UI
**Priority:** P2 (Medium)
**Status:** pending

## Overview
Implement download button for completed document.

## User Story
**As** User
**I want** download filled document
**So that** get final .docx file

## Acceptance Criteria
- [ ] Download button
- [ ] Success message
- [ ] Link to /download/{result_id}
- [ ] Option to start over

## Dependencies
- Depends on: story-frontend-setup
- Requires: story-download-api (backend)

## Technical Details

### Component Structure
```jsx
import { downloadFile } from '../api'

function DownloadBtn({ fileId }) {
  const handleDownload = () => {
    downloadFile(fileId)
  }

  const handleReset = () => {
    window.location.reload()
  }

  return (
    <div className="max-w-md mx-auto text-center">
      <div className="mb-6">
        <svg className="w-16 h-16 mx-auto text-green-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h2 className="text-2xl font-bold mb-2">Hoàn thành!</h2>
        <p className="text-gray-600">Tài liệu của bạn đã sẵn sàng</p>
      </div>

      <button
        onClick={handleDownload}
        className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 mb-4"
      >
        Tải xuống (.docx)
      </button>

      <button
        onClick={handleReset}
        className="w-full px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50"
      >
        Xử lý tài liệu khác
      </button>
    </div>
  )
}

export default DownloadBtn
```

## Definition of Done
- [ ] Download working
- [ ] UI displays correctly
- [ ] Reset functionality working
- [ ] Vietnamese text
