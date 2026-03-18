"""Entry point for ``python -m poule.server``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import anyio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool, TextContent

from poule.server.handlers import (
    handle_find_related,
    handle_get_lemma,
    handle_list_modules,
    handle_search_by_name,
    handle_search_by_structure,
    handle_search_by_symbols,
    handle_search_by_type,
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
    handle_visualize_proof_state,
    handle_visualize_proof_tree,
    handle_visualize_dependencies,
    handle_visualize_proof_sequence,
)
from poule.server.handlers_wrappers import (
    handle_coq_query,
    handle_notation_query,
    handle_audit_assumptions,
    handle_audit_module,
    handle_compare_assumptions,
    handle_inspect_universes,
    handle_inspect_definition_constraints,
    handle_diagnose_universe_error,
    handle_list_instances,
    handle_list_typeclasses,
    handle_trace_resolution,
    handle_transitive_closure,
    handle_impact_analysis,
    handle_detect_cycles,
    handle_module_summary,
    handle_generate_documentation,
    handle_extract_code,
    handle_check_proof,
    handle_build_project,
    handle_query_packages,
    handle_add_dependency,
    handle_tactic_lookup,
    handle_suggest_tactics,
    handle_inspect_hint_db,
    handle_compare_tactics,
)
from poule.storage.errors import IndexNotFoundError, IndexVersionError

logger = logging.getLogger("poule.server")

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
    # --- Proof interaction tools (Spec §4.3) ---
    Tool(
        name="open_proof_session",
        description="Start an interactive proof session for a named proof in a .v file.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a .v file",
                },
                "proof_name": {
                    "type": "string",
                    "description": "Fully qualified proof name within the file",
                },
            },
            "required": ["file_path", "proof_name"],
        },
    ),
    Tool(
        name="close_proof_session",
        description="Terminate a proof session and release its Coq backend process.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID returned by open_proof_session",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="list_proof_sessions",
        description="List all active proof sessions with metadata.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="observe_proof_state",
        description="Get the current proof state (goals, hypotheses, focused goal).",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="get_proof_state_at_step",
        description="Get the proof state at a specific step index.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "step": {
                    "type": "integer",
                    "description": "Step index (0-based)",
                },
            },
            "required": ["session_id", "step"],
        },
    ),
    Tool(
        name="extract_proof_trace",
        description="Get the full proof trace (all states + tactics).",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="submit_tactic",
        description="Submit a tactic and receive the resulting proof state.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "tactic": {
                    "type": "string",
                    "description": "Coq tactic to execute",
                },
            },
            "required": ["session_id", "tactic"],
        },
    ),
    Tool(
        name="step_backward",
        description="Undo the last tactic, returning to the previous proof state.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="step_forward",
        description="Replay the next tactic from the original proof script.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="submit_tactic_batch",
        description="Submit multiple tactics in sequence. Stops on first failure.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "tactics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tactics to execute in order",
                },
            },
            "required": ["session_id", "tactics"],
        },
    ),
    Tool(
        name="get_proof_premises",
        description="Get premise annotations for all tactic steps in the proof.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="get_step_premises",
        description="Get premise annotations for a single proof step.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "step": {
                    "type": "integer",
                    "description": "Step index (1-based, range [1, total_steps])",
                },
            },
            "required": ["session_id", "step"],
        },
    ),
    # --- Visualization tools (Spec §4.4) ---
    Tool(
        name="visualize_proof_state",
        description="Render the current proof state as a Mermaid diagram.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "step": {
                    "type": "integer",
                    "description": "Step index (default: current step)",
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["summary", "standard", "detailed"],
                    "description": "Diagram detail level (default: standard)",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="visualize_proof_tree",
        description="Render a completed proof trace as a Mermaid proof tree diagram.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="visualize_dependencies",
        description="Render a theorem's dependency subgraph as a Mermaid diagram.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Fully qualified declaration name",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum BFS depth (default: 2)",
                },
                "max_nodes": {
                    "type": "integer",
                    "description": "Maximum nodes in diagram (default: 50)",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="visualize_proof_sequence",
        description="Render step-by-step proof evolution as a sequence of Mermaid diagrams.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["summary", "standard", "detailed"],
                    "description": "Diagram detail level (default: standard)",
                },
            },
            "required": ["session_id"],
        },
    ),
    # --- Wrapper tools ---
    Tool(
        name="coq_query",
        description="Execute a Coq vernacular introspection command (Print, Check, About, Locate, Search, Compute, Eval).",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["Print", "Check", "About", "Locate", "Search", "Compute", "Eval"],
                },
                "argument": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["command", "argument"],
        },
    ),
    Tool(
        name="notation_query",
        description="Inspect Coq notations, scopes, and visibility.",
        inputSchema={
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["print_notation", "locate_notation", "print_scope", "print_visibility"],
                },
                "input": {
                    "type": "string",
                    "description": "Notation string or scope name (not used for print_visibility)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Active proof session ID",
                },
            },
            "required": ["subcommand", "session_id"],
        },
    ),
    Tool(
        name="audit_assumptions",
        description="Audit axiom dependencies for a Coq theorem using Print Assumptions.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["name", "session_id"],
        },
    ),
    Tool(
        name="audit_module",
        description="Audit all theorems in a Coq module for axiom dependencies.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "session_id": {"type": "string"},
                "flag_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["module", "session_id"],
        },
    ),
    Tool(
        name="compare_assumptions",
        description="Compare axiom dependency profiles across multiple Coq theorems.",
        inputSchema={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "session_id": {"type": "string"},
            },
            "required": ["names", "session_id"],
        },
    ),
    Tool(
        name="inspect_universes",
        description="Retrieve the full universe constraint graph from the current Coq environment.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="inspect_definition_constraints",
        description="Retrieve universe constraints for a specific Coq definition.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["name", "session_id"],
        },
    ),
    Tool(
        name="diagnose_universe_error",
        description="Diagnose a Coq universe inconsistency error.",
        inputSchema={
            "type": "object",
            "properties": {
                "error_message": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["error_message", "session_id"],
        },
    ),
    Tool(
        name="list_instances",
        description="List registered instances of a Coq typeclass.",
        inputSchema={
            "type": "object",
            "properties": {
                "typeclass_name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["typeclass_name", "session_id"],
        },
    ),
    Tool(
        name="list_typeclasses",
        description="List all registered typeclasses in the current Coq session.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="trace_resolution",
        description="Trace typeclass instance resolution in the current Coq session.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="transitive_closure",
        description="Compute the transitive closure of dependencies from a declaration.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "max_depth": {"type": "integer"},
                "scope_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="impact_analysis",
        description="Compute the impact set (reverse transitive closure) from a declaration.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "max_depth": {"type": "integer"},
                "scope_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="detect_cycles",
        description="Detect dependency cycles in the indexed Coq project.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="module_summary",
        description="Generate a dependency summary grouped by module.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="generate_documentation",
        description="Generate literate documentation from a Coq source file using Alectryon.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["html", "rst", "latex"],
                    "description": "Output format (default: html)",
                },
                "output_path": {"type": "string"},
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="extract_code",
        description="Extract a Coq definition to OCaml, Haskell, or Scheme.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "definition_name": {"type": "string"},
                "language": {
                    "type": "string",
                    "enum": ["ocaml", "haskell", "scheme"],
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Use Recursive Extraction (default: false)",
                },
                "output_path": {"type": "string"},
            },
            "required": ["session_id", "definition_name", "language"],
        },
    ),
    Tool(
        name="check_proof",
        description="Run the independent Coq proof checker (coqchk) on a compiled file.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a .vo file",
                },
                "include_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "load_paths": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300)",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="build_project",
        description="Execute a Coq project build using make or dune.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
                "target": {"type": "string"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300)",
                },
            },
            "required": ["project_dir"],
        },
    ),
    Tool(
        name="query_packages",
        description="List installed opam packages.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="add_dependency",
        description="Add an opam dependency to the project's .opam file.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
                "package_name": {"type": "string"},
                "version": {
                    "type": "string",
                    "description": "Version constraint (optional)",
                },
            },
            "required": ["project_dir", "package_name"],
        },
    ),
    Tool(
        name="tactic_lookup",
        description="Look up a Coq tactic definition and metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="suggest_tactics",
        description="Get contextual tactic suggestions for the current proof state.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Max suggestions to return (default: 10)",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="inspect_hint_db",
        description="Inspect a Coq hint database.",
        inputSchema={
            "type": "object",
            "properties": {
                "db_name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["db_name"],
        },
    ),
    Tool(
        name="compare_tactics",
        description="Compare two or more Coq tactics structurally.",
        inputSchema={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "session_id": {"type": "string"},
            },
            "required": ["names"],
        },
    ),
]


class _PipelineFacade:
    """Adapts module-level pipeline functions and reader methods into the
    ``ctx.pipeline.*`` interface expected by handler functions."""

    def __init__(self, pipeline_ctx):
        self._ctx = pipeline_ctx

    def search_by_name(self, pattern: str, limit: int):
        from poule.pipeline.search import search_by_name
        return search_by_name(self._ctx, pattern, limit)

    def search_by_type(self, type_expr: str, limit: int):
        from poule.pipeline.search import search_by_type
        return search_by_type(self._ctx, type_expr, limit)

    def search_by_structure(self, expression: str, limit: int):
        from poule.pipeline.search import search_by_structure
        return search_by_structure(self._ctx, expression, limit)

    def search_by_symbols(self, symbols: list[str], limit: int):
        from poule.pipeline.search import search_by_symbols
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

    def build_graph(self):
        from poule.analysis.graph import build_graph
        if not hasattr(self, "_graph_cache"):
            self._graph_cache = build_graph(index_reader=self._ctx.reader)
        return self._graph_cache


class _MermaidFacade:
    """Adapts module-level Mermaid renderer functions into an object interface
    expected by visualization handler functions."""

    @staticmethod
    def render_proof_state(state, detail_level=None):
        from poule.rendering.mermaid_renderer import render_proof_state
        from poule.rendering.types import DetailLevel
        if detail_level is None:
            detail_level = DetailLevel.STANDARD
        return render_proof_state(state, detail_level)

    @staticmethod
    def render_proof_tree(trace):
        from poule.rendering.mermaid_renderer import render_proof_tree
        return render_proof_tree(trace)

    @staticmethod
    def render_dependencies(theorem_name, adjacency_list, *, max_depth=2, max_nodes=50):
        from poule.rendering.mermaid_renderer import render_dependencies
        return render_dependencies(theorem_name, adjacency_list, max_depth, max_nodes)

    @staticmethod
    def render_proof_sequence(trace, detail_level=None):
        from poule.rendering.mermaid_renderer import render_proof_sequence
        from poule.rendering.types import DetailLevel
        if detail_level is None:
            detail_level = DetailLevel.STANDARD
        return render_proof_sequence(trace, detail_level)


class _ServerContext:
    """Context object passed to handler functions."""

    def __init__(self):
        self.index_ready: bool = False
        self.index_version_mismatch: bool = False
        self.found_version: str | None = None
        self.expected_version: str | None = None
        self.pipeline: _PipelineFacade | None = None
        self.session_manager: Any = None
        self.renderer: _MermaidFacade = _MermaidFacade()


def _dispatch_tool(ctx: _ServerContext, name: str, arguments: dict):
    """Route an MCP tool call to the appropriate handler function.

    Returns a dict for sync search tools, or a coroutine for async proof
    interaction tools. The caller (``call_tool``) awaits coroutines.
    """
    # Search tools (sync — return dict directly)
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
    # Proof interaction tools (async — return coroutine, awaited by call_tool)
    elif name == "open_proof_session":
        return handle_open_proof_session(
            ctx,
            file_path=arguments.get("file_path", ""),
            proof_name=arguments.get("proof_name", ""),
        )
    elif name == "close_proof_session":
        return handle_close_proof_session(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "list_proof_sessions":
        return handle_list_proof_sessions(ctx)
    elif name == "observe_proof_state":
        return handle_observe_proof_state(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "get_proof_state_at_step":
        return handle_get_proof_state_at_step(
            ctx,
            session_id=arguments.get("session_id", ""),
            step=arguments.get("step", 0),
        )
    elif name == "extract_proof_trace":
        return handle_extract_proof_trace(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "submit_tactic":
        return handle_submit_tactic(
            ctx,
            session_id=arguments.get("session_id", ""),
            tactic=arguments.get("tactic", ""),
        )
    elif name == "step_backward":
        return handle_step_backward(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "step_forward":
        return handle_step_forward(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "submit_tactic_batch":
        return handle_submit_tactic_batch(
            ctx,
            session_id=arguments.get("session_id", ""),
            tactics=arguments.get("tactics", []),
        )
    elif name == "get_proof_premises":
        return handle_get_proof_premises(
            ctx, session_id=arguments.get("session_id", ""),
        )
    elif name == "get_step_premises":
        return handle_get_step_premises(
            ctx,
            session_id=arguments.get("session_id", ""),
            step=arguments.get("step", 0),
        )
    # Visualization tools (async — return JSON string, wrapped by call_tool)
    elif name == "visualize_proof_state":
        return handle_visualize_proof_state(
            session_id=arguments.get("session_id", ""),
            session_manager=ctx.session_manager,
            renderer=ctx.renderer,
            step=arguments.get("step"),
            detail_level=arguments.get("detail_level"),
        )
    elif name == "visualize_proof_tree":
        return handle_visualize_proof_tree(
            session_id=arguments.get("session_id", ""),
            session_manager=ctx.session_manager,
            renderer=ctx.renderer,
        )
    elif name == "visualize_dependencies":
        return handle_visualize_dependencies(
            name=arguments.get("name", ""),
            search_index=ctx.pipeline,
            renderer=ctx.renderer,
            max_depth=arguments.get("max_depth", 2),
            max_nodes=arguments.get("max_nodes", 50),
        )
    elif name == "visualize_proof_sequence":
        return handle_visualize_proof_sequence(
            session_id=arguments.get("session_id", ""),
            session_manager=ctx.session_manager,
            renderer=ctx.renderer,
            detail_level=arguments.get("detail_level"),
        )
    # Wrapper tools (async — return coroutine, awaited by call_tool)
    elif name == "coq_query":
        return handle_coq_query(
            ctx,
            command=arguments.get("command", ""),
            argument=arguments.get("argument", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "notation_query":
        return handle_notation_query(
            ctx,
            subcommand=arguments.get("subcommand", ""),
            input=arguments.get("input", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "audit_assumptions":
        return handle_audit_assumptions(
            ctx,
            name=arguments.get("name", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "audit_module":
        return handle_audit_module(
            ctx,
            module=arguments.get("module", ""),
            session_id=arguments.get("session_id", ""),
            flag_categories=arguments.get("flag_categories", []),
        )
    elif name == "compare_assumptions":
        return handle_compare_assumptions(
            ctx,
            names=arguments.get("names", []),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "inspect_universes":
        return handle_inspect_universes(
            ctx,
            session_id=arguments.get("session_id", ""),
        )
    elif name == "inspect_definition_constraints":
        return handle_inspect_definition_constraints(
            ctx,
            name=arguments.get("name", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "diagnose_universe_error":
        return handle_diagnose_universe_error(
            ctx,
            error_message=arguments.get("error_message", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "list_instances":
        return handle_list_instances(
            ctx,
            typeclass_name=arguments.get("typeclass_name", ""),
            session_id=arguments.get("session_id", ""),
        )
    elif name == "list_typeclasses":
        return handle_list_typeclasses(
            ctx,
            session_id=arguments.get("session_id", ""),
        )
    elif name == "trace_resolution":
        return handle_trace_resolution(
            ctx,
            session_id=arguments.get("session_id", ""),
        )
    elif name == "transitive_closure":
        return handle_transitive_closure(
            ctx,
            name=arguments.get("name", ""),
            max_depth=arguments.get("max_depth"),
            scope_filter=arguments.get("scope_filter"),
        )
    elif name == "impact_analysis":
        return handle_impact_analysis(
            ctx,
            name=arguments.get("name", ""),
            max_depth=arguments.get("max_depth"),
            scope_filter=arguments.get("scope_filter"),
        )
    elif name == "detect_cycles":
        return handle_detect_cycles(ctx)
    elif name == "module_summary":
        return handle_module_summary(ctx)
    elif name == "generate_documentation":
        return handle_generate_documentation(
            ctx,
            file_path=arguments.get("file_path", ""),
            format=arguments.get("format"),
            output_path=arguments.get("output_path"),
        )
    elif name == "extract_code":
        return handle_extract_code(
            ctx,
            session_id=arguments.get("session_id", ""),
            definition_name=arguments.get("definition_name", ""),
            language=arguments.get("language", ""),
            recursive=arguments.get("recursive"),
            output_path=arguments.get("output_path"),
        )
    elif name == "check_proof":
        return handle_check_proof(
            ctx,
            file_path=arguments.get("file_path", ""),
            include_paths=arguments.get("include_paths"),
            load_paths=arguments.get("load_paths"),
            timeout=arguments.get("timeout"),
        )
    elif name == "build_project":
        return handle_build_project(
            ctx,
            project_dir=arguments.get("project_dir", ""),
            target=arguments.get("target"),
            timeout=arguments.get("timeout"),
        )
    elif name == "query_packages":
        return handle_query_packages(ctx)
    elif name == "add_dependency":
        return handle_add_dependency(
            ctx,
            project_dir=arguments.get("project_dir", ""),
            package_name=arguments.get("package_name", ""),
            version=arguments.get("version"),
        )
    elif name == "tactic_lookup":
        return handle_tactic_lookup(
            ctx,
            name=arguments.get("name", ""),
            session_id=arguments.get("session_id"),
        )
    elif name == "suggest_tactics":
        return handle_suggest_tactics(
            ctx,
            session_id=arguments.get("session_id", ""),
            limit=arguments.get("limit"),
        )
    elif name == "inspect_hint_db":
        return handle_inspect_hint_db(
            ctx,
            db_name=arguments.get("db_name", ""),
            session_id=arguments.get("session_id"),
        )
    elif name == "compare_tactics":
        return handle_compare_tactics(
            ctx,
            names=arguments.get("names", []),
            session_id=arguments.get("session_id"),
        )
    else:
        from poule.server.errors import format_error, PARSE_ERROR
        return format_error(PARSE_ERROR, f"Unknown tool: {name}")


async def _init_context(db_path: Path, log_level: str) -> _ServerContext:
    """Configure logging and initialise the server context (index + session manager)."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    ctx = _ServerContext()

    from poule.session.manager import SessionManager

    async def _default_backend_factory(file_path: str):
        """Placeholder backend factory — will be replaced with real CoqBackend."""
        raise NotImplementedError("Coq backend not yet configured")

    ctx.session_manager = SessionManager(_default_backend_factory)

    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        # Server still starts — all tool calls return INDEX_MISSING
    else:
        try:
            from poule.pipeline.context import create_context
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

    return ctx


