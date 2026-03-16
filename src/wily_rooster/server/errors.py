"""Error formatting and error code constants for the MCP server layer."""

from __future__ import annotations

import json

# Error code constants
INDEX_MISSING: str = "INDEX_MISSING"
INDEX_VERSION_MISMATCH: str = "INDEX_VERSION_MISMATCH"
NOT_FOUND: str = "NOT_FOUND"
PARSE_ERROR: str = "PARSE_ERROR"


def format_error(code: str, message: str) -> dict:
    """Format an error as an MCP error response dict.

    Returns a dict with ``content`` (list of text items) and ``isError: True``.
    """
    error_json = json.dumps({"error": {"code": code, "message": message}})
    return {
        "content": [{"type": "text", "text": error_json}],
        "isError": True,
    }
