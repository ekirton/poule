# Setoid Rewriting Assistant — Specification

**Architecture**: [setoid-rewriting-assistant.md](../doc/architecture/setoid-rewriting-assistant.md)

---

## 1. Purpose

Diagnose `setoid_rewrite` failures by identifying missing `Proper` instances, check whether suitable instances already exist, generate `Instance Proper ...` declaration skeletons with correct `respectful` signatures, and detect when `rewrite` should be replaced with `setoid_rewrite` under binders.

## 2. Scope

**In scope:**
- Error parsing for three failure patterns: missing `Proper` constraint, rewrite under binder, typeclass resolution failure
- Existing instance lookup via `Print Instances` and `Search`
- Base relation registration check (`Equivalence`/`PreOrder`)
- Standard library coverage check against a static lookup table
- Signature generation with type decomposition, binder handling, and variance detection
- Proof strategy suggestion (`solve_proper`, `f_equiv`, manual skeleton)
- Bulk morphism coverage audit (P2, `"audit"` mode)

**Out of scope:**
- Modifying Coq's setoid rewriting engine or error messages
- Completing `Proper` proof obligations (skeleton only, not proof body)
- Standalone morphism database beyond Coq's typeclass system
- IDE plugins — accessed via Claude Code MCP integration
- Rewriting frameworks outside Coq (Lean `simp`, Isabelle `transfer`)

## 3. Definitions

| Term | Definition |
|------|------------|
| Proper instance | A typeclass instance `Proper (R1 ==> R2 ==> ... ==> Rout) f` declaring that function `f` maps related inputs to related outputs. |
| Respectful (`==>`) | The combinator `respectful R S : relation (A -> B)` defined as `fun f g => forall x y, R x y -> S (f x) (g y)`. Covariant lifting. |
| Flip respectful (`-->`) | Contravariant variant: `fun f g => forall x y, R y x -> S (f x) (g y)`. |
| pointwise_relation | `pointwise_relation A R : relation (A -> B)` defined as `fun f g => forall a, R (f a) (g a)`. Used for rewriting under non-dependent binders. |
| forall_relation | `forall_relation (R : forall a, relation (B a))`. Used for rewriting under dependent binders. |
| Base relation | The equivalence or preorder relation that the user's `setoid_rewrite` operates over. Must be registered as an `Equivalence` or `PreOrder` instance. |
| Variance | Whether an argument appears in a covariant (`==>`), contravariant (`-->`), or invariant (`<==>`) position. |

## 4. Behavioral Requirements

### 4.1 diagnose_rewrite(session_id, error_message, mode, target_function, target_relation)

- REQUIRES: `session_id` references an active proof session. `mode` is one of `"diagnose"`, `"generate"`, `"audit"`. When `error_message` is null, the session must have recent messages. When `target_function` is non-null, it is a valid identifier in scope.
- ENSURES: Returns a `RewriteDiagnosis`. In `"diagnose"` mode, `generated_signature` and `proof_strategy` are null. In `"generate"` mode, they are populated. In `"audit"` mode, diagnosis runs per-definition across the current module.
- MAINTAINS: The session's proof state is unchanged. No Coq state is modified.

### 4.2 Error parsing

#### 4.2.1 Pattern 1: Missing Proper constraint

When the error text contains `"Proper"` within an evar constraint of the form `?X==[... |- Proper (... ==> ...) {function}]`, the parser shall extract:

1. The function name from the term after the respectful chain.
2. The partial signature from the `==>` chain, marking evar positions as unresolved.
3. The hypothesis context from the `[... |-` prefix.

- ENSURES: `ParsedError.error_class` = `"missing_proper"`. `ParsedError.function_name` is non-null. `ParsedError.partial_signature` contains one `RelationSlot` per argument position.

> Given error: `"setoid rewrite failed: Unable to satisfy the following constraints: ?X42==[H : equiv x y |- Proper (?R1 ==> eq_set) union]"`
> When error parsing runs
> Then `function_name` = `"union"`, `partial_signature` = `[{position: 0, relation: null, variance: "covariant"}, {position: 1, relation: "eq_set", variance: "covariant"}]`, `error_class` = `"missing_proper"`.

