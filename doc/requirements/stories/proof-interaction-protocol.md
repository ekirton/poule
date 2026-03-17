# User Stories: Proof Interaction Protocol

Derived from [doc/requirements/proof-interaction-protocol.md](../proof-interaction-protocol.md).

---

## Epic 1: Session Management

### 1.1 Open a Proof Session

**As a** tool builder or AI researcher,
**I want to** start an interactive proof session by specifying a .v file and proof name,
**so that** I can programmatically observe and interact with the proof state.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid .v file and a named proof within it WHEN the open-session tool is called THEN a new session is created and returns a unique session ID and the initial proof state
- GIVEN a .v file that does not exist WHEN the open-session tool is called THEN a structured error is returned indicating the file was not found
- GIVEN a valid .v file but a nonexistent proof name WHEN the open-session tool is called THEN a structured error is returned indicating the proof was not found
- GIVEN a valid session is opened WHEN the initial proof state is returned THEN it includes goals, hypotheses, and local context in the version-stable JSON format

### 1.2 Close a Proof Session

**As a** tool builder,
**I want to** terminate a proof session and release all associated resources,
**so that** long-running tools do not leak memory or processes.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active session WHEN the close-session tool is called with the session ID THEN the session is terminated and all associated resources are released
- GIVEN a closed or nonexistent session ID WHEN the close-session tool is called THEN a structured error is returned indicating the session was not found
- GIVEN a session is closed WHEN any tool is called with that session ID THEN a structured error is returned indicating the session is no longer active

### 1.3 List Active Sessions

**As a** tool builder managing multiple proof explorations,
**I want to** enumerate all open sessions with their metadata,
**so that** I can track and manage concurrent proof interactions.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN one or more active sessions WHEN the list-sessions tool is called THEN it returns a list of session objects each including session ID, file path, proof name, current step index, and creation timestamp
- GIVEN no active sessions WHEN the list-sessions tool is called THEN it returns an empty list

### 1.4 Concurrent Session Isolation

**As an** AI researcher running parallel proof explorations,
**I want** each session to maintain independent state,
**so that** actions in one session do not affect another.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN three or more concurrent sessions WHEN a tactic is submitted in one session THEN the proof states of all other sessions remain unchanged
- GIVEN three or more concurrent sessions WHEN one session is closed THEN all other sessions continue to operate normally
- GIVEN concurrent sessions on the same proof WHEN different tactics are submitted in each THEN each session reflects only its own tactic history

---

## Epic 2: Proof State Observation

### 2.1 Observe Current Proof State

**As a** tool builder or AI researcher,
**I want to** observe the current proof state of an active session,
**so that** I can inspect goals, hypotheses, and context at the current step.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active session WHEN the observe-state tool is called THEN it returns the current proof state including all open goals, hypotheses, the focused goal, and the current step index
- GIVEN a proof state with multiple goals WHEN the state is returned THEN each goal includes its index, type, and associated hypotheses
- GIVEN a proof state WHEN the state is serialized THEN it conforms to the version-stable JSON schema with a declared schema version field

### 2.2 Get Proof State at a Specific Step

**As an** AI researcher analyzing proof structure,
**I want to** access the proof state at any step k in a completed proof,
**so that** I can perform random-access analysis of proof evolution.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a session with a completed proof of N tactic steps WHEN the get-state-at-step tool is called with step k (0 ≤ k ≤ N) THEN it returns the proof state after the k-th tactic (step 0 = initial state)
- GIVEN a step index outside the valid range WHEN the get-state-at-step tool is called THEN a structured error is returned indicating the step is out of range

### 2.3 Extract Full Proof Trace

**As an** AI researcher building training datasets,
**I want to** extract the complete proof trace (all N+1 states and N tactics) in a single call,
**so that** I can efficiently collect proof data without per-step round trips.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a session with a completed proof of N tactic steps WHEN the extract-trace tool is called THEN it returns all N+1 proof states and the N tactics in order
- GIVEN the returned trace WHEN it is inspected THEN each entry includes the step index, the tactic applied (except for the initial state), and the resulting proof state
- GIVEN the returned trace WHEN it is serialized THEN it conforms to the version-stable JSON schema with a declared schema version field

### 2.4 Incremental Tracing

**As an** AI researcher iterating on a Coq project,
**I want to** trace proof changes without reprocessing the entire project,
**so that** I can efficiently update training data after incremental edits.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project that has been previously traced WHEN a subset of .v files have changed THEN only the changed files are reprocessed to update proof traces
- GIVEN incremental tracing WHEN it completes THEN the resulting traces are identical to what a full reprocessing would produce

---

## Epic 3: Tactic Interaction

### 3.1 Submit a Single Tactic

