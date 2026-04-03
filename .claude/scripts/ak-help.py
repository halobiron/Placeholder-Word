#!/usr/bin/env python3
"""
Backward-compatible wrapper for ak-help.

Canonical implementation lives at:
  .claude/skills/ak-help/scripts/ak-help.py
"""

import runpy
import sys
from pathlib import Path


def main() -> int:
    target = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "ak-help"
        / "scripts"
        / "ak-help.py"
    )

    if not target.exists():
        print(f"Error: canonical ak-help script not found: {target}", file=sys.stderr)
        return 1

    # Preserve argv; run canonical script as __main__.
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
