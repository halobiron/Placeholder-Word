# Mail Merge Placeholder System - Architecture Design (Demo Version)

## Overview
Web app demo: Upload file Word → Tự động chuyển đổi vùng trống thành Mail Merge placeholders → Điền dữ liệu với Gemini AI.

**⚠️ Demo này được thiết kế để dễ dàng tích hợp vào `ai-server-xbot` sau khi thành công.**

## Current State of ai-server-xbot

Đã có sẵn:
- ✅ FastAPI framework với API v3
- ✅ DOCX processing utilities (`utils/docx_to_form/`)
- ✅ Gemini/OpenAI/xAI/Deepseek integration
- ✅ File upload/handling infrastructure
- ✅ API authentication (`xgeni-api-key`)
- ✅ TTLCache + Background tasks
- ✅ Logging với Loguru

**Còn thiếu**: Mail Merge fields conversion (`<w:fldSimple>`) theo `instructions.md`

## Tech Stack (Minimal)

**Backend**
```
FastAPI (Python 3.10+)
├── Gemini API (đã có trong ai-server-xbot)
├── python-docx + lxml
└── docx-mailmerge2
```

**Frontend**
```
React + Vite
├── TailwindCSS
└── React Dropzone
```

## Architecture

```
┌─────────────────────────────────────┐
│         Frontend (React)            │
│  Upload → Convert → Fill → Download │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│      Backend (FastAPI)              │
│  /convert  /merge  /download        │
└─────────────────────────────────────┘
    ↓           ↓           ↓
 Local      Gemini     docx-mailmerge
 Files        API
```

## Demo Project Structure

```
placeholder/
├── backend/
│   ├── main.py                    # FastAPI standalone (cho demo)
│   ├── mail_merge_processor.py    # Core logic từ instructions.md
│   │                              # → Sau này vào: utils/mail_merge/
│   ├── gemini_client.py           # Gemini integration
│   │                              # → Tái sử dụng từ core/config.py
│   ├── requirements.txt
│   └── uploads/                   # Local file storage
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── FileUpload.jsx
│   │   │   ├── ContextForm.jsx
│   │   │   └── DownloadBtn.jsx
│   │   └── api.js
│   └── package.json
├── instructions.md
└── ARCHITECTURE.md
```

## Integration Plan (sau demo thành công)

### Bước 1: Port code vào ai-server-xbot

```
ai-server-xbot/modules/
├── utils/
│   └── mail_merge/
│       ├── __init__.py
│       ├── processor.py           # Từ mail_merge_processor.py
│       │                          # Logic: Word → Mail Merge
│       ├── field_analyzer.py      # Field naming với Gemini
│       └── executor.py            # docx-mailmerge2 execution
├── api/v3/endpoints/
│   └── mail_merge.py              # API endpoints
│       ├── /upload                # Upload .docx
│       ├── /convert               # Convert to mail merge
│       ├── /merge                 # Fill data vào template
│       └── /download/{id}         # Download kết quả
└── api/v3/api.py                  # Add mail_merge_router
```

### Bước 2: Tái sử dụng components có sẵn

```python
# Từ ai-server-xbot/modules/api/v3/endpoints/mail_merge.py

from fastapi import APIRouter, UploadFile, File, Depends
from core.config import settings
from utils.mail_merge.processor import MailMergeProcessor
from utils.mail_merge.executor import MailMergeExecutor
from api.v3.endpoints.docx_form import check_xgeni_tool_key  # Tái dùng auth

mail_merge_router = APIRouter()

@mail_merge_router.post("/convert")
async def convert_to_template(
    _api_key: str = Depends(check_xgeni_tool_key),  # Tái dùng auth
    file: UploadFile = File(...)
):
    """Upload .docx → Tạo mail merge template"""
    processor = MailMergeProcessor(gemini_api_key=settings.GEMINI_API_KEY)
    result = await processor.convert_to_mail_merge(file)
    return result
```

### Bước 3: API Endpoints trong ai-server-xbot

```
/api/v3/mail-merge/upload           # Upload file .docx
/api/v3/mail-merge/convert          # Chuyển thành mail merge template
/api/v3/mail-merge/merge            # Điền dữ liệu vào template
/api/v3/mail-merge/download/{id}    # Download kết quả
```

## Key Components

### 1. Mail Merge Processor (`processor.py`)

