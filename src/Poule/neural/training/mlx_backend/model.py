"""MLX tactic classifier model for neural tactic prediction training.

Architecturally identical to the PyTorch TacticClassifier: CodeBERT encoder
with mean pooling and a linear classification head, producing logits over
a fixed set of tactic families.

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


class MLXTacticClassifier(nn.Module):
    """CodeBERT encoder with category head + per-category within-category heads.

    Architecture: CodeBERT -> mean pooling -> category_head [B, num_categories]
                                           -> within_heads[cat] [B, cat_size]
    Also supports flat classification (backward compat) when per_category_sizes is None.
    """

    def __init__(
        self,
        vocab_size: int,
        num_classes: int = 1,
        num_layers: int = 6,
        hidden_size: int = 768,
        num_heads: int = 12,
        max_seq_length: int = 514,
        embedding_dim: int = 128,
        per_category_sizes: dict[str, int] | None = None,
        num_categories: int = 0,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_classes = num_classes
        self._is_hierarchical = per_category_sizes is not None
        self.per_category_sizes = per_category_sizes or {}
        self.num_categories = num_categories
        self.embedding = nn.Embedding(vocab_size, embedding_dim)
        self.position_embedding = nn.Embedding(max_seq_length, hidden_size)
        if embedding_dim < hidden_size:
            self.embedding_projection = nn.Linear(
                embedding_dim, hidden_size, bias=False,
            )
        else:
            self.embedding_projection = None
        self.layers = [
            TransformerEncoderLayer(hidden_size, num_heads)
            for _ in range(num_layers)
        ]
        self.embedding_ln = nn.LayerNorm(hidden_size)

        if self._is_hierarchical:
            self.category_head = nn.Linear(hidden_size, num_categories)
            self.within_heads = {
                cat: nn.Linear(hidden_size, size)
                for cat, size in per_category_sizes.items()
            }
            self.classifier = None
        else:
            self.classifier = nn.Linear(hidden_size, num_classes)
            self.category_head = None
            self.within_heads = None

    def _encode(self, input_ids: mx.array, attention_mask: mx.array) -> mx.array:
        """Shared encoder: produce pooled representation [B, hidden_size]."""
        seq_len = input_ids.shape[1]
        positions = mx.arange(seq_len)

        word_embs = self.embedding(input_ids)
        if self.embedding_projection is not None:
            word_embs = self.embedding_projection(word_embs)
        x = word_embs + self.position_embedding(positions)
        x = self.embedding_ln(x)

        if attention_mask is not None:
            attn_mask = mx.where(
                attention_mask[:, None, None, :].astype(mx.bool_),
                mx.array(0.0),
                mx.array(-1e9),
            )
        else:
            attn_mask = None

        for layer in self.layers:
            x = layer(x, mask=attn_mask)

        mask_expanded = attention_mask[:, :, None].astype(mx.float32)
        summed = (x * mask_expanded).sum(axis=1)
        counts = mx.maximum(mask_expanded.sum(axis=1), mx.array(1e-9))
        return summed / counts

    def __call__(self, input_ids: mx.array, attention_mask: mx.array):
        """Classify proof states.

        Returns:
            If hierarchical: (category_logits, dict[cat -> within_logits])
            If flat: [B, num_classes] logits
        """
        pooled = self._encode(input_ids, attention_mask)

        if self._is_hierarchical:
            category_logits = self.category_head(pooled)
            within_logits = {
                cat: head(pooled)
                for cat, head in self.within_heads.items()
            }
            return category_logits, within_logits
        else:
            return self.classifier(pooled)

    def load_codebert_weights(
        self, pytorch_model_name: str = "microsoft/codebert-base"
    ) -> None:
        """Load CodeBERT weights from HuggingFace, converting to MLX arrays.

        Converts torch.Tensor -> numpy -> mx.array and maps parameter names
        from HuggingFace convention to MLX convention. Classification heads
        (category_head, within_heads, or classifier) are left with random init.
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

        # Copy word embeddings (overlap, truncated to embedding_dim)
        old_emb = pt_state["embeddings.word_embeddings.weight"].detach().numpy()
        old_vocab_size = old_emb.shape[0]
        embedding_dim = self.embedding.weight.shape[1]
        overlap = min(vocab_size, old_vocab_size)
        copy_dim = min(embedding_dim, old_emb.shape[1])
        emb_np = np.array(self.embedding.weight)
        emb_np[:overlap, :copy_dim] = old_emb[:overlap, :copy_dim]
        # Random init for new tokens (sigma=0.02)
        if vocab_size > old_vocab_size:
            rng = np.random.default_rng(42)
            emb_np[old_vocab_size:] = rng.normal(
                0, 0.02, (vocab_size - old_vocab_size, embedding_dim)
            ).astype(np.float32)
        self.embedding.weight = mx.array(emb_np)

        # Initialize embedding projection from truncated SVD of CodeBERT embeddings
        if self.embedding_projection is not None:
            full_emb = old_emb[:old_vocab_size].astype(np.float32)
            _, _, Vt = np.linalg.svd(full_emb, full_matrices=False)
            # Projection maps D -> H: use top-D right singular vectors
            proj_weight = Vt[:embedding_dim].T  # [H, D]
            self.embedding_projection.weight = mx.array(
                proj_weight.astype(np.float32)
            )

        # Copy transformer layers (with layer dropping)
        from Poule.neural.training.model import _layer_indices
        source_indices = _layer_indices(num_layers)
        for dst_i, src_i in enumerate(source_indices):
            prefix = f"encoder.layer.{src_i}"
            layer = self.layers[dst_i]

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

        # Free PyTorch model and state dict to reclaim ~500 MB.
        # MLX lazy eval may hold numpy intermediates; explicit del + gc
        # ensures the PyTorch graph is released before training begins.
        del pt_state, pt_model, old_emb
        import gc; gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass


