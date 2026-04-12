"""MLX cross-entropy loss with LDAM margins for tactic classifier training.

Weighted cross-entropy loss reimplemented using mlx.core operations,
with LDAM margin offsets (Cao et al., 2019) for class-imbalanced learning.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import mlx.core as mx


def cross_entropy_loss(
    logits: mx.array,
    labels: mx.array,
    class_weights: mx.array | None = None,
) -> mx.array:
    """Compute weighted cross-entropy loss.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights.
            If None, all classes are weighted equally.

    Returns:
        Scalar loss averaged over the batch (weighted mean).
    """
    B = logits.shape[0]
    num_classes = logits.shape[1]

    # Numerically stable log-softmax: logits - logsumexp(logits, axis=-1)
    log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)  # [B, C]

    # Gather log-probabilities for the true class
    # One-hot encode labels and dot with log_probs
    one_hot = mx.zeros((B, num_classes))
    one_hot = one_hot.at[mx.arange(B), labels].add(mx.ones((B,)))
    nll = -(one_hot * log_probs).sum(axis=-1)  # [B]

    if class_weights is not None:
        # Per-sample weight from its true class
        sample_weights = class_weights[labels]  # [B]
        return (nll * sample_weights).sum() / sample_weights.sum()
    else:
        return mx.mean(nll)


def ldam_cross_entropy_loss(
    logits: mx.array,
    labels: mx.array,
    class_weights: mx.array | None = None,
    margins: mx.array | None = None,
) -> mx.array:
    """Cross-entropy with LDAM margin offsets.

    Subtracts margin[y] from the logit of the true class before computing CE.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class weights.
        margins: [num_classes] LDAM margins. If None, no adjustment.

    Returns:
        Scalar loss.
    """
    if margins is not None:
        B = logits.shape[0]
        num_classes = logits.shape[1]
        one_hot = mx.zeros((B, num_classes))
        one_hot = one_hot.at[mx.arange(B), labels].add(mx.ones((B,)))
        adjusted_logits = logits - one_hot * margins
    else:
        adjusted_logits = logits
    return cross_entropy_loss(adjusted_logits, labels, class_weights)


def compute_ldam_margins_mlx(
    class_counts: mx.array,
    ldam_C: float = 0.3,
) -> mx.array:
    """Compute LDAM class-dependent margins: margin[c] = C / n_c^(1/4)."""
    return ldam_C / mx.power(class_counts, 0.25)


def precompute_category_indices(
    category_labels: mx.array,
    num_categories: int,
) -> list[mx.array]:
    """Pre-compute per-category sample indices for the full training set.

    Call once after pre-tokenization. Returns a list of mx.array index
    vectors, one per category, avoiding per-batch numpy round-trips.
    """
    import numpy as np

    cat_np = numpy_array_from_mlx(category_labels)
    indices = []
    for cat_idx in range(num_categories):
        idx = numpy_array_from_mlx(None, raw=np.where(cat_np == cat_idx)[0])
        indices.append(idx)
    return indices


def numpy_array_from_mlx(arr, *, raw=None):
    """Convert MLX array to numpy, or wrap a raw numpy array as mx.array."""
    import numpy as np
    if raw is not None:
        return mx.array(raw)
    return np.array(arr)


def hierarchical_loss_mlx(
    category_logits: mx.array,
    within_logits: dict[str, mx.array],
    category_labels: mx.array,
    within_labels: mx.array,
    category_weights: mx.array,
    per_category_weights: dict[str, mx.array],
    category_names: list[str],
    lambda_within: float = 1.0,
    batch_cat_indices: list[mx.array] | None = None,
    category_margins: mx.array | None = None,
    per_category_margins: dict[str, mx.array] | None = None,
) -> mx.array:
    """Hierarchical loss: L = L_category + lambda * L_within(active head).

    Args:
        category_logits: [B, num_categories]
        within_logits: dict[cat_name -> [B, cat_size]]
        category_labels: [B] true category indices
        within_labels: [B] true within-category indices
        category_weights: [num_categories] class weights
        per_category_weights: dict[cat_name -> [cat_size]] per-category weights
        category_names: ordered category names
        lambda_within: balancing weight
        batch_cat_indices: pre-computed per-category index arrays for this batch
        category_margins: [num_categories] LDAM margins for categories
        per_category_margins: dict[cat_name -> [cat_size]] LDAM margins per category

    Returns:
        Scalar combined loss.
    """
    l_category = ldam_cross_entropy_loss(
        category_logits, category_labels, category_weights, category_margins,
    )

    l_within = mx.array(0.0)
    total_weight = 0.0

    if batch_cat_indices is not None:
        for cat_idx, cat_name in enumerate(category_names):
            idx = batch_cat_indices[cat_idx]
            n = idx.shape[0]
            if n == 0:
                continue
            cat_within_labels = within_labels[idx]
            cat_logits = within_logits[cat_name][idx]
            cat_weights = per_category_weights[cat_name]
            cat_margins = per_category_margins.get(cat_name) if per_category_margins else None
            cat_loss = ldam_cross_entropy_loss(
                cat_logits, cat_within_labels, cat_weights, cat_margins,
            )
            l_within = l_within + cat_loss * n
            total_weight += n
    else:
        import numpy as np
        cat_labels_np = np.array(category_labels)
        for cat_idx, cat_name in enumerate(category_names):
            indices = np.where(cat_labels_np == cat_idx)[0]
            n = len(indices)
            if n == 0:
                continue
            idx = mx.array(indices)
            cat_within_labels = within_labels[idx]
            cat_logits = within_logits[cat_name][idx]
            cat_weights = per_category_weights[cat_name]
            cat_margins = per_category_margins.get(cat_name) if per_category_margins else None
            cat_loss = ldam_cross_entropy_loss(
                cat_logits, cat_within_labels, cat_weights, cat_margins,
            )
            l_within = l_within + cat_loss * n
            total_weight += n

    if total_weight > 0:
        l_within = l_within / total_weight

    return l_category + lambda_within * l_within
