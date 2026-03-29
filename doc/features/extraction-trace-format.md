# Extraction Trace Format

The structured output format for extracted proof traces: what each record contains, how records are organized, and what metadata accompanies the dataset.

---

## Problem

Existing Coq proof datasets (CoqGym) use ad hoc formats that conflate proof text with metadata, lack premise annotations, and provide no schema versioning. Downstream consumers must reverse-engineer the format from examples. When the format changes, tools break silently.

AI researchers need two things from the same dataset: linearized proof traces for tactic prediction (state → tactic → next_state) and premise annotation pairs for retrieval training (goal → premises_used). No existing format serves both consumers in a unified schema.

## Solution

The extraction pipeline produces **compact training data** in JSON Lines format. Each line is a self-contained record in one of these types:

- **Pair record** (`"t": "p"`) — one per tactic step that used premises: serialized proof state, source file path, and the premises the tactic actually used (determined by proof term analysis)
- **Goal-state record** (`"t": "g"`) — supplementary serialized proof states not covered by any pair, for vocabulary construction
- **Metadata/error/summary records** — provenance, extraction errors, and campaign statistics (passed through unchanged)

This compact format replaces the original full proof trace format. The extraction pipeline writes compact records directly — no post-processing step is needed. Each training pair is typically 200-500 bytes, making the output several orders of magnitude smaller than full proof traces.

The dataset includes provenance metadata: Coq version, project commit hash, extraction tool version, and extraction timestamp.

## Design Rationale

### Why JSON Lines over alternatives

JSON Lines (one JSON object per line) enables streaming consumption — a consumer can process records one at a time without loading the entire dataset. This matters at scale: a 100K-theorem dataset in a single JSON array would require full deserialization before any record is accessible. JSON Lines also enables parallel processing (split by line), append-friendly writes (crash recovery loses at most one record), and simple concatenation of multi-project outputs.

Alternatives considered:
- **Parquet/Arrow**: better compression and columnar access, but requires specialized tooling and is harder to inspect manually. A P2 requirement covers ML framework export for this use case.
- **SQLite**: good for random access, but streaming writes are slower and the format is harder to diff in version control.
- **Protocol Buffers**: compact and fast, but adds a compilation step and reduces accessibility for researchers who want to inspect data with standard tools.

### Why per-step granularity rather than per-proof summaries

Tactic prediction models need the (state_k, tactic_k, state_{k+1}) triple at every step. Premise selection models need the (goal_k, premises_k) pair at every step. Per-proof summaries (e.g., "this proof used these 12 lemmas") lose step-level alignment, which is critical for training both model types. LeanDojo uses per-step granularity for the same reason.

### Why include both full states and diffs

Full proof states at every step are self-contained — a consumer can process any step independently without reading prior steps. Diffs capture the tactic's effect compactly — "this tactic split one goal into two and added a hypothesis." Both views are valuable: full states for training, diffs for analysis and visualization. Including both avoids forcing every consumer to compute diffs from full states.

### Why provenance metadata is P0

Without provenance, a dataset file is an opaque artifact. Researchers need to know: which Coq version compiled the project (behavior varies across versions), which commit of the project was extracted (proofs change over time), which version of the extraction tool produced the output (schema may evolve), and when extraction happened (for audit trails). This metadata enables exact reproduction of any dataset.

### Why schema versioning in every record

When the extraction format evolves, downstream tools must detect the change. A schema version field in each record (not just in file-level metadata) means that even concatenated or shuffled datasets remain self-describing. A consumer can handle mixed-version datasets by dispatching on the version field.

## Scope Boundaries

The extraction trace format provides:

- Per-step proof states, tactics, and premise annotations in a unified record
- JSON Lines output with schema versioning
- Provenance metadata for reproducibility
- Proof state diffs alongside full snapshots (P1)

It does **not** provide:

- ML-framework-specific formats (HuggingFace, PyTorch — separate P2 feature)
- Compressed or columnar formats (Parquet, Arrow)
- Tokenized or embedded representations of proof states
- Cross-proof or cross-project aggregation (that is a dataset-level concern)

## Acceptance Criteria

### Per-Step Proof State and Tactic Capture

**Priority:** P0
**Stability:** Stable

- GIVEN a proof of N tactic steps WHEN the trace record is inspected THEN it contains N+1 proof states and N tactic texts, one per step
- GIVEN a proof state at step k WHEN it is inspected THEN it includes all open goals, hypotheses, and local context at that step
- GIVEN a proof trace record WHEN it is inspected THEN it includes the theorem's fully qualified name and source file path

**Traces to:** R3-P0-2

### Per-Step Premise Annotations

**Priority:** P0
**Stability:** Stable

- GIVEN a proof trace record WHEN the premise annotations are inspected THEN each tactic step includes a list of premises used by that tactic
- GIVEN a premise annotation WHEN it is inspected THEN each premise includes its fully qualified name and kind (lemma, hypothesis, constructor, or definition)
- GIVEN the premise annotations for a validation set of ≥ 100 proofs WHEN compared against hand-curated ground truth THEN they match the ground truth

**Traces to:** R3-P0-2

### Proof State Diffs

**Priority:** P1
**Stability:** Stable

- GIVEN consecutive proof states at steps k and k+1 WHEN the diff is inspected THEN it includes goals added, goals removed, goals changed, hypotheses added, hypotheses removed, and hypotheses changed
- GIVEN the diffs in a proof trace WHEN they are inspected alongside full proof state snapshots THEN both representations are present in the output

**Traces to:** R3-P1-6

### JSON Lines Output

**Priority:** P0
**Stability:** Stable

- GIVEN a completed extraction WHEN the output file is inspected THEN each line is a valid JSON object representing one proof trace
- GIVEN the output WHEN it is inspected THEN it includes a declared schema version field in each record
- GIVEN the output WHEN it is processed line by line THEN each line is independently parseable without reference to other lines

**Traces to:** R3-P0-3

### Provenance Metadata

**Priority:** P0
**Stability:** Stable

- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the Coq version used to build the project
- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the project's git commit hash
- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the extraction tool version and extraction timestamp

**Traces to:** R3-P0-11
