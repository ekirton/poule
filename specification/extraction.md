# Coq Library Extraction

Offline extraction of declarations from compiled Coq/Rocq libraries into the search index.

**Architecture**: [coq-extraction.md](../doc/architecture/coq-extraction.md), [coq-normalization.md](../doc/architecture/coq-normalization.md), [storage.md](../doc/architecture/storage.md)

---

## 1. Purpose

Define the extraction pipeline that reads compiled `.vo` files via coq-lsp, converts declarations to normalized expression trees, computes derived data (symbol sets, WL histograms, dependencies), and writes everything to a SQLite index database.

## 2. Scope

**In scope**: Backend interface (coq-lsp), library discovery, version detection, two-pass extraction pipeline, kind mapping, module path derivation, progress reporting, CLI entry point.

**Out of scope**: Normalization algorithms (owned by coq-normalization and cse-normalization), storage schema (owned by storage), retrieval logic.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Backend | The external tool (coq-lsp) used to read `.vo` files and extract declarations |
| Pass 1 | Per-declaration processing: parse, normalize, extract symbols, compute WL vectors, write to database |
| Pass 2 | Post-insertion dependency resolution: extract and write dependency edges |
| Kind mapping | Translation from Coq declaration forms to storage kind values |

## 4. Behavioral Requirements

### 4.1 Backend Interface

The system shall define a `Backend` protocol with operations:

#### list_declarations(vo_path)

- REQUIRES: `vo_path` is a path to a compiled `.vo` file.
- ENSURES: Returns a list of `(name, kind, constr_t)` tuples for all declarations in the file. Each `name` shall be a fully qualified canonical name (e.g., `Coq.Arith.PeanoNat.Nat.add_comm`), matching the format required by the `declarations.name` field (see [index-entities.md](../doc/architecture/data-models/index-entities.md)). The `constr_t` value is backend-dependent: backends that provide kernel terms return a `ConstrNode`; backends that provide only metadata (e.g., coq-lsp Search output) return a dict containing at minimum `{"type_signature": str, "source": str}`.
- MAINTAINS: The `kind` value for each declaration is determined by the kind detection mechanism (§4.1.1).

#### 4.1.1 Kind Detection

The backend shall determine each declaration's kind during `list_declarations`. The mechanism is backend-dependent because not all backends return kind information directly from declaration listing.

**coq-lsp backend:** The `Search _ inside M.` command returns `(name, type_sig)` pairs without declaration kinds. The backend shall issue an `About <name>.` Vernac command per declaration and parse the response to determine the kind. About queries for declarations within a single module may be batched into a single synthetic document with one command per line (batch size capped at 100 commands per document). The contract (one About per declaration, version-dependent parsing) is unchanged.

The `About` response format is version-dependent:

| Version | Format | Kind extraction |
|---------|--------|----------------|
| Coq ≤ 8.x | `<name> is [a] <Kind>.` | Extract `<Kind>` from the `is [a]` pattern |
| Rocq 9.x | Multi-line; includes `Expands to: <Category> <path>` | Map `<Category>`: `Constant` → `definition`, `Inductive` → `inductive`, `Constructor` → `constructor`, `Notation` → `notation` |
| Rocq 9.x | `Ltac <path>` (single line) | Kind is `ltac` (excluded via §4.2) |
| Rocq 9.x | `Module <path>` (single line) | Kind is `module` (excluded via §4.2) |

**Parsing precedence (coq-lsp):** The `About` response may contain multiple `Expands to:` lines. When a notation aliases a real constant, the response includes both `Expands to: Notation <path>` and `Expands to: Constant <path>` (or `Inductive`/`Constructor`). The backend shall prefer the first `Constant`, `Inductive`, or `Constructor` category over `Notation`. If only `Notation` categories are present, the kind is `"notation"` (excluded via §4.2). The Rocq 9.x `"Expands to:"` pattern takes precedence over the Coq ≤ 8.x `"is [a]"` pattern.

**Fallback:** When `About` returns `"<name> not a defined object."` or no parseable kind information, the backend shall default to `"definition"`.

> **Given** a declaration `Nat.add` in Rocq 9.x where `About` returns `Expands to: Constant Corelib.Init.Nat.add`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value is `"definition"` (Constant maps to definition via §4.2).

