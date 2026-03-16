# Task: MCP Server Implementation

## 1. Overview

Implement the MCP server component as specified in `specification/mcp-server.md`. This is the protocol translation layer that exposes the Coq semantic search system as a set of MCP tools callable by Claude Code over stdio. The server validates inputs, dispatches to the retrieval pipeline, formats responses, and reports structured errors.

The MCP server is the outermost layer of the system — the entry point for all user-facing queries. It depends on the pipeline layer (for search orchestration) and the storage layer (for database access and startup validation). It does not implement any search logic itself.

---

## 2. Dependencies

### Must be implemented first

| Dependency | Specification | Reason |
|------------|--------------|--------|
| Storage schema and read path | `specification/storage.md` | Server opens the database at startup, reads `index_meta` for validation, and the pipeline queries all tables |
| Data structures | `specification/data-structures.md` | `ExprTree`, `WlHistogram`, `ScoredResult` types used by the pipeline |
| FTS5 channel | `specification/channel-fts.md` | Required by `search_by_name` (sole channel) and `search_by_type` (one of three channels) |
| MePo channel | `specification/channel-mepo.md` | Required by `search_by_symbols` and `search_by_type` |
| WL kernel channel | `specification/channel-wl-kernel.md` | Required by `search_by_structure` and `search_by_type` |
| Fusion | `specification/fusion.md` | Required by `search_by_structure` and `search_by_type` |
| Pipeline orchestration | `specification/pipeline.md` | Dispatches all search tool calls to the appropriate channel combinations |

### External dependencies (Python packages)

| Package | Purpose |
|---------|---------|
| `mcp` | Official MCP Python SDK (PyPI: `mcp`). Provides the `Server` class, stdio transport, tool registration decorators, and JSON-RPC message handling. |
| `pydantic` | Input validation for tool parameters (pulled in by `mcp` SDK) |

### Can be stubbed for initial development

- Coq expression parsing (`search_by_type`, `search_by_structure`) can initially accept raw strings and skip syntactic validation, returning `PARSE_ERROR` as a stub.
- WL, TED, collapse-match, and const-jaccard channels can be stubbed with empty result lists to test the server shell.

---

## 3. Module Structure

```
src/
  coq_search/
    __init__.py
    __main__.py                     # entry point: `python -m coq_search`
    server/
      __init__.py
      app.py                        # MCP server setup, tool registration, lifecycle
      tools.py                      # 7 tool handler functions
      validation.py                 # input validation logic
      errors.py                     # error codes, error response formatting
      response_types.py             # SearchResult, LemmaDetail, Module dataclasses
      formatting.py                 # convert internal ScoredResult + DB rows to response types
    pipeline/
      __init__.py
      orchestrator.py               # dispatch logic per tool (Sections 3-6 of pipeline.md)
      ... (channel modules, fusion — covered by separate tasks)
    storage/
      __init__.py
      database.py                   # SQLite connection management, read-only access
      queries.py                    # SQL query functions for declarations, dependencies, modules
      loader.py                     # startup data loading (WL histograms, symbol index, symbol_freq)
      ... (schema creation — covered by storage task)
    types/
      __init__.py
      data_structures.py            # ExprTree, NodeLabel, WlHistogram, ScoredResult
```

---

## 4. Implementation Steps

### Step 1: Project scaffolding

Create the Python package structure and configuration files.

**Files to create:**
- `src/coq_search/__init__.py` — package marker, `__version__ = "0.1.0"`
- `src/coq_search/__main__.py` — entry point (see Step 7)
- `src/coq_search/server/__init__.py`
- `src/coq_search/server/errors.py` (Step 2)
- `src/coq_search/server/response_types.py` (Step 3)
- `src/coq_search/server/validation.py` (Step 4)
- `src/coq_search/server/formatting.py` (Step 5)
- `src/coq_search/server/tools.py` (Step 6)
- `src/coq_search/server/app.py` (Step 7)
- `pyproject.toml` — project metadata, dependencies (`mcp>=1.0`), entry point configuration

**`pyproject.toml` key sections:**
```toml
[project]
name = "coq-search"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["mcp>=1.0"]

[project.scripts]
coq-search = "coq_search.__main__:main"
```

