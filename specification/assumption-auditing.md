# Assumption Auditing

Axiom dependency extraction, classification, batch auditing, and comparison for Coq theorems via the `Print Assumptions` command.

**Architecture**: [assumption-auditing.md](../doc/architecture/assumption-auditing.md)

---

## 1. Purpose

Define the assumption auditing component that extracts axiom dependencies from Coq theorems, classifies each axiom against a known-axiom registry, supports batch auditing of entire modules, and compares assumption profiles across theorems — enabling Claude Code to surface foundational dependencies through MCP tools.

## 2. Scope

**In scope**: Single-theorem assumption extraction via `Print Assumptions`, output parsing, axiom/opaque separation, three-stage axiom classification (exact match, prefix match, type heuristic), known-axiom registry structure, batch module auditing with per-theorem error isolation, multi-theorem comparison with set operations and matrix view, result assembly for all three modes.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), Coq backend process management (owned by coq-proof-backend), search index construction (owned by extraction pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Assumption | An axiom or opaque dependency that a theorem relies on, as reported by `Print Assumptions` |
| Axiom | A declaration whose kind is `Axiom` or `Parameter` in the Coq environment |
| Opaque dependency | A declaration ended with `Qed` or `Admitted` that blocks reduction |
| Known-axiom registry | A static declarative data structure mapping fully qualified axiom names and module prefixes to categories and explanations |
| Closed theorem | A theorem with no axiom dependencies beyond Coq's core, as indicated by `Print Assumptions` returning "Closed under the global context" |
| Flagged theorem | A theorem whose axiom dependencies include at least one axiom in a caller-specified set of categories |
| Weakest theorem | Among compared theorems, the one(s) with the fewest axiom dependencies; strict subset inclusion takes priority over cardinality |

## 4. Behavioral Requirements

### 4.1 Single-Theorem Auditing

#### audit_assumptions(name)

- REQUIRES: `name` is a non-empty string containing a fully qualified Coq theorem name. An active Coq session exists with the relevant library loaded.
- ENSURES: Sends `Print Assumptions <name>.` to the Coq backend via the Proof Session Manager's `submit_command` operation (coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1 — coq-lsp cannot capture Print output). Parses the response. Separates axioms from opaque dependencies. Classifies each axiom. Returns an AssumptionResult.
- MAINTAINS: The Coq session state is unchanged after the call. No side effects on the proof environment.

> **Given** a theorem `Coq.Arith.PeanoNat.Nat.add_comm` in the loaded environment that depends on no axioms
> **When** `audit_assumptions("Coq.Arith.PeanoNat.Nat.add_comm")` is called
> **Then** an AssumptionResult is returned with `is_closed = true`, empty `axioms`, and empty `opaque_dependencies`

> **Given** a theorem `my_theorem` that depends on `Coq.Logic.Classical_Prop.classic`
> **When** `audit_assumptions("my_theorem")` is called
> **Then** an AssumptionResult is returned with `is_closed = false` and `axioms` containing a ClassifiedAxiom with `category = "classical"` and a non-empty `explanation`

> **Given** no active Coq session
> **When** `audit_assumptions("anything")` is called
> **Then** a `SESSION_NOT_FOUND` error is returned

### 4.2 Output Parsing

The component shall parse `Print Assumptions` output according to two forms:

1. When the output is `Closed under the global context`, the component shall produce `is_closed = true` with empty axiom and opaque dependency lists.
2. When the output contains one dependency per line in the format `<qualified_name> : <type>`, the component shall split each line on the first ` : ` separator, treating the left side as the fully qualified name and the right side as the pretty-printed type.

> **Given** Coq returns `Closed under the global context`
> **When** the output is parsed
> **Then** `is_closed = true`, `axioms = []`, `opaque_dependencies = []`

> **Given** Coq returns two lines: `Classic : forall P : Prop, P \/ ~ P` and `my_lemma : nat -> nat`
> **When** the output is parsed
> **Then** two dependencies are extracted, each with the correct `name` and `type` fields

### 4.3 Axiom/Opaque Separation

After parsing, the component shall classify each dependency as axiom or opaque:

1. The component shall query the Coq environment to determine the declaration kind via the Proof Session Manager's `submit_command` operation (coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1 — coq-lsp cannot capture About output).
2. When the declaration kind is `Axiom` or `Parameter`, the component shall classify it as an axiom.
3. When the declaration is opaque (ended with `Qed` or is `Admitted`), the component shall classify it as an opaque dependency.
4. When the declaration kind cannot be determined, the component shall treat it as an axiom.

> **Given** a dependency `my_lemma` whose declaration kind is opaque (`Qed`)
> **When** axiom/opaque separation runs
> **Then** `my_lemma` appears in `opaque_dependencies`, not in `axioms`

> **Given** a dependency from a `.vo`-only library with no source, whose kind cannot be determined
> **When** axiom/opaque separation runs
> **Then** the dependency is treated as an axiom (conservative default)

### 4.4 Axiom Classification

The component shall classify each axiom through a three-stage cascade, stopping at the first match:

**Stage 1 — Exact match**: Look up the fully qualified axiom name in the known-axiom registry. When found, return the registry's category and explanation.

**Stage 2 — Prefix match**: Check whether the axiom name falls under a known module prefix (e.g., any name under `Coq.Logic.Classical_Prop` maps to `"classical"`). When matched, return the category and a generic explanation for that module.

**Stage 3 — Type-based heuristic**: Inspect the axiom's type string for structural indicators of known categories. Fire only on well-established patterns. When matched, return the inferred category and a generic explanation.

**Default**: When no stage matches, return `category = "custom"` with explanation `"User-defined axiom. Review manually for consistency."`.

- REQUIRES: `axiom_name` is a non-empty string. `axiom_type` is a non-empty string.
- ENSURES: Returns exactly one (category, explanation) pair. The category is a valid AxiomCategory value.
- MAINTAINS: Classification is deterministic — the same (axiom_name, axiom_type) pair always produces the same (category, explanation).

> **Given** axiom name `Coq.Logic.Classical_Prop.classic`
> **When** classification runs
> **Then** Stage 1 matches: `category = "classical"`, explanation describes the law of excluded middle

> **Given** axiom name `Coq.Logic.Classical_Prop.some_new_variant` not individually registered
> **When** classification runs
> **Then** Stage 2 matches via the `Coq.Logic.Classical_Prop` prefix: `category = "classical"`

> **Given** axiom name `MyLib.custom_em` with type `forall P : Prop, P \/ ~ P`
> **When** classification runs
> **Then** Stage 3 matches the excluded-middle pattern: `category = "classical"`

> **Given** axiom name `MyLib.my_axiom` with type `nat -> nat` matching no known pattern
> **When** classification runs
> **Then** `category = "custom"`, explanation = `"User-defined axiom. Review manually for consistency."`

### 4.5 Known-Axiom Registry

The registry shall be a static declarative data structure containing at minimum the following entries:

| Category | Axiom Name | Description |
|----------|-----------|-------------|
| `classical` | `Coq.Logic.Classical_Prop.classic` | Law of excluded middle |
| `classical` | `Coq.Logic.Classical_Prop.NNPP` | Double-negation elimination |
| `classical` | `Coq.Logic.ClassicalEpsilon.excluded_middle_informative` | Informative excluded middle |
| `classical` | `Coq.Logic.Decidable.dec_not_not` | Decidable double negation |
| `extensionality` | `Coq.Logic.FunctionalExtensionality.functional_extensionality_dep` | Dependent functional extensionality |
| `extensionality` | `Coq.Logic.PropExtensionality.propositional_extensionality` | Propositional extensionality |
| `choice` | `Coq.Logic.IndefiniteDescription.constructive_indefinite_description` | Indefinite description |
| `choice` | `Coq.Logic.ClassicalChoice.choice` | Classical choice |
| `choice` | `Coq.Logic.Epsilon.epsilon` | Hilbert's epsilon |
| `proof_irrelevance` | `Coq.Logic.ProofIrrelevance.proof_irrelevance` | All proofs of a Prop are equal |
| `proof_irrelevance` | `Coq.Logic.JMeq.JMeq_eq` | Heterogeneous equality collapse |

The registry shall also include module-prefix mappings for Stage 2 classification:

| Module Prefix | Category |
|---------------|----------|
| `Coq.Logic.Classical_Prop` | `classical` |
| `Coq.Logic.ClassicalEpsilon` | `classical` |
| `Coq.Logic.FunctionalExtensionality` | `extensionality` |
| `Coq.Logic.PropExtensionality` | `extensionality` |
| `Coq.Logic.ChoiceFacts` | `choice` |
| `Coq.Logic.IndefiniteDescription` | `choice` |
| `Coq.Logic.ClassicalChoice` | `choice` |
| `Coq.Logic.Epsilon` | `choice` |
| `Coq.Logic.ProofIrrelevance` | `proof_irrelevance` |
| `Coq.Logic.ProofIrrelevanceFacts` | `proof_irrelevance` |

### 4.6 Batch Module Auditing

#### audit_module(module, flag_categories)

- REQUIRES: `module` is a non-empty string containing a fully qualified Coq module name. An active Coq session exists with the module loaded. `flag_categories` is a list of valid AxiomCategory values; defaults to `["classical", "choice", "proof_irrelevance", "custom"]`.
- ENSURES: Enumerates all proof-carrying declarations using a three-strategy cascade via `submit_command` (coqtop subprocess routing per [proof-session.md](proof-session.md) §4.4.1): (1) send `Print Module <module>.` and parse the response; (2) if `Print Module` fails or returns zero declarations, send `Search _ inside <module>.` and parse each result line; (3) if `Search _ inside <module>.` also fails, send `Search _ inside Top.` and parse each result line — this covers local `.v` files loaded as scripts whose declarations reside in the default `Top` module. If all three strategies return zero declarations, a `NOT_FOUND` error is raised. Calls `audit_assumptions` for each declaration sequentially. Aggregates results into a ModuleAuditResult. Theorems with axioms in `flag_categories` appear in `flagged_theorems`. The `axiom_summary` is sorted by `dependent_count` descending.
- MAINTAINS: A single-theorem error does not abort the batch. The failed theorem's AssumptionResult includes an `error` field with the failure reason, and auditing continues with the remaining declarations.

> **Given** a module `MyLib.Foo` containing 3 theorems, 2 of which use `classic`
> **When** `audit_module("MyLib.Foo", flag_categories=["classical"])` is called
> **Then** a ModuleAuditResult is returned with `theorem_count = 3`, `flagged_theorems` containing the 2 classical theorems, and `axiom_summary` listing `classic` with `dependent_count = 2`

> **Given** a module `MyLib.Bar` containing 50 theorems, and theorem 23 causes a parse error
> **When** `audit_module("MyLib.Bar")` is called
> **Then** the batch completes with `theorem_count = 50`, theorem 23's result contains an `error` field, and the remaining 49 theorems have normal results

> **Given** a local `.v` file defining 3 lemmas, loaded into a proof session without a logical path (declarations reside in `Top`)
> **When** `audit_module("algebra")` is called and both `Print Module algebra.` and `Search _ inside algebra.` fail
> **Then** the component falls back to `Search _ inside Top.`, enumerates the 3 declarations, and returns a ModuleAuditResult with `theorem_count = 3`

> **Given** a non-existent module `NoSuch.Module` where `Print Module`, `Search _ inside <module>`, and `Search _ inside Top.` all return no results
> **When** `audit_module("NoSuch.Module")` is called
> **Then** a `NOT_FOUND` error is returned

### 4.7 Assumption Comparison

#### compare_assumptions(names)

- REQUIRES: `names` is a list of fully qualified theorem names with at least 2 entries. An active Coq session exists with all named theorems in scope.
- ENSURES: Calls `audit_assumptions` for each theorem. Computes set intersection (shared axioms), set difference (unique axioms per theorem), and identifies the weakest theorem(s). When `names` contains 3 or more entries, includes a `matrix` field. Returns a ComparisonResult.
- MAINTAINS: Weakest determination uses strict subset inclusion as the primary criterion. When no strict subset relationship exists, the theorem(s) with the fewest axiom dependencies are weakest. Ties result in multiple entries in `weakest`.

**Two-theorem comparison:**

> **Given** theorem A depends on `{classic, functional_extensionality_dep}` and theorem B depends on `{classic}`
> **When** `compare_assumptions(["A", "B"])` is called
> **Then** `shared_axioms` contains `classic`, `unique_axioms["A"]` contains `functional_extensionality_dep`, `unique_axioms["B"]` is empty, `weakest = ["B"]`, and `matrix` is absent

**N-theorem comparison (N >= 3):**

> **Given** theorems T1 (axioms: `{classic}`), T2 (axioms: `{classic, choice}`), T3 (axioms: `{choice}`)
> **When** `compare_assumptions(["T1", "T2", "T3"])` is called
> **Then** `shared_axioms` is empty (no axiom is in all three), `matrix` has 2 rows (`classic` present in T1/T2, `choice` present in T2/T3), and `weakest` contains both `T1` and `T3` (each has 1 axiom, neither is a subset of the other)

> **Given** fewer than 2 names are provided
> **When** `compare_assumptions(["only_one"])` is called
> **Then** an `INVALID_INPUT` error is returned

## 5. Data Model

### AssumptionResult

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; fully qualified theorem name |
| `is_closed` | boolean | Required; true when no axiom dependencies exist |
| `axioms` | ordered list of ClassifiedAxiom | Required; empty when `is_closed = true` |
| `opaque_dependencies` | ordered list of OpaqueDependency | Required; empty when `is_closed = true` |
| `error` | string or null | Null on success; failure reason when this theorem failed during batch auditing |

### ClassifiedAxiom

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; fully qualified axiom name |
| `type` | string | Required; pretty-printed Coq type |
| `category` | AxiomCategory | Required |
| `explanation` | string | Required; non-empty plain-language description |

### AxiomCategory

Enumeration with exactly five values:

| Value | Meaning |
|-------|---------|
| `"classical"` | Law of excluded middle, double-negation elimination, and equivalent principles |
| `"extensionality"` | Functional extensionality, propositional extensionality |
| `"choice"` | Axiom of choice variants, indefinite description |
| `"proof_irrelevance"` | All proofs of a proposition are equal |
| `"custom"` | User-defined axioms not in the known-axiom registry |

### OpaqueDependency

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; fully qualified name |
| `type` | string | Required; pretty-printed Coq type |

### ModuleAuditResult

| Field | Type | Constraints |
|-------|------|-------------|
| `module` | string | Required; fully qualified module name |
| `theorem_count` | non-negative integer | Required; total theorems audited |
| `axiom_free_count` | non-negative integer | Required; ≤ `theorem_count` |
| `axiom_summary` | ordered list of AxiomUsageSummary | Required; sorted by `dependent_count` descending |
| `flagged_theorems` | ordered list of FlaggedTheorem | Required; empty when no theorems match flagged categories |
| `per_theorem` | ordered list of AssumptionResult | Required; one entry per audited theorem |

### AxiomUsageSummary

| Field | Type | Constraints |
|-------|------|-------------|
| `axiom_name` | string | Required; fully qualified axiom name |
| `category` | AxiomCategory | Required |
| `dependent_count` | non-negative integer | Required; ≥ 1 |

### FlaggedTheorem

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; fully qualified theorem name |
| `flagged_axioms` | ordered list of ClassifiedAxiom | Required; non-empty |

### ComparisonResult

| Field | Type | Constraints |
|-------|------|-------------|
| `theorems` | ordered list of string | Required; the input theorem names, preserving input order |
| `shared_axioms` | ordered list of ClassifiedAxiom | Required; axioms present in every theorem |
| `unique_axioms` | map of string to ordered list of ClassifiedAxiom | Required; keyed by theorem name |
| `matrix` | ordered list of MatrixRow or null | Required when `len(theorems) >= 3`; null otherwise |
| `weakest` | ordered list of string | Required; non-empty; theorem name(s) with fewest axiom dependencies |

### MatrixRow

| Field | Type | Constraints |
|-------|------|-------------|
| `axiom` | ClassifiedAxiom | Required |
| `present_in` | ordered list of string | Required; non-empty subset of `theorems` |

## 6. Interface Contracts

### Assumption Auditing Engine → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `submit_command` for `Print Assumptions <name>.`, `Print Module <module>.`, and `About <name>.` (declaration kind query) — all routed through the coqtop subprocess per [proof-session.md](proof-session.md) §4.4.1 because coq-lsp cannot capture vernacular output |
| Concurrency | Serialized — one command at a time per session |
| Error strategy | `NOT_FOUND` → propagate to caller. `SESSION_NOT_FOUND` → propagate. `BACKEND_CRASHED` → propagate. `PARSE_ERROR` → propagate for single-theorem; record and continue for batch. |
| Idempotency | All operations are read-only queries; safe to retry on transient failure |

### MCP Server → Assumption Auditing Engine

| Property | Value |
|----------|-------|
| Operations used | `audit_assumptions`, `audit_module`, `compare_assumptions` |
| Input validation | MCP server validates: `name` is non-empty, `names` has ≥ 2 entries, `module` is non-empty, `flag_categories` contains only valid AxiomCategory values |
| Error strategy | Engine errors are translated to MCP error responses by the MCP server |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Empty `name` argument | `INVALID_INPUT` | Theorem name must be non-empty. |
| Empty `module` argument | `INVALID_INPUT` | Module name must be non-empty. |
| Fewer than 2 entries in `names` | `INVALID_INPUT` | Comparison requires at least 2 theorem names. |
| Invalid value in `flag_categories` | `INVALID_INPUT` | Unknown axiom category: `{value}`. Valid categories: classical, extensionality, choice, proof_irrelevance, custom. |

### 7.2 State Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| No active Coq session | `SESSION_NOT_FOUND` | No active Coq session. Open a proof session first or ensure the relevant library is loaded. |

### 7.3 Dependency Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Theorem not found in loaded environment | `NOT_FOUND` | Declaration `{name}` not found in the current Coq environment. |
| Module not found | `NOT_FOUND` | Module `{module}` not found in the current Coq environment. |
| Coq backend crashed during audit | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |
| `Print Assumptions` output cannot be parsed | `PARSE_ERROR` | Failed to parse `Print Assumptions` output for `{name}`: `{details}` |

### 7.4 Batch Error Isolation

When a single theorem fails during batch auditing (`audit_module`), the batch shall not terminate. The failed theorem's AssumptionResult shall have its `error` field set to the failure reason (error code and message). All other theorems are audited normally. The `theorem_count` includes failed theorems. The `axiom_free_count` excludes failed theorems.

## 8. Non-Functional Requirements

- Batch auditing of 200 theorems in a compiled module shall complete within 30 seconds.
- Each `Print Assumptions` round-trip shall complete within 150 ms for compiled libraries.
- Classification of a single axiom (all three stages) shall complete within 1 ms.
- The known-axiom registry shall load into memory within 10 ms at startup.
- Memory usage for a single ModuleAuditResult with 200 theorems and 50 distinct axioms shall not exceed 10 MB.

## 9. Examples

### Single-theorem audit — closed theorem

```
audit_assumptions("Coq.Arith.PeanoNat.Nat.add_0_r")

Coq output: "Closed under the global context"

Result:
{
  "name": "Coq.Arith.PeanoNat.Nat.add_0_r",
  "is_closed": true,
  "axioms": [],
  "opaque_dependencies": [],
  "error": null
}
```

### Single-theorem audit — axiom dependencies

```
audit_assumptions("my_classical_theorem")

Coq output:
  Coq.Logic.Classical_Prop.classic : forall P : Prop, P \/ ~ P
  helper_lemma : nat -> nat -> Prop

Result:
{
  "name": "my_classical_theorem",
  "is_closed": false,
  "axioms": [
    {
      "name": "Coq.Logic.Classical_Prop.classic",
      "type": "forall P : Prop, P \\/ ~ P",
      "category": "classical",
      "explanation": "Law of excluded middle: for any proposition P, either P or its negation holds."
    }
  ],
  "opaque_dependencies": [
    {
      "name": "helper_lemma",
      "type": "nat -> nat -> Prop"
    }
  ],
  "error": null
}
```

### Batch module audit

```
audit_module("MyLib.Arithmetic", flag_categories=["classical"])

Module contains 3 theorems: add_comm (closed), add_assoc (closed), decide_eq (uses classic).

Result:
{
  "module": "MyLib.Arithmetic",
  "theorem_count": 3,
  "axiom_free_count": 2,
  "axiom_summary": [
    {"axiom_name": "Coq.Logic.Classical_Prop.classic", "category": "classical", "dependent_count": 1}
  ],
  "flagged_theorems": [
    {"name": "MyLib.Arithmetic.decide_eq", "flagged_axioms": [{"name": "Coq.Logic.Classical_Prop.classic", ...}]}
  ],
  "per_theorem": [
    {"name": "MyLib.Arithmetic.add_comm", "is_closed": true, "axioms": [], "opaque_dependencies": [], "error": null},
    {"name": "MyLib.Arithmetic.add_assoc", "is_closed": true, "axioms": [], "opaque_dependencies": [], "error": null},
    {"name": "MyLib.Arithmetic.decide_eq", "is_closed": false, "axioms": [...], "opaque_dependencies": [], "error": null}
  ]
}
```

### Comparison — two theorems

```
compare_assumptions(["thm_A", "thm_B"])

thm_A axioms: {classic, functional_extensionality_dep}
thm_B axioms: {classic}

Result:
{
  "theorems": ["thm_A", "thm_B"],
  "shared_axioms": [{"name": "Coq.Logic.Classical_Prop.classic", "category": "classical", ...}],
  "unique_axioms": {
    "thm_A": [{"name": "Coq.Logic.FunctionalExtensionality.functional_extensionality_dep", "category": "extensionality", ...}],
    "thm_B": []
  },
  "matrix": null,
  "weakest": ["thm_B"]
}
```

## 10. Language-Specific Notes (Python)

- Package location: `src/poule/auditing/`.
- Entry points: `async def audit_assumptions(session_manager, name)`, `async def audit_module(session_manager, module, flag_categories)`, `async def compare_assumptions(session_manager, names)`.
- Use `asyncio` for Coq backend communication via the Proof Session Manager.
- The known-axiom registry shall be a module-level constant (dict of str to tuple of AxiomCategory and str), loaded at import time.
- Module-prefix mappings shall be a separate ordered list of (prefix, category) tuples, checked in order during Stage 2.
- Type-based heuristic patterns shall be compiled `re.Pattern` objects, stored in a module-level list.
- AxiomCategory shall be a `str` enum (`enum.StrEnum` on Python 3.11+, `str` + `enum.Enum` otherwise).
- Data structures (AssumptionResult, ClassifiedAxiom, etc.) shall be `dataclasses.dataclass` with frozen=True.
- Parsing of `Print Assumptions` output shall use `str.split(" : ", maxsplit=1)` per line.
