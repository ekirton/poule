# Training Data Extraction Types

Canonical definitions for all data types used in batch proof trace extraction — extraction records, campaign metadata, error records, and quality metrics. These types are produced by the Extraction Campaign Orchestrator, serialized to JSON Lines output, and consumed by downstream ML pipelines.

**Architecture docs**: [extraction-campaign.md](../extraction-campaign.md), [extraction-output.md](../extraction-output.md), [extraction-reporting.md](../extraction-reporting.md)

---

## ExtractionRecord

A single proof's extracted data: the proof trace with premise annotations, ready for ML consumption.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; identifies the extraction output format version |
| `record_type` | text | Required; literal `"proof_trace"` — discriminator for JSON Lines parsing |
| `theorem_name` | qualified name | Required; fully qualified name (e.g., `Coq.Arith.PeanoNat.Nat.add_comm`) |
| `source_file` | text | Required; path relative to project root |
| `project_id` | text | Required; identifier for the source project (see CampaignMetadata) |
| `total_steps` | non-negative integer | Required; number of tactic steps in the proof |
| `steps` | list of ExtractionStep | Required; N+1 entries for N tactic steps (step 0 = initial state) |

### Relationships

- **Belongs to** one project (via `project_id`).
- **Contains** one or more ExtractionStep objects (1:*; ordered by step_index).

---

## ExtractionStep

A single step within a proof trace, combining proof state, tactic, and premise annotations.

| Field | Type | Constraints |
|-------|------|-------------|
| `step_index` | non-negative integer | Required; 0 = initial state |
| `tactic` | text or null | Required; null for step 0 (initial state); tactic text for all subsequent steps |
| `goals` | list of Goal | Required; open goals at this step (reuses Goal from proof-types.md) |
| `focused_goal_index` | non-negative integer or null | Required; null when proof is complete |
| `premises` | list of Premise | Required; premises used by this step's tactic; empty list for step 0 |
| `diff` | ExtractionDiff or null | P1; null for step 0; diff from previous state for subsequent steps; null when diffs are not requested |

### Relationships

- **Belongs to** one ExtractionRecord (ordered within `steps`).
- **Contains** zero or more Goal objects (reused from [proof-types.md](proof-types.md)).
- **Contains** zero or more Premise objects.

---

## Premise

A single premise used by a tactic step.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | qualified name | Required; fully qualified name for global premises; short name for local hypotheses |
| `kind` | text | Required; one of: `lemma`, `hypothesis`, `constructor`, `definition` |

### Notes

This type mirrors the premise structure in PremiseAnnotation ([proof-types.md](proof-types.md)) but is embedded directly in ExtractionStep rather than existing as a separate per-step annotation. The classification rules are identical to those in [proof-session.md](../proof-session.md) § Premise Classification.

---

## ExtractionDiff

The change between consecutive proof states at step k-1 and step k. Structurally identical to ProofStateDiff in [proof-types.md](proof-types.md), embedded within ExtractionStep for self-contained records.

| Field | Type | Constraints |
|-------|------|-------------|
| `goals_added` | list of Goal | Required; goals present at step k but not step k-1 |
| `goals_removed` | list of Goal | Required; goals present at step k-1 but not step k |
| `goals_changed` | list of GoalChange | Required; goals present in both with differing types |
| `hypotheses_added` | list of Hypothesis | Required; hypotheses present at step k but not step k-1 |
| `hypotheses_removed` | list of Hypothesis | Required; hypotheses present at step k-1 but not step k |
| `hypotheses_changed` | list of HypothesisChange | Required; hypotheses present in both with differing types or bodies |

### Notes

GoalChange and HypothesisChange are as defined in [proof-types.md](proof-types.md). Diff computation uses the same algorithm specified in [proof-serialization.md](../proof-serialization.md) § Diff Computation.

---

## ExtractionError

A structured error record emitted when a single proof fails to extract. Appears in the same JSON Lines output stream as ExtractionRecord entries.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; same version as ExtractionRecord |
| `record_type` | text | Required; literal `"extraction_error"` — discriminator |
| `theorem_name` | qualified name | Required; fully qualified name of the proof that failed |
| `source_file` | text | Required; path relative to project root |
| `project_id` | text | Required; identifier for the source project |
| `error_kind` | text | Required; one of: `timeout`, `backend_crash`, `tactic_failure`, `load_failure`, `no_proof_body`, `unknown` |
| `error_message` | text | Required; human-readable description of the failure |

### Relationships

- **Belongs to** one project (via `project_id`).

---

## CampaignMetadata

Top-level metadata for an extraction campaign. Emitted as the first record in the JSON Lines output.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; same version as ExtractionRecord |
| `record_type` | text | Required; literal `"campaign_metadata"` |
| `extraction_tool_version` | text | Required; semantic version of the extraction tool |
| `extraction_timestamp` | timestamp | Required; ISO 8601; time extraction started |
| `projects` | list of ProjectMetadata | Required; one entry per project in the campaign |

---

## ProjectMetadata

Per-project provenance within a campaign.

| Field | Type | Constraints |
|-------|------|-------------|
| `project_id` | text | Required; unique within the campaign; derived from project directory name |
| `project_path` | text | Required; absolute path to the project directory |
| `coq_version` | text | Required; Coq/Rocq version used to build the project |
| `commit_hash` | text or null | Required; git commit hash of the project; null if not a git repository |

