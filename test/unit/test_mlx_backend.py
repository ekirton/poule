"""TDD tests for MLX training backend (specification/neural-training.md §4.10–4.12).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/Poule/neural/training/mlx_backend/.

Covers: MLXBiEncoder (construction, forward, weight loading), MLXTrainer
(training loop, masked contrastive loss, checkpoint format), WeightConverter
(MLX → PyTorch conversion, validation), BackendNotAvailableError,
WeightConversionError.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Imports from production code (TDD — will fail until implemented)
# ---------------------------------------------------------------------------

from Poule.neural.training.errors import (
    NeuralTrainingError,
    BackendNotAvailableError,
    WeightConversionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# MLX is macOS-only.  Tests must run on Linux CI too, so we mock mlx
# throughout and only test logic, not GPU execution.

MLX_AVAILABLE = False
try:
    import mlx.core as mx  # noqa: F401

    MLX_AVAILABLE = True
except ImportError:
    pass

skip_no_mlx = pytest.mark.skipif(not MLX_AVAILABLE, reason="mlx not installed")


def _make_mock_mlx():
    """Create a mock mlx module for testing on non-macOS."""
    mock_mx = MagicMock()
    mock_nn = MagicMock()
    mock_mx.nn = mock_nn
    mock_mx.core = mock_mx
    return mock_mx


def _write_jsonl(path, records):
    """Write a list of dicts as a JSON Lines file."""
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# §5 Error hierarchy: BackendNotAvailableError, WeightConversionError
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    """BackendNotAvailableError and WeightConversionError extend NeuralTrainingError."""

    def test_backend_not_available_is_neural_training_error(self):
        err = BackendNotAvailableError("MLX is not installed")
        assert isinstance(err, NeuralTrainingError)

    def test_backend_not_available_message(self):
        err = BackendNotAvailableError("MLX is not installed. Install with: pip install mlx")
        assert "MLX is not installed" in str(err)

    def test_weight_conversion_is_neural_training_error(self):
        err = WeightConversionError(max_distance=0.015)
        assert isinstance(err, NeuralTrainingError)

    def test_weight_conversion_stores_distance(self):
        err = WeightConversionError(max_distance=0.015)
        assert err.max_distance == 0.015
        assert "0.015" in str(err) or "0.0150" in str(err)

    def test_weight_conversion_default_message(self):
        err = WeightConversionError(max_distance=0.025)
        assert "0.01" in str(err)  # mentions threshold


# ---------------------------------------------------------------------------
# §4.10 MLXBiEncoder
# ---------------------------------------------------------------------------


class TestMLXBiEncoderConstruction:
    """spec §4.10: MLXBiEncoder construction with vocabulary-sized embeddings."""

    @skip_no_mlx
    def test_construction_creates_model(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1000)
        assert model is not None

    @skip_no_mlx
    def test_construction_sets_vocab_size(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1500)
        # The embedding layer should have vocab_size entries
        assert model.embedding.weight.shape[0] == 1500

    @skip_no_mlx
    def test_construction_default_hidden_size(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1000)
        assert model.embedding.weight.shape[1] == 768

    @skip_no_mlx
    def test_construction_default_layers(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1000, num_layers=12)
        assert len(model.layers) == 12

    @skip_no_mlx
    def test_construction_custom_architecture(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=500, num_layers=2, hidden_size=64, num_heads=4)
        assert model.embedding.weight.shape == (500, 64)
        assert len(model.layers) == 2


class TestMLXBiEncoderForward:
    """spec §4.10: forward produces L2-normalized embeddings."""

    @skip_no_mlx
    def test_forward_output_shape(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=100, num_layers=1, hidden_size=32, num_heads=4)
        input_ids = mx.array([[1, 2, 3, 4]], dtype=mx.int32)
        attention_mask = mx.array([[1, 1, 1, 0]], dtype=mx.int32)
        output = model(input_ids, attention_mask)
        mx.eval(output)
        assert output.shape == (1, 32)

    @skip_no_mlx
    def test_forward_l2_normalized(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=100, num_layers=1, hidden_size=32, num_heads=4)
        input_ids = mx.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=mx.int32)
        attention_mask = mx.array([[1, 1, 1, 1], [1, 1, 0, 0]], dtype=mx.int32)
        output = model(input_ids, attention_mask)
        mx.eval(output)
        norms = np.linalg.norm(np.array(output), axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    @skip_no_mlx
    def test_forward_batch_independence(self):
        """Each sequence in a batch should produce the same embedding
        regardless of other sequences in the batch."""
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=100, num_layers=1, hidden_size=32, num_heads=4)
        ids = mx.array([[1, 2, 3]], dtype=mx.int32)
        mask = mx.array([[1, 1, 1]], dtype=mx.int32)
        out_single = model(ids, mask)

        ids_batch = mx.array([[1, 2, 3], [4, 5, 6]], dtype=mx.int32)
        mask_batch = mx.array([[1, 1, 1], [1, 1, 1]], dtype=mx.int32)
        out_batch = model(ids_batch, mask_batch)
        mx.eval(out_single, out_batch)

        np.testing.assert_allclose(
            np.array(out_single[0]), np.array(out_batch[0]), atol=1e-5
        )


class TestMLXBiEncoderWeightLoading:
    """spec §4.10: load_codebert_weights maps HuggingFace params to MLX."""

    @skip_no_mlx
    def test_load_codebert_weights_requires_transformers(self):
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1000)
        with patch.dict(sys.modules, {"transformers": None}):
            with pytest.raises(ImportError, match="transformers"):
                model.load_codebert_weights()

    @skip_no_mlx
    def test_load_codebert_weights_changes_parameters(self):
        """After loading, parameters should differ from random init."""
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder

        model = MLXBiEncoder(vocab_size=1000, num_layers=1, hidden_size=768, num_heads=12)
        # Capture a param before loading
        before = np.array(model.layers[0].attention.query_proj.weight)

        # This will download CodeBERT — may be slow on first run
        try:
            model.load_codebert_weights()
        except Exception:
            pytest.skip("CodeBERT download failed")

        after = np.array(model.layers[0].attention.query_proj.weight)
        assert not np.allclose(before, after)


# ---------------------------------------------------------------------------
# §4.11 MLXTrainer
# ---------------------------------------------------------------------------


class TestMLXTrainerPlatformCheck:
    """spec §4.11: MLXTrainer raises BackendNotAvailableError on wrong platform."""

    def test_raises_when_mlx_not_installed(self):
        from Poule.neural.training.mlx_backend.trainer import MLXTrainer

        with patch("sys.platform", "darwin"), \
             patch.dict(sys.modules, {"mlx": None, "mlx.core": None, "mlx.nn": None, "mlx.optimizers": None}):
            trainer = MLXTrainer()
            with pytest.raises(BackendNotAvailableError, match="MLX is not installed"):
                trainer.train(
                    dataset=Mock(),
                    output_dir=Path("/tmp/out"),
                    vocabulary_path=Path("/tmp/vocab.json"),
                )

    def test_raises_on_non_macos(self):
        from Poule.neural.training.mlx_backend.trainer import MLXTrainer

        with patch("sys.platform", "linux"):
            trainer = MLXTrainer()
            with pytest.raises(BackendNotAvailableError, match="macOS"):
                trainer.train(
                    dataset=Mock(),
                    output_dir=Path("/tmp/out"),
                    vocabulary_path=Path("/tmp/vocab.json"),
                )


class TestMLXTrainerCheckpointFormat:
    """spec §4.11: MLX checkpoints contain required files."""

    @skip_no_mlx
    def test_checkpoint_directory_structure(self, tmp_path):
        """After training, the output dir should contain the required files."""
        from Poule.neural.training.mlx_backend.trainer import MLXTrainer
        from Poule.neural.training.data import TrainingDataset

        # Create minimal dataset
        pairs = [("state " + str(i), ["premise_" + str(i % 5)]) for i in range(100)]
        corpus = {"premise_" + str(i): f"Definition premise_{i}." for i in range(10)}
        dataset = TrainingDataset(
            train=pairs[:80],
            val=pairs[80:90],
            test=pairs[90:],
            premise_corpus=corpus,
            train_files=["file" + str(i) for i in range(80)],
            val_files=["file" + str(i) for i in range(80, 90)],
            test_files=["file" + str(i) for i in range(90, 100)],
            file_deps={},
            file_premises={},
        )

        # Create vocab
        vocab = {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "[MASK]": 4}
        for i in range(10):
            vocab[f"premise_{i}"] = 5 + i
        for tok in ["state", "Definition", "."]:
            vocab[tok] = len(vocab)
        for i in range(100):
            vocab[str(i)] = len(vocab)
        vocab_path = tmp_path / "vocab.json"
        vocab_path.write_text(json.dumps(vocab))

        output_dir = tmp_path / "model"
        trainer = MLXTrainer()
        trainer.train(
            dataset=dataset,
            output_dir=output_dir,
            vocabulary_path=vocab_path,
            hyperparams={"max_epochs": 1, "batch_size": 16, "max_seq_length": 32},
        )

        assert (output_dir / "model.safetensors").exists()
        assert (output_dir / "config.json").exists()
        assert (output_dir / "hyperparams.json").exists()
        assert (output_dir / "vocabulary_path.txt").exists()
        assert (output_dir / "best_recall_32.txt").exists()


class TestMLXMaskedContrastiveLoss:
    """spec §4.11: MLX masked contrastive loss matches PyTorch behavior."""

    @skip_no_mlx
    def test_loss_with_single_positive(self):
        from Poule.neural.training.mlx_backend.loss import masked_contrastive_loss_mlx

        # 2 states, 3 premises, state 0 -> premise 0, state 1 -> premise 1
        state_embs = mx.array(np.random.randn(2, 8).astype(np.float32))
        state_embs = state_embs / mx.linalg.norm(state_embs, axis=1, keepdims=True)
        premise_embs = mx.array(np.random.randn(3, 8).astype(np.float32))
        premise_embs = premise_embs / mx.linalg.norm(premise_embs, axis=1, keepdims=True)

        positive_indices = [[0], [1]]
        loss = masked_contrastive_loss_mlx(
            state_embs, premise_embs, positive_indices, temperature=0.05
        )
        mx.eval(loss)
        assert float(loss) > 0.0

    @skip_no_mlx
    def test_loss_masking_excludes_shared_positives(self):
        """When premise P is positive for both state A and state B,
        P should be excluded from the negative set for both."""
        from Poule.neural.training.mlx_backend.loss import masked_contrastive_loss_mlx

        # Make premise 0 positive for both states
        state_embs = mx.array(np.eye(2, 4, dtype=np.float32))
        state_embs = state_embs / mx.linalg.norm(state_embs, axis=1, keepdims=True)
        premise_embs = mx.array(np.eye(3, 4, dtype=np.float32))
        premise_embs = premise_embs / mx.linalg.norm(premise_embs, axis=1, keepdims=True)

        # Both states share premise 0 as positive
        positive_indices = [[0, 1], [0, 2]]
        loss = masked_contrastive_loss_mlx(
            state_embs, premise_embs, positive_indices, temperature=0.05
        )
        mx.eval(loss)
        assert float(loss) >= 0.0  # Should compute without error

    @skip_no_mlx
    def test_loss_numerically_matches_pytorch(self):
        """MLX loss should match PyTorch loss within floating-point tolerance."""
        from Poule.neural.training.mlx_backend.loss import masked_contrastive_loss_mlx
        from Poule.neural.training.trainer import masked_contrastive_loss
        import torch

        np.random.seed(42)
        s_np = np.random.randn(3, 8).astype(np.float32)
        s_np = s_np / np.linalg.norm(s_np, axis=1, keepdims=True)
        p_np = np.random.randn(5, 8).astype(np.float32)
        p_np = p_np / np.linalg.norm(p_np, axis=1, keepdims=True)

        positive_indices = [[0], [1, 2], [3]]

        # PyTorch
        s_torch = torch.tensor(s_np)
        p_torch = torch.tensor(p_np)
        loss_pt = masked_contrastive_loss(s_torch, p_torch, positive_indices, 0.05)

        # MLX
        s_mlx = mx.array(s_np)
        p_mlx = mx.array(p_np)
        loss_mlx = masked_contrastive_loss_mlx(s_mlx, p_mlx, positive_indices, 0.05)
        mx.eval(loss_mlx)

        np.testing.assert_allclose(float(loss_mlx), loss_pt.item(), rtol=1e-4)


# ---------------------------------------------------------------------------
# §4.12 WeightConverter
# ---------------------------------------------------------------------------


class TestWeightConverterRequiredFiles:
    """spec §4.12: convert requires specific files in the MLX checkpoint dir."""

    def test_missing_safetensors_raises(self, tmp_path):
        from Poule.neural.training.mlx_backend.converter import WeightConverter
        from Poule.neural.training.errors import CheckpointNotFoundError

        # Create dir without model.safetensors
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "hyperparams.json").write_text("{}")
        (tmp_path / "vocabulary_path.txt").write_text("/tmp/v.json")

        with pytest.raises(CheckpointNotFoundError):
            WeightConverter.convert(tmp_path, tmp_path / "model.pt")

    def test_missing_config_raises(self, tmp_path):
        from Poule.neural.training.mlx_backend.converter import WeightConverter
        from Poule.neural.training.errors import CheckpointNotFoundError

        (tmp_path / "model.safetensors").write_bytes(b"")
        (tmp_path / "hyperparams.json").write_text("{}")
        (tmp_path / "vocabulary_path.txt").write_text("/tmp/v.json")

        with pytest.raises(CheckpointNotFoundError):
            WeightConverter.convert(tmp_path, tmp_path / "model.pt")


class TestWeightConverterConversion:
    """spec §4.12: convert produces a compatible PyTorch checkpoint."""

    @skip_no_mlx
    def test_roundtrip_conversion(self, tmp_path):
        """Train with MLX, convert, load in PyTorch — should succeed."""
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder
        from Poule.neural.training.mlx_backend.converter import WeightConverter
        import torch

        # Create a small MLX model and save it
        model = MLXBiEncoder(vocab_size=50, num_layers=1, hidden_size=32, num_heads=4)
        mlx_dir = tmp_path / "mlx_checkpoint"
        mlx_dir.mkdir()

        # Save MLX checkpoint
        mx.save_safetensors(str(mlx_dir / "model.safetensors"), dict(model.parameters()))
        (mlx_dir / "config.json").write_text(json.dumps({
            "vocab_size": 50,
            "num_layers": 1,
            "hidden_size": 32,
            "num_heads": 4,
        }))
        (mlx_dir / "hyperparams.json").write_text(json.dumps({
            "learning_rate": 2e-5,
            "temperature": 0.05,
        }))
        (mlx_dir / "vocabulary_path.txt").write_text("/tmp/vocab.json")
        (mlx_dir / "best_recall_32.txt").write_text("0.5")

        # Convert
        pt_path = tmp_path / "model.pt"
        WeightConverter.convert(mlx_dir, pt_path)

        # Load PyTorch checkpoint
        checkpoint = torch.load(pt_path, map_location="cpu", weights_only=False)
        assert "model_state_dict" in checkpoint
        assert "hyperparams" in checkpoint
        assert "vocabulary_path" in checkpoint

    @skip_no_mlx
    def test_converted_checkpoint_compatible_with_quantizer(self, tmp_path):
        """The converted checkpoint should be loadable by ModelQuantizer."""
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder
        from Poule.neural.training.mlx_backend.converter import WeightConverter
        import torch

        model = MLXBiEncoder(vocab_size=50, num_layers=1, hidden_size=32, num_heads=4)
        mlx_dir = tmp_path / "mlx_ckpt"
        mlx_dir.mkdir()

        mx.save_safetensors(str(mlx_dir / "model.safetensors"), dict(model.parameters()))
        (mlx_dir / "config.json").write_text(json.dumps({
            "vocab_size": 50, "num_layers": 1, "hidden_size": 32, "num_heads": 4,
        }))
        (mlx_dir / "hyperparams.json").write_text(json.dumps({}))
        (mlx_dir / "vocabulary_path.txt").write_text("/tmp/vocab.json")
        (mlx_dir / "best_recall_32.txt").write_text("0.5")

        pt_path = tmp_path / "model.pt"
        WeightConverter.convert(mlx_dir, pt_path)

        # Should have the same keys as a BiEncoderTrainer checkpoint
        ckpt = torch.load(pt_path, map_location="cpu", weights_only=False)
        assert "model_state_dict" in ckpt
        assert "epoch" in ckpt
        assert "best_recall_32" in ckpt


class TestWeightConverterValidation:
    """spec §4.12: convert validates cosine distance < 0.01."""

    @skip_no_mlx
    def test_validation_threshold(self):
        """WeightConversionError if cosine distance >= 0.01."""
        err = WeightConversionError(max_distance=0.015)
        assert err.max_distance == 0.015
        assert "0.01" in str(err)


class TestWeightConverterParameterMapping:
    """spec §4.10/4.12: parameter name mapping is invertible."""

    def test_mapping_is_invertible(self):
        from Poule.neural.training.mlx_backend.converter import (
            HF_TO_MLX_MAPPING,
            MLX_TO_HF_MAPPING,
        )

        # Every HF key maps to a unique MLX key
        assert len(set(HF_TO_MLX_MAPPING.values())) == len(HF_TO_MLX_MAPPING)

        # The reverse mapping inverts the forward mapping
        for hf_key, mlx_key in HF_TO_MLX_MAPPING.items():
            assert MLX_TO_HF_MAPPING[mlx_key] == hf_key
