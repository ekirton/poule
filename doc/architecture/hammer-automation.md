# Hammer Automation

The component that wraps CoqHammer tactics (`hammer`, `sauto`, `qauto`) for invocation within active proof sessions, managing strategy sequencing, timeout budgets, and result interpretation.

**Feature**: [Hammer Automation](../features/hammer-automation.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
MCP Server
  │
  │ try_automation(session_id, strategy="auto_hammer", options={...})
  ▼
┌───────────────────────────────────────────────────────────────┐
│                   Hammer Automation                            │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Strategy Executor                                       │  │
│  │                                                         │  │
│  │  Input: session_id, strategy, timeout, hints, options   │  │
│  │                                                         │  │
│  │  If strategy is specific (hammer | sauto | qauto):      │  │
│  │    1. Build tactic string with options and hints        │  │
│  │    2. Submit to Proof Session Manager                   │  │
│  │    3. Interpret result → HammerResult                   │  │
│  │                                                         │  │
│  │  If strategy is "auto" (multi-strategy fallback):       │  │
│  │    1. Initialize time budget from timeout               │  │
│  │    2. For each strategy in [hammer, sauto, qauto]:      │  │
│  │       a. Compute per-strategy timeout from remaining    │  │
│  │          budget                                         │  │
│  │       b. Build tactic string                            │  │
│  │       c. Submit to Proof Session Manager                │  │
│  │       d. On success → return HammerResult immediately   │  │
│  │       e. On failure → record diagnostic, continue       │  │
│  │       f. If budget exhausted → stop, return failure     │  │
│  │    3. All failed → return HammerResult with all diags   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────┐  ┌──────────────────────────────────┐  │
│  │ Tactic Builder    │  │ Result Interpreter               │  │
│  │                   │  │                                  │  │
│  │ Assembles tactic  │  │ Parses Coq output into          │  │
│  │ string from:      │  │ HammerResult:                   │  │
│  │  - strategy name  │  │  - success → proof script       │  │
│  │  - timeout value  │  │  - timeout → timeout diagnostic │  │
│  │  - lemma hints    │  │  - failure → failure reason     │  │
│  │  - sauto/qauto    │  │  - reconstruction failure       │  │
│  │    options        │  │    → partial progress           │  │
│  └───────────────────┘  └──────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
  │
  │ submit_tactic(session_id, tactic_string)
  │ observe_proof_state(session_id)
  ▼
Proof Session Manager
  │
  │ coq-lsp / SerAPI
  ▼
Coq Backend Process
```

## Tool Surface

Hammer automation is exposed as a dedicated `try_automation` MCP tool, separate from `suggest_tactics`. This reflects their different roles: `suggest_tactics` is a pedagogical tool that provides explained hints to help students learn proof strategy, while `try_automation` is a solver that attempts to close goals without human involvement.

```typescript
try_automation(
  session_id: string,
  strategy?: string,           // "hammer" | "sauto" | "qauto" | "auto_hammer" (default)
  options?: {
    timeout?: number,          // seconds; default: 30 for hammer, 10 for sauto/qauto, 90 for auto_hammer
    hints?: string[],          // lemma names to pass as hints
    sauto_depth?: number,      // search depth for sauto (P1)
    qauto_depth?: number,      // search depth for qauto (P1)
    unfold?: string[],         // definitions to unfold (sauto/qauto, P1)
  }
) → HammerResult
```

For backward compatibility, `submit_tactic` still recognizes hammer keywords and delegates to the same engine. New commands and prompts should use `try_automation` for solver invocations and `submit_tactic` for regular tactic submission.

## Data Structures

**HammerResult** — the output of a hammer automation invocation:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"success"` or `"failure"` | Whether the goal was discharged |
| `proof_script` | text or null | On success: the Coq tactic script that closes the goal |
| `atp_proof` | text or null | On `hammer` success via ATP: the high-level ATP proof (P1); null for `sauto`/`qauto` or when ATP proof is unavailable |
| `strategy_used` | `"hammer"` or `"sauto"` or `"qauto"` or null | The strategy that succeeded; null on failure |
| `state` | ProofState | The proof state after the invocation (goal closed on success, unchanged on failure) |
| `diagnostics` | list of StrategyDiagnostic | One entry per strategy attempted; empty list if a single strategy succeeded on first try |
| `wall_time_ms` | non-negative integer | Total wall-clock time across all strategies |

**StrategyDiagnostic** — diagnostic information for a single strategy attempt:

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | `"hammer"` or `"sauto"` or `"qauto"` | The strategy that was attempted |
| `failure_reason` | `"timeout"` or `"no_proof_found"` or `"reconstruction_failed"` or `"tactic_error"` | Why the strategy failed |
| `detail` | text | Human-readable detail from Coq's error output |
| `partial_progress` | text or null | When ATP found a proof but reconstruction failed: the ATP proof text |
| `wall_time_ms` | non-negative integer | Time consumed by this strategy |
| `timeout_used` | number | The timeout value (seconds) that was applied to this strategy |

## Strategy Execution Algorithm

### Single Strategy

When a specific strategy is requested (`hammer`, `sauto`, or `qauto`):

```
execute_single(session_id, strategy, timeout, hints, options)
  │
  ├─ Build tactic string via Tactic Builder
  │    e.g., "hammer" → "hammer"
  │         "sauto" with depth 5 → "sauto depth: 5"
  │         "hammer" with hints [lem1, lem2] → "hammer using: lem1, lem2"
  │
  ├─ Set Coq-level timeout:
  │    Wrap tactic with "Set Hammer Timeout {t}." for hammer
  │    Wrap tactic with "Timeout {t} {tactic}." for sauto/qauto
  │
  ├─ Submit tactic to Proof Session Manager
  │    submit_tactic(session_id, timeout_wrapped_tactic_string)
  │
  ├─ Observe result:
  │    ├─ Tactic succeeded (proof state shows goal closed):
  │    │    Extract proof script from Coq output
  │    │    Return HammerResult(status="success", proof_script=..., strategy_used=strategy)
  │    │
  │    └─ Tactic failed (TACTIC_ERROR from Proof Session Manager):
  │         Parse error message via Result Interpreter
  │         Return HammerResult(status="failure", diagnostics=[...])
  │
  └─ Wall-clock timeout exceeded before Coq responds:
       Return HammerResult(status="failure", diagnostics=[timeout diagnostic])
```

### Multi-Strategy Fallback

When `auto_hammer` is requested:

```
execute_auto(session_id, total_timeout, hints, options)
  │
  ├─ strategies = [hammer, sauto, qauto]
  ├─ budget_remaining = total_timeout
  ├─ diagnostics = []
  ├─ deadline = now + total_timeout
  │
  ├─ For each strategy in strategies:
  │    │
  │    ├─ If now >= deadline → break (budget exhausted)
  │    │
  │    ├─ per_strategy_timeout = min(
  │    │    budget_remaining,
  │    │    default_timeout_for(strategy)
  │    │  )
  │    │
  │    ├─ result = execute_single(session_id, strategy, per_strategy_timeout, hints, options)
  │    │
  │    ├─ budget_remaining -= result.wall_time_ms / 1000
  │    │
  │    ├─ If result.status == "success":
  │    │    Return result (with diagnostics from prior failed attempts prepended)
  │    │
  │    └─ Else:
  │         Append result.diagnostics to diagnostics
  │         Continue to next strategy
  │
  └─ All strategies exhausted or budget exceeded:
       Return HammerResult(status="failure", diagnostics=diagnostics)
```

The strategy order — `hammer`, then `sauto`, then `qauto` — runs the most powerful tactic first. If `hammer` succeeds, the lighter strategies are never tried. If `hammer` times out, whatever budget remains is available to the faster alternatives.

### Default Timeouts

| Strategy | Default per-strategy timeout | Rationale |
|----------|------------------------------|-----------|
| `hammer` | 30 seconds | External ATP solvers are slow; 30s matches CoqHammer's own default |
| `sauto` | 10 seconds | No external solvers; purely internal search |
| `qauto` | 5 seconds | Lightest tactic; should succeed quickly or not at all |
| `auto_hammer` | 60 seconds | Total budget for the full sequence |

### Tactic Builder

The Tactic Builder assembles syntactically valid Coq tactic strings from structured parameters.

| Input | Tactic string produced |
|-------|----------------------|
| `hammer` with no options | `hammer` |
| `hammer` with hints `[lem1, lem2]` | `hammer using: lem1, lem2` |
| `sauto` with no options | `sauto` |
| `sauto` with depth 5 | `sauto depth: 5` |
| `sauto` with hints `[lem1]` and unfold `[def1]` | `sauto use: lem1 unfold: def1` |
| `qauto` with depth 3 and hints `[lem1]` | `qauto depth: 3 use: lem1` |

The builder validates that hint names are syntactically valid Coq identifiers and that numeric options are positive integers. Invalid options produce an immediate error without submitting to Coq.

## Integration with Proof Session Manager

Hammer Automation reuses the existing Proof Session Manager — it does not create or close sessions, manage backend processes, or maintain its own state.

**Operations used:**

| Operation | Purpose |
|-----------|---------|
| `submit_tactic` | Submit the assembled hammer tactic string to Coq |
| `observe_proof_state` | Check whether the goal was closed after submission |

**Session state contract:**

- On success, the proof session advances by one step (the hammer tactic). The proof state reflects the closed goal. The tactic is recorded in the session's step history.
- On failure, the proof session state is unchanged. The Proof Session Manager's existing behavior — returning a `TACTIC_ERROR` alongside the unchanged `ProofState` — applies directly.
- Multi-strategy fallback submits at most one successful tactic. Failed attempts produce `TACTIC_ERROR` responses from the Proof Session Manager, which leave the session state unchanged. No rollback is needed.

**No session forking:** Unlike the Proof Search Engine, which explores many branches, Hammer Automation submits tactics linearly. Each strategy attempt either succeeds (one step forward) or fails (no state change). There is no branching, backtracking, or replay.

## Result Interpreter

The Result Interpreter classifies Coq's output into structured failure reasons. Classification is based on pattern matching against known CoqHammer error message formats.

| Coq output pattern | Classified as | `partial_progress` |
|--------------------|--------------|--------------------|
| Tactic succeeds, goal closed | `success` | n/a |
| "Timeout" or wall-clock exceeded | `timeout` | null |
| "No proof found" / "hammer failed" | `no_proof_found` | null |
| "Reconstruction failed" with ATP proof in output | `reconstruction_failed` | ATP proof text |
| Other tactic error | `tactic_error` | null |

When the Result Interpreter cannot classify an error message into a specific reason, it falls back to `tactic_error` with the raw Coq error as `detail`. This ensures that unexpected CoqHammer output surfaces to the user rather than being silently swallowed.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Session not found or expired | Return `SESSION_NOT_FOUND` error immediately (no tactic submitted) |
| Backend crashed | Return `BACKEND_CRASHED` error (consistent with existing MCP error contract) |
| No active goal (proof already complete) | Return `TACTIC_ERROR` with message indicating no open goals |
| Invalid hint name (not a valid Coq identifier) | Return `PARSE_ERROR` immediately (no tactic submitted) |
| Invalid option value (negative depth, etc.) | Return `PARSE_ERROR` immediately (no tactic submitted) |
| CoqHammer not installed | Coq returns a tactic error ("Unknown tactic hammer"); classified as `tactic_error` with detail explaining the prerequisite |
| ATP solver not installed | `hammer` returns a failure; classified as `no_proof_found` or `tactic_error` depending on CoqHammer's output |
| Single strategy timeout in multi-strategy mode | Diagnostic recorded; next strategy attempted with remaining budget |
| Total budget exhausted in multi-strategy mode | Return failure with all diagnostics collected so far |

All errors use the MCP Server's existing error contract (see [mcp-server.md](mcp-server.md) Error Contract). Hammer Automation does not define new error codes — it reuses `SESSION_NOT_FOUND`, `TACTIC_ERROR`, `PARSE_ERROR`, and `BACKEND_CRASHED`.

## Design Rationale

### Why sequential strategy fallback rather than parallel

Running `hammer`, `sauto`, and `qauto` in parallel would require three concurrent tactic submissions on the same proof session. The Proof Session Manager serializes tactic submissions — one at a time per session (see [proof-session.md](proof-session.md)). Parallel execution would require forking to three sessions, tripling backend process count for every hammer invocation. Sequential fallback reuses a single session, has bounded resource usage, and matches the user's mental model of "try this, then that." The overhead of sequential attempts is acceptable because each failed tactic returns quickly relative to a successful one.

### Why reuse the Proof Session Manager rather than a standalone Coq invocation

Hammer tactics depend on the proof context — the current goal, hypotheses, and imported libraries. The Proof Session Manager already maintains this context through a live Coq backend process. Submitting hammer tactics through the existing session guarantees they see the correct context. A standalone invocation would need to reconstruct the proof state from scratch (re-importing the file, replaying to the current position), which is slow and fragile.

### Why a dedicated try_automation tool rather than a mode of submit_tactic

The original design embedded hammer as a mode of `submit_tactic` to minimize the tool count (RH-P0-6). However, `suggest_tactics` and hammer automation serve fundamentally different purposes: `suggest_tactics` provides pedagogical hints that Claude explains to help students learn proof strategy, while hammer automation is a solver that closes goals without human involvement. Conflating hints and solutions in the same tool — or routing both through `submit_tactic` — obscures this distinction in prompts and commands. A dedicated `try_automation` tool makes the intent explicit: use `suggest_tactics` for teaching moments, `try_automation` for routine subgoals. The tool count increase (one additional tool) is justified by the clearer separation of concerns. For backward compatibility, `submit_tactic` still recognizes hammer keywords.

### Why a shared timeout budget for multi-strategy mode

Independent per-strategy timeouts would mean a worst-case wall time of `timeout_hammer + timeout_sauto + timeout_qauto` — potentially 45 seconds with defaults. A shared budget lets the user specify one number ("give hammer automation 60 seconds total") without thinking about individual strategy allocations. If `hammer` uses 25 of 60 seconds, `sauto` and `qauto` share the remaining 35. This keeps total wait time predictable.

### Why hammer first in the strategy order

`hammer` is the most powerful tactic — it invokes external ATP solvers that can discharge goals beyond the reach of `sauto` and `qauto`. If `hammer` can solve a goal, running lighter tactics first wastes time. The cost is that `hammer` is also the slowest, so if it fails, less budget remains for alternatives. The default budget (60 seconds) is sized to accommodate this: even if `hammer` uses its full 30-second default, 30 seconds remain for `sauto` and `qauto` combined.
