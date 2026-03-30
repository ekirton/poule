"""MLX training loop for bi-encoder model.

spec §4.11: Functional gradient computation using mlx.nn.value_and_grad.

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

from Poule.neural.training.data import TrainingDataset
from Poule.neural.training.errors import (
    BackendNotAvailableError,
    InsufficientDataError,
)
from Poule.neural.training.negatives import sample_hard_negatives
from Poule.neural.training.trainer import DEFAULT_HYPERPARAMS, EarlyStoppingTracker

logger = logging.getLogger(__name__)


class MLXTrainer:
    """Trains a bi-encoder model using MLX on Apple Silicon.

    spec §4.11: Creates an MLXBiEncoder, trains with functional gradients,
    saves checkpoints in MLX safetensors format.
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
        dataset: TrainingDataset,
        output_dir: Path,
        vocabulary_path: Path,
        hyperparams: dict[str, Any] | None = None,
        epoch_callback: Callable[[int, float], None] | None = None,
    ) -> None:
        """Train a bi-encoder model using MLX.

        Args:
            dataset: Training data with train/val/test splits.
            output_dir: Directory to save MLX checkpoint.
            vocabulary_path: Path to closed vocabulary JSON.
            hyperparams: Override default hyperparameters.
            epoch_callback: Called after each epoch with (epoch, val_recall).
        """
        self._check_platform()

        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim

        from Poule.neural.training.mlx_backend.loss import masked_contrastive_loss_mlx
        from Poule.neural.training.mlx_backend.model import MLXBiEncoder
        from Poule.neural.training.vocabulary import CoqTokenizer

        # Merge hyperparams
        hp = dict(DEFAULT_HYPERPARAMS)
        if hyperparams:
            hp.update(hyperparams)

        batch_size = hp["batch_size"]
        lr = hp["learning_rate"]
        weight_decay = hp["weight_decay"]
        temperature = hp["temperature"]
        hard_neg_k = hp["hard_negatives_per_state"]
        max_seq_length = hp["max_seq_length"]
        max_epochs = hp["max_epochs"]
        patience = hp["early_stopping_patience"]

        if len(dataset.train) < 1000:
            raise InsufficientDataError(
                f"Need at least 1,000 training pairs, got {len(dataset.train)}"
            )

        # Load tokenizer
        tokenizer = CoqTokenizer(str(vocabulary_path))

        # Create model
        model = MLXBiEncoder(vocab_size=tokenizer.vocab_size)
        mx.eval(model.parameters())

        # Optimizer
        optimizer = optim.AdamW(learning_rate=lr, weight_decay=weight_decay)

        # Build premise corpus name set for hard negatives
        corpus_names = set()
        if hasattr(dataset.premise_corpus, 'keys'):
            corpus_names = set(dataset.premise_corpus.keys())
        elif hasattr(dataset.premise_corpus, '_names'):
            corpus_names = set(dataset.premise_corpus._names)

        # Prepare output
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        early_stopping = EarlyStoppingTracker(patience)
        micro_batch_size = min(32, batch_size)
        accumulation_steps = max(1, batch_size // micro_batch_size)

        best_recall = -1.0
        best_epoch = 0
        training_log = []

        def _tokenize(texts: list[str]) -> tuple[mx.array, mx.array]:
            result = tokenizer.encode_batch(texts, max_length=max_seq_length)
            ids = mx.array(np.array(result["input_ids"], dtype=np.int32))
            mask = mx.array(np.array(result["attention_mask"], dtype=np.int32))
            return ids, mask

        for epoch in range(1, max_epochs + 1):
            # Shuffle training data
            indices = list(range(len(dataset.train)))
            random.shuffle(indices)

            epoch_loss = 0.0
            num_batches = 0

            for batch_start in range(0, len(indices), micro_batch_size):
                batch_indices = indices[batch_start:batch_start + micro_batch_size]
                batch_pairs = [dataset.train[i] for i in batch_indices]

                # Collect states and premises
                states = [p[0] for p in batch_pairs]
                all_premises = []
                positive_indices_list = []

                for state_text, premise_names in batch_pairs:
                    pos_indices = []
                    for name in premise_names:
                        text = ""
                        if hasattr(dataset.premise_corpus, '__getitem__'):
                            try:
                                text = dataset.premise_corpus[name]
                            except (KeyError, IndexError):
                                text = name
                        else:
                            text = name
                        if text not in all_premises:
                            all_premises.append(text)
                        pos_indices.append(all_premises.index(text))
                    positive_indices_list.append(pos_indices)

                    # Hard negatives
                    pos_set = set(premise_names)
                    source_file = ""
                    accessible = set()
                    if dataset.file_deps and source_file in dataset.file_deps:
                        for dep_file in dataset.file_deps[source_file]:
                            if dep_file in dataset.file_premises:
                                accessible |= dataset.file_premises[dep_file]

                    neg_names = sample_hard_negatives(
                        state_text, pos_set, accessible, k=hard_neg_k,
                        corpus=corpus_names if corpus_names else None,
                    )
                    for neg_name in neg_names:
                        neg_text = neg_name
                        if hasattr(dataset.premise_corpus, '__getitem__'):
                            try:
                                neg_text = dataset.premise_corpus[neg_name]
                            except (KeyError, IndexError):
                                neg_text = neg_name
                        if neg_text not in all_premises:
                            all_premises.append(neg_text)

                if not all_premises:
                    continue

                # Tokenize
                s_ids, s_mask = _tokenize(states)
                p_ids, p_mask = _tokenize(all_premises)

                # Forward + backward using value_and_grad
                def loss_fn(model):
                    s_embs = model(s_ids, s_mask)
                    p_embs = model(p_ids, p_mask)
                    return masked_contrastive_loss_mlx(
                        s_embs, p_embs, positive_indices_list, temperature
                    )

                loss, grads = nn.value_and_grad(model, loss_fn)(model)
                optimizer.update(model, grads)
                mx.eval(model.parameters(), optimizer.state, loss)

                epoch_loss += float(loss)
                num_batches += 1

            avg_loss = epoch_loss / max(num_batches, 1)

            # Validation
            val_recall = self._compute_recall(
                model, dataset, tokenizer, max_seq_length
            )

            logger.info(
                f"Epoch {epoch}: loss={avg_loss:.4f}, val_R@32={val_recall:.4f}"
            )
            print(f"Epoch {epoch}: loss={avg_loss:.4f}, val_R@32={val_recall:.4f}")

            training_log.append({
                "epoch": epoch,
                "loss": avg_loss,
                "val_recall_32": val_recall,
            })

            if epoch_callback is not None:
                epoch_callback(epoch, val_recall)

            # Save best checkpoint
            if val_recall > best_recall:
                best_recall = val_recall
                best_epoch = epoch
                self._save_checkpoint(
                    model, output_dir, hp, vocabulary_path, best_recall
                )

            if early_stopping.should_stop(val_recall):
                print(f"Early stopping at epoch {epoch} (best: epoch {best_epoch})")
                break

        # Save training log
        log_path = output_dir / "training_log.jsonl"
        with open(log_path, "w") as f:
            for entry in training_log:
                f.write(json.dumps(entry) + "\n")

    def _compute_recall(
        self,
        model,
        dataset: TrainingDataset,
        tokenizer,
        max_seq_length: int,
        k: int = 32,
    ) -> float:
        """Compute Recall@k on the validation set."""
        import mlx.core as mx

        if not dataset.val:
            return 0.0

        def _tokenize(texts):
            result = tokenizer.encode_batch(texts, max_length=max_seq_length)
            ids = mx.array(np.array(result["input_ids"], dtype=np.int32))
            mask = mx.array(np.array(result["attention_mask"], dtype=np.int32))
            return ids, mask

        # Build premise corpus subset (cap at 10K)
        all_positive_names = set()
        for _, premises in dataset.val:
            all_positive_names.update(premises)

        corpus_texts = []
        corpus_names = []
        if hasattr(dataset.premise_corpus, 'iter_batched'):
            for name, text in dataset.premise_corpus.iter_batched():
                corpus_names.append(name)
                corpus_texts.append(text)
                if len(corpus_texts) >= 10000 and name not in all_positive_names:
                    continue
        elif hasattr(dataset.premise_corpus, 'items'):
            for name, text in dataset.premise_corpus.items():
                corpus_names.append(name)
                corpus_texts.append(text)
        else:
            return 0.0

        if not corpus_texts:
            return 0.0

        # Encode premises
        p_ids, p_mask = _tokenize(corpus_texts)
        p_embs = model(p_ids, p_mask)
        mx.eval(p_embs)

        hits = 0
        total = 0

        for state_text, premise_names in dataset.val:
            s_ids, s_mask = _tokenize([state_text])
            s_emb = model(s_ids, s_mask)
            mx.eval(s_emb)

            # Cosine similarity
            sim = mx.matmul(s_emb, p_embs.T)[0]
            mx.eval(sim)

            top_k_indices = np.array(sim).argsort()[-k:][::-1]
            top_k_names = {corpus_names[i] for i in top_k_indices}

            if top_k_names & set(premise_names):
                hits += 1
            total += 1

        return hits / max(total, 1)

    def _save_checkpoint(
        self,
        model,
        output_dir: Path,
        hyperparams: dict,
        vocabulary_path: Path,
        best_recall: float,
    ) -> None:
        """Save MLX checkpoint in the spec-defined directory format."""
        import mlx.core as mx

        # Flatten model parameters for safetensors
        params = {}
        for k, v in model.parameters().items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, dict):
                        for k3, v3 in v2.items():
                            params[f"{k}.{k2}.{k3}"] = v3
                    else:
                        params[f"{k}.{k2}"] = v2
            else:
                params[k] = v

        mx.save_safetensors(str(output_dir / "model.safetensors"), params)

        config = {
            "vocab_size": model.embedding.weight.shape[0],
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
        (output_dir / "best_recall_32.txt").write_text(str(best_recall))
