"""TDD tests for the MePo symbol-relevance channel.

Tests written before implementation exists.
Implementation target: src/poule/channels/mepo.py
Specification: specification/channel-mepo.md
"""

from __future__ import annotations

import math

import pytest


# ---------------------------------------------------------------------------
# symbol_weight
# ---------------------------------------------------------------------------

class TestSymbolWeight:
    """Tests for symbol_weight(freq) -> 1.0 + 2.0 / log2(freq + 1)."""

    def test_freq_1_returns_3(self):
        from Poule.channels.mepo import symbol_weight

        # 1.0 + 2.0 / log2(1 + 1) = 1.0 + 2.0 / 1.0 = 3.0
        assert symbol_weight(1) == pytest.approx(3.0)

    def test_freq_1000_approximately_1_2(self):
        from Poule.channels.mepo import symbol_weight

        expected = 1.0 + 2.0 / math.log2(1001)
        assert symbol_weight(1000) == pytest.approx(expected)
        # Sanity: should be close to 1.2
        assert 1.1 < symbol_weight(1000) < 1.3

    def test_large_freq_approaches_1(self):
        from Poule.channels.mepo import symbol_weight

        w = symbol_weight(1_000_000)
        assert w > 1.0
        assert w < 1.2  # 1.0 + 2.0 / log2(1_000_001) ≈ 1.1003


# ---------------------------------------------------------------------------
# Missing symbol handling — freq=1 at query time
# ---------------------------------------------------------------------------

class TestMissingSymbolFrequency:
    """When a symbol is absent from symbol_frequencies, treat freq as 1."""

    def test_missing_symbol_uses_freq_1(self):
        from Poule.channels.mepo import mepo_relevance

        # Candidate has a single symbol "unknown" not in freq map.
        # Working set contains "unknown".
        # Weight for freq=1 is 3.0; overlap == total => relevance == 1.0.
        candidate_symbols = {"unknown"}
        working_set = {"unknown"}
        symbol_frequencies: dict[str, int] = {}  # empty — symbol missing

        result = mepo_relevance(candidate_symbols, working_set, symbol_frequencies)
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# mepo_relevance
# ---------------------------------------------------------------------------

class TestMepoRelevance:
    """Tests for mepo_relevance(candidate_symbols, working_set, symbol_frequencies)."""

    def test_full_overlap_returns_1(self):
        from Poule.channels.mepo import mepo_relevance

        syms = {"A", "B", "C"}
        freq = {"A": 10, "B": 20, "C": 30}
        assert mepo_relevance(syms, syms, freq) == pytest.approx(1.0)

    def test_no_overlap_returns_0(self):
        from Poule.channels.mepo import mepo_relevance

        candidate = {"A", "B"}
        working = {"X", "Y"}
        freq = {"A": 5, "B": 5, "X": 5, "Y": 5}
        assert mepo_relevance(candidate, working, freq) == pytest.approx(0.0)

    def test_partial_overlap_computed_correctly(self):
        from Poule.channels.mepo import mepo_relevance, symbol_weight

        candidate = {"A", "B", "C"}
        working = {"A", "C"}
        freq = {"A": 1, "B": 10, "C": 100}

        w_a = symbol_weight(freq["A"])
        w_b = symbol_weight(freq["B"])
        w_c = symbol_weight(freq["C"])

        expected = (w_a + w_c) / (w_a + w_b + w_c)
        assert mepo_relevance(candidate, working, freq) == pytest.approx(expected)

    def test_empty_candidate_returns_0(self):
        from Poule.channels.mepo import mepo_relevance

        result = mepo_relevance(set(), {"A", "B"}, {"A": 1, "B": 1})
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# mepo_select
# ---------------------------------------------------------------------------

def _simple_index():
    """Build a small test universe for mepo_select tests.

    Declarations:
      1: {A, B}       -- shares A with query
      2: {B, C}       -- shares B with decl 1 (transitive)
      3: {X}          -- unrelated
      4: {A, C}       -- shares A with query, C with decl 2

    Query symbols: {A}
    """
    inverted_index: dict[str, set[int]] = {
        "A": {1, 4},
        "B": {1, 2},
        "C": {2, 4},
        "X": {3},
    }
    symbol_frequencies: dict[str, int] = {"A": 2, "B": 2, "C": 2, "X": 1}
    declaration_symbols: dict[int, set[str]] = {
        1: {"A", "B"},
        2: {"B", "C"},
        3: {"X"},
        4: {"A", "C"},
    }
    return inverted_index, symbol_frequencies, declaration_symbols


