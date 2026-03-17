"""Alectryon subprocess adapter for interactive proof documentation generation.

Spec: specification/literate-documentation.md
Architecture: doc/architecture/literate-documentation.md
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from .types import (
    BatchDocumentationRequest,
    BatchDocumentationResult,
    DocumentationRequest,
    DocumentationResult,
    FileOutcome,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINIMUM_VERSION = (1, 3, 0)

FORMAT_TO_BACKEND = {
    "html": "webpage",
    "html-fragment": "webpage-no-header",
    "latex": "latex",
}

FORMAT_TO_EXTENSION = {
    "html": ".html",
    "html-fragment": ".html",
    "latex": ".tex",
}

DECLARATION_KEYWORDS = (
    "Theorem", "Lemma", "Definition", "Fixpoint",
    "Corollary", "Proposition", "Example", "Fact", "Remark",
)

PROOF_TERMINATORS = ("Qed.", "Defined.", "Admitted.")

# ---------------------------------------------------------------------------
# Availability cache
# ---------------------------------------------------------------------------

_availability_cache: Optional[str] = None  # "available", "not_installed", "version_too_old"


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like '1.4.0' into a tuple of ints."""
    parts = version_str.strip().split(".")
    result = []
    for p in parts:
        # Extract leading digits
        m = re.match(r"(\d+)", p)
        if m:
            result.append(int(m.group(1)))
    return tuple(result)


async def check_availability(*, _bypass_cache: bool = False) -> str:
    """Check whether Alectryon is installed and meets the minimum version.

    Returns one of: "available", "not_installed", "version_too_old".
    Results are cached after the first successful check.
    Pass _bypass_cache=True to force a fresh check (resets cache).
    """
    global _availability_cache

    if not _bypass_cache and _availability_cache is not None:
        return _availability_cache

    try:
        process = await asyncio.create_subprocess_exec(
            "alectryon", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if process.returncode != 0:
            _availability_cache = "not_installed"
            return _availability_cache

        version_str = stdout.decode().strip()
        version = _parse_version(version_str)

        if version < MINIMUM_VERSION:
            _availability_cache = "version_too_old"
        else:
            _availability_cache = "available"

        return _availability_cache

    except FileNotFoundError:
        _availability_cache = "not_installed"
        return _availability_cache


# ---------------------------------------------------------------------------
# Single-file generation
# ---------------------------------------------------------------------------


async def generate_documentation(request: DocumentationRequest) -> DocumentationResult:
    """Generate documentation for a single Coq source file.

    Spec: Section 4.2.
    """
    fmt = request.format
    input_path = Path(request.input_file)

    # --- Input validation ---

    # Reject non-.v files first
    if not request.input_file.endswith(".v"):
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "INVALID_INPUT",
                "message": f"Expected a .v file, got: {request.input_file}",
            },
        )

    # Reject relative paths
    if not input_path.is_absolute():
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "INVALID_INPUT",
                "message": f"Expected a .v file, got: {request.input_file}",
            },
        )

    # Check file existence
    if not input_path.exists():
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "FILE_NOT_FOUND",
                "message": f"File not found: {request.input_file}",
            },
        )

    # Check output directory existence
    if request.output_path is not None:
        output_parent = Path(request.output_path).parent
        if not output_parent.exists():
            return DocumentationResult(
                status="failure",
                format=fmt,
                error={
                    "code": "OUTPUT_DIR_NOT_FOUND",
                    "message": f"Output directory does not exist: {output_parent}",
                },
            )

    # --- Availability check ---

    availability = await check_availability()
    if availability == "not_installed":
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "ALECTRYON_NOT_FOUND",
                "message": (
                    "Alectryon is not installed or not on the system PATH. "
                    "Install it with: pip install alectryon"
                ),
            },
        )
    if availability == "version_too_old":
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "ALECTRYON_VERSION_UNSUPPORTED",
                "message": (
                    "Alectryon version is below the minimum required version. "
                    "Upgrade with: pip install --upgrade alectryon"
                ),
            },
        )

    # --- Build CLI arguments ---

    backend = FORMAT_TO_BACKEND[fmt]
    extension = FORMAT_TO_EXTENSION[fmt]

    use_temp_dir = request.output_path is None
    if use_temp_dir:
        tmp_dir = tempfile.mkdtemp()
        output_dir = tmp_dir
    else:
        output_dir = str(Path(request.output_path).parent)
        tmp_dir = None

    cmd_args = [
        "alectryon",
        "--frontend", "coq",
        "--backend", backend,
        "--output-directory", output_dir,
    ]
    cmd_args.extend(request.custom_flags)
    cmd_args.append(request.input_file)

    # --- Spawn subprocess ---

    timeout = request.timeout if request.timeout is not None else 120
    working_dir = str(input_path.parent)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return DocumentationResult(
                status="failure",
                format=fmt,
                error={
                    "code": "GENERATION_TIMEOUT",
                    "message": (
                        f"Documentation generation timed out after {timeout} "
                        f"seconds for {request.input_file}"
                    ),
                },
            )

        if process.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            # Determine if it's a Coq error or a general Alectryon error
            if "Error" in stderr_text and (
                "line" in stderr_text.lower() or "syntax" in stderr_text.lower()
            ):
                return DocumentationResult(
                    status="failure",
                    format=fmt,
                    error={
                        "code": "COQ_ERROR",
                        "message": f"Coq error in {request.input_file}: {stderr_text}",
                    },
                )
            else:
                return DocumentationResult(
                    status="failure",
                    format=fmt,
                    error={
                        "code": "ALECTRYON_ERROR",
                        "message": (
                            f"Alectryon failed with exit code "
                            f"{process.returncode}: {stderr_text}"
                        ),
                    },
                )

        # --- Locate and handle output ---

        output_filename = input_path.stem + extension
        generated_path = Path(output_dir) / output_filename

        if request.output_path is not None:
            # Move to requested output path
            shutil.move(str(generated_path), request.output_path)
            return DocumentationResult(
                status="success",
                output_path=request.output_path,
                content=None,
                format=fmt,
            )
        else:
            # Read content inline
            content = Path.read_text(generated_path)
            return DocumentationResult(
                status="success",
                output_path=None,
                content=content,
                format=fmt,
            )

    except asyncio.TimeoutError:
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "GENERATION_TIMEOUT",
                "message": (
                    f"Documentation generation timed out after {timeout} "
                    f"seconds for {request.input_file}"
                ),
            },
        )


