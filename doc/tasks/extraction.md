# Task: Coq Library Extraction Pipeline

**Specification**: [specification/extraction.md](../../specification/extraction.md)
**Date**: 2026-03-16

---

## 1. Overview

Implement the offline pipeline that reads compiled Coq libraries (`.vo` files), extracts every declaration's type as a normalized expression tree, computes retrieval artifacts (WL histograms, symbol sets, dependency edges), and writes everything to a SQLite database. This is the sole write path into the search index -- all downstream components (retrieval channels, MCP server) consume the database read-only.

The pipeline targets Coq standard library and MathComp for Phase 1, processing approximately 50K declarations into a single SQLite file.

---

## 2. Dependencies

### Must Be Implemented First

| Dependency | Reason | Spec |
|-----------|--------|------|
| Data structures (`ExprTree`, `NodeLabel`, etc.) | Every extraction step produces or consumes these types | [specification/data-structures.md](../../specification/data-structures.md) |
| Storage schema (DDL + read/write helpers) | Extraction writes to all tables | [specification/storage.md](../../specification/storage.md) |

### Co-Developed (Extraction Calls These)

| Dependency | Reason | Spec |
|-----------|--------|------|
| Coq normalization (`constr_to_tree`, `recompute_depths`, `assign_node_ids`) | Per-declaration processing steps 2-4 | [specification/coq-normalization.md](../../specification/coq-normalization.md) |
| CSE normalization (`cse_normalize`) | Per-declaration processing step 5 | [specification/cse-normalization.md](../../specification/cse-normalization.md) |
| WL histogram computation (`wl_histogram`) | Per-declaration processing step 8 | [specification/channel-wl-kernel.md](../../specification/channel-wl-kernel.md) |

### External

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Coq/Rocq | 8.19+ or Rocq 9.0+ | Source of `.vo` files |
| coq-lsp or coq-serapi | Compatible with installed Coq | Reads `.vo` files, enumerates declarations, extracts `Constr.t` terms |
| Python | 3.11+ | Implementation language |
| sqlite3 (stdlib) | Bundled with Python | Database |

---

## 3. Module Structure

```
src/coq_search/
    __init__.py
    models/
        __init__.py
        expr_tree.py           # ExprTree, NodeLabel hierarchy (from data-structures spec)
        types.py               # WlHistogram, SymbolSet, ScoredResult type aliases
    storage/
        __init__.py
        schema.py              # DDL, table creation, integrity check
        writer.py              # BatchWriter class for transactional inserts
        reader.py              # Read-path helpers (for query serving, not this task)
    normalization/
        __init__.py
        coq_normalize.py       # constr_to_tree, recompute_depths, assign_node_ids
        cse_normalize.py       # 3-pass CSE algorithm
    extraction/
        __init__.py
        coq_backend.py         # Abstract interface + concrete backend(s)
        discovery.py           # Library/vo file discovery
        declaration.py         # Per-declaration processing pipeline
        symbols.py             # extract_symbols, extract_dependencies
        pipeline.py            # Top-level orchestrator
        wl.py                  # wl_histogram (may live in a shared channel module)
    cli/
        __init__.py
        index_cmd.py           # CLI entry point for extraction
```

---

## 4. Implementation Steps

### Step 1: Data Structures Module

**Files**: `src/coq_search/models/expr_tree.py`, `src/coq_search/models/types.py`

Implement the `NodeLabel` class hierarchy and `ExprTree` dataclass exactly as specified in data-structures.md Section 3 (Python-specific notes). This is the foundation for everything else.

```python
# expr_tree.py - key signatures
class NodeLabel: ...           # Base class, not instantiated directly
class LRel(NodeLabel): ...     # frozen dataclass, index: int
class LConst(NodeLabel): ...   # frozen dataclass, name: str
# ... all 16 variants

@dataclass
class ExprTree:
    label: NodeLabel
    children: list["ExprTree"] = field(default_factory=list)
    depth: int = 0
    node_id: int = 0
```

