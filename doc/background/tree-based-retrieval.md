# Tree-Based and Structural Retrieval Methods for Formal Mathematics (March 2026)

A survey of training-free, structure-aware retrieval methods for formal mathematical libraries, with implementation-level detail relevant to building a Coq/Rocq semantic search system.

Cross-references:
- [semantic-search.md](semantic-search.md) — Architecture options and delivery mechanisms
- [coq-premise-retrieval.md](coq-premise-retrieval.md) — Neural and hybrid premise selection
- [coq-ecosystem-gaps.md](coq-ecosystem-gaps.md) — Gap 1 (Semantic Lemma Search)

---

## 1. Tree-Based Premise Selection (Wang et al., NeurIPS 2025)

**Paper**: "Tree-Based Premise Selection for Lean4"
**Authors**: Zichen Wang, Anjie Dong, Zaiwen Wen
**Code**: https://github.com/imathwy/tbps (Python 58%, TypeScript 33%, Lean 4%)
**OpenReview**: https://openreview.net/forum?id=omyNP89YW6

The first training-free premise selection system competitive with neural methods. Represents formal expressions as trees, normalizes them with Common Subexpression Elimination, then applies a multi-stage pipeline: Weisfeiler-Lehman kernel for coarse screening, Tree Edit Distance + multiple similarity metrics for fine ranking.

### 1.1 Multi-Stage Pipeline

```
Query expression
    │
    ▼
[CSE normalization] ──→ normalized tree
    │
    ▼
[Size filtering] ──→ candidates within 1.2x node count ratio (1.8x for ≥600 nodes)
    │
    ▼
[WL coarse screening] ──→ top-1500 by cosine similarity of WL histograms (h=3)
    │
    ▼
[Fine ranking] ──→ weighted fusion of 4 metrics
    │
    ▼
Top-K results
```

### 1.2 Common Subexpression Elimination (CSE)

Operates in three phases on serialized expression trees:

1. **De Bruijn normalization**: Convert de Bruijn indices to binder names so structurally identical subexpressions under different binders hash identically.
2. **Subexpression hashing**: Recursively hash every subexpression with type-prefixed string hashing (e.g., `"App-{hash(fn)}-{hash(arg)}"`). Count occurrences in a frequency table.
3. **Variable replacement**: Replace any non-Const subexpression appearing more than once with a fresh free variable. Constants are preserved because they carry semantic meaning.

**Effect**: Recovers the DAG structure that exists in Coq/Lean's internal hash-consed representation but is lost during serialization. Reduces tree size by 2-10x in expressions with heavy type annotation repetition.

### 1.3 Weisfeiler-Lehman Kernel

The WL subtree kernel (Shervashidze et al., JMLR 2011) iteratively relabels tree nodes by hashing each node's label together with its sorted children's labels:

```
For each iteration i = 1..h:
  For each node v:
    new_label(v) = MD5(label(v) + "(" + sorted(children_labels) + ")")
```

After h iterations, each node's label encodes its depth-h subtree structure. The tree's feature vector is a histogram of all labels at all iterations. Cosine similarity between histograms measures structural similarity.

**Properties**:
- Time: O(h × m) per tree, where m = edges
- After h iterations, distinguishes trees up to subtree isomorphism at depth h
- h=3 is used for coarse screening (sufficient for local structure; fast)
- Precomputed WL vectors stored in database for the full library

**Initial labeling**: Depth-aware — `label(node) = simplified_type + "_d" + depth`. This makes the kernel position-sensitive (a `Nat` at depth 2 is different from a `Nat` at depth 5).

### 1.4 Tree Edit Distance (TED)

Zhang-Shasha algorithm via the Python `zss` library. Computes minimum-cost edit sequence (insert, delete, rename) between two ordered labeled trees.

**Cost model** (reflecting structural importance):

| Operation | Variable/Constant nodes | Interior nodes |
|-----------|------------------------|----------------|
| Insert | 0.2 | 1.0 |
| Delete | 0.2 | 1.0 |
| Rename (same type) | 0.0 | 0.0 |
| Rename (cross type) | 0.4 | 0.4 |

Normalized: `similarity = 1 - edit_distance / max(|T1|, |T2|)`

**Critical limitation**: Zhang-Shasha is O(n² × m²). The tbps implementation skips TED entirely for expressions with >50 nodes. This is a Python-specific bottleneck — an OCaml or Rust implementation of APTED (O(n³) worst case) could raise this to 200-500 nodes.

