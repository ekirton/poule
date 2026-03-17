"""CLI subcommands for searching, proof replay, and batch extraction."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from poule.cli.formatting import (
    format_lemma_detail,
    format_modules,
    format_proof_trace,
    format_search_results,
)
from poule.session.errors import SessionError
from poule.session.manager import SessionManager
from poule.models.responses import LemmaDetail, Module, SearchResult
from poule.pipeline.context import create_context
from poule.pipeline.parser import ParseError
from poule.pipeline.search import (
    search_by_name,
    search_by_structure,
    search_by_symbols,
    search_by_type,
)
from poule.server.validation import validate_limit
from poule.storage.errors import IndexNotFoundError, IndexVersionError
from poule.cli.download import download_index
from poule.extraction.campaign import run_campaign
from poule.extraction.dependency_graph import extract_dependency_graph
from poule.extraction.reporting import generate_quality_report


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


cli.add_command(download_index)


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
    from poule.session.backend import create_coq_backend
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
# extract
# ---------------------------------------------------------------------------


@cli.command("extract")
@click.argument("project_dirs", nargs=-1, required=True)
@click.option("--output", required=True, type=click.Path(), help="Path for JSON Lines output file.")
@click.option("--name-pattern", default=None, help="Only extract proofs matching this name pattern (P1).")
@click.option("--modules", default=None, help="Comma-separated module prefixes (P1).")
@click.option("--incremental", is_flag=True, default=False, help="Re-extract only changed files (P1).")
@click.option("--resume", "resume_flag", is_flag=True, default=False, help="Resume interrupted extraction (P1).")
@click.option("--include-diffs", is_flag=True, default=False, help="Include proof state diffs (P1).")
@click.option("--timeout", default=60, type=int, help="Per-proof timeout in seconds.")
def cmd_extract(
    project_dirs: tuple[str, ...],
    output: str,
    name_pattern: str | None,
    modules: str | None,
    incremental: bool,
    resume_flag: bool,
    include_diffs: bool,
    timeout: int,
):
    """Batch extract proof traces from Coq project directories."""
    if incremental and resume_flag:
        click.echo("--incremental and --resume cannot be used together.", err=True)
        sys.exit(2)

    # Validate project directories exist
    for d in project_dirs:
        if not Path(d).is_dir():
            click.echo(f"Project directory not found: {d}", err=True)
            sys.exit(1)

    scope_filter = None
    if name_pattern or modules:
        from poule.extraction.types import ScopeFilter
        module_list = [m.strip() for m in modules.split(",")] if modules else None
        scope_filter = ScopeFilter(name_pattern=name_pattern, module_prefixes=module_list)

    kwargs = {}
    if scope_filter is not None:
        kwargs["scope_filter"] = scope_filter
    if include_diffs:
        kwargs["include_diffs"] = include_diffs
    if timeout != 60:
        kwargs["timeout_seconds"] = timeout

    summary = asyncio.run(run_campaign(
        list(project_dirs), output, kwargs,
    ))

    click.echo(f"Extraction complete.", err=True)
    click.echo(f"  Theorems found:    {summary.total_theorems_found}", err=True)
    click.echo(f"  Extracted:         {summary.total_extracted}", err=True)
    click.echo(f"  Failed:            {summary.total_failed}", err=True)
    click.echo(f"  Skipped:           {summary.total_skipped}", err=True)
    click.echo(f"  Output: {output}", err=True)

    if summary.total_extracted == 0 and summary.total_theorems_found > 0:
        click.echo(
            f"Extraction failed: all {summary.total_failed} proofs failed.", err=True,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# extract-deps
# ---------------------------------------------------------------------------


@cli.command("extract-deps")
@click.argument("extraction_output")
@click.option("--output", required=True, type=click.Path(), help="Path for dependency graph output.")
def cmd_extract_deps(extraction_output: str, output: str):
    """Extract theorem dependency graph from extraction output."""
    input_path = Path(extraction_output)
    if not input_path.is_file():
        click.echo(f"Input file not found: {extraction_output}", err=True)
        sys.exit(1)
    try:
        extract_dependency_graph(input_path, Path(output))
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# quality-report
# ---------------------------------------------------------------------------


@cli.command("quality-report")
@click.argument("extraction_output")
@click.option("--json", "json_mode", is_flag=True, default=False, help="Output as JSON.")
@click.option("--output", default=None, type=click.Path(), help="Write report to file.")
def cmd_quality_report(extraction_output: str, json_mode: bool, output: str | None):
    """Generate a quality report from extraction output."""
    input_path = Path(extraction_output)
    if not input_path.is_file():
        click.echo(f"Input file not found: {extraction_output}", err=True)
        sys.exit(1)

    try:
        report = generate_quality_report(input_path)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    if json_mode:
        report_text = _format_quality_report_json(report)
    else:
        report_text = _format_quality_report_human(report)

    if output:
        Path(output).write_text(report_text + "\n", encoding="utf-8")
    else:
        click.echo(report_text)


def _format_quality_report_json(report) -> str:
    """Format QualityReport as compact JSON."""
    obj = {
        "premise_coverage": report.premise_coverage,
        "proof_length_distribution": {
            "min": report.proof_length_distribution.min,
            "max": report.proof_length_distribution.max,
            "mean": report.proof_length_distribution.mean,
            "median": report.proof_length_distribution.median,
            "p25": report.proof_length_distribution.p25,
            "p75": report.proof_length_distribution.p75,
            "p95": report.proof_length_distribution.p95,
        },
        "tactic_vocabulary": [
            {"tactic": tf.tactic, "count": tf.count}
            for tf in report.tactic_vocabulary
        ],
        "per_project": [
            {
                "project_id": p.project_id,
                "premise_coverage": p.premise_coverage,
                "proof_length_distribution": {
                    "min": p.proof_length_distribution.min,
                    "max": p.proof_length_distribution.max,
                    "mean": p.proof_length_distribution.mean,
                    "median": p.proof_length_distribution.median,
                    "p25": p.proof_length_distribution.p25,
                    "p75": p.proof_length_distribution.p75,
                    "p95": p.proof_length_distribution.p95,
                },
                "theorem_count": p.theorem_count,
            }
            for p in report.per_project
        ],
    }
    return json.dumps(obj, separators=(",", ":"))


def _format_quality_report_human(report) -> str:
    """Format QualityReport as human-readable text."""
    d = report.proof_length_distribution
    lines = [
        "Quality Report",
        "==============",
        f"Premise coverage: {report.premise_coverage * 100:.1f}%",
        f"Proof length: min={d.min}, max={d.max}, mean={d.mean}, "
        f"median={d.median}, p25={d.p25}, p75={d.p75}, p95={d.p95}",
        "",
        "Top tactics:",
    ]
    for tf in report.tactic_vocabulary[:20]:
        lines.append(f"  {tf.tactic:<12s} {tf.count}")
    if report.per_project:
        lines.append("")
        lines.append("Per-project:")
        for p in report.per_project:
            lines.append(
                f"  {p.project_id}  ({p.theorem_count} theorems, "
                f"{p.premise_coverage * 100:.1f}% premise coverage)"
            )
    return "\n".join(lines)


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
