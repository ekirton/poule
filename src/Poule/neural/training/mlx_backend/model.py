"""MLX bi-encoder model for neural premise selection training.

Architecturally identical to the PyTorch BiEncoder: shared-weight encoder
with mean pooling and L2 normalization, producing 768-dim embeddings.

Requires: mlx (macOS with Apple Silicon only).
"""

from __future__ import annotations

import math
from typing import Any

import mlx.core as mx
import mlx.nn as nn
import numpy as np


class TransformerEncoderLayer(nn.Module):
    """Single transformer encoder layer matching CodeBERT/RoBERTa architecture."""

    def __init__(self, hidden_size: int, num_heads: int):
        super().__init__()
        self.attention = nn.MultiHeadAttention(
            dims=hidden_size, num_heads=num_heads, bias=True,
        )
        self.ln1 = nn.LayerNorm(hidden_size)
        self.ln2 = nn.LayerNorm(hidden_size)
        self.linear1 = nn.Linear(hidden_size, hidden_size * 4)
        self.linear2 = nn.Linear(hidden_size * 4, hidden_size)

    def __call__(self, x: mx.array, mask: mx.array | None = None) -> mx.array:
        # Self-attention with residual + layer norm
        attn_out = self.attention(x, x, x, mask=mask)
        x = self.ln1(x + attn_out)
        # FFN with residual + layer norm
        ffn_out = self.linear2(nn.gelu(self.linear1(x)))
        return self.ln2(x + ffn_out)


