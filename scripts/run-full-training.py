#!/usr/bin/env python3
"""Full training pipeline: HPO -> final model -> evaluation.

Runs Optuna trials with MLX on Apple Silicon, trains the final model
with the best hyperparameters, evaluates on the test set, and writes
results to /data/final-model-validation.txt.
"""

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("full-training")

DATA_DIR = Path("/Users/ekirton/poule-home/data")
TRAINING_DATA = DATA_DIR / "training.jsonl"
VOCABULARY = DATA_DIR / "coq-vocabulary.json"
HPO_DIR = DATA_DIR / "hpo-results"
FINAL_MODEL_DIR = DATA_DIR / "final-model"
RESULTS_FILE = DATA_DIR / "final-model-validation.txt"


def main():
    from Poule.neural.training.data import TrainingDataLoader

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

    # ---- Step 2: HPO ----
    from Poule.neural.training.tuner import HyperparameterTuner

    logger.info("Starting hyperparameter optimization (15 trials)...")
    t0 = time.time()
    result = HyperparameterTuner.tune(
        dataset,
        HPO_DIR,
        vocabulary_path=VOCABULARY,
        n_trials=15,
        study_name="poule-hpo-hierarchical",
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

    # ---- Step 3: Train final model with best hyperparams ----
    from Poule.neural.training.mlx_backend.trainer import MLXTrainer

    best_hp = dict(result.best_hyperparams)
    best_hp["max_epochs"] = 20
    best_hp["early_stopping_patience"] = 3

    logger.info("Training final model with best hyperparameters...")
    t0 = time.time()
    trainer = MLXTrainer()
    trainer.train(
        dataset,
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

    # ---- Step 5: Write results ----
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

    # Count dead classes (zero test recall)
    dead_count = sum(
        1 for rec in report.per_family_recall.values() if rec == 0.0
    )
    total_families = len(report.per_family_recall)
    lines.append(f"Dead classes (0.0 recall): {dead_count} of {total_families}")
    lines.append("")

    # Success criteria check
    lines.append("--- Success Criteria ---")
    checks = [
        ("test_acc@5 > 46.6%", report.accuracy_at_5 > 0.466),
        ("dead families < 20", dead_count < 20),
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
