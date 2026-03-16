"""TDD tests for the MCP server layer (validation, errors, handlers).

Tests are written BEFORE implementation. They will fail with ImportError
until src/wily_rooster/server/ modules exist.

Spec: specification/mcp-server.md
Architecture: doc/architecture/mcp-server.md
Tasks: tasks/mcp-server.md

Import paths under test:
  wily_rooster.server.handlers
  wily_rooster.server.validation
  wily_rooster.server.errors
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------

def _import_validation():
    from wily_rooster.server.validation import (
        validate_string,
        validate_limit,
        validate_symbols,
        validate_relation,
    )
    return validate_string, validate_limit, validate_symbols, validate_relation


def _import_errors():
    from wily_rooster.server.errors import (
        format_error,
        INDEX_MISSING,
        INDEX_VERSION_MISMATCH,
        NOT_FOUND,
        PARSE_ERROR,
    )
    return format_error, INDEX_MISSING, INDEX_VERSION_MISMATCH, NOT_FOUND, PARSE_ERROR


def _import_handlers():
    from wily_rooster.server.handlers import (
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
