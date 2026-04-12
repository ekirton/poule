"""Sharpness-Aware Minimization (SAM) for MLX.

SAM seeks parameters in flat loss neighborhoods rather than sharp minima,
improving generalization on class-imbalanced data (Shwartz-Ziv et al., 2023).

Each training step performs two forward-backward passes:
1. Compute gradient, perturb parameters by rho * grad / ||grad||.
2. Compute gradient at perturbed point, apply base optimizer step, restore.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn
import mlx.utils


def sam_step(
    model: nn.Module,
    loss_fn,
    optimizer,
    rho: float,
) -> mx.array:
    """Perform one SAM training step.

    When ``rho > 0``, computes the gradient at the current parameters,
    perturbs toward the ascent direction, recomputes the gradient at
    the perturbed point, restores original parameters, and applies
    the base optimizer with the second gradient.

    When ``rho == 0``, equivalent to a single forward-backward pass
    with the base optimizer (plain AdamW).

    Args:
        model: MLX model (parameters are mutated in place).
        loss_fn: Callable taking the model and returning a scalar loss.
        optimizer: MLX optimizer instance (e.g., ``optim.AdamW``).
        rho: Perturbation radius. 0.0 disables SAM.

    Returns:
        Scalar loss value (from the first forward pass).
    """
    # First forward-backward pass
    loss, grads = nn.value_and_grad(model, loss_fn)(model)

    if rho > 0:
        # Compute L2 norm of the full gradient tree
        flat_grads = mlx.utils.tree_flatten(grads)
        grad_norm = mx.sqrt(
            sum(mx.sum(mx.square(g)) for _, g in flat_grads)
        )
        scale = rho / (grad_norm + 1e-12)
        mx.eval(scale)

        # Save original parameters
        old_params = mlx.utils.tree_map(lambda p: p, model.parameters())

        # Perturb: theta_perturbed = theta + scale * grad
        perturbed = mlx.utils.tree_map(
            lambda p, g: p + scale * g,
            model.parameters(),
            grads,
        )
        model.update(perturbed)
        mx.eval(model.parameters())

        # Second forward-backward pass at perturbed point
        _, grads = nn.value_and_grad(model, loss_fn)(model)

        # Restore original parameters before optimizer step
        model.update(old_params)

    # Apply optimizer with the (second) gradient
    optimizer.update(model, grads)
    mx.eval(model.parameters(), optimizer.state, loss)
    return loss
