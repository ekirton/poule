"""FTS5 full-text search channel.

Provides query preprocessing and search execution over SQLite FTS5 indexes.
See specification/channel-fts.md for the authoritative specification.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Poule.storage.reader import IndexReader

from Poule.models.responses import SearchResult

# FTS5 special characters that require quoting
_FTS5_SPECIAL = re.compile(r'[*"()+\-:^{},=]')

_TOKEN_LIMIT = 20


def _escape_token(token: str) -> str:
    """Wrap token in double quotes if it contains FTS5 special characters."""
    if _FTS5_SPECIAL.search(token):
        return f'"{token}"'
    return token


def fts_query(raw_query: str) -> str:
    """Preprocess *raw_query* into an FTS5-compatible query string.

    Query classification (priority order):
    1. Contains "." -> split on ".", join with " AND "
    2. Contains "_" and no spaces -> split on "_", join with " AND "
    3. Everything else -> split on whitespace, join with " OR "
    """
    stripped = raw_query.strip()
    if not stripped:
        return ""

    if "." in stripped:
        tokens = stripped.split(".")
        joiner = " AND "
    elif "_" in stripped and " " not in stripped:
        tokens = stripped.split("_")
        joiner = " AND "
    else:
        tokens = stripped.split()
        joiner = " OR "

    # Filter empty tokens, escape specials, enforce limit
    tokens = [_escape_token(t) for t in tokens if t][:_TOKEN_LIMIT]

    return joiner.join(tokens)


def fts_search(
    query: str,
    limit: int,
    reader: IndexReader,
) -> list[SearchResult]:
    """Execute an FTS5 search and return results with normalized BM25 scores.

    Scores are negated (FTS5 BM25 returns negative values where lower is better)
    and divided by the maximum absolute score to normalize into [0, 1].
    If all scores are equal, every result receives 1.0.
    """
    if not query:
        return []

    rows = reader.search_fts(query, limit=limit)
    if not rows:
        return []

    # Negate raw BM25 scores (make positive)
    negated = [-row["score"] for row in rows]
    max_score = max(negated)

    results: list[SearchResult] = []
    for row, neg_score in zip(rows, negated):
        if max_score == 0.0:
            normalized = 1.0
        else:
            normalized = neg_score / max_score

        results.append(
            SearchResult(
                name=row.get("name", ""),
                statement=row.get("statement", ""),
                type=row.get("type", ""),
                module=row.get("module", ""),
                kind=row.get("kind", ""),
                score=normalized,
            )
        )

    return results
