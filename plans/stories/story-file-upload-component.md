# Story: File Upload Component

**ID:** story-file-upload-component
**Epic:** Phase 2 - Frontend UI
**Priority:** P1 (High)
**Status:** pending

## Overview
Implement drag-drop file upload component with validation.

## User Story
**As** User
**I want** upload .docx file easily
**So that** can start conversion process

## Acceptance Criteria
- [ ] Drag-drop file upload area
- [ ] Click to browse files
- [ ] Validate .docx file type
- [ ] Validate file size (< 10MB)
- [ ] Show upload progress
- [ ] Call API /convert endpoint
- [ ] Display detected fields after conversion
- [ ] Error handling for invalid files

## Dependencies
- Depends on: story-frontend-setup
- Requires: story-convert-api (backend)

## Technical Details

### Component Structure
```jsx
import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { convertDocx } from '../api'

function FileUpload({ onNext }) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0]

    // Validation
    if (!file.name.endsWith('.docx')) {
      setError('Chỉ chấp nhận file .docx')
      return
    }

    if (file.size > 10 * 1024 * 1024) {
      setError('File quá lớn (tối đa 10MB)')
      return
    }

    // Upload
    setUploading(true)
    setError(null)

    try {
      const result = await convertDocx(file)
      onNext(result.template_id, result.fields)
    } catch (err) {
      setError('Upload thất bại: ' + err.message)
    } finally {
      setUploading(false)
    }
  }, [onNext])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] },
    multiple: false
  })

  return (
    <div className="max-w-xl mx-auto">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer
          ${isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300'}
          ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <input {...getInputProps()} />

        {uploading ? (
          <p>Đang tải lên...</p>
        ) : (
          <>
            <p className="text-lg mb-2">
              {isDragActive ? 'Thả file vào đây' : 'Kéo thả file .docx vào đây'}
            </p>
            <p className="text-sm text-gray-500">
              hoặc click để chọn file
            </p>
          </>
        )}
      </div>

      {error && (
        <div className="mt-4 p-4 bg-red-50 text-red-700 rounded">
          {error}
        </div>
      )}
    </div>
  )
}

export default FileUpload
```

## Definition of Done
- [ ] Drag-drop working
- [ ] File validation working
- [ ] API integration working
- [ ] Progress indication
- [ ] Error handling tested
- [ ] Vietnamese text displayed correctly