### Relationships

- **Belongs to** one CampaignMetadata.

---

## ExtractionSummary

Summary statistics for a completed extraction campaign. Emitted as the last record in the JSON Lines output.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; same version as ExtractionRecord |
| `record_type` | text | Required; literal `"extraction_summary"` |
| `total_theorems_found` | non-negative integer | Required |
| `total_extracted` | non-negative integer | Required |
| `total_failed` | non-negative integer | Required |
| `total_no_proof_body` | non-negative integer | Required; declarations without proof bodies (expected, not failures) |
| `total_skipped` | non-negative integer | Required |
| `per_project` | list of ProjectSummary | Required |

---

## ProjectSummary

Per-project extraction statistics.

| Field | Type | Constraints |
|-------|------|-------------|
| `project_id` | text | Required |
| `theorems_found` | non-negative integer | Required |
| `extracted` | non-negative integer | Required |
| `failed` | non-negative integer | Required |
| `no_proof_body` | non-negative integer | Required; declarations without proof bodies |
| `skipped` | non-negative integer | Required |
| `per_file` | list of FileSummary | Required |

---

## FileSummary

Per-file extraction statistics within a project.

| Field | Type | Constraints |
|-------|------|-------------|
| `source_file` | text | Required; path relative to project root |
| `theorems_found` | non-negative integer | Required |
| `extracted` | non-negative integer | Required |
| `failed` | non-negative integer | Required |
| `no_proof_body` | non-negative integer | Required; declarations without proof bodies |
| `skipped` | non-negative integer | Required |

---

## DependencyEntry

A single node in the theorem-level dependency graph (P1).

| Field | Type | Constraints |
|-------|------|-------------|
| `theorem_name` | qualified name | Required; fully qualified name of the theorem |
| `source_file` | text | Required; path relative to project root |
| `project_id` | text | Required |
| `depends_on` | list of DependencyRef | Required; the theorems, definitions, and axioms this proof uses |

---

## DependencyRef

A reference to a dependency in the dependency graph.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | qualified name | Required; fully qualified name |
| `kind` | text | Required; one of: `theorem`, `lemma`, `definition`, `axiom`, `constructor`, `inductive` |

---

## QualityReport

Dataset quality metrics for a completed extraction (P1).

| Field | Type | Constraints |
|-------|------|-------------|
| `premise_coverage` | float | Required; fraction of tactic steps with ≥ 1 annotated premise (0.0–1.0) |
| `proof_length_distribution` | DistributionStats | Required |
| `tactic_vocabulary` | list of TacticFrequency | Required; sorted by count descending |
| `per_project` | list of ProjectQualityReport | Required |

---

## DistributionStats

Summary statistics for a numeric distribution.

| Field | Type | Constraints |
|-------|------|-------------|
| `min` | non-negative integer | Required |
| `max` | non-negative integer | Required |
| `mean` | float | Required |
| `median` | float | Required |
| `p25` | float | Required; 25th percentile |
| `p75` | float | Required; 75th percentile |
| `p95` | float | Required; 95th percentile |

---

## TacticFrequency

A tactic name and its occurrence count.

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | text | Required; the tactic keyword (e.g., `rewrite`, `apply`, `induction`) |
| `count` | positive integer | Required |

---

## ProjectQualityReport

Per-project quality metrics within a quality report.

| Field | Type | Constraints |
|-------|------|-------------|
| `project_id` | text | Required |
| `premise_coverage` | float | Required |
| `proof_length_distribution` | DistributionStats | Required |
| `theorem_count` | non-negative integer | Required |

---

## ErrorAnalysisReport

Aggregated error analysis for one or more extraction output files (P1).

| Field | Type | Constraints |
|-------|------|-------------|
| `files_analyzed` | positive integer | Required; number of JSONL files read |
| `total_theorems` | non-negative integer | Required; total proof_trace + extraction_error records |
| `total_extracted` | non-negative integer | Required; count of proof_trace records |
| `total_failed` | non-negative integer | Required; count of extraction_error records |
| `by_error_kind` | dict mapping text to non-negative integer | Required; error_kind string → count |
| `by_file` | list of FileErrorSummary | Required; sorted by error count descending |
| `near_timeout` | list of NearTimeoutEntry | Required; successful proofs within 10% of the timeout threshold |
| `slowest_successful` | list of TimingEntry | Required; top-N slowest successful extractions by total duration |
| `timeout_threshold` | positive integer | Required; the timeout value in seconds used for near-timeout detection |

---

## FileErrorSummary

Per-source-file error breakdown within an ErrorAnalysisReport.

| Field | Type | Constraints |
|-------|------|-------------|
| `source_file` | text | Required; source file path |
| `error_count` | non-negative integer | Required; total errors in this file |
| `by_kind` | dict mapping text to non-negative integer | Required; error_kind → count within this file |

---

## NearTimeoutEntry

A successful proof that completed within 10% of the timeout threshold.

| Field | Type | Constraints |
|-------|------|-------------|
| `theorem_name` | qualified name | Required |
| `source_file` | text | Required |
| `total_duration_s` | float | Required; total extraction duration in seconds |

---

## TimingEntry

A successful proof with its total extraction duration.

| Field | Type | Constraints |
|-------|------|-------------|
| `theorem_name` | qualified name | Required |
| `source_file` | text | Required |
| `total_duration_s` | float | Required; total extraction duration in seconds |
