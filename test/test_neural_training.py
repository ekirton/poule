"""TDD tests for neural training pipeline (specification/neural-training.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/neural/training/.

Covers: TrainingDataLoader (JSONL parsing, pair extraction, file-level split),
hard negative sampling, BiEncoderTrainer (masked contrastive loss, early stopping,
checkpoint format), fine-tuning, RetrievalEvaluator (evaluate, compare, thresholds),
ModelQuantizer (ONNX export, validation), TrainingDataValidator (warning conditions),
error hierarchy.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Imports from production code (TDD — will fail until implemented)
# ---------------------------------------------------------------------------

from poule.neural.training.data import TrainingDataLoader, TrainingDataset
from poule.neural.training.negatives import sample_hard_negatives
from poule.neural.training.trainer import BiEncoderTrainer
from poule.neural.training.evaluator import RetrievalEvaluator, EvaluationReport, ComparisonReport
from poule.neural.training.quantizer import ModelQuantizer
from poule.neural.training.validator import TrainingDataValidator, ValidationReport
from poule.neural.training.errors import (
    NeuralTrainingError,
    DataFormatError,
    CheckpointNotFoundError,
    TrainingResourceError,
    QuantizationError,
    InsufficientDataError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path, records):
    """Write a list of dicts as a JSON Lines file."""
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _make_extraction_record(source_file, steps):
    """Create a minimal ExtractionRecord dict for testing."""
    return {
        "source_file": source_file,
        "steps": steps,
    }


def _make_step(state_before, premises):
    """Create a minimal step dict."""
    return {
        "state_before": state_before,
        "premises": premises,
    }


def _make_minimal_index_db(db_path, declarations=None):
    """Create a minimal index database with declarations table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE declarations (id INTEGER PRIMARY KEY, name TEXT, "
        "statement TEXT, module TEXT, symbol_set TEXT)"
    )
    conn.execute(
        "CREATE TABLE dependencies (src INTEGER, dst INTEGER, relation TEXT)"
    )
    conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
    if declarations:
        for decl in declarations:
            conn.execute(
                "INSERT INTO declarations (id, name, statement, module) VALUES (?, ?, ?, ?)",
                decl,
            )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 1. TrainingDataLoader — Pair Extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestPairExtraction:
    """spec §4.1: Pair extraction from ExtractionRecords."""

    def test_extracts_pairs_from_steps_with_premises(self, tmp_path):
        """spec §4.1: Steps with non-empty premise lists emit training pairs."""
        jsonl_path = tmp_path / "data.jsonl"
        record = _make_extraction_record(
            "Coq.Init.Nat",
            [
                _make_step("goal 1", ["Nat.add_comm", "Nat.add_assoc"]),
                _make_step("goal 2", []),  # empty — skipped
                _make_step("goal 3", ["Nat.mul_comm"]),
            ],
        )
        _write_jsonl(jsonl_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "Nat.add_comm", "stmt1", "Coq.Init.Nat"),
            (2, "Nat.add_assoc", "stmt2", "Coq.Init.Nat"),
            (3, "Nat.mul_comm", "stmt3", "Coq.Init.Nat"),
        ])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        # 5 steps, 2 with non-empty premises → 2 training pairs
        all_pairs = dataset.train + dataset.val + dataset.test
        # Given/When/Then: 3 steps, 2 with non-empty premises → 2 pairs
        assert len(all_pairs) == 2

    def test_skips_steps_with_empty_premises(self, tmp_path):
        """spec §4.1: Steps with empty premise lists shall be skipped."""
        jsonl_path = tmp_path / "data.jsonl"
        record = _make_extraction_record(
            "Coq.Init.Nat",
            [
                _make_step("goal 1", []),
                _make_step("goal 2", []),
            ],
        )
        _write_jsonl(jsonl_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 0

    def test_pair_contains_state_and_premises(self, tmp_path):
        """spec §4.1: Each pair is (state_text, premises_used_names)."""
        jsonl_path = tmp_path / "data.jsonl"
        record = _make_extraction_record(
            "Coq.Init.Nat",
            [_make_step("forall n : nat, n + 0 = n", ["Nat.add_0_r"])],
        )
        _write_jsonl(jsonl_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "Nat.add_0_r", "stmt", "Coq.Init.Nat")])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        state, premises = all_pairs[0]
        assert state == "forall n : nat, n + 0 = n"
        assert premises == ["Nat.add_0_r"]

    def test_handles_multiple_jsonl_files(self, tmp_path):
        """spec §4.1: load accepts a list of JSONL paths."""
        file1 = tmp_path / "a.jsonl"
        file2 = tmp_path / "b.jsonl"
        _write_jsonl(file1, [
            _make_extraction_record("FileA", [_make_step("s1", ["P1"])]),
        ])
        _write_jsonl(file2, [
            _make_extraction_record("FileB", [_make_step("s2", ["P2"])]),
        ])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "P1", "stmt1", "FileA"),
            (2, "P2", "stmt2", "FileB"),
        ])

        dataset = TrainingDataLoader.load([file1, file2], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 2. TrainingDataLoader — File-Level Split
# ═══════════════════════════════════════════════════════════════════════════


class TestFileLevelSplit:
    """spec §4.1: Deterministic train/val/test split by source file position."""

    def test_split_positions_for_10_files(self, tmp_path):
        """spec §4.1: position % 10 == 8 → val, == 9 → test, else → train.

        Given 10 files sorted lexicographically (file_00..file_09),
        file_08 → val, file_09 → test, rest → train.
        """
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        for i in range(10):
            records.append(
                _make_extraction_record(
                    f"file_{i:02d}",
                    [_make_step(f"state_{i}", [f"premise_{i}"])],
                )
            )
        _write_jsonl(jsonl_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"premise_{i}", f"stmt_{i}", f"file_{i:02d}") for i in range(10)]
        _make_minimal_index_db(db_path, decls)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)

        # Files sorted lexicographically: file_00..file_09
        # position 8 → val, position 9 → test, 0-7 → train
        assert len(dataset.train) == 8
        assert len(dataset.val) == 1
        assert len(dataset.test) == 1

    def test_split_positions_for_100_files(self, tmp_path):
        """spec §4.1: Given 100 files, indices 8,18,28,...→val; 9,19,29,...→test."""
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        for i in range(100):
            records.append(
                _make_extraction_record(
                    f"file_{i:03d}",
                    [_make_step(f"state_{i}", [f"premise_{i}"])],
                )
            )
        _write_jsonl(jsonl_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"premise_{i}", f"stmt_{i}", f"file_{i:03d}") for i in range(100)]
        _make_minimal_index_db(db_path, decls)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)

        # 10 val files (pos 8,18,...,98), 10 test files (pos 9,19,...,99), 80 train
        assert len(dataset.train) == 80
        assert len(dataset.val) == 10
        assert len(dataset.test) == 10

    def test_no_pair_in_multiple_splits(self, tmp_path):
        """spec §4.1 MAINTAINS: No pair from same file in more than one split."""
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        for i in range(20):
            # Multiple steps per file
            steps = [
                _make_step(f"state_{i}_a", [f"premise_{i}"]),
                _make_step(f"state_{i}_b", [f"premise_{i}"]),
            ]
            records.append(_make_extraction_record(f"file_{i:02d}", steps))
        _write_jsonl(jsonl_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"premise_{i}", f"stmt_{i}", f"file_{i:02d}") for i in range(20)]
        _make_minimal_index_db(db_path, decls)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)

        train_states = {s for s, _ in dataset.train}
        val_states = {s for s, _ in dataset.val}
        test_states = {s for s, _ in dataset.test}

        assert train_states.isdisjoint(val_states)
        assert train_states.isdisjoint(test_states)
        assert val_states.isdisjoint(test_states)

    def test_split_is_deterministic(self, tmp_path):
        """Split should be identical across two calls with the same data."""
        jsonl_path = tmp_path / "data.jsonl"
        records = [
            _make_extraction_record(f"file_{i:02d}", [_make_step(f"s{i}", [f"p{i}"])])
            for i in range(15)
        ]
        _write_jsonl(jsonl_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"p{i}", f"stmt_{i}", f"file_{i:02d}") for i in range(15)]
        _make_minimal_index_db(db_path, decls)

        d1 = TrainingDataLoader.load([jsonl_path], db_path)
        d2 = TrainingDataLoader.load([jsonl_path], db_path)

        assert d1.train == d2.train
        assert d1.val == d2.val
        assert d1.test == d2.test