```python
# types.py
WlHistogram = dict[str, int]
Symbol = str
SymbolSet = list[Symbol]
```

### Step 2: Storage Schema and Writer

**Files**: `src/coq_search/storage/schema.py`, `src/coq_search/storage/writer.py`

Implement DDL from storage.md Section 3. The writer handles batched transactional inserts.

```python
# schema.py
def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables (declarations, dependencies, wl_vectors, symbol_freq,
    index_meta, declarations_fts). Executes all DDL in a single transaction."""

def rebuild_fts(conn: sqlite3.Connection) -> None:
    """INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')"""

def run_integrity_check(conn: sqlite3.Connection) -> bool:
    """Run PRAGMA integrity_check; return True if clean."""

SCHEMA_VERSION = 1
```

```python
# writer.py
class BatchWriter:
    """Accumulates declaration rows and flushes every `batch_size` declarations."""

    def __init__(self, conn: sqlite3.Connection, batch_size: int = 1000): ...

    def add_declaration(
        self,
        name: str,
        module: str,
        kind: str,
        statement: str,
        type_expr: str | None,
        constr_tree_blob: bytes | None,
        node_count: int | None,
        symbol_set: list[str],
    ) -> int:
        """Insert a declaration row. Returns the assigned id.
        Does NOT commit -- call flush() to commit the batch."""

    def add_wl_vector(self, decl_id: int, h: int, histogram: dict[str, int]) -> None:
        """Queue a wl_vectors row."""

    def add_dependency(self, src_name: str, dst_name: str, relation: str) -> None:
        """Queue a dependency edge by name. Resolution to IDs happens in finalize()."""

    def flush(self) -> None:
        """Commit the current batch."""

    def finalize(self, conn: sqlite3.Connection) -> None:
        """After all declarations are inserted:
        1. Resolve dependency names to declaration IDs and insert rows
        2. Build symbol_freq from all declarations' symbol_sets
        3. Rebuild FTS index
        """
```

**Design decision -- dependency resolution**: Dependencies are collected by name during per-declaration processing. After all declarations have been inserted, `finalize()` resolves names to `declarations.id` via a single `SELECT name, id FROM declarations` query into a lookup dict. Unresolved names (references outside indexed scope) are logged and skipped. This two-pass approach avoids the ordering problem described in the spec feedback.

### Step 3: Coq Backend Interface

**Files**: `src/coq_search/extraction/coq_backend.py`

Define the abstract interface between Python and Coq. Then implement one concrete backend (SerAPI recommended for Phase 1 -- it has a stable, well-documented S-expression protocol; coq-lsp can be added later).

```python
# coq_backend.py

@dataclass
class RawDeclaration:
    """A declaration as extracted from Coq, before normalization."""
    name: str                    # Fully qualified name
    module: str                  # Module path
    kind: str                    # "Lemma", "Theorem", "Definition", etc.
    constr_sexp: str             # S-expression of Constr.t type term
    statement: str               # Pretty-printed statement (from Coq)
    type_expr: str | None        # Pretty-printed type expression
    is_instance: bool            # Whether this is a typeclass instance


class CoqBackend(Protocol):
    """Interface for reading declarations from compiled Coq libraries."""

    def get_coq_version(self) -> str:
        """Return the Coq version string (e.g., '8.19.0')."""
        ...

    def load_vo_file(self, vo_path: Path) -> list[RawDeclaration]:
        """Load a .vo file and return all declarations it contains.

        Raises CoqBackendError if the file cannot be loaded.
        Individual declaration extraction failures are returned as
        RawDeclaration with constr_sexp=None and logged internally.
        """
        ...

    def shutdown(self) -> None:
        """Clean up the backend process."""
        ...


class SerAPIBackend:
    """Concrete backend using SerAPI (sertop) subprocess."""

    def __init__(self, sertop_path: str | None = None):
        """Start sertop process. If sertop_path is None, find it on PATH."""
        ...

    # implements CoqBackend protocol
```

