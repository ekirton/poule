"""Error types and error code constants for the build system integration layer."""

from __future__ import annotations

# Error code constants (spec section 7)
PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
BUILD_SYSTEM_NOT_DETECTED = "BUILD_SYSTEM_NOT_DETECTED"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
BUILD_TIMEOUT = "BUILD_TIMEOUT"
FILE_NOT_WRITABLE = "FILE_NOT_WRITABLE"
DEPENDENCY_EXISTS = "DEPENDENCY_EXISTS"
PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
INVALID_PARAMETER = "INVALID_PARAMETER"


class BuildSystemError(Exception):
    """Structured error raised by the build system adapter."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
