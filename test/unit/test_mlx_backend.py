"""Tests for MLX training backend (specification/neural-training.md §4.10–4.12).

Covers: MLXTrainer (platform checks), WeightConverter
(MLX → PyTorch conversion, validation, parameter mapping),
BackendNotAvailableError, WeightConversionError.
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
        from Poule.neural.training.mlx_backend.model import MLXTacticClassifier
        from Poule.neural.training.mlx_backend.converter import WeightConverter
        import torch

        # Create a small MLX model and save it
        model = MLXTacticClassifier(
            vocab_size=50, num_categories=2,
            per_category_sizes={"cat_a": 3, "cat_b": 2},
            num_layers=1, hidden_size=32, num_heads=4,
        )
        mlx_dir = tmp_path / "mlx_checkpoint"
        mlx_dir.mkdir()

        # Save MLX checkpoint
        import mlx.nn as mlx_nn
        mx.save_safetensors(str(mlx_dir / "model.safetensors"), dict(mlx_nn.utils.tree_flatten(model.parameters())))
        (mlx_dir / "config.json").write_text(json.dumps({
            "vocab_size": 50,
            "num_layers": 1,
            "hidden_size": 32,
            "num_heads": 4,
            "num_categories": 2,
            "per_category_sizes": {"cat_a": 3, "cat_b": 2},
        }))
        (mlx_dir / "hyperparams.json").write_text(json.dumps({
            "learning_rate": 2e-5,
        }))
        (mlx_dir / "vocabulary_path.txt").write_text("/tmp/vocab.json")
        (mlx_dir / "best_accuracy_5.txt").write_text("0.5")

        # Convert
        pt_path = tmp_path / "model.pt"
        WeightConverter.convert(mlx_dir, pt_path)

        # Load PyTorch checkpoint
        checkpoint = torch.load(pt_path, map_location="cpu", weights_only=False)
        assert "model_state_dict" in checkpoint
        assert "hyperparams" in checkpoint
        assert "vocabulary_path" in checkpoint


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
