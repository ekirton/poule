# Extraction Campaign Orchestrator

The batch component that processes one or more Coq project directories, extracts proof traces for all provable theorems, and produces a streaming JSON Lines dataset with graceful degradation on per-proof failures.

**Feature**: [Batch Extraction CLI](../features/batch-extraction-cli.md), [Extraction Library Support](../features/extraction-library-support.md)
**Data models**: [extraction-types.md](data-models/extraction-types.md), [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
CLI (extract subcommand)
  │
  │ project directories, options
  ▼
┌───────────────────────────────────────────────────────┐
│         Extraction Campaign Orchestrator               │
│                                                        │
│  Campaign Planner                                      │
│    enumerate projects → enumerate files → list proofs  │
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
extract(project_dirs[], options)
  │
  ├─ Validate all project directories exist
  │
  ├─ Build campaign plan:
  │    For each project_dir:
  │      Detect Coq version (coqc --version)
  │      Detect git commit hash (git rev-parse HEAD, or null)
  │      Enumerate .v files in deterministic order (sorted by path)
  │      For each .v file:
  │        List provable theorems (via Coq backend query)
  │        Apply scope filter if configured (name pattern, module filter)
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
| `unknown` | Any other unexpected error | Skip this proof |

When a file fails to load, all theorems in that file are skipped with `load_failure` errors rather than attempting each one independently.

## Theorem Enumeration

The campaign planner enumerates theorems by querying the Coq backend for each .v file. The enumeration mechanism is backend-dependent:

- **coq-lsp**: Process the file and list all completed proof blocks
- **SerAPI**: Load the file and query for all proof-bearing vernacular commands

The enumeration returns theorems in declaration order within each file. This ordering, combined with sorted file paths and ordered project directories, produces a deterministic total order over all theorems in the campaign.

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
