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
coq-lsp
  │  List declarations: (name, type_sig) per module via Search
  │  Detect kind per declaration (About queries, batched)
  │
  ▼
Deduplicate declarations by fully qualified name (keep first occurrence)
  │
  ▼
Per-declaration processing:
  1. Parse type_signature text → ConstrNode (via TypeExprParser)
     (parse failure → partial result stored, declaration reachable only via name/FTS search)
  2. coq_normalize(constr_node)→ normalized ExprTree (constr_to_tree + recompute_depths + assign_node_ids)
  3. cse_normalize(tree)       → CSE-reduced tree (recomputes depths + node_ids after)
  4. extract_symbols(tree)     → raw symbol set {short display names from parsed text}
  5. resolve_symbols(raw_set)  → FQN symbol set {fully qualified kernel names via Locate queries}
     (unresolvable names kept as-is; ambiguous names resolved to all matching FQNs)
  6. wl_histogram(tree, h=3)   → WL kernel vector for structural screening (Phase 1 computes h=3 only)
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

### Fully qualified name derivation

Backends that return short names (e.g., coq-lsp `Search` returns `Nat.add_comm` rather than `Coq.Arith.PeanoNat.Nat.add_comm`) derive fully qualified names by prepending the `.vo` file's logical module path. The logical module path is derived from the filesystem path using heuristic prefix stripping (see below). The resulting name has the form `<logical_module_path>.<short_name>`.

### Module path derivation

The `module` field on each declaration is the logical path of the `.vo` file from which the declaration was extracted — not derived from string manipulation of the fully qualified name. For nested modules, the `.vo` file is the source of truth.

The logical path is derived from the `.vo` file's filesystem path by stripping known directory prefixes (`user-contrib/`, `theories/`), removing version-specific prefixes (e.g., `Stdlib/`), converting path separators to dots, and removing the `.vo` extension.

### Kind detection

Declaration kind is not always available directly from the backend's declaration listing. Some backends (e.g., coq-lsp) return only `(name, type_sig)` pairs and require a separate query per declaration to determine the kind. The kind detection mechanism is backend-dependent, and the response format may vary across Coq/Rocq versions. See the extraction specification (§4.1.1) for backend-specific detection contracts.

In Rocq 9.x, the `About` response may include multiple `Expands to:` lines when a notation aliases a real constant (e.g., `pred` is a notation that expands to `Nat.pred`, which is a `Constant`). Kind detection must prefer the underlying constant/inductive/constructor category over the notation category when both are present. This ensures that notation aliases of indexable declarations remain in the index.

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
| `Ltac` | *(excluded)* | Tactic definitions — no kernel term |
| `Module` | *(excluded)* | Module declarations — no kernel term |

### Serialization

The `constr_tree` BLOB format is defined in [storage.md](storage.md). See the storage specification for serialization requirements.

## Extraction Targets

### Phase 1 (MVP)

All declarations from the six Tier 0 libraries (see [extraction-library-support.md](../features/extraction-library-support.md)):

- **Coq standard library** (stdlib)
- **MathComp**
- **stdpp**
- **Flocq**
- **Coquelicot**
- **CoqInterval**

Each library is indexed into a per-library SQLite database distinguished by module path. See [index-build-script.md](index-build-script.md) for the per-library build pipeline.

### Phase 2

- **User project**: Declarations from a user-specified project directory. Supports incremental re-indexing — only changed files are re-extracted.

## Tier Coverage

The feature specification ([extraction-library-support.md](../features/extraction-library-support.md)) defines three tiers of library coverage with explicit success-rate targets. The architecture phases map to these tiers as follows:

### Tier-to-phase mapping

| Feature Tier | Libraries | Success-Rate Target | Architecture Phase |
|---|---|---|---|
| Tier 0 (P0) | Coq stdlib, MathComp, stdpp, Flocq, Coquelicot, CoqInterval | 95% (stdlib, Flocq, Coquelicot) / 90% (MathComp, stdpp, CoqInterval) | Phase 1 — the extraction pipeline, text-based type parser, and per-declaration error isolation described above are the mechanisms that achieve Tier 0 targets |
| Tier 1 (P1) | Validated opam-installable projects (standard-Ltac and ssreflect-based) | Reported per-project | Phase 2 — user-project extraction with incremental re-indexing extends the pipeline to arbitrary opam-installable projects; Tier 1 projects are those where extraction has been validated |
| Tier 2 (P2) | Custom proof mode projects (Iris, CompCert, Fiat-Crypto) | Best-effort | No dedicated phase — the existing pipeline extracts declarations from these projects but with reduced premise granularity where custom tactics wrap standard Coq tactics |

### How the pipeline achieves tier targets

**Tier 0 coverage** relies on three properties of the extraction pipeline:

1. **Per-declaration error isolation**: Individual extraction failures are logged but do not abort the indexing run. This prevents a single malformed declaration from reducing the overall success rate.
2. **Text-based type parsing consistency**: Both index-time and query-time parsing use the same `TypeExprParser`, so structural matching works correctly even without kernel-precise terms.
3. **Batched kind detection**: The `About`-query batching mechanism (up to 100 queries per document) keeps extraction throughput high enough to process the full Tier 0 library set in a single indexing run.

**Tier 1 coverage** adds incremental re-indexing (Phase 2) so that validated projects can be re-extracted efficiently as upstream libraries evolve. Success rates are reported per-project rather than guaranteed; the pipeline infrastructure is the same as Tier 0.

