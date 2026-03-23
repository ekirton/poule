"""SQLite storage for the education database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from Poule.education.models import Chunk, ChunkMetadata

SCHEMA_SQL = """\
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume TEXT NOT NULL,
    volume_title TEXT NOT NULL,
    chapter TEXT NOT NULL,
    chapter_file TEXT NOT NULL,
    section_title TEXT NOT NULL,
    section_path TEXT NOT NULL,
    anchor_id TEXT,
    text TEXT NOT NULL,
    code_blocks TEXT,
    token_count INTEGER NOT NULL
);

CREATE TABLE education_embeddings (
    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,
    PRIMARY KEY (chunk_id)
);

CREATE TABLE education_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, section_title, chapter,
    content=chunks, content_rowid=id,
    tokenize='porter unicode61'
);
"""


class EducationStorage:
    """SQLite read/write operations for the education database."""

    @staticmethod
    def create(db_path: Path) -> None:
        db_path = Path(db_path)
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.close()

    @staticmethod
    def write_chunks(db_path: Path, chunks: list[Chunk]) -> list[int]:
        conn = sqlite3.connect(str(db_path))
        ids = []
        for chunk in chunks:
            cursor = conn.execute(
                """INSERT INTO chunks
                   (volume, volume_title, chapter, chapter_file,
                    section_title, section_path, anchor_id,
                    text, code_blocks, token_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.metadata.volume,
                    chunk.metadata.volume_title,
                    chunk.metadata.chapter,
                    chunk.metadata.chapter_file,
                    chunk.metadata.section_title,
                    json.dumps(chunk.metadata.section_path),
                    chunk.metadata.anchor_id,
                    chunk.text,
                    json.dumps(chunk.code_blocks),
                    chunk.token_count,
                ),
            )
            chunk_id = cursor.lastrowid
            ids.append(chunk_id)
            # Populate FTS index
            conn.execute(
                "INSERT INTO chunks_fts(rowid, text, section_title, chapter) VALUES (?, ?, ?, ?)",
                (chunk_id, chunk.text, chunk.metadata.section_title, chunk.metadata.chapter),
            )
        conn.commit()
        conn.close()
        return ids

    @staticmethod
    def write_embeddings(
        db_path: Path, chunk_ids: list[int], vectors: list[np.ndarray]
    ) -> None:
        conn = sqlite3.connect(str(db_path))
        for chunk_id, vec in zip(chunk_ids, vectors):
            conn.execute(
                "INSERT INTO education_embeddings (chunk_id, vector) VALUES (?, ?)",
                (chunk_id, vec.astype(np.float32).tobytes()),
            )
        conn.commit()
        conn.close()

    @staticmethod
    def write_meta(db_path: Path, metadata: dict[str, str]) -> None:
        conn = sqlite3.connect(str(db_path))
        for key, value in metadata.items():
            conn.execute(
                "INSERT OR REPLACE INTO education_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        conn.commit()
        conn.close()

    @staticmethod
    def load_chunks(db_path: Path) -> dict[int, Chunk]:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            """SELECT id, volume, volume_title, chapter, chapter_file,
                      section_title, section_path, anchor_id,
                      text, code_blocks, token_count
               FROM chunks"""
        ).fetchall()
        conn.close()

        result = {}
        for row in rows:
            (
                chunk_id, volume, volume_title, chapter, chapter_file,
                section_title, section_path_json, anchor_id,
                text, code_blocks_json, token_count,
            ) = row
            result[chunk_id] = Chunk(
                text=text,
                code_blocks=json.loads(code_blocks_json) if code_blocks_json else [],
                metadata=ChunkMetadata(
                    volume=volume,
                    volume_title=volume_title,
                    chapter=chapter,
                    chapter_file=chapter_file,
                    section_title=section_title,
                    section_path=json.loads(section_path_json),
                    anchor_id=anchor_id,
                ),
                token_count=token_count,
            )
        return result

    @staticmethod
    def load_embeddings(db_path: Path) -> tuple[np.ndarray, np.ndarray]:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT chunk_id, vector FROM education_embeddings ORDER BY chunk_id"
        ).fetchall()
        conn.close()

        if not rows:
            return np.empty((0, 384), dtype=np.float32), np.empty(0, dtype=np.int64)

        ids = []
        vectors = []
        for chunk_id, blob in rows:
            ids.append(chunk_id)
            vec = np.frombuffer(blob, dtype=np.float32).copy()
            vectors.append(vec)

        dim = vectors[0].shape[0]
        matrix = np.stack(vectors).astype(np.float32)
        id_map = np.array(ids, dtype=np.int64)
        return matrix, id_map
