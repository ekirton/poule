# Cross-Library Compatibility Analysis

The component that extracts dependency declarations from Coq project files, queries opam repository metadata for version constraints across the full transitive dependency tree, determines whether a mutually satisfying combination of package versions exists, and produces structured conflict reports with plain-language explanations and resolution suggestions. The `/check-compat` slash command (agentic, owned by Claude Code) is the user interface; this document covers the code components it delegates to.

**Feature**: [Cross-Library Compatibility Analysis](../features/compatibility-analysis.md)

---

## Component Diagram

```
Claude Code / LLM
  │
  │ /check-compat slash command (agentic)
  │
  │ Orchestrates pipeline stages, formats final report
  ▼
┌───────────────────────────────────────────────────────────────────────┐
│               Compatibility Analysis Engine                            │
│                                                                        │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐    │
│  │  Dependency Scanner   │  │  Opam Metadata Resolver              │    │
│  │                       │  │                                      │    │
│  │  .opam parsing        │  │  opam show (version constraints)     │    │
│  │  dune-project parsing │  │  Transitive dependency expansion     │    │
│  │  _CoqProject parsing  │  │  Version enumeration                 │    │
│  │                       │  │                                      │    │
│  │  → DependencySet      │  │  → ResolvedConstraintTree            │    │
│  └──────────────────────┘  └──────────────────────────────────────┘    │
│                                                                        │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐    │
│  │  Constraint Parser    │  │  Conflict Detector                   │    │
│  │                       │  │                                      │    │
│  │  opam version ranges  │  │  Constraint intersection             │    │
│  │  Interval arithmetic  │  │  Per-resource satisfaction check     │    │
│  │  Normalization        │  │  Minimal conflict set extraction     │    │
│  │                       │  │                                      │    │
│  │  → VersionConstraint  │  │  → ConflictSet or CompatibleSet     │    │
│  └──────────────────────┘  └──────────────────────────────────────┘    │
│                                                                        │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐    │
│  │  Explanation Builder  │  │  Resolution Suggester                │    │
│  │                       │  │                                      │    │
│  │  Conflict → plain     │  │  Version relaxation candidates      │    │
│  │  language narrative   │  │  Upgrade / downgrade options         │    │
│  │  Transitive chain     │  │  Alternative package suggestions    │    │
│  │  rendering            │  │  Trade-off annotations               │    │
│  │                       │  │                                      │    │
│  │  → ExplanationText    │  │  → list of Resolution                │    │
│  └──────────────────────┘  └──────────────────────────────────────┘    │
└────────┬─────────────────────────────┬────────────────────────────────┘
         │                             │
         │ subprocess calls            │ reads project files
         ▼                             ▼
   ┌───────────┐                ┌──────────────────┐
   │   opam    │                │  .opam           │
   │ show/list │                │  dune-project    │
   └───────────┘                │  _CoqProject     │
    (subprocesses)              └──────────────────┘
                                 (filesystem)
```

The Compatibility Analysis Engine is a set of in-process code components invoked by the `/check-compat` slash command. The slash command (agentic, owned by Claude Code) orchestrates the pipeline — calling each stage in sequence, interpreting intermediate results, and composing the final user-facing report. The code components handle the mechanical work: file parsing, opam querying, constraint arithmetic, and conflict analysis.

---

## Pipeline

The analysis proceeds in five stages. Each stage consumes the output of the previous stage and produces a well-defined intermediate data structure.

### Stage 1: Dependency Scanning

The Dependency Scanner reads dependency declarations from the project's build files. It reuses the file detection logic from the Build System Adapter (see [build-system-integration.md](build-system-integration.md) § Build System Detection) to locate configuration files, then parses each file type for dependency declarations.

```
scan_dependencies(project_dir, hypothetical_additions?)
  │
  ├─ Detect build system and locate config files
  │    (reuses Build System Adapter detection logic)
  │
  ├─ Parse each located file:
  │    .opam         → extract depends field entries
  │    dune-project  → extract (depends ...) stanza entries
  │    _CoqProject   → extract -Q/-R logical path roots, infer package names
  │
  ├─ Merge declarations across files (union, with source tracking)
  │
  ├─ If hypothetical_additions provided:
  │    Append each addition to the merged set (marked as hypothetical)
  │
  ├─ Validate package names against opam repository:
  │    Run: ["opam", "show", "--field=name", package_name]
  │    for each declared dependency
  │    → flag unknown packages with PACKAGE_NOT_FOUND
  │
  └─ Return DependencySet
```

