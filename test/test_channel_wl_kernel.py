"""TDD tests for the WL kernel screening channel.

Tests are written before implementation exists. They will fail with ImportError
until src/wily_rooster/channels/wl_kernel.py is implemented.

Specification: specification/channel-wl-kernel.md
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Import helpers — will fail until implementation exists (TDD)
# ---------------------------------------------------------------------------

def _import_wl():
    from wily_rooster.channels.wl_kernel import (
        wl_histogram,
        wl_cosine,
        size_filter,
        wl_screen,
        compute_wl_vector,
    )
    return wl_histogram, wl_cosine, size_filter, wl_screen, compute_wl_vector


HEX32_RE = re.compile(r"^[0-9a-f]{32}$")


# ===================================================================
# Helper: build trees using conftest fixtures
# ===================================================================

@pytest.fixture
def single_node_tree(make_leaf, make_tree):
    """A tree with exactly one leaf node."""
    leaf = make_leaf("Rel")
    return make_tree(leaf)


@pytest.fixture
def three_node_tree(make_node, make_leaf, make_tree):
    """LProd(LSort_PROP, LRel_0) — 3-node tree mirroring spec example."""
    child_a = make_leaf("Prop")
    child_b = make_leaf("Rel")
    root = make_node("Prod", [child_a, child_b])
    return make_tree(root)


@pytest.fixture
def five_node_tree(make_node, make_leaf, make_tree):
    """LApp(LApp(LConst, LRel), LRel) — 5-node tree from conftest sample_app_tree shape."""
    inner_left = make_leaf("C:Coq.Init.Nat.add")
    inner_right = make_leaf("Rel")
    inner = make_node("App", [inner_left, inner_right])
    outer_right = make_leaf("Rel")
    root = make_node("App", [inner, outer_right])
    return make_tree(root)


@pytest.fixture
def different_tree(make_node, make_leaf, make_tree):
    """A structurally different tree from three_node_tree."""
    child_a = make_leaf("Lam")
    child_b = make_leaf("App")
    child_c = make_leaf("Fix")
    root = make_node("Case", [child_a, child_b, child_c])
    return make_tree(root)


# ===================================================================
# 1-5: wl_histogram tests
# ===================================================================

class TestWlHistogram:
    """Tests for wl_histogram(tree, h) -> dict[str, int]."""

    def test_returns_dict_with_hex32_keys(self, three_node_tree):
        """1. wl_histogram returns dict with 32-char hex keys."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(three_node_tree, h=3)
        assert isinstance(hist, dict)
        for key in hist:
            assert HEX32_RE.match(key), f"Key {key!r} is not 32-char lowercase hex"

    def test_single_node_tree_one_entry(self, single_node_tree):
        """2. wl_histogram on single-node tree -> 1 entry with count 1."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(single_node_tree, h=0)
        assert len(hist) == 1
        assert list(hist.values()) == [1]

    def test_multi_node_tree_correct_entries(self, three_node_tree):
        """3. wl_histogram on multi-node tree -> correct number of entries."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(three_node_tree, h=1)
        assert isinstance(hist, dict)
        # 3 nodes * (1+1) iterations = 6 total labels; histogram has <= 6 entries
        total_count = sum(hist.values())
        assert total_count == 6
        assert all(v >= 1 for v in hist.values())

    def test_identical_trees_identical_histograms(self, make_leaf, make_node, make_tree):
        """4. Identical trees produce identical histograms."""
        wl_histogram, *_ = _import_wl()

        def build():
            a = make_leaf("Prop")
            b = make_leaf("Rel")
            r = make_node("Prod", [a, b])
            return make_tree(r)

        tree_a = build()
        tree_b = build()
        assert wl_histogram(tree_a, h=3) == wl_histogram(tree_b, h=3)

    def test_different_trees_different_histograms(self, three_node_tree, different_tree):
        """5. Different trees produce different histograms."""
        wl_histogram, *_ = _import_wl()
        hist_a = wl_histogram(three_node_tree, h=3)
        hist_b = wl_histogram(different_tree, h=3)
        assert hist_a != hist_b


