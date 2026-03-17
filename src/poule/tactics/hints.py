"""Hint database inspection.

Spec: specification/tactic-documentation.md section 4.5.
"""

from __future__ import annotations

import re
from typing import Optional

from poule.tactics.types import HintDatabase, HintEntry, HintSummary

# Maximum entries returned before truncation (per spec example).
_TRUNCATION_LIMIT = 200


class TacticDocError(Exception):
    """Error raised by hint database operations."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Resolve <lemma_name> : <type> (cost <n>)
_RE_RESOLVE = re.compile(
    r'^Resolve\s+([\w.]+)\s*:\s*\S+\s*\(cost\s+(\d+)\)',
    re.IGNORECASE,
)

# Unfold <constant_name> (cost <n>)
_RE_UNFOLD = re.compile(
    r'^Unfold\s+([\w.]+)\s*\(cost\s+(\d+)\)',
    re.IGNORECASE,
)

# Constructors <inductive_name> (cost <n>)
_RE_CONSTRUCTORS = re.compile(
    r'^Constructors\s+([\w.]+)\s*\(cost\s+(\d+)\)',
    re.IGNORECASE,
)

# Extern <n> (<pattern>) => <tactic>
_RE_EXTERN = re.compile(
    r'^Extern\s+(\d+)\s+(.+?)\s+=>\s+(.+)$',
    re.IGNORECASE,
)


def _parse_hint_line(line: str) -> Optional[HintEntry]:
    """Parse a single line of Print HintDb output into a HintEntry, or None."""
    line = line.strip()
    if not line:
        return None

    m = _RE_RESOLVE.match(line)
    if m:
        return HintEntry(
            hint_type="resolve",
            name=m.group(1),
            pattern=None,
            tactic=None,
            cost=int(m.group(2)),
        )

    m = _RE_UNFOLD.match(line)
    if m:
        return HintEntry(
            hint_type="unfold",
            name=m.group(1),
            pattern=None,
            tactic=None,
            cost=int(m.group(2)),
        )

    m = _RE_CONSTRUCTORS.match(line)
    if m:
        return HintEntry(
            hint_type="constructors",
            name=m.group(1),
            pattern=None,
            tactic=None,
            cost=int(m.group(2)),
        )

    m = _RE_EXTERN.match(line)
    if m:
        return HintEntry(
            hint_type="extern",
            name=None,
            pattern=m.group(2).strip(),
            tactic=m.group(3).strip(),
            cost=int(m.group(1)),
        )

    return None


def _parse_hintdb_output(db_name: str, output: str) -> HintDatabase:
    """Parse the output of Print HintDb into a HintDatabase record."""
    if re.search(r"Error:.*not found", output, re.IGNORECASE):
        raise TacticDocError(
            "NOT_FOUND",
            f'Hint database "{db_name}" not found.',
        )

    all_entries: list[HintEntry] = []
    for line in output.splitlines():
        entry = _parse_hint_line(line)
        if entry is not None:
            all_entries.append(entry)

    total_entries = len(all_entries)
    truncated = total_entries > _TRUNCATION_LIMIT
    entries = all_entries[:_TRUNCATION_LIMIT] if truncated else all_entries

    # Compute summary from the full set of parsed entries before truncation
    resolve_count = sum(1 for e in all_entries if e.hint_type == "resolve")
    unfold_count = sum(1 for e in all_entries if e.hint_type == "unfold")
    constructors_count = sum(1 for e in all_entries if e.hint_type == "constructors")
    extern_count = sum(1 for e in all_entries if e.hint_type == "extern")

    summary = HintSummary(
        resolve_count=resolve_count,
        unfold_count=unfold_count,
        constructors_count=constructors_count,
        extern_count=extern_count,
    )

    return HintDatabase(
        name=db_name,
        summary=summary,
        entries=entries,
        truncated=truncated,
        total_entries=total_entries,
    )


async def hint_inspect(
    db_name: str,
    session_id: Optional[str] = None,
    coq_query=None,
) -> HintDatabase:
    """Inspect a hint database and return a structured HintDatabase record.

    Spec: section 4.5.
    """
    if not db_name:
        raise TacticDocError(
            "INVALID_ARGUMENT",
            "Hint database name must not be empty.",
        )

    result = await coq_query("Print", f"HintDb {db_name}", session_id=session_id)
    return _parse_hintdb_output(db_name, result.output)
