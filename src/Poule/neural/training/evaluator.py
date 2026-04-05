"""Tactic prediction evaluation and deployment readiness reporting.

Implements TacticEvaluator with accuracy@k, per-family precision/recall,
and confusion matrix for hierarchical tactic family classification.
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
    # Hierarchical metrics
    category_accuracy_at_1: float = 0.0
    per_category_accuracy: dict[str, float] = field(default_factory=dict)

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
    """Evaluates hierarchical tactic family classification quality."""

    def __init__(self, model, tokenizer, label_names: list[str], device,
                 category_names: list[str] | None = None,
                 per_category_label_names: dict[str, list[str]] | None = None):
        self.model = model
        self.tokenizer = tokenizer
        self.label_names = label_names
        self.device = device
        self.num_classes = len(label_names)
        self.category_names = category_names or []
        self.per_category_label_names = per_category_label_names or {}
        self._is_hierarchical = bool(category_names)

    def evaluate(
        self,
        test_pairs: list[tuple[str, int] | tuple[str, int, int]],
        batch_size: int = 64,
    ) -> EvaluationReport:
        """Evaluate the tactic classifier on test data.

        Args:
            test_pairs: List of (proof_state_text, label_index) pairs or
                        (proof_state_text, category_idx, within_idx) triples.
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

        if self._is_hierarchical:
            return self._evaluate_hierarchical(test_pairs, batch_size)
        else:
            return self._evaluate_flat(test_pairs, batch_size)

    def _evaluate_hierarchical(self, test_pairs, batch_size):
        """Evaluate using product rule: P(tactic) = P(cat) * P(tactic|cat)."""
        import torch
        from Poule.neural.training.trainer import _tokenize_batch

        self.model.eval()

        # Build flat tactic index
        flat_tactics = []
        flat_to_cat_within = []
        for cat_idx, cat in enumerate(self.category_names):
            tactics = self.per_category_label_names.get(cat, [])
            for within_idx, tac in enumerate(tactics):
                flat_tactics.append(tac)
                flat_to_cat_within.append((cat_idx, within_idx))

        num_flat = len(flat_tactics)
        confusion = [[0] * num_flat for _ in range(num_flat)]
        tp = [0] * num_flat
        fp = [0] * num_flat
        fn = [0] * num_flat
        hits_at_1 = 0
        hits_at_5 = 0
        cat_hits = 0

        # Per-category accuracy tracking
        per_cat_correct = {cat: 0 for cat in self.category_names}
        per_cat_total = {cat: 0 for cat in self.category_names}

        texts = [p[0] for p in test_pairs]
        true_cats = [p[1] for p in test_pairs]
        true_withins = [p[2] for p in test_pairs]

        t0 = time.perf_counter()

        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch_texts = texts[start:start + batch_size]
                batch_true_cats = true_cats[start:start + batch_size]
                batch_true_withins = true_withins[start:start + batch_size]

                tokens = _tokenize_batch(self.tokenizer, batch_texts, 512)
                cat_logits, within_logits = self.model(
                    tokens["input_ids"].to(self.device),
                    tokens["attention_mask"].to(self.device),
                )

                cat_probs = torch.softmax(cat_logits, dim=-1)
                top1_cats = cat_probs.argmax(dim=-1)

                # Product rule scores
                all_scores = []
                for cat_idx, cat in enumerate(self.category_names):
                    within_probs = torch.softmax(within_logits[cat], dim=-1)
                    product = cat_probs[:, cat_idx:cat_idx+1] * within_probs
                    all_scores.append(product)
                all_scores_tensor = torch.cat(all_scores, dim=-1)

                k5 = min(5, all_scores_tensor.size(1))
                top5 = torch.topk(all_scores_tensor, k5, dim=-1).indices
                top1 = top5[:, 0]

                for i in range(len(batch_texts)):
                    true_cat = batch_true_cats[i]
                    true_within = batch_true_withins[i]

                    # True flat index
                    offset = sum(
                        len(self.per_category_label_names.get(self.category_names[c], []))
                        for c in range(true_cat)
                    )
                    true_flat = offset + true_within
                    pred_flat = top1[i].item()

                    # Category accuracy
                    if top1_cats[i].item() == true_cat:
                        cat_hits += 1

                    # Per-category tracking
                    cat_name = self.category_names[true_cat]
                    per_cat_total[cat_name] += 1

                    # Confusion matrix
                    if true_flat < num_flat and pred_flat < num_flat:
                        confusion[true_flat][pred_flat] += 1

                    # Accuracy@1
                    if pred_flat == true_flat:
                        hits_at_1 += 1
                        per_cat_correct[cat_name] += 1

                    # Accuracy@5
                    if true_flat in top5[i].tolist():
                        hits_at_5 += 1

                    # Per-family precision/recall
                    if pred_flat == true_flat:
                        if true_flat < num_flat:
                            tp[true_flat] += 1
                    else:
                        if pred_flat < num_flat:
                            fp[pred_flat] += 1
                        if true_flat < num_flat:
                            fn[true_flat] += 1

        t1 = time.perf_counter()
        n = len(test_pairs)

        per_family_precision = {}
        per_family_recall = {}
        for c in range(num_flat):
            name = flat_tactics[c]
            denom_p = tp[c] + fp[c]
            per_family_precision[name] = tp[c] / denom_p if denom_p > 0 else 0.0
            denom_r = tp[c] + fn[c]
            per_family_recall[name] = tp[c] / denom_r if denom_r > 0 else 0.0

        per_category_accuracy = {}
        for cat in self.category_names:
            total = per_cat_total[cat]
            per_category_accuracy[cat] = per_cat_correct[cat] / total if total > 0 else 0.0

        return EvaluationReport(
            accuracy_at_1=hits_at_1 / n,
            accuracy_at_5=hits_at_5 / n,
            per_family_precision=per_family_precision,
            per_family_recall=per_family_recall,
            confusion_matrix=confusion,
            label_names=flat_tactics,
            test_count=n,
            eval_latency_ms=(t1 - t0) * 1000.0,
            category_accuracy_at_1=cat_hits / n,
            per_category_accuracy=per_category_accuracy,
        )

    def _evaluate_flat(self, test_pairs, batch_size):
        """Original flat evaluation (backward compat)."""
        import torch
        from Poule.neural.training.trainer import _tokenize_batch

        self.model.eval()
        texts = [pair[0] for pair in test_pairs]
        labels = [pair[1] for pair in test_pairs]

        hits_at_1 = 0
        hits_at_5 = 0
        confusion = [[0] * self.num_classes for _ in range(self.num_classes)]
        tp = [0] * self.num_classes
        fp = [0] * self.num_classes
        fn = [0] * self.num_classes

        t0 = time.perf_counter()

        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch_texts = texts[start:start + batch_size]
                batch_labels = labels[start:start + batch_size]

                tokens = _tokenize_batch(self.tokenizer, batch_texts, 512)
                logits = self.model(
                    tokens["input_ids"].to(self.device),
                    tokens["attention_mask"].to(self.device),
                )

                k5 = min(5, self.num_classes)
                top5 = torch.topk(logits, k5, dim=-1).indices
                top1 = top5[:, 0]

                for i, true_label in enumerate(batch_labels):
                    pred_label = top1[i].item()
                    confusion[true_label][pred_label] += 1
                    if pred_label == true_label:
                        hits_at_1 += 1
                    if true_label in top5[i].tolist():
                        hits_at_5 += 1
                    if pred_label == true_label:
                        tp[true_label] += 1
                    else:
                        fp[pred_label] += 1
                        fn[true_label] += 1

        t1 = time.perf_counter()
        n = len(test_pairs)

        per_family_precision = {}
        per_family_recall = {}
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
            eval_latency_ms=(t1 - t0) * 1000.0,
        )
