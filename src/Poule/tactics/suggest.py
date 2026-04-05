"""Contextual tactic suggestion.

Spec: specification/tactic-documentation.md section 4.4,
      specification/neural-training.md §8.2.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from Poule.tactics.types import TacticSuggestion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Neural predictor (lazy singleton)
# ---------------------------------------------------------------------------

_predictor = None  # type: ignore[assignment]
_predictor_checked = False


def _get_predictor():
    """Return the TacticPredictor singleton, or None if unavailable."""
    global _predictor, _predictor_checked
    if _predictor_checked:
        return _predictor
    _predictor_checked = True
    try:
        from Poule.neural.predictor import TacticPredictor

        if TacticPredictor.is_available():
            _predictor = TacticPredictor.load_default()
            logger.info("Neural tactic predictor loaded")
        else:
            logger.debug("Neural tactic predictor not available (model files missing)")
    except Exception:
        logger.debug("Neural tactic predictor not available", exc_info=True)
    return _predictor


# ---------------------------------------------------------------------------
# Argument retriever (lazy singleton)
# ---------------------------------------------------------------------------

_retriever = None  # type: ignore[assignment]
_retriever_checked = False


def _get_retriever():
    """Return the ArgumentRetriever singleton, or None if unavailable."""
    global _retriever, _retriever_checked
    if _retriever_checked:
        return _retriever
    _retriever_checked = True
    try:
        from Poule.tactics.argument_retriever import ArgumentRetriever

        _retriever = ArgumentRetriever(pipeline_context=None)
        logger.debug("Argument retriever initialized (no pipeline context yet)")
    except Exception:
        logger.debug("Argument retriever not available", exc_info=True)
    return _retriever


def set_retriever_context(pipeline_context) -> None:
    """Set the pipeline context for argument retrieval.

    Called when the search index is loaded, enabling argument retrieval
    for tactic suggestions.
    """
    global _retriever, _retriever_checked
    _retriever_checked = True
    try:
        from Poule.tactics.argument_retriever import ArgumentRetriever

        _retriever = ArgumentRetriever(pipeline_context=pipeline_context)
        logger.info("Argument retriever loaded with pipeline context")
    except Exception:
        logger.debug("Argument retriever setup failed", exc_info=True)


class TacticDocError(Exception):
    """Error raised by tactic suggestion operations."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


# ---------------------------------------------------------------------------
# Goal classification
# ---------------------------------------------------------------------------

def _classify_goal(goal_type: str) -> Optional[str]:
    """Return the structural category of a goal type string.

    Returns one of: "conjunction", "disjunction", "existential",
    "equality", "forall", "propositional", "arithmetic", "application", or None.
    """
    t = goal_type.strip()

    # Universal quantification (check before equality: forall x, ... = ... should be forall)
    if t.startswith("forall "):
        return "forall"

    # Existential
    if t.startswith("exists "):
        return "existential"

    # Conjunction: top-level /\
    if "/\\" in t:
        return "conjunction"

    # Disjunction: top-level \/
    if "\\/" in t:
        return "disjunction"

    # Equality: look for " = " at top level (simple heuristic)
    if re.search(r'\s=\s', t):
        return "equality"

    # Arithmetic keywords
    arith_keywords = re.compile(
        r'\b(nat|Z|N|Nat|int|0|[0-9]+)\b|[+\-*/<>≤≥]'
    )
    if arith_keywords.search(t):
        return "arithmetic"

    # Propositional connectives
    if re.search(r'\b(True|False|not|~|->|<->)\b', t):
        return "propositional"

    return "application"


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------

