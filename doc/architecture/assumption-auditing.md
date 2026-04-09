# Assumption Auditing

The component that extracts, classifies, and compares axiom dependencies for Coq theorems. Claude Code invokes assumption auditing as MCP tools; the component handles Coq interaction, output parsing, classification, and result assembly internally.

**Feature**: [Assumption Auditing](../features/assumption-auditing.md)

---

## Component Diagram

```
MCP Server
  │
  │ audit_assumptions(name)
  │ audit_module(module)
  │ compare_assumptions(names)
  ▼
┌───────────────────────────────────────────────────────────────┐
│                  Assumption Auditing Engine                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Assumption Extractor                                    │  │
│  │                                                         │  │
│  │  Send `Print Assumptions <name>.` to Coq backend        │  │
│  │  Parse response into structured assumption list          │  │
│  │  Separate axioms from opaque dependencies               │  │
│  └────────────────────────┬────────────────────────────────┘  │
│                           │                                   │
│                           ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Axiom Classifier                                        │  │
│  │                                                         │  │
│  │  Match each axiom against known-axiom registry           │  │
│  │  Assign category + explanation                           │  │
│  │  Fall back to "custom" for unrecognized axioms           │  │
│  └────────────────────────┬────────────────────────────────┘  │
│                           │                                   │
│                           ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Result Assembly                                          │  │
│  │                                                         │  │
│  │  Single: AssumptionResult                                │  │
│  │  Batch:  ModuleAuditResult (summary + per-theorem)      │  │
│  │  Compare: ComparisonResult (shared / unique / matrix)   │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
  │
  │ `Print Assumptions` commands
  ▼
Proof Session Manager → Coq Backend Process
```

## Tool Signatures

Assumption auditing is exposed as a dedicated `coq_audit` tool rather than a subcommand of `coq_query`. Rationale: the classification logic, batch iteration, and comparison operations constitute a distinct concern with their own data structures and error modes. Overloading `coq_query` would conflate search/retrieval semantics with auditing semantics.

```typescript
// Audit axiom dependencies for a single theorem
audit_assumptions(
  name: string,             // fully qualified theorem name
) → AssumptionResult

// Audit all theorems in a module
audit_module(
  module: string,           // fully qualified module name (e.g., "Coq.Arith.PeanoNat")
  flag_categories?: string[] // categories to flag (default: ["classical", "choice", "proof_irrelevance", "custom"])
) → ModuleAuditResult

// Compare assumption profiles of two or more theorems
compare_assumptions(
  names: string[],          // fully qualified theorem names (minimum 2)
) → ComparisonResult
```

## Data Structures

### AssumptionResult

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Fully qualified theorem name |
| `is_closed` | boolean | True when the theorem has no axiom dependencies beyond Coq's core |
| `axioms` | list of ClassifiedAxiom | Axiom dependencies with classification |
| `opaque_dependencies` | list of OpaqueDependency | Opaque definitions (ended with `Qed` or `Admitted`) that block reduction |

### ClassifiedAxiom

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Fully qualified axiom name |
| `type` | string | Pretty-printed Coq type of the axiom |
| `category` | AxiomCategory | Classification category |
| `explanation` | string | Short plain-language description of what the axiom asserts and its implications |

### AxiomCategory

One of:
- `"classical"` — law of excluded middle, double-negation elimination, and equivalent principles
- `"extensionality"` — functional extensionality, propositional extensionality
- `"choice"` — axiom of choice variants, indefinite description
- `"proof_irrelevance"` — all proofs of a proposition are equal
- `"custom"` — user-defined axioms not in the known-axiom registry

### OpaqueDependency

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Fully qualified name |
| `type` | string | Pretty-printed Coq type |

### ModuleAuditResult

| Field | Type | Description |
|-------|------|-------------|
| `module` | string | Fully qualified module name |
| `theorem_count` | non-negative integer | Total theorems audited |
| `axiom_free_count` | non-negative integer | Theorems with no axiom dependencies |
| `axiom_summary` | list of AxiomUsageSummary | Per-axiom usage across the module |
| `flagged_theorems` | list of FlaggedTheorem | Theorems that use axioms in the flagged categories |
| `per_theorem` | list of AssumptionResult | Individual audit results |

