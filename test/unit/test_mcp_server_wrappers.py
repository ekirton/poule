"""TDD tests for MCP protocol wrapper tools.

Tests exercise each wrapper tool through the _dispatch_tool MCP dispatch
layer, verifying that:
  - tool names are registered in TOOL_DEFINITIONS
  - handler functions are routable via _dispatch_tool
  - success responses use the MCP content format
  - error responses use the MCP error format
  - input validation returns structured errors

Spec: specification/mcp-server.md (wrapper tool extensions)
Import paths under test:
  poule.server.handlers_wrappers
  poule.server.__main__ (_dispatch_tool, TOOL_DEFINITIONS)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_handlers_wrappers():
    from Poule.server import handlers_wrappers
    return handlers_wrappers


def _import_dispatch_tool():
    from Poule.server.__main__ import _dispatch_tool
    return _dispatch_tool


def _import_tool_definitions():
    from Poule.server.__main__ import TOOL_DEFINITIONS
    return TOOL_DEFINITIONS


def _import_server_ctx():
    from Poule.server.__main__ import _ServerContext
    return _ServerContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Return a _ServerContext with mocked session_manager and pipeline."""
    _ServerContext = _import_server_ctx()
    c = _ServerContext()
    c.index_ready = True
    c.index_version_mismatch = False
    # Mock session manager
    c.session_manager = MagicMock()
    c.session_manager.send_command = AsyncMock(return_value="")
    c.session_manager.submit_command = AsyncMock(return_value="")
    c.session_manager.observe_state = AsyncMock()
    c.session_manager.coq_query = AsyncMock(return_value="")
    # Mock pipeline
    c.pipeline = MagicMock()
    c.pipeline.build_graph = MagicMock(
        return_value=MagicMock(
            forward_adj={},
            reverse_adj={},
            metadata={},
            nodes=set(),
            edges=set(),
        )
    )
    c.pipeline.find_related = MagicMock(return_value=[])
    return c


def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _dispatch_and_await(ctx, name, arguments):
    """Call _dispatch_tool and await the result if it's a coroutine."""
    import inspect
    _dispatch_tool = _import_dispatch_tool()
    result = _dispatch_tool(ctx, name, arguments)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _parse_response(result):
    """Parse the content JSON from an MCP response dict."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Verify all 25 new wrapper tools appear in TOOL_DEFINITIONS."""

    def _names(self):
        defs = _import_tool_definitions()
        return {t.name for t in defs}

    def test_coq_query_registered(self):
        assert "coq_query" in self._names()

    def test_notation_query_registered(self):
        assert "notation_query" in self._names()

    def test_audit_assumptions_registered(self):
        assert "audit_assumptions" in self._names()

    def test_audit_module_registered(self):
        assert "audit_module" in self._names()

    def test_compare_assumptions_registered(self):
        assert "compare_assumptions" in self._names()

    def test_inspect_universes_registered(self):
        assert "inspect_universes" in self._names()

    def test_inspect_definition_constraints_registered(self):
        assert "inspect_definition_constraints" in self._names()

    def test_diagnose_universe_error_registered(self):
        assert "diagnose_universe_error" in self._names()

    def test_list_instances_registered(self):
        assert "list_instances" in self._names()

    def test_list_typeclasses_registered(self):
        assert "list_typeclasses" in self._names()

    def test_trace_resolution_registered(self):
        assert "trace_resolution" in self._names()

    def test_transitive_closure_registered(self):
        assert "transitive_closure" in self._names()

    def test_impact_analysis_registered(self):
        assert "impact_analysis" in self._names()

    def test_detect_cycles_registered(self):
        assert "detect_cycles" in self._names()

    def test_module_summary_registered(self):
        assert "module_summary" in self._names()

    def test_generate_documentation_registered(self):
        assert "generate_documentation" in self._names()

    def test_extract_code_registered(self):
        assert "extract_code" in self._names()

    def test_check_proof_registered(self):
        assert "check_proof" in self._names()

    def test_build_project_registered(self):
        assert "build_project" in self._names()

    def test_query_packages_registered(self):
        assert "query_packages" in self._names()

    def test_add_dependency_registered(self):
        assert "add_dependency" in self._names()

    def test_tactic_lookup_registered(self):
        assert "tactic_lookup" in self._names()

    def test_suggest_tactics_registered(self):
        assert "suggest_tactics" in self._names()

    def test_inspect_hint_db_registered(self):
        assert "inspect_hint_db" in self._names()

    def test_compare_tactics_registered(self):
        assert "compare_tactics" in self._names()

    def test_profile_proof_registered(self):
        assert "profile_proof" in self._names()


# ---------------------------------------------------------------------------
# TestCoqQuery
# ---------------------------------------------------------------------------