### 1.5 Additional Metrics

**Collapse-Match Similarity**: Measures whether the query tree structure can "collapse onto" a candidate's tree through node merging. Scores matching levels plus recursive child scores, normalized by candidate tree size.

**Const Name Jaccard**: Extracts all constant declaration names from both trees (filtering out typeclass instances), computes Jaccard similarity of the name sets. This is essentially a lightweight symbol-overlap measure.

### 1.6 Metric Fusion

For expressions ≤50 nodes:
```
score = 0.15 × WL + 0.40 × TED + 0.30 × collapse_match + 0.15 × const_jaccard
```

For expressions >50 nodes (no TED):
```
score = 0.15 × WL + 0.30 × collapse_match + 0.15 × const_jaccard
```

### 1.7 Performance

Evaluated on 217,555 Mathlib4 theorems (v4.18.0-rc1). Significantly outperforms BM25 and MePo across all K values (K = 1, 4, 8, 16, 32, 64, 128, 256). Training-free; no GPU required.

### 1.8 Computational Cost

| Stage | Offline | Online (per query) |
|-------|---------|-------------------|
| CSE | All 217K theorems | Query expression |
| WL encoding | All theorems at h=1,3,5,10,20,40,80 | Query at h=3 |
| Size filtering | — | Linear scan |
| WL screening | — | Cosine vs. 217K vectors |
| TED (≤50 nodes) | — | 1500 × O(50⁴) |
| Collapse-match | — | 1500 candidates |
| Const Jaccard | — | 1500 candidates |

Bottleneck is TED. WL screening alone is sub-second.

---

## 2. MePo: Symbol-Overlap Baseline

**Reference**: Meng & Paulson, "Lightweight Relevance Filtering for Machine-Generated Resolution Problems", JAL 2009.

Iterative breadth-first expansion over the symbol graph:

```
S = symbols(goal)
R = {}
for i = 0, 1, 2, ...:
  for each unselected fact f:
    relevance(f) = Σ w(s) for s ∈ symbols(f) ∩ S
                   ─────────────────────────────
                   Σ w(s) for s ∈ symbols(f)
    where w(s) = 1 + 2/log₂(freq(s) + 1)
  select facts where relevance(f) ≥ p × (1/c)^i
  add their symbols to S
```

Parameters: p=0.6 (threshold), c=2.4 (decay). Rare symbols weighted higher.

**Performance**: R@32 = 42.1% on Lean Mathlib. Beats ReProver (38.7%) at the same cutoff — a strong training-free baseline.

**Coq**: CoqHammer already implements a MePo-like approach. Simple to extract and run independently.

---

## 3. SInE: Trigger-Based Axiom Selection

**Reference**: Hoder & Voronkov, "Sine Qua Non for Large Theory Reasoning", CADE 2011.

Each axiom has a "trigger" — its rarest symbol. Selection is transitive: an axiom is selected if its trigger appears in the goal or in an already-selected axiom.

```
trigger(axiom) = argmin_{s ∈ symbols(axiom)} freq(s)
Selected = {a : trigger(a) ∈ symbols(goal)}  // depth 0
For depth 1..d:
  Selected += {a : trigger(a) ∈ symbols(Selected)}
```

Very fast: O(|Library| × depth) with hash lookups. Won the CASC large-theory division. Complementary to MePo — SInE uses single-trigger selection while MePo uses weighted overlap.

---

## 4. BM25 on Serialized Expressions

Treat pretty-printed formal expressions as text documents. Apply standard BM25 (Okapi) ranking. Tokens = identifiers, operators, keywords.

Simple baseline; typically outperformed by structure-aware methods. Useful as a sanity check and as a complementary signal in hybrid retrieval. Standard off-the-shelf implementations available (SQLite FTS5, Tantivy, etc.).

---

## 5. k-NN with Proof-Level Locality

**Reference**: Blaauwbroek et al., "Graph2Tac", ICML 2024 (the k-NN component).

For each proof state, find the k nearest previous proof states in the same proof or nearby proofs in the dependency graph. Use the premises that worked for those states. Exploits a strong locality prior: nearby proof states often need similar lemmas.

In Graph2Tac, k-NN and GNN are highly complementary (1.27x improvement over either alone). The k-NN component alone outperforms CoqHammer on the Tactician benchmark.

**Relevance for search**: This is a *proof-time* method (requires an active proof state), not a *library-browsing* method. But the locality principle informs search design: results from the user's current file/project context should be ranked higher.

