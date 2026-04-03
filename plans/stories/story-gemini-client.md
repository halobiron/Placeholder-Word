# Story: Gemini Client - Smart Field Naming

**ID:** story-gemini-client
**Epic:** Phase 1 - Backend Core
**Priority:** P0 (Blocker)
**Status:** pending

## Overview
Implement Gemini AI client for intelligent field naming based on Vietnamese context.

## User Story
**As** System
**I want** AI to name fields intelligently
**So that** field names are meaningful (ho_ten, ngay, thang, not field_1, field_2)

## Acceptance Criteria
- [ ] GeminiClient class implemented
- [ ] suggest_field_names() method works
- [ ] Priority 1: Inline context (label before : or -)
- [ ] Priority 2: Time context (ngày, tháng, năm)
- [ ] Priority 3: Section context (heading)
- [ ] Slugify: snake_case, remove accents
- [ ] Max 3-4 words per field name
- [ ] De-duplicate with _2, _3 suffix
- [ ] Remove noise: (nếu có), (ghi rõ...)

## Dependencies
- Depends on: story-backend-setup

## Technical Details

### Prompt Strategy
```python
prompt = f"""Analyze this Vietnamese text and suggest field names for placeholders.

Rules:
1. Priority 1 - Inline context: Check for label before colon (:) or dash (-)
2. Priority 2 - Time context: If "ngày", "tháng", "năm" before, use ngay, thang, nam
3. Priority 3 - Section context: Use heading name if line only has placeholder
4. Slugify to snake_case, remove accents, max 3-4 words
5. Remove noise: (nếu có), (ghi rõ...)

Context: {context}
Placeholders: {placeholders}

Return JSON mapping placeholder → field_name"""
```

### API
```python
class GeminiClient:
    def __init__(self, api_key: str)
    async def suggest_field_names(self, context: str, placeholders: list) -> dict
```

## Test Cases
```python
# Case 1: Inline context
"Tôi tên: ........"
→ {"ho_ten": "Tôi tên: ........"}

# Case 2: Time context
"[Hà Nội], ngày... tháng... năm 20..."
→ {"ngay": "ngày...", "thang": "tháng...", "nam": "năm 20..."}

# Case 3: Checkbox
"□ Khác: .................."
→ {"khac": "□ Khác: .................."}

# Case 4: De-duplication
"Lớp: ............ Trường: ............"
→ {"lop": "Lớp: ............", "truong": "Trường: ............"}
```

## Definition of Done
- [ ] Code implemented with class structure
- [ ] Gemini API integration working
- [ ] Returns JSON with field names
- [ ] Error handling for API failures
- [ ] Test cases passing
