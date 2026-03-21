# Typeclass Debugging

The component that wraps Coq's typeclass-related vernacular commands, parses their unstructured output into structured data, and provides the MCP server with instance listing, resolution tracing, failure explanation, and conflict detection capabilities.

**Feature**: [Typeclass Debugging](../features/typeclass-debugging.md)

---

## Component Diagram

```
MCP Server
  |
  | typeclass debugging tool calls
  v
+---------------------------------------------------------------+
|                  Typeclass Debug Component                     |
|                                                               |
|  +-------------------------+  +----------------------------+  |
|  | Instance Inspector      |  | Resolution Tracer          |  |
|  |                         |  |                            |  |
|  | Print Instances <class> |  | Set Typeclasses Debug      |  |
|  | Print Typeclasses       |  | Debug output capture       |  |
|  |                         |  | Trace parser               |  |
|  | -> TypeclassInfo[]      |  | -> ResolutionTrace         |  |
|  +-------------------------+  +----------------------------+  |
|                                                               |
|  +-------------------------+  +----------------------------+  |
|  | Failure Analyzer        |  | Conflict Detector          |  |
|  |                         |  |                            |  |
|  | Reads ResolutionTrace   |  | Reads ResolutionTrace +   |  |
|  | Classifies failure mode |  |   instance list            |  |
|  | Identifies root cause   |  | Identifies overlapping    |  |
|  |                         |  |   instances                |  |
|  | -> FailureExplanation   |  | -> InstanceConflict[]     |  |
|  +-------------------------+  +----------------------------+  |
|                                                               |
+---------------------------------------------------------------+
  |                         |
  | session operations      | Coq vernacular commands
  v                         v
Proof Session Manager     Coq Backend Process
  |                       (via session's backend)
  v
Coq Backend Process
```

The component does not own a Coq backend process. It borrows the backend associated with an active proof session to execute vernacular commands and capture their output. Instance listing (`Print Instances`, `Print Typeclasses`) does not require a proof session -- it operates on any active session's backend. Resolution tracing requires a session positioned at a proof state with an unresolved typeclass goal.

## Instance Listing

### Parsing `Print Instances` Output

The `Print Instances <class>` command produces a list of lines, each containing an instance name and its type signature. The parser:

1. Sends `Print Instances <class>` to the session backend.
2. If the response indicates the name is not a typeclass, produces a `NOT_A_TYPECLASS` error.
3. Splits the response into individual instance lines.
4. For each line, extracts:
   - **Instance name**: the fully qualified name before the colon.
   - **Type signature**: the type expression after the colon.
   - **Defining module**: derived from the fully qualified name prefix.
5. Returns a list of `TypeclassInfo` records.

An empty response (no instances) is a valid result -- it produces an empty list, not an error.

### Parsing `Print Typeclasses` Output

The `Print Typeclasses` command produces a list of all registered typeclasses. The parser:

1. Sends `Print Typeclasses` to the session backend.
2. Splits the response into individual typeclass entries.
3. For each entry, extracts the typeclass name.
4. For each typeclass, issues a follow-up `Print Instances <class>` to count registered instances.
5. Returns a list of records with typeclass name and instance count.

The follow-up `Print Instances` calls are a trade-off: one round-trip per typeclass for richer summary data. For environments with very large numbers of typeclasses, the follow-up calls may be omitted and instance counts reported as unknown.

## Resolution Tracing

### Debug Output Capture

Resolution tracing requires a proof session positioned at a goal that triggers typeclass resolution. The sequence:

1. Send `Set Typeclasses Debug Verbosity 2` to the session backend to enable verbose tracing.
2. Re-attempt resolution of the current goal (by re-submitting the tactic or triggering resolution via a diagnostic command).
3. Capture the debug output stream produced by the resolution engine.
4. Send `Unset Typeclasses Debug` to restore normal operation.

The debug flag is set and unset within a single operation. The component never leaves debug mode enabled across tool calls.

### Parsing Debug Output into a Search Tree

Coq's `Set Typeclasses Debug` output encodes the resolution search tree via indentation. Each line represents a resolution step; nesting depth indicates parent-child relationships in the search. The parser:

