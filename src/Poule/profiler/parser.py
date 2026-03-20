"""Timing output parsers for coqc -time and Ltac profiling.

Spec: specification/proof-profiling.md, Sections 4.5 and 4.11.
"""

from __future__ import annotations

import re
from typing import List

from Poule.profiler.types import LtacProfile, LtacProfileEntry, TimingSentence

# Regex from Coq's own TimeFileMaker.py
_TIMING_RE = re.compile(
    r"^Chars (\d+) - (\d+) (\S+) ([\d.]+) secs \(([\d.]+)u,([\d.]+)s\)$"
)

# Ltac profile header
_LTAC_TOTAL_RE = re.compile(r"total time:\s*([\d.]+)s")

# Ltac profile row — handles variable padding between columns
# Format: ─<name> ---- <local>% <total>% <calls> <max>s
# Note: leading ─ is Unicode U+2500, separator dashes are ASCII hyphen
_LTAC_ROW_RE = re.compile(
    r"^\s*[─]"                      # leading whitespace + at least one ─ (U+2500)
    r"(\w+)"                        # tactic name (word chars only)
    r"\s+[-─]*\s+"                  # separator (ASCII hyphens or Unicode dashes) + space
    r"([\d.]+)%\s+"                 # local %
    r"([\d.]+)%\s+"                 # total %
    r"(\d+)\s+"                     # calls
    r"([\d.]+)s\s*$"               # max time
)


def parse_timing_output(timing_text: str) -> List[TimingSentence]:
    """Parse coqc -time-file output into TimingSentence records.

    Lines not matching the timing regex are skipped.
    Results are returned in source order (ascending char_start).
    """
    sentences: List[TimingSentence] = []
    for line in timing_text.splitlines():
        m = _TIMING_RE.match(line.strip())
        if m:
            sentences.append(
                TimingSentence(
                    char_start=int(m.group(1)),
                    char_end=int(m.group(2)),
                    snippet=m.group(3),
                    real_time_s=float(m.group(4)),
                    user_time_s=float(m.group(5)),
                    sys_time_s=float(m.group(6)),
                )
            )
    sentences.sort(key=lambda s: s.char_start)
    return sentences


def parse_ltac_profile(output_text: str) -> LtacProfile:
    """Parse Show Ltac Profile output into an LtacProfile.

    Empty or unparseable input returns an LtacProfile with zero time,
    empty entries, and a caveat noting the parse failure.
    """
    if not output_text or not output_text.strip():
        return LtacProfile(
            total_time_s=0.0,
            entries=[],
            caveats=["Ltac profile output was empty or could not be parsed"],
        )

    # Extract total time
    total_time = 0.0
    total_match = _LTAC_TOTAL_RE.search(output_text)
    if total_match:
        total_time = float(total_match.group(1))

    # Extract entries
    entries: List[LtacProfileEntry] = []
    for line in output_text.splitlines():
        m = _LTAC_ROW_RE.match(line)
        if m:
            entries.append(
                LtacProfileEntry(
                    tactic_name=m.group(1),
                    local_pct=float(m.group(2)),
                    total_pct=float(m.group(3)),
                    calls=int(m.group(4)),
                    max_time_s=float(m.group(5)),
                )
            )

    # Sort by total_pct descending
    entries.sort(key=lambda e: e.total_pct, reverse=True)

    # Detect caveats
    caveats: List[str] = []
    if "may be inaccurate" in output_text:
        caveats.append(
            "Ltac profiler may report inaccurate times for backtracking "
            "tactics (eauto, typeclasses eauto). See Coq issue #12196."
        )

    if not total_match and not entries:
        caveats.append("Ltac profile output was empty or could not be parsed")

    return LtacProfile(
        total_time_s=total_time,
        entries=entries,
        caveats=caveats,
    )
