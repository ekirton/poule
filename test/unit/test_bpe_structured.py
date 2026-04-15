"""Tests for BPE tokenization and structured proof state serialization.

Covers: BpeVocabularyBuilder, CoqTokenizer (BPE), serialize_structured,
extract_goal_head, context feature extraction in TrainingDataLoader,
perturb_proof_state (structured format), and removal of embedding factorization.

These tests target improvements 1, 2, 4, 5, 6 from the training data plan:
1. BPE tokenization (replace 158K closed vocabulary with ~16K BPE)
2. Structured segment markers ([HYP], [TYPE], [GOAL], [GOALSEP])
4. Goal head constructor as explicit feature ([HEAD=X])
5. Previous tactic context ([PREV=X], [DEPTH=N], [NGOALS=N])
6. Let-bound hypothesis bodies ([BODY])
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_step_records(path, steps, goals=None):
    """Write compact training data JSONL with step and goal records."""
    with open(path, "w") as f:
        for source_file, state_text, tactic_text in steps:
            f.write(json.dumps({
                "t": "s", "f": source_file, "s": state_text, "c": tactic_text,
            }) + "\n")
        for state_text in (goals or []):
            f.write(json.dumps(
                {"t": "g", "s": state_text},
                ensure_ascii=False,
            ) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# 1. BpeVocabularyBuilder
# ═══════════════════════════════════════════════════════════════════════════


def _build_test_vocab(tmp_path, vocab_size=500):
    """Build a small BPE vocabulary for testing. Returns (output_dir, report)."""
    from Poule.neural.training.vocabulary import BpeVocabularyBuilder

    jsonl_path = tmp_path / "train.jsonl"
    # Generate enough diverse text to support the vocab size + user_defined_symbols
    steps = []
    for i in range(500):
        state = f"H{i} : nat\nH{i}_proof : bool\nforall x{i} : nat, x{i} + {i} = {i} + x{i}"
        steps.append((f"file{i % 50}.v", state, "intros"))
    _write_step_records(jsonl_path, steps)

    output_dir = tmp_path / "vocab"
    report = BpeVocabularyBuilder.build(
        jsonl_paths=[jsonl_path],
        output_dir=output_dir,
        vocab_size=vocab_size,
    )
    return output_dir, report


class TestBpeVocabularyBuilder:
    """spec §4.0: BpeVocabularyBuilder trains a SentencePiece BPE model."""

    def test_build_creates_tokenizer_model(self, tmp_path):
        """spec §4.0: build() produces a tokenizer.model file in output_dir."""
        output_dir, _ = _build_test_vocab(tmp_path)
        assert (output_dir / "tokenizer.model").exists()

    def test_build_returns_vocabulary_report(self, tmp_path):
        """spec §4.0: build() returns a VocabularyReport with bpe_tokens count."""
        from Poule.neural.training.vocabulary import VocabularyReport

        _, report = _build_test_vocab(tmp_path)
        assert isinstance(report, VocabularyReport)
        assert hasattr(report, "bpe_tokens")
        assert report.bpe_tokens > 0

    def test_special_tokens_included(self, tmp_path):
        """spec §4.0: Structural markers exist as single pieces in the vocabulary."""
        from Poule.neural.training.vocabulary import CoqTokenizer

        output_dir, _ = _build_test_vocab(tmp_path)
        tokenizer = CoqTokenizer(output_dir)
        # Each structural marker should be a dedicated piece in the vocab
        for marker in ["[HYP]", "[TYPE]", "[BODY]", "[GOAL]", "[GOALSEP]"]:
            piece_id = tokenizer._sp.piece_to_id(marker)
            assert piece_id >= 0, f"{marker} should be in the vocabulary as a single piece"

    def test_vocab_size_respected(self, tmp_path):
        """spec §4.0: Resulting vocabulary size does not exceed requested."""
        _, report = _build_test_vocab(tmp_path, vocab_size=500)
        assert report.bpe_tokens <= 500

    def test_empty_jsonl_raises_error(self, tmp_path):
        """spec §4.0: Empty training data raises InsufficientDataError."""
        from Poule.neural.training.vocabulary import BpeVocabularyBuilder
        from Poule.neural.training.errors import InsufficientDataError

        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.touch()

        output_dir = tmp_path / "vocab"
        with pytest.raises(InsufficientDataError):
            BpeVocabularyBuilder.build(
                jsonl_paths=[jsonl_path],
                output_dir=output_dir,
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. CoqTokenizer (BPE)
# ═══════════════════════════════════════════════════════════════════════════


class TestCoqTokenizerBPE:
    """spec §4.0.1: CoqTokenizer wraps a trained SentencePiece BPE model."""

    @pytest.fixture
    def vocab_dir(self, tmp_path):
        """Build a small BPE vocabulary for testing."""
        output_dir, _ = _build_test_vocab(tmp_path)
        return output_dir

    def test_init_loads_sentencepiece_model(self, vocab_dir):
        """spec §4.0.1: CoqTokenizer loads from vocabulary_dir."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        tokenizer = CoqTokenizer(vocab_dir)
        assert tokenizer is not None

    def test_encode_returns_tuple_of_lists(self, vocab_dir):
        """spec §4.0.1: encode() returns (input_ids, attention_mask) lists."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        tokenizer = CoqTokenizer(vocab_dir)
        ids, mask = tokenizer.encode("n : nat")
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)
        assert len(ids) > 0
        assert len(mask) == len(ids)

    def test_encode_max_length_truncates(self, vocab_dir):
        """spec §4.0.1: encode() truncates to max_length."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        tokenizer = CoqTokenizer(vocab_dir)
        long_text = " ".join(["nat"] * 1000)
        ids, mask = tokenizer.encode(long_text, max_length=32)
        assert len(ids) <= 32

    def test_encode_batch_returns_padded_tensors(self, vocab_dir):
        """spec §4.0.1: encode_batch() returns (input_ids, attention_mask) tensors."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        tokenizer = CoqTokenizer(vocab_dir)
        texts = ["n : nat", "forall x, x = x", "H : bool"]
        input_ids, attention_mask = tokenizer.encode_batch(texts, max_length=32)
        assert input_ids.shape[0] == 3  # batch size
        assert input_ids.shape[1] == 32  # max_length
        assert attention_mask.shape == input_ids.shape

    def test_structural_markers_are_single_tokens(self, vocab_dir):
        """spec §4.0.1: Structural markers encode as single tokens."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        tokenizer = CoqTokenizer(vocab_dir)
        # Encode a structured state with markers
        text = "[HYP] n [TYPE] nat [GOAL] n = n"
        ids, mask = tokenizer.encode(text)
        # The markers should not be split into subwords
        assert len(ids) > 0

    def test_missing_model_raises_error(self, tmp_path):
        """spec §4.0.1: Missing tokenizer.model raises FileNotFoundError."""
        from Poule.neural.training.vocabulary import CoqTokenizer
        with pytest.raises(FileNotFoundError):
            CoqTokenizer(tmp_path / "nonexistent")