**SerAPI communication strategy**:
- Start `sertop` as a long-lived subprocess communicating over stdin/stdout
- Use `(Add () "Require Import <module>.")` to load a module
- Use `(Query () (Vernac "Print All."))` or iterate with `(Query ((sid <n>)) Goals)` to enumerate declarations
- Use `(Print ((pp ((pp_format PpSer)))) (CoqConstr <term>))` to get S-expression representation of terms
- Use `(Print ((pp ((pp_format PpStr)))) (CoqConstr <term>))` to get pretty-printed strings
- Parse S-expressions using a lightweight recursive-descent parser (no external dependency needed)

**Alternative -- coq-lsp backend**:
- Communicate over JSON-RPC (LSP protocol)
- Use `coq/document` and `coq/goals` requests
- Parse JSON responses
- Advantage: actively maintained, better Rocq 9.0 support
- Disadvantage: designed for incremental editing, not batch extraction; may require constructing synthetic `.v` files

### Step 4: S-Expression Parser

**File**: `src/coq_search/extraction/sexp_parser.py`

Parse SerAPI's S-expression output into Python data structures for `constr_to_tree` consumption.

```python
# sexp_parser.py

SExp = str | list["SExp"]  # Atom or list

def parse_sexp(text: str) -> SExp:
    """Parse a single S-expression from text."""

def parse_constr(sexp: SExp) -> "ExprTree":
    """Convert a Constr.t S-expression into an ExprTree.

    Applies Coq normalizations during conversion:
    - Currifies n-ary App to binary
    - Strips Cast nodes
    - Erases universe annotations
    - Normalizes Proj nodes
    - Fully qualifies names (names arrive fully qualified from SerAPI)

    Raises ConstrParseError for unrecognized variants.
    """
```

The S-expression format for Coq `Constr.t` terms from SerAPI follows this structure:
```
(App (Const (name <fqn>) (univs ...)) ((Ind (name <fqn>) ...) ...))
(Prod (Name <n>) <type_sexp> <body_sexp>)
(Lambda (Name <n>) <type_sexp> <body_sexp>)
(Rel <index>)
(Const (name <fqn>) (univs ...))
(Ind (name <fqn>) <index>)
(Construct (name <fqn>) <ind_idx> <constr_idx>)
(Case ...)
(Fix ...)
(Cast <expr> <kind> <type>)
(Proj <proj> <term>)
(Sort <sort>)
```

### Step 5: Coq Normalization

**Files**: `src/coq_search/normalization/coq_normalize.py`

Implement the normalization pipeline from coq-normalization.md Section 10.

```python
# coq_normalize.py

def constr_to_tree(sexp: SExp) -> ExprTree:
    """Convert parsed Constr.t S-expression to ExprTree.
    Applies all Coq-specific normalizations during conversion:
    - Currification of n-ary App (Section 3)
    - Cast stripping (Section 4)
    - Universe erasure (Section 5)
    - Projection normalization (Section 6)
    - Fully qualified names (Section 8)

    Max recursion depth: 1000.
    """

def recompute_depths(tree: ExprTree, depth: int = 0) -> ExprTree:
    """Set depth field on all nodes, bottom-up."""

def assign_node_ids(tree: ExprTree) -> ExprTree:
    """Assign unique sequential node_ids via pre-order traversal."""

def coq_normalize(sexp: SExp) -> ExprTree:
    """Full normalization pipeline: constr_to_tree -> recompute_depths -> assign_node_ids."""
```

### Step 6: CSE Normalization

**File**: `src/coq_search/normalization/cse_normalize.py`

Implement the 3-pass algorithm from cse-normalization.md Section 3.

