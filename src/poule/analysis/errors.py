"""Error types for the deep dependency analysis engine."""

from __future__ import annotations


class AnalysisError(Exception):
    """Structured error with an error code and human-readable message.

    Error codes: NOT_FOUND, INVALID_INPUT, INDEX_MISSING, FILE_NOT_FOUND,
    PARSE_ERROR, GRAPH_NOT_READY, TOOL_MISSING, RESULT_TOO_LARGE.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
