"""Education encoder wrapping an all-MiniLM-L6-v2 INT8 ONNX model."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

from Poule.neural.errors import ModelNotFoundError, ModelLoadError

logger = logging.getLogger(__name__)


class EducationEncoder:
    """Encodes text into L2-normalized 384-dim embedding vectors via ONNX Runtime."""

    def __init__(self, session, tokenizer, file_hash: str):
        self._session = session
        self._tokenizer = tokenizer
        self._file_hash = file_hash

    @classmethod
    def load(cls, model_path: Path, tokenizer_path: Path) -> EducationEncoder:
        model_path = Path(model_path)
        tokenizer_path = Path(tokenizer_path)

        if not model_path.exists():
            raise ModelNotFoundError(f"Model not found: {model_path}")
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer not found: {tokenizer_path}")

        try:
            from tokenizers import Tokenizer
        except ImportError as e:
            raise ModelLoadError(f"Required dependency not installed: {e}") from e

        try:
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as e:
            raise ModelLoadError(f"Failed to load tokenizer: {e}") from e

        try:
            import onnxruntime as ort
        except ImportError as e:
            raise ModelLoadError(f"Required dependency not installed: {e}") from e

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
        encoding = self._tokenizer.encode(text)
        input_ids = encoding.ids[:256]
        attention_mask = encoding.attention_mask[:256]
        seq_len = len(input_ids)

        input_ids_np = np.array([input_ids], dtype=np.int64)
        attention_mask_np = np.array([attention_mask], dtype=np.int64)

        # Build feed dict from the model's required inputs (some models
        # require token_type_ids, others do not).
        feed = {"input_ids": input_ids_np, "attention_mask": attention_mask_np}
        required = {inp.name for inp in self._session.get_inputs()}
        if "token_type_ids" in required:
            feed["token_type_ids"] = np.zeros((1, seq_len), dtype=np.int64)

        outputs = self._session.run(None, feed)

        # Mean pooling over token embeddings
        token_embeddings = outputs[0]  # [1, seq_len, dim]
        mask_expanded = np.expand_dims(attention_mask_np, axis=-1).astype(np.float32)
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
