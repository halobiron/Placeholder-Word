# Story: XML Surgical Injection

**ID:** story-xml-injection
**Epic:** Phase 1 - Backend Core
**Priority:** P0 (Blocker)
**Status:** pending

## Overview
Implement XML surgical injection to replace placeholders with `<w:fldSimple>` mail merge fields.

## User Story
**As** System
**I want** inject mail merge fields into DOCX
**So that** Microsoft Word can recognize and fill them

## Acceptance Criteria
- [ ] Inject `<w:fldSimple w:instr=" MERGEFIELD {field} \* MERGEFORMAT ">`
- [ ] Preserve original formatting from offset map
- [ ] Replace placeholder text with field
- [ ] Use lxml for XML manipulation
- [ ] No namespaces in xpath (use `w:` prefix directly)
- [ ] Handle fragmented runs (merge/split as needed)

## Dependencies
- Depends on: story-placeholder-detector, story-gemini-client

## Technical Details

### XML Structure
```xml
<!-- Before -->
<w:r>
  <w:rPr><w:b/></w:rPr>  <!-- Bold -->
  <w:t>........</w:t>
</w:r>

<!-- After -->
<w:r>
  <w:rPr><w:b/></w:rPr>  <!-- Preserve formatting -->
  <w:fldSimple w:instr=" MERGEFIELD ho_ten \* MERGEFORMAT ">
    <w:r>
      <w:t>«ho_ten»</w:t>
    </w:r>
  </w:fldSimple>
</w:r>
```

### Implementation
```python
def _inject_merge_fields(self, paragraph, fields: dict, offset_map: dict):
    """Inject mail merge fields using lxml

    Args:
        paragraph: docx paragraph object
        fields: {placeholder: field_name}
        offset_map: {position: {text, format}}
    """
    # 1. Get paragraph XML
    p_element = paragraph._p

    # 2. Build new runs list
    new_runs = []

    # 3. For each run in original order
    for run in paragraph.runs:
        # Check if run contains placeholder
        # Replace with <w:fldSimple>
        # Preserve formatting
        pass

    # 4. Remove old runs, insert new runs
    # 5. Using lxml etree operations
```

### lxml Operations
```python
from lxml import etree

# No namespaces!
field_element = etree.SubElement(w:r, 'w:fldSimple')
field_element.set('w:instr', f' MERGEFIELD {field_name} \\* MERGEFORMAT ')

# Add text
w_r = etree.SubElement(field_element, 'w:r')
w_t = etree.SubElement(w_r, 'w:t')
w_t.text = f'«{field_name}»'
```

## Test Cases
```python
# Case 1: Simple replacement
Input: "Tôi tên: ........"
Output: "Tôi tên: «ho_ten»"

# Case 2: Preserve formatting
Input: Bold "........"
Output: Bold "«ho_ten»"

# Case 3: Multiple fields
Input: "Tôi tên: ........ Số CMND: ........"
Output: "Tôi tên: «ho_ten» Số CMND: «so_cmnd»"

# Case 4: Fragmented runs
Input: Split across <w:r>
Output: Merge into single <w:fldSimple>
```

## Definition of Done
- [ ] XML injection working
- [ ] Formatting preserved
- [ ] Valid DOCX output (opens in Word)
- [ ] Word recognizes mail merge fields
- [ ] Test cases passing
