# Typeclass Debugging

Wrapping Coq's typeclass vernacular commands, parsing their unstructured output into structured data, and providing the MCP server with instance listing, resolution tracing, failure explanation, and conflict detection.

**Architecture**: [typeclass-debugging.md](../doc/architecture/typeclass-debugging.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the typeclass debugging component that inspects registered typeclass instances, traces typeclass resolution, classifies resolution failures, and detects instance conflicts -- producing structured data from Coq's unstructured debug output so the MCP server can deliver actionable typeclass diagnostics.

## 2. Scope

**In scope**: Instance listing (`Print Instances`, `Print Typeclasses`), resolution tracing (`Set Typeclasses Debug`), failure explanation (no-instance, unification failure, depth exceeded), conflict detection (goal-level and instance-level), debug output parsing, session backend borrowing, debug flag cleanup.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), natural language explanation generation (owned by the LLM layer), typeclass instance registration or modification.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Typeclass | A Coq structure registered with `Existing Class` or declared with `Class`, enabling ad-hoc polymorphism via instance resolution |
| Instance | A registered implementation of a typeclass for specific type arguments |
| Resolution trace | A tree-structured record of the typeclass resolution engine's search, captured from `Set Typeclasses Debug` output |
| Resolution node | A single step in the resolution search tree, representing one instance attempt at one sub-goal |
| Failure mode | One of three classified resolution outcomes: no matching instance, unification failure, or resolution depth exceeded |
| Instance conflict | A situation where multiple instances match the same typeclass goal |
| Session backend | The Coq backend process associated with an active proof session, borrowed by this component for command execution |

## 4. Behavioral Requirements

### 4.1 Instance Listing

#### list_instances(session_id, typeclass_name)

- REQUIRES: `session_id` references an active session in the Proof Session Manager. `typeclass_name` is a non-empty string.
- ENSURES: Sends `Print Instances <typeclass_name>.` to the session backend via the Proof Session Manager's `submit_command` operation (coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1 — coq-lsp cannot capture Print output). Parses the response into a list of TypeclassInfo records. Returns the list, which may be empty.
- MAINTAINS: The session's proof state is unchanged after the call.

> **Given** a session with `EqDec` registered and instances `EqDec_nat`, `EqDec_bool` in scope
> **When** `list_instances(session_id, "EqDec")` is called
> **Then** a list of two TypeclassInfo records is returned, one per instance, each with `instance_name`, `typeclass_name`, `type_signature`, and `defining_module` populated

> **Given** a session where `EqDec` is registered but no instances exist
> **When** `list_instances(session_id, "EqDec")` is called
> **Then** an empty list is returned (not an error)

> **Given** a session where `not_a_class` is a regular definition, not a typeclass
> **When** `list_instances(session_id, "not_a_class")` is called
> **Then** a `NOT_A_TYPECLASS` error is returned

#### list_typeclasses(session_id)

- REQUIRES: `session_id` references an active session in the Proof Session Manager.
- ENSURES: Sends `Print Typeclasses` to the session backend via the Proof Session Manager's `submit_command` operation (coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1 — coq-lsp cannot capture Print output). Parses the response into a list of records, each with typeclass name and instance count. For each typeclass, a follow-up `Print Instances <class>` is issued via `submit_command` to obtain the instance count.
- MAINTAINS: The session's proof state is unchanged after the call.

When the environment contains more than 200 typeclasses, the component shall omit follow-up `Print Instances` calls and report instance counts as `null`.

> **Given** a session with 3 registered typeclasses
> **When** `list_typeclasses(session_id)` is called
> **Then** a list of 3 records is returned, each with `typeclass_name` and `instance_count`

> **Given** a session with 500 registered typeclasses
> **When** `list_typeclasses(session_id)` is called
> **Then** a list of 500 records is returned, each with `typeclass_name` and `instance_count = null`

### 4.2 Resolution Tracing

#### trace_resolution(session_id)

- REQUIRES: `session_id` references an active proof session positioned at a goal that involves typeclass resolution.
- ENSURES: Enables verbose debug output (`Set Typeclasses Debug Verbosity 2`), re-triggers resolution of the current goal, captures debug output, disables debug output (`Unset Typeclasses Debug`), parses the captured output into a ResolutionTrace, and returns it.
- MAINTAINS: The session's proof state is unchanged after the call. Debug mode is never left enabled across tool calls -- even when an error occurs mid-operation, the component issues `Unset Typeclasses Debug` before returning.

> **Given** a proof session at goal `Decidable (eq_nat 3 4)` with instance `Decidable_eq_nat` in scope
> **When** `trace_resolution(session_id)` is called
> **Then** a ResolutionTrace is returned with `succeeded = true`, containing resolution nodes showing instance attempts

