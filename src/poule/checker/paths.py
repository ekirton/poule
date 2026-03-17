"""Library path resolution and command construction for coqchk.

Spec: specification/independent-proof-checking.md, Sections 4.3 and 4.4.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def resolve_library_name(
    file_path: str,
    load_paths: List[Tuple[str, str]],
) -> str:
    """Resolve a .vo file path to a dot-separated logical library name.

    Finds the load path entry whose physical directory is a prefix of
    file_path, selects the longest match, strips the .vo extension,
    replaces path separators with dots, and prepends the logical prefix.

    When no load path matches, returns the bare filename without extension
    and emits a warning.
    """
    fp = Path(file_path)
    # Strip .vo extension
    base = str(fp.with_suffix(""))

    # Find matching load paths, select longest physical prefix
    best_logical = None
    best_physical = ""

    for logical, physical in load_paths:
        # Normalize physical path (remove trailing separator)
        phys = str(Path(physical))
        if base.startswith(phys + os.sep) or base.startswith(phys + "/"):
            if len(phys) > len(best_physical):
                best_physical = phys
                best_logical = logical

    if best_logical is not None:
        # Get relative path from the physical directory
        relative = base[len(best_physical):].lstrip(os.sep).lstrip("/")
        # Replace path separators with dots
        parts = relative.replace(os.sep, ".").replace("/", ".")
        return f"{best_logical}.{parts}"
    else:
        # Fallback: bare filename without extension
        logger.warning(
            "No load path matches file %s; using bare filename", file_path
        )
        return fp.stem


def build_command(
    coqchk_path: str,
    load_paths: List[Tuple[str, str]],
    include_paths: List[str],
    library_names: List[str],
) -> List[str]:
    """Build the coqchk argument vector.

    Returns [coqchk_path, load_path_flags..., include_flags..., library_names...].
    Each (logical, physical) pair produces -Q physical logical.
    Each include path produces -I path.
    """
    cmd: List[str] = [coqchk_path]

    for logical, physical in load_paths:
        cmd.extend(["-Q", physical, logical])

    for path in include_paths:
        cmd.extend(["-I", path])

    cmd.extend(library_names)

    return cmd