1. Reads the captured debug output line by line.
2. Computes the indentation level of each line (number of leading spaces, normalized to a depth integer).
3. Classifies each line by pattern matching:
   - **Goal line**: begins with a goal identifier and the typeclass constraint being resolved.
   - **Attempt line**: names the instance being tried.
   - **Success line**: indicates the attempt succeeded.
   - **Failure line**: indicates the attempt failed, optionally with a reason (unification failure, sub-goal failure).
   - **Depth limit line**: indicates the resolution depth was exceeded.
4. Constructs a tree of `ResolutionNode` records by using the indentation depth to determine parent-child relationships. A line at depth N+1 following a line at depth N is a child of that node.
5. Wraps the tree root(s) in a `ResolutionTrace` record.

The parser is tolerant of minor formatting variations across Coq versions. Unrecognized lines are preserved as raw text in the enclosing node rather than causing a parse failure.

## Failure Explanation

The Failure Analyzer consumes a `ResolutionTrace` and classifies the failure into one of three modes:

### No Matching Instance

Detected when the root node (or a sub-goal node) has zero children -- no instance was attempted. The analyzer reports:
- The typeclass being resolved.
- The concrete type arguments that lack an instance.
- The goal context (hypotheses that might provide the instance if the user imported the right module).

### Unification Failure

Detected when one or more instances were attempted but all failed with a unification error. The analyzer identifies the instance that came closest to matching by:
1. Counting how many type arguments unified successfully before the first mismatch.
2. Selecting the instance with the most successful unifications as the "closest match."
3. Reporting the specific type arguments that failed to unify and the expected vs. actual types.

### Resolution Depth Exceeded

Detected when the trace contains a depth limit line. The analyzer:
1. Extracts the resolution path from root to the depth limit node.
2. Inspects the path for repeated typeclass names, which indicate a cycle.
3. Reports the cycle (if found) or the chain length and the deepest typeclass goal reached.

The failure mode classification is exhaustive over these three cases. If the trace does not match any pattern (e.g., the trace is empty or malformed), the analyzer returns the raw trace with a note that automatic classification was not possible.

## Conflict Detection

The Conflict Detector identifies cases where multiple instances match the same goal. It operates in two modes.

### Goal-Level Conflict Detection

Given a `ResolutionTrace` for a goal:

