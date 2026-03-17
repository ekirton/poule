"""Diversity filter for tactic candidates.

Spec: specification/proof-search-engine.md §4.5
"""

from __future__ import annotations

import re


def _normalize_whitespace(tactic: str) -> str:
    """Collapse all whitespace to single spaces, strip, and remove space before period."""
    normalized = re.sub(r"\s+", " ", tactic.strip())
    # Remove space before trailing period (e.g., "apply foo ." → "apply foo.")
    normalized = re.sub(r"\s+\.$", ".", normalized)
    return normalized


def _normalize_syntax(tactic: str) -> str:
    """Normalize surface syntax variants.

    E.g., 'rewrite -> H' and 'rewrite H' are equivalent in Coq.
    """
    normalized = _normalize_whitespace(tactic)
    # rewrite -> H ↔ rewrite H (default direction is ->)
    normalized = re.sub(r"\brewrite\s+->\s+", "rewrite ", normalized)
    return normalized


def filter_candidates(candidates: list[str]) -> list[str]:
    """Deduplicate and filter candidate tactics.

    - Exact duplicates: removed (keep first occurrence).
    - Whitespace-only differences: collapsed.
    - Surface syntax equivalents (e.g., rewrite H / rewrite -> H): collapsed.
    - Relative order of non-filtered candidates is preserved.
    - Solver tactics are never filtered against LLM candidates (they share
      the same dedup set, but solver tactics appear first so they are kept).
    """
    seen: set[str] = set()
    result: list[str] = []

    for tactic in candidates:
        key = _normalize_syntax(tactic)
        if key not in seen:
            seen.add(key)
            result.append(tactic)

    return result