def _build_server(ctx: _ServerContext) -> Server:
    """Create the MCP Server and register tool handlers against *ctx*."""
    server = Server("poule")

    @server.list_tools()
    async def list_tools():
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        import inspect
        result = _dispatch_tool(ctx, name, arguments)
        if inspect.isawaitable(result):
            result = await result
        # Visualization handlers return JSON strings; wrap into dict format
        if isinstance(result, str):
            parsed = json.loads(result)
            is_error = "error" in parsed
            result = {
                "content": [{"type": "text", "text": result}],
                "isError": is_error,
            }
        # Convert handler dict response to MCP types
        content = result.get("content", [])
        mcp_content = []
        for item in content:
            if item.get("type") == "text":
                mcp_content.append(TextContent(type="text", text=item["text"]))
        is_error = result.get("isError", False)
        return CallToolResult(content=mcp_content, isError=is_error)

    return server


async def run_server(db_path: Path, log_level: str = "INFO"):
    """Start the MCP server with stdio transport."""
    ctx = await _init_context(db_path, log_level)
    server = _build_server(ctx)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_server_http(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 3000,
    log_level: str = "INFO",
):
    """Start the MCP server with streamable-HTTP transport.

    Listens on ``http://<host>:<port>/mcp`` for Claude Code connections.
    The server runs as a persistent background process; Claude Code reconnects
    to it via the ``url`` field in settings.json rather than spawning a
    subprocess.
    """
    import contextlib

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette

    ctx = await _init_context(db_path, log_level)
    server = _build_server(ctx)

    session_manager = StreamableHTTPSessionManager(app=server)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    # Starlette handles lifespan only; /mcp is routed at the ASGI level
    # because session_manager.handle_request sends responses directly via
    # the ASGI send callable, which is incompatible with Starlette's Route
    # endpoint pattern (expects a Response return value).
    starlette_app = Starlette(lifespan=lifespan)

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            await session_manager.handle_request(scope, receive, send)
        else:
            await starlette_app(scope, receive, send)

    config = uvicorn.Config(app, host=host, port=port, log_level=log_level.lower())
    uv_server = uvicorn.Server(config)
    logger.info("Poule MCP server (streamable-http) listening on %s:%d", host, port)
    await uv_server.serve()


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
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport protocol: stdio (default), streamable-http, or sse (legacy)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="SSE server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="SSE server port (default: 3000)",
    )
    args = parser.parse_args()
    if args.transport in ("sse", "streamable-http"):
        asyncio.run(run_server_http(args.db, args.host, args.port, args.log_level))
    else:
        asyncio.run(run_server(args.db, args.log_level))


if __name__ == "__main__":
    main()