class TestMepoSelect:
    """Tests for mepo_select iterative selection."""

    def test_single_round_selects_relevant_declarations(self):
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()

        # With p=0.0 (accept all) and max_rounds=1, should find decls
        # reachable from {A} in one step: decls 1 and 4.
        results = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=1)
        selected_ids = {did for did, _ in results}
        assert 1 in selected_ids
        assert 4 in selected_ids
        # Decl 2 requires going through B (from decl 1), so not reachable in round 1
        # unless B is also in query. Decl 3 is unrelated.
        assert 3 not in selected_ids

    def test_iterative_expansion_discovers_transitive_matches(self):
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()

        # With p=0.0 (accept everything) and enough rounds, decl 2 should be
        # discovered via B (from decl 1 selected in round 1).
        results = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=5)
        selected_ids = {did for did, _ in results}
        assert 2 in selected_ids

    def test_empty_query_returns_empty(self):
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()
        results = mepo_select(set(), inv, freq, decl_syms)
        assert results == []

    def test_threshold_decay(self):
        """With high initial p, only high-relevance decls pass round 1.
        After decay, lower-relevance decls can pass in later rounds."""
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()

        # p=1.0 means only perfect overlap passes round 1.
        # After one round, t = 1.0 / 2.4 ≈ 0.417, allowing more through.
        high_t = mepo_select({"A"}, inv, freq, decl_syms, p=1.0, c=2.4, max_rounds=5)
        low_t = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=5)

        # Low threshold should select at least as many as high threshold.
        assert len(low_t) >= len(high_t)

    def test_early_stop_when_no_new_candidates(self):
        """If a round selects nothing new, iteration stops."""
        from Poule.channels.mepo import mepo_select

        # Only decl 3 is reachable from X, and it will be selected in round 1.
        # Round 2 won't find anything new (X is the only symbol), so it stops.
        inv, freq, decl_syms = _simple_index()
        results = mepo_select({"X"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=5)
        selected_ids = {did for did, _ in results}
        assert selected_ids == {3}

    def test_max_rounds_limit_respected(self):
        """mepo_select must not exceed max_rounds iterations."""
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()

        # With max_rounds=1 and p=0.0, we only get round-1 results.
        r1 = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=1)
        r5 = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=5)

        # More rounds can discover more (transitive) declarations.
        assert len(r5) >= len(r1)
        # Round 1 should not have decl 2 (only reachable transitively).
        r1_ids = {did for did, _ in r1}
        assert 2 not in r1_ids

    def test_batch_expansion_not_within_round(self):
        """S is updated only between rounds, not during scoring within a round.

        If S were updated within a round, decl 2 could be found in round 1
        because decl 1's symbols (B) would be added to S mid-round, making
        decl 2 reachable. With batch expansion, decl 2 is NOT reachable in
        round 1 — it requires round 2.
        """
        from Poule.channels.mepo import mepo_select

        # Custom universe where within-round expansion would change results.
        # Query: {A}
        # Decl 10: {A, B} — reachable from A
        # Decl 20: {B}    — reachable from B only
        inv = {"A": {10}, "B": {10, 20}}
        freq = {"A": 1, "B": 2}
        decl_syms = {10: {"A", "B"}, 20: {"B"}}

        # Round 1 with p=0.0: candidates reachable from S={A} are {10}.
        # If batch: S is only updated to {A,B} AFTER round 1 scoring.
        # Decl 20 is not a candidate in round 1 (only reachable via B).
        r1 = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=1)
        r1_ids = {did for did, _ in r1}
        assert r1_ids == {10}
        # With 2 rounds, decl 20 should appear.
        r2 = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=2)
        r2_ids = {did for did, _ in r2}
        assert r2_ids == {10, 20}

    def test_results_sorted_descending_by_relevance(self):
        from Poule.channels.mepo import mepo_select

        inv, freq, decl_syms = _simple_index()
        results = mepo_select({"A"}, inv, freq, decl_syms, p=0.0, c=2.4, max_rounds=5)

        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# extract_consts
# ---------------------------------------------------------------------------

class TestExtractConsts:
    """Tests for extract_consts(tree) -> set[str]."""

    def test_extracts_lconst_lind_lconstruct(self, make_leaf, make_node, make_tree):
        from Poule.channels.mepo import extract_consts
        from Poule.models.labels import (
            LApp, LConst, LInd, LConstruct, LRel,
        )

        # Tree: LApp(LApp(LConst("Nat.add"), LInd("Nat")), LConstruct("Bool", 0))
        tree = make_tree(
            make_node(LApp(), [
                make_node(LApp(), [
                    make_leaf(LConst("Nat.add")),
                    make_leaf(LInd("Nat")),
                ]),
                make_leaf(LConstruct("Bool", 0)),
            ])
        )

        result = extract_consts(tree)
        assert result == {"Nat.add", "Nat", "Bool"}

    def test_lconstruct_contributes_parent_inductive_fqn(self, make_leaf, make_tree):
        from Poule.channels.mepo import extract_consts
        from Poule.models.labels import LConstruct

        # LConstruct stores the parent inductive FQN, not the constructor name.
        tree = make_tree(make_leaf(LConstruct("Stdlib.Init.Datatypes.bool", 1)))
        result = extract_consts(tree)
        assert "Stdlib.Init.Datatypes.bool" in result

    def test_tree_with_no_constants_returns_empty_set(
        self, make_leaf, make_node, make_tree,
    ):
        from Poule.channels.mepo import extract_consts
        from Poule.models.labels import LProd, LSort, LRel
        from Poule.models.enums import SortKind

        tree = make_tree(
            make_node(LProd(), [
                make_leaf(LSort(SortKind.PROP)),
                make_leaf(LRel(0)),
            ])
        )
        result = extract_consts(tree)
        assert result == set()

    def test_duplicates_collapsed_to_set(self, make_leaf, make_node, make_tree):
        from Poule.channels.mepo import extract_consts
        from Poule.models.labels import LApp, LConst

        # Same constant appears twice in the tree.
        tree = make_tree(
            make_node(LApp(), [
                make_leaf(LConst("Nat.add")),
                make_leaf(LConst("Nat.add")),
            ])
        )
        result = extract_consts(tree)
        assert result == {"Nat.add"}
        assert isinstance(result, set)
