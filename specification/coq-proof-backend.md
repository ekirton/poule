# Coq Proof Backend

Per-session Coq process wrapper providing bidirectional, stateful proof interaction.

**Architecture**: [proof-session.md](../doc/architecture/proof-session.md) (CoqBackend Interface, Process Isolation, Crash Detection), [component-boundaries.md](../doc/architecture/component-boundaries.md) (Proof Session Manager → Coq Backend Processes)
**Data models**: [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the `CoqBackend` protocol and the `create_coq_backend` factory function that the Proof Session Manager uses to spawn and communicate with per-session Coq processes. The backend abstracts the difference between coq-lsp and SerAPI, presenting a uniform async interface for file loading, proof positioning, tactic execution, state observation, undo, premise extraction, and process shutdown.

## 2. Scope

**In scope**: `CoqBackend` protocol definition, `create_coq_backend` factory, process spawning and communication, `.v` file loading and proof positioning, tactic execution and state translation, undo mechanism, premise extraction, process shutdown and crash detection, error translation.

**Out of scope**: Session registry and lifecycle management (owned by proof-session), proof state serialization (owned by proof-serialization), MCP protocol handling (owned by mcp-server), extraction of declarations from `.vo` files (owned by extraction — separate backend with a different interface), vernacular command output capture (see §4.5).

## 3. Definitions

| Term | Definition |
|------|-----------|
| CoqBackend | An async protocol abstracting a single coq-lsp or SerAPI process for interactive proof exploration |
| Backend factory | An async callable `(file_path: str) -> CoqBackend` that spawns a new backend process |
| Proof positioning | Navigating a loaded `.v` file to the start of a named proof, making its initial state observable |
| Original script | The sequence of tactic strings comprising a completed proof's body, extracted during positioning |
| Raw premise reference | A backend-dependent representation of a premise used by a tactic, before classification into the `Premise` type |

## 4. Behavioral Requirements

### 4.1 CoqBackend Protocol

The `CoqBackend` protocol defines 7 async operations. All operations except `shutdown` may raise exceptions on failure. Every `CoqBackend` instance is bound to a single Coq process — it is not reusable across processes.

#### load_file(file_path)

- REQUIRES: `file_path` is a non-empty string pointing to a `.v` source file.
- ENSURES: The backend process loads and checks the file. After successful return, the file's definitions and proofs are accessible for positioning. The backend retains the file context for the lifetime of the process.
- On file not found or unreadable: raises `FileNotFoundError` or `OSError`.
- On Coq check failure (syntax error, dependency missing): raises an exception with the Coq error message.

> **Given** a valid `.v` file with no Coq errors
> **When** `load_file(path)` is called
> **Then** the call returns successfully and proofs in the file are available for positioning

> **Given** a path to a file that does not exist
> **When** `load_file(path)` is called
> **Then** `FileNotFoundError` is raised

> **Given** a `.v` file with a syntax error
> **When** `load_file(path)` is called
> **Then** an exception is raised containing the Coq error diagnostic

#### position_at_proof(proof_name)

- REQUIRES: `load_file` has been called successfully. `proof_name` is a non-empty string.
- ENSURES: The backend navigates to the start of the named proof. Returns a `ProofState` representing the initial state (step 0) — the state immediately after the proof command (`Theorem`, `Lemma`, `Proof`, etc.) but before any tactic. If the proof has an existing tactic script, the backend makes the original script accessible via the `original_script` attribute.
- On proof not found: raises `ValueError`, `KeyError`, or `LookupError`.

The returned `ProofState` shall have:
- `schema_version`: the current schema version (1)
- `session_id`: empty string (the session manager stamps the real session ID)
- `step_index`: 0
- `is_complete`: false (the proof has at least one goal at step 0)
- `focused_goal_index`: 0 (the first goal is focused)
- `goals`: at least one Goal with the proof statement as its type

> **Given** a loaded file containing `Lemma add_comm : forall n m, n + m = m + n.`
> **When** `position_at_proof("add_comm")` is called
> **Then** the returned ProofState has step_index=0, is_complete=false, and goals[0].type contains "forall n m, n + m = m + n" (or the Coq-normalized form)

> **Given** a loaded file that does not contain a proof named "nonexistent"
> **When** `position_at_proof("nonexistent")` is called
> **Then** a `ValueError`, `KeyError`, or `LookupError` is raised

#### original_script (attribute)

- REQUIRES: `position_at_proof` has been called successfully.
- ENSURES: A `list[str]` containing the tactic strings from the proof's existing script, in order. Empty list if the proof has no script (e.g., opened interactively without a body).
- Each string is a single tactic command as it appears in the source, including the trailing period (e.g., `"intros n m."`).
- Tactic boundaries shall be derived from the coq-lsp document model (`coq/getDocument` sentence ranges) when available. The backend queries `coq/getDocument` for the loaded file, identifies spans within the proof body (between the `Proof.` keyword and the `Qed`/`Defined`/`Admitted` terminator), and extracts the source text for each sentence span. This produces exact tactic boundaries as parsed by coq-lsp's Fleche engine — handling bullets (`-`, `+`, `*`), braces (`{`, `}`), comments containing periods, numeric literals, ssreflect tactic chains, and all other Coq syntax that a regex-based splitter cannot reliably handle.
- When `coq/getDocument` is unavailable or returns no spans (e.g., a non-Fleche backend), the backend shall fall back to regex-based sentence splitting as a degraded mode.

> **Given** a proof with body `intros n m. ring.`
> **When** `original_script` is accessed after `position_at_proof`
> **Then** it returns `["intros n m.", "ring."]`

> **Given** a proof with no existing body (just `Proof.` with no tactics)
> **When** `original_script` is accessed
> **Then** it returns `[]`

> **Given** a proof with body `intros n. - simpl. ring. - reflexivity.` (using bullet markers)
> **When** `original_script` is accessed after `position_at_proof`
> **Then** each bullet marker and its tactic are correctly split as separate sentences, matching coq-lsp's sentence segmentation

> **Given** a proof without an explicit `Proof.` keyword where tactics begin directly after the statement (e.g., `Lemma foo : P. intros. auto. Qed.`)
> **When** `original_script` is accessed after `position_at_proof`
> **Then** it returns the tactic list (same as if `Proof.` were present)

#### original_states (attribute)

- REQUIRES: `position_at_proof` has been called successfully.
- ENSURES: A `list` of backend state tokens, one per successfully replayed step of the original script (index 0 = initial state before any tactic, index k = state after tactic k). During `position_at_proof`, the backend replays the original script via `petanque/run` to build this state history. If a tactic fails at step k, the list contains states 0..k-1 (the successfully replayed prefix). These state tokens are valid for subsequent calls to `petanque/goals` and `petanque/premises` without requiring a second replay.
- The session manager may use `original_states` to extract proof states and premises without invoking `execute_tactic`, avoiding redundant replay of the original proof script.

> **Given** a proof with 5 tactics that all replay successfully
> **When** `original_states` is accessed after `position_at_proof`
> **Then** it contains 6 state tokens (initial + one per tactic)

> **Given** a proof with 5 tactics where tactic 3 fails during replay
> **When** `original_states` is accessed after `position_at_proof`
> **Then** it contains 3 state tokens (initial + states after tactics 1 and 2)

#### execute_tactic(tactic)

- REQUIRES: A proof is active (either via `position_at_proof` or a previous `execute_tactic` that did not complete the proof). `tactic` is a non-empty string.
- ENSURES: The tactic is sent to the Coq process for execution. On success, returns a `ProofState` reflecting the state after the tactic. On Coq-level failure (invalid tactic, type mismatch, etc.), raises an exception containing the Coq error message; the backend's internal state is unchanged (the failed tactic is not applied).

The returned `ProofState` shall have:
- `step_index`: the value the session manager will assign (the backend may return 0; the session manager overwrites this)
- `is_complete`: true if no goals remain after the tactic
- `focused_goal_index`: the index of the focused goal, or null if complete
- `goals`: the updated goal list

> **Given** a proof at step 0 with goal `forall n m, n + m = m + n`
> **When** `execute_tactic("intros n m.")` succeeds
> **Then** the returned ProofState has goals with hypotheses `n : nat` and `m : nat`, and the goal type is `n + m = m + n`

> **Given** a proof at step 1
> **When** `execute_tactic("invalid_not_a_tactic.")` is called and Coq rejects it
> **Then** an exception is raised with the Coq error message, and the backend state remains at step 1

> **Given** a proof with one remaining goal
> **When** `execute_tactic("reflexivity.")` closes the last goal
> **Then** the returned ProofState has `is_complete = true`, `focused_goal_index = null`, and `goals = []`

#### undo()

- REQUIRES: A proof is active and at least one tactic has been executed.
- ENSURES: The last applied tactic is undone. The backend's internal state reverts to the state before the last tactic. The mechanism is backend-dependent (coq-lsp may replay from the start; SerAPI may use `Undo 1.`).
- On failure (undo unsupported or backend error): may raise an exception. The session manager treats undo failure as best-effort (per architecture: "Backend-dependent; best-effort").

> **Given** a proof at step 3 after executing tactics T1, T2, T3
> **When** `undo()` is called
> **Then** the backend state is equivalent to the state after T1 and T2 (step 2)

#### get_premises_at_step(step)

- REQUIRES: A proof is active. `step` is a positive integer representing a tactic step index (1-based, corresponding to the tactic at `original_script[step - 1]`). The proof has been executed through at least step `step`.
- ENSURES: Returns a list of raw premise reference dicts. Each dict contains at minimum `{"name": str, "kind": str}` where `name` is the fully qualified canonical name of the premise and `kind` is one of `"lemma"`, `"hypothesis"`, `"constructor"`, `"definition"`.
- The extraction mechanism is backend-dependent:
  - **coq-lsp**: Query proof state annotations or document model at the tactic position
  - **SerAPI**: Inspect the `Environ` and tactic trace after the step

> **Given** a proof where step 2 uses `rewrite Nat.add_comm.`
> **When** `get_premises_at_step(2)` is called
> **Then** the returned list includes `{"name": "Coq.Arith.PeanoNat.Nat.add_comm", "kind": "lemma"}`

> **Given** a proof where step 1 uses `intros n m.` (no external premises)
> **When** `get_premises_at_step(1)` is called
> **Then** the returned list is empty

#### shutdown()

- REQUIRES: None (may be called at any time, including on a crashed or already-shut-down backend).
- ENSURES: The Coq process is terminated. All associated resources (file handles, pipes, memory) are released. After shutdown, no other operation may be called. Shutdown shall not raise exceptions — it always succeeds (kills the process if necessary).

> **Given** an active backend with a running Coq process
> **When** `shutdown()` is called
> **Then** the process is terminated and resources are released

> **Given** a backend whose process has already exited (crashed)
> **When** `shutdown()` is called
> **Then** the call succeeds without error (idempotent cleanup)

### 4.2 Backend Factory

The system shall provide an async factory function:

#### create_coq_backend(file_path, watchdog_timeout=None)

- REQUIRES: `file_path` is a non-empty string. `watchdog_timeout` is a positive float (seconds) or `None`.
- ENSURES: Spawns a new Coq process (coq-lsp or SerAPI, determined by configuration or availability). Returns a `CoqBackend` instance connected to that process with the given `watchdog_timeout` configured. The process is ready for `load_file` to be called.
- On process spawn failure (coq-lsp not installed, binary not found): raises an exception with a descriptive message.

The factory is the only way to create `CoqBackend` instances. The session manager receives it as a constructor parameter, enabling test injection of mock backends.

> **Given** coq-lsp is installed and available on PATH
> **When** `create_coq_backend("/path/to/file.v")` is called
> **Then** a CoqBackend instance is returned with a running coq-lsp process

> **Given** coq-lsp is installed and a watchdog_timeout of 600
> **When** `create_coq_backend("/path/to/file.v", watchdog_timeout=600)` is called
> **Then** a CoqBackend instance is returned with watchdog_timeout=600 configured

> **Given** neither coq-lsp nor SerAPI is installed
> **When** `create_coq_backend("/path/to/file.v")` is called
> **Then** an exception is raised indicating no Coq backend is available

### 4.3 ProofState Translation

The backend shall translate Coq's internal proof state representation into the `ProofState` type defined in [proof-types.md](../doc/architecture/data-models/proof-types.md).

| Coq concept | ProofState field |
|-------------|-----------------|
| Proof obligation / subgoal | `Goal` object |
| Goal conclusion type | `Goal.type` (pretty-printed as a Coq expression string) |
| Local context entry (variable or assumption) | `Hypothesis` object |
| Let-binding in local context | `Hypothesis` with `body` set to the definition term |
| Focused goal (selected subgoal) | `focused_goal_index` |
| No remaining goals | `is_complete = true`, `goals = []` |

The backend shall use Coq's pretty-printer for type and body strings. The same Coq version on the same input shall produce identical strings (determinism requirement from proof-serialization spec §4.13).

Goals shall be ordered by their index as Coq presents them. Hypotheses within each goal shall be ordered as Coq presents them in the local context (typically oldest-first).

### 4.4 Premise Classification

When `get_premises_at_step` extracts raw premise references, the backend shall classify each premise:

| Source in the Coq environment | Assigned `kind` |
|-------------------------------|----------------|
| Previously proved lemma or theorem | `"lemma"` |
| Local hypothesis in the proof context | `"hypothesis"` |
| Inductive type constructor | `"constructor"` |
| Definition (unfolded or referenced) | `"definition"` |

Classification shall use the Coq environment's declaration metadata. When a local name shadows a global name, the premise shall be classified based on what Coq actually resolved — determined by Coq's scoping rules, not by name lookup in the global environment.

> **Given** a tactic `apply H.` where `H` is a local hypothesis
> **When** premises are extracted for that step
> **Then** the premise has `kind = "hypothesis"`

> **Given** a tactic `apply Nat.add_comm.` where `Nat.add_comm` is a global lemma
> **When** premises are extracted for that step
> **Then** the premise has `name = "Coq.Arith.PeanoNat.Nat.add_comm"` and `kind = "lemma"`

> **Given** a local hypothesis named `Nat.add_comm` that shadows the global lemma
> **When** `apply Nat.add_comm.` is used and Coq resolves it to the local hypothesis
> **Then** the premise has `kind = "hypothesis"` (matches what Coq resolved, not the global name)

### 4.5 Vernacular Output Capture Limitation

The `CoqBackend` protocol does not include a vernacular command execution operation. The coq-lsp backend communicates via the LSP JSON-RPC protocol, which does not expose the output of successful vernacular introspection commands (Print, Check, About, Locate, Search, Compute, Eval):

| coq-lsp mechanism | What it returns | Captures vernacular output? |
|---|---|---|
| LSP diagnostics | Errors and warnings only | No — successful queries emit no diagnostic |
| `textDocument/hover` | Type information for identifiers at cursor position | No — returns hover data, not command output |
| `coq/getDocument` | Document span ranges | No — returns structural metadata without content |

This is an inherent limitation of the LSP protocol as implemented by coq-lsp, not a bug.

The session manager is responsible for vernacular output capture. When a session requires vernacular command execution (via `submit_command`), the session manager shall use a coqtop subprocess rather than the session's CoqBackend. See [proof-session.md](proof-session.md) §4.4 for the coqtop subprocess lifecycle and routing.

> **Given** a coq-lsp backend with a loaded file
> **When** a `Print nat.` command is executed via LSP diagnostics
> **Then** the diagnostics collection is empty (no error occurred, but no output is captured)

## 5. Data Model

The `CoqBackend` protocol has no persistent data model — it is a stateful process wrapper. Its inputs and outputs use the types defined in [proof-types.md](../doc/architecture/data-models/proof-types.md):

| Operation | Returns |
|-----------|---------|
| `position_at_proof` | `ProofState` |
| `execute_tactic` | `ProofState` |
| `get_premises_at_step` | `list[dict]` with `{"name": str, "kind": str}` entries |

The `original_script` attribute is a `list[str]` — plain tactic strings, not a domain type.

## 6. Interface Contracts

### Session Manager → CoqBackend

The session manager is the sole consumer of the `CoqBackend` protocol. The contract is defined in [proof-session.md](../doc/architecture/proof-session.md) and [specification/proof-session.md](proof-session.md) §6.

| Operation | Input | Output | Error |
|-----------|-------|--------|-------|
| `load_file(path)` | File path string | None | `FileNotFoundError`, `OSError`, or Coq check error |
| `position_at_proof(name)` | Proof name string | `ProofState` (initial state) | `ValueError`, `KeyError`, `LookupError` |
| `execute_tactic(tactic)` | Tactic string | `ProofState` (new state) | Exception with Coq error message |
| `get_current_state()` | None | `ProofState` | None |
| `undo()` | None | None | Backend-dependent; may fail |
| `get_premises_at_step(step)` | Step index integer | `list[dict]` of raw premise references | Backend-dependent |
| `shutdown()` | None | None | Never raises |

Concurrency: each `CoqBackend` instance is used by exactly one session. The session manager's per-session lock ensures that operations on a single backend are serialized. No concurrent calls to the same backend instance.

### CoqBackend → Coq Process

| Property | Value |
|----------|-------|
| Transport | stdin/stdout pipes via `asyncio.subprocess` |
| Protocol | coq-lsp: LSP JSON-RPC (Content-Length framed); SerAPI: S-expression protocol |
| Direction | Bidirectional, stateful |
| Cardinality | One Coq process per CoqBackend instance |
| Lifecycle | Process spawned by `create_coq_backend`, terminated by `shutdown` |

## 7. State and Lifecycle

### 7.1 Backend State Machine

| Current State | Event | Guard | Action | Next State |
|--------------|-------|-------|--------|------------|
| — | `create_coq_backend` | Coq binary available | Spawn process, initialize protocol | `spawned` |
| — | `create_coq_backend` | Coq binary not found | Raise exception | — |
| `spawned` | `load_file` | File exists, Coq accepts | Send file to process | `file_loaded` |
| `spawned` | `load_file` | File error | Raise exception | `spawned` |
| `file_loaded` | `position_at_proof` | Proof found | Navigate to proof start, extract script | `proof_active` |
| `file_loaded` | `position_at_proof` | Proof not found | Raise exception | `file_loaded` |
| `proof_active` | `execute_tactic` | Tactic succeeds | Apply tactic, return new state | `proof_active` |
| `proof_active` | `execute_tactic` | Tactic fails | Raise exception, state unchanged | `proof_active` |
| `proof_active` | `execute_tactic` | Tactic closes all goals | Apply tactic, return complete state | `proof_complete` |
| `proof_active` | `undo` | Has previous state | Revert to previous state | `proof_active` |
| `proof_active` | `get_premises_at_step` | Valid step | Query and return premises | `proof_active` |
| `proof_complete` | `undo` | Has previous state | Revert to previous state | `proof_active` |
| `proof_complete` | `get_premises_at_step` | Valid step | Query and return premises | `proof_complete` |
| Any | `shutdown` | — | Kill process, release resources | `shut_down` (terminal) |
| Any | Process exits unexpectedly | — | Mark as crashed | `crashed` (terminal) |
| `crashed` | `shutdown` | — | No-op (process already gone) | `shut_down` (terminal) |
| `crashed` | Any other operation | — | Raise exception | `crashed` |

### 7.2 Process Lifecycle

1. **Spawn**: `create_coq_backend` starts the Coq process and completes the protocol initialization handshake (LSP `initialize` for coq-lsp, or SerAPI version query).
2. **Use**: The session manager calls `load_file`, `position_at_proof`, then any combination of `execute_tactic`, `undo`, `get_premises_at_step`, and `get_current_state`.
3. **Shutdown**: `shutdown` sends a termination signal and waits for the process to exit. If the process does not exit within a timeout (implementation-defined, recommended 5 seconds), it is forcefully killed (`SIGKILL`).

### 7.3 Crash Detection

The backend shall monitor its Coq process. If the process exits unexpectedly (exit code != 0, or signal-terminated):

1. The backend transitions to `crashed` state.
2. Any subsequent operation (except `shutdown`) raises an exception.
3. `shutdown` on a crashed backend is a no-op that succeeds.

The session manager detects the crash when it next calls a backend operation, and marks the session as `BACKEND_CRASHED`.

### 7.4 Liveness Watchdog

When `watchdog_timeout` is configured (non-null), the backend shall wrap each I/O read in `_read_message` with a per-read inactivity timeout. If `watchdog_timeout` seconds elapse with no data received on the backend's stdout pipe, the read shall be cancelled and a `ConnectionError` raised with the message `"coq-lsp unresponsive for {watchdog_timeout}s"`.

The watchdog timer resets on every successful data read. A tactic that takes several minutes to compute but then produces a response in one message is not affected — the watchdog only fires during complete silence on the pipe.

When `watchdog_timeout` is `None`, reads block indefinitely (the default for interactive MCP sessions where the user controls timing).

The `ConnectionError` from a watchdog kill is indistinguishable from a genuine backend crash (EOF on pipe). Both propagate through the same error handling path: `execute_tactic` raises → `extract_trace` catches and returns a partial `ProofTrace` → the campaign emits a `PartialExtractionRecord` or `ExtractionError`.

> **Given** a backend with `watchdog_timeout=600` and a coq-lsp process that has stopped producing output
> **When** 600 seconds of inactivity pass during a `_read_message` call
> **Then** a `ConnectionError` is raised with message containing "unresponsive"

> **Given** a backend with `watchdog_timeout=600` and a tactic that takes 300 seconds to compute
> **When** the tactic completes and coq-lsp responds
> **Then** the response is received normally (the watchdog did not fire because the 600s window was not exceeded)

> **Given** a backend with `watchdog_timeout=None`
> **When** the coq-lsp process stops producing output
> **Then** the read blocks indefinitely (no watchdog)

## 8. Error Specification

### Error types

| Condition | Exception | Category |
|-----------|-----------|----------|
| File does not exist or is unreadable | `FileNotFoundError` / `OSError` | Input error |
| File has Coq syntax or dependency errors | Backend-specific exception with Coq diagnostic | Dependency error |
| Proof name not found in loaded file | `ValueError` / `KeyError` / `LookupError` | Input error |
| Tactic rejected by Coq | Exception with Coq error message | Dependency error |
| Undo fails (unsupported or backend error) | Exception (backend-dependent) | Dependency error |
| Coq process not found on PATH | `FileNotFoundError` / `OSError` | Dependency error |
| Coq process crashes during operation | Exception (detected by EOF on pipe or nonzero exit) | Dependency error |
| Coq process unresponsive (watchdog) | `ConnectionError` (detected by inactivity timeout on pipe) | Dependency error |
| Operation called after shutdown | Undefined behavior (caller's obligation to not call) | Invariant violation |

### Edge cases

| Condition | Behavior |
|-----------|----------|
| `load_file` called twice on same backend | Backend-dependent; may reload or raise. Session manager calls it exactly once. |
| `position_at_proof` called twice | Backend-dependent. Session manager calls it exactly once per session. |
| `execute_tactic` on a completed proof (no goals) | Forwards to Coq; Coq returns an error ("No focused proof") |
| `undo` at step 0 (before any tactic) | Backend-dependent; may fail. Session manager guards against this. |
| `get_premises_at_step` for a step not yet executed | Undefined. Session manager ensures materialization before calling. |
| `shutdown` called multiple times | Idempotent; second call is a no-op |
| Process killed by OS (OOM, SIGKILL) | Detected as crash; backend enters `crashed` state |
| Very large `.v` file (> 10K lines) | No specific limit; bounded by Coq process memory. Session manager does not impose file size limits. |

## 9. Non-Functional Requirements

- Process spawn time (factory call to ready state): < 5 seconds on a system with Coq installed.
- Tactic execution overhead (backend wrapper, excluding Coq execution time): < 5 ms per tactic.
- Shutdown shall complete within 10 seconds (5s graceful + 5s forced kill).
- Memory: each backend process consumes memory proportional to the Coq environment loaded. Typical: 50–200 MB per process for standard library proofs.

## 10. Examples

### Full lifecycle

```
backend = await create_coq_backend("/path/to/arith.v")
await backend.load_file("/path/to/arith.v")
initial_state = await backend.position_at_proof("add_comm")
# initial_state.goals[0].type ≈ "forall n m, n + m = m + n"
# backend.original_script = ["intros n m.", "ring."]

state1 = await backend.execute_tactic("intros n m.")
# state1.goals[0].type ≈ "n + m = m + n"
# state1.goals[0].hypotheses = [Hypothesis("n", "nat"), Hypothesis("m", "nat")]

state2 = await backend.execute_tactic("ring.")
# state2.is_complete = True, state2.goals = []

premises = await backend.get_premises_at_step(2)
# premises = [{"name": "Coq.setoid_ring.Ring_theory.ring_theory", "kind": "lemma"}]

await backend.shutdown()
# Process terminated, resources released
```

### Error recovery

```
backend = await create_coq_backend("/path/to/file.v")
await backend.load_file("/path/to/file.v")
await backend.position_at_proof("my_proof")

try:
    await backend.execute_tactic("bad_tactic.")
except Exception as e:
    # e contains Coq error message
    # Backend state unchanged — can continue with a valid tactic
    state = await backend.execute_tactic("intros.")

await backend.shutdown()
```

### Crash scenario

```
backend = await create_coq_backend("/path/to/file.v")
await backend.load_file("/path/to/file.v")
await backend.position_at_proof("my_proof")

# ... Coq process is killed by OS (OOM) ...

try:
    await backend.execute_tactic("intros.")
except Exception:
    # Backend detected process crash
    pass

await backend.shutdown()  # Succeeds (idempotent)
```

## 11. Language-Specific Notes (Python)

- Define `CoqBackend` as a `typing.Protocol` class with async methods.
- Use `asyncio.create_subprocess_exec` for process spawning.
- Use `asyncio.StreamReader` / `asyncio.StreamWriter` for stdin/stdout pipe communication.
- For coq-lsp: reuse the Content-Length framing and JSON-RPC message format from the extraction backend (`poule.extraction.backends.coqlsp_backend`), but implement the proof-specific LSP interactions (document open with tactic stepping, `proof/goals` queries).
- For SerAPI: use S-expression parsing for responses.
- The `create_coq_backend` factory should attempt coq-lsp first, falling back to SerAPI if coq-lsp is not available.
- Package location: `src/poule/session/backend.py`.
- The `_get_backend_factory` function in `poule.cli.commands` imports `create_coq_backend` from this module.
