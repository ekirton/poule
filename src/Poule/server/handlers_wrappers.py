"""MCP tool handler functions for wrapper tool categories."""

from __future__ import annotations

from typing import Any

from Poule.server.handlers import (
    _format_success,
    _serialize,
    _session_error_response,
    _check_index,
)
from Poule.server.errors import (
    format_error,
    PARSE_ERROR,
    NOT_FOUND,
    SESSION_NOT_FOUND,
)
from Poule.server.validation import validate_string
from Poule.session.errors import SessionError


# ---------------------------------------------------------------------------
# Vernacular introspection (spec: vernacular-introspection.md)
# ---------------------------------------------------------------------------

async def handle_coq_query(ctx: Any, *, command: str, argument: str, session_id: str) -> dict:
    """Handle coq_query tool call."""
    try:
        command = validate_string(command)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "command must be a non-empty string.")
    try:
        argument = validate_string(argument)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "argument must be a non-empty string.")
    try:
        from Poule.query.handler import coq_query, QueryError
        result = await coq_query(
            command,
            argument,
            session_id=session_id or None,
            session_manager=ctx.session_manager,
            process_pool=ctx.process_pool,
        )
    except Exception as exc:
        # Check if it's a QueryError (has .code and .message)
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success({
        "command": result.command,
        "argument": result.argument,
        "output": result.output,
        "warnings": result.warnings,
    })


# ---------------------------------------------------------------------------
# Notation inspection (spec: notation-inspection.md)
# ---------------------------------------------------------------------------

_VALID_NOTATION_SUBCOMMANDS = frozenset(
    {"print_notation", "locate_notation", "print_scope", "print_visibility"}
)


async def handle_notation_query(
    ctx: Any, *, subcommand: str, input: str, session_id: str
) -> dict:
    """Handle notation_query tool call."""
    try:
        subcommand = validate_string(subcommand)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "subcommand must be a non-empty string.")
    if subcommand not in _VALID_NOTATION_SUBCOMMANDS:
        return format_error(
            PARSE_ERROR,
            f"Unknown subcommand: {subcommand!r}. Valid: "
            + ", ".join(sorted(_VALID_NOTATION_SUBCOMMANDS)),
        )
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")

    if subcommand in ("print_notation", "locate_notation"):
        notation = input
        scope_name = ""
    elif subcommand == "print_scope":
        notation = ""
        scope_name = input
    else:  # print_visibility
        notation = ""
        scope_name = ""

    try:
        from Poule.notation.dispatcher import dispatch_notation_query, NotationError
        result = await dispatch_notation_query(
            command=subcommand,
            session_id=session_id,
            session_manager=ctx.session_manager,
            notation=notation,
            scope_name=scope_name,
        )
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


# ---------------------------------------------------------------------------
# Assumption auditing (spec: assumption-auditing.md)
# ---------------------------------------------------------------------------

