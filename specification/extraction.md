# Coq Library Extraction

Offline pipeline that reads compiled Coq libraries (`.vo` files), extracts declarations with their types and proofs, and populates the SQLite index.

Parent architecture: [doc/architecture/coq-extraction.md](../doc/architecture/coq-extraction.md)
Storage schema: [storage.md](storage.md)
Normalization: [coq-normalization.md](coq-normalization.md), [cse-normalization.md](cse-normalization.md)
Data structures: [data-structures.md](data-structures.md)

---

## 1. Purpose

Transform compiled Coq libraries into the indexed form required by the retrieval pipeline. This is the sole write path to the database — all downstream components (retrieval channels, MCP server) consume the index read-only.

---

## 2. Scope

Covers the extraction pipeline from `.vo` file discovery through database population. Includes per-declaration processing, error handling for individual extraction failures, and index finalization.

**Phase 1 targets**: Coq standard library and MathComp.
**Phase 2 targets**: User project libraries with incremental re-indexing (out of scope for this spec).

---

## 3. Definitions

| Term | Meaning |
|------|---------|
| **Declaration** | A named Coq definition: lemma, theorem, definition, inductive type, constructor, instance, or axiom |
| **Constr.t** | Coq's internal kernel term representation (the raw expression before our normalization) |
| **`.vo` file** | Compiled Coq library file containing type-checked declarations |

---

## 4. Extraction Pipeline

### 4.1 Overall Flow

```
1. Discover .vo files for target libraries (stdlib, MathComp)
2. Create fresh SQLite database (drop existing if present)
3. Create all tables (see storage.md)
4. For each .vo file:
   a. Load the file via coq-lsp or SerAPI
   b. Enumerate all declarations in the file
   c. For each declaration, run per-declaration processing (Section 4.2)
   d. Batch-insert results into SQLite (commit every 1,000 rows)
5. Build global symbol_freq table from all declarations' symbol sets
6. Rebuild FTS index
7. Write index_meta entries (schema_version, coq_version, mathcomp_version, created_at)
8. Run integrity check
```

### 4.2 Per-Declaration Processing

For each declaration extracted from a `.vo` file:

```
1. Extract the Constr.t term (type expression for the declaration)
2. constr_to_tree(constr_t)              → raw ExprTree
   Applies during conversion:
   - Currify n-ary App to binary (coq-normalization.md)
   - Strip Cast nodes (coq-normalization.md)
   - Erase universe annotations (coq-normalization.md)
   - Normalize projections (coq-normalization.md)
   - Fully qualify all names (coq-normalization.md)
3. recompute_depths(tree)                → depth-annotated tree
4. assign_node_ids(tree)                 → id-annotated tree
5. cse_normalize(tree)                   → CSE-reduced tree
6. extract_symbols(tree)                 → list of fully qualified symbol names
7. extract_dependencies(declaration)     → list of (dst_name, relation) edges
8. wl_histogram(tree, h=3)              → WL feature vector
9. pretty_print(declaration)             → human-readable statement string
```

**Output per declaration** (one row in each relevant table):
- `declarations`: name, module, kind, statement, type_expr, serialized constr_tree, node_count, symbol_set (JSON)
- `wl_vectors`: (decl_id, h=3, histogram JSON)
- `dependencies`: (src_id, dst_id, relation) for each resolved dependency

### 4.3 Symbol Extraction

Collect all `LConst`, `LInd`, and `LConstruct` names from the normalized expression tree. Deduplicate into a set. This becomes `declarations.symbol_set`.

```
function extract_symbols(tree: ExprTree) -> list[str]:
    symbols = set()
    for node in tree (depth-first):
        if isinstance(node.label, (LConst, LInd)):
            symbols.add(node.label.name)
        elif isinstance(node.label, LConstruct):
            symbols.add(node.label.name)
    return sorted(symbols)
```

### 4.4 Dependency Extraction

Extract edges from a declaration to other declarations it references.

| Relation | Meaning | How to detect |
|----------|---------|---------------|
| `uses` | Declaration's type/body references another constant | Presence of `LConst(name)` in the expression tree |
| `instance_of` | Declaration is a typeclass instance | Coq's instance registration metadata |

