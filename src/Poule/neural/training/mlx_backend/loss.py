"""MLX masked contrastive loss for bi-encoder training.

spec §4.11: Same InfoNCE-with-masking algorithm as the PyTorch version,
reimplemented using mlx.core operations.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import mlx.core as mx


def masked_contrastive_loss_mlx(
    state_embs: mx.array,
    premise_embs: mx.array,
    positive_indices: list[list[int]],
    temperature: float,
) -> mx.array:
    """Compute masked contrastive loss (InfoNCE with premise masking).

    Args:
        state_embs: [B, dim] L2-normalized state embeddings.
        premise_embs: [P, dim] L2-normalized premise embeddings.
        positive_indices: positive_indices[i] gives the premise indices
            that are positive for state i.
        temperature: τ scalar.

    Returns:
        Scalar loss averaged over all positive pairs.
    """
    B = state_embs.shape[0]
    P = premise_embs.shape[0]

    # Cosine similarity scaled by temperature
    sim = mx.matmul(state_embs, premise_embs.T) / temperature  # [B, P]

    total_loss = mx.array(0.0)
    count = 0

    for i in range(B):
        pos_set = set(positive_indices[i])
        if not pos_set:
            continue

        for j in positive_indices[i]:
            # Mask: exclude other positives for this state from negatives
            mask = mx.ones(P, dtype=mx.bool_)
            for p in pos_set:
                if p != j:
                    mask = mask.at[p].add(-1)  # set to False

            # Rebuild mask without .at (not always available)
            mask_list = [True] * P
            for p in pos_set:
                if p != j:
                    mask_list[p] = False
            mask = mx.array(mask_list)

            pos_logit = sim[i, j]
            candidate_logits = sim[i][mask]
            loss_ij = -pos_logit + mx.logsumexp(candidate_logits)
            total_loss = total_loss + loss_ij
            count += 1

    if count == 0:
        return mx.array(0.0)

    return total_loss / count
