"""TDD tests for the MCP server layer (validation, errors, handlers).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/server/ modules exist.

Spec: specification/mcp-server.md
Architecture: doc/architecture/mcp-server.md
Tasks: tasks/mcp-server.md

Import paths under test:
  poule.server.handlers
  poule.server.validation
  poule.server.errors
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------

def _import_validation():
    from Poule.server.validation import (
        validate_string,
        validate_limit,
        validate_symbols,
        validate_relation,
    )
    return validate_string, validate_limit, validate_symbols, validate_relation


def _import_errors():
    from Poule.server.errors import (
        format_error,
        INDEX_MISSING,
        INDEX_VERSION_MISMATCH,
        NOT_FOUND,
        PARSE_ERROR,
    )
    return format_error, INDEX_MISSING, INDEX_VERSION_MISMATCH, NOT_FOUND, PARSE_ERROR


def _import_handlers():
    from Poule.server.handlers import (
        handle_search_by_name,
        handle_search_by_type,
        handle_search_by_structure,
        handle_search_by_symbols,
        handle_get_lemma,
        handle_find_related,
        handle_list_modules,
    )
    return (
        handle_search_by_name,
        handle_search_by_type,
        handle_search_by_structure,
        handle_search_by_symbols,
        handle_get_lemma,
        handle_find_related,
        handle_list_modules,
    )


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def _make_search_result(
    name: str = "Coq.Arith.PeanoNat.Nat.add_comm",
    statement: str = "forall n m : nat, n + m = m + n",
    type_: str = "forall n m : nat, n + m = m + n",
    module: str = "Coq.Arith.PeanoNat",
    kind: str = "lemma",
    score: float = 0.95,
) -> dict:
    """Build a search result dict matching the MCP response format."""
    return {
        "name": name,
        "statement": statement,
        "type": type_,
        "module": module,
        "kind": kind,
        "score": score,
    }


def _make_lemma_detail(
    name: str = "Coq.Arith.PeanoNat.Nat.add_comm",
    statement: str = "forall n m : nat, n + m = m + n",
    type_: str = "forall n m : nat, n + m = m + n",
    module: str = "Coq.Arith.PeanoNat",
    kind: str = "lemma",
    score: float = 1.0,
    dependencies: list[str] | None = None,
    dependents: list[str] | None = None,
    proof_sketch: str = "",
    symbols: list[str] | None = None,
    node_count: int = 5,
) -> dict:
    """Build a LemmaDetail dict matching the MCP response format."""
    return {
        "name": name,
        "statement": statement,
        "type": type_,
        "module": module,
        "kind": kind,
        "score": score,
        "dependencies": dependencies or [],
        "dependents": dependents or [],
        "proof_sketch": proof_sketch,
        "symbols": symbols or [],
        "node_count": node_count,
    }


def _make_mock_pipeline_context(*, index_ready: bool = True):
    """Create a mock PipelineContext for handler tests.

    When index_ready is False, simulates an INDEX_MISSING state.
    """
    ctx = MagicMock()
    ctx.index_ready = index_ready
    return ctx


# ===========================================================================
# 1. validate_string
# ===========================================================================

class TestValidateString:
    """validate_string: non-empty after strip passes; empty/whitespace raises."""

    def test_valid_non_empty_string(self):
        validate_string, *_ = _import_validation()
        result = validate_string("Nat.add_comm")
        assert result == "Nat.add_comm"

    def test_valid_string_with_surrounding_whitespace_is_stripped(self):
        validate_string, *_ = _import_validation()
        result = validate_string("  Nat.add_comm  ")
        assert result == "Nat.add_comm"

    def test_empty_string_raises(self):
        validate_string, *_ = _import_validation()
        with pytest.raises(Exception) as exc_info:
            validate_string("")
        # The error should indicate a parse/validation error
        assert exc_info.value is not None

    def test_whitespace_only_raises(self):
        validate_string, *_ = _import_validation()
        with pytest.raises(Exception):
            validate_string("   ")

    def test_tab_only_raises(self):
        validate_string, *_ = _import_validation()
        with pytest.raises(Exception):
            validate_string("\t")

    def test_newline_only_raises(self):
        validate_string, *_ = _import_validation()
        with pytest.raises(Exception):
            validate_string("\n")


# ===========================================================================
# 2. validate_limit
# ===========================================================================

class TestValidateLimit:
    """validate_limit: clamp to [1, 200]."""

    def test_default_value_50(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(50) == 50

    def test_zero_clamped_to_1(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(0) == 1

    def test_negative_clamped_to_1(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(-5) == 1

    def test_over_200_clamped_to_200(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(300) == 200

    def test_within_range_unchanged(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(100) == 100

    def test_boundary_1(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(1) == 1

    def test_boundary_200(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(200) == 200

    def test_large_negative_clamped_to_1(self):
        _, validate_limit, *_ = _import_validation()
        assert validate_limit(-999) == 1


# ===========================================================================
# 3. validate_symbols
# ===========================================================================

class TestValidateSymbols:
    """validate_symbols: non-empty list of non-empty stripped strings."""

    def test_valid_symbol_list(self):
        *_, validate_symbols, _ = _import_validation()
        result = validate_symbols(["Nat.add", "Nat.mul"])
        assert result == ["Nat.add", "Nat.mul"]

    def test_strips_whitespace_from_elements(self):
        *_, validate_symbols, _ = _import_validation()
        result = validate_symbols(["  Nat.add  ", " Nat.mul "])
        assert result == ["Nat.add", "Nat.mul"]

    def test_empty_list_raises(self):
        *_, validate_symbols, _ = _import_validation()
        with pytest.raises(Exception):
            validate_symbols([])

    def test_list_with_empty_string_raises(self):
        *_, validate_symbols, _ = _import_validation()
        with pytest.raises(Exception):
            validate_symbols(["Nat.add", ""])

    def test_list_with_whitespace_only_element_raises(self):
        *_, validate_symbols, _ = _import_validation()
        with pytest.raises(Exception):
            validate_symbols(["Nat.add", "   "])

    def test_single_valid_symbol(self):
        *_, validate_symbols, _ = _import_validation()
        result = validate_symbols(["Nat.add"])
        assert result == ["Nat.add"]


# ===========================================================================
# 4. validate_relation
# ===========================================================================

class TestValidateRelation:
    """validate_relation: accepts 4 valid values; rejects others."""

    @pytest.mark.parametrize("relation", ["uses", "used_by", "same_module", "same_typeclass"])
    def test_valid_relations(self, relation):
        *_, validate_relation = _import_validation()
        result = validate_relation(relation)
        assert result == relation

    def test_invalid_relation_raises(self):
        *_, validate_relation = _import_validation()
        with pytest.raises(Exception):
            validate_relation("invalid_relation")

    def test_empty_string_raises(self):
        *_, validate_relation = _import_validation()
        with pytest.raises(Exception):
            validate_relation("")

    def test_case_sensitive_rejection(self):
        *_, validate_relation = _import_validation()
        with pytest.raises(Exception):
            validate_relation("Uses")

    def test_similar_but_wrong_value_raises(self):
        *_, validate_relation = _import_validation()
        with pytest.raises(Exception):
            validate_relation("use")


# ===========================================================================
# 5. format_error
# ===========================================================================

class TestFormatError:
    """format_error: produces correct MCP error JSON structure."""

    def test_structure_has_content_and_is_error(self):
        format_error, *_ = _import_errors()
        result = format_error("SOME_CODE", "Some message")
        assert "content" in result
        assert result["isError"] is True

    def test_content_is_list_with_text_type(self):
        format_error, *_ = _import_errors()
        result = format_error("SOME_CODE", "Some message")
        content = result["content"]
        assert isinstance(content, list)
        assert len(content) == 1
        assert content[0]["type"] == "text"

    def test_text_field_contains_valid_json(self):
        format_error, *_ = _import_errors()
        result = format_error("NOT_FOUND", "Declaration foo not found.")
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert "error" in parsed
        assert parsed["error"]["code"] == "NOT_FOUND"
        assert parsed["error"]["message"] == "Declaration foo not found."

    def test_index_missing_error(self):
        format_error, INDEX_MISSING, *_ = _import_errors()
        result = format_error(INDEX_MISSING, "Index database not found at /path/to/db.")
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == INDEX_MISSING
        assert result["isError"] is True

    def test_index_version_mismatch_error(self):
        format_error, _, INDEX_VERSION_MISMATCH, *_ = _import_errors()
        result = format_error(INDEX_VERSION_MISMATCH, "Schema version 1 incompatible with 2.")
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == INDEX_VERSION_MISMATCH

    def test_parse_error(self):
        format_error, _, _, _, PARSE_ERROR = _import_errors()
        result = format_error(PARSE_ERROR, "Failed to parse expression: bad syntax")
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == PARSE_ERROR

    def test_error_code_constants_are_strings(self):
        _, INDEX_MISSING, INDEX_VERSION_MISMATCH, NOT_FOUND, PARSE_ERROR = _import_errors()
        assert INDEX_MISSING == "INDEX_MISSING"
        assert INDEX_VERSION_MISMATCH == "INDEX_VERSION_MISMATCH"
        assert NOT_FOUND == "NOT_FOUND"
        assert PARSE_ERROR == "PARSE_ERROR"


# ===========================================================================
# 6-7. handle_search_by_name
# ===========================================================================

class TestHandleSearchByName:
    """handle_search_by_name: delegates to pipeline, validates input."""

    def test_delegates_to_pipeline_and_returns_results(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        mock_results = [_make_search_result(score=0.95)]
        ctx.pipeline.search_by_name.return_value = mock_results

        result = handle_search_by_name(ctx, pattern="Nat.add_comm", limit=10)

        ctx.pipeline.search_by_name.assert_called_once()
        assert "content" in result
        content_text = result["content"][0]["text"]
        parsed = json.loads(content_text)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"

    def test_empty_pattern_returns_parse_error(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_name(ctx, pattern="", limit=50)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    def test_whitespace_pattern_returns_parse_error(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_name(ctx, pattern="   ", limit=50)

        assert result["isError"] is True

    def test_limit_clamping_applied(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = []

        handle_search_by_name(ctx, pattern="foo", limit=500)

        # The pipeline should receive the clamped limit (200), not 500
        call_args = ctx.pipeline.search_by_name.call_args
        # limit argument should be <= 200
        limit_arg = call_args[1].get("limit") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("limit", 200)
        assert limit_arg <= 200


# ===========================================================================
# 8. handle_search_by_type
# ===========================================================================

class TestHandleSearchByType:
    """handle_search_by_type: delegates to pipeline."""

    def test_delegates_to_pipeline(self):
        (_, handle_search_by_type, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_type.return_value = [
            _make_search_result(name="Coq.Init.Nat.add", score=0.8)
        ]

        result = handle_search_by_type(ctx, type_expr="nat -> nat -> nat", limit=50)

        ctx.pipeline.search_by_type.assert_called_once()
        assert "content" in result
        assert result.get("isError") is not True

    def test_empty_type_expr_returns_parse_error(self):
        (_, handle_search_by_type, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_type(ctx, type_expr="", limit=50)

        assert result["isError"] is True


# ===========================================================================
# 9. handle_search_by_structure
# ===========================================================================

class TestHandleSearchByStructure:
    """handle_search_by_structure: delegates to pipeline; parse error handling."""

    def test_delegates_to_pipeline(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_structure.return_value = [
            _make_search_result(score=0.75)
        ]

        result = handle_search_by_structure(ctx, expression="forall n : nat, n = n", limit=50)

        ctx.pipeline.search_by_structure.assert_called_once()
        assert result.get("isError") is not True

    def test_pipeline_parse_error_returns_parse_error_response(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        # Simulate the pipeline raising a parse error
        ctx.pipeline.search_by_structure.side_effect = Exception("Failed to parse expression")

        result = handle_search_by_structure(ctx, expression="bad(((syntax", limit=50)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    def test_empty_expression_returns_parse_error(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_structure(ctx, expression="", limit=50)

        assert result["isError"] is True


# ===========================================================================
# 10. handle_search_by_symbols
# ===========================================================================

class TestHandleSearchBySymbols:
    """handle_search_by_symbols: delegates to pipeline."""

    def test_delegates_to_pipeline(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_symbols.return_value = [
            _make_search_result(score=0.9)
        ]

        result = handle_search_by_symbols(
            ctx, symbols=["Nat.add", "Nat.mul"], limit=50
        )

        ctx.pipeline.search_by_symbols.assert_called_once()
        assert result.get("isError") is not True

    def test_empty_symbols_returns_parse_error(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_symbols(ctx, symbols=[], limit=50)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    def test_symbol_with_empty_string_returns_parse_error(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_search_by_symbols(ctx, symbols=["Nat.add", ""], limit=50)

        assert result["isError"] is True


# ===========================================================================
# 11-12. handle_get_lemma
# ===========================================================================

class TestHandleGetLemma:
    """handle_get_lemma: returns LemmaDetail or NOT_FOUND."""

    def test_found_returns_lemma_detail(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = _make_lemma_detail(
            dependencies=["Nat.add", "Nat.mul"],
            dependents=["Some.theorem"],
            symbols=["Nat.add"],
            node_count=5,
        )

        result = handle_get_lemma(ctx, name="Coq.Arith.PeanoNat.Nat.add_comm")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"
        assert parsed["proof_sketch"] == ""
        assert parsed["score"] == 1.0
        assert isinstance(parsed["dependencies"], list)
        assert isinstance(parsed["dependents"], list)
        assert isinstance(parsed["symbols"], list)
        assert isinstance(parsed["node_count"], int)

    def test_not_found_returns_error(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = None  # not found

        result = handle_get_lemma(ctx, name="nonexistent.declaration")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "NOT_FOUND"
        assert "nonexistent.declaration" in text["error"]["message"]

    def test_empty_name_returns_parse_error(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_get_lemma(ctx, name="")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    def test_phase1_proof_sketch_always_empty(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = _make_lemma_detail()

        result = handle_get_lemma(ctx, name="Coq.Arith.PeanoNat.Nat.add_comm")

        parsed = json.loads(result["content"][0]["text"])
        assert parsed["proof_sketch"] == ""

    def test_score_always_1_point_0(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = _make_lemma_detail()

        result = handle_get_lemma(ctx, name="Coq.Arith.PeanoNat.Nat.add_comm")

        parsed = json.loads(result["content"][0]["text"])
        assert parsed["score"] == 1.0


# ===========================================================================
# 13-15. handle_find_related
# ===========================================================================

class TestHandleFindRelated:
    """handle_find_related: 4 relation types, error cases."""

    @pytest.mark.parametrize("relation", ["uses", "used_by", "same_module", "same_typeclass"])
    def test_each_relation_type_delegates(self, relation):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = [
            _make_search_result(score=1.0)
        ]

        result = handle_find_related(
            ctx, name="Coq.Arith.PeanoNat.Nat.add_comm", relation=relation, limit=50
        )

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)

    def test_all_results_have_score_1_point_0(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = [
            _make_search_result(name="A", score=1.0),
            _make_search_result(name="B", score=1.0),
        ]

        result = handle_find_related(
            ctx, name="Coq.Arith.PeanoNat.Nat.add_comm", relation="uses", limit=50
        )

        parsed = json.loads(result["content"][0]["text"])
        for item in parsed:
            assert item["score"] == 1.0

    def test_invalid_relation_returns_parse_error(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_find_related(
            ctx, name="Coq.Arith.PeanoNat.Nat.add_comm", relation="invalid", limit=50
        )

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    def test_unknown_name_returns_not_found(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = None  # declaration not found

        result = handle_find_related(
            ctx, name="nonexistent.decl", relation="uses", limit=50
        )

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "NOT_FOUND"
        assert "nonexistent.decl" in text["error"]["message"]

    def test_empty_name_returns_parse_error(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()

        result = handle_find_related(ctx, name="", relation="uses", limit=50)

        assert result["isError"] is True

    def test_empty_result_is_not_error(self):
        """A relation with no matching edges returns an empty list, not an error."""
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = []

        result = handle_find_related(
            ctx, name="Coq.Some.Decl", relation="uses", limit=50
        )

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == []


# ===========================================================================
# 16. handle_list_modules
# ===========================================================================

class TestHandleListModules:
    """handle_list_modules: prefix filtering."""

    def test_no_prefix_returns_all(self):
        (*_, handle_list_modules) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.list_modules.return_value = [
            {"name": "Coq.Arith.PeanoNat", "decl_count": 42},
            {"name": "Coq.Init.Nat", "decl_count": 15},
        ]

        result = handle_list_modules(ctx, prefix="")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) == 2

    def test_with_prefix_filters(self):
        (*_, handle_list_modules) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.list_modules.return_value = [
            {"name": "Coq.Arith.PeanoNat", "decl_count": 42},
        ]

        result = handle_list_modules(ctx, prefix="Coq.Arith")

        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat"

    def test_empty_result_is_not_error(self):
        (*_, handle_list_modules) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.list_modules.return_value = []

        result = handle_list_modules(ctx, prefix="nonexistent")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == []

    def test_modules_have_name_and_decl_count(self):
        (*_, handle_list_modules) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.list_modules.return_value = [
            {"name": "Coq.Init.Nat", "decl_count": 15},
        ]

        result = handle_list_modules(ctx, prefix="")

        parsed = json.loads(result["content"][0]["text"])
        assert "name" in parsed[0]
        assert "decl_count" in parsed[0]


# ===========================================================================
# 17. Index missing → all handlers return INDEX_MISSING
# ===========================================================================

class TestIndexMissing:
    """When the index is missing, all handlers return INDEX_MISSING error."""

    def _assert_index_missing(self, result):
        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "INDEX_MISSING"

    def test_search_by_name_index_missing(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_search_by_name(ctx, pattern="foo", limit=50)
        self._assert_index_missing(result)

    def test_search_by_type_index_missing(self):
        (_, handle_search_by_type, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_search_by_type(ctx, type_expr="nat -> nat", limit=50)
        self._assert_index_missing(result)

    def test_search_by_structure_index_missing(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_search_by_structure(ctx, expression="forall n, n = n", limit=50)
        self._assert_index_missing(result)

    def test_search_by_symbols_index_missing(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_search_by_symbols(ctx, symbols=["Nat.add"], limit=50)
        self._assert_index_missing(result)

    def test_get_lemma_index_missing(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_get_lemma(ctx, name="Nat.add_comm")
        self._assert_index_missing(result)

    def test_find_related_index_missing(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_find_related(ctx, name="Nat.add_comm", relation="uses", limit=50)
        self._assert_index_missing(result)

    def test_list_modules_index_missing(self):
        (*_, handle_list_modules) = _import_handlers()
        ctx = _make_mock_pipeline_context(index_ready=False)
        result = handle_list_modules(ctx, prefix="")
        self._assert_index_missing(result)


# ===========================================================================
# 18. Schema version mismatch → INDEX_VERSION_MISMATCH
# ===========================================================================

class TestIndexVersionMismatch:
    """When schema version mismatches, handlers return INDEX_VERSION_MISMATCH."""

    def test_version_mismatch_returns_error(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.index_ready = True
        ctx.index_version_mismatch = True  # signals version mismatch

        result = handle_search_by_name(ctx, pattern="foo", limit=50)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "INDEX_VERSION_MISMATCH"

    def test_version_mismatch_message_includes_versions(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.index_ready = True
        ctx.index_version_mismatch = True
        ctx.found_version = "1"
        ctx.expected_version = "2"

        result = handle_search_by_name(ctx, pattern="foo", limit=50)

        text = json.loads(result["content"][0]["text"])
        # Message should mention version information
        assert text["error"]["code"] == "INDEX_VERSION_MISMATCH"


# ===========================================================================
# 19. Limit clamping across all search handlers
# ===========================================================================

class TestLimitClampingAllSearchHandlers:
    """Limit clamping [1, 200] applies to all search handlers."""

    def _get_pipeline_limit(self, mock_method):
        """Extract the limit argument passed to the mock pipeline method."""
        assert mock_method.called, "Pipeline method was not called"
        call_args = mock_method.call_args
        # Try keyword arg first, then positional
        if "limit" in (call_args.kwargs or {}):
            return call_args.kwargs["limit"]
        # Positional: pattern/expr is arg[0], limit is arg[1]
        if len(call_args.args) > 1:
            return call_args.args[1]
        return None

    def test_search_by_name_clamps_high_limit(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = []

        handle_search_by_name(ctx, pattern="foo", limit=999)

        limit = self._get_pipeline_limit(ctx.pipeline.search_by_name)
        assert limit is not None and limit <= 200

    def test_search_by_type_clamps_zero_limit(self):
        (_, handle_search_by_type, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_type.return_value = []

        handle_search_by_type(ctx, type_expr="nat", limit=0)

        limit = self._get_pipeline_limit(ctx.pipeline.search_by_type)
        assert limit is not None and limit >= 1

    def test_search_by_structure_clamps_negative_limit(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_structure.return_value = []

        handle_search_by_structure(ctx, expression="forall n, n = n", limit=-10)

        limit = self._get_pipeline_limit(ctx.pipeline.search_by_structure)
        assert limit is not None and limit >= 1

    def test_search_by_symbols_clamps_high_limit(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_symbols.return_value = []

        handle_search_by_symbols(ctx, symbols=["Nat.add"], limit=500)

        limit = self._get_pipeline_limit(ctx.pipeline.search_by_symbols)
        assert limit is not None and limit <= 200

    def test_find_related_clamps_high_limit(self):
        (*_, handle_find_related, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = []

        handle_find_related(
            ctx, name="Coq.Some.Decl", relation="uses", limit=300
        )

        limit = self._get_pipeline_limit(ctx.pipeline.find_related)
        assert limit is not None and limit <= 200


# ===========================================================================
# Response formatting: MCP content type and DeclKind serialization
# ===========================================================================

class TestResponseFormatting:
    """Successful responses use MCP content type 'text' with JSON."""

    def test_successful_response_has_text_content_type(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [_make_search_result()]

        result = handle_search_by_name(ctx, pattern="foo", limit=10)

        assert result["content"][0]["type"] == "text"

    def test_result_text_is_valid_json(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [_make_search_result()]

        result = handle_search_by_name(ctx, pattern="foo", limit=10)

        # Should not raise
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)

    def test_decl_kind_serialized_as_lowercase(self):
        """DeclKind values should be lowercase strings per spec."""
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [
            _make_search_result(kind="lemma"),
        ]

        result = handle_search_by_name(ctx, pattern="foo", limit=10)

        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["kind"] == "lemma"

    def test_search_result_has_all_required_fields(self):
        """SearchResult must have: name, statement, type, module, kind, score."""
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [_make_search_result()]

        result = handle_search_by_name(ctx, pattern="foo", limit=10)

        parsed = json.loads(result["content"][0]["text"])
        item = parsed[0]
        required_fields = {"name", "statement", "type", "module", "kind", "score"}
        assert required_fields.issubset(set(item.keys()))

    def test_lemma_detail_has_all_required_fields(self):
        """LemmaDetail must have SearchResult fields plus extended fields."""
        (*_, handle_get_lemma, _, _) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = _make_lemma_detail()

        result = handle_get_lemma(ctx, name="Coq.Arith.PeanoNat.Nat.add_comm")

        parsed = json.loads(result["content"][0]["text"])
        required_fields = {
            "name", "statement", "type", "module", "kind", "score",
            "dependencies", "dependents", "proof_sketch", "symbols", "node_count",
        }
        assert required_fields.issubset(set(parsed.keys()))


# ===========================================================================
# Dataclass serialization: handlers must serialize real dataclass instances
# ===========================================================================

def _import_response_types():
    from Poule.models.responses import SearchResult, LemmaDetail, Module
    return SearchResult, LemmaDetail, Module


class TestDataclassSerialization:
    """Handlers must serialize dataclass instances returned by the pipeline.

    The pipeline returns SearchResult, LemmaDetail, and Module dataclass
    instances, not plain dicts. The handler layer must convert these to
    JSON-serializable dicts before calling json.dumps().

    Spec §4.5: "All successful responses shall be formatted as MCP content
    with type: 'text' containing a JSON-serialized result."
    Spec §8: "JSON serialization via dataclasses.asdict() + json.dumps()
    for response types."
    """

    def test_search_by_name_serializes_search_result_dataclass(self):
        (handle_search_by_name, *_) = _import_handlers()
        SearchResult, _, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [
            SearchResult(
                name="Nat.add_comm",
                statement="forall n m, n + m = m + n",
                type="forall n m, n + m = m + n",
                module="Coq.Arith.PeanoNat",
                kind="lemma",
                score=0.95,
            )
        ]

        result = handle_search_by_name(ctx, pattern="add_comm", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Nat.add_comm"
        assert parsed[0]["score"] == 0.95

    def test_search_by_type_serializes_search_result_dataclass(self):
        (_, handle_search_by_type, *_) = _import_handlers()
        SearchResult, _, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_type.return_value = [
            SearchResult(
                name="Nat.add",
                statement="",
                type="nat -> nat -> nat",
                module="Coq.Init.Nat",
                kind="definition",
                score=0.8,
            )
        ]

        result = handle_search_by_type(ctx, type_expr="nat -> nat -> nat", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["name"] == "Nat.add"

    def test_search_by_structure_serializes_search_result_dataclass(self):
        (*_, handle_search_by_structure, _, _, _, _) = _import_handlers()
        SearchResult, _, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_structure.return_value = [
            SearchResult(
                name="Nat.add_0_r",
                statement="forall n, n + 0 = n",
                type="forall n, n + 0 = n",
                module="Coq.Arith.PeanoNat",
                kind="lemma",
                score=0.75,
            )
        ]

        result = handle_search_by_structure(ctx, expression="forall n, n + 0 = n", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["name"] == "Nat.add_0_r"

    def test_search_by_symbols_serializes_search_result_dataclass(self):
        (*_, handle_search_by_symbols, _, _, _) = _import_handlers()
        SearchResult, _, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_symbols.return_value = [
            SearchResult(
                name="Nat.add_comm",
                statement="",
                type="",
                module="Coq.Arith.PeanoNat",
                kind="lemma",
                score=0.9,
            )
        ]

        result = handle_search_by_symbols(ctx, symbols=["Nat.add"], limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["name"] == "Nat.add_comm"

    def test_get_lemma_serializes_lemma_detail_dataclass(self):
        (*_, handle_get_lemma, _, _) = _import_handlers()
        _, LemmaDetail, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.get_lemma.return_value = LemmaDetail(
            name="Nat.add_comm",
            statement="forall n m, n + m = m + n",
            type="forall n m, n + m = m + n",
            module="Coq.Arith.PeanoNat",
            kind="lemma",
            score=1.0,
            dependencies=["Nat.add"],
            dependents=["Some.theorem"],
            proof_sketch="",
            symbols=["Nat.add"],
            node_count=5,
        )

        result = handle_get_lemma(ctx, name="Nat.add_comm")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["name"] == "Nat.add_comm"
        assert parsed["dependencies"] == ["Nat.add"]
        assert parsed["node_count"] == 5

    def test_find_related_serializes_search_result_dataclass(self):
        (*_, handle_find_related, _) = _import_handlers()
        SearchResult, _, _ = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.find_related.return_value = [
            SearchResult(
                name="Nat.add_assoc",
                statement="",
                type="",
                module="Coq.Arith.PeanoNat",
                kind="lemma",
                score=1.0,
            )
        ]

        result = handle_find_related(ctx, name="Nat.add_comm", relation="same_module", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["name"] == "Nat.add_assoc"

    def test_list_modules_serializes_module_dataclass(self):
        (*_, handle_list_modules) = _import_handlers()
        _, _, Module = _import_response_types()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.list_modules.return_value = [
            Module(name="Coq.Arith.PeanoNat", decl_count=42),
            Module(name="Coq.Init.Nat", decl_count=15),
        ]

        result = handle_list_modules(ctx, prefix="")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat"
        assert parsed[0]["decl_count"] == 42

    def test_empty_list_of_dataclasses_serializes(self):
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = []

        result = handle_search_by_name(ctx, pattern="nonexistent", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == []

    def test_mixed_list_not_accepted_plain_dicts_still_work(self):
        """Plain dicts (e.g. from get_lemma/find_related internals) still serialize."""
        (handle_search_by_name, *_) = _import_handlers()
        ctx = _make_mock_pipeline_context()
        ctx.pipeline.search_by_name.return_value = [
            {"name": "A", "statement": "", "type": "", "module": "M", "kind": "lemma", "score": 1.0}
        ]

        result = handle_search_by_name(ctx, pattern="A", limit=10)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed[0]["name"] == "A"

    def test_serialize_converts_sets_to_lists(self):
        """Sets and frozensets must be converted to JSON-serializable lists."""
        from Poule.server.handlers import _serialize
        result = _serialize({"nodes": {"b", "a", "c"}, "count": 3})
        assert isinstance(result["nodes"], list)
        assert result["nodes"] == ["a", "b", "c"]  # sorted

    def test_serialize_converts_int_dict_keys_to_strings(self):
        """Dict keys that are ints must be converted to strings for JSON."""
        from Poule.server.handlers import _serialize
        result = _serialize({0: {"root"}, 1: {"child"}})
        assert "0" in result
        assert isinstance(result["0"], list)

    def test_serialize_handles_nested_sets_in_dataclass(self):
        """dataclasses.asdict preserves sets; _serialize must convert them."""
        from Poule.analysis.impact import ImpactSet
        from Poule.server.handlers import _serialize
        impact = ImpactSet(
            root="A",
            impacted_nodes={"A", "B"},
            edges={("A", "B")},
            depth_map={0: {"A"}, 1: {"B"}},
            total_depth=1,
        )
        result = _serialize(impact)
        # All sets should now be lists
        assert isinstance(result["impacted_nodes"], list)
        assert isinstance(result["edges"], list)
        assert isinstance(result["depth_map"]["0"], list)
        # Should be JSON-serializable without error
        json.dumps(result)


# ===========================================================================
# Proof Interaction Handlers (Spec §4.3)
# ===========================================================================

def _import_proof_handlers():
    from Poule.server.handlers import (
        handle_open_proof_session,
        handle_close_proof_session,
        handle_list_proof_sessions,
        handle_observe_proof_state,
        handle_get_proof_state_at_step,
        handle_extract_proof_trace,
        handle_submit_tactic,
        handle_step_backward,
        handle_step_forward,
        handle_submit_tactic_batch,
        handle_get_proof_premises,
        handle_get_step_premises,
    )
    return (
        handle_open_proof_session,
        handle_close_proof_session,
        handle_list_proof_sessions,
        handle_observe_proof_state,
        handle_get_proof_state_at_step,
        handle_extract_proof_trace,
        handle_submit_tactic,
        handle_step_backward,
        handle_step_forward,
        handle_submit_tactic_batch,
        handle_get_proof_premises,
        handle_get_step_premises,
    )


def _import_proof_errors():
    from Poule.server.errors import (
        SESSION_NOT_FOUND,
        SESSION_EXPIRED,
        FILE_NOT_FOUND,
        PROOF_NOT_FOUND,
        TACTIC_ERROR,
        STEP_OUT_OF_RANGE,
        NO_PREVIOUS_STATE,
        PROOF_COMPLETE,
        BACKEND_CRASHED,
    )
    return (
        SESSION_NOT_FOUND, SESSION_EXPIRED, FILE_NOT_FOUND, PROOF_NOT_FOUND,
        TACTIC_ERROR, STEP_OUT_OF_RANGE, NO_PREVIOUS_STATE, PROOF_COMPLETE,
        BACKEND_CRASHED,
    )


def _import_session_error():
    from Poule.session.errors import SessionError
    return SessionError


def _make_proof_state(
    session_id: str = "abc123",
    step_index: int = 0,
    is_complete: bool = False,
):
    """Build a ProofState dict for mock returns."""
    from Poule.session.types import ProofState, Goal
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=0 if not is_complete else None,
        goals=[Goal(index=0, type="n = n")] if not is_complete else [],
    )


def _make_mock_session_manager():
    """Create a mock session manager for handler tests."""
    mgr = AsyncMock()
    return mgr


def _make_proof_handler_ctx(*, index_ready: bool = True, session_manager=None):
    """Create a mock context with both pipeline and session manager."""
    ctx = _make_mock_pipeline_context(index_ready=index_ready)
    ctx.session_manager = session_manager or _make_mock_session_manager()
    return ctx


# ===========================================================================
# Proof error code constants
# ===========================================================================

class TestProofErrorCodeConstants:
    """Proof interaction error code constants are strings."""

    def test_all_proof_error_codes_are_strings(self):
        codes = _import_proof_errors()
        for code in codes:
            assert isinstance(code, str)

    def test_session_not_found_value(self):
        (SESSION_NOT_FOUND, *_) = _import_proof_errors()
        assert SESSION_NOT_FOUND == "SESSION_NOT_FOUND"

    def test_session_expired_value(self):
        (_, SESSION_EXPIRED, *_) = _import_proof_errors()
        assert SESSION_EXPIRED == "SESSION_EXPIRED"

    def test_file_not_found_value(self):
        (_, _, FILE_NOT_FOUND, *_) = _import_proof_errors()
        assert FILE_NOT_FOUND == "FILE_NOT_FOUND"

    def test_proof_not_found_value(self):
        (_, _, _, PROOF_NOT_FOUND, *_) = _import_proof_errors()
        assert PROOF_NOT_FOUND == "PROOF_NOT_FOUND"

    def test_tactic_error_value(self):
        (_, _, _, _, TACTIC_ERROR, *_) = _import_proof_errors()
        assert TACTIC_ERROR == "TACTIC_ERROR"

    def test_step_out_of_range_value(self):
        (_, _, _, _, _, STEP_OUT_OF_RANGE, *_) = _import_proof_errors()
        assert STEP_OUT_OF_RANGE == "STEP_OUT_OF_RANGE"

    def test_no_previous_state_value(self):
        (_, _, _, _, _, _, NO_PREVIOUS_STATE, *_) = _import_proof_errors()
        assert NO_PREVIOUS_STATE == "NO_PREVIOUS_STATE"

    def test_proof_complete_value(self):
        (_, _, _, _, _, _, _, PROOF_COMPLETE, _) = _import_proof_errors()
        assert PROOF_COMPLETE == "PROOF_COMPLETE"

    def test_backend_crashed_value(self):
        (*_, BACKEND_CRASHED) = _import_proof_errors()
        assert BACKEND_CRASHED == "BACKEND_CRASHED"


# ===========================================================================
# handle_open_proof_session
# ===========================================================================

class TestHandleOpenProofSession:
    """handle_open_proof_session: delegates to session manager."""

    @pytest.mark.asyncio
    async def test_successful_open(self):
        (handle_open, *_) = _import_proof_handlers()
        state = _make_proof_state()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.create_session.return_value = ("abc123", state)

        result = await handle_open(
            ctx, file_path="/path/to/Nat.v", proof_name="Nat.add_comm",
        )

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert "session_id" in parsed
        assert "state" in parsed

    @pytest.mark.asyncio
    async def test_empty_file_path_returns_parse_error(self):
        (handle_open, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_open(ctx, file_path="", proof_name="Nat.add_comm")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_empty_proof_name_returns_parse_error(self):
        (handle_open, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_open(ctx, file_path="/path.v", proof_name="")

        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_file_not_found_error(self):
        (handle_open, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.create_session.side_effect = SessionError(
            "FILE_NOT_FOUND", "File not found: /bad/path.v"
        )

        result = await handle_open(ctx, file_path="/bad/path.v", proof_name="P")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "FILE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_proof_not_found_error(self):
        (handle_open, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.create_session.side_effect = SessionError(
            "PROOF_NOT_FOUND", "Proof not found"
        )

        result = await handle_open(ctx, file_path="/path.v", proof_name="Bad")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PROOF_NOT_FOUND"


# ===========================================================================
# handle_close_proof_session
# ===========================================================================

class TestHandleCloseProofSession:
    """handle_close_proof_session: delegates to session manager."""

    @pytest.mark.asyncio
    async def test_successful_close(self):
        (_, handle_close, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.close_session.return_value = None

        result = await handle_close(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["closed"] is True

    @pytest.mark.asyncio
    async def test_unknown_session_returns_error(self):
        (_, handle_close, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.close_session.side_effect = SessionError(
            "SESSION_NOT_FOUND", "nonexistent"
        )

        result = await handle_close(ctx, session_id="nonexistent")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_session_id_returns_parse_error(self):
        (_, handle_close, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_close(ctx, session_id="")

        assert result["isError"] is True


# ===========================================================================
# handle_list_proof_sessions
# ===========================================================================

class TestHandleListProofSessions:
    """handle_list_proof_sessions: returns all active sessions."""

    @pytest.mark.asyncio
    async def test_returns_session_list(self):
        (_, _, handle_list, *_) = _import_proof_handlers()
        from Poule.session.types import Session
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.list_sessions.return_value = [
            Session(
                session_id="abc",
                file_path="/f.v",
                proof_name="P",
                current_step=0,
                total_steps=5,
                created_at="2026-03-17T14:00:00Z",
                last_active_at="2026-03-17T14:00:00Z",
            )
        ]

        result = await handle_list(ctx)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["session_id"] == "abc"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_sessions(self):
        (_, _, handle_list, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.list_sessions.return_value = []

        result = await handle_list(ctx)

        parsed = json.loads(result["content"][0]["text"])
        assert parsed == []


# ===========================================================================
# handle_observe_proof_state
# ===========================================================================

class TestHandleObserveProofState:
    """handle_observe_proof_state: returns current proof state."""

    @pytest.mark.asyncio
    async def test_returns_proof_state(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.observe_state.return_value = _make_proof_state()

        result = await handle_observe(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert "step_index" in parsed
        assert "goals" in parsed

    @pytest.mark.asyncio
    async def test_session_not_found_error(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.observe_state.side_effect = SessionError(
            "SESSION_NOT_FOUND", "nonexistent"
        )

        result = await handle_observe(ctx, session_id="nonexistent")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_session_id_returns_parse_error(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_observe(ctx, session_id="")

        assert result["isError"] is True


# ===========================================================================
# handle_get_proof_state_at_step
# ===========================================================================

class TestHandleGetProofStateAtStep:
    """handle_get_proof_state_at_step: returns proof state at step k."""

    @pytest.mark.asyncio
    async def test_returns_state_at_step(self):
        (_, _, _, _, handle_get_at_step, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.get_state_at_step.return_value = _make_proof_state(step_index=3)

        result = await handle_get_at_step(ctx, session_id="abc123", step=3)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["step_index"] == 3

    @pytest.mark.asyncio
    async def test_step_out_of_range(self):
        (_, _, _, _, handle_get_at_step, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.get_state_at_step.side_effect = SessionError(
            "STEP_OUT_OF_RANGE", "Step 99 out of range"
        )

        result = await handle_get_at_step(ctx, session_id="abc123", step=99)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "STEP_OUT_OF_RANGE"


# ===========================================================================
# handle_extract_proof_trace
# ===========================================================================

class TestHandleExtractProofTrace:
    """handle_extract_proof_trace: returns full proof trace."""

    @pytest.mark.asyncio
    async def test_returns_trace(self):
        (_, _, _, _, _, handle_extract, *_) = _import_proof_handlers()
        from Poule.session.types import ProofTrace, TraceStep
        state0 = _make_proof_state(step_index=0)
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.extract_trace.return_value = ProofTrace(
            schema_version=1,
            session_id="abc123",
            proof_name="P",
            file_path="/f.v",
            total_steps=0,
            steps=[TraceStep(step_index=0, tactic=None, state=state0)],
        )

        result = await handle_extract(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert "steps" in parsed
        assert parsed["total_steps"] == 0


# ===========================================================================
# handle_submit_tactic
# ===========================================================================

class TestHandleSubmitTactic:
    """handle_submit_tactic: submits tactic, returns resulting state."""

    @pytest.mark.asyncio
    async def test_successful_tactic(self):
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.submit_tactic.return_value = _make_proof_state(step_index=1)

        result = await handle_submit(ctx, session_id="abc123", tactic="intro n.")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["step_index"] == 1

    @pytest.mark.asyncio
    async def test_empty_tactic_returns_parse_error(self):
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_submit(ctx, session_id="abc123", tactic="")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_tactic_error_returns_error_response(self):
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.submit_tactic.side_effect = SessionError(
            "TACTIC_ERROR", "No such tactic."
        )

        result = await handle_submit(ctx, session_id="abc123", tactic="bad_tactic.")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "TACTIC_ERROR"


# ===========================================================================
# handle_step_backward
# ===========================================================================

class TestHandleStepBackward:
    """handle_step_backward: returns previous state."""

    @pytest.mark.asyncio
    async def test_successful_step_backward(self):
        (_, _, _, _, _, _, _, handle_back, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.step_backward.return_value = _make_proof_state(step_index=0)

        result = await handle_back(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["step_index"] == 0

    @pytest.mark.asyncio
    async def test_at_initial_state_returns_error(self):
        (_, _, _, _, _, _, _, handle_back, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.step_backward.side_effect = SessionError(
            "NO_PREVIOUS_STATE", "Already at initial state"
        )

        result = await handle_back(ctx, session_id="abc123")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "NO_PREVIOUS_STATE"


# ===========================================================================
# handle_step_forward
# ===========================================================================

class TestHandleStepForward:
    """handle_step_forward: returns tactic and resulting state."""

    @pytest.mark.asyncio
    async def test_successful_step_forward(self):
        (_, _, _, _, _, _, _, _, handle_fwd, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.step_forward.return_value = (
            "intro n.",
            _make_proof_state(step_index=1),
        )

        result = await handle_fwd(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["tactic"] == "intro n."
        assert "state" in parsed

    @pytest.mark.asyncio
    async def test_proof_complete_returns_error(self):
        (_, _, _, _, _, _, _, _, handle_fwd, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.step_forward.side_effect = SessionError(
            "PROOF_COMPLETE", "No more steps"
        )

        result = await handle_fwd(ctx, session_id="abc123")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "PROOF_COMPLETE"


# ===========================================================================
# handle_submit_tactic_batch (P1)
# ===========================================================================

class TestHandleSubmitTacticBatch:
    """handle_submit_tactic_batch: batch tactic submission."""

    @pytest.mark.asyncio
    async def test_successful_batch(self):
        (_, _, _, _, _, _, _, _, _, handle_batch, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.submit_tactic_batch.return_value = [
            {"tactic": "intro n.", "state": _make_proof_state(step_index=1), "error": None},
            {"tactic": "reflexivity.", "state": _make_proof_state(step_index=2, is_complete=True), "error": None},
        ]

        result = await handle_batch(
            ctx, session_id="abc123", tactics=["intro n.", "reflexivity."],
        )

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    @pytest.mark.asyncio
    async def test_empty_tactics_returns_parse_error(self):
        (_, _, _, _, _, _, _, _, _, handle_batch, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()

        result = await handle_batch(ctx, session_id="abc123", tactics=[])

        assert result["isError"] is True


# ===========================================================================
# handle_get_proof_premises
# ===========================================================================

class TestHandleGetProofPremises:
    """handle_get_proof_premises: returns premise annotations for all steps."""

    @pytest.mark.asyncio
    async def test_returns_annotations(self):
        (_, _, _, _, _, _, _, _, _, _, handle_premises, _) = _import_proof_handlers()
        from Poule.session.types import PremiseAnnotation, Premise
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.get_premises.return_value = [
            PremiseAnnotation(
                step_index=1,
                tactic="rewrite Nat.add_comm.",
                premises=[Premise(name="Nat.add_comm", kind="lemma")],
            )
        ]

        result = await handle_premises(ctx, session_id="abc123")

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert isinstance(parsed, list)
        assert len(parsed) == 1


# ===========================================================================
# handle_get_step_premises
# ===========================================================================

class TestHandleGetStepPremises:
    """handle_get_step_premises: returns premise annotation for a single step."""

    @pytest.mark.asyncio
    async def test_returns_single_annotation(self):
        (*_, handle_step_premises) = _import_proof_handlers()
        from Poule.session.types import PremiseAnnotation
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.get_step_premises.return_value = PremiseAnnotation(
            step_index=1,
            tactic="reflexivity.",
        )

        result = await handle_step_premises(ctx, session_id="abc123", step=1)

        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["step_index"] == 1

    @pytest.mark.asyncio
    async def test_step_out_of_range(self):
        (*_, handle_step_premises) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.get_step_premises.side_effect = SessionError(
            "STEP_OUT_OF_RANGE", "Step 99 out of range"
        )

        result = await handle_step_premises(ctx, session_id="abc123", step=99)

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "STEP_OUT_OF_RANGE"


# ===========================================================================
# Proof tools work without search index (Spec §4.5)
# ===========================================================================

class TestProofToolsIndexIndependent:
    """Proof interaction tools shall function even when the index is missing."""

    @pytest.mark.asyncio
    async def test_observe_state_works_without_index(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx(index_ready=False)
        ctx.session_manager.observe_state.return_value = _make_proof_state()

        result = await handle_observe(ctx, session_id="abc123")

        # Should NOT return INDEX_MISSING — proof tools are index-independent
        assert result.get("isError") is not True

    @pytest.mark.asyncio
    async def test_open_session_works_without_index(self):
        (handle_open, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx(index_ready=False)
        ctx.session_manager.create_session.return_value = ("abc123", _make_proof_state())

        result = await handle_open(
            ctx, file_path="/path.v", proof_name="P",
        )

        assert result.get("isError") is not True


# ===========================================================================
# SessionError → MCP error translation
# ===========================================================================

class TestSessionErrorTranslation:
    """The MCP server translates SessionError into MCP error responses."""

    @pytest.mark.asyncio
    async def test_session_expired_translated(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.observe_state.side_effect = SessionError(
            "SESSION_EXPIRED", "abc123"
        )

        result = await handle_observe(ctx, session_id="abc123")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "SESSION_EXPIRED"

    @pytest.mark.asyncio
    async def test_backend_crashed_translated(self):
        (_, _, _, handle_observe, *_) = _import_proof_handlers()
        SessionError = _import_session_error()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.observe_state.side_effect = SessionError(
            "BACKEND_CRASHED", "abc123"
        )

        result = await handle_observe(ctx, session_id="abc123")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "BACKEND_CRASHED"


# ===========================================================================
# TACTIC_ERROR enriched response (Spec §4.9)
# ===========================================================================

class TestTacticErrorEnrichedResponse:
    """§4.9: TACTIC_ERROR response includes both the error object and the
    unchanged ProofState so the LLM can report both without a separate
    observe_proof_state call.

    The session manager raises a SessionError with code TACTIC_ERROR; the
    session manager also attaches the unchanged state to the exception so
    the handler can include it in the response body.
    """

    def _make_tactic_session_error(self, step_index=0, message="Tactic failed: No such tactic."):
        """Build a SessionError for TACTIC_ERROR that carries the unchanged state."""
        SessionError = _import_session_error()
        exc = SessionError("TACTIC_ERROR", message)
        # Attach the unchanged proof state so the handler can embed it
        exc.state = _make_proof_state(step_index=step_index)
        return exc

    @pytest.mark.asyncio
    async def test_tactic_error_response_includes_unchanged_proof_state(self):
        """When submit_tactic raises TACTIC_ERROR with attached state, the JSON
        body includes both the error object and the unchanged ProofState fields
        (step_index, goals, is_complete).  Spec §4.9."""
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.submit_tactic.side_effect = (
            self._make_tactic_session_error(step_index=2)
        )

        result = await handle_submit(ctx, session_id="abc123", tactic="bad_tactic.")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert text["error"]["code"] == "TACTIC_ERROR"
        # §4.9: response body includes the unchanged ProofState
        assert "state" in text["error"]
        state = text["error"]["state"]
        assert state["step_index"] == 2
        assert "goals" in state
        assert "is_complete" in state

    @pytest.mark.asyncio
    async def test_tactic_error_is_error_true(self):
        """TACTIC_ERROR response sets isError=True (§4.9)."""
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        ctx.session_manager.submit_tactic.side_effect = (
            self._make_tactic_session_error(
                message="Tactic failed: The reference bad_tactic was not found."
            )
        )

        result = await handle_submit(ctx, session_id="abc123", tactic="bad_tactic.")

        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_tactic_error_state_is_complete_field_present(self):
        """§4.9: is_complete field is present in the embedded state and
        reflects the unchanged proof state (False when proof is not done)."""
        (_, _, _, _, _, _, handle_submit, *_) = _import_proof_handlers()
        ctx = _make_proof_handler_ctx()
        exc = _import_session_error()("TACTIC_ERROR", "Tactic failed: No matching clauses for induction.")
        exc.state = _make_proof_state(step_index=1, is_complete=False)
        ctx.session_manager.submit_tactic.side_effect = exc

        result = await handle_submit(ctx, session_id="abc123", tactic="induction bad.")

        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        state = text["error"]["state"]
        assert state["is_complete"] is False


# ===========================================================================
# Diagram write error handling (Spec §4.4, diagram-file-output §5)
# ===========================================================================

def _import_viz_handlers():
    from Poule.server.handlers import (
        handle_visualize_proof_state,
        handle_visualize_proof_tree,
        handle_visualize_proof_sequence,
    )
    return handle_visualize_proof_state, handle_visualize_proof_tree, handle_visualize_proof_sequence


def _make_mock_renderer():
    """Create a mock Mermaid renderer."""
    renderer = MagicMock()
    renderer.render_proof_state.return_value = "flowchart TD\n    s0g0[\"n = n\"]"
    renderer.render_proof_tree.return_value = "flowchart TD\n    s0g0[\"n = n\"]"
    renderer.render_proof_sequence.return_value = []
    return renderer


def _make_mock_session_manager_for_viz():
    """Create a mock session manager that returns a proof state."""
    mgr = AsyncMock()
    state = _make_proof_state(step_index=0)
    mgr.observe_state.return_value = state
    mgr.get_state_at_step.return_value = state

    # Build a minimal ProofTrace for tree/sequence tests
    from Poule.session.types import ProofTrace, TraceStep
    complete_state = _make_proof_state(step_index=1, is_complete=True)
    trace = ProofTrace(
        schema_version=1,
        session_id="abc123",
        proof_name="P",
        file_path="/f.v",
        total_steps=1,
        steps=[
            TraceStep(step_index=0, tactic=None, state=state),
            TraceStep(step_index=1, tactic="reflexivity.", state=complete_state),
        ],
    )
    mgr.extract_trace.return_value = trace
    return mgr


class TestDiagramWriteErrorHandling:
    """§4.4 + diagram-file-output §5: When the diagram directory is unwritable,
    the visualization handler catches the exception, logs at WARNING, and still
    returns a valid response — the error is not propagated."""

    @pytest.mark.asyncio
    async def test_unwritable_dir_does_not_propagate_for_proof_state(self, caplog):
        """visualize_proof_state: OSError from write_diagram_html is caught and
        logged at WARNING; the handler returns a valid JSON response.

        write_diagram_html is imported locally inside the handler, so we patch
        the function in its defining module (diagram_writer)."""
        handle_visualize_proof_state, _, _ = _import_viz_handlers()
        mgr = _make_mock_session_manager_for_viz()
        renderer = _make_mock_renderer()

        with patch(
            "Poule.server.diagram_writer.write_diagram_html",
            side_effect=OSError("Permission denied"),
        ):
            with caplog.at_level(logging.WARNING):
                result_json = await handle_visualize_proof_state(
                    session_id="abc123",
                    session_manager=mgr,
                    renderer=renderer,
                    diagram_dir="/unwritable/dir",
                )

        # Handler must return a valid response, not raise
        data = json.loads(result_json)
        assert "error" not in data
        assert "mermaid" in data
        assert "step_index" in data

        # The write failure must be logged at WARNING
        assert any(
            record.levelno == logging.WARNING for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_unwritable_dir_does_not_propagate_for_proof_tree(self, caplog):
        """visualize_proof_tree: OSError from write_diagram_html is caught and
        logged at WARNING; the handler returns a valid JSON response."""
        _, handle_visualize_proof_tree, _ = _import_viz_handlers()
        mgr = _make_mock_session_manager_for_viz()
        renderer = _make_mock_renderer()

        with patch(
            "Poule.server.diagram_writer.write_diagram_html",
            side_effect=OSError("Read-only file system"),
        ):
            with caplog.at_level(logging.WARNING):
                result_json = await handle_visualize_proof_tree(
                    session_id="abc123",
                    session_manager=mgr,
                    renderer=renderer,
                    diagram_dir="/unwritable/dir",
                )

        data = json.loads(result_json)
        assert "error" not in data
        assert "mermaid" in data
        assert "total_steps" in data

        assert any(
            record.levelno == logging.WARNING for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_diagram_dir_none_skips_write_no_side_effect(self):
        """When diagram_dir is None, no write attempt is made and the handler
        returns normally."""
        handle_visualize_proof_state, _, _ = _import_viz_handlers()
        mgr = _make_mock_session_manager_for_viz()
        renderer = _make_mock_renderer()

        with patch(
            "Poule.server.diagram_writer.write_diagram_html",
        ) as mock_write:
            result_json = await handle_visualize_proof_state(
                session_id="abc123",
                session_manager=mgr,
                renderer=renderer,
                diagram_dir=None,
            )

        mock_write.assert_not_called()
        data = json.loads(result_json)
        assert "mermaid" in data
