"""SQLite storage layer for the Coq/Rocq search index."""

from wily_rooster.storage.errors import (
    IndexNotFoundError,
    IndexVersionError,
    StorageError,
)
from wily_rooster.storage.reader import IndexReader
from wily_rooster.storage.writer import IndexWriter

__all__ = [
    "IndexNotFoundError",
    "IndexReader",
    "IndexVersionError",
    "IndexWriter",
    "StorageError",
]