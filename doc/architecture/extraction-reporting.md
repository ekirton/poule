# Extraction Reporting

How dataset quality reports are generated from extraction output, how extraction scope is configured, and how benchmark subsets and ML exports are produced.

**Feature**: [Extraction Quality Reports](../features/extraction-quality-reports.md), [Extraction Benchmarks and Export](../features/extraction-benchmarks-export.md)
**Data models**: [extraction-types.md](data-models/extraction-types.md) (QualityReport, DistributionStats, TacticFrequency)

---

## Quality Report Pipeline (P1)

```
generate_quality_report(extraction_output_path)
  │
  ├─ Read JSON Lines file, filtering for record_type = "proof_trace"
  │
  ├─ Compute aggregate metrics:
  │    │
  │    ├─ Premise coverage:
  │    │    total_steps_with_premises / total_tactic_steps
  │    │    (step 0 excluded — initial state has no tactic)
  │    │
  │    ├─ Proof length distribution:
  │    │    Collect total_steps for each ExtractionRecord
  │    │    Compute min, max, mean, median, p25, p75, p95
  │    │
  │    └─ Tactic vocabulary:
  │         Extract tactic keyword from each step's tactic text
  │         (first whitespace-delimited token, normalized to lowercase)
  │         Count occurrences, sort descending
  │
  ├─ Compute per-project breakdown:
  │    Group records by project_id, repeat aggregate computation per group
  │
  └─ Emit QualityReport as JSON
```

### Tactic Keyword Extraction

Tactic text is free-form (e.g., `rewrite Nat.add_comm.`, `apply (f_equal S).`, `simpl; reflexivity.`). The tactic keyword is the first whitespace-delimited token, lowercased, with trailing punctuation stripped. Compound tactics (`;`-separated) are split and each sub-tactic is counted independently.

This is a heuristic — it does not fully parse the Ltac grammar. The purpose is to provide a rough vocabulary distribution for dataset assessment, not a precise tactic categorization.

## Scope Configuration

Scope filtering is applied by the Extraction Campaign Orchestrator during theorem enumeration, before extraction begins. The reporting module does not filter — it computes metrics on whatever extraction output it receives.

Configuration options passed to the campaign:

| Option | Type | Effect |
|--------|------|--------|
| Name pattern | glob or regex | Only extract proofs whose fully qualified name matches |
| Module filter | list of module prefixes | Only extract proofs in specified modules |
| (none) | — | Extract all provable theorems (default) |

Filtered (skipped) theorems appear in the ExtractionSummary as `skipped` counts, not in the quality report (which covers only extracted proofs).

## Benchmark Subset Generation (P2)

```
generate_benchmarks(extraction_output_path, split_strategy, output_dir)
  │
  ├─ Read JSON Lines file, filtering for record_type = "proof_trace"
  │
  ├─ Apply split strategy:
  │    │
  │    ├─ By difficulty:
  │    │    Classify by proof length (short: ≤5 steps, medium: 6-20, long: >20)
  │    │    and tactic diversity (count of distinct tactic keywords)
  │    │
  │    ├─ By project:
  │    │    Group by project_id
  │    │
  │    └─ By domain:
  │         Classify by module path heuristics
  │         (Arith* → arithmetic, Algebra* → algebra, Logic* → logic, etc.)
  │
  └─ Write subsets as separate JSON Lines files in output_dir
```

### Difficulty Classification

Difficulty is a composite heuristic, not a learned metric:
- **Proof length**: number of tactic steps (total_steps)
- **Tactic diversity**: number of distinct tactic keywords in the proof
- Thresholds are configurable but have sensible defaults

### Domain Classification

Domain is classified by module path prefix matching — a heuristic that works well for the standard library and MathComp (which have organized module hierarchies) but may be less accurate for projects with flat module structures. This is acceptable for P2 — the feature is a convenience, not a precision tool.

## ML Framework Export (P2)

```
export_to_huggingface(extraction_output_path, output_dir)
  │
  ├─ Read JSON Lines file, filtering for record_type = "proof_trace"
  │
  ├─ Map ExtractionRecord fields to HuggingFace Dataset columns:
  │    theorem_name → string column
  │    source_file  → string column
  │    project_id   → string column
  │    total_steps  → int column
  │    steps        → list column (nested structure preserved)
  │
  ├─ Write Arrow/Parquet files in HuggingFace Datasets format
  │
  └─ Write dataset_info.json with schema metadata
```

The export preserves all fields from the JSON Lines format — no information is lost in conversion. The purpose is format compatibility, not schema transformation.

## Proof Trace Validation (P2)

```
validate_traces(extraction_output_path)
  │
  ├─ Read JSON Lines file, filtering for record_type = "proof_trace"
  │
  ├─ For each ExtractionRecord:
  │    ├─ Open a proof session (same as extraction)
  │    ├─ Replay the tactic sequence from the record
  │    ├─ Compare resulting proof states against recorded states
  │    │    Match: goals, hypotheses at each step
  │    │    Mismatch: record validation failure
  │    └─ Close session
  │
  └─ Report: total validated, total failed, per-failure details
```

Validation replays the extracted tactic sequence against Coq and confirms the resulting proof states match what was recorded. This catches extraction bugs where tactic text or proof states were incorrectly captured.

## Dataset Deduplication (P2)

```
deduplicate(extraction_output_path)
  │
  ├─ Read JSON Lines file, filtering for record_type = "proof_trace"
  │
  ├─ For each pair of proofs, compute semantic similarity:
  │    ├─ Tactic sequence identity (exact match after normalization)
  │    ├─ Goal sequence similarity (initial and final goals match)
  │    └─ Name similarity (same short name across projects)
  │
  ├─ Group semantically equivalent proofs into clusters
  │
  └─ Emit deduplication report:
       Per cluster: list of equivalent proofs with project and file info
```

Semantic equivalence is approximate — exact semantic equivalence would require theorem proving. The heuristic focuses on the common case: proofs that re-prove the same lemma (same initial goal) using the same tactic sequence, possibly in different projects.

## Design Rationale

### Why quality reports are post-hoc rather than inline

Computing quality metrics during extraction would require accumulating statistics across all proofs before emitting the report, which conflicts with streaming output. Post-hoc computation reads the already-produced output file and can be run independently of extraction — useful when a researcher wants to assess a dataset they received, not one they produced.

### Why tactic keyword extraction is a heuristic

Full tactic parsing requires a Coq grammar parser, which is complex and version-dependent. The first-token heuristic captures the tactic family (`rewrite`, `apply`, `induction`) correctly for the vast majority of Coq tactics. The exceptions (Ltac2 expressions, custom notations) are edge cases that affect accuracy marginally for the purpose of vocabulary distribution.

### Why deduplication is approximate

Exact semantic deduplication (are these two proofs proving the same theorem?) is equivalent to theorem equivalence checking, which is undecidable in general. The heuristic approach catches the practical cases: identical proofs copied across projects, compatibility lemmas, and re-derived standard results.
