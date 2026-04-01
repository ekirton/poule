"""Educational content retrieval (RAG) over Software Foundations."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from Poule.education.fts import education_fts_query
from Poule.education.models import EducationSearchResult
from Poule.education.storage import EducationStorage
from Poule.education.embedding_index import EmbeddingIndex

logger = logging.getLogger(__name__)

# FTS score weight relative to embedding score in additive fusion.
# Higher values make keyword/title matches dominate over embedding similarity.
_FTS_WEIGHT = 2.0


class EducationRAG:
    """Facade for educational content retrieval."""

    def __init__(
        self,
        db_path: Path,
        model_path: Path,
        tokenizer_path: Path,
    ):
        self._db_path = db_path
        self._encoder = None
        self._index = None
        self._chunks = {}

        try:
            from Poule.education.encoder import EducationEncoder

            self._encoder = EducationEncoder.load(model_path, tokenizer_path)
            matrix, id_map = EducationStorage.load_embeddings(db_path)
            if matrix.shape[0] > 0:
                self._index = EmbeddingIndex.build(matrix, id_map)
            self._chunks = EducationStorage.load_chunks(db_path)
            logger.info(
                "Education RAG loaded: %d chunks, %d embeddings",
                len(self._chunks),
                matrix.shape[0],
            )
        except Exception:
            logger.warning("Failed to load education RAG", exc_info=True)

    def is_available(self) -> bool:
        return (
            self._encoder is not None
            and self._index is not None
            and len(self._chunks) > 0
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        volume_filter: str | None = None,
    ) -> list[EducationSearchResult]:
        if not self.is_available():
            return []

        candidate_k = limit * 4

        # Channel 1: embedding cosine similarity
        query_vec = self._encoder.encode(query)
        k_embed = candidate_k * 2 if volume_filter else candidate_k
        embed_results = self._index.search(query_vec, k_embed)

        # Channel 2: FTS5 keyword search (BM25 with chapter/title boosting)
        # Use a larger candidate pool to ensure chapter-title matches surface.
        fts_query_str = education_fts_query(query)
        fts_results = EducationStorage.search_fts(
            self._db_path, fts_query_str, limit=candidate_k * 2,
        )

        # Additive score fusion: embed_score + weight * bm25_score.
        # Both scores are in [0, 1]. Using scores (not ranks) preserves
        # the large BM25 gap between chapter-title matches and text matches.
        scores: defaultdict[int, float] = defaultdict(float)
        for chunk_id, embed_score in embed_results:
            scores[chunk_id] += embed_score
        for chunk_id, bm25_score in fts_results:
            scores[chunk_id] += _FTS_WEIGHT * bm25_score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for chunk_id, fused_score in ranked:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            if volume_filter and chunk.metadata.volume != volume_filter:
                continue

            vol_upper = chunk.metadata.volume.upper()
            location = f"{vol_upper} > {chunk.metadata.chapter} > {chunk.metadata.section_title}"

            homedir = os.environ.get("CONTAINER_HOME", "")
            if homedir:
                browser_path = f"file://{homedir}/software-foundations/{chunk.metadata.volume}/{chunk.metadata.chapter_file}"
            else:
                browser_path = f"~/poule-home/software-foundations/{chunk.metadata.volume}/{chunk.metadata.chapter_file}"
            if chunk.metadata.anchor_id:
                browser_path += f"#{chunk.metadata.anchor_id}"

            results.append(
                EducationSearchResult(
                    text=chunk.text,
                    code_blocks=chunk.code_blocks,
                    metadata=chunk.metadata,
                    score=float(fused_score),
                    location=location,
                    browser_path=browser_path,
                )
            )
            if len(results) >= limit:
                break

        return results
