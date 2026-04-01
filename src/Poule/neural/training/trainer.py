"""Tactic classifier trainer with weighted cross-entropy loss and early stopping."""

from __future__ import annotations

import json
import logging
import math
import pickle
import random
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from Poule.neural.training.data import TacticDataset
from Poule.neural.training.errors import (
    CheckpointNotFoundError,
    InsufficientDataError,
    TrainingResourceError,
)

logger = logging.getLogger(__name__)

DEFAULT_HYPERPARAMS = {
    "batch_size": 64,
    "learning_rate": 2e-5,
    "weight_decay": 1e-2,
    "max_seq_length": 256,
    "max_epochs": 20,
    "early_stopping_patience": 3,
    "class_weight_alpha": 0.5,
}


class EarlyStoppingTracker:
    """Tracks validation Accuracy@5 and signals when to stop training."""

    def __init__(self, patience: int):
        self.patience = patience
        self.best_accuracy = -1.0
        self.best_epoch = 0
        self._epochs_without_improvement = 0
        self._epoch = 0

    def should_stop(self, accuracy_at_5: float) -> bool:
        self._epoch += 1
        if accuracy_at_5 > self.best_accuracy:
            self.best_accuracy = accuracy_at_5
            self.best_epoch = self._epoch
            self._epochs_without_improvement = 0
        else:
            self._epochs_without_improvement += 1

        return self._epochs_without_improvement >= self.patience


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------


def _get_device():
    """Select compute device: CUDA > CPU.

    MPS is excluded — sync overhead exceeds compute savings on
    classification workloads.  Set POULE_DEVICE=cpu to override.
    """
    import os

    import torch

    override = os.environ.get("POULE_DEVICE")
    if override:
        return torch.device(override)

    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Tokenization helper (require torch — imported lazily)
# ---------------------------------------------------------------------------


def _tokenize_batch(tokenizer, texts, max_seq_length):
    """Tokenize a batch of texts using either CoqTokenizer or HuggingFace tokenizer."""
    from Poule.neural.training.vocabulary import CoqTokenizer

    if isinstance(tokenizer, CoqTokenizer):
        result = tokenizer.encode_batch(texts, max_length=max_seq_length)
        import torch

        return {
            "input_ids": torch.tensor(result["input_ids"], dtype=torch.long)
            if not isinstance(result["input_ids"], torch.Tensor)
            else result["input_ids"],
            "attention_mask": torch.tensor(
                result["attention_mask"], dtype=torch.long
            )
            if not isinstance(result["attention_mask"], torch.Tensor)
            else result["attention_mask"],
        }
    else:
        return tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_seq_length,
            return_tensors="pt",
        )


# ---------------------------------------------------------------------------
# Class weight computation
# ---------------------------------------------------------------------------


def compute_class_weights(family_counts: dict[str, int], label_map: dict[str, int],
                          num_classes: int, alpha: float = 0.5):
    """Compute inverse-frequency class weights.

    weight[c] = (total / (num_classes * count[c])) ^ alpha

    Args:
        family_counts: mapping from label name to occurrence count.
        label_map: mapping from label name to class index.
        num_classes: total number of classes.
        alpha: smoothing exponent (0 = uniform, 1 = full inverse frequency).

    Returns:
        A torch float tensor of shape [num_classes].
    """
    import torch

    total = sum(family_counts.values())
    weights = torch.ones(num_classes, dtype=torch.float32)

    for name, idx in label_map.items():
        count = family_counts.get(name, 1)
        weights[idx] = (total / (num_classes * count)) ** alpha

    return weights


# ---------------------------------------------------------------------------
# Validation accuracy@k
# ---------------------------------------------------------------------------