> **Given** a proof session at a goal `n + 0 = n` that does not involve typeclass resolution
> **When** `trace_resolution(session_id)` is called
> **Then** a `NO_TYPECLASS_GOAL` error is returned

> **Given** a proof session where the backend crashes during debug output capture
> **When** `trace_resolution(session_id)` is called
> **Then** a `BACKEND_CRASHED` error is returned (debug flag cleanup is impossible but the backend is already terminated)

### 4.3 Debug Output Parsing

The parser shall convert raw `Set Typeclasses Debug` output into a tree of ResolutionNode records:

1. When a line's indentation level is computed, the parser shall count leading spaces and divide by the indentation unit (detected from the first indented line) to produce a depth integer.
2. When a line matches a goal pattern, the parser shall create a ResolutionNode with the goal text.
3. When a line matches an attempt pattern, the parser shall record the instance name being tried.
4. When a line matches a success pattern, the parser shall set the enclosing node's outcome to `"success"`.
5. When a line matches a failure pattern, the parser shall set the enclosing node's outcome to `"unification_failure"` or `"subgoal_failure"` and extract the failure detail text.
6. When a line matches a depth-limit pattern, the parser shall set the enclosing node's outcome to `"depth_exceeded"`.
7. When a line at depth N+1 follows a line at depth N, the parser shall make it a child of that node.
8. When a line does not match any recognized pattern, the parser shall preserve it as raw text in the enclosing node's `failure_detail` field rather than raising a parse error.

> **Given** debug output with 3 levels of indentation showing a successful resolution
> **When** the parser processes the output
> **Then** a tree with depth up to 3 is produced, leaf nodes have `outcome = "success"`

> **Given** debug output containing an unrecognized line format
> **When** the parser processes the output
> **Then** the unrecognized line is preserved as raw text and no parse error is raised

### 4.4 Failure Explanation

#### explain_failure(resolution_trace)

- REQUIRES: `resolution_trace` is a ResolutionTrace with `succeeded = false`.
- ENSURES: Independently classifies the failure from the trace's tree structure into one of three modes and returns a FailureExplanation. The classification is exhaustive over the three modes defined below. The `trace.failure_mode` field is informational (set during trace construction as a preliminary classification) and `explain_failure` may produce a different classification based on its own tree-structure analysis.

**No Matching Instance**: When a root node has zero children (no instance was attempted), or when `root_nodes` is empty and `trace.failure_mode == "no_instance"`, the component shall report:

| Field | Content |
|-------|---------|
| `failure_mode` | `"no_instance"` |
| `typeclass` | The typeclass being resolved |
| `type_arguments` | The concrete type arguments that lack an instance |
| `goal_context` | Hypotheses available in the goal context |

> **Given** a trace where the root goal `Show (list (list nat))` has zero children
> **When** `explain_failure(trace)` is called
> **Then** a FailureExplanation with `failure_mode = "no_instance"`, `typeclass = "Show"`, and `type_arguments` including `list (list nat)` is returned

**Unification Failure**: When one or more instances were attempted but all failed with unification errors, the component shall identify the closest match:

1. Count how many type arguments unified successfully before the first mismatch per instance.
2. Select the instance with the highest count as the closest match.
3. Report the specific mismatched type arguments.

| Field | Content |
|-------|---------|
| `failure_mode` | `"unification"` |
| `closest_instance` | Name of the instance that came closest to matching |
| `successful_unifications` | Number of type arguments that matched |
| `mismatch_expected` | The type the instance expected at the point of failure |
| `mismatch_actual` | The type provided at the point of failure |

> **Given** a trace where `Eq_nat` unified 2 of 3 arguments and `Eq_bool` unified 0, for goal `Eq (nat * string)`
> **When** `explain_failure(trace)` is called
> **Then** a FailureExplanation with `failure_mode = "unification"` and `closest_instance = "Eq_nat"` is returned

**Resolution Depth Exceeded**: When the trace contains a depth-limit node, the component shall:

1. Extract the path from root to the depth-limit node.
2. Inspect the path for repeated typeclass names indicating a cycle.
3. Report the cycle or the chain depth.

| Field | Content |
|-------|---------|
| `failure_mode` | `"depth_exceeded"` |
| `resolution_path` | Ordered list of typeclass names from root to depth limit |
| `cycle_detected` | Boolean indicating whether a cycle was found |
| `cycle_typeclasses` | List of typeclass names forming the cycle, or empty if no cycle |
| `max_depth_reached` | The depth at which resolution was terminated |