1. Examine the root node's children. Each child represents an instance that was attempted.
2. Count how many children succeeded (the instance matched and all sub-goals were resolved).
3. If more than one child succeeded, these are conflicting instances. Report:
   - All matching instance names.
   - Which instance was actually selected (the first succeeding child, per Coq's resolution order).
   - The basis for selection: declaration order in the environment, priority hints (`|` syntax), or specificity (more specific instance preferred).

### Instance-Level Explanation

Given a specific instance name and a goal:

1. Locate the node in the resolution trace corresponding to that instance.
2. If the instance was tried and succeeded: report the unification substitution and whether it was ultimately selected or overridden by a higher-priority instance.
3. If the instance was tried and failed: report the failure reason (unification failure details or sub-goal failure).
4. If the instance does not appear in the trace: report that it was not considered a candidate, with the likely reason (wrong typeclass, not in scope, filtered by priority).

## Data Structures

**TypeclassInfo** -- a registered instance of a typeclass:

| Field | Type | Description |
|-------|------|-------------|
| `instance_name` | string | Fully qualified instance name |
| `typeclass_name` | string | Fully qualified typeclass name |
| `type_signature` | string | Pretty-printed type of the instance |
| `defining_module` | string | Module where the instance is defined |

**ResolutionTrace** -- the complete resolution trace for a goal:

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | The typeclass goal being resolved |
| `root_nodes` | list of ResolutionNode | Top-level resolution attempts |
| `succeeded` | boolean | Whether resolution succeeded overall |
| `failure_mode` | string or null | `"no_instance"`, `"unification"`, `"depth_exceeded"`, or null if succeeded |
| `raw_output` | string | The original debug output, preserved for fallback |

**ResolutionNode** -- a single node in the resolution search tree:

| Field | Type | Description |
|-------|------|-------------|
| `instance_name` | string | Instance attempted at this node |
| `goal` | string | The sub-goal this instance was applied to |
| `outcome` | string | `"success"`, `"unification_failure"`, `"subgoal_failure"`, `"depth_exceeded"` |
| `failure_detail` | string or null | Specific failure reason (e.g., "expected nat, got bool") |
| `children` | list of ResolutionNode | Sub-goal resolution attempts spawned by this instance |
| `depth` | non-negative integer | Depth in the search tree (root = 0) |

**InstanceConflict** -- an ambiguity where multiple instances match:

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | The goal with ambiguous resolution |
| `matching_instances` | list of string | Names of all instances that match |
| `selected_instance` | string | The instance that resolution actually chose |
| `selection_basis` | string | `"declaration_order"`, `"priority_hint"`, or `"specificity"` |

## Integration with Proof Sessions

Typeclass debugging operates within the context of a proof session managed by the [Proof Session Manager](proof-session.md). The integration points:

1. **Session requirement**: Resolution tracing and failure explanation require an active proof session positioned at a goal that involves typeclass resolution. The MCP server passes the `session_id` to the typeclass debug component, which borrows the session's Coq backend.

2. **Instance listing without a session**: `Print Instances` and `Print Typeclasses` are environment-level queries. They require a Coq backend but do not require a specific proof state. Any active session's backend can service these queries. If no session is active, the component returns a `SESSION_NOT_FOUND` error -- it does not manage its own backend processes.

3. **State preservation**: The component must not alter the proof state of the borrowed session. Debug flags (`Set Typeclasses Debug`) are set and unset within a single operation. If an error occurs after setting the flag, the component issues `Unset Typeclasses Debug` in a cleanup step before returning the error.

4. **Concurrency**: The component serializes access to the session backend. It does not issue concurrent commands to the same backend. This follows the same contract as the Proof Search Engine's use of sessions.

## Error Handling

| Condition | Error Code | Message |
|-----------|------------|---------|
| Name is not a typeclass | `NOT_A_TYPECLASS` | `{name}` is not a registered typeclass. |
| Typeclass not found | `NOT_FOUND` | Typeclass `{name}` not found in the current environment. |
| No active session (for tracing) | `SESSION_NOT_FOUND` | Typeclass resolution tracing requires an active proof session. |
| Session backend crashed | `BACKEND_CRASHED` | The Coq backend for session `{session_id}` has crashed. Close the session and open a new one. |
| Current goal does not involve typeclass resolution | `NO_TYPECLASS_GOAL` | The current goal does not involve typeclass resolution. |
| Debug output parsing failed | `PARSE_ERROR` | Failed to parse typeclass debug output. Raw output is included in the response. |
| Command timeout (> 5 seconds) | `TIMEOUT` | Typeclass command timed out after 5 seconds. The typeclass hierarchy may be too large. |

When debug output parsing fails, the component returns the raw output alongside the error so that the LLM can still attempt interpretation. This is a degraded mode, not a complete failure.

## Design Rationale

### Why parse debug output rather than extend coq-lsp

Coq's `Set Typeclasses Debug` and `Print Instances` commands are mature, stable, and produce all the information needed for debugging. Extending coq-lsp to expose structured typeclass resolution data would require changes to the Coq language server protocol, negotiation with upstream maintainers, and a dependency on a specific coq-lsp version. Parsing the textual output is self-contained, requires no upstream changes, and can be implemented and shipped immediately. The output format is stable across Coq versions (minor variations are handled by tolerant parsing).

### Why the LLM interpretation layer

The structured data produced by parsing is necessary but not sufficient. The raw `ResolutionTrace` may contain dozens of nodes across multiple levels. The component's role is to structure the data and classify failure modes; the LLM's role is to interpret the structured result in the context of the user's question and produce a natural-language explanation. This separation keeps the component's logic deterministic and testable while leveraging the LLM for the part of the task -- contextual explanation -- where it excels. The component does not generate natural language; it provides the structured input that makes the LLM's explanation accurate.

### Why failure mode classification is exhaustive over three cases

The three failure modes -- no matching instance, unification failure, and depth exceeded -- cover the resolution engine's possible outcomes. Resolution either finds no candidates (no instance), finds candidates that do not match (unification), or runs out of budget (depth). There is no fourth case in the resolution algorithm. By classifying exhaustively, the Failure Analyzer guarantees that every trace receives a structured explanation rather than falling through to raw output. The fallback to raw output exists only for malformed traces, not for unrecognized failure modes.

### Why conflict detection is separate from failure explanation

A conflict (multiple matching instances) is not necessarily a failure -- resolution succeeds by picking one. Conflicts are diagnostic information for library authors who need to understand instance interaction, not for users debugging a failed resolution. Keeping the Conflict Detector separate from the Failure Analyzer reflects this distinction: failure explanation answers "why did this break?"; conflict detection answers "is this ambiguous?"
