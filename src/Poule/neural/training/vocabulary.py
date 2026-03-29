"""Closed-vocabulary construction for Coq/Rocq neural premise selection.

Builds a vocabulary JSON file mapping every Coq identifier, syntax token,
and Unicode symbol to a unique integer token ID. Replaces CodeBERT's generic
BPE tokenizer with O(1) dictionary lookup.

See specification/neural-training.md §4.0.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from Poule.neural.training.data import serialize_goals
from Poule.neural.training.errors import DataFormatError, InsufficientDataError


@dataclass
class VocabularyReport:
    """Results from vocabulary construction."""

    total_tokens: int
    special_tokens: int
    fixed_tokens: int
    index_tokens: int
    training_data_tokens: int
    output_path: Path


# ---------------------------------------------------------------------------
# Fixed token sets (spec §4.0)
# ---------------------------------------------------------------------------

SPECIAL_TOKENS = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]

PUNCTUATION = [
    "(", ")", "{", "}", "[", "]", ":", ";", ",", ".", "|",
    "@", "!", "?", "_", "'", "#", "=", "+", "-", "*", "/",
    "<", ">", "~",
]

SSREFLECT_TACTICALS = ["/=", "//", "//=", "=>", "->", "<-"]

SCOPE_DELIMITERS = ["%N", "%Z", "%R", "%Q", "%positive", "%type"]

UNICODE_MATH_SYMBOLS = [
    "∀", "∃", "→", "←", "↔", "⊢", "⊣", "≤", "≥", "≠", "≡",
    "∧", "∨", "¬", "⊆", "⊇", "∈", "∉", "⊂", "⊃", "∪", "∩",
    "∘", "×", "⊕", "⊗", "ℕ", "ℤ", "ℚ", "ℝ", "ℂ",
]

GREEK_LETTERS = [
    "α", "β", "γ", "δ", "ε", "ζ", "η", "θ", "ι", "κ", "λ", "μ",
    "ν", "ξ", "π", "ρ", "σ", "τ", "υ", "φ", "χ", "ψ", "ω",
    "Γ", "Δ", "Θ", "Λ", "Ξ", "Π", "Σ", "Φ", "Ψ", "Ω",
]

DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


def _nfc(s: str) -> str:
    """Apply NFC Unicode normalization."""
    return unicodedata.normalize("NFC", s)


class VocabularyBuilder:
    """Constructs a closed vocabulary from the search index and training data."""

    @staticmethod
    def build(
        index_db_path: Path,
        jsonl_paths: list[Path],
        output_path: Path,
    ) -> VocabularyReport:
        """Build a closed vocabulary and write it to a JSON file.

        Args:
            index_db_path: Path to the SQLite index database.
            jsonl_paths: Paths to JSON Lines extraction output files.
            output_path: Path where the vocabulary JSON will be written.

        Returns:
            VocabularyReport with token counts.

        Raises:
            FileNotFoundError: If index_db_path or any jsonl_path does not exist.
            InsufficientDataError: If the index has no declarations.
        """
        # Validate inputs exist
        if not Path(index_db_path).exists():
            raise FileNotFoundError(
                f"Index database not found: {index_db_path}"
            )
        for path in jsonl_paths:
            if not Path(path).exists():
                raise FileNotFoundError(
                    f"Training data file not found: {path}"
                )

        vocab: dict[str, int] = {}
        next_id = 0

        # Step 1: Special tokens at IDs 0–4
        for token in SPECIAL_TOKENS:
            vocab[token] = next_id
            next_id += 1
        special_count = len(SPECIAL_TOKENS)

        # Step 2: Fixed token sets
        fixed_sets = [
            PUNCTUATION,
            SSREFLECT_TACTICALS,
            SCOPE_DELIMITERS,
            UNICODE_MATH_SYMBOLS,
            GREEK_LETTERS,
            DIGITS,
        ]
        fixed_start = next_id
        for token_set in fixed_sets:
            for token in token_set:
                normalized = _nfc(token)
                if normalized not in vocab:
                    vocab[normalized] = next_id
                    next_id += 1
        fixed_count = next_id - fixed_start

        # Step 3: Declaration names from the index
        conn = sqlite3.connect(str(index_db_path))
        rows = conn.execute("SELECT name FROM declarations ORDER BY name").fetchall()
        conn.close()

        if not rows:
            raise InsufficientDataError(
                "No declarations found in index database"
            )

        index_start = next_id
        for (name,) in rows:
            normalized = _nfc(name)
            if normalized not in vocab:
                vocab[normalized] = next_id
                next_id += 1
        index_count = next_id - index_start

        # Step 4: Tokens from training data
        # Reads "s" field from both "p" (pair) and "g" (goal-state) records
        # in the compact training data format (spec §4.0.5).
        training_tokens: set[str] = set()
        for path in jsonl_paths:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Compact format: read "s" from "p" and "g" records
                    if record.get("t") in ("p", "g"):
                        state_text = record.get("s", "")
                        if state_text:
                            for token in state_text.split():
                                normalized = _nfc(token)
                                if normalized not in vocab:
                                    training_tokens.add(normalized)

        # Add training data tokens sorted lexicographically
        training_start = next_id
        for token in sorted(training_tokens):
            vocab[token] = next_id
            next_id += 1
        training_count = next_id - training_start

        # Step 5: Write the vocabulary JSON
        output_path = Path(output_path)
        output_path.write_text(
            json.dumps(vocab, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return VocabularyReport(
            total_tokens=len(vocab),
            special_tokens=special_count,
            fixed_tokens=fixed_count,
            index_tokens=index_count,
            training_data_tokens=training_count,
            output_path=output_path,
        )


# ---------------------------------------------------------------------------
# CoqTokenizer (spec §4.0.1)
# ---------------------------------------------------------------------------


class CoqTokenizer:
    """Lightweight tokenizer using a closed vocabulary JSON file.

    Performs whitespace splitting and O(1) dictionary lookup.
    Replaces AutoTokenizer.from_pretrained("microsoft/codebert-base").

    See specification/neural-training.md §4.0.1.
    """

    def __init__(self, vocabulary_path: Path):
        vocabulary_path = Path(vocabulary_path)
        if not vocabulary_path.exists():
            raise FileNotFoundError(
                f"Vocabulary file not found: {vocabulary_path}"
            )
        try:
            self._vocab: dict[str, int] = json.loads(
                vocabulary_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise DataFormatError(
                f"Invalid vocabulary file: {vocabulary_path}"
            ) from exc

        self.pad_token_id = self._vocab["[PAD]"]
        self.unk_token_id = self._vocab["[UNK]"]
        self.cls_token_id = self._vocab["[CLS]"]
        self.sep_token_id = self._vocab["[SEP]"]
        self.mask_token_id = self._vocab["[MASK]"]

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)

    def encode(
        self, text: str, max_length: int = 512
    ) -> tuple[list[int], list[int]]:
        """Tokenize text with whitespace split + vocabulary lookup.

        Returns (input_ids, attention_mask) as lists of integers.
        """
        text = _nfc(text)
        tokens = text.split() if text.strip() else []

        # Map tokens to IDs
        token_ids = [self._vocab.get(t, self.unk_token_id) for t in tokens]

        # Prepend CLS, append SEP
        token_ids = [self.cls_token_id] + token_ids + [self.sep_token_id]

        # Truncate if needed (keep CLS at start, replace last with SEP)
        if len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            token_ids[-1] = self.sep_token_id

        # Build attention mask (1 for real tokens)
        attention_mask = [1] * len(token_ids)

        # Pad to max_length
        pad_count = max_length - len(token_ids)
        if pad_count > 0:
            token_ids.extend([self.pad_token_id] * pad_count)
            attention_mask.extend([0] * pad_count)

        return token_ids, attention_mask

    def encode_batch(
        self, texts: list[str], max_length: int = 512
    ) -> dict:
        """Encode a batch of texts with dynamic padding.

        Returns a dict with 'input_ids' and 'attention_mask' as numpy arrays
        of shape (batch_size, padded_length). Callers convert to tensors as
        needed (torch is a training-only dependency).

        Padding is to the longest sequence in the batch, not max_length.
        """
        import numpy as np

        encoded = [self.encode(t, max_length) for t in texts]

        # Find max actual length (non-padding) for dynamic padding
        actual_lengths = [sum(mask) for _, mask in encoded]
        padded_length = max(actual_lengths)

        # Trim all sequences to padded_length
        input_ids = [ids[:padded_length] for ids, _ in encoded]
        attention_masks = [mask[:padded_length] for _, mask in encoded]

        return {
            "input_ids": np.array(input_ids, dtype=np.int64),
            "attention_mask": np.array(attention_masks, dtype=np.int64),
        }
