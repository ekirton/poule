# Setoid Rewriting Assistant

The component that diagnoses `setoid_rewrite` failures by parsing error messages and proof state to identify missing `Proper` instances, checks existing instances in the environment, generates `Instance Proper ...` declaration skeletons with correct `respectful` signatures, and detects when `rewrite` should be replaced with `setoid_rewrite` under binders.

**Feature**: [Setoid Rewriting Assistant](../features/setoid-rewriting-assistant.md)
**Stories**: [Epics 1–4](../requirements/stories/setoid-rewriting-assistant.md)

---

## Component Diagram

```
MCP Server
  │
  │ diagnose_rewrite(session_id, error_message?, mode?)
  ▼
┌──────────────────────────────────────────────────────────────────┐
│                Setoid Rewrite Analyzer                            │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ Error Parser                                              │   │
│  │                                                           │   │
│  │  Input: error message or proof state messages             │   │
│  │                                                           │   │
│  │  Pattern 1: "Unable to satisfy ... Proper constraint"     │   │
│  │    → extract function name, expected relation signature   │   │
│  │                                                           │   │
│  │  Pattern 2: "Found no subterm matching ..."               │   │
│  │    → check if target is under a binder                    │   │
│  │                                                           │   │
│  │  Pattern 3: typeclass resolution failure for Proper       │   │
│  │    → delegate to Typeclass Debugging for trace            │   │
│  │                                                           │   │
│  │  → ParsedError                                            │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Instance Checker                                          │   │
│  │                                                           │   │
│  │  1. Search Proper instances for the identified function   │   │
│  │     via Print Instances + Search                          │   │
│  │  2. Check if base relation has Equivalence/PreOrder       │   │
│  │  3. Check standard library coverage                       │   │
│  │                                                           │   │
│  │  → InstanceCheckResult                                    │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Signature Generator                                       │   │
│  │                                                           │   │
│  │  Input: function type, context relation, binder info      │   │
│  │                                                           │   │
│  │  1. Decompose function type into argument types           │   │
│  │  2. Map each argument type to its relation                │   │
│  │  3. Handle binders via pointwise_relation/forall_relation │   │
│  │  4. Determine variance (==>, -->, <==>)                   │   │
│  │                                                           │   │
│  │  → ProperSignature + Instance declaration skeleton        │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Proof Advisor                                             │   │
│  │                                                           │   │
│  │  Input: ProperSignature, function definition              │   │
│  │                                                           │   │
│  │  1. Try solve_proper / f_equiv feasibility check          │   │
│  │  2. Suggest manual proof skeleton if automation fails     │   │
│  │                                                           │   │
│  │  → ProofStrategy                                          │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
  │                     │                        │
  │ observe_proof_state │ coq_query              │ list_instances
  │                     │ (Check, Print,         │ trace_resolution
  │                     │  Search, About)        │
  ▼                     ▼                        ▼
Proof Session        Vernacular              Typeclass Debugging
Manager              Introspection           Component
```

The component does not own a Coq backend process. It borrows the backend associated with an active proof session and leverages the Typeclass Debugging component for resolution tracing when deeper diagnosis is needed.

## Tool Signature

```typescript
diagnose_rewrite(
  session_id: string,                // active proof session
  error_message: string | null = null,
                                     // if provided, the error to diagnose; if null, captured from session
  mode: "diagnose" | "generate" | "audit" = "diagnose",
                                     // "diagnose" = identify the problem;
                                     // "generate" = diagnose + generate Instance declaration;
                                     // "audit" = bulk check for missing Proper instances
  target_function: string | null = null,
                                     // if provided, focus on this function's Proper instance
  target_relation: string | null = null
                                     // if provided, use this relation in the generated signature
) → RewriteDiagnosis
```

In `"diagnose"` mode, the component identifies the problem and reports it. In `"generate"` mode, it additionally produces the `Instance Proper ...` declaration skeleton. In `"audit"` mode, it scans the current module's definitions for functions that may need `Proper` instances (P2 feature).

## Error Parser

