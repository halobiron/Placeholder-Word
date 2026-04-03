# Story: Placeholder Detection & Offset Mapping

**ID:** story-placeholder-detector
**Epic:** Phase 1 - Backend Core
**Priority:** P0 (Blocker)
**Status:** pending

## Overview
Implement placeholder detection regex and offset mapping for DOCX fragmented text handling.

## User Story
**As** System
**I want** detect all placeholders accurately
**So that** can convert them to mail merge fields

## Acceptance Criteria
- [ ] Placeholder regex: `([._…]{2,}(?:\s+[._…]{2,})*)`
- [ ] Greedy matching (no adjacent meaningless fields)
- [ ] Multi-line placeholder support
- [ ] Offset mapping for fragmented text
- [ ] Preserve formatting (Bold, Italic, Size...)
- [ ] Build offset map from <w:r> runs

## Dependencies
- Depends on: story-backend-setup

## Technical Details

### Regex Patterns
```python
PLACEHOLDER_PATTERN = r'([._…]{2,}(?:\s+[._…]{2,})*)'
MULTI_LINE_PATTERN = r'([._…]{2,}(?:\s+[._…]{2,})*\s*\n\s*[._…]{2,})'
NOISE_PATTERN = r'\s*(\(nếu có\)|\(ghi rõ.*?\))\s*'
```

### Offset Mapping
```python
def _build_offset_map(self, paragraph) -> dict:
    """Map runs → positions + formatting

    Returns:
        {
            0: {"text": "Tôi tên:", "format": {...}},
            8: {"text": "........", "format": {...}},
            ...
        }
    """
```

### Fragmented Text Handling
DOCX splits text across multiple `<w:r>` tags:
```xml
<w:r><w:t>Tôi</w:t></w:r>
<w:r><w:t> </w:t></w:r>
<w:r><w:t>tên:</w:t></w:r>
<w:r><w:t>.</w:t></w:r>
<w:r><w:t>......</w:t></w:r>
```

Must rebuild to: "Tôi tên: ......." for regex detection

## Test Cases
```python
# Case 1: Simple placeholder
"Tôi tên: ........"
→ ["........"]

# Case 2: Multi-placeholder
"Tôi tên: ........ Số CMND: ........"
→ ["........", "........"]

# Case 3: Checkbox
"□ Khác: .................."
→ [".................."]

# Case 4: Multi-line
"Địa chỉ: ..................................\n         ................................................................"
→ One placeholder spanning 2 lines

# Case 5: Date
"[Hà Nội], ngày... tháng... năm 20..."
→ ["...", "...", "20..."]
```

## Definition of Done
- [ ] Regex patterns implemented
- [ ] Offset mapping working
- [ ] Handles fragmented text
- [ ] Test cases passing
- [ ] Performance: < 1s per paragraph
