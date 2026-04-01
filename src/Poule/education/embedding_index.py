"""FAISS-backed embedding index for cosine similarity search."""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


class EmbeddingIndex:
    """Holds L2-normalized embeddings in a FAISS index for cosine search."""

    def __init__(self, index: faiss.Index):
        self._index = index

    @classmethod
    def build(cls, embedding_matrix: np.ndarray, decl_id_map: np.ndarray) -> EmbeddingIndex:
        matrix = np.ascontiguousarray(embedding_matrix.astype(np.float32))
        ids = decl_id_map.astype(np.int64)
        dim = matrix.shape[1]
        flat = faiss.IndexFlatIP(dim)
        index = faiss.IndexIDMap(flat)
        index.add_with_ids(matrix, ids)
        return cls(index)

    @classmethod
    def from_file(cls, faiss_path: Path | str) -> EmbeddingIndex:
        path = Path(faiss_path)
        if not path.exists():
            raise FileNotFoundError(f"FAISS index not found: {path}")
        index = faiss.read_index(str(path))
        return cls(index)

    def save(self, faiss_path: Path | str) -> None:
        faiss.write_index(self._index, str(faiss_path))

    def search(self, query_vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        query = np.ascontiguousarray(
            query_vector.astype(np.float32).reshape(1, -1)
        )
        actual_k = min(k, self._index.ntotal)
        if actual_k == 0:
            return []
        scores, ids = self._index.search(query, actual_k)
        return [
            (int(ids[0][i]), float(scores[0][i]))
            for i in range(len(ids[0]))
            if ids[0][i] != -1
        ]