The Error Parser classifies the error message into one of three patterns and extracts structured information from each.

### Pattern 1: Missing Proper Constraint

Error format:
```
Tactic failure: setoid rewrite failed: Unable to satisfy the following constraints:
UNDEFINED EVARS:
 ?X42==[... |- Proper (?R1 ==> ?R2) {function_name}] (internal placeholder)
```

The parser:

1. Searches the error text for `Proper` constraints in the evar list. Each evar that contains `Proper` identifies a missing instance.
2. For each `Proper` evar, extracts:
   - **Function name**: the term after the closing parenthesis of the respectful chain.
   - **Partial signature**: the `?R1 ==> ?R2 ==> ...` chain, where `?Rn` may be concrete relations or unresolved evars.
   - **Context**: the hypothesis names and types in the evar's substitution context (the `[... |-` prefix).
3. When the signature contains unresolved evars (`?Rn`), the parser marks those positions as "relation to be determined" — the Signature Generator will fill them in.

### Pattern 2: Rewrite Under Binder

Error format:
```
Error: Found no subterm matching "{pattern}" in the current goal.
```

The parser:

1. Detects this specific error text.
2. Checks whether the pattern appears inside a binder in the current goal. It fetches the goal via `observe_proof_state` and searches for the pattern inside `forall`, `exists`, `fun`, or other binding constructs.
3. If the pattern is found under a binder, classifies this as a `BINDER_REWRITE` error. If the pattern is genuinely absent, classifies this as `PATTERN_NOT_FOUND` (not a setoid rewriting issue).

### Pattern 3: Typeclass Resolution Failure

When the error mentions typeclass resolution failure for a `Proper` goal without providing the structured evar dump, the parser delegates to the Typeclass Debugging component's resolution tracer. It:

1. Calls `trace_resolution` with the `Proper` goal extracted from the error.
2. Receives a `ResolutionTrace` from the Typeclass Debugging component.
3. Uses the trace to identify which specific instance or relation caused the resolution to fail.

This delegation avoids duplicating the resolution tracing logic.

## Instance Checker

The Instance Checker determines whether a suitable `Proper` instance already exists in the environment.

### Existing Instance Search

1. Query `Print Instances Proper` to get all registered `Proper` instances. Filter for instances whose function argument matches the target function.
2. If a matching function is found, compare the instance's relation signature against the required signature:
   - **Exact match**: the instance has exactly the right relations. Report: "Instance exists; ensure it is in scope."
   - **Compatible match**: the instance uses a stronger relation (e.g., `eq` where `equiv` is needed). An instance for `eq` is always compatible because Leibniz equality implies any equivalence. Report: "Instance exists with `eq`; this may suffice."
   - **Incompatible match**: the instance exists but with a different, incompatible relation. Report the mismatch.
3. If no instance is found for the target function, check whether the target function is from a well-known library (stdlib, MathComp, std++, Coquelicot) and suggest importing the module that typically provides the instance.

### Base Relation Check

Before suggesting a new `Proper` instance, verify that the base relation is registered:

1. Query `Search Equivalence {relation}` and `Search PreOrder {relation}`.
2. If neither is found, the relation is not registered and `setoid_rewrite` will fail regardless of `Proper` instances. Report this as the root cause and suggest declaring an `Equivalence` or `PreOrder` instance first.

### Standard Library Coverage Check

For rewriting under logical connectives and quantifiers, the standard library provides instances in `Coq.Classes.Morphisms_Prop`. The checker maintains a static lookup table of known instances:

| Function | Relation | Module |
|----------|----------|--------|
| `and` | `iff ==> iff ==> iff` | `Morphisms_Prop` |
| `or` | `iff ==> iff ==> iff` | `Morphisms_Prop` |
| `not` | `iff ==> iff` | `Morphisms_Prop` |
| `impl` | `iff ==> iff ==> iff` | `Morphisms_Prop` |
| `all` (forall) | `pointwise_relation A iff ==> iff` | `Morphisms_Prop` |
| `ex` (exists) | `pointwise_relation A iff ==> iff` | `Morphisms_Prop` |