For `_CoqProject` files, which do not declare opam-level dependencies directly, the scanner infers package names from `-Q` and `-R` logical path roots. The mapping from logical paths to opam package names uses the `coq-` prefix convention (e.g., logical root `Mathcomp` maps to `coq-mathcomp-ssreflect`). When inference is ambiguous, the scanner includes all candidates and flags the ambiguity.

### Stage 2: Opam Metadata Resolution

The Opam Metadata Resolver queries opam for the version constraints of each dependency and its transitive dependencies, building a complete constraint tree.

```
resolve_metadata(dependency_set)
  │
  ├─ For each dependency in the set:
  │    │
  │    ├─ Run: ["opam", "show", package_name,
  │    │        "--field=depends,version,all-versions"]
  │    │
  │    ├─ Parse the depends field into a list of
  │    │    (dependency_name, version_constraint) pairs
  │    │
  │    └─ For each transitive dependency not yet resolved:
  │         Recurse (with cycle detection to handle circular opam metadata)
  │
  ├─ Build the full constraint tree:
  │    Each node is a package with its available versions
  │    Each edge carries the version constraint imposed by the parent
  │
  └─ Return ResolvedConstraintTree
```

Opam queries are subprocess calls (same pattern as the Build System Adapter). The resolver caches opam show results within a single analysis run to avoid redundant subprocess invocations for packages that appear multiple times in the tree.

### Stage 3: Constraint Parsing

The Constraint Parser normalizes opam version constraint expressions into a uniform internal representation suitable for intersection and satisfaction testing.

Opam version constraints use a specific syntax: comparison operators (`=`, `!=`, `<`, `>`, `<=`, `>=`), logical combinators (`&`, `|`), and version strings with optional build suffixes (e.g., `8.18~`, `8.19+flambda`). The parser converts each constraint expression into a set of version intervals.

```
parse_constraint(constraint_expression)
  │
  ├─ Tokenize the constraint expression
  │
  ├─ Parse into an AST of comparisons and logical operators
  │
  ├─ Normalize to disjunctive normal form (union of intersections)
  │
  └─ Return VersionConstraint (a set of version intervals)
```

Version comparison follows opam's ordering rules: numeric segments compared numerically, string segments compared lexicographically, tilde (`~`) sorts before any other character at the same position (so `8.18~` < `8.18`).

### Stage 4: Conflict Detection

The Conflict Detector determines whether the full set of constraints can be simultaneously satisfied. It operates per shared resource — each package that appears as a dependency of more than one path through the tree is a potential conflict point.

```
detect_conflicts(constraint_tree)
  │
  ├─ Identify shared resources:
  │    Packages constrained by more than one path through the tree
  │    (Coq version is always a shared resource for Coq projects)
  │
  ├─ For each shared resource:
  │    │
  │    ├─ Collect all constraints on this resource from every path
  │    │
  │    ├─ Intersect the constraint intervals
  │    │    (VersionConstraint intersection using interval arithmetic)
  │    │
  │    ├─ Enumerate available versions of this resource
  │    │    (from opam metadata, already in the constraint tree)
  │    │
  │    ├─ Check whether any available version falls within the intersection
  │    │    → If yes: this resource is satisfiable
  │    │    → If no: this resource is a conflict point
  │    │
  │    └─ If conflict: extract the minimal set of constraints that
  │       produce an empty intersection (for explanation)
  │
  ├─ If all shared resources are satisfiable:
  │    Compute the newest mutually compatible version of each dependency
  │    Return CompatibleSet (verdict: compatible, with version map)
  │
  └─ If any shared resource has a conflict:
     Return ConflictSet (verdict: incompatible, with conflict details)
```

The minimal conflict set extraction identifies the smallest subset of constraints that are mutually unsatisfiable. This is important for explanation quality — reporting all constraints on a resource may include constraints that are not involved in the conflict.

