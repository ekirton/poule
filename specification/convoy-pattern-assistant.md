# Convoy Pattern Assistant — Specification

**Architecture**: [convoy-pattern-assistant.md](../doc/architecture/convoy-pattern-assistant.md)

---

## 1. Purpose

Diagnose dependent-destruction failures in Coq proof states, recommend a repair technique based on axiom tolerance and proof mode, and generate the tactic or term-level boilerplate to fix the proof.

## 2. Scope

**In scope:**
- Dependency scanning: identifying which hypotheses depend on the indices of a destructed term
- Parameter/index distinction for inductive types
- Technique selection with axiom-awareness
- Boilerplate generation for revert-before-destruct, dependent destruction, convoy pattern, and Equations depelim
- Optional validation of generated code via the session backend

**Out of scope:**
- Modifying Coq's destruct tactic or match compilation
- Implementing new Coq tactics or plugins
- Automatic application of fixes without user confirmation
- Lean or Agda dependent pattern matching

## 3. Definitions

| Term | Definition |
|------|------------|
| Index | An argument of an inductive type that varies across constructors (e.g., `n` in `Fin n`). Distinguished from parameters, which are uniform across all constructors. |
| Parameter | An argument of an inductive type that is uniform across all constructors (e.g., `T` in `vec T n`). Parameters do not cause dependent-destruction problems. |
| Dependent hypothesis | A hypothesis whose type mentions one or more index variables of the target term's inductive type. |
| Convoy pattern | A technique for dependent pattern matching where dependent terms are threaded through `match` arms as function arguments in the `return` clause, causing Coq to refine their types per-branch. |
| Revert order | The order in which dependent hypotheses must be reverted before `destruct`. If `H1`'s type mentions `H2`, then `H1` is reverted first (stack discipline). |

## 4. Behavioral Requirements

### 4.1 diagnose_destruct(session_id, target, axiom_tolerance, generate_code)

- REQUIRES: `session_id` references an active proof session. When `target` is non-null, it is a valid identifier in the current proof state. `axiom_tolerance` is `"strict"` or `"permissive"`. `generate_code` is boolean.
- ENSURES: Returns a `DestructDiagnosis` containing a `DependencyReport`, a `TechniqueRecommendation`, and optionally a `GeneratedCode`.
- MAINTAINS: The session's proof state is unchanged after the call. No debug flags are left enabled.

#### 4.1.1 Target inference

When `target` is null, the component shall inspect the session's message buffer for "Abstracting over the terms ... leads to a term which is ill-typed" and extract the target term from the error. When no error message is available and `target` is null, the component shall return `TARGET_NOT_FOUND`.

> Given a session where `destruct v` just failed with "Abstracting over the terms `n` and `v`..."
> When `diagnose_destruct(session_id, null, "strict", true)` is called
> Then the target is inferred as `v` and diagnosis proceeds.

> Given a session with no recent error and target = null
> When `diagnose_destruct(session_id, null, "strict", true)` is called
> Then `TARGET_NOT_FOUND` error is returned.

#### 4.1.2 Index identification

The component shall query `Check {target}` to obtain the target's type and `Print {inductive}` to obtain the inductive type definition. The component shall classify each argument of the inductive type as a parameter or index by examining whether the argument varies across constructor signatures in the `Print` output.

- REQUIRES: The target's type is an applied inductive type (not a bare sort or function type).
- ENSURES: `DependencyReport.parameters` contains parameter names. `DependencyReport.indices` contains index names with their types. When the target type is not an indexed inductive, the component returns `NOT_INDEXED`.

> Given target `v` of type `vec nat 3`
> When index identification runs
> Then `parameters` = `["nat"]`, `indices` = `[{name: "3", type: "nat", has_decidable_eq: true}]`.

> Given target `x` of type `nat`
> When index identification runs
> Then `NOT_INDEXED` is returned with message noting `nat` has no indices.

#### 4.1.3 Hypothesis scanning

For each hypothesis in `ProofState.hypotheses`, the component shall check whether any index variable name from `DependencyReport.indices` appears as a syntactic substring in the hypothesis type string, excluding occurrences inside binding positions.

- ENSURES: `DependencyReport.dependent_hypotheses` contains all hypotheses whose types mention at least one index variable. Each entry records which indices are mentioned.
- MAINTAINS: Scanning is read-only; no Coq commands are issued beyond the initial proof state observation.

> Given indices = `["n"]` and hypotheses `H1 : P n`, `H2 : Q m`, `H3 : R n m`
> When hypothesis scanning runs
> Then `dependent_hypotheses` = `[H1, H3]` (H2 excluded because it does not mention `n`).

#### 4.1.4 Dependency ordering