```python
# cse_normalize.py

def hash_subtree(node: ExprTree) -> str:
    """Pass 1: Compute MD5 content hash for every subtree, bottom-up."""

def count_frequencies(node: ExprTree) -> dict[str, int]:
    """Pass 2: Build hash -> frequency table."""

def cse_replace(
    node: ExprTree,
    freq: dict[str, int],
    seen: dict[str, int],
    next_var_id: list[int],  # mutable counter
) -> ExprTree:
    """Pass 3: Replace repeated non-constant subtrees with LCseVar nodes.
    Key invariant: LConst, LInd, LConstruct are never replaced."""

def cse_normalize(tree: ExprTree) -> ExprTree:
    """Run all three passes. Returns CSE-reduced tree."""
```

### Step 7: Symbol and Dependency Extraction

**File**: `src/coq_search/extraction/symbols.py`

```python
# symbols.py

def extract_symbols(tree: ExprTree) -> list[str]:
    """Collect all LConst, LInd, LConstruct names from the tree.
    Returns sorted, deduplicated list of fully qualified names."""

def extract_dependencies(
    raw_decl: RawDeclaration,
    tree: ExprTree,
) -> list[tuple[str, str]]:
    """Extract (target_name, relation) dependency edges.

    - 'uses' relation: every LConst name in the tree
    - 'instance_of' relation: if raw_decl.is_instance, add edge to the class
    """
```

### Step 8: WL Histogram Computation

**File**: `src/coq_search/extraction/wl.py`

```python
# wl.py

import hashlib

def simplified_label(node: ExprTree) -> str:
    """Map NodeLabel to short string per channel-wl-kernel.md Section 3."""

def wl_iterate(tree: ExprTree, h: int) -> dict[int, str]:
    """Compute WL labels for all nodes through h iterations.
    Returns {node_id: label} including labels from all iterations 0..h."""

def wl_histogram(tree: ExprTree, h: int = 3) -> dict[str, int]:
    """Compute sparse histogram from WL labels."""
```

### Step 9: Library Discovery

**File**: `src/coq_search/extraction/discovery.py`

```python
# discovery.py

from pathlib import Path

@dataclass
class LibraryTarget:
    name: str            # "stdlib" or "mathcomp"
    vo_files: list[Path]
    version: str

def find_coq_installation() -> Path:
    """Run `coqc -where` and return the Coq lib directory.
    Raises CoqNotFoundError if coqc is not on PATH or returns an error."""

def discover_stdlib(coq_path: Path) -> LibraryTarget:
    """Find all .vo files under <coq_path>/theories/.
    Raises LibraryNotFoundError if theories/ is missing or empty."""

def discover_mathcomp(coq_path: Path) -> LibraryTarget | None:
    """Find MathComp .vo files. Returns None if MathComp is not installed.
    Uses `coqc` to resolve the `mathcomp` logical path."""

def get_coq_version() -> str:
    """Run `coqc --version` and parse the version string."""

def get_mathcomp_version() -> str | None:
    """Detect MathComp version from opam or package metadata. Returns None if not installed."""
```

### Step 10: Per-Declaration Processing Pipeline

**File**: `src/coq_search/extraction/declaration.py`

```python
# declaration.py

import logging
import pickle

logger = logging.getLogger(__name__)

@dataclass
class ProcessedDeclaration:
    """Result of processing a single declaration."""
    name: str
    module: str
    kind: str
    statement: str
    type_expr: str | None
    constr_tree_blob: bytes | None     # pickle.dumps(tree)
    node_count: int | None
    symbol_set: list[str]
    dependencies: list[tuple[str, str]]  # (target_name, relation)
    wl_histogram: dict[str, int] | None

def process_declaration(raw: RawDeclaration) -> ProcessedDeclaration | None:
    """Run the full per-declaration pipeline.

    Steps (from extraction.md Section 4.2):
    1. Parse constr_sexp -> ExprTree (constr_to_tree with normalizations)
    2. recompute_depths
    3. assign_node_ids
    4. cse_normalize
    5. extract_symbols
    6. extract_dependencies
    7. wl_histogram(tree, h=3)
    8. Assemble ProcessedDeclaration

    Returns None if extraction fails (logs warning and continues).
    Individual step failures are handled per error spec:
    - constr_to_tree fails -> return None
    - CSE produces invalid tree -> return None
    - pretty_print fails -> use empty statement
    - dependency extraction fails -> skip edges
    """
```

