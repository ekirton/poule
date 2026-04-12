"""LDAM loss, class-conditional label smoothing, deferred re-balancing, and hierarchical loss.

LDAM (Cao et al., 2019): class-dependent margin offsets penalize misclassification
of minority classes more heavily by subtracting margin[c] = C / n_c^(1/4) from the
true-class logit before softmax.

Deferred re-balancing (DRW): two-phase training schedule — instance-balanced sampling
for the first 80% of epochs, class-balanced sampling for the final 20%.

Class-conditional label smoothing distributes smoothing mass proportionally to class
weights rather than uniformly, directing more probability mass toward minority classes.

Reference: Cao et al. (2019), LDAM; Shwartz-Ziv et al. (2023), NeurIPS.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def compute_ldam_margins(
    class_counts: torch.Tensor,
    ldam_C: float = 0.3,
) -> torch.Tensor:
    """Compute LDAM class-dependent margins.

    margin[c] = C / n_c^(1/4)

    Args:
        class_counts: [num_classes] per-class sample counts.
        ldam_C: scaling constant (default 0.3).

    Returns:
        [num_classes] margin offsets.
    """
    return ldam_C / class_counts.pow(0.25)


def compute_drw_sample_weights(
    labels: torch.Tensor,
    class_counts: torch.Tensor,
) -> torch.Tensor:
    """Compute per-sample weights for class-balanced sampling (DRW phase 2).

    Each sample gets weight 1 / class_count[its_class].

    Args:
        labels: [N] integer class labels for all training samples.
        class_counts: [num_classes] per-class sample counts.

    Returns:
        [N] per-sample weights.
    """
    return 1.0 / class_counts[labels]


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
) -> torch.Tensor:
    """Weighted cross-entropy with class-conditional label smoothing.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights.
        label_smoothing: smoothing parameter e in [0, 1).

    Returns:
        Scalar loss (weighted mean over batch).
    """
    targets = _smooth_targets(labels, class_weights, label_smoothing)  # [B, C]
    log_probs = F.log_softmax(logits, dim=-1)  # [B, C]
    per_sample_loss = -(targets * log_probs).sum(dim=-1)  # [B]

    sample_weights = class_weights[labels]  # [B]
    return (per_sample_loss * sample_weights).sum() / sample_weights.sum()


def ldam_cross_entropy(
    logits: torch.Tensor,
    labels: torch.Tensor,
    class_weights: torch.Tensor,
    class_counts: torch.Tensor,
    ldam_C: float = 0.3,
    label_smoothing: float = 0.0,
) -> torch.Tensor:
    """LDAM loss: cross-entropy with class-dependent margin offsets.

    Subtracts margin[y] from the logit of the true class before computing
    the cross-entropy loss.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights (for smoothing).
        class_counts: [num_classes] per-class sample counts.
        ldam_C: LDAM scaling constant.
        label_smoothing: smoothing parameter.

    Returns:
        Scalar loss (weighted mean over batch).
    """
    margins = compute_ldam_margins(class_counts, ldam_C)  # [C]

    # Subtract margin from true-class logit only
    adjusted_logits = logits.clone()
    batch_indices = torch.arange(logits.size(0), device=logits.device)
    adjusted_logits[batch_indices, labels] -= margins[labels]

    return class_conditional_cross_entropy(
        adjusted_logits, labels, class_weights, label_smoothing,
    )


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
    category_counts: torch.Tensor | None = None,
    per_category_counts: dict[str, torch.Tensor] | None = None,
    ldam_C: float = 0.0,
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
        category_counts: [num_categories] per-category sample counts (for LDAM).
        per_category_counts: dict[cat_name -> [cat_size]] per-category tactic counts (for LDAM).
        ldam_C: LDAM scaling constant. When 0.0, no LDAM margins are applied.

    Returns:
        Scalar combined loss.
    """
    # Category loss
    if ldam_C > 0.0 and category_counts is not None:
        l_category = ldam_cross_entropy(
            category_logits, category_labels, category_weights,
            category_counts, ldam_C, label_smoothing,
        )
    else:
        l_category = class_conditional_cross_entropy(
            category_logits, category_labels, category_weights, label_smoothing,
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

        if ldam_C > 0.0 and per_category_counts is not None and cat_name in per_category_counts:
            cat_loss = ldam_cross_entropy(
                cat_logits, cat_within_labels, cat_weights,
                per_category_counts[cat_name], ldam_C, label_smoothing,
            )
        else:
            cat_loss = class_conditional_cross_entropy(
                cat_logits, cat_within_labels, cat_weights, label_smoothing,
            )
        n = mask.sum().item()
        l_within = l_within + cat_loss * n
        total_within_weight += n

    if total_within_weight > 0:
        l_within = l_within / total_within_weight

    return l_category + lambda_within * l_within