The component shall build a directed graph among dependent hypotheses where an edge from `H1` to `H2` means `H1`'s type mentions `H2`. The component shall topologically sort this graph to produce the revert order.

- REQUIRES: `dependent_hypotheses` is non-empty.
- ENSURES: `dependent_hypotheses` is ordered such that the first element is reverted first (the hypothesis with the most outgoing dependencies). The ordering is a valid topological sort of the dependency graph.
- When the dependency graph contains a cycle, the component shall return `DEPENDENCY_CYCLE`.

> Given `H1 : P n H2` and `H2 : Q n` (H1 depends on H2)
> When dependency ordering runs
> Then revert order is `[H1, H2]` (H1 reverted first, then H2).

#### 4.1.5 Decidable equality detection

For each index in `DependencyReport.indices`, the component shall query `Search EqDec {type}` and `Search (forall x y : {type}, {x = y} + {x <> y})`.

- ENSURES: `IndexInfo.has_decidable_eq` is true when a decidable equality instance exists for the index type. False otherwise.

### 4.2 Technique selection

The Technique Selector shall evaluate the following rules in order. The first matching rule determines `TechniqueRecommendation.primary`. All matching rules contribute to `TechniqueRecommendation.alternatives`.

| Rule | Guard | Primary technique | Axioms |
|------|-------|-------------------|--------|
| 1 | Target is a hypothesis AND indices are concrete constructors AND `dependent_hypotheses` count ≤ 2 | `inversion` | None |
| 2 | Tactic mode AND `dependent_hypotheses` non-empty | `revert_destruct` | None |
| 3 | `axiom_tolerance` = `"permissive"` | `dependent_destruction` | `JMeq_eq` |
| 4 | Term mode (detected by `refine`/`exact` in proof state) | `convoy_pattern` | None |
| 5 | Equations plugin available (detected by `Locate Equations.Init`) | `equations_depelim` | None |

- REQUIRES: `DependencyReport` is populated.
- ENSURES: `TechniqueRecommendation.primary` is set. `alternatives` contains all other matching techniques. When rule 3 matches, `TechniqueRecommendation.axiom_warning` is non-null and contains the string `JMeq_eq`.

> Given tactic mode, axiom_tolerance = "strict", 3 dependent hypotheses, Equations not available
> When technique selection runs
> Then primary = `revert_destruct`, alternatives = `[]`, axiom_warning = null.

> Given tactic mode, axiom_tolerance = "permissive", 1 dependent hypothesis, concrete indices, Equations available
> When technique selection runs
> Then primary = `inversion`, alternatives include `revert_destruct`, `dependent_destruction`, `equations_depelim`. axiom_warning mentions `JMeq_eq`.

#### 4.2.1 Axiom warning content

When `dependent_destruction` appears as primary or alternative, `TechniqueRecommendation.axiom_warning` shall contain:
1. The fully qualified axiom name: `Coq.Logic.JMeq.JMeq_eq`.
2. A note that `Print Assumptions` will show this axiom.
3. A note that the axiom is consistent but not provable in Coq's core theory.

When all index types have decidable equality (`has_decidable_eq` = true for all indices), the warning shall additionally note that `Eqdep_dec.eq_rect_eq_dec` can eliminate the axiom dependency.

### 4.3 Boilerplate generation

When `generate_code` is true, the Boilerplate Generator shall produce a `GeneratedCode` record for `TechniqueRecommendation.primary`.

#### 4.3.1 revert_destruct code generation

- REQUIRES: `dependent_hypotheses` in revert order, target name.
- ENSURES: `GeneratedCode.code` contains `revert {H_n} ... {H_1}. destruct {target}.` with hypotheses in revert order. `GeneratedCode.imports` is empty. `GeneratedCode.setup` is empty.

> Given dependent_hypotheses = `[H1, H3]` (revert order), target = `v`
> When revert_destruct generation runs
> Then code = `"revert H1 H3. destruct v."`.

#### 4.3.2 dependent_destruction code generation

- REQUIRES: Target name.
- ENSURES: `GeneratedCode.code` contains `dependent destruction {target}.`. When `Program.Equality` is not loaded (detected by `Locate dependent_destruction` failing), `GeneratedCode.imports` contains `"Require Import Coq.Program.Equality."`.

#### 4.3.3 convoy_pattern code generation

- REQUIRES: Target term, inductive type with index names, dependent terms, result type.
- ENSURES: `GeneratedCode.code` contains a `match` expression with `as`, `in`, `return` annotations. The `return` clause includes dependent terms as function arguments. Each branch has `fun` binders for the convoyed arguments. The expression ends with the convoy actuals. When equality evidence is convoyed, `eq_refl` is the final actual.

