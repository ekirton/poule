"""Build pipeline: HTML → chunks → embeddings → SQLite education database."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from Poule.education.chunker import HTMLChunker
from Poule.education.storage import EducationStorage

logger = logging.getLogger(__name__)


def build_education_db(
    sf_dir: Path,
    output_path: Path,
    model_path: Path,
    tokenizer_path: Path,
    *,
    batch_size: int = 64,
) -> dict[str, int]:
    """Build the education database from Software Foundations HTML.

    Returns a dict of statistics: total_chunks, total_tokens, volumes_indexed.
    """
    sf_dir = Path(sf_dir)
    output_path = Path(output_path)

    logger.info("Chunking SF corpus from %s", sf_dir)
    chunker = HTMLChunker()
    chunks = chunker.chunk_corpus(sf_dir)
    logger.info("Produced %d chunks", len(chunks))

    if not chunks:
        raise ValueError(f"No chunks produced from {sf_dir}")

    # Create database
    EducationStorage.create(output_path)
    chunk_ids = EducationStorage.write_chunks(output_path, chunks)
    logger.info("Wrote %d chunks to %s", len(chunk_ids), output_path)

    # Encode chunks
    from Poule.education.encoder import EducationEncoder

    encoder = EducationEncoder.load(model_path, tokenizer_path)

    vectors = []
    total = len(chunks)
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        batch_texts = [c.text for c in batch]
        batch_vecs = encoder.encode_batch(batch_texts)
        vectors.extend(batch_vecs)
        logger.info("Encoded %d / %d chunks", min(i + batch_size, total), total)

    EducationStorage.write_embeddings(output_path, chunk_ids, vectors)
    logger.info("Wrote %d embeddings", len(vectors))

    # Write metadata
    volumes = {c.metadata.volume for c in chunks}
    EducationStorage.write_meta(output_path, {
        "schema_version": "1",
        "model_hash": encoder.model_hash(),
        "build_date": time.strftime("%Y-%m-%d"),
        "chunk_count": str(len(chunks)),
        "volumes_indexed": ",".join(sorted(volumes)),
    })

    stats = {
        "total_chunks": len(chunks),
        "total_tokens": sum(c.token_count for c in chunks),
        "volumes_indexed": len(volumes),
    }
    logger.info("Build complete: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build education database")
    parser.add_argument("--sf-dir", required=True, help="Path to software-foundations/")
    parser.add_argument("--output", required=True, help="Output SQLite database path")
    parser.add_argument("--model", required=True, help="Path to ONNX encoder model")
    parser.add_argument("--tokenizer", required=True, help="Path to tokenizer.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = build_education_db(
        Path(args.sf_dir), Path(args.output), Path(args.model), Path(args.tokenizer)
    )
    print(f"Done: {stats}")