### Step 11: Pipeline Orchestrator

**File**: `src/coq_search/extraction/pipeline.py`

```python
# pipeline.py

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

def run_extraction(
    db_path: Path,
    include_mathcomp: bool = True,
    batch_size: int = 1000,
) -> None:
    """Top-level extraction pipeline.

    Steps (from extraction.md Section 4.1):
    1. Discover .vo files for target libraries
    2. Create fresh SQLite database (delete existing file if present)
    3. Create all tables
    4. Initialize Coq backend
    5. For each .vo file:
       a. Load file via backend
       b. For each declaration: process_declaration()
       c. Batch-insert results (commit every batch_size declarations)
    6. Finalize: resolve dependencies, build symbol_freq, rebuild FTS
    7. Write index_meta (schema_version, coq_version, mathcomp_version, created_at)
    8. Run integrity check
    9. Shutdown backend

    On pipeline-level error: delete partial database file, re-raise.
    """

def _write_index_meta(
    conn: sqlite3.Connection,
    coq_version: str,
    mathcomp_version: str | None,
) -> None:
    """Write required index_meta keys."""
```

### Step 12: CLI Entry Point

**File**: `src/coq_search/cli/index_cmd.py`

```python
# index_cmd.py

import argparse
import logging
import sys
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `coq-search index`.

    Usage:
        coq-search index [--db PATH] [--no-mathcomp] [--batch-size N] [--verbose]

    Options:
        --db PATH          Output database path (default: ./coq_search.db)
        --no-mathcomp      Skip MathComp extraction
        --batch-size N     Declarations per commit batch (default: 1000)
        --verbose          Enable debug logging
    """
```

### Step 13: ExprTree Serialization

**File**: `src/coq_search/models/serialization.py`

```python
# serialization.py

import pickle

def serialize_tree(tree: ExprTree) -> bytes:
    """Serialize ExprTree to bytes using pickle protocol 5."""

def deserialize_tree(data: bytes) -> ExprTree:
    """Deserialize bytes back to ExprTree."""
```

Pickle protocol 5 is used per storage.md Section 9.1. The format is internal -- only this codebase reads it.

---

## 5. Testing Plan

### 5.1 Unit Tests (No Coq Required)

These tests use hardcoded inputs and do not require a Coq installation.

**File**: `test/test_models.py`

| Test Case | Description |
|-----------|-------------|
| `test_node_label_equality` | Verify frozen dataclass equality and hashing for all 16 label variants |
| `test_expr_tree_construction` | Build a tree for `nat -> nat`, verify structure, depth, node_id |
| `test_expr_tree_serialization` | Round-trip serialize/deserialize, verify equality |

**File**: `test/test_coq_normalize.py`

| Test Case | Description |
|-----------|-------------|
| `test_currify_binary` | `App(f, [a, b])` becomes `App(App(f, a), b)` |
| `test_currify_ternary` | `App(f, [a, b, c])` produces 3 nested App nodes |
| `test_currify_nullary` | `App(f, [])` returns `f` unchanged |
| `test_strip_cast` | `Cast(App(f, [a]), vm, ty)` strips the Cast |
| `test_erase_universes` | `Const(name, [Set])` becomes `LConst(name)` with no universe |
| `test_projection_normalization` | `Proj(proj, term)` becomes `LProj` node with 1 child |
| `test_recompute_depths` | Verify root=0, children=1, grandchildren=2 |
| `test_assign_node_ids` | Verify pre-order sequential assignment, uniqueness |
| `test_recursion_depth_limit` | Tree with depth > 1000 raises or is skipped |
| `test_full_pipeline_nat_arrow_nat` | End-to-end: S-exp for `nat -> nat` through full normalization |