#### 4.3.4 equations_depelim code generation

- REQUIRES: Function name, argument types, return type.
- ENSURES: `GeneratedCode.imports` contains `"From Equations Require Import Equations."` when not already loaded. `GeneratedCode.setup` contains `Derive NoConfusion` and `Derive Signature` commands when not already derived (detected by `Locate NoConfusion_{type}`). `GeneratedCode.code` contains an `Equations` definition skeleton.

#### 4.3.5 Code validation

When `generate_code` is true and the generated technique is `revert_destruct` or `dependent_destruction`, the component may validate the generated code by submitting it to the session backend via `check_proof`. Validation operates on a checkpoint of the proof state; the original state is restored afterward.

- ENSURES: When validation succeeds, `GeneratedCode.validation_result` = `"valid"`. When validation fails, `GeneratedCode.validation_result` contains the Coq error message. When validation is skipped, `GeneratedCode.validation_result` = null.
- MAINTAINS: The session's proof state is unchanged after validation.

## 5. Data Model

### DependencyReport

| Field | Type | Constraints |
|-------|------|-------------|
| `target` | string | Required; non-empty identifier |
| `target_type` | string | Required; pretty-printed Coq type |
| `inductive_name` | string | Required; fully qualified inductive type name |
| `parameters` | ordered list of string | Required; may be empty |
| `indices` | ordered list of IndexInfo | Required; at least one element (otherwise NOT_INDEXED) |
| `dependent_hypotheses` | ordered list of DependentHypothesis | Required; in revert order; may be empty |
| `goal_depends_on_index` | boolean | Required |
| `error_message` | string or null | Null when no error message was captured |

### IndexInfo

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; variable or term name |
| `type` | string | Required; Coq type name |
| `has_decidable_eq` | boolean | Required |

### DependentHypothesis

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; hypothesis identifier |
| `type` | string | Required; pretty-printed hypothesis type |
| `indices_mentioned` | ordered list of string | Required; non-empty subset of index names from DependencyReport.indices |
| `depends_on` | ordered list of string | Required; may be empty; each element is a name from another DependentHypothesis |

### TechniqueRecommendation

| Field | Type | Constraints |
|-------|------|-------------|
| `primary` | Technique | Required |
| `alternatives` | ordered list of Technique | Required; may be empty; excludes primary |
| `axiom_warning` | string or null | Non-null when any technique in primary or alternatives introduces axioms |

### Technique

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; one of `"inversion"`, `"revert_destruct"`, `"dependent_destruction"`, `"convoy_pattern"`, `"equations_depelim"` |
| `description` | string | Required; single sentence |
| `axioms_introduced` | ordered list of string | Required; empty for axiom-free techniques; contains fully qualified axiom names otherwise |
| `requires_plugin` | string or null | Non-null only for `"equations_depelim"` (value: `"Equations"`) |

### GeneratedCode

| Field | Type | Constraints |
|-------|------|-------------|
| `technique` | string | Required; matches the technique name this code implements |
| `imports` | ordered list of string | Required; each element is a valid `Require Import` line; empty when imports already loaded |
| `setup` | ordered list of string | Required; each element is a Coq command (e.g., `Derive`); empty when not needed |
| `code` | string | Required; non-empty; syntactically valid Coq tactic sequence or term |
| `validation_result` | string or null | Null when validation was not performed; `"valid"` on success; Coq error message on failure |

### DestructDiagnosis

| Field | Type | Constraints |
|-------|------|-------------|
| `dependency_report` | DependencyReport | Required |
| `recommendation` | TechniqueRecommendation | Required |
| `generated_code` | GeneratedCode or null | Null when `generate_code` was false |

## 6. Interface Contracts

### Convoy Pattern Analyzer → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `observe_proof_state` (read proof state), `check_proof` (optional validation) |
| Concurrency | Serialized — one command at a time per session backend |
| State preservation | All operations are read-only except optional `check_proof`, which restores proof state afterward |
| Error strategy | `SESSION_NOT_FOUND` → return error immediately. `BACKEND_CRASHED` → return error immediately. |

### Convoy Pattern Analyzer → Vernacular Introspection

| Property | Value |
|----------|-------|
| Operations used | `coq_query` with commands: `Check`, `Print`, `About`, `Search`, `Locate` |
| Concurrency | Serialized — shares session backend with proof state operations |
| Error strategy | Query failure → populate `PARSE_ERROR` with raw output and continue with best-effort analysis |

## 7. State and Lifecycle

The Convoy Pattern Analyzer is stateless. Each `diagnose_destruct` call is independent — no data is persisted between invocations. The component borrows a session backend for the duration of the call and releases it when the call completes (successfully or with an error).

## 8. Error Specification