When a missing instance matches one of these entries, the checker suggests `Require Import Coq.Classes.Morphisms_Prop` instead of generating a new instance.

## Signature Generator

The Signature Generator constructs the `respectful` signature for a `Proper` instance from the function's type and the context's relation requirements.

### Type Decomposition

1. Query the function's type via `coq_query("Check", function_name, session_id)`.
2. Decompose the type into argument types and return type. For `f : A -> B -> C`, the arguments are `[A, B]` and the return type is `C`.
3. For each argument type, determine the appropriate relation:
   - If the error parser identified a specific relation for this position, use it.
   - If the argument type matches the type of the rewrite lemma's LHS, use the rewrite lemma's relation.
   - If the argument type is the same as the return type and a target relation was specified, use the target relation.
   - Otherwise, default to `eq` (Leibniz equality), which is always safe but may be weaker than needed.

### Binder Handling

When the function takes a function argument (higher-order), the relation must be lifted:

- **Non-dependent function argument** (`(A -> B)`): use `pointwise_relation A R` where `R` is the relation on `B`.
- **Dependent function argument** (`forall (x : A), B x`): use `forall_relation (fun x => R x)` where `R x` is the relation on `B x`, which may itself depend on `x`.

The generator detects function arguments by checking whether the argument type is a product type (`forall` or `->`).

### Variance Determination

The default variance is covariant (`==>`). The generator adjusts when:

- **Contravariant position**: the function argument appears on the left of an implication or in a negative position. Use `-->` (flip).
- **Both positions**: when the same argument appears both covariantly and contravariantly, use `<==>` (iff-like, requires the relation to be symmetric).

Variance detection is approximate: the generator examines the function's definition (via `Print`) to determine whether arguments appear in positive or negative positions. If the definition is opaque (`Qed`), the generator defaults to `==>` and notes the uncertainty.

### Output

The generator produces:

```coq
Instance {function_name}_proper : Proper ({R1} ==> {R2} ==> ... ==> {Rout}) {function_name}.
Proof.
  (* {proof_hint} *)
Admitted.
```

The instance name follows the convention `{function_name}_proper`. The `Admitted` is a placeholder — the Proof Advisor may replace it with a concrete strategy.

## Proof Advisor

The Proof Advisor suggests how to prove the `Proper` obligation.

### Automation Check

1. Construct a `Proper` goal term from the generated signature.
2. Check whether `solve_proper` is likely to succeed. The heuristic: `solve_proper` works when the function is defined as a composition of functions that already have `Proper` instances. If the function's definition (from `Print`) consists only of applications of functions for which `Proper` instances exist, `solve_proper` is likely to work.
3. If `solve_proper` is not expected to work, check `f_equiv` — which works for goals of the form `R (f x1 ... xn) (f y1 ... yn)` by applying congruence lemmas.

### Manual Strategy

When automation is not expected to work, the advisor produces a proof skeleton:

```coq
Proof.
  unfold Proper, respectful.
  intros {x1} {y1} {H1} {x2} {y2} {H2} ... .
  (* Now prove: {Rout} ({function_name} {x1} {x2} ...) ({function_name} {y1} {y2} ...) *)
  (* using {H1} : {R1} {x1} {y1}, {H2} : {R2} {x2} {y2}, ... *)
Admitted.
```

The variable and hypothesis names are generated from the relation names. The comments guide the user on what remains to prove.

## Data Structures

### ParsedError

| Field | Type | Description |
|-------|------|-------------|
| `error_class` | string | `"missing_proper"`, `"binder_rewrite"`, `"missing_equivalence"`, `"pattern_not_found"` |
| `function_name` | string or null | The function lacking a `Proper` instance (null for `binder_rewrite`) |
| `partial_signature` | list of RelationSlot | Partially resolved signature from the error |
| `binder_type` | string or null | `"forall"`, `"exists"`, `"fun"`, or null if not a binder issue |
| `rewrite_target` | string or null | The pattern that was being rewritten |
| `raw_error` | string | The original error message |

