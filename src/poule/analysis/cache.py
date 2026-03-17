"""Graph cache with invalidation support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import DependencyGraph


@dataclass
class _CacheEntry:
    source_path: str
    graph: DependencyGraph
    schema_version: str
    created_at: str


class GraphCache:
    """Process-scoped cache holding at most one DependencyGraph per project key.

    Cache is invalidated when schema_version, created_at, or source_path changes.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}

    def get(
        self,
        project_key: str,
        source_path: str,
        schema_version: str,
        created_at: str,
    ) -> DependencyGraph | None:
        """Return cached graph if it matches, otherwise None."""
        entry = self._entries.get(project_key)
        if entry is None:
            return None
        if (
            entry.source_path == source_path
            and entry.schema_version == schema_version
            and entry.created_at == created_at
        ):
            return entry.graph
        # Parameters don't match — return None but keep the stored entry intact.
        # Only put() replaces entries; get() never evicts.
        return None

    def put(
        self,
        project_key: str,
        source_path: str,
        graph: DependencyGraph,
        schema_version: str,
        created_at: str,
    ) -> None:
        """Store a graph in the cache, replacing any existing entry for this project."""
        self._entries[project_key] = _CacheEntry(
            source_path=source_path,
            graph=graph,
            schema_version=schema_version,
            created_at=created_at,
        )