def _compute_accuracy_at_k(model, tokenizer, pairs, max_seq_length, device, k=5):
    """Compute Accuracy@k on (state_text, label_index) pairs.

    A prediction is correct if the true label appears in the top-k
    predicted classes.
    """
    import torch

    if not pairs:
        return 0.0

    model.eval()
    hits = 0
    _CHUNK = 256

    with torch.no_grad():
        for start in range(0, len(pairs), _CHUNK):
            chunk = pairs[start : start + _CHUNK]
            texts = [s for s, _ in chunk]
            labels = [lbl for _, lbl in chunk]

            tokens = _tokenize_batch(tokenizer, texts, max_seq_length)
            logits = model(
                tokens["input_ids"].to(device),
                tokens["attention_mask"].to(device),
            )
            topk = torch.topk(logits, min(k, logits.size(1)), dim=1).indices
            for i, true_label in enumerate(labels):
                if true_label in topk[i].tolist():
                    hits += 1

    return hits / len(pairs)


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class TacticClassifierTrainer:
    """Trains a tactic classifier using weighted cross-entropy loss."""

    def __init__(self, hyperparams: dict[str, Any] | None = None):
        self.hyperparams = dict(DEFAULT_HYPERPARAMS)
        if hyperparams:
            self.hyperparams.update(hyperparams)

    def train(
        self,
        dataset: TacticDataset,
        tokenizer,
        output_path: Path,
        vocabulary_path: Path | None = None,
        hyperparams: dict | None = None,
        sample: float | None = None,
        epoch_callback=None,
    ) -> Path:
        """Train a tactic classifier from scratch.

        Args:
            dataset: TacticDataset with train/val/test splits and label metadata.
            tokenizer: CoqTokenizer or HuggingFace tokenizer instance.
            output_path: path to save the best checkpoint.
            vocabulary_path: path to vocabulary file (saved in checkpoint).
            hyperparams: optional overrides for default hyperparameters.
            sample: optional float in (0.0, 1.0] — sub-samples the training
                split to ceil(len * sample) pairs.
            epoch_callback: optional (epoch, val_accuracy) -> None, invoked
                after each epoch's validation. If it raises, training terminates.

        Returns:
            Path to the saved checkpoint.
        """
        train_pairs = dataset.train_pairs

        if sample is not None and sample < 1.0:
            n = math.ceil(len(train_pairs) * sample)
            train_pairs = random.sample(train_pairs, n)

        if len(train_pairs) < 1000:
            raise InsufficientDataError(
                f"Training requires at least 1,000 pairs, got {len(train_pairs)}"
            )

        hp = dict(self.hyperparams)
        if hyperparams:
            hp.update(hyperparams)

        return self._train_impl(
            train_pairs=train_pairs,
            val_pairs=dataset.val_pairs,
            label_map=dataset.label_map,
            label_names=dataset.label_names,
            family_counts=dataset.family_counts,
            tokenizer=tokenizer,
            output_path=Path(output_path),
            hp=hp,
            vocabulary_path=vocabulary_path,
            epoch_callback=epoch_callback,
        )

    # -----------------------------------------------------------------------
    # Core training loop
    # -----------------------------------------------------------------------

    def _train_impl(
        self,
        train_pairs,
        val_pairs,
        label_map,
        label_names,
        family_counts,
        tokenizer,
        output_path,
        hp,
        vocabulary_path=None,
        epoch_callback=None,
    ) -> Path:
        """Core training loop."""
        import gc

        import torch
        import torch.nn as nn

        from Poule.neural.training.model import TacticClassifier

        output_path = Path(output_path)
        device = _get_device()
        num_classes = len(label_names)

        # Build model
        from Poule.neural.training.vocabulary import CoqTokenizer

        if isinstance(tokenizer, CoqTokenizer):
            model = TacticClassifier(
                num_classes=num_classes,
                vocab_size=tokenizer.vocab_size,
            )
        else:
            model = TacticClassifier(num_classes=num_classes)

        # Free transient allocations from model loading before
        # the optimizer doubles the memory footprint.
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        model = model.to(device)

        # Class-weighted cross-entropy loss
        alpha = hp.get("class_weight_alpha", 0.5)
        class_weights = compute_class_weights(
            family_counts, label_map, num_classes, alpha=alpha,
        ).to(device)
        criterion = nn.CrossEntropyLoss(weight=class_weights)

        # Optimizer
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=hp["learning_rate"],
            weight_decay=hp["weight_decay"],
        )

        # Mixed precision (CUDA only)
        use_amp = device.type == "cuda"
        scaler = None
        autocast_ctx = nullcontext
        if use_amp:
            try:
                from torch.amp import GradScaler, autocast

                scaler = GradScaler("cuda")
                autocast_ctx = lambda: autocast(device_type="cuda", dtype=torch.float16)
            except ImportError:
                from torch.cuda.amp import GradScaler, autocast as _autocast

                scaler = GradScaler()
                autocast_ctx = _autocast

        batch_size = hp["batch_size"]
        tracker = EarlyStoppingTracker(hp["early_stopping_patience"])
        best_accuracy = -1.0
        final_epoch = 0

        for epoch in range(1, hp["max_epochs"] + 1):
            final_epoch = epoch
            model.train()
            epoch_loss = 0.0
            n_batches = 0

            indices = list(range(len(train_pairs)))
            random.shuffle(indices)

            total_batches = (len(indices) + batch_size - 1) // batch_size
            for batch_start in range(0, len(indices), batch_size):
                batch_indices = indices[batch_start : batch_start + batch_size]
                batch_idx = batch_start // batch_size
                if batch_idx % 50 == 0:
                    logger.info("  batch %d/%d", batch_idx, total_batches)

                texts = [train_pairs[i][0] for i in batch_indices]
                labels = torch.tensor(
                    [train_pairs[i][1] for i in batch_indices],
                    dtype=torch.long,
                    device=device,
                )

                tokens = _tokenize_batch(tokenizer, texts, hp["max_seq_length"])

                try:
                    input_ids = tokens["input_ids"].to(device)
                    attention_mask = tokens["attention_mask"].to(device)

                    with autocast_ctx():
                        logits = model(input_ids, attention_mask)
                        loss = criterion(logits, labels)

                    optimizer.zero_grad()
                    if scaler:
                        scaler.scale(loss).backward()
                        scaler.step(optimizer)
                        scaler.update()
                    else:
                        loss.backward()
                        optimizer.step()

                    epoch_loss += loss.detach().item()
                    n_batches += 1

                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        raise TrainingResourceError(
                            f"GPU out of memory with batch_size={batch_size}. "
                            f"Try reducing batch_size."
                        ) from e
                    raise

            # Validation
            avg_loss = epoch_loss / max(n_batches, 1)

            val_accuracy = 0.0
            if val_pairs:
                val_accuracy = _compute_accuracy_at_k(
                    model,
                    tokenizer,
                    val_pairs,
                    hp["max_seq_length"],
                    device,
                    k=5,
                )

            print(f"Epoch {epoch}: loss={avg_loss:.4f}, val_acc@5={val_accuracy:.4f}")

            # Epoch callback (used by HPO tuner for pruning)
            if epoch_callback is not None:
                epoch_callback(epoch, val_accuracy)

            # Save best checkpoint
            if val_accuracy > best_accuracy:
                best_accuracy = val_accuracy
                save_checkpoint(
                    {
                        "model_state_dict": {
                            k: v.cpu() for k, v in model.state_dict().items()
                        },
                        "hyperparams": hp,
                        "label_map": label_map,
                        "vocabulary_path": str(vocabulary_path) if vocabulary_path else None,
                        "class_weights": class_weights.cpu(),
                        "epoch": epoch,
                        "best_accuracy_5": val_accuracy,
                    },
                    output_path,
                )

            if tracker.should_stop(val_accuracy):
                break

        # Save final checkpoint alongside best
        final_path = output_path.parent / (
            output_path.stem + ".final" + output_path.suffix
        )
        save_checkpoint(
            {
                "model_state_dict": {
                    k: v.cpu() for k, v in model.state_dict().items()
                },
                "hyperparams": hp,
                "label_map": label_map,
                "vocabulary_path": str(vocabulary_path) if vocabulary_path else None,
                "class_weights": class_weights.cpu(),
                "epoch": final_epoch,
                "best_accuracy_5": best_accuracy,
            },
            final_path,
        )

        return output_path


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------


