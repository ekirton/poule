"""Bi-encoder trainer with masked contrastive loss and early stopping."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from poule.neural.training.errors import InsufficientDataError

DEFAULT_HYPERPARAMS = {
    "batch_size": 256,
    "learning_rate": 2e-5,
    "weight_decay": 1e-2,
    "temperature": 0.05,
    "hard_negatives_per_state": 3,
    "max_seq_length": 512,
    "max_epochs": 20,
    "early_stopping_patience": 3,
    "embedding_dim": 768,
}

FINE_TUNE_OVERRIDES = {
    "learning_rate": 5e-6,
    "max_epochs": 10,
}


class EarlyStoppingTracker:
    """Tracks validation Recall@32 and signals when to stop training."""

    def __init__(self, patience: int):
        self.patience = patience
        self.best_recall = -1.0
        self.best_epoch = 0
        self._epochs_without_improvement = 0
        self._epoch = 0

    def should_stop(self, recall_at_32: float) -> bool:
        self._epoch += 1
        if recall_at_32 > self.best_recall:
            self.best_recall = recall_at_32
            self.best_epoch = self._epoch
            self._epochs_without_improvement = 0
        else:
            self._epochs_without_improvement += 1

        return self._epochs_without_improvement >= self.patience


class BiEncoderTrainer:
    """Trains a bi-encoder model using masked contrastive loss."""

    def __init__(self, hyperparams: dict[str, Any] | None = None):
        self.hyperparams = dict(DEFAULT_HYPERPARAMS)
        if hyperparams:
            self.hyperparams.update(hyperparams)

    def train(self, dataset, output_path: Path, hyperparams: dict | None = None):
        if len(dataset.train) < 1000:
            raise InsufficientDataError(
                f"Training requires at least 1,000 pairs, got {len(dataset.train)}"
            )
        # Full training loop would use torch here — omitted for TDD phase


def save_checkpoint(data: dict, path: Path) -> None:
    path = Path(path)
    with open(path, "wb") as f:
        pickle.dump(data, f)


def load_checkpoint(path: Path) -> dict:
    path = Path(path)
    with open(path, "rb") as f:
        return pickle.load(f)


def get_fine_tune_hyperparams(overrides: dict | None = None) -> dict:
    params = dict(DEFAULT_HYPERPARAMS)
    params.update(FINE_TUNE_OVERRIDES)
    if overrides:
        params.update(overrides)
    return params