```python
from docx import Document
from lxml import etree
import re

class MailMergeProcessor:
    """Convert .docx → Mail Merge template với <w:fldSimple>"""

    def __init__(self, gemini_api_key: str):
        self.gemini_client = GeminiClient(gemini_api_key)

    async def convert_to_mail_merge(self, docx_path: str) -> str:
        """
        Main pipeline theo instructions.md:
        1. Extract text from DOCX
        2. Find placeholder patterns (dots, underscores)
        3. Use Gemini to name fields intelligently
        4. Inject <w:fldSimple> tags with XML surgical injection
        """
        doc = Document(docx_path)

        for paragraph in doc.paragraphs:
            # Build offset map
            offset_map = self._build_offset_map(paragraph)

            # Find placeholders with regex
            placeholders = self._find_placeholders(paragraph.text)

            # Get field names from Gemini
            field_names = await self.gemini_client.suggest_field_names(
                context=paragraph.text,
                placeholders=placeholders
            )

            # Inject mail merge fields
            self._inject_merge_fields(paragraph, field_names, offset_map)

        return doc.save(output_path)

    def _build_offset_map(self, paragraph) -> dict:
        """Map runs → positions + formatting"""
        # Logic từ instructions.md
        pass

    def _find_placeholders(self, text: str) -> list:
        """Find patterns: ([._…]{2,}(?:\s+[._…]{2,})*)"""
        regex = r'([._…]{2,}(?:\s+[._…]{2,})*)'
        return re.findall(regex, text)

    def _inject_merge_fields(self, paragraph, fields: dict, offset_map: dict):
        """XML surgical injection with lxml"""
        # Logic từ instructions.md
        pass
```

### 2. Gemini Client (`gemini_client.py`)

```python
import google.generativeai as genai

class GeminiClient:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    async def suggest_field_names(self, context: str, placeholders: list) -> dict:
        """Suggest field names based on context (instructions.md)"""
        prompt = f"""Analyze this Vietnamese text and suggest field names for placeholders.

Rules:
1. Priority 1 - Inline context: Check for label before colon (:) or dash (-)
2. Priority 2 - Time context: If "ngày", "tháng", "năm" before, use ngay, thang, nam
3. Priority 3 - Section context: Use heading name if line only has placeholder
4. Slugify to snake_case, remove accents, max 3-4 words

Context: {context}
Placeholders: {placeholders}

Return JSON mapping placeholder → field_name"""

        response = await self.model.generate_content_async(prompt)
        return self._parse_response(response.text)
```

### 3. Merge Executor (`executor.py`)

```python
from mailmerge import MailMerge

class MergeExecutor:
    def execute_merge(self, template_path: str, data: dict) -> str:
        """Fill mail merge template with data (instructions.md Phase 2)"""
        document = MailMerge(template_path)

        # Validate fields
        template_fields = document.get_merge_fields()
        missing = set(template_fields) - set(data.keys())

        if missing:
            raise ValueError(f"Missing fields: {missing}")

        # Merge
        document.merge(**data)
        document.write(output_path)

        return output_path
```

## API Endpoints (Demo)

```python
# backend/main.py (standalone for demo)

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.post("/convert")
async def convert_to_template(file: UploadFile):
    """Upload .docx → Tạo mail merge template"""
    # Save file
    # Process with MailMergeProcessor
    # Return template file
    return FileResponse(template_path)

@app.post("/merge")
async def merge_template(template: UploadFile, context: str):
    """Template + Context → Final .docx"""
    # Parse context with Gemini
    # Fill template
    # Return final file
    return FileResponse(output_path)
```

## Frontend (React)

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
```

## Environment Variables

```bash
# .env (demo)
GEMINI_API_KEY=your_api_key_here
UPLOAD_DIR=./uploads
MAX_FILE_SIZE=10485760

# Sau khi tích hợp vào ai-server-xbot:
# Sử dụng settings.GEMINI_API_KEY (đã có sẵn)
```

## Development Steps

### Step 1: Backend Core (2-3 ngày)
- [ ] FastAPI standalone setup
- [ ] MailMergeProcessor (instructions.md Phase 1)
- [ ] GeminiClient integration
- [ ] File upload/download

### Step 2: Frontend UI (2-3 ngày)
- [ ] React + Vite setup
- [ ] Upload interface
- [ ] Context input form
- [ ] Download button

### Step 3: Integration & Testing (1-2 ngày)
- [ ] MergeExecutor (instructions.md Phase 2)
- [ ] End-to-end testing
- [ ] Demo với file mẫu

### Step 4: Port to ai-server-xbot (1 ngày)
- [ ] Move processor → `utils/mail_merge/`
- [ ] Create `api/v3/endpoints/mail_merge.py`
- [ ] Update `api/v3/api.py`
- [ ] Test với hệ thống có sẵn

## Running Demo

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Notes

**Demo standalone:**
- Không cần database
- File lưu local
- Auth đơn giản (hoặc không cần)

**Sau khi tích hợp:**
- Tái sử dụng `settings`, logger, auth
- Tái sử dụng file handling infrastructure
- Tái sử dụng Gemini API keys đã config
- Follow pattern của `docx_form_router`
