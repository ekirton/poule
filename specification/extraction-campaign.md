# Extraction Campaign Orchestrator

Batch component that processes Coq project directories, extracts proof traces for all provable theorems, and produces a streaming JSON Lines dataset with graceful degradation.

**Architecture**: [extraction-campaign.md](../doc/architecture/extraction-campaign.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [extraction-types.md](../doc/architecture/data-models/extraction-types.md)

---

## 1. Purpose

Define the campaign orchestrator that enumerates projects and theorems, drives per-proof extraction via the Proof Session Manager, emits ExtractionRecord and ExtractionError records to a JSON Lines stream, enforces deterministic output ordering, and produces extraction summary statistics.

## 2. Scope

**In scope**: Campaign planning (project/file/theorem enumeration), per-proof extraction loop, failure isolation, deterministic ordering, streaming output, summary statistics, scope filtering (P1), per-proof timeout.

**Out of scope**: Session management and Coq backend communication (owned by proof-session), JSON serialization of extraction types (owned by extraction-output), incremental extraction and resumption (owned by extraction-checkpointing), dependency graph extraction (owned by extraction-dependency-graph), quality reports (owned by extraction-reporting).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Campaign | A single invocation of the extraction pipeline across one or more Coq project directories |
| Campaign plan | The ordered list of (project, file, theorem) triples to extract, determined before extraction begins |
| Extraction loop | The sequential iteration over the campaign plan, extracting one proof per iteration |
| Graceful degradation | The property that a single proof failure produces an error record without halting extraction of remaining proofs |
| Scope filter | An optional name pattern or module list that restricts which theorems are extracted (P1) |

## 4. Behavioral Requirements

### 4.1 Campaign Planning

#### build_campaign_plan(project_dirs, scope_filter)

- REQUIRES: `project_dirs` is a non-empty list of directory paths. Each directory exists on disk. `scope_filter` is optional (null means extract all).
- ENSURES: Returns a CampaignPlan containing: a list of ProjectMetadata (one per project), and an ordered list of ExtractionTarget triples `(project_id, source_file, theorem_name)`. The ordering is deterministic: projects in `project_dirs` order, files in lexicographic path order within each project, theorems in declaration order within each file.
- On directory not found: raises `DIRECTORY_NOT_FOUND` error before any extraction begins.

> **Given** two project directories `/stdlib` and `/mathcomp`
> **When** `build_campaign_plan(["/stdlib", "/mathcomp"], null)` is called
> **Then** the plan contains projects in order [stdlib, mathcomp], files sorted within each, theorems in declaration order

> **Given** a project directory that does not exist
> **When** `build_campaign_plan(["/nonexistent"])` is called
> **Then** a `DIRECTORY_NOT_FOUND` error is raised

#### Project metadata detection

For each project directory, the system shall detect:

| Field | Detection method |
|-------|-----------------|
| `project_id` | Directory basename; disambiguated with numeric suffix if collisions exist |
| `coq_version` | Output of `coqc --version` (or equivalent query to the Coq installation) |
| `commit_hash` | Output of `git rev-parse HEAD` in the project directory; null if not a git repository |
| `project_path` | Absolute path to the project directory |

- REQUIRES: Coq is installed and `coqc` is on the PATH.
- ENSURES: ProjectMetadata is populated for each project.

> **Given** two project directories both named `theories`
> **When** project IDs are derived
> **Then** the first is `theories`, the second is `theories-2`

#### Theorem enumeration

For each .v file in a project, the system shall enumerate provable theorems by querying the Coq backend.

- REQUIRES: The .v file is loadable by the Coq backend.
- ENSURES: Returns theorems in declaration order within the file. Each theorem has a fully qualified name.
- On file load failure: all theorems in this file are marked as `load_failure` errors. Enumeration continues with the next file.

> **Given** a .v file containing theorems `A`, `B`, `C` in declaration order
> **When** theorems are enumerated
> **Then** they are returned in order [A, B, C]

> **Given** a .v file that fails to load (syntax error, missing dependency)
> **When** theorem enumeration is attempted
> **Then** a `load_failure` error is recorded for the file, and enumeration continues with the next file

#### Scope filtering (P1)

When a scope filter is provided, the system shall apply it after theorem enumeration:

- Name pattern filter: only theorems whose fully qualified name matches the pattern are included.
- Module filter: only theorems in modules matching any of the specified prefixes are included.
- Filtered theorems are counted as `skipped` in the summary.

- REQUIRES: `scope_filter` contains a valid name pattern (glob or regex) or a non-empty module prefix list.
- ENSURES: The campaign plan includes only theorems matching the filter. Skipped theorem count is tracked per-file.

> **Given** a scope filter with name pattern `*add*` and a project with theorems `add_comm`, `mul_comm`, `add_assoc`
> **When** the filter is applied
> **Then** only `add_comm` and `add_assoc` are included; `mul_comm` is counted as skipped

### 4.2 Per-Proof Extraction

#### extract_single_proof(project_id, source_file, theorem_name)

- REQUIRES: `source_file` is a valid .v file path. `theorem_name` is a fully qualified proof name.
- ENSURES: Creates a proof session, replays the full proof, extracts the proof trace and premise annotations, assembles an ExtractionRecord, closes the session, and returns the record. The session is closed in a finally block regardless of success or failure.
- On session creation failure: returns ExtractionError with `error_kind` = `load_failure` or `tactic_failure`.
- On tactic failure during replay: returns ExtractionError with `error_kind` = `tactic_failure`.
- On backend crash: returns ExtractionError with `error_kind` = `backend_crash`.
- On timeout: returns ExtractionError with `error_kind` = `timeout`.
- On any other unexpected error: returns ExtractionError with `error_kind` = `unknown`.

> **Given** a valid proof `Nat.add_comm` with 5 tactic steps
> **When** `extract_single_proof("coq-stdlib", "theories/Arith/PeanoNat.v", "Nat.add_comm")` is called
> **Then** an ExtractionRecord is returned with `total_steps = 5`, 6 ExtractionSteps, and per-step premise annotations

> **Given** a proof where tactic 3 of 5 fails during replay
> **When** `extract_single_proof(...)` is called
> **Then** an ExtractionError is returned with `error_kind = "tactic_failure"`, and the session is closed

> **Given** a proof where the Coq backend crashes mid-replay
> **When** `extract_single_proof(...)` is called
> **Then** an ExtractionError is returned with `error_kind = "backend_crash"`

#### Per-proof timeout

The system shall enforce a per-proof time limit on extraction. When the time limit is exceeded:

- The session is closed (backend process terminated).
- An ExtractionError is returned with `error_kind` = `timeout`.
- The timeout duration is implementation-defined (suggested default: 60 seconds per proof).

> **Given** a proof that takes 120 seconds to replay with a 60-second timeout
> **When** `extract_single_proof(...)` is called
> **Then** an ExtractionError with `error_kind = "timeout"` is returned after ~60 seconds

#### ExtractionRecord assembly

When a proof is successfully extracted, the system shall assemble an ExtractionRecord:

- REQUIRES: A valid ProofTrace and a list of PremiseAnnotation objects from the session manager.
- ENSURES: The ExtractionRecord contains: `schema_version` (current), `record_type = "proof_trace"`, `theorem_name` (fully qualified), `source_file` (relative to project root), `project_id`, `total_steps`, and a `steps` list of ExtractionStep objects. Each ExtractionStep embeds the proof state, tactic, and premises from the corresponding trace step and premise annotation. `session_id` is excluded from all embedded proof states.

> **Given** a ProofTrace with 3 steps and PremiseAnnotations for steps 1-3
> **When** an ExtractionRecord is assembled
> **Then** the record has 4 ExtractionSteps (0-3); step 0 has `tactic = null` and `premises = []`; steps 1-3 embed their respective premises

#### Proof state diff embedding (P1)

When diffs are enabled, the system shall compute a proof state diff for each consecutive pair of states and embed it in the ExtractionStep as the `diff` field.

- REQUIRES: Diffs are enabled via extraction options. The proof has been fully traced.
- ENSURES: Each ExtractionStep at index k > 0 has a non-null `diff` field computed from states k-1 and k. Step 0 has `diff = null`.

### 4.3 Campaign Execution

#### run_campaign(project_dirs, output_path, options)

- REQUIRES: `project_dirs` is a non-empty list of existing directory paths. `output_path` is a writable file path.
- ENSURES: Builds a campaign plan. Emits CampaignMetadata as the first line of output. Iterates over the campaign plan in deterministic order, calling `extract_single_proof` for each target. Emits each ExtractionRecord or ExtractionError to the output stream as it is produced. Computes and emits ExtractionSummary as the last line of output. Returns the ExtractionSummary.
- On all proofs failing: still emits CampaignMetadata and ExtractionSummary. Returns summary with `total_extracted = 0`.

> **Given** a campaign with 100 theorems where 97 succeed and 3 fail
> **When** `run_campaign(...)` completes
> **Then** the output contains 1 CampaignMetadata + 97 ExtractionRecords + 3 ExtractionErrors + 1 ExtractionSummary, in deterministic order

> **Given** a campaign with 50 theorems where all fail
> **When** `run_campaign(...)` completes
> **Then** the output contains 1 CampaignMetadata + 50 ExtractionErrors + 1 ExtractionSummary

#### Deterministic ordering

The system shall emit records in the following deterministic order:

1. CampaignMetadata (first line)
2. For each project in `project_dirs` order:
   - For each .v file in lexicographic path order:
     - For each theorem in declaration order:
       - ExtractionRecord or ExtractionError
3. ExtractionSummary (last line)

MAINTAINS: Identical inputs (same project directories at the same commits, same Coq version, same extraction options) shall produce byte-identical output. The only per-run variable is the `extraction_timestamp` in CampaignMetadata.

> **Given** the same project directory at the same commit
> **When** `run_campaign` is called twice
> **Then** the outputs differ only in the `extraction_timestamp` field of CampaignMetadata

#### Summary statistics

The system shall accumulate extraction counters during the campaign:

| Counter | Definition |
|---------|-----------|
| `theorems_found` | Total theorems enumerated (before scope filtering) |
| `extracted` | Theorems that produced an ExtractionRecord |
| `failed` | Theorems that produced an ExtractionError |
| `skipped` | Theorems excluded by scope filter (P1); 0 when no filter is applied |

MAINTAINS: `extracted + failed + skipped == theorems_found` for each file, project, and the campaign as a whole.

The ExtractionSummary shall include per-project and per-file breakdowns of these counters.

> **Given** a project with 3 files: A.v (10 proofs, 9 extracted, 1 failed), B.v (5 proofs, 5 extracted), C.v (2 proofs, 0 extracted, 2 failed)
> **When** the summary is computed
> **Then** the project totals are: found=17, extracted=14, failed=3, skipped=0

## 5. Interface Contracts

### CLI → Extraction Campaign Orchestrator

| Operation | Input | Output | Error codes |
|-----------|-------|--------|-------------|
| `run_campaign(project_dirs, output_path, options)` | List of directory paths + output path + options | ExtractionSummary | `DIRECTORY_NOT_FOUND` |

Options:

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `scope_filter` | ScopeFilter or null | null | Name pattern or module filter (P1) |
| `include_diffs` | boolean | false | Include proof state diffs in output (P1) |
| `timeout_seconds` | positive integer | 60 | Per-proof extraction timeout |

### Extraction Campaign Orchestrator → Proof Session Manager

The orchestrator calls the session manager's existing API for each proof:

| Step | Session Manager Operation |
|------|--------------------------|
| 1 | `create_session(file_path, theorem_name)` → session_id + initial state |
| 2 | `extract_trace(session_id)` → ProofTrace |
| 3 | `get_premises(session_id)` → list[PremiseAnnotation] |
| 4 | `close_session(session_id)` → confirmation |

The orchestrator does not add new operations to the session manager API. It reuses the same interface used by the MCP server and CLI proof replay.

### Extraction Campaign Orchestrator → Output Stream

The orchestrator writes JSON Lines to the output stream via the extraction output serializer (see [extraction-output.md](extraction-output.md)). It does not serialize records directly.

## 6. State and Lifecycle

### Campaign State Machine

| Current State | Event | Guard | Action | Next State |
|--------------|-------|-------|--------|------------|
| — | `run_campaign` called | All directories exist | Build plan, emit metadata | `extracting` |
| — | `run_campaign` called | A directory missing | Raise `DIRECTORY_NOT_FOUND` | — |
| `extracting` | Next target in plan | — | Call `extract_single_proof`, emit record | `extracting` |
| `extracting` | Plan exhausted | — | Compute summary, emit summary | `complete` (terminal) |
| `extracting` | Interrupted (signal) | — | Emit partial summary, close output | `interrupted` (terminal) |

The campaign does not support pause/resume within `run_campaign`. Resumption is handled by the checkpointing module (see [extraction-checkpointing.md](extraction-checkpointing.md)).

## 7. Error Specification

### Error types

| Error code | Category | Condition |
|-----------|----------|-----------|
| `DIRECTORY_NOT_FOUND` | Input error | A project directory in `project_dirs` does not exist |
| `EXTRACTION_TIMEOUT` | Dependency error | Per-proof time limit exceeded |

Per-proof errors (tactic failure, backend crash, load failure) are not raised — they are captured as ExtractionError records in the output stream.

### Edge cases

| Condition | Behavior |
|-----------|----------|
| Empty project directory (no .v files) | Project appears in summary with all counters = 0 |
| .v file with no provable theorems | File appears in per-file summary with all counters = 0 |
| All proofs in a project fail | Campaign continues; project summary reflects 0 extracted |
| `project_dirs` list is empty | Raise input validation error (not `DIRECTORY_NOT_FOUND`) |
| Same directory listed twice in `project_dirs` | Extracted twice with disambiguated project_ids |
| Extraction interrupted by SIGINT | Emit partial summary with counts through the last completed proof, close output stream |

## 8. Non-Functional Requirements

- The system shall process the Coq standard library in under 1 hour on a single machine without GPU.
- Memory usage shall be bounded by the largest single proof's trace, not by the total dataset size (streaming output).
- The orchestrator shall process proofs sequentially (one session at a time). Parallel extraction is not specified in this phase.

## 9. Examples

### Minimal campaign

```
plan = build_campaign_plan(["/path/to/stdlib"], null)
# plan.projects = [ProjectMetadata(project_id="stdlib", coq_version="9.1.1", ...)]
# plan.targets = [("stdlib", "theories/Init/Logic.v", "eq_refl"), ...]

summary = run_campaign(["/path/to/stdlib"], "/output/stdlib.jsonl", default_options)
# summary.total_extracted = 4500
# summary.total_failed = 50
# Output file: CampaignMetadata + 4500 ExtractionRecords + 50 ExtractionErrors + ExtractionSummary
```

### Multi-project campaign

```
summary = run_campaign(
    ["/path/to/stdlib", "/path/to/mathcomp"],
    "/output/combined.jsonl",
    default_options
)
# summary.per_project[0].project_id = "stdlib"
# summary.per_project[1].project_id = "mathcomp"
```

### Failed proof handling

```
# Proof "tricky_lemma" times out during extraction
# Output stream contains:
#   {"record_type":"extraction_error","theorem_name":"M.tricky_lemma",
#    "error_kind":"timeout","error_message":"Proof extraction exceeded 60s time limit",...}
# Extraction continues with the next theorem
```

## 10. Language-Specific Notes (Python)

- Use `asyncio.run()` to bridge the sync CLI entry point to the async `SessionManager` API.
- Use `asyncio.wait_for()` with `timeout_seconds` for per-proof timeout enforcement.
- Use `pathlib.Path` for all file path operations; resolve to absolute paths at campaign start.
- Use `subprocess.run(["coqc", "--version"])` for Coq version detection.
- Use `subprocess.run(["git", "rev-parse", "HEAD"])` for commit hash detection; catch `FileNotFoundError` and `subprocess.CalledProcessError` for non-git directories.
- Package location: `src/poule/extraction/campaign.py`.
