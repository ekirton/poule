#!/usr/bin/env python3
"""Evaluate and export the best model from a completed HPO study.

Skips HPO entirely. Promotes the best trial's checkpoint from a prior HPO run,
evaluates on the test set, and exports to ONNX.
"""

import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("train-final-model")

DATA_DIR = Path(os.environ.get("POULE_DATA_DIR", Path.home() / "poule-home" / "data"))
TRAINING_DATA = DATA_DIR / "training.jsonl"
VOCABULARY = DATA_DIR / "coq-vocabulary.json"
HPO_DB = DATA_DIR / "hpo-results-run1" / "hpo-study.db"
FINAL_MODEL_DIR = DATA_DIR / "final-model"
RESULTS_FILE = DATA_DIR / "final-model-validation.txt"

UNDERSAMPLE_CAP = 2000
UNDERSAMPLE_MIN = max(1, int(UNDERSAMPLE_CAP * 0.05))  # 5% of cap = 100
OVERSAMPLE_FLOOR = max(1, int(UNDERSAMPLE_CAP * 0.25))  # 25% of cap = 500


def load_best_hyperparams(db_path: Path) -> tuple[dict, int]:
    """Load best hyperparameters and best epoch from completed Optuna study."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("""
            SELECT t.trial_id, t.number, tv.value
            FROM trials t JOIN trial_values tv ON t.trial_id = tv.trial_id
            WHERE t.state = 'COMPLETE'
            ORDER BY tv.value DESC LIMIT 1
        """).fetchone()
        if row is None:
            raise RuntimeError(f"No completed trials found in {db_path}")
        trial_id, trial_number, best_value = row
        logger.info("Best trial: %d, val acc@5=%.4f", trial_number, best_value)

        # Decode params (categorical params stored as indices)
        params_rows = conn.execute(
            "SELECT param_name, param_value, distribution_json FROM trial_params WHERE trial_id=?",
            (trial_id,),
        ).fetchall()
        hp = {}
        for name, val, dist_json in params_rows:
            dist = json.loads(dist_json)
            if dist.get("name") == "CategoricalDistribution":
                choices = dist["attributes"]["choices"]
                hp[name] = choices[int(val)]
            else:
                hp[name] = val

        # Best epoch from intermediate values (epoch with highest val acc@5)
        intermediates = conn.execute(
            "SELECT step, intermediate_value FROM trial_intermediate_values WHERE trial_id=? ORDER BY intermediate_value DESC LIMIT 1",
            (trial_id,),
        ).fetchone()
        best_epoch = int(intermediates[0]) if intermediates else 10
        logger.info("Best epoch: %d", best_epoch)
        return hp, best_epoch
    finally:
        conn.close()


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

    # Undersample training set (same as HPO phase)
    original_train = len(dataset.train_pairs)
    dataset = undersample_train(dataset, cap=UNDERSAMPLE_CAP, min_count=UNDERSAMPLE_MIN)
    logger.info(
        "Undersampled train set: %d -> %d (cap=%d, min=%d per family)",
        original_train,
        len(dataset.train_pairs),
        UNDERSAMPLE_CAP,
        UNDERSAMPLE_MIN,
    )

    # Oversample minority families
    pre_oversample = len(dataset.train_pairs)
    dataset = oversample_train(dataset, floor=OVERSAMPLE_FLOOR)
    logger.info(
        "Oversampled train set: %d -> %d (floor=%d per family)",
        pre_oversample,
        len(dataset.train_pairs),
        OVERSAMPLE_FLOOR,
    )

    # ---- Step 2: Load best hyperparams from HPO run ----
    logger.info("Loading best hyperparams from %s", HPO_DB)
    best_hp, best_epoch = load_best_hyperparams(HPO_DB)
    logger.info("Best hyperparameters: %s", best_hp)

    # ---- Step 3: Promote best HPO trial model ----
    best_model_src = HPO_DB.parent / "best-model.pt"
    if not best_model_src.exists():
        logger.error("best-model.pt not found in %s", HPO_DB.parent)
        sys.exit(1)

    FINAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    best_model_dst = FINAL_MODEL_DIR / "model.pt"
    shutil.copy2(best_model_src, best_model_dst)
    logger.info("Promoted best HPO model: %s -> %s", best_model_src, best_model_dst)

    # ---- Step 4: Evaluate ----
    logger.info("Evaluating final model on test set...")
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

    # Copy vocabulary alongside model artifacts
    vocab_dest = FINAL_MODEL_DIR / "coq-vocabulary.json"
    if not vocab_dest.exists() and VOCABULARY.exists():
        shutil.copy2(VOCABULARY, vocab_dest)
        logger.info("Copied vocabulary to %s", vocab_dest)

    # ---- Step 6: Write results ----
    _MIN_TRAINABLE = UNDERSAMPLE_MIN
    _COMFORTABLE = UNDERSAMPLE_MIN * 2

    ge_min = [f for f in report.per_family_recall if dataset.family_counts.get(f, 0) >= _MIN_TRAINABLE]
    ge_comf = [f for f in report.per_family_recall if dataset.family_counts.get(f, 0) >= _COMFORTABLE]
    nonzero_ge_min = sum(1 for f in ge_min if report.per_family_recall[f] > 0.0)
    nonzero_ge_comf = sum(1 for f in ge_comf if report.per_family_recall[f] > 0.0)
    cov_ge_min = nonzero_ge_min / len(ge_min) if ge_min else 0.0
    cov_ge_comf = nonzero_ge_comf / len(ge_comf) if ge_comf else 0.0
    dead_count = sum(1 for rec in report.per_family_recall.values() if rec == 0.0)
    total_families = len(report.per_family_recall)

    lines = []
    lines.append("=" * 60)
    lines.append("FINAL MODEL VALIDATION RESULTS (HIERARCHICAL)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Training data: {TRAINING_DATA}")
    lines.append(f"HPO study: {HPO_DB}")
    lines.append(f"Vocabulary: {VOCABULARY} ({tokenizer.vocab_size} tokens)")
    lines.append(f"Model checkpoint: {pt_path}")
    lines.append("")
    lines.append("--- Dataset ---")
    lines.append(f"Train samples:       {len(dataset.train_pairs)}")
    lines.append(f"Val samples:         {len(dataset.val_pairs)}")
    lines.append(f"Test samples:        {len(dataset.test_pairs)}")
    lines.append(f"Categories:          {dataset.num_categories}")
    lines.append(f"Total tactics:       {dataset.num_classes}")
    lines.append("")
    lines.append("--- HPO (pre-loaded) ---")
    lines.append(f"Best HPO val acc@5: (from prior run)")
    lines.append(f"Best epoch:         {best_epoch}")
    lines.append("")
    lines.append("Best hyperparameters:")
    for k, v in sorted(best_hp.items()):
        if isinstance(v, float):
            lines.append(f"  {k:30s} {v:.6g}")
        else:
            lines.append(f"  {k:30s} {v}")
    lines.append("")
    lines.append("--- Final Model (best HPO trial) ---")
    lines.append(f"Hidden layers: {best_hp.get('num_hidden_layers', 4)}")
    lines.append(f"Best epoch: {best_epoch}")
    lines.append(f"Category Accuracy@1: {report.category_accuracy_at_1:.4f} ({report.category_accuracy_at_1*100:.1f}%)")
    lines.append(f"Accuracy@1: {report.accuracy_at_1:.4f} ({report.accuracy_at_1*100:.1f}%)")
    lines.append(f"Accuracy@5: {report.accuracy_at_5:.4f} ({report.accuracy_at_5*100:.1f}%)")
    lines.append(f"Eval latency: {report.eval_latency_ms:.1f} ms")
    lines.append("")

    lines.append("--- Per-Category Accuracy ---")
    lines.append(f"{'Category':<25s} {'Accuracy':>10s}")
    lines.append("-" * 37)
    for cat, acc in sorted(report.per_category_accuracy.items()):
        lines.append(f"{cat:<25s} {acc:>10.4f}")
    lines.append("")

    lines.append("--- Per-Family Precision/Recall ---")
    lines.append(f"{'Family':<30s} {'Precision':>10s} {'Recall':>10s}")
    lines.append("-" * 52)
    for family in sorted(report.per_family_precision.keys()):
        prec = report.per_family_precision.get(family, 0.0)
        rec = report.per_family_recall.get(family, 0.0)
        lines.append(f"{family:<30s} {prec:>10.4f} {rec:>10.4f}")
    lines.append("")

    lines.append(f"Zero-recall families: {dead_count} of {total_families}")
    lines.append(f"Trainable coverage (>={_MIN_TRAINABLE} examples): {nonzero_ge_min}/{len(ge_min)} = {cov_ge_min:.1%}")
    lines.append(f"Trainable coverage (>={_COMFORTABLE} examples): {nonzero_ge_comf}/{len(ge_comf)} = {cov_ge_comf:.1%}")
    lines.append("")

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
