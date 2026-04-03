# Story: Context Form Component

**ID:** story-context-form-component
**Epic:** Phase 2 - Frontend UI
**Priority:** P1 (High)
**Status:** pending

## Overview
Implement context input form for providing data to fill template.

## User Story
**As** User
**I want** enter context data
**So that** generate filled document

## Acceptance Criteria
- [ ] Textarea for context input
- [ ] Display detected fields from template
- [ ] Show placeholder instructions
- [ ] Submit button to call /merge
- [ ] Loading state during merge
- [ ] Error handling

## Dependencies
- Depends on: story-frontend-setup
- Requires: story-merge-api (backend)

## Technical Details

### Component Structure
```jsx
import { useState } from 'react'
import { mergeTemplate } from '../api'

function ContextForm({ fileId, fields, onNext }) {
  const [context, setContext] = useState('')
  const [merging, setMerging] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!context.trim()) {
      setError('Vui lòng nhập context')
      return
    }

    setMerging(true)
    setError(null)

    try {
      const result = await mergeTemplate(fileId, context)
      onNext(result.result_id)
    } catch (err) {
      setError('Merge thất bại: ' + err.message)
    } finally {
      setMerging(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Nhập dữ liệu</h2>

      <div className="bg-blue-50 p-4 rounded mb-4">
        <p className="font-semibold mb-2">Các trường đã phát hiện:</p>
        <div className="flex flex-wrap gap-2">
          {fields.map(field => (
            <span key={field} className="px-3 py-1 bg-white rounded text-sm">
              {field}
            </span>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="Ví dụ: Tôi là Nguyễn Văn A, sinh ngày 01/01/1990, số CMND: 123456789..."
          className="w-full h-64 p-4 border rounded-lg focus:ring-2 focus:ring-blue-500"
          disabled={merging}
        />

        <button
          type="submit"
          disabled={merging || !context.trim()}
          className="mt-4 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {merging ? 'Đang xử lý...' : 'Tạo tài liệu'}
        </button>
      </form>

      {error && (
        <div className="mt-4 p-4 bg-red-50 text-red-700 rounded">
          {error}
        </div>
      )}
    </div>
  )
}

export default ContextForm
```

## Definition of Done
- [ ] Form displays fields
- [ ] Text input working
- [ ] API integration working
- [ ] Loading state working
- [ ] Error handling tested
- [ ] Vietnamese labels and placeholders