### Stage 5: Explanation and Resolution

**Explanation Builder**: For each conflict, the builder constructs a plain-language explanation by tracing the constraint chain from the user's direct dependencies through intermediate packages to the point of disagreement.

```
build_explanation(conflict)
  │
  ├─ For each constraint in the minimal conflict set:
  │    Trace the path from the user's direct dependency
  │    through transitive dependencies to the conflicting constraint
  │
  ├─ Compose the explanation:
  │    "{package_A} requires {resource} {constraint_A}, but
  │     {package_B} requires {resource} {constraint_B} —
  │     {there is no version of {resource} that satisfies both /
  │      the only versions satisfying both are ...}"
  │
  ├─ If the conflict involves transitive dependencies:
  │    Include the full chain:
  │    "{package_A} depends on {intermediate}, which requires
  │     {resource} {constraint}"
  │
  └─ Return ExplanationText
```

**Resolution Suggester**: For each conflict, the suggester identifies concrete actions that would resolve it by relaxing, upgrading, or downgrading one side of the conflict.

```
suggest_resolutions(conflict, constraint_tree)
  │
  ├─ For each constraint in the minimal conflict set:
  │    │
  │    ├─ Check whether a newer version of the constraining package
  │    │    relaxes the constraint:
  │    │    Query opam for newer versions, parse their constraints
  │    │    → If found: emit UPGRADE resolution with target version
  │    │
  │    ├─ Check whether an older version of the opposing package
  │    │    is compatible:
  │    │    → If found: emit DOWNGRADE resolution with target version
  │    │
  │    └─ Check whether alternative packages provide equivalent
  │         functionality with compatible constraints:
  │         (heuristic: packages with the same name prefix or
  │          in the same opam repository category)
  │         → If found: emit ALTERNATIVE resolution
  │
  ├─ Annotate each resolution with trade-offs:
  │    UPGRADE: "requires updating {package} from {current} to {target},
  │             which may introduce API changes"
  │    DOWNGRADE: "loses features available in {current} but not in {target}"
  │    ALTERNATIVE: "replaces {package} with {alternative}"
  │
  ├─ If no resolution exists within available versions:
  │    Emit NO_RESOLUTION with explicit statement
  │
  └─ Return list of Resolution (sorted: upgrades first, then downgrades,
     then alternatives)
```

---

## Hypothetical Analysis

When the user asks "would adding package X break anything?" or "are my dependencies compatible with Coq 8.19?", the pipeline runs identically but with a modified input:

- **Hypothetical addition**: The Dependency Scanner appends the hypothetical package to the DependencySet (marked as hypothetical so it does not appear as a file modification suggestion).
- **Target Coq version**: The Conflict Detector pins the Coq version constraint to the specified version, then checks whether all other constraints are satisfiable against that pin.

No project files are read or written differently. The modification is to the in-memory DependencySet only.

---

## Relationship to Build System Adapter

The Compatibility Analysis Engine and the Build System Adapter (see [build-system-integration.md](build-system-integration.md)) interact at two points:

1. **Build system detection**: The Dependency Scanner reuses the Build System Adapter's detection logic to locate `.opam`, `dune-project`, and `_CoqProject` files. It does not duplicate the detection algorithm.

2. **opam subprocess pattern**: Both components invoke opam as a subprocess. They use the same subprocess management conventions (fresh process per invocation, output capture, timeout enforcement). However, the Compatibility Analysis Engine only invokes read-only opam commands (`opam show`, `opam list`). It never invokes `opam install` or any switch-modifying operation.

The Dependency Manager in the Build System Adapter provides a `check_dependency_conflicts` function that runs `opam install --dry-run`. The Compatibility Analysis Engine does not use this function. The dry-run approach delegates constraint analysis entirely to opam's solver, which produces opaque output when it fails. The Compatibility Analysis Engine performs its own constraint intersection so that it can identify minimal conflict sets, trace constraint chains, and generate targeted explanations — none of which are possible when the solver is a black box.

---

## Data Structures

**DependencySet** — the merged set of declared dependencies:

| Field | Type | Description |
|-------|------|-------------|
| `dependencies` | list of DeclaredDependency | All declared dependencies, with source tracking |
| `project_dir` | string | Absolute path to the project directory |
| `build_system` | BuildSystem | Detected build system (reuses Build System Adapter's enum) |
| `unknown_packages` | list of string | Package names not found in the opam repository |

**DeclaredDependency** — a single dependency declaration:

| Field | Type | Description |
|-------|------|-------------|
| `package_name` | string | opam package name |
| `version_constraint` | string or null | Constraint from the project file (null if unconstrained) |
| `source_file` | string | Path to the file containing the declaration |
| `hypothetical` | boolean | True if added for hypothetical analysis, not from a project file |

**ResolvedConstraintTree** — the full transitive constraint tree:

| Field | Type | Description |
|-------|------|-------------|
| `root_dependencies` | list of string | The user's direct dependencies (package names) |
| `nodes` | map of package name to PackageNode | All packages in the transitive tree |
| `edges` | list of ConstraintEdge | Directed edges carrying version constraints |

**PackageNode** — a package in the constraint tree:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | opam package name |
| `available_versions` | list of string | All available versions, descending order |
| `installed_version` | string or null | Currently installed version (null if not installed) |

**ConstraintEdge** — a directed constraint from one package to another:

| Field | Type | Description |
|-------|------|-------------|
| `from_package` | string | Package imposing the constraint |
| `to_package` | string | Package being constrained |
| `constraint` | VersionConstraint | The parsed version constraint |
| `raw_constraint` | string | Original opam constraint expression |

**VersionConstraint** — a normalized version constraint:

| Field | Type | Description |
|-------|------|-------------|
| `intervals` | list of VersionInterval | Union of version intervals (disjunctive normal form) |

**VersionInterval** — a single contiguous version range:

| Field | Type | Description |
|-------|------|-------------|
| `lower` | VersionBound or null | Lower bound (null = no lower bound) |
| `upper` | VersionBound or null | Upper bound (null = no upper bound) |

**VersionBound** — one end of a version interval:

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Version string |
| `inclusive` | boolean | Whether the bound includes the version itself |

**ConflictSet** — the result when dependencies are incompatible:

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | string | Always `"incompatible"` |
| `conflicts` | list of Conflict | Each detected conflict |

**CompatibleSet** — the result when dependencies are compatible:

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | string | Always `"compatible"` |
| `version_map` | map of package name to string | Newest mutually compatible version of each dependency |
| `coq_version_range` | VersionConstraint | Range of Coq versions that satisfy all constraints |

**Conflict** — a single detected conflict:

| Field | Type | Description |
|-------|------|-------------|
| `resource` | string | The shared resource (package name, e.g., `"coq"`, `"ocaml"`) |
| `minimal_constraint_set` | list of ConstraintEdge | Smallest set of constraints producing an empty intersection |
| `explanation` | ExplanationText | Plain-language explanation |
| `resolutions` | list of Resolution | Suggested resolution strategies |

**ExplanationText** — a plain-language conflict explanation:

| Field | Type | Description |
|-------|------|-------------|
| `summary` | string | One-sentence conflict summary |
| `constraint_chains` | list of list of string | Each chain traces from a direct dependency through intermediates to the conflict |

**Resolution** — a suggested resolution strategy:

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | string | One of `UPGRADE`, `DOWNGRADE`, `ALTERNATIVE`, `NO_RESOLUTION` |
| `target_package` | string | Package to change |
| `target_version` | string or null | Version to change to (null for `ALTERNATIVE` and `NO_RESOLUTION`) |
| `alternative_package` | string or null | Replacement package (only for `ALTERNATIVE`) |
| `trade_off` | string | Plain-language description of the trade-off |

---

## Error Handling

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Project directory does not exist | `PROJECT_NOT_FOUND` | Return error immediately; no analysis attempted |
| No dependency declarations found in any project file | `NO_DEPENDENCIES` | Return informational result; no conflicts possible |
| `opam` not found on PATH | `TOOL_NOT_FOUND` | Return error naming opam as the missing tool |
| opam show fails for a package | `PACKAGE_NOT_FOUND` | Flag the package in `unknown_packages`; continue analysis for remaining packages |
| opam subprocess timeout | `OPAM_TIMEOUT` | Return partial results with indication of which metadata was not retrieved |
| Circular dependency in opam metadata | (handled internally) | Cycle detection in resolver prevents infinite recursion; cycles are noted in the constraint tree but do not block analysis |
| Version constraint parse failure | `CONSTRAINT_PARSE_ERROR` | Report the unparseable constraint with raw text; skip this edge in conflict detection |

All errors use the standard error format. When surfaced through the `/check-compat` slash command, Claude Code formats them into the user-facing response.

---

## Design Rationale

### Own constraint analysis vs. delegate to opam solver

The Build System Adapter already wraps `opam install --dry-run` for conflict detection. The Compatibility Analysis Engine does not reuse that mechanism because the opam solver is a satisfiability engine, not an explanation engine. When the solver fails, its output describes its internal search process — which variable it tried, which constraint it propagated, which backtrack it attempted — not which user-visible packages disagree or what the user can do about it. By performing constraint intersection directly, the engine can identify minimal conflict sets, trace constraint chains through the transitive tree, and generate targeted resolution suggestions. This requires more code than delegating to the solver, but the entire value of the feature depends on explanation quality.

### Constraint parsing rather than string comparison

Opam version constraints are not simple strings — they are logical expressions over ordered version identifiers. Comparing them requires parsing into interval sets and computing intersections. String-level comparison (e.g., checking whether two constraint strings are "the same") would miss cases where differently-written constraints are actually compatible or actually conflicting. The interval arithmetic approach handles all cases correctly: ranges, disjunctions, negations, and the tilde sort-before semantics.

### Subprocess per opam query

Each `opam show` invocation spawns a fresh subprocess, following the same pattern as the Build System Adapter. Batching multiple queries into a single opam invocation is not supported by opam's CLI interface (there is no "show multiple packages in one call" mode). The per-query subprocess cost is acceptable because a typical project has 5–20 direct dependencies, and transitive expansion rarely exceeds 100 unique packages. The resolver caches results within a single analysis run, so each package is queried at most once.

### Slash command as orchestrator

The `/check-compat` slash command is agentic — it is a prompt that directs Claude Code to invoke the code components in sequence. This keeps the pipeline flexible: Claude Code can skip stages (e.g., skip resolution suggestions if there are no conflicts), adapt explanations to context (e.g., simplify for a user who asked a yes/no question), and handle hypothetical queries by modifying the input to Stage 1. The code components are stateless functions that receive inputs and return outputs; the orchestration logic lives in the slash command prompt, not in code.

## Boundary Contracts

### Slash Command → Compatibility Analysis Engine

| Property | Value |
|----------|-------|
| Mechanism | In-process function calls, invoked by Claude Code during `/check-compat` execution |
| Direction | Request-response (each stage called independently) |
| Input per stage | Stage 1: project directory + optional hypothetical additions. Stage 2: DependencySet. Stage 3: raw constraint strings (within Stage 2 internally). Stage 4: ResolvedConstraintTree. Stage 5: ConflictSet. |
| Output per stage | DependencySet, ResolvedConstraintTree, ConflictSet or CompatibleSet, list of Explanation + Resolution |
| Statefulness | Stateless — no data persists between invocations |

### Compatibility Analysis Engine → opam (subprocess)

| Property | Value |
|----------|-------|
| Mechanism | Subprocess invocation (fresh process per query) |
| Direction | Request-response |
| Commands used | `opam show` (package metadata), `opam list` (installed packages) |
| Read-only | Yes — no switch-modifying commands are ever invoked |
| Timeout | Configurable per subprocess; default 30 seconds |
| Caching | Results cached in-memory within a single analysis run |

### Compatibility Analysis Engine → Build System Adapter (shared logic)

| Property | Value |
|----------|-------|
| Mechanism | Shared build system detection function (in-process) |
| Direction | Call |
| Purpose | Locate `.opam`, `dune-project`, and `_CoqProject` files in the project directory |
| Scope | Detection only — the Compatibility Analysis Engine does not invoke build execution or dependency management functions |