### AxiomUsageSummary

| Field | Type | Description |
|-------|------|-------------|
| `axiom_name` | string | Fully qualified axiom name |
| `category` | AxiomCategory | Classification category |
| `dependent_count` | non-negative integer | Number of theorems depending on this axiom |

### FlaggedTheorem

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Fully qualified theorem name |
| `flagged_axioms` | list of ClassifiedAxiom | The axioms that triggered the flag |

### ComparisonResult

| Field | Type | Description |
|-------|------|-------------|
| `theorems` | list of string | The theorem names being compared |
| `shared_axioms` | list of ClassifiedAxiom | Axioms common to all theorems |
| `unique_axioms` | map of string to list of ClassifiedAxiom | Per-theorem axioms not shared by all others |
| `matrix` | list of MatrixRow | Axiom-by-theorem presence matrix (included when 3+ theorems are compared) |
| `weakest` | list of string | Theorem name(s) with the fewest axiom dependencies (may be multiple if tied) |

### MatrixRow

| Field | Type | Description |
|-------|------|-------------|
| `axiom` | ClassifiedAxiom | The axiom |
| `present_in` | list of string | Theorem names that depend on this axiom |

## Assumption Extraction

### Coq Command Protocol

The Assumption Extractor sends `Print Assumptions <name>.` to a Coq backend process via the Proof Session Manager. The command requires a compiled environment where the named identifier is in scope.

### Output Parsing

`Print Assumptions` returns one of two forms:

1. **Closed theorem** — a single line:
   ```
   Closed under the global context
   ```
   Parsed as: `is_closed = true`, empty axiom and opaque dependency lists.

2. **Open theorem** — one dependency per line:
   ```
   <qualified_name> : <type>
   ```
   Each line is split on the first ` : ` separator. The left side is the fully qualified name; the right side is the pretty-printed type.

### Separating Axioms from Opaque Dependencies

After parsing, each dependency is classified as either an axiom or an opaque dependency:

1. Query the Coq environment to determine the declaration kind (axiom, parameter, definition ended with `Qed`, etc.).
2. Declarations whose kind is `Axiom` or `Parameter` are axioms. Declarations that are opaque (ended with `Qed` or are `Admitted`) are opaque dependencies.
3. If the declaration kind cannot be determined (e.g., because the identifier is from a library that provides only `.vo` files without source), it is treated as an axiom — the conservative default ensures zero false negatives.

## Axiom Classification Algorithm

### Known-Axiom Registry

A static registry maps fully qualified axiom names to their category and explanation. The registry is a declarative data structure (not executable logic), organized by category.

Registry entries include at minimum:

**Classical:**
- `Coq.Logic.Classical_Prop.classic` — law of excluded middle
- `Coq.Logic.Classical_Prop.NNPP` — double-negation elimination
- `Coq.Logic.ClassicalEpsilon.excluded_middle_informative` — informative excluded middle
- `Coq.Logic.Decidable.dec_not_not` — decidable double negation

**Extensionality:**
- `Coq.Logic.FunctionalExtensionality.functional_extensionality_dep` — dependent functional extensionality
- `Coq.Logic.PropExtensionality.propositional_extensionality` — propositional extensionality

**Choice:**
- `Coq.Logic.ChoiceFacts.*` variants — various choice principles
- `Coq.Logic.IndefiniteDescription.constructive_indefinite_description` — indefinite description
- `Coq.Logic.ClassicalChoice.choice` — classical choice
- `Coq.Logic.Epsilon.epsilon` — Hilbert's epsilon

**Proof Irrelevance:**
- `Coq.Logic.ProofIrrelevance.proof_irrelevance` — all proofs of a Prop are equal
- `Coq.Logic.ProofIrrelevanceFacts.*` — derived proof irrelevance facts
- `Coq.Logic.JMeq.JMeq_eq` — heterogeneous equality collapse (often classified here due to its relationship with proof irrelevance in practice)

### Classification Procedure