async def handle_audit_assumptions(ctx: Any, *, name: str, session_id: str) -> dict:
    """Handle audit_assumptions tool call."""
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.auditing.engine import audit_assumptions
        result = await audit_assumptions(ctx.session_manager, name, session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_audit_module(
    ctx: Any, *, module: str, session_id: str, flag_categories: list
) -> dict:
    """Handle audit_module tool call."""
    try:
        module = validate_string(module)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "module must be a non-empty string.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.auditing.engine import audit_module
        result = await audit_module(
            ctx.session_manager, module, flag_categories or None, session_id
        )
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_compare_assumptions(
    ctx: Any, *, names: list, session_id: str
) -> dict:
    """Handle compare_assumptions tool call."""
    if not names or len(names) < 2:
        return format_error(PARSE_ERROR, "names must be a list with at least 2 items.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.auditing.engine import compare_assumptions
        result = await compare_assumptions(ctx.session_manager, names, session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


# ---------------------------------------------------------------------------
# Universe constraint inspection (spec: universe-inspection.md)
# ---------------------------------------------------------------------------

async def handle_inspect_universes(ctx: Any, *, session_id: str) -> dict:
    """Handle inspect_universes tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.universe.retrieval import retrieve_full_graph
        result = await retrieve_full_graph(ctx.session_manager, session_id)
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(result)


async def handle_inspect_definition_constraints(
    ctx: Any, *, name: str, session_id: str
) -> dict:
    """Handle inspect_definition_constraints tool call."""
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.universe.retrieval import retrieve_definition_constraints
        result = await retrieve_definition_constraints(
            ctx.session_manager, session_id, name
        )
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(result)


async def handle_diagnose_universe_error(
    ctx: Any, *, error_message: str, session_id: str
) -> dict:
    """Handle diagnose_universe_error tool call."""
    try:
        error_message = validate_string(error_message)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "error_message must be a non-empty string.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.universe.diagnosis import diagnose_universe_error
        result = await diagnose_universe_error(
            ctx.session_manager, session_id, error_message, {}
        )
    except ValueError as exc:
        return format_error(PARSE_ERROR, str(exc))
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(result)


# ---------------------------------------------------------------------------
# Typeclass debugging (spec: typeclass-debugging.md)
# ---------------------------------------------------------------------------

async def handle_list_instances(
    ctx: Any, *, typeclass_name: str, session_id: str
) -> dict:
    """Handle list_instances tool call."""
    try:
        typeclass_name = validate_string(typeclass_name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "typeclass_name must be a non-empty string.")
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.typeclass.debugging import list_instances, TypeclassError
        result = await list_instances(session_id, typeclass_name, ctx.session_manager)
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_list_typeclasses(ctx: Any, *, session_id: str) -> dict:
    """Handle list_typeclasses tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.typeclass.debugging import list_typeclasses
        result = await list_typeclasses(session_id, ctx.session_manager)
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_trace_resolution(ctx: Any, *, session_id: str) -> dict:
    """Handle trace_resolution tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.typeclass.debugging import trace_resolution
        result = await trace_resolution(session_id, ctx.session_manager)
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


# ---------------------------------------------------------------------------
# Deep dependency analysis (spec: deep-dependency-analysis.md)
# ---------------------------------------------------------------------------

def _parse_scope_filters(filter_specs: list[str]) -> list | None:
    """Convert filter spec strings to callables for the analysis engine."""
    if not filter_specs:
        return None
    from Poule.analysis.filters import same_project, module_prefix, exclude_prefix
    filters = []
    for spec in filter_specs:
        if spec == "same_project":
            filters.append(same_project)
        elif spec.startswith("module_prefix:"):
            prefix = spec[len("module_prefix:"):]
            filters.append(module_prefix(prefix))
        elif spec.startswith("exclude_prefix:"):
            prefix = spec[len("exclude_prefix:"):]
            filters.append(exclude_prefix(prefix))
        else:
            raise ValueError(
                f"Unknown filter: {spec!r}. Valid: same_project, "
                f"module_prefix:<prefix>, exclude_prefix:<prefix>"
            )
    return filters or None


async def handle_transitive_closure(
    ctx: Any, *, name: str, max_depth: int | None, scope_filter: list | None,
    dot_file_path: str | None = None,
) -> dict:
    """Handle transitive_closure tool call."""
    if dot_file_path is None:
        index_err = _check_index(ctx)
        if index_err is not None:
            return index_err
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        parsed_filters = _parse_scope_filters(scope_filter or [])
    except ValueError as exc:
        return format_error(PARSE_ERROR, str(exc))
    try:
        if dot_file_path is not None:
            graph = ctx.pipeline.build_graph(dot_file_path=dot_file_path)
        else:
            graph = ctx.pipeline.build_graph()
        from Poule.analysis.closure import transitive_closure
        result = transitive_closure(graph, name, max_depth or None, parsed_filters)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


_SPARSE_RESULT_HINT = (
    "The index contains only type-level and axiom-level dependency edges. "
    "Proof-body dependencies (theorem-to-theorem) require importing a "
    "dependency graph via import_dependencies or providing a coq-dpdgraph "
    "DOT file via the dot_file_path parameter."
)


async def handle_impact_analysis(
    ctx: Any, *, name: str, max_depth: int | None, scope_filter: list | None,
    dot_file_path: str | None = None,
) -> dict:
    """Handle impact_analysis tool call."""
    if dot_file_path is None:
        index_err = _check_index(ctx)
        if index_err is not None:
            return index_err
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        parsed_filters = _parse_scope_filters(scope_filter or [])
    except ValueError as exc:
        return format_error(PARSE_ERROR, str(exc))
    try:
        if dot_file_path is not None:
            graph = ctx.pipeline.build_graph(dot_file_path=dot_file_path)
        else:
            graph = ctx.pipeline.build_graph()
        from Poule.analysis.impact import impact_analysis
        result = impact_analysis(graph, name, max_depth or None, parsed_filters)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    # Sparse-result hint: when graph is from storage and result has only root
    if dot_file_path is None and len(result.impacted_nodes) == 1:
        serialized = _serialize(result)
        serialized["hint"] = _SPARSE_RESULT_HINT
        return _format_success(serialized)
    return _format_success(result)


async def handle_detect_cycles(
    ctx: Any, *, dot_file_path: str | None = None,
) -> dict:
    """Handle detect_cycles tool call."""
    if dot_file_path is None:
        index_err = _check_index(ctx)
        if index_err is not None:
            return index_err
    try:
        if dot_file_path is not None:
            graph = ctx.pipeline.build_graph(dot_file_path=dot_file_path)
        else:
            graph = ctx.pipeline.build_graph()
        from Poule.analysis.cycles import detect_cycles
        result = detect_cycles(graph)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_module_summary(
    ctx: Any, *, dot_file_path: str | None = None,
) -> dict:
    """Handle module_summary tool call."""
    if dot_file_path is None:
        index_err = _check_index(ctx)
        if index_err is not None:
            return index_err
    try:
        if dot_file_path is not None:
            graph = ctx.pipeline.build_graph(dot_file_path=dot_file_path)
        else:
            graph = ctx.pipeline.build_graph()
        from Poule.analysis.modules import module_summary
        result = module_summary(graph)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


# ---------------------------------------------------------------------------
# Literate documentation (spec: literate-documentation.md)
# ---------------------------------------------------------------------------

async def handle_generate_documentation(
    ctx: Any, *, file_path: str, format: str | None, output_path: str | None
) -> dict:
    """Handle generate_documentation tool call."""
    try:
        file_path = validate_string(file_path)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "file_path must be a non-empty string.")
    try:
        from Poule.documentation.adapter import generate_documentation, DocumentationRequest
        request = DocumentationRequest(
            input_file=file_path,
            format=format or "html",
            output_path=output_path or None,
        )
        result = await generate_documentation(request)
    except ValueError as exc:
        return format_error(PARSE_ERROR, str(exc))
    return _format_success(result)


# ---------------------------------------------------------------------------
# Code extraction management (spec: code-extraction-management.md)
# ---------------------------------------------------------------------------

async def handle_extract_code(
    ctx: Any,
    *,
    session_id: str,
    definition_name: str,
    language: str,
    recursive: bool | None,
    output_path: str | None,
) -> dict:
    """Handle extract_code tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        definition_name = validate_string(definition_name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "definition_name must be a non-empty string.")
    try:
        language = validate_string(language)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "language must be a non-empty string.")
    try:
        from Poule.extraction.handler import extract_code
        result = await extract_code(
            ctx.session_manager,
            session_id,
            definition_name,
            language,
            recursive or False,
            output_path or None,
        )
    except SessionError as exc:
        return _session_error_response(exc)
    return _format_success(result)


# ---------------------------------------------------------------------------
# Independent proof checking (spec: independent-proof-checking.md)
# ---------------------------------------------------------------------------

async def handle_check_proof(
    ctx: Any,
    *,
    file_path: str,
    include_paths: list | None,
    load_paths: list | None,
    timeout: int | None,
) -> dict:
    """Handle check_proof tool call."""
    try:
        file_path = validate_string(file_path)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "file_path must be a non-empty string.")
    from Poule.checker.adapter import check_proof
    from Poule.checker.types import CheckRequest
    request = CheckRequest(
        mode="single",
        file_path=file_path,
        include_paths=include_paths or [],
        load_paths=load_paths or [],
        timeout_seconds=timeout or 300,
    )
    result = await check_proof(request)
    return _format_success(result)


# ---------------------------------------------------------------------------
# Build system integration (spec: build-system-integration.md)
# ---------------------------------------------------------------------------

async def handle_build_project(
    ctx: Any, *, project_dir: str, target: str | None, timeout: int | None
) -> dict:
    """Handle build_project tool call."""
    try:
        project_dir = validate_string(project_dir)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "project_dir must be a non-empty string.")
    try:
        from Poule.build.adapter import execute_build
        from Poule.build.types import BuildRequest
        from Poule.build.errors import BuildSystemError
        request = BuildRequest(
            project_dir=project_dir,
            target=target or None,
            timeout=timeout or 300,
        )
        result = await execute_build(request)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_query_packages(ctx: Any) -> dict:
    """Handle query_packages tool call."""
    try:
        from Poule.build.adapter import query_installed_packages
        from Poule.build.errors import BuildSystemError
        result = await query_installed_packages()
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success([{"name": n, "version": v} for n, v in result])


