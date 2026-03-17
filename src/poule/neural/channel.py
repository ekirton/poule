"""Neural retrieval channel and availability checks."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from poule.neural.encoder import NeuralEncoder
from poule.neural.errors import ModelNotFoundError, ModelLoadError

logger = logging.getLogger(__name__)


def neural_retrieve(ctx, query_text: str, limit: int) -> list[tuple[int, float]]:
    try:
        query_vector = ctx.neural_encoder.encode(query_text)
    except Exception:
        logger.warning("Neural encoder failed on query text: %s", query_text[:100])
        return []
    return ctx.embedding_index.search(query_vector, k=limit)


def check_availability(db_path: Path, model_path: Path) -> bool:
    model_path = Path(model_path)
    if not model_path.exists():
        return False

    try:
        encoder = NeuralEncoder.load(model_path)
    except (ModelNotFoundError, ModelLoadError):
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        # Check embeddings table has rows
        try:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        except sqlite3.OperationalError:
            conn.close()
            return False
        if count == 0:
            conn.close()
            return False
        # Check model hash matches
        try:
            stored_hash = conn.execute(
                "SELECT value FROM index_meta WHERE key = 'neural_model_hash'"
            ).fetchone()
        except sqlite3.OperationalError:
            conn.close()
            return False
        conn.close()
        if stored_hash is None or stored_hash[0] != encoder.model_hash():
            return False
        return True
    except Exception:
        return False


def neural_query_text_for_type(type_expr: str) -> str:
    return type_expr


def neural_query_text_for_symbols(symbols: list[str]) -> str:
    return " ".join(symbols)
