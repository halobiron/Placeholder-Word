# Story: Frontend Setup & Basic UI

**ID:** story-frontend-setup
**Epic:** Phase 2 - Frontend UI
**Priority:** P1 (High)
**Status:** pending

## Overview
Initialize React + Vite frontend with TailwindCSS and basic structure.

## User Story
**As** User
**I want** clean web interface
**So that** easily upload and convert documents

## Acceptance Criteria
- [ ] React + Vite app running
- [ ] TailwindCSS configured
- [ ] Basic routing/state machine
- [ ] Components directory structure
- [ ] API client configured

## Dependencies
- None (parallel with backend)

## Technical Details

### Setup
```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install react-dropzone axios
```

### Directory Structure
```
frontend/
├── src/
│   ├── App.jsx
│   ├── main.jsx
│   ├── components/
│   │   ├── FileUpload.jsx
│   │   ├── ContextForm.jsx
│   │   └── DownloadBtn.jsx
│   └── api.js
├── package.json
└── vite.config.js
```

### App.jsx
```jsx
import { useState } from 'react'
import FileUpload from './components/FileUpload'
import ContextForm from './components/ContextForm'
import DownloadBtn from './components/DownloadBtn'

function App() {
  const [step, setStep] = useState('upload')
  const [fileId, setFileId] = useState(null)

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      {step === 'upload' && (
        <FileUpload onNext={(id) => { setFileId(id); setStep('fill') }} />
      )}
      {step === 'fill' && (
        <ContextForm fileId={fileId} onNext={() => setStep('download')} />
      )}
      {step === 'download' && <DownloadBtn fileId={fileId} />}
    </div>
  )
}

export default App
```

### api.js
```javascript
import axios from 'axios'

const API_BASE = 'http://localhost:8000'

export const convertDocx = async (file) => {
  const formData = new FormData()
  formData.append('file', file)

  const response = await axios.post(`${API_BASE}/convert`, formData)
  return response.data
}

export const mergeTemplate = async (templateId, context) => {
  const response = await axios.post(`${API_BASE}/merge`, {
    template_id: templateId,
    context
  })
  return response.data
}

export const downloadFile = (fileId) => {
  window.location.href = `${API_BASE}/download/${fileId}`
}
```

## Definition of Done
- [ ] App running on port 5173
- [ ] TailwindCSS styling working
- [ ] Component structure created
- [ ] API client configured
- [ ] No console errors
