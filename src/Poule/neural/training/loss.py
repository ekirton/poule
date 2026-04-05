"""Class-conditional label smoothing cross-entropy loss.

Distributes smoothing mass proportionally to class weights rather than
uniformly, directing more probability mass toward minority classes.

Reference: Shwartz-Ziv et al. (2023), NeurIPS — class-conditional smoothing
prevents overfitting on underrepresented groups.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def _smooth_targets(
    labels: torch.Tensor,
    class_weights: torch.Tensor,
    label_smoothing: float,
) -> torch.Tensor:
    """Build class-conditional soft targets.

    smooth_dist[c] = class_weight[c] / sum(class_weights)
    y = (1 - ε) * one_hot(label) + ε * smooth_dist

    Args:
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class weights.
        label_smoothing: smoothing parameter ε in [0, 1).

    Returns:
        [B, num_classes] soft target distribution.
    """
    num_classes = class_weights.shape[0]
    smooth_dist = class_weights / class_weights.sum()  # [C]
    one_hot = F.one_hot(labels, num_classes).float()  # [B, C]
    return (1.0 - label_smoothing) * one_hot + label_smoothing * smooth_dist


def class_conditional_cross_entropy(
    logits: torch.Tensor,
    labels: torch.Tensor,
    class_weights: torch.Tensor,
    label_smoothing: float,
) -> torch.Tensor:
    """Weighted cross-entropy with class-conditional label smoothing.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights.
        label_smoothing: smoothing parameter ε in [0, 1).

    Returns:
        Scalar loss (weighted mean over batch).
    """
    targets = _smooth_targets(labels, class_weights, label_smoothing)  # [B, C]
    log_probs = F.log_softmax(logits, dim=-1)  # [B, C]
    per_sample_loss = -(targets * log_probs).sum(dim=-1)  # [B]

    sample_weights = class_weights[labels]  # [B]
    return (per_sample_loss * sample_weights).sum() / sample_weights.sum()
