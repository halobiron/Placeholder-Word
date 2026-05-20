```markdown
# Placeholder-Word Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill introduces the core development patterns and workflows used in the Placeholder-Word repository, a Python-based project focused on document processing and placeholder/merge logic. You'll learn the project's coding conventions, how to coordinate multi-file backend hotfixes, update placeholder logic, and follow the established testing and commit practices. This guide is ideal for contributors aiming for consistency and efficiency in maintaining or extending the codebase.

## Coding Conventions

- **File Naming:**  
  All files use `snake_case` for readability and consistency.  
  _Example:_  
  ```
  docx_editor.py
  smart_mail_merge_converter.py
  batch_update_models.py
  ```

- **Import Style:**  
  Relative imports are preferred within the package.  
  _Example:_  
  ```python
  from .table_utils import extract_tables
  from .batch_operations import BatchProcessor
  ```

- **Export Style:**  
  Named exports are used; classes and functions are explicitly defined and imported as needed.  
  _Example:_  
  ```python
  # In template_manager.py
  class TemplateManager:
      ...

  # In another module
  from .template_manager import TemplateManager
  ```

- **Commit Messages:**  
  - Freeform style, often short (~17 characters on average).
  - Prefixes are not enforced.
  - For hotfixes, include terms like "hotfix" or "fix" in the message.

## Workflows

### Multi-file Backend Hotfix
**Trigger:** When a bug or issue affects multiple backend modules and requires coordinated changes.  
**Command:** `/multi-backend-hotfix`

1. **Identify** all backend modules affected by the bug or issue.
2. **Edit** two or more of the following files as needed:
    - `backend/docx_editor.py`
    - `backend/smart_mail_merge_converter.py`
    - `backend/template_manager.py`
    - `backend/batch_operations.py`
    - `backend/table_utils.py`
3. **Commit** your changes with a message indicating a hotfix or fix.
    - _Example commit message:_  
      ```
      hotfix: fix merge logic in docx_editor and template_manager
      ```
4. **Test** the affected modules to ensure the bug is resolved.

### Update Placeholder or Merge Logic
**Trigger:** When you need to improve, fix, or extend placeholder handling or merge logic in document processing.  
**Command:** `/update-placeholder-logic`

1. **Edit** the following core files:
    - `backend/merge_executor.py`
    - `backend/smart_mail_merge_converter.py`
2. **Optionally update**:
    - `backend/batch_operations.py`
    - `backend/batch_update_models.py`
    if data flow or batch processing is affected.
3. **Test** your changes, focusing on placeholder handling and merge logic.
    - _Example:_  
      ```python
      # In merge_executor.py
      def execute_merge(template, data):
          # Updated placeholder logic
          ...
      ```
4. **Commit** with a descriptive message.
    - _Example commit message:_  
      ```
      update: improve placeholder parsing in merge_executor
      ```

## Testing Patterns

- **Framework:** Not explicitly detected; testing framework is unknown.
- **File Pattern:** Test files follow the `*.test.*` naming convention.
    - _Example:_  
      ```
      test_merge_executor.test.py
      docx_editor.test.py
      ```
- **Best Practice:** Place tests alongside or near the modules they cover, and ensure all new or updated logic is covered by relevant test cases.

## Commands

| Command                     | Purpose                                                        |
|-----------------------------|----------------------------------------------------------------|
| /multi-backend-hotfix       | Coordinate and apply hotfixes across multiple backend modules.  |
| /update-placeholder-logic   | Update or improve placeholder and merge logic in the backend.   |
```
