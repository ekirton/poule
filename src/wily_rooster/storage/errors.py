"""Storage error hierarchy."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for all storage errors."""
    pass


class IndexNotFoundError(StorageError):
    """Database file missing."""
    pass


class IndexVersionError(StorageError):
    """Schema version mismatch."""

    def __init__(self, found: str, expected: str) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"Schema version mismatch: found {found!r}, expected {expected!r}"
        )
