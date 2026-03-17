"""Three-stage axiom classification cascade."""

from __future__ import annotations

import re
from typing import Tuple

from poule.auditing.registry import KNOWN_AXIOMS, MODULE_PREFIXES
from poule.auditing.types import AxiomCategory

# Type-based heuristic patterns (Stage 3).
# Each entry is (compiled_pattern, category, explanation).
_TYPE_HEURISTICS: list[tuple[re.Pattern[str], AxiomCategory, str]] = [
    # Classical: excluded middle pattern  forall P : Prop, P \/ ~ P
    (
        re.compile(r"forall\s+\w+\s*:\s*Prop\s*,\s*\w+\s*\\/\s*~\s*\w+"),
        AxiomCategory("classical"),
        "Type matches excluded-middle pattern (forall P : Prop, P \\/ ~ P).",
    ),
    # Classical: double negation  forall P : Prop, ~ ~ P -> P
    (
        re.compile(r"forall\s+\w+\s*:\s*Prop\s*,\s*~\s*~\s*\w+\s*->\s*\w+"),
        AxiomCategory("classical"),
        "Type matches double-negation elimination pattern.",
    ),
    # Extensionality: functional extensionality
    (
        re.compile(r"forall\s+.*,\s*\(forall\s+\w+\s*,\s*\w+\s+\w+\s*=\s*\w+\s+\w+\)\s*->\s*\w+\s*=\s*\w+"),
        AxiomCategory("extensionality"),
        "Type matches functional extensionality pattern.",
    ),
    # Proof irrelevance: forall (P : Prop) (p1 p2 : P), p1 = p2
    (
        re.compile(r"forall\s+.*Prop.*,\s*\w+\s*=\s*\w+\s*$"),
        AxiomCategory("proof_irrelevance"),
        "Type matches proof irrelevance pattern.",
    ),
]


def classify_axiom(
    axiom_name: str, axiom_type: str
) -> Tuple[AxiomCategory, str]:
    """Classify an axiom through the three-stage cascade.

    Returns (category, explanation). Deterministic for the same inputs.
    """
    # Stage 1: Exact match
    if axiom_name in KNOWN_AXIOMS:
        return KNOWN_AXIOMS[axiom_name]

    # Stage 2: Prefix match
    for prefix, category in MODULE_PREFIXES:
        if axiom_name.startswith(prefix + "."):
            return category, f"Axiom under module {prefix}."

    # Stage 3: Type-based heuristic
    for pattern, category, explanation in _TYPE_HEURISTICS:
        if pattern.search(axiom_type):
            return category, explanation

    # Default
    return AxiomCategory("custom"), "User-defined axiom. Review manually for consistency."