### RelationSlot

| Field | Type | Description |
|-------|------|-------------|
| `position` | non-negative integer | Argument position (0-indexed) |
| `relation` | string or null | Resolved relation name, or null if unresolved |
| `argument_type` | string | The type at this position |
| `variance` | string | `"covariant"`, `"contravariant"`, or `"invariant"` |

### InstanceCheckResult

| Field | Type | Description |
|-------|------|-------------|
| `existing_instances` | list of ExistingInstance | `Proper` instances found for the target function |
| `base_relation_registered` | boolean | Whether the base relation has an `Equivalence`/`PreOrder` instance |
| `base_relation_class` | string or null | `"Equivalence"`, `"PreOrder"`, `"PER"`, or null if not registered |
| `stdlib_suggestion` | string or null | `Require Import` suggestion if a stdlib instance covers the need |

### ExistingInstance

| Field | Type | Description |
|-------|------|-------------|
| `instance_name` | string | Fully qualified instance name |
| `signature` | string | Pretty-printed `Proper` signature |
| `compatibility` | string | `"exact_match"`, `"compatible"`, or `"incompatible"` |
| `incompatibility_detail` | string or null | Explanation of mismatch if incompatible |

### ProperSignature

| Field | Type | Description |
|-------|------|-------------|
| `function_name` | string | The function this instance is for |
| `slots` | list of RelationSlot | Fully resolved relation at each position |
| `return_relation` | string | The relation on the output type |
| `declaration` | string | The complete `Instance Proper ...` declaration text |

### ProofStrategy

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | string | `"solve_proper"`, `"f_equiv"`, or `"manual"` |
| `confidence` | string | `"high"` (automation expected to work), `"medium"` (may work), `"low"` (manual likely needed) |
| `proof_skeleton` | string | Proof script text (complete for automation, skeleton with comments for manual) |

### RewriteDiagnosis

| Field | Type | Description |
|-------|------|-------------|
| `parsed_error` | ParsedError | Classified and parsed error information |
| `instance_check` | InstanceCheckResult | Results of checking existing instances |
| `generated_signature` | ProperSignature or null | Generated instance declaration (null in diagnose-only mode) |
| `proof_strategy` | ProofStrategy or null | Suggested proof approach (null in diagnose-only mode) |
| `suggestion` | string | Plain-language summary of the diagnosis and recommended action |

## Integration with Existing Components

### Proof Session Manager

The Setoid Rewrite Analyzer borrows the session backend for proof state observation and Coq queries. Same contract as Typeclass Debugging:

1. **Session required**: All operations require an active proof session.
2. **State preservation**: All queries are read-only. The analyzer does not submit tactics or modify the proof state.
3. **Concurrency**: Serialized access to the session backend.

### Vernacular Introspection

The analyzer uses `coq_query` for:
- `Check {function}` — to obtain the function's type for signature generation.
- `Print {function}` — to inspect the function's definition for variance analysis and `solve_proper` feasibility.
- `Print Instances Proper` — to list existing `Proper` instances.
- `Search Proper {function}` — to find `Proper` instances for a specific function.
- `Search Equivalence {relation}` — to check if the base relation is registered.
- `About {name}` — to check module membership for import suggestions.

### Typeclass Debugging Component

The analyzer delegates to the Typeclass Debugging component (same architecture doc) when the error parser encounters a typeclass resolution failure that needs deeper analysis. Specifically:

- **Resolution tracing**: When the error is a `Proper` resolution failure, the analyzer calls the Resolution Tracer to obtain a `ResolutionTrace` showing which `Proper` instances were tried and why they failed.
- **Instance listing**: The analyzer reuses the Instance Inspector to enumerate `Proper` instances rather than reimplementing `Print Instances` parsing.

This reuse means the Setoid Rewrite Analyzer has a runtime dependency on the Typeclass Debugging component. Both components borrow the same session backend; they do not conflict because the analyzer serializes all calls.

### Assumption Auditing (for audit mode)

