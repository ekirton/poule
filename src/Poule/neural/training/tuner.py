"""Optuna-based hyperparameter optimization for tactic classifier training.

spec §4.8: Automated search over training hyperparameters to maximize
validation accuracy@5 using TPE sampling and MedianPruner.
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
from Poule.neural.training.trainer import TacticClassifierTrainer, load_checkpoint

# ---------------------------------------------------------------------------
# MLX backend detection
# ---------------------------------------------------------------------------


def _mlx_available() -> bool:
    """Return True when running on macOS with Apple Silicon and MLX installed."""
    import sys

    if sys.platform != "darwin":
        return False
    try:
        import mlx.core  # noqa: F401

        return True
    except (ImportError, ModuleNotFoundError):
        return False

logger = logging.getLogger(__name__)

# spec §4.8: tunable hyperparameters with sampling ranges
# Updated for hierarchical classification (8-dim search space)
TUNABLE_HYPERPARAMS: dict[str, dict[str, Any]] = {
    "num_hidden_layers": {"choices": [4, 6, 8]},
    "learning_rate": {"low": 1e-6, "high": 1e-4, "log": True},
    "batch_size": {"choices": [16, 32, 64]},
    "weight_decay": {"low": 1e-4, "high": 1e-1, "log": True},
    "class_weight_alpha": {"low": 0.0, "high": 1.0},
    "label_smoothing": {"low": 0.0, "high": 0.2},
    "sam_rho": {"low": 0.15, "high": 0.3, "log": True},
    "lambda_within": {"low": 0.3, "high": 3.0, "log": True},
}


@dataclass
class TuningResult:
    """Result of a hyperparameter optimization study.

    spec §4.8: contains best hyperparams, best accuracy@5, trial counts,
    study path, and per-trial summaries.
    """

    best_hyperparams: dict[str, Any]
    best_value: float
    n_trials: int
    n_pruned: int
    study_path: str
    best_epoch: int = 0
    all_trials: list[dict[str, Any]] = field(default_factory=list)


class HyperparameterTuner:
    """Optuna-based hyperparameter optimization for TacticClassifierTrainer.

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
        hpo_max_epochs: int | None = None,
        hpo_patience: int | None = None,
    ) -> TuningResult:
        """Run hyperparameter optimization.

        Args:
            dataset: TacticDataset (same as TacticClassifierTrainer.train).
            output_dir: Directory for study DB, trial checkpoints, and best model.
            vocabulary_path: Optional closed vocabulary JSON path.
            n_trials: Number of trials to run (default: 20).
            study_name: Optuna study name (default: "poule-hpo").
            resume: If True, resume an existing study from the SQLite DB.
            hpo_max_epochs: Override max_epochs for HPO trials (default: use sampled value).
            hpo_patience: Override early_stopping_patience for HPO trials.

        Returns:
            TuningResult with best hyperparameters and study statistics.

        Raises:
            InsufficientDataError: If dataset has < 1,000 training steps.
            TuningError: If zero trials complete successfully.
        """
        import optuna

        if len(dataset.train_pairs) < 1000:
            raise InsufficientDataError(
                f"Tuning requires at least 1,000 training steps, got {len(dataset.train_pairs)}"
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
            sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=3),
            pruner=optuna.pruners.MedianPruner(
                n_startup_trials=3,
                n_warmup_steps=3,
            ),
        )

        use_mlx = _mlx_available()
        if use_mlx:
            logger.info("Using MLX backend for HPO (Apple Silicon GPU)")

        def objective(trial):
            # Sample hyperparameters from search space
            hp = {
                "num_hidden_layers": trial.suggest_categorical(
                    "num_hidden_layers",
                    TUNABLE_HYPERPARAMS["num_hidden_layers"]["choices"],
                ),
                "learning_rate": trial.suggest_float(
                    "learning_rate",
                    TUNABLE_HYPERPARAMS["learning_rate"]["low"],
                    TUNABLE_HYPERPARAMS["learning_rate"]["high"],
                    log=TUNABLE_HYPERPARAMS["learning_rate"]["log"],
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
                "class_weight_alpha": trial.suggest_float(
                    "class_weight_alpha",
                    TUNABLE_HYPERPARAMS["class_weight_alpha"]["low"],
                    TUNABLE_HYPERPARAMS["class_weight_alpha"]["high"],
                ),
                "label_smoothing": trial.suggest_float(
                    "label_smoothing",
                    TUNABLE_HYPERPARAMS["label_smoothing"]["low"],
                    TUNABLE_HYPERPARAMS["label_smoothing"]["high"],
                ),
                "sam_rho": trial.suggest_float(
                    "sam_rho",
                    TUNABLE_HYPERPARAMS["sam_rho"]["low"],
                    TUNABLE_HYPERPARAMS["sam_rho"]["high"],
                    log=TUNABLE_HYPERPARAMS["sam_rho"].get("log", False),
                ),
                "lambda_within": trial.suggest_float(
                    "lambda_within",
                    TUNABLE_HYPERPARAMS["lambda_within"]["low"],
                    TUNABLE_HYPERPARAMS["lambda_within"]["high"],
                    log=TUNABLE_HYPERPARAMS["lambda_within"].get("log", False),
                ),
            }

            # Apply HPO-specific epoch/patience overrides
            if hpo_max_epochs is not None:
                hp["max_epochs"] = hpo_max_epochs
            if hpo_patience is not None:
                hp["early_stopping_patience"] = hpo_patience

            def epoch_callback(epoch, val_accuracy):
                trial.report(val_accuracy, epoch)
                if trial.should_prune():
                    raise optuna.TrialPruned()

            try:
                if use_mlx:
                    from Poule.neural.training.mlx_backend.trainer import MLXTrainer

                    trial_dir = output_dir / f"trial-{trial.number}"
                    trainer = MLXTrainer()
                    trainer.train(
                        dataset,
                        trial_dir,
                        vocabulary_path=vocabulary_path,
                        hyperparams=hp,
                        epoch_callback=epoch_callback,
                    )
                    # Read best accuracy from text file
                    acc_path = trial_dir / "best_accuracy_5.txt"
                    if acc_path.exists():
                        return float(acc_path.read_text().strip())
                    # Fall back to converted .pt checkpoint
                    pt_path = trial_dir / "model.pt"
                    if pt_path.exists():
                        checkpoint = load_checkpoint(pt_path)
                        return checkpoint.get("best_accuracy_5", 0.0)
                    return 0.0
                else:
                    trial_output = output_dir / f"trial-{trial.number}.pt"
                    trainer = TacticClassifierTrainer(hyperparams=hp)
                    # Build tokenizer
                    if vocabulary_path:
                        from Poule.neural.training.vocabulary import CoqTokenizer
                        tokenizer = CoqTokenizer(vocabulary_path)
                    else:
                        from transformers import AutoTokenizer
                        tokenizer = AutoTokenizer.from_pretrained(
                            "microsoft/codebert-base"
                        )
                    trainer.train(
                        dataset,
                        tokenizer,
                        output_path=trial_output,
                        vocabulary_path=vocabulary_path,
                        epoch_callback=epoch_callback,
                    )
                    checkpoint = load_checkpoint(trial_output)
                    return checkpoint.get("best_accuracy_5", 0.0)
            except optuna.TrialPruned:
                raise  # Let Optuna handle pruned trials
            except TrainingResourceError as e:
                logger.warning("Trial %d OOM: %s", trial.number, e)
                raise optuna.TrialPruned()  # Treat OOM as pruned

        def _cleanup_memory():
            gc.collect()
            try:
                import mlx.core as mx
                mx.metal.reset_peak_memory()
            except Exception:
                pass
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

        # Run optimization until n_trials completed-or-pruned trials exist in the
        # study (across all sessions, including resumed ones).  Failures do not
        # count toward the budget — they wasted compute but produced no useful
        # data for TPE.  A safety cap of 3× prevents infinite loops when every
        # attempt consistently fails.
        max_attempts = n_trials * 3
        attempts = 0
        while attempts < max_attempts:
            valid = sum(
                1
                for t in study.trials
                if t.state.name in ("COMPLETE", "PRUNED")
            )
            if valid >= n_trials:
                break
            study.optimize(objective, n_trials=1, catch=(Exception,))
            _cleanup_memory()
            attempts += 1

        # Check if any trials completed
        completed = [t for t in study.trials if t.state.name == "COMPLETE"]
        if not completed:
            raise TuningError(
                f"Hyperparameter optimization failed: "
                f"0 of {len(study.trials)} trials completed successfully"
            )

        # Copy best trial's checkpoint to best-model.pt
        best_trial = study.best_trial
        best_checkpoint_dst = output_dir / "best-model.pt"
        if use_mlx:
            # MLX trials save to directories; use the converted model.pt
            best_trial_dir = output_dir / f"trial-{best_trial.number}"
            best_pt = best_trial_dir / "model.pt"
            if best_pt.exists():
                shutil.copy2(best_pt, best_checkpoint_dst)
            elif best_trial_dir.exists():
                # Trigger conversion
                checkpoint = load_checkpoint(best_trial_dir)
                import torch
                torch.save(checkpoint, best_checkpoint_dst)
        else:
            best_checkpoint_src = output_dir / f"trial-{best_trial.number}.pt"
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

        # Determine best epoch from intermediate values
        best_epoch = 0
        intermediates = best_trial.intermediate_values
        if intermediates:
            best_epoch = max(intermediates, key=intermediates.get)

        return TuningResult(
            best_hyperparams=best_trial.params,
            best_value=best_trial.value,
            n_trials=len(study.trials),
            n_pruned=pruned_count,
            study_path=str(study_path),
            best_epoch=best_epoch,
            all_trials=all_trials,
        )