> **Given** a trace with path `[Monad, Applicative, Functor, Applicative, Functor, ...]` exceeding depth 100
> **When** `explain_failure(trace)` is called
> **Then** a FailureExplanation with `failure_mode = "depth_exceeded"`, `cycle_detected = true`, and `cycle_typeclasses = ["Applicative", "Functor"]` is returned

**Fallback**: When the trace does not match any of the three modes above, the component shall return a FailureExplanation with `failure_mode = "unclassified"` and include the raw trace output. In particular, when `root_nodes` is empty and `trace.failure_mode` is not `"no_instance"`, the classification is `"unclassified"`.

### 4.5 Conflict Detection

#### detect_conflicts(resolution_trace)

- REQUIRES: `resolution_trace` is a ResolutionTrace (may be succeeded or failed).
- ENSURES: Examines root node children. When more than one child has `outcome = "success"`, returns a list of InstanceConflict records. When zero or one child succeeded, returns an empty list.

> **Given** a trace where instances `Eq_nat_stdlib` and `Eq_nat_custom` both succeed for goal `Eq nat`
> **When** `detect_conflicts(trace)` is called
> **Then** a list with one InstanceConflict is returned, listing both instances and indicating which was selected

> **Given** a trace where exactly one instance succeeded
> **When** `detect_conflicts(trace)` is called
> **Then** an empty list is returned

#### explain_instance(resolution_trace, instance_name)

- REQUIRES: `resolution_trace` is a ResolutionTrace. `instance_name` is a non-empty string.
- ENSURES: Locates the node corresponding to `instance_name` in the trace and returns its status:
  - If the instance was tried and succeeded: reports the unification substitution and whether it was selected or overridden.
  - If the instance was tried and failed: reports the failure reason.
  - If the instance does not appear in the trace: reports that it was not considered a candidate.

> **Given** a trace containing `Eq_nat` which succeeded but was overridden by `Eq_nat_fast`
> **When** `explain_instance(trace, "Eq_nat")` is called
> **Then** a report indicating `Eq_nat` succeeded but was overridden by `Eq_nat_fast` (higher priority) is returned

> **Given** a trace that does not contain `Eq_string`
> **When** `explain_instance(trace, "Eq_string")` is called
> **Then** a report indicating `Eq_string` was not considered a candidate is returned

## 5. Data Model

### TypeclassInfo

| Field | Type | Constraints |
|-------|------|-------------|
| `instance_name` | string | Required; fully qualified instance name |
| `typeclass_name` | string | Required; fully qualified typeclass name |
| `type_signature` | string | Required; pretty-printed type of the instance |
| `defining_module` | string | Required; derived from the fully qualified name prefix |

### TypeclassSummary

| Field | Type | Constraints |
|-------|------|-------------|
| `typeclass_name` | string | Required; fully qualified typeclass name |
| `instance_count` | non-negative integer or null | Null when follow-up `Print Instances` calls are omitted (> 200 typeclasses) |

### ResolutionTrace

| Field | Type | Constraints |
|-------|------|-------------|
| `goal` | string | Required; the typeclass goal being resolved |
| `root_nodes` | ordered list of ResolutionNode | Required; top-level resolution attempts; may be empty |
| `succeeded` | boolean | Required; whether resolution succeeded overall |
| `failure_mode` | `"no_instance"`, `"unification"`, `"depth_exceeded"`, or null | Null when `succeeded = true` |
| `raw_output` | string | Required; the original debug output, preserved for fallback |

### ResolutionNode

| Field | Type | Constraints |
|-------|------|-------------|
| `instance_name` | string | Required; instance attempted at this node |
| `goal` | string | Required; the sub-goal this instance was applied to |
| `outcome` | `"success"`, `"unification_failure"`, `"subgoal_failure"`, `"depth_exceeded"` | Required |
| `failure_detail` | string or null | Null when `outcome = "success"`; contains failure reason or raw unrecognized text otherwise |
| `children` | ordered list of ResolutionNode | Required; sub-goal resolution attempts; empty for leaf nodes |
| `depth` | non-negative integer | Required; root = 0 |

### FailureExplanation

