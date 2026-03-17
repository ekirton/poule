"""State cache: SHA-256 hashing of proof states for deduplication.

Spec: specification/proof-search-engine.md §4.6
"""

from __future__ import annotations

import hashlib

from poule.session.types import ProofState


def hash_proof_state(proof_state: ProofState) -> bytes:
    """Compute a SHA-256 hash of a proof state's mathematical content.

    The hash is order-independent for goals (sorted by type string) and
    order-dependent for hypotheses within each goal (sorted by name).
    Session ID and step index are excluded.

    Returns a 32-byte SHA-256 digest.
    """
    # Sort goals by type string for order-independence
    sorted_goals = sorted(proof_state.goals, key=lambda g: g.type)

    parts: list[str] = []
    for goal in sorted_goals:
        # Sort hypotheses by name within each goal
        sorted_hyps = sorted(goal.hypotheses, key=lambda h: h.name)
        hyp_strs = [(h.name, h.type) for h in sorted_hyps]
        parts.append(repr((goal.type, hyp_strs)))

    content = "|".join(parts)
    return hashlib.sha256(content.encode("utf-8")).digest()
