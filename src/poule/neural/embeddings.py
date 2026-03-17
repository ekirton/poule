"""Embedding write and read paths for the neural channel."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def compute_embeddings(db_path: Path, encoder) -> None:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id, statement FROM declarations ORDER BY id").fetchall()

    ids = [r[0] for r in rows]
    statements = [r[1] for r in rows]

    # Encode in batches of 64
    all_vectors = []
    for i in range(0, len(statements), 64):
        batch = statements[i : i + 64]
        vectors = encoder.encode_batch(batch)
        all_vectors.extend(vectors)

    # Insert embeddings
    for decl_id, vec in zip(ids, all_vectors):
        blob = vec.astype(np.float32).tobytes()
        conn.execute("INSERT INTO embeddings (decl_id, vector) VALUES (?, ?)", (decl_id, blob))

    # Write model hash
    conn.execute(
        "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('neural_model_hash', ?)",
        (encoder.model_hash(),),
    )
    conn.commit()
    conn.close()


def load_embeddings(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT decl_id, vector FROM embeddings ORDER BY decl_id").fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return (None, None)

    conn.close()

    if not rows:
        return (None, None)

    id_map = np.array([r[0] for r in rows], dtype=np.int64)
    matrix = np.stack(
        [np.frombuffer(r[1], dtype=np.float32) for r in rows]
    )
    return matrix, id_map
