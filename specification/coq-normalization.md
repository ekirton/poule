# Coq-Specific Adaptations

Transformations applied during `to_expr_tree()` conversion, before any retrieval processing. They normalize Coq's kernel term representation to match the assumptions of the tree algorithms (which were designed for Lean 4's binary-application, no-cast representation).

Parent architecture: [doc/architecture/coq-normalization.md](../doc/architecture/coq-normalization.md)
Data structures: [data-structures.md](data-structures.md)
Next step: [cse-normalization.md](cse-normalization.md)

---

## 1. Purpose

Normalize Coq's `Constr.t` kernel terms into a canonical `ExprTree` form that is structurally uniform across Coq-specific syntactic variations. Without these adaptations, structurally equivalent expressions would produce different trees, degrading retrieval quality.

---

## 2. Scope

Covers the six Coq-specific transforms applied during `constr_to_tree()` conversion, plus the depth and node-id assignment passes. Does not cover CSE normalization (see [cse-normalization.md](cse-normalization.md)) or the retrieval channels that consume the normalized tree.

---

## 3. Currification of N-ary Application

**Problem**: Coq represents application as `App(f, [|a1; a2; ...; an|])` — a single node with n+1 children. Lean uses binary application `App(App(f, a1), a2)`. The WL kernel and TED algorithms expect uniform tree structure; n-ary application creates variable fan-out that distorts similarity.

**Transform**: Convert n-ary `App` to nested binary `App` during tree construction.

```
function currify_app(f, args):
    # args = [a1, a2, ..., an]
    result = f
    for a in args:
        result = ExprTree(label=LApp, children=[result, a])
    return result
```

Example: `App(f, [a, b, c])` becomes `App(App(App(f, a), b), c)`.

**Depth assignment**: After currification, recompute depths bottom-up. The outermost `App` inherits the original `App` node's depth; inner `App` nodes get increasing depths.

**Node count impact**: An n-ary application `App(f, [a1..an])` with 1 App node becomes n App nodes. This increases the total node count. The size filtering thresholds in WL screening are calibrated on the post-currification count.

---

## 4. Cast Stripping

**Problem**: `Cast(expr, kind, type)` nodes are computationally irrelevant — they assert a type annotation but do not change the expression's meaning. Including them adds noise to structural comparison.

**Transform**: Replace every `Cast(expr, _, _)` with its inner `expr`, recursively.

```
function strip_casts(tree):
    match tree.label:
        LCast -> strip_casts(tree.children[0])  # the inner expression
        _ -> ExprTree(tree.label, [strip_casts(c) for c in tree.children])
```

Note: `LCast` is not in the `node_label` type because it is stripped before the tree is constructed. During raw `Constr.t` traversal, when encountering a `Cast` node, simply recurse into the first child and ignore the cast kind and type arguments.

---

## 5. Universe Erasure

**Problem**: Coq's universe-polymorphic constants carry universe instance annotations: `Const(name, [u1; u2; ...])`. These are structural noise for retrieval — two uses of the same constant at different universe levels should be treated identically.

**Transform**: When constructing `LConst`, `LInd`, or `LConstruct` nodes from `Constr.t`, discard the universe instance entirely. The node carries only the qualified name.

```
# During Constr.t traversal:
case Const(name, _univs):  → ExprTree(label=LConst(canonical_fqn(name)))
case Ind((name, i), _univs):  → ExprTree(label=LInd(canonical_fqn(name)))
case Construct(((name, i), j), _univs):  → ExprTree(label=LConstruct(canonical_fqn(name), j))
```

---

## 6. Projection Normalization

**Problem**: Coq has two ways to project a field from a record: `Proj(projection, term)` and the equivalent `Case` elimination. These are semantically identical but structurally different.

**Transform**: Treat `Proj` as a special interior node with one child (the term being projected). The projection name goes into the label.

```
case Proj(proj, term):
    proj_name = projection_to_string(proj)
    → ExprTree(label=LProj(proj_name), children=[convert(term)])
```

This preserves the projection in the tree. Two uses of the same projection will match via WL labels.

