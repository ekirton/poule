# Extraction Quality Reports

Dataset quality metrics and configurable extraction scope, enabling researchers to assess fitness of extracted data and build focused datasets.

---

## Problem

An extracted dataset's raw theorem count tells researchers little about its fitness for training. Key questions remain unanswered: What fraction of tactic steps have premise annotations? Are proof lengths distributed evenly or dominated by trivial one-step proofs? Which tactics appear frequently enough to train on? Without quality metrics, researchers must write custom analysis scripts before they can assess whether a dataset is usable.

Separately, researchers building domain-specific models (e.g., arithmetic reasoning, algebraic proofs) need to extract focused subsets without processing entire projects and filtering after the fact.

## Solution

Two capabilities:

1. **Quality reports** — after extraction, generate metrics including:
   - Premise annotation coverage (percentage of tactic steps with at least one annotated premise)
   - Distribution of proof lengths (number of tactic steps per proof)
   - Tactic vocabulary frequency (which tactics appear and how often)
   - Per-project breakdowns of all metrics in multi-project extractions

2. **Configurable extraction scope** — restrict extraction to:
   - Proofs matching a name pattern (e.g., all theorems containing "add" or "mul")
   - Proofs in specified modules (e.g., only `Coq.Arith.*`)
   - All proofs (default behavior when no filter is specified)

## Design Rationale

### Why quality reports are P1 rather than P0

The P0 extraction summary (Epic 5) provides operational metrics — how many proofs succeeded or failed. Quality reports go further: they characterize the *content* of successful extractions. This is valuable for dataset assessment but not blocking for initial extraction. Researchers can compute these metrics from the JSON Lines output themselves; the feature saves effort and standardizes the analysis.

### Why premise annotation coverage is the lead metric

Premise annotations are the primary differentiator of this pipeline over CoqGym. A dataset where 95% of tactic steps have premise annotations is far more valuable for premise selection training than one where only 30% do. Leading with this metric lets researchers quickly assess whether the dataset meets their needs.

### Why configurable scope rather than post-hoc filtering

Filtering after extraction wastes compute — extracting 50K proofs to keep 2K is inefficient. Pre-extraction filtering is especially valuable during development: a researcher iterating on extraction quality for arithmetic proofs should not wait for the entire library to extract on each iteration. Scope configuration also enables focused quality assessment of specific domains.

## Scope Boundaries

Extraction quality reports provide:

- Premise annotation coverage, proof length distribution, and tactic frequency metrics
- Per-project breakdowns for multi-project extractions
- Name-pattern and module-based extraction scope filtering

It does **not** provide:

- Automated quality thresholds or pass/fail judgments
- Semantic categorization of proofs by domain (arithmetic, algebra, etc. — that requires understanding proof content, not just names)
- Comparison across extraction runs or dataset versions
- Recommendations for improving extraction coverage

## Acceptance Criteria

### Dataset Quality Reports

**Priority:** P1
**Stability:** Stable

- GIVEN a completed extraction WHEN the quality report is generated THEN it includes premise annotation coverage (percentage of tactic steps with at least one annotated premise)
- GIVEN a completed extraction WHEN the quality report is generated THEN it includes distribution of proof lengths and tactic vocabulary frequency
- GIVEN a multi-project extraction WHEN the quality report is generated THEN it includes per-project breakdowns of all metrics

**Traces to:** R3-P1-3

### Configurable Extraction Scope

**Priority:** P1
**Stability:** Stable

- GIVEN an extraction with a name pattern filter WHEN extraction runs THEN only proofs whose fully qualified names match the pattern are extracted
- GIVEN an extraction with a module filter WHEN extraction runs THEN only proofs in the specified modules are extracted
- GIVEN no filter is specified WHEN extraction runs THEN all provable theorems are extracted (default behavior)

**Traces to:** R3-P1-4