**As a** tool builder or AI researcher,
**I want to** submit a single tactic to the current proof state and receive the resulting state,
**so that** I can implement an observe-submit-feedback loop for proof exploration.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active session with open goals WHEN a valid tactic is submitted THEN the resulting proof state is returned with updated goals and hypotheses
- GIVEN an active session WHEN an invalid tactic is submitted THEN a structured error is returned including the Coq error message and the proof state remains unchanged
- GIVEN a tactic that closes all goals WHEN it is submitted THEN the response indicates the proof is complete

### 3.2 Step Backward

**As a** tool builder exploring alternative proof strategies,
**I want to** undo the last tactic and return to the previous proof state,
**so that** I can backtrack and try different approaches.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active session at step k > 0 WHEN the step-backward tool is called THEN the session returns to the proof state at step k-1
- GIVEN an active session at step 0 (initial state) WHEN the step-backward tool is called THEN a structured error is returned indicating there is no previous state
- GIVEN a step-backward operation WHEN the resulting state is returned THEN it is identical to the state that was observed at step k-1

### 3.3 Step Forward Through Existing Proof

**As a** tool builder replaying a completed proof,
**I want to** step forward through the original proof script one tactic at a time,
**so that** I can observe state transitions without manually submitting each tactic.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a session opened on a completed proof at step k < N WHEN the step-forward tool is called THEN the next tactic from the original proof script is applied and the resulting state is returned
- GIVEN a session at the final step N WHEN the step-forward tool is called THEN a structured error is returned indicating the proof is already complete
- GIVEN a step-forward operation WHEN the resulting state is returned THEN it includes the tactic that was applied

### 3.4 Submit Tactic Batch

**As an** AI researcher running automated proof search,
**I want to** submit multiple tactics in a single request and receive the state after each step,
**so that** I can reduce round-trip overhead during batch exploration.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active session WHEN a batch of N tactics is submitted THEN the response includes N entries, each containing the tactic and the resulting proof state
- GIVEN a batch where tactic k fails WHEN the batch is processed THEN the response includes successful results for tactics 1..k-1, a structured error for tactic k, and the remaining tactics are not executed
- GIVEN a batch that completes the proof at tactic k < N WHEN the batch is processed THEN the response includes results for tactics 1..k and indicates the proof is complete

---

## Epic 4: Premise Tracking

### 4.1 Get Premise Annotations for Completed Proof

**As an** AI researcher building premise selection datasets,
**I want to** extract the premise annotations for each tactic step of a completed proof,
**so that** I can identify which lemmas and hypotheses each tactic relied on.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a session with a completed proof WHEN the get-premises tool is called THEN it returns a per-tactic list of premise annotations
- GIVEN a premise annotation WHEN it is inspected THEN each premise includes its fully qualified name and kind (lemma, hypothesis, constructor, definition)
- GIVEN the premise annotations WHEN they are compared against hand-curated ground truth on a set of ≥ 50 proofs THEN they match the ground truth

### 4.2 Get Premise Annotations for a Single Step

**As an** AI researcher analyzing individual tactic behavior,
**I want to** query premise annotations for a specific tactic step,
**so that** I can examine which premises were used at a particular point in the proof.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a session with a completed proof at step k WHEN the get-step-premises tool is called with step k THEN it returns the premise annotations for that specific tactic step
- GIVEN a step index outside the valid range WHEN the get-step-premises tool is called THEN a structured error is returned indicating the step is out of range

---

## Epic 5: Proof Trace Serialization

### 5.1 Serialize Proof Trace to JSON

**As an** AI researcher exporting proof data,
**I want** proof traces to be serialized in a version-stable JSON format with a declared schema version,
**so that** downstream tools can reliably parse traces across tool versions.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof trace WHEN it is serialized THEN the output is valid JSON containing a top-level schema version field
- GIVEN traces produced by the same tool version WHEN they are compared THEN the serialization is deterministic (identical input produces identical output)
- GIVEN a schema version change WHEN a downstream tool reads a trace THEN the schema version field allows it to detect incompatibility

### 5.2 Proof State Diff

**As a** tool builder analyzing proof evolution,
**I want to** compute a diff between consecutive proof states,
**so that** I can see what goals and hypotheses were added, removed, or changed by a tactic.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN two consecutive proof states (step k and step k+1) WHEN the diff tool is called THEN it returns the goals added, goals removed, goals changed, hypotheses added, hypotheses removed, and hypotheses changed
- GIVEN a diff result WHEN it is inspected THEN changed items include both the before and after values

---

## Epic 6: MCP Tool Surface

### 6.1 Start the MCP Server with Proof Interaction Tools

