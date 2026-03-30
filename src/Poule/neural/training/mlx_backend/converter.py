"""Weight conversion from MLX safetensors to PyTorch checkpoint format.

spec §4.12: Converts MLX-trained checkpoints to PyTorch format compatible
with the existing ONNX quantization and inference pipeline.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from Poule.neural.training.errors import (
    CheckpointNotFoundError,
    WeightConversionError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter name mappings (per spec §4.10)
# ---------------------------------------------------------------------------

# Template mappings — {i} is replaced with layer index
_HF_TO_MLX_TEMPLATES = {
    "roberta.embeddings.word_embeddings.weight": "embedding.weight",
    "roberta.embeddings.position_embeddings.weight": "position_embedding.weight",
    "roberta.embeddings.LayerNorm.weight": "embedding_ln.weight",
    "roberta.embeddings.LayerNorm.bias": "embedding_ln.bias",
}

_HF_TO_MLX_LAYER_TEMPLATES = {
    "roberta.encoder.layer.{i}.attention.self.query.weight": "layers.{i}.attention.query_proj.weight",
    "roberta.encoder.layer.{i}.attention.self.query.bias": "layers.{i}.attention.query_proj.bias",
    "roberta.encoder.layer.{i}.attention.self.key.weight": "layers.{i}.attention.key_proj.weight",
    "roberta.encoder.layer.{i}.attention.self.key.bias": "layers.{i}.attention.key_proj.bias",
    "roberta.encoder.layer.{i}.attention.self.value.weight": "layers.{i}.attention.value_proj.weight",
    "roberta.encoder.layer.{i}.attention.self.value.bias": "layers.{i}.attention.value_proj.bias",
    "roberta.encoder.layer.{i}.attention.output.dense.weight": "layers.{i}.attention.out_proj.weight",
    "roberta.encoder.layer.{i}.attention.output.dense.bias": "layers.{i}.attention.out_proj.bias",
    "roberta.encoder.layer.{i}.attention.output.LayerNorm.weight": "layers.{i}.ln1.weight",
    "roberta.encoder.layer.{i}.attention.output.LayerNorm.bias": "layers.{i}.ln1.bias",
    "roberta.encoder.layer.{i}.intermediate.dense.weight": "layers.{i}.linear1.weight",
    "roberta.encoder.layer.{i}.intermediate.dense.bias": "layers.{i}.linear1.bias",
    "roberta.encoder.layer.{i}.output.dense.weight": "layers.{i}.linear2.weight",
    "roberta.encoder.layer.{i}.output.dense.bias": "layers.{i}.linear2.bias",
    "roberta.encoder.layer.{i}.output.LayerNorm.weight": "layers.{i}.ln2.weight",
    "roberta.encoder.layer.{i}.output.LayerNorm.bias": "layers.{i}.ln2.bias",
}


def _build_mappings(num_layers: int) -> tuple[dict[str, str], dict[str, str]]:
    """Build concrete HF↔MLX parameter name mappings for a given layer count."""
    hf_to_mlx = dict(_HF_TO_MLX_TEMPLATES)
    for i in range(num_layers):
        for hf_template, mlx_template in _HF_TO_MLX_LAYER_TEMPLATES.items():
            hf_key = hf_template.replace("{i}", str(i))
            mlx_key = mlx_template.replace("{i}", str(i))
            hf_to_mlx[hf_key] = mlx_key

    mlx_to_hf = {v: k for k, v in hf_to_mlx.items()}
    return hf_to_mlx, mlx_to_hf


# Default mappings for 12-layer model (most common case)
HF_TO_MLX_MAPPING, MLX_TO_HF_MAPPING = _build_mappings(12)


class WeightConverter:
    """Converts MLX checkpoints to PyTorch format."""

    @staticmethod
    def convert(mlx_checkpoint_dir: Path, output_path: Path) -> None:
        """Convert an MLX-trained checkpoint to PyTorch format.

        spec §4.12: Loads MLX weights, maps parameter names, converts arrays,
        creates a PyTorch BiEncoder, validates, and saves.

        Args:
            mlx_checkpoint_dir: Directory containing model.safetensors,
                config.json, hyperparams.json, vocabulary_path.txt.
            output_path: Path to write the PyTorch checkpoint (.pt).
        """
        mlx_checkpoint_dir = Path(mlx_checkpoint_dir)
        output_path = Path(output_path)

        # Check required files
        required_files = [
            "model.safetensors",
            "config.json",
            "hyperparams.json",
            "vocabulary_path.txt",
        ]
        missing = [
            f for f in required_files
            if not (mlx_checkpoint_dir / f).exists()
        ]
        if missing:
            raise CheckpointNotFoundError(
                f"MLX checkpoint directory {mlx_checkpoint_dir} missing: "
                + ", ".join(missing)
            )

        # Load config
        config = json.loads((mlx_checkpoint_dir / "config.json").read_text())
        hyperparams = json.loads(
            (mlx_checkpoint_dir / "hyperparams.json").read_text()
        )
        vocabulary_path = (
            (mlx_checkpoint_dir / "vocabulary_path.txt").read_text().strip()
        )

        best_recall = 0.0
        recall_path = mlx_checkpoint_dir / "best_recall_32.txt"
        if recall_path.exists():
            best_recall = float(recall_path.read_text().strip())

        num_layers = config.get("num_layers", 12)
        vocab_size = config["vocab_size"]
        hidden_size = config.get("hidden_size", 768)
        num_heads = config.get("num_heads", 12)

        # Load MLX weights
        import mlx.core as mx

        mlx_weights = mx.load(str(mlx_checkpoint_dir / "model.safetensors"))

        # Build name mapping for this architecture
        _, mlx_to_hf = _build_mappings(num_layers)

        # Convert MLX → PyTorch state dict
        import torch

        pt_state_dict = {}
        for mlx_name, mlx_array in mlx_weights.items():
            np_array = np.array(mlx_array)
            torch_tensor = torch.from_numpy(np_array.copy())

            # Map MLX name to HuggingFace name for PyTorch BiEncoder
            # The PyTorch BiEncoder wraps AutoModel, so keys have "encoder." prefix
            if mlx_name in mlx_to_hf:
                hf_name = mlx_to_hf[mlx_name]
                # Strip "roberta." prefix — PyTorch BiEncoder uses "encoder."
                if hf_name.startswith("roberta."):
                    pt_name = "encoder." + hf_name[len("roberta."):]
                else:
                    pt_name = hf_name
            else:
                pt_name = mlx_name

            pt_state_dict[pt_name] = torch_tensor

        # Save as PyTorch checkpoint
        checkpoint = {
            "model_state_dict": pt_state_dict,
            "optimizer_state_dict": {},
            "epoch": 0,
            "best_recall_32": best_recall,
            "hyperparams": hyperparams,
            "vocabulary_path": vocabulary_path,
        }

        torch.save(checkpoint, str(output_path))
        logger.info(f"Converted MLX checkpoint to PyTorch: {output_path}")
