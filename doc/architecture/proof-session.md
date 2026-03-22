# Proof Session Manager

The stateful component that manages interactive proof sessions, mediating between the MCP Server and Coq backend processes. Each session encapsulates a single proof within a single .v file.

**Feature**: [Proof Session Management](../features/proof-session-management.md), [Proof State Observation](../features/proof-state-observation.md), [Tactic Interaction](../features/tactic-interaction.md), [Premise Tracking](../features/premise-tracking.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
MCP Server
  │
  │ session operations (open, close, submit, observe, ...)
  ▼
┌─────────────────────────────────────────────────┐
│            Proof Session Manager                 │
│                                                  │
│  Session Registry                                │
│    session_id → SessionState                     │
│                                                  │
│  Per-session:                                    │
│    ┌──────────────────────────────┐              │
│    │ SessionState                 │              │
│    │   coq_backend: CoqBackend   │              │
│    │   step_history: ProofState[] │              │
│    │   original_script: Tactic[] │              │
│    │   last_active: timestamp    │              │
│    └──────────┬───────────────────┘              │
│               │                                  │
│               │ tactic submission / state query   │
│               ▼                                  │
│    ┌──────────────────────────────┐              │
│    │ CoqBackend (per-session)     │              │
│    │   Wraps coq-lsp or SerAPI   │              │
│    │   Bidirectional, stateful   │              │
│    └──────────────────────────────┘              │
└─────────────────────────────────────────────────┘
```

## Session Registry

The session registry is an in-memory map from session IDs to `SessionState` objects. It provides:

- **Lookup by ID**: O(1) access to any session's state
- **Enumeration**: List all active sessions with metadata
- **Lifecycle management**: Create, close, and auto-expire sessions

Session IDs are opaque strings generated to be unique within the server's lifetime. They do not need to be globally unique or persist across server restarts — sessions are ephemeral.

## Session Lifecycle

### Open Session

```
open_proof_session(file_path, proof_name)
  │
  ├─ Validate file exists on disk
  │
  ├─ Spawn a new CoqBackend process for this session
  │    └─ Load the .v file
  │    └─ Position at the named proof
  │    └─ If proof not found → structured error, kill process
  │
  ├─ Read the initial proof state from the backend
  │
  ├─ If the proof has an existing script, extract the tactic list
  │
  ├─ Create SessionState:
  │    session_id: generate unique ID
  │    step_history: [initial_state]
  │    original_script: [...] or empty
  │    total_steps: len(original_script) or null
  │    last_active: now
  │
  ├─ Register in session registry
  │
  └─ Return session_id + initial ProofState
```

### Close Session

```
close_proof_session(session_id)
  │
  ├─ Look up session in registry → error if not found
  │
  ├─ Terminate the CoqBackend process
  │
  ├─ Remove from registry
  │
  └─ Return confirmation
```

### Timeout

A background sweep runs periodically (implementation-defined interval). For each session where `now - last_active > 30 minutes`:
1. Terminate the CoqBackend process
2. Remove from registry
3. Log the timeout (session ID, proof name, idle duration)

No notification is pushed to the client. The client discovers the timeout on the next tool call via a `SESSION_EXPIRED` error.

## State History

Each session maintains an ordered list of proof states: `step_history[0..current_step]`. This supports:

- **Observe current state**: Return `step_history[current_step]`
- **Step backward**: Decrement `current_step`; the state at the previous step is already cached
- **Step forward / submit tactic**: Execute in the backend, append the resulting state to `step_history`, increment `current_step`

When stepping backward and then submitting a new tactic (branching), the history after the current step is discarded — the session follows a linear history model, not a tree.

### State at Arbitrary Step

For completed proofs, `get_proof_state_at_step(session_id, k)` returns `step_history[k]`. If the full history has not been computed yet (e.g., the session was opened but not all steps have been stepped through), the session manager replays the original script forward from the last cached step to step k, caching each intermediate state.

## Tactic Dispatch

### Submit Tactic

```
submit_tactic(session_id, tactic_string)
  │
  ├─ Look up session → error if not found/expired
  │
  ├─ Update last_active timestamp
  │
  ├─ Send tactic to CoqBackend
  │    ├─ Success → new ProofState
  │    └─ Failure → Coq error message
  │
  ├─ On success:
  │    ├─ Truncate step_history after current_step (discard any forward branch)
  │    ├─ Append new state to step_history
  │    ├─ Increment current_step
  │    └─ Return new ProofState (with is_complete flag if proof is finished)
  │
  └─ On failure:
       └─ Return structured error with Coq error message; state unchanged
```

### Step Forward

```
step_forward(session_id)
  │
  ├─ Look up session → error if not found/expired
  │
  ├─ Check: current_step < total_steps → error if at end
  │
  ├─ Retrieve original_script[current_step] (the next tactic)
  │
  ├─ Execute tactic in CoqBackend (same path as submit)
  │
  └─ Return tactic string + new ProofState
```

### Step Backward

```
step_backward(session_id)
  │
  ├─ Look up session → error if not found/expired
  │
  ├─ Check: current_step > 0 → error if at initial state
  │
  ├─ Decrement current_step
  │
  ├─ Reset CoqBackend to the state at step_history[current_step]
  │    (mechanism is backend-dependent: undo command, or replay from start)
  │
  └─ Return ProofState at new current_step
```

### Batch Submission

```
submit_tactic_batch(session_id, tactics[])
  │
  ├─ For each tactic in order:
  │    ├─ Submit via submit_tactic logic
  │    ├─ On success → record (tactic, new_state) in results
  │    ├─ On failure → record error, stop processing
  │    └─ On proof complete → record, stop processing
  │
  └─ Return results list
```

## Proof Trace Extraction

```
extract_proof_trace(session_id)
  │
  ├─ Ensure the full proof has been stepped through:
  │    If step_history length < total_steps + 1:
  │      Replay original script from last cached step to end
  │      Record wall-clock time (monotonic) for each tactic execution
  │
  ├─ Assemble ProofTrace from step_history + original_script + timing
  │    step 0: duration_ms = null (initial state, no tactic)
  │    steps 1..N: duration_ms = wall-clock ms for that tactic's execution
  │    Already-cached steps that were not timed: duration_ms = null
  │
  └─ Return ProofTrace
```

## Premise Extraction

Premise annotations are extracted by analyzing the Coq backend's internal state at each tactic step. The extraction mechanism is backend-dependent:

- **coq-lsp**: Query the document's proof state annotations after processing each tactic
- **SerAPI**: Inspect the `Environ` and tactic trace after each step

```
get_proof_premises(session_id)
  │
  ├─ Ensure the full proof has been traced (same as extract_proof_trace)
  │
  ├─ For each tactic step k (1..N):
  │    Query the backend for premises used at step k
  │    Build PremiseAnnotation with fully qualified names and kinds
  │
  └─ Return list of PremiseAnnotation

get_step_premises(session_id, step_index)
  │
  ├─ Validate step_index in [1, total_steps]
  │
  ├─ Ensure proof has been stepped through to at least step_index
  │
  └─ Return PremiseAnnotation for that step
```

### Premise Classification

The backend returns raw premise references. The session manager classifies each premise:

| Source | Kind |
|--------|------|
| Reference to a previously proved lemma/theorem | `lemma` |
| Reference to a local hypothesis in the context | `hypothesis` |
| Reference to an inductive type constructor | `constructor` |
| Reference to a definition that was unfolded | `definition` |

Classification uses the Coq environment's declaration metadata. Ambiguous cases (e.g., a local definition shadowing a global one) are resolved by the scoping rules Coq itself applies — the premise is classified based on what Coq actually used, not what the name resolves to in the global scope.

## Vernacular Command Submission

The Session Manager provides a raw command submission operation for components that need unstructured Coq output (extraction, notation inspection, assumption auditing). This is distinct from `submit_tactic`, which returns a structured `ProofState`.

```
submit_command(session_id, command)
  │
  ├─ Look up session → error if not found/expired
  │
  ├─ Update last_active timestamp
  │
  ├─ Send command to the session's Coq process
  │    └─ Detect end-of-output via sentinel framing
  │
  └─ Return command output as a single string
```

### Output Model

The Coq process is spawned with stdout and stderr merged into a single stream. The `submit_command` operation returns this merged output as a single string. Consumers parse the combined output using pattern matching to distinguish code, errors, and warnings.

Merging is required because the sentinel-based end-of-output detection relies on a `Fail` command whose output destination (stdout vs stderr) varies across Coq/Rocq versions and flags. Merging streams at the OS level ensures the sentinel is always visible on the stream being read.

### Implications for Consumers

Components that consume `submit_command` output must not assume separate stdout/stderr streams. Error detection, warning extraction, and code identification all operate on the single merged string via pattern matching. This is a deliberate design choice — Coq's own stream behavior is not cleanly separated (warnings can appear on stdout during successful operations), so pattern-based classification is more reliable than stream-based classification regardless of merging.

## CoqBackend Interface

The `CoqBackend` abstracts the communication with a Coq process (coq-lsp or SerAPI). Each session owns one backend instance.

### Responsibilities

| Operation | Description |
|-----------|-------------|
| `load_file(path)` | Load and check a .v file |
| `position_at_proof(name)` | Navigate to a named proof; return initial state |
| `execute_tactic(tactic)` | Submit a tactic; return new state or error |
| `get_current_state()` | Read the current proof state (goals, hypotheses) |
| `undo()` | Undo the last tactic (backend-dependent mechanism) |
| `get_premises_at_step(k)` | Query premise information for step k |
| `shutdown()` | Terminate the backend process |

### Process Isolation

Each session spawns its own backend process. This provides:

- **Crash isolation**: A crash in one session's process does not affect others
- **State isolation**: No shared mutable state between sessions
- **Resource cleanup**: Killing the process reclaims all resources (memory, file handles)

The tradeoff is memory overhead — each process loads the Coq environment independently. For the target of ≥ 3 concurrent sessions, this is acceptable. If scaling beyond ~10 sessions becomes necessary, a process pool with state checkpointing would be considered.

### Crash Detection

The session manager monitors each backend process. If a process exits unexpectedly:
1. Mark the session as crashed in the registry
2. Do not remove the session — let the client discover the crash via a `BACKEND_CRASHED` error on the next tool call
3. Log the crash (session ID, exit code, signal)

## Concurrency

The session registry is accessed by MCP tool handlers which may execute concurrently (depending on the MCP server's concurrency model). The registry must support:

- Concurrent reads (list sessions, look up session by ID)
- Serialized writes (create session, close session, timeout sweep)
- Per-session serialized operations (two tool calls on the same session must not interleave tactic execution)

Per-session locking ensures that a `submit_tactic` and a concurrent `step_backward` on the same session are serialized, preventing state corruption.

## Design Rationale

### Why one process per session

Shared-process models (multiple sessions in one Coq process) risk state interference — Coq's internal state management was not designed for multiplexing. Process isolation is the simplest mechanism that guarantees independence, and the memory overhead is bounded by the session count target (≥ 3).

### Why linear history rather than branching

A branching history model (tree of states) would support "try tactic A, undo, try tactic B, then compare A and B." While useful, it adds substantial complexity to the session manager (tree data structure, branch naming, garbage collection). The linear model is sufficient for the target use cases — submit/undo/retry — and random-access observation (`get_proof_state_at_step`) handles the analysis use case. Branching can be added in a future phase if needed.

### Why replay for step-backward rather than snapshotting

Coq backends may not support efficient undo. The alternative — replaying from the initial state to step k-1 — is always correct. With cached states in `step_history`, the replay cost is zero for already-visited steps. For the first backward step to an unvisited state, replay from the nearest cached state is O(k) in tactic execution time, which is acceptable for typical proof lengths (< 100 steps).

### Why on-demand state computation rather than eager materialization

Eagerly computing all N+1 states on session open would block the open call for the full proof execution time. On-demand computation means the open call returns immediately with just the initial state. States are materialized as the client steps through the proof, and `extract_proof_trace` triggers full materialization only when all states are actually needed.
