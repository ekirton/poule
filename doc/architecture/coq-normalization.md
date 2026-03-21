# Coq Expression Normalization

Transformations applied during tree construction to normalize Coq's kernel term representation for the retrieval algorithms.

**Feature**: [Expression Normalization](../features/expression-normalization.md)
**Implementation spec**: [specification/coq-normalization.md](../../specification/coq-normalization.md)

---

## Normalization Pipeline

Applied to each extracted `Constr.t` term:

```
constr_t → constr_to_tree() → recompute_depths() → assign_node_ids() → normalized tree
```

During `constr_to_tree()`, the following adaptations are applied inline. The input to `constr_to_tree()` is a `ConstrNode` — an intermediate representation of Coq's `Constr.t` kernel term with pre-resolved fully qualified names. The `ConstrNode` is produced by a backend-specific parser (coq-lsp JSON or SerAPI S-expression) before normalization.

### ConstrNode

The `ConstrNode` intermediate type mirrors Coq's `Constr.t` algebraic data type with one key difference: all constant, inductive, and constructor references carry pre-resolved fully qualified canonical names (not kernel-internal indices). This eager FQN resolution happens during parsing, before `constr_to_tree()` is called.

`ConstrNode` variants (matching Coq's `Constr.t` constructors):
`Rel(n)`, `Var(name)`, `Sort(sort)`, `Cast(term, _, type)`, `Prod(name, type, body)`, `Lambda(name, type, body)`, `LetIn(name, value, type, body)`, `App(func, args[])`, `Const(fqn, _)`, `Ind(fqn, _)`, `Construct(fqn, idx, _)`, `Case(info, scrutinee, branches[])`, `Fix(idx, names[], types[], bodies[])`, `CoFix(idx, names[], types[], bodies[])`, `Proj(proj, term)`, `Int(value)`, `Float(value)`

Universe parameters (marked `_`) are present in the intermediate representation but erased during `constr_to_tree()`.

## Adaptations

| Concern | Problem | Transform |
|---------|---------|-----------|
| N-ary `App(f, args)` | Variable fan-out distorts WL and TED similarity | Currify to binary `LApp(LApp(f, a1), a2)` |
| `Cast` nodes | Computationally irrelevant; adds structural noise | Strip — recurse into inner expression, skip cast |
| `Var` nodes | Should not occur in closed `.vo` terms | Error — `Var` in a closed term is an extraction-layer fault |
| Universe annotations | Two uses of the same constant at different universe levels should be identical | Erase universe parameters from `Const`, `Ind`, `Construct` |
| Binder names | Names in `Lambda`, `LetIn`, `Prod` are irrelevant (de Bruijn) | Discard — `LAbs`, `LLet`, `LProd` carry no name payload |
| `Sort` values | Multiple sort variants (`Prop`, `SProp`, `Set`, `Type(u)`) | Map to three SortKind values: `PROP` (Prop+SProp), `SET`, `TYPE_UNIV` (Type with universe erased) |
| `Proj` vs `Case` | Semantically identical, structurally different | MVP: keep `Proj` as special interior node with projection name in label |
| `Construct` names | Constructors carry `(mind_name, i, j)` tuple | `LConstruct` stores the parent inductive type's FQN (resolved from mind_name+i), plus the constructor index `j`. All constructors of the same inductive type contribute the same symbol name. |
| `Fix`/`CoFix` | Coq's `Fix(rec_index, (names, types, bodies))` carries extra data | The parser backend destructures the tuple, delivering `(idx, bodies)` to `constr_to_tree()`. Types and names are discarded. `LFix(idx)` has `len(bodies)` children. |
| `Int`/`Float` | Primitive literals | Map to `LPrimitive(value)` leaf nodes |
| Notation | Surface syntax (`x + y`) differs from kernel term (`Nat.add x y`) | No action — coq-lsp/SerAPI extraction yields kernel terms. REQUIRES: input is a kernel-level `Constr.t` term with all notations expanded. |
| Name qualification | Same definition referenced by short, partial, or fully qualified name | Always use fully qualified canonical names. When the backend provides kernel terms, names are pre-resolved to canonical FQNs during extraction (eager resolution), before reaching `constr_to_tree()`. When the backend provides type signature text (coq-lsp path), the `TypeExprParser` produces short display names; these are resolved to FQNs in a post-extraction step via batched `Locate` queries (see [coq-extraction.md](coq-extraction.md#symbol-fqn-resolution)). |
| Section variables | Open-section definitions have free variables; closed form adds binders | Index only closed (post-section) forms from `.vo` files |

### Direct Mappings (no transform needed)

The following `Constr.t` variants map directly to `ExprTree` nodes without special adaptation:

| Constr.t variant | ExprTree label | Children |
|-----------------|----------------|----------|
| `Rel(n)` | `LRel(n)` | Leaf (0 children) |
| `Const(fqn, _)` | `LConst(fqn)` | Leaf (0 children) |
| `Ind(fqn, _)` | `LInd(fqn)` | Leaf (0 children) |
| `Prod(_, type, body)` | `LProd` | 2 children: type, body |
| `Case(info, scrutinee, branches)` | `LCase(ind_name)` | 1 + len(branches) children: scrutinee, then each branch |

## CSE Normalization

After the Coq-specific pipeline, Common Subexpression Elimination reduces expression size by replacing repeated non-constant subexpressions with fresh `LCseVar` variables. Three passes: subexpression hashing, frequency counting, variable replacement.

Key invariant: constants (`LConst`, `LInd`, `LConstruct`) are never replaced — they carry semantic identity.

Typical effect: 2-10x node reduction on expressions with heavy type annotation repetition.

See [specification/cse-normalization.md](../../specification/cse-normalization.md) for the full algorithm.
