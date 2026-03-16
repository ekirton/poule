# CSE Normalization Test Feedback

## Incorrect `node_count` expectation in two tests

**Tests affected:**
- `TestNodeCountUpdated::test_node_count_reduced_after_cse` (line 400)
- `TestSpecExamples::test_list_nat_arrow_list_nat_cse` (line 664)

**Issue:** Both tests build the same tree structure: `Prod(App(Ind(list), Ind(nat)), App(Ind(list), Ind(nat)))` with initial `node_count=7`. After CSE, the second `App(Ind(list), Ind(nat))` subtree is correctly replaced by `LCseVar(0)`, producing `Prod(App(Ind(list), Ind(nat)), LCseVar(0))`.

The resulting tree has **5 nodes**: `LProd` + `LApp` + `LInd(list)` + `LInd(nat)` + `LCseVar(0)` = 5.

Both tests assert `tree.node_count == 4`, which is an arithmetic error. The correct expected value is `5`.

Both tests' structural assertions pass correctly — the tree structure is exactly as expected. Only the `node_count` integer assertion is wrong.

**Suggested fix:** Change `assert tree.node_count == 4` to `assert tree.node_count == 5` in both tests.
