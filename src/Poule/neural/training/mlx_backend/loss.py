"""MLX cross-entropy loss for tactic classifier training.

Weighted cross-entropy loss reimplemented using mlx.core operations,
matching the PyTorch trainer's weighted CrossEntropyLoss.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import mlx.core as mx


def cross_entropy_loss(
    logits: mx.array,
    labels: mx.array,
    class_weights: mx.array | None = None,
    focal_gamma: float = 0.0,
) -> mx.array:
    """Compute weighted cross-entropy loss.

    Args:
        logits: [B, num_classes] unnormalized logits.
        labels: [B] integer class labels.
        class_weights: [num_classes] per-class inverse-frequency weights.
            If None, all classes are weighted equally.
        focal_gamma: focusing parameter (Lin et al., 2017). When > 0,
            down-weights easy examples via (1 - p_t)^gamma modulation.

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

    # Focal modulation: down-weight easy (high p_t) examples
    if focal_gamma > 0.0:
        probs = mx.softmax(logits, axis=-1)  # [B, C]
        p_t = (one_hot * probs).sum(axis=-1)  # [B]
        nll = nll * (1.0 - p_t) ** focal_gamma

    if class_weights is not None:
        # Per-sample weight from its true class
        sample_weights = class_weights[labels]  # [B]
        return (nll * sample_weights).sum() / sample_weights.sum()
    else:
        return mx.mean(nll)


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
    focal_gamma: float = 0.0,
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
        batch_cat_indices: pre-computed per-category index arrays for this
            batch (avoids numpy round-trip). If None, falls back to computing
            indices from category_labels.

    Returns:
        Scalar combined loss.
    """
    l_category = cross_entropy_loss(
        category_logits, category_labels, category_weights, focal_gamma,
    )

    l_within = mx.array(0.0)
    total_weight = 0.0

    if batch_cat_indices is not None:
        # Fast path: use pre-computed indices (no CPU-GPU sync)
        for cat_idx, cat_name in enumerate(category_names):
            idx = batch_cat_indices[cat_idx]
            n = idx.shape[0]
            if n == 0:
                continue
            cat_within_labels = within_labels[idx]
            cat_logits = within_logits[cat_name][idx]
            cat_weights = per_category_weights[cat_name]
            cat_loss = cross_entropy_loss(
                cat_logits, cat_within_labels, cat_weights, focal_gamma,
            )
            l_within = l_within + cat_loss * n
            total_weight += n
    else:
        # Fallback: compute indices via numpy (causes CPU-GPU sync)
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
            cat_loss = cross_entropy_loss(
                cat_logits, cat_within_labels, cat_weights, focal_gamma,
            )
            l_within = l_within + cat_loss * n
            total_weight += n

    if total_weight > 0:
        l_within = l_within / total_weight

    return l_category + lambda_within * l_within