### Step 2: Error codes and error response formatting

**File:** `src/coq_search/server/errors.py`

Define the error contract from specification Section 7.

```python
from enum import Enum

class ErrorCode(str, Enum):
    INDEX_MISSING = "INDEX_MISSING"
    INDEX_VERSION_MISMATCH = "INDEX_VERSION_MISMATCH"
    INDEX_REBUILDING = "INDEX_REBUILDING"
    NOT_FOUND = "NOT_FOUND"
    PARSE_ERROR = "PARSE_ERROR"

# Default human-readable messages per error code
ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INDEX_MISSING: "No search index found. Run 'coq-search index' to build the index.",
    ErrorCode.INDEX_VERSION_MISMATCH: "Index version is incompatible with this tool version. Re-index required.",
    ErrorCode.INDEX_REBUILDING: "Index rebuild in progress. Try again later.",
    ErrorCode.NOT_FOUND: "Declaration not found in index.",
    ErrorCode.PARSE_ERROR: "Input validation failed.",
}


class SearchError(Exception):
    """Raised by tool handlers to signal a structured MCP error response."""
    def __init__(self, code: ErrorCode, message: str | None = None):
        self.code = code
        self.message = message or ERROR_MESSAGES[code]
        super().__init__(self.message)


def format_error_response(error: SearchError) -> dict:
    """Format a SearchError as the structured error dict for MCP content."""
    return {
        "error": {
            "code": error.code.value,
            "message": error.message,
        }
    }
```

### Step 3: Response type dataclasses

**File:** `src/coq_search/server/response_types.py`

Define the three response types from specification Section 5.

```python
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    name: str
    statement: str
    type: str
    module: str
    kind: str
    score: float


@dataclass
class LemmaDetail:
    name: str
    statement: str
    type: str
    module: str
    kind: str
    score: float               # always 1.0
    dependencies: list[str]
    dependents: list[str]
    proof_sketch: str
    symbols: list[str]
    node_count: int


@dataclass
class Module:
    name: str
    decl_count: int
```

Add serialization methods to convert each dataclass to a dict suitable for MCP response content (JSON-serializable).

```python
from dataclasses import asdict

def to_mcp_content(result) -> dict:
    """Convert a response dataclass to a JSON-serializable dict."""
    return asdict(result)
```

### Step 4: Input validation

**File:** `src/coq_search/server/validation.py`

Implement validation rules from specification Section 6.

```python
from coq_search.server.errors import SearchError, ErrorCode

VALID_RELATIONS = {"uses", "used_by", "same_module", "same_typeclass"}
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MIN_LIMIT = 1


def validate_non_empty_string(value: str | None, param_name: str) -> str:
    """Validate that a required string parameter is present and non-empty.

    Raises SearchError(PARSE_ERROR) if missing or empty.
    Returns the stripped string.
    """
    ...


def validate_limit(value: int | None) -> int:
    """Validate and clamp the limit parameter.

    Returns DEFAULT_LIMIT if None.
    Clamps to [MIN_LIMIT, MAX_LIMIT] if out of range (per spec: clamp silently).
    """
    ...


def validate_relation(value: str | None) -> str:
    """Validate the relation parameter for find_related.

    Raises SearchError(PARSE_ERROR) listing valid values if invalid.
    Returns the validated relation string.
    """
    ...


def validate_symbols_list(value: list | None) -> list[str]:
    """Validate that symbols is a non-empty list of strings.

    Raises SearchError(PARSE_ERROR) if missing, empty, or contains non-strings.
    """
    ...


def validate_coq_expression(value: str | None, param_name: str) -> str:
    """Validate a Coq expression string for search_by_type and search_by_structure.

    Phase 1: validate non-empty string only.
    Phase 2 (future): invoke Coq parser and raise PARSE_ERROR with parse details.
    """
    ...
```

### Step 5: Response formatting

**File:** `src/coq_search/server/formatting.py`

Convert internal pipeline results (ScoredResult + database rows) into the response types.

