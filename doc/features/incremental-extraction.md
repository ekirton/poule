# Incremental Extraction

Re-extract only proofs affected by changed source files, and resume interrupted extraction campaigns without re-processing completed work.

---

## Problem

Full extraction of a large Coq project (stdlib + MathComp + additional libraries) can take significant time. When a researcher modifies a few files in a project and re-runs extraction, re-extracting the entire project is wasteful. When a long extraction campaign crashes or times out partway through, starting over from scratch is unacceptable.

LeanDojo v2 solved this with incremental tracing — re-processing only changed files. Coq extraction needs the same capability to be practical for iterative dataset development.

## Solution

Two complementary capabilities:

1. **Incremental re-extraction** — when a project has been previously extracted and only some source files have changed, re-extract only the affected proofs and merge results with the prior extraction. The resulting dataset is identical to what a full re-extraction would produce.

2. **Campaign resumption** — when an extraction campaign is interrupted (crash, timeout, manual stop), resume from the last completed proof without re-extracting already-completed work. The resulting dataset is identical to what an uninterrupted extraction would produce.

## Design Rationale

### Why incremental re-extraction must produce identical results to full extraction

If incremental and full extraction can diverge, researchers cannot trust incremental results. They would need to periodically run full extractions to verify, defeating the purpose. Guaranteeing identical output means incremental extraction is a pure performance optimization with no correctness tradeoff.

### Why resumption is separate from incremental extraction

Incremental extraction handles the case where source files changed — it must determine which proofs are affected and re-extract them. Resumption handles the case where nothing changed but extraction did not finish — it must pick up where it left off. The two features share checkpointing infrastructure but serve different user needs and have different correctness requirements.

### Why both are P1 rather than P0

The initial value of the extraction pipeline comes from full extraction runs that produce complete datasets. Incremental extraction and resumption are productivity improvements that become important once researchers are iterating on extraction regularly. They are not blocking for initial dataset creation.

## Scope Boundaries

Incremental extraction provides:

- Change-aware re-extraction that processes only affected proofs
- Campaign resumption from the point of interruption
- Output equivalence with full extraction in both cases

It does **not** provide:

- Real-time file watching or automatic re-extraction on save
- Distributed extraction across multiple machines
- Dependency-aware change propagation (if a dependency of a proof changes, that is a full re-extraction scenario)

## Acceptance Criteria

### Incremental Re-Extraction

**Priority:** P1
**Stability:** Stable

- GIVEN a project previously extracted WHEN a subset of .v files have changed THEN only the affected proofs are re-extracted
- GIVEN an incremental re-extraction WHEN it completes THEN the resulting dataset is identical to what a full re-extraction would produce
- GIVEN an incremental re-extraction WHEN it runs THEN it completes faster than a full extraction

**Traces to:** R3-P1-1

### Resume Interrupted Extraction

**Priority:** P1
**Stability:** Stable

- GIVEN an extraction that was interrupted mid-campaign WHEN the extraction command is resumed THEN it continues from the last completed proof without re-extracting already-completed proofs
- GIVEN a resumed extraction WHEN it completes THEN the output is identical to what an uninterrupted extraction would produce

**Traces to:** R3-P1-5
