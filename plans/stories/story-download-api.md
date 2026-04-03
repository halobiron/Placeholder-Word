# Story: Download API Endpoint

**ID:** story-download-api
**Epic:** Phase 1 - Backend Core
**Priority:** P2 (Medium)
**Status:** pending

## Overview
Implement GET /download/{id} endpoint for downloading generated files.

## User Story
**As** User
**I want** download result file
**So that** get final .docx document

## Acceptance Criteria
- [ ] GET /download/{id} endpoint working
- [ ] Support template download
- [ ] Support result download
- [ ] Return FileResponse with correct headers
- [ ] Error handling for missing files

## Dependencies
- Depends on: story-backend-setup

## Technical Details

### Endpoint
```python
from fastapi.responses import FileResponse

@app.get("/download/{file_id}")
async def download_file(file_id: str) -> FileResponse:
    """Download template or result file

    Args:
        file_id: UUID of template or result

    Returns:
        .docx file download
    """
```

### File Resolution
```python
def _find_file(self, file_id: str) -> Path:
    """Find file in templates or results directories

    Args:
        file_id: UUID

    Returns:
        Path to file

    Raises:
        HTTPException: If file not found
    """
    # Check templates
    template_path = UPLOAD_DIR / "templates" / f"{file_id}.docx"
    if template_path.exists():
        return template_path

    # Check results
    result_path = UPLOAD_DIR / "results" / f"{file_id}.docx"
    if result_path.exists():
        return result_path

    raise HTTPException(404, "File not found")
```

### Response Headers
```python
return FileResponse(
    path=file_path,
    filename=f"document_{file_id}.docx",
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
```

## Definition of Done
- [ ] Endpoint working
- [ ] File download working
- [ ] Correct MIME type
- [ ] Error handling tested