def save_checkpoint(data: dict, path: Path) -> None:
    """Save checkpoint dict. Uses torch.save when available, pickle otherwise."""
    path = Path(path)
    try:
        import torch

        torch.save(data, path)
    except ImportError:
        with open(path, "wb") as f:
            pickle.dump(data, f)


def load_checkpoint(path: Path) -> dict:
    """Load checkpoint dict.

    Accepts PyTorch .pt files or MLX safetensors checkpoint directories.
    When *path* points to a ``.safetensors`` file, the sibling ``.pt``
    file is checked first.  If absent, the safetensors checkpoint is
    converted, saved as ``.pt`` for future use, and returned.
    """
    path = Path(path)

    # Prefer .pt sibling when given a .safetensors path
    if path.suffix == ".safetensors":
        pt_path = path.with_suffix(".pt")
        if pt_path.exists():
            path = pt_path
        else:
            ckpt = _load_safetensors_checkpoint(path)
            # Cache as .pt so subsequent loads skip conversion
            try:
                import torch
                torch.save(ckpt, pt_path)
                logger.info(f"Cached converted checkpoint: {pt_path}")
            except Exception:
                pass  # non-fatal — conversion still succeeded
            return ckpt

    if path.is_dir() and (path / "model.safetensors").exists():
        return load_checkpoint(path / "model.safetensors")

    try:
        import torch

        return torch.load(path, map_location="cpu", weights_only=False)
    except ImportError:
        with open(path, "rb") as f:
            return pickle.load(f)


