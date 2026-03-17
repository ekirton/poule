"""MCP tool handler functions for the poule server."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from poule.server.errors import (
    format_error,
    INDEX_MISSING,
    INDEX_VERSION_MISMATCH,
    NOT_FOUND,
    PARSE_ERROR,
    PROOF_INCOMPLETE,
)
from poule.session.errors import SessionError
from poule.server.validation import (
    validate_string,
    validate_limit,
    validate_symbols,
    validate_relation,
)


def _serialize(obj: Any) -> Any:
    """Convert dataclass instances to dicts for JSON serialization."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def _format_success(data: Any) -> dict:
    """Format a successful response as an MCP content dict."""
    return {
        "content": [{"type": "text", "text": json.dumps(_serialize(data))}],
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


# ---------------------------------------------------------------------------
# Proof interaction handlers (Spec §4.3)
# ---------------------------------------------------------------------------

def _session_error_response(exc: SessionError) -> dict:
    """Translate a SessionError into an MCP error response."""
    return format_error(exc.code, exc.message)


async def handle_open_proof_session(
    ctx: Any, *, file_path: str, proof_name: str,
) -> dict:
    """Handle open_proof_session tool call."""
    try:
        file_path = validate_string(file_path)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "file_path must be a non-empty string.")
    try:
        proof_name = validate_string(proof_name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "proof_name must be a non-empty string.")
    try:
        session_id, state = await ctx.session_manager.create_session(file_path, proof_name)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success({"session_id": session_id, "state": _serialize(state)})


