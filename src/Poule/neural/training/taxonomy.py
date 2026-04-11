"""Canonical tactic taxonomy for hierarchical classification.

Single source of truth for category mapping. All other files import from here.

Six categories: top 5 by frequency plus "other" as catch-all for rare
categories (arithmetic, contradiction, ssreflect).
"""

from __future__ import annotations


# Category names in canonical order (used as class indices for category head).
CATEGORY_NAMES: list[str] = [
    "introduction",
    "elimination",
    "rewriting",
    "hypothesis_mgmt",
    "automation",
    "other",
]

# Tactics per category. Each tactic maps to exactly one category.
TACTIC_CATEGORIES: dict[str, list[str]] = {
    "introduction": [
        "intros", "intro", "split", "left", "right", "exists",
        "eexists", "constructor", "econstructor", "exact",
    ],
    "elimination": [
        "destruct", "induction", "case", "elim", "inversion",
        "discriminate", "injection",
    ],
    "rewriting": [
        "rewrite", "replace", "simpl", "unfold", "change", "pattern",
        "subst", "f_equal", "congruence", "reflexivity", "symmetry",
        "transitivity",
    ],
    "hypothesis_mgmt": [
        "apply", "eapply", "have", "assert", "enough", "pose", "set",
        "specialize", "generalize", "revert", "remember", "cut",
        "clear", "rename",
    ],
    "automation": [
        "auto", "eauto", "trivial", "tauto", "intuition", "firstorder",
        "decide", "now", "easy", "assumption",
    ],
    "other": [
        # Arithmetic (formerly its own category)
        "lia", "omega", "ring", "field",
        # Contradiction (formerly its own category)
        "exfalso", "absurd", "contradiction",
        # SSReflect (formerly its own category)
        "move", "suff", "wlog", "congr", "unlock",
    ],
}

# Reverse mapping: tactic name -> category name
TACTIC_TO_CATEGORY: dict[str, str] = {}
for _cat, _tactics in TACTIC_CATEGORIES.items():
    for _tac in _tactics:
        TACTIC_TO_CATEGORY[_tac] = _cat

# Proof structure tokens excluded from training entirely.
# They are not tactics and are trivially predictable from subgoal count.
EXCLUDED_TOKENS: frozenset[str] = frozenset({"-", "+", "*", "{", "}"})


def classify_tactic(family: str) -> str | None:
    """Map a normalized tactic family to its category name.

    Returns the category name, or None if the tactic is not in the taxonomy.
    """
    return TACTIC_TO_CATEGORY.get(family)