> **Given** a declaration `Nat.add_comm` in Rocq 9.x where `About` returns `"Nat.add_comm not a defined object."`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value defaults to `"definition"`.

> **Given** a declaration `Nat.add` in Coq 8.x where `About` returns `"Nat.add is a Definition."`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value is `"definition"` (Definition maps to definition via §4.2).

> **Given** a notation `pred` in Rocq 9.x where `About` returns `Notation pred := Nat.pred\nExpands to: Notation Corelib.Init.Peano.pred\n...\nExpands to: Constant Corelib.Init.Nat.pred`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value is `"definition"` (the `Constant` category is preferred over `Notation`).

> **Given** a tactic `reflexivity` in Rocq 9.x where `About` returns `Ltac Corelib.Init.Ltac.reflexivity`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value is `"ltac"` (excluded via §4.2).

> **Given** a module `Decimal` in Rocq 9.x where `About` returns `Module Corelib.Init.Decimal`,
> **When** `list_declarations` processes this declaration,
> **Then** the kind value is `"module"` (excluded via §4.2).

#### 4.1.2 Fully Qualified Name Derivation

Backends that do not return fully qualified names directly (e.g., coq-lsp `Search` returns short names like `Nat.add_comm`) shall derive them during `list_declarations`. The derivation mechanism is backend-dependent:

**coq-lsp backend:** The fully qualified name is constructed by prepending the `.vo` file's logical module path to the short name returned by `Search`. The logical module path is derived from the `.vo` file path using heuristic path parsing (stripping known prefixes such as `user-contrib/`, `theories/`, and version-specific prefixes like `Stdlib/`). The resulting name has the form `<logical_module_path>.<short_name>` (e.g., `Coq.Arith.PeanoNat` + `Nat.add_comm` → `Coq.Arith.PeanoNat.Nat.add_comm`).

> **Given** a `.vo` file at `/path/to/user-contrib/Stdlib/Arith/PeanoNat.vo` containing a declaration `Nat.add_comm`,
> **When** `list_declarations` processes this file,
> **Then** the returned name is `Coq.Arith.PeanoNat.Nat.add_comm`.

> **Given** a `.vo` file at `/path/to/user-contrib/mathcomp/ssreflect/ssrbool.vo` containing a declaration `negb_involutive`,
> **When** `list_declarations` processes this file,
> **Then** the returned name is `mathcomp.ssreflect.ssrbool.negb_involutive`.

#### get_type(name)

- REQUIRES: `name` is a fully qualified declaration name.
- ENSURES: Returns the type's `ConstrNode` (with pre-resolved FQNs), or `None` if type extraction is unsupported for this declaration kind.

#### pretty_print(name)

- REQUIRES: `name` is a fully qualified declaration name.
- ENSURES: Returns the human-readable statement string.

#### pretty_print_type(name)

- REQUIRES: `name` is a fully qualified declaration name.
- ENSURES: Returns the human-readable type signature string, or `None`.

#### get_dependencies(name)

- REQUIRES: `name` is a fully qualified declaration name.
- ENSURES: Returns a list of `(target_name, relation)` pairs.

#### locate(name)

- REQUIRES: `name` is a short display name or infix operator string (e.g., `"nat"`, `"+"`, `"list"`).
- ENSURES: Returns the resolution result:
  - A single FQN string when the name resolves unambiguously (e.g., `"Coq.Init.Datatypes.nat"`).
  - A list of FQN strings when the name is ambiguous (e.g., `[\"Coq.Init.Nat.add\", \"Coq.ZArith.BinInt.Z.add\"]`).
  - `None` when the name cannot be resolved (e.g., user-defined name not in the Coq environment).

**coq-lsp backend:** Issues a `Locate <name>.` Vernac command (or `Locate "<op>".` for infix operators). Parses the response to extract the FQN(s). `Locate` queries may be batched into shared synthetic documents (≤100 commands per document) following the same pattern as kind detection (§4.1.1). The response format is version-dependent:

| Response pattern | Interpretation |
|-----------------|---------------|
| `Constant <fqn>` | Single FQN; return `<fqn>` |
| `Inductive <fqn>` | Single FQN; return `<fqn>` |
| `Constructor <fqn>` | Single FQN; return `<fqn>` |
| `Notation <path>` | Skip — notations are not indexable symbols |
| Multiple `Constant`/`Inductive`/`Constructor` lines | Ambiguous; return list of all FQNs |
| Error or `"<name> not a defined object"` | Unresolvable; return `None` |

