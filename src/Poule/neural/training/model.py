"""Hierarchical tactic family classifier for neural tactic prediction.

CodeBERT encoder with mean pooling, a category classification head,
and per-category within-category heads. Produces category logits and
per-category within-category logits.

Requires: torch, transformers (training-only dependencies).
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn
from transformers import AutoModel


def _layer_indices(num_hidden_layers: int) -> list[int]:
    """Compute evenly spaced layer indices for layer dropping.

    Selects ``num_hidden_layers`` layers from a 12-layer source at
    evenly spaced positions: ``[i * 12 // num_hidden_layers for i ...]``.
    """
    return [i * 12 // num_hidden_layers for i in range(num_hidden_layers)]


class HierarchicalTacticClassifier(nn.Module):
    """CodeBERT encoder with category head + per-category within-category heads.

    Architecture:
        CodeBERT -> mean pooling -> category_head [B, num_categories]
                                 -> within_heads[cat] [B, num_tactics_in_cat]
    """

    def __init__(
        self,
        model_name: str = "microsoft/codebert-base",
        per_category_sizes: dict[str, int] | None = None,
        num_categories: int = 8,
        vocab_size: int | None = None,
        num_hidden_layers: int = 6,
        # Backward compat: if num_classes is provided, create a flat classifier
        num_classes: int | None = None,
    ):
        super().__init__()
        self.num_categories = num_categories
        self.per_category_sizes = per_category_sizes or {}
        self._is_hierarchical = per_category_sizes is not None

        encoder = AutoModel.from_pretrained(model_name)

        # Layer dropping: select a subset of transformer layers
        if num_hidden_layers < 12:
            indices = _layer_indices(num_hidden_layers)
            new_layers = torch.nn.ModuleList(
                [encoder.encoder.layer[i] for i in indices]
            )
            encoder.encoder.layer = new_layers
            encoder.config.num_hidden_layers = num_hidden_layers

        self.encoder = encoder
        hidden_size = self.encoder.config.hidden_size

        # Replace embedding layer if a custom vocab size is provided
        # Full-rank (768-d) — no factorization with BPE vocabulary
        if vocab_size is not None:
            old_embeddings = self.encoder.embeddings.word_embeddings
            new_embeddings = nn.Embedding(vocab_size, hidden_size)
            nn.init.normal_(new_embeddings.weight, mean=0.0, std=0.02)
            overlap = min(vocab_size, old_embeddings.num_embeddings)
            with torch.no_grad():
                new_embeddings.weight[:overlap, :] = (
                    old_embeddings.weight[:overlap, :]
                )
            self.encoder.embeddings.word_embeddings = new_embeddings
            del old_embeddings
            import gc; gc.collect()

        self.embedding_projection = None

        # Hierarchical heads
        if self._is_hierarchical:
            self.category_head = nn.Linear(hidden_size, num_categories)
            self.within_heads = nn.ModuleDict({
                cat: nn.Linear(hidden_size, size)
                for cat, size in per_category_sizes.items()
            })
            # For backward compat
            self.num_classes = sum(per_category_sizes.values())
            self.classifier = None
        else:
            # Flat classifier (backward compat)
            nc = num_classes if num_classes is not None else 1
            self.num_classes = nc
            self.classifier = nn.Linear(hidden_size, nc)
            self.category_head = None
            self.within_heads = None

    @classmethod
    def from_checkpoint(cls, checkpoint: dict) -> "HierarchicalTacticClassifier":
        """Instantiate from a checkpoint dict.

        Detects hierarchical vs flat format and reconstructs accordingly.
        """
        from transformers import RobertaConfig, RobertaModel

        state_dict = checkpoint["model_state_dict"]
        num_hidden_layers = checkpoint.get("num_hidden_layers", 6)
        per_category_sizes = checkpoint.get("per_category_sizes")

        emb_key = "encoder.embeddings.word_embeddings.weight"
        vocab_size = state_dict[emb_key].shape[0] if emb_key in state_dict else None

        hidden_size = 768
        config = RobertaConfig(
            vocab_size=vocab_size or 50265,
            hidden_size=hidden_size,
            num_hidden_layers=num_hidden_layers,
            num_attention_heads=12,
            intermediate_size=3072,
            max_position_embeddings=514,
            type_vocab_size=1,
            pad_token_id=1,
            bos_token_id=0,
            eos_token_id=2,
        )
        model = cls.__new__(cls)
        nn.Module.__init__(model)
        model.encoder = RobertaModel(config)
        model.embedding_projection = None

        if per_category_sizes is not None:
            # Hierarchical model
            model._is_hierarchical = True
            model.per_category_sizes = per_category_sizes
            num_categories = checkpoint.get("num_categories", len(per_category_sizes))
            model.num_categories = num_categories
            model.category_head = nn.Linear(hidden_size, num_categories)
            model.within_heads = nn.ModuleDict({
                cat: nn.Linear(hidden_size, size)
                for cat, size in per_category_sizes.items()
            })
            model.num_classes = sum(per_category_sizes.values())
            model.classifier = None
        else:
            # Flat model (backward compat)
            model._is_hierarchical = False
            model.per_category_sizes = {}
            num_classes = checkpoint.get("num_classes", 1)
            model.num_classes = num_classes
            model.num_categories = 0
            model.classifier = nn.Linear(hidden_size, num_classes)
            model.category_head = None
            model.within_heads = None

        model.load_state_dict(state_dict, strict=False)
        return model

    @property
    def label_map(self) -> dict[str, int] | None:
        return getattr(self, "_label_map", None)

    @label_map.setter
    def label_map(self, mapping: dict[str, int]) -> None:
        self._label_map = mapping

    def _encode(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Shared encoder: produce pooled representation [B, hidden_size]."""
        outputs = self.encoder(
            input_ids=input_ids, attention_mask=attention_mask,
        )
        token_embs = outputs.last_hidden_state

        # Mean pooling over non-padding tokens
        mask = attention_mask.unsqueeze(-1).float()
        summed = (token_embs * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        return summed / counts

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor,
    ) -> torch.Tensor | tuple[torch.Tensor, dict[str, torch.Tensor]]:
        """Classify proof states.

        Returns:
            If hierarchical: (category_logits [B, num_categories],
                              dict[cat_name -> within_logits [B, cat_size]])
            If flat: [B, num_classes] logits (backward compat)
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

    def save_checkpoint(
        self,
        path: str,
        label_map: dict[str, int],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Save model weights and metadata to a checkpoint file."""
        checkpoint: dict[str, Any] = {
            "model_state_dict": self.state_dict(),
            "num_classes": self.num_classes,
            "num_hidden_layers": self.encoder.config.num_hidden_layers,
            "label_map": label_map,
        }
        if self._is_hierarchical:
            checkpoint["per_category_sizes"] = dict(self.per_category_sizes)
            checkpoint["num_categories"] = self.num_categories
        if extra:
            checkpoint.update(extra)
        torch.save(checkpoint, path)


# Backward compat alias
TacticClassifier = HierarchicalTacticClassifier