| Field | Type | Constraints |
|-------|------|-------------|
| `failure_mode` | `"no_instance"`, `"unification"`, `"depth_exceeded"`, `"unclassified"` | Required |
| `typeclass` | string or null | Required for `"no_instance"` |
| `type_arguments` | list of string or null | Required for `"no_instance"` |
| `goal_context` | list of string or null | Required for `"no_instance"` |
| `closest_instance` | string or null | Required for `"unification"` |
| `successful_unifications` | non-negative integer or null | Required for `"unification"` |
| `mismatch_expected` | string or null | Required for `"unification"` |
| `mismatch_actual` | string or null | Required for `"unification"` |
| `resolution_path` | ordered list of string or null | Required for `"depth_exceeded"` |
| `cycle_detected` | boolean or null | Required for `"depth_exceeded"` |
| `cycle_typeclasses` | list of string or null | Required for `"depth_exceeded"`; empty if no cycle |
| `max_depth_reached` | non-negative integer or null | Required for `"depth_exceeded"` |
| `raw_output` | string or null | Required for `"unclassified"` |

### InstanceConflict

| Field | Type | Constraints |
|-------|------|-------------|
| `goal` | string | Required; the goal with ambiguous resolution |
| `matching_instances` | ordered list of string | Required; at least 2 entries |
| `selected_instance` | string | Required; must be a member of `matching_instances` |
| `selection_basis` | `"declaration_order"`, `"priority_hint"`, or `"specificity"` | Required |

### InstanceExplanation

| Field | Type | Constraints |
|-------|------|-------------|
| `instance_name` | string | Required |
| `status` | `"selected"`, `"succeeded_overridden"`, `"failed"`, `"not_considered"` | Required |
| `overridden_by` | string or null | Non-null only when `status = "succeeded_overridden"` |
| `failure_reason` | string or null | Non-null only when `status = "failed"` |
| `not_considered_reason` | string or null | Non-null only when `status = "not_considered"` |

## 6. Interface Contracts

### Typeclass Debug Component -> Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `submit_command` (for `Print Instances`, `Print Typeclasses`, `Set Typeclasses Debug Verbosity 2`, `Unset Typeclasses Debug` — coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1; coq-lsp cannot capture Print output) |
| Concurrency | Serialized -- one command at a time per session backend |
| Error strategy | `SESSION_NOT_FOUND` -> return error immediately. `BACKEND_CRASHED` -> return error (cleanup impossible). `TIMEOUT` -> issue `Unset Typeclasses Debug` in cleanup, then return timeout error. |
| Idempotency | Not required -- listing operations are naturally idempotent; tracing operations are stateful but leave no persistent side effects after cleanup. |
| State preservation | The component shall not alter the proof state. Debug flags are set and unset within a single operation. |

### MCP Server -> Typeclass Debug Component

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | `session_id` + operation-specific parameters (`typeclass_name` for listing, none for tracing) |
| Output | TypeclassInfo list, TypeclassSummary list, ResolutionTrace, FailureExplanation, InstanceConflict list, or InstanceExplanation |
| Error contract | All errors returned as structured error records with code and message |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Error Code | Behavior |
|-----------|------------|----------|
| `typeclass_name` is empty | `INVALID_INPUT` | Return error immediately: "Typeclass name must be non-empty." |
| `instance_name` is empty (for `explain_instance`) | `INVALID_INPUT` | Return error immediately: "Instance name must be non-empty." |
| Name is not a registered typeclass | `NOT_A_TYPECLASS` | Return error: "`{name}` is not a registered typeclass." |
| Typeclass not found in environment | `NOT_FOUND` | Return error: "Typeclass `{name}` not found in the current environment." |

### 7.2 State Errors

| Condition | Error Code | Behavior |
|-----------|------------|----------|
| No active session | `SESSION_NOT_FOUND` | Return error: "Typeclass resolution tracing requires an active proof session." |
| Current goal does not involve typeclass resolution | `NO_TYPECLASS_GOAL` | Return error: "The current goal does not involve typeclass resolution." |

### 7.3 Dependency Errors

| Condition | Error Code | Behavior |
|-----------|------------|----------|
| Session backend crashed | `BACKEND_CRASHED` | Return error: "The Coq backend for session `{session_id}` has crashed. Close the session and open a new one." |
| Command timed out (> 5 seconds) | `TIMEOUT` | Issue `Unset Typeclasses Debug` cleanup, then return error: "Typeclass command timed out after 5 seconds. The typeclass hierarchy may be too large." |
| Debug output parsing failed | `PARSE_ERROR` | Return error with raw output attached: "Failed to parse typeclass debug output. Raw output is included in the response." The raw output enables the LLM to attempt interpretation. |

### 7.4 Cleanup Guarantee

When an error occurs after `Set Typeclasses Debug Verbosity 2` has been sent but before `Unset Typeclasses Debug` has been sent, the component shall issue `Unset Typeclasses Debug` before returning the error. The sole exception is `BACKEND_CRASHED`, where cleanup is impossible because the backend process has terminated.

