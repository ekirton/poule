#!/usr/bin/env python3
"""Full training pipeline: HPO → final model → evaluation.

Runs 10 Optuna trials with MLX on Apple Silicon, trains the final model
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
        "  train=%d, val=%d, test=%d, classes=%d",
        len(dataset.train_pairs),
        len(dataset.val_pairs),
        len(dataset.test_pairs),
        dataset.num_classes,
    )

    # ---- Step 2: HPO ----
    from Poule.neural.training.tuner import HyperparameterTuner

    logger.info("Starting hyperparameter optimization (10 trials)...")
    t0 = time.time()
    result = HyperparameterTuner.tune(
        dataset,
        HPO_DIR,
        vocabulary_path=VOCABULARY,
        n_trials=10,
        study_name="poule-hpo",
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
    # Use full 20 epochs with patience 3 for the final model
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
        logger.error("model.pt not found — MLX→PyTorch conversion may have failed")
        sys.exit(1)

    from Poule.neural.training.evaluator import TacticEvaluator
    from Poule.neural.training.model import TacticClassifier
    from Poule.neural.training.trainer import load_checkpoint
    from Poule.neural.training.vocabulary import CoqTokenizer
    import torch

    ckpt = load_checkpoint(pt_path)
    label_map = ckpt.get("label_map", {})
    label_names = sorted(label_map.keys(), key=lambda k: label_map[k])
    num_classes = len(label_names)

    tokenizer = CoqTokenizer(VOCABULARY)
    device = torch.device("cpu")

    model = TacticClassifier.from_checkpoint(ckpt)
    model = model.to(device)
    model.eval()

    # Re-map test pairs to checkpoint's label map
    test_pairs = []
    for state_text, label_idx in dataset.test_pairs:
        family = dataset.label_names[label_idx]
        if family in label_map:
            test_pairs.append((state_text, label_map[family]))
        elif "other" in label_map:
            test_pairs.append((state_text, label_map["other"]))

    logger.info("  test_pairs=%d", len(test_pairs))

    evaluator = TacticEvaluator(model, tokenizer, label_names, device)
    report = evaluator.evaluate(test_pairs)

    # ---- Step 5: Write results ----
    lines = []
    lines.append("=" * 60)
    lines.append("FINAL MODEL VALIDATION RESULTS")
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
    lines.append(f"Test samples:       {len(test_pairs)}")
    lines.append(f"Tactic classes:     {num_classes}")
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
    lines.append(f"Accuracy@1: {report.accuracy_at_1:.4f} ({report.accuracy_at_1*100:.1f}%)")
    lines.append(f"Accuracy@5: {report.accuracy_at_5:.4f} ({report.accuracy_at_5*100:.1f}%)")
    lines.append(f"Eval latency: {report.eval_latency_ms:.1f} ms")
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
    lines.append("=" * 60)

    text = "\n".join(lines) + "\n"
    RESULTS_FILE.write_text(text)
    logger.info("Results written to %s", RESULTS_FILE)

    # Also print to stdout
    print(text)


if __name__ == "__main__":
    main()
