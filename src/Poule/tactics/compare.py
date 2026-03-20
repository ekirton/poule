"""Tactic comparison.

Spec: specification/tactic-documentation.md section 4.3.
"""

from __future__ import annotations

from itertools import combinations
from typing import Optional

from Poule.tactics.lookup import TacticDocError, tactic_lookup
from Poule.tactics.types import (
    PairwiseDiff,
    SelectionHint,
    TacticComparison,
    TacticInfo,
)

# ---------------------------------------------------------------------------
# Known pairwise knowledge for primitive tactics (no body available)
# ---------------------------------------------------------------------------

_PRIMITIVE_SHARED: dict[frozenset, list[str]] = {
    frozenset({"auto", "eauto"}): [
        "proof search using hint databases",
        "backtracking",
    ],
    frozenset({"auto", "typeclasses eauto"}): [
        "proof search",
        "backtracking",
    ],
    frozenset({"eauto", "typeclasses eauto"}): [
        "proof search using hint databases",
        "backtracking",
        "existential variable instantiation",
    ],
    frozenset({"auto", "trivial"}): [
        "proof search using hint databases",
    ],
    frozenset({"intuition", "tauto"}): [
        "propositional logic decision procedure",
    ],
    frozenset({"lia", "omega"}): [
        "linear arithmetic decision procedure",
    ],
    frozenset({"ring", "field"}): [
        "algebraic normalization",
    ],
    frozenset({"intro", "intros"}): [
        "introduction of universally quantified variables",
    ],
    frozenset({"simpl", "cbn"}): [
        "reduction of terms",
    ],
}

_PRIMITIVE_DIFFS: dict[frozenset, list[str]] = {
    frozenset({"auto", "eauto"}): [
        "eauto supports existential variable instantiation; auto does not",
        "eauto may use Resolve hints with existential parameters; auto requires fully instantiated hints",
    ],
    frozenset({"auto", "typeclasses eauto"}): [
        "typeclasses eauto searches the typeclass_instances database by default; auto uses core",
        "typeclasses eauto supports existential variable instantiation; auto does not",
    ],
    frozenset({"eauto", "typeclasses eauto"}): [
        "typeclasses eauto searches the typeclass_instances database by default; eauto uses core",
        "typeclasses eauto uses a different search strategy optimized for typeclass resolution",
    ],
    frozenset({"auto", "trivial"}): [
        "trivial does not perform backtracking; auto does",
        "trivial only applies hints at cost 0",
    ],
    frozenset({"intuition", "tauto"}): [
        "intuition can produce proof terms for non-purely-propositional goals; tauto is purely propositional",
        "intuition may leave non-propositional subgoals; tauto either closes the goal or fails",
    ],
    frozenset({"lia", "omega"}): [
        "lia handles linear arithmetic over integers and naturals; omega handles only integer arithmetic",
        "lia supersedes omega in modern Coq",
    ],
    frozenset({"intro", "intros"}): [
        "intro introduces exactly one hypothesis; intros introduces all available hypotheses",
        "intros accepts patterns for destructuring",
    ],
    frozenset({"simpl", "cbn"}): [
        "cbn is call-by-name reduction and is generally more predictable than simpl",
        "simpl may unfold more aggressively than cbn",
    ],
}

_PRIMITIVE_PREFER_WHEN: dict[str, list[str]] = {
    "auto": ["all hint arguments are fully determined", "lower search cost is desired"],
    "eauto": ["the goal requires existential variable instantiation", "Resolve hints have uninstantiated parameters"],
    "typeclasses eauto": ["the goal requires typeclass instance resolution", "the typeclass_instances hint database should be searched"],
    "trivial": ["the goal can be closed by a cost-0 hint without backtracking"],
    "intuition": ["the goal contains non-propositional subterms", "partial proof automation is acceptable"],
    "tauto": ["the goal is purely propositional"],
    "lia": ["the goal is a linear arithmetic statement over integers or naturals"],
    "omega": ["the goal is a linear integer arithmetic statement (legacy)"],
    "ring": ["the goal is an algebraic ring equality"],
    "field": ["the goal is an algebraic field equality"],
    "intro": ["introducing exactly one variable is desired"],
    "intros": ["introducing all variables at once is desired"],
    "simpl": ["aggressive reduction is acceptable"],
    "cbn": ["predictable call-by-name reduction is preferred"],
    "destruct": ["case analysis on an inductive type is needed"],
    "induction": ["proof by induction over an inductive type is needed"],
    "reflexivity": ["the goal is a syntactic equality"],
    "congruence": ["the goal follows from equalities in the context by congruence closure"],
    "rewrite": ["a specific rewrite lemma should be applied"],
    "exact": ["a specific term proves the goal exactly"],
    "assumption": ["the goal is already in the hypothesis context"],
    "split": ["the goal is a conjunction"],
    "left": ["the goal is a disjunction and the left branch holds"],
    "right": ["the goal is a disjunction and the right branch holds"],
    "constructor": ["the goal can be proved by applying an inductive constructor"],
    "exists": ["a witness for an existential goal is known"],
    "eexists": ["a witness for an existential goal needs to be inferred"],
}