Input for these tests: manually constructed S-expressions matching SerAPI format, or directly constructed `ExprTree` objects for normalization-only tests.

**File**: `test/test_cse_normalize.py`

| Test Case | Description |
|-----------|-------------|
| `test_no_duplicates` | `nat -> bool` is unchanged |
| `test_constant_preservation` | Repeated `LInd("nat")` is NOT replaced |
| `test_compound_cse` | `list nat -> list nat` replaces second `App(Ind(list), Ind(nat))` with `CseVar(0)` |
| `test_empty_tree` | Returns empty tree unchanged |
| `test_single_node` | Returns single node unchanged |

**File**: `test/test_symbols.py`

| Test Case | Description |
|-----------|-------------|
| `test_extract_symbols_nat_add_comm` | Tree with LConst(nat), LConst(add), LConst(eq) extracts those 3 symbols sorted |
| `test_extract_symbols_no_duplicates` | Symbols appearing multiple times are deduplicated |
| `test_extract_dependencies_uses` | LConst references produce `uses` edges |
| `test_extract_dependencies_instance` | Instance declaration produces `instance_of` edge |

**File**: `test/test_wl.py`

| Test Case | Description |
|-----------|-------------|
| `test_simplified_label` | Each NodeLabel variant maps to correct string |
| `test_wl_iterate_h0` | Iteration 0 produces depth-tagged labels |
| `test_wl_iterate_h1` | Iteration 1 incorporates child labels |
| `test_histogram_nat_arrow_nat` | Matches expected histogram from spec example |
| `test_histogram_empty_tree` | Returns empty histogram |

**File**: `test/test_storage.py`

| Test Case | Description |
|-----------|-------------|
| `test_create_tables` | All tables created, schema matches spec |
| `test_batch_writer_insert` | Insert 3 declarations, verify rows in DB |
| `test_batch_writer_flush` | Verify commit happens at batch_size threshold |
| `test_finalize_dependencies` | Dependencies resolved by name to ID |
| `test_finalize_unresolved_deps` | Out-of-scope dependency names are skipped |
| `test_finalize_symbol_freq` | Global freq table built correctly |
| `test_fts_rebuild` | FTS index returns results after rebuild |
| `test_integrity_check` | Passes on valid DB |
| `test_index_meta` | Required keys written and readable |

**File**: `test/test_sexp_parser.py`

| Test Case | Description |
|-----------|-------------|
| `test_parse_atom` | Parses `"hello"` |
| `test_parse_nested` | Parses `(App (Const foo) (Rel 0))` |
| `test_parse_constr_prod` | Parses `Prod` S-expression into `LProd` tree |
| `test_parse_constr_app` | Parses `App` with argument list, currifies |
| `test_parse_constr_cast` | Parses `Cast`, strips it |
| `test_unrecognized_variant` | Raises `ConstrParseError` |

### 5.2 Integration Tests (Mock Coq Backend)

**File**: `test/test_pipeline_integration.py`

Create a `MockCoqBackend` that implements the `CoqBackend` protocol and returns pre-built `RawDeclaration` objects with known S-expressions.

| Test Case | Description |
|-----------|-------------|
| `test_full_pipeline_small_library` | Process 10 mock declarations, verify all tables populated |
| `test_pipeline_partial_failure` | 1 of 10 declarations fails extraction; verify other 9 are indexed and warning is logged |
| `test_pipeline_idempotency` | Run twice, verify databases are identical (except `created_at`) |
| `test_pipeline_creates_fresh_db` | Existing DB file is replaced |
| `test_pipeline_deletes_on_error` | Pipeline-level error (e.g., backend init fails) deletes partial DB |
| `test_batch_commit_boundary` | With batch_size=3 and 7 declarations, verify 3 commits (3+3+1) |

### 5.3 End-to-End Tests (Requires Coq Installation)