> **Given** a Coq environment where `nat` is defined,
> **When** `locate("nat")` is called,
> **Then** it returns `"Coq.Init.Datatypes.nat"`.

> **Given** a Coq environment where `+` resolves to `Nat.add`,
> **When** `locate("+")` is called,
> **Then** it returns `"Coq.Init.Nat.add"`.

> **Given** a name `my_custom_def` not in the Coq environment,
> **When** `locate("my_custom_def")` is called,
> **Then** it returns `None`.

#### detect_version()

- ENSURES: Returns the Coq/Rocq version string (e.g., `"8.19"`).

### 4.2 Kind Mapping

| Coq Declaration Form | Storage Kind |
|---------------------|-------------|
| `Lemma` | `lemma` |
| `Theorem` | `theorem` |
| `Definition`, `Let`, `Coercion`, `Canonical Structure` | `definition` |
| `Inductive`, `Record`, `Class` | `inductive` |
| `Constructor` | `constructor` |
| `Instance` | `instance` |
| `Axiom`, `Parameter`, `Conjecture` | `axiom` |
| `Notation`, `Abbreviation`, `Section Variable` | *(excluded — not indexed)* |
| `Ltac`, `Module` | *(excluded — not indexed)* |

Excluded forms have no kernel term and shall be silently skipped.

**Unknown kinds:** When the detected kind string does not match any row in the table above (including the excluded forms), `map_kind` shall return `"definition"`. The `map_kind` function shall return `None` only for explicitly excluded forms (Notation, Abbreviation, Section Variable, Ltac, Module). This prevents unknown kinds from silently dropping declarations from the index.

### 4.3 Module Path Derivation

The `module` field on each declaration shall be the logical path of the `.vo` file from which the declaration was extracted. It is NOT derived from string manipulation of the fully qualified name.

The pipeline shall convert each `.vo` file path to a logical module path before storing it in the `module` field. The conversion uses the same heuristic path parsing described in §4.1.2 (stripping known prefixes, converting path segments to dot-separated components, removing the `.vo` extension).

> **Given** a `.vo` file at `/path/to/user-contrib/Stdlib/Arith/PeanoNat.vo`,
> **When** the pipeline derives the module path,
> **Then** the `module` field value is `Coq.Arith.PeanoNat`.

> **Given** a `.vo` file at `/path/to/user-contrib/mathcomp/ssreflect/ssrbool.vo`,
> **When** the pipeline derives the module path,
> **Then** the `module` field value is `mathcomp.ssreflect.ssrbool`.

The pipeline shall NOT store raw filesystem paths (e.g., `/Users/.../PeanoNat.vo`) in the `module` field.

### 4.4 Pass 1 — Per-Declaration Processing

For each declaration extracted from a `.vo` file:

1. When `constr_t` contains kernel term data (i.e., is not a metadata dict): Parse `Constr.t` → `ConstrNode` (backend-specific; produces pre-resolved FQNs). When `constr_t` is metadata-only (a dict with `type_signature` field), parse the `type_signature` text via `TypeExprParser` → `ConstrNode`, then proceed with steps 2–6 using the parsed node. If parsing fails, fall back to a partial result with no tree, empty symbol set, empty WL vector, and `node_count` = 1. Parse failures are logged but do not abort the declaration.
2. `coq_normalize(constr_node)` → normalized `ExprTree`
3. `cse_normalize(tree)` → CSE-reduced tree (recomputes depths, node_ids, node_count)
4. `extract_consts(tree)` → raw symbol set (short display names from parsed text)
5. `resolve_symbols(raw_set, backend)` → FQN symbol set (see §4.4.1). The `backend` parameter provides the `locate()` method for `Locate` queries. A shared resolution cache is passed across declarations to avoid redundant queries.
6. `wl_histogram(tree, h=3)` → WL vector (Phase 1 computes h=3 only)
7. `pretty_print(name)` → statement
8. Type expression: derived from the Search output `type_signature` field in `constr_t` when available; falls back to `pretty_print_type(name)` otherwise (nullable)

