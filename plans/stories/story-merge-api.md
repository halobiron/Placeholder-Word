# Story: Merge API Endpoint

**ID:** story-merge-api
**Epic:** Phase 3 - Integration & Testing
**Priority:** P1 (High)
**Status:** pending

## Overview
Implement POST /merge endpoint for filling templates with context data.

## User Story
**As** User
**I want** provide context data
**So that** get filled .docx document

## Acceptance Criteria
- [ ] POST /merge endpoint working
- [ ] Accept template_id + context
- [ ] Parse context with Gemini AI
- [ ] Call MergeExecutor.execute_merge()
- [ ] Return result_id + download_url
- [ ] Error handling for missing/invalid templates

## Dependencies
- Depends on: story-merge-executor, story-gemini-client

## Technical Details

### Endpoint
```python
@app.post("/merge")
async def merge_template(
    template_id: str,
    context: str
) -> JSONResponse:
    """Fill mail merge template with context

    Args:
        template_id: UUID from /convert
        context: Text context (Vietnamese)

    Returns:
        {
            "result_id": "uuid",
            "download_url": "/download/{result_id}"
        }
    """
```

### Context Parsing
```python
# Use Gemini to extract structured data
gemini_client = GeminiClient(api_key=settings.GEMINI_API_KEY)

prompt = f"""Extract data from this Vietnamese text for mail merge.

Template fields: {template_fields}
Context: {context}

Return JSON with field names as keys."""
```

### Validation
```python
# Check template exists
template_path = UPLOAD_DIR / "templates" / f"{template_id}.docx"
if not template_path.exists():
    raise HTTPException(404, "Template not found")
```

## Definition of Done
- [ ] Endpoint working
- [ ] Context parsing working
- [ ] Merge execution working
- [ ] Returns valid JSON
- [ ] Error handling tested
