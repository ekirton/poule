"""Leave-one-library-out cross-validation for tactic prediction.

Orchestrates per-library folds: for each library, hold it out as the
test set, train on the remaining libraries, and evaluate.

spec §4.1: LibraryLOOCV, FoldResult, LOOCVReport.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class FoldResult:
    """Result of a single LOOCV fold."""

    held_out_library: str
    train_samples: int
    val_samples: int
    test_samples: int
    accuracy_at_1: float
    accuracy_at_5: float
    category_accuracy_at_1: float
    dead_families: int
    total_families: int
    per_family_recall: dict[str, float]
    training_time_s: float


@dataclass
class LOOCVReport:
    """Aggregate report across all LOOCV folds."""

    folds: list[FoldResult]
    undersample_cap: int
    mean_test_acc_at_5: float
    std_test_acc_at_5: float
    mean_dead_families: float
    per_library_acc_at_5: dict[str, float]

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        return {
            "folds": [asdict(f) for f in self.folds],
            "undersample_cap": self.undersample_cap,
            "mean_test_acc_at_5": self.mean_test_acc_at_5,
            "std_test_acc_at_5": self.std_test_acc_at_5,
            "mean_dead_families": self.mean_dead_families,
            "per_library_acc_at_5": self.per_library_acc_at_5,
        }


class LibraryLOOCV:
    """Leave-one-library-out cross-validation runner."""

    @staticmethod
    def run(
        library_paths: dict[str, list[Path]],
        vocabulary_path: Path,
        output_dir: Path,
        undersample_cap: int = 1000,
        hyperparams: dict | None = None,
        backend: str = "mlx",
        always_train_libraries: list[str] | None = None,
    ) -> LOOCVReport:
        """Run LOOCV across all libraries.

        For each library, holds it out as the test set, trains on the
        remaining libraries, evaluates, and collects a FoldResult.

        Libraries in ``always_train_libraries`` are included in training
        for every fold but are never held out as a fold themselves.
        """
        from Poule.neural.training.data import (
            TrainingDataLoader,
            undersample_train,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        always_train = set(always_train_libraries or [])

        folds: list[FoldResult] = []

        for held_out in library_paths:
            if held_out in always_train:
                continue
            print(f"\n{'='*60}")
            print(f"LOOCV fold: holding out {held_out}")
            print(f"{'='*60}")

            # Load data with library-level split
            dataset = TrainingDataLoader.load_by_library(
                library_paths, held_out_library=held_out,
                always_train_libraries=list(always_train),
            )

            # Undersample training split
            dataset = undersample_train(
                dataset, cap=undersample_cap, seed=42
            )

            print(
                f"  train={len(dataset.train_pairs)}, "
                f"val={len(dataset.val_pairs)}, "
                f"test={len(dataset.test_pairs)}"
            )

            # Train
            fold_dir = output_dir / f"fold-{held_out}"
            fold_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = fold_dir / "checkpoint.pt"

            hp = dict(hyperparams) if hyperparams else {}
            # Don't re-undersample inside trainer
            hp.pop("undersample_cap", None)

            start_time = time.time()
            fold_result = _train_and_evaluate_fold(
                dataset=dataset,
                vocabulary_path=vocabulary_path,
                checkpoint_path=checkpoint_path,
                hyperparams=hp,
                backend=backend,
                held_out_library=held_out,
            )
            fold_result.training_time_s = time.time() - start_time

            folds.append(fold_result)

            # Clean up checkpoint
            if checkpoint_path.exists():
                checkpoint_path.unlink()
            # Clean up MLX checkpoints if any
            for f in fold_dir.glob("*.safetensors"):
                f.unlink()
            for f in fold_dir.glob("*.json"):
                f.unlink()

        # Aggregate
        acc_values = [f.accuracy_at_5 for f in folds]
        dead_values = [f.dead_families for f in folds]

        report = LOOCVReport(
            folds=folds,
            undersample_cap=undersample_cap,
            mean_test_acc_at_5=statistics.mean(acc_values),
            std_test_acc_at_5=(
                statistics.stdev(acc_values) if len(acc_values) > 1 else 0.0
            ),
            mean_dead_families=statistics.mean(dead_values),
            per_library_acc_at_5={
                f.held_out_library: f.accuracy_at_5 for f in folds
            },
        )

        # Write report
        report_path = output_dir / "loocv-report.json"
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nLOOCV report written to {report_path}")
        print(f"Mean test_acc@5: {report.mean_test_acc_at_5:.3f} "
              f"± {report.std_test_acc_at_5:.3f}")

        return report


def _train_and_evaluate_fold(
    dataset,
    vocabulary_path: Path,
    checkpoint_path: Path,
    hyperparams: dict,
    backend: str,
    held_out_library: str,
) -> FoldResult:
    """Train a model and evaluate on the held-out library for one fold."""
    from Poule.neural.training.vocabulary import CoqTokenizer

    tokenizer = CoqTokenizer(vocabulary_path)

    if backend == "mlx":
        from Poule.neural.training.mlx_backend.trainer import MLXTrainer

        trainer = MLXTrainer()
        trainer.train(
            dataset,
            output_dir=checkpoint_path.parent,
            vocabulary_path=vocabulary_path,
            hyperparams=hyperparams or None,
        )
    else:
        from Poule.neural.training.trainer import TacticClassifierTrainer

        trainer = TacticClassifierTrainer(hyperparams=hyperparams or None)
        trainer.train(
            dataset,
            tokenizer,
            output_path=checkpoint_path,
            vocabulary_path=vocabulary_path,
        )

    # Evaluate on the test split (held-out library)
    import torch
    from Poule.neural.training.evaluator import TacticEvaluator
    from Poule.neural.training.model import HierarchicalTacticClassifier
    from Poule.neural.training.trainer import load_checkpoint

    # The MLX backend converts to PyTorch checkpoint as "model.pt" in the output dir;
    # checkpoint_path may be "checkpoint.pt" which doesn't exist after MLX training.
    pt_path = checkpoint_path.parent / "model.pt" if not checkpoint_path.exists() else checkpoint_path
    ckpt = load_checkpoint(pt_path)
    label_map = ckpt.get("label_map", {})
    label_names = sorted(label_map.keys(), key=lambda k: label_map[k])
    device = torch.device("cpu")
    model = HierarchicalTacticClassifier.from_checkpoint(ckpt)
    model = model.to(device)
    model.eval()
    evaluator = TacticEvaluator(
        model, tokenizer, label_names, device,
        category_names=dataset.category_names,
        per_category_label_names=dict(dataset.per_category_label_names),
    )
    report = evaluator.evaluate(dataset.test_pairs)

    # Compute per-family recall and dead families
    per_family_recall: dict[str, float] = {}
    dead_families = 0
    total_families = len(dataset.label_names)

    if hasattr(report, "per_family_recall"):
        per_family_recall = report.per_family_recall
        dead_families = sum(1 for r in per_family_recall.values() if r == 0.0)
    elif hasattr(report, "per_family_metrics"):
        for name, metrics in report.per_family_metrics.items():
            recall = metrics.get("recall", 0.0)
            per_family_recall[name] = recall
            if recall == 0.0:
                dead_families += 1

    return FoldResult(
        held_out_library=held_out_library,
        train_samples=len(dataset.train_pairs),
        val_samples=len(dataset.val_pairs),
        test_samples=len(dataset.test_pairs),
        accuracy_at_1=getattr(report, "accuracy_at_1", 0.0),
        accuracy_at_5=getattr(report, "accuracy_at_5", 0.0),
        category_accuracy_at_1=getattr(report, "category_accuracy_at_1", 0.0),
        dead_families=dead_families,
        total_families=total_families,
        per_family_recall=per_family_recall,
        training_time_s=0.0,  # Filled by caller
    )
