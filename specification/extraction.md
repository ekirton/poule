# Coq Library Extraction

Offline extraction of declarations from compiled Coq/Rocq libraries into the search index.

**Architecture**: [coq-extraction.md](../doc/architecture/coq-extraction.md), [coq-normalization.md](../doc/architecture/coq-normalization.md), [storage.md](../doc/architecture/storage.md)

---

## 1. Purpose

Define the extraction pipeline that reads compiled `.vo` files via coq-lsp or SerAPI, converts declarations to normalized expression trees, computes derived data (symbol sets, WL histograms, dependencies), and writes everything to a SQLite index database.

## 2. Scope

**In scope**: Backend interface (coq-lsp / SerAPI), library discovery, version detection, two-pass extraction pipeline, kind mapping, module path derivation, progress reporting, CLI entry point.

**Out of scope**: Normalization algorithms (owned by coq-normalization and cse-normalization), storage schema (owned by storage), retrieval logic.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Backend | The external tool (coq-lsp or SerAPI) used to read `.vo` files and access `Constr.t` kernel terms |
| Pass 1 | Per-declaration processing: parse, normalize, extract symbols, compute WL vectors, write to database |
| Pass 2 | Post-insertion dependency resolution: extract and write dependency edges |
| Kind mapping | Translation from Coq declaration forms to storage kind values |

## 4. Behavioral Requirements

### 4.1 Backend Interface

The system shall define a `Backend` protocol with operations:

#### list_declarations(vo_path)

- REQUIRES: `vo_path` is a path to a compiled `.vo` file.
- ENSURES: Returns a list of `(name, kind, constr_t)` tuples for all declarations in the file.
- MAINTAINS: The `kind` value for each declaration is determined by the kind detection mechanism (§4.1.1).

#### 4.1.1 Kind Detection

The backend shall determine each declaration's kind during `list_declarations`. The mechanism is backend-dependent because not all backends return kind information directly from declaration listing.

**coq-lsp backend:** The `Search _ inside M.` command returns `(name, type_sig)` pairs without declaration kinds. The backend shall issue an `About <name>.` Vernac command per declaration and parse the response to determine the kind. About queries for declarations within a single module may be batched into a single synthetic document with one command per line (batch size capped at 100 commands per document). The contract (one About per declaration, version-dependent parsing) is unchanged.

The `About` response format is version-dependent:

| Version | Format | Kind extraction |
|---------|--------|----------------|
| Coq ≤ 8.x | `<name> is [a] <Kind>.` | Extract `<Kind>` from the `is [a]` pattern |
| Rocq 9.x | Multi-line; includes `Expands to: <Category> <path>` | Map `<Category>`: `Constant` → `definition`, `Inductive` → `inductive`, `Constructor` → `constructor` |

**Parsing precedence (coq-lsp):** When both formats are present in the response, the Coq ≤ 8.x `"is [a] <Kind>"` pattern takes precedence (it is more specific).

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

Excluded forms have no kernel term and shall be silently skipped.

**Unknown kinds:** When the detected kind string does not match any row in the table above (including the excluded forms), `map_kind` shall return `"definition"`. The `map_kind` function shall return `None` only for explicitly excluded forms (Notation, Abbreviation, Section Variable). This prevents unknown kinds from silently dropping declarations from the index.

### 4.3 Module Path Derivation

The `module` field on each declaration shall be the logical path of the `.vo` file from which the declaration was extracted. It is NOT derived from string manipulation of the fully qualified name.

### 4.4 Pass 1 — Per-Declaration Processing

For each declaration extracted from a `.vo` file:

1. Parse `Constr.t` → `ConstrNode` (backend-specific; produces pre-resolved FQNs)
2. `coq_normalize(constr_node)` → normalized `ExprTree`
3. `cse_normalize(tree)` → CSE-reduced tree (recomputes depths, node_ids, node_count)
4. `extract_consts(tree)` → symbol set
5. `wl_histogram(tree, h=3)` → WL vector (Phase 1 computes h=3 only)
6. `pretty_print(name)` → statement
7. Type expression: derived from the Search output `type_signature` field in `constr_t` when available; falls back to `pretty_print_type(name)` otherwise (nullable)

The declaration row, WL vector, and declaration data are co-inserted in the same batch transaction (batch size: 1000 declarations).

**Individual declaration failure**: When normalization or extraction fails for a single declaration, log the declaration name and error, then continue to the next declaration. The index is usable with partial coverage.

### 4.5 Pass 2 — Dependency Resolution

After all declarations are inserted:

1. For each declaration, call `backend.get_dependencies(name)`
2. Resolve target names to declaration IDs (skip unresolved targets — they reference declarations outside the indexed scope)
3. Insert dependency edges in batches

### 4.6 Post-Processing

After both passes:

1. Compute global symbol frequencies across all declarations → `insert_symbol_freq`
2. Write index metadata: `schema_version`, `coq_version`, `mathcomp_version`, `created_at`
3. Call `writer.finalize()` — FTS5 rebuild + integrity check

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

- REQUIRES: `target` specifies which libraries to index (stdlib, MathComp, or user project path).
- ENSURES: Returns a list of `.vo` file paths for the target libraries.

Phase 1 targets:
- **Coq standard library**: All `.vo` files from the installed Coq/Rocq stdlib.
- **MathComp**: All `.vo` files from the installed MathComp package.

### 4.9 Progress Reporting

- Pass 1: `"Extracting declarations [N/total]"` (per-declaration granularity)
- Pass 2: `"Resolving dependencies [N/total]"` (per-declaration granularity)

### 4.10 Backend Process Lifecycle

When the extraction backend (coq-lsp or SerAPI) crashes or becomes unresponsive:
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

### Full indexing run

```
libraries = discover_libraries("stdlib+mathcomp")
version = backend.detect_version()
delete_if_exists("/path/to/index.db")
writer = IndexWriter.create("/path/to/index.db")

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
write_metadata(writer, version)
writer.finalize()
```

## 8. Language-Specific Notes (Python)

- Use `subprocess` to manage coq-lsp or SerAPI processes.
- Parse coq-lsp JSON responses with `json.loads`; parse SerAPI S-expressions with a lightweight parser.
- Use `pathlib.Path` for `.vo` file discovery.
- CLI entry point via `argparse` or `click`.
- Package location: `src/wily_rooster/extraction/`.
