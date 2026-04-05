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


def masked_contrastive_loss_mlx(
    state_embs: mx.array,
    premise_embs: mx.array,
    positive_indices: list[list[int]],
    temperature: float = 0.05,
) -> mx.array:
    """Compute masked contrastive loss (InfoNCE with shared-positive masking).

    For each state, its positive premises contribute to the numerator. Any
    premise that is positive for ANY state in the batch is excluded from
    all states' negative sets.

    Args:
        state_embs: [N_states, dim] L2-normalized state embeddings.
        premise_embs: [N_premises, dim] L2-normalized premise embeddings.
        positive_indices: For each state, list of premise indices that are
            positive for that state.
        temperature: Scaling factor for similarity logits.

    Returns:
        Scalar loss averaged over all (state, positive_premise) pairs.
    """
    N_states = state_embs.shape[0]
    N_premises = premise_embs.shape[0]

    # Similarity matrix: [N_states, N_premises]
    sim = (state_embs @ premise_embs.T) / temperature

    # Build positive mask
    pos_mask_np = __import__("numpy").zeros((N_states, N_premises), dtype=__import__("numpy").float32)
    for i, pos in enumerate(positive_indices):
        for j in pos:
            pos_mask_np[i, j] = 1.0
    positive_mask = mx.array(pos_mask_np)

    # Build exclusion mask: any premise positive for ANY state is excluded
    any_positive = (positive_mask.sum(axis=0) > 0).astype(mx.float32)  # [N_premises]
    negative_mask = 1.0 - mx.broadcast_to(
        mx.expand_dims(any_positive, axis=0), (N_states, N_premises)
    )

    # For numerical stability, subtract max
    sim_max = mx.stop_gradient(sim.max(axis=1, keepdims=True))
    sim_stable = sim - sim_max

    # Denominator: negatives + own positives
    denom_mask = negative_mask + positive_mask
    exp_sim = mx.exp(sim_stable) * denom_mask
    log_denom = mx.log(exp_sim.sum(axis=1, keepdims=True) + 1e-10)

    # Per-pair loss
    per_pair_loss = -(sim_stable - log_denom) * positive_mask

    # Average over all positive pairs
    total_positives = positive_mask.sum()
    return per_pair_loss.sum() / mx.maximum(total_positives, mx.array(1e-10))
