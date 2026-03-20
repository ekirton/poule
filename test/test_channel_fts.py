"""TDD tests for the FTS5 channel — written before implementation.

Tests target the public API defined in specification/channel-fts.md:
  - fts_query(raw_query) -> str
  - fts_search(query, limit, reader) -> list of results with normalized scores

Implementation will live in src/poule/channels/fts.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from Poule.channels.fts import fts_query, fts_search


# ---------------------------------------------------------------------------
# fts_query: Query classification and preprocessing
# ---------------------------------------------------------------------------


class TestFtsQueryQualifiedName:
    """Rule 1: query contains '.' -> split on '.', join with AND."""

    def test_simple_qualified_name(self):
        result = fts_query("Coq.Arith.PeanoNat")
        assert result == "Coq AND Arith AND PeanoNat"

    def test_long_qualified_name(self):
        result = fts_query("Coq.Arith.PeanoNat.Nat.add")
        terms = result.split(" AND ")
        assert len(terms) == 5
        assert terms == ["Coq", "Arith", "PeanoNat", "Nat", "add"]


class TestFtsQueryIdentifier:
    """Rule 2: query contains '_' and no spaces -> split on '_', join with AND."""

    def test_two_part_identifier(self):
        result = fts_query("nat_add")
        assert result == "nat AND add"

    def test_three_part_identifier(self):
        result = fts_query("nat_add_comm")
        assert result == "nat AND add AND comm"


class TestFtsQueryFallback:
    """Rule 3: everything else -> split on whitespace, join with OR."""

    def test_two_words(self):
        result = fts_query("addition commutative")
        assert result == "addition OR commutative"

    def test_single_word(self):
        result = fts_query("nat")
        assert result == "nat"


# ---------------------------------------------------------------------------
# fts_query: Classification priority
# ---------------------------------------------------------------------------


class TestFtsQueryClassificationPriority:
    """Rules are evaluated in priority order; first match wins."""

    def test_dot_beats_underscore(self):
        """'Coq.nat_add' contains both '.' and '_'; Rule 1 wins."""
        result = fts_query("Coq.nat_add")
        # Rule 1: split on '.', producing "Coq" and "nat_add", joined with AND.
        terms = result.split(" AND ")
        assert terms[0] == "Coq"
        assert "nat_add" in terms[1]  # kept as single token (not split on _)
        assert "OR" not in result

    def test_underscore_with_space_falls_to_rule3(self):
        """'nat_add comm' has '_' and a space; Rule 2 requires NO spaces, so Rule 3 applies."""
        result = fts_query("nat_add comm")
        assert "OR" in result


# ---------------------------------------------------------------------------
# fts_query: Token safety limit
# ---------------------------------------------------------------------------


class TestFtsQueryTokenLimit:
    """Tokens beyond 20 are dropped."""

    def test_excess_tokens_dropped(self):
        # 25 dot-separated segments -> only 20 kept
        segments = [f"seg{i}" for i in range(25)]
        raw = ".".join(segments)
        result = fts_query(raw)
        terms = result.split(" AND ")
        assert len(terms) == 20


# ---------------------------------------------------------------------------
# fts_query: FTS5 special character escaping
# ---------------------------------------------------------------------------


class TestFtsQuerySpecialCharEscaping:
    """Tokens containing FTS5 special characters are wrapped in double quotes."""

    def test_asterisk_quoted(self):
        # A qualified-name token containing '*' must be double-quoted.
        result = fts_query("Coq.add*helper")
        # The token "add*helper" should appear wrapped in double quotes.
        assert '"add*helper"' in result

    def test_parenthesis_quoted(self):
        result = fts_query("Coq.foo(bar)")
        assert '"foo(bar)"' in result

    @pytest.mark.parametrize(
        "char",
        ["*", '"', "(", ")", "+", "-", ":", "^", "{", "}", ",", "="],
        ids=lambda c: f"char_{ord(c):02x}",
    )
    def test_every_special_char_quoted(self, char):
        """Every FTS5 special character must cause its token to be quoted."""
        token = f"foo{char}bar"
        result = fts_query(token)
        assert f'"{token}"' in result

    def test_comma_in_fallback_path(self):
        """Comma in a whitespace-split (fallback) query must be quoted.

        Coq type expressions hit the fallback path: 'forall (A : Type), ...'
        produces tokens like 'Type),' which must be quoted.
        """
        result = fts_query("Type), list")
        # 'Type),' contains both ')' and ',' — must be quoted
        assert '"Type),"' in result
        assert "list" in result

    def test_equals_in_fallback_path(self):
        """Equals sign in a whitespace-split query must be quoted.

        Coq equality expressions like 'A = B' produce a bare '=' token.
        """
        result = fts_query("A = B")
        assert '"="' in result

    def test_coq_type_expression_all_specials_quoted(self):
        """Full Coq type expression: every token with a special char is quoted."""
        result = fts_query("forall (A : Type), list A -> nat")
        # No unquoted special characters should survive outside of quotes
        tokens = result.split(" OR ")
        for token in tokens:
            stripped = token.strip()
            if stripped.startswith('"') and stripped.endswith('"'):
                continue  # quoted — safe
            # Unquoted tokens must contain no special characters
            for ch in '*"()+\\-:^{},=':
                assert ch not in stripped, (
                    f"Unquoted token {stripped!r} contains special char {ch!r}"
                )


# ---------------------------------------------------------------------------
# fts_query / fts_search: Empty query
# ---------------------------------------------------------------------------


class TestFtsQueryEmpty:
    """Empty or whitespace-only queries produce no results."""

    def test_empty_string_query(self):
        result = fts_query("")
        assert result == ""

    def test_whitespace_only_query(self):
        result = fts_query("   ")
        assert result == ""

    def test_fts_search_empty_query_returns_empty(self):
        reader = MagicMock()
        results = fts_search("", limit=10, reader=reader)
        assert results == []


# ---------------------------------------------------------------------------
# fts_search: BM25 normalization with mock reader
# ---------------------------------------------------------------------------


class TestFtsSearchBM25Normalization:
    """BM25 scores are negated, divided by max abs score, and clamped to [0,1]."""

    def test_scores_normalized_zero_to_one(self):
        """Results returned by the reader have raw BM25 (negative) scores.
        fts_search must normalize them into [0, 1]."""
        reader = MagicMock()
        # Simulate reader returning rows with negative BM25 scores
        # (lower = more relevant in raw BM25).
        reader.search_fts.return_value = [
            {"id": 1, "name": "Nat.add", "score": -10.0},
            {"id": 2, "name": "Nat.mul", "score": -5.0},
            {"id": 3, "name": "Nat.sub", "score": -2.0},
        ]

        results = fts_search("Nat", limit=10, reader=reader)

        assert len(results) == 3
        for r in results:
            assert 0.0 <= r.score <= 1.0

        # The most relevant item (raw -10.0, highest abs) should get score 1.0
        assert results[0].score == 1.0

    def test_all_equal_scores_normalize_to_one(self):
        """When all BM25 scores are identical, every result gets 1.0."""
        reader = MagicMock()
        reader.search_fts.return_value = [
            {"id": 1, "name": "A", "score": -5.0},
            {"id": 2, "name": "B", "score": -5.0},
            {"id": 3, "name": "C", "score": -5.0},
        ]

        results = fts_search("test", limit=10, reader=reader)

        assert len(results) == 3
        for r in results:
            assert r.score == 1.0
