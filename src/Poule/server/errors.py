"""Error formatting and error code constants for the MCP server layer."""

from __future__ import annotations

import json

# Error code constants — search
INDEX_MISSING: str = "INDEX_MISSING"
INDEX_VERSION_MISMATCH: str = "INDEX_VERSION_MISMATCH"
NOT_FOUND: str = "NOT_FOUND"
PARSE_ERROR: str = "PARSE_ERROR"

# Error code constants — proof interaction
SESSION_NOT_FOUND: str = "SESSION_NOT_FOUND"
SESSION_EXPIRED: str = "SESSION_EXPIRED"
FILE_NOT_FOUND: str = "FILE_NOT_FOUND"
PROOF_NOT_FOUND: str = "PROOF_NOT_FOUND"
TACTIC_ERROR: str = "TACTIC_ERROR"
STEP_OUT_OF_RANGE: str = "STEP_OUT_OF_RANGE"
NO_PREVIOUS_STATE: str = "NO_PREVIOUS_STATE"
PROOF_COMPLETE: str = "PROOF_COMPLETE"
BACKEND_CRASHED: str = "BACKEND_CRASHED"

# Error code constants — profiling
TOOL_MISSING: str = "TOOL_MISSING"
INVALID_FILE: str = "INVALID_FILE"
INVALID_REQUEST: str = "INVALID_REQUEST"

# Error code constants — visualization
PROOF_INCOMPLETE: str = "PROOF_INCOMPLETE"
DIAGRAM_TRUNCATED: str = "DIAGRAM_TRUNCATED"


def format_error(code: str, message: str) -> dict:
    """Format an error as an MCP error response dict.

    Returns a dict with ``content`` (list of text items) and ``isError: True``.
    """
    error_json = json.dumps({"error": {"code": code, "message": message}})
    return {
        "content": [{"type": "text", "text": error_json}],
        "isError": True,
    }
