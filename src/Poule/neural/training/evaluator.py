"""Tactic prediction evaluation and deployment readiness reporting.

Implements TacticEvaluator with accuracy@k, per-family precision/recall,
and confusion matrix for tactic family classification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationReport:
    """Metrics from evaluating a tactic classifier on a test set."""

    accuracy_at_1: float
    accuracy_at_5: float
    per_family_precision: dict[str, float]
    per_family_recall: dict[str, float]
    confusion_matrix: list[list[int]]
    label_names: list[str]
    test_count: int
    eval_latency_ms: float
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.accuracy_at_1 < 0.40:
            self.warnings.append(
                "Model does not meet deployment threshold (accuracy@1 < 40%)"
            )
        if self.accuracy_at_5 < 0.80:
            self.warnings.append(
                "Model does not meet deployment threshold (accuracy@5 < 80%)"
            )


class TacticEvaluator:
    """Evaluates tactic family classification quality."""

    def __init__(self, model, tokenizer, label_names: list[str], device):
        self.model = model
        self.tokenizer = tokenizer
        self.label_names = label_names
        self.device = device
        self.num_classes = len(label_names)

    def evaluate(
        self,
        test_pairs: list[tuple[str, int]],
        batch_size: int = 64,
    ) -> EvaluationReport:
        """Evaluate the tactic classifier on test data.

        Args:
            test_pairs: List of (proof_state_text, label_index) pairs.
            batch_size: Number of examples per forward pass.

        Returns:
            EvaluationReport with accuracy, precision/recall, and confusion matrix.
        """
        import torch

        if not test_pairs:
            return EvaluationReport(
                accuracy_at_1=0.0,
                accuracy_at_5=0.0,
                per_family_precision={name: 0.0 for name in self.label_names},
                per_family_recall={name: 0.0 for name in self.label_names},
                confusion_matrix=[[0] * self.num_classes for _ in range(self.num_classes)],
                label_names=list(self.label_names),
                test_count=0,
                eval_latency_ms=0.0,
            )

        self.model.eval()

        texts = [pair[0] for pair in test_pairs]
        labels = [pair[1] for pair in test_pairs]

        hits_at_1 = 0
        hits_at_5 = 0
        confusion = [[0] * self.num_classes for _ in range(self.num_classes)]

        # Per-family tracking for precision and recall
        tp = [0] * self.num_classes
        fp = [0] * self.num_classes
        fn = [0] * self.num_classes

        t0 = time.perf_counter()

        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch_texts = texts[start : start + batch_size]
                batch_labels = labels[start : start + batch_size]

                tokens = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                logits = self.model(
                    tokens["input_ids"].to(self.device),
                    tokens["attention_mask"].to(self.device),
                )  # [B, num_classes]

                # Top-k predictions
                k5 = min(5, self.num_classes)
                top5 = torch.topk(logits, k5, dim=-1).indices  # [B, k5]
                top1 = top5[:, 0]  # [B]

                for i, true_label in enumerate(batch_labels):
                    pred_label = top1[i].item()

                    # Confusion matrix: rows = true, cols = predicted
                    confusion[true_label][pred_label] += 1

                    # Accuracy@1
                    if pred_label == true_label:
                        hits_at_1 += 1

                    # Accuracy@5
                    if true_label in top5[i].tolist():
                        hits_at_5 += 1

                    # Per-family precision/recall tracking
                    if pred_label == true_label:
                        tp[true_label] += 1
                    else:
                        fp[pred_label] += 1
                        fn[true_label] += 1

        t1 = time.perf_counter()
        eval_latency_ms = (t1 - t0) * 1000.0

        n = len(test_pairs)

        # Compute per-family precision and recall
        per_family_precision: dict[str, float] = {}
        per_family_recall: dict[str, float] = {}
        for c in range(self.num_classes):
            name = self.label_names[c]
            denom_p = tp[c] + fp[c]
            per_family_precision[name] = tp[c] / denom_p if denom_p > 0 else 0.0
            denom_r = tp[c] + fn[c]
            per_family_recall[name] = tp[c] / denom_r if denom_r > 0 else 0.0

        return EvaluationReport(
            accuracy_at_1=hits_at_1 / n,
            accuracy_at_5=hits_at_5 / n,
            per_family_precision=per_family_precision,
            per_family_recall=per_family_recall,
            confusion_matrix=confusion,
            label_names=list(self.label_names),
            test_count=n,
            eval_latency_ms=eval_latency_ms,
        )
