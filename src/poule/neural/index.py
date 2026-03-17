"""In-memory embedding index with brute-force cosine similarity search."""

from __future__ import annotations

import numpy as np


class EmbeddingIndex:
    """Holds a matrix of L2-normalized premise embeddings for cosine search."""

    def __init__(self, matrix: np.ndarray, id_map: np.ndarray):
        self._matrix = matrix
        self._id_map = id_map

    @classmethod
    def build(cls, embedding_matrix: np.ndarray, decl_id_map: np.ndarray) -> EmbeddingIndex:
        return cls(
            embedding_matrix.astype(np.float32),
            decl_id_map.copy(),
        )

    def search(self, query_vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        # Cosine similarity = dot product for L2-normalized vectors
        scores = self._matrix @ query_vector.astype(np.float32)
        n = len(scores)
        actual_k = min(k, n)
        if actual_k >= n:
            top_indices = np.argsort(scores)[::-1]
        else:
            # argpartition for top-k, then sort those k
            top_indices = np.argpartition(scores, -actual_k)[-actual_k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        return [
            (int(self._id_map[i]), float(scores[i]))
            for i in top_indices
        ]
