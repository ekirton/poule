"""Educational content retrieval (RAG) over Software Foundations."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from Poule.education.models import EducationSearchResult
from Poule.education.storage import EducationStorage
from Poule.neural.index import EmbeddingIndex

logger = logging.getLogger(__name__)


class EducationRAG:
    """Facade for educational content retrieval."""

    def __init__(
        self,
        db_path: Path,
        model_path: Path,
        tokenizer_path: Path,
    ):
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

        query_vec = self._encoder.encode(query)
        # Retrieve more candidates than needed for filtering
        k = limit * 3 if volume_filter else limit
        raw_results = self._index.search(query_vec, k)

        results = []
        for chunk_id, score in raw_results:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            if volume_filter and chunk.metadata.volume != volume_filter:
                continue

            vol_upper = chunk.metadata.volume.upper()
            location = f"{vol_upper} > {chunk.metadata.chapter} > {chunk.metadata.section_title}"

            browser_path = f"~/software-foundations/{chunk.metadata.volume}/{chunk.metadata.chapter_file}"
            if chunk.metadata.anchor_id:
                browser_path += f"#{chunk.metadata.anchor_id}"

            results.append(
                EducationSearchResult(
                    text=chunk.text,
                    code_blocks=chunk.code_blocks,
                    metadata=chunk.metadata,
                    score=float(score),
                    location=location,
                    browser_path=browser_path,
                )
            )
            if len(results) >= limit:
                break

        return results