These tests are optional and run only when Coq + SerAPI/coq-lsp are available. Mark with `@pytest.mark.skipif(not coq_available())`.

**File**: `test/test_e2e_extraction.py`

| Test Case | Description |
|-----------|-------------|
| `test_extract_nat_add_comm` | Extract `Coq.Arith.PeanoNat.Nat.add_comm`, verify name, kind, symbol_set matches spec example |
| `test_extract_stdlib_init_nat` | Extract all declarations from `Coq.Init.Nat`, verify count > 0 and all declarations have valid trees |
| `test_extract_single_vo_file` | Extract a single known `.vo` file, verify declarations are reasonable |

### 5.4 Test Fixtures

**File**: `test/fixtures/sexp_samples.py`

Maintain a collection of representative S-expression strings for common Coq constructs:
- `SEXP_NAT_ARROW_NAT`: `(Prod (Name _) (Ind ((name Coq.Init.Datatypes.nat) 0) ()) (Ind ((name Coq.Init.Datatypes.nat) 0) ()))`
- `SEXP_NAT_ADD_COMM_TYPE`: Full S-expression for `forall n m : nat, n + m = m + n`
- `SEXP_WITH_CAST`: Expression containing a Cast node
- `SEXP_WITH_UNIVERSES`: Expression with universe annotations
- `SEXP_DEEP_NESTED`: Deeply nested expression for recursion depth testing

These fixtures are captured once from a real Coq installation and committed to the repository.

---

## 6. Acceptance Criteria

### Functional

1. **Library discovery**: `discover_stdlib()` finds `.vo` files under the Coq installation; `discover_mathcomp()` finds MathComp files or returns None.
2. **Per-declaration pipeline**: Given a valid `RawDeclaration`, `process_declaration()` returns a `ProcessedDeclaration` with all fields populated (or None on failure).
3. **Normalization correctness**: The tree for `nat -> nat` matches the spec example in data-structures.md Section 8. The tree for `Nat.add_comm` produces the expected symbol set from extraction.md Section 8.
4. **CSE correctness**: `list nat -> list nat` is reduced from 7 nodes to 4 nodes per cse-normalization.md Section 6.
5. **Database populated**: After `run_extraction()`, all 6 tables contain data. Every declaration has a `wl_vectors` row with h=3. `symbol_freq` has one row per unique symbol. `index_meta` has all 4 required keys.
6. **FTS working**: `SELECT * FROM declarations_fts WHERE declarations_fts MATCH 'nat'` returns results.
7. **Dependencies resolved**: Dependency edges reference valid `declarations.id` values. Unresolved names are absent from the table.
8. **Partial failure resilience**: A single declaration failure does not abort the pipeline. The log contains a warning. All other declarations are indexed.
9. **Idempotency**: Two runs produce identical databases (ignoring `created_at`).
10. **Integrity check passes**: `PRAGMA integrity_check` returns `"ok"` after extraction.

### Non-Functional

11. **Performance**: Extraction of a mock library with 1000 declarations completes in under 30 seconds (excluding Coq backend time).
12. **Progress reporting**: Log output includes `.vo` file progress (e.g., `Processing Coq.Init.Nat [42/312]`).
13. **Clean error messages**: Coq-not-installed produces a clear error with installation instructions, not a stack trace.

---

## 7. Risks and Mitigations

### Risk 1: SerAPI / coq-lsp Availability and Compatibility

**Risk**: SerAPI may not be maintained for newer Coq/Rocq versions. coq-lsp may not expose batch extraction APIs.

**Likelihood**: Medium. SerAPI's last release targets Coq 8.19. Rocq 9.0+ compatibility is uncertain.

**Mitigation**:
- Abstract the Coq backend behind a protocol (Step 3) so backends can be swapped.
- Start with SerAPI for Coq 8.19 (well-documented, stable S-expression format).
- Investigate coq-lsp as an alternative backend early. If coq-lsp provides `Constr.t` export, prefer it for Rocq 9.0+.
- As a fallback, consider a thin OCaml shim that directly reads `.vo` files using Coq's OCaml API and outputs S-expressions to stdout. This eliminates the SerAPI/coq-lsp dependency entirely but requires OCaml compilation.

