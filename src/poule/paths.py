"""Platform-specific data directory helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def get_data_dir() -> Path:
    """Return the platform-specific data directory for poule.

    - macOS: ~/Library/Application Support/poule/
    - Linux: ~/.local/share/poule/
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "poule"
    return Path.home() / ".local" / "share" / "poule"


def get_model_dir() -> Path:
    """Return the directory for model checkpoints."""
    return get_data_dir() / "models"