```python
from coq_search.server.response_types import SearchResult, LemmaDetail, Module


def format_search_results(
    scored_results: list,   # list of ScoredResult or (decl_id, score) tuples
    db,                     # database connection or query interface
    limit: int,
) -> list[SearchResult]:
    """Look up declaration details for each scored result and format as SearchResult.

    Fetches name, statement, type_expr, module, kind from declarations table.
    Normalizes scores to [0.0, 1.0] range if needed.
    Returns at most `limit` results.
    """
    ...


def format_lemma_detail(
    decl_row: dict,         # full row from declarations table
    dependencies: list[str],
    dependents: list[str],
    symbols: list[str],
) -> LemmaDetail:
    """Assemble a LemmaDetail from a declaration row and its relationships.

    Sets score=1.0 (exact match).
    Sets proof_sketch from decl_row if available, empty string otherwise.
    """
    ...


def format_module_list(
    module_rows: list[tuple[str, int]],  # (module_name, decl_count) pairs
) -> list[Module]:
    """Convert module aggregation query results to Module response objects."""
    ...
```

### Step 6: Tool handler functions

**File:** `src/coq_search/server/tools.py`

Implement the 7 tool handlers. Each handler: validates input, checks server state (index availability), dispatches to pipeline or database, formats response.

```python
import json
from coq_search.server.validation import (
    validate_non_empty_string, validate_limit, validate_relation,
    validate_symbols_list, validate_coq_expression,
)
from coq_search.server.errors import SearchError, ErrorCode
from coq_search.server.formatting import (
    format_search_results, format_lemma_detail, format_module_list,
)


class ToolHandlers:
    """Stateful handler class that holds references to the pipeline and database."""

    def __init__(self, db, pipeline, server_state):
        self.db = db
        self.pipeline = pipeline
        self.server_state = server_state  # tracks INDEX_MISSING, VERSION_MISMATCH, etc.

    def _check_index_state(self):
        """Raise SearchError if the index is not in a servable state."""
        if self.server_state.error is not None:
            raise self.server_state.error

    async def search_by_name(self, pattern: str, limit: int | None = None) -> list[dict]:
        self._check_index_state()
        pattern = validate_non_empty_string(pattern, "pattern")
        limit = validate_limit(limit)
        results = self.pipeline.search_by_name(pattern, limit)
        return [to_mcp_content(r) for r in format_search_results(results, self.db, limit)]

    async def search_by_type(self, type_expr: str, limit: int | None = None) -> list[dict]:
        self._check_index_state()
        type_expr = validate_coq_expression(type_expr, "type_expr")
        limit = validate_limit(limit)
        results = self.pipeline.search_by_type(type_expr, limit)
        return [to_mcp_content(r) for r in format_search_results(results, self.db, limit)]

    async def search_by_structure(self, expression: str, limit: int | None = None) -> list[dict]:
        self._check_index_state()
        expression = validate_coq_expression(expression, "expression")
        limit = validate_limit(limit)
        results = self.pipeline.search_by_structure(expression, limit)
        return [to_mcp_content(r) for r in format_search_results(results, self.db, limit)]

    async def search_by_symbols(self, symbols: list[str], limit: int | None = None) -> list[dict]:
        self._check_index_state()
        symbols = validate_symbols_list(symbols)
        limit = validate_limit(limit)
        results = self.pipeline.search_by_symbols(symbols, limit)
        return [to_mcp_content(r) for r in format_search_results(results, self.db, limit)]

    async def get_lemma(self, name: str) -> dict:
        self._check_index_state()
        name = validate_non_empty_string(name, "name")
        # Direct database lookup — no pipeline dispatch
        decl_row = self.db.get_declaration_by_name(name)
        if decl_row is None:
            raise SearchError(
                ErrorCode.NOT_FOUND,
                f"Declaration '{name}' not found in index."
            )
        dependencies = self.db.get_dependencies(decl_row["id"])
        dependents = self.db.get_dependents(decl_row["id"])
        symbols = json.loads(decl_row["symbol_set"] or "[]")
        detail = format_lemma_detail(decl_row, dependencies, dependents, symbols)
        return to_mcp_content(detail)

    async def find_related(
        self, name: str, relation: str, limit: int | None = None
    ) -> list[dict]:
        self._check_index_state()
        name = validate_non_empty_string(name, "name")
        relation = validate_relation(relation)
        limit = validate_limit(limit)
        # Verify the source declaration exists
        decl_row = self.db.get_declaration_by_name(name)
        if decl_row is None:
            raise SearchError(
                ErrorCode.NOT_FOUND,
                f"Declaration '{name}' not found in index."
            )
        results = self.db.find_related(decl_row["id"], relation, limit)
        return [to_mcp_content(r) for r in format_search_results(results, self.db, limit)]

    async def list_modules(self, prefix: str | None = None) -> list[dict]:
        self._check_index_state()
        modules = self.db.list_modules(prefix or "")
        return [to_mcp_content(m) for m in format_module_list(modules)]
```

