"""Output parser for raw Coq vernacular output.

Transforms raw output into (output, warnings) tuples with:
  1. Whitespace normalization
  2. Warning extraction
  3. Search truncation
  4. 1 MB buffer limit
"""

from __future__ import annotations

import re

# Warning pattern: lines starting with "Warning:" (compiled once).
_WARNING_RE = re.compile(r"^Warning:\s*", re.IGNORECASE)

# Maximum output buffer size (1 MB).
_MAX_BUFFER = 1_000_000


def parse_output(
    raw: str,
    command: str,
    truncation_limit: int = 50,
) -> tuple[str, list[str]]:
    """Parse raw Coq output into (output, warnings).

    Args:
        raw: Raw Coq output string.
        command: The command that produced this output (e.g. "Search").
        truncation_limit: Maximum number of search result entries before truncation.

    Returns:
        A tuple of (output_text, warnings_list).
    """
    if not raw:
        return "", []

    # Step 0: Enforce 1 MB buffer limit on raw input.
    truncated_by_buffer = False
    if len(raw) > _MAX_BUFFER:
        raw = raw[:_MAX_BUFFER]
        truncated_by_buffer = True

    lines = raw.split("\n")

    # Step 2: Warning extraction.
    warnings: list[str] = []
    output_lines: list[str] = []
    for line in lines:
        if _WARNING_RE.match(line):
            # Strip the "Warning: " prefix for the warnings list.
            warning_text = _WARNING_RE.sub("", line).strip()
            warnings.append(warning_text)
        else:
            output_lines.append(line)

    # Step 3: Search truncation.
    if command == "Search":
        # Count non-empty lines as entries.
        non_empty = [l for l in output_lines if l.strip()]
        total = len(non_empty)
        if total > truncation_limit:
            kept = non_empty[:truncation_limit]
            kept.append(f"(... truncated, {total} results total)")
            output_lines = kept

    # Step 1: Whitespace normalization -- collapse runs of blank lines.
    normalized: list[str] = []
    prev_blank = False
    for line in output_lines:
        is_blank = not line.strip()
        if is_blank:
            if not prev_blank:
                normalized.append("")
            prev_blank = True
        else:
            normalized.append(line)
            prev_blank = False

    output = "\n".join(normalized).strip()

    if truncated_by_buffer:
        output += "\n(... output truncated, exceeded 1 MB limit)"

    return output, warnings
