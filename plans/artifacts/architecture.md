# Architecture Design - Mail Merge Placeholder System

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (React)                     │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Upload  │→ │ ContextForm │→ │ DownloadBtn      │  │
│  │  .docx   │  │             │  │                  │  │
│  └──────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
                      ↓ HTTP
┌─────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                     │
│  ┌─────────────────────────────────────────────────┐   │
│  │  POST /convert    POST /merge    GET /download  │   │
│  └─────────────────────────────────────────────────┘   │
│                      ↓                                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │         MailMergeProcessor (Core Logic)          │   │
│  │  • Placeholder Detection                         │   │
│  │  • Offset Mapping                                │   │
│  │  • XML Surgical Injection                        │   │
│  └─────────────────────────────────────────────────┘   │
│                      ↓                                  │
│  ┌────────────────┐              ┌──────────────────┐  │
│  │ GeminiClient   │              │ MergeExecutor    │  │
│  │ (AI Field      │              │ (Fill Template)  │  │
│  │  Naming)       │              │                  │  │
│  └────────────────┘              └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Component Architecture

### Backend Components

#### 1. MailMergeProcessor (`mail_merge_processor.py`)

**Responsibility:** Convert .docx to Mail Merge template

**Key Methods:**
```python
class MailMergeProcessor:
    def __init__(self, gemini_api_key: str)
    async def convert_to_mail_merge(self, docx_path: str) -> dict
    def _build_offset_map(self, paragraph) -> dict
    def _find_placeholders(self, text: str) -> list
    def _inject_merge_fields(self, paragraph, fields, offset_map)
```

**Flow:**
```
1. Extract text from DOCX paragraphs
2. Build offset map (preserve formatting)
3. Find placeholders with regex
4. Call Gemini for field names
5. Inject <w:fldSimple> tags
6. Return template path + fields
```

#### 2. GeminiClient (`gemini_client.py`)

**Responsibility:** Smart field naming with context

**Key Methods:**
```python
class GeminiClient:
    def __init__(self, api_key: str)
    async def suggest_field_names(self, context, placeholders) -> dict
```

**Prompt Strategy:**
```
Priority 1: Inline context (label before : or -)
Priority 2: Time context (ngày, tháng, năm)
Priority 3: Section context (heading)
Rules: Slugify, remove accents, max 3-4 words
```

#### 3. MergeExecutor (`merge_executor.py`)

**Responsibility:** Execute mail merge with data

**Key Methods:**
```python
class MergeExecutor:
    def execute_merge(self, template_path: str, data: dict) -> str
    def _validate_fields(self, template, data)
```

**Library:** `docx-mailmerge2==1.0.1`

### Frontend Components

#### 1. App.jsx
State machine: upload → fill → download

#### 2. FileUpload.jsx
Drag-drop file upload with validation

#### 3. ContextForm.jsx
Text input for context data

#### 4. api.js
HTTP client for backend communication

## Data Flow

### Convert Flow
```
User uploads .docx
    ↓
FastAPI receives file
    ↓
MailMergeProcessor.process()
    ├→ Extract text
    ├→ Build offset map
    ├→ Find placeholders
    ├→ GeminiClient.suggest_field_names()
    └→ Inject <w:fldSimple>
    ↓
Save template locally
    ↓
Return template_id + fields list
```

### Merge Flow
```
User provides context
    ↓
FastAPI receives template_id + context
    ↓
GeminiClient.parse_context() → structured data
    ↓
MergeExecutor.execute_merge()
    ├→ Validate fields
    ├→ Merge data into template
    └→ Save result
    ↓
Return result_id
```

## Technical Specifications

### DOCX XML Structure
```xml
<w:p>
  <w:r>
    <w:rPr>
      <w:b/>  <!-- Bold -->
    </w:rPr>
    <w:t>Tôi tên:</w:t>
  </w:r>
  <w:r>
    <w:t>........</w:t>  <!-- Replace with <w:fldSimple> -->
  </w:r>
</w:p>
```

