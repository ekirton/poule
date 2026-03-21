# Fill Admits Orchestrator

The component that scans a Coq proof script for `admit` calls, opens proof sessions at each admit location, invokes proof search on each, and assembles the result into a modified script.

**Feature**: [Fill Admits](../features/fill-admits.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
MCP Server
  │
  │ fill_admits(file_path, timeout_per_admit, max_depth, max_breadth)
  ▼
┌────────────────────────────────────────────────────┐
│              Fill Admits Orchestrator                │
│                                                     │
│  1. Parse file, locate admit positions              │
│  2. For each admit:                                 │
│       open session → position at admit              │
│       invoke Proof Search Engine                    │
│       collect result (success or failure)            │
│       close session                                 │
│  3. Assemble modified script                        │
│  4. Return result summary + modified script         │
│                                                     │
└──────────────┬──────────────────┬───────────────────┘
               │                  │
               │ proof search     │ session lifecycle
               ▼                  ▼
     Proof Search Engine    Proof Session Manager
```

## Admit Location

The orchestrator parses the .v file to locate `admit` calls. Each admit is identified by:

| Field | Type | Description |
|-------|------|-------------|
| `proof_name` | qualified name | The proof containing this admit |
| `admit_index` | non-negative integer | 0-based index of this admit within the proof (for proofs with multiple admits) |
| `line_number` | positive integer | Source line number |
| `column_range` | (start, end) | Column span of the `admit` text |

Admit detection is syntactic — scanning for `admit.` and `Admitted.` tokens. This does not require Coq to be running; it operates on the source text directly.

## Orchestration Loop

```
fill_admits(file_path, timeout_per_admit=30, max_depth=10, max_breadth=20)
  │
  ├─ Read file contents
  │
  ├─ Locate all admit positions → admit_list
  │    If empty → return success with zero admits found
  │
  ├─ results = []
  │
  ├─ For each admit in admit_list (in source order):
  │    │
  │    ├─ Open proof session at admit's proof_name
  │    │    On error (file not found, proof not found) → record error, continue
  │    │
  │    ├─ Navigate to the admit's position in the proof:
  │    │    Step forward through the proof's tactic sequence until reaching
  │    │    the admit's position (the proof state just before the admit)
  │    │
  │    ├─ Invoke proof_search(session_id, timeout_per_admit, max_depth, max_breadth)
  │    │    ├─ On success → record replacement tactic sequence
  │    │    └─ On failure → record failure with search stats
  │    │
  │    ├─ Close proof session
  │    │
  │    └─ Append result to results
  │
  ├─ Assemble modified script:
  │    For each successful result, replace the admit text span with the
  │    verified tactic sequence. Unfilled admits remain as-is.
  │
  └─ Return FillAdmitsResult
```

## Result Type

**FillAdmitsResult**:

| Field | Type | Description |
|-------|------|-------------|
| `total_admits` | non-negative integer | Total admits found in the file |
| `filled` | non-negative integer | Number of admits successfully replaced |
| `unfilled` | non-negative integer | Number of admits that could not be filled |
| `results` | list of AdmitResult | Per-admit outcome |
| `modified_script` | text | The file contents with successful replacements applied |

**AdmitResult**:

| Field | Type | Description |
|-------|------|-------------|
| `proof_name` | qualified name | The proof containing this admit |
| `admit_index` | non-negative integer | Index of this admit within the proof |
| `line_number` | positive integer | Source line of the original admit |
| `status` | `"filled"` or `"unfilled"` | Whether the admit was successfully replaced |
| `replacement` | list of string or null | On filled: the tactic sequence that replaces the admit |
| `search_stats` | SearchResult stats or null | On unfilled: the search failure information |

## Sketch-Then-Prove

Sketch-then-prove is a usage pattern over fill-admits, not a separate mechanism:

1. Claude Code generates a proof sketch with `admit` stubs for intermediate subgoals
2. The user (or Claude) writes this sketch to a .v file
3. `fill_admits` is invoked on the file
4. Each `admit` stub is attacked independently by proof search
5. The result shows which stubs were filled and which remain

The orchestrator does not distinguish between "admits in an incomplete proof" and "admits in a deliberate sketch." Both are processed identically — locate, search, replace.

## Session Lifecycle

Each admit gets its own proof session. Sessions are created and closed within the per-admit loop iteration — no sessions are held open across admits.

This means:
- Admits in different proofs within the same file are handled naturally (different session per proof)
- Multiple admits in the same proof each get a fresh session (positioned at the admit's location)
- A crash during one admit's search does not affect subsequent admits

The tradeoff is session creation overhead (spawning a Coq backend process per admit). For files with many admits, this overhead may dominate. A future optimization could reuse a single session across admits within the same proof — but this requires careful state management (stepping forward to each admit's position within a single session, resetting between admits).

## Error Handling

| Condition | Behavior |
|-----------|----------|
| File not found | Return structured error immediately |
| No admits found | Return success with zero admits, unmodified script |
| Proof not found for an admit | Record error for that admit, continue with remaining admits |
| Backend crash during one admit's search | Record failure for that admit, continue with remaining admits |
| All admits fail | Return result with `filled: 0` and per-admit failure details |

## Design Rationale

### Why process admits sequentially rather than in parallel

Parallel search across admits would require multiple concurrent Coq backend processes — one per admit under search. This multiplies memory consumption (each Coq process loads the full environment). Sequential processing bounds resource usage at one session at a time. If throughput becomes a concern, bounded parallelism (e.g., 3 concurrent searches) can be added with a semaphore.

### Why fresh sessions per admit rather than session reuse

Session reuse within a proof would avoid re-loading the .v file and re-positioning at the proof. But it introduces complexity: after searching at admit k, the session state must be restored to the exact position of admit k+1. A failed search may leave the session in an unexpected state. Fresh sessions are stateless from the orchestrator's perspective — each admit is an independent unit of work. The overhead of session creation (~1-2 seconds per admit) is small relative to the search timeout (30 seconds).

### Why syntactic admit detection rather than Coq-assisted

Syntactic detection (scanning for `admit.` tokens) works without running Coq and handles files that may not compile (common when admits are present). Coq-assisted detection would require loading the file and inspecting the proof state — which is what the session does anyway. Syntactic detection gives the orchestrator a quick plan (how many admits, where) before committing to expensive session creation.
