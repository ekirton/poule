# Extraction Output Format

JSON Lines serialization of extraction records, provenance metadata, and summary statistics for batch proof trace extraction.

**Architecture**: [extraction-output.md](../doc/architecture/extraction-output.md), [extraction-types.md](../doc/architecture/data-models/extraction-types.md)

---

## 1. Purpose

Define the serialization format for all extraction output types — ExtractionRecord, ExtractionError, CampaignMetadata, and ExtractionSummary — and the determinism contract that guarantees byte-identical output for identical inputs.

## 2. Scope

**In scope**: JSON Lines stream structure, record type discrimination, field ordering for all extraction types, determinism rules, streaming write contract.

**Out of scope**: Extraction logic (owned by extraction-campaign), session management (owned by proof-session), Phase 2 proof serialization (owned by proof-serialization — this spec extends those conventions to batch extraction types).

## 3. Definitions

| Term | Definition |
|------|-----------|
| JSON Lines | A text format where each line is a valid JSON object, newline-delimited (one record per line) |
| Record type | The `record_type` string field present in every output record, used as a discriminator for parsing |
| Provenance | Metadata identifying how a dataset was produced: tool version, Coq version, project commit, timestamp |

## 4. Behavioral Requirements

### 4.1 Output Stream Structure

The system shall write output as a single JSON Lines file in **compact training data format**:

| Position | Record type | Discriminator | Cardinality |
|----------|-------------|---------------|-------------|
| First line | `campaign_metadata` | `"record_type": "campaign_metadata"` | Exactly one |
| Body lines | Pair records | `"t": "p"` | Zero or more (one per tactic step with premises) |
| Body lines | Goal-state records | `"t": "g"` | Zero or more (supplementary states for vocabulary) |
| Body lines | Extraction errors | `"record_type": "extraction_error"` | Zero or more |
| Last line | `extraction_summary` | `"record_type": "extraction_summary"` | Exactly one |

Each pair record contains a serialized proof state, source file path, and the premises the tactic actually used (determined by proof term diffing). Goal-state records contain supplementary proof states not covered by any pair, for vocabulary construction.

MAINTAINS: Every JSON object in the output contains either a `"t"` field (compact records) or a `"record_type"` field (metadata/error/summary records).

> **Given** a campaign that extracts 10 proofs (30 tactic steps total, 20 with premises) with 2 failures
> **When** the output is written
> **Then** the file contains: 1 metadata + 20 pair records + supplementary goal records + 2 extraction_error + 1 summary

> **Given** a campaign with zero theorems found
> **When** the output is written
> **Then** the file contains exactly 2 lines: 1 metadata + 1 summary

#### 4.1.1 Compact Pair Record

| Field | JSON type | Description |
|-------|-----------|-------------|
| `t` | `"p"` | Record type discriminator |
| `f` | string | Source file path (for file-level splitting) |
| `s` | string | Serialized proof state (output of `serialize_goals`) |
| `p` | array of string | Premise names actually used by this tactic step |

#### 4.1.2 Compact Goal-State Record

| Field | JSON type | Description |
|-------|-----------|-------------|
| `t` | `"g"` | Record type discriminator |
| `s` | string | Serialized proof state |

### 4.2 CampaignMetadata Serialization

The system shall serialize CampaignMetadata with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `schema_version` | integer | Constant: current schema version |
| 2 | `record_type` | string | Constant: `"campaign_metadata"` |
| 3 | `extraction_tool_version` | string | Semantic version of the extraction tool |
| 4 | `extraction_timestamp` | string | ISO 8601 with seconds precision and UTC suffix `Z` |
| 5 | `projects` | array of ProjectMetadata | One per project in `project_dirs` order |

- REQUIRES: `projects` is non-empty. `extraction_tool_version` is a valid semantic version string.
- ENSURES: Returns a JSON string with exactly 5 fields in the order above. `extraction_timestamp` is recorded once at campaign start.

> **Given** a campaign with 2 projects
> **When** CampaignMetadata is serialized
> **Then** the `projects` array has 2 elements in project_dirs order

### 4.3 ProjectMetadata Serialization

The system shall serialize ProjectMetadata with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `project_id` | string | Derived from directory basename |
| 2 | `project_path` | string | Absolute path |
| 3 | `coq_version` | string | Detected Coq version |
| 4 | `commit_hash` | string or null | Git commit hash; null if not a git repository |

