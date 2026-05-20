---
name: multi-file-backend-hotfix
description: Workflow command scaffold for multi-file-backend-hotfix in Placeholder-Word.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /multi-file-backend-hotfix

Use this workflow when working on **multi-file-backend-hotfix** in `Placeholder-Word`.

## Goal

Apply hotfixes or bugfixes that require coordinated changes across multiple backend modules, often including docx_editor.py, smart_mail_merge_converter.py, and template_manager.py.

## Common Files

- `backend/docx_editor.py`
- `backend/smart_mail_merge_converter.py`
- `backend/template_manager.py`
- `backend/batch_operations.py`
- `backend/table_utils.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Identify related backend modules affected by the bug.
- Edit 2 or more of: docx_editor.py, smart_mail_merge_converter.py, template_manager.py, batch_operations.py, table_utils.py.
- Commit changes with a message indicating hotfix or fix.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.