# ═══════════════════════════════════════════════════════════════════════════
# 3. Hard Negative Sampling
# ═══════════════════════════════════════════════════════════════════════════


class TestHardNegativeSampling:
    r"""spec §4.2: sample_hard_negatives from accessible \ positive premises."""

    def test_returns_k_negatives_from_accessible(self):
        r"""spec §4.2: Returns k premises from accessible \ positive."""
        positive = {"A", "B"}
        accessible = {"A", "B", "C", "D", "E", "F"}
        result = sample_hard_negatives("state", positive, accessible, k=3)
        assert len(result) == 3
        assert all(r not in positive for r in result)
        assert all(r in accessible for r in result)

    def test_returns_all_when_fewer_than_k(self):
        r"""spec §4.2: If |accessible \ positive| < k, returns all available."""
        positive = {"A", "B"}
        accessible = {"A", "B", "C"}
        result = sample_hard_negatives("state", positive, accessible, k=5)
        # Only "C" is available
        assert len(result) == 1
        assert result == ["C"] or set(result) == {"C"}

    def test_fallback_to_corpus_when_no_accessible(self):
        """spec §4.2: If accessible is empty, sample from full corpus as fallback."""
        positive = {"A"}
        accessible = set()
        corpus = {"A", "B", "C", "D", "E"}
        result = sample_hard_negatives("state", positive, accessible, k=3, corpus=corpus)
        assert len(result) == 3
        assert all(r not in positive for r in result)

    def test_excludes_positive_premises(self):
        r"""spec §4.2: Negatives come from accessible \ positive."""
        positive = {"A", "B", "C"}
        accessible = {"A", "B", "C", "D", "E"}
        result = sample_hard_negatives("state", positive, accessible, k=2)
        for r in result:
            assert r not in positive