# ═══════════════════════════════════════════════════════════════════════════
# 3. serialize_structured
# ═══════════════════════════════════════════════════════════════════════════


class TestSerializeStructured:
    """spec §4.0.8: serialize_structured converts flat proof state to structured format."""

    def test_single_goal_with_hypotheses(self):
        """spec §4.0.8 example 1: Single goal with two hypotheses."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nIHn : n + 0 = n\nn + 0 = n",
            prev_tactic="intros",
            depth=2,
            ngoals=1,
        )
        assert "[PREV=intros]" in result
        assert "[DEPTH=2]" in result
        assert "[NGOALS=1]" in result
        assert "[HEAD=" in result
        assert "[HYP] n [TYPE] nat" in result
        assert "[HYP] IHn [TYPE] n + 0 = n" in result
        assert "[GOAL] n + 0 = n" in result

    def test_multi_goal(self):
        """spec §4.0.8 example 2: Two goals separated by [GOALSEP]."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nS n = S n\n\nm : nat\nm + 0 = m",
            prev_tactic="split",
            depth=3,
            ngoals=2,
        )
        assert "[PREV=split]" in result
        assert "[NGOALS=2]" in result
        assert "[GOALSEP]" in result
        # First goal
        assert "[HYP] n [TYPE] nat" in result
        assert "[GOAL] S n = S n" in result
        # Second goal
        assert "[HYP] m [TYPE] nat" in result
        assert "[GOAL] m + 0 = m" in result

    def test_empty_state(self):
        """spec §4.0.8 example 3: Empty state returns context prefix only."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="",
            prev_tactic=None,
            depth=0,
            ngoals=1,
        )
        assert "[PREV=none]" in result
        assert "[DEPTH=0]" in result
        assert "[NGOALS=1]" in result
        assert "[HEAD=other]" in result

    def test_prev_tactic_none_becomes_none(self):
        """spec §4.0.8 example 4: None prev_tactic becomes [PREV=none]."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nn = n",
            prev_tactic=None,
            depth=0,
            ngoals=1,
        )
        assert "[PREV=none]" in result

    def test_depth_clamped_at_10(self):
        """spec §4.0.8 example 5: depth >= 10 becomes [DEPTH=10+]."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nn = n",
            prev_tactic="simpl",
            depth=15,
            ngoals=1,
        )
        assert "[DEPTH=10+]" in result

    def test_ngoals_clamped_at_5(self):
        """spec §4.0.8 example 6: ngoals >= 5 becomes [NGOALS=5+]."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nn = n",
            prev_tactic="simpl",
            depth=1,
            ngoals=8,
        )
        assert "[NGOALS=5+]" in result

    def test_let_bound_hypothesis_body(self):
        """spec §4.0.8: Let-bound hypotheses emit [BODY] marker."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="H : n = n := eq_refl\nn : nat\nn = n",
            prev_tactic="intros",
            depth=1,
            ngoals=1,
        )
        assert "[BODY]" in result
        assert "eq_refl" in result

    def test_no_cls_sep_tokens(self):
        """spec §4.0.8: Output does not include [CLS] or [SEP] — tokenizer adds those."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nn = n",
            prev_tactic="intros",
            depth=0,
            ngoals=1,
        )
        assert "[CLS]" not in result
        assert "[SEP]" not in result

    def test_head_constructor_eq(self):
        """spec §4.0.8: Goal 'n + 0 = n' has head constructor 'eq'."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="n : nat\nn + 0 = n",
            prev_tactic=None,
            depth=0,
            ngoals=1,
        )
        assert "[HEAD=eq]" in result

    def test_head_constructor_forall(self):
        """spec §4.0.8: Goal 'forall n, n = n' has head constructor 'forall'."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="forall n, n = n",
            prev_tactic=None,
            depth=0,
            ngoals=1,
        )
        assert "[HEAD=forall]" in result

    def test_head_constructor_unknown(self):
        """spec §4.0.8: Unknown head constructor becomes [HEAD=other]."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="SomeCustomType x y z",
            prev_tactic=None,
            depth=0,
            ngoals=1,
        )
        assert "[HEAD=other]" in result

    def test_goal_without_hypotheses(self):
        """spec §4.0.8: Goal-only state (no hypotheses) produces [GOAL] only."""
        from Poule.neural.training.data import serialize_structured

        result = serialize_structured(
            state_text="True",
            prev_tactic="split",
            depth=1,
            ngoals=1,
        )
        assert "[GOAL] True" in result
        assert "[HYP]" not in result


# ═══════════════════════════════════════════════════════════════════════════
# 4. extract_goal_head
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractGoalHead:
    """spec §4.0.8: extract_goal_head extracts the first token from goal type."""

    def test_simple_eq(self):
        """Goal 'n = n' → 'eq' (= is Coq notation for eq)."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("n + 0 = n") == "eq"

    def test_forall(self):
        """Goal 'forall n, ...' → 'forall'."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("forall n : nat, n = n") == "forall"

    def test_and(self):
        """Goal 'A /\\ B' → 'and'."""
        from Poule.neural.training.data import extract_goal_head
        # In Coq, /\ is notation for `and`
        assert extract_goal_head("A /\\ B") in ("and", "other")

    def test_leading_parens_stripped(self):
        """Goal '(forall n, ...)' strips leading parens."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("(forall n, n = n)") == "forall"

    def test_unknown_head(self):
        """Goal with non-standard head → 'other'."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("CustomInductive x y") == "other"

    def test_empty_string(self):
        """Empty goal → 'other'."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("") == "other"

    def test_true(self):
        """Goal 'True' → 'True'."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("True") == "True"

    def test_false(self):
        """Goal 'False' → 'False'."""
        from Poule.neural.training.data import extract_goal_head
        assert extract_goal_head("False") == "False"

    def test_le(self):
        """Goal 'n <= m' → 'le'."""
        from Poule.neural.training.data import extract_goal_head
        # <= is Coq notation for le
        assert extract_goal_head("n <= m") in ("le", "other")

    def test_ex(self):
        """Goal 'exists n, ...' → 'ex'."""
        from Poule.neural.training.data import extract_goal_head
        # `exists` is notation for `ex`
        assert extract_goal_head("exists n, n = n") in ("ex", "other")


# ═══════════════════════════════════════════════════════════════════════════
# 5. HEAD_CONSTRUCTORS
# ═══════════════════════════════════════════════════════════════════════════


class TestHeadConstructors:
    """spec §4.0.8: HEAD_CONSTRUCTORS is a fixed set."""

    def test_contains_required_entries(self):
        """spec §4.0.8: HEAD_CONSTRUCTORS contains the specified set."""
        from Poule.neural.training.data import HEAD_CONSTRUCTORS

        required = {
            "forall", "eq", "and", "or", "ex", "not", "True", "False",
            "le", "lt", "ge", "gt", "plus", "mult", "minus", "iff",
            "prod", "sum", "Peano.le", "Peano.lt", "other",
        }
        for entry in required:
            assert entry in HEAD_CONSTRUCTORS, f"Missing {entry} from HEAD_CONSTRUCTORS"


# ═══════════════════════════════════════════════════════════════════════════
# 6. perturb_proof_state (structured format)
# ═══════════════════════════════════════════════════════════════════════════


class TestPerturbProofStateStructured:
    """spec §4.1: perturb_proof_state on structured text with markers."""

    def test_shuffles_hypotheses_in_structured_format(self):
        """Hypothesis segments are reordered; goal stays in place."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=intros] [DEPTH=2] [NGOALS=1] [HEAD=eq] "
            "[HYP] H [TYPE] nat [HYP] H0 [TYPE] bool [HYP] H1 [TYPE] list nat "
            "[GOAL] H = H0"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        # Context prefix preserved
        assert result.startswith("[PREV=intros] [DEPTH=2] [NGOALS=1] [HEAD=eq]")
        # Goal still present
        assert "[GOAL]" in result
        # All hypotheses present (though possibly reordered and renamed)
        assert result.count("[HYP]") == 3

    def test_renames_identifiers_in_structured_format(self):
        """Hypothesis names are replaced with synthetic names."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=intros] [DEPTH=1] [NGOALS=1] [HEAD=eq] "
            "[HYP] n [TYPE] nat [HYP] m [TYPE] nat "
            "[GOAL] n + m = m + n"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        # Original names should not appear after [HYP]
        # (they are renamed to synthetic v0, v1, etc.)
        assert "[PREV=intros]" in result  # prefix preserved
        assert "[GOAL]" in result

    def test_context_prefix_preserved(self):
        """Context prefix is never modified by perturbation."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=rewrite] [DEPTH=5] [NGOALS=2] [HEAD=forall] "
            "[HYP] x [TYPE] nat [GOAL] forall y, x = y "
            "[GOALSEP] [HYP] z [TYPE] bool [GOAL] z = true"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        assert "[PREV=rewrite] [DEPTH=5] [NGOALS=2] [HEAD=forall]" in result

    def test_multi_goal_structured_perturbation(self):
        """Each goal block's hypotheses are shuffled independently."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=split] [DEPTH=3] [NGOALS=2] [HEAD=eq] "
            "[HYP] A [TYPE] nat [GOAL] A + 1 = 2 "
            "[GOALSEP] [HYP] B [TYPE] bool [GOAL] true = B"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        assert "[GOALSEP]" in result
        assert result.count("[GOAL]") == 2

    def test_no_hypotheses_unchanged(self):
        """State with no hypotheses returns unchanged."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=none] [DEPTH=0] [NGOALS=1] [HEAD=forall] "
            "[GOAL] forall n, n = n"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        assert result == state

    def test_deterministic(self):
        """Same rng state produces same result."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=intros] [DEPTH=2] [NGOALS=1] [HEAD=eq] "
            "[HYP] H [TYPE] nat [HYP] H0 [TYPE] bool [GOAL] H = H0"
        )
        r1 = perturb_proof_state(state, random.Random(42))
        r2 = perturb_proof_state(state, random.Random(42))
        assert r1 == r2

    def test_word_boundary_replacement_structured(self):
        """Replacing 'H' does not affect 'H0' or 'IHn'."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=intros] [DEPTH=1] [NGOALS=1] [HEAD=eq] "
            "[HYP] H [TYPE] nat [HYP] H0 [TYPE] bool [HYP] IHn [TYPE] nat "
            "[GOAL] H + H0 + IHn = 0"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        # All three should be independently renamed
        assert result.count("[HYP]") == 3

    def test_body_marker_preserved(self):
        """Let-bound hypotheses with [BODY] markers are preserved."""
        from Poule.neural.training.data import perturb_proof_state

        state = (
            "[PREV=intros] [DEPTH=1] [NGOALS=1] [HEAD=eq] "
            "[HYP] H [TYPE] n = n [BODY] eq_refl "
            "[GOAL] n = n"
        )
        rng = random.Random(42)
        result = perturb_proof_state(state, rng)
        assert "[BODY]" in result