### Risk 2: S-Expression Format Variability

**Risk**: The exact S-expression format for `Constr.t` may vary between SerAPI versions and Coq versions.

**Likelihood**: Medium.

**Mitigation**:
- Capture reference S-expressions from a known SerAPI + Coq version combination and commit as test fixtures.
- Write the parser to be tolerant of unknown fields (log and skip rather than crash).
- Version-pin SerAPI in the development environment.

### Risk 3: Performance for Large Libraries

**Risk**: 50K declarations with SerAPI subprocess communication may be slow (target: under 10 minutes).

**Likelihood**: Medium. SerAPI communication overhead is non-trivial.

**Mitigation**:
- Batch operations where possible (load entire `.vo` file, enumerate all declarations at once).
- Profile early with stdlib and optimize bottlenecks.
- Consider parallelizing `.vo` file processing with multiprocessing (each file gets its own SerAPI process). The BatchWriter would need to synchronize but this is straightforward with a queue.
- The OCaml shim fallback (Risk 1) would also solve performance by eliminating IPC overhead.

### Risk 4: `.vo` File Format Changes

**Risk**: `.vo` is an internal binary format that changes between Coq major versions. The extraction tooling (SerAPI/coq-lsp) must match the Coq version that compiled the `.vo` files.

**Likelihood**: Low for Phase 1 (single Coq version). Higher for supporting multiple versions.

**Mitigation**:
- Record `coq_version` in `index_meta`. Detect version mismatches at startup.
- Only support the installed Coq version -- do not attempt to read `.vo` files from a different Coq version.
- Document the supported Coq version range.

### Risk 5: Incomplete Declaration Kind Coverage

**Risk**: Coq has more declaration kinds than the spec lists (Record, Class, Canonical Structure, Coercion, etc.). Unknown kinds may cause extraction failures.

**Likelihood**: High. This will happen with real libraries.

**Mitigation**:
- Map known Coq kinds to the spec's 7 categories (e.g., Record -> Inductive, Class -> Definition).
- For unknown kinds, log a warning and classify as "Definition" (safe default).
- Track which kinds appear in practice during initial testing and refine the mapping.

### Risk 6: Memory Usage for Large Trees

**Risk**: Some Coq declarations have very large `Constr.t` terms (thousands of nodes). Recursive tree processing may hit Python's recursion limit or use excessive memory.

**Likelihood**: Low-medium.

**Mitigation**:
- Cap recursion depth at 1000 (per coq-normalization.md Section 11).
- For the S-expression parser, use an iterative parser rather than recursive descent if stack depth becomes an issue.
- Skip declarations that exceed the depth limit (log and continue).

---

## 8. Implementation Order

The recommended implementation sequence, with rough effort estimates:

| Phase | Steps | Effort | Notes |
|-------|-------|--------|-------|
| A: Foundation | 1 (data structures), 2 (storage), 13 (serialization) | 2 days | No Coq dependency. Fully testable in isolation. |
| B: Normalization | 5 (coq normalize), 6 (CSE) | 2 days | Test with hand-constructed trees. No Coq dependency. |
| C: Extraction helpers | 7 (symbols/deps), 8 (WL) | 1 day | Test with hand-constructed trees. No Coq dependency. |
| D: Coq interface | 3 (backend), 4 (S-exp parser) | 3 days | Requires Coq + SerAPI installed. Most uncertain step. |
| E: Pipeline | 9 (discovery), 10 (per-decl pipeline), 11 (orchestrator) | 2 days | Integration of all previous steps. |
| F: CLI + polish | 12 (CLI), end-to-end tests | 1 day | |

Phases A-C can proceed without any Coq installation. Phase D is the highest-risk step and should start as soon as A is complete (to derisk the Coq interface early).