In `"audit"` mode, the analyzer scans all definitions in the current module. For each definition that takes arguments of types with registered equivalence relations, it checks whether a `Proper` instance exists. This uses the `module_summary` tool to enumerate definitions and then the Instance Checker on each.

## Error Handling

| Condition | Error Code | Message |
|-----------|------------|---------|
| No active session | `SESSION_NOT_FOUND` | Rewrite diagnosis requires an active proof session. |
| Error message not recognized | `UNRECOGNIZED_ERROR` | Could not parse the error message as a rewriting failure. Raw message included in response. |
| Function type could not be retrieved | `TYPE_ERROR` | Could not retrieve the type of `{function}`. Ensure it is in scope. |
| Function definition is opaque | `OPAQUE_DEFINITION` | `{function}` is opaque (closed with `Qed`). Variance analysis may be inaccurate; defaulting to covariant. |
| No Coq session messages available | `NO_ERROR_CONTEXT` | No error messages found in the session. Provide the error message explicitly via the `error_message` parameter. |
| Backend crash | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |

When the error message is not recognized (`UNRECOGNIZED_ERROR`), the raw message is included so the LLM can still attempt interpretation. This parallels the degraded-mode pattern in Typeclass Debugging.

When a function definition is opaque (`OPAQUE_DEFINITION`), the analyzer proceeds with default covariant variance rather than failing. The generated instance may need manual variance correction; the diagnostic notes this.

## Design Rationale

### Why delegate to Typeclass Debugging rather than reimplement resolution tracing

Setoid rewriting failures are, at their core, typeclass resolution failures for `Proper` goals. The Typeclass Debugging component already implements resolution tracing, search tree parsing, and failure classification. Reimplementing this for `Proper`-specific goals would duplicate logic and risk inconsistency. Delegation means improvements to typeclass debugging (e.g., better trace parsing for new Coq versions) automatically benefit setoid rewriting diagnosis.

### Why a static lookup table for standard library instances

The standard library's `Morphisms_Prop` module provides `Proper` instances for a fixed, small set of logical connectives and quantifiers. This set changes rarely (on the order of once per major Coq release). A static lookup table is simpler, faster, and more reliable than querying the environment — it works even when `Morphisms_Prop` is not yet imported, which is exactly the case where the suggestion is most useful. The table is maintained as a data constant, not generated at runtime.

### Why default to `eq` for unknown argument relations

When the Signature Generator cannot determine the correct relation for an argument position, Leibniz equality (`eq`) is the safe default. `Proper (eq ==> R) f` means "f produces R-related outputs for equal inputs" — this is trivially true for any function and any relation R (by congruence). The generated instance may be weaker than optimal (the user might want `equiv ==> R`), but it will type-check and satisfy the immediate `setoid_rewrite` requirement. The user can strengthen the instance later. A wrong relation, by contrast, would produce a type error or an unprovable obligation.

### Why variance detection is approximate

Determining the exact variance of a function argument requires analyzing the function's definition to find whether the argument appears in positive or negative positions — essentially a polarity analysis. For transparent definitions, this is feasible by inspecting the term structure. For opaque definitions (closed with `Qed`), the definition is not available and variance cannot be determined. Rather than failing on opaque definitions, the analyzer defaults to covariant (`==>`) and reports the uncertainty. The user can override with `-->` or `<==>` if needed. This design prioritizes availability over precision: producing a usable (if slightly wrong) instance is better than producing nothing.

### Why the Error Parser handles three distinct patterns

The three patterns — missing `Proper` constraint, rewrite under binder, and typeclass resolution failure — are the three ways a rewriting failure manifests to the user. They have different error message formats, different root causes, and different fixes. A single-pattern parser would miss two-thirds of the cases. Each pattern has its own extraction logic because the information in the error message is structured differently: the evar dump in pattern 1 encodes the missing signature; pattern 2 has no signature information at all (it's a discoverability problem); pattern 3 requires trace analysis. Handling all three in one component means the user gets a consistent diagnostic interface regardless of which failure mode they hit.