Dependencies reference declarations by fully qualified name. During database insertion, resolve names to `declarations.id` foreign keys. Skip unresolved names (they reference declarations outside the indexed scope).

### 4.5 Global Frequency Table

After all declarations are inserted, build `symbol_freq`:

```
function build_symbol_freq(db):
    freq = {}  # symbol → count
    for each declaration in db:
        for symbol in json.loads(declaration.symbol_set):
            freq[symbol] = freq.get(symbol, 0) + 1
    insert all (symbol, count) pairs into symbol_freq table
```

---

## 5. Extraction Tooling

### 5.1 Coq Interface

The extraction layer communicates with Coq through coq-lsp or SerAPI to:
- Load `.vo` files
- Enumerate declarations (name, kind)
- Retrieve `Constr.t` terms for each declaration
- Pretty-print declarations for human-readable output
- Resolve fully qualified names

The choice between coq-lsp and SerAPI is an implementation decision. Both expose the required APIs. The extraction layer should abstract this choice behind a common interface.

### 5.2 Library Discovery

**Standard library**: Locate `.vo` files under the Coq installation's `theories/` directory. Use `coqc -where` to find the installation path.

**MathComp**: Locate `.vo` files under the MathComp installation directory. Use `coqc` to resolve the `mathcomp` logical path.

---

## 6. Error Specification

### 6.1 Per-Declaration Errors

Individual declaration extraction may fail due to:

| Error | Classification | Outcome |
|-------|---------------|---------|
| `Constr.t` extraction fails | Dependency error | Log warning with declaration name, skip declaration, continue |
| Normalization produces invalid tree | Invariant violation | Log warning, skip declaration, continue |
| Pretty-printing fails | Dependency error | Log warning, store empty statement, continue |
| Name resolution fails | Dependency error | Log warning, skip unresolved dependency edges, continue |

**MAINTAINS**: The index remains usable after partial extraction failures. A declaration that fails extraction is simply absent from the index.

### 6.2 Pipeline-Level Errors

| Error | Classification | Outcome |
|-------|---------------|---------|
| `.vo` file not found for expected library | Input error | Abort with clear error message listing expected paths |
| Coq not installed or wrong version | Dependency error | Abort with installation instructions |
| Database write failure (disk full, permissions) | Dependency error | Abort, delete partial database file |
| Integrity check fails | Invariant violation | Delete database, report error |

---

## 7. Non-Functional Requirements

- **Idempotency**: Running extraction twice produces an identical database (modulo `created_at` timestamp). The database file is always created fresh.
- **Progress reporting**: Log progress at the `.vo` file level (e.g., `"Processing Coq.Init.Nat [42/312]"`).
- **Throughput**: Target extraction of stdlib + MathComp (~50K declarations) in under 10 minutes on a modern laptop.

---

## 8. Examples

### Example: Extracting `Nat.add_comm`

**Given**: The declaration `Nat.add_comm` in `Coq.Arith.PeanoNat` states `forall n m : nat, n + m = m + n`.

**When**: Per-declaration processing runs on this declaration.

**Then**:
- `declarations` row: name=`"Coq.Arith.PeanoNat.Nat.add_comm"`, module=`"Coq.Arith.PeanoNat"`, kind=`"Lemma"`, statement=`"forall n m : nat, n + m = m + n"`, node_count=~15 (post-CSE)
- `symbol_set`: `["Coq.Init.Datatypes.nat", "Coq.Init.Nat.add", "Coq.Init.Logic.eq"]`
- `wl_vectors`: one row with h=3, histogram JSON containing ~50 entries
- `dependencies`: edges to `Coq.Init.Nat.add`, `Coq.Init.Logic.eq`, `Coq.Init.Datatypes.nat` with relation `uses`

### Example: Handling a Failed Declaration

**Given**: Declaration `Foo.bar` triggers an exception during `Constr.t` extraction.

**When**: Per-declaration processing catches the exception.

**Then**: A warning is logged: `"Skipping Foo.bar: extraction failed: <error details>"`. The pipeline continues with the next declaration. `Foo.bar` is absent from the index. All other declarations are indexed normally.
