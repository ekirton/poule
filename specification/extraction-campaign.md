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

#### build_campaign_plan(project_dirs, index_db_path, scope_filter)

- REQUIRES: `project_dirs` is a non-empty list of directory paths. Each directory exists on disk. `index_db_path` is a path to a valid SQLite index database with schema version 1. `scope_filter` is optional (null means extract all).
- ENSURES: Returns a CampaignPlan containing: a list of ProjectMetadata (one per project), and an ordered list of ExtractionTarget tuples `(project_id, source_file, theorem_name, decl_kind)`. Theorem names are fully qualified (from the index). Declaration kinds are one of: `lemma`, `theorem`, `instance`, `definition`. The ordering is deterministic: projects in `project_dirs` order, files in lexicographic path order within each project, declarations in `(module, name)` order within each file.
- On directory not found: raises `DIRECTORY_NOT_FOUND` error before any extraction begins.
- On index not found or invalid: raises `INDEX_NOT_FOUND` error before any extraction begins.

> **Given** two project directories `/stdlib` and `/mathcomp` and a valid index DB
> **When** `build_campaign_plan(["/stdlib", "/mathcomp"], "index.db", null)` is called
> **Then** the plan contains projects in order [stdlib, mathcomp], files sorted within each, declarations ordered by (module, name)

> **Given** a project directory that does not exist
> **When** `build_campaign_plan(["/nonexistent"], "index.db")` is called
> **Then** a `DIRECTORY_NOT_FOUND` error is raised

> **Given** an index_db_path that does not exist
> **When** `build_campaign_plan(["/stdlib"], "/missing/index.db")` is called
> **Then** an `INDEX_NOT_FOUND` error is raised

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

#### Declaration enumeration

The system shall enumerate provable declarations by querying the SQLite search index for declarations with kind in `{lemma, theorem, instance, definition}` and `has_proof_body = 1`.

- REQUIRES: `index_db_path` points to a valid index database. Each declaration in the index has a fully qualified `name`, `module`, `kind`, and `has_proof_body`.
- ENSURES: Returns only declarations with `has_proof_body = 1`, ordered by `(module, name)` within each source file. Each declaration has a fully qualified name and a `decl_kind`. Source file paths are derived from module paths using `module_to_source_file()`.
- The index is the sole enumeration source. No regex or file-scanning heuristics are used.
- **Backward compatibility:** If the filtered query returns zero results (indicating an older index without `has_proof_body` annotations), the system shall fall back to unfiltered enumeration (all provable kinds, no `has_proof_body` filter).

> **Given** an index containing declarations `Coq.Arith.PeanoNat.Nat.add_comm` (lemma, has_proof_body=1) and `Coq.Arith.PeanoNat.Nat.add_0_r` (lemma, has_proof_body=1)
> **When** declarations are enumerated
> **Then** both are returned with source_file `Arith/PeanoNat.v` and their fully qualified names

> **Given** an index containing `Coq.Arith.PeanoNat.Nat.eq` (definition, has_proof_body=0) — a `:=` definition without a proof block
> **When** declarations are enumerated
> **Then** it is excluded from the campaign plan

> **Given** an index containing `Coq.Arith.PeanoNat.Nat.add_0_l` (lemma, has_proof_body=0) — an Include'd re-export
> **When** declarations are enumerated
> **Then** it is excluded from the campaign plan

> **Given** an index containing an `Instance` declaration `Coq.Classes.Morphisms.eq_Reflexive` (has_proof_body=1)
> **When** declarations are enumerated
> **Then** it is included with `decl_kind = "instance"`

> **Given** an older index where all declarations have `has_proof_body = 0` (built before this annotation existed)
> **When** declarations are enumerated
> **Then** the system falls back to unfiltered enumeration (all provable kinds)

#### module_to_source_file(module, project_path, module_prefix)

- REQUIRES: `module` is a dot-separated module path from the index. `module_prefix` is the library's known module prefix (e.g., `Coq.`, `mathcomp.`).
- ENSURES: Returns a relative file path by stripping the prefix, replacing dots with `/`, and appending `.v`. For example, `Coq.Reals.Ranalysis1` with prefix `Coq.` yields `Reals/Ranalysis1.v`.
- The utility shall handle `Corelib.` as an alias for `Coq.` (Rocq 9.x compatibility).

> **Given** module `Coq.Reals.Ranalysis1` and prefix `Coq.`
> **When** `module_to_source_file` is called
> **Then** the result is `Reals/Ranalysis1.v`

> **Given** module `mathcomp.algebra.ring` and prefix `mathcomp.`
> **When** `module_to_source_file` is called
> **Then** the result is `algebra/ring.v`

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

#### extract_single_proof(project_id, source_file, theorem_name, project_path)

- REQUIRES: `source_file` is a relative path (relative to project root) to a .v file. `project_path` is the absolute path to the project root directory. `theorem_name` is a fully qualified proof name. The orchestrator resolves `project_path / source_file` to an absolute path before passing it to `create_session`.
- ENSURES: Creates a proof session using the resolved absolute file path, replays the full proof, extracts the proof trace and premise annotations, assembles an ExtractionRecord (storing the relative `source_file`), closes the session, and returns the record. The session is closed in a finally block regardless of success or failure.
- On session creation failure with `PROOF_NOT_FOUND`: returns ExtractionError with `error_kind` = `no_proof_body`. With `has_proof_body` pre-filtering, this should be rare (only false positives from the regex-based source scan). Without pre-filtering (backward compatibility), this is expected for definitions without proof bodies.
- On session creation failure (other): returns ExtractionError with `error_kind` = `load_failure` or `tactic_failure`.
- On tactic failure during replay at step k > 1: `extract_trace` returns a partial ProofTrace. The orchestrator assembles a PartialExtractionRecord from the completed steps (0..k-1). This is counted as `partial` in the summary, not `failed`.
- On tactic failure at step 1 (no completed tactic steps): returns ExtractionError with `error_kind` = `tactic_failure`. A partial trace with only the initial state produces zero training pairs and is not worth recording as a partial extraction.
- On backend crash during replay at step k > 1: same as tactic failure — assembles a PartialExtractionRecord from steps 0..k-1 if premise data is available. If the backend crash prevents premise extraction entirely, returns ExtractionError with `error_kind` = `backend_crash`.
- On timeout: returns ExtractionError with `error_kind` = `timeout`.
- On any other unexpected error: returns ExtractionError with `error_kind` = `unknown`.