# ===================================================================
# 6-10: wl_cosine tests
# ===================================================================

class TestWlCosine:
    """Tests for wl_cosine(hist_a, hist_b) -> float."""

    def test_identical_histograms_return_one(self):
        """6. wl_cosine of identical histograms = 1.0."""
        _, wl_cosine, *_ = _import_wl()
        hist = {"a" * 32: 3, "b" * 32: 5}
        assert wl_cosine(hist, hist) == pytest.approx(1.0)

    def test_disjoint_histograms_return_zero(self):
        """7. wl_cosine of disjoint histograms = 0.0."""
        _, wl_cosine, *_ = _import_wl()
        hist_a = {"a" * 32: 3}
        hist_b = {"b" * 32: 5}
        assert wl_cosine(hist_a, hist_b) == pytest.approx(0.0)

    def test_empty_histogram_returns_zero(self):
        """8. wl_cosine of empty histogram = 0.0."""
        _, wl_cosine, *_ = _import_wl()
        assert wl_cosine({}, {"a" * 32: 1}) == pytest.approx(0.0)
        assert wl_cosine({"a" * 32: 1}, {}) == pytest.approx(0.0)
        assert wl_cosine({}, {}) == pytest.approx(0.0)

    def test_symmetry(self):
        """9. wl_cosine symmetry: cosine(a,b) == cosine(b,a)."""
        _, wl_cosine, *_ = _import_wl()
        hist_a = {"a" * 32: 2, "b" * 32: 3}
        hist_b = {"a" * 32: 1, "c" * 32: 4}
        assert wl_cosine(hist_a, hist_b) == pytest.approx(wl_cosine(hist_b, hist_a))

    def test_result_in_unit_interval(self):
        """10. wl_cosine result in [0, 1]."""
        _, wl_cosine, *_ = _import_wl()
        hist_a = {"a" * 32: 2, "b" * 32: 3, "c" * 32: 1}
        hist_b = {"a" * 32: 1, "b" * 32: 1, "d" * 32: 7}
        score = wl_cosine(hist_a, hist_b)
        assert 0.0 <= score <= 1.0

    def test_proportionally_identical_return_one(self):
        """Proportionally identical histograms (scaled) produce cosine = 1.0."""
        _, wl_cosine, *_ = _import_wl()
        hist_a = {"a" * 32: 2, "b" * 32: 4}
        hist_b = {"a" * 32: 1, "b" * 32: 2}
        assert wl_cosine(hist_a, hist_b) == pytest.approx(1.0)

    def test_no_nan(self):
        """Cosine never produces NaN."""
        _, wl_cosine, *_ = _import_wl()
        import math
        result = wl_cosine({}, {})
        assert not math.isnan(result)


# ===================================================================
# 11-15: size_filter tests
# ===================================================================

