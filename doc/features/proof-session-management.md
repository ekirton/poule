# Proof Session Management

Interactive proof sessions that allow external tools to observe and interact with Coq proof states over time. Each session encapsulates a single proof within a single .v file, maintaining independent state from other sessions.

---

## Problem

Coq's existing external interfaces (SerAPI, coq-lsp) are designed for single-client IDE workflows. There is no protocol for multiple independent tools to interact with proof states concurrently. A tool builder who wants to explore two alternative proof strategies in parallel must manually manage separate processes and reconstruct state from scratch.

## Solution

A session-based interaction model where each session:
- Is opened by specifying a .v file and a named proof
- Returns a unique session ID used for all subsequent operations
- Maintains its own proof state, tactic history, and step position
- Is explicitly closed when no longer needed, or auto-closed after inactivity

Multiple sessions can be open simultaneously, including on the same proof — each with fully independent state.

## Session Lifecycle

### Opening

A session is opened by specifying a .v file path and the name of a proof within it. The server loads the file, positions at the proof, and returns the initial proof state along with a session ID. If the file does not exist or the proof name is not found, a structured error is returned immediately.

### Active Use

While active, a session accepts tactic submissions, state observations, step navigation, and trace extraction. Each operation references the session by its ID. The session tracks the full tactic history and allows stepping forward and backward through it.

### Closing

A session is explicitly closed by the client, releasing all resources (Coq backend processes, in-memory state). After closing, any operation referencing that session ID returns a structured error.

### Listing

Clients can enumerate all active sessions to discover their metadata: session ID, file path, proof name, current step index, and creation timestamp.

## Concurrency Model

Sessions are fully isolated. Actions in one session never affect the state of another, even when multiple sessions are open on the same proof in the same file. This isolation extends to error conditions — a crash in one session's Coq backend does not affect other sessions.

The target is at least 3 concurrent sessions without state interference.

## Resilience

### Session Timeout

Sessions that receive no tool calls for 30 minutes are automatically closed and their resources released. This prevents abandoned sessions from leaking memory or processes in long-running server deployments. The timeout duration is a server-side default, not configurable per-session in the initial release.

### Backend Crash Isolation

Each session's Coq backend process is isolated. If one crashes — due to a pathological tactic, out-of-memory, or a Coq bug — the failure is contained to that session. Other sessions continue normally. The crashed session returns a structured error on the next tool call referencing it.

## Design Rationale

### Why session-based rather than stateless

Coq proof interaction is inherently stateful — each tactic changes the proof state, and stepping backward requires remembering the history. A stateless API would force clients to replay the full tactic sequence on every request, which is too slow for interactive use (tactic execution takes 10s–100s of milliseconds each).

### Why explicit session IDs rather than implicit state

Explicit session IDs allow clients to manage multiple concurrent proof explorations and to hand off session references between components. An implicit "current session" model would not support the concurrent use case that AI researchers need for parallel proof search.

### Why auto-close on timeout rather than relying on explicit close

Tools crash. Network connections drop. AI research scripts abort. Without a timeout, every abnormal termination would leak a Coq backend process. The 30-minute timeout is generous enough that no normal interactive use will hit it, but short enough to bound resource leakage.

### Why crash isolation per session

The primary users (AI researchers running parallel proof search) will submit speculative, potentially pathological tactics. A crash in one exploration branch must not invalidate other branches. Process-level isolation is the simplest mechanism that provides this guarantee.

## Acceptance Criteria

### Open a Proof Session

**Priority:** P0
**Stability:** Stable

- GIVEN a valid .v file and a named proof within it WHEN the open-session tool is called THEN a new session is created and returns a unique session ID and the initial proof state
- GIVEN a .v file that does not exist WHEN the open-session tool is called THEN a structured error is returned indicating the file was not found
- GIVEN a valid .v file but a nonexistent proof name WHEN the open-session tool is called THEN a structured error is returned indicating the proof was not found
- GIVEN a valid session is opened WHEN the initial proof state is returned THEN it includes goals, hypotheses, and local context in the version-stable JSON format

### Close a Proof Session

**Priority:** P0
**Stability:** Stable

- GIVEN an active session WHEN the close-session tool is called with the session ID THEN the session is terminated and all associated resources are released
- GIVEN a closed or nonexistent session ID WHEN the close-session tool is called THEN a structured error is returned indicating the session was not found
- GIVEN a session is closed WHEN any tool is called with that session ID THEN a structured error is returned indicating the session is no longer active

### List Active Sessions

**Priority:** P0
**Stability:** Stable

- GIVEN one or more active sessions WHEN the list-sessions tool is called THEN it returns a list of session objects each including session ID, file path, proof name, current step index, and creation timestamp
- GIVEN no active sessions WHEN the list-sessions tool is called THEN it returns an empty list

### Concurrent Session Isolation

**Priority:** P0
**Stability:** Stable

- GIVEN three or more concurrent sessions WHEN a tactic is submitted in one session THEN the proof states of all other sessions remain unchanged
- GIVEN three or more concurrent sessions WHEN one session is closed THEN all other sessions continue to operate normally
- GIVEN concurrent sessions on the same proof WHEN different tactics are submitted in each THEN each session reflects only its own tactic history

### Session Timeout and Cleanup

**Priority:** P0
**Stability:** Draft

- GIVEN an active session with no tool calls for 30 minutes WHEN the timeout period elapses THEN the session is automatically closed and resources are released
- GIVEN an auto-closed session WHEN any tool is called with that session ID THEN a structured error is returned indicating the session timed out

### Backend Process Crash Recovery

**Priority:** P0
**Stability:** Draft

- GIVEN multiple concurrent sessions WHEN the Coq backend process for one session crashes THEN all other sessions continue to operate normally
- GIVEN a crashed session WHEN any tool is called with that session ID THEN a structured error is returned indicating the backend process crashed
