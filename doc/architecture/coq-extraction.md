# Coq Library Extraction

Offline extraction of declarations from compiled Coq/Rocq libraries into the search index.

**Feature**: [Library Indexing](../features/library-indexing.md)
**Stories**: [Epic 1: Library Indexing](../requirements/stories/tree-search-mcp.md#epic-1-library-indexing)

---

## Extraction Pipeline

```
.vo files (compiled Coq libraries)
  │
  ▼
coq-lsp or SerAPI
  │  Read each declaration's Constr.t kernel term
  │
  ▼
Per-declaration processing:
  1. Parse Constr.t            → ConstrNode (with pre-resolved FQNs)
  2. coq_normalize(constr_node)→ normalized ExprTree (constr_to_tree + recompute_depths + assign_node_ids)
  3. cse_normalize(tree)       → CSE-reduced tree (recomputes depths + node_ids after)
  4. extract_symbols(tree)     → symbol set {constants, inductives, constructors}
  5. wl_histogram(tree, h=3)   → WL kernel vector for structural screening (Phase 1 computes h=3 only)
  6. pretty_print(name)        → human-readable statement
  7. pretty_print_type(name)   → human-readable type signature

  Pass 2 (after all declarations are inserted):
  8. extract_dependencies()   → dependency edges (uses, instance_of, ...)
  │
  ▼
SQLite database (see storage.md)
  Write: declarations, dependencies, symbols, wl_vectors, symbol_freq,
         declarations_fts, index_meta
```

### Module path derivation

The `module` field on each declaration is the logical path of the `.vo` file from which the declaration was extracted — not derived from string manipulation of the fully qualified name. For nested modules, the `.vo` file is the source of truth.

### Kind mapping

Declaration kind values are stored as lowercase strings. The extraction layer maps Coq declaration forms to storage kinds and lowercases before storage.

| Coq Declaration Form | Storage Kind | Notes |
|---------------------|-------------|-------|
| `Lemma` | `lemma` | |
| `Theorem` | `theorem` | |
| `Definition` | `definition` | |
| `Let` | `definition` | Local definition |
| `Coercion` | `definition` | |
| `Canonical Structure` | `definition` | |
| `Inductive` | `inductive` | |
| `Record` | `inductive` | Records are inductive types |
| `Class` | `inductive` | Classes are records |
| `Constructor` | `constructor` | Inductive type constructors |
| `Instance` | `instance` | Typeclass instances |
| `Axiom` | `axiom` | |
| `Parameter` | `axiom` | |
| `Conjecture` | `axiom` | |
| `Notation` | *(excluded)* | Not indexable — no kernel term |
| `Abbreviation` | *(excluded)* | Not indexable — no kernel term |
| `Section Variable` | *(excluded)* | Not present in closed `.vo` forms |

### Serialization

The `constr_tree` BLOB format is defined in [storage.md](storage.md). See the storage specification for serialization requirements.

## Extraction Targets

### Phase 1 (MVP)

- **Coq standard library**: All declarations from the installed Coq/Rocq stdlib `.vo` files.
- **MathComp**: All declarations from the installed MathComp `.vo` files, indexed into the same database distinguished by module path.

### Phase 2

- **User project**: Declarations from a user-specified project directory. Supports incremental re-indexing — only changed files are re-extracted.

## Extraction Tooling

Declarations are read from compiled `.vo` files via coq-lsp or SerAPI. Both tools provide access to `Constr.t` kernel terms, which are the input to the normalization pipeline. The choice between them is an implementation decision — both produce equivalent kernel terms.

Key requirement: the extraction tool must be version-compatible with the installed Coq/Rocq version. The extracted library version is recorded in `index_meta` for stale detection.

## Error Handling

Extraction of individual declarations may fail (e.g., unsupported term constructors, serialization errors). Failures are logged with the declaration name and error, but do not abort the indexing run. The index is usable with partial coverage; missing declarations are a degraded-quality outcome, not a fatal error.

**Backend process crash or hang**: If the extraction backend (coq-lsp or SerAPI) crashes or becomes unresponsive during an indexing run, the pipeline aborts and deletes the partial database file. This is a pipeline-level fatal error.

## Progress Reporting

Both extraction passes report progress:
- Pass 1: "Extracting declarations [N/total]" (per-declaration granularity)
- Pass 2: "Resolving dependencies [N/total]" (per-declaration granularity)

## Index Construction

The indexing command:
1. Detects the installed Coq/Rocq version and target library versions
2. Extracts all declarations through the pipeline above
3. Computes global symbol frequencies across all declarations
4. Writes everything to a single SQLite database
5. Records the index schema version and library versions in `index_meta`

The entire process runs without GPU, network access, or external API keys.
