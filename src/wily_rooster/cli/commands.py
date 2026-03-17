"""CLI subcommands for searching the Coq/Rocq declaration index and replaying proofs."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from wily_rooster.cli.formatting import (
    format_lemma_detail,
    format_modules,
    format_proof_trace,
    format_search_results,
)
from wily_rooster.session.errors import SessionError
from wily_rooster.session.manager import SessionManager
from wily_rooster.models.responses import LemmaDetail, Module, SearchResult
from wily_rooster.pipeline.context import create_context
from wily_rooster.pipeline.parser import ParseError
from wily_rooster.pipeline.search import (
    search_by_name,
    search_by_structure,
    search_by_symbols,
    search_by_type,
)
from wily_rooster.server.validation import validate_limit
from wily_rooster.storage.errors import IndexNotFoundError, IndexVersionError


def _to_search_result(row: dict, score: float = 1.0) -> SearchResult:
    """Convert a declaration dict from the reader to a SearchResult."""
    return SearchResult(
        name=row["name"],
        statement=row.get("statement", ""),
        type=row.get("type_expr", ""),
        module=row.get("module", ""),
        kind=row.get("kind", ""),
        score=score,
    )


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

_db_option = click.option(
    "--db", required=True, type=click.Path(), help="Path to the SQLite index database."
)
_json_option = click.option("--json", "json_mode", is_flag=True, default=False, help="Output as JSON.")
_limit_option = click.option("--limit", default=50, type=int, help="Maximum number of results (1-200).")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """Wily Rooster — search the Coq/Rocq declaration index."""
    pass


# ---------------------------------------------------------------------------
# search-by-name
# ---------------------------------------------------------------------------


@cli.command("search-by-name")
@_db_option
@_json_option
@_limit_option
@click.argument("pattern")
def cmd_search_by_name(db: str, json_mode: bool, limit: int, pattern: str):
    """Search declarations by name pattern."""
    limit = validate_limit(limit)
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)
    results = search_by_name(ctx, pattern, limit)
    sr_list = _normalize_results(results, ctx)
    output = format_search_results(sr_list, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# search-by-type
# ---------------------------------------------------------------------------


@cli.command("search-by-type")
@_db_option
@_json_option
@_limit_option
@click.argument("type_expr")
def cmd_search_by_type(db: str, json_mode: bool, limit: int, type_expr: str):
    """Search declarations by type expression."""
    limit = validate_limit(limit)
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)
    try:
        results = search_by_type(ctx, type_expr, limit)
    except ParseError as exc:
        click.echo(f"Failed to parse expression: {exc}", err=True)
        sys.exit(1)
    sr_list = _normalize_results(results, ctx)
    output = format_search_results(sr_list, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# search-by-structure
# ---------------------------------------------------------------------------


@cli.command("search-by-structure")
@_db_option
@_json_option
@_limit_option
@click.argument("expression")
def cmd_search_by_structure(db: str, json_mode: bool, limit: int, expression: str):
    """Search declarations by structural similarity."""
    limit = validate_limit(limit)
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)
    try:
        results = search_by_structure(ctx, expression, limit)
    except ParseError as exc:
        click.echo(f"Failed to parse expression: {exc}", err=True)
        sys.exit(1)
    sr_list = _normalize_results(results, ctx)
    output = format_search_results(sr_list, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# search-by-symbols
# ---------------------------------------------------------------------------


@cli.command("search-by-symbols")
@_db_option
@_json_option
@_limit_option
@click.argument("symbols", nargs=-1, required=True)
def cmd_search_by_symbols(db: str, json_mode: bool, limit: int, symbols: tuple[str, ...]):
    """Search declarations by symbol names."""
    limit = validate_limit(limit)
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)
    results = search_by_symbols(ctx, list(symbols), limit)
    sr_list = _normalize_results(results, ctx)
    output = format_search_results(sr_list, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# get-lemma
# ---------------------------------------------------------------------------


@cli.command("get-lemma")
@_db_option
@_json_option
@click.argument("name")
def cmd_get_lemma(db: str, json_mode: bool, name: str):
    """Retrieve full details for a specific declaration."""
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)

    decl = ctx.reader.get_declaration(name)
    if decl is None:
        click.echo(f"Declaration {name} not found in the index.", err=True)
        sys.exit(1)

    decl_id = decl["id"]

    # Outgoing uses dependencies
    out_deps = ctx.reader.get_dependencies(decl_id, "outgoing", "uses")
    dep_names = [d["target_name"] for d in out_deps]

    # Incoming uses dependencies (dependents)
    in_deps = ctx.reader.get_dependencies(decl_id, "incoming", "uses")
    dependent_names = [d["target_name"] for d in in_deps]

    # Symbols
    symbols_raw = decl.get("symbol_set", "[]")
    if isinstance(symbols_raw, str):
        symbols = json.loads(symbols_raw)
    else:
        symbols = symbols_raw or []

    detail = LemmaDetail(
        name=decl["name"],
        statement=decl.get("statement", ""),
        type=decl.get("type_expr", ""),
        module=decl.get("module", ""),
        kind=decl.get("kind", ""),
        score=1.0,
        dependencies=dep_names,
        dependents=dependent_names,
        proof_sketch="",
        symbols=symbols,
        node_count=decl.get("node_count", 1),
    )

    output = format_lemma_detail(detail, json_mode=json_mode)
    click.echo(output)


# ---------------------------------------------------------------------------
# find-related
# ---------------------------------------------------------------------------

_VALID_RELATIONS = ("uses", "used_by", "same_module", "same_typeclass")


@cli.command("find-related")
@_db_option
@_json_option
@_limit_option
@click.option(
    "--relation", required=True, type=click.Choice(_VALID_RELATIONS),
    help="Relation type: uses, used_by, same_module, same_typeclass.",
)
@click.argument("name")
def cmd_find_related(db: str, json_mode: bool, limit: int, relation: str, name: str):
    """Navigate the dependency graph from a known declaration."""
    limit = validate_limit(limit)
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)

    decl = ctx.reader.get_declaration(name)
    if decl is None:
        click.echo(f"Declaration {name} not found in the index.", err=True)
        sys.exit(1)

    decl_id = decl["id"]
    results: list[SearchResult] = []

    if relation == "uses":
        deps = ctx.reader.get_dependencies(decl_id, "outgoing", "uses")
        target_ids = [d["dst"] for d in deps]
        if target_ids:
            rows = ctx.reader.get_declarations_by_ids(target_ids[:limit])
            results = [_to_search_result(r) for r in rows]

    elif relation == "used_by":
        deps = ctx.reader.get_dependencies(decl_id, "incoming", "uses")
        target_ids = [d["src"] for d in deps]
        if target_ids:
            rows = ctx.reader.get_declarations_by_ids(target_ids[:limit])
            results = [_to_search_result(r) for r in rows]

    elif relation == "same_module":
        rows = ctx.reader.get_declarations_by_module(decl["module"], exclude_id=decl_id)
        results = [_to_search_result(r) for r in rows[:limit]]

    elif relation == "same_typeclass":
        # Two-hop: find typeclasses via instance_of edges, then find other instances
        tc_deps = ctx.reader.get_dependencies(decl_id, "outgoing", "instance_of")
        tc_ids = [d["dst"] for d in tc_deps]
        seen = {decl_id}
        for tc_id in tc_ids:
            instance_deps = ctx.reader.get_dependencies(tc_id, "incoming", "instance_of")
            for d in instance_deps:
                if d["src"] not in seen:
                    seen.add(d["src"])
        seen.discard(decl_id)
        if seen:
            rows = ctx.reader.get_declarations_by_ids(list(seen)[:limit])
            results = [_to_search_result(r) for r in rows]

    output = format_search_results(results, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# list-modules
# ---------------------------------------------------------------------------


@cli.command("list-modules")
@_db_option
@_json_option
@click.argument("prefix", default="")
def cmd_list_modules(db: str, json_mode: bool, prefix: str):
    """Browse the module hierarchy."""
    try:
        ctx = create_context(db)
    except (IndexNotFoundError, IndexVersionError) as exc:
        _handle_index_error(exc)

    raw_modules = ctx.reader.list_modules(prefix)
    modules = [
        Module(name=m["module"], decl_count=m["count"])
        for m in raw_modules
    ]

    output = format_modules(modules, json_mode=json_mode)
    if output:
        click.echo(output)
    elif json_mode:
        click.echo("[]")


# ---------------------------------------------------------------------------
# replay-proof
# ---------------------------------------------------------------------------


_json_option_proof = click.option("--json", "json_mode", is_flag=True, default=False, help="Output as JSON.")
_premises_option = click.option("--premises", is_flag=True, default=False, help="Include premise annotations.")


@cli.command("replay-proof")
@_json_option_proof
@_premises_option
@click.argument("file_path")
@click.argument("proof_name")
def cmd_replay_proof(json_mode: bool, premises: bool, file_path: str, proof_name: str):
    """Replay a proof and output the complete trace."""
    try:
        asyncio.run(_replay_proof_async(file_path, proof_name, json_mode, premises))
    except SystemExit:
        raise
    except SessionError as exc:
        _handle_session_error(exc)


async def _replay_proof_async(
    file_path: str, proof_name: str, json_mode: bool, include_premises: bool,
) -> None:
    backend_factory = _get_backend_factory()
    mgr = SessionManager(backend_factory)
    session_id, _ = await mgr.create_session(file_path, proof_name)
    try:
        trace = await mgr.extract_trace(session_id)
        premise_list = None
        if include_premises:
            premise_list = await mgr.get_premises(session_id)
        output = format_proof_trace(trace, premises=premise_list, json_mode=json_mode)
        click.echo(output)
    except SessionError:
        await mgr.close_session(session_id)
        raise
    else:
        await mgr.close_session(session_id)


def _get_backend_factory():
    """Return the default Coq backend factory. Patchable by tests."""
    from wily_rooster.session.backend import create_coq_backend
    return create_coq_backend


_SESSION_ERROR_MESSAGES = {
    "FILE_NOT_FOUND": lambda exc: exc.message,
    "PROOF_NOT_FOUND": lambda exc: exc.message,
    "BACKEND_CRASHED": lambda _: "Backend crashed during proof replay.",
}


def _handle_session_error(exc: SessionError) -> None:
    """Map SessionError to stderr message and exit 1."""
    formatter = _SESSION_ERROR_MESSAGES.get(exc.code)
    msg = formatter(exc) if formatter else (exc.message or str(exc))
    click.echo(msg, err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handle_index_error(exc: Exception) -> None:
    """Print index error to stderr and exit with code 1."""
    if isinstance(exc, IndexNotFoundError):
        click.echo(
            f"Index database not found at {exc}. Run the indexing command to create it.",
            err=True,
        )
    elif isinstance(exc, IndexVersionError):
        click.echo(
            f"Index schema version {exc.found} is incompatible with tool version {exc.expected}. Re-index to update.",
            err=True,
        )
    else:
        click.echo(f"Error: {exc}", err=True)
    sys.exit(1)


def _normalize_results(results: list, ctx) -> list[SearchResult]:
    """Convert pipeline results to SearchResult objects.

    Pipeline functions return mixed types (_ScoredResult, dicts, SearchResult).
    This normalizes them all to SearchResult.
    """
    normalized = []
    for r in results:
        if isinstance(r, SearchResult):
            normalized.append(r)
        elif hasattr(r, "decl_id") and hasattr(r, "score"):
            # _ScoredResult from pipeline — need to look up declaration
            decl_rows = ctx.reader.get_declarations_by_ids([r.decl_id])
            if decl_rows:
                normalized.append(_to_search_result(decl_rows[0], score=r.score))
        elif isinstance(r, dict):
            normalized.append(_to_search_result(r, score=r.get("score", 0.0)))
        elif hasattr(r, "name") and hasattr(r, "score"):
            # Duck-type: something with name and score attributes
            normalized.append(SearchResult(
                name=r.name,
                statement=getattr(r, "statement", ""),
                type=getattr(r, "type", ""),
                module=getattr(r, "module", ""),
                kind=getattr(r, "kind", ""),
                score=r.score,
            ))
    return normalized
