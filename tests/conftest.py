"""Pytest configuration helpers."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_on_path() -> None:
    """Make sure the project root is importable as a package."""

    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


_ensure_repo_on_path()

