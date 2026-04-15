"""Vocabulary construction for Coq/Rocq neural tactic prediction.

Provides both the legacy closed-vocabulary builder (VocabularyBuilder) and
the new BPE vocabulary builder (BpeVocabularyBuilder) using SentencePiece.

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
    bpe_tokens: int = 0


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
        # Reads "s" field from both "s" (step) and "g" (goal-state) records
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

                    # Compact format: read "s" from "s" and "g" records
                    if record.get("t") in ("s", "g"):
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
# BPE vocabulary builder (spec §4.0)
# ---------------------------------------------------------------------------

# Structural markers and context tokens for the BPE vocabulary
STRUCTURAL_TOKENS = [
    "[HYP]", "[TYPE]", "[BODY]", "[GOAL]", "[GOALSEP]",
]

# Context prefix tokens — these are added as user_defined_symbols
# to SentencePiece so they are always single tokens.
_CONTEXT_PREV_TOKENS = [
    f"[PREV={t}]" for t in [
        "none", "intros", "apply", "rewrite", "simpl", "unfold", "destruct",
        "induction", "auto", "exact", "reflexivity", "symmetry", "split",
        "left", "right", "exists", "constructor", "discriminate", "injection",
        "inversion", "subst", "clear", "rename", "assert", "pose", "set",
        "specialize", "generalize", "change", "replace", "lia", "omega",
        "ring", "field", "tauto", "intuition", "eauto", "trivial",
        "assumption", "contradiction", "exfalso", "f_equal", "congruence",
        "case", "elim", "move", "have", "suff", "congr", "rewrite!",
        "ssromega", "done", "by", "other",
    ]
]

_CONTEXT_DEPTH_TOKENS = [f"[DEPTH={i}]" for i in range(11)] + ["[DEPTH=10+]"]
_CONTEXT_NGOALS_TOKENS = [f"[NGOALS={i}]" for i in range(1, 6)] + ["[NGOALS=5+]"]

# Import HEAD_CONSTRUCTORS from data module
from Poule.neural.training.data import HEAD_CONSTRUCTORS  # noqa: E402

_CONTEXT_HEAD_TOKENS = [f"[HEAD={h}]" for h in sorted(HEAD_CONSTRUCTORS)]

# User-defined symbols for SentencePiece (excludes PAD/UNK/CLS/SEP
# which are configured via dedicated SentencePiece parameters)
_USER_DEFINED_SYMBOLS = (
    ["[MASK]"]
    + STRUCTURAL_TOKENS
    + _CONTEXT_PREV_TOKENS
    + _CONTEXT_DEPTH_TOKENS
    + _CONTEXT_NGOALS_TOKENS
    + _CONTEXT_HEAD_TOKENS
)


class BpeVocabularyBuilder:
    """Trains a SentencePiece BPE vocabulary from extracted Coq proof data.

    See specification/neural-training.md §4.0.
    """

    @staticmethod
    def build(
        jsonl_paths: list[Path],
        output_dir: Path,
        vocab_size: int = 16000,
    ) -> VocabularyReport:
        """Train a BPE vocabulary and write the SentencePiece model.

        Args:
            jsonl_paths: Paths to JSONL training data files.
            output_dir: Directory where tokenizer.model will be written.
            vocab_size: Target vocabulary size (default 16000).

        Returns:
            VocabularyReport with token counts.

        Raises:
            InsufficientDataError: If no training text is extracted.
        """
        import tempfile

        try:
            import sentencepiece as spm
        except ImportError as exc:
            raise ImportError(
                "sentencepiece is required for BPE vocabulary building. "
                "Install with: pip install sentencepiece"
            ) from exc

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Extract all proof state text from JSONL files
        texts: list[str] = []
        for path in jsonl_paths:
            if not Path(path).exists():
                raise FileNotFoundError(f"Training data file not found: {path}")
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("t") in ("s", "g"):
                        state_text = record.get("s", "")
                        if state_text:
                            texts.append(state_text)

        if not texts:
            raise InsufficientDataError(
                "No training text found in JSONL files"
            )

        # Write texts to a temporary file for SentencePiece training
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as tmp:
            for text in texts:
                tmp.write(text + "\n")
            tmp_path = tmp.name

        try:
            # Train SentencePiece BPE model
            model_prefix = str(output_dir / "tokenizer")
            spm.SentencePieceTrainer.train(
                input=tmp_path,
                model_prefix=model_prefix,
                vocab_size=vocab_size,
                model_type="bpe",
                user_defined_symbols=_USER_DEFINED_SYMBOLS,
                pad_id=0,
                unk_id=1,
                bos_id=2,  # [CLS]
                eos_id=3,  # [SEP]
                pad_piece="[PAD]",
                unk_piece="[UNK]",
                bos_piece="[CLS]",
                eos_piece="[SEP]",
                character_coverage=1.0,
                normalization_rule_name="identity",
            )
        finally:
            import os
            os.unlink(tmp_path)

        # Load trained model to get actual vocab size
        sp = spm.SentencePieceProcessor()
        sp.load(str(output_dir / "tokenizer.model"))
        actual_vocab_size = sp.get_piece_size()

        return VocabularyReport(
            total_tokens=actual_vocab_size,
            special_tokens=len(SPECIAL_TOKENS),
            fixed_tokens=len(STRUCTURAL_TOKENS),
            index_tokens=0,
            training_data_tokens=actual_vocab_size - len(SPECIAL_TOKENS) - len(STRUCTURAL_TOKENS),
            output_path=output_dir,
            bpe_tokens=actual_vocab_size,
        )


# ---------------------------------------------------------------------------
# CoqTokenizer (spec §4.0.1)
# ---------------------------------------------------------------------------


class CoqTokenizer:
    """BPE tokenizer for Coq proof states, wrapping a trained SentencePiece model.

    See specification/neural-training.md §4.0.1.
    """

    def __init__(self, vocabulary_dir: Path):
        """Initialize tokenizer from a vocabulary directory containing tokenizer.model.

        Args:
            vocabulary_dir: Path to a directory containing tokenizer.model.
        """
        vocabulary_dir = Path(vocabulary_dir)
        if not vocabulary_dir.exists():
            raise FileNotFoundError(
                f"Vocabulary directory not found: {vocabulary_dir}"
            )

        model_path = vocabulary_dir / "tokenizer.model"
        if not model_path.exists():
            raise FileNotFoundError(
                f"SentencePiece model not found: {model_path}"
            )
        try:
            import sentencepiece as spm
        except ImportError as exc:
            raise ImportError(
                "sentencepiece is required for BPE tokenization. "
                "Install with: pip install sentencepiece"
            ) from exc
        self._sp = spm.SentencePieceProcessor()
        self._sp.load(str(model_path))

        self.pad_token_id = self._sp.pad_id()
        self.unk_token_id = self._sp.unk_id()
        self.cls_token_id = self._sp.bos_id()  # [CLS]
        self.sep_token_id = self._sp.eos_id()  # [SEP]
        mask_id = self._sp.piece_to_id("[MASK]")
        self.mask_token_id = mask_id if mask_id >= 0 else self.unk_token_id

    @property
    def vocab_size(self) -> int:
        return self._sp.get_piece_size()

    def encode(
        self, text: str, max_length: int = 512
    ) -> tuple[list[int], list[int]]:
        """Tokenize text with BPE and return (input_ids, attention_mask)."""
        token_ids = self._sp.encode(text, out_type=int)

        # Prepend CLS, append SEP
        token_ids = [self.cls_token_id] + token_ids + [self.sep_token_id]

        # Truncate
        if len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            token_ids[-1] = self.sep_token_id

        attention_mask = [1] * len(token_ids)

        # Pad
        pad_count = max_length - len(token_ids)
        if pad_count > 0:
            token_ids.extend([self.pad_token_id] * pad_count)
            attention_mask.extend([0] * pad_count)

        return token_ids, attention_mask

    def encode_batch(
        self, texts: list[str], max_length: int = 512
    ) -> tuple:
        """Encode a batch of texts with padding.

        Returns (input_ids, attention_mask) as numpy arrays of shape
        (batch_size, max_length).
        """
        import numpy as np

        encoded = [self.encode(t, max_length) for t in texts]

        input_ids = np.array([ids for ids, _ in encoded], dtype=np.int64)
        attention_masks = np.array([mask for _, mask in encoded], dtype=np.int64)

        return input_ids, attention_masks
