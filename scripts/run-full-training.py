#!/usr/bin/env python3
"""Full training pipeline: HPO -> final model -> evaluation -> ONNX export.

Runs Optuna trials with MLX on Apple Silicon, trains the final model
with the best hyperparameters, evaluates on the test set, exports to
ONNX, and writes results to $POULE_DATA_DIR/final-model-validation.txt.
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
logger = logging.getLogger("full-training")

DATA_DIR = Path(os.environ.get("POULE_DATA_DIR", Path.home() / "poule-home" / "data"))
TRAINING_DATA = DATA_DIR / "training.jsonl"
VOCABULARY = DATA_DIR / "coq-vocabulary.json"
HPO_DIR = DATA_DIR / "hpo-results"
FINAL_MODEL_DIR = DATA_DIR / "final-model"
RESULTS_FILE = DATA_DIR / "final-model-validation.txt"
LOOCV_DIR = DATA_DIR / "loocv-results"

# Libraries included in training.
# MathComp provides SSReflect training signal; always included in training,
# excluded from LOOCV hold-out folds. CoqInterval excluded entirely (no transfer).
LIBRARY_JSONL_STEMS = ["stdlib", "stdpp", "flocq", "coquelicot", "mathcomp"]

# Libraries always included in training during LOOCV (never held out).
ALWAYS_TRAIN_LIBRARIES = ["mathcomp"]


def main():
    from Poule.neural.training.data import TrainingDataLoader, oversample_train, undersample_train

    # ---- Step 1: Load data ----
    logger.info("Loading training data...")
    dataset = TrainingDataLoader.load([TRAINING_DATA])
    logger.info(
        "  train=%d, val=%d, test=%d, categories=%d, total_tactics=%d",
        len(dataset.train_pairs),
        len(dataset.val_pairs),
        len(dataset.test_pairs),
        dataset.num_categories,
        dataset.num_classes,
    )

    # Print category distribution
    for cat in dataset.category_names:
        total = sum(dataset.per_category_counts.get(cat, {}).values())
        n_tactics = len(dataset.per_category_label_names.get(cat, []))
        logger.info("  %s: %d samples, %d tactic families", cat, total, n_tactics)

    # ---- Step 1b: Undersample dominant families ----
    UNDERSAMPLE_CAP = 2000
    UNDERSAMPLE_MIN = max(1, int(UNDERSAMPLE_CAP * 0.05))  # 5% of cap
    OVERSAMPLE_FLOOR = max(1, int(UNDERSAMPLE_CAP * 0.25))  # 25% of cap
    original_train = len(dataset.train_pairs)
    dataset = undersample_train(dataset, cap=UNDERSAMPLE_CAP, min_count=UNDERSAMPLE_MIN)
    logger.info(
        "Undersampled training set: %d -> %d (cap=%d, min=%d per family)",
        original_train,
        len(dataset.train_pairs),
        UNDERSAMPLE_CAP,
        UNDERSAMPLE_MIN,
    )

    # ---- Step 1c: Oversample minority families ----
    pre_oversample = len(dataset.train_pairs)
    dataset = oversample_train(dataset, floor=OVERSAMPLE_FLOOR)
    logger.info(
        "Oversampled training set: %d -> %d (floor=%d per family)",
        pre_oversample,
        len(dataset.train_pairs),
        OVERSAMPLE_FLOOR,
    )

    # ---- Step 2: HPO ----
    from Poule.neural.training.tuner import HyperparameterTuner

    logger.info("Starting hyperparameter optimization (15 trials)...")
    t0 = time.time()
    result = HyperparameterTuner.tune(
        dataset,
        HPO_DIR,
        vocabulary_path=VOCABULARY,
        n_trials=15,
        study_name="poule-hpo-undersampled",
        resume=False,
        hpo_max_epochs=10,
        hpo_patience=2,
    )
    hpo_time = time.time() - t0
    logger.info(
        "HPO complete: %d trials (%d pruned), best acc@5=%.4f in %.0f min",
        result.n_trials,
        result.n_pruned,
        result.best_value,
        hpo_time / 60,
    )
    logger.info("Best hyperparameters: %s", result.best_hyperparams)

    # ---- Step 3: Fold validation data into training and train final model ----
    from Poule.neural.training.data import fold_val_into_train
    from Poule.neural.training.mlx_backend.trainer import MLXTrainer

    # Fold validation data back into training — HPO has selected hyperparams,
    # so the validation split has served its purpose.
    final_dataset = fold_val_into_train(dataset)
    final_dataset = undersample_train(final_dataset, cap=UNDERSAMPLE_CAP, min_count=UNDERSAMPLE_MIN)
    final_dataset = oversample_train(final_dataset, floor=OVERSAMPLE_FLOOR)
    logger.info(
        "Folded val into train: %d train samples (no validation set)",
        len(final_dataset.train_pairs),
    )

    best_hp = dict(result.best_hyperparams)
    # Train for a fixed epoch count based on HPO convergence — no early stopping
    # since there is no validation set to monitor.
    final_epochs = result.best_epoch if result.best_epoch > 0 else 10
    best_hp["max_epochs"] = final_epochs
    best_hp["early_stopping_patience"] = final_epochs  # effectively disabled

    logger.info(
        "Training final model: %d epochs (from HPO best epoch), best hyperparameters...",
        final_epochs,
    )
    t0 = time.time()
    trainer = MLXTrainer()
    trainer.train(
        final_dataset,
        FINAL_MODEL_DIR,
        vocabulary_path=VOCABULARY,
        hyperparams=best_hp,
    )
    train_time = time.time() - t0
    logger.info("Final model training complete in %.0f min", train_time / 60)

    # ---- Step 4: Evaluate ----
    logger.info("Evaluating final model...")
    pt_path = FINAL_MODEL_DIR / "model.pt"
    if not pt_path.exists():
        logger.error("model.pt not found -- MLX->PyTorch conversion may have failed")
        sys.exit(1)

    from Poule.neural.training.evaluator import TacticEvaluator
    from Poule.neural.training.model import HierarchicalTacticClassifier
    from Poule.neural.training.trainer import load_checkpoint
    from Poule.neural.training.vocabulary import CoqTokenizer
    import torch

    ckpt = load_checkpoint(pt_path)
    label_map = ckpt.get("label_map", {})
    label_names = sorted(label_map.keys(), key=lambda k: label_map[k])

    tokenizer = CoqTokenizer(VOCABULARY)
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

    # ---- Step 5: Export to ONNX ----
    from Poule.neural.training.quantizer import ModelQuantizer

    onnx_path = FINAL_MODEL_DIR / "tactic-predictor.onnx"
    logger.info("Exporting to ONNX: %s -> %s", pt_path, onnx_path)
    ModelQuantizer.quantize(pt_path, onnx_path)
    logger.info("ONNX export complete: %s", onnx_path)

    # Also copy vocabulary alongside model artifacts
    import shutil
    vocab_dest = FINAL_MODEL_DIR / "coq-vocabulary.json"
    if not vocab_dest.exists() and VOCABULARY.exists():
        shutil.copy2(VOCABULARY, vocab_dest)
        logger.info("Copied vocabulary to %s", vocab_dest)

    # ---- Step 5b: LOOCV (optional, set RUN_LOOCV=1) ----
    loocv_report = None
    if os.environ.get("RUN_LOOCV", "0") == "1":
        library_paths: dict[str, list[Path]] = {}
        for stem in LIBRARY_JSONL_STEMS:
            lib_jsonl = DATA_DIR / f"{stem}.jsonl"
            if lib_jsonl.exists():
                library_paths[stem] = [lib_jsonl]
            else:
                logger.warning("LOOCV: %s not found, skipping", lib_jsonl)

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
                always_train_libraries=ALWAYS_TRAIN_LIBRARIES,
            )
            loocv_time = time.time() - t0
            logger.info(
                "LOOCV complete in %.0f min: mean_acc@5=%.3f ± %.3f",
                loocv_time / 60,
                loocv_report.mean_test_acc_at_5,
                loocv_report.std_test_acc_at_5,
            )
        else:
            logger.warning(
                "LOOCV: need >=2 per-library JSONL files in %s, found %d",
                DATA_DIR,
                len(library_paths),
            )

    # ---- Step 6: Write results ----
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
    lines.append(f"HPO train samples:  {len(dataset.train_pairs)}")
    lines.append(f"HPO val samples:    {len(dataset.val_pairs)}")
    lines.append(f"Final train samples:{len(final_dataset.train_pairs)} (val folded in)")
    lines.append(f"Test samples:       {len(dataset.test_pairs)}")
    lines.append(f"Categories:         {dataset.num_categories}")
    lines.append(f"Total tactics:      {dataset.num_classes}")
    lines.append("")
    lines.append("--- HPO Results ---")
    lines.append(f"Trials: {result.n_trials} ({result.n_pruned} pruned)")
    lines.append(f"HPO time: {hpo_time / 60:.1f} min")
    lines.append(f"Best HPO val acc@5: {result.best_value:.4f}")
    lines.append("")
    lines.append("Best hyperparameters:")
    for k, v in sorted(best_hp.items()):
        if isinstance(v, float):
            lines.append(f"  {k:30s} {v:.6g}")
        else:
            lines.append(f"  {k:30s} {v}")
    lines.append("")
    lines.append("--- Final Model ---")
    lines.append(f"Hidden layers: {best_hp.get('num_hidden_layers', 6)}")
    lines.append(f"Fixed epochs: {final_epochs} (from HPO best epoch)")
    lines.append(f"Training time: {train_time / 60:.1f} min")
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

    # Count dead classes (zero test recall) and trainable coverage
    dead_count = sum(
        1 for rec in report.per_family_recall.values() if rec == 0.0
    )
    total_families = len(report.per_family_recall)
    lines.append(f"Zero-recall families: {dead_count} of {total_families}")

    # Trainable coverage: families above min_count threshold (5% of cap)
    # and a higher "confident" tier at 2x min_count
    _MIN_TRAINABLE = UNDERSAMPLE_MIN          # 5% of cap (default 100)
    _COMFORTABLE = UNDERSAMPLE_MIN * 2        # 10% of cap (default 200)
    ge_min = [f for f in report.per_family_recall if final_dataset.family_counts.get(f, 0) >= _MIN_TRAINABLE]
    ge_comf = [f for f in report.per_family_recall if final_dataset.family_counts.get(f, 0) >= _COMFORTABLE]
    nonzero_ge_min = sum(1 for f in ge_min if report.per_family_recall[f] > 0.0)
    nonzero_ge_comf = sum(1 for f in ge_comf if report.per_family_recall[f] > 0.0)
    cov_ge_min = nonzero_ge_min / len(ge_min) if ge_min else 0.0
    cov_ge_comf = nonzero_ge_comf / len(ge_comf) if ge_comf else 0.0
    lines.append(f"Trainable coverage (>={_MIN_TRAINABLE} examples): {nonzero_ge_min}/{len(ge_min)} = {cov_ge_min:.1%}")
    lines.append(f"Trainable coverage (>={_COMFORTABLE} examples): {nonzero_ge_comf}/{len(ge_comf)} = {cov_ge_comf:.1%}")
    lines.append("")

    # LOOCV results (if run)
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

    # Success criteria check
    lines.append("--- Success Criteria ---")
    checks = [
        ("test_acc@5 > 57.0%", report.accuracy_at_5 > 0.570),
        (f">50% coverage (>={_MIN_TRAINABLE} examples): {nonzero_ge_min}/{len(ge_min)}", cov_ge_min > 0.50),
        (f">60% coverage (>={_COMFORTABLE} examples): {nonzero_ge_comf}/{len(ge_comf)}", cov_ge_comf > 0.60),
        ("category_acc@1 > 35%", report.category_accuracy_at_1 > 0.35),
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
