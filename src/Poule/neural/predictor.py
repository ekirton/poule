"""Inference for the quantized tactic prediction model.

Loads an INT8-quantized ONNX tactic classifier and predicts tactic families
from Coq proof state text. Supports both hierarchical (product-rule) and
flat (legacy) label formats.

See specification/neural-training.md §8.1.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Model files are found via get_data_dir() which respects POULE_DATA_DIR.
from Poule.paths import get_data_dir

_MODEL_FILENAME = "tactic-predictor.onnx"
_LABELS_FILENAME = "tactic-labels.json"
_TOKENIZER_FILENAME = "tokenizer.model"


def _find_file(filename: str) -> Path | None:
    """Search the data directory for a model file."""
    p = get_data_dir() / filename
    if p.exists():
        return p
    return None


class TacticPredictor:
    """Loads a quantized ONNX tactic classifier and predicts tactic families."""

    def __init__(
        self,
        model_path: Path | str,
        labels_path: Path | str,
        vocabulary_dir: Path | str,
    ) -> None:
        import onnxruntime as ort

        from Poule.neural.training.vocabulary import CoqTokenizer

        model_path = Path(model_path)
        labels_path = Path(labels_path)
        vocabulary_dir = Path(vocabulary_dir)

        for p, desc in [
            (model_path, "ONNX model"),
            (labels_path, "labels"),
            (vocabulary_dir, "vocabulary directory"),
        ]:
            if not p.exists():
                raise FileNotFoundError(f"{desc} not found: {p}")

        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

        labels_data = json.loads(labels_path.read_text(encoding="utf-8"))

        # Detect hierarchical vs flat label format
        if isinstance(labels_data, dict) and "categories" in labels_data:
            self._is_hierarchical = True
            self._categories = labels_data["categories"]
            self._per_category = labels_data["per_category"]
            # Build flat label list in order matching ONNX output
            self._labels = []
            self._label_categories = []
            for cat in self._categories:
                tactics = self._per_category.get(cat, [])
                for tac in tactics:
                    self._labels.append(tac)
                    self._label_categories.append(cat)
        else:
            self._is_hierarchical = False
            self._labels = labels_data
            self._categories = []
            self._per_category = {}
            self._label_categories = []

        self._tokenizer = CoqTokenizer(vocabulary_dir)

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

        ids_arr = np.array([input_ids], dtype=np.int64)
        mask_arr = np.array([attention_mask], dtype=np.int64)

        logits = self._session.run(
            None,
            {"input_ids": ids_arr, "attention_mask": mask_arr},
        )[0]  # shape [1, total_tactics]

        # Softmax (the ONNX model already applies product rule for hierarchical)
        logits = logits[0]
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Top-K
        k = min(top_k, len(self._labels))
        top_indices = np.argsort(probs)[::-1][:k]

        results = []
        for i in top_indices:
            name = self._labels[int(i)]
            confidence = float(probs[i])
            results.append((name, confidence))

        return results

    def predict_with_category(
        self, proof_state_text: str, top_k: int = 5,
    ) -> list[tuple[str, str, float]]:
        """Predict tactic families with category metadata.

        Returns a list of (family_name, category_name, confidence) tuples.
        Only available for hierarchical models; falls back to ("", ) for flat.
        """
        import numpy as np

        input_ids, attention_mask = self._tokenizer.encode(
            proof_state_text, max_length=512
        )
        ids_arr = np.array([input_ids], dtype=np.int64)
        mask_arr = np.array([attention_mask], dtype=np.int64)

        logits = self._session.run(
            None,
            {"input_ids": ids_arr, "attention_mask": mask_arr},
        )[0][0]

        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        k = min(top_k, len(self._labels))
        top_indices = np.argsort(probs)[::-1][:k]

        results = []
        for i in top_indices:
            idx = int(i)
            name = self._labels[idx]
            cat = self._label_categories[idx] if self._label_categories else ""
            confidence = float(probs[idx])
            results.append((name, cat, confidence))

        return results

    @staticmethod
    def is_available() -> bool:
        """Check if all required model files exist at expected paths."""
        return all(
            _find_file(f) is not None
            for f in (_MODEL_FILENAME, _LABELS_FILENAME, _TOKENIZER_FILENAME)
        )

    @classmethod
    def load_default(cls) -> TacticPredictor:
        """Load predictor from default file locations.

        Raises FileNotFoundError if any required file is missing.
        """
        model_path = _find_file(_MODEL_FILENAME)
        labels_path = _find_file(_LABELS_FILENAME)
        tokenizer_path = _find_file(_TOKENIZER_FILENAME)

        missing = []
        if model_path is None:
            missing.append(_MODEL_FILENAME)
        if labels_path is None:
            missing.append(_LABELS_FILENAME)
        if tokenizer_path is None:
            missing.append(_TOKENIZER_FILENAME)
        if missing:
            raise FileNotFoundError(
                f"Missing model files: {', '.join(missing)}"
            )

        # CoqTokenizer expects the directory containing tokenizer.model
        vocabulary_dir = tokenizer_path.parent
        return cls(model_path, labels_path, vocabulary_dir)