async def handle_add_dependency(
    ctx: Any, *, project_dir: str, package_name: str, version: str | None
) -> dict:
    """Handle add_dependency tool call."""
    try:
        project_dir = validate_string(project_dir)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "project_dir must be a non-empty string.")
    try:
        package_name = validate_string(package_name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "package_name must be a non-empty string.")
    try:
        from Poule.build.adapter import add_dependency
        from Poule.build.errors import BuildSystemError
        add_dependency(project_dir, package_name, version or None)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success({"added": True, "package": package_name})


# ---------------------------------------------------------------------------
# Tactic documentation (spec: tactic-documentation.md)
# ---------------------------------------------------------------------------

def _make_coq_query_fn(ctx: Any):
    """Build the coq_query callable needed by tactic tools."""
    async def _coq_query_fn(command: str, argument: str, session_id: str | None = None):
        from Poule.query.handler import coq_query
        return await coq_query(
            command,
            argument,
            session_id=session_id,
            session_manager=ctx.session_manager,
            process_pool=ctx.process_pool,
        )
    return _coq_query_fn


async def handle_tactic_lookup(
    ctx: Any, *, name: str, session_id: str | None
) -> dict:
    """Handle tactic_lookup tool call."""
    try:
        name = validate_string(name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "name must be a non-empty string.")
    try:
        from Poule.tactics.lookup import tactic_lookup, TacticDocError
        coq_query_fn = _make_coq_query_fn(ctx)
        result = await tactic_lookup(
            name,
            session_id=session_id or None,
            coq_query=coq_query_fn,
        )
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_suggest_tactics(
    ctx: Any, *, session_id: str, limit: int | None
) -> dict:
    """Handle suggest_tactics tool call."""
    try:
        session_id = validate_string(session_id)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "session_id must be a non-empty string.")
    try:
        from Poule.tactics.suggest import tactic_suggest
        result = await tactic_suggest(
            session_id,
            limit=limit or 10,
            observe_proof_state=ctx.session_manager.observe_state,
        )
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_inspect_hint_db(
    ctx: Any, *, db_name: str, session_id: str | None
) -> dict:
    """Handle inspect_hint_db tool call."""
    try:
        db_name = validate_string(db_name)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "db_name must be a non-empty string.")
    try:
        from Poule.tactics.hints import hint_inspect
        from Poule.tactics.lookup import TacticDocError
        coq_query_fn = _make_coq_query_fn(ctx)
        result = await hint_inspect(
            db_name,
            session_id=session_id or None,
            coq_query=coq_query_fn,
        )
    except SessionError as exc:
        return _session_error_response(exc)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


