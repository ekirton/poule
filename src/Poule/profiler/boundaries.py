"""Proof boundary detection and sentence classification.

Spec: specification/proof-profiling.md, Sections 4.7, 4.8, 4.6.
"""

from __future__ import annotations

import re
from typing import List

from Poule.profiler.types import ProofBoundary, TimingSentence

# Declaration keywords that may introduce a proof
_DECL_RE = re.compile(
    r"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Example"
    r"|Definition|Fixpoint|CoFixpoint|Let|Instance|Program)\s+(\w+)"
)

# Proof-closing keywords (must be followed by a period)
_CLOSE_RE = re.compile(r"\b(Qed|Defined|Admitted|Abort)\s*\.")

# Snippet prefix patterns for sentence classification
_IMPORT_PREFIXES = ("Require", "Import", "Export")
_DEFINITION_PREFIXES = (
    "Lemma", "Theorem", "Proposition", "Corollary", "Fact", "Remark",
    "Example", "Definition", "Fixpoint", "CoFixpoint", "Let", "Instance",
    "Program",
)
_PROOF_OPEN_PREFIXES = ("Proof",)
_PROOF_CLOSE_PREFIXES = ("Qed", "Defined", "Admitted", "Abort")


def detect_proof_boundaries(source_text: str) -> List[ProofBoundary]:
    """Detect proof boundaries in Coq source text.

    Returns a list of ProofBoundary records pairing declarations
    with their closing keywords (Qed/Defined/Admitted/Abort).
    """
    # Find all declarations
    decls = []
    for m in _DECL_RE.finditer(source_text):
        decls.append((m.group(2), m.start()))  # (name, byte offset)

    # Find all closers
    closers = []
    for m in _CLOSE_RE.finditer(source_text):
        closers.append(m.end())  # byte offset past the period

    # Pair declarations with closers
    boundaries: List[ProofBoundary] = []
    closer_idx = 0
    for i, (name, decl_start) in enumerate(decls):
        # Find the next closer that comes after this declaration
        # but before the next declaration (if any)
        next_decl_start = decls[i + 1][1] if i + 1 < len(decls) else len(source_text)

        found_closer = False
        for j in range(closer_idx, len(closers)):
            if closers[j] > decl_start and closers[j] <= next_decl_start:
                boundaries.append(
                    ProofBoundary(
                        name=name,
                        decl_char_start=decl_start,
                        close_char_end=closers[j],
                    )
                )
                closer_idx = j + 1
                found_closer = True
                break

        if not found_closer:
            # Check for closer after next_decl_start (for inline proofs
            # or cases where closer is after the next declaration keyword
            # within the same proof)
            pass  # No boundary for definitions without proof bodies

    return boundaries


def _normalize_snippet(snippet: str) -> str:
    """Normalize a timing snippet for prefix matching.

    Strips brackets and replaces ~ with space.
    """
    s = snippet.strip()
    if s.startswith("["):
        s = s[1:]
    if s.endswith("]"):
        s = s[:-1]
    return s.replace("~", " ")


def classify_sentence(
    sentence: TimingSentence,
    proof_boundaries: List[ProofBoundary],
) -> None:
    """Classify a sentence's kind and assign containing_proof.

    Mutates the sentence in place.
    """
    normalized = _normalize_snippet(sentence.snippet)

    # Check prefix-based classification
    for prefix in _IMPORT_PREFIXES:
        if normalized.startswith(prefix):
            sentence.sentence_kind = "Import"
            _assign_containing_proof(sentence, proof_boundaries)
            return

    for prefix in _PROOF_CLOSE_PREFIXES:
        if normalized.startswith(prefix):
            sentence.sentence_kind = "ProofClose"
            _assign_containing_proof(sentence, proof_boundaries)
            return

    for prefix in _PROOF_OPEN_PREFIXES:
        if normalized.startswith(prefix):
            sentence.sentence_kind = "ProofOpen"
            _assign_containing_proof(sentence, proof_boundaries)
            return

    for prefix in _DEFINITION_PREFIXES:
        if normalized.startswith(prefix):
            sentence.sentence_kind = "Definition"
            _assign_containing_proof(sentence, proof_boundaries)
            return

    # If within a proof boundary, classify as Tactic
    for boundary in proof_boundaries:
        if boundary.decl_char_start <= sentence.char_start < boundary.close_char_end:
            sentence.sentence_kind = "Tactic"
            sentence.containing_proof = boundary.name
            return

    sentence.sentence_kind = "Other"
    sentence.containing_proof = None


def _assign_containing_proof(
    sentence: TimingSentence,
    proof_boundaries: List[ProofBoundary],
) -> None:
    """Set containing_proof based on proof boundary membership."""
    for boundary in proof_boundaries:
        if boundary.decl_char_start <= sentence.char_start < boundary.close_char_end:
            sentence.containing_proof = boundary.name
            return
    sentence.containing_proof = None


def resolve_line_numbers(
    sentences: List[TimingSentence],
    source_bytes: bytes,
) -> None:
    """Resolve char_start byte offsets to 1-based line numbers.

    Mutates sentences in place. Handles UTF-8 correctly because
    coqc -time reports byte offsets.
    """
    # Build byte-offset-to-line-number map
    line_starts = [0]  # Line 1 starts at byte 0
    for i, b in enumerate(source_bytes):
        if b == ord("\n"):
            line_starts.append(i + 1)

    for sentence in sentences:
        # Binary search for the line containing char_start
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= sentence.char_start:
                lo = mid
            else:
                hi = mid - 1
        sentence.line_number = lo + 1  # 1-based
