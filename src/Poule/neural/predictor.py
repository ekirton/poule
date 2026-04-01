"""Inference for the quantized tactic prediction model.

Loads an INT8-quantized ONNX tactic classifier and predicts tactic families
from Coq proof state text.

See specification/neural-training.md §8.1.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Expected model file paths -- checked in order of preference.
_MODEL_DIRS = [
    Path.home() / ".local" / "share" / "poule" / "models",
    Path("/data"),
]

_MODEL_FILENAME = "tactic-predictor.onnx"
_LABELS_FILENAME = "tactic-labels.json"
_VOCABULARY_FILENAME = "coq-vocabulary.json"


def _find_file(filename: str) -> Path | None:
    """Search candidate directories for a model file."""
    for d in _MODEL_DIRS:
        p = d / filename
        if p.exists():
            return p
    return None


class TacticPredictor:
    """Loads a quantized ONNX tactic classifier and predicts tactic families."""

    def __init__(
        self,
        model_path: Path | str,
        labels_path: Path | str,
        vocabulary_path: Path | str,
    ) -> None:
        import onnxruntime as ort

        from Poule.neural.training.vocabulary import CoqTokenizer

        model_path = Path(model_path)
        labels_path = Path(labels_path)
        vocabulary_path = Path(vocabulary_path)

        for p, desc in [
            (model_path, "ONNX model"),
            (labels_path, "labels"),
            (vocabulary_path, "vocabulary"),
        ]:
            if not p.exists():
                raise FileNotFoundError(f"{desc} file not found: {p}")

        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._labels: list[str] = json.loads(
            labels_path.read_text(encoding="utf-8")
        )
        self._tokenizer = CoqTokenizer(vocabulary_path)

    def predict(
        self, proof_state_text: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Predict tactic families from proof state text.

        Returns a list of (family_name, confidence) tuples sorted by
        confidence descending, length = min(top_k, num_classes).
        """
        import numpy as np

        input_ids, attention_mask = self._tokenizer.encode(
            proof_state_text, max_length=512
        )

        # ONNX expects [batch, seq_len] int64 arrays
        ids_arr = np.array([input_ids], dtype=np.int64)
        mask_arr = np.array([attention_mask], dtype=np.int64)

        logits = self._session.run(
            None,
            {"input_ids": ids_arr, "attention_mask": mask_arr},
        )[0]  # shape [1, num_classes]

        # Softmax
        logits = logits[0]
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Top-K
        k = min(top_k, len(self._labels))
        top_indices = np.argsort(probs)[::-1][:k]

        return [
            (self._labels[int(i)], float(probs[i]))
            for i in top_indices
        ]

    @staticmethod
    def is_available() -> bool:
        """Check if all required model files exist at expected paths."""
        return all(
            _find_file(f) is not None
            for f in (_MODEL_FILENAME, _LABELS_FILENAME, _VOCABULARY_FILENAME)
        )

    @classmethod
    def load_default(cls) -> TacticPredictor:
        """Load predictor from default file locations.

        Raises FileNotFoundError if any required file is missing.
        """
        model_path = _find_file(_MODEL_FILENAME)
        labels_path = _find_file(_LABELS_FILENAME)
        vocabulary_path = _find_file(_VOCABULARY_FILENAME)

        missing = []
        if model_path is None:
            missing.append(_MODEL_FILENAME)
        if labels_path is None:
            missing.append(_LABELS_FILENAME)
        if vocabulary_path is None:
            missing.append(_VOCABULARY_FILENAME)
        if missing:
            raise FileNotFoundError(
                f"Missing model files: {', '.join(missing)}"
            )

        return cls(model_path, labels_path, vocabulary_path)