- ENSURES: Returns a JSON object with exactly 4 fields. `commit_hash` is explicitly `null` when unavailable, not omitted.

### 4.4 ExtractionRecord Serialization

The system shall serialize ExtractionRecord with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `schema_version` | integer | Current schema version |
| 2 | `record_type` | string | Constant: `"proof_trace"` |
| 3 | `theorem_name` | string | Fully qualified name |
| 4 | `source_file` | string | Path relative to project root |
| 5 | `project_id` | string | Matching CampaignMetadata.projects entry |
| 6 | `total_steps` | integer | Number of tactic steps |
| 7 | `steps` | array of ExtractionStep | Length = `total_steps + 1` |

- REQUIRES: `len(steps) == total_steps + 1`. `steps[0].tactic` is null. `steps[k].tactic` for k >= 1 is non-null.
- ENSURES: Returns a JSON string with exactly 7 fields. Steps are ordered by `step_index` ascending.
- On step count mismatch: raises `ValueError`.

> **Given** an ExtractionRecord with total_steps=3
> **When** it is serialized
> **Then** the `steps` array contains exactly 4 ExtractionStep objects

### 4.5 ExtractionStep Serialization

The system shall serialize ExtractionStep with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `step_index` | integer | Step number (0 = initial state) |
| 2 | `tactic` | string or null | Tactic text; null for step 0 |
| 3 | `goals` | array of Goal objects | Open goals at this step |
| 4 | `focused_goal_index` | integer or null | Index of focused goal; null when complete |
| 5 | `premises` | array of Premise objects | Premises used by this tactic; empty for step 0 |
| 6 | `diff` | ExtractionDiff or null | Diff from previous state (P1); null for step 0 or when diffs disabled |

- REQUIRES: For step 0: `tactic` is null, `premises` is empty. For step k > 0: `tactic` is non-null.
- ENSURES: Returns a JSON object with exactly 6 fields. `diff` is explicitly `null` when not present, not omitted.

> **Given** ExtractionStep at index 0
> **When** it is serialized
> **Then** `tactic` is `null`, `premises` is `[]`, `diff` is `null`

> **Given** ExtractionStep at index 2 with diffs disabled
> **When** it is serialized
> **Then** `diff` is `null` (not omitted)

### 4.6 Premise Serialization (Extraction Context)

The system shall serialize Premise with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `name` | string | Fully qualified name (global) or short name (hypothesis) |
| 2 | `kind` | string | One of: `"lemma"`, `"hypothesis"`, `"constructor"`, `"definition"` |

- REQUIRES: `kind` is one of the four valid values.
- ENSURES: Returns a JSON object with exactly 2 fields.

This matches the Phase 2 Premise serialization defined in [proof-serialization.md](proof-serialization.md) §4.8.

### 4.7 ExtractionDiff Serialization (P1)

The system shall serialize ExtractionDiff with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `goals_added` | array of Goal | Goals added at this step |
| 2 | `goals_removed` | array of Goal | Goals removed at this step |
| 3 | `goals_changed` | array of GoalChange | Goals with changed types |
| 4 | `hypotheses_added` | array of Hypothesis | Hypotheses added |
| 5 | `hypotheses_removed` | array of Hypothesis | Hypotheses removed |
| 6 | `hypotheses_changed` | array of HypothesisChange | Hypotheses with changed types or bodies |

- ENSURES: All array fields are present even when empty (serialized as `[]`).