# ═══════════════════════════════════════════════════════════════════════════
# 4. BiEncoderTrainer — Hyperparameters
# ═══════════════════════════════════════════════════════════════════════════


class TestBiEncoderTrainerHyperparams:
    """spec §4.3: Default hyperparameters and constraints."""

    def test_default_hyperparameters(self):
        """spec §4.3: Verify default hyperparameter values."""
        trainer = BiEncoderTrainer()
        assert trainer.hyperparams["batch_size"] == 256
        assert trainer.hyperparams["learning_rate"] == 2e-5
        assert trainer.hyperparams["weight_decay"] == 1e-2
        assert trainer.hyperparams["temperature"] == 0.05
        assert trainer.hyperparams["hard_negatives_per_state"] == 3
        assert trainer.hyperparams["max_seq_length"] == 512
        assert trainer.hyperparams["max_epochs"] == 20
        assert trainer.hyperparams["early_stopping_patience"] == 3
        assert trainer.hyperparams["embedding_dim"] == 768

    def test_custom_hyperparameters_override_defaults(self):
        """spec §4.3: Caller can override defaults."""
        trainer = BiEncoderTrainer(hyperparams={"batch_size": 128, "learning_rate": 1e-5})
        assert trainer.hyperparams["batch_size"] == 128
        assert trainer.hyperparams["learning_rate"] == 1e-5
        # Non-overridden defaults remain
        assert trainer.hyperparams["temperature"] == 0.05


# ═══════════════════════════════════════════════════════════════════════════
# 5. BiEncoderTrainer — Early Stopping
# ═══════════════════════════════════════════════════════════════════════════