class TestSizeFilter:
    """Tests for size_filter(query_nc, cand_nc) -> bool."""

    def test_small_query_passes_within_threshold(self):
        """11. query=30, cand=35 -> True (35/30=1.17 < 1.2)."""
        *_, size_filter, _, _ = _import_wl()
        assert size_filter(30, 35) is True

    def test_small_query_rejects_exceeding_threshold(self):
        """12. query=30, cand=40 -> False (40/30=1.33 > 1.2)."""
        *_, size_filter, _, _ = _import_wl()
        assert size_filter(30, 40) is False

    def test_large_query_passes_within_threshold(self):
        """13. query=700, cand=900 -> True (900/700=1.29 < 1.8)."""
        *_, size_filter, _, _ = _import_wl()
        assert size_filter(700, 900) is True

    def test_large_query_rejects_exceeding_threshold(self):
        """14. query=700, cand=1300 -> False (1300/700=1.86 > 1.8)."""
        *_, size_filter, _, _ = _import_wl()
        assert size_filter(700, 1300) is False

    def test_equal_sizes_pass(self):
        """15. Equal sizes always pass."""
        *_, size_filter, _, _ = _import_wl()
        assert size_filter(50, 50) is True
        assert size_filter(700, 700) is True
        assert size_filter(1, 1) is True

    def test_boundary_599_uses_strict_threshold(self):
        """query_nc=599 uses the 1.2 threshold (< 600)."""
        *_, size_filter, _, _ = _import_wl()
        # 599 * 1.2 = 718.8; candidate 719 has ratio 719/599 = 1.200... > 1.2
        assert size_filter(599, 719) is False
        # candidate 718: 718/599 = 1.1986... < 1.2
        assert size_filter(599, 718) is True

    def test_boundary_600_uses_relaxed_threshold(self):
        """query_nc=600 uses the 1.8 threshold (>= 600)."""
        *_, size_filter, _, _ = _import_wl()
        # 600 * 1.8 = 1080; candidate 1080 has ratio 1.8 exactly -> passes
        assert size_filter(600, 1080) is True
        # candidate 1081 has ratio 1081/600 = 1.8017 > 1.8
        assert size_filter(600, 1081) is False

    def test_ratio_exactly_at_threshold_passes(self):
        """Ratio exactly equal to threshold passes (reject is strictly greater)."""
        *_, size_filter, _, _ = _import_wl()
        # query=10, cand=12: ratio 12/10 = 1.2 exactly -> passes
        assert size_filter(10, 12) is True

    def test_zero_query_does_not_raise(self):
        """query_nc=0 does not raise (denominator guarded by max(..., 1))."""
        *_, size_filter, _, _ = _import_wl()
        # Should not raise; exact result depends on implementation guard
        result = size_filter(0, 10)
        assert isinstance(result, bool)

    def test_small_query_reverse_ratio(self):
        """Size filter uses max/min ratio, so direction does not matter."""
        *_, size_filter, _, _ = _import_wl()
        # query=40, cand=30: max/min = 40/30 = 1.33 > 1.2 -> False
        assert size_filter(40, 30) is False


# ===================================================================
# 16-19: wl_screen tests
# ===================================================================

class TestWlScreen:
    """Tests for wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n)."""

    def _make_lib(self, entries):
        """Build lib_hists and lib_ncs from a list of (decl_id, hist, nc)."""
        lib_hists = {did: hist for did, hist, _ in entries}
        lib_ncs = {did: nc for did, _, nc in entries}
        return lib_hists, lib_ncs

    def test_returns_up_to_n_sorted_descending(self):
        """16. wl_screen returns up to n candidates sorted by score descending."""
        _, wl_cosine, _, wl_screen, _ = _import_wl()
        query_hist = {"a" * 32: 3, "b" * 32: 2}
        query_nc = 5
        entries = [
            (1, {"a" * 32: 3, "b" * 32: 2}, 5),   # identical -> 1.0
            (2, {"a" * 32: 1, "b" * 32: 1}, 5),   # similar
            (3, {"a" * 32: 1}, 5),                  # partial overlap
            (4, {"c" * 32: 1}, 5),                  # disjoint -> 0.0
        ]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n=3)
        assert len(results) <= 3
        # Scores are in descending order
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_filters_by_size(self):
        """17. wl_screen filters by size."""
        _, _, _, wl_screen, _ = _import_wl()
        query_hist = {"a" * 32: 3}
        query_nc = 30
        entries = [
            (1, {"a" * 32: 3}, 30),   # same size -> passes
            (2, {"a" * 32: 3}, 100),  # ratio 100/30=3.33 > 1.2 -> filtered
        ]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n=500)
        result_ids = [did for did, _ in results]
        assert 1 in result_ids
        assert 2 not in result_ids

    def test_empty_query_histogram_returns_empty(self):
        """18. wl_screen with empty query histogram -> empty list."""
        _, _, _, wl_screen, _ = _import_wl()
        entries = [(1, {"a" * 32: 3}, 10)]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen({}, 10, lib_hists, lib_ncs, n=500)
        assert results == []

    def test_empty_library_returns_empty(self):
        """19. wl_screen with empty library -> empty list."""
        _, _, _, wl_screen, _ = _import_wl()
        results = wl_screen({"a" * 32: 1}, 10, {}, {}, n=500)
        assert results == []

    def test_all_filtered_returns_empty(self):
        """wl_screen returns empty when all candidates are size-filtered."""
        _, _, _, wl_screen, _ = _import_wl()
        query_hist = {"a" * 32: 3}
        query_nc = 10
        entries = [
            (1, {"a" * 32: 3}, 100),  # ratio 10 > 1.2
            (2, {"a" * 32: 3}, 200),  # ratio 20 > 1.2
        ]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n=500)
        assert results == []

    def test_scores_in_unit_interval(self):
        """All returned scores are in [0.0, 1.0]."""
        _, _, _, wl_screen, _ = _import_wl()
        query_hist = {"a" * 32: 2, "b" * 32: 1}
        query_nc = 10
        entries = [
            (1, {"a" * 32: 3, "b" * 32: 2}, 10),
            (2, {"a" * 32: 1, "c" * 32: 5}, 10),
        ]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n=500)
        for _, score in results:
            assert 0.0 <= score <= 1.0

    def test_returns_decl_id_score_tuples(self):
        """Results contain (decl_id, score) tuples."""
        _, _, _, wl_screen, _ = _import_wl()
        query_hist = {"a" * 32: 1}
        query_nc = 10
        entries = [(42, {"a" * 32: 1}, 10)]
        lib_hists, lib_ncs = self._make_lib(entries)
        results = wl_screen(query_hist, query_nc, lib_hists, lib_ncs, n=500)
        assert len(results) == 1
        decl_id, score = results[0]
        assert decl_id == 42
        assert isinstance(score, float)


