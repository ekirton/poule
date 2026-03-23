# Proof Interaction Types

Canonical definitions for all data types used in proof interaction — session metadata, proof states, premise annotations, and proof traces. These types are produced by the Proof Session Manager, serialized by the Proof Serialization layer, and returned by the MCP Server.

**Architecture docs**: [proof-session.md](../proof-session.md), [proof-serialization.md](../proof-serialization.md), [mcp-server.md](../mcp-server.md)

---

## Session

Metadata for an active proof interaction session.

| Field | Type | Constraints |
|-------|------|-------------|
| `session_id` | identifier | Primary key; unique across all active sessions; opaque string |
| `file_path` | text | Required; absolute path to the .v source file |
| `proof_name` | qualified name | Required; fully qualified name of the proof within the file |
| `current_step` | non-negative integer | Required; 0 = initial state (before any tactic); incremented by submit/step-forward, decremented by step-backward |
| `total_steps` | non-negative integer or null | Required; total tactic steps in the original proof script; null if the proof is being constructed interactively (no original script) |
| `created_at` | timestamp | Required; ISO 8601 |
| `last_active_at` | timestamp | Required; ISO 8601; updated on every tool call targeting this session |

### Relationships

- **Owns** one Coq backend process (1:1; process lifecycle tied to session lifecycle).
- **Produces** ProofState snapshots on observation (1:*; not persisted — computed on demand).
- **Produces** PremiseAnnotation lists on premise queries (1:*; not persisted — computed on demand).

---

## ProofState

A snapshot of the proof state at a single point in a proof, representing what the user sees in CoqIDE at that step.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; identifies the serialization format version |
| `session_id` | reference to Session | Required; the session this state belongs to |
| `step_index` | non-negative integer | Required; 0 = initial state; k = state after k-th tactic |
| `is_complete` | boolean | Required; true when no open goals remain |
| `focused_goal_index` | non-negative integer or null | Required; index into `goals` of the currently focused goal; null when `is_complete` is true |
| `goals` | list of Goal | Required; may be empty when proof is complete |

### Relationships

- **Belongs to** one Session (via `session_id`).
- **Contains** zero or more Goal objects (1:*; ordered).

---

## Goal

A single proof obligation — one subgoal that must be discharged.

| Field | Type | Constraints |
|-------|------|-------------|
| `index` | non-negative integer | Required; position in the parent ProofState's `goals` list |
| `type` | text | Required; the goal's type as a Coq expression string |
| `hypotheses` | list of Hypothesis | Required; the local context for this goal; ordered as Coq presents them |

### Relationships

