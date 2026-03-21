"""Map Coq declaration forms to storage kind strings."""

from __future__ import annotations

# Mapping from lowercase Coq form to storage kind.
_KIND_MAP: dict[str, str] = {
    "lemma": "lemma",
    "theorem": "theorem",
    "definition": "definition",
    "let": "definition",
    "coercion": "definition",
    "canonical structure": "definition",
    "inductive": "inductive",
    "record": "inductive",
    "class": "inductive",
    "constructor": "constructor",
    "instance": "instance",
    "axiom": "axiom",
    "parameter": "axiom",
    "conjecture": "axiom",
}

# Excluded forms — no kernel term, not indexed.
_EXCLUDED: frozenset[str] = frozenset({
    "notation",
    "abbreviation",
    "section variable",
    "ltac",
    "module",
})


def map_kind(coq_form: str) -> str | None:
    """Map a Coq declaration form to a storage kind string.

    Returns ``None`` for excluded forms (Notation, Abbreviation,
    Section Variable).
    """
    key = coq_form.lower()
    if key in _EXCLUDED:
        return None
    return _KIND_MAP.get(key, "definition")