class TestCoqQuery:
    def test_valid_check_command(self, ctx):
        @dataclass
        class _QueryResult:
            command: str
            argument: str
            output: str
            warnings: list

        mock_result = _QueryResult(
            command="Check",
            argument="Nat.add_comm",
            output="forall n m : nat, n + m = m + n",
            warnings=[],
        )
        with patch("Poule.query.handler.coq_query", new_callable=AsyncMock, return_value=mock_result):
            result = _dispatch_and_await(
                ctx, "coq_query", {"command": "Check", "argument": "Nat.add_comm"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["command"] == "Check"
        assert parsed["argument"] == "Nat.add_comm"

    def test_empty_command_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "coq_query", {"command": "", "argument": "Nat.add_comm"}
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert "error" in parsed

    def test_empty_argument_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "coq_query", {"command": "Check", "argument": ""}
        )
        assert result.get("isError") is True

    def test_query_error_translates_to_mcp_error(self, ctx):
        class _QueryError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.query.handler.coq_query",
            new_callable=AsyncMock,
            side_effect=_QueryError("NOT_FOUND", "not found"),
        ):
            result = _dispatch_and_await(
                ctx, "coq_query", {"command": "Check", "argument": "foo"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "NOT_FOUND"

    def test_whitespace_only_command_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "coq_query", {"command": "   ", "argument": "Nat.add"}
        )
        assert result.get("isError") is True

    def test_session_free_passes_process_pool(self, ctx):
        """handle_coq_query passes ctx.process_pool to coq_query for session-free calls."""
        @dataclass
        class _QueryResult:
            command: str
            argument: str
            output: str
            warnings: list

        mock_result = _QueryResult(
            command="Check",
            argument="nat",
            output="nat : Set",
            warnings=[],
        )
        with patch(
            "Poule.query.handler.coq_query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_coq_query:
            ctx.process_pool = MagicMock()
            result = _dispatch_and_await(
                ctx, "coq_query", {"command": "Check", "argument": "nat"}
            )
        assert result.get("isError") is not True
        # Verify process_pool was forwarded to coq_query
        call_kwargs = mock_coq_query.call_args
        assert call_kwargs.kwargs.get("process_pool") is ctx.process_pool

    def test_session_free_with_no_session_id(self, ctx):
        """When session_id is omitted, handle_coq_query passes session_id=None."""
        @dataclass
        class _QueryResult:
            command: str
            argument: str
            output: str
            warnings: list

        mock_result = _QueryResult(
            command="Print",
            argument="nat",
            output="Inductive nat : Set := ...",
            warnings=[],
        )
        with patch(
            "Poule.query.handler.coq_query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_coq_query:
            ctx.process_pool = MagicMock()
            _dispatch_and_await(
                ctx, "coq_query", {"command": "Print", "argument": "nat"}
            )
        call_kwargs = mock_coq_query.call_args
        assert call_kwargs.kwargs.get("session_id") is None


# ---------------------------------------------------------------------------
# TestServerContextProcessPool
# ---------------------------------------------------------------------------

class TestServerContextProcessPool:
    """_ServerContext includes process_pool field for session-free coq_query."""

    def test_process_pool_default_is_none(self):
        _ServerContext = _import_server_ctx()
        ctx = _ServerContext()
        assert ctx.process_pool is None

    def test_process_pool_is_settable(self):
        _ServerContext = _import_server_ctx()
        ctx = _ServerContext()
        ctx.process_pool = "fake_pool"
        assert ctx.process_pool == "fake_pool"


# ---------------------------------------------------------------------------
# TestNotationQuery
# ---------------------------------------------------------------------------

class TestNotationQuery:
    def test_valid_print_notation(self, ctx):
        mock_result = {"notation": "+", "output": "some notation info"}
        with patch(
            "Poule.notation.dispatcher.dispatch_notation_query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "notation_query",
                {"subcommand": "print_notation", "input": "+", "session_id": "s1"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["notation"] == "+"

    def test_unknown_subcommand_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "notation_query",
            {"subcommand": "unknown_cmd", "input": "", "session_id": "s1"},
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert "error" in parsed
        assert "Unknown subcommand" in parsed["error"]["message"]

    def test_empty_subcommand_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "notation_query",
            {"subcommand": "", "input": "", "session_id": "s1"},
        )
        assert result.get("isError") is True

    def test_missing_session_id_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "notation_query",
            {"subcommand": "print_notation", "input": "+", "session_id": ""},
        )
        assert result.get("isError") is True

    def test_print_visibility_subcommand(self, ctx):
        mock_result = {"visibilities": []}
        with patch(
            "Poule.notation.dispatcher.dispatch_notation_query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "notation_query",
                {"subcommand": "print_visibility", "input": "", "session_id": "s1"},
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestAuditAssumptions
# ---------------------------------------------------------------------------

class TestAuditAssumptions:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"theorem": "Nat.add_comm", "axioms": []}
        with patch(
            "Poule.auditing.engine.audit_assumptions",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "audit_assumptions",
                {"name": "Nat.add_comm", "session_id": "s1"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["theorem"] == "Nat.add_comm"

    def test_empty_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "audit_assumptions", {"name": "", "session_id": "s1"}
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "audit_assumptions", {"name": "Nat.add_comm", "session_id": ""}
        )
        assert result.get("isError") is True

    def test_audit_error_translates_to_mcp_error(self, ctx):
        class _AuditError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.auditing.engine.audit_assumptions",
            new_callable=AsyncMock,
            side_effect=_AuditError("AUDIT_FAILED", "audit failed"),
        ):
            result = _dispatch_and_await(
                ctx,
                "audit_assumptions",
                {"name": "Nat.add_comm", "session_id": "s1"},
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "AUDIT_FAILED"


# ---------------------------------------------------------------------------
# TestAuditModule
# ---------------------------------------------------------------------------

class TestAuditModule:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"module": "Stdlib.Arith", "results": []}
        with patch(
            "Poule.auditing.engine.audit_module",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "audit_module",
                {"module": "Stdlib.Arith", "session_id": "s1", "flag_categories": []},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["module"] == "Stdlib.Arith"

    def test_empty_module_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "audit_module",
            {"module": "", "session_id": "s1", "flag_categories": []},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "audit_module",
            {"module": "Stdlib.Arith", "session_id": "", "flag_categories": []},
        )
        assert result.get("isError") is True

    def test_with_flag_categories(self, ctx):
        mock_result = {"module": "Stdlib.Arith", "results": []}
        with patch(
            "Poule.auditing.engine.audit_module",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "audit_module",
                {
                    "module": "Stdlib.Arith",
                    "session_id": "s1",
                    "flag_categories": ["classical"],
                },
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestCompareAssumptions
# ---------------------------------------------------------------------------

class TestCompareAssumptions:
    def test_two_names_succeeds(self, ctx):
        mock_result = {"comparison": []}
        with patch(
            "Poule.auditing.engine.compare_assumptions",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "compare_assumptions",
                {"names": ["Nat.add_comm", "Nat.mul_comm"], "session_id": "s1"},
            )
        assert result.get("isError") is not True

    def test_fewer_than_two_names_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "compare_assumptions",
            {"names": ["Nat.add_comm"], "session_id": "s1"},
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert "error" in parsed

    def test_empty_names_list_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "compare_assumptions",
            {"names": [], "session_id": "s1"},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "compare_assumptions",
            {"names": ["A", "B"], "session_id": ""},
        )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestInspectUniverses
# ---------------------------------------------------------------------------

class TestInspectUniverses:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"constraints": [], "universes": []}
        with patch(
            "Poule.universe.retrieval.retrieve_full_graph",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "inspect_universes", {"session_id": "s1"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "constraints" in parsed

    def test_missing_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "inspect_universes", {"session_id": ""})
        assert result.get("isError") is True

    def test_session_error_translates(self, ctx):
        from Poule.session.errors import SessionError
        with patch(
            "Poule.universe.retrieval.retrieve_full_graph",
            new_callable=AsyncMock,
            side_effect=SessionError("SESSION_NOT_FOUND", "session not found"),
        ):
            result = _dispatch_and_await(
                ctx, "inspect_universes", {"session_id": "s1"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# TestInspectDefinitionConstraints
# ---------------------------------------------------------------------------

class TestInspectDefinitionConstraints:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"name": "MyDef", "constraints": []}
        with patch(
            "Poule.universe.retrieval.retrieve_definition_constraints",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "inspect_definition_constraints",
                {"name": "MyDef", "session_id": "s1"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["name"] == "MyDef"

    def test_empty_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "inspect_definition_constraints",
            {"name": "", "session_id": "s1"},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "inspect_definition_constraints",
            {"name": "MyDef", "session_id": ""},
        )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestDiagnoseUniverseError
# ---------------------------------------------------------------------------

class TestDiagnoseUniverseError:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"diagnosis": "universe inconsistency", "suggestions": []}
        with patch(
            "Poule.universe.diagnosis.diagnose_universe_error",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "diagnose_universe_error",
                {
                    "error_message": "Universe inconsistency detected",
                    "session_id": "s1",
                },
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "diagnosis" in parsed

    def test_empty_error_message_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "diagnose_universe_error",
            {"error_message": "", "session_id": "s1"},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "diagnose_universe_error",
            {"error_message": "some error", "session_id": ""},
        )
        assert result.get("isError") is True

    def test_value_error_translates_to_parse_error(self, ctx):
        with patch(
            "Poule.universe.diagnosis.diagnose_universe_error",
            new_callable=AsyncMock,
            side_effect=ValueError("bad format"),
        ):
            result = _dispatch_and_await(
                ctx,
                "diagnose_universe_error",
                {"error_message": "Universe U < U", "session_id": "s1"},
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# TestListInstances
# ---------------------------------------------------------------------------

class TestListInstances:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"typeclass": "Eq", "instances": []}
        with patch(
            "Poule.typeclass.debugging.list_instances",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "list_instances",
                {"typeclass_name": "Eq", "session_id": "s1"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "instances" in parsed

    def test_empty_typeclass_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "list_instances",
            {"typeclass_name": "", "session_id": "s1"},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "list_instances",
            {"typeclass_name": "Eq", "session_id": ""},
        )
        assert result.get("isError") is True

    def test_typeclass_error_translates(self, ctx):
        class _TypeclassError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.typeclass.debugging.list_instances",
            new_callable=AsyncMock,
            side_effect=_TypeclassError("TC_NOT_FOUND", "typeclass not found"),
        ):
            result = _dispatch_and_await(
                ctx,
                "list_instances",
                {"typeclass_name": "NonExistent", "session_id": "s1"},
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "TC_NOT_FOUND"


# ---------------------------------------------------------------------------
# TestListTypeclasses
# ---------------------------------------------------------------------------

class TestListTypeclasses:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"typeclasses": ["Eq", "Ord"]}
        with patch(
            "Poule.typeclass.debugging.list_typeclasses",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "list_typeclasses", {"session_id": "s1"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "typeclasses" in parsed

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "list_typeclasses", {"session_id": ""})
        assert result.get("isError") is True

    def test_session_error_translates(self, ctx):
        from Poule.session.errors import SessionError
        with patch(
            "Poule.typeclass.debugging.list_typeclasses",
            new_callable=AsyncMock,
            side_effect=SessionError("SESSION_NOT_FOUND", "session not found"),
        ):
            result = _dispatch_and_await(
                ctx, "list_typeclasses", {"session_id": "s1"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# TestTraceResolution
# ---------------------------------------------------------------------------

class TestTraceResolution:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"resolution_trace": []}
        with patch(
            "Poule.typeclass.debugging.trace_resolution",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "trace_resolution", {"session_id": "s1"}
            )
        assert result.get("isError") is not True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "trace_resolution", {"session_id": ""})
        assert result.get("isError") is True

    def test_session_error_translates(self, ctx):
        from Poule.session.errors import SessionError
        with patch(
            "Poule.typeclass.debugging.trace_resolution",
            new_callable=AsyncMock,
            side_effect=SessionError("SESSION_NOT_FOUND", "session not found"),
        ):
            result = _dispatch_and_await(
                ctx, "trace_resolution", {"session_id": "s1"}
            )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestTransitiveClosure
# ---------------------------------------------------------------------------

class TestTransitiveClosure:
    def test_valid_call_with_mock_graph(self, ctx):
        from Poule.analysis.closure import TransitiveClosure
        mock_result = TransitiveClosure(
            root="Nat.add_comm",
            nodes={"Nat.add_comm", "Nat.add"},
            edges={("Nat.add_comm", "Nat.add")},
            depth_map={0: {"Nat.add_comm"}, 1: {"Nat.add"}},
            total_depth=1,
        )
        with patch(
            "Poule.analysis.closure.transitive_closure",
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "transitive_closure", {"name": "Nat.add_comm"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["root"] == "Nat.add_comm"
        assert isinstance(parsed["nodes"], list)
        assert isinstance(parsed["edges"], list)
        assert isinstance(parsed["depth_map"], dict)
        assert all(isinstance(k, str) for k in parsed["depth_map"])

    def test_index_missing_when_not_ready(self, ctx):
        ctx.index_ready = False
        result = _dispatch_and_await(
            ctx, "transitive_closure", {"name": "Nat.add_comm"}
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "INDEX_MISSING"

    def test_empty_name_returns_parse_error(self, ctx):
        result = _dispatch_and_await(ctx, "transitive_closure", {"name": ""})
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "PARSE_ERROR"

    def test_analysis_error_translates(self, ctx):
        class _AnalysisError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.analysis.closure.transitive_closure",
            side_effect=_AnalysisError("NOT_FOUND", "declaration not found"),
        ):
            result = _dispatch_and_await(
                ctx, "transitive_closure", {"name": "Missing.Decl"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "NOT_FOUND"

    def test_invalid_scope_filter_returns_parse_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "transitive_closure",
            {"name": "Nat.add_comm", "scope_filter": ["invalid_filter"]},
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# TestImpactAnalysis
# ---------------------------------------------------------------------------

class TestImpactAnalysis:
    def test_valid_call_with_mock_graph(self, ctx):
        from Poule.analysis.impact import ImpactSet
        mock_result = ImpactSet(
            root="Nat.add_comm",
            impacted_nodes={"Nat.add_comm", "Nat.add_assoc"},
            edges={("Nat.add_comm", "Nat.add_assoc")},
            depth_map={0: {"Nat.add_comm"}, 1: {"Nat.add_assoc"}},
            total_depth=1,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis", {"name": "Nat.add_comm"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["root"] == "Nat.add_comm"
        assert isinstance(parsed["impacted_nodes"], list)
        assert isinstance(parsed["edges"], list)
        assert isinstance(parsed["depth_map"], dict)
        assert all(isinstance(k, str) for k in parsed["depth_map"])

    def test_index_missing_when_not_ready(self, ctx):
        ctx.index_ready = False
        result = _dispatch_and_await(
            ctx, "impact_analysis", {"name": "Nat.add_comm"}
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "INDEX_MISSING"

    def test_empty_name_returns_parse_error(self, ctx):
        result = _dispatch_and_await(ctx, "impact_analysis", {"name": ""})
        assert result.get("isError") is True

    def test_analysis_error_translates(self, ctx):
        class _AnalysisError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.analysis.impact.impact_analysis",
            side_effect=_AnalysisError("NOT_FOUND", "not found"),
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis", {"name": "Missing.Decl"}
            )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestDetectCycles
# ---------------------------------------------------------------------------

class TestDetectCycles:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"cycles": []}
        with patch(
            "Poule.analysis.cycles.detect_cycles",
            return_value=mock_result,
        ):
            result = _dispatch_and_await(ctx, "detect_cycles", {})
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "cycles" in parsed

    def test_index_missing_when_not_ready(self, ctx):
        ctx.index_ready = False
        result = _dispatch_and_await(ctx, "detect_cycles", {})
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "INDEX_MISSING"


# ---------------------------------------------------------------------------
# TestModuleSummary
# ---------------------------------------------------------------------------

class TestModuleSummary:
    def test_valid_call_returns_success(self, ctx):
        mock_result = {"modules": []}
        with patch(
            "Poule.analysis.modules.module_summary",
            return_value=mock_result,
        ):
            result = _dispatch_and_await(ctx, "module_summary", {})
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "modules" in parsed

    def test_index_missing_when_not_ready(self, ctx):
        ctx.index_ready = False
        result = _dispatch_and_await(ctx, "module_summary", {})
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "INDEX_MISSING"


# ---------------------------------------------------------------------------
# TestGenerateDocumentation
# ---------------------------------------------------------------------------

class TestGenerateDocumentation:
    def test_valid_call_returns_result(self, ctx):
        @dataclass
        class _DocumentationResult:
            status: str
            output_path: str
            format: str

        mock_result = _DocumentationResult(
            status="success", output_path="/out/file.html", format="html"
        )
        with patch(
            "Poule.documentation.adapter.generate_documentation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "generate_documentation",
                {"file_path": "/path/to/file.v"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["status"] == "success"

    def test_empty_file_path_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "generate_documentation", {"file_path": ""}
        )
        assert result.get("isError") is True

    def test_value_error_translates_to_parse_error(self, ctx):
        with patch(
            "Poule.documentation.adapter.generate_documentation",
            new_callable=AsyncMock,
            side_effect=ValueError("unsupported format"),
        ):
            result = _dispatch_and_await(
                ctx,
                "generate_documentation",
                {"file_path": "/path/to/file.v", "format": "invalid"},
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# TestExtractCode
# ---------------------------------------------------------------------------

class TestExtractCode:
    def test_valid_call_returns_result(self, ctx):
        mock_result = {
            "definition": "myFn",
            "language": "ocaml",
            "code": "let myFn = ...",
        }
        with patch(
            "Poule.extraction.handler.extract_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "extract_code",
                {
                    "session_id": "s1",
                    "definition_name": "myFn",
                    "language": "ocaml",
                },
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["language"] == "ocaml"

    def test_empty_definition_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "extract_code",
            {"session_id": "s1", "definition_name": "", "language": "ocaml"},
        )
        assert result.get("isError") is True

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "extract_code",
            {"session_id": "", "definition_name": "myFn", "language": "ocaml"},
        )
        assert result.get("isError") is True

    def test_empty_language_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "extract_code",
            {"session_id": "s1", "definition_name": "myFn", "language": ""},
        )
        assert result.get("isError") is True

    def test_session_error_translates(self, ctx):
        from Poule.session.errors import SessionError
        with patch(
            "Poule.extraction.handler.extract_code",
            new_callable=AsyncMock,
            side_effect=SessionError("SESSION_NOT_FOUND", "session not found"),
        ):
            result = _dispatch_and_await(
                ctx,
                "extract_code",
                {"session_id": "s1", "definition_name": "myFn", "language": "ocaml"},
            )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestCheckProof
# ---------------------------------------------------------------------------

class TestCheckProof:
    def test_valid_call_returns_result(self, ctx):
        mock_result = {"status": "ok", "file": "/path/to/file.vo"}
        with patch(
            "Poule.checker.adapter.check_proof",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "check_proof", {"file_path": "/path/to/file.vo"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["status"] == "ok"

    def test_empty_file_path_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "check_proof", {"file_path": ""})
        assert result.get("isError") is True

    def test_with_include_paths_and_timeout(self, ctx):
        mock_result = {"status": "ok", "file": "/path/to/file.vo"}
        with patch(
            "Poule.checker.adapter.check_proof",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx,
                "check_proof",
                {
                    "file_path": "/path/to/file.vo",
                    "include_paths": ["/include1"],
                    "timeout": 60,
                },
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestBuildProject
# ---------------------------------------------------------------------------

class TestBuildProject:
    def test_valid_call_returns_result(self, ctx):
        mock_result = {"status": "success", "output": ""}
        with patch(
            "Poule.build.adapter.execute_build",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "build_project", {"project_dir": "/my/project"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["status"] == "success"

    def test_empty_project_dir_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "build_project", {"project_dir": ""})
        assert result.get("isError") is True

    def test_build_system_error_translates(self, ctx):
        class _BuildSystemError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.build.adapter.execute_build",
            new_callable=AsyncMock,
            side_effect=_BuildSystemError("BUILD_FAILED", "make failed"),
        ):
            result = _dispatch_and_await(
                ctx, "build_project", {"project_dir": "/my/project"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "BUILD_FAILED"


# ---------------------------------------------------------------------------
# TestQueryPackages
# ---------------------------------------------------------------------------

class TestQueryPackages:
    def test_valid_call_returns_list(self, ctx):
        with patch(
            "Poule.build.adapter.query_installed_packages",
            new_callable=AsyncMock,
            return_value=[("coq", "8.18.0"), ("coq-stdlib", "8.18.0")],
        ):
            result = _dispatch_and_await(ctx, "query_packages", {})
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "coq"
        assert parsed[0]["version"] == "8.18.0"

    def test_build_system_error_translates(self, ctx):
        class _BuildSystemError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.build.adapter.query_installed_packages",
            new_callable=AsyncMock,
            side_effect=_BuildSystemError("OPAM_ERROR", "opam not found"),
        ):
            result = _dispatch_and_await(ctx, "query_packages", {})
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "OPAM_ERROR"


# ---------------------------------------------------------------------------
# TestAddDependency
# ---------------------------------------------------------------------------

class TestAddDependency:
    def test_valid_call_returns_added_true(self, ctx):
        with patch("Poule.build.adapter.add_dependency", return_value=None):
            result = _dispatch_and_await(
                ctx,
                "add_dependency",
                {"project_dir": "/my/project", "package_name": "coq-equations"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["added"] is True
        assert parsed["package"] == "coq-equations"

    def test_empty_package_name_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "add_dependency",
            {"project_dir": "/my/project", "package_name": ""},
        )
        assert result.get("isError") is True

    def test_empty_project_dir_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx,
            "add_dependency",
            {"project_dir": "", "package_name": "coq-equations"},
        )
        assert result.get("isError") is True

    def test_build_system_error_translates(self, ctx):
        class _BuildSystemError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.build.adapter.add_dependency",
            side_effect=_BuildSystemError("OPAM_ERROR", "opam failed"),
        ):
            result = _dispatch_and_await(
                ctx,
                "add_dependency",
                {"project_dir": "/my/project", "package_name": "coq-equations"},
            )
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# TestTacticLookup
# ---------------------------------------------------------------------------

class TestTacticLookup:
    def test_valid_call_returns_tactic_info(self, ctx):
        mock_result = {"name": "omega", "description": "Solves linear arithmetic."}
        with patch(
            "Poule.tactics.lookup.tactic_lookup",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "tactic_lookup", {"name": "omega"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["name"] == "omega"

    def test_empty_name_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "tactic_lookup", {"name": ""})
        assert result.get("isError") is True

    def test_tactic_doc_error_translates(self, ctx):
        class _TacticDocError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.tactics.lookup.tactic_lookup",
            new_callable=AsyncMock,
            side_effect=_TacticDocError("TACTIC_NOT_FOUND", "tactic not found"),
        ):
            result = _dispatch_and_await(
                ctx, "tactic_lookup", {"name": "unknown_tactic"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "TACTIC_NOT_FOUND"

    def test_session_id_is_optional(self, ctx):
        mock_result = {"name": "ring", "description": "Ring tactic."}
        with patch(
            "Poule.tactics.lookup.tactic_lookup",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "tactic_lookup", {"name": "ring"}
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestSuggestTactics
# ---------------------------------------------------------------------------

class TestSuggestTactics:
    def test_valid_call_returns_list(self, ctx):
        mock_result = [{"name": "omega", "confidence": 0.9}]
        with patch(
            "Poule.tactics.suggest.tactic_suggest",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "suggest_tactics", {"session_id": "s1"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "omega"

    def test_empty_session_id_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "suggest_tactics", {"session_id": ""})
        assert result.get("isError") is True

    def test_session_error_translates(self, ctx):
        from Poule.session.errors import SessionError
        with patch(
            "Poule.tactics.suggest.tactic_suggest",
            new_callable=AsyncMock,
            side_effect=SessionError("SESSION_NOT_FOUND", "session not found"),
        ):
            result = _dispatch_and_await(
                ctx, "suggest_tactics", {"session_id": "s1"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "SESSION_NOT_FOUND"

    def test_custom_limit(self, ctx):
        mock_result = []
        with patch(
            "Poule.tactics.suggest.tactic_suggest",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "suggest_tactics", {"session_id": "s1", "limit": 5}
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestInspectHintDb
# ---------------------------------------------------------------------------

class TestInspectHintDb:
    def test_valid_call_returns_hint_database(self, ctx):
        mock_result = {"db_name": "core", "hints": []}
        with patch(
            "Poule.tactics.hints.hint_inspect",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "inspect_hint_db", {"db_name": "core"}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert parsed["db_name"] == "core"

    def test_empty_db_name_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "inspect_hint_db", {"db_name": ""})
        assert result.get("isError") is True

    def test_tactic_doc_error_translates(self, ctx):
        class _TacticDocError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.tactics.hints.hint_inspect",
            new_callable=AsyncMock,
            side_effect=_TacticDocError("DB_NOT_FOUND", "hint db not found"),
        ):
            result = _dispatch_and_await(
                ctx, "inspect_hint_db", {"db_name": "nonexistent"}
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "DB_NOT_FOUND"

    def test_session_id_is_optional(self, ctx):
        mock_result = {"db_name": "rewrite_db", "hints": []}
        with patch(
            "Poule.tactics.hints.hint_inspect",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "inspect_hint_db", {"db_name": "rewrite_db"}
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestCompareTactics
# ---------------------------------------------------------------------------

class TestCompareTactics:
    def test_two_names_succeeds(self, ctx):
        mock_result = {"tactics": ["omega", "lia"], "comparison": {}}
        with patch(
            "Poule.tactics.compare.tactic_compare",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "compare_tactics", {"names": ["omega", "lia"]}
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "tactics" in parsed

    def test_fewer_than_two_names_returns_error(self, ctx):
        result = _dispatch_and_await(
            ctx, "compare_tactics", {"names": ["omega"]}
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert "error" in parsed

    def test_empty_names_list_returns_error(self, ctx):
        result = _dispatch_and_await(ctx, "compare_tactics", {"names": []})
        assert result.get("isError") is True

    def test_tactic_doc_error_translates(self, ctx):
        class _TacticDocError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message

        with patch(
            "Poule.tactics.compare.tactic_compare",
            new_callable=AsyncMock,
            side_effect=_TacticDocError("TACTIC_NOT_FOUND", "tactic not found"),
        ):
            result = _dispatch_and_await(
                ctx, "compare_tactics", {"names": ["omega", "unknown"]}
            )
        assert result.get("isError") is True

    def test_session_id_is_optional(self, ctx):
        mock_result = {"tactics": ["omega", "lia"], "comparison": {}}
        with patch(
            "Poule.tactics.compare.tactic_compare",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = _dispatch_and_await(
                ctx, "compare_tactics", {"names": ["omega", "lia"]}
            )
        assert result.get("isError") is not True


# ---------------------------------------------------------------------------
# TestDotFilePathParameter — Spec §4.1 MCP Tool dot_file_path Parameter
# ---------------------------------------------------------------------------

class TestDotFilePathParameter:
    """Spec §4.1: All graph-dependent MCP tools accept optional dot_file_path."""

    def test_impact_analysis_schema_includes_dot_file_path(self):
        """impact_analysis tool schema includes dot_file_path string parameter."""
        defs = _import_tool_definitions()
        tool = next(t for t in defs if t.name == "impact_analysis")
        assert "dot_file_path" in tool.inputSchema["properties"]
        assert tool.inputSchema["properties"]["dot_file_path"]["type"] == "string"

    def test_transitive_closure_schema_includes_dot_file_path(self):
        """transitive_closure tool schema includes dot_file_path string parameter."""
        defs = _import_tool_definitions()
        tool = next(t for t in defs if t.name == "transitive_closure")
        assert "dot_file_path" in tool.inputSchema["properties"]
        assert tool.inputSchema["properties"]["dot_file_path"]["type"] == "string"

    def test_detect_cycles_schema_includes_dot_file_path(self):
        """detect_cycles tool schema includes dot_file_path string parameter."""
        defs = _import_tool_definitions()
        tool = next(t for t in defs if t.name == "detect_cycles")
        assert "dot_file_path" in tool.inputSchema["properties"]
        assert tool.inputSchema["properties"]["dot_file_path"]["type"] == "string"

    def test_module_summary_schema_includes_dot_file_path(self):
        """module_summary tool schema includes dot_file_path string parameter."""
        defs = _import_tool_definitions()
        tool = next(t for t in defs if t.name == "module_summary")
        assert "dot_file_path" in tool.inputSchema["properties"]
        assert tool.inputSchema["properties"]["dot_file_path"]["type"] == "string"

    def test_dot_file_path_not_required(self):
        """dot_file_path is optional (not in required list) for all 4 tools."""
        defs = _import_tool_definitions()
        for tool_name in ("impact_analysis", "transitive_closure", "detect_cycles", "module_summary"):
            tool = next(t for t in defs if t.name == tool_name)
            required = tool.inputSchema.get("required", [])
            assert "dot_file_path" not in required, f"{tool_name} should not require dot_file_path"

    def test_impact_analysis_with_dot_file_path(self, ctx):
        """When dot_file_path is provided, handler builds graph from DOT file."""
        import tempfile, textwrap
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        dot_content = textwrap.dedent('''\
            digraph {
                "A" -> "B"
                "B" -> "C"
            }
        ''')
        with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
            f.write(dot_content)
            dot_path = f.name

        fake_result = _FakeImpact(
            root="C", impacted_nodes={"C", "B", "A"},
            edges={("B", "C"), ("A", "B")}, depth_map={0: {"C"}, 1: {"B"}, 2: {"A"}},
            total_depth=2,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ) as mock_ia:
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "C", "dot_file_path": dot_path},
            )
        assert result.get("isError") is not True
        # Verify build_graph was called with dot_file_path
        ctx.pipeline.build_graph.assert_called_with(dot_file_path=dot_path)

    def test_impact_analysis_without_dot_file_uses_storage(self, ctx):
        """When dot_file_path is omitted, handler uses storage (default)."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="X", impacted_nodes={"X"}, edges=set(),
            depth_map={0: {"X"}}, total_depth=0,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis", {"name": "X"},
            )
        assert result.get("isError") is not True
        # Verify build_graph was called without dot_file_path
        ctx.pipeline.build_graph.assert_called_with()

    def test_dot_file_not_found_returns_error(self, ctx):
        """When dot_file_path points to nonexistent file, FILE_NOT_FOUND error."""
        from Poule.analysis.errors import AnalysisError
        ctx.pipeline.build_graph = MagicMock(
            side_effect=AnalysisError("FILE_NOT_FOUND", "DOT file not found: /no/such.dot")
        )
        result = _dispatch_and_await(
            ctx, "impact_analysis",
            {"name": "X", "dot_file_path": "/no/such.dot"},
        )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "FILE_NOT_FOUND"


# ---------------------------------------------------------------------------
# TestSparseResultHint — Spec §4.5 Sparse-Result Hint
# ---------------------------------------------------------------------------

class TestSparseResultHint:
    """Spec §4.5: When impact_analysis returns only root from storage, include hint."""

    def test_hint_present_when_root_only_from_storage(self, ctx):
        """When impact set contains only root and source is storage, response has hint."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="Nat.add_comm", impacted_nodes={"Nat.add_comm"},
            edges=set(), depth_map={0: {"Nat.add_comm"}}, total_depth=0,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis", {"name": "Nat.add_comm"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "hint" in parsed
        assert "dot_file_path" in parsed["hint"]

    def test_no_hint_when_impact_has_dependents(self, ctx):
        """When impact set has dependents, no hint is included."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="nat", impacted_nodes={"nat", "add_comm", "add_assoc"},
            edges={("add_comm", "nat"), ("add_assoc", "nat")},
            depth_map={0: {"nat"}, 1: {"add_comm", "add_assoc"}},
            total_depth=1,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis", {"name": "nat"},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "hint" not in parsed

    def test_no_hint_when_dot_file_used(self, ctx):
        """When graph is from DOT file, no hint even if result has root only."""
        import tempfile, textwrap
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        dot_content = textwrap.dedent('''\
            digraph {
                "X" -> "Y"
            }
        ''')
        with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
            f.write(dot_content)
            dot_path = f.name

        fake_result = _FakeImpact(
            root="X", impacted_nodes={"X"}, edges=set(),
            depth_map={0: {"X"}}, total_depth=0,
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "X", "dot_file_path": dot_path},
            )
        assert result.get("isError") is not True
        parsed = _parse_response(result)
        assert "hint" not in parsed


# ---------------------------------------------------------------------------
# Name Aliasing -- Spec §4.3 / §4.5 (Name Aliasing MCP Handler)
# ---------------------------------------------------------------------------

class TestNameAliasingImpactAnalysis:
    """Spec §4.5: MCP handler applies bidirectional Coq.*/Stdlib.* aliasing."""

    def test_coq_prefix_aliased_to_stdlib(self, ctx):
        """When graph has Stdlib.* name but user passes Coq.*, handler aliases."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="Stdlib.Init.Nat.add_comm",
            impacted_nodes={"Stdlib.Init.Nat.add_comm", "MyLib.foo"},
            edges={("MyLib.foo", "Stdlib.Init.Nat.add_comm")},
            depth_map={0: {"Stdlib.Init.Nat.add_comm"}, 1: {"MyLib.foo"}},
            total_depth=1,
        )
        # Graph contains Stdlib.* names (canonical), not Coq.*
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={"Stdlib.Init.Nat.add_comm": set()},
            reverse_adj={"Stdlib.Init.Nat.add_comm": {"MyLib.foo"}},
            metadata={"Stdlib.Init.Nat.add_comm": MagicMock(module="Stdlib.Init.Nat")},
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ) as mock_ia:
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "Coq.Init.Nat.add_comm"},
            )
            # Handler should pass the aliased name to the engine
            mock_ia.assert_called_once()
            call_args = mock_ia.call_args
            assert call_args[0][1] == "Stdlib.Init.Nat.add_comm"
        assert result.get("isError") is not True

    def test_corelib_prefix_aliased_to_coq(self, ctx):
        """When graph has Coq.* name but user passes Corelib.*, handler aliases."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="Stdlib.Init.Nat.add_comm",
            impacted_nodes={"Stdlib.Init.Nat.add_comm"},
            edges=set(),
            depth_map={0: {"Stdlib.Init.Nat.add_comm"}},
            total_depth=0,
        )
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={"Stdlib.Init.Nat.add_comm": set()},
            reverse_adj={"Stdlib.Init.Nat.add_comm": set()},
            metadata={"Stdlib.Init.Nat.add_comm": MagicMock(module="Stdlib.Init.Nat")},
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ) as mock_ia:
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "Corelib.Init.Nat.add_comm"},
            )
            mock_ia.assert_called_once()
            call_args = mock_ia.call_args
            assert call_args[0][1] == "Stdlib.Init.Nat.add_comm"
        assert result.get("isError") is not True

    def test_no_aliasing_when_name_exists(self, ctx):
        """When name exists directly in graph, no aliasing is applied."""
        from dataclasses import dataclass

        @dataclass
        class _FakeImpact:
            root: str
            impacted_nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeImpact(
            root="Stdlib.Init.Nat.add_comm",
            impacted_nodes={"Stdlib.Init.Nat.add_comm"},
            edges=set(),
            depth_map={0: {"Stdlib.Init.Nat.add_comm"}},
            total_depth=0,
        )
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={"Stdlib.Init.Nat.add_comm": set()},
            reverse_adj={"Stdlib.Init.Nat.add_comm": set()},
            metadata={"Stdlib.Init.Nat.add_comm": MagicMock(module="Stdlib.Init.Nat")},
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            return_value=fake_result,
        ) as mock_ia:
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "Stdlib.Init.Nat.add_comm"},
            )
            mock_ia.assert_called_once()
            call_args = mock_ia.call_args
            assert call_args[0][1] == "Stdlib.Init.Nat.add_comm"
        assert result.get("isError") is not True

    def test_not_found_when_neither_name_nor_alias_exists(self, ctx):
        """When neither original nor aliased name exists, NOT_FOUND propagates."""
        from Poule.analysis.errors import AnalysisError
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={},
            reverse_adj={},
            metadata={},
        )
        with patch(
            "Poule.analysis.impact.impact_analysis",
            side_effect=AnalysisError("NOT_FOUND", "Declaration X not found"),
        ):
            result = _dispatch_and_await(
                ctx, "impact_analysis",
                {"name": "Nonexistent.Name"},
            )
        assert result.get("isError") is True
        parsed = _parse_response(result)
        assert parsed["error"]["code"] == "NOT_FOUND"


class TestNameAliasingTransitiveClosure:
    """Spec §4.3: MCP handler applies bidirectional Coq.*/Stdlib.* aliasing."""

    def test_coq_prefix_aliased_to_stdlib(self, ctx):
        """When graph has Stdlib.* name but user passes Coq.*, handler aliases."""
        from dataclasses import dataclass

        @dataclass
        class _FakeClosure:
            root: str
            nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeClosure(
            root="Stdlib.Init.Nat.add_comm",
            nodes={"Stdlib.Init.Nat.add_comm"},
            edges=set(),
            depth_map={0: {"Stdlib.Init.Nat.add_comm"}},
            total_depth=0,
        )
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={"Stdlib.Init.Nat.add_comm": set()},
            reverse_adj={"Stdlib.Init.Nat.add_comm": set()},
            metadata={"Stdlib.Init.Nat.add_comm": MagicMock(module="Stdlib.Init.Nat")},
        )
        with patch(
            "Poule.analysis.closure.transitive_closure",
            return_value=fake_result,
        ) as mock_tc:
            result = _dispatch_and_await(
                ctx, "transitive_closure",
                {"name": "Coq.Init.Nat.add_comm"},
            )
            mock_tc.assert_called_once()
            call_args = mock_tc.call_args
            assert call_args[0][1] == "Stdlib.Init.Nat.add_comm"
        assert result.get("isError") is not True

    def test_corelib_prefix_aliased_to_coq(self, ctx):
        """When graph has Coq.* name but user passes Corelib.*, handler aliases."""
        from dataclasses import dataclass

        @dataclass
        class _FakeClosure:
            root: str
            nodes: set
            edges: set
            depth_map: dict
            total_depth: int

        fake_result = _FakeClosure(
            root="Stdlib.Init.Nat.add_comm",
            nodes={"Stdlib.Init.Nat.add_comm"},
            edges=set(),
            depth_map={0: {"Stdlib.Init.Nat.add_comm"}},
            total_depth=0,
        )
        ctx.pipeline.build_graph.return_value = MagicMock(
            forward_adj={"Stdlib.Init.Nat.add_comm": set()},
            reverse_adj={"Stdlib.Init.Nat.add_comm": set()},
            metadata={"Stdlib.Init.Nat.add_comm": MagicMock(module="Stdlib.Init.Nat")},
        )
        with patch(
            "Poule.analysis.closure.transitive_closure",
            return_value=fake_result,
        ) as mock_tc:
            result = _dispatch_and_await(
                ctx, "transitive_closure",
                {"name": "Corelib.Init.Nat.add_comm"},
            )
            mock_tc.assert_called_once()
            call_args = mock_tc.call_args
            assert call_args[0][1] == "Stdlib.Init.Nat.add_comm"
        assert result.get("isError") is not True
