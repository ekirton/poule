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
from Poule.neural.training.errors import InsufficientDataError


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

                    # Skip non-proof records
                    if record.get("record_type") not in ("proof_trace", None):
                        continue

                    steps = record.get("steps", [])
                    for step in steps:
                        goals = step.get("goals", [])
                        if goals:
                            state_text = serialize_goals(goals)
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