This matches the Phase 2 ProofStateDiff structure but omits `from_step` and `to_step` (implicit from the containing ExtractionStep's `step_index`).

### 4.8 PartialExtractionRecord Serialization

The system shall serialize PartialExtractionRecord with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `schema_version` | integer | Current schema version |
| 2 | `record_type` | string | Constant: `"partial_proof_trace"` |
| 3 | `theorem_name` | string | Fully qualified name |
| 4 | `source_file` | string | Path relative to project root |
| 5 | `project_id` | string | Matching CampaignMetadata.projects entry |
| 6 | `total_steps` | integer | Total tactic steps in the original proof |
| 7 | `completed_steps` | integer | Number of steps successfully replayed (steps 0..completed_steps are present) |
| 8 | `failure_at_step` | integer | Step index where replay failed |
| 9 | `failure_kind` | string | One of: `"tactic_failure"`, `"backend_crash"` |
| 10 | `failure_message` | string | Human-readable error description |
| 11 | `steps` | array of ExtractionStep | Length = `completed_steps + 1` (initial state + completed tactic steps) |

- REQUIRES: `completed_steps >= 1` (at least one tactic step succeeded; failures at step 1 produce ExtractionError, not partial records). `failure_at_step == completed_steps + 1`. `len(steps) == completed_steps + 1`.
- ENSURES: Returns a JSON string with exactly 11 fields. Steps use the same ExtractionStep format as §4.5.
- Downstream consumers process partial records identically to complete records — they iterate over whatever steps exist. The training data loader accepts `record_type == "partial_proof_trace"` alongside `"proof_trace"`.

> **Given** a proof of 12 steps that fails at step 5
> **When** the PartialExtractionRecord is serialized
> **Then** `total_steps = 12`, `completed_steps = 4`, `failure_at_step = 5`, and `steps` contains 5 ExtractionStep objects (steps 0-4)

> **Given** a partial record with premise annotations available for steps 1-3 but not step 4
> **When** the PartialExtractionRecord is assembled
> **Then** `completed_steps = 3` and steps contains 4 ExtractionStep objects (steps 0-3), using the intersection of trace and premise availability

### 4.9 ExtractionError Serialization

The system shall serialize ExtractionError with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `schema_version` | integer | Current schema version |
| 2 | `record_type` | string | Constant: `"extraction_error"` |
| 3 | `theorem_name` | string | Fully qualified name |
| 4 | `source_file` | string | Path relative to project root |
| 5 | `project_id` | string | Matching CampaignMetadata entry |
| 6 | `error_kind` | string | One of: `"timeout"`, `"backend_crash"`, `"tactic_failure"`, `"load_failure"`, `"unknown"` |
| 7 | `error_message` | string | Human-readable error description |

- REQUIRES: `error_kind` is one of the five valid values.
- ENSURES: Returns a JSON string with exactly 7 fields. `error_message` uses fixed templates with interpolated values for determinism.

> **Given** a timeout error for theorem `M.lemma1`
> **When** it is serialized
> **Then** `error_kind` is `"timeout"` and `error_message` follows the template `"Proof extraction exceeded {n}s time limit"`

### 4.10 ExtractionSummary Serialization

The system shall serialize ExtractionSummary with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `schema_version` | integer | Current schema version |
| 2 | `record_type` | string | Constant: `"extraction_summary"` |
| 3 | `total_theorems_found` | integer | Total enumerated |
| 4 | `total_extracted` | integer | Successful complete extractions |
| 5 | `total_partial` | integer | Partial extractions (failed mid-proof but recovered training data) |
| 6 | `total_failed` | integer | Failed extractions (no data recovered) |
| 7 | `total_skipped` | integer | Scope-filtered (P1); 0 when no filter |
| 8 | `per_project` | array of ProjectSummary | One per project |

ProjectSummary fields in order: `project_id`, `theorems_found`, `extracted`, `partial`, `failed`, `skipped`, `per_file`.

FileSummary fields in order: `source_file`, `theorems_found`, `extracted`, `partial`, `failed`, `skipped`.

### 4.11 Determinism Contract

The serialization system shall produce byte-identical output for identical input. The following rules apply:

| Rule | Requirement |
|------|-------------|
| Field ordering | Fields shall be emitted in the position order defined in §4.2–§4.10 |
| List ordering — steps | Steps ordered by `step_index` ascending |
| List ordering — goals | Goals ordered by `index` ascending |
| List ordering — hypotheses | Hypotheses ordered as Coq presents them |
| List ordering — premises | Premises ordered by appearance in the tactic trace |
| List ordering — projects | Projects ordered as provided in `project_dirs` |
| List ordering — files | Files ordered lexicographically by path |
| Null handling | Nullable fields shall be explicitly present with JSON `null`, never omitted |
| Integer formatting | Integers without leading zeros or decimal points |
| String formatting | JSON standard escaping (RFC 8259 §7) |
| Timestamp formatting | ISO 8601 with seconds precision and UTC suffix `Z` |
| JSON encoding | Compact format (no whitespace), one JSON object per line, newline-terminated, UTF-8 without BOM |

> **Given** two extraction runs on the same inputs
> **When** both outputs are compared
> **Then** they are byte-identical except for the `extraction_timestamp` in CampaignMetadata

### 4.12 Schema Version

The initial extraction schema version shall be `1`.

All record types in a single output file share the same schema version. The version is incremented on backward-incompatible changes to any record type. Additive changes (new optional fields) do not require a version increment. The policy matches [proof-serialization.md](proof-serialization.md) §4.1.

## 5. Error Specification

| Condition | Error |
|-----------|-------|
| ExtractionRecord with `len(steps) != total_steps + 1` | `ValueError`: step count mismatch |
| PartialExtractionRecord with `len(steps) != completed_steps + 1` | `ValueError`: step count mismatch |
| PartialExtractionRecord with `completed_steps < 1` | `ValueError`: partial records require at least one completed tactic step |
| ExtractionStep at index 0 with non-null tactic | `ValueError`: step 0 must have null tactic |
| ExtractionStep at index > 0 with null tactic | `ValueError`: steps 1..N must have non-null tactic |
| ExtractionError with invalid `error_kind` | `ValueError`: error_kind must be one of timeout, backend_crash, tactic_failure, load_failure, unknown |
| PartialExtractionRecord with invalid `failure_kind` | `ValueError`: failure_kind must be one of tactic_failure, backend_crash |
| Premise with invalid `kind` | `ValueError`: kind must be one of lemma, hypothesis, constructor, definition |

## 6. Non-Functional Requirements

- Serialization of a single ExtractionRecord shall complete in < 10 ms for proofs with up to 100 steps and 50 goals per step.
- Output shall be written in streaming fashion — records emitted as produced, not buffered in memory.
- JSON output shall be compact (no pretty-printing whitespace).

## 7. Examples

### Complete output stream

```
{"schema_version":1,"record_type":"campaign_metadata","extraction_tool_version":"0.3.0","extraction_timestamp":"2026-03-17T14:30:00Z","projects":[{"project_id":"coq-stdlib","project_path":"/opt/opam/coq/lib/coq/user-contrib/Stdlib","coq_version":"9.1.1","commit_hash":null}]}
{"schema_version":1,"record_type":"proof_trace","theorem_name":"Coq.Init.Logic.eq_refl","source_file":"theories/Init/Logic.v","project_id":"coq-stdlib","total_steps":1,"steps":[{"step_index":0,"tactic":null,"goals":[{"index":0,"type":"x = x","hypotheses":[{"name":"A","type":"Type","body":null},{"name":"x","type":"A","body":null}]}],"focused_goal_index":0,"premises":[],"diff":null},{"step_index":1,"tactic":"reflexivity.","goals":[],"focused_goal_index":null,"premises":[],"diff":null}]}
{"schema_version":1,"record_type":"extraction_error","theorem_name":"Coq.Arith.PeanoNat.Nat.sub_diag","source_file":"theories/Arith/PeanoNat.v","project_id":"coq-stdlib","error_kind":"timeout","error_message":"Proof extraction exceeded 60s time limit"}
{"schema_version":1,"record_type":"extraction_summary","total_theorems_found":2,"total_extracted":1,"total_failed":1,"total_skipped":0,"per_project":[{"project_id":"coq-stdlib","theorems_found":2,"extracted":1,"failed":1,"skipped":0,"per_file":[{"source_file":"theories/Init/Logic.v","theorems_found":1,"extracted":1,"failed":0,"skipped":0},{"source_file":"theories/Arith/PeanoNat.v","theorems_found":1,"extracted":0,"failed":1,"skipped":0}]}]}
```

## 8. Language-Specific Notes (Python)

- Use `json.dumps(obj, separators=(',', ':'), sort_keys=False)` for compact output.
- Implement per-type serialization functions (`serialize_extraction_record`, `serialize_extraction_error`, etc.) rather than relying on generic serialization, to enforce field ordering and validation.
- Use `datetime.isoformat(timespec='seconds')` + `'Z'` suffix for timestamps.
- Write output using `open(path, 'w', encoding='utf-8')` with explicit UTF-8 encoding.
- Flush after each line write for crash resilience during long campaigns.
- Package location: `src/poule/extraction/output.py`.
