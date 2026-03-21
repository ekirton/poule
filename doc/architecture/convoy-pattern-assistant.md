# Convoy Pattern Assistant

The component that diagnoses dependent-destruction failures by analyzing proof state type dependencies, selects the appropriate repair technique based on context, and generates the tactic sequences or term-level boilerplate needed to fix the proof.

**Feature**: [Convoy Pattern Assistant](../features/convoy-pattern-assistant.md)

---

## Component Diagram

```
MCP Server
  │
  │ diagnose_destruct(session_id, target?)
  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Convoy Pattern Analyzer                          │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ Dependency Scanner                                        │   │
│  │                                                           │   │
│  │  Inputs: ProofState, target term                          │   │
│  │                                                           │   │
│  │  1. Identify the inductive type and its index arguments   │   │
│  │  2. Scan all hypotheses for index references              │   │
│  │  3. Scan the goal for index references                    │   │
│  │  4. Build dependency ordering (innermost first)           │   │
│  │                                                           │   │
│  │  → DependencyReport                                       │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Technique Selector                                        │   │
│  │                                                           │   │
│  │  Inputs: DependencyReport, axiom_tolerance, proof_mode    │   │
│  │                                                           │   │
│  │  Decision tree:                                           │   │
│  │    concrete indices + simple structure → inversion         │   │
│  │    tactic mode + axiom-free → revert-before-destruct      │   │
│  │    tactic mode + axioms ok → dependent destruction        │   │
│  │    term mode → convoy pattern                             │   │
│  │    Equations available → depelim                           │   │
│  │                                                           │   │
│  │  → TechniqueRecommendation                                │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Boilerplate Generator                                     │   │
│  │                                                           │   │
│  │  revert-before-destruct:                                  │   │
│  │    → tactic sequence (revert H1 H2. destruct x.)         │   │
│  │                                                           │   │
│  │  dependent destruction:                                   │   │
│  │    → Require + tactic (dependent destruction x.)          │   │
│  │                                                           │   │
│  │  convoy pattern:                                          │   │
│  │    → match term with as/in/return annotations             │   │
│  │                                                           │   │
│  │  Equations depelim:                                       │   │
│  │    → Derive + Equations definition                        │   │
│  │                                                           │   │
│  │  → GeneratedCode                                          │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
  │                     │                        │
  │ observe_proof_state │ coq_query              │ check_proof
  │                     │ (Check, Print,         │ (validate generated
  │                     │  About)                │  code)
  ▼                     ▼                        ▼
Proof Session        Vernacular              Proof Session
Manager              Introspection           Manager
```

The component does not own a Coq backend process. It borrows the backend associated with an active proof session to inspect the proof state and execute queries about types. The Boilerplate Generator optionally validates generated code by submitting it via `check_proof`.

## Tool Signature

```typescript
diagnose_destruct(
  session_id: string,           // active proof session positioned at or after a destruct
  target: string | null = null, // term to destruct; if null, inferred from the most recent tactic or goal
  axiom_tolerance: "strict" | "permissive" = "strict",
                                // "strict" avoids JMeq_eq; "permissive" allows it
  generate_code: boolean = true // if true, generate the boilerplate for the recommended technique
) → DestructDiagnosis
```