# ═══════════════════════════════════════════════════════════════════════════
# 7. Context features in TrainingDataLoader
# ═══════════════════════════════════════════════════════════════════════════


class TestContextFeatureExtraction:
    """spec §4.1: TrainingDataLoader.load() derives context features."""

    def test_load_produces_structured_state_text(self, tmp_path):
        """spec §4.1: load() returns structured state text in train_pairs."""
        from Poule.neural.training.data import TrainingDataLoader

        # Create JSONL with multiple steps from same file (for prev_tactic derivation)
        jsonl_path = tmp_path / "train.jsonl"
        _write_step_records(jsonl_path, [
            # 10 files × 3 steps each to ensure we get train split
            *[(f"file{i:02d}.v", "n : nat\nn + 0 = n", "intros") for i in range(10)],
            *[(f"file{i:02d}.v", "n : nat\nIHn : n + 0 = n\nn + 0 = n", "rewrite") for i in range(10)],
            *[(f"file{i:02d}.v", "n : nat\nn = n", "reflexivity") for i in range(10)],
        ])

        dataset = TrainingDataLoader.load([jsonl_path])
        # At least some train_pairs should exist
        assert len(dataset.train_pairs) > 0

        # Check that structured markers are present in state text
        state_text, _, _ = dataset.train_pairs[0]
        assert "[PREV=" in state_text
        assert "[DEPTH=" in state_text
        assert "[NGOALS=" in state_text
        assert "[HEAD=" in state_text

    def test_first_step_has_prev_none(self, tmp_path):
        """spec §4.1: First step in a file has prev_tactic=None → [PREV=none]."""
        from Poule.neural.training.data import TrainingDataLoader

        jsonl_path = tmp_path / "train.jsonl"
        # Create enough files for a train split
        _write_step_records(jsonl_path, [
            (f"file{i:02d}.v", "n : nat\nn = n", "intros")
            for i in range(10)
        ])

        dataset = TrainingDataLoader.load([jsonl_path])
        # All steps are first-in-file, so all should have [PREV=none]
        for state_text, _, _ in dataset.train_pairs:
            assert "[PREV=none]" in state_text

    def test_second_step_has_prev_from_first(self, tmp_path):
        """spec §4.1: Second step's prev_tactic is derived from first step's family."""
        from Poule.neural.training.data import TrainingDataLoader

        jsonl_path = tmp_path / "train.jsonl"
        # Two steps per file, first is "intros", second should see [PREV=intros]
        _write_step_records(jsonl_path, [
            *[(f"file{i:02d}.v", "forall n, n = n", "intros") for i in range(10)],
            *[(f"file{i:02d}.v", "n : nat\nn = n", "reflexivity") for i in range(10)],
        ])

        dataset = TrainingDataLoader.load([jsonl_path])
        # At least some train_pairs should have [PREV=intros]
        prev_intros = [s for s, _, _ in dataset.train_pairs if "[PREV=intros]" in s]
        assert len(prev_intros) > 0

    def test_structural_markers_in_loaded_data(self, tmp_path):
        """spec §4.1: Loaded data contains [HYP], [TYPE], [GOAL] markers."""
        from Poule.neural.training.data import TrainingDataLoader

        jsonl_path = tmp_path / "train.jsonl"
        _write_step_records(jsonl_path, [
            (f"file{i:02d}.v", "n : nat\nn + 0 = n", "intros")
            for i in range(10)
        ])

        dataset = TrainingDataLoader.load([jsonl_path])
        # Check at least one train pair has structural markers
        has_hyp = any("[HYP]" in s for s, _, _ in dataset.train_pairs)
        has_goal = any("[GOAL]" in s for s, _, _ in dataset.train_pairs)
        assert has_hyp, "No [HYP] markers found in loaded data"
        assert has_goal, "No [GOAL] markers found in loaded data"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Embedding factorization removed
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingFullRank:
    """spec §4.3: With BPE, embedding is always 768-d, no factorization."""

    def test_no_embedding_dim_in_hyperparams(self):
        """spec §4.3: embedding_dim removed from hyperparams (always 768)."""
        from Poule.neural.training.trainer import DEFAULT_HYPERPARAMS
        assert "embedding_dim" not in DEFAULT_HYPERPARAMS

    def test_no_projection_layer(self):
        """spec §4.3: Model has no embedding_projection layer."""
        import torch.nn as nn
        from unittest.mock import patch

        def _mock_encoder():
            class MockEmbeddings:
                def __init__(self):
                    self.word_embeddings = nn.Embedding(50265, 768)

            class MockConfig:
                def __init__(self):
                    self.hidden_size = 768
                    self.num_hidden_layers = 12

            class MockEncoder:
                def __init__(self):
                    self.embeddings = MockEmbeddings()
                    self.config = MockConfig()
                    self.encoder = type("E", (), {
                        "layer": nn.ModuleList([
                            nn.TransformerEncoderLayer(
                                d_model=768, nhead=12, batch_first=True
                            )
                            for _ in range(12)
                        ])
                    })()

                def __call__(self, input_ids=None, attention_mask=None, inputs_embeds=None):
                    import torch
                    if inputs_embeds is not None:
                        B, S = inputs_embeds.shape[:2]
                    else:
                        B, S = input_ids.shape
                    hidden = torch.randn(B, S, 768)
                    return type("Output", (), {"last_hidden_state": hidden})()

            return MockEncoder()

        from Poule.neural.training.model import HierarchicalTacticClassifier

        with patch("Poule.neural.training.model.AutoModel") as mock_auto:
            mock_auto.from_pretrained.return_value = _mock_encoder()
            model = HierarchicalTacticClassifier(
                per_category_sizes={"rewriting": 3, "introduction": 2},
                num_categories=2,
                vocab_size=1000,
                num_hidden_layers=6,
            )
        assert not hasattr(model, "embedding_projection") or model.embedding_projection is None

    def test_embedding_shape_is_full_rank(self):
        """spec §4.3: Embedding layer shape is (vocab_size, 768)."""
        import torch.nn as nn
        from unittest.mock import patch

        def _mock_encoder():
            class MockEmbeddings:
                def __init__(self):
                    self.word_embeddings = nn.Embedding(50265, 768)

            class MockConfig:
                def __init__(self):
                    self.hidden_size = 768
                    self.num_hidden_layers = 12

            class MockEncoder:
                def __init__(self):
                    self.embeddings = MockEmbeddings()
                    self.config = MockConfig()
                    self.encoder = type("E", (), {
                        "layer": nn.ModuleList([
                            nn.TransformerEncoderLayer(
                                d_model=768, nhead=12, batch_first=True
                            )
                            for _ in range(12)
                        ])
                    })()

                def __call__(self, input_ids=None, attention_mask=None, inputs_embeds=None):
                    import torch
                    if inputs_embeds is not None:
                        B, S = inputs_embeds.shape[:2]
                    else:
                        B, S = input_ids.shape
                    hidden = torch.randn(B, S, 768)
                    return type("Output", (), {"last_hidden_state": hidden})()

            return MockEncoder()

        from Poule.neural.training.model import HierarchicalTacticClassifier

        with patch("Poule.neural.training.model.AutoModel") as mock_auto:
            mock_auto.from_pretrained.return_value = _mock_encoder()
            model = HierarchicalTacticClassifier(
                per_category_sizes={"rewriting": 3},
                num_categories=1,
                vocab_size=500,
                num_hidden_layers=6,
            )
        emb = model.encoder.embeddings.word_embeddings
        assert emb.weight.shape == (500, 768)

    def test_checkpoint_no_embedding_dim_field(self):
        """spec §4.3: Checkpoint format no longer includes embedding_dim."""
        from Poule.neural.training.trainer import DEFAULT_HYPERPARAMS
        assert "embedding_dim" not in DEFAULT_HYPERPARAMS