#### 4.2.2 Pattern 2: Rewrite under binder

When the error text matches `"Found no subterm matching"` and the quoted pattern appears inside a `forall`, `exists`, or `fun` in the current goal (fetched via `observe_proof_state`), the parser shall classify the error as `"binder_rewrite"`.

- REQUIRES: A proof session with an observable goal.
- ENSURES: `ParsedError.error_class` = `"binder_rewrite"`. `ParsedError.binder_type` is one of `"forall"`, `"exists"`, `"fun"`. `ParsedError.rewrite_target` contains the pattern.

When the pattern is genuinely absent from the goal (not under a binder), `ParsedError.error_class` = `"pattern_not_found"`.

> Given error: `"Found no subterm matching \"P x\" in the current goal"` and goal `forall x, P x /\ Q x`
> When error parsing runs
> Then `error_class` = `"binder_rewrite"`, `binder_type` = `"forall"`, `rewrite_target` = `"P x"`.

> Given error: `"Found no subterm matching \"R x\" in the current goal"` and goal `P x /\ Q x` (R does not appear)
> When error parsing runs
> Then `error_class` = `"pattern_not_found"`.

#### 4.2.3 Pattern 3: Typeclass resolution failure

When the error mentions typeclass resolution failure for a `Proper` goal but does not provide the structured evar dump, the parser shall delegate to the Typeclass Debugging component's `trace_resolution`.

- REQUIRES: Typeclass Debugging component is available.
- ENSURES: `ParsedError` is populated from the `ResolutionTrace` returned by the Typeclass Debugging component. `error_class` = `"missing_proper"` when resolution found no matching instance.

#### 4.2.4 Unrecognized error

When the error text does not match any of the three patterns, the component shall return `UNRECOGNIZED_ERROR` with the raw error message included.

### 4.3 Instance checking

#### 4.3.1 Existing instance search

The Instance Checker shall query `Print Instances Proper` and filter for instances whose function argument matches `target_function`. For each match, the checker shall classify compatibility:

| Condition | Classification |
|-----------|---------------|
| Instance signature exactly matches required signature | `"exact_match"` |
| Instance uses `eq` where a weaker relation is needed | `"compatible"` |
| Instance uses a different, incompatible relation | `"incompatible"` |

- ENSURES: `InstanceCheckResult.existing_instances` contains all matching instances with classifications. When no instances match, the list is empty.

> Given `Print Instances Proper` returns an instance `Proper (eq ==> eq ==> eq_set) union`
> When checking for `Proper (eq_set ==> eq_set ==> eq_set) union`
> Then classification = `"incompatible"`, detail = "Instance uses `eq` for argument 0 but `eq_set` is required".

> Given `Print Instances Proper` returns an instance `Proper (eq ==> eq_set ==> eq_set) union`
> When checking for `Proper (eq ==> eq_set ==> eq_set) union`
> Then classification = `"exact_match"`.

#### 4.3.2 Base relation check

Before suggesting a new instance, the component shall query `Search Equivalence {relation}` and `Search PreOrder {relation}`.

- ENSURES: `InstanceCheckResult.base_relation_registered` is true when the base relation has an `Equivalence` or `PreOrder` instance. `base_relation_class` is `"Equivalence"`, `"PreOrder"`, `"PER"`, or null.
- When the base relation is not registered, `ParsedError.error_class` shall be updated to `"missing_equivalence"` and `RewriteDiagnosis.suggestion` shall recommend declaring the relational instance before the `Proper` instance.

> Given relation `my_equiv` with no `Equivalence` instance
> When base relation check runs
> Then `base_relation_registered` = false, suggestion = "Declare `Instance my_equiv_equiv : Equivalence my_equiv` before declaring Proper instances."

#### 4.3.3 Standard library coverage check

The Instance Checker shall maintain a static lookup table:

