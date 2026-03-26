"""TDD tests for the Const Jaccard channel.

Tests written BEFORE implementation. Implementation will live in
src/poule/channels/const_jaccard.py.

Specification: specification/channel-const-jaccard.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# jaccard_similarity tests
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    """Tests for jaccard_similarity(set_a, set_b)."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from Poule.channels.const_jaccard import jaccard_similarity

        self.jaccard_similarity = jaccard_similarity

    def test_identical_sets_return_one(self):
        """Identical nonempty sets -> 1.0."""
        s = {"Stdlib.Init.Nat.add", "Stdlib.Init.Datatypes.nat"}
        assert self.jaccard_similarity(s, s.copy()) == 1.0

    def test_partial_overlap(self):
        """{"a","b"} vs {"a","c"} -> 1/3."""
        result = self.jaccard_similarity({"a", "b"}, {"a", "c"})
        assert result == pytest.approx(1.0 / 3.0)

    def test_no_overlap(self):
        """Disjoint sets -> 0.0."""
        assert self.jaccard_similarity({"Nat.add"}, {"Bool.andb"}) == 0.0

    def test_both_empty(self):
        """Both empty -> 0.0 (not division by zero)."""
        assert self.jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        """One empty, one nonempty -> 0.0."""
        assert self.jaccard_similarity(set(), {"a", "b"}) == 0.0
        assert self.jaccard_similarity({"a", "b"}, set()) == 0.0

    def test_single_element_overlap(self):
        """{"a","b","c"} vs {"a","d","e"} -> 1/5."""
        result = self.jaccard_similarity({"a", "b", "c"}, {"a", "d", "e"})
        assert result == pytest.approx(1.0 / 5.0)

    def test_return_type_is_float(self):
        """Return value is always a float."""
        result = self.jaccard_similarity({"a"}, {"a"})
        assert isinstance(result, float)

    def test_symmetry(self):
        """jaccard(A, B) == jaccard(B, A)."""
        a = {"Nat.add", "Nat.mul"}
        b = {"Nat.add", "Nat.sub"}
        assert self.jaccard_similarity(a, b) == self.jaccard_similarity(b, a)


# ---------------------------------------------------------------------------
# extract_consts tests
# ---------------------------------------------------------------------------