The declaration row, WL vector, and declaration data are co-inserted in the same batch transaction (batch size: 1000 declarations).

**Individual declaration failure**: When normalization or extraction fails for a single declaration, log the declaration name and error, then continue to the next declaration. The index is usable with partial coverage.

#### 4.4.1 Symbol FQN Resolution

When extraction uses the text-based path (coq-lsp `Search` output parsed by `TypeExprParser`), `extract_consts` produces short display names (e.g., `nat`, `+`, `list`, `eq`). These shall be resolved to fully qualified kernel names before storage.

#### resolve_symbols(raw_symbols, backend, cache=None)

- REQUIRES: `raw_symbols` is a set of symbol name strings extracted from an expression tree. `backend` has a `locate(name)` method (§4.1). `cache` is an optional `dict[str, str | list[str] | None]` shared across declarations within an indexing run.
- ENSURES: Returns a set of fully qualified kernel names. Each short name is resolved via `backend.locate()`. Unresolvable names are included as-is.

Resolution mechanism:

1. **Locate query**: For each unique short name not already in the resolution cache, issue a coq-lsp `Locate <name>.` query. `Locate` returns the FQN and object kind (Constant, Inductive, Constructor). Infix operators are queried as `Locate "<op>".` (e.g., `Locate "+".`).

2. **Caching**: Maintain a `short_name → FQN` lookup table for the duration of the indexing run. The cache is keyed by the exact short name string. Most short names recur across thousands of declarations, so the cache eliminates redundant queries.

3. **Batch processing**: `Locate` queries shall be batched into shared synthetic documents (≤100 commands per document), following the same batching pattern as kind detection (§4.1.1), to reduce document lifecycle overhead.

4. **Ambiguous names**: When `Locate` returns multiple matches (e.g., `Locate "+"` may resolve to both `Nat.add` and `Z.add`), all matching FQNs shall be included in the symbol set.

5. **Fallback**: When `Locate` returns an error or no result, the short name is stored as-is in the symbol set. This preserves information without discarding unresolvable names.

MAINTAINS: After resolution, the `symbol_set` column in `declarations` and the `symbol_freq` table (§4.6) both use FQNs as keys. The MePo inverted index built from `symbol_set` is keyed by FQN.

> **Given** a declaration with type `forall n m : nat, n + m = m + n` parsed via `TypeExprParser`,
> **When** `extract_consts` produces `{"nat", "+", "="}` and `resolve_symbols` is called,
> **Then** `Locate nat.` returns `Coq.Init.Datatypes.nat`, `Locate "+".` returns `Coq.Init.Nat.add`, `Locate "=".` returns `Coq.Init.Logic.eq`, and the stored symbol set is `{"Coq.Init.Datatypes.nat", "Coq.Init.Nat.add", "Coq.Init.Logic.eq"}`.

> **Given** a declaration containing the symbol `my_custom_def` not in the Coq environment,
> **When** `Locate my_custom_def.` returns an error,
> **Then** the symbol `my_custom_def` is stored as-is in the symbol set.

**Declaration deduplication**: When multiple `.vo` files contain the same fully qualified declaration name (e.g., via module re-exports), the pipeline shall keep the first occurrence and skip subsequent duplicates. Duplicates are detected after collection and before Pass 1 processing.

### 4.5 Pass 2 — Dependency Resolution

After all declarations are inserted:

1. For each declaration, collect dependency pairs from both tree-based and backend-based sources (see below)
2. Resolve target names to declaration IDs using multi-strategy name resolution (see below)
3. Deduplicate edges by (src, dst, relation) tuple
4. Insert dependency edges in batches

All dependency edges shall use the relation values defined in the `dependencies` entity ([index-entities.md](../doc/architecture/data-models/index-entities.md)): `"uses"` or `"instance_of"`. No other relation values shall be stored.

#### Dependency Sources

**Tree-based dependency extraction** (when expression tree is available): `extract_dependencies(tree)` walks `LConst` nodes to produce `"uses"` edges and reads instance metadata for `"instance_of"` edges. These are direct structural references with fully qualified names — no name resolution is needed.