class MLXBiEncoder(nn.Module):
    """Shared-weight bi-encoder with mean pooling and L2 normalization.

    spec §4.10: Architecturally identical to the PyTorch BiEncoder.
    """

    def __init__(
        self,
        vocab_size: int,
        num_layers: int = 12,
        hidden_size: int = 768,
        num_heads: int = 12,
        max_seq_length: int = 514,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(vocab_size, hidden_size)
        self.position_embedding = nn.Embedding(max_seq_length, hidden_size)
        self.layers = [
            TransformerEncoderLayer(hidden_size, num_heads)
            for _ in range(num_layers)
        ]
        self.embedding_ln = nn.LayerNorm(hidden_size)

    def __call__(self, input_ids: mx.array, attention_mask: mx.array) -> mx.array:
        """Encode text to L2-normalized embedding vectors.

        Args:
            input_ids: [B, seq_len] token IDs.
            attention_mask: [B, seq_len] with values 0 or 1.

        Returns:
            [B, hidden_size] L2-normalized embeddings.
        """
        seq_len = input_ids.shape[1]
        positions = mx.arange(seq_len)

        x = self.embedding(input_ids) + self.position_embedding(positions)
        x = self.embedding_ln(x)

        # Create causal-style mask for attention (0 = attend, -inf = ignore)
        # MLX MultiHeadAttention expects additive mask
        if attention_mask is not None:
            # [B, seq_len] -> [B, 1, 1, seq_len] for broadcasting
            attn_mask = mx.where(
                attention_mask[:, None, None, :].astype(mx.bool_),
                mx.array(0.0),
                mx.array(-1e9),
            )
        else:
            attn_mask = None

        for layer in self.layers:
            x = layer(x, mask=attn_mask)

        # Mean pooling over non-padding tokens
        mask_expanded = attention_mask[:, :, None].astype(mx.float32)
        summed = (x * mask_expanded).sum(axis=1)
        counts = mx.maximum(mask_expanded.sum(axis=1), mx.array(1e-9))
        pooled = summed / counts

        # L2 normalization
        norms = mx.linalg.norm(pooled, axis=1, keepdims=True)
        norms = mx.maximum(norms, mx.array(1e-9))
        return pooled / norms

    def load_codebert_weights(
        self, pytorch_model_name: str = "microsoft/codebert-base"
    ) -> None:
        """Load CodeBERT weights from HuggingFace, converting to MLX arrays.

        spec §4.10: Converts torch.Tensor → numpy → mx.array and maps
        parameter names from HuggingFace convention to MLX convention.
        """
        try:
            from transformers import AutoModel
        except ImportError:
            raise ImportError(
                "transformers is required for CodeBERT weight initialization"
            )

        import torch

        pt_model = AutoModel.from_pretrained(pytorch_model_name)
        pt_state = pt_model.state_dict()

        num_layers = len(self.layers)
        vocab_size = self.embedding.weight.shape[0]
        hidden_size = self.hidden_size

        # Copy position embeddings
        pos_weight = pt_state["embeddings.position_embeddings.weight"]
        max_pos = min(pos_weight.shape[0], self.position_embedding.weight.shape[0])
        pos_np = pos_weight[:max_pos].detach().numpy()
        new_pos = np.array(self.position_embedding.weight)
        new_pos[:max_pos] = pos_np
        self.position_embedding.weight = mx.array(new_pos)

        # Copy embedding layer norm
        self.embedding_ln.weight = mx.array(
            pt_state["embeddings.LayerNorm.weight"].detach().numpy()
        )
        self.embedding_ln.bias = mx.array(
            pt_state["embeddings.LayerNorm.bias"].detach().numpy()
        )

        # Copy word embeddings (overlap)
        old_vocab_size = pt_state["embeddings.word_embeddings.weight"].shape[0]
        overlap = min(vocab_size, old_vocab_size)
        emb_np = np.array(self.embedding.weight)
        emb_np[:overlap] = (
            pt_state["embeddings.word_embeddings.weight"][:overlap].detach().numpy()
        )
        # Random init for new tokens (σ=0.02)
        if vocab_size > old_vocab_size:
            rng = np.random.default_rng(42)
            emb_np[old_vocab_size:] = rng.normal(
                0, 0.02, (vocab_size - old_vocab_size, hidden_size)
            ).astype(np.float32)
        self.embedding.weight = mx.array(emb_np)

        # Copy transformer layers
        for i in range(min(num_layers, len(pt_state) // 16)):
            prefix = f"encoder.layer.{i}"
            layer = self.layers[i]

            def _copy(src_key: str, dst_param_name: str) -> mx.array:
                return mx.array(pt_state[src_key].detach().numpy())

            # Attention
            layer.attention.query_proj.weight = _copy(
                f"{prefix}.attention.self.query.weight", "query_proj.weight"
            )
            layer.attention.query_proj.bias = _copy(
                f"{prefix}.attention.self.query.bias", "query_proj.bias"
            )
            layer.attention.key_proj.weight = _copy(
                f"{prefix}.attention.self.key.weight", "key_proj.weight"
            )
            layer.attention.key_proj.bias = _copy(
                f"{prefix}.attention.self.key.bias", "key_proj.bias"
            )
            layer.attention.value_proj.weight = _copy(
                f"{prefix}.attention.self.value.weight", "value_proj.weight"
            )
            layer.attention.value_proj.bias = _copy(
                f"{prefix}.attention.self.value.bias", "value_proj.bias"
            )
            layer.attention.out_proj.weight = _copy(
                f"{prefix}.attention.output.dense.weight", "out_proj.weight"
            )
            layer.attention.out_proj.bias = _copy(
                f"{prefix}.attention.output.dense.bias", "out_proj.bias"
            )

            # Layer norms
            layer.ln1.weight = _copy(
                f"{prefix}.attention.output.LayerNorm.weight", "ln1.weight"
            )
            layer.ln1.bias = _copy(
                f"{prefix}.attention.output.LayerNorm.bias", "ln1.bias"
            )
            layer.ln2.weight = _copy(
                f"{prefix}.output.LayerNorm.weight", "ln2.weight"
            )
            layer.ln2.bias = _copy(
                f"{prefix}.output.LayerNorm.bias", "ln2.bias"
            )

            # FFN
            layer.linear1.weight = _copy(
                f"{prefix}.intermediate.dense.weight", "linear1.weight"
            )
            layer.linear1.bias = _copy(
                f"{prefix}.intermediate.dense.bias", "linear1.bias"
            )
            layer.linear2.weight = _copy(
                f"{prefix}.output.dense.weight", "linear2.weight"
            )
            layer.linear2.bias = _copy(
                f"{prefix}.output.dense.bias", "linear2.bias"
            )