class TestExtractConsts:
    """Tests for extract_consts(tree)."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from Poule.channels.const_jaccard import extract_consts

        self.extract_consts = extract_consts

    def _leaf(self, label):
        from Poule.models.tree import TreeNode

        return TreeNode(label=label, children=[])

    def _node(self, label, children):
        from Poule.models.tree import TreeNode

        return TreeNode(label=label, children=children)

    def _tree(self, root):
        from Poule.models.tree import ExprTree, node_count as _nc

        return ExprTree(root=root, node_count=_nc(root))

    def test_lconst_nodes_extracted(self):
        """Tree with LConst nodes -> their FQNs are in the result set."""
        from Poule.models.labels import LConst, LApp

        root = self._node(
            LApp(),
            [
                self._leaf(LConst("Stdlib.Init.Nat.add")),
                self._leaf(LConst("Stdlib.Init.Nat.mul")),
            ],
        )
        result = self.extract_consts(self._tree(root))
        assert result == {"Stdlib.Init.Nat.add", "Stdlib.Init.Nat.mul"}

    def test_lind_nodes_extracted(self):
        """Tree with LInd node -> its FQN is in the result set."""
        from Poule.models.labels import LInd

        root = self._leaf(LInd("Stdlib.Init.Datatypes.nat"))
        result = self.extract_consts(self._tree(root))
        assert result == {"Stdlib.Init.Datatypes.nat"}

    def test_lconstruct_extracts_parent_inductive_fqn(self):
        """LConstruct contributes the parent inductive FQN (name field)."""
        from Poule.models.labels import LConstruct

        root = self._leaf(LConstruct("Stdlib.Init.Datatypes.nat", 0))
        result = self.extract_consts(self._tree(root))
        assert result == {"Stdlib.Init.Datatypes.nat"}

    def test_mixed_labels_only_constants(self):
        """Only LConst, LInd, LConstruct contribute; LApp, LProd, LRel do not."""
        from Poule.models.labels import LApp, LProd, LConst, LRel

        inner = self._node(
            LProd(),
            [
                self._leaf(LConst("Nat.add")),
                self._leaf(LRel(0)),
            ],
        )
        root = self._node(LApp(), [inner, self._leaf(LRel(1))])
        result = self.extract_consts(self._tree(root))
        assert result == {"Nat.add"}

    def test_duplicate_constants_collapsed(self):
        """Duplicate constant references -> set with no duplicates."""
        from Poule.models.labels import LConst, LApp

        root = self._node(
            LApp(),
            [
                self._leaf(LConst("Nat.add")),
                self._leaf(LConst("Nat.add")),
            ],
        )
        result = self.extract_consts(self._tree(root))
        assert result == {"Nat.add"}

    def test_no_constants_returns_empty_set(self):
        """Tree with no constant/inductive/constructor nodes -> empty set."""
        from Poule.models.labels import LProd, LRel
        from Poule.models.enums import SortKind
        from Poule.models.labels import LSort

        root = self._node(
            LProd(),
            [
                self._leaf(LSort(SortKind.PROP)),
                self._leaf(LRel(0)),
            ],
        )
        result = self.extract_consts(self._tree(root))
        assert result == set()

    def test_all_three_label_types_combined(self):
        """Tree with LConst, LInd, and LConstruct -> union of all names."""
        from Poule.models.labels import LApp, LConst, LInd, LConstruct

        children = [
            self._leaf(LConst("Nat.add")),
            self._leaf(LInd("Nat")),
            self._leaf(LConstruct("Bool", 0)),
        ]
        # Use nested LApp to hold multiple children (binary application)
        inner = self._node(LApp(), [children[0], children[1]])
        root = self._node(LApp(), [inner, children[2]])
        result = self.extract_consts(self._tree(root))
        assert result == {"Nat.add", "Nat", "Bool"}

    def test_deeply_nested_constants_collected(self):
        """Constants at various depths are all collected."""
        from Poule.models.labels import LApp, LConst

        # Build a chain: LApp(LApp(LConst(a), LConst(b)), LConst(c))
        inner = self._node(
            LApp(),
            [
                self._leaf(LConst("deep.a")),
                self._leaf(LConst("deep.b")),
            ],
        )
        root = self._node(LApp(), [inner, self._leaf(LConst("deep.c"))])
        result = self.extract_consts(self._tree(root))
        assert result == {"deep.a", "deep.b", "deep.c"}

    def test_parser_placeholders_excluded(self):
        """Parser placeholder constants (_match_, _if_, etc.) are excluded.

        Spec: channel-const-jaccard.md §4.1 — names matching _*_ pattern
        are parser artifacts and shall be excluded."""
        from Poule.models.labels import LApp, LConst

        root = self._node(
            LApp(),
            [
                self._leaf(LConst("Nat.add")),
                self._leaf(LConst("_match_")),
                self._leaf(LConst("_if_")),
                self._leaf(LConst("_unit_")),
                self._leaf(LConst("_nil_")),
                self._leaf(LConst("_record_")),
            ],
        )
        result = self.extract_consts(self._tree(root))
        assert result == {"Nat.add"}

    def test_underscored_non_placeholder_kept(self):
        """Names with underscores that don't match _*_ pattern are kept."""
        from Poule.models.labels import LConst

        root = self._leaf(LConst("my_function"))
        result = self.extract_consts(self._tree(root))
        assert result == {"my_function"}


# ---------------------------------------------------------------------------
# const_jaccard_rank tests
# ---------------------------------------------------------------------------


