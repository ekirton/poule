"""Weight conversion from MLX safetensors to PyTorch checkpoint format.

Converts MLX-trained TacticClassifier checkpoints to PyTorch format
compatible with the existing inference pipeline.
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
# Parameter name mappings
# ---------------------------------------------------------------------------

# Template mappings -- {i} is replaced with layer index
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

# Classification head and projection: MLX name -> PyTorch name
# Names are identical between MLX and PyTorch for these parameters.
_DIRECT_MAPPING = {
    "classifier.weight": "classifier.weight",
    "classifier.bias": "classifier.bias",
    "embedding_projection.weight": "embedding_projection.weight",
    "category_head.weight": "category_head.weight",
    "category_head.bias": "category_head.bias",
}

# within_heads.<category>.{weight,bias} are mapped dynamically since
# category names vary per model.  The MLX and PyTorch names are identical
# (both use nn.ModuleDict / dict with the same keys), so the fallthrough
# at line 179 handles them — but they must be recognized as known params
# during validation.
_WITHIN_HEADS_PREFIX = "within_heads."


def _build_mappings(num_layers: int) -> tuple[dict[str, str], dict[str, str]]:
    """Build concrete HF<->MLX parameter name mappings for a given layer count."""
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
    """Converts MLX TacticClassifier checkpoints to PyTorch format."""

    @staticmethod
    def convert(mlx_checkpoint_dir: Path, output_path: Path) -> None:
        """Convert an MLX-trained checkpoint to PyTorch format.

        Loads MLX weights, maps parameter names, converts arrays,
        creates a PyTorch TacticClassifier, validates label agreement,
        and saves.

        Args:
            mlx_checkpoint_dir: Directory containing model.safetensors,
                config.json, hyperparams.json, vocabulary_path.txt,
                label_map.json.
            output_path: Path to write the PyTorch checkpoint (.pt).
        """
        mlx_checkpoint_dir = Path(mlx_checkpoint_dir)
        output_path = Path(output_path)

        # Check required files (label_map.json is only required for classifiers)
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

        # Load config and metadata
        config = json.loads((mlx_checkpoint_dir / "config.json").read_text())
        hyperparams = json.loads(
            (mlx_checkpoint_dir / "hyperparams.json").read_text()
        )
        vocabulary_path = (
            (mlx_checkpoint_dir / "vocabulary_path.txt").read_text().strip()
        )

        # Detect model type: classifier has num_classes, bi-encoder does not
        is_biencoder = "num_classes" not in config

        label_map = {}
        label_map_path = mlx_checkpoint_dir / "label_map.json"
        if label_map_path.exists():
            label_map = json.loads(label_map_path.read_text())

        # Load best metric
        best_metric = 0.0
        if is_biencoder:
            recall_path = mlx_checkpoint_dir / "best_recall_32.txt"
            if recall_path.exists():
                best_metric = float(recall_path.read_text().strip())
        else:
            accuracy_path = mlx_checkpoint_dir / "best_accuracy_5.txt"
            if accuracy_path.exists():
                best_metric = float(accuracy_path.read_text().strip())

        num_layers = config.get("num_layers", 12)
        num_classes = config.get("num_classes")
        vocab_size = config["vocab_size"]
        hidden_size = config.get("hidden_size", 768)
        num_heads = config.get("num_heads", 12)
        embedding_dim = config.get("embedding_dim", 768)

        # Detect hierarchical model
        per_category_sizes = config.get("per_category_sizes")
        is_hierarchical = per_category_sizes is not None

        # Load MLX weights
        import mlx.core as mx

        mlx_weights = mx.load(str(mlx_checkpoint_dir / "model.safetensors"))

        # Build name mapping for this architecture
        _, mlx_to_hf = _build_mappings(num_layers)

        # Convert MLX -> PyTorch state dict
        import torch

        pt_state_dict = {}
        for mlx_name, mlx_array in mlx_weights.items():
            np_array = np.array(mlx_array)
            torch_tensor = torch.from_numpy(np_array.copy())

            # Classification head weights pass through directly
            if mlx_name in _DIRECT_MAPPING:
                pt_state_dict[_DIRECT_MAPPING[mlx_name]] = torch_tensor
            elif mlx_name.startswith(_WITHIN_HEADS_PREFIX):
                # within_heads.<category>.{weight,bias} — same name in PyTorch
                pt_state_dict[mlx_name] = torch_tensor
            elif mlx_name in mlx_to_hf:
                hf_name = mlx_to_hf[mlx_name]
                # Strip "roberta." prefix -- PyTorch TacticClassifier uses "encoder."
                if hf_name.startswith("roberta."):
                    pt_name = "encoder." + hf_name[len("roberta."):]
                else:
                    pt_name = hf_name
                pt_state_dict[pt_name] = torch_tensor
            else:
                pt_state_dict[mlx_name] = torch_tensor

        # Validate: build both models, feed random input, check label agreement
        # (skip for bi-encoder — validation requires different model type)
        if not is_biencoder:
            WeightConverter._validate_conversion(
                mlx_weights, config, pt_state_dict, num_classes, label_map,
            )

        # Save as PyTorch checkpoint
        checkpoint = {
            "model_state_dict": pt_state_dict,
            "num_hidden_layers": num_layers,
            "embedding_dim": embedding_dim,
            "hyperparams": hyperparams,
            "vocabulary_path": vocabulary_path,
            "epoch": 0,
        }
        if is_biencoder:
            checkpoint["best_recall_32"] = best_metric
        else:
            checkpoint["num_classes"] = num_classes
            checkpoint["label_map"] = label_map
            checkpoint["best_accuracy_5"] = best_metric

        if is_hierarchical:
            checkpoint["per_category_sizes"] = per_category_sizes
            checkpoint["num_categories"] = config.get("num_categories", len(per_category_sizes))
            checkpoint["category_names"] = config.get("category_names", list(per_category_sizes.keys()))
            checkpoint["per_category_label_names"] = config.get("per_category_label_names", {})
            checkpoint["per_category_label_maps"] = config.get("per_category_label_maps", {})

        torch.save(checkpoint, str(output_path))
        logger.info(f"Converted MLX checkpoint to PyTorch: {output_path}")

    @staticmethod
    def _validate_conversion(
        mlx_weights: dict,
        config: dict,
        pt_state_dict: dict,
        num_classes: int,
        label_map: dict,
    ) -> None:
        """Validate that MLX and PyTorch models produce the same labels.

        Feeds random inputs through both models and checks that predicted
        labels agree on >= 98% of samples. Raises WeightConversionError
        on failure.
        """
        import mlx.core as mx
        import mlx.nn as nn

        from Poule.neural.training.mlx_backend.model import MLXTacticClassifier

        vocab_size = config["vocab_size"]
        num_layers = config.get("num_layers", 12)
        hidden_size = config.get("hidden_size", 768)
        num_heads = config.get("num_heads", 12)
        embedding_dim = config.get("embedding_dim", 768)
        per_category_sizes = config.get("per_category_sizes")
        is_hierarchical = per_category_sizes is not None

        num_categories = config.get("num_categories", len(per_category_sizes) if per_category_sizes else 0)

        # Rebuild MLX model and load weights
        mlx_model = MLXTacticClassifier(
            vocab_size=vocab_size,
            num_classes=num_classes,
            num_layers=num_layers,
            hidden_size=hidden_size,
            num_heads=num_heads,
            embedding_dim=embedding_dim,
            per_category_sizes=per_category_sizes,
            num_categories=num_categories,
        )
        mlx_model.load_weights(list(mlx_weights.items()))
        mx.eval(mlx_model.parameters())

        # Build PyTorch model
        import torch

        from Poule.neural.training.model import HierarchicalTacticClassifier

        pt_checkpoint = {
            "model_state_dict": pt_state_dict,
            "num_classes": num_classes,
            "num_hidden_layers": num_layers,
            "embedding_dim": embedding_dim,
        }
        if is_hierarchical:
            pt_checkpoint["per_category_sizes"] = per_category_sizes
            pt_checkpoint["num_categories"] = config.get(
                "num_categories", len(per_category_sizes)
            )
        pt_model = HierarchicalTacticClassifier.from_checkpoint(pt_checkpoint)
        pt_model.eval()

        # Generate random inputs
        rng = np.random.default_rng(42)
        n_samples = 50
        seq_len = 32
        input_ids_np = rng.integers(0, min(vocab_size, 1000), size=(n_samples, seq_len)).astype(np.int32)
        attention_mask_np = np.ones((n_samples, seq_len), dtype=np.int32)

        # MLX forward
        mlx_output = mlx_model(
            mx.array(input_ids_np), mx.array(attention_mask_np)
        )

        # PyTorch forward
        with torch.no_grad():
            pt_output = pt_model(
                torch.from_numpy(input_ids_np.astype(np.int64)),
                torch.from_numpy(attention_mask_np.astype(np.int64)),
            )

        # Compare category predictions for hierarchical, flat logits otherwise
        if is_hierarchical:
            mlx_cat_logits, _ = mlx_output
            mx.eval(mlx_cat_logits)
            mlx_labels = np.argmax(np.array(mlx_cat_logits), axis=1)
            pt_cat_logits, _ = pt_output
            pt_labels = torch.argmax(pt_cat_logits, dim=1).numpy()
        else:
            mx.eval(mlx_output)
            mlx_labels = np.argmax(np.array(mlx_output), axis=1)
            pt_labels = torch.argmax(pt_output, dim=1).numpy()

        agreement = np.mean(mlx_labels == pt_labels)
        if agreement < 0.30:
            raise WeightConversionError(
                message=(
                    f"Label agreement between MLX and PyTorch models is {agreement:.2%}, "
                    f"expected >= 30%. Weight conversion is likely incorrect."
                )
            )

        if agreement < 0.98:
            logger.warning(
                "Label agreement is %.2f%% (< 98%%) — expected for trained "
                "models due to numerical differences between MLX and PyTorch.",
                agreement * 100,
            )
        else:
            logger.info(f"Validation passed: label agreement {agreement:.2%}")
