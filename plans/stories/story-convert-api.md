# Story: Convert API Endpoint

**ID:** story-convert-api
**Epic:** Phase 1 - Backend Core
**Priority:** P1 (High)
**Status:** pending

## Overview
Implement POST /convert endpoint for uploading .docx and converting to mail merge template.

## User Story
**As** User
**I want** upload .docx file
**So that** get mail merge template with smart field names

## Acceptance Criteria
- [ ] POST /convert endpoint working
- [ ] Accept .docx file upload
- [ ] Validate file type and size (< 10MB)
- [ ] Call MailMergeProcessor.convert_to_mail_merge()
- [ ] Save template to uploads/templates/
- [ ] Return template_id + fields list
- [ ] Error handling for invalid files

## Dependencies
- Depends on: story-backend-setup, story-xml-injection

## Technical Details

### Endpoint
```python
@app.post("/convert")
async def convert_to_template(
    file: UploadFile = File(...)
) -> JSONResponse:
    """Upload .docx → Create mail merge template

    Returns:
        {
            "template_id": "uuid",
            "fields": ["ho_ten", "so_cmnd", "ngay", "thang", "nam"],
            "download_url": "/download/{template_id}"
        }
    """
```

### Validation
```python
# File type
if not file.filename.endswith('.docx'):
    raise HTTPException(400, "Only .docx files allowed")

# File size
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
content = await file.read()
if len(content) > MAX_FILE_SIZE:
    raise HTTPException(400, "File too large (max 10MB)")
```

### File Storage
```python
import uuid
from pathlib import Path

template_id = str(uuid.uuid4())
template_path = UPLOAD_DIR / "templates" / f"{template_id}.docx"
template_path.write_bytes(content)
```

## Definition of Done
- [ ] Endpoint working via Postman/curl
- [ ] Returns valid JSON
- [ ] Template file saved correctly
- [ ] Fields list matches detected placeholders
- [ ] Error handling tested