async def handle_compare_tactics(
    ctx: Any, *, names: list, session_id: str | None
) -> dict:
    """Handle compare_tactics tool call."""
    if not names or len(names) < 2:
        return format_error(PARSE_ERROR, "names must be a list with at least 2 items.")
    try:
        from Poule.tactics.compare import tactic_compare
        from Poule.tactics.lookup import TacticDocError
        coq_query_fn = _make_coq_query_fn(ctx)
        result = await tactic_compare(
            names,
            session_id=session_id or None,
            coq_query=coq_query_fn,
        )
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)


# ---------------------------------------------------------------------------
# Proof profiling (spec: proof-profiling.md)
# ---------------------------------------------------------------------------

async def handle_profile_proof(
    ctx: Any,
    *,
    file_path: str,
    lemma_name: str | None,
    mode: str | None,
    baseline_path: str | None,
    timeout_seconds: int | None,
) -> dict:
    """Handle profile_proof tool call."""
    try:
        file_path = validate_string(file_path)
    except (ValueError, Exception):
        return format_error(PARSE_ERROR, "file_path must be a non-empty string.")
    try:
        from Poule.profiler.types import ProfileRequest
        from Poule.profiler.engine import profile_proof

        request = ProfileRequest(
            file_path=file_path,
            lemma_name=lemma_name or None,
            mode=mode or "timing",
            baseline_path=baseline_path or None,
            timeout_seconds=timeout_seconds or 300,
        )
        result = await profile_proof(request)
    except ValueError as exc:
        return format_error(NOT_FOUND, str(exc))
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "message"):
            return format_error(exc.code, exc.message)
        raise
    return _format_success(result)