| Function | Signature | Module |
|----------|-----------|--------|
| `and` | `iff ==> iff ==> iff` | `Coq.Classes.Morphisms_Prop` |
| `or` | `iff ==> iff ==> iff` | `Coq.Classes.Morphisms_Prop` |
| `not` | `iff ==> iff` | `Coq.Classes.Morphisms_Prop` |
| `impl` | `iff ==> iff ==> iff` | `Coq.Classes.Morphisms_Prop` |
| `all` | `pointwise_relation A iff ==> iff` | `Coq.Classes.Morphisms_Prop` |
| `ex` | `pointwise_relation A iff ==> iff` | `Coq.Classes.Morphisms_Prop` |

When a missing instance matches a table entry, `InstanceCheckResult.stdlib_suggestion` shall contain `"Require Import Coq.Classes.Morphisms_Prop."`.

> Given missing `Proper` instance for `and` with `iff`
> When stdlib check runs
> Then `stdlib_suggestion` = `"Require Import Coq.Classes.Morphisms_Prop."`.

### 4.4 Signature generation

#### 4.4.1 Type decomposition

The Signature Generator shall query `Check {function}` and decompose the type into argument types and return type.

- REQUIRES: `target_function` is in scope.
- ENSURES: `ProperSignature.slots` has one entry per argument position with `argument_type` populated.

#### 4.4.2 Relation assignment

For each argument position, the generator shall assign a relation using the following priority:

1. Use the relation from `ParsedError.partial_signature` if resolved at this position.
2. Use `target_relation` if the argument type matches the return type and `target_relation` is non-null.
3. Default to `eq`.

- ENSURES: Every `RelationSlot.relation` is non-null after generation.

> Given function `f : A -> B -> C`, partial_signature has `eq_set` at position 1, target_relation = null
> When relation assignment runs
> Then slot 0 relation = `"eq"`, slot 1 relation = `"eq_set"`.

#### 4.4.3 Binder handling

When an argument type is a product type (`forall` or `->`):

| Argument type | Generated relation |
|---------------|-------------------|
| `A -> B` (non-dependent) | `pointwise_relation A {R_B}` where `R_B` is the relation on `B` |
| `forall (x : A), B x` (dependent) | `forall_relation (fun x => {R_Bx})` where `R_Bx` is the relation on `B x` |

- ENSURES: Higher-order argument positions use the appropriate lifted relation.

#### 4.4.4 Variance determination

The default variance is covariant (`==>`). When the function definition is transparent (queryable via `Print`), the generator shall examine whether each argument appears in positive or negative positions:

| Position | Variance | Combinator |
|----------|----------|------------|
| Positive only | Covariant | `==>` |
| Negative only | Contravariant | `-->` |
| Both | Invariant | `<==>` |

When the function definition is opaque (`Qed`), the generator shall default to `==>` for all positions and set `OPAQUE_DEFINITION` as a warning (non-fatal).

#### 4.4.5 Declaration output

- ENSURES: `ProperSignature.declaration` is a syntactically valid Coq `Instance` declaration of the form:
  ```
  Instance {function}_proper : Proper ({R1} ==> {R2} ==> ... ==> {Rout}) {function}.
  ```
  The instance name follows the convention `{function_name}_proper`.

### 4.5 Proof strategy suggestion

#### 4.5.1 Automation feasibility

The Proof Advisor shall check `solve_proper` feasibility by examining the function definition (via `Print`). When the definition consists only of applications of functions for which `Proper` instances exist (checked via `Search Proper {callee}`), the advisor shall set `ProofStrategy.strategy` = `"solve_proper"` with `confidence` = `"high"`.

When `solve_proper` is not expected to work but the goal has the form `R (f x1 ... xn) (f y1 ... yn)`, the advisor shall suggest `f_equiv` with `confidence` = `"medium"`.

Otherwise, the advisor shall produce a manual skeleton with `confidence` = `"low"`.

#### 4.5.2 Manual proof skeleton

