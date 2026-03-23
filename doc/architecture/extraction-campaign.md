# Extraction Campaign Orchestrator

The batch component that processes one or more Coq project directories, extracts proof traces for all provable theorems, and produces a streaming JSON Lines dataset with graceful degradation on per-proof failures.

**Feature**: [Batch Extraction CLI](../features/batch-extraction-cli.md), [Extraction Library Support](../features/extraction-library-support.md)
**Data models**: [extraction-types.md](data-models/extraction-types.md), [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
CLI (extract subcommand)
  │
  │ project directories, index_db_path, options
  ▼
┌───────────────────────────────────────────────────────┐
│         Extraction Campaign Orchestrator               │
│                                                        │
│  Campaign Planner                                      │
│    query index DB → map modules to files → list proofs │
│                                                        │
│  Per-proof Extraction Loop                             │
│    ┌─────────────────────────────────────┐             │
│    │ For each proof:                     │             │
│    │   open session → replay → extract   │             │
│    │   → annotate premises → close       │             │
│    │   On failure: emit ExtractionError  │             │
│    └──────────────┬──────────────────────┘             │
│                   │                                    │
│  Output Writer                                         │
│    CampaignMetadata → ExtractionRecords → Summary      │
│                                                        │
│  Checkpoint Manager (P1)                               │
│    progress tracking, resumption                       │
└──────────┬────────────────────────────────┬────────────┘
           │                                │
           │ session operations              │ streaming writes
           ▼                                ▼
     Proof Session Manager            JSON Lines output
     (reused from Phase 2)            (see extraction-output.md)
           │
           │ coq-lsp / SerAPI
           ▼
     Coq Backend Processes
```

## Campaign Pipeline

```
extract(project_dirs[], index_db_path, options)
  │
  ├─ Validate all project directories exist
  ├─ Validate index_db_path exists and is a valid index
  │
  ├─ Build campaign plan:
  │    Enumerate provable declarations from index DB
  │      (kind IN lemma, theorem, instance, definition)
  │    Map module paths to source files in project directories
  │    For each project_dir:
  │      Detect Coq version (coqc --version)
  │      Detect git commit hash (git rev-parse HEAD, or null)
  │    Apply scope filter if configured (name pattern, module filter)
  │
  ├─ Emit CampaignMetadata record (first line of output)
  │
  ├─ For each project, in project_dirs order:
  │    For each .v file, in sorted path order:
  │      For each theorem, in declaration order within file:
  │        extract_single_proof(project, file, theorem)
  │
  ├─ Compute ExtractionSummary from accumulated counters
  │
  └─ Emit ExtractionSummary record (last line of output)
```

## Per-Proof Extraction

```
extract_single_proof(project, file, theorem)
  │
  ├─ Create a session via SessionManager.create_session(file, theorem)
  │    On failure → emit ExtractionError, return
  │
  ├─ Replay the full proof: step forward through all tactic steps
  │    On tactic failure → emit ExtractionError, close session, return
  │    On backend crash → emit ExtractionError, return
  │    On timeout → emit ExtractionError, close session, return
  │
  ├─ Extract proof trace via SessionManager.extract_proof_trace(session_id)
  │
  ├─ Extract premise annotations via SessionManager.get_proof_premises(session_id)
  │
  ├─ Compute proof state diffs if enabled (P1)
  │
  ├─ Assemble ExtractionRecord from trace + premises + diffs
  │
  ├─ Close session via SessionManager.close_session(session_id)
  │    Always executed (even on partial success), via finally block
  │
  └─ Emit ExtractionRecord to output stream
```

### Failure Isolation

Each proof is extracted in its own session with its own Coq backend process. A failure in one proof (tactic error, backend crash, timeout) produces an ExtractionError record and does not affect subsequent proofs. The session is always closed in a finally block to prevent resource leaks.

Failure kinds:

| Kind | Cause | Recovery |
|------|-------|----------|
| `load_failure` | .v file cannot be loaded by the backend | Skip all proofs in this file |
| `tactic_failure` | A tactic in the original proof fails during replay | Skip this proof |
| `backend_crash` | Coq backend process exits unexpectedly | Skip this proof |
| `timeout` | Per-proof time limit exceeded | Skip this proof |
| `no_proof_body` | Declaration has no proof body (e.g., `Definition foo := 42.`) | Expected; not counted as failure |
| `unknown` | Any other unexpected error | Skip this proof |

When a file fails to load, all theorems in that file are skipped with `load_failure` errors rather than attempting each one independently.

Declarations classified as `no_proof_body` are reported separately from failures in the extraction summary. The summary invariant becomes: `extracted + partial + failed + no_proof_body + skipped == found`.

## Theorem Enumeration

The campaign planner enumerates provable declarations by querying the SQLite search index (`index.db`). The `declarations` table contains every declaration's fully qualified name, kind, and module. The campaign planner queries for declaration kinds that may have proof bodies: `lemma`, `theorem`, `instance`, `definition`.

```
_enumerate_from_index(index_db_path, project_dirs)
  │
  ├─ Open IndexReader on index_db_path
  ├─ Query: SELECT name, module, kind FROM declarations
  │         WHERE kind IN ('lemma', 'theorem', 'instance', 'definition')
  │           AND has_proof_body = 1
  │         ORDER BY module, name
  │  (Fallback: if no declarations match with has_proof_body = 1,
  │   re-query without the filter for backward compatibility)
  ├─ For each declaration:
  │    Map module to source file via module_to_source_file()
  │    Match source file to project directory
  │    Yield (project_id, source_file, fqn, decl_kind)
  └─ Close IndexReader
```

The index is a required input. The extraction pipeline already requires a built index (the training data loader reads the premise corpus from it), so this adds no new prerequisite.

### Module-to-File Mapping

The index stores `module` as a dot-separated path (e.g., `Coq.Reals.Ranalysis1`). The campaign plan needs source file paths relative to the project root.

Each library has a known prefix that is stripped to produce the relative path:

| Library | Module prefix | Example |
|---------|--------------|---------|
| stdlib | `Coq.` | `Coq.Reals.Ranalysis1` → `Reals/Ranalysis1.v` |
| MathComp | `mathcomp.` | `mathcomp.algebra.ring` → `algebra/ring.v` |
| stdpp | `stdpp.` | `stdpp.fin_maps` → `fin_maps.v` |
| Flocq | `Flocq.` | `Flocq.Core.Raux` → `Core/Raux.v` |
| Coquelicot | `Coquelicot.` | `Coquelicot.Derive` → `Derive.v` |
| Interval | `Interval.` | `Interval.Tactic` → `Tactic.v` |

The prefix is detected from the project path basename or provided explicitly. Stdlib under Rocq 9.x may use `Corelib.` prefix instead of `Coq.`; the module_to_source_file utility handles both.

### Pre-filtering on `has_proof_body`

Not all declarations in the index have tactic proof bodies. The index distinguishes declarations with proof bodies from those without via the `has_proof_body` column (see [index-entities.md](data-models/index-entities.md)). Declarations without proof bodies include:

- `:=` definitions (e.g., `Definition foo := 42.`)
- Declarations brought into scope via module `Include` or functor application (their proof bodies exist in the original source files, not in the re-exporting file)
- Axioms, parameters, and conjectures

The campaign planner filters the index query to only include declarations where `has_proof_body = 1`. This eliminates the majority of wasted extraction attempts — in the Coq stdlib, module `Include` chains (e.g., `PeanoNat.Nat` includes 15+ sub-modules) generate thousands of re-exported declarations per file, none of which have extractable proof bodies in the re-exporting file.

When `has_proof_body` filtering is active, the campaign still encounters occasional `no_proof_body` errors (e.g., false positives from the regex-based source scan). These are handled as before — classified as `no_proof_body` in the summary, not counted as failures.

#### Fallback behavior

If the index was built without `has_proof_body` annotations (all values are 0 or the column is absent), the campaign planner falls back to unfiltered enumeration to maintain backward compatibility with older indexes.

### Scope Filtering (P1)

When a name pattern or module filter is configured, the campaign planner applies the filter after theorem enumeration and before extraction. Filtered theorems are counted as `skipped` in the summary (not `failed`).

## Determinism

Byte-identical output for identical inputs requires:

1. **Deterministic enumeration order**: Projects in command-line order, files in sorted path order, theorems in declaration order within files
2. **Deterministic proof state serialization**: Reuses the determinism guarantees from [proof-serialization.md](proof-serialization.md) — fixed field ordering, explicit nulls, deterministic list ordering
3. **Deterministic premise ordering**: Premises within each step are ordered by appearance in the tactic trace (same as Phase 2)
4. **No nondeterministic metadata**: The extraction timestamp is recorded once in CampaignMetadata, not per-record. No random IDs, no hash-map iteration, no floating-point rounding variation
5. **Deterministic error records**: Error messages use fixed templates with interpolated values, not free-form text from nondeterministic sources

### Session ID Exclusion

Phase 2's ProofState includes a `session_id` field. Extraction records do not include session IDs — they are ephemeral identifiers that would break byte-identical output across runs. The ExtractionStep type omits `session_id` by design.

## Reuse of Phase 2 Infrastructure

The campaign orchestrator is a new component that reuses (does not fork or reimplement) Phase 2's Proof Session Manager:

| Phase 2 Component | Reuse in Phase 3 |
|---|---|
| `SessionManager` | Session lifecycle (create, close) for each proof |
| `CoqBackend` | Per-session Coq process management |
| `extract_proof_trace()` | Proof state extraction at every tactic step |
| `get_proof_premises()` | Per-step premise annotation extraction |
| Proof state diff computation | Step-level diff generation (P1) |
| Proof serialization | JSON field mapping, determinism rules |

The orchestrator adds: project/file enumeration, failure isolation, streaming output, progress tracking, summary statistics, and provenance metadata. These concerns do not exist in Phase 2's interactive model.

## Concurrency Model

The initial implementation processes proofs sequentially — one session at a time, one proof at a time. This simplifies output ordering (determinism), resource management (one Coq process active), and error handling.

Sequential processing is acceptable because:
- Extraction throughput is bounded by Coq proof checking speed, not parallelism overhead
- The success metric (stdlib in under 1 hour) is achievable with sequential processing
- Deterministic output is trivial with sequential processing; parallel processing would require a sort-and-merge phase

If sequential throughput proves insufficient, parallelism can be added within the file level (multiple proofs from the same file in parallel) with a deterministic merge step. This is not designed or specified in this phase.

## Design Rationale

### Why the orchestrator is a separate component from SessionManager

The SessionManager is designed for interactive use — open a session, step through it, close it. The orchestrator's concerns (enumerate projects, iterate files, skip failures, stream output, compute summaries) are batch-pipeline concerns that do not belong in an interactive session manager. Keeping them separate preserves Phase 2's clean session API and avoids coupling batch-specific logic into the MCP code path.

### Why sequential processing over parallel

Deterministic output is a P0 requirement. Sequential processing makes determinism trivial — proofs are extracted and emitted in enumeration order. Parallel extraction would require buffering and reordering, adding complexity and memory overhead. The throughput target (stdlib in under 1 hour) does not require parallelism.

### Why one session per proof rather than one session per file

Coq's proof state is per-proof, not per-file. A session encapsulates a single proof's lifecycle. Opening one session per proof reuses Phase 2's SessionManager without modification and provides natural failure isolation — a crash in proof P's session does not affect proof Q's session, even if both are in the same file.