```
classify(axiom_name, axiom_type)
  │
  ├─ Exact match: look up axiom_name in the known-axiom registry
  │    ├─ Found → return (category, explanation) from registry
  │    └─ Not found → continue
  │
  ├─ Prefix match: check if axiom_name falls under a known module prefix
  │    (e.g., any name under `Coq.Logic.Classical_Prop` → classical)
  │    ├─ Found → return (category, generic explanation for that module)
  │    └─ Not found → continue
  │
  ├─ Type-based heuristic: inspect axiom_type for structural indicators
  │    (e.g., type mentions `∀ P, P ∨ ¬P` → classical;
  │     type mentions `∀ f g, (∀ x, f x = g x) → f = g` → extensionality)
  │    ├─ Match → return (inferred category, generic explanation)
  │    └─ No match → continue
  │
  └─ Default: return ("custom", "User-defined axiom. Review manually for consistency.")
```

The three-stage cascade ensures high accuracy on standard library axioms (exact match), reasonable coverage of less common standard library axioms (prefix match), and a safety net for axioms that follow recognizable patterns but are defined outside the standard library (type heuristic). The type-based heuristic is conservative — it fires only on well-established structural patterns and prefers `"custom"` over a wrong classification.

## Batch Auditing

### Module Enumeration

Batch auditing iterates over all declarations in a module. Three enumeration strategies are attempted in sequence:

```
audit_module(module, flag_categories)
  │
  ├─ Enumerate declarations in module (three-strategy cascade)
  │    1. Send `Print Module <module>.` to the Coq backend
  │       Parse the response to extract declaration names
  │    2. If `Print Module` fails or returns zero declarations,
  │       send `Search _ inside <module>.` and parse result lines
  │    3. If `Search _ inside <module>.` also fails (e.g., local .v files
  │       without a logical path), send `Search _ inside Top.`
  │       and parse result lines (covers default Top module)
  │
  ├─ For each declaration name:
  │    ├─ Call audit_assumptions(name)
  │    ├─ Accumulate per-theorem results
  │    └─ Check if any axiom's category is in flag_categories → add to flagged list
  │
  ├─ Aggregate axiom usage summary:
  │    Group all classified axioms across theorems
  │    Count dependent theorems per axiom
  │    Sort by dependent count descending
  │
  └─ Assemble ModuleAuditResult
```

### Performance Considerations