def _compute_shared_capabilities(tactics: list[TacticInfo]) -> list[str]:
    """Identify capabilities shared by all compared tactics."""
    if len(tactics) == 2:
        key = frozenset({tactics[0].name, tactics[1].name})
        if key in _PRIMITIVE_SHARED:
            return list(_PRIMITIVE_SHARED[key])

    # For Ltac tactics: look for shared referenced tactics across all bodies
    bodies_with_refs = [t for t in tactics if t.body is not None]
    if len(bodies_with_refs) >= 2:
        # Find tactics referenced in all bodies
        ref_sets = [set(t.referenced_tactics) for t in bodies_with_refs]
        shared_refs = ref_sets[0].intersection(*ref_sets[1:])
        if shared_refs:
            return [f"shared use of: {', '.join(sorted(shared_refs))}"]

    # For tactics sharing a category
    categories = {t.category for t in tactics if t.category}
    if len(categories) == 1:
        cat = next(iter(categories))
        return [f"{cat} tactic"]

    return []


def _compute_pairwise_diffs(tactics: list[TacticInfo]) -> list[PairwiseDiff]:
    """Compute pairwise differences between each unique pair of tactics."""
    diffs = []
    for t_a, t_b in combinations(tactics, 2):
        key = frozenset({t_a.name, t_b.name})
        if key in _PRIMITIVE_DIFFS:
            differences = list(_PRIMITIVE_DIFFS[key])
        elif t_a.body is not None and t_b.body is not None:
            # Both are Ltac: compute from bodies
            differences = _analyze_ltac_diffs(t_a, t_b)
        else:
            # Generic structural difference
            differences = _generic_diffs(t_a, t_b)
        diffs.append(PairwiseDiff(
            tactic_a=t_a.name,
            tactic_b=t_b.name,
            differences=differences,
        ))
    return diffs


def _analyze_ltac_diffs(t_a: TacticInfo, t_b: TacticInfo) -> list[str]:
    """Identify differences between two Ltac tactics from their bodies."""
    differences = []
    refs_a = set(t_a.referenced_tactics)
    refs_b = set(t_b.referenced_tactics)

    only_a = refs_a - refs_b
    only_b = refs_b - refs_a

    if only_a:
        differences.append(
            f"{t_a.name} additionally calls: {', '.join(sorted(only_a))}"
        )
    if only_b:
        differences.append(
            f"{t_b.name} additionally calls: {', '.join(sorted(only_b))}"
        )

    # Check superset relationship
    if refs_b and refs_a.issuperset(refs_b):
        differences.append(
            f"{t_a.name} is a superset of {t_b.name} in referenced tactics"
        )
    elif refs_a and refs_b.issuperset(refs_a):
        differences.append(
            f"{t_b.name} is a superset of {t_a.name} in referenced tactics"
        )

    if not differences:
        differences.append(f"{t_a.name} and {t_b.name} have different tactic bodies")

    return differences


def _generic_diffs(t_a: TacticInfo, t_b: TacticInfo) -> list[str]:
    """Produce generic difference descriptions when no specific knowledge is available."""
    differences = []
    if t_a.category != t_b.category:
        cat_a = t_a.category or "unclassified"
        cat_b = t_b.category or "unclassified"
        differences.append(
            f"{t_a.name} is categorized as {cat_a}; {t_b.name} is categorized as {cat_b}"
        )
    else:
        differences.append(
            f"{t_a.name} and {t_b.name} differ in behavior; consult Coq documentation for details"
        )
    return differences


def _compute_selection_guidance(tactics: list[TacticInfo]) -> list[SelectionHint]:
    """Produce selection hints for each tactic."""
    hints = []
    for t in tactics:
        prefer_when = list(_PRIMITIVE_PREFER_WHEN.get(t.name, []))
        if not prefer_when:
            # Derive from category
            if t.category == "automation":
                prefer_when = ["automated proof search is desired"]
            elif t.category == "rewriting":
                prefer_when = ["rewriting or equality reasoning is needed"]
            elif t.category == "case_analysis":
                prefer_when = ["case analysis or induction is needed"]
            elif t.category == "introduction":
                prefer_when = ["introducing hypotheses or variables"]
            elif t.category == "arithmetic":
                prefer_when = ["arithmetic goals need to be discharged"]
            else:
                prefer_when = ["this tactic applies to the current goal"]
        hints.append(SelectionHint(tactic=t.name, prefer_when=prefer_when))
    return hints


async def tactic_compare(
    names: list[str],
    session_id: Optional[str] = None,
    coq_query=None,
) -> TacticComparison:
    """Compare two or more tactics by name and return a structured TacticComparison.

    Spec: section 4.3.
    """
    if len(names) < 2:
        raise TacticDocError(
            "INVALID_ARGUMENT",
            "Comparison requires at least two tactic names.",
        )

    if coq_query is None:
        from Poule.query.handler import coq_query as _coq_query
        from Poule.query.process_pool import ProcessPool

        _pool = ProcessPool()

        async def coq_query(command, argument, session_id=None):
            return await _coq_query(
                command, argument, session_id=session_id, process_pool=_pool,
            )

    resolved: list[TacticInfo] = []
    not_found: list[str] = []

    for name in names:
        try:
            info = await tactic_lookup(name, session_id=session_id, coq_query=coq_query)
            resolved.append(info)
        except TacticDocError as e:
            if e.code == "NOT_FOUND":
                not_found.append(name)
            else:
                raise

    if len(resolved) == 0:
        raise TacticDocError(
            "INVALID_ARGUMENT",
            "Comparison requires at least two valid tactics. None of the provided names were found.",
        )
    if len(resolved) == 1:
        raise TacticDocError(
            "INVALID_ARGUMENT",
            f'Comparison requires at least two valid tactics. Only "{resolved[0].name}" was found.',
        )

    return TacticComparison(
        tactics=resolved,
        shared_capabilities=_compute_shared_capabilities(resolved),
        pairwise_differences=_compute_pairwise_diffs(resolved),
        selection_guidance=_compute_selection_guidance(resolved),
        not_found=not_found,
    )
