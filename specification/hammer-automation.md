# Hammer Automation

Wraps CoqHammer tactics (`hammer`, `sauto`, `qauto`) for invocation within active proof sessions, managing strategy sequencing, timeout budgets, and result interpretation.

**Architecture**: [hammer-automation.md](../doc/architecture/hammer-automation.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the hammer automation component that assembles CoqHammer tactic strings from structured parameters, submits them to the Proof Session Manager within active proof sessions, interprets Coq output into structured results, and orchestrates multi-strategy fallback with a shared timeout budget.

## 2. Scope

**In scope**: Tactic building (assembling syntactically valid CoqHammer tactic strings), single-strategy execution, multi-strategy fallback sequencing, timeout budget management, result interpretation (classifying Coq output into structured failure reasons), input validation for hints and options.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), Coq backend process management (owned by proof-session), proof search tree exploration (owned by proof-search-engine), premise retrieval (owned by retrieval-pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Strategy | One of `hammer`, `sauto`, or `qauto` -- a specific CoqHammer tactic to attempt |
| Multi-strategy fallback | Sequential execution of strategies in a fixed order, stopping on the first success or budget exhaustion |
| Time budget | A shared wall-clock allocation across all strategy attempts in multi-strategy mode |
| Hint | A Coq lemma name passed to a CoqHammer tactic to guide proof search |
| Reconstruction | The process by which CoqHammer translates an ATP proof into a Coq tactic script |

## 4. Behavioral Requirements

### 4.1 Tool Surface

Hammer automation is exposed as a dedicated `try_automation` MCP tool, separate from `suggest_tactics`. `suggest_tactics` provides pedagogical hints (neural + rule-based) for teaching proof strategy; `try_automation` is a solver that attempts to close goals without human involvement.

The `try_automation` tool accepts a `strategy` parameter (`hammer`, `sauto`, `qauto`, or `auto_hammer`; default `auto_hammer`) and an `options` parameter for solver-specific configuration. For backward compatibility, `submit_tactic` still recognizes hammer keywords and delegates to the same engine.

### 4.2 Single-Strategy Execution

#### execute_single(session_id, strategy, timeout, hints, options)

- REQUIRES: `session_id` references an active proof session with at least one open goal. `strategy` is one of `hammer`, `sauto`, `qauto`. `timeout` is a positive number (seconds). `hints` is a list of syntactically valid Coq identifiers (may be empty). `options` is a map of strategy-specific parameters (may be empty).
- ENSURES: Builds a tactic string via the Tactic Builder. Wraps it with the appropriate timeout directive. Submits it to the Proof Session Manager. Passes the Coq output and post-submission proof state to the Result Interpreter, which returns a `ClassifiedOutput`. Assembles a `HammerResult` by combining the `ClassifiedOutput` with the strategy identity, wall-clock timing, proof script (on success), and diagnostics.
- MAINTAINS: On success, exactly one tactic step is added to the session. On failure, the session state is unchanged.

> **Given** a proof session at goal `n + 0 = n` with `Nat.add_0_r` available
> **When** `execute_single(session_id, "hammer", 30, ["Nat.add_0_r"], {})` is called
> **Then** the tactic `hammer using: Nat.add_0_r` is submitted, and on success, a HammerResult with `status = "success"`, `strategy_used = "hammer"`, and a non-null `proof_script` is returned

> **Given** a proof session at a goal that `sauto` cannot solve
> **When** `execute_single(session_id, "sauto", 10, [], {})` is called
> **Then** a HammerResult with `status = "failure"` and one StrategyDiagnostic entry is returned, and the proof session state is unchanged

> **Given** a proof session at a goal, with a 5-second timeout
> **When** `execute_single(session_id, "hammer", 5, [], {})` is called and the tactic does not complete within 5 seconds
> **Then** a HammerResult with `status = "failure"` and a diagnostic with `failure_reason = "timeout"` is returned

### 4.3 Multi-Strategy Fallback

#### execute_auto(session_id, total_timeout, hints, options)

- REQUIRES: `session_id` references an active proof session with at least one open goal. `total_timeout` is a positive number (seconds), default 60.
- ENSURES: Executes strategies in the fixed order `[hammer, sauto, qauto]`. For each strategy, computes `per_strategy_timeout = min(budget_remaining, default_timeout_for(strategy))`. On the first success, returns immediately with the successful HammerResult and diagnostics from prior failed attempts prepended. When all strategies fail or the budget is exhausted, returns a HammerResult with `status = "failure"` and all collected diagnostics.
- MAINTAINS: At most one successful tactic step is added to the session. Failed attempts leave the session state unchanged.

> **Given** a proof session where `hammer` times out but `sauto` succeeds
> **When** `execute_auto(session_id, 60, [], {})` is called
> **Then** a HammerResult with `status = "success"`, `strategy_used = "sauto"` is returned, with `diagnostics` containing one entry for the failed `hammer` attempt

> **Given** a proof session where all three strategies fail within the budget
> **When** `execute_auto(session_id, 60, [], {})` is called
> **Then** a HammerResult with `status = "failure"` is returned, with `diagnostics` containing three entries (one per strategy)

> **Given** a proof session where `hammer` consumes 55 of 60 seconds and fails
> **When** `execute_auto(session_id, 60, [], {})` is called
> **Then** `sauto` receives at most 5 seconds of budget, and if it also fails, `qauto` is skipped because the budget is exhausted

### 4.4 Default Timeouts

| Strategy | Default per-strategy timeout (seconds) |
|----------|----------------------------------------|
| `hammer` | 30 |
| `sauto` | 10 |
| `qauto` | 5 |
| `auto_hammer` | 90 (total budget) |

When a caller provides an explicit `timeout`, it overrides the default for single-strategy calls. For `auto_hammer`, the caller-provided timeout overrides the total budget.

### 4.5 Tactic Builder

#### build_tactic(strategy, hints, options)

- REQUIRES: `strategy` is one of `hammer`, `sauto`, `qauto`. Each entry in `hints` is a syntactically valid Coq identifier (matches `[a-zA-Z_][a-zA-Z0-9_'.]*`). Numeric options (`sauto_depth`, `qauto_depth`) are positive integers. Entries in `unfold` are syntactically valid Coq identifiers.
- ENSURES: Returns a syntactically valid Coq tactic string assembled from the inputs per the mapping table below.
- On invalid hint name: returns a `PARSE_ERROR` immediately without submitting to Coq.
- On invalid option value (non-positive depth, non-identifier in unfold): returns a `PARSE_ERROR` immediately without submitting to Coq.

| Strategy | Hints | Options | Tactic string produced |
|----------|-------|---------|----------------------|
| `hammer` | none | none | `hammer` |
| `hammer` | `[lem1, lem2]` | none | `hammer using: lem1, lem2` |
| `sauto` | none | none | `sauto` |
| `sauto` | none | `depth=5` | `sauto depth: 5` |
| `sauto` | `[lem1]` | `unfold=[def1]` | `sauto use: lem1 unfold: def1` |
| `qauto` | `[lem1]` | `depth=3` | `qauto depth: 3 use: lem1` |

> **Given** strategy `hammer` with hints `["Nat.add_comm", "Nat.add_0_r"]`
> **When** `build_tactic` is called
> **Then** the result is `"hammer using: Nat.add_comm, Nat.add_0_r"`

> **Given** strategy `sauto` with depth 5 and unfold `["my_def"]`
> **When** `build_tactic` is called
> **Then** the result is `"sauto depth: 5 unfold: my_def"`

> **Given** strategy `hammer` with hints `["123invalid"]`
> **When** `build_tactic` is called
> **Then** a `PARSE_ERROR` is returned immediately

### 4.6 Timeout Wrapping

The engine shall wrap tactic strings with Coq-level timeout directives before submission:

| Strategy | Wrapping |
|----------|----------|
| `hammer` | `Set Hammer Timeout {t}.` issued before the tactic |
| `sauto` | `Timeout {t} sauto ...` |
| `qauto` | `Timeout {t} qauto ...` |

Where `{t}` is the per-strategy timeout in seconds.

### 4.7 Result Interpreter

#### interpret_result(coq_output, proof_state_after)

- REQUIRES: `coq_output` is the raw text output from the Proof Session Manager after tactic submission. `proof_state_after` is the ProofState observed after submission.
- ENSURES: Returns a `ClassifiedOutput` per the mapping table below. The caller (`execute_single` or `execute_auto`) assembles the full `HammerResult` by combining the `ClassifiedOutput` with strategy identity, wall-clock timing, and diagnostics.

| Coq output pattern | `classification` | `partial_progress` |
|--------------------|--------------|--------------------|
| Tactic succeeded (goal closed in `proof_state_after`) | `success` | null |
| "Timeout" or wall-clock exceeded | `timeout` | null |
| "No proof found" or "hammer failed" | `no_proof_found` | null |
| "Reconstruction failed" with ATP proof present | `reconstruction_failed` | ATP proof text |
| Any other tactic error | `tactic_error` | null |

When the interpreter cannot classify an error message into a specific reason, the interpreter shall fall back to `tactic_error` with the raw Coq error as `detail`.

> **Given** Coq output containing "Reconstruction failed" followed by an ATP proof
> **When** `interpret_result` is called
> **Then** the result is a `ClassifiedOutput` with `classification = "reconstruction_failed"` and `partial_progress` containing the ATP proof text

> **Given** Coq output containing "Error: Unknown tactic hammer"
> **When** `interpret_result` is called
> **Then** the result is a `ClassifiedOutput` with `classification = "tactic_error"` and `detail` containing the raw error message

## 5. Data Model

### HammerResult

| Field | Type | Constraints |
|-------|------|-------------|
| `status` | `"success"` or `"failure"` | Required |
| `proof_script` | text or null | Required; non-null on success; null on failure |
| `atp_proof` | text or null | On `hammer` success via ATP: the high-level ATP proof; null for `sauto`/`qauto` or when unavailable |
| `strategy_used` | `"hammer"` or `"sauto"` or `"qauto"` or null | Required; the strategy that succeeded; null on failure |
| `state` | ProofState | Required; proof state after invocation (goal closed on success, unchanged on failure) |
| `diagnostics` | list of StrategyDiagnostic | Required; one entry per strategy attempted; empty list when a single strategy succeeds on first try |
| `wall_time_ms` | non-negative integer | Required; total wall-clock time across all strategies |

### StrategyDiagnostic

| Field | Type | Constraints |
|-------|------|-------------|
| `strategy` | `"hammer"` or `"sauto"` or `"qauto"` | Required |
| `failure_reason` | `"timeout"` or `"no_proof_found"` or `"reconstruction_failed"` or `"tactic_error"` | Required |
| `detail` | text | Required; human-readable detail from Coq error output |
| `partial_progress` | text or null | ATP proof text when reconstruction failed; null otherwise |
| `wall_time_ms` | non-negative integer | Required; time consumed by this strategy |
| `timeout_used` | number | Required; the timeout value (seconds) applied to this strategy |

### ClassifiedOutput

| Field | Type | Constraints |
|-------|------|-------------|
| `classification` | `"success"` or `"timeout"` or `"no_proof_found"` or `"reconstruction_failed"` or `"tactic_error"` | Required |
| `detail` | text or null | Human-readable detail from Coq error output; null on success |
| `partial_progress` | text or null | ATP proof text when reconstruction failed; null otherwise |

`interpret_result` returns a `ClassifiedOutput`. The caller (`execute_single` or `execute_auto`) uses the `ClassifiedOutput` to construct a `StrategyDiagnostic` (on failure) or populate the success fields of a `HammerResult` (on success).

### Relationships

- HammerResult references one ProofState (from proof-types).
- HammerResult contains zero or more StrategyDiagnostic entries (1:*; ordered by attempt sequence).
- `interpret_result` produces a ClassifiedOutput; the caller assembles this into a HammerResult.

## 6. Interface Contracts

### Hammer Automation -> Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `submit_tactic`, `observe_proof_state` |
| Concurrency | Serialized -- one tactic submission at a time per session |
| Session state on success | One tactic step added; proof state reflects the closed goal; tactic recorded in session step history |
| Session state on failure | Unchanged; the Proof Session Manager returns `TACTIC_ERROR` alongside the unchanged ProofState |
| Multi-strategy invariant | At most one successful tactic is submitted; failed attempts produce `TACTIC_ERROR` responses that leave session state unchanged; no rollback is needed |
| Error strategy | `TACTIC_ERROR` -> classify via Result Interpreter and return HammerResult. `SESSION_NOT_FOUND` -> propagate immediately. `BACKEND_CRASHED` -> propagate immediately. |
| Idempotency | Not required -- hammer invocations are not retriable |

### Hammer Automation -> MCP Server (inbound)

| Property | Value |
|----------|-------|
| Trigger | `try_automation` called with a `strategy` parameter (or `submit_tactic` called with `tactic` matching a hammer keyword for backward compatibility) |
| Keyword detection | MCP Server checks `strategy` (or `tactic`) against `{"hammer", "sauto", "qauto", "auto_hammer"}`; Proof Session Manager is unaware of hammer automation |
| Options passthrough | `options` parameter on `try_automation` (or `submit_tactic`) carries hammer-specific configuration |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Behavior |
|-----------|----------|
| `session_id` references a non-existent session | Return `SESSION_NOT_FOUND` immediately; no tactic submitted |
| `session_id` references an expired session | Return `SESSION_NOT_FOUND` immediately; no tactic submitted |
| No active goal (proof already complete) | Return `TACTIC_ERROR` with message indicating no open goals |
| Hint name is not a valid Coq identifier | Return `PARSE_ERROR` immediately; no tactic submitted |
| Numeric option is not a positive integer | Return `PARSE_ERROR` immediately; no tactic submitted |
| Unfold entry is not a valid Coq identifier | Return `PARSE_ERROR` immediately; no tactic submitted |

### 7.2 Dependency Errors

| Condition | Behavior |
|-----------|----------|
| Coq backend crashes during execution | Return `BACKEND_CRASHED` error |
| CoqHammer not installed | Coq returns "Unknown tactic hammer"; classified as `tactic_error` with detail explaining the prerequisite |
| ATP solver not installed | `hammer` returns a failure; classified as `no_proof_found` or `tactic_error` depending on Coq output |

### 7.3 Multi-Strategy Budget Errors

| Condition | Behavior |
|-----------|----------|
| Single strategy times out within multi-strategy mode | Diagnostic recorded with `failure_reason = "timeout"`; next strategy attempted with remaining budget |
| Total budget exhausted before all strategies tried | Return HammerResult with `status = "failure"` and diagnostics for all attempted strategies; remaining strategies skipped |
| All strategies fail within budget | Return HammerResult with `status = "failure"` and diagnostics for all three strategies |

## 8. Non-Functional Requirements

- The Tactic Builder shall produce a tactic string in < 1 ms for any valid input combination.
- The Result Interpreter shall classify Coq output in < 1 ms per invocation.
- Wall-clock time reported in `wall_time_ms` shall be accurate to within 10 ms of actual elapsed time.
- The component shall not allocate persistent state beyond the lifetime of a single invocation. All intermediate data (diagnostics list, budget tracking) is scoped to one `execute_single` or `execute_auto` call.

## 9. Examples

### Successful single strategy -- hammer with hints

```
try_automation(session_id="abc123", strategy="hammer", options={hints: ["Nat.add_0_r"]})

Proof state: n : nat |- n + 0 = n

Execution:
  Tactic Builder produces: "hammer using: Nat.add_0_r"
  Timeout wrapping: "Set Hammer Timeout 30."
  Submitted to Proof Session Manager
  Coq succeeds, goal closed

Result:
{
  "status": "success",
  "proof_script": "hammer using: Nat.add_0_r.",
  "atp_proof": "by auto using Nat.add_0_r",
  "strategy_used": "hammer",
  "state": {"is_complete": true, "goals": []},
  "diagnostics": [],
  "wall_time_ms": 2400
}
```

### Failed single strategy -- timeout

```
try_automation(session_id="def456", strategy="hammer", options={timeout: 10})

Proof state: |- complex_theorem

Execution:
  Tactic Builder produces: "hammer"
  Timeout wrapping: "Set Hammer Timeout 10."
  Submitted to Proof Session Manager
  Coq returns: "Error: Timeout"

Result:
{
  "status": "failure",
  "proof_script": null,
  "atp_proof": null,
  "strategy_used": null,
  "state": {"is_complete": false, "goals": [{"type": "complex_theorem", ...}]},
  "diagnostics": [
    {
      "strategy": "hammer",
      "failure_reason": "timeout",
      "detail": "Error: Timeout",
      "partial_progress": null,
      "wall_time_ms": 10050,
      "timeout_used": 10
    }
  ],
  "wall_time_ms": 10050
}
```

### Multi-strategy fallback -- hammer fails, sauto succeeds

```
try_automation(session_id="ghi789", strategy="auto_hammer", options={timeout: 60})

Proof state: H : a = b |- b = a

Execution:
  Strategy 1: hammer (timeout=30)
    Tactic: "hammer"
    Result: timeout after 30s
    Budget remaining: 30s

  Strategy 2: sauto (timeout=10, capped to 10)
    Tactic: "sauto"
    Result: success after 0.5s

Result:
{
  "status": "success",
  "proof_script": "sauto.",
  "atp_proof": null,
  "strategy_used": "sauto",
  "state": {"is_complete": true, "goals": []},
  "diagnostics": [
    {
      "strategy": "hammer",
      "failure_reason": "timeout",
      "detail": "Error: Timeout",
      "partial_progress": null,
      "wall_time_ms": 30000,
      "timeout_used": 30
    }
  ],
  "wall_time_ms": 30500
}
```

## 10. Language-Specific Notes (Python)

- Use `asyncio` for tactic submission via the Proof Session Manager's async interface.
- Use `time.monotonic()` for wall-clock budget tracking; do not use `time.time()` (susceptible to clock adjustments).
- Use `re` for Coq identifier validation (`^[a-zA-Z_][a-zA-Z0-9_'.]*$`).
- Use `re` for Coq error output pattern matching in the Result Interpreter.
- Package location: `src/poule/hammer/`.
- Entry point: `async def execute_hammer(session_manager, session_id, strategy, timeout, hints, options) -> HammerResult`.
- Multi-strategy entry point: `async def execute_auto_hammer(session_manager, session_id, timeout, hints, options) -> HammerResult`.
- Tactic Builder: pure function `def build_tactic(strategy, hints, options) -> str`, raising `ParseError` on invalid inputs.
- Result Interpreter: pure function `def interpret_result(coq_output, proof_state) -> ClassifiedOutput`.
