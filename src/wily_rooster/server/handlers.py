"""MCP tool handler functions for the wily-rooster server."""

from __future__ import annotations

import json
from typing import Any

from wily_rooster.server.errors import (
    format_error,
    INDEX_MISSING,
    INDEX_VERSION_MISMATCH,
    NOT_FOUND,
    PARSE_ERROR,
)
from wily_rooster.server.validation import (
    validate_string,
    validate_limit,
    validate_symbols,
    validate_relation,
)


def _format_success(data: Any) -> dict:
    """Format a successful response as an MCP content dict."""
    return {
        "content": [{"type": "text", "text": json.dumps(data)}],
    }


def _check_index(ctx: Any) -> dict | None:
    """Check index state; return an error response dict if not ready, else None."""
    if not ctx.index_ready:
        return format_error(INDEX_MISSING, "Index database not found. Run the indexing command to create it.")
    if getattr(ctx, "index_version_mismatch", False) is True:
        found = getattr(ctx, "found_version", "unknown")
        expected = getattr(ctx, "expected_version", "unknown")
        return format_error(
            INDEX_VERSION_MISMATCH,
            f"Index schema version {found} is incompatible with tool version {expected}. Re-indexing from scratch.",
        )
    return None


def handle_search_by_name(ctx: Any, *, pattern: str, limit: int) -> dict:
    """Handle search_by_name tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        pattern = validate_string(pattern)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "pattern must be a non-empty string.")
    limit = validate_limit(limit)
    results = ctx.pipeline.search_by_name(pattern, limit)
    return _format_success(results)


def handle_search_by_type(ctx: Any, *, type_expr: str, limit: int) -> dict:
    """Handle search_by_type tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        type_expr = validate_string(type_expr)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "type_expr must be a non-empty string.")
    limit = validate_limit(limit)
    results = ctx.pipeline.search_by_type(type_expr, limit)
    return _format_success(results)


def handle_search_by_structure(ctx: Any, *, expression: str, limit: int) -> dict:
    """Handle search_by_structure tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        expression = validate_string(expression)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "expression must be a non-empty string.")
    limit = validate_limit(limit)
    try:
        results = ctx.pipeline.search_by_structure(expression, limit)
    except Exception as exc:
        return format_error(PARSE_ERROR, f"Failed to parse expression: {exc}")
    return _format_success(results)


def handle_search_by_symbols(ctx: Any, *, symbols: list[str], limit: int) -> dict:
    """Handle search_by_symbols tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        symbols = validate_symbols(symbols)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "symbols must be a non-empty list of non-empty strings.")
    limit = validate_limit(limit)
    results = ctx.pipeline.search_by_symbols(symbols, limit)
    return _format_success(results)


def handle_get_lemma(ctx: Any, *, name: str) -> dict:
    """Handle get_lemma tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    result = ctx.pipeline.get_lemma(name)
    if result is None:
        return format_error(NOT_FOUND, f"Declaration {name} not found in the index.")
    return _format_success(result)


def handle_find_related(ctx: Any, *, name: str, relation: str, limit: int) -> dict:
    """Handle find_related tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        relation = validate_relation(relation)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, f"Invalid relation '{relation}'.")
    limit = validate_limit(limit)
    result = ctx.pipeline.find_related(name, relation, limit=limit)
    if result is None:
        return format_error(NOT_FOUND, f"Declaration {name} not found in the index.")
    return _format_success(result)


def handle_list_modules(ctx: Any, *, prefix: str) -> dict:
    """Handle list_modules tool call."""
    index_err = _check_index(ctx)
    if index_err is not None:
        return index_err
    results = ctx.pipeline.list_modules(prefix)
    return _format_success(results)