**Tier 2 coverage** uses the same extraction pipeline without framework-specific adapters. Declarations are extracted and indexed, but premise annotations reflect the custom-tactic level rather than the underlying Coq-tactic level. The architecture does not provide framework-specific extraction plugins — this is an explicit scope boundary in the feature specification.

## Extraction Tooling

Declarations are read from compiled `.vo` files via coq-lsp. coq-lsp is the sole supported extraction backend (see [library-indexing.md](../features/library-indexing.md) for design rationale).

The `Search _ inside M.` command returns textual `name : type_signature` pairs without kernel terms. To produce structural data (expression trees, symbol sets, WL histograms), the pipeline parses type signature strings into `ConstrNode` trees using a pure-Python text parser (`TypeExprParser`). This parser is used at both index time and query time for consistent structural matching.

coq-lsp does not return declaration kinds directly. The backend issues a separate `About <name>.` query per declaration to determine kind, with queries batched into shared documents (≤100 per document) to reduce round-trip overhead.

Key requirement: coq-lsp must be version-compatible with the installed Coq/Rocq version. The extracted library version is recorded in `index_meta` for stale detection.

### Text-Based Type Parsing

When coq-lsp returns a type signature string (e.g., `"forall n : nat, n + 0 = n"`), the `TypeExprParser` converts it to a `ConstrNode` tree:

```
type_signature string
  │
  ▼
TypeExprParser.parse(text)
  │  Tokenize → Pratt parse → resolve names (de Bruijn) → ConstrNode
  │
  ▼
coq_normalize(constr_node) → ExprTree
  │
  ▼
cse_normalize(tree) → CSE-reduced tree
  │
  ▼
extract_symbols(tree), wl_histogram(tree, h=3)
```

The text parser initially produces short display names — `Const("nat")` rather than the kernel-precise `Ind("Coq.Init.Datatypes.nat")`. A post-extraction symbol resolution step resolves these short names to fully qualified kernel names using batched coq-lsp `Locate` queries (see Symbol FQN Resolution below). This ensures the symbol index uses canonical FQNs, which is essential for the MePo Symbol Overlap channel to match user queries like `Nat.add` against the correct index entries. WL histograms and structural matching continue to use the parser's display-name labels, which are internally consistent between index time and query time.

## Symbol FQN Resolution

The `TypeExprParser` produces short display names (`nat`, `+`, `list`, `eq`) because it parses textual type signatures, not kernel terms. These short names must be resolved to fully qualified kernel names (`Coq.Init.Datatypes.nat`, `Coq.Init.Nat.add`, `Coq.Init.Datatypes.list`, `Coq.Init.Logic.eq`) before being stored in the symbol index.

### Resolution mechanism

After `extract_symbols(tree)` produces a raw symbol set of short names, a resolution step maps each to its FQN:

1. **Batch `Locate` queries**: Issue coq-lsp `Locate <name>.` queries for each unique short name in the extraction batch. The `Locate` command returns the FQN and object kind (Constant, Inductive, Constructor). Queries are batched into shared documents (≤100 per document) to reduce round-trip overhead, following the same batching pattern as kind detection.

2. **Cache**: Maintain a `short_name → FQN` lookup table for the duration of the indexing run. Most short names recur across thousands of declarations (e.g., `nat` appears in ~40% of stdlib declarations), so the cache eliminates redundant queries. The cache is keyed by the exact short name string.

3. **Infix operator resolution**: Infix operators parsed as `Const("+")`, `Const("*")`, `Const("<")`, etc. are resolved via `Locate` like any other name. Coq's `Locate "+"` returns the underlying constant (e.g., `Coq.Init.Nat.add`). Operators that resolve to multiple notations are expanded to all matching FQNs.

4. **Fallback**: Names that cannot be resolved (e.g., `Locate` returns an error or the name is user-defined and not in the Coq environment) are stored as-is in the symbol set. This preserves information without discarding unresolvable names.

### Invariant

After resolution, the `symbol_set` column in `declarations` and the `symbol_freq` table both use FQNs as keys. The MePo inverted index built from `symbol_set` is therefore keyed by FQN, ensuring that query-time symbol resolution (see [retrieval-pipeline.md](retrieval-pipeline.md)) can match user-provided names at any qualification level.

## Error Handling

Extraction of individual declarations may fail (e.g., unsupported term constructors, serialization errors). Failures are logged with the declaration name and error, but do not abort the indexing run. The index is usable with partial coverage; missing declarations are a degraded-quality outcome, not a fatal error.

**Backend process crash or hang**: If the extraction backend (coq-lsp or SerAPI) crashes or becomes unresponsive during an indexing run, the pipeline aborts and deletes the partial database file. This is a pipeline-level fatal error.

## Progress Reporting

Progress reporting is opt-in: the indexing command is quiet by default and prints progress messages only when the caller enables a progress flag. When enabled, messages are written to stderr so they do not interfere with structured output.

Both extraction passes report progress at per-declaration granularity, and each message identifies the current stage:
- Pass 1: "Extracting declarations [N/total]"
- Pass 2: "Resolving dependencies [N/total]"

## Index Construction

The indexing command:
1. Deletes any existing database file at the output path
2. Detects the installed Coq/Rocq version and target library versions
3. Collects declarations from all `.vo` files, then deduplicates by fully qualified name (keeps first occurrence; duplicates arise from module re-exports across `.vo` files)
4. Processes each unique declaration through the pipeline above
5. Computes global symbol frequencies across all declarations
6. Writes everything to a single SQLite database
7. Records the index schema version and library versions in `index_meta`

The entire process runs without GPU, network access, or external API keys.