Each `Print Assumptions` call requires a Coq round-trip. For a module with N theorems, the batch audit performs N sequential commands (Coq's `Print Assumptions` is stateless and cannot be parallelized within a single backend session). The 30-second budget for 200 theorems (R-P1-1 acceptance criteria) requires each command to complete in under 150 ms — well within typical `Print Assumptions` latency for compiled libraries.

If a single `Print Assumptions` call times out or errors, the batch audit records the error for that theorem and continues with the remaining declarations. The batch never fails entirely due to a single-theorem error.

## Comparison

### Two-Theorem Comparison

```
compare_assumptions([A, B])
  │
  ├─ audit_assumptions(A) → result_A
  ├─ audit_assumptions(B) → result_B
  │
  ├─ Compute axiom sets:
  │    set_A = { axiom.name for axiom in result_A.axioms }
  │    set_B = { axiom.name for axiom in result_B.axioms }
  │
  ├─ shared = set_A ∩ set_B
  ├─ unique_to_A = set_A \ set_B
  ├─ unique_to_B = set_B \ set_A
  │
  ├─ Determine weakest:
  │    If set_A ⊂ set_B → weakest = [A]
  │    If set_B ⊂ set_A → weakest = [B]
  │    If set_A = set_B → weakest = [A, B]
  │    Otherwise → weakest = whichever has fewer elements (ties → both)
  │
  └─ Assemble ComparisonResult (matrix omitted for 2-theorem case)
```

### N-Theorem Comparison (N >= 3)

For three or more theorems, the comparison includes a matrix view:

```
compare_assumptions([T1, T2, ..., Tn])
  │
  ├─ For each Ti: audit_assumptions(Ti) → result_i
  │
  ├─ Collect union of all axiom names across all results
  │
  ├─ For each axiom in the union:
  │    Record which theorems depend on it → MatrixRow
  │
  ├─ shared = axioms present in every theorem
  ├─ unique_to_Ti = axioms present only in Ti (for each i)
  │
  ├─ Determine weakest: theorem(s) with the smallest axiom set
  │    Strict subset takes priority over cardinality
  │    (if Ti's axioms ⊂ Tj's axioms, Ti is strictly weaker regardless of other theorems)
  │
  └─ Assemble ComparisonResult with matrix
```

## Integration with MCP Server

The [MCP Server](mcp-server.md) registers the three `coq_audit` tool variants and delegates to the Assumption Auditing Engine. The MCP server is responsible for:

- Validating inputs (non-empty `name`, non-empty `names` with minimum 2 entries for comparison, valid `module` string)
- Delegating to the Assumption Auditing Engine
- Formatting results into MCP response objects
- Translating engine errors into the MCP error contract

The Assumption Auditing Engine communicates with the Coq backend through the [Proof Session Manager](proof-session.md). It requires an active session with the relevant library loaded.

## Error Handling

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Theorem not found in loaded environment | `NOT_FOUND` | Declaration `{name}` not found in the current Coq environment. |
| Module not found | `NOT_FOUND` | Module `{module}` not found in the current Coq environment. |
| No active Coq session | `SESSION_NOT_FOUND` | No active Coq session. Open a proof session first or ensure the relevant library is loaded. |
| Coq backend crashed during audit | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |
| Single theorem fails during batch audit | (not an error) | Batch continues; the failed theorem's `AssumptionResult` includes an `error` field with the failure reason. |
| Fewer than 2 names in comparison | `INVALID_INPUT` | Comparison requires at least 2 theorem names. |
| `Print Assumptions` output cannot be parsed | `PARSE_ERROR` | Failed to parse `Print Assumptions` output for `{name}`: `{details}` |

## Design Rationale

### Why a dedicated tool rather than a subcommand of `coq_query`

The `coq_query` family of tools (search by structure, symbols, name, type) operates on a pre-built index and returns search results. Assumption auditing operates on a live Coq session, produces fundamentally different data structures (classified axiom lists, not search results), and includes batch and comparison modes that have no analogue in the search tools. A dedicated tool avoids overloading `coq_query` with unrelated parameters and gives Claude Code a clear signal about when to invoke auditing vs. search.

### Why a static registry rather than LLM-based classification

Axiom classification must be deterministic, reproducible, and auditable. The same axiom must receive the same classification every time, regardless of prompt phrasing or model version. A static registry achieves this trivially. The type-based heuristic as a fallback covers axioms that follow known patterns but are not in the registry. LLM-based classification could be layered on top for the `"custom"` category in a future iteration, but the core classification must remain deterministic.

### Why the three-stage classification cascade

Exact match handles the common case (standard library axioms) with perfect accuracy. Prefix match handles axioms from recognized modules that were not individually registered — this is important because Coq libraries evolve and new axioms appear under established module paths. The type-based heuristic catches axioms defined outside the standard library that nonetheless follow well-known patterns (e.g., a user-defined excluded middle variant). Each stage is strictly more speculative than the last, and the cascade stops at the first match, ensuring the most reliable classification is always preferred.

### Why batch audit is sequential rather than parallel

Coq's `Print Assumptions` is a query against a single shared environment. Parallelizing would require multiple Coq backend processes, each loading the same environment — multiplying memory consumption without meaningful latency improvement, since the command is I/O-bound on the Coq process communication, not CPU-bound. Sequential execution within a single session is simpler, has bounded resource usage, and meets the 30-second target for 200 theorems.

### Why comparison uses set operations rather than semantic similarity

Two axioms are either the same axiom or different axioms. There is no meaningful notion of "similar axioms" for the purpose of comparison — `classic` and `NNPP` are logically equivalent but are distinct axioms with distinct names, and a developer may have reasons to prefer one over the other. Set intersection and difference over axiom names is exact, fast, and produces unambiguous results. The `weakest` field uses strict subset inclusion as the primary criterion because it is the only ordering that is mathematically sound — cardinality is a tiebreaker, not a dominance relation.