**As a** Coq developer using Claude Code,
**I want** the MCP server to expose both search and proof interaction tools,
**so that** I can use all capabilities within a single conversational workflow.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid MCP configuration WHEN the server starts via stdio transport THEN it exposes all search tools (from Phase 1) and all proof interaction tools
- GIVEN a connected server WHEN the tool list is requested THEN proof interaction tools include at minimum: open-session, close-session, list-sessions, observe-state, submit-tactic, step-backward, step-forward, extract-trace, get-premises
- GIVEN a connected server WHEN any proof interaction tool is called THEN it returns well-formed MCP tool responses

### 6.2 Proof State Response Format

**As a** tool builder integrating with the MCP server,
**I want** proof state responses to use consistent ProofState, Goal, and Hypothesis schemas,
**so that** I can write reliable clients without handling format variations.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN any tool that returns proof state WHEN the response is inspected THEN it uses the ProofState schema containing: schema version, session ID, step index, focused goal index, and a list of Goal objects
- GIVEN a Goal object WHEN it is inspected THEN it contains: goal index, goal type (as a string), and a list of Hypothesis objects
- GIVEN a Hypothesis object WHEN it is inspected THEN it contains: name, type (as a string), and optionally a body (for let-bound hypotheses)

---

## Epic 7: Error Handling and Resilience

### 7.1 Coq Backend Errors

**As a** tool builder submitting tactics programmatically,
**I want** Coq error messages to be surfaced as structured data in MCP responses,
**so that** I can programmatically handle errors without parsing free-text output.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic that fails in Coq WHEN the error is returned THEN the MCP response includes a structured error object with the Coq error message, error location (if available), and the unchanged proof state
- GIVEN a file that fails to load WHEN the error is returned THEN the response includes a structured error with the Coq error message

### 7.2 Session Timeout and Cleanup

**As an** operator of the MCP server,
**I want** idle sessions to be automatically closed after 30 minutes of inactivity,
**so that** abandoned sessions do not leak resources indefinitely.

**Priority:** P0
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an active session with no tool calls for 30 minutes WHEN the timeout period elapses THEN the session is automatically closed and resources are released
- GIVEN an auto-closed session WHEN any tool is called with that session ID THEN a structured error is returned indicating the session timed out

### 7.3 Backend Process Crash Recovery

**As a** tool builder running long proof explorations,
**I want** a crash in one session's Coq backend to be isolated from other sessions,
**so that** a single failure does not bring down all concurrent work.

**Priority:** P0
**Stability:** Draft

**Acceptance criteria:**
- GIVEN multiple concurrent sessions WHEN the Coq backend process for one session crashes THEN all other sessions continue to operate normally
- GIVEN a crashed session WHEN any tool is called with that session ID THEN a structured error is returned indicating the backend process crashed

---

## Epic 8: Batch Proof Replay CLI

### 8.1 Replay Proof Trace via CLI

**As a** Coq developer or dataset-building script,
**I want to** run `replay-proof` from the terminal with a file path and proof name and receive the complete proof trace,
**so that** I can extract proof data without an MCP client.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid .v file and a named proof within it WHEN `replay-proof <file_path> <proof_name>` is executed THEN the command prints a human-readable trace to stdout showing each proof step with its tactic, goals, and hypotheses, and exits with code 0
- GIVEN a valid .v file and proof WHEN `replay-proof <file_path> <proof_name> --json` is executed THEN the command prints the serialized proof trace as JSON to stdout and exits with code 0
- GIVEN the JSON output WHEN it is parsed THEN it conforms to the `ProofTrace` schema produced by `serialize_proof_trace()`

**Traces to:** R2-P0-5 (extract full proof state at each step)

### 8.2 Replay Proof with Premise Annotations

**As an** AI researcher building premise selection datasets,
**I want to** include per-step premise annotations when replaying a proof,
**so that** I can extract both proof traces and premise data in a single command invocation.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid proof WHEN `replay-proof <file_path> <proof_name> --premises` is executed THEN the output includes per-step premise annotations alongside the proof trace
- GIVEN `--json --premises` flags WHEN the command is executed THEN the JSON output wraps the trace and premises as `{"trace": ..., "premises": [...]}`
- GIVEN the premise annotations WHEN they are inspected THEN each annotation includes the step index, tactic, and list of premises with name and kind

**Traces to:** R2-P0-6 (extract premise annotations)

### 8.3 Replay Proof Error Handling

**As a** CI pipeline or script author,
**I want** `replay-proof` to report errors to stderr with a nonzero exit code,
**so that** I can detect failures programmatically.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a file path that does not exist WHEN `replay-proof` is executed THEN an error message is printed to stderr and the command exits with code 1
- GIVEN a valid file but a nonexistent proof name WHEN `replay-proof` is executed THEN an error message is printed to stderr and the command exits with code 1
- GIVEN a Coq backend crash during replay WHEN the error is detected THEN an error message is printed to stderr, the session is cleaned up, and the command exits with code 1
- GIVEN missing required arguments WHEN `replay-proof` is executed THEN the command exits with code 2 (usage error)