### Step 7: MCP server setup and lifecycle

**File:** `src/coq_search/server/app.py`

Wire up the MCP SDK, register tools, manage startup/shutdown lifecycle.

```python
import argparse
import logging
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from coq_search.server.errors import SearchError, ErrorCode, format_error_response
from coq_search.server.tools import ToolHandlers

logger = logging.getLogger("coq_search")

# Current schema version — must match index_meta.schema_version
SCHEMA_VERSION = "1"


class ServerState:
    """Tracks whether the index is available for serving."""
    def __init__(self):
        self.error: SearchError | None = None


def create_server() -> Server:
    """Create and configure the MCP server with all 7 tool definitions."""
    server = Server("coq-search")
    return server


def register_tools(server: Server, handlers: ToolHandlers):
    """Register the 7 MCP tool definitions and their handlers.

    Each tool is registered with:
    - name: tool name from the spec
    - description: human-readable description for Claude Code
    - inputSchema: JSON Schema for parameters (drives MCP parameter validation)
    - handler function: async function that validates, dispatches, and formats
    """
    ...
```

**Tool definitions (JSON Schema for MCP registration):**

Each tool must be registered with an `inputSchema` that the MCP SDK uses for parameter extraction. Define these as constants:

```python
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
```

**Startup sequence** (specification Section 8.1):

```python
async def run_server(db_path: Path, log_level: str = "INFO"):
    """Execute the full server startup sequence and enter the message loop.

    1. Parse command-line arguments (db_path, log_level)
    2. Configure logging to stderr
    3. Check database file exists -> INDEX_MISSING if not
    4. Open database read-only
    5. Validate index_meta (schema_version, coq_version, mathcomp_version)
       -> INDEX_VERSION_MISMATCH if mismatch
    6. Load WL histograms (h=3) into memory
    7. Build in-memory inverted symbol index
    8. Load symbol_freq table into memory
    9. Create pipeline orchestrator with loaded data
    10. Create ToolHandlers with db, pipeline, server_state
    11. Register MCP tool handlers
    12. Enter stdio message loop
    """
    # Configure logging to stderr (never write non-MCP content to stdout)
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    server_state = ServerState()

    # Step 2-3: Check database existence
    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        server_state.error = SearchError(ErrorCode.INDEX_MISSING)
        # Continue to serve — all tool calls will return INDEX_MISSING
    else:
        # Step 4: Open database read-only
        db = open_database_readonly(db_path)

        # Step 5: Validate index_meta
        try:
            validate_index_meta(db, SCHEMA_VERSION)
        except SearchError as e:
            server_state.error = e

        if server_state.error is None:
            # Steps 6-8: Load data into memory
            wl_histograms = load_wl_histograms(db, h=3)
            symbol_index = build_inverted_symbol_index(db)
            symbol_freq = load_symbol_freq(db)

            # Step 9: Create pipeline
            pipeline = create_pipeline(db, wl_histograms, symbol_index, symbol_freq)
        else:
            pipeline = None

    # Steps 10-11: Create handlers and register tools
    handlers = ToolHandlers(db, pipeline, server_state)
    server = create_server()
    register_tools(server, handlers)

    # Step 12: Enter stdio message loop
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
```

**Entry point:**

**File:** `src/coq_search/__main__.py`