- ENSURES: `ProofStrategy.proof_skeleton` contains:
  ```
  Proof.
    unfold Proper, respectful.
    intros {x1} {y1} {H1} ... .
    (* prove: {Rout} ({f} {x1} ...) ({f} {y1} ...) *)
    (* using: {H1} : {R1} {x1} {y1}, ... *)
  Admitted.
  ```
  Variable names are generated from argument positions. Hypothesis names follow `H{n}` convention. Comments describe the remaining obligation.

> Given `Proper (eq_set ==> eq_set ==> eq_set) union`, function is compositional
> When proof strategy is computed
> Then strategy = `"solve_proper"`, confidence = `"high"`, proof_skeleton = `"Proof. solve_proper. Qed."`.

> Given `Proper (my_rel ==> my_rel) my_opaque_fun`, function is opaque
> When proof strategy is computed
> Then strategy = `"manual"`, confidence = `"low"`, proof_skeleton includes `unfold Proper, respectful. intros x1 y1 H1.`.

## 5. Data Model

### ParsedError

| Field | Type | Constraints |
|-------|------|-------------|
| `error_class` | string | Required; one of `"missing_proper"`, `"binder_rewrite"`, `"missing_equivalence"`, `"pattern_not_found"` |
| `function_name` | string or null | Required for `"missing_proper"` and `"missing_equivalence"`; null for `"binder_rewrite"` and `"pattern_not_found"` |
| `partial_signature` | ordered list of RelationSlot | Required; may be empty for `"binder_rewrite"` and `"pattern_not_found"` |
| `binder_type` | string or null | Non-null only for `"binder_rewrite"`; one of `"forall"`, `"exists"`, `"fun"` |
| `rewrite_target` | string or null | Non-null for `"binder_rewrite"` and `"pattern_not_found"` |
| `raw_error` | string | Required; the original error message text |

### RelationSlot

| Field | Type | Constraints |
|-------|------|-------------|
| `position` | non-negative integer | Required; 0-indexed argument position |
| `relation` | string or null | Null when unresolved (from error parsing); non-null after signature generation |
| `argument_type` | string | Required; Coq type at this position |
| `variance` | string | Required; one of `"covariant"`, `"contravariant"`, `"invariant"` |

### InstanceCheckResult

| Field | Type | Constraints |
|-------|------|-------------|
| `existing_instances` | ordered list of ExistingInstance | Required; may be empty |
| `base_relation_registered` | boolean | Required |
| `base_relation_class` | string or null | Non-null when `base_relation_registered` is true; one of `"Equivalence"`, `"PreOrder"`, `"PER"` |
| `stdlib_suggestion` | string or null | Non-null when a standard library import would resolve the issue; contains a `Require Import` statement |

### ExistingInstance

| Field | Type | Constraints |
|-------|------|-------------|
| `instance_name` | string | Required; fully qualified instance name |
| `signature` | string | Required; pretty-printed `Proper` signature |
| `compatibility` | string | Required; one of `"exact_match"`, `"compatible"`, `"incompatible"` |
| `incompatibility_detail` | string or null | Non-null only when `compatibility` = `"incompatible"` |

### ProperSignature

| Field | Type | Constraints |
|-------|------|-------------|
| `function_name` | string | Required; the function this instance is for |
| `slots` | ordered list of RelationSlot | Required; all `relation` fields non-null (fully resolved) |
| `return_relation` | string | Required; the relation on the output type |
| `declaration` | string | Required; syntactically valid `Instance Proper ...` declaration text |

### ProofStrategy

| Field | Type | Constraints |
|-------|------|-------------|
| `strategy` | string | Required; one of `"solve_proper"`, `"f_equiv"`, `"manual"` |
| `confidence` | string | Required; one of `"high"`, `"medium"`, `"low"` |
| `proof_skeleton` | string | Required; Coq proof script text; complete for automation strategies, skeleton with comments for `"manual"` |

### RewriteDiagnosis

