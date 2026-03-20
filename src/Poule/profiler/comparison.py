"""Timing comparison and sentence matching between profiling runs.

Spec: specification/proof-profiling.md, Sections 4.13 and 4.14.
"""

from __future__ import annotations

from collections import defaultdict
from typing import List, Tuple

from Poule.profiler.types import TimingDiff, TimingComparison, TimingSentence


def match_sentences(
    baseline_sentences: List[TimingSentence],
    current_sentences: List[TimingSentence],
    fuzz_bytes: int = 500,
) -> Tuple[
    List[Tuple[TimingSentence, TimingSentence]],
    List[TimingSentence],
    List[TimingSentence],
]:
    """Match sentences between baseline and current profiling runs.

    Two-pass strategy:
    1. Snippet match: identical snippet text, with positional ordering
       for duplicate snippets.
    2. Fuzz match: for unmatched sentences, match by char_start within
       ±fuzz_bytes tolerance.

    Returns (matched_pairs, unmatched_baseline, unmatched_current).
    """
    matched: List[Tuple[TimingSentence, TimingSentence]] = []
    used_baseline: set[int] = set()
    used_current: set[int] = set()

    # Pass 1: Snippet-based matching with positional ordering
    # Group by snippet
    baseline_by_snippet: dict[str, list[int]] = defaultdict(list)
    current_by_snippet: dict[str, list[int]] = defaultdict(list)

    for i, s in enumerate(baseline_sentences):
        baseline_by_snippet[s.snippet].append(i)
    for i, s in enumerate(current_sentences):
        current_by_snippet[s.snippet].append(i)

    for snippet, b_indices in baseline_by_snippet.items():
        c_indices = current_by_snippet.get(snippet, [])
        for k in range(min(len(b_indices), len(c_indices))):
            bi = b_indices[k]
            ci = c_indices[k]
            matched.append((baseline_sentences[bi], current_sentences[ci]))
            used_baseline.add(bi)
            used_current.add(ci)

    # Pass 2: Fuzz match for unmatched sentences
    for bi, bs in enumerate(baseline_sentences):
        if bi in used_baseline:
            continue
        for ci, cs in enumerate(current_sentences):
            if ci in used_current:
                continue
            if abs(bs.char_start - cs.char_start) <= fuzz_bytes:
                matched.append((bs, cs))
                used_baseline.add(bi)
                used_current.add(ci)
                break

    unmatched_baseline = [
        baseline_sentences[i]
        for i in range(len(baseline_sentences))
        if i not in used_baseline
    ]
    unmatched_current = [
        current_sentences[i]
        for i in range(len(current_sentences))
        if i not in used_current
    ]

    return matched, unmatched_baseline, unmatched_current