- **Contained in** one ProofState (via parent's `goals` list).
- **Contains** zero or more Hypothesis objects (1:*; ordered).

---

## Hypothesis

A named assumption in the local proof context of a goal.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | text | Required; the hypothesis name as it appears in the proof context |
| `type` | text | Required; the hypothesis's type as a Coq expression string |
| `body` | text or null | Optional; the body for let-bound hypotheses (e.g., `let x := 5 in ...`); null for non-let hypotheses |

### Relationships

- **Contained in** one Goal (via parent's `hypotheses` list).

---

## ProofTrace

A complete or partial record of a proof's execution: all states and the tactics that produced them.

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | positive integer | Required; must match ProofState's `schema_version` |
| `session_id` | reference to Session | Required |
| `proof_name` | qualified name | Required; fully qualified proof name |
| `file_path` | text | Required; absolute path to the .v file |
| `total_steps` | positive integer | Required; N (the total number of tactics in the original proof) |
| `steps` | list of TraceStep | Required; for complete traces, length equals `total_steps + 1`; for partial traces, length equals `failure_step` (steps 0..failure_step-1) |
| `partial` | boolean | Required; default false; true when tactic replay failed before completing all steps |
| `failure_step` | non-negative integer or null | Required; null when `partial` is false; the step index where replay failed when `partial` is true |
| `failure_message` | text | Required; empty string when `partial` is false; error description when `partial` is true |

### Relationships

- **Belongs to** one Session.
- **Contains** TraceStep objects (1:*; ordered by step index). For complete traces: `total_steps + 1` steps. For partial traces: `failure_step` steps (the successfully replayed prefix).

---

## TraceStep

A single entry in a proof trace, pairing a tactic (if any) with the resulting proof state.

| Field | Type | Constraints |
|-------|------|-------------|
| `step_index` | non-negative integer | Required; 0 for initial state, 1..N for tactic steps |
| `tactic` | text or null | Required; null for step 0 (initial state); the tactic string for steps 1..N |
| `state` | ProofState | Required; the proof state after this step |
| `duration_ms` | float or null | Required; null for step 0 (no tactic executed); wall-clock milliseconds for tactic execution at steps 1..N |

### Relationships

- **Contained in** one ProofTrace (via parent's `steps` list).
- **Contains** one ProofState (1:1; inline).

---

## PremiseAnnotation

The set of premises used by a single tactic step.

| Field | Type | Constraints |
|-------|------|-------------|
| `step_index` | positive integer | Required; range [1, N]; corresponds to the tactic at that step |
| `tactic` | text | Required; the tactic string |
| `premises` | list of Premise | Required; the premises this tactic used; may be empty (e.g., `reflexivity` uses no external premises) |

### Relationships

- **Associated with** one TraceStep (via `step_index`; not contained — produced by a separate query).
- **Contains** zero or more Premise objects (1:*).

---

## Premise

A single named entity that a tactic consumed or referenced during execution.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | qualified name | Required; fully qualified canonical name |
| `kind` | enumeration | Required; one of: `lemma`, `hypothesis`, `constructor`, `definition` |

### Relationships

- **Contained in** one PremiseAnnotation (via parent's `premises` list).

---

## ProofStateDiff

The delta between two consecutive proof states, showing what a tactic changed.

| Field | Type | Constraints |
|-------|------|-------------|
| `from_step` | non-negative integer | Required; the step index of the earlier state |
| `to_step` | positive integer | Required; must equal `from_step + 1` |
| `goals_added` | list of Goal | Required; goals present in `to_step` but not `from_step` |
| `goals_removed` | list of Goal | Required; goals present in `from_step` but not `to_step` |
| `goals_changed` | list of GoalChange | Required; goals at the same index with modified type |
| `hypotheses_added` | list of Hypothesis | Required; hypotheses present in `to_step` but not `from_step` (across all goals) |
| `hypotheses_removed` | list of Hypothesis | Required; hypotheses present in `from_step` but not `to_step` |
| `hypotheses_changed` | list of HypothesisChange | Required; hypotheses with the same name but modified type or body |

### Relationships

- **Derived from** two consecutive ProofState snapshots (not independently stored).

---

## GoalChange

A goal that exists at the same index in consecutive states but has a modified type.

| Field | Type | Constraints |
|-------|------|-------------|
| `index` | non-negative integer | Required; the goal index |
| `before` | text | Required; the goal type before the tactic |
| `after` | text | Required; the goal type after the tactic |

---

## HypothesisChange

A hypothesis with the same name in consecutive states but a modified type or body.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | text | Required; the hypothesis name |
| `type_before` | text | Required; the type before the tactic |
| `type_after` | text | Required; the type after the tactic |
| `body_before` | text or null | Required; the body before (null if not let-bound) |
| `body_after` | text or null | Required; the body after (null if not let-bound) |

---

## Cross-Entity Relationships

```
Session 1──* ProofState (produces on demand)
Session 1──1 ProofTrace (via extract-trace)
Session 1──* PremiseAnnotation (via premise queries)

ProofState 1──* Goal (contains, ordered)
Goal 1──* Hypothesis (contains, ordered)

ProofTrace 1──* TraceStep (contains, ordered)
TraceStep 1──1 ProofState (inline)

PremiseAnnotation 1──* Premise (contains)

ProofStateDiff ──> 2 ProofState (derived from consecutive pair)
```