def _suggestions_for_goal(goal_type: str) -> list[dict]:
    """Return ordered candidate suggestions based on goal classification."""
    category = _classify_goal(goal_type)
    candidates = []

    if category == "equality":
        # Reflexivity check: both sides of = appear identical
        m = re.search(r'^(.+)\s=\s(.+)$', goal_type.strip())
        if m and m.group(1).strip() == m.group(2).strip():
            candidates.append({
                "tactic": "reflexivity",
                "confidence": "high",
                "rationale": "Goal is a reflexive equality",
                "category": "rewriting",
            })
        else:
            candidates.append({
                "tactic": "reflexivity",
                "confidence": "high",
                "rationale": "Goal is an equality; reflexivity may close it if both sides are definitionally equal",
                "category": "rewriting",
            })
        candidates += [
            {
                "tactic": "congruence",
                "confidence": "medium",
                "rationale": "congruence can close equality goals derivable from context",
                "category": "rewriting",
            },
            {
                "tactic": "rewrite",
                "confidence": "medium",
                "rationale": "rewriting with a hypothesis or lemma may simplify the equality",
                "category": "rewriting",
            },
        ]

    elif category == "conjunction":
        candidates += [
            {
                "tactic": "split",
                "confidence": "high",
                "rationale": "Goal is a conjunction; split produces two subgoals",
                "category": "case_analysis",
            },
            {
                "tactic": "constructor",
                "confidence": "medium",
                "rationale": "constructor applies the conjunction introduction rule",
                "category": "case_analysis",
            },
        ]

    elif category == "disjunction":
        candidates += [
            {
                "tactic": "left",
                "confidence": "medium",
                "rationale": "Goal is a disjunction; prove the left disjunct",
                "category": "case_analysis",
            },
            {
                "tactic": "right",
                "confidence": "medium",
                "rationale": "Goal is a disjunction; prove the right disjunct",
                "category": "case_analysis",
            },
            {
                "tactic": "destruct",
                "confidence": "medium",
                "rationale": "Destructing a hypothesis may enable the disjunction proof",
                "category": "case_analysis",
            },
        ]

    elif category == "existential":
        candidates += [
            {
                "tactic": "exists",
                "confidence": "high",
                "rationale": "Goal is an existential; provide a witness",
                "category": "case_analysis",
            },
            {
                "tactic": "eexists",
                "confidence": "medium",
                "rationale": "eexists provides an existential witness to be inferred",
                "category": "case_analysis",
            },
        ]

    elif category == "forall":
        candidates += [
            {
                "tactic": "intro",
                "confidence": "high",
                "rationale": "Goal is a universal quantification; introduce the bound variable",
                "category": "introduction",
            },
            {
                "tactic": "intros",
                "confidence": "high",
                "rationale": "Introduces all universally quantified variables",
                "category": "introduction",
            },
            {
                "tactic": "induction",
                "confidence": "medium",
                "rationale": "Goal quantifies over an inductive type; induction is a common proof strategy",
                "category": "case_analysis",
            },
        ]

    elif category == "arithmetic":
        candidates += [
            {
                "tactic": "lia",
                "confidence": "medium",
                "rationale": "Goal appears to be a linear arithmetic statement",
                "category": "arithmetic",
            },
            {
                "tactic": "ring",
                "confidence": "medium",
                "rationale": "ring can solve ring equality goals",
                "category": "arithmetic",
            },
            {
                "tactic": "omega",
                "confidence": "medium",
                "rationale": "omega handles linear integer arithmetic",
                "category": "arithmetic",
            },
        ]

    elif category == "propositional":
        candidates += [
            {
                "tactic": "tauto",
                "confidence": "medium",
                "rationale": "Goal appears to be a propositional tautology",
                "category": "automation",
            },
            {
                "tactic": "intuition",
                "confidence": "medium",
                "rationale": "intuition handles propositional logic and may leave non-propositional subgoals",
                "category": "automation",
            },
        ]

    else:
        # application or unknown: low-confidence general strategies
        candidates += [
            {
                "tactic": "unfold",
                "confidence": "low",
                "rationale": "Unfold defined constants to expose the goal structure",
                "category": "rewriting",
            },
            {
                "tactic": "simpl",
                "confidence": "low",
                "rationale": "Reduce the goal using simplification",
                "category": "rewriting",
            },
            {
                "tactic": "auto",
                "confidence": "low",
                "rationale": "No specific tactic identified; auto may close the goal via hint databases",
                "category": "automation",
            },
        ]

    # Always append general tactics at low priority (but not if they duplicate)
    tactic_names = {c["tactic"] for c in candidates}
    if "auto" not in tactic_names:
        candidates.append({
            "tactic": "auto",
            "confidence": "low",
            "rationale": "General proof search via hint databases",
            "category": "automation",
        })

    return candidates


def _suggestions_from_hypotheses(hypotheses, goal_type: str) -> list[dict]:
    """Generate tactic suggestions based on hypothesis shapes."""
    suggestions = []
    for hyp in hypotheses:
        h_name = hyp.name
        h_type = hyp.type.strip()

        # H : goal_type => exact H / assumption
        if h_type == goal_type.strip():
            suggestions.append({
                "tactic": f"exact {h_name}",
                "confidence": "high",
                "rationale": f"Hypothesis {h_name} has exactly the goal type",
                "category": "rewriting",
            })
            suggestions.append({
                "tactic": "assumption",
                "confidence": "high",
                "rationale": "The goal is already in the hypothesis context",
                "category": "rewriting",
            })
            continue

        # H : x = y => rewrite H
        if re.search(r'\s=\s', h_type):
            suggestions.append({
                "tactic": f"rewrite {h_name}",
                "confidence": "medium",
                "rationale": f"Hypothesis {h_name} is an equality that may simplify the goal",
                "category": "rewriting",
            })

        # H : A /\ B, H : A \/ B, H : exists x, P x => destruct H
        elif "/\\" in h_type:
            suggestions.append({
                "tactic": f"destruct {h_name}",
                "confidence": "medium",
                "rationale": f"Hypothesis {h_name} is a conjunction; destruct produces components",
                "category": "case_analysis",
            })
        elif "\\/" in h_type:
            suggestions.append({
                "tactic": f"destruct {h_name}",
                "confidence": "medium",
                "rationale": f"Hypothesis {h_name} is a disjunction; destruct performs case analysis",
                "category": "case_analysis",
            })
        elif h_type.startswith("exists "):
            suggestions.append({
                "tactic": f"destruct {h_name}",
                "confidence": "medium",
                "rationale": f"Hypothesis {h_name} is an existential; destruct extracts the witness",
                "category": "case_analysis",
            })

    return suggestions