---

## 7. Notation Transparency

**Problem**: Coq's notation system allows expressions like `x + y` which are parsed into kernel terms like `Nat.add x y`. The search system must index kernel terms, not surface syntax, so that notation differences don't affect retrieval.

**Action**: No transform needed. Extraction produces kernel-level `Constr.t` terms, which are already notation-expanded. Index the kernel terms as-is. The pretty-printed surface form (with notation) is stored separately for display and full-text search.

---

## 8. Fully Qualified Names

**Problem**: Coq's section and module system means the same definition can be referenced by short name (`add_comm`), partially qualified name (`Nat.add_comm`), or fully qualified name (`Coq.Arith.PeanoNat.Nat.add_comm`). The search index must use a canonical form.

**Action**: Always use fully qualified names in `LConst`, `LInd`, and `LConstruct` labels. During extraction, resolve all names to their fully qualified canonical form using the Coq environment.

```
# Use the kernel's canonical name resolution:
fqn = canonical_fqn(const_name)
```

Store the fully qualified name in `declarations.name`. The shorter display name can be stored separately or computed on demand.

---

## 9. Section Variable Abstraction

**Problem**: Definitions inside Coq sections reference section variables as free variables. When the section is closed, these become universally quantified parameters. The indexed form should be the closed (post-section) form.

**Action**: Index only the closed form of each definition. If extracting while a section is open, either:
- Wait for the section to close and extract the discharged form, or
- Manually abstract over section variables (adding `Prod` binders for each section variable)

When indexing from compiled `.vo` files, sections are already closed and no special handling is needed.

---

## 10. Normalization Pipeline

The full normalization pipeline, applied to each extracted `Constr.t` term:

```
function coq_normalize(constr_t):
    tree = constr_to_tree(constr_t)     # raw conversion, handling:
                                         #   - Cast: skip, recurse into child
                                         #   - App: currify to binary
                                         #   - Const/Ind/Construct: erase universes, fully qualify
                                         #   - Proj: keep as LProj node
    tree = recompute_depths(tree)        # set depth field on all nodes
    tree = assign_node_ids(tree)         # set unique node_id on all nodes
    return tree
```

After `coq_normalize`, the tree is ready for CSE normalization (see [cse-normalization.md](cse-normalization.md)) and then channel processing.

---

## 11. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Unrecognized `Constr.t` variant | Dependency error | Log warning with declaration name and variant tag; skip declaration |
| Name resolution fails (canonical FQN not found) | Dependency error | Use the raw name as-is; log warning |
| `Constr.t` contains cyclic references | Invariant violation | Cap recursion depth at 1,000; skip declaration if exceeded |
| Cast stripping produces empty tree | Invariant violation | Skip declaration; log warning |
| Currification of 0-arg App (degenerate) | Input error | Return `f` unchanged (no App node created) |

---

## 12. Examples

### Example: Currification of `App(f, [a, b, c])`

**Given**: A raw `Constr.t` node `App(f, [a, b, c])`.

**When**: `constr_to_tree` processes this node.

**Then**: Three nested binary `App` nodes are created:
```
App(App(App(f_tree, a_tree), b_tree), c_tree)
```
Node count increases from 1 App node to 3 App nodes.

### Example: Universe erasure for `@eq`

**Given**: `Const("Coq.Init.Logic.eq", [Set])` — the equality predicate specialized to `Set`.

**When**: `constr_to_tree` processes this node.

**Then**: `ExprTree(label=LConst("Coq.Init.Logic.eq"), children=[])`. The universe `[Set]` is discarded. A second occurrence `Const("Coq.Init.Logic.eq", [Type])` produces an identical tree node.

### Example: Cast stripping

**Given**: `Cast(App(f, [a]), VMcast, nat_type)` — an application with a VM cast annotation.

**When**: `constr_to_tree` encounters the `Cast`.

**Then**: The `Cast` wrapper is discarded. Processing continues with `App(f, [a])`, which produces `ExprTree(label=LApp, children=[f_tree, a_tree])`.