class TestConstJaccardRank:
    """Tests for const_jaccard_rank(query_tree, candidates, declaration_symbols)."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from Poule.channels.const_jaccard import const_jaccard_rank

        self.const_jaccard_rank = const_jaccard_rank

    def _leaf(self, label):
        from Poule.models.tree import TreeNode

        return TreeNode(label=label, children=[])

    def _node(self, label, children):
        from Poule.models.tree import TreeNode

        return TreeNode(label=label, children=children)

    def _tree(self, root):
        from Poule.models.tree import ExprTree, node_count as _nc

        return ExprTree(root=root, node_count=_nc(root))

    def _query_tree_with_consts(self, names: list[str]):
        """Build a simple tree containing LConst leaves for each name."""
        from Poule.models.labels import LConst, LApp

        if len(names) == 0:
            from Poule.models.labels import LRel

            return self._tree(self._leaf(LRel(0)))
        if len(names) == 1:
            return self._tree(self._leaf(LConst(names[0])))
        # Chain LApp nodes for multiple constants
        node = self._leaf(LConst(names[0]))
        for name in names[1:]:
            node = self._node(LApp(), [node, self._leaf(LConst(name))])
        return self._tree(node)

    def test_correct_scores_for_all_candidates(self):
        """Rank multiple candidates with known overlaps."""
        query = self._query_tree_with_consts(["Nat.add", "Nat.mul"])
        candidates = [1, 2, 3]
        decl_symbols = {
            1: {"Nat.add", "Nat.mul"},          # identical -> 1.0
            2: {"Nat.add", "Nat.sub"},          # 1 of 3 -> 1/3
            3: {"Bool.andb", "Bool.orb"},       # no overlap -> 0.0
        }
        results = self.const_jaccard_rank(query, candidates, decl_symbols)
        scores = {decl_id: score for decl_id, score in results}
        assert scores[1] == pytest.approx(1.0)
        assert scores[2] == pytest.approx(1.0 / 3.0)
        assert scores[3] == pytest.approx(0.0)

    def test_empty_query_constants_all_zero(self):
        """Query tree with no constants -> all candidates score 0.0."""
        query = self._query_tree_with_consts([])
        candidates = [1, 2]
        decl_symbols = {
            1: {"Nat.add"},
            2: {"Bool.andb"},
        }
        results = self.const_jaccard_rank(query, candidates, decl_symbols)
        for decl_id, score in results:
            assert score == 0.0, f"Expected 0.0 for decl {decl_id}, got {score}"

    def test_missing_candidate_in_declaration_symbols(self):
        """Candidate not in declaration_symbols -> score 0.0."""
        query = self._query_tree_with_consts(["Nat.add"])
        candidates = [1, 99]  # 99 is missing from decl_symbols
        decl_symbols = {
            1: {"Nat.add"},
        }
        results = self.const_jaccard_rank(query, candidates, decl_symbols)
        scores = {decl_id: score for decl_id, score in results}
        assert scores[1] == pytest.approx(1.0)
        assert scores[99] == 0.0

    def test_returns_pair_for_every_candidate(self):
        """Output length equals input candidate count."""
        query = self._query_tree_with_consts(["Nat.add"])
        candidates = [10, 20, 30, 40]
        decl_symbols = {
            10: {"Nat.add"},
            20: {"Nat.mul"},
            30: set(),
            40: {"Nat.add", "Nat.sub"},
        }
        results = self.const_jaccard_rank(query, candidates, decl_symbols)
        assert len(results) == len(candidates)
        result_ids = [decl_id for decl_id, _ in results]
        for cid in candidates:
            assert cid in result_ids

    def test_empty_candidate_list(self):
        """No candidates -> empty result list."""
        query = self._query_tree_with_consts(["Nat.add"])
        results = self.const_jaccard_rank(query, [], {})
        assert results == []

    def test_result_is_list_of_tuples(self):
        """Each result element is a (decl_id, score) pair."""
        query = self._query_tree_with_consts(["Nat.add"])
        candidates = [1]
        decl_symbols = {1: {"Nat.add"}}
        results = self.const_jaccard_rank(query, candidates, decl_symbols)
        assert len(results) == 1
        decl_id, score = results[0]
        assert decl_id == 1
        assert isinstance(score, float)
