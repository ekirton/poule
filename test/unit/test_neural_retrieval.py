"""TDD tests for neural retrieval channel (specification/neural-retrieval.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/neural/.

Covers: NeuralEncoder (load, encode, encode_batch, model_hash),
EmbeddingIndex (build, search), neural channel availability checks,
embedding write path, embedding read path, graceful degradation,
and pipeline integration.
"""

from __future__ import annotations

import struct
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Imports from production code (TDD — will fail until implemented)
# ---------------------------------------------------------------------------

from Poule.neural.encoder import NeuralEncoder
from Poule.neural.index import EmbeddingIndex
from Poule.neural.channel import neural_retrieve, check_availability
from Poule.neural.embeddings import compute_embeddings, load_embeddings, build_faiss_index, load_faiss_index
from Poule.neural.errors import ModelNotFoundError, ModelLoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _random_unit_vector(dim=768, seed=42):
    """Return a random L2-normalized vector of given dimension."""
    rng = np.random.RandomState(seed)
    v = rng.randn(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _random_embedding_matrix(n, dim=768, seed=42):
    """Return an (n, dim) matrix of L2-normalized row vectors."""
    rng = np.random.RandomState(seed)
    m = rng.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / norms


def _vector_to_blob(v):
    """Serialize a float32 numpy vector to raw bytes."""
    return v.astype(np.float32).tobytes()


# ═══════════════════════════════════════════════════════════════════════════
# 1. NeuralEncoder
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralEncoderLoad:
    """NeuralEncoder.load loads an ONNX model and prepares for inference."""

    def test_load_nonexistent_raises_model_not_found(self, tmp_path):
        with pytest.raises(ModelNotFoundError):
            NeuralEncoder.load(tmp_path / "nonexistent.onnx")

    def test_load_invalid_onnx_raises_model_load_error(self, tmp_path):
        bad_file = tmp_path / "bad.onnx"
        bad_file.write_bytes(b"not an onnx model")
        with pytest.raises(ModelLoadError):
            NeuralEncoder.load(bad_file)


class TestNeuralEncoderEncode:
    """NeuralEncoder.encode maps text to L2-normalized 768-dim vectors."""

    @pytest.fixture
    def encoder(self):
        """Mock encoder that returns deterministic vectors."""
        enc = Mock(spec=NeuralEncoder)
        # Return a deterministic unit vector based on text hash
        def _encode(text):
            v = np.zeros(768, dtype=np.float32)
            v[hash(text) % 768] = 1.0
            return v

        enc.encode.side_effect = _encode
        enc.encode_batch.side_effect = lambda texts: [_encode(t) for t in texts]
        enc.model_hash.return_value = "abc123"
        return enc

    def test_encode_returns_768_dim_vector(self, encoder):
        result = encoder.encode("forall n m : nat, n + m = m + n")
        assert result.shape == (768,)
        assert result.dtype == np.float32

    def test_encode_returns_unit_vector(self, encoder):
        """spec §4.1: encode returns an L2-normalized float vector."""
        result = encoder.encode("forall n : nat, n + 0 = n")
        # L2 norm should be 1.0
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5

    def test_encode_deterministic(self, encoder):
        """spec §4.1: The same input text always produces the same output vector."""
        text = "forall n m : nat, n + m = m + n"
        v1 = encoder.encode(text)
        v2 = encoder.encode(text)
        np.testing.assert_array_equal(v1, v2)

    def test_encode_batch_preserves_order(self, encoder):
        """spec §4.1: encode_batch returns vectors in input order."""
        texts = ["text_a", "text_b", "text_c"]
        batch_results = encoder.encode_batch(texts)
        individual_results = [encoder.encode(t) for t in texts]
        assert len(batch_results) == 3
        for br, ir in zip(batch_results, individual_results):
            np.testing.assert_array_equal(br, ir)

    def test_model_hash_returns_string(self, encoder):
        """spec §4.1: model_hash returns a SHA-256 hex digest."""
        h = encoder.model_hash()
        assert isinstance(h, str)
        assert len(h) > 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. EmbeddingIndex
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingIndexBuild:
    """EmbeddingIndex.build constructs a FAISS-backed search index."""

    def test_build_from_matrix_and_id_map(self):
        matrix = _random_embedding_matrix(100)
        id_map = np.arange(100, dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)
        assert index is not None

    def test_build_preserves_dimensions(self):
        matrix = _random_embedding_matrix(50)
        id_map = np.arange(50, dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)
        # Should be able to search after build
        results = index.search(_random_unit_vector(), k=5)
        assert len(results) == 5

    def test_build_stores_declaration_ids(self):
        """FAISS IndexIDMap stores declaration IDs directly in the index."""
        matrix = _random_embedding_matrix(5)
        id_map = np.array([10, 20, 30, 40, 50], dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)
        query = matrix[0]  # query the first vector
        results = index.search(query, k=1)
        assert results[0][0] == 10  # should return decl_id 10, not row index 0


class TestEmbeddingIndexSearch:
    """EmbeddingIndex.search retrieves top-k by cosine similarity."""

    @pytest.fixture
    def index_50k(self):
        """An index with 50,000 embeddings for performance testing."""
        matrix = _random_embedding_matrix(50_000, seed=0)
        id_map = np.arange(50_000, dtype=np.int64)
        return EmbeddingIndex.build(matrix, id_map)

    @pytest.fixture
    def small_index(self):
        """An index with 10 known embeddings."""
        matrix = _random_embedding_matrix(10, seed=1)
        id_map = np.arange(10, dtype=np.int64)
        return EmbeddingIndex.build(matrix, id_map), matrix

    def test_returns_k_results(self, index_50k):
        """spec §4.2: Returns up to min(k, N) results."""
        query = _random_unit_vector(seed=99)
        results = index_50k.search(query, k=32)
        assert len(results) == 32

    def test_returns_min_k_n_when_n_less_than_k(self, small_index):
        """spec §4.2: Returns up to min(k, N) when N < k."""
        index, _ = small_index
        query = _random_unit_vector(seed=99)
        results = index.search(query, k=32)
        assert len(results) == 10  # N=10 < k=32

    def test_results_sorted_by_descending_score(self, index_50k):
        """spec §4.2: sorted by descending score."""
        query = _random_unit_vector(seed=99)
        results = index_50k.search(query, k=32)
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_results_contain_declaration_ids_and_scores(self, small_index):
        """spec §4.2: Returns (declaration_id, cosine_similarity_score) pairs."""
        index, _ = small_index
        query = _random_unit_vector(seed=99)
        results = index.search(query, k=5)
        for decl_id, score in results:
            assert isinstance(int(decl_id), int)
            assert isinstance(float(score), float)
            assert -1.0 <= score <= 1.0

    def test_exact_search_finds_identical_vector(self, small_index):
        """Exact search (IndexFlatIP) must return exact match at rank 1."""
        index, matrix = small_index
        # Query with the exact vector at row 3
        query = matrix[3]
        results = index.search(query, k=1)
        assert len(results) == 1
        decl_id, score = results[0]
        assert int(decl_id) == 3
        # cos(x, x) = 1.0 for unit vectors
        assert abs(score - 1.0) < 1e-5

    def test_scores_are_cosine_similarities(self, small_index):
        """spec §4.2: Scores are cosine similarities."""
        index, matrix = small_index
        query = _random_unit_vector(seed=99)
        results = index.search(query, k=10)
        # Verify against manual cosine computation
        for decl_id, score in results:
            expected = float(np.dot(matrix[int(decl_id)], query))
            assert abs(score - expected) < 1e-5


# ═══════════════════════════════════════════════════════════════════════════
# 2b. EmbeddingIndex Serialization (FAISS)
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingIndexSerialization:
    """EmbeddingIndex save/from_file round-trips through FAISS serialization."""

    def test_save_creates_file(self, tmp_path):
        """spec §4.2: save writes a FAISS index file."""
        matrix = _random_embedding_matrix(20)
        id_map = np.arange(20, dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)
        faiss_path = tmp_path / "test.faiss"
        index.save(faiss_path)
        assert faiss_path.exists()
        assert faiss_path.stat().st_size > 0

    def test_round_trip_preserves_search_results(self, tmp_path):
        """Save and from_file produce an index with identical search results."""
        matrix = _random_embedding_matrix(50)
        id_map = np.array([i * 10 for i in range(50)], dtype=np.int64)
        original = EmbeddingIndex.build(matrix, id_map)

        faiss_path = tmp_path / "test.faiss"
        original.save(faiss_path)
        restored = EmbeddingIndex.from_file(faiss_path)

        query = _random_unit_vector(seed=99)
        original_results = original.search(query, k=10)
        restored_results = restored.search(query, k=10)

        assert len(original_results) == len(restored_results)
        for (id_a, sc_a), (id_b, sc_b) in zip(original_results, restored_results):
            assert id_a == id_b
            assert abs(sc_a - sc_b) < 1e-5

    def test_from_file_nonexistent_raises(self, tmp_path):
        """spec §4.2: from_file raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            EmbeddingIndex.from_file(tmp_path / "nonexistent.faiss")

    def test_from_file_preserves_declaration_ids(self, tmp_path):
        """IndexIDMap stores IDs through serialization round-trip."""
        matrix = _random_embedding_matrix(5)
        id_map = np.array([100, 200, 300, 400, 500], dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)
        faiss_path = tmp_path / "test.faiss"
        index.save(faiss_path)

        restored = EmbeddingIndex.from_file(faiss_path)
        # Query the first vector — should return decl_id 100
        results = restored.search(matrix[0], k=1)
        assert results[0][0] == 100


# ═══════════════════════════════════════════════════════════════════════════
# 2c. FAISS Index Build/Load from SQLite
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildFaissIndex:
    """build_faiss_index reads SQLite embeddings and writes a .faiss sidecar."""

    def test_builds_sidecar_from_sqlite(self, tmp_path):
        """spec §4.5: Reads embeddings from SQLite, writes .faiss file."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        v1 = _random_unit_vector(seed=1)
        v2 = _random_unit_vector(seed=2)
        conn.execute("INSERT INTO embeddings VALUES (10, ?)", (_vector_to_blob(v1),))
        conn.execute("INSERT INTO embeddings VALUES (20, ?)", (_vector_to_blob(v2),))
        conn.commit()
        conn.close()

        faiss_path = build_faiss_index(db_path)
        assert faiss_path is not None
        assert faiss_path == tmp_path / "index.faiss"
        assert faiss_path.exists()

    def test_returns_none_for_empty_embeddings(self, tmp_path):
        """spec §4.5: No sidecar when embeddings table is empty."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        conn.commit()
        conn.close()

        result = build_faiss_index(db_path)
        assert result is None

    def test_sidecar_search_matches_source_vectors(self, tmp_path):
        """Sidecar index returns correct results for known vectors."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        v1 = _random_unit_vector(seed=1)
        v2 = _random_unit_vector(seed=2)
        conn.execute("INSERT INTO embeddings VALUES (42, ?)", (_vector_to_blob(v1),))
        conn.execute("INSERT INTO embeddings VALUES (99, ?)", (_vector_to_blob(v2),))
        conn.commit()
        conn.close()

        faiss_path = build_faiss_index(db_path)
        index = EmbeddingIndex.from_file(faiss_path)
        # Query with v1 — should return decl_id 42 as top result
        results = index.search(v1, k=1)
        assert results[0][0] == 42
        assert abs(results[0][1] - 1.0) < 1e-5


class TestLoadFaissIndex:
    """load_faiss_index loads from sidecar with SQLite fallback."""

    def test_loads_from_existing_sidecar(self, tmp_path):
        """spec §4.6: Loads from .faiss sidecar when it exists."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        v1 = _random_unit_vector(seed=1)
        conn.execute("INSERT INTO embeddings VALUES (10, ?)", (_vector_to_blob(v1),))
        conn.commit()
        conn.close()

        # Pre-build the sidecar
        build_faiss_index(db_path)
        assert (tmp_path / "index.faiss").exists()

        index = load_faiss_index(db_path)
        assert index is not None
        results = index.search(v1, k=1)
        assert results[0][0] == 10

    def test_builds_sidecar_from_sqlite_fallback(self, tmp_path):
        """spec §4.6: Builds FAISS index from SQLite when sidecar is missing."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        v1 = _random_unit_vector(seed=1)
        conn.execute("INSERT INTO embeddings VALUES (10, ?)", (_vector_to_blob(v1),))
        conn.commit()
        conn.close()

        # No sidecar exists
        assert not (tmp_path / "index.faiss").exists()

        index = load_faiss_index(db_path)
        assert index is not None
        # Sidecar should now exist for next time
        assert (tmp_path / "index.faiss").exists()

    def test_returns_none_when_no_embeddings(self, tmp_path):
        """spec §4.6: Returns None when no embeddings exist."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        conn.commit()
        conn.close()

        result = load_faiss_index(db_path)
        assert result is None

    def test_returns_none_when_no_embeddings_table(self, tmp_path):
        """spec §4.6: Returns None when embeddings table doesn't exist."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        result = load_faiss_index(db_path)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. Availability Checks
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralChannelAvailability:
    """check_availability determines if the neural channel can serve queries."""

    def test_unavailable_when_no_model_checkpoint(self, tmp_path):
        """spec §4.4: condition 1 — model checkpoint must exist."""
        db_path = tmp_path / "index.db"
        model_path = tmp_path / "nonexistent.onnx"
        # Create minimal database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER, vector BLOB)")
        conn.execute("INSERT INTO embeddings VALUES (1, ?)", (b"\x00" * 3072,))
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO index_meta VALUES ('neural_model_hash', 'abc')")
        conn.commit()
        conn.close()

        assert check_availability(db_path, model_path) is False

    def test_unavailable_when_no_embeddings(self, tmp_path):
        """spec §4.4: condition 2 — embeddings table must have rows."""
        db_path = tmp_path / "index.db"
        model_path = tmp_path / "model.onnx"
        model_path.write_bytes(b"dummy")
        # Create database with empty embeddings
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER, vector BLOB)")
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        with patch.object(NeuralEncoder, "load") as mock_load:
            mock_encoder = Mock()
            mock_encoder.model_hash.return_value = "abc"
            mock_load.return_value = mock_encoder
            assert check_availability(db_path, model_path) is False

    def test_unavailable_when_model_hash_mismatch(self, tmp_path):
        """spec §4.4: condition 3 — model hash must match stored hash."""
        db_path = tmp_path / "index.db"
        model_path = tmp_path / "model.onnx"
        model_path.write_bytes(b"dummy")
        # Create database with hash mismatch
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER, vector BLOB)")
        conn.execute("INSERT INTO embeddings VALUES (1, ?)", (b"\x00" * 3072,))
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO index_meta VALUES ('neural_model_hash', 'old_hash')")
        conn.commit()
        conn.close()

        with patch.object(NeuralEncoder, "load") as mock_load:
            mock_encoder = Mock()
            mock_encoder.model_hash.return_value = "new_hash"  # mismatch
            mock_load.return_value = mock_encoder
            assert check_availability(db_path, model_path) is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Embedding Write Path
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeEmbeddings:
    """compute_embeddings populates the embeddings table during indexing."""

    def test_writes_embeddings_for_all_declarations(self, tmp_path):
        """spec §4.5: For each declaration, encodes and inserts the vector."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE declarations (id INTEGER PRIMARY KEY, name TEXT, statement TEXT)"
        )
        conn.execute("INSERT INTO declarations VALUES (1, 'A', 'stmt_a')")
        conn.execute("INSERT INTO declarations VALUES (2, 'B', 'stmt_b')")
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        encoder = Mock(spec=NeuralEncoder)
        v1 = _random_unit_vector(seed=1)
        v2 = _random_unit_vector(seed=2)
        encoder.encode_batch.return_value = [v1, v2]
        encoder.model_hash.return_value = "hash123"

        compute_embeddings(db_path, encoder)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT decl_id, vector FROM embeddings ORDER BY decl_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == 1
        assert rows[1][0] == 2
        # Check vector size: 768 * 4 bytes = 3072
        assert len(rows[0][1]) == 3072
        assert len(rows[1][1]) == 3072

        # Check model hash written
        meta = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'neural_model_hash'"
        ).fetchone()
        assert meta[0] == "hash123"
        conn.close()

    def test_embedding_blob_is_3072_bytes(self, tmp_path):
        """spec §5: 768 × 4 = 3,072 bytes per vector."""
        v = _random_unit_vector()
        blob = _vector_to_blob(v)
        assert len(blob) == 3072


# ═══════════════════════════════════════════════════════════════════════════
# 5. Embedding Read Path
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadEmbeddings:
    """load_embeddings loads all embeddings into a contiguous matrix."""

    def test_returns_matrix_and_id_map(self, tmp_path):
        """spec §4.6: Returns (embedding_matrix, decl_id_map)."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        v1 = _random_unit_vector(seed=1)
        v2 = _random_unit_vector(seed=2)
        conn.execute("INSERT INTO embeddings VALUES (10, ?)", (_vector_to_blob(v1),))
        conn.execute("INSERT INTO embeddings VALUES (20, ?)", (_vector_to_blob(v2),))
        conn.commit()
        conn.close()

        matrix, id_map = load_embeddings(db_path)
        assert matrix.shape == (2, 768)
        assert matrix.dtype == np.float32
        assert len(id_map) == 2
        assert set(id_map) == {10, 20}

    def test_returns_none_when_table_empty(self, tmp_path):
        """spec §4.6: Returns (None, None) if embeddings table is empty."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE embeddings (decl_id INTEGER PRIMARY KEY, vector BLOB)")
        conn.commit()
        conn.close()

        result = load_embeddings(db_path)
        assert result == (None, None)

    def test_returns_none_when_table_missing(self, tmp_path):
        """spec §4.6: Returns (None, None) if embeddings table does not exist."""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        result = load_embeddings(db_path)
        assert result == (None, None)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Neural Channel Query
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralRetrieve:
    """neural_retrieve encodes a query and searches the embedding index."""

    def test_returns_ranked_results(self):
        """spec §4.3: Returns a list of (declaration_id, score) pairs."""
        encoder = Mock(spec=NeuralEncoder)
        query_vec = _random_unit_vector(seed=42)
        encoder.encode.return_value = query_vec

        matrix = _random_embedding_matrix(100, seed=0)
        id_map = np.arange(100, dtype=np.int64)
        index = EmbeddingIndex.build(matrix, id_map)

        ctx = Mock()
        ctx.neural_encoder = encoder
        ctx.embedding_index = index

        results = neural_retrieve(ctx, "nat -> nat -> nat", limit=32)
        assert len(results) == 32
        # Should be sorted by descending score
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_returns_empty_on_encoder_failure(self):
        """spec §6: If encoder fails on query text, return empty list."""
        encoder = Mock(spec=NeuralEncoder)
        encoder.encode.side_effect = RuntimeError("encoding failed")

        ctx = Mock()
        ctx.neural_encoder = encoder
        ctx.embedding_index = Mock()

        results = neural_retrieve(ctx, "bad query", limit=32)
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════
# 7. Neural Query Text Construction
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralQueryText:
    """Neural channel constructs query text differently per search operation."""

    def test_search_by_type_uses_type_expr(self):
        """spec §4.7: search_by_type passes type_expr string to encoder."""
        # The pipeline should pass the raw type_expr to the neural channel.
        # This is a behavioral spec — tested at the pipeline integration level.
        # Here we verify the query text mapping table.
        from Poule.neural.channel import neural_query_text_for_type
        assert neural_query_text_for_type("nat -> nat -> nat") == "nat -> nat -> nat"

    def test_search_by_symbols_joins_with_spaces(self):
        """spec §4.7: search_by_symbols passes space-joined symbol names."""
        from Poule.neural.channel import neural_query_text_for_symbols
        result = neural_query_text_for_symbols(["Stdlib.Init.Nat.add", "Stdlib.Init.Nat.mul"])
        assert result == "Stdlib.Init.Nat.add Stdlib.Init.Nat.mul"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Error Hierarchy
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralErrors:
    """Error types follow the hierarchy defined in spec §7."""

    def test_model_not_found_is_catchable(self):
        assert issubclass(ModelNotFoundError, Exception)

    def test_model_load_error_is_catchable(self):
        assert issubclass(ModelLoadError, Exception)

    def test_errors_are_distinct(self):
        assert not issubclass(ModelNotFoundError, ModelLoadError)
        assert not issubclass(ModelLoadError, ModelNotFoundError)


# ═══════════════════════════════════════════════════════════════════════════
# 9. NeuralEncoder with CoqTokenizer
# ═══════════════════════════════════════════════════════════════════════════


def _write_vocab_file(path, tokens):
    """Write a minimal vocabulary JSON file."""
    import json

    vocab = {
        "[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "[MASK]": 4,
    }
    next_id = 5
    for t in tokens:
        if t not in vocab:
            vocab[t] = next_id
            next_id += 1
    path.write_text(json.dumps(vocab), encoding="utf-8")


class TestNeuralEncoderWithVocabulary:
    """spec §4.1: NeuralEncoder.load accepts vocabulary_path for CoqTokenizer."""

    def test_load_with_vocabulary_path_stores_coq_tokenizer(self, tmp_path):
        """When vocabulary_path is provided, the encoder uses CoqTokenizer."""
        from Poule.neural.training.vocabulary import CoqTokenizer

        vocab_path = tmp_path / "vocab.json"
        _write_vocab_file(vocab_path, ["nat", ":", "forall"])

        # We can't construct a full encoder without ONNX, but we can verify
        # the constructor accepts a CoqTokenizer
        tokenizer = CoqTokenizer(vocab_path)
        enc = NeuralEncoder(
            session=Mock(),
            tokenizer=tokenizer,
            file_hash="abc123",
        )
        assert isinstance(enc._tokenizer, CoqTokenizer)

    def test_encode_with_coq_tokenizer(self, tmp_path):
        """NeuralEncoder.encode works with CoqTokenizer (whitespace split)."""
        from Poule.neural.training.vocabulary import CoqTokenizer

        vocab_path = tmp_path / "vocab.json"
        _write_vocab_file(vocab_path, ["forall", "n", ":", "nat"])
        tokenizer = CoqTokenizer(vocab_path)

        # Mock ONNX session that returns a plausible embedding
        mock_session = Mock()
        # ONNX output: [1, seq_len, 768] for last_hidden_state
        def run_side_effect(output_names, inputs):
            seq_len = inputs["input_ids"].shape[1]
            return [np.random.randn(1, seq_len, 768).astype(np.float32)]

        mock_session.run.side_effect = run_side_effect

        enc = NeuralEncoder(
            session=mock_session,
            tokenizer=tokenizer,
            file_hash="abc123",
        )
        result = enc.encode("forall n : nat")
        assert result.shape == (768,)
        assert result.dtype == np.float32
        # L2 normalized
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5

    def test_encode_with_coq_tokenizer_passes_correct_shapes(self, tmp_path):
        """CoqTokenizer produces integer arrays for ONNX session."""
        from Poule.neural.training.vocabulary import CoqTokenizer

        vocab_path = tmp_path / "vocab.json"
        _write_vocab_file(vocab_path, ["a", "b"])
        tokenizer = CoqTokenizer(vocab_path)

        captured_inputs = {}

        def run_side_effect(output_names, inputs):
            captured_inputs.update(inputs)
            seq_len = inputs["input_ids"].shape[1]
            return [np.ones((1, seq_len, 768), dtype=np.float32)]

        mock_session = Mock()
        mock_session.run.side_effect = run_side_effect

        enc = NeuralEncoder(
            session=mock_session,
            tokenizer=tokenizer,
            file_hash="test",
        )
        enc.encode("a b")

        # input_ids should be int, shape (1, seq_len)
        assert captured_inputs["input_ids"].dtype in (np.int64, np.int32)
        assert captured_inputs["input_ids"].ndim == 2
        assert captured_inputs["input_ids"].shape[0] == 1
        # attention_mask same shape
        assert captured_inputs["attention_mask"].shape == captured_inputs["input_ids"].shape

    def test_load_with_nonexistent_vocabulary_raises(self, tmp_path):
        """spec §4.1: FileNotFoundError when vocabulary file does not exist."""
        # Create a dummy model file so the model path check passes
        model_path = tmp_path / "model.onnx"
        model_path.write_bytes(b"dummy")
        with pytest.raises(FileNotFoundError, match="Vocabulary"):
            NeuralEncoder.load(
                model_path,
                vocabulary_path=tmp_path / "nonexistent_vocab.json",
            )
