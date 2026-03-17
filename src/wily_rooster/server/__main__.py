"""Entry point for ``python -m wily_rooster.server``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from wily_rooster.server.handlers import (
    handle_find_related,
    handle_get_lemma,
    handle_list_modules,
    handle_search_by_name,
    handle_search_by_structure,
    handle_search_by_symbols,
    handle_search_by_type,
)
from wily_rooster.storage.errors import IndexNotFoundError, IndexVersionError

logger = logging.getLogger("wily_rooster.server")

TOOL_DEFINITIONS = [
    Tool(
        name="search_by_name",
        description="Search for Coq declarations by name pattern (glob or substring).",
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Name pattern — supports * glob wildcard and substring matching",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200)",
                },
            },
            "required": ["pattern"],
        },
    ),
    Tool(
        name="search_by_type",
        description="Multi-channel search for Coq declarations matching a type expression.",
        inputSchema={
            "type": "object",
            "properties": {
                "type_expr": {
                    "type": "string",
                    "description": "A Coq type expression (e.g., 'forall n : nat, n + 0 = n')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200)",
                },
            },
            "required": ["type_expr"],
        },
    ),
    Tool(
        name="search_by_structure",
        description="Find Coq declarations with structurally similar expressions.",
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A Coq expression to match structurally",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200)",
                },
            },
            "required": ["expression"],
        },
    ),
    Tool(
        name="search_by_symbols",
        description="Find Coq declarations sharing mathematical symbols with the query.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of fully qualified symbol names",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200)",
                },
            },
            "required": ["symbols"],
        },
    ),
    Tool(
        name="get_lemma",
        description="Retrieve full details for a specific Coq declaration by name.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Fully qualified declaration name",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="find_related",
        description="Navigate the dependency graph from a Coq declaration.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Fully qualified declaration name",
                },
                "relation": {
                    "type": "string",
                    "enum": ["uses", "used_by", "same_module", "same_typeclass"],
                    "description": "Relationship type to navigate",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200)",
                },
            },
            "required": ["name", "relation"],
        },
    ),
    Tool(
        name="list_modules",
        description="Browse the Coq module hierarchy.",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Module path prefix filter (e.g., 'Coq.Arith')",
                },
            },
        },
    ),
]


class _PipelineFacade:
    """Adapts module-level pipeline functions and reader methods into the
    ``ctx.pipeline.*`` interface expected by handler functions."""

    def __init__(self, pipeline_ctx):
        self._ctx = pipeline_ctx

    def search_by_name(self, pattern: str, limit: int):
        from wily_rooster.pipeline.search import search_by_name
        return search_by_name(self._ctx, pattern, limit)

    def search_by_type(self, type_expr: str, limit: int):
        from wily_rooster.pipeline.search import search_by_type
        return search_by_type(self._ctx, type_expr, limit)

    def search_by_structure(self, expression: str, limit: int):
        from wily_rooster.pipeline.search import search_by_structure
        return search_by_structure(self._ctx, expression, limit)

    def search_by_symbols(self, symbols: list[str], limit: int):
        from wily_rooster.pipeline.search import search_by_symbols
        return search_by_symbols(self._ctx, symbols, limit)

    def get_lemma(self, name: str):
        reader = self._ctx.reader
        decl = reader.get_declaration(name)
        if decl is None:
            return None
        decl_id = decl["id"]
        outgoing = reader.get_dependencies(decl_id, "outgoing", "uses")
        incoming = reader.get_dependencies(decl_id, "incoming", "uses")
        symbols = json.loads(decl.get("symbol_set") or "[]")
        return {
            "name": decl["name"],
            "statement": decl.get("statement", ""),
            "type": decl.get("type_expr", ""),
            "module": decl.get("module", ""),
            "kind": decl.get("kind", ""),
            "score": 1.0,
            "dependencies": [d["target_name"] for d in outgoing],
            "dependents": [d["target_name"] for d in incoming],
            "proof_sketch": "",
            "symbols": symbols if isinstance(symbols, list) else [],
            "node_count": decl.get("node_count", 0),
        }

    def find_related(self, name: str, relation: str, *, limit: int = 50):
        reader = self._ctx.reader
        decl = reader.get_declaration(name)
        if decl is None:
            return None
        decl_id = decl["id"]

        if relation == "uses":
            deps = reader.get_dependencies(decl_id, "outgoing", "uses")
            target_names = [d["target_name"] for d in deps]
        elif relation == "used_by":
            deps = reader.get_dependencies(decl_id, "incoming", "uses")
            target_names = [d["target_name"] for d in deps]
        elif relation == "same_module":
            rows = reader.get_declarations_by_module(decl["module"], exclude_id=decl_id)
            target_names = [r["name"] for r in rows]
        elif relation == "same_typeclass":
            # Two-hop: find typeclasses via instance_of edges, then other instances
            tc_deps = reader.get_dependencies(decl_id, "outgoing", "instance_of")
            tc_ids = [d["dst"] for d in tc_deps]
            target_names = []
            seen = set()
            for tc_id in tc_ids:
                inst_deps = reader.get_dependencies(tc_id, "incoming", "instance_of")
                for d in inst_deps:
                    if d["src"] != decl_id and d["target_name"] not in seen:
                        seen.add(d["target_name"])
                        target_names.append(d["target_name"])
        else:
            return []

        results = []
        for tname in target_names[:limit]:
            target_decl = reader.get_declaration(tname)
            if target_decl:
                results.append({
                    "name": target_decl["name"],
                    "statement": target_decl.get("statement", ""),
                    "type": target_decl.get("type_expr", ""),
                    "module": target_decl.get("module", ""),
                    "kind": target_decl.get("kind", ""),
                    "score": 1.0,
                })
        return results

    def list_modules(self, prefix: str):
        reader = self._ctx.reader
        rows = reader.list_modules(prefix)
        return [{"name": r["module"], "decl_count": r["count"]} for r in rows]


class _ServerContext:
    """Context object passed to handler functions."""

    def __init__(self):
        self.index_ready: bool = False
        self.index_version_mismatch: bool = False
        self.found_version: str | None = None
        self.expected_version: str | None = None
        self.pipeline: _PipelineFacade | None = None


def _dispatch_tool(ctx: _ServerContext, name: str, arguments: dict):
    """Route an MCP tool call to the appropriate handler function."""
    if name == "search_by_name":
        return handle_search_by_name(
            ctx, pattern=arguments.get("pattern", ""), limit=arguments.get("limit", 50)
        )
    elif name == "search_by_type":
        return handle_search_by_type(
            ctx, type_expr=arguments.get("type_expr", ""), limit=arguments.get("limit", 50)
        )
    elif name == "search_by_structure":
        return handle_search_by_structure(
            ctx, expression=arguments.get("expression", ""), limit=arguments.get("limit", 50)
        )
    elif name == "search_by_symbols":
        return handle_search_by_symbols(
            ctx, symbols=arguments.get("symbols", []), limit=arguments.get("limit", 50)
        )
    elif name == "get_lemma":
        return handle_get_lemma(ctx, name=arguments.get("name", ""))
    elif name == "find_related":
        return handle_find_related(
            ctx,
            name=arguments.get("name", ""),
            relation=arguments.get("relation", ""),
            limit=arguments.get("limit", 50),
        )
    elif name == "list_modules":
        return handle_list_modules(ctx, prefix=arguments.get("prefix", ""))
    else:
        from wily_rooster.server.errors import format_error, PARSE_ERROR
        return format_error(PARSE_ERROR, f"Unknown tool: {name}")


async def run_server(db_path: Path, log_level: str = "INFO"):
    """Start the MCP server with stdio transport."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    ctx = _ServerContext()

    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        # Server still starts — all tool calls return INDEX_MISSING
    else:
        try:
            from wily_rooster.pipeline.context import create_context
            pipeline_ctx = create_context(str(db_path))
            ctx.index_ready = True
            ctx.pipeline = _PipelineFacade(pipeline_ctx)
            logger.info("Index loaded from %s", db_path)
        except IndexNotFoundError:
            logger.error("Database file not found: %s", db_path)
        except IndexVersionError as exc:
            ctx.index_ready = True
            ctx.index_version_mismatch = True
            ctx.found_version = getattr(exc, "found", "unknown")
            ctx.expected_version = getattr(exc, "expected", "unknown")
            logger.error("Schema version mismatch: %s", exc)

    server = Server("wily-rooster")

    @server.list_tools()
    async def list_tools():
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        result = _dispatch_tool(ctx, name, arguments)
        # Convert handler dict response to MCP types
        content = result.get("content", [])
        mcp_content = []
        for item in content:
            if item.get("type") == "text":
                mcp_content.append(TextContent(type="text", text=item["text"]))
        is_error = result.get("isError", False)
        return mcp_content

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Coq semantic search MCP server")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("index.db"),
        help="Path to the search index database",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()
    asyncio.run(run_server(args.db, args.log_level))


if __name__ == "__main__":
    main()