def _load_safetensors(file_path: Path) -> dict:
    """Load safetensors file into a dict of torch tensors.

    Parses the safetensors binary format directly so the ``safetensors``
    package is not required at runtime.
    """
    import struct

    import torch

    _DTYPE_MAP = {
        "F64": torch.float64,
        "F32": torch.float32,
        "F16": torch.float16,
        "BF16": torch.bfloat16,
        "I64": torch.int64,
        "I32": torch.int32,
        "I16": torch.int16,
        "I8": torch.int8,
        "U8": torch.uint8,
        "BOOL": torch.bool,
    }

    with open(file_path, "rb") as f:
        (header_len,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(header_len))
        data_start = 8 + header_len
        buf = f.read()

    tensors = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        dtype = _DTYPE_MAP[meta["dtype"]]
        shape = meta["shape"]
        begin, end = meta["data_offsets"]
        tensors[name] = torch.frombuffer(
            buf, dtype=dtype, count=(end - begin) // torch.tensor([], dtype=dtype).element_size(),
            offset=begin,
        ).reshape(shape).clone()

    return tensors


def _load_safetensors_checkpoint(path: Path) -> dict:
    """Convert an MLX safetensors checkpoint to a PyTorch checkpoint dict."""
    from Poule.neural.training.mlx_backend.converter import _build_mappings

    path = Path(path)
    if path.is_dir():
        ckpt_dir = path
        safetensors_path = path / "model.safetensors"
    else:
        ckpt_dir = path.parent
        safetensors_path = path

    mlx_weights = _load_safetensors(safetensors_path)

    # Read sibling metadata
    config_path = ckpt_dir / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}

    hyperparams_path = ckpt_dir / "hyperparams.json"
    hyperparams = (
        json.loads(hyperparams_path.read_text()) if hyperparams_path.exists() else {}
    )

    vocab_path = ckpt_dir / "vocabulary_path.txt"
    vocabulary_path = vocab_path.read_text().strip() if vocab_path.exists() else None

    # Map MLX parameter names to PyTorch names
    num_layers = config.get("num_layers", 12)
    _, mlx_to_hf = _build_mappings(num_layers)

    pt_state_dict = {}
    for mlx_name, tensor in mlx_weights.items():
        if mlx_name in mlx_to_hf:
            hf_name = mlx_to_hf[mlx_name]
            if hf_name.startswith("roberta."):
                pt_name = "encoder." + hf_name[len("roberta."):]
            else:
                pt_name = hf_name
        else:
            pt_name = mlx_name
        pt_state_dict[pt_name] = tensor

    return {
        "model_state_dict": pt_state_dict,
        "optimizer_state_dict": {},
        "epoch": 0,
        "hyperparams": hyperparams,
        "vocabulary_path": vocabulary_path,
    }