# ---------------------------------------------------------------------------
# Proof extraction
# ---------------------------------------------------------------------------


def _find_proof_names(source: str) -> list[str]:
    """Find all declaration names in a Coq source string."""
    pattern = r"\b(" + "|".join(DECLARATION_KEYWORDS) + r")\s+(\w+)"
    return [m.group(2) for m in re.finditer(pattern, source)]


def _extract_proof(source: str, proof_name: str) -> Optional[str]:
    """Extract a named proof and its compilation context from Coq source.

    Returns the extracted content, or None if the proof is not found.
    Conservative extraction: includes everything from the start of the file
    up through the proof terminator.
    """
    # Find the declaration
    pattern = (
        r"\b(" + "|".join(DECLARATION_KEYWORDS) + r")\s+" + re.escape(proof_name) + r"\b"
    )
    match = re.search(pattern, source)
    if match is None:
        return None

    # Find the proof terminator after the declaration
    decl_start = match.start()
    rest = source[decl_start:]

    terminator_pattern = r"\b(Qed|Defined|Admitted)\s*\."
    term_match = re.search(terminator_pattern, rest)
    if term_match is not None:
        proof_end = decl_start + term_match.end()
    else:
        # No terminator found; take everything from declaration to end
        proof_end = len(source)

    # Conservative extraction: include everything from the beginning of the
    # file up to and including the proof terminator. This ensures imports,
    # section variables, and local definitions are included.
    extracted = source[:proof_end].strip() + "\n"
    return extracted


# ---------------------------------------------------------------------------
# Proof-scoped generation
# ---------------------------------------------------------------------------


async def generate_proof_documentation(
    request: DocumentationRequest,
) -> DocumentationResult:
    """Generate documentation for a single named proof.

    Spec: Section 4.3.
    """
    fmt = request.format
    input_path = Path(request.input_file)

    # --- Input validation (same as single-file) ---

    if not request.input_file.endswith(".v"):
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "INVALID_INPUT",
                "message": f"Expected a .v file, got: {request.input_file}",
            },
        )

    if not input_path.is_absolute():
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "INVALID_INPUT",
                "message": f"Expected a .v file, got: {request.input_file}",
            },
        )

    if not Path.exists(input_path):
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "FILE_NOT_FOUND",
                "message": f"File not found: {request.input_file}",
            },
        )

    # --- Availability check ---

    availability = await check_availability()
    if availability == "not_installed":
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "ALECTRYON_NOT_FOUND",
                "message": (
                    "Alectryon is not installed or not on the system PATH. "
                    "Install it with: pip install alectryon"
                ),
            },
        )
    if availability == "version_too_old":
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "ALECTRYON_VERSION_UNSUPPORTED",
                "message": (
                    "Alectryon version is below the minimum required version. "
                    "Upgrade with: pip install --upgrade alectryon"
                ),
            },
        )

    # --- Read source and extract proof ---

    source = Path.read_text(input_path)

    extracted = _extract_proof(source, request.proof_name)
    if extracted is None:
        available = _find_proof_names(source)
        return DocumentationResult(
            status="failure",
            format=fmt,
            error={
                "code": "PROOF_NOT_FOUND",
                "message": (
                    f"Proof {request.proof_name} not found in {request.input_file}. "
                    f"Available proofs: {', '.join(available)}"
                ),
            },
        )

    # --- Write temporary file ---

    tmp_filename = f".poule_tmp_{request.proof_name}.v"
    tmp_path = input_path.parent / tmp_filename

    tmp_path.write_text(extracted)

    try:
        # Delegate to single-file generation with the temporary file
        tmp_request = DocumentationRequest(
            input_file=str(tmp_path),
            proof_name=None,
            output_path=request.output_path,
            format=request.format,
            custom_flags=request.custom_flags,
            timeout=request.timeout,
        )
        result = await generate_documentation(tmp_request)
        return result
    finally:
        # Always clean up the temporary file
        tmp_path.unlink()


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------


