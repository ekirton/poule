"""MCP protocol-level tests for proof interaction and visualization tools.

These tests spawn the actual MCP server as a subprocess and communicate
with it via the MCP SDK's stdio client, verifying that:
  1. All 48 tools (7 search + 12 proof + 4 visualization + 25 wrapper) are listed
  2. Proof tools are callable and return proper MCP responses
  3. Proof tools work without a search index (Spec §4.5)

Spec: specification/mcp-server.md §2, §4.3, §4.4, §4.5
"""

from __future__ import annotations

import json
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROOF_TOOL_NAMES = [
    "open_proof_session",
    "close_proof_session",
    "list_proof_sessions",
    "observe_proof_state",
    "get_proof_state_at_step",
    "extract_proof_trace",
    "submit_tactic",
    "step_backward",
    "step_forward",
    "submit_tactic_batch",
    "get_proof_premises",
    "get_step_premises",
]

SEARCH_TOOL_NAMES = [
    "search_by_name",
    "search_by_type",
    "search_by_structure",
    "search_by_symbols",
    "get_lemma",
    "find_related",
    "list_modules",
]

VISUALIZATION_TOOL_NAMES = [
    "visualize_proof_state",
    "visualize_proof_tree",
    "visualize_dependencies",
    "visualize_proof_sequence",
]


async def _run_with_session(tmp_path, callback):
    """Spawn the MCP server, initialize a session, run callback, then clean up.

    Uses a helper function instead of a fixture to avoid anyio cancel scope
    issues with pytest-asyncio async generator fixtures.
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "Poule.server", "--db", str(tmp_path / "nonexistent.db")],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await callback(session)


class TestToolListing:
    """Verify all 48 tools (7 search + 12 proof + 4 visualization + 25 wrapper) are advertised."""

    @pytest.mark.asyncio
    async def test_lists_all_48_tools(self, tmp_path):
        async def check(session):
            result = await session.list_tools()
            tool_names = [t.name for t in result.tools]
            assert len(tool_names) == 48
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_all_search_tools_present(self, tmp_path):
        async def check(session):
            result = await session.list_tools()
            tool_names = {t.name for t in result.tools}
            for name in SEARCH_TOOL_NAMES:
                assert name in tool_names, f"Missing search tool: {name}"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_all_proof_tools_present(self, tmp_path):
        async def check(session):
            result = await session.list_tools()
            tool_names = {t.name for t in result.tools}
            for name in PROOF_TOOL_NAMES:
                assert name in tool_names, f"Missing proof tool: {name}"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_all_visualization_tools_present(self, tmp_path):
        async def check(session):
            result = await session.list_tools()
            tool_names = {t.name for t in result.tools}
            for name in VISUALIZATION_TOOL_NAMES:
                assert name in tool_names, f"Missing visualization tool: {name}"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_proof_tool_schemas_have_required_fields(self, tmp_path):
        async def check(session):
            result = await session.list_tools()
            tools_by_name = {t.name: t for t in result.tools}

            schema = tools_by_name["open_proof_session"].inputSchema
            assert "file_path" in schema["properties"]
            assert "proof_name" in schema["properties"]
            assert set(schema["required"]) == {"file_path", "proof_name"}

            schema = tools_by_name["submit_tactic"].inputSchema
            assert "session_id" in schema["properties"]
            assert "tactic" in schema["properties"]
            assert set(schema["required"]) == {"session_id", "tactic"}

            schema = tools_by_name["list_proof_sessions"].inputSchema
            assert schema.get("required") is None or schema["required"] == []
        await _run_with_session(tmp_path, check)


class TestProofToolsWithoutIndex:
    """Proof tools must work when no index is present (Spec §4.5)."""

    @pytest.mark.asyncio
    async def test_list_sessions_returns_empty(self, tmp_path):
        async def check(session):
            result = await session.call_tool("list_proof_sessions", {})
            assert not result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed == []
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_observe_unknown_session_returns_error(self, tmp_path):
        async def check(session):
            result = await session.call_tool(
                "observe_proof_state", {"session_id": "nonexistent"},
            )
            assert result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["error"]["code"] == "SESSION_NOT_FOUND"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_close_unknown_session_returns_error(self, tmp_path):
        async def check(session):
            result = await session.call_tool(
                "close_proof_session", {"session_id": "nonexistent"},
            )
            assert result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["error"]["code"] == "SESSION_NOT_FOUND"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_submit_tactic_empty_returns_parse_error(self, tmp_path):
        async def check(session):
            result = await session.call_tool(
                "submit_tactic", {"session_id": "abc", "tactic": ""},
            )
            assert result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["error"]["code"] == "PARSE_ERROR"
        await _run_with_session(tmp_path, check)

    @pytest.mark.asyncio
    async def test_open_session_empty_path_returns_parse_error(self, tmp_path):
        async def check(session):
            result = await session.call_tool(
                "open_proof_session", {"file_path": "", "proof_name": "test"},
            )
            assert result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["error"]["code"] == "PARSE_ERROR"
        await _run_with_session(tmp_path, check)


class TestSearchToolsIndexMissing:
    """Search tools should return INDEX_MISSING without a database."""

    @pytest.mark.asyncio
    async def test_search_by_name_returns_index_missing(self, tmp_path):
        async def check(session):
            result = await session.call_tool(
                "search_by_name", {"pattern": "test"},
            )
            assert result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["error"]["code"] == "INDEX_MISSING"
        await _run_with_session(tmp_path, check)