### Mail Merge Field XML
```xml
<w:r>
  <w:rPr>...</w:rPr>  <!-- Preserve formatting -->
  <w:fldSimple w:instr=" MERGEFIELD ho_ten \* MERGEFORMAT ">
    <w:w:r>
      <w:t>«ho_ten»</w:t>
    </w:w:r>
  </w:fldSimple>
</w:r>
```

### Regex Patterns
```python
# Placeholder detection
PLACEHOLDER_PATTERN = r'([._…]{2,}(?:\s+[._…]{2,})*)'

# Date patterns
DATE_PATTERN = r'(?i)(ngày|tháng|năm)\s*(20)?\s*$'

# Noise reduction
NOISE_PATTERN = r'\s*(\(nếu có\)|\(ghi rõ.*?\))\s*'
```

## File Structure

### Backend (Demo)
```
backend/
├── main.py                    # FastAPI app + endpoints
├── mail_merge_processor.py    # Core conversion logic
├── gemini_client.py           # AI integration
├── merge_executor.py          # Mail merge execution
├── requirements.txt
└── uploads/                   # Local file storage
    ├── templates/
    └── results/
```

### Frontend
```
frontend/
├── src/
│   ├── App.jsx
│   ├── components/
│   │   ├── FileUpload.jsx
│   │   ├── ContextForm.jsx
│   │   └── DownloadBtn.jsx
│   └── api.js
├── package.json
└── vite.config.js
```

## Integration with ai-server-xbot

### Path Mapping
```
Demo                          →  ai-server-xbot
─────────────────────────────────────────────────
backend/mail_merge_processor.py  →  modules/utils/mail_merge/processor.py
backend/gemini_client.py          →  modules/utils/mail_merge/field_analyzer.py
backend/merge_executor.py         →  modules/utils/mail_merge/executor.py
backend/main.py                   →  modules/api/v3/endpoints/mail_merge.py
```

### Reusable Components
```python
# Authentication
from api.v3.endpoints.docx_form import check_xgeni_tool_key

# Settings
from core.config import settings

# Logging
from loguru import logger

# File handling
# (existing infrastructure)
```

## Error Handling

### Backend
```python
class PlaceholderDetectionError(Exception)
class FieldNamingError(Exception)
class MergeExecutionError(Exception)
class InvalidTemplateError(Exception)
```

### Frontend
- File validation (.docx only, < 10MB)
- Network error handling
- User-friendly error messages

## Security Considerations

### Demo
- File size limit: 10MB
- File type validation
- Local file storage

### Production (ai-server-xbot)
- API key authentication
- Virus scanning
- TTL for uploaded files
- Secure file storage

## Testing Strategy

### Unit Tests
- Placeholder detection regex
- Field naming logic
- Offset mapping

### Integration Tests
- End-to-end conversion
- Merge execution
- API endpoints

### Test Cases (Vietnamese)
```
1. Multi-placeholder: "Tôi tên: ........ Số CMND: ........"
2. Date fields: "[Hà Nội], ngày... tháng... năm 20..."
3. Checkboxes: "□ Khác: .................."
4. Multi-line: Dòng nối tiếp chỉ toàn dấu chấm
5. Fragmented text: DOCX text split across <w:r>
```

## Performance Optimization

### Caching
- Gemini API responses (TTL: 1 hour)
- Processed templates

### Async Processing
- Non-blocking Gemini calls
- Background merge tasks

### Resource Management
- Clean up uploaded files (TTL: 24 hours)
- Connection pooling for APIs

## Deployment

### Demo (Standalone)
```bash
# Backend
cd backend && uvicorn main:app --port 8000

# Frontend
cd frontend && npm run dev
```

### Production (ai-server-xbot)
- Add to existing FastAPI app
- Use existing infrastructure
- No additional deployment needed
