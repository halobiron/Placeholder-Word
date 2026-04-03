"""
Merge Executor - Execute mail merge with data
Fills mail merge templates with provided data
"""
import uuid
from pathlib import Path
from typing import Dict
from mailmerge import MailMerge


class MergeExecutor:
    """Execute mail merge operations"""

    def __init__(self, result_dir: str = None):
        """Initialize executor

        Args:
            result_dir: Directory to save merged documents
        """
        if result_dir is None:
            self.result_dir = Path("backend/uploads/results")
        else:
            self.result_dir = Path(result_dir)

        # Ensure directory exists
        self.result_dir.mkdir(parents=True, exist_ok=True)

    def execute_merge(self, template_path: str, data: Dict[str, str]) -> str:
        """Execute mail merge with provided data

        Args:
            template_path: Path to mail merge template
            data: Dict mapping field names to values

        Returns:
            Path to merged document

        Raises:
            ValueError: If template or data is invalid
        """
        # Validate template exists
        template_path = Path(template_path)
        if not template_path.exists():
            raise ValueError(f"Template not found: {template_path}")

        # Load template
        try:
            document = MailMerge(str(template_path))
        except Exception as e:
            raise ValueError(f"Failed to load template: {e}")

        # Get required fields
        template_fields = document.get_merge_fields()

        # Validate all fields are provided
        self._validate_fields(template_fields, data)

        # Execute merge
        try:
            document.merge(**data)
        except Exception as e:
            raise ValueError(f"Merge failed: {e}")

        # Generate result path
        result_id = str(uuid.uuid4())
        result_path = self.result_dir / f"{result_id}.docx"

        # Save merged document
        document.write(str(result_path))

        return str(result_path), result_id

    def _validate_fields(self, template_fields: list, data: Dict[str, str]):
        """Validate that all required fields are present in data

        Args:
            template_fields: List of fields in template
            data: Provided data

        Raises:
            ValueError: If any required field is missing
        """
        missing_fields = set(template_fields) - set(data.keys())

        if missing_fields:
            raise ValueError(
                f"Missing required fields: {', '.join(sorted(missing_fields))}. "
                f"Template requires: {', '.join(sorted(template_fields))}"
            )

    def get_template_fields(self, template_path: str) -> list:
        """Get list of fields in template

        Args:
            template_path: Path to template

        Returns:
            List of field names
        """
        try:
            document = MailMerge(template_path)
            return document.get_merge_fields()
        except Exception as e:
            raise ValueError(f"Failed to read template: {e}")