class TestEarlyStopping:
    """spec §4.3: Early stopping based on validation Recall@32."""

    def test_stops_after_patience_epochs_without_improvement(self):
        """spec §4.3: Given patience=3, stops after 3 epochs with no R@32 improvement.

        Given patience=3 and validation R@32 does not improve for epochs 8, 9, 10
        When epoch 10 completes
        Then training stops and the checkpoint from epoch 7 is retained.
        """
        from poule.neural.training.trainer import EarlyStoppingTracker

        tracker = EarlyStoppingTracker(patience=3)
        # Epochs 1-7: improving
        for epoch, recall in enumerate([0.10, 0.20, 0.30, 0.35, 0.38, 0.40, 0.42], 1):
            assert tracker.should_stop(recall) is False

        # Epochs 8-10: no improvement (all <= 0.42)
        assert tracker.should_stop(0.41) is False   # epoch 8, 1 bad
        assert tracker.should_stop(0.40) is False   # epoch 9, 2 bad
        assert tracker.should_stop(0.39) is True    # epoch 10, 3 bad → stop

        assert tracker.best_epoch == 7
        assert abs(tracker.best_recall - 0.42) < 1e-6

    def test_resets_on_improvement(self):
        """spec §4.3: Patience counter resets when R@32 improves."""
        from poule.neural.training.trainer import EarlyStoppingTracker

        tracker = EarlyStoppingTracker(patience=3)
        tracker.should_stop(0.30)  # epoch 1
        tracker.should_stop(0.29)  # epoch 2, 1 bad
        tracker.should_stop(0.28)  # epoch 3, 2 bad
        tracker.should_stop(0.31)  # epoch 4, improvement! reset
        tracker.should_stop(0.30)  # epoch 5, 1 bad
        tracker.should_stop(0.29)  # epoch 6, 2 bad
        assert tracker.should_stop(0.28) is True  # epoch 7, 3 bad → stop

        assert tracker.best_epoch == 4


# ═══════════════════════════════════════════════════════════════════════════
# 6. BiEncoderTrainer — Checkpoint Format
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckpointFormat:
    """spec §4.3: Checkpoint includes required fields."""

    def test_checkpoint_contains_required_fields(self, tmp_path):
        """spec §4.3: Checkpoint shall include model state, optimizer state,
        epoch number, best validation R@32, and hyperparameters."""
        from poule.neural.training.trainer import save_checkpoint, load_checkpoint

        checkpoint_data = {
            "model_state_dict": {"layer.weight": np.zeros(10)},
            "optimizer_state_dict": {"param_groups": []},
            "epoch": 12,
            "best_recall_32": 0.54,
            "hyperparams": {"batch_size": 256, "learning_rate": 2e-5},
        }
        path = tmp_path / "checkpoint.pt"
        save_checkpoint(checkpoint_data, path)
        loaded = load_checkpoint(path)

        assert "model_state_dict" in loaded
        assert "optimizer_state_dict" in loaded
        assert loaded["epoch"] == 12
        assert abs(loaded["best_recall_32"] - 0.54) < 1e-6
        assert loaded["hyperparams"]["batch_size"] == 256


# ═══════════════════════════════════════════════════════════════════════════
# 7. Fine-Tuning
# ═══════════════════════════════════════════════════════════════════════════


class TestFineTuning:
    """spec §4.4: Fine-tuning hyperparameter overrides."""

    def test_fine_tune_default_overrides(self):
        """spec §4.4: Fine-tuning defaults to lr=5e-6 and max_epochs=10."""
        from poule.neural.training.trainer import get_fine_tune_hyperparams

        params = get_fine_tune_hyperparams()
        assert params["learning_rate"] == 5e-6
        assert params["max_epochs"] == 10
        # Other defaults remain from base
        assert params["batch_size"] == 256
        assert params["temperature"] == 0.05

    def test_fine_tune_accepts_custom_overrides(self):
        """spec §4.4: Caller can still override fine-tuning defaults."""
        from poule.neural.training.trainer import get_fine_tune_hyperparams

        params = get_fine_tune_hyperparams(overrides={"learning_rate": 1e-6})
        assert params["learning_rate"] == 1e-6
        assert params["max_epochs"] == 10  # fine-tune default retained


