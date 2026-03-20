"""Bottleneck classification against known Coq performance patterns.

Spec: specification/proof-profiling.md, Section 4.12.
"""

from __future__ import annotations

import re
from typing import List, Union

from Poule.profiler.types import (
    BottleneckClassification,
    LtacProfileEntry,
    TimingSentence,
)

_EAUTO_DEPTH_RE = re.compile(r"eauto\s+(\d+)")

# Suggestion hints per category (from spec)
_HINTS = {
    "SlowQed": [
        "use abstract to encapsulate expensive sub-proofs",
        "replace simpl in H with eval/replace pattern",
        "add Opaque directives for definitions not needed in reduction",
    ],
    "SlowReduction": [
        "use lazy or cbv for controlled reduction",
        "use change with an explicit target term",
        "set Arguments ... : simpl never for expensive definitions",
    ],
    "TypeclassBlowup": [
        "use Set Typeclasses Debug to trace the search",
        "adjust instance priorities",
        "use Hint Cut to prune search branches",
    ],
    "HighSearchDepth": [
        "reduce search depth",
        "use auto where backtracking is unnecessary",
        "provide explicit witnesses with eapply",
    ],
    "ExpensiveMatch": [
        "simplify the match pattern",
        "add early termination guards",
    ],
    "General": [],
}


def _get_time(item: Union[TimingSentence, LtacProfileEntry]) -> float:
    """Extract the relevant time value from an item."""
    if isinstance(item, TimingSentence):
        return item.real_time_s
    return item.max_time_s  # For LtacProfileEntry, use max_time_s


def _get_snippet(item: Union[TimingSentence, LtacProfileEntry]) -> str:
    """Extract text to match against patterns."""
    if isinstance(item, TimingSentence):
        return item.snippet.replace("~", " ").strip("[]")
    return item.tactic_name


def _get_kind(item: Union[TimingSentence, LtacProfileEntry]) -> str:
    """Get sentence_kind if available."""
    if isinstance(item, TimingSentence):
        return item.sentence_kind
    return ""


def _classify_one(
    item: Union[TimingSentence, LtacProfileEntry],
    total_time_s: float,
) -> tuple[str, float] | None:
    """Classify a single item. Returns (category, threshold_time) or None."""
    time_val = _get_time(item)
    snippet = _get_snippet(item)
    kind = _get_kind(item)

    # Priority 1: SlowQed
    if kind == "ProofClose" and time_val > 2.0:
        # Infer tactic_time as total - close_time
        tactic_time = max(0.0, total_time_s - time_val)
        if time_val > 5 * tactic_time:
            return ("SlowQed", time_val)

    # Priority 2: SlowReduction
    if ("simpl" in snippet.lower() or "cbn" in snippet.lower()) and time_val > 2.0:
        return ("SlowReduction", time_val)

    # Priority 3: TypeclassBlowup
    if "typeclasses eauto" in snippet.lower() and time_val > 2.0:
        return ("TypeclassBlowup", time_val)

    # Priority 4: HighSearchDepth
    m = _EAUTO_DEPTH_RE.search(snippet)
    if m and int(m.group(1)) > 6 and time_val > 1.0:
        return ("HighSearchDepth", time_val)

    # Priority 5: ExpensiveMatch
    if ("match goal" in snippet.lower() or "repeat" in snippet.lower()) and time_val > 3.0:
        return ("ExpensiveMatch", time_val)

    # Priority 6: General
    if time_val > 5.0:
        return ("General", time_val)

    return None


def _assign_severity(
    category: str,
    time_val: float,
    total_time_s: float,
) -> str:
    """Assign severity level."""
    # Critical if > 50% of total time
    if total_time_s > 0 and time_val / total_time_s > 0.5:
        return "critical"

    # Category-specific critical thresholds
    critical_thresholds = {
        "SlowQed": 10.0,
        "SlowReduction": 10.0,
        "TypeclassBlowup": 10.0,
        "HighSearchDepth": 5.0,
        "ExpensiveMatch": float("inf"),  # no critical threshold
        "General": 30.0,
    }

    if time_val > critical_thresholds.get(category, float("inf")):
        return "critical"

    return "warning"


def classify_bottlenecks(
    items: List[Union[TimingSentence, LtacProfileEntry]],
    total_time_s: float,
) -> List[BottleneckClassification]:
    """Classify bottlenecks in a list of timing items.

    Returns up to 5 BottleneckClassification records, ranked by time descending.
    Items below all thresholds produce an empty list.
    """
    candidates = []
    for item in items:
        result = _classify_one(item, total_time_s)
        if result is not None:
            category, time_val = result
            severity = _assign_severity(category, time_val, total_time_s)
            candidates.append((time_val, category, severity, item))

    # Sort by time descending
    candidates.sort(key=lambda x: x[0], reverse=True)

    # Take top 5
    classifications = []
    for rank, (time_val, category, severity, item) in enumerate(candidates[:5], start=1):
        classifications.append(
            BottleneckClassification(
                rank=rank,
                category=category,
                sentence=item,
                severity=severity,
                suggestion_hints=list(_HINTS.get(category, [])),
            )
        )

    return classifications
