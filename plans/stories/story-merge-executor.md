# Story: Merge Executor

**ID:** story-merge-executor
**Epic:** Phase 3 - Integration & Testing
**Priority:** P1 (High)
**Status:** pending

## Overview
Implement mail merge execution to fill templates with data.

## User Story
**As** System
**I want** fill mail merge template with data
**So that** generate final .docx with user data

## Acceptance Criteria
- [ ] MergeExecutor class implemented
- [ ] execute_merge() method working
- [ ] Validate fields before merge
- [ ] Use docx-mailmerge2 library
- [ ] Handle missing fields error
- [ ] Save result to uploads/results/

## Dependencies
- Depends on: story-backend-setup

## Technical Details

### Implementation
```python
from mailmerge import MailMerge

class MergeExecutor:
    def execute_merge(self, template_path: str, data: dict) -> str:
        """Fill mail merge template with data

        Args:
            template_path: Path to mail merge template
            data: {field_name: value}

        Returns:
            Path to merged document

        Raises:
            ValueError: If missing required fields
        """
        document = MailMerge(template_path)

        # Validate fields
        template_fields = document.get_merge_fields()
        missing = set(template_fields) - set(data.keys())

        if missing:
            raise ValueError(f"Missing fields: {missing}")

        # Merge
        document.merge(**data)

        # Save
        result_path = self._generate_result_path()
        document.write(result_path)

        return result_path
```

### Validation
```python
def _validate_fields(self, template_fields: list, data: dict):
    """Check if all required fields are present in data"""
    missing = set(template_fields) - set(data.keys())

    if missing:
        raise ValueError(
            f"Missing required fields: {', '.join(missing)}. "
            f"Template requires: {template_fields}"
        )
```

## Test Cases
```python
# Case 1: Valid merge
Template: ["ho_ten", "so_cmnd"]
Data: {"ho_ten": "Nguyen Van A", "so_cmnd": "123456"}
→ Success

# Case 2: Missing field
Template: ["ho_ten", "so_cmnd"]
Data: {"ho_ten": "Nguyen Van A"}
→ ValueError: Missing field 'so_cmnd'

# Case 3: Extra data
Template: ["ho_ten"]
Data: {"ho_ten": "A", "extra": "ignored"}
→ Success (extra ignored)
```

## Definition of Done
- [ ] MergeExecutor working
- [ ] Field validation working
- [ ] Generates valid .docx
- [ ] Error handling tested
- [ ] Test cases passing
