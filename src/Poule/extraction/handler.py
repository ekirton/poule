"""Code extraction handler for Coq/Rocq extraction commands.

Wraps Coq's Extraction and Recursive Extraction commands to extract
verified definitions to OCaml, Haskell, or Scheme.

Spec: specification/code-extraction-management.md
Architecture: doc/architecture/code-extraction-management.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

from Poule.extraction.code_types import (
    CodeExtractionError,
    ExtractionResult,
    WriteConfirmation,
)
from Poule.session.errors import SessionError


# ---------------------------------------------------------------------------
# Error classification patterns — ordered most-specific to least-specific
# (Section 4.5)
# ---------------------------------------------------------------------------

_ERROR_CATEGORIES = [
    (
        "opaque_term",
        re.compile(r"is not a defined object"),
        (
            "The definition or one of its dependencies is opaque "
            "(marked Qed instead of Defined, or behind an abstraction barrier). "
            "Coq cannot extract computational content from opaque terms."
        ),
        [
            "Change Qed to Defined if the proof is computational.",
            "Use Transparent {name}. to expose the term.",
            "Provide an Extract Constant directive mapping the opaque term to target language code.",
        ],
    ),
    (
        "axiom_without_realizer",
        re.compile(r"has no body"),
        (
            "An axiom used by the definition has no computational realizer. "
            "Extraction produces a stub that fails at runtime."
        ),
        [
            'Provide Extract Constant {axiom} => "{implementation}". to bind the axiom to target language code.',
            "Replace the axiom with a proven definition.",
        ],
    ),
    (
        "universe_inconsistency",
        re.compile(r"Universe inconsistency"),
        (
            "A universe constraint conflict prevents extraction, typically from "
            "mixing universe-polymorphic and monomorphic definitions."
        ),
        [
            "Check for universe-polymorphic definitions that conflict with monomorphic ones.",
            "Restructure the definition to avoid the inconsistency.",
        ],
    ),
    (
        "unsupported_match",
        re.compile(r"Cannot extract"),
        (
            "Coq's extraction mechanism does not support the match pattern used. "
            "Deep pattern matching on dependent types is a common trigger."
        ),
        [
            "Refactor the match to use simpler patterns.",
            "Introduce an auxiliary function that eliminates the problematic pattern.",
        ],
    ),
    (
        "module_type_mismatch",
        re.compile(r"Module type"),
        (
            "A module type mismatch prevents extraction due to misaligned "
            "module functors or signatures."
        ),
        [
            "Verify module signatures match expected types.",
            "Simplify module structure to avoid functor application issues.",
        ],
    ),
]

_UNKNOWN_EXPLANATION = (
    "Extraction failed for a reason not in the known categories. "
    "The raw Coq error is included for manual diagnosis."
)

_UNKNOWN_SUGGESTIONS = [
    "Consult the Coq reference manual for the specific error.",
    "Simplify the definition and retry extraction to isolate the cause.",
]


# ---------------------------------------------------------------------------
# Command construction — pure function (Section 4.2, Section 10)
# ---------------------------------------------------------------------------


def build_command(definition_name: str, language: str, recursive: bool) -> str:
    """Build the Coq extraction command sequence.

    Returns a string of the form:
        ``Extraction Language {lang}. [Recursive] Extraction {name}.``

    The definition name is included verbatim — no quoting, escaping, or
    qualification is applied (Section 4.2).
    """
    directive = f"Extraction Language {language}."
    if recursive:
        extraction = f"Recursive Extraction {definition_name}."
    else:
        extraction = f"Extraction {definition_name}."
    return f"{directive} {extraction}"


# ---------------------------------------------------------------------------
# Error classification (Section 4.5)
# ---------------------------------------------------------------------------


def _classify_error(
    stderr: str,
    definition_name: str,
    language: str,
) -> CodeExtractionError:
    """Classify a Coq extraction error by matching stderr patterns."""
    for category, pattern, explanation, suggestions in _ERROR_CATEGORIES:
        if pattern.search(stderr):
            return CodeExtractionError(
                definition_name=definition_name,
                language=language,
                category=category,
                raw_error=stderr,
                explanation=explanation,
                suggestions=list(suggestions),
            )
    # Unknown category
    return CodeExtractionError(
        definition_name=definition_name,
        language=language,
        category="unknown",
        raw_error=stderr,
        explanation=_UNKNOWN_EXPLANATION,
        suggestions=list(_UNKNOWN_SUGGESTIONS),
    )


# ---------------------------------------------------------------------------
# Result parsing (Section 4.3)
# ---------------------------------------------------------------------------


def _is_error(stderr: str) -> bool:
    """Return True if stderr contains an error (not just a warning)."""
    return "Error:" in stderr


def _is_warning_only(stderr: str) -> bool:
    """Return True if stderr contains only warnings, no errors."""
    return bool(stderr.strip()) and not _is_error(stderr)


def _parse_warnings(stderr: str) -> list[str]:
    """Extract individual warning lines from stderr."""
    if not stderr.strip():
        return []
    return [line.strip() for line in stderr.strip().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Output splitting — separate code from error/warning lines (Section 4.3)
# ---------------------------------------------------------------------------


def _split_output(combined: str) -> tuple[str, str]:
    """Split a combined coqtop output string into (stdout, stderr) components.

    The real SessionManager.submit_command returns a single string that
    merges stdout and stderr.  This function heuristically separates
    error/warning lines (which would have appeared on stderr) from
    extracted code (which would have appeared on stdout).

    Lines starting with "Error:" or "Warning:" (possibly preceded by
    whitespace or a filename/location prefix) are classified as stderr.
    Everything else is classified as stdout.
    """
    if not combined.strip():
        return ("", "")

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    for line in combined.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("Error:") or stripped.startswith("Warning:"):
            stderr_lines.append(line)
        else:
            stdout_lines.append(line)

    return ("".join(stdout_lines).strip(), "".join(stderr_lines).strip())


# ---------------------------------------------------------------------------
# Entry points (Section 4.1, Section 4.4, Section 10)
# ---------------------------------------------------------------------------


async def extract_code(
    session_manager,
    session_id: str,
    definition_name: str,
    language: str,
    recursive: bool = False,
    output_path: str | None = None,
) -> Union[ExtractionResult, CodeExtractionError]:
    """Extract a Coq definition to a target language.

    Constructs the extraction command, submits it to Coq via the session
    manager, and parses the result.

    Raises SessionError on SESSION_NOT_FOUND or BACKEND_CRASHED — these
    are not caught here; they propagate to the caller (Section 6).
    """
    cmd = build_command(definition_name, language, recursive)

    # Submit to Coq — SessionError propagates (Section 6, 7.1, 7.2)
    # submit_command returns str: the merged Coq output (Section 6)
    response = await session_manager.submit_command(session_id, cmd)

    # Split merged output into code vs error/warning lines (Section 4.3)
    stdout, stderr = _split_output(response)

    # Section 4.3 / 7.4: stderr error takes priority over stdout code
    if _is_error(stderr):
        return _classify_error(stderr, definition_name, language)

    # Section 4.3: non-fatal warnings
    warnings = _parse_warnings(stderr)

    # Section 7.4: empty stdout with no error
    if not stdout.strip():
        warnings.append("Empty extraction output")

    result = ExtractionResult(
        definition_name=definition_name,
        language=language,
        recursive=recursive,
        code=stdout,
        warnings=warnings,
        output_path=None,
    )

    # Write mode (Section 4.4)
    if output_path is not None:
        confirmation = write_extraction(stdout, output_path)
        result.output_path = confirmation.output_path

    return result


def write_extraction(code: str, output_path: str) -> WriteConfirmation:
    """Write extracted code to disk.

    REQUIRES: code is a non-empty string, output_path is an absolute path
    whose parent directory exists (Section 4.4).

    Raises ValueError with INVALID_OUTPUT_PATH for path validation failures.
    Raises OSError with WRITE_FAILED for filesystem errors.
    """
    p = Path(output_path)

    if not p.is_absolute():
        raise ValueError(f"INVALID_OUTPUT_PATH: output_path must be absolute, got: {output_path}")

    if not p.parent.exists():
        raise ValueError(
            f"INVALID_OUTPUT_PATH: parent directory does not exist: {p.parent}"
        )

    try:
        p.write_text(code)
    except OSError as exc:
        raise OSError(f"WRITE_FAILED: {exc}") from exc

    return WriteConfirmation(
        output_path=output_path,
        bytes_written=len(code.encode("utf-8")),
    )


# ---------------------------------------------------------------------------
# ExtractionHandler class (Section 10)
# ---------------------------------------------------------------------------


class ExtractionHandler:
    """Encapsulates extraction command construction, result parsing,
    error classification, and file writing.

    Provides an object-oriented facade over the module-level functions.
    """

    def __init__(self, session_manager) -> None:
        self._session_manager = session_manager

    @staticmethod
    def build_command(
        definition_name: str, language: str, recursive: bool
    ) -> str:
        return build_command(definition_name, language, recursive)

    async def extract_code(
        self,
        session_id: str,
        definition_name: str,
        language: str,
        recursive: bool = False,
        output_path: str | None = None,
    ) -> Union[ExtractionResult, CodeExtractionError]:
        return await extract_code(
            self._session_manager,
            session_id,
            definition_name,
            language,
            recursive,
            output_path,
        )

    @staticmethod
    def write_extraction(code: str, output_path: str) -> WriteConfirmation:
        return write_extraction(code, output_path)
