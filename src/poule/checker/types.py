"""Data model types for the Proof Checker Adapter.

Spec: specification/independent-proof-checking.md, Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CheckRequest:
    """Input to the proof checker adapter."""

    mode: str  # "single" or "project"
    file_path: Optional[str] = None
    project_dir: Optional[str] = None
    include_paths: List[str] = field(default_factory=list)
    load_paths: List[Tuple[str, str]] = field(default_factory=list)
    timeout_seconds: int = 300


@dataclass
class CheckResult:
    """Output from the proof checker adapter."""

    status: str  # "pass", "fail", or "error"
    files_checked: int = 0
    files_passed: int = 0
    files_failed: int = 0
    failures: List[CheckFailure] = field(default_factory=list)
    stale_files: List[str] = field(default_factory=list)
    wall_time_ms: int = 0
    raw_output: str = ""


@dataclass
class CheckFailure:
    """One failed file in a check result."""

    file_path: str
    module_name: Optional[str] = None
    definition: Optional[str] = None
    failure_kind: str = "unknown"  # inconsistency, missing_dependency, axiom_mismatch, type_error, unknown
    raw_message: str = ""