**Metadata-only declarations** (no expression tree): The backend's `get_dependencies(name)` provides dependency information. When the backend uses `Print Assumptions` (coq-lsp), the output represents transitive axiom dependencies, not direct term references. These edges shall be stored with relation `"uses"` as an approximation. The approximation is acceptable because `Print Assumptions` output is a superset of direct references for most declarations, and the dependency graph is navigational (not scored).

When both sources are available for a declaration, their edges shall be merged and deduplicated.

#### Name Resolution Strategy

`Print Assumptions` returns dependency names with qualification that may differ from the canonical fully qualified names stored in the index (e.g., `Nat.add` vs `Coq.Init.Nat.add`). The resolver shall attempt matching in the following order:

1. **Exact match** against the name-to-ID map.
2. **`Coq.` prefix**: prepend `Coq.` and retry (handles stdlib names like `Init.Nat.add`).
3. **Suffix match**: build a reverse lookup from all dot-separated suffixes of each FQN. If the target name matches exactly one FQN's suffix, resolve to that FQN. If the suffix is ambiguous (maps to multiple distinct FQNs), skip it.

Unresolved targets (no match after all strategies) are silently skipped — they reference declarations outside the indexed scope.

The suffix reverse lookup table shall be built once per `resolve_and_insert_dependencies` call from all FQNs in the name-to-ID map.

### 4.6 Post-Processing

After both passes:

1. Compute global symbol frequencies across all declarations → `insert_symbol_freq`
2. Write index metadata: `schema_version`, `coq_version`, `created_at`. When extracting a single library target (per-library index), also write `library` (the library identifier) and `library_version` (from `detect_library_version`). When extracting multiple targets, write `mathcomp_version` for backward compatibility.
3. Write `declarations` metadata key with the count of indexed declarations.
4. Call `writer.finalize()` — FTS5 rebuild + integrity check

### 4.7 Existing Database Replacement

When `run_extraction` is called and a file exists at `db_path`:

- REQUIRES: `db_path` is a writable filesystem path.
- ENSURES: The existing file at `db_path` is deleted before `IndexWriter.create()` is called. No confirmation is requested.

> **Given** an existing SQLite database at the output path,
> **When** `run_extraction` is called,
> **Then** the existing file is deleted and a fresh index is created.

> **Given** no file at the output path,
> **When** `run_extraction` is called,
> **Then** the index is created normally (no error, no no-op).

### 4.8 Library Discovery

#### discover_libraries(target)

- REQUIRES: `target` is one of the 6 supported library identifiers or a filesystem path to a user project.
- ENSURES: Returns a list of `.vo` file paths for the target library. If `target` is not a recognized library identifier and is not a valid filesystem path, raises `ExtractionError` listing valid identifiers.

Supported library targets:

| Target identifier | Discovery path | Notes |
|------------------|---------------|-------|
| `stdlib` | `user-contrib/Stdlib/` (Rocq 9.x) or `theories/` (Coq 8.x) | Uses whichever location has more `.vo` files |
| `mathcomp` | `user-contrib/mathcomp/` | All `.vo` files recursively |
| `stdpp` | `user-contrib/stdpp/` | All `.vo` files recursively |
| `flocq` | `user-contrib/Flocq/` | All `.vo` files recursively |
| `coquelicot` | `user-contrib/Coquelicot/` | All `.vo` files recursively |
| `coqinterval` | `user-contrib/Interval/` | All `.vo` files recursively |

All paths are relative to the Coq base directory returned by `coqc -where`. Filesystem paths are also accepted for user projects.

> **Given** stdpp is installed and `user-contrib/stdpp/` contains `.vo` files
> **When** `discover_libraries("stdpp")` is called
> **Then** returns all `.vo` files from `user-contrib/stdpp/`

> **Given** CoqInterval is installed
> **When** `discover_libraries("coqinterval")` is called
> **Then** returns all `.vo` files from `user-contrib/Interval/` (note: directory name differs from identifier)

> **Given** an unrecognized target `"unknown"` that is not a filesystem path
> **When** `discover_libraries("unknown")` is called
> **Then** raises `ExtractionError` listing valid identifiers: stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval

### 4.9 Library Version Detection

#### detect_library_version(library)

- REQUIRES: `library` is one of the 6 supported library identifiers.
- ENSURES: Returns the version string for the installed library. If the library is not installed, returns `"none"`.

