"""Response types: SearchResult, LemmaDetail, Module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """Immutable search result response."""

    name: str
    statement: str
    type: str
    module: str
    kind: str
    score: float


@dataclass(frozen=True)
class LemmaDetail(SearchResult):
    """Extends SearchResult with detailed lemma information."""

    dependencies: list[str] = None  # type: ignore[assignment]
    dependents: list[str] = None  # type: ignore[assignment]
    proof_sketch: str = ""
    symbols: list[str] = None  # type: ignore[assignment]
    node_count: int = 1


@dataclass(frozen=True)
class Module:
    """Immutable module response."""

    name: str
    decl_count: int

    @property
    def count(self) -> int:
        """Alias for decl_count (backwards compatibility)."""
        return self.decl_count