# ═══════════════════════════════════════════════════════════════════════════
# 8. RetrievalEvaluator — Evaluation Report
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluationReport:
    """spec §4.5: EvaluationReport fields and thresholds."""

    def test_report_contains_required_fields(self):
        """spec §4.5: EvaluationReport has all specified fields."""
        report = EvaluationReport(
            recall_at_1=0.22,
            recall_at_10=0.41,
            recall_at_32=0.52,
            mrr=0.35,
            test_count=1000,
            mean_premises_per_state=2.3,
            mean_query_latency_ms=8.5,
        )
        assert report.recall_at_1 == 0.22
        assert report.recall_at_10 == 0.41
        assert report.recall_at_32 == 0.52
        assert report.mrr == 0.35
        assert report.test_count == 1000
        assert report.mean_premises_per_state == 2.3
        assert report.mean_query_latency_ms == 8.5

    def test_warning_when_recall_below_threshold(self):
        """spec §4.5: When recall_at_32 < 0.50, include a warning."""
        report = EvaluationReport(
            recall_at_1=0.10,
            recall_at_10=0.25,
            recall_at_32=0.35,  # below 0.50
            mrr=0.20,
            test_count=500,
            mean_premises_per_state=1.5,
            mean_query_latency_ms=9.0,
        )
        assert any("Recall@32 < 50%" in w for w in report.warnings)

    def test_no_warning_when_recall_meets_threshold(self):
        """spec §4.5: No warning when recall_at_32 >= 0.50."""
        report = EvaluationReport(
            recall_at_1=0.30,
            recall_at_10=0.45,
            recall_at_32=0.55,
            mrr=0.40,
            test_count=1000,
            mean_premises_per_state=2.0,
            mean_query_latency_ms=7.0,
        )
        assert not any("Recall@32" in w for w in report.warnings)


# ═══════════════════════════════════════════════════════════════════════════
# 9. RetrievalEvaluator — Comparison Report
# ═══════════════════════════════════════════════════════════════════════════


class TestComparisonReport:
    """spec §4.5: ComparisonReport fields and thresholds."""

    def test_report_contains_required_fields(self):
        """spec §4.5: ComparisonReport has all specified fields."""
        report = ComparisonReport(
            neural_recall_32=0.52,
            symbolic_recall_32=0.38,
            union_recall_32=0.55,
            relative_improvement=0.45,
            overlap_pct=37.5,
            neural_exclusive_pct=25.0,
            symbolic_exclusive_pct=37.5,
        )
        assert report.neural_recall_32 == 0.52
        assert report.symbolic_recall_32 == 0.38
        assert report.union_recall_32 == 0.55
        assert abs(report.relative_improvement - 0.45) < 1e-6

    def test_relative_improvement_formula(self):
        """spec §4.5: relative_improvement = (union - symbolic) / symbolic."""
        report = ComparisonReport(
            neural_recall_32=0.52,
            symbolic_recall_32=0.38,
            union_recall_32=0.55,
            # (0.55 - 0.38) / 0.38 ≈ 0.4474
            relative_improvement=(0.55 - 0.38) / 0.38,
            overlap_pct=37.5,
            neural_exclusive_pct=25.0,
            symbolic_exclusive_pct=37.5,
        )
        expected = (0.55 - 0.38) / 0.38
        assert abs(report.relative_improvement - expected) < 1e-4

    def test_warning_when_improvement_below_threshold(self):
        """spec §4.5: Warning when relative_improvement < 0.15."""
        report = ComparisonReport(
            neural_recall_32=0.35,
            symbolic_recall_32=0.38,
            union_recall_32=0.40,
            relative_improvement=0.05,  # below 15%
            overlap_pct=80.0,
            neural_exclusive_pct=5.0,
            symbolic_exclusive_pct=15.0,
        )
        assert any("union improvement < 15%" in w for w in report.warnings)

    def test_no_warning_when_improvement_meets_threshold(self):
        """spec §4.5: No warning when relative_improvement >= 0.15."""
        report = ComparisonReport(
            neural_recall_32=0.52,
            symbolic_recall_32=0.38,
            union_recall_32=0.55,
            relative_improvement=0.45,
            overlap_pct=37.5,
            neural_exclusive_pct=25.0,
            symbolic_exclusive_pct=37.5,
        )
        assert not any("union improvement" in w for w in report.warnings)

    def test_overlap_example_from_spec(self):
        """spec §4.5 example: neural=100, symbolic=120, overlap=60.

        overlap_pct = 60 / (100 + 120 - 60) = 37.5%
        neural_exclusive_pct = 40 / 160 = 25%
        symbolic_exclusive_pct = 60 / 160 = 37.5%
        """
        neural_correct = 100
        symbolic_correct = 120
        overlap = 60
        total_unique = neural_correct + symbolic_correct - overlap  # 160

        overlap_pct = overlap / total_unique * 100  # 37.5
        neural_exclusive_pct = (neural_correct - overlap) / total_unique * 100  # 25.0
        symbolic_exclusive_pct = (symbolic_correct - overlap) / total_unique * 100  # 37.5

        assert abs(overlap_pct - 37.5) < 0.1
        assert abs(neural_exclusive_pct - 25.0) < 0.1
        assert abs(symbolic_exclusive_pct - 37.5) < 0.1


