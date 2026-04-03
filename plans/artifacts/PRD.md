# Product Requirements Document - Mail Merge Placeholder System

## Overview
Web application demo chuyển đổi file Word có vùng trống (dấu chấm, gạch dưới) thành Microsoft Word Mail Merge templates, sau đó điền dữ liệu bằng AI.

**Target Integration**: Sau khi demo thành công, tích hợp vào `ai-server-xbot`

## Problem Statement
Biểu mẫu tiếng Việt sử dụng dấu chấm/gạch dưới để tạo chỗ trống:
```
Tôi tên: ........ Số CMND: ........
[Hà Nội], ngày... tháng... năm 20...
□ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: .................
```

**Pain points:**
- Manual điền dữ liệu tốn thời gian
- Khó tự động hóa do format không chuẩn
- Cần inteligent field naming theo context tiếng Việt

## Solution
Web app: Upload .docx → Auto convert → Fill data → Download

## User Stories

### US1: Upload & Convert
**As** người dùng biểu mẫu
**I want** upload file .docx có dấu chấm
**So that** tự động chuyển thành Mail Merge template

**Acceptance Criteria:**
- Upload .docx file success
- Detect tất cả placeholders (dots, underscores, checkboxes)
- Smart field naming với Gemini AI (tiếng Việt)
- Return .docx mail merge template

### US2: Fill & Download
**As** người dùng
**I want** cung cấp context và điền template
**So that** nhận file .docx đã điền dữ liệu

**Acceptance Criteria:**
- Input: template + context (text hoặc JSON)
- Parse context với Gemini AI
- Map fields → data
- Execute mail merge
- Download .docx kết quả

## Functional Requirements

### FR1: Placeholder Detection
- Regex pattern: `([._…]{2,}(?:\s+[._…]{2,})*)`
- Greedy matching (không tạo adjacent fields)
- Multi-line placeholder support
- Fragmented text handling (DOCX splits across `<w:r>`)

### FR2: Smart Field Naming
**Priority:**
1. Inline context: Label before colon/dash
2. Time context: ngay, thang, nam
3. Section context: Heading name
4. Fallback: field_1, field_2...

**Rules:**
- Slugify: snake_case, remove accents
- Max 3-4 words
- De-duplicate: _2, _3 suffix
- Remove noise: (nếu có), (ghi rõ...)

### FR3: XML Surgical Injection
- Build offset map của runs (w:r)
- Preserve formatting (Bold, Italic, Size...)
- Inject `<w:fldSimple w:instr=" MERGEFIELD {field} \* MERGEFORMAT ">`
- No namespaces in xpath

### FR4: Mail Merge Execution
- Use `docx-mailmerge2==1.0.1`
- Validate fields before merge
- Handle missing fields error

## Non-Functional Requirements

### NFR1: Performance
- Convert single .docx: < 10s
- API response: < 5s (network excluded)

### NFR2: Vietnamese Support
- First-class language support
- Proper accent handling
- Context-aware field naming

### NFR3: Security
- File upload limit: 10MB
- Virus scan (future)
- API key authentication (when integrated)

### NFR4: Maintainability
- Class-based architecture
- Exception handling
- Code comments at regex/XML manipulation
- < 200 lines per file

## API Endpoints

### POST /convert
Upload .docx → Create mail merge template

**Request:**
- File: .docx

**Response:**
```json
{
  "template_id": "uuid",
  "fields": ["ho_ten", "so_cmnd", "ngay", "thang", "nam"],
  "download_url": "/download/{id}"
}
```

### POST /merge
Template + Context → Final .docx

**Request:**
```json
{
  "template_id": "uuid",
  "context": "Tôi là Nguyễn Văn A..."
}
```

**Response:**
```json
{
  "result_id": "uuid",
  "download_url": "/download/{id}"
}
```

### GET /download/{id}
Download generated file

## Tech Stack

### Backend
- FastAPI (Python 3.10+)
- python-docx + lxml (DOCX manipulation)
- docx-mailmerge2 (v1.0.1)
- Gemini API (Smart field naming)

### Frontend
- React + Vite
- TailwindCSS
- React Dropzone

## Success Metrics

- Convert accuracy: > 95% placeholders detected
- Field naming relevance: > 80% correct (user feedback)
- End-to-end time: < 30s per document
- Demo success → Integration into ai-server-xbot

## Dependencies & Risks

### Dependencies
- Gemini API availability
- docx-mailmerge2 v1.0.1 compatibility

### Risks
- Complex Vietnamese text patterns
- DOCX fragmentation edge cases
- Gemini API rate limits

### Mitigation
- Comprehensive test cases (multi-line, checkboxes, dates)
- Offset mapping for fragmented text
- Caching + fallback logic

## Roadmap

### Phase 1: Backend Core (Week 1)
- [ ] FastAPI setup
- [ ] MailMergeProcessor class
- [ ] GeminiClient integration
- [ ] File upload/download

### Phase 2: Frontend UI (Week 2)
- [ ] React + Vite setup
- [ ] Upload interface
- [ ] Context input form
- [ ] Download button

### Phase 3: Integration & Testing (Week 3)
- [ ] MergeExecutor
- [ ] End-to-end testing
- [ ] Vietnamese forms test cases

### Phase 4: Port to ai-server-xbot (Week 4)
- [ ] Move to utils/mail_merge/
- [ ] Create API endpoints
- [ ] Test with existing infrastructure

## Out of Scope

- Database (demo uses local files)
- User authentication (demo only)
- Batch processing
- Multiple file formats (DOCX only)
- Custom field mapping UI (auto via Gemini)
