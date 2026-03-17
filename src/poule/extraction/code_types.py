"""Data types for code extraction management.

Separate from existing types.py to avoid name collisions with the
extraction pipeline types.

Spec: specification/code-extraction-management.md, Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ExtractionRequest:
    """Request to extract a Coq definition to a target language.

    Fields per Section 5 of the specification.
    """

    session_id: str
    definition_name: str
    language: str  # "OCaml" | "Haskell" | "Scheme"
    recursive: bool = False
    output_path: Optional[str] = None


@dataclass
class ExtractionResult:
    """Successful extraction result.

    Fields per Section 5 of the specification.
    """

    definition_name: str
    language: str  # "OCaml" | "Haskell" | "Scheme"
    recursive: bool
    code: str
    warnings: List[str] = field(default_factory=list)
    output_path: Optional[str] = None


@dataclass
class CodeExtractionError:
    """Classified extraction failure.

    Named CodeExtractionError (not ExtractionError) to avoid collision
    with poule.extraction.errors.ExtractionError.

    Fields per Section 5 of the specification.
    """

    definition_name: str
    language: str  # "OCaml" | "Haskell" | "Scheme"
    category: str  # one of the six categories from Section 4.5
    raw_error: str
    explanation: str
    suggestions: List[str] = field(default_factory=list)


@dataclass
class WriteConfirmation:
    """Confirmation of a successful file write.

    Fields per Section 4.4 / Section 9 of the specification.
    """

    output_path: str
    bytes_written: int
