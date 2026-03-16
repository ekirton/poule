# CSE Normalization

Common Subexpression Elimination reduces expression size by replacing repeated non-constant subexpressions with fresh variables, recovering the DAG structure lost during serialization.

Applied after [coq-normalization.md](coq-normalization.md), before any channel processing.

Parent architecture: [doc/architecture/coq-normalization.md](../doc/architecture/coq-normalization.md)
Data structures: [data-structures.md](data-structures.md)

Based on CSE normalization for tree-based premise selection (see [doc/background/tree-based-retrieval.md](../doc/background/tree-based-retrieval.md)).

---

## 1. Purpose

Reduce tree size by factoring out repeated subexpressions, improving retrieval quality in two ways: (1) WL histograms become more discriminating when duplicated boilerplate is collapsed, and (2) TED computation becomes feasible for expressions that would otherwise exceed the 50-node threshold.

---

## 2. Scope

Covers the 3-pass CSE algorithm (hash, count, replace) and its key invariant. Does not cover the Coq-specific normalization that precedes CSE (see [coq-normalization.md](coq-normalization.md)) or the retrieval channels that consume the CSE-reduced tree.

---

## 3. Algorithm

Three passes over the tree.

### Pass 1: Subexpression Hashing

Compute a content hash for every subtree, bottom-up.

```
function hash_subtree(node):
    if node is a leaf:
        return tag(node.label) + to_string(node.label)
    child_hashes = [hash_subtree(c) for c in node.children]
    return MD5(tag(node.label) + "-" + join(child_hashes, "-"))
```

Where `tag()` returns the constructor name as a short prefix string: `"Rel"`, `"Const"`, `"App"`, etc.

Store the hash on every node. Time: O(n) where n = node count.

### Pass 2: Frequency Counting

Build a frequency table `freq: hash -> int` counting how many times each subtree hash appears in the entire tree.

```
function count_frequencies(node, freq):
    freq[node.hash] += 1
    for c in node.children:
        count_frequencies(c, freq)
```

### Pass 3: Variable Replacement

Replace repeated non-constant subtrees with fresh CSE variables.

```
function cse_replace(node, freq, next_var_id, seen):
    if node.label is LConst or LInd or LConstruct:
        return node  # preserve constants — they carry semantic meaning

    if freq[node.hash] > 1:
        if node.hash in seen:
            return leaf(LCseVar(seen[node.hash]))
        else:
            seen[node.hash] = next_var_id
            next_var_id += 1
            # still process children for the first occurrence
            new_children = [cse_replace(c, freq, next_var_id, seen)
                            for c in node.children]
            return {node with children = new_children}
    else:
        new_children = [cse_replace(c, freq, next_var_id, seen)
                        for c in node.children]
        return {node with children = new_children}
```

---

## 4. Key Invariant

Constants (`LConst`, `LInd`, `LConstruct`) are never replaced, even if duplicated. They carry the semantic identity of the expression.

---

## 5. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Empty tree (no nodes) | Edge case | Return empty tree unchanged |
| Single-node tree | Edge case | Return tree unchanged (no duplicates possible) |
| Hash collision (two structurally different subtrees produce same MD5) | Invariant violation | Accepted as negligible risk — MD5 collision probability is ~2⁻⁶⁴ for birthday attacks on typical tree sizes (< 10K nodes) |
| Tree with all-constant nodes | Normal case | No replacements made; tree returned unchanged |

---

## 6. Examples

### Example: CSE on a type with repeated `nat`

**Given**: The type `nat → nat → nat`, which after Coq normalization produces:

```
Prod(
  Ind("Coq.Init.Datatypes.nat"),     # first nat
  Prod(
    Ind("Coq.Init.Datatypes.nat"),   # second nat
    Ind("Coq.Init.Datatypes.nat")    # third nat
  )
)
```

**When**: CSE normalization runs.

**Then**: The three `Ind("nat")` subtrees all share the same hash. However, `LInd` is a constant label, so the key invariant prevents replacement. The tree is returned unchanged. Node count remains 5.

### Example: CSE on a type with repeated compound subexpressions

**Given**: The type `list nat → list nat`, which after normalization contains two occurrences of the subtree `App(Ind("list"), Ind("nat"))`:

```
Prod(
  App(Ind("Coq.Init.Datatypes.list"), Ind("Coq.Init.Datatypes.nat")),
  App(Ind("Coq.Init.Datatypes.list"), Ind("Coq.Init.Datatypes.nat"))
)
```

Node count: 5 (1 Prod + 2 App + 2 pairs of Ind leaves... actually 7 nodes total).

**When**: CSE normalization runs.

**Then**:
- Pass 1: Both `App(Ind("list"), Ind("nat"))` subtrees get the same hash
- Pass 2: That hash has frequency 2
- Pass 3: The `App` node is not a constant, so the first occurrence is kept (with children processed), and the second is replaced by `LCseVar(0)`

Result:
```
Prod(
  App(Ind("Coq.Init.Datatypes.list"), Ind("Coq.Init.Datatypes.nat")),
  CseVar(0)
)
```

Node count reduced from 7 to 4.

### Example: CSE with no duplicates

**Given**: The type `nat → bool`, which has no repeated non-constant subtrees.

**When**: CSE normalization runs.

**Then**: All subtree hashes have frequency 1. No replacements are made. Tree is returned unchanged.
