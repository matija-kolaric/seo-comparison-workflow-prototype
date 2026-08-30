#!/usr/bin/env python3
"""Run the workflow CLI from a source checkout without installing the package."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seobility_workflow.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