# ===================================================================
# 20: compute_wl_vector alias test
# ===================================================================

class TestComputeWlVector:
    """Tests for compute_wl_vector — alias for wl_histogram."""

    def test_is_alias_for_wl_histogram(self, three_node_tree):
        """20. compute_wl_vector is alias for wl_histogram."""
        wl_histogram, _, _, _, compute_wl_vector = _import_wl()
        h = 3
        assert compute_wl_vector(three_node_tree, h) == wl_histogram(three_node_tree, h)


# ===================================================================
# 21: h-value consistency
# ===================================================================

class TestHValueConsistency:
    """Tests verifying h-value consistency between query and library."""

    def test_different_h_produces_different_histograms(self, three_node_tree):
        """21. Different h values produce different histograms — must be consistent."""
        wl_histogram, *_ = _import_wl()
        hist_h1 = wl_histogram(three_node_tree, h=1)
        hist_h3 = wl_histogram(three_node_tree, h=3)
        # Different h values must produce different histograms for non-trivial trees
        assert hist_h1 != hist_h3

    def test_h_zero_no_refinement(self, single_node_tree):
        """h=0 produces only iteration-0 labels (no refinement)."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(single_node_tree, h=0)
        # single node, h=0: exactly 1 label occurrence
        assert sum(hist.values()) == 1

    def test_h_increases_label_count(self, three_node_tree):
        """Higher h produces more total label occurrences."""
        wl_histogram, *_ = _import_wl()
        hist_h0 = wl_histogram(three_node_tree, h=0)
        hist_h1 = wl_histogram(three_node_tree, h=1)
        # 3 nodes at h=0: 3 labels; at h=1: 6 labels
        assert sum(hist_h0.values()) == 3
        assert sum(hist_h1.values()) == 6


# ===================================================================
# Additional edge-case tests
# ===================================================================

class TestWlHistogramEdgeCases:
    """Additional edge-case coverage for wl_histogram."""

    def test_all_values_positive(self, five_node_tree):
        """Histogram values are all >= 1 (sparse, no zero entries)."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(five_node_tree, h=3)
        assert all(v >= 1 for v in hist.values())

    def test_deterministic(self, three_node_tree):
        """Same tree and h always produce the same histogram."""
        wl_histogram, *_ = _import_wl()
        hist_a = wl_histogram(three_node_tree, h=3)
        hist_b = wl_histogram(three_node_tree, h=3)
        assert hist_a == hist_b

    def test_single_node_h1_two_labels(self, single_node_tree):
        """Single-node tree at h=1 produces 2 total label occurrences."""
        wl_histogram, *_ = _import_wl()
        hist = wl_histogram(single_node_tree, h=1)
        assert sum(hist.values()) == 2
