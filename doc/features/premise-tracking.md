# Premise Tracking

Extraction of premise annotations — which lemmas and hypotheses each tactic used — for completed proofs and individual tactic steps.

---

## Problem

Training a neural premise selection model requires knowing which premises (lemmas, hypotheses, constructors, definitions) each tactic actually used. Lean has LeanDojo, which extracts these annotations at scale (122K+ theorems). Coq has no equivalent — the premise information exists inside the Coq kernel during execution but is not exposed to external tools.

Without premise annotations, AI researchers cannot build the premise selection datasets that LLM copilots and CoqHammer-style tools depend on.

## Solution

Two query granularities:

1. **Per-proof premises** — extract premise annotations for every tactic step in a completed proof, returned as a list aligned with the tactic sequence
2. **Per-step premises** — query premise annotations for a single tactic step by index

Each premise annotation includes:
- **Fully qualified name** — e.g., `Coq.Arith.PeanoNat.Nat.add_comm`
- **Kind** — lemma, hypothesis, constructor, or definition

## What Counts as a Premise

A premise is any named entity that a tactic consumes or references during execution:

| Kind | Example | Notes |
|------|---------|-------|
| Lemma/theorem | `Nat.add_comm` | Previously proved results applied or rewritten |
| Hypothesis | `H : n = 0` | Local assumptions from the proof context |
| Constructor | `O`, `S` | Used by tactics like `destruct`, `induction` |
| Definition | `Nat.add` | Unfolded or referenced by computation |

This classification aligns with LeanDojo's premise categories, enabling comparable training data.

## Accuracy Target

Premise annotations must match hand-curated ground truth on a set of at least 50 proofs. This target validates that the extraction is reliable enough for downstream ML training — incorrect annotations would inject noise into training data.

## Design Rationale

### Why premise tracking is P0 alongside proof state observation

Proof states without premises have limited ML value. The (state, tactic, next_state) triple tells you *what* happened; premise annotations tell you *why* — which existing knowledge the tactic relied on. Neural premise selection models are trained to predict this "why" given the current state. Without premise data, the Proof Interaction Protocol enables proof replay but not the training data extraction that motivates it.

### Why per-step query in addition to full-proof query

AI researchers building datasets will use the full-proof query. But tool builders implementing premise-aware search or suggestion need per-step access — they want to know "what did this specific tactic use?" without extracting the entire proof. The per-step API also supports debugging: if a premise annotation looks wrong, the developer can query one step at a time to isolate the issue.

### Why fully qualified names rather than short names

Short names are ambiguous — `add_comm` could be `Nat.add_comm`, `Z.add_comm`, or a local hypothesis. Fully qualified names are unique identifiers that can be resolved across different files and libraries. This is essential for building cross-project training datasets where the same short name appears in multiple contexts.

## Acceptance Criteria

### Get Premise Annotations for Completed Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a session with a completed proof WHEN the get-premises tool is called THEN it returns a per-tactic list of premise annotations
- GIVEN a premise annotation WHEN it is inspected THEN each premise includes its fully qualified name and kind (lemma, hypothesis, constructor, definition)
- GIVEN the premise annotations WHEN they are compared against hand-curated ground truth on a set of ≥ 50 proofs THEN they match the ground truth

### Get Premise Annotations for a Single Step

**Priority:** P0
**Stability:** Stable

- GIVEN a session with a completed proof at step k WHEN the get-step-premises tool is called with step k THEN it returns the premise annotations for that specific tactic step
- GIVEN a step index outside the valid range WHEN the get-step-premises tool is called THEN a structured error is returned indicating the step is out of range