async def handle_close_proof_session(ctx: Any, *, session_id: str) -> dict:
    """Handle close_proof_session tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        await ctx.session_manager.close_session(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success({"closed": True})


async def handle_list_proof_sessions(ctx: Any) -> dict:
    """Handle list_proof_sessions tool call."""
    sessions = await ctx.session_manager.list_sessions()
    return _format_success(sessions)


async def handle_observe_proof_state(ctx: Any, *, session_id: str) -> dict:
    """Handle observe_proof_state tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        state = await ctx.session_manager.observe_state(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(state)


async def handle_get_proof_state_at_step(
    ctx: Any, *, session_id: str, step: int,
) -> dict:
    """Handle get_proof_state_at_step tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        state = await ctx.session_manager.get_state_at_step(session_id, step)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(state)


async def handle_extract_proof_trace(ctx: Any, *, session_id: str) -> dict:
    """Handle extract_proof_trace tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        trace = await ctx.session_manager.extract_trace(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(trace)


async def handle_submit_tactic(
    ctx: Any, *, session_id: str, tactic: str,
) -> dict:
    """Handle submit_tactic tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        tactic = validate_string(tactic)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "tactic must be a non-empty string.")
    try:
        state = await ctx.session_manager.submit_tactic(session_id, tactic)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(state)


async def handle_step_backward(ctx: Any, *, session_id: str) -> dict:
    """Handle step_backward tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        state = await ctx.session_manager.step_backward(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(state)


async def handle_step_forward(ctx: Any, *, session_id: str) -> dict:
    """Handle step_forward tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        tactic, state = await ctx.session_manager.step_forward(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success({"tactic": tactic, "state": _serialize(state)})


async def handle_submit_tactic_batch(
    ctx: Any, *, session_id: str, tactics: list[str],
) -> dict:
    """Handle submit_tactic_batch tool call (P1)."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    if not tactics:
        return format_error(PARSE_ERROR, "tactics must be a non-empty list.")
    try:
        results = await ctx.session_manager.submit_tactic_batch(session_id, tactics)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(results)


async def handle_get_proof_premises(ctx: Any, *, session_id: str) -> dict:
    """Handle get_proof_premises tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        annotations = await ctx.session_manager.get_premises(session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(annotations)


async def handle_get_step_premises(
    ctx: Any, *, session_id: str, step: int,
) -> dict:
    """Handle get_step_premises tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        annotation = await ctx.session_manager.get_step_premises(session_id, step)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(annotation)


# ---------------------------------------------------------------------------
# Visualization handlers (Spec §4.4)
# ---------------------------------------------------------------------------

def _format_json(data: Any) -> str:
    """Format response data as a JSON string."""
    return json.dumps(_serialize(data))


def _format_json_error(code: str, message: str) -> str:
    """Format an error as a JSON string."""
    return json.dumps({"error": {"code": code, "message": message}})


async def handle_visualize_proof_state(
    *,
    session_id: str,
    session_manager: Any,
    renderer: Any,
    step: int | None = None,
    detail_level: str | None = None,
) -> str:
    """Handle visualize_proof_state tool call.

    Returns a JSON string with {mermaid, step_index} or {error}.
    """
    from poule.server.validation import validate_detail_level

    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return _format_json_error(PARSE_ERROR, "session_id must be a non-empty string.")

    dl = validate_detail_level(detail_level)

    try:
        if step is not None:
            state = await session_manager.get_state_at_step(session_id, step)
        else:
            state = await session_manager.observe_state(session_id)
    except SessionError as exc:
        return _format_json_error(exc.code, exc.message)

    mermaid = renderer.render_proof_state(state, dl)
    return _format_json({"mermaid": mermaid, "step_index": state.step_index})


async def handle_visualize_proof_tree(
    *,
    session_id: str,
    session_manager: Any,
    renderer: Any,
) -> str:
    """Handle visualize_proof_tree tool call.

    Returns a JSON string with {mermaid, total_steps} or {error}.
    """
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return _format_json_error(PARSE_ERROR, "session_id must be a non-empty string.")

    try:
        trace = await session_manager.extract_trace(session_id)
    except SessionError as exc:
        return _format_json_error(exc.code, exc.message)

    # Check proof is complete
    if trace.steps and not trace.steps[-1].state.is_complete:
        return _format_json_error(
            PROOF_INCOMPLETE,
            f"Cannot visualize proof tree: proof in session {session_id} is not yet complete.",
        )

    mermaid = renderer.render_proof_tree(trace)
    return _format_json({"mermaid": mermaid, "total_steps": trace.total_steps})


async def handle_visualize_dependencies(
    *,
    name: str,
    search_index: Any,
    renderer: Any,
    max_depth: int = 2,
    max_nodes: int = 50,
) -> str:
    """Handle visualize_dependencies tool call.

    Returns a JSON string with {mermaid, node_count, truncated} or {error}.
    """
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return _format_json_error(PARSE_ERROR, "name must be a non-empty string.")

    # Check index availability
    if hasattr(search_index, "index_ready") and not search_index.index_ready:
        return _format_json_error(INDEX_MISSING, "Index database not found. Run the indexing command to create it.")

    # Resolve dependency data from search index
    try:
        adjacency_list = _resolve_dependencies(search_index, name, max_depth)
    except Exception:
        return _format_json_error(NOT_FOUND, f"Declaration {name} not found in the index.")

    result = renderer.render_dependencies(name, adjacency_list, max_depth=max_depth, max_nodes=max_nodes)
    return _format_json({
        "mermaid": result.mermaid,
        "node_count": result.node_count,
        "truncated": result.truncated,
    })


def _resolve_dependencies(
    search_index: Any,
    name: str,
    max_depth: int,
) -> dict[str, list[dict[str, str]]]:
    """Resolve dependency adjacency list from the search index via find_related."""
    from collections import deque

    adjacency_list: dict[str, list[dict[str, str]]] = {}
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    queue.append((name, 0))
    visited.add(name)

    while queue:
        current, depth = queue.popleft()
        related = search_index.find_related(current, "uses")

        deps = []
        if related:
            for item in related:
                dep_name = item.get("name", item) if isinstance(item, dict) else getattr(item, "name", str(item))
                dep_kind = item.get("kind", "lemma") if isinstance(item, dict) else getattr(item, "kind", "lemma")
                deps.append({"name": dep_name, "kind": dep_kind})
                if dep_name not in visited and depth < max_depth:
                    visited.add(dep_name)
                    queue.append((dep_name, depth + 1))

        adjacency_list[current] = deps

    return adjacency_list


async def handle_visualize_proof_sequence(
    *,
    session_id: str,
    session_manager: Any,
    renderer: Any,
    detail_level: str | None = None,
) -> str:
    """Handle visualize_proof_sequence tool call.

    Returns a JSON string with {diagrams: [{step_index, tactic, mermaid}, ...]}.
    """
    from poule.server.validation import validate_detail_level

    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return _format_json_error(PARSE_ERROR, "session_id must be a non-empty string.")

    dl = validate_detail_level(detail_level)

    try:
        trace = await session_manager.extract_trace(session_id)
    except SessionError as exc:
        if exc.code == "STEP_OUT_OF_RANGE":
            return _format_json_error(
                PROOF_INCOMPLETE,
                f"Cannot visualize proof sequence: session {session_id} has no original proof script.",
            )
        return _format_json_error(exc.code, exc.message)

    entries = renderer.render_proof_sequence(trace, dl)
    diagrams = [_serialize(entry) for entry in entries]
    return _format_json({"diagrams": diagrams})


# ---------------------------------------------------------------------------
# Proof search handlers (Spec §4.5)
# ---------------------------------------------------------------------------

def _clamp_positive(value: float | int, default: float | int) -> float | int:
    """Clamp a value to be positive; use default if None."""
    if value is None:
        return default
    return max(1, value)


async def handle_proof_search(
    *,
    search_engine: Any,
    session_id: str,
    timeout: float | None = 30,
    max_depth: int | None = 10,
    max_breadth: int | None = 20,
) -> dict:
    """Handle proof_search MCP tool call (spec §4.5)."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")

    timeout = _clamp_positive(timeout, 30)
    max_depth = int(_clamp_positive(max_depth, 10))
    max_breadth = int(_clamp_positive(max_breadth, 20))

    try:
        result = await search_engine.proof_search(
            session_id, timeout, max_depth, max_breadth,
        )
    except SessionError as exc:
        return _session_error_response(exc)

    return _format_success(result)


async def handle_fill_admits(
    *,
    orchestrator: Any,
    file_path: str,
    timeout_per_admit: float | None = 30,
    max_depth: int | None = 10,
    max_breadth: int | None = 20,
) -> dict:
    """Handle fill_admits MCP tool call (spec §4.5)."""
    try:
        file_path = validate_string(file_path)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "file_path must be a non-empty string.")

    timeout_per_admit = _clamp_positive(timeout_per_admit, 30)
    max_depth = int(_clamp_positive(max_depth, 10))
    max_breadth = int(_clamp_positive(max_breadth, 20))

    try:
        result = await orchestrator.fill_admits(
            file_path, timeout_per_admit, max_depth, max_breadth,
        )
    except SessionError as exc:
        return _session_error_response(exc)

    return _format_success(result)