---

## 6. Coq Term Structure

### 6.1 Constr.t (Kernel Terms)

Coq's kernel terms have 17+ constructors:

| Constructor | Description | Leaf/Interior |
|-------------|-------------|---------------|
| `Rel(n)` | De Bruijn index | Leaf |
| `Var(id)` | Named variable | Leaf |
| `Meta(n)` | Metavariable | Leaf |
| `Evar(n, args)` | Existential variable | Interior |
| `Sort(s)` | Prop, Set, Type(u) | Leaf |
| `Cast(c, kind, t)` | Type cast | Interior (strip for comparison) |
| `Prod(name, type, body)` | Dependent product (∀) | Interior |
| `Lambda(name, type, body)` | Lambda abstraction | Interior |
| `LetIn(name, val, type, body)` | Let binding | Interior |
| `App(f, args)` | Application (**n-ary**) | Interior |
| `Const(name, univs)` | Constant reference | Leaf |
| `Ind(name, univs)` | Inductive type | Leaf |
| `Construct(name, univs)` | Constructor | Leaf |
| `Case(info, scrutinee, branches)` | Pattern match | Interior |
| `Fix(bodies)` | Fixpoint | Interior |
| `CoFix(bodies)` | Cofixpoint | Interior |
| `Proj(proj, term)` | Primitive projection | Interior |
| `Int(n)` | Primitive integer (8.10+) | Leaf |

### 6.2 Key Differences from Lean4 for Tree-Based Methods

| Aspect | Lean4 | Coq |
|--------|-------|-----|
| Application | Binary (curried) | N-ary: `App(f, [|a1;...;an|])` |
| Casts | None in kernel | `Cast` nodes (should strip) |
| Universes | Universe parameters | Universe polymorphism (should erase for comparison) |
| Projections | Integrated | `Proj` vs `Case` duality |
| Hash-consing | Internal (lost on export) | Internal (lost on export) |
| Extraction API | `Lean.Expr` via metaprogramming | `Constr.t` via OCaml API, MetaCoq, or coq-lsp |

### 6.3 Extraction Paths

1. **coq-lsp**: Exposes proof state and term information via LSP extensions. Can extract term structure incrementally. Most actively maintained path.
2. **SerAPI**: Deep serialization to S-expressions or JSON. Version-locked but comprehensive.
3. **MetaCoq**: Coq plugin that reifies `Constr.t` as Coq inductive types. Enables in-Coq analysis.
4. **OCaml plugin**: Direct access to `Constr.kind`. Most powerful but requires Coq version-specific compilation.

---

## 7. Complexity Comparison

| Method | Online Time (per query) | Offline Time | Training | GPU |
|--------|------------------------|-------------|----------|-----|
| MePo | O(Library × symbols) | Symbol frequency table | None | No |
| SInE | O(Library × depth) | Trigger table | None | No |
| BM25 | O(Library) with index | Build inverted index | None | No |
| WL screening | O(Library × h × m) | Compute all WL vectors | None | No |
| TED fine ranking | O(candidates × n² × m²) | None | None | No |
| Neural (ReProver) | O(Library) with ANN index | Train encoder model | Yes | Yes |

For a library of ~50-100K items, all training-free methods are sub-second for coarse screening on modern hardware. TED is the only bottleneck, and only for fine ranking of small candidate sets.

---

## References

Wang, Z., Dong, A., and Wen, Z. "Tree-Based Premise Selection for Lean4." NeurIPS 2025.

Shervashidze, N. et al. "Weisfeiler-Lehman Graph Kernels." JMLR 2011.

Zhang, K. and Shasha, D. "Simple Fast Algorithms for the Editing Distance Between Trees and Related Problems." SIAM J. Computing, 1989.

Pawlik, M. and Augsten, N. "Tree Edit Distance: Robust and Memory-Efficient." Information Systems, 2016.

Meng, J. and Paulson, L.C. "Lightweight Relevance Filtering for Machine-Generated Resolution Problems." JAL 2009.

Hoder, K. and Voronkov, A. "Sine Qua Non for Large Theory Reasoning." CADE 2011.

Blaauwbroek, L. et al. "Graph2Tac: Online Representation Learning of Formal Math Concepts." ICML 2024.

Alama, J. et al. "Premise Selection for Mathematics by Corpus Analysis and Kernel Methods." JAR 2013.
