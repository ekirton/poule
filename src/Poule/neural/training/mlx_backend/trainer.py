"""MLX training loop for tactic classifier model.

Functional gradient computation using mlx.nn.value_and_grad.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np

from Poule.neural.training.data import TacticDataset
from Poule.neural.training.errors import (
    BackendNotAvailableError,
    InsufficientDataError,
)
from Poule.neural.training.trainer import DEFAULT_HYPERPARAMS, EarlyStoppingTracker

logger = logging.getLogger(__name__)


class MLXTrainer:
    """Trains a tactic classifier model using MLX on Apple Silicon.

    Creates an MLXTacticClassifier, trains with functional gradients and
    weighted cross-entropy loss, saves checkpoints in MLX safetensors format.
    """

    def _check_platform(self) -> None:
        """Verify MLX is available and platform is macOS."""
        if sys.platform != "darwin":
            raise BackendNotAvailableError(
                "MLX training requires macOS with Apple Silicon"
            )
        try:
            import mlx.core  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            raise BackendNotAvailableError(
                "MLX is not installed. Install with: pip install mlx"
            )

    def train(
        self,
        dataset: TacticDataset,
        output_dir: Path,
        vocabulary_path: Path,
        hyperparams: dict[str, Any] | None = None,
        epoch_callback: Callable[[int, float], None] | None = None,
    ) -> None:
        """Train a tactic classifier model using MLX.

        Args:
            dataset: TacticDataset with train/val/test splits and label metadata.
            output_dir: Directory to save MLX checkpoint.
            vocabulary_path: Path to closed vocabulary JSON.
            hyperparams: Override default hyperparameters.
            epoch_callback: Called after each epoch with (epoch, val_accuracy@5).
        """
        self._check_platform()

        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim

        from Poule.neural.training.mlx_backend.loss import cross_entropy_loss
        from Poule.neural.training.mlx_backend.model import MLXTacticClassifier
        from Poule.neural.training.vocabulary import CoqTokenizer

        # Merge hyperparams
        hp = dict(DEFAULT_HYPERPARAMS)
        if hyperparams:
            hp.update(hyperparams)

        batch_size = hp["batch_size"]
        lr = hp["learning_rate"]
        weight_decay = hp["weight_decay"]
        max_seq_length = hp["max_seq_length"]
        max_epochs = hp["max_epochs"]
        patience = hp["early_stopping_patience"]
        class_weight_alpha = hp.get("class_weight_alpha", 0.5)

        train_pairs = dataset.train_pairs
        if len(train_pairs) < 1000:
            raise InsufficientDataError(
                f"Need at least 1,000 training pairs, got {len(train_pairs)}"
            )

        num_classes = dataset.num_classes

        # Load tokenizer
        tokenizer = CoqTokenizer(str(vocabulary_path))

        model = MLXTacticClassifier(
            vocab_size=tokenizer.vocab_size,
            num_classes=num_classes,
        )
        mx.eval(model.parameters())

        # Compute class weights (inverse-frequency)
        class_weights = self._compute_class_weights(
            dataset.family_counts, dataset.label_map, num_classes,
            alpha=class_weight_alpha,
        )

        # Optimizer
        optimizer = optim.AdamW(learning_rate=lr, weight_decay=weight_decay)

        # Prepare output
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        early_stopping = EarlyStoppingTracker(patience)
        micro_batch_size = min(32, batch_size)
        accumulation_steps = max(1, batch_size // micro_batch_size)

        best_accuracy = -1.0
        best_epoch = 0
        training_log = []

        def _tokenize(texts: list[str]) -> tuple[mx.array, mx.array]:
            result = tokenizer.encode_batch(texts, max_length=max_seq_length)
            ids = mx.array(np.array(result["input_ids"], dtype=np.int32))
            mask = mx.array(np.array(result["attention_mask"], dtype=np.int32))
            return ids, mask

        for epoch in range(1, max_epochs + 1):
            # Shuffle training data
            indices = list(range(len(train_pairs)))
            random.shuffle(indices)

            epoch_loss = 0.0
            num_batches = 0

            total_micros = (len(indices) + micro_batch_size - 1) // micro_batch_size
            for batch_start in range(0, len(indices), micro_batch_size):
                micro_idx = batch_start // micro_batch_size
                if micro_idx % 50 == 0:
                    print(f"  micro-batch {micro_idx}/{total_micros}", flush=True)
                batch_indices = indices[batch_start:batch_start + micro_batch_size]
                batch_pairs = [train_pairs[i] for i in batch_indices]

                # Collect states and labels
                states = [p[0] for p in batch_pairs]
                labels = mx.array(
                    np.array([p[1] for p in batch_pairs], dtype=np.int32)
                )

                # Tokenize states
                s_ids, s_mask = _tokenize(states)

                # Forward + backward
                def loss_fn(model):
                    logits = model(s_ids, s_mask)
                    return cross_entropy_loss(logits, labels, class_weights)

                loss, grads = nn.value_and_grad(model, loss_fn)(model)
                optimizer.update(model, grads)
                mx.eval(model.parameters(), optimizer.state, loss)

                epoch_loss += float(loss)
                num_batches += 1

                # Free computation graph to prevent memory accumulation
                del loss, grads, s_ids, s_mask, labels

            avg_loss = epoch_loss / max(num_batches, 1)

            # Validation: accuracy@5
            val_accuracy = self._compute_accuracy_at_k(
                model, dataset.val_pairs, tokenizer, max_seq_length, k=5
            )

            logger.info(
                f"Epoch {epoch}: loss={avg_loss:.4f}, val_acc@5={val_accuracy:.4f}"
            )
            print(f"Epoch {epoch}: loss={avg_loss:.4f}, val_acc@5={val_accuracy:.4f}")

            training_log.append({
                "epoch": epoch,
                "loss": avg_loss,
                "val_accuracy_5": val_accuracy,
            })

            if epoch_callback is not None:
                epoch_callback(epoch, val_accuracy)

            # Save best checkpoint
            if val_accuracy > best_accuracy:
                best_accuracy = val_accuracy
                best_epoch = epoch
                self._save_checkpoint(
                    model, output_dir, hp, vocabulary_path,
                    best_accuracy, dataset.label_map,
                )

            if early_stopping.should_stop(val_accuracy):
                print(f"Early stopping at epoch {epoch} (best: epoch {best_epoch})")
                break

        # Save training log
        log_path = output_dir / "training_log.jsonl"
        with open(log_path, "w") as f:
            for entry in training_log:
                f.write(json.dumps(entry) + "\n")

        # Auto-convert to PyTorch checkpoint for downstream tools
        pt_path = output_dir / "model.pt"
        try:
            from Poule.neural.training.mlx_backend.converter import WeightConverter
            WeightConverter.convert(output_dir, pt_path)
            print(f"Converted MLX checkpoint to PyTorch: {pt_path}")
        except Exception as exc:
            logger.warning(f"Auto-conversion to PyTorch failed: {exc}")
            print(f"Warning: auto-conversion to model.pt failed: {exc}")
            print("Run `poule convert-checkpoint` manually, or pass model.safetensors directly.")

    _ENCODE_CHUNK = 256

    def _compute_accuracy_at_k(
        self,
        model,
        pairs: list[tuple[str, int]],
        tokenizer,
        max_seq_length: int,
        k: int = 5,
    ) -> float:
        """Compute Accuracy@k on the validation set, batched to bound memory."""
        import mlx.core as mx

        if not pairs:
            return 0.0

        def _tokenize(texts):
            result = tokenizer.encode_batch(texts, max_length=max_seq_length)
            ids = mx.array(np.array(result["input_ids"], dtype=np.int32))
            mask = mx.array(np.array(result["attention_mask"], dtype=np.int32))
            return ids, mask

        hits = 0
        for start in range(0, len(pairs), self._ENCODE_CHUNK):
            chunk = pairs[start:start + self._ENCODE_CHUNK]
            texts = [s for s, _ in chunk]
            labels = [lbl for _, lbl in chunk]

            s_ids, s_mask = _tokenize(texts)
            logits = model(s_ids, s_mask)
            mx.eval(logits)

            # Convert to numpy for top-k
            logits_np = np.array(logits)
            effective_k = min(k, logits_np.shape[1])
            # argsort descending, take top-k
            top_k_indices = np.argsort(logits_np, axis=1)[:, -effective_k:]

            for i, true_label in enumerate(labels):
                if true_label in top_k_indices[i]:
                    hits += 1

        return hits / len(pairs)

    @staticmethod
    def _compute_class_weights(
        family_counts: dict[str, int],
        label_map: dict[str, int],
        num_classes: int,
        alpha: float = 0.5,
    ) -> "mx.array":
        """Compute inverse-frequency class weights as an mx.array.

        weight[c] = (total / (num_classes * count[c])) ^ alpha
        """
        import mlx.core as mx

        total = sum(family_counts.values())
        weights = np.ones(num_classes, dtype=np.float32)

        for name, idx in label_map.items():
            count = family_counts.get(name, 1)
            weights[idx] = (total / (num_classes * count)) ** alpha

        return mx.array(weights)

    def _save_checkpoint(
        self,
        model,
        output_dir: Path,
        hyperparams: dict,
        vocabulary_path: Path,
        best_accuracy: float,
        label_map: dict[str, int],
    ) -> None:
        """Save MLX checkpoint in the spec-defined directory format."""
        import mlx.core as mx
        import mlx.nn as nn

        # Flatten model parameters using MLX's tree_flatten utility
        params = dict(nn.utils.tree_flatten(model.parameters()))
        mx.save_safetensors(str(output_dir / "model.safetensors"), params)

        config = {
            "vocab_size": model.embedding.weight.shape[0],
            "num_classes": model.num_classes,
            "num_layers": len(model.layers),
            "hidden_size": model.hidden_size,
            "num_heads": model.layers[0].attention.num_heads
            if hasattr(model.layers[0].attention, 'num_heads')
            else 12,
        }
        (output_dir / "config.json").write_text(json.dumps(config, indent=2))
        (output_dir / "hyperparams.json").write_text(
            json.dumps(hyperparams, indent=2)
        )
        (output_dir / "vocabulary_path.txt").write_text(str(vocabulary_path))
        (output_dir / "best_accuracy_5.txt").write_text(str(best_accuracy))
        (output_dir / "label_map.json").write_text(
            json.dumps(label_map, indent=2)
        )