| Library | Detection method | opam package |
|---------|-----------------|-------------|
| `stdlib` | Parse version from `coqc --version` output | `coq` |
| `mathcomp` | `opam show coq-mathcomp-ssreflect --field=version` | `coq-mathcomp-ssreflect` |
| `stdpp` | `opam show coq-stdpp --field=version` | `coq-stdpp` |
| `flocq` | `opam show coq-flocq --field=version` | `coq-flocq` |
| `coquelicot` | `opam show coq-coquelicot --field=version` | `coq-coquelicot` |
| `coqinterval` | `opam show coq-interval --field=version` | `coq-interval` |

> **Given** MathComp 2.2.0 is installed via opam
> **When** `detect_library_version("mathcomp")` is called
> **Then** returns `"2.2.0"`

> **Given** stdpp is not installed
> **When** `detect_library_version("stdpp")` is called
> **Then** returns `"none"`

> **Given** Coq 8.19.2 is installed
> **When** `detect_library_version("stdlib")` is called
> **Then** returns `"8.19.2"`

### 4.10 Progress Reporting

- REQUIRES: The caller has enabled the progress flag.
- ENSURES: When enabled, the extraction pipeline writes progress messages to stderr for each processing stage. When disabled (the default), no progress messages are emitted.

Per-stage message format (per-declaration granularity):
- Pass 1: `"Extracting declarations [N/total]"`
- Pass 2: `"Resolving dependencies [N/total]"`

Each message identifies the current stage name. Messages are written to stderr so they do not interfere with structured output on stdout.

### 4.11 Backend Process Lifecycle

When the extraction backend (coq-lsp) crashes or becomes unresponsive:
- Abort the indexing run
- Close the database connection
- Delete the partial database file
- Report the error to the caller

This is a pipeline-level fatal error — partial results are not preserved.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Backend not found / not installed | `ExtractionError` | Fatal; abort before starting |
| Backend version incompatible | `ExtractionError` | Fatal; abort before starting |
| Backend crash during extraction | `ExtractionError` | Fatal; delete partial database |
| Single declaration normalization failure | `NormalizationError` | Logged; declaration skipped |
| Single declaration parse failure | Logged | Declaration skipped |
| Database integrity check failure | `StorageError` | Database deleted; error propagated |
| Target library not found | `ExtractionError` | Fatal; abort |

Error hierarchy:
- `ExtractionError` — base class for extraction pipeline errors
  - Carries `message: str` with context

## 6. Non-Functional Requirements

- The entire process runs without GPU, network access, or external API keys.
- Batch size: 1000 declarations per transaction.
- Progress reporting at per-declaration granularity.
- **Kind detection overhead (coq-lsp):** About queries are batched into shared documents (≤100 commands each), and Print + Print Assumptions queries are batched similarly (≤50 declarations = ≤100 lines per document), reducing document lifecycle overhead by 3–10x compared to per-declaration queries.

## 7. Examples

### Full indexing run (single library)

```
libraries = discover_libraries("stdlib")
version = backend.detect_version()
delete_if_exists("/path/to/index-stdlib.db")
writer = IndexWriter.create("/path/to/index-stdlib.db")

# Pass 1
for vo_path in libraries:
    for name, kind, constr_t in backend.list_declarations(vo_path):
        # normalize, extract symbols, compute WL, pretty print
        # batch insert declarations + WL vectors

# Pass 2
for decl in all_declarations:
    deps = backend.get_dependencies(decl.name)
    # resolve targets, batch insert edges

# Post-processing
compute_and_insert_symbol_freq(writer)
write_metadata(writer, version,
    library="stdlib",
    library_version=detect_library_version("stdlib"))
writer.finalize()
```

### Per-library build (all 6 libraries)

```
for lib in ["stdlib", "mathcomp", "stdpp", "flocq", "coquelicot", "coqinterval"]:
    run_extraction(
        targets=[lib],
        db_path=f"index-{lib}.db",
        progress_callback=print,
    )
```

## 8. Language-Specific Notes (Python)

- Use `subprocess` to manage coq-lsp processes.
- Parse coq-lsp JSON responses with `json.loads`.
- Use `pathlib.Path` for `.vo` file discovery.
- CLI entry point via `argparse` or `click`.
- Package location: `src/poule/extraction/`.
