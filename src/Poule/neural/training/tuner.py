"""Optuna-based hyperparameter optimization for bi-encoder training.

spec §4.8: Automated search over training hyperparameters to maximize
validation Recall@32 using TPE sampling and MedianPruner.
"""

from __future__ import annotations

import gc
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Poule.neural.training.errors import (
    InsufficientDataError,
    TuningError,
    TrainingResourceError,
)
from Poule.neural.training.trainer import BiEncoderTrainer, load_checkpoint

logger = logging.getLogger(__name__)

# spec §4.8: tunable hyperparameters with sampling ranges
TUNABLE_HYPERPARAMS: dict[str, dict[str, Any]] = {
    "learning_rate": {"low": 1e-6, "high": 1e-4, "log": True},
    "temperature": {"low": 0.01, "high": 0.2, "log": True},
    "batch_size": {"choices": [64, 128, 256]},
    "weight_decay": {"low": 1e-4, "high": 1e-1, "log": True},
    "hard_negatives_per_state": {"low": 1, "high": 5},
}


@dataclass
class TuningResult:
    """Result of a hyperparameter optimization study.

    spec §4.8: contains best hyperparams, best R@32, trial counts,
    study path, and per-trial summaries.
    """

    best_hyperparams: dict[str, Any]
    best_value: float
    n_trials: int
    n_pruned: int
    study_path: str
    all_trials: list[dict[str, Any]] = field(default_factory=list)


class HyperparameterTuner:
    """Optuna-based hyperparameter optimization for BiEncoderTrainer.

    spec §4.8: runs sequential trials with TPE sampling and median pruning,
    persisting results in SQLite for crash recovery.
    """

    @staticmethod
    def tune(
        dataset,
        output_dir: Path,
        vocabulary_path: Path | None = None,
        n_trials: int = 20,
        study_name: str = "poule-hpo",
        resume: bool = False,
    ) -> TuningResult:
        """Run hyperparameter optimization.

        Args:
            dataset: TrainingDataset (same as BiEncoderTrainer.train).
            output_dir: Directory for study DB, trial checkpoints, and best model.
            vocabulary_path: Optional closed vocabulary JSON path.
            n_trials: Number of trials to run (default: 20).
            study_name: Optuna study name (default: "poule-hpo").
            resume: If True, resume an existing study from the SQLite DB.

        Returns:
            TuningResult with best hyperparameters and study statistics.

        Raises:
            InsufficientDataError: If dataset has < 1,000 training pairs.
            TuningError: If zero trials complete successfully.
        """
        import optuna

        if len(dataset.train) < 1000:
            raise InsufficientDataError(
                f"Tuning requires at least 1,000 training pairs, got {len(dataset.train)}"
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        study_path = output_dir / "hpo-study.db"
        storage = f"sqlite:///{study_path}"

        # spec §4.8: TPESampler(seed=42), MedianPruner(n_startup_trials=3, n_warmup_steps=3)
        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            load_if_exists=resume,
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(
                n_startup_trials=3,
                n_warmup_steps=3,
            ),
        )

        def objective(trial):
            # Sample hyperparameters from search space
            hp = {
                "learning_rate": trial.suggest_float(
                    "learning_rate",
                    TUNABLE_HYPERPARAMS["learning_rate"]["low"],
                    TUNABLE_HYPERPARAMS["learning_rate"]["high"],
                    log=TUNABLE_HYPERPARAMS["learning_rate"]["log"],
                ),
                "temperature": trial.suggest_float(
                    "temperature",
                    TUNABLE_HYPERPARAMS["temperature"]["low"],
                    TUNABLE_HYPERPARAMS["temperature"]["high"],
                    log=TUNABLE_HYPERPARAMS["temperature"]["log"],
                ),
                "batch_size": trial.suggest_categorical(
                    "batch_size",
                    TUNABLE_HYPERPARAMS["batch_size"]["choices"],
                ),
                "weight_decay": trial.suggest_float(
                    "weight_decay",
                    TUNABLE_HYPERPARAMS["weight_decay"]["low"],
                    TUNABLE_HYPERPARAMS["weight_decay"]["high"],
                    log=TUNABLE_HYPERPARAMS["weight_decay"]["log"],
                ),
                "hard_negatives_per_state": trial.suggest_int(
                    "hard_negatives_per_state",
                    TUNABLE_HYPERPARAMS["hard_negatives_per_state"]["low"],
                    TUNABLE_HYPERPARAMS["hard_negatives_per_state"]["high"],
                ),
            }

            def epoch_callback(epoch, val_recall):
                trial.report(val_recall, epoch)
                if trial.should_prune():
                    raise optuna.TrialPruned()

            trial_output = output_dir / f"trial-{trial.number}.pt"
            trainer = BiEncoderTrainer(hyperparams=hp)

            try:
                trainer.train(
                    dataset,
                    trial_output,
                    vocabulary_path=vocabulary_path,
                    epoch_callback=epoch_callback,
                )
            except optuna.TrialPruned:
                raise  # Let Optuna handle pruned trials
            except TrainingResourceError as e:
                logger.warning("Trial %d OOM: %s", trial.number, e)
                raise optuna.TrialPruned()  # Treat OOM as pruned

            # Load checkpoint to get best R@32
            checkpoint = load_checkpoint(trial_output)
            return checkpoint["best_recall_32"]

        def _cleanup_memory():
            gc.collect()
            try:
                import torch
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
            except ImportError:
                pass

        # Run optimization with per-trial cleanup
        for i in range(n_trials):
            study.optimize(objective, n_trials=1, catch=(Exception,))
            _cleanup_memory()

        # Check if any trials completed
        completed = [t for t in study.trials if t.state.name == "COMPLETE"]
        if not completed:
            raise TuningError(
                f"Hyperparameter optimization failed: "
                f"0 of {len(study.trials)} trials completed successfully"
            )

        # Copy best trial's checkpoint to best-model.pt
        best_trial = study.best_trial
        best_checkpoint_src = output_dir / f"trial-{best_trial.number}.pt"
        best_checkpoint_dst = output_dir / "best-model.pt"
        if best_checkpoint_src.exists():
            shutil.copy2(best_checkpoint_src, best_checkpoint_dst)

        # Build result
        pruned_count = sum(
            1 for t in study.trials if t.state.name == "PRUNED"
        )
        all_trials = [
            {
                "number": t.number,
                "value": t.value,
                "state": t.state.name,
                "hyperparams": t.params,
            }
            for t in study.trials
        ]

        return TuningResult(
            best_hyperparams=best_trial.params,
            best_value=best_trial.value,
            n_trials=len(study.trials),
            n_pruned=pruned_count,
            study_path=str(study_path),
            all_trials=all_trials,
        )
