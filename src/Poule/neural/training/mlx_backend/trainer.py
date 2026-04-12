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
            dataset: TacticDataset with hierarchical labels.
            output_dir: Directory to save MLX checkpoint.
            vocabulary_path: Path to closed vocabulary JSON.
            hyperparams: Override default hyperparameters.
            epoch_callback: Called after each epoch with (epoch, val_metric).
        """
        self._check_platform()

        self._train_classifier(
            dataset, output_dir, vocabulary_path, hyperparams, epoch_callback,
        )

    def _train_classifier(
        self,
        dataset: TacticDataset,
        output_dir: Path,
        vocabulary_path: Path,
        hyperparams: dict[str, Any] | None = None,
        epoch_callback: Callable[[int, float], None] | None = None,
    ) -> None:
        """Train a tactic classifier model using MLX."""

        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim

        from Poule.neural.training.mlx_backend.loss import (
            compute_ldam_margins_mlx,
            cross_entropy_loss,
            hierarchical_loss_mlx,
            precompute_category_indices,
        )
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
        lambda_within = hp.get("lambda_within", 1.0)
        ldam_C = hp.get("ldam_C", 0.3)

        train_pairs = dataset.train_pairs
        if len(train_pairs) < 1000:
            raise InsufficientDataError(
                f"Need at least 1,000 training pairs, got {len(train_pairs)}"
            )

        num_classes = dataset.num_classes
        is_hierarchical = (
            hasattr(dataset, "category_names")
            and len(dataset.category_names) > 0
        )

        # Load tokenizer
        tokenizer = CoqTokenizer(str(vocabulary_path))

        num_hidden_layers = hp.get("num_hidden_layers", 6)
        embedding_dim = hp.get("embedding_dim", 128)

        if is_hierarchical:
            per_category_sizes = dataset.per_category_sizes
            num_categories = dataset.num_categories
            model = MLXTacticClassifier(
                vocab_size=tokenizer.vocab_size,
                num_layers=num_hidden_layers,
                embedding_dim=embedding_dim,
                per_category_sizes=per_category_sizes,
                num_categories=num_categories,
            )
        else:
            model = MLXTacticClassifier(
                vocab_size=tokenizer.vocab_size,
                num_classes=num_classes,
                num_layers=num_hidden_layers,
                embedding_dim=embedding_dim,
            )
        mx.eval(model.parameters())

        # Initialize with pre-trained CodeBERT weights for transfer learning
        print("Loading CodeBERT weights...", flush=True)
        model.load_codebert_weights()
        mx.eval(model.parameters())

        # Compute class weights (inverse-frequency)
        if is_hierarchical:
            # Category-level weights
            cat_counts = {}
            for cat in dataset.category_names:
                cat_counts[cat] = sum(dataset.per_category_counts.get(cat, {}).values())
            cat_label_map = {cat: i for i, cat in enumerate(dataset.category_names)}
            category_weights = self._compute_class_weights(
                cat_counts, cat_label_map, num_categories, alpha=class_weight_alpha,
            )
            # Per-category within-class weights
            per_cat_weights = {}
            for cat in dataset.category_names:
                cat_family_counts = dataset.per_category_counts.get(cat, {})
                cat_lm = dataset.per_category_label_maps[cat]
                n_cat = len(dataset.per_category_label_names[cat])
                per_cat_weights[cat] = self._compute_class_weights(
                    cat_family_counts, cat_lm, n_cat, alpha=class_weight_alpha,
                )
            class_weights = None  # not used for hierarchical

            # Compute LDAM margins from raw category/within-category counts
            if ldam_C > 0:
                cat_counts_arr = mx.array([
                    float(sum(dataset.per_category_counts.get(cat, {}).values()))
                    for cat in dataset.category_names
                ])
                category_margins = compute_ldam_margins_mlx(cat_counts_arr, ldam_C)
                per_cat_margins = {}
                for cat in dataset.category_names:
                    cat_family_counts = dataset.per_category_counts.get(cat, {})
                    cat_lm = dataset.per_category_label_maps[cat]
                    n_cat = len(dataset.per_category_label_names[cat])
                    counts = mx.array([
                        float(cat_family_counts.get(name, 1))
                        for name in dataset.per_category_label_names[cat]
                    ])
                    per_cat_margins[cat] = compute_ldam_margins_mlx(counts, ldam_C)
            else:
                category_margins = None
                per_cat_margins = None
        else:
            class_weights = self._compute_class_weights(
                dataset.family_counts, dataset.label_map, num_classes,
                alpha=class_weight_alpha,
            )

        # Optimizer: SAM-AdamW or plain AdamW
        sam_rho = hp.get("sam_rho", 0.15)
        optimizer = optim.AdamW(learning_rate=lr, weight_decay=weight_decay)
        use_sam = sam_rho > 0.0
        if use_sam:
            from Poule.neural.training.mlx_backend.sam import sam_step

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

        # Pre-tokenize all training data to avoid per-batch tokenization cost.
        # Pad all sequences to max_seq_length for uniform array shapes.
        # Store actual lengths for length-bucketed batching.
        print("Pre-tokenizing training data...", flush=True)
        all_ids_np = np.zeros((len(train_pairs), max_seq_length), dtype=np.int32)
        all_mask_np = np.zeros((len(train_pairs), max_seq_length), dtype=np.int32)
        all_label_np = np.zeros(len(train_pairs), dtype=np.int32)
        all_cat_label_np = np.zeros(len(train_pairs), dtype=np.int32)
        all_within_label_np = np.zeros(len(train_pairs), dtype=np.int32)
        all_lengths = np.zeros(len(train_pairs), dtype=np.int32)
        for i, item in enumerate(train_pairs):
            if is_hierarchical:
                text, cat_idx, within_idx = item
                all_cat_label_np[i] = cat_idx
                all_within_label_np[i] = within_idx
            else:
                text = item[0]
                all_label_np[i] = item[1]
            ids, mask = tokenizer.encode(text, max_length=max_seq_length)
            all_ids_np[i] = ids
            all_mask_np[i] = mask
            all_lengths[i] = sum(mask)
        # Sort by length for efficient length-bucketed batching
        sort_idx = np.argsort(all_lengths)
        all_ids_np = all_ids_np[sort_idx]
        all_mask_np = all_mask_np[sort_idx]
        all_label_np = all_label_np[sort_idx]
        all_cat_label_np = all_cat_label_np[sort_idx]
        all_within_label_np = all_within_label_np[sort_idx]
        print(
            f"Pre-tokenized {len(train_pairs)} samples "
            f"(lengths: median={int(np.median(all_lengths))}, "
            f"mean={int(np.mean(all_lengths))}, max={int(all_lengths.max())})",
            flush=True,
        )
        # Convert to MLX and free all numpy arrays
        all_ids = mx.array(all_ids_np)
        all_masks = mx.array(all_mask_np)
        all_labels = mx.array(all_label_np)
        all_cat_labels = mx.array(all_cat_label_np)
        all_within_labels = mx.array(all_within_label_np)
        del all_ids_np, all_mask_np, all_label_np, all_cat_label_np
        del all_within_label_np, all_lengths, sort_idx
        import gc; gc.collect()

        n_train = len(train_pairs)

        # Pre-compute per-category sample indices for the full training set.
        # These map global positions -> per-category indices, avoiding
        # numpy round-trips inside the loss function on every micro-batch.
        if is_hierarchical:
            global_cat_indices = precompute_category_indices(
                all_cat_labels, len(dataset.category_names),
            )
            # Convert global indices to numpy for fast batch slicing
            global_cat_indices_np = [np.array(idx) for idx in global_cat_indices]

        # Pre-compute batch start indices for length-bucketed batching.
        # Data is sorted by length; we shuffle batch ORDER each epoch
        # so the model sees batches in random order while keeping
        # similar-length samples together (avoids wasted attention on padding).
        batch_starts = list(range(0, n_train, micro_batch_size))
        total_micros = len(batch_starts)

        # Deferred re-balancing (DRW): after drw_start_epoch, weight batch
        # selection proportionally to the inverse-class-frequency of samples
        # in each batch, biasing training toward minority classes.
        drw_start_fraction = hp.get("drw_start_fraction", 0.8)
        drw_start_epoch = max(1, int(max_epochs * drw_start_fraction))
        batch_drw_weights = None
        if is_hierarchical and ldam_C > 0:
            # Compute per-sample inverse-class-frequency weight
            sample_weights = np.ones(n_train, dtype=np.float32)
            cat_labels_np = np.array(all_cat_labels)
            within_labels_np = np.array(all_within_labels)
            for i in range(n_train):
                cat_idx = int(cat_labels_np[i])
                cat_name = dataset.category_names[cat_idx]
                within_idx = int(within_labels_np[i])
                family = dataset.per_category_label_names[cat_name][within_idx]
                count = dataset.per_category_counts.get(cat_name, {}).get(family, 1)
                sample_weights[i] = 1.0 / max(count, 1)
            # Aggregate per-batch weights (mean of sample weights in each batch)
            batch_drw_weights = np.zeros(len(batch_starts), dtype=np.float64)
            for bi, bs in enumerate(batch_starts):
                end = min(bs + micro_batch_size, n_train)
                batch_drw_weights[bi] = sample_weights[bs:end].mean()
            batch_drw_weights /= batch_drw_weights.sum()

        for epoch in range(1, max_epochs + 1):
            if batch_drw_weights is not None and epoch >= drw_start_epoch:
                # DRW phase 2: class-balanced batch sampling with replacement
                selected = np.random.choice(
                    len(batch_starts), size=len(batch_starts),
                    replace=True, p=batch_drw_weights,
                )
                epoch_batch_starts = [batch_starts[i] for i in selected]
            else:
                epoch_batch_starts = list(batch_starts)
                np.random.shuffle(epoch_batch_starts)

            epoch_loss = 0.0
            num_batches = 0

            for bi, batch_start in enumerate(epoch_batch_starts):
                if bi % 100 == 0:
                    print(f"  micro-batch {bi}/{total_micros}", flush=True)

                end = min(batch_start + micro_batch_size, n_train)
                s_ids_full = all_ids[batch_start:end]
                s_mask_full = all_masks[batch_start:end]

                # Trim to actual max sequence length in this batch to
                # reduce attention cost (O(n²)) for short-sequence batches.
                actual_max = int(s_mask_full.sum(axis=1).max())
                s_ids = s_ids_full[:, :actual_max]
                s_mask = s_mask_full[:, :actual_max]

                if is_hierarchical:
                    cat_labels = all_cat_labels[batch_start:end]
                    within_labels = all_within_labels[batch_start:end]

                    # Slice pre-computed category indices to this batch.
                    # Global indices are positions in the full training set;
                    # we select those within [batch_start, end) and remap
                    # to batch-local positions (0..batch_size-1).
                    batch_cat_idx = []
                    for cat_global in global_cat_indices_np:
                        in_batch = cat_global[(cat_global >= batch_start) & (cat_global < end)]
                        batch_cat_idx.append(mx.array(in_batch - batch_start))

                    def loss_fn(model):
                        cat_logits, within_logits = model(s_ids, s_mask)
                        return hierarchical_loss_mlx(
                            cat_logits, within_logits,
                            cat_labels, within_labels,
                            category_weights, per_cat_weights,
                            dataset.category_names, lambda_within,
                            batch_cat_indices=batch_cat_idx,
                            category_margins=category_margins,
                            per_category_margins=per_cat_margins,
                        )
                else:
                    labels = all_labels[batch_start:end]

                    def loss_fn(model):
                        logits = model(s_ids, s_mask)
                        return cross_entropy_loss(
                            logits, labels, class_weights,
                        )

                if use_sam:
                    loss = sam_step(model, loss_fn, optimizer, sam_rho)
                else:
                    loss, grads = nn.value_and_grad(model, loss_fn)(model)
                    optimizer.update(model, grads)
                    mx.eval(model.parameters(), optimizer.state, loss)

                epoch_loss += float(loss)
                num_batches += 1

            avg_loss = epoch_loss / max(num_batches, 1)

            # Validation: accuracy@5
            if is_hierarchical:
                val_accuracy = self._compute_hierarchical_accuracy_at_k(
                    model, dataset.val_pairs, tokenizer, max_seq_length,
                    dataset.category_names, dataset.per_category_label_names, k=5,
                )
            else:
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
                    dataset=dataset if is_hierarchical else None,
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

    def _compute_hierarchical_accuracy_at_k(
        self,
        model,
        pairs: list[tuple[str, int, int]],
        tokenizer,
        max_seq_length: int,
        category_names: list[str],
        per_category_label_names: dict[str, list[str]],
        k: int = 5,
    ) -> float:
        """Compute Accuracy@k using product rule for hierarchical model."""
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
            texts = [s for s, _, _ in chunk]
            true_cats = [c for _, c, _ in chunk]
            true_withins = [w for _, _, w in chunk]

            s_ids, s_mask = _tokenize(texts)
            cat_logits, within_logits = model(s_ids, s_mask)
            mx.eval(cat_logits)

            cat_probs_np = np.array(mx.softmax(cat_logits, axis=-1))

            all_scores = []
            for cat_idx, cat in enumerate(category_names):
                within_np = np.array(mx.softmax(within_logits[cat], axis=-1))
                product = cat_probs_np[:, cat_idx:cat_idx+1] * within_np
                all_scores.append(product)
            all_scores_np = np.concatenate(all_scores, axis=-1)

            effective_k = min(k, all_scores_np.shape[1])
            top_k_indices = np.argsort(all_scores_np, axis=1)[:, -effective_k:]

            for i in range(len(chunk)):
                offset = sum(
                    len(per_category_label_names.get(category_names[c], []))
                    for c in range(true_cats[i])
                )
                true_flat = offset + true_withins[i]
                if true_flat in top_k_indices[i]:
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
        dataset=None,
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
            "embedding_dim": model.embedding.weight.shape[1],
        }
        if model._is_hierarchical:
            config["per_category_sizes"] = dict(model.per_category_sizes)
            config["num_categories"] = model.num_categories
        if dataset is not None:
            config["category_names"] = dataset.category_names
            config["per_category_label_names"] = dict(dataset.per_category_label_names)
            config["per_category_label_maps"] = dict(dataset.per_category_label_maps)

        (output_dir / "config.json").write_text(json.dumps(config, indent=2))
        (output_dir / "hyperparams.json").write_text(
            json.dumps(hyperparams, indent=2)
        )
        (output_dir / "vocabulary_path.txt").write_text(str(vocabulary_path))
        (output_dir / "best_accuracy_5.txt").write_text(str(best_accuracy))
        (output_dir / "label_map.json").write_text(
            json.dumps(label_map, indent=2)
        )

