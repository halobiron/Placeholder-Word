---
name: update-placeholder-or-merge-logic
description: Workflow command scaffold for update-placeholder-or-merge-logic in Placeholder-Word.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /update-placeholder-or-merge-logic

Use this workflow when working on **update-placeholder-or-merge-logic** in `Placeholder-Word`.

## Goal

Update logic related to placeholders or merge operations, typically involving merge_executor.py and smart_mail_merge_converter.py, sometimes with batch_operations.py or batch_update_models.py.

## Common Files

- `backend/merge_executor.py`
- `backend/smart_mail_merge_converter.py`
- `backend/batch_operations.py`
- `backend/batch_update_models.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Edit merge_executor.py and smart_mail_merge_converter.py.
- Optionally update batch_operations.py or batch_update_models.py if data flow is affected.
- Test changes, especially for placeholder handling.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.