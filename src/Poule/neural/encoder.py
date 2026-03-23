"""Neural encoder interface wrapping an INT8-quantized ONNX model."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

from Poule.neural.errors import ModelNotFoundError, ModelLoadError

logger = logging.getLogger(__name__)


def _tokenize_for_onnx(tokenizer, text: str, max_length: int = 512) -> dict:
    """Tokenize text for ONNX inference, handling both CoqTokenizer and HuggingFace."""
    from Poule.neural.training.vocabulary import CoqTokenizer

    if isinstance(tokenizer, CoqTokenizer):
        ids, mask = tokenizer.encode(text, max_length=max_length)
        return {
            "input_ids": np.array([ids], dtype=np.int64),
            "attention_mask": np.array([mask], dtype=np.int64),
        }
    else:
        return tokenizer(
            text,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=max_length,
        )


class NeuralEncoder:
    """Encodes text into L2-normalized 768-dim embedding vectors via ONNX Runtime."""

    def __init__(self, session, tokenizer, file_hash: str):
        self._session = session
        self._tokenizer = tokenizer
        self._file_hash = file_hash

    @classmethod
    def load(
        cls, model_path: Path, vocabulary_path: Path | None = None
    ) -> NeuralEncoder:
        model_path = Path(model_path)
        if not model_path.exists():
            raise ModelNotFoundError(f"Model not found: {model_path}")

        # Load tokenizer: CoqTokenizer if vocabulary provided, else CodeBERT
        if vocabulary_path is not None:
            vocabulary_path = Path(vocabulary_path)
            if not vocabulary_path.exists():
                raise FileNotFoundError(
                    f"Vocabulary file not found: {vocabulary_path}"
                )
            from Poule.neural.training.vocabulary import CoqTokenizer

            tokenizer = CoqTokenizer(vocabulary_path)
        else:
            try:
                from transformers import AutoTokenizer
            except ImportError as e:
                raise ModelLoadError(
                    f"Required dependency not installed: {e}"
                ) from e
            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    "microsoft/codebert-base"
                )
            except Exception as e:
                raise ModelLoadError(
                    f"Failed to load tokenizer: {e}"
                ) from e

        try:
            import onnxruntime as ort
        except ImportError as e:
            raise ModelLoadError(
                f"Required dependency not installed: {e}"
            ) from e

        file_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()

        try:
            session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as e:
            raise ModelLoadError(f"Failed to load ONNX model: {e}") from e

        return cls(session, tokenizer, file_hash)

    def encode(self, text: str) -> np.ndarray:
        inputs = _tokenize_for_onnx(self._tokenizer, text)
        outputs = self._session.run(None, dict(inputs))
        # Mean pooling over token embeddings
        token_embeddings = outputs[0]  # [1, seq_len, dim]
        attention_mask = inputs["attention_mask"]
        mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        embedding = (summed / counts).squeeze(0).astype(np.float32)
        # L2 normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def encode_batch(self, texts: list[str]) -> list[np.ndarray]:
        return [self.encode(t) for t in texts]

    def model_hash(self) -> str:
        return self._file_hash