```python
import argparse
import asyncio
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Coq semantic search MCP server")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".coq-search" / "index.db",
        help="Path to the search index database",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (output goes to stderr)",
    )
    args = parser.parse_args()

    from coq_search.server.app import run_server
    asyncio.run(run_server(args.db, args.log_level))


if __name__ == "__main__":
    main()
```

### Step 8: Database query layer (server-side)

**File:** `src/coq_search/storage/queries.py`

Implement the database queries needed by `get_lemma`, `find_related`, and `list_modules` (the three tools that do direct DB access rather than pipeline dispatch).

```python
def get_declaration_by_name(conn, name: str) -> dict | None:
    """SELECT * FROM declarations WHERE name = ?"""
    ...


def get_dependencies(conn, decl_id: int) -> list[str]:
    """SELECT d.name FROM dependencies dep
       JOIN declarations d ON d.id = dep.dst
       WHERE dep.src = ? AND dep.relation = 'uses'"""
    ...


def get_dependents(conn, decl_id: int) -> list[str]:
    """SELECT d.name FROM dependencies dep
       JOIN declarations d ON d.id = dep.src
       WHERE dep.dst = ? AND dep.relation = 'uses'"""
    ...


def find_related_uses(conn, decl_id: int, limit: int) -> list[tuple[int, float]]:
    """Declarations that `decl_id` uses. Returns (decl_id, score=1.0) pairs."""
    ...


def find_related_used_by(conn, decl_id: int, limit: int) -> list[tuple[int, float]]:
    """Declarations that use `decl_id`. Returns (decl_id, score=1.0) pairs."""
    ...


def find_related_same_module(conn, decl_id: int, limit: int) -> list[tuple[int, float]]:
    """Declarations in the same module as `decl_id`.
       SELECT id FROM declarations WHERE module = (
           SELECT module FROM declarations WHERE id = ?
       ) AND id != ? LIMIT ?"""
    ...


def find_related_same_typeclass(conn, decl_id: int, limit: int) -> list[tuple[int, float]]:
    """Declarations that are instances of the same typeclass.
       Uses the `instance_of` relation in the dependencies table:
       1. Find typeclasses that decl_id is an instance_of
       2. Find other declarations that are also instance_of those typeclasses
    """
    ...


def list_modules(conn, prefix: str) -> list[tuple[str, int]]:
    """SELECT module, COUNT(*) as decl_count
       FROM declarations
       WHERE module LIKE ? || '%'
       GROUP BY module
       ORDER BY module"""
    ...
```

### Step 9: Startup data loader

**File:** `src/coq_search/storage/loader.py`

Implement the in-memory data loading from specification Section 8.1, steps 5-7.

```python
import json
import sqlite3


def load_wl_histograms(conn: sqlite3.Connection, h: int = 3) -> dict[int, dict[str, int]]:
    """Load all WL histograms for iteration depth h into memory.

    Returns: {decl_id: {md5_label: count, ...}, ...}

    Query: SELECT decl_id, histogram FROM wl_vectors WHERE h = ?
    Parse each histogram JSON string into a dict.
    """
    ...


def build_inverted_symbol_index(conn: sqlite3.Connection) -> dict[str, set[int]]:
    """Build in-memory inverted index: symbol -> set of decl_ids.

    Query: SELECT id, symbol_set FROM declarations WHERE symbol_set IS NOT NULL
    For each declaration, parse the JSON symbol_set array and add the decl_id
    to each symbol's set.
    """
    ...


def load_symbol_freq(conn: sqlite3.Connection) -> dict[str, int]:
    """Load the global symbol frequency table into memory.

    Query: SELECT symbol, freq FROM symbol_freq
    Returns: {symbol: freq, ...}
    """
    ...


def validate_index_meta(conn: sqlite3.Connection, expected_schema_version: str):
    """Check index_meta for version compatibility.

    Reads schema_version, coq_version, mathcomp_version from index_meta.
    Raises SearchError(INDEX_VERSION_MISMATCH) if schema_version does not match.
    Raises SearchError(INDEX_VERSION_MISMATCH) if library versions differ.
    """
    ...
```

### Step 10: Error handling wrapper for tool dispatch

In `app.py`, the tool handler wrapper must catch `SearchError` and convert it to the MCP error response format. Non-`SearchError` exceptions should be logged and returned as a generic internal error.