## 8. Non-Functional Requirements

- `list_instances` shall complete within 2 seconds for typeclasses with up to 500 registered instances.
- `list_typeclasses` shall complete within 10 seconds for environments with up to 200 typeclasses (including follow-up instance count queries).
- `trace_resolution` shall complete within 5 seconds. When the 5-second deadline is reached, the component shall capture partial output and return a `TIMEOUT` error.
- Debug output parsing shall process up to 10,000 lines of trace output without exceeding 50 MB of memory.
- The component shall not spawn additional OS processes; it reuses the session's existing backend process.

## 9. Examples

### Instance listing -- populated typeclass

```
list_instances(session_id="abc123", typeclass_name="Eq")

Backend command: Print Instances Eq.
Backend response:
  Eq_nat : Eq nat
  Eq_bool : Eq bool
  Eq_prod : forall A B, Eq A -> Eq B -> Eq (A * B)

Result:
[
  {"instance_name": "Eq_nat", "typeclass_name": "Eq", "type_signature": "Eq nat", "defining_module": "Stdlib.Classes"},
  {"instance_name": "Eq_bool", "typeclass_name": "Eq", "type_signature": "Eq bool", "defining_module": "Stdlib.Classes"},
  {"instance_name": "Eq_prod", "typeclass_name": "Eq", "type_signature": "forall A B, Eq A -> Eq B -> Eq (A * B)", "defining_module": "Stdlib.Classes"}
]
```

### Resolution tracing -- successful resolution

```
trace_resolution(session_id="abc123")

Current goal: Eq (nat * bool)

Debug output (captured):
  1: looking for Eq (nat * bool)
    1.1: trying Eq_prod
      1.1.1: looking for Eq nat
        1.1.1.1: trying Eq_nat — success
      1.1.2: looking for Eq bool
        1.1.2.1: trying Eq_bool — success
    1.1: Eq_prod — success

Result:
{
  "goal": "Eq (nat * bool)",
  "root_nodes": [
    {
      "instance_name": "Eq_prod",
      "goal": "Eq (nat * bool)",
      "outcome": "success",
      "failure_detail": null,
      "children": [
        {"instance_name": "Eq_nat", "goal": "Eq nat", "outcome": "success", "failure_detail": null, "children": [], "depth": 1},
        {"instance_name": "Eq_bool", "goal": "Eq bool", "outcome": "success", "failure_detail": null, "children": [], "depth": 1}
      ],
      "depth": 0
    }
  ],
  "succeeded": true,
  "failure_mode": null,
  "raw_output": "..."
}
```

### Failure explanation -- no matching instance

```
explain_failure(trace)  # trace for goal: Show (list (list nat))

Result:
{
  "failure_mode": "no_instance",
  "typeclass": "Show",
  "type_arguments": ["list (list nat)"],
  "goal_context": ["H : Show nat"],
  "closest_instance": null,
  "successful_unifications": null,
  "mismatch_expected": null,
  "mismatch_actual": null,
  "resolution_path": null,
  "cycle_detected": null,
  "cycle_typeclasses": null,
  "max_depth_reached": null,
  "raw_output": null
}
```

### Conflict detection -- overlapping instances

```
detect_conflicts(trace)  # trace for goal: Eq nat, with Eq_nat and Eq_nat_fast both succeeding

Result:
[
  {
    "goal": "Eq nat",
    "matching_instances": ["Eq_nat", "Eq_nat_fast"],
    "selected_instance": "Eq_nat_fast",
    "selection_basis": "priority_hint"
  }
]
```

## 10. Language-Specific Notes (Python)

- Package location: `src/poule/typeclass/`.
- Entry points: async functions `list_instances`, `list_typeclasses`, `trace_resolution`, `explain_failure`, `detect_conflicts`, `explain_instance`.
- Use `asyncio` for backend command execution via the session manager.
- Debug output parser: implement as a stateful line-by-line parser class (`TraceParser`) with an explicit stack for tree construction.
- Use `re` module for line classification (goal, attempt, success, failure, depth-limit patterns).
- Use `dataclasses` for TypeclassInfo, ResolutionTrace, ResolutionNode, FailureExplanation, InstanceConflict, InstanceExplanation.
- Cleanup guarantee: use `try`/`finally` around the debug capture sequence to ensure `Unset Typeclasses Debug` is always sent.
- The 200-typeclass threshold for omitting follow-up `Print Instances` calls is a constant (`MAX_TYPECLASSES_FOR_INSTANCE_COUNT`).
- The 5-second command timeout is a constant (`TYPECLASS_COMMAND_TIMEOUT_SECONDS`).
