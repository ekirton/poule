"""Class-conditional label smoothing cross-entropy loss and hierarchical loss.

Distributes smoothing mass proportionally to class weights rather than
uniformly, directing more probability mass toward minority classes.

Reference: Shwartz-Ziv et al. (2023), NeurIPS -- class-conditional smoothing
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
    y = (1 - e) * one_hot(label) + e * smooth_dist

    Args:
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class weights.
        label_smoothing: smoothing parameter e in [0, 1).

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
    focal_gamma: float = 0.0,
) -> torch.Tensor:
    """Weighted cross-entropy with class-conditional label smoothing.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights.
        label_smoothing: smoothing parameter e in [0, 1).
        focal_gamma: focusing parameter (Lin et al., 2017). When > 0,
            down-weights easy examples via (1 - p_t)^gamma modulation.

    Returns:
        Scalar loss (weighted mean over batch).
    """
    targets = _smooth_targets(labels, class_weights, label_smoothing)  # [B, C]
    log_probs = F.log_softmax(logits, dim=-1)  # [B, C]
    per_sample_loss = -(targets * log_probs).sum(dim=-1)  # [B]

    # Focal modulation: down-weight easy (high p_t) examples
    if focal_gamma > 0.0:
        probs = torch.softmax(logits, dim=-1)  # [B, C]
        p_t = probs[torch.arange(logits.size(0)), labels]  # [B]
        per_sample_loss = per_sample_loss * (1.0 - p_t) ** focal_gamma

    sample_weights = class_weights[labels]  # [B]
    return (per_sample_loss * sample_weights).sum() / sample_weights.sum()


def hierarchical_loss(
    category_logits: torch.Tensor,
    within_logits: dict[str, torch.Tensor],
    category_labels: torch.Tensor,
    within_labels: torch.Tensor,
    category_weights: torch.Tensor,
    per_category_weights: dict[str, torch.Tensor],
    category_names: list[str],
    label_smoothing: float,
    lambda_within: float = 1.0,
    focal_gamma: float = 0.0,
) -> torch.Tensor:
    """Hierarchical loss: L = L_category + lambda * L_within(active head).

    Only the head corresponding to the true category receives gradients
    for L_within.

    Args:
        category_logits: [B, num_categories] from category head.
        within_logits: dict[cat_name -> [B, cat_size]] from within-category heads.
        category_labels: [B] true category indices.
        within_labels: [B] true within-category tactic indices.
        category_weights: [num_categories] inverse-frequency weights for categories.
        per_category_weights: dict[cat_name -> [cat_size]] per-category class weights.
        category_names: ordered list of category names (index -> name).
        label_smoothing: smoothing parameter.
        lambda_within: balancing weight for within-category loss.
        focal_gamma: focusing parameter for focal loss modulation.

    Returns:
        Scalar combined loss.
    """
    # Category loss
    l_category = class_conditional_cross_entropy(
        category_logits, category_labels, category_weights, label_smoothing,
        focal_gamma,
    )

    # Within-category loss: gather samples per true category
    l_within = torch.tensor(0.0, device=category_logits.device)
    total_within_weight = 0.0

    for cat_idx, cat_name in enumerate(category_names):
        mask = category_labels == cat_idx
        if not mask.any():
            continue

        cat_within_labels = within_labels[mask]
        cat_logits = within_logits[cat_name][mask]
        cat_weights = per_category_weights[cat_name]

        cat_loss = class_conditional_cross_entropy(
            cat_logits, cat_within_labels, cat_weights, label_smoothing,
            focal_gamma,
        )
        n = mask.sum().item()
        l_within = l_within + cat_loss * n
        total_within_weight += n

    if total_within_weight > 0:
        l_within = l_within / total_within_weight

    return l_category + lambda_within * l_within
