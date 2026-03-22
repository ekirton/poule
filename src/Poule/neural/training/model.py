"""Bi-encoder model for neural premise selection training.

Shared-weight encoder wrapping CodeBERT with mean pooling and
L2 normalization, producing 768-dim embeddings. The same encoder
is used for both proof states and premises.

Requires: torch, transformers (training-only dependencies).
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel


class BiEncoder(nn.Module):
    """Shared-weight bi-encoder with mean pooling and L2 normalization.

    Architecture: CodeBERT -> mean pooling -> L2 normalize -> 768-dim.
    """

    def __init__(self, model_name: str = "microsoft/codebert-base"):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(model_name)

    @property
    def embedding_dim(self) -> int:
        return self.encoder.config.hidden_size

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        """Encode text to L2-normalized embedding vectors.

        Args:
            input_ids: [B, seq_len] token IDs.
            attention_mask: [B, seq_len] attention mask.

        Returns:
            [B, 768] L2-normalized embeddings.
        """
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        token_embs = outputs.last_hidden_state  # [B, seq_len, dim]

        # Mean pooling over non-padding tokens
        mask = attention_mask.unsqueeze(-1).float()
        summed = (token_embs * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        pooled = summed / counts  # [B, dim]

        return F.normalize(pooled, p=2, dim=1)
