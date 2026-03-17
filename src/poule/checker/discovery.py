"""File discovery and _CoqProject parsing for project-wide checking.

Spec: specification/independent-proof-checking.md, Section 4.6.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def parse_coqproject(content: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Parse _CoqProject content into load paths and include paths.

    Recognizes -Q, -R, and -I directives. Ignores comment lines (starting
    with #) and unrecognized directives.

    Returns (load_paths, include_paths) where load_paths is a list of
    (logical_prefix, physical_directory) tuples.

    Raises no exceptions; malformed lines are silently skipped.
    """
    load_paths: List[Tuple[str, str]] = []
    include_paths: List[str] = []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        directive = parts[0]

        if directive in ("-Q", "-R") and len(parts) >= 3:
            physical = parts[1]
            logical = parts[2]
            load_paths.append((logical, physical))
        elif directive == "-I" and len(parts) >= 2:
            include_paths.append(parts[1])
        # Unrecognized directives are silently ignored

    return load_paths, include_paths


def discover_vo_files(
    directory: str,
    load_paths: List[Tuple[str, str]] | None = None,
) -> List[str]:
    """Discover .vo files in a directory tree.

    If load_paths are provided, walks directories referenced by load path
    entries. Otherwise, walks the entire directory recursively.

    Returns a list of absolute paths to .vo files.
    Skips directories that raise permission errors.
    """
    vo_files: List[str] = []
    root = Path(directory)

    if load_paths:
        # Walk directories referenced by load path entries
        dirs_to_walk = set()
        for _, physical in load_paths:
            phys_path = Path(physical)
            if not phys_path.is_absolute():
                phys_path = root / phys_path
            dirs_to_walk.add(str(phys_path))

        for d in dirs_to_walk:
            vo_files.extend(_walk_for_vo(d))
    else:
        vo_files.extend(_walk_for_vo(str(root)))

    return sorted(vo_files)


def _walk_for_vo(directory: str) -> List[str]:
    """Walk a directory tree collecting .vo files, skipping permission errors."""
    vo_files: List[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(directory):
            for fname in filenames:
                if fname.endswith(".vo"):
                    vo_files.append(os.path.join(dirpath, fname))
    except PermissionError:
        logger.warning("Permission denied accessing %s; skipping", directory)
    return vo_files
