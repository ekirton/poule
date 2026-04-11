#!/usr/bin/env python3
"""Retry LOOCV after fixing the MLXTrainer interface bug.

Picks up the best hyperparameters from the already-completed training
pipeline and runs only the LOOCV + results-writing stages.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("loocv-retry")

DATA_DIR = Path(os.environ.get("POULE_DATA_DIR", Path.home() / "poule-home" / "data"))
TRAINING_DATA = DATA_DIR / "training.jsonl"
VOCABULARY = DATA_DIR / "coq-vocabulary.json"
FINAL_MODEL_DIR = DATA_DIR / "final-model"
RESULTS_FILE = DATA_DIR / "final-model-validation.txt"
LOOCV_DIR = DATA_DIR / "loocv-results"
LIBRARY_JSONL_STEMS = ["stdlib", "stdpp", "flocq", "coquelicot", "coqinterval"]


def main():
    import torch
    from Poule.neural.training.data import TrainingDataLoader, undersample_train
    from Poule.neural.training.evaluator import TacticEvaluator
    from Poule.neural.training.model import HierarchicalTacticClassifier
    from Poule.neural.training.trainer import load_checkpoint
    from Poule.neural.training.vocabulary import CoqTokenizer

    # Load dataset (needed for results writing)
    dataset = TrainingDataLoader.load([TRAINING_DATA])
    dataset = undersample_train(dataset, cap=2000)

    # Load best hyperparameters from saved file
    hp_path = FINAL_MODEL_DIR / "hyperparams.json"
    best_hp = json.loads(hp_path.read_text())
    logger.info("Best hyperparameters loaded from %s", hp_path)

    # Load tokenizer
    tokenizer = CoqTokenizer(VOCABULARY)

    # Evaluate the final model (to get report for results file)
    pt_path = FINAL_MODEL_DIR / "model.pt"
    logger.info("Evaluating final model at %s...", pt_path)
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
    logger.info(
        "  cat_acc@1=%.3f, acc@1=%.3f, acc@5=%.3f, latency=%.1fms",
        report.category_accuracy_at_1,
        report.accuracy_at_1,
        report.accuracy_at_5,
        report.eval_latency_ms,
    )

    # Run LOOCV
    library_paths: dict[str, list[Path]] = {}
    for stem in LIBRARY_JSONL_STEMS:
        lib_jsonl = DATA_DIR / f"{stem}.jsonl"
        if lib_jsonl.exists():
            library_paths[stem] = [lib_jsonl]
        else:
            logger.warning("LOOCV: %s not found, skipping", lib_jsonl)

    loocv_report = None
    if len(library_paths) >= 2:
        from Poule.neural.training.loocv import LibraryLOOCV

        logger.info(
            "Running LOOCV across %d libraries: %s",
            len(library_paths),
            ", ".join(sorted(library_paths)),
        )
        t0 = time.time()
        loocv_report = LibraryLOOCV.run(
            library_paths=library_paths,
            vocabulary_path=VOCABULARY,
            output_dir=LOOCV_DIR,
            undersample_cap=1000,
            hyperparams=best_hp,
            backend="mlx",
        )
        loocv_time = time.time() - t0
        logger.info(
            "LOOCV complete in %.0f min: mean_acc@5=%.3f ± %.3f",
            loocv_time / 60,
            loocv_report.mean_test_acc_at_5,
            loocv_report.std_test_acc_at_5,
        )

    # Write full results file
    lines = []
    lines.append("=" * 60)
    lines.append("FINAL MODEL VALIDATION RESULTS (HIERARCHICAL)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Training data: {TRAINING_DATA}")
    lines.append(f"Vocabulary: {VOCABULARY} ({tokenizer.vocab_size} tokens)")
    lines.append(f"Model checkpoint: {pt_path}")
    lines.append("")
    lines.append("--- Dataset ---")
    lines.append(f"Train samples:      {len(dataset.train_pairs)}")
    lines.append(f"Validation samples: {len(dataset.val_pairs)}")
    lines.append(f"Test samples:       {len(dataset.test_pairs)}")
    lines.append(f"Categories:         {dataset.num_categories}")
    lines.append(f"Total tactics:      {dataset.num_classes}")
    lines.append("")
    lines.append("--- Best Hyperparameters ---")
    for k, v in sorted(best_hp.items()):
        if isinstance(v, float):
            lines.append(f"  {k:30s} {v:.6g}")
        else:
            lines.append(f"  {k:30s} {v}")
    lines.append("")
    lines.append("--- Final Model ---")
    lines.append(f"Hidden layers: {best_hp.get('num_hidden_layers', 6)}")
    lines.append(f"Category Accuracy@1: {report.category_accuracy_at_1:.4f} ({report.category_accuracy_at_1*100:.1f}%)")
    lines.append(f"Accuracy@1: {report.accuracy_at_1:.4f} ({report.accuracy_at_1*100:.1f}%)")
    lines.append(f"Accuracy@5: {report.accuracy_at_5:.4f} ({report.accuracy_at_5*100:.1f}%)")
    lines.append(f"Eval latency: {report.eval_latency_ms:.1f} ms")
    lines.append("")

    # Per-category accuracy
    lines.append("--- Per-Category Accuracy ---")
    lines.append(f"{'Category':<25s} {'Accuracy':>10s}")
    lines.append("-" * 37)
    for cat, acc in sorted(report.per_category_accuracy.items()):
        lines.append(f"{cat:<25s} {acc:>10.4f}")
    lines.append("")

    # Per-family metrics
    lines.append("--- Per-Family Precision/Recall ---")
    lines.append(f"{'Family':<30s} {'Precision':>10s} {'Recall':>10s}")
    lines.append("-" * 52)
    for family in sorted(report.per_family_precision.keys()):
        prec = report.per_family_precision.get(family, 0.0)
        rec = report.per_family_recall.get(family, 0.0)
        lines.append(f"{family:<30s} {prec:>10.4f} {rec:>10.4f}")
    lines.append("")

    dead_count = sum(1 for rec in report.per_family_recall.values() if rec == 0.0)
    total_families = len(report.per_family_recall)
    lines.append(f"Zero-recall families: {dead_count} of {total_families}")

    _MIN_TRAINABLE = 20
    _COMFORTABLE = 50
    ge20 = [f for f in report.per_family_recall if dataset.family_counts.get(f, 0) >= _MIN_TRAINABLE]
    ge50 = [f for f in report.per_family_recall if dataset.family_counts.get(f, 0) >= _COMFORTABLE]
    nonzero_ge20 = sum(1 for f in ge20 if report.per_family_recall[f] > 0.0)
    nonzero_ge50 = sum(1 for f in ge50 if report.per_family_recall[f] > 0.0)
    cov_ge20 = nonzero_ge20 / len(ge20) if ge20 else 0.0
    cov_ge50 = nonzero_ge50 / len(ge50) if ge50 else 0.0
    lines.append(f"Trainable coverage (>=20 examples): {nonzero_ge20}/{len(ge20)} = {cov_ge20:.1%}")
    lines.append(f"Trainable coverage (>=50 examples): {nonzero_ge50}/{len(ge50)} = {cov_ge50:.1%}")
    lines.append("")

    if loocv_report is not None:
        lines.append("--- LOOCV Results ---")
        lines.append(f"Libraries: {len(loocv_report.folds)}")
        lines.append(f"Undersample cap: {loocv_report.undersample_cap}")
        lines.append(f"Mean test_acc@5: {loocv_report.mean_test_acc_at_5:.4f} ± {loocv_report.std_test_acc_at_5:.4f}")
        lines.append(f"Mean dead families: {loocv_report.mean_dead_families:.1f}")
        lines.append("")
        lines.append(f"{'Library':<20s} {'Acc@5':>10s} {'Dead':>6s} {'Train':>8s} {'Test':>8s}")
        lines.append("-" * 56)
        for fold in loocv_report.folds:
            lines.append(
                f"{fold.held_out_library:<20s} "
                f"{fold.accuracy_at_5:>10.4f} "
                f"{fold.dead_families:>6d} "
                f"{fold.train_samples:>8d} "
                f"{fold.test_samples:>8d}"
            )
        lines.append("")

    # Success criteria
    lines.append("--- Success Criteria ---")
    checks = [
        ("test_acc@5 > 46.6%", report.accuracy_at_5 > 0.466),
        (f">80% coverage (>=20 examples): {nonzero_ge20}/{len(ge20)}", cov_ge20 > 0.80),
        (f">90% coverage (>=50 examples): {nonzero_ge50}/{len(ge50)}", cov_ge50 > 0.90),
        ("category_acc@1 > 80%", report.category_accuracy_at_1 > 0.80),
    ]
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        lines.append(f"  [{status}] {name}")
    lines.append("")
    lines.append("=" * 60)

    text = "\n".join(lines) + "\n"
    RESULTS_FILE.write_text(text)
    logger.info("Results written to %s", RESULTS_FILE)
    print(text)


if __name__ == "__main__":
    main()
