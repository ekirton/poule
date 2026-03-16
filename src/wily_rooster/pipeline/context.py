"""PipelineContext and create_context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from wily_rooster.storage.reader import IndexReader


@dataclass
class PipelineContext:
    """Shared resource container for the retrieval pipeline."""

    reader: Any
    wl_histograms: dict[int, dict[str, int]]
    inverted_index: dict[str, set[int]]
    symbol_frequencies: dict[str, int]
    declaration_symbols: dict[int, set[str]]
    declaration_node_counts: dict[int, int]
    parser: Any = None


def create_context(db_path: str) -> PipelineContext:
    """Open an IndexReader and load all in-memory data structures.

    The parser field is left as None (lazy initialization).
    """
    reader = IndexReader(db_path)

    wl_histograms = reader.load_wl_histograms()
    inverted_index = reader.load_inverted_index()
    symbol_frequencies = reader.load_symbol_frequencies()
    declaration_node_counts = reader.load_declaration_node_counts()

    # Derive declaration_symbols from inverted_index:
    # inverted_index maps symbol -> set of decl_ids
    # declaration_symbols maps decl_id -> set of symbols
    declaration_symbols: dict[int, set[str]] = {}
    for symbol, decl_ids in inverted_index.items():
        for decl_id in decl_ids:
            if decl_id not in declaration_symbols:
                declaration_symbols[decl_id] = set()
            declaration_symbols[decl_id].add(symbol)

    return PipelineContext(
        reader=reader,
        wl_histograms=wl_histograms,
        inverted_index=inverted_index,
        symbol_frequencies=symbol_frequencies,
        declaration_symbols=declaration_symbols,
        declaration_node_counts=declaration_node_counts,
        parser=None,
    )