| Field | Type | Constraints |
|-------|------|-------------|
| `parsed_error` | ParsedError | Required |
| `instance_check` | InstanceCheckResult | Required |
| `generated_signature` | ProperSignature or null | Null in `"diagnose"` mode |
| `proof_strategy` | ProofStrategy or null | Null in `"diagnose"` mode |
| `suggestion` | string | Required; plain-language summary of diagnosis and recommended action |

## 6. Interface Contracts

### Setoid Rewrite Analyzer → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `observe_proof_state` (read goal for binder detection) |
| Concurrency | Serialized — one command at a time per session backend |
| State preservation | All operations are read-only; proof state is never modified |
| Error strategy | `SESSION_NOT_FOUND` → return error immediately. `BACKEND_CRASHED` → return error immediately. |

### Setoid Rewrite Analyzer → Vernacular Introspection

| Property | Value |
|----------|-------|
| Operations used | `coq_query` with commands: `Check`, `Print`, `About`, `Search`, `Print Instances Proper` |
| Concurrency | Serialized — shares session backend |
| Error strategy | `Check` failure → `TYPE_ERROR`. `Print` opaque → `OPAQUE_DEFINITION` (non-fatal, continue with defaults). |

### Setoid Rewrite Analyzer → Typeclass Debugging Component

| Property | Value |
|----------|-------|
| Operations used | `trace_resolution` (for Pattern 3 errors), `list_instances` (for instance enumeration) |
| Concurrency | Serialized — same session backend; calls do not overlap |
| Availability | Required dependency; component fails gracefully if Typeclass Debugging is unavailable (falls back to `Print Instances` directly) |
| Error strategy | Resolution trace failure → return `ParsedError` with `raw_error` populated; LLM interprets manually. |

## 7. State and Lifecycle

The Setoid Rewrite Analyzer is stateless. Each `diagnose_rewrite` call is independent — no data is persisted between invocations. The static standard library lookup table (§4.3.3) is a compile-time constant, not runtime state.

In `"audit"` mode, the component iterates over definitions in the current module (via `module_summary`). Each definition is checked independently. Failure on one definition does not abort the audit; the definition is recorded with an error and the audit continues.

## 8. Error Specification

| Condition | Error Code | Behavior |
|-----------|------------|----------|
| `session_id` does not reference an active session | `SESSION_NOT_FOUND` | Return error immediately: "Rewrite diagnosis requires an active proof session." |
| Error text does not match any of the three patterns | `UNRECOGNIZED_ERROR` | Return error with raw message: "Could not parse the error message as a rewriting failure." Include raw error text in response for LLM interpretation. |
| `Check {function}` fails (function not in scope) | `TYPE_ERROR` | Return error: "Could not retrieve the type of `{function}`. Ensure it is in scope." |
| `Print {function}` returns opaque definition | `OPAQUE_DEFINITION` | Non-fatal warning. Continue with default covariant variance. Include note: "`{function}` is opaque. Variance analysis defaulted to covariant; manual adjustment may be needed." |
| `error_message` is null and no messages in session buffer | `NO_ERROR_CONTEXT` | Return error: "No error messages found in the session. Provide the error message explicitly." |
| Coq backend process has crashed | `BACKEND_CRASHED` | Return error immediately: "The Coq backend has crashed. Close the session and open a new one." |
| Typeclass Debugging component unavailable (Pattern 3) | `PARSE_ERROR` | Fall back to `Print Instances Proper` direct query. Return parsed result with degraded confidence. |
| Audit mode: `module_summary` fails | `PARSE_ERROR` | Return error: "Could not enumerate module definitions." Include raw output. |

## 9. Non-Functional Requirements

- `diagnose_rewrite` in `"diagnose"` mode shall complete within 3 seconds for standard proof states.
- `diagnose_rewrite` in `"generate"` mode shall complete within 5 seconds.
- `diagnose_rewrite` in `"audit"` mode shall complete within 30 seconds for modules with up to 100 definitions.
- Error parsing shall handle error messages up to 50,000 characters without truncation.
- The static standard library lookup table shall contain at most 20 entries (currently 6).
- The component shall not spawn additional OS processes.
- Generated `Instance` declaration strings shall not exceed 2,000 characters.