```python
async def wrap_tool_call(handler_coro):
    """Wrap a tool handler coroutine to catch SearchError and format responses.

    On success: return list[TextContent] with JSON-serialized results.
    On SearchError: return list[TextContent] with JSON-serialized error dict, is_error=True.
    On unexpected exception: log to stderr, return generic error.
    """
    try:
        result = await handler_coro
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except SearchError as e:
        error_body = format_error_response(e)
        return [TextContent(type="text", text=json.dumps(error_body, indent=2))], True
    except Exception:
        logger.exception("Unexpected error in tool handler")
        error_body = {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}}
        return [TextContent(type="text", text=json.dumps(error_body, indent=2))], True
```

### Step 11: Shutdown handling

Register signal handlers for clean shutdown (specification Section 8.2).

```python
import signal

def setup_shutdown_handlers(db):
    """On stdin EOF or SIGTERM: close database connection, exit cleanly."""
    def handle_shutdown(signum, frame):
        logger.info("Received signal %s, shutting down", signum)
        if db is not None:
            db.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
```

The MCP SDK's `stdio_server` context manager handles stdin EOF naturally — when the context exits, the server stops. The database connection should be closed in a `finally` block.

---

## 5. Testing Plan

### 5.1 Unit tests

**Directory:** `test/server/`

| Test file | What it tests |
|-----------|--------------|
| `test_validation.py` | All input validation rules: empty strings, limit clamping, invalid relation values, symbol list validation |
| `test_errors.py` | Error code enum values, error message formatting, SearchError construction |
| `test_response_types.py` | Dataclass construction, serialization to dict, field presence |
| `test_formatting.py` | Conversion from internal ScoredResult + DB rows to SearchResult/LemmaDetail/Module |
| `test_tools.py` | Tool handler logic with mocked DB and pipeline — one test per tool, covering happy path and error cases |

**Key validation test cases:**

| Input | Expected |
|-------|----------|
| `pattern=""` | `PARSE_ERROR` with "pattern" in message |
| `pattern=None` | `PARSE_ERROR` with "pattern" in message |
| `limit=0` | Clamped to 1 |
| `limit=999` | Clamped to 200 |
| `limit=None` | Defaults to 50 |
| `limit=50` | Returns 50 unchanged |
| `relation="invalid"` | `PARSE_ERROR` listing valid values |
| `symbols=[]` | `PARSE_ERROR`: empty list |
| `symbols=[""]` | `PARSE_ERROR`: empty string in list |

### 5.2 Integration tests

**Directory:** `test/integration/`

| Test file | What it tests |
|-----------|--------------|
| `test_server_lifecycle.py` | Startup with missing DB -> INDEX_MISSING state; startup with valid DB -> tools respond; startup with version mismatch -> INDEX_VERSION_MISMATCH |
| `test_mcp_protocol.py` | Send raw JSON-RPC messages over stdio pipes, verify responses conform to MCP spec |
| `test_tool_dispatch.py` | End-to-end: build a small test DB with 10-20 declarations, call each tool, verify response shape and content |

**MCP protocol test approach:**

Spawn the server as a subprocess (`python -m coq_search --db test.db`), write JSON-RPC requests to its stdin, read JSON-RPC responses from stdout. Verify:
- `tools/list` returns all 7 tools with correct schemas
- Each tool call returns valid MCP response with `content` array
- Error responses have the correct structure
- Server shuts down cleanly on stdin close

### 5.3 Test fixtures

Create a minimal test database fixture with:
- 5-10 declarations spanning multiple modules and kinds
- A few dependency edges
- WL histograms for the declarations
- A populated FTS5 index
- Valid `index_meta` entries

Store the fixture creation logic in `test/conftest.py` using pytest fixtures.

---

## 6. Acceptance Criteria