def _rank_candidates(candidates: list[dict]) -> list[dict]:
    """Deduplicate and sort candidates, assigning ranks."""
    seen_tactics: set[str] = set()
    deduped = []
    for c in candidates:
        if c["tactic"] not in seen_tactics:
            seen_tactics.add(c["tactic"])
            deduped.append(c)

    # Sort: high > medium > low
    order = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda c: order.get(c["confidence"], 3))

    return deduped


async def tactic_suggest(
    session_id: str,
    limit: int = 10,
    observe_proof_state=None,
) -> list[TacticSuggestion]:
    """Return a ranked list of tactic suggestions for the current proof state.

    Spec: section 4.4.
    """
    # Clamp limit to at least 1
    if limit <= 0:
        limit = 1

    # Retrieve proof state; propagate SESSION_NOT_FOUND if raised
    proof_state = await observe_proof_state(session_id)

    if proof_state.is_complete or not proof_state.goals:
        raise TacticDocError(
            "SESSION_REQUIRED",
            "Tactic suggestion requires at least one open goal. The proof is complete.",
        )

    # Get focused goal
    focused_index = proof_state.focused_goal_index or 0
    goal = proof_state.goals[focused_index]
    goal_type = goal.type
    hypotheses = goal.hypotheses

    # ---------------------------------------------------------------------------
    # Neural predictions (spec §8.2)
    # ---------------------------------------------------------------------------
    neural_suggestions: list[TacticSuggestion] = []
    predictor = _get_predictor()
    if predictor is not None:
        try:
            # Build proof state text: "hyp_name : hyp_type\n...\ngoal_type"
            lines = [f"{h.name} : {h.type}" for h in hypotheses]
            lines.append(goal_type)
            proof_state_text = "\n".join(lines)

            predictions = predictor.predict_with_category(proof_state_text, top_k=5)
            retriever = _get_retriever()

            for prediction in predictions:
                if len(prediction) == 3:
                    family_name, pred_category, confidence = prediction
                else:
                    family_name, confidence = prediction[0], prediction[1]
                    pred_category = "neural"

                conf_label = (
                    "high" if confidence >= 0.3
                    else "medium" if confidence >= 0.1
                    else "low"
                )
                # Family-only suggestion
                neural_suggestions.append(
                    TacticSuggestion(
                        tactic=family_name,
                        rank=0,  # assigned below
                        rationale=f"Neural prediction (confidence: {confidence:.0%})",
                        confidence=conf_label,
                        category=pred_category or "neural",
                        source="neural",
                    )
                )
                # Argument-enriched suggestions (spec §8.4)
                if retriever is not None and confidence >= 0.1:
                    try:
                        candidates = retriever.retrieve(
                            family_name, goal_type, hypotheses, limit=3,
                        )
                        for cand in candidates:
                            combined_score = confidence * cand.score
                            arg_conf = (
                                "high" if combined_score >= 0.25
                                else "medium" if combined_score >= 0.08
                                else "low"
                            )
                            neural_suggestions.append(
                                TacticSuggestion(
                                    tactic=f"{family_name} {cand.name}",
                                    rank=0,
                                    rationale=f"Neural prediction + retrieval ({cand.name}, score: {cand.score:.0%})",
                                    confidence=arg_conf,
                                    category="neural",
                                    source="neural+retrieval",
                                )
                            )
                    except Exception:
                        logger.debug(
                            "Argument retrieval failed for %s", family_name,
                            exc_info=True,
                        )
        except Exception:
            logger.debug("Neural prediction failed, falling back to rules", exc_info=True)

    # ---------------------------------------------------------------------------
    # Rule-based candidates (existing behavior)
    # ---------------------------------------------------------------------------

    # Build candidates from goal classification
    goal_candidates = _suggestions_for_goal(goal_type)

    # Build candidates from hypotheses
    hyp_candidates = _suggestions_from_hypotheses(hypotheses, goal_type)

    # Merge: hypothesis-derived suggestions come first (they're more specific)
    all_candidates = hyp_candidates + goal_candidates

    ranked = _rank_candidates(all_candidates)

    rule_suggestions = [
        TacticSuggestion(
            tactic=c["tactic"],
            rank=0,  # assigned below
            rationale=c["rationale"],
            confidence=c["confidence"],
            category=c["category"],
            source="rule",
        )
        for c in ranked
    ]

    # ---------------------------------------------------------------------------
    # Merge: neural first, then rule-based (excluding duplicates)
    # ---------------------------------------------------------------------------
    neural_tactic_names = {s.tactic for s in neural_suggestions}
    merged = list(neural_suggestions)
    for s in rule_suggestions:
        if s.tactic not in neural_tactic_names:
            merged.append(s)

    # Assign final ranks and apply limit
    merged = merged[:limit]
    for i, s in enumerate(merged):
        s.rank = i + 1

    return merged