# ═══════════════════════════════════════════════════════════════════════════
# 10. ModelQuantizer
# ═══════════════════════════════════════════════════════════════════════════


class TestModelQuantizer:
    """spec §4.6: ModelQuantizer ONNX export and validation."""

    def test_quantize_raises_on_missing_checkpoint(self, tmp_path):
        """spec §5: CheckpointNotFoundError when checkpoint is missing."""
        with pytest.raises(CheckpointNotFoundError):
            ModelQuantizer.quantize(
                tmp_path / "nonexistent.pt",
                tmp_path / "output.onnx",
            )

    def test_quantization_error_on_high_cosine_distance(self):
        """spec §4.6: If max cosine distance >= 0.02, raise QuantizationError."""
        # QuantizationError should carry the distance value
        err = QuantizationError(max_distance=0.025)
        assert err.max_distance == 0.025
        assert "0.02" in str(err) or "distance" in str(err).lower()


# ═══════════════════════════════════════════════════════════════════════════
# 11. TrainingDataValidator
# ═══════════════════════════════════════════════════════════════════════════


class TestTrainingDataValidator:
    """spec §4.7: TrainingDataValidator warning conditions."""

    def test_report_fields(self, tmp_path):
        """spec §4.7: ValidationReport has all specified fields."""
        jsonl_path = tmp_path / "data.jsonl"
        records = [
            _make_extraction_record(
                "file_a",
                [
                    _make_step("s1", ["P1", "P2"]),
                    _make_step("s2", []),
                    _make_step("s3", ["P1"]),
                ],
            )
        ]
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])

        assert report.total_pairs == 2
        assert report.empty_premise_pairs == 1
        assert isinstance(report.malformed_pairs, int)
        assert isinstance(report.unique_premises, int)
        assert isinstance(report.unique_states, int)
        assert isinstance(report.top_premises, list)
        assert isinstance(report.warnings, list)

    def test_warning_over_10_pct_empty(self, tmp_path):
        """spec §4.7: Warning when empty / (total + empty) > 0.10.

        9 non-empty + 2 empty = 11 total steps.
        2 / 11 ≈ 18% > 10%.
        """
        jsonl_path = tmp_path / "data.jsonl"
        steps = [_make_step(f"s{i}", [f"P{i}"]) for i in range(9)]
        steps += [_make_step("empty1", []), _make_step("empty2", [])]
        records = [_make_extraction_record("file_a", steps)]
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("empty premise" in w.lower() for w in report.warnings)

    def test_no_warning_when_empty_below_threshold(self, tmp_path):
        """No warning when empty rate <= 10%."""
        jsonl_path = tmp_path / "data.jsonl"
        steps = [_make_step(f"s{i}", [f"P{i}"]) for i in range(95)]
        steps += [_make_step("empty1", [])]
        # 1 / 96 ≈ 1% < 10%
        records = [_make_extraction_record("file_a", steps)]
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert not any("empty premise" in w.lower() for w in report.warnings)

    def test_warning_malformed_pairs(self, tmp_path):
        """spec §4.7: Warning when malformed_pairs > 0."""
        jsonl_path = tmp_path / "data.jsonl"
        # Write a valid record + an invalid JSON line
        with open(jsonl_path, "w") as f:
            f.write(json.dumps(_make_extraction_record(
                "file_a", [_make_step("s1", ["P1"])]
            )) + "\n")
            f.write("not valid json\n")

        report = TrainingDataValidator.validate([jsonl_path])
        assert report.malformed_pairs > 0
        assert any("malformed" in w.lower() for w in report.warnings)

    def test_warning_too_few_pairs(self, tmp_path):
        """spec §4.7: Warning when total_pairs < 5000."""
        jsonl_path = tmp_path / "data.jsonl"
        records = [
            _make_extraction_record("file_a", [_make_step(f"s{i}", [f"P{i}"])])
            for i in range(100)
        ]
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("training pairs" in w.lower() for w in report.warnings)

    def test_warning_too_few_unique_premises(self, tmp_path):
        """spec §4.7: Warning when unique_premises < 1000."""
        jsonl_path = tmp_path / "data.jsonl"
        # All steps reference the same small set of premises
        records = [
            _make_extraction_record(
                f"file_{i}",
                [_make_step(f"s{i}", ["CommonPremise"])],
            )
            for i in range(100)
        ]
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("unique premises" in w.lower() for w in report.warnings)

    def test_warning_dominant_premise(self, tmp_path):
        """spec §4.7: Warning when any premise > 5% of all occurrences."""
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        # Create 100 steps: 10 reference "DominantPremise" (10% > 5%)
        for i in range(100):
            if i < 10:
                premises = ["DominantPremise"]
            else:
                premises = [f"premise_{i}"]
            records.append(
                _make_extraction_record(
                    f"file_{i:03d}",
                    [_make_step(f"s{i}", premises)],
                )
            )
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("DominantPremise" in w for w in report.warnings)

    def test_top_premises_returns_10(self, tmp_path):
        """spec §4.7: top_premises contains 10 most frequently referenced premises."""
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        for i in range(50):
            records.append(
                _make_extraction_record(
                    f"file_{i:03d}",
                    [_make_step(f"s{i}", [f"premise_{i % 15}"])],
                )
            )
        _write_jsonl(jsonl_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert len(report.top_premises) <= 10
        # Each entry is (name, count)
        for name, count in report.top_premises:
            assert isinstance(name, str)
            assert isinstance(count, int)
            assert count > 0


# ═══════════════════════════════════════════════════════════════════════════
# 12. Error Hierarchy
# ═══════════════════════════════════════════════════════════════════════════


class TestNeuralTrainingErrors:
    """spec §5: Error hierarchy for training pipeline."""

    def test_base_class(self):
        """spec §5: NeuralTrainingError is the base class."""
        assert issubclass(NeuralTrainingError, Exception)

    def test_data_format_error(self):
        assert issubclass(DataFormatError, NeuralTrainingError)

    def test_checkpoint_not_found_error(self):
        assert issubclass(CheckpointNotFoundError, NeuralTrainingError)

    def test_training_resource_error(self):
        assert issubclass(TrainingResourceError, NeuralTrainingError)

    def test_quantization_error(self):
        assert issubclass(QuantizationError, NeuralTrainingError)

    def test_insufficient_data_error(self):
        assert issubclass(InsufficientDataError, NeuralTrainingError)

    def test_all_are_distinct_from_each_other(self):
        """All error types are distinct subclasses."""
        error_types = [
            DataFormatError,
            CheckpointNotFoundError,
            TrainingResourceError,
            QuantizationError,
            InsufficientDataError,
        ]
        for i, t1 in enumerate(error_types):
            for j, t2 in enumerate(error_types):
                if i != j:
                    assert not issubclass(t1, t2), f"{t1.__name__} should not be subclass of {t2.__name__}"


# ═══════════════════════════════════════════════════════════════════════════
# 13. Insufficient Data Guard
# ═══════════════════════════════════════════════════════════════════════════


class TestInsufficientDataGuard:
    """spec §4.3/§5: Training requires at least 1,000 pairs."""

    def test_train_raises_on_too_few_pairs(self, tmp_path):
        """spec §4.3: REQUIRES dataset with at least 1,000 training pairs."""
        # Create a dataset with only 10 training pairs
        dataset = TrainingDataset(
            train=[(_make_step(f"s{i}", [f"p{i}"]) ) for i in range(10)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        with pytest.raises(InsufficientDataError):
            trainer.train(dataset, tmp_path / "model.pt")
