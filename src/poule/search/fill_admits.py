"""Fill Admits Orchestrator: batch automation for replacing admit calls.

Spec: specification/fill-admits-orchestrator.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from poule.search.types import (
    AdmitLocation,
    AdmitResult,
    FillAdmitsResult,
)
from poule.session.errors import (
    BACKEND_CRASHED,
    FILE_NOT_FOUND,
    PROOF_NOT_FOUND,
    SessionError,
)


def locate_admits(file_contents: str) -> list[AdmitLocation]:
    """Locate all admit./Admitted. calls in Coq source, excluding comments.

    Returns an ordered list of AdmitLocation sorted by line number (ascending).
    Case-sensitive: matches 'admit.' and 'Admitted.' per Coq conventions.
    """
    if not file_contents:
        return []

    # First, identify all comment regions (handling nesting)
    comment_ranges: list[tuple[int, int]] = []
    _find_comment_ranges(file_contents, comment_ranges)

    # Find all admit./Admitted. tokens
    locations: list[AdmitLocation] = []
    # Track current proof name for proof_name field
    current_proof: str | None = None
    admit_counts: dict[str, int] = {}  # proof_name -> count of admits seen

    lines = file_contents.split("\n")

    # Scan for proof starts (Lemma, Theorem, Definition, etc.)
    proof_pattern = re.compile(
        r"\b(Lemma|Theorem|Proposition|Corollary|Definition|Fixpoint|Example|Fact|Remark)\s+(\w+)"
    )

    # Build a map of line -> proof_name by scanning declarations
    line_to_proof: dict[int, str] = {}
    active_proof: str | None = None
    for line_idx, line in enumerate(lines):
        m = proof_pattern.search(line)
        if m:
            active_proof = m.group(2)
            admit_counts[active_proof] = 0
        if active_proof:
            line_to_proof[line_idx] = active_proof
        # Qed./Defined./Abort. end a proof
        if re.search(r"\b(Qed|Defined|Abort)\s*\.", line):
            active_proof = None

    # Find admit. and Admitted. occurrences
    admit_pattern = re.compile(r"\b(admit\.|Admitted\.)")

    for line_idx, line in enumerate(lines):
        for m in admit_pattern.finditer(line):
            start_offset = m.start()
            end_offset = m.end()

            # Compute absolute position to check against comments
            abs_start = sum(len(lines[i]) + 1 for i in range(line_idx)) + start_offset

            # Check if inside a comment
            if _in_comment(abs_start, comment_ranges):
                continue

            proof_name = line_to_proof.get(line_idx, "unknown")
            admit_index = admit_counts.get(proof_name, 0)
            admit_counts[proof_name] = admit_index + 1

            locations.append(AdmitLocation(
                proof_name=proof_name,
                admit_index=admit_index,
                line_number=line_idx + 1,  # 1-based
                column_range=(start_offset, end_offset),
            ))

    # Sort by line number (should already be in order, but ensure)
    locations.sort(key=lambda loc: (loc.line_number, loc.column_range[0]))
    return locations


def _find_comment_ranges(text: str, ranges: list[tuple[int, int]]) -> None:
    """Find all comment regions including nested (* ... *) comments."""
    i = 0
    while i < len(text) - 1:
        if text[i:i + 2] == "(*":
            start = i
            depth = 1
            i += 2
            while i < len(text) - 1 and depth > 0:
                if text[i:i + 2] == "(*":
                    depth += 1
                    i += 2
                elif text[i:i + 2] == "*)":
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth == 0:
                ranges.append((start, i))
            else:
                # Unclosed comment — treat rest as comment
                ranges.append((start, len(text)))
        else:
            i += 1


def _in_comment(pos: int, comment_ranges: list[tuple[int, int]]) -> bool:
    """Check if a position is inside any comment range."""
    for start, end in comment_ranges:
        if start <= pos < end:
            return True
    return False


async def fill_admits(
    session_manager: Any,
    search_engine: Any,
    file_path: str,
    timeout_per_admit: float = 30,
    max_depth: int = 10,
    max_breadth: int = 20,
) -> FillAdmitsResult:
    """Scan a .v file for admit calls, attempt to fill each via proof search.

    Raises SessionError(FILE_NOT_FOUND) if the file does not exist or path is empty.
    """
    # Input validation (spec §7.1)
    if not file_path or not file_path.strip():
        raise SessionError(FILE_NOT_FOUND, f"File not found: {file_path}")

    if timeout_per_admit <= 0:
        timeout_per_admit = 1
    if max_depth <= 0:
        max_depth = 1
    if max_breadth <= 0:
        max_breadth = 1

    path = Path(file_path)
    if not path.exists():
        raise SessionError(FILE_NOT_FOUND, f"File not found: {file_path}")

    file_contents = path.read_text()

    # Locate admits (spec §4.2)
    admits = locate_admits(file_contents)

    if not admits:
        return FillAdmitsResult(
            total_admits=0,
            filled=0,
            unfilled=0,
            results=[],
            modified_script=file_contents,
        )

    # Process each admit (spec §4.3)
    results: list[AdmitResult] = []

    for admit in admits:
        result = await _process_admit(
            session_manager=session_manager,
            search_engine=search_engine,
            file_path=file_path,
            admit=admit,
            timeout_per_admit=timeout_per_admit,
            max_depth=max_depth,
            max_breadth=max_breadth,
        )
        results.append(result)

    # Assemble modified script (spec §4.4)
    modified_script = _assemble_script(file_contents, admits, results)

    filled = sum(1 for r in results if r.status == "filled")
    unfilled = len(results) - filled

    return FillAdmitsResult(
        total_admits=len(admits),
        filled=filled,
        unfilled=unfilled,
        results=results,
        modified_script=modified_script,
    )


async def _process_admit(
    session_manager: Any,
    search_engine: Any,
    file_path: str,
    admit: AdmitLocation,
    timeout_per_admit: float,
    max_depth: int,
    max_breadth: int,
) -> AdmitResult:
    """Process a single admit: open session, navigate, search, close."""
    session_id = None

    try:
        # 1. Open session (spec §4.3 step 1)
        session_id, _state = await session_manager.create_session(
            file_path, admit.proof_name,
        )

        # 2. Navigate to admit position (spec §4.3 step 2)
        for _ in range(admit.admit_index):
            try:
                await session_manager.step_forward(session_id)
            except SessionError as exc:
                return AdmitResult(
                    proof_name=admit.proof_name,
                    admit_index=admit.admit_index,
                    line_number=admit.line_number,
                    status="unfilled",
                    replacement=None,
                    search_stats=None,
                    error=f"Step forward failed: {exc.message}",
                )

        # 3. Invoke proof search (spec §4.3 step 3)
        search_result = await search_engine.proof_search(
            session_id, timeout_per_admit, max_depth, max_breadth,
        )

        # 4. Record result (spec §4.3 step 4)
        if search_result.status == "success":
            tactics = [step.tactic for step in search_result.proof_script]
            return AdmitResult(
                proof_name=admit.proof_name,
                admit_index=admit.admit_index,
                line_number=admit.line_number,
                status="filled",
                replacement=tactics,
                search_stats=None,
                error=None,
            )
        else:
            return AdmitResult(
                proof_name=admit.proof_name,
                admit_index=admit.admit_index,
                line_number=admit.line_number,
                status="unfilled",
                replacement=None,
                search_stats={
                    "states_explored": search_result.states_explored,
                    "unique_states": search_result.unique_states,
                    "wall_time_ms": search_result.wall_time_ms,
                },
                error=None,
            )

    except SessionError as exc:
        # Session open failure, backend crash, etc.
        return AdmitResult(
            proof_name=admit.proof_name,
            admit_index=admit.admit_index,
            line_number=admit.line_number,
            status="unfilled",
            replacement=None,
            search_stats=None,
            error=f"{exc.code}: {exc.message}",
        )

    finally:
        # 5. Close session (spec §4.3 step 5)
        if session_id is not None:
            try:
                await session_manager.close_session(session_id)
            except Exception:
                pass


def _assemble_script(
    file_contents: str,
    admits: list[AdmitLocation],
    results: list[AdmitResult],
) -> str:
    """Replace filled admits in the file contents.

    Replacements are applied from last to first (reverse source order)
    to preserve line numbers for earlier replacements (spec §4.4).
    """
    lines = file_contents.split("\n")

    # Process in reverse order
    for admit, result in reversed(list(zip(admits, results))):
        if result.status != "filled" or result.replacement is None:
            continue

        line_idx = admit.line_number - 1  # 0-based
        start_col, end_col = admit.column_range
        line = lines[line_idx]

        # Replace the admit text with the tactic sequence
        replacement_text = " ".join(result.replacement)
        lines[line_idx] = line[:start_col] + replacement_text + line[end_col:]

    return "\n".join(lines)
