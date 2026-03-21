# Extraction Benchmarks and Export

Generate benchmark subsets from extracted data, export to ML framework formats, validate traces by replay, and deduplicate across projects.

---

## Problem

Extracted proof traces in JSON Lines format are a raw material, not a finished product for ML researchers. Common downstream needs include: splitting data into train/test/validation sets stratified by difficulty or domain, loading data into HuggingFace Datasets or PyTorch DataLoaders without custom conversion scripts, verifying that extracted traces are faithful to the original proofs, and identifying duplicate proofs across projects that could leak between train and test splits.

Each of these is a standard step in ML dataset preparation that every consumer would otherwise implement independently.

## Solution

Four post-extraction capabilities:

1. **Benchmark subset generation** — split extracted data by difficulty (proof length, tactic diversity), by domain (arithmetic, algebra, logic), or by project, producing reproducible benchmark slices for evaluation

2. **ML framework export** — convert JSON Lines output to HuggingFace Datasets format (and potentially PyTorch-compatible formats), preserving all schema fields so data is directly loadable by standard ML tooling

3. **Proof trace validation** — replay extracted tactic sequences against Coq to confirm they reproduce the original proof, reporting how many traces replayed successfully

4. **Dataset deduplication** — identify and flag semantically equivalent proofs across projects, enabling researchers to build non-leaking train/test splits

## Design Rationale

### Why all four are P2

Each capability adds convenience and rigor but is not required for initial dataset value. Researchers can manually split data, write conversion scripts, spot-check traces, and deduplicate with simple heuristics. These features standardize and automate what would otherwise be ad hoc post-processing. They become important as the user base grows beyond the project's own Phase 4 consumers.

### Why benchmark generation by difficulty, domain, and project

ML evaluation requires controlled splits. Difficulty-based splits (short vs. long proofs, simple vs. diverse tactic usage) reveal whether a model generalizes beyond easy proofs. Domain-based splits test transfer across mathematical areas. Project-based splits test generalization to unseen codebases — the most stringent evaluation. LeanDojo provides project-based splits; adding difficulty and domain splits goes further.

### Why validation by replay rather than static checking

Static analysis can verify that a trace is well-formed JSON with valid field types, but it cannot verify that the tactic sequence actually produces the claimed proof states. Replay — feeding the tactic sequence back to Coq and comparing the resulting states — is the only way to confirm fidelity. This catches extraction bugs where the tactic text or proof state was incorrectly captured.

### Why deduplication across projects rather than within

Within a single project, exact proof duplication is rare. Across projects, it is common: many projects re-prove standard library lemmas, include compatibility shims, or copy proofs from upstream dependencies. If a duplicated proof appears in both the training and test set, evaluation metrics are inflated. Cross-project deduplication prevents this.

## Scope Boundaries

Extraction benchmarks and export provides:

- Benchmark subsets stratified by difficulty, domain, or project
- HuggingFace Datasets export with full schema preservation
- Replay-based trace validation
- Cross-project semantic deduplication

It does **not** provide:

- Model training, evaluation harnesses, or leaderboard infrastructure
- Continuous benchmark updates or CI-driven regeneration
- Tokenization, embedding, or feature engineering for extracted data
- Automated difficulty or domain classification beyond simple heuristics (proof length, tactic counts)

## Acceptance Criteria

### Benchmark Subset Generation

**Priority:** P2
**Stability:** Draft

- GIVEN an extracted dataset WHEN benchmark generation is run with a difficulty split THEN it produces subsets stratified by proof length and tactic diversity
- GIVEN an extracted dataset WHEN benchmark generation is run with a domain split THEN it produces subsets categorized by domain (arithmetic, algebra, logic)
- GIVEN an extracted dataset WHEN benchmark generation is run with a project split THEN it produces per-project subsets

**Traces to:** R3-P2-2

### ML Framework Export

**Priority:** P2
**Stability:** Draft

- GIVEN an extracted dataset WHEN export to HuggingFace Datasets format is run THEN the output is loadable by the `datasets` library
- GIVEN an exported dataset WHEN it is loaded THEN the schema preserves all fields from the JSON Lines format

**Traces to:** R3-P2-3

### Proof Trace Validation by Replay

**Priority:** P2
**Stability:** Draft

- GIVEN an extracted proof trace WHEN it is replayed against Coq THEN the replayed tactic sequence reproduces the original proof
- GIVEN a replay validation run WHEN it completes THEN it reports how many traces replayed successfully and how many failed

**Traces to:** R3-P2-4

### Dataset Deduplication

**Priority:** P2
**Stability:** Draft

- GIVEN a multi-project dataset WHEN deduplication is run THEN semantically equivalent proofs across projects are identified and flagged
- GIVEN a flagged duplicate WHEN it is inspected THEN it includes references to all equivalent proofs

**Traces to:** R3-P2-5