When `target` is null, the component inspects the proof state to identify the most likely target — the term whose `destruct` just failed or whose destruction is causing the current proof state to be weaker than expected. If the proof state contains a recent "Abstracting over ... leads to an ill-typed term" error message (captured in the session's message buffer), the target is extracted from the error.

When `axiom_tolerance` is `"strict"`, the Technique Selector excludes `dependent destruction` from its recommendations. When `"permissive"`, it may recommend `dependent destruction` but always includes the axiom warning.

## Dependency Scanner

The Dependency Scanner determines which hypotheses and goal components depend on the indices of the target term's inductive type.

### Index Identification

1. Query the type of the target term via `coq_query("Check", target, session_id)`.
2. Parse the type to identify the inductive type constructor and its index arguments. For example, if the target has type `Fin n`, the inductive type is `Fin` and the index is `n`. If the target has type `vec T n`, the indices are `T` and `n` (though `T` is typically a parameter, not an index — the scanner must distinguish parameters from indices).
3. Query the inductive type definition via `coq_query("Print", inductive_name, session_id)` to determine which arguments are parameters (uniform across constructors) and which are indices (vary per constructor). Parameters do not cause dependent-destruction problems; only indices do.

### Hypothesis Scanning

For each hypothesis in the proof state:

1. Extract the hypothesis type from the `ProofState.hypotheses` list.
2. Check whether any index variable from the target's type appears free in the hypothesis type. A variable `n` "appears free" if it occurs in the type expression outside of binding positions.
3. If the hypothesis type mentions an index, record it as a dependent hypothesis.

The scanner performs syntactic occurrence checking on the pretty-printed hypothesis types. This is a heuristic — it may produce false positives when a variable name is shadowed by a local binder, and false negatives when an index is hidden behind a definition. For the common case (simple variable indices like `n` in `Fin n`), syntactic checking is sufficient.

### Goal Scanning

The goal is scanned the same way as hypotheses. If the goal type mentions an index, the dependency is noted but does not require an explicit `revert` — Coq's `destruct` handles the goal's return type automatically.

### Dependency Ordering

Dependent hypotheses must be reverted in the correct order: if hypothesis `H1` mentions hypothesis `H2` in its type, then `H2` must be reverted before `H1` (i.e., `H1` is reverted first, then `H2`, because `revert` operates as a stack). The scanner builds a dependency graph among the dependent hypotheses and produces a topological sort. If the graph has cycles (which should not occur in well-typed proof states), the scanner reports an error.

## Technique Selector

The Technique Selector consumes a `DependencyReport` and produces a `TechniqueRecommendation`. The decision logic is a prioritized rule set, not a single decision tree, because multiple techniques may be applicable and the selector ranks them.

### Selection Rules

Rules are evaluated in order. The first matching rule determines the primary recommendation. All matching rules contribute to the alternatives list.

1. **Inversion candidate.** If the target is a hypothesis (not a term in the goal), the inductive type has concrete constructor indices (not variables), and there are few dependent hypotheses (≤ 2), recommend `inversion`. This handles the simple case where the user is inverting a relation like `step (App e1 e2) v` and wants constructor-specific information.

2. **Revert-before-destruct.** If the proof is in tactic mode and the dependency scanner found dependent hypotheses, recommend `revert H1 H2 ... . destruct target.` with the hypotheses in the order determined by the Dependency Scanner. This is the default for axiom-free tactic-mode proofs.

3. **Dependent destruction.** If `axiom_tolerance` is `"permissive"`, recommend `dependent destruction target` as an alternative. Always attach the axiom warning.

4. **Convoy pattern.** If the user is writing a `match` expression in term mode (detected by the proof state showing a `refine` or `exact` tactic, or by the user explicitly requesting term-mode help), recommend the convoy pattern with generated return-clause annotations.

5. **Equations depelim.** If the Equations plugin is available in the environment (detected by querying `Locate Equations.` or checking for `Equations.Init` in the loaded modules), recommend `depelim` as an axiom-free alternative. Include the required `Derive NoConfusion` and `Derive Signature` commands.

### Axiom Warning

When `dependent destruction` is recommended (rule 3), the recommendation includes:

- The specific axiom introduced: `Coq.Logic.JMeq.JMeq_eq`.
- That `Print Assumptions <lemma_name>` will show this axiom after the proof is closed.
- That the axiom is consistent with Coq's theory but not provable in it.
- The axiom-free alternatives (revert-before-destruct, Equations).

### Decidable Equality Optimization

When the index type has a decidable equality instance (detected by `Search EqDec <index_type>` or `Search (forall x y : <index_type>, {x = y} + {x <> y})`), the selector notes that `dependent destruction` can be made axiom-free by using `Eqdep_dec.eq_rect_eq_dec` instead of `JMeq_eq`. This is reported as a note on the `dependent destruction` alternative, not as a separate technique.

## Boilerplate Generator

The Boilerplate Generator produces concrete code for the recommended technique.

### Revert-Before-Destruct

Input: ordered list of dependent hypotheses, target term name.

Output:
```
revert {H_n} ... {H_1}.
destruct {target}.
```

The hypotheses are listed in revert order (reverse of dependency order: the hypothesis with the most dependencies is reverted first). After `destruct`, the user will see subgoals where the dependent hypotheses have been re-introduced with refined types.

If the user would benefit from explicit `intros` after destruct (e.g., to restore the original hypothesis names), the generator appends:
```
- intros {H_1} ... {H_n}.
```
for each branch.

### Dependent Destruction

Input: target term name.

Output:
```
Require Import Coq.Program.Equality.
dependent destruction {target}.
```

The `Require Import` is included only if `Program.Equality` is not already loaded (detected by `Locate dependent_destruction`).

### Convoy Pattern

Input: target term, its inductive type with index names, dependent terms to convoy, result type.

The generator constructs a `match` expression with `as`, `in`, and `return` annotations:

```coq
match {target} as {binder} in {inductive} {index_patterns} return ({convoy_args} -> {result_type_with_indices_replaced}) with
| {constructor_1} => fun {convoy_params} => _
| {constructor_2} => fun {convoy_params} => _
...
end {convoy_actuals}
```

Where:
- `{binder}` is a fresh name for the matched term.
- `{index_patterns}` replace the concrete index values with pattern variables.
- `{convoy_args}` are the dependent hypotheses, added as function arguments so their types are refined per-branch.
- `{result_type_with_indices_replaced}` is the result type with concrete indices replaced by the pattern variables from `in`.
- `{convoy_actuals}` are the actual dependent hypothesis values, passed as arguments to the match result.

When the convoy includes an equality proof (`target = constructor_args`), the generator adds `eq_refl` as the final actual argument.

### Equations Definition

Input: function name, argument types including the indexed type, return type.

Output:
```coq
From Equations Require Import Equations.
Derive NoConfusion for {inductive_type}.
Derive Signature for {inductive_type}.

Equations {function_name} {args} : {return_type} :=
  {function_name} {pattern_1} := _;
  {function_name} {pattern_2} := _.
```

The `Derive` commands are included only if they have not already been issued for this type (detected by `Locate NoConfusion_{type_name}`).

## Data Structures

### DependencyReport

| Field | Type | Description |
|-------|------|-------------|
| `target` | string | The term being destructed |
| `target_type` | string | Pretty-printed type of the target |
| `inductive_name` | string | Name of the inductive type |
| `parameters` | list of string | Parameter names (uniform across constructors) |
| `indices` | list of IndexInfo | Index names and their types |
| `dependent_hypotheses` | list of DependentHypothesis | Hypotheses whose types mention an index, in revert order |
| `goal_depends_on_index` | boolean | Whether the goal type mentions an index |
| `error_message` | string or null | The original error message if `destruct` failed |

### IndexInfo

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Variable name of the index (e.g., `n`) |
| `type` | string | Type of the index (e.g., `nat`) |
| `has_decidable_eq` | boolean | Whether the index type has a decidable equality instance |

### DependentHypothesis

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Hypothesis name (e.g., `H`) |
| `type` | string | Pretty-printed hypothesis type |
| `indices_mentioned` | list of string | Which index variables appear in this hypothesis type |
| `depends_on` | list of string | Other dependent hypothesis names this one references |

### TechniqueRecommendation

| Field | Type | Description |
|-------|------|-------------|
| `primary` | Technique | The recommended technique |
| `alternatives` | list of Technique | Other applicable techniques, ranked |
| `axiom_warning` | string or null | Non-null when the primary or any alternative introduces axioms |

### Technique

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | `"inversion"`, `"revert_destruct"`, `"dependent_destruction"`, `"convoy_pattern"`, or `"equations_depelim"` |
| `description` | string | One-sentence description of the technique |
| `axioms_introduced` | list of string | Axiom names introduced (empty for axiom-free techniques) |
| `requires_plugin` | string or null | Plugin name if required (e.g., `"Equations"`) |

### GeneratedCode

| Field | Type | Description |
|-------|------|-------------|
| `technique` | string | Which technique this code implements |
| `imports` | list of string | `Require Import` lines needed (empty if already loaded) |
| `setup` | list of string | Setup commands (e.g., `Derive NoConfusion`) — empty if not needed |
| `code` | string | The tactic sequence or term to insert |
| `validation_result` | string or null | Result of `check_proof` if validation was performed; null if skipped |

### DestructDiagnosis

| Field | Type | Description |
|-------|------|-------------|
| `dependency_report` | DependencyReport | Full dependency analysis |
| `recommendation` | TechniqueRecommendation | Technique recommendation with alternatives |
| `generated_code` | GeneratedCode or null | Generated boilerplate (null if `generate_code` was false) |

## Integration with Existing Components

### Proof Session Manager

The Convoy Pattern Analyzer borrows the session backend to inspect the proof state and execute queries. Integration follows the same contract as Typeclass Debugging and Auto Trace Explanation:

1. **Session required**: All operations require an active proof session. The MCP server passes the `session_id`; the analyzer resolves it through the session registry.
2. **State preservation**: The analyzer does not modify the proof state. All queries are read-only (`observe_proof_state`, `coq_query` with `Check`/`Print`/`About`/`Search`). When `check_proof` is used for validation, it operates on a copy of the proof state, not the live session.
3. **Concurrency**: The analyzer serializes access to the session backend. It does not issue concurrent commands to the same session.

### Vernacular Introspection

The analyzer uses `coq_query` for:
- `Check {target}` — to obtain the target's type.
- `Print {inductive}` — to distinguish parameters from indices in the inductive type definition.
- `About {name}` — to check whether `Program.Equality` or Equations is loaded.
- `Search EqDec {type}` — to detect decidable equality instances.
- `Locate {name}` — to check whether Equations derivations already exist.

### Assumption Auditing (optional)

When `axiom_tolerance` is not specified by the user, the analyzer may query the current proof's assumption profile via `Print Assumptions` (if the proof is complete enough to check) to detect whether the development already uses `JMeq_eq`. If it does, `dependent destruction` can be recommended without the axiom warning being a significant concern. This is an optimization, not a requirement.

## Error Handling

| Condition | Error Code | Message |
|-----------|------------|---------|
| No active session | `SESSION_NOT_FOUND` | Destruct diagnosis requires an active proof session. |
| Target term not found in proof state | `TARGET_NOT_FOUND` | Term `{target}` not found in the current proof state. |
| Target type is not an indexed inductive | `NOT_INDEXED` | `{target}` has type `{type}`, which is not an indexed inductive type. No dependent-destruction issue is possible. |
| No dependent hypotheses found | `NO_DEPENDENCY` | No hypotheses depend on the indices of `{target}`. Standard `destruct` should work. |
| Dependency cycle detected | `DEPENDENCY_CYCLE` | Circular dependency among hypotheses: {cycle}. This should not occur in a well-typed proof state; please report this as a bug. |
| Inductive type definition unparseable | `PARSE_ERROR` | Could not parse the definition of `{inductive}`. Raw output included in response. |
| Backend crash | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |

When the target is not an indexed inductive (`NOT_INDEXED`), the response includes a suggestion to use plain `destruct` — the user may have invoked the diagnostic tool unnecessarily.

## Design Rationale

### Why syntactic occurrence checking rather than full type-dependency analysis

The Dependency Scanner checks whether index variable names appear in hypothesis type strings. A full semantic analysis — tracking variables through definitions, checking whether an occurrence is truly free vs. bound, handling name shadowing — would require reimplementing significant portions of Coq's type checker. Syntactic checking handles the common case correctly (direct variable references like `n` in `P n`) and is simple to implement. False positives (a shadowed variable name matches) produce extra `revert` calls that are harmless. False negatives (an index hidden behind a definition) are rare and can be caught by the LLM layer, which sees the full proof state.

### Why a decision tree with ranked alternatives rather than a single recommendation

Users have different constraints (axiom tolerance, plugin availability, proof mode) that the tool cannot always infer. Presenting a ranked list — primary recommendation plus alternatives — lets the user see the tradeoffs and choose. The primary recommendation is the one the tool believes is best given the available information; the alternatives are there for users who have constraints the tool did not detect.

### Why optional validation via check_proof

The Boilerplate Generator produces code from templates and type information. Template-based generation can produce syntactically valid but semantically incorrect code (e.g., wrong return-clause structure). Validating the generated code by submitting it to Coq catches these errors before the user tries to use the code. Validation is optional (controlled by `generate_code`) because it requires a round-trip to the Coq backend and may modify the session state, which the analyzer normally avoids.

### Why parameter/index distinction is queried from the inductive definition

A naive implementation would treat all arguments of an indexed inductive type as indices. But parameters (arguments that are uniform across all constructors, like `T` in `vec T n`) do not cause dependent-destruction problems. Only indices (arguments that vary per constructor, like `n` in `vec T n`) need to be tracked. The distinction is determined by Coq's `Print` output for the inductive type, which separates parameters from indices in the constructor signatures.
