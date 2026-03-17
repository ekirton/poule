"""Data types for the literate documentation adapter.

Spec: specification/literate-documentation.md, Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DocumentationRequest:
    """Input for single-file and proof-scoped documentation generation."""

    input_file: str
    format: str = "html"
    proof_name: Optional[str] = None
    output_path: Optional[str] = None
    custom_flags: list[str] = field(default_factory=list)
    timeout: Optional[int] = 120


@dataclass
class DocumentationResult:
    """Output for single-file and proof-scoped documentation generation."""

    status: str  # "success" or "failure"
    output_path: Optional[str] = None
    content: Optional[str] = None
    format: str = "html"
    error: Optional[dict[str, str]] = None


@dataclass
class BatchDocumentationRequest:
    """Input for batch documentation generation."""

    source_directory: str
    output_directory: str
    format: str = "html"
    custom_flags: list[str] = field(default_factory=list)
    timeout_per_file: Optional[int] = 120


@dataclass
class BatchDocumentationResult:
    """Output for batch documentation generation."""

    index_path: str
    output_directory: str
    results: list[FileOutcome]
    total: int
    succeeded: int
    failed: int
    error: Optional[dict[str, str]] = None


@dataclass
class FileOutcome:
    """Per-file result within a batch."""

    input_file: str
    output_file: Optional[str] = None
    status: str = "success"  # "success" or "failure"
    error: Optional[dict[str, str]] = None
