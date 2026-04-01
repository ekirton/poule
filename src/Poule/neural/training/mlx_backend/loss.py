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

    Vectorized: builds mask matrices and computes logsumexp in bulk
    rather than iterating per positive pair in Python.

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

    # Flatten all (state_idx, positive_idx) pairs and build masks.
    # For each positive pair (i, j), candidates = {j} ∪ {all non-positives for i}.
    # We use additive masking: 0 for candidates, -inf for excluded.
    rows = []      # state index for each pair
    pos_cols = []  # positive premise index for each pair
    # mask_matrix[pair_k, p] = 0 if p is a candidate, -inf otherwise
    import numpy as np
    mask_rows = []

    for i in range(B):
        pos_set = set(positive_indices[i])
        if not pos_set:
            continue
        for j in positive_indices[i]:
            rows.append(i)
            pos_cols.append(j)
            # Candidate mask: j itself + all non-positives
            mask = np.full(P, -1e9, dtype=np.float32)
            mask[j] = 0.0
            for p in range(P):
                if p not in pos_set:
                    mask[p] = 0.0
            mask_rows.append(mask)

    if not rows:
        return mx.array(0.0)

    K = len(rows)
    rows_arr = mx.array(np.array(rows, dtype=np.int32))
    pos_cols_arr = mx.array(np.array(pos_cols, dtype=np.int32))
    mask_matrix = mx.array(np.stack(mask_rows))  # [K, P]

    # Gather similarity rows for each pair: [K, P]
    pair_sims = sim[rows_arr]  # [K, P]

    # Apply mask (additive: -inf removes non-candidates from logsumexp)
    masked_sims = pair_sims + mask_matrix  # [K, P]

    # logsumexp over candidates for each pair
    lse = mx.logsumexp(masked_sims, axis=1)  # [K]

    # Positive logits: sim[rows[k], pos_cols[k]]
    pos_logits = sim[rows_arr, pos_cols_arr]  # [K]

    # Loss per pair: -pos_logit + logsumexp(candidates)
    losses = -pos_logits + lse  # [K]

    return mx.mean(losses)