def _generate_index_html(
    outcomes: list[FileOutcome],
    source_directory: str,
    output_directory: str,
) -> str:
    """Generate an index.html page listing all files and their documentation status."""
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head><title>Documentation Index</title></head>",
        "<body>",
        "<h1>Documentation Index</h1>",
        "<ul>",
    ]

    for outcome in outcomes:
        rel_input = str(Path(outcome.input_file).relative_to(source_directory))
        if outcome.status == "success" and outcome.output_file is not None:
            rel_output = str(Path(outcome.output_file).relative_to(output_directory))
            lines.append(
                f'  <li><a href="{rel_output}">{rel_input}</a></li>'
            )
        else:
            error_msg = ""
            if outcome.error:
                error_msg = f" - Error: {outcome.error.get('message', '')}"
            lines.append(f"  <li>{rel_input} (failed{error_msg})</li>")

    lines.extend([
        "</ul>",
        "</body>",
        "</html>",
    ])

    return "\n".join(lines)


async def generate_batch_documentation(
    request: BatchDocumentationRequest,
) -> BatchDocumentationResult:
    """Generate documentation for all .v files in a directory tree.

    Spec: Section 4.4.
    """
    source_dir = Path(request.source_directory)
    output_dir = Path(request.output_directory)

    # --- Pre-flight checks ---

    # Check availability
    availability = await check_availability()
    if availability == "not_installed":
        return BatchDocumentationResult(
            index_path="",
            output_directory=request.output_directory,
            results=[],
            total=0,
            succeeded=0,
            failed=0,
            error={
                "code": "ALECTRYON_NOT_FOUND",
                "message": (
                    "Alectryon is not installed or not on the system PATH. "
                    "Install it with: pip install alectryon"
                ),
            },
        )
    if availability == "version_too_old":
        return BatchDocumentationResult(
            index_path="",
            output_directory=request.output_directory,
            results=[],
            total=0,
            succeeded=0,
            failed=0,
            error={
                "code": "ALECTRYON_VERSION_UNSUPPORTED",
                "message": (
                    "Alectryon version is below the minimum required version. "
                    "Upgrade with: pip install --upgrade alectryon"
                ),
            },
        )

    # Check source directory
    if not Path.exists(source_dir) or not Path.is_dir(source_dir):
        return BatchDocumentationResult(
            index_path="",
            output_directory=request.output_directory,
            results=[],
            total=0,
            succeeded=0,
            failed=0,
            error={
                "code": "SOURCE_DIR_NOT_FOUND",
                "message": f"Source directory does not exist: {request.source_directory}",
            },
        )

    # --- Enumerate .v files ---

    v_files = sorted(Path.rglob(source_dir, "*.v"))

    if not v_files:
        return BatchDocumentationResult(
            index_path="",
            output_directory=request.output_directory,
            results=[],
            total=0,
            succeeded=0,
            failed=0,
            error={
                "code": "NO_INPUT_FILES",
                "message": f"No .v files found in {request.source_directory}",
            },
        )

    # --- Process each file ---

    extension = FORMAT_TO_EXTENSION[request.format]
    outcomes: list[FileOutcome] = []

    for v_file in v_files:
        rel_path = v_file.relative_to(source_dir)
        output_file_path = output_dir / rel_path.with_suffix(extension)

        # Create output subdirectory
        Path.mkdir(output_file_path.parent, parents=True, exist_ok=True)

        # Build per-file request
        file_request = DocumentationRequest(
            input_file=str(v_file),
            proof_name=None,
            output_path=str(output_file_path),
            format=request.format,
            custom_flags=request.custom_flags,
            timeout=request.timeout_per_file,
        )

        result = await generate_documentation(file_request)

        if result.status == "success":
            outcomes.append(FileOutcome(
                input_file=str(v_file),
                output_file=str(output_file_path),
                status="success",
                error=None,
            ))
        else:
            outcomes.append(FileOutcome(
                input_file=str(v_file),
                output_file=None,
                status="failure",
                error=result.error,
            ))

    # --- Generate index page ---

    succeeded = sum(1 for o in outcomes if o.status == "success")
    failed = len(outcomes) - succeeded

    index_content = _generate_index_html(
        outcomes, request.source_directory, request.output_directory
    )
    index_path = output_dir / "index.html"
    Path.write_text(index_path, index_content)

    return BatchDocumentationResult(
        index_path=str(index_path),
        output_directory=request.output_directory,
        results=outcomes,
        total=len(v_files),
        succeeded=succeeded,
        failed=failed,
    )