| Condition | Error Code | Behavior |
|-----------|------------|----------|
| `session_id` does not reference an active session | `SESSION_NOT_FOUND` | Return error immediately: "Destruct diagnosis requires an active proof session." |
| `target` is non-null but not found in proof state | `TARGET_NOT_FOUND` | Return error immediately: "Term `{target}` not found in the current proof state." |
| `target` is null and no error message in session buffer | `TARGET_NOT_FOUND` | Return error immediately: "No target specified and no recent destruct error found." |
| Target type is not an indexed inductive type | `NOT_INDEXED` | Return error with suggestion: "`{target}` has type `{type}`, which is not an indexed inductive type. Standard `destruct` should work." |
| No dependent hypotheses found for any index | `NO_DEPENDENCY` | Return error with suggestion: "No hypotheses depend on the indices of `{target}`. Standard `destruct` should work." |
| Dependency graph among hypotheses contains a cycle | `DEPENDENCY_CYCLE` | Return error: "Circular dependency among hypotheses: {cycle}. Please report this as a bug." |
| `Print {inductive}` output could not be parsed | `PARSE_ERROR` | Return error with raw output: "Could not parse the definition of `{inductive}`." Include raw `Print` output. |
| Coq backend process has crashed | `BACKEND_CRASHED` | Return error immediately: "The Coq backend has crashed. Close the session and open a new one." |

## 9. Non-Functional Requirements

- `diagnose_destruct` shall complete within 5 seconds for proof states with up to 50 hypotheses and inductive types with up to 20 constructors.
- Dependency scanning shall issue at most `2 + H` Coq queries, where `H` is the number of hypotheses in the proof state (1 `Check` for the target, 1 `Print` for the inductive, and 1 `Search EqDec` per index type — at most `H` queries total since the number of indices is bounded by `H`).
- The component shall not spawn additional OS processes.
- Generated code strings shall not exceed 10,000 characters.

## 10. Examples

### Example 1: Simple revert-before-destruct

> Given a proof session with:
>   - Goal: `P (S n)`
>   - Hypotheses: `v : Fin (S n)`, `H : Q (S n)`, `H2 : R m`
>   - Target: `v`
>   - axiom_tolerance: `"strict"`
>
> When `diagnose_destruct(session_id, "v", "strict", true)` is called
>
> Then:
>   - `dependency_report.indices` = `[{name: "S n", type: "nat", has_decidable_eq: true}]`
>   - `dependency_report.dependent_hypotheses` = `[{name: "H", type: "Q (S n)", ...}]`
>   - `recommendation.primary.name` = `"revert_destruct"`
>   - `recommendation.axiom_warning` = null
>   - `generated_code.code` = `"revert H. destruct v."`

### Example 2: Permissive mode with decidable equality

> Given a proof session with:
>   - Hypotheses: `v : vec nat n`, `H : length_proof n`
>   - Target: `v`
>   - axiom_tolerance: `"permissive"`
>   - Index type `nat` has decidable equality
>
> When `diagnose_destruct(session_id, "v", "permissive", true)` is called
>
> Then:
>   - `recommendation.primary.name` = `"revert_destruct"`
>   - `recommendation.alternatives` includes `dependent_destruction`
>   - `recommendation.axiom_warning` contains `"JMeq_eq"` and notes `Eqdep_dec.eq_rect_eq_dec` is available

### Example 3: Not an indexed inductive

> Given a proof session with target `x` of type `nat` (no indices)
>
> When `diagnose_destruct(session_id, "x", "strict", true)` is called
>
> Then `NOT_INDEXED` error is returned with message: "`x` has type `nat`, which is not an indexed inductive type. Standard `destruct` should work."

## 11. Language-Specific Notes

- Package location: `src/poule/convoy/`
- Entry point: `async def diagnose_destruct(session_id: str, target: str | None, axiom_tolerance: str, generate_code: bool) -> DestructDiagnosis`
- Index identification parses `Print` output using regex patterns for constructor signatures. The parameter/index boundary is identified by the `Parameters` keyword in the `Print` output for inductive types.
- Hypothesis scanning uses `re.search(r'\b' + re.escape(index_name) + r'\b', hyp_type)` for syntactic occurrence checking.
- Dependency ordering uses `graphlib.TopologicalSorter` from the standard library.
- Technique names are a `StrEnum`: `INVERSION`, `REVERT_DESTRUCT`, `DEPENDENT_DESTRUCTION`, `CONVOY_PATTERN`, `EQUATIONS_DEPELIM`.
- Constants: `MAX_HYPOTHESES = 200` (above this, scanning is truncated with a warning), `DIAGNOSE_TIMEOUT_SECONDS = 5`.