| Criterion | Verification method |
|-----------|-------------------|
| Server starts and registers 7 tools | `tools/list` MCP call returns 7 tool definitions |
| `search_by_name` returns ranked SearchResult list | Integration test with test DB |
| `search_by_type` dispatches to WL + MePo + FTS5 and fuses results | Integration test with test DB |
| `search_by_structure` dispatches to structural pipeline | Integration test with test DB |
| `search_by_symbols` dispatches to MePo | Integration test with test DB |
| `get_lemma` returns LemmaDetail with all fields populated | Integration test: verify dependencies, dependents, symbols, node_count present |
| `get_lemma` with unknown name returns NOT_FOUND error | Integration test |
| `find_related` returns related declarations for all 4 relation types | Integration test per relation type |
| `list_modules` returns alphabetically sorted Module list with counts | Integration test |
| Missing DB at startup -> all tools return INDEX_MISSING | Integration test |
| Schema version mismatch -> all tools return INDEX_VERSION_MISMATCH | Integration test |
| Invalid inputs return PARSE_ERROR with descriptive messages | Unit tests for each validation rule |
| `limit` out of range is silently clamped | Unit test |
| All logging goes to stderr, stdout contains only JSON-RPC | Integration test: capture stdout and stderr separately |
| Server configurable in Claude Code's `mcp_servers.json` format | Manual verification: add config, verify Claude Code discovers the tools |
| Server shuts down cleanly on stdin EOF | Integration test: close stdin pipe, verify process exits with code 0 |
| Tool call latency < 1s for search tools on 50K declarations | Performance test (deferred to after pipeline implementation) |

---

## 7. Risks and Mitigations

### MCP SDK compatibility

**Risk:** The `mcp` Python SDK may change its API between versions, or its stdio transport implementation may have edge cases with buffering.

**Mitigation:** Pin the `mcp` package version in `pyproject.toml`. Write integration tests that exercise the actual stdio transport. Monitor the `mcp` SDK changelog.

### JSON-RPC framing over stdio

**Risk:** JSON-RPC messages over stdio require careful framing. If the server writes non-JSON content to stdout (logging, debug prints, stack traces), the MCP client will fail to parse responses.

**Mitigation:** Configure all logging to stderr. Use the MCP SDK's built-in stdio transport rather than implementing framing manually. Add a test that verifies stdout contains only valid JSON-RPC messages.

### Coq expression parsing

**Risk:** `search_by_type` and `search_by_structure` require parsing Coq expressions. The spec says `type_expr` must be "syntactically valid Coq expression." Implementing a Coq parser in Python is non-trivial.

**Mitigation:** Phase the implementation. Phase 1: accept any non-empty string, skip syntactic validation. Phase 2: integrate with coq-lsp or a lightweight Coq expression parser. The `PARSE_ERROR` contract is already defined, so adding validation later is backward-compatible.

### Startup memory budget

**Risk:** Loading WL histograms for 50K declarations may consume more than the 200 MB estimate if histograms are larger than expected.

**Mitigation:** Profile memory usage during integration testing. If needed, use a memory-mapped approach or load histograms lazily. The spec states total server memory should be < 500 MB.

### `same_typeclass` relation

**Risk:** The `same_typeclass` query for `find_related` requires traversing the dependency graph through `instance_of` edges. The spec does not fully define what "same typeclass" means when a declaration is an instance of multiple typeclasses.

**Mitigation:** Implement as: find all typeclasses the source declaration is an `instance_of`, then find all other declarations that are `instance_of` any of those typeclasses. This may return a large set; the `limit` parameter controls the output size.

### Concurrent tool calls

**Risk:** The spec says "single-threaded event loop" and "no concurrent tool calls," but the MCP SDK uses asyncio. If the SDK dispatches multiple tool calls before one completes (e.g., due to pipelining), shared state (DB connection, in-memory indexes) could see inconsistent reads.

**Mitigation:** The server is read-only after startup — in-memory data structures and the SQLite read-only connection do not mutate. Asyncio is cooperative, so CPU-bound operations (WL cosine scan) will block the event loop, which naturally serializes tool calls. If needed, add an explicit asyncio.Lock around tool dispatch.

### `find_related` score semantics

**Risk:** The spec says `find_related` returns `SearchResult` with a `score` field, but graph-navigated results do not have a natural relevance score. The score semantics are underspecified.

**Mitigation:** Set `score=1.0` for all `find_related` results (they are exact graph matches, not ranked by relevance). Document this in the tool's response.