## 10. Examples

### Example 1: Missing Proper instance — diagnose and generate

> Given a proof session where `setoid_rewrite H` failed with:
>   `"setoid rewrite failed: Unable to satisfy ... ?X42==[... |- Proper (?R ==> eq_set) union]"`
>   and `union : set A -> set A -> set A`
>   and `eq_set` has an `Equivalence` instance
>   and no existing `Proper` instance for `union`
>
> When `diagnose_rewrite(session_id, error_text, "generate", null, null)` is called
>
> Then:
>   - `parsed_error.error_class` = `"missing_proper"`
>   - `parsed_error.function_name` = `"union"`
>   - `instance_check.existing_instances` = `[]`
>   - `instance_check.base_relation_registered` = true
>   - `generated_signature.declaration` = `"Instance union_proper : Proper (eq_set ==> eq_set ==> eq_set) union."`
>   - `proof_strategy.strategy` = `"manual"` or `"solve_proper"`
>   - `suggestion` = "Function `union` needs a `Proper` instance for `eq_set`. No existing instance found."

### Example 2: Rewrite under binder — suggest setoid_rewrite

> Given a proof session where `rewrite H` failed with:
>   `"Found no subterm matching \"P x\" in the current goal"`
>   and the goal is `forall x, P x /\ Q x`
>   and `H : forall x, P x <-> P' x`
>   and `Morphisms_Prop` is not imported
>
> When `diagnose_rewrite(session_id, error_text, "diagnose", null, null)` is called
>
> Then:
>   - `parsed_error.error_class` = `"binder_rewrite"`
>   - `parsed_error.binder_type` = `"forall"`
>   - `instance_check.stdlib_suggestion` = `"Require Import Coq.Classes.Morphisms_Prop."`
>   - `suggestion` = "Use `setoid_rewrite H` instead of `rewrite H`. The target is under a `forall`, which `rewrite` cannot enter. Import `Morphisms_Prop` for the required `Proper` instances."

### Example 3: Missing base relation

> Given a `setoid_rewrite` failure for relation `my_equiv` with no `Equivalence` instance
>
> When `diagnose_rewrite(session_id, error_text, "generate", "f", "my_equiv")` is called
>
> Then:
>   - `instance_check.base_relation_registered` = false
>   - `suggestion` includes "Declare `Instance : Equivalence my_equiv` before declaring Proper instances."
>   - `generated_signature` is null (cannot generate without registered relation)

## 11. Language-Specific Notes

- Package location: `src/poule/setoid/`
- Entry point: `async def diagnose_rewrite(session_id: str, error_message: str | None, mode: str, target_function: str | None, target_relation: str | None) -> RewriteDiagnosis`
- Error parsing uses regex patterns:
  - Pattern 1: `r'\?X\d+==[^|]*\|-\s*Proper\s*\(([^)]+)\)\s*(\S+)\]'`
  - Pattern 2: `r'Found no subterm matching "([^"]+)"'`
- Binder detection scans the goal string for `forall`, `exists`, `fun` using `re.search(r'\b(forall|exists|fun)\b.*' + re.escape(pattern), goal_text)`.
- The standard library lookup table is a `dict[str, tuple[str, str]]` mapping function name to `(signature, module)`.
- Variance detection uses a simple polarity tracker: positive context starts at the goal, each `->` on the left flips polarity. This is implemented as a recursive descent on the `Print` output.
- Error class and strategy names are `StrEnum` types.
- Constants: `DIAGNOSE_TIMEOUT_SECONDS = 5`, `AUDIT_TIMEOUT_SECONDS = 30`, `MAX_ERROR_LENGTH = 50_000`, `STDLIB_LOOKUP_TABLE` (6 entries).
- The Typeclass Debugging dependency is a soft dependency: when unavailable, the component falls back to direct `Print Instances Proper` queries with reduced diagnostic quality.