> **Given** a valid proof `Nat.add_comm` with 5 tactic steps
> **When** `extract_single_proof("coq-stdlib", "theories/Arith/PeanoNat.v", "Nat.add_comm")` is called
> **Then** an ExtractionRecord is returned with `total_steps = 5`, 6 ExtractionSteps, and per-step premise annotations

> **Given** a proof where tactic 5 of 12 fails during replay
> **When** `extract_single_proof(...)` is called
> **Then** a PartialExtractionRecord is returned with `completed_steps = 4`, `failure_at_step = 5`, 5 ExtractionSteps (steps 0-4), and the session is closed

> **Given** a proof where tactic 1 of 5 fails during replay (first tactic)
> **When** `extract_single_proof(...)` is called
> **Then** an ExtractionError is returned with `error_kind = "tactic_failure"`, and the session is closed

> **Given** a proof where the Coq backend crashes mid-replay at step 3
> **When** `extract_single_proof(...)` is called
> **Then** a PartialExtractionRecord is returned with steps 0-2 if premises were obtainable, or an ExtractionError with `error_kind = "backend_crash"` if premises could not be extracted

#### Backend liveness

The system relies on the CoqBackend's liveness watchdog (see [coq-proof-backend.md](coq-proof-backend.md) §7.4) to detect dead backends during extraction. There is no per-proof budget timeout — complex proofs that take minutes to replay are allowed to complete as long as the backend remains responsive.

When the watchdog fires (backend unresponsive), the `ConnectionError` propagates through `extract_trace`, which returns a partial ProofTrace. The orchestrator converts this to a `PartialExtractionRecord` or `ExtractionError` via the standard partial recovery path.

> **Given** a proof where the backend becomes unresponsive at step 5
> **When** `extract_single_proof(...)` is called with a watchdog-enabled session manager
> **Then** after the watchdog timeout, a PartialExtractionRecord with steps 0-4 is returned (or ExtractionError if failure is at step 1)

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
| `theorems_found` | Total declarations enumerated from the index (before scope filtering) |
| `extracted` | Declarations that produced an ExtractionRecord (complete traces) |
| `partial` | Declarations that produced a PartialExtractionRecord (incomplete traces with recoverable training data) |
| `failed` | Declarations that produced an ExtractionError (excluding `no_proof_body`) |
| `no_proof_body` | Declarations that produced an ExtractionError with `error_kind = "no_proof_body"` (expected, not failures) |
| `skipped` | Declarations excluded by scope filter (P1); 0 when no filter is applied |

MAINTAINS: `extracted + partial + failed + no_proof_body + skipped == theorems_found` for each file, project, and the campaign as a whole.

The ExtractionSummary shall include per-project and per-file breakdowns of these counters.

> **Given** a project with 3 files: A.v (10 proofs, 9 extracted, 1 failed), B.v (5 proofs, 5 extracted), C.v (2 proofs, 0 extracted, 2 failed)
> **When** the summary is computed
> **Then** the project totals are: found=17, extracted=14, failed=3, skipped=0

## 5. Interface Contracts

### CLI → Extraction Campaign Orchestrator

| Operation | Input | Output | Error codes |
|-----------|-------|--------|-------------|
| `run_campaign(project_dirs, output_path, options)` | List of directory paths + output path + options | ExtractionSummary | `DIRECTORY_NOT_FOUND`, `INDEX_NOT_FOUND` |

Options:

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `index_db_path` | file path | (required) | Path to SQLite search index for declaration enumeration |
| `scope_filter` | ScopeFilter or null | null | Name pattern or module filter (P1) |
| `include_diffs` | boolean | false | Include proof state diffs in output (P1) |
| `watchdog_timeout` | positive float or null | 600 | Inactivity threshold (seconds) before declaring backend dead; null to disable |

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
| `INDEX_NOT_FOUND` | Input error | `index_db_path` does not exist or is not a valid index |

Per-proof errors (tactic failure, backend crash, backend unresponsive, load failure) are not raised — they are captured as ExtractionError or PartialExtractionRecord records in the output stream. Backend liveness is enforced by the CoqBackend's watchdog (§7.4 in coq-proof-backend.md), not by a campaign-level timeout.

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
plan = build_campaign_plan(["/path/to/stdlib"], "/data/index.db", null)
# plan.projects = [ProjectMetadata(project_id="stdlib", coq_version="9.1.1", ...)]
# plan.targets = [("stdlib", "Init/Logic.v", "Coq.Init.Logic.eq_refl", "lemma"), ...]
# With has_proof_body filtering: ~5000 targets (vs ~31000 without)

summary = run_campaign(["/path/to/stdlib"], "/output/stdlib.jsonl", {index_db_path: "/data/index.db"})
# summary.total_extracted = 4500
# summary.total_failed = 50
# summary.total_no_proof_body = 200  (false positives from regex scan; was ~26000 without filtering)
# Output file: CampaignMetadata + 4500 ExtractionRecords + 250 ExtractionErrors + ExtractionSummary
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
