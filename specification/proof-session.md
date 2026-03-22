# Proof Session Manager

Stateful component that manages interactive proof sessions, mediating between the MCP Server and per-session Coq backend processes.

**Architecture**: [proof-session.md](../doc/architecture/proof-session.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the session manager that creates and destroys proof sessions, dispatches tactic operations to per-session Coq backends, maintains proof state history, extracts premise annotations, and enforces concurrency and timeout policies.

## 2. Scope

**In scope**: Session registry, session lifecycle (open, close, timeout, crash), SessionState data model, state history management, tactic dispatch (submit, step forward, step backward, batch), vernacular command submission, proof trace extraction, premise extraction, CoqBackend interface, concurrency model.

**Out of scope**: MCP protocol handling (owned by mcp-server), proof state serialization to JSON (owned by proof-serialization), search index and retrieval (independent subsystem).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Session | An interactive proof exploration context encapsulating one proof in one .v file, with independent state |
| Session registry | An in-memory map from session IDs to SessionState objects |
| Step history | An ordered list of ProofState snapshots maintained per session, indexed by step number |
| Current step | The session's current position in the step history; 0 = initial state |
| Original script | The tactic list from a completed proof's source; null for interactively constructed proofs |
| CoqBackend | An abstraction over a single coq-lsp or SerAPI process providing bidirectional, stateful proof interaction |

## 4. Behavioral Requirements

### 4.1 Session Registry

The system shall maintain an in-memory session registry mapping session IDs to SessionState objects.

#### create_session(file_path, proof_name)

- REQUIRES: `file_path` is a non-empty string. `proof_name` is a non-empty string.
- ENSURES: A new CoqBackend process is spawned. The backend loads the .v file and positions at the named proof. A unique session ID is generated. A SessionState is created with `step_history = [initial_state]`, `current_step = 0`, `original_script` populated from the existing proof script (or empty if the proof has no script), `total_steps = len(original_script)` (or null if no script), `created_at = now`, `last_active_at = now`. The SessionState is registered in the session registry. Returns the session ID and initial ProofState.
- On file not found: the CoqBackend is not spawned; returns `FILE_NOT_FOUND` error.
- On proof not found: the spawned CoqBackend is terminated; returns `PROOF_NOT_FOUND` error.

> **Given** a valid .v file containing a proof named `my_lemma`
> **When** `create_session("/path/to/file.v", "my_lemma")` is called
> **Then** a new session is returned with `current_step = 0`, `is_complete = false`, and the initial proof state containing all goals and hypotheses

> **Given** a .v file path that does not exist on disk
> **When** `create_session("/nonexistent.v", "my_lemma")` is called
> **Then** a `FILE_NOT_FOUND` error is returned and no session is created

> **Given** a valid .v file that does not contain a proof named `missing`
> **When** `create_session("/path/to/file.v", "missing")` is called
> **Then** a `PROOF_NOT_FOUND` error is returned, the backend process is terminated, and no session is created

#### close_session(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: The session's CoqBackend process is terminated. The SessionState is removed from the registry. Returns confirmation.
- On session not found: returns `SESSION_NOT_FOUND` error.

> **Given** an active session with ID "abc-123"
> **When** `close_session("abc-123")` is called
> **Then** the CoqBackend process is terminated, the session is removed from the registry, and confirmation is returned

> **Given** a session ID that does not exist in the registry
> **When** `close_session("nonexistent")` is called
> **Then** a `SESSION_NOT_FOUND` error is returned

> **Given** a crashed session with ID "abc-123"
> **When** `close_session("abc-123")` is called
> **Then** the session entry is removed from the registry and confirmation is returned

#### list_sessions()

- REQUIRES: None.
- ENSURES: Returns a list of Session metadata objects for all active sessions (state = `active`). Each contains: `session_id`, `file_path`, `proof_name`, `current_step`, `total_steps`, `created_at`, `last_active_at`. Crashed sessions are not included.

> **Given** three sessions: two active and one crashed
> **When** `list_sessions()` is called
> **Then** the returned list contains two Session objects (the active ones only)

> **Given** no active sessions
> **When** `list_sessions()` is called
> **Then** an empty list is returned

#### lookup_session(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns the SessionState for the given ID. Updates `last_active_at` to `now`.
- On session not found: returns `SESSION_NOT_FOUND` error.
- On session timed out: returns `SESSION_EXPIRED` error.
- On session crashed: returns `BACKEND_CRASHED` error.

MAINTAINS: Every operation that targets a session by ID shall call `lookup_session` first. The `last_active_at` timestamp is updated only on successful lookup (not on error).

> **Given** an active session with ID "abc-123"
> **When** `lookup_session("abc-123")` is called
> **Then** the SessionState is returned and `last_active_at` is updated to the current time

> **Given** a session that was auto-closed by timeout
> **When** `lookup_session` is called with that session's ID
> **Then** a `SESSION_EXPIRED` error is returned

### 4.2 State Observation

#### observe_state(session_id)

- REQUIRES: Session exists and is active.
- ENSURES: Returns `step_history[current_step]`.

> **Given** an active session at step 3
> **When** `observe_state(session_id)` is called
> **Then** the ProofState at step 3 is returned, including goals, hypotheses, and step_index = 3

> **Given** an active session at step 0 (initial state)
> **When** `observe_state(session_id)` is called
> **Then** the initial ProofState is returned with the original goals from the proof statement

#### get_state_at_step(session_id, step)

- REQUIRES: Session exists and is active. `step` is an integer in [0, `total_steps`].
- ENSURES: If `step_history` has been computed through step `step`, returns `step_history[step]`. Otherwise, replays the original script from the last cached step forward to step `step`, caching each intermediate state, then returns `step_history[step]`.
- On step out of range: returns `STEP_OUT_OF_RANGE` error with the valid range.
- On session with no original script and step > current_step: returns `STEP_OUT_OF_RANGE` error.

> **Given** a session at step 2 with total_steps = 10 and step_history cached through step 2
> **When** `get_state_at_step(session_id, 5)` is called
> **Then** the backend replays tactics 3, 4, 5 from the original script, caches states 3..5, and returns state at step 5

> **Given** a session with total_steps = 5
> **When** `get_state_at_step(session_id, 7)` is called
> **Then** a `STEP_OUT_OF_RANGE` error is returned indicating the valid range is [0, 5]

> **Given** a session at step 5 with step_history already cached through step 8
> **When** `get_state_at_step(session_id, 3)` is called
> **Then** the cached state at step 3 is returned immediately (no replay needed)

#### extract_trace(session_id)

- REQUIRES: Session exists and is active. The session has an original script (`total_steps` is not null).
- ENSURES: If step_history length < `total_steps + 1`, replays the original script from the last cached step to the end, caching all states and recording wall-clock time (monotonic) for each tactic execution. Assembles and returns a ProofTrace containing all `total_steps + 1` TraceSteps (step 0 with `tactic = null` and `duration_ms = null`, steps 1..N with the original tactic strings and `duration_ms` set to the wall-clock milliseconds measured during replay, or `null` if the step was already cached before this call).
- On session with no original script: returns `STEP_OUT_OF_RANGE` error (no complete proof to trace).

> **Given** a session with total_steps = 3 and step_history cached through step 1
> **When** `extract_trace(session_id)` is called
> **Then** the backend replays tactics 2 and 3, and the returned ProofTrace contains 4 steps: step 0 with null tactic and null duration_ms; step 1 with tactic string and null duration_ms (already cached); steps 2-3 with tactic strings and non-negative float duration_ms values

> **Given** a session opened on an incomplete proof (no original script)
> **When** `extract_trace(session_id)` is called
> **Then** a `STEP_OUT_OF_RANGE` error is returned

### 4.3 Tactic Dispatch

#### submit_tactic(session_id, tactic)

- REQUIRES: Session exists and is active. `tactic` is a non-empty string.
- ENSURES: Sends the tactic to the CoqBackend. On success: truncates `step_history` after `current_step` (discards forward branch), appends the new ProofState, increments `current_step`, returns the new ProofState. On backend failure: returns `TACTIC_ERROR` with the Coq error message; `step_history` and `current_step` are unchanged.
- MAINTAINS: After a successful submit, `len(step_history) == current_step + 1`. The new state's `is_complete` is true when no open goals remain.

> **Given** a session at step 3 with step_history length 6 (previously stepped forward to step 5, then back to step 3)
> **When** `submit_tactic(session_id, "simpl.")` succeeds
> **Then** step_history is truncated to steps 0..3, the new state is appended as step 4, current_step becomes 4, and the previous states 4..5 are discarded

> **Given** a session at step 1
> **When** `submit_tactic(session_id, "invalid_tactic.")` is called and Coq returns an error
> **Then** a `TACTIC_ERROR` is returned with the Coq error message, current_step remains 1, and step_history is unchanged

> **Given** a session with one remaining goal
> **When** `submit_tactic(session_id, "reflexivity.")` succeeds and closes the last goal
> **Then** the returned ProofState has `is_complete = true`, `focused_goal_index = null`, and `goals = []`

#### step_forward(session_id)

- REQUIRES: Session exists and is active. `current_step < total_steps`.
- ENSURES: Retrieves `original_script[current_step]` (the next tactic). Executes it in the CoqBackend. Appends the resulting state to `step_history`. Increments `current_step`. Returns the tactic string and new ProofState.
- On current_step >= total_steps: returns `PROOF_COMPLETE` error.
- On session with no original script: returns `PROOF_COMPLETE` error (no script to step through).

> **Given** a session at step 2 with total_steps = 5
> **When** `step_forward(session_id)` is called
> **Then** the original tactic at index 2 is executed, current_step becomes 3, and both the tactic string and resulting ProofState are returned

> **Given** a session at step 5 with total_steps = 5
> **When** `step_forward(session_id)` is called
> **Then** a `PROOF_COMPLETE` error is returned

#### step_backward(session_id)

- REQUIRES: Session exists and is active. `current_step > 0`.
- ENSURES: Decrements `current_step`. Resets the CoqBackend to the state at `step_history[current_step]` (mechanism is backend-dependent: undo command or replay from initial state). Returns the ProofState at the new `current_step`.
- On current_step == 0: returns `NO_PREVIOUS_STATE` error.

> **Given** a session at step 3
> **When** `step_backward(session_id)` is called
> **Then** current_step becomes 2 and the ProofState at step 2 is returned

> **Given** a session at step 0 (initial state)
> **When** `step_backward(session_id)` is called
> **Then** a `NO_PREVIOUS_STATE` error is returned

#### submit_tactic_batch(session_id, tactics)

- REQUIRES: Session exists and is active. `tactics` is a non-empty list of non-empty strings.
- ENSURES: Processes tactics sequentially using the `submit_tactic` logic. For each tactic: on success, records `{tactic, state}` in the results list; on failure, records the error and stops processing; on proof completion, records the result and stops processing. Returns the results list.
- MAINTAINS: After batch execution, `current_step` reflects the number of successfully applied tactics. Step_history is consistent with the sequential application.

> **Given** a session at step 0
> **When** `submit_tactic_batch(session_id, ["intro n.", "induction n.", "invalid."])` is called and tactics 1-2 succeed but tactic 3 fails
> **Then** the results list contains 2 success entries and 1 error entry, current_step is 2, and step_history contains states 0..2

> **Given** a session at step 0
> **When** `submit_tactic_batch(session_id, ["intro n.", "reflexivity."])` is called and tactic 2 completes the proof
> **Then** the results list contains 2 success entries, the second has `is_complete = true`, and no further tactics are processed

### 4.4 Vernacular Command Submission

#### submit_command(session_id, command)

- REQUIRES: Session exists and is active. `command` is a non-empty string containing one or more Coq vernacular commands (each terminated with `.`).
- ENSURES: Sends `command` to a coqtop subprocess (not the session's CoqBackend — see §4.4.1). Returns the command output as a single string. The output is the merged stdout and stderr from the coqtop process — consumers must not assume separate streams.
- MAINTAINS: The session's `last_active_at` is updated. The session's proof state history is not modified — `submit_command` does not track states or update `step_history`. The Coq environment may be modified by the command (e.g., `Extraction Language OCaml.` changes extraction settings) within the coqtop subprocess only — the session's CoqBackend state is unaffected.
- On session not found: returns `SESSION_NOT_FOUND` error.
- On session expired: returns `SESSION_EXPIRED` error.
- On backend crashed: returns `BACKEND_CRASHED` error.

> **Given** an active session with a definition `my_fn` in scope
> **When** `submit_command(session_id, "Extraction Language OCaml. Extraction my_fn.")` is called
> **Then** a string is returned containing the Coq output (extracted OCaml code, or error messages, or both warnings and code — all merged into a single string)

> **Given** an active session
> **When** `submit_command(session_id, "Print Assumptions my_theorem.")` is called
> **Then** a string is returned containing the Coq output listing the assumptions

> **Given** a session that has timed out
> **When** `submit_command(session_id, "Check nat.")` is called
> **Then** a `SESSION_EXPIRED` error is returned

#### 4.4.1 Coqtop Subprocess for Vernacular Commands

The session's CoqBackend (coq-lsp) communicates via the LSP protocol, which does not expose the output of successful vernacular introspection commands (Print, Check, About, Locate). See [coq-proof-backend.md](coq-proof-backend.md) §4.5. To capture vernacular output, `submit_command` routes commands through a coqtop subprocess.

The session manager shall lazily spawn a coqtop subprocess on the first `submit_command` call for a given session. The subprocess:

1. Is spawned with stdout and stderr merged into a single stream.
2. Loads the session's file context — all vernacular commands from the `.v` file that precede the proof target (imports, definitions, notations, section variables, prior lemmas with their proofs, etc.) — so that the query context matches the session's environment. If the session has no proof target (i.e., `proof_name` is empty), loads only the file's `Require`/`Import` commands.
3. Persists for the lifetime of the session — subsequent `submit_command` calls reuse the same subprocess.
4. Is terminated when the session is closed, times out, or the CoqBackend crashes.

The coqtop subprocess is independent of the CoqBackend process. Commands executed in coqtop do not affect the CoqBackend's proof state, and tactic operations in the CoqBackend do not affect the coqtop environment.

| Property | CoqBackend (coq-lsp) | Coqtop subprocess |
|----------|---------------------|-------------------|
| Purpose | Proof interaction (tactics, undo, state observation) | Vernacular output capture |
| Protocol | LSP JSON-RPC | stdin/stdout with sentinel-based detection |
| Spawning | Eager (at session creation) | Lazy (on first `submit_command`) |
| Lifecycle | Session creation → session close | First `submit_command` → session close |

> **Given** a session that has never called `submit_command`
> **When** `submit_command(session_id, "Check nat.")` is called for the first time
> **Then** a coqtop subprocess is spawned, the file's context (all vernacular commands preceding the proof target) is loaded, the command is executed, and the output is returned

> **Given** a session on `add_comm` in a file containing `Lemma my_lemma : ... Proof. ... Qed.` before `add_comm`
> **When** `submit_command(session_id, "Check my_lemma.")` is called
> **Then** the output contains the type of `my_lemma`, because the file content preceding `add_comm` was loaded into the coqtop subprocess

> **Given** a session with an active coqtop subprocess
> **When** `submit_command(session_id, "Print nat.")` is called
> **Then** the existing coqtop subprocess is reused (no new process is spawned)

#### Output model

The coqtop subprocess is spawned with stdout and stderr merged into a single stream. This is required because the sentinel-based end-of-output detection relies on a `Fail` command whose output destination varies across Coq/Rocq versions and flags. Merging at the OS level ensures the sentinel is always visible.

Consumers that need to distinguish code from errors or warnings (e.g., the extraction handler) use pattern matching on the merged output string. The session manager does not perform any classification — it returns the raw merged output.

#### Relationship to submit_tactic

`submit_command` and `submit_tactic` serve different purposes:

| Property | `submit_tactic` | `submit_command` |
|----------|-----------------|------------------|
| Backend | CoqBackend (coq-lsp) | Coqtop subprocess |
| Return type | `ProofState` (structured) | `str` (raw merged output) |
| State tracking | Updates `step_history` and `current_step` | No state tracking |
| Use case | Interactive proof stepping | Extraction, notation inspection, assumption auditing, queries |
| Concurrency | Serialized per session | Serialized per session |

### 4.5 Premise Extraction

#### get_premises(session_id)

- REQUIRES: Session exists and is active. The session has an original script.
- ENSURES: Ensures the full proof has been traced (same materialization as `extract_trace`). For each tactic step k (1..N), queries the CoqBackend for premises used at step k. Returns a list of N PremiseAnnotation objects, one per tactic step. Each PremiseAnnotation contains: `step_index`, `tactic`, and a list of Premise objects with fully qualified `name` and `kind`.

> **Given** a session with a completed proof of 3 tactic steps
> **When** `get_premises(session_id)` is called
> **Then** 3 PremiseAnnotation objects are returned, each with `step_index` in [1, 3] and the corresponding tactic string

> **Given** a step that uses `rewrite Nat.add_comm.`
> **When** premises are extracted for that step
> **Then** the PremiseAnnotation includes a Premise with `name = "Coq.Arith.PeanoNat.Nat.add_comm"` and `kind = "lemma"`

#### get_step_premises(session_id, step)

- REQUIRES: Session exists and is active. `step` is an integer in [1, `total_steps`].
- ENSURES: Ensures the proof has been stepped through to at least step `step`. Returns a single PremiseAnnotation for that step.
- On step out of range: returns `STEP_OUT_OF_RANGE` error.

> **Given** a session with total_steps = 5
> **When** `get_step_premises(session_id, 3)` is called
> **Then** a single PremiseAnnotation for step 3 is returned

> **Given** a session with total_steps = 5
> **When** `get_step_premises(session_id, 0)` is called
> **Then** a `STEP_OUT_OF_RANGE` error is returned (premise step range is [1, N], not [0, N])

#### Premise classification

When the CoqBackend reports raw premise references, the session manager shall classify each premise:

| Source in the Coq environment | Assigned `kind` |
|-------------------------------|----------------|
| Previously proved lemma or theorem | `lemma` |
| Local hypothesis in the proof context | `hypothesis` |
| Inductive type constructor | `constructor` |
| Definition (unfolded or referenced) | `definition` |

Classification shall use the Coq environment's declaration metadata. When a local name shadows a global name, the premise shall be classified based on what Coq actually resolved — determined by Coq's scoping rules, not by name lookup in the global environment.

### 4.6 Session Timeout

The session manager shall run a periodic background sweep (interval is implementation-defined). For each session where `now - last_active_at > 30 minutes`:

1. Terminate the CoqBackend process.
2. Remove the session from the registry.
3. Log: session ID, proof name, idle duration.

No notification is pushed to the client. The client discovers the timeout on the next `lookup_session` call via a `SESSION_EXPIRED` error.

### 4.7 Crash Detection

The session manager shall monitor each CoqBackend process. When a process exits unexpectedly:

1. Mark the session as `crashed` in the registry (do not remove it).
2. Log: session ID, exit code, signal (if available).

The client discovers the crash on the next `lookup_session` call via a `BACKEND_CRASHED` error. A crashed session can be closed via `close_session` to clean up the registry entry.

## 5. Data Model

### SessionState

Internal state object maintained per session. Not directly exposed to callers — the Session metadata type (defined in [proof-types.md](../doc/architecture/data-models/proof-types.md)) is the external representation.

| Field | Type | Constraint |
|-------|------|-----------|
| `session_id` | string | Required; unique opaque identifier |
| `file_path` | string | Required; absolute path to .v file |
| `proof_name` | string | Required; fully qualified proof name |
| `state` | enumeration | Required; one of: `active`, `crashed` |
| `current_step` | non-negative integer | Required; 0 = initial state |
| `total_steps` | non-negative integer or null | Required; null for interactively constructed proofs |
| `step_history` | ordered list of ProofState | Required; `step_history[0]` is always the initial state |
| `original_script` | ordered list of tactic strings | Required; may be empty |
| `coq_backend` | CoqBackend | Required when state = `active`; null when state = `crashed` |
| `coqtop_process` | async subprocess or null | Null until first `submit_command`; lazily spawned per §4.4.1 |
| `created_at` | timestamp | Required; ISO 8601; set at creation |
| `last_active_at` | timestamp | Required; ISO 8601; updated on every successful `lookup_session` |

MAINTAINS: `len(step_history) >= current_step + 1`. The step_history always contains at least the initial state and all states up to `current_step`. It may contain additional states beyond `current_step` if replay has materialized them.

## 6. Interface Contracts

### MCP Server → Session Manager

The MCP server calls session manager functions in-process. The session manager returns domain objects (ProofState, ProofTrace, PremiseAnnotation, Session) or structured errors. The MCP server is responsible for serializing these to JSON.

| Operation | Input | Output | Error codes |
|-----------|-------|--------|-------------|
| `create_session(file_path, proof_name)` | Two strings | `(session_id, ProofState)` | `FILE_NOT_FOUND`, `PROOF_NOT_FOUND` |
| `close_session(session_id)` | Session ID string | Confirmation | `SESSION_NOT_FOUND` |
| `list_sessions()` | None | `Session[]` | None |
| `observe_state(session_id)` | Session ID string | `ProofState` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED` |
| `get_state_at_step(session_id, step)` | Session ID + integer | `ProofState` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `STEP_OUT_OF_RANGE` |
| `extract_trace(session_id)` | Session ID string | `ProofTrace` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `STEP_OUT_OF_RANGE` |
| `submit_tactic(session_id, tactic)` | Session ID + string | `ProofState` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `TACTIC_ERROR` |
| `step_forward(session_id)` | Session ID string | `(tactic, ProofState)` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `PROOF_COMPLETE` |
| `step_backward(session_id)` | Session ID string | `ProofState` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `NO_PREVIOUS_STATE` |
| `submit_tactic_batch(session_id, tactics)` | Session ID + string list | `BatchResult[]` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED` |
| `get_premises(session_id)` | Session ID string | `PremiseAnnotation[]` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `STEP_OUT_OF_RANGE` |
| `get_step_premises(session_id, step)` | Session ID + integer | `PremiseAnnotation` | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `STEP_OUT_OF_RANGE` |
| `submit_command(session_id, command)` | Session ID + command string | `str` (merged Coq output) | `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED` |

Concurrency: the MCP server may call session manager functions concurrently from different tool handlers. The session manager serializes operations on the same session (§7.2).

### Session Manager → CoqBackend

Each session owns one CoqBackend instance. The interface is defined by the `CoqBackend` protocol:

| Operation | Input | Output | Error |
|-----------|-------|--------|-------|
| `load_file(path)` | File path string | None | Raises on file not found or Coq check failure |
| `position_at_proof(name)` | Proof name string | Initial ProofState | Raises on proof not found |
| `execute_tactic(tactic)` | Tactic string | ProofState | Raises on tactic failure (includes Coq error message) |
| `get_current_state()` | None | ProofState | None |
| `undo()` | None | None | Backend-dependent; may fail if undo is unsupported |
| `get_premises_at_step(step)` | Step index integer | List of raw premise references | Backend-dependent |
| `shutdown()` | None | None | Always succeeds (kills process) |

The CoqBackend abstracts the difference between coq-lsp and SerAPI. The session manager does not know which backend is in use.

## 7. State and Lifecycle

### 7.1 Session State Machine

| Current State | Event | Guard | Action | Next State |
|--------------|-------|-------|--------|------------|
| — | `create_session` | File exists, proof found | Spawn backend, read initial state, register | `active` |
| — | `create_session` | File not found | Return `FILE_NOT_FOUND` | — |
| — | `create_session` | Proof not found | Kill backend, return `PROOF_NOT_FOUND` | — |
| `active` | `close_session` | — | Kill backend and coqtop subprocess (if spawned), deregister | `closed` (terminal) |
| `active` | `submit_tactic` | Tactic succeeds | Truncate forward history, append state, increment step | `active` |
| `active` | `submit_tactic` | Tactic fails | Return `TACTIC_ERROR` | `active` |
| `active` | `step_forward` | `current_step < total_steps` | Execute next original tactic, append state, increment step | `active` |
| `active` | `step_forward` | `current_step >= total_steps` or no script | Return `PROOF_COMPLETE` | `active` |
| `active` | `step_backward` | `current_step > 0` | Decrement step, reset backend | `active` |
| `active` | `step_backward` | `current_step == 0` | Return `NO_PREVIOUS_STATE` | `active` |
| `active` | `observe_state` | — | Return cached state | `active` |
| `active` | `get_state_at_step` | `0 <= step <= total_steps` | Replay if needed, return state | `active` |
| `active` | `get_state_at_step` | Step out of range | Return `STEP_OUT_OF_RANGE` | `active` |
| `active` | `extract_trace` | Has original script | Materialize all states, return trace | `active` |
| `active` | `extract_trace` | No original script | Return `STEP_OUT_OF_RANGE` | `active` |
| `active` | `get_premises` | Has original script | Materialize + extract premises | `active` |
| `active` | `get_step_premises` | Valid step | Ensure stepped through, return premises | `active` |
| `active` | `get_step_premises` | Invalid step | Return `STEP_OUT_OF_RANGE` | `active` |
| `active` | `submit_tactic_batch` | — | Process sequentially per §4.3 | `active` |
| `active` | `submit_command` | coqtop not spawned | Spawn coqtop, load imports, send command, return output | `active` |
| `active` | `submit_command` | coqtop already spawned | Send command to existing coqtop, return output | `active` |
| `active` | timeout sweep | Idle > 30 min | Kill backend and coqtop subprocess (if spawned), deregister, log | `timed_out` (terminal) |
| `active` | backend crash | Process exited unexpectedly | Mark crashed, log | `crashed` |
| `crashed` | `close_session` | — | Deregister | `closed` (terminal) |
| `crashed` | Any operation except `close_session` | — | Return `BACKEND_CRASHED` | `crashed` |
| `crashed` | timeout sweep | Idle > 30 min | Deregister, log | `timed_out` (terminal) |

Terminal states (`closed`, `timed_out`) are not stored — the session is removed from the registry.

`list_sessions` operates on the registry, not on individual sessions. It does not appear in the per-session state machine. Active sessions are included in listings; crashed sessions are excluded.

### 7.2 Concurrency Model

The session registry shall support:

| Access pattern | Guarantee |
|---------------|-----------|
| Concurrent reads (list sessions, lookup by ID) | Safe without locking |
| Registry writes (create, close, timeout sweep) | Serialized |
| Per-session operations (submit tactic, submit command, step, observe) | Serialized per session; independent across sessions |

Two concurrent operations on the same session (e.g., `submit_tactic` and `step_backward`) shall not interleave. Per-session locking ensures serial execution.

Two operations on different sessions shall execute concurrently without interference.

## 8. Error Specification

### Error types

| Error code | Category | Condition |
|-----------|----------|-----------|
| `FILE_NOT_FOUND` | Input error | `create_session` with a file path that does not exist on disk |
| `PROOF_NOT_FOUND` | Input error | `create_session` with a proof name not found in the specified file |
| `SESSION_NOT_FOUND` | State error | Any session operation with an ID not present in the registry |
| `SESSION_EXPIRED` | State error | Any session operation on a session that was auto-closed by timeout |
| `BACKEND_CRASHED` | Dependency error | Any session operation (except `close_session`) on a session whose CoqBackend process exited unexpectedly |
| `TACTIC_ERROR` | Dependency error | `submit_tactic` when the Coq backend rejects the tactic; includes Coq's error message |
| `STEP_OUT_OF_RANGE` | Input error | `get_state_at_step` or `get_step_premises` with a step index outside [0, total_steps] (or [1, total_steps] for premises); also `extract_trace` or `get_premises` on a session with no original script |
| `NO_PREVIOUS_STATE` | State error | `step_backward` when `current_step == 0` |
| `PROOF_COMPLETE` | State error | `step_forward` when `current_step >= total_steps` or no original script exists |

### Edge cases

| Condition | Behavior |
|-----------|----------|
| `create_session` called with an empty `file_path` | MCP server validates before calling; session manager may assume non-empty |
| `close_session` on an already-closed session | `SESSION_NOT_FOUND` (closed sessions are removed from registry) |
| `close_session` on a crashed session | Deregisters the session; returns confirmation |
| `submit_tactic` on a completed proof (is_complete = true) | Tactic is forwarded to Coq; Coq will return an error since no goals remain |
| `step_forward` on a session that diverged from the original script via `submit_tactic` | If step_history was truncated and current_step < total_steps, step_forward uses the original script; this may fail if the diverged state is incompatible with the original tactic |
| `extract_trace` or `get_premises` on a session with no original script | `STEP_OUT_OF_RANGE` error; these operations require a complete original proof |
| Concurrent `submit_tactic` and `observe_state` on the same session | Serialized by per-session lock; observe_state waits until submit_tactic completes |
| `submit_tactic_batch` with an empty tactics list | Returns an empty results list |
| Backend process killed by OS (e.g., OOM) | Detected as unexpected exit → session marked as `crashed` |

## 9. Non-Functional Requirements

- The session manager shall support at least 3 concurrent sessions without state interference.
- Tactic submission round-trip latency (session manager overhead, excluding Coq execution time) shall be < 10 ms.
- Session timeout threshold: 30 minutes of inactivity. Implementation-defined sweep interval.
- Session IDs shall be opaque strings, unique within the server's lifetime. They need not be globally unique or persist across server restarts.

## 10. Examples

### Open session and submit tactics

```
(session_id, state0) = create_session("/path/to/Nat.v", "Nat.add_comm")
# state0: step_index=0, goals=[{type: "forall n m, n + m = m + n", ...}]

state1 = submit_tactic(session_id, "intros n m.")
# state1: step_index=1, goals=[{type: "n + m = m + n", hypotheses: [n:nat, m:nat]}]

state0_again = step_backward(session_id)
# state0_again: identical to state0, step_index=0

state1b = submit_tactic(session_id, "induction n.")
# Branching: step_history truncated after step 0, new branch starts
# state1b: step_index=1, goals=[base case, inductive case]

close_session(session_id)
# Backend process terminated, session removed
```

### Extract full trace

```
(session_id, _) = create_session("/path/to/Nat.v", "Nat.add_comm")
trace = extract_trace(session_id)
# trace.total_steps = 5
# trace.steps[0] = {step_index: 0, tactic: null, state: initial_state}
# trace.steps[1] = {step_index: 1, tactic: "intros n m.", state: state_after_intros}
# ...
# trace.steps[5] = {step_index: 5, tactic: "reflexivity.", state: {is_complete: true}}
```

### Premise extraction

```
(session_id, _) = create_session("/path/to/Nat.v", "Nat.add_comm")
premises = get_premises(session_id)
# premises[0] = {step_index: 1, tactic: "intros n m.", premises: []}
# premises[2] = {step_index: 3, tactic: "rewrite Nat.add_succ_r.",
#                premises: [{name: "Coq.Arith.PeanoNat.Nat.add_succ_r", kind: "lemma"}]}
```

### Timeout scenario

```
(session_id, _) = create_session("/path/to/file.v", "my_proof")
# ... 30+ minutes of inactivity ...
observe_state(session_id)
# Error: SESSION_EXPIRED
```

### Crash scenario

```
(session_id, _) = create_session("/path/to/file.v", "my_proof")
# Backend process crashes (e.g., OOM kill)
submit_tactic(session_id, "simpl.")
# Error: BACKEND_CRASHED
close_session(session_id)
# Cleanup: deregisters the crashed session entry
```

## 11. Language-Specific Notes (Python)

- Use `asyncio.subprocess` for CoqBackend process management.
- Use `uuid.uuid4().hex` for session ID generation.
- Use `asyncio.Lock` per session for per-session serialization.
- Use `dict` for the session registry; guard writes with a registry-level `asyncio.Lock`.
- Use `asyncio.create_task` for the background timeout sweep loop.
- SessionState can be a mutable dataclass holding the CoqBackend, step_history list, and metadata.
- Package location: `src/poule/session/`.
