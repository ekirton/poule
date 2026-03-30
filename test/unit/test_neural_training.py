"""TDD tests for neural training pipeline (specification/neural-training.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/neural/training/.

Covers: TrainingDataLoader (JSONL parsing, pair extraction from ExtractionRecord
goals/premises, hypothesis filtering, file-level split), serialize_goals,
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

from Poule.neural.training.data import (
    SplitReport,
    TrainingDataLoader,
    TrainingDataset,
    serialize_goals,
)
from Poule.neural.training.negatives import sample_hard_negatives
from Poule.neural.training.trainer import BiEncoderTrainer
from Poule.neural.training.evaluator import RetrievalEvaluator, EvaluationReport, ComparisonReport
from Poule.neural.training.quantizer import ModelQuantizer
from Poule.neural.training.validator import TrainingDataValidator, ValidationReport
from Poule.neural.training.vocabulary import VocabularyBuilder, VocabularyReport, CoqTokenizer
from Poule.neural.training.errors import (
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


def _make_goal(goal_type, hypotheses=None):
    """Create a Goal dict matching the ExtractionStep schema."""
    return {
        "index": 0,
        "type": goal_type,
        "hypotheses": hypotheses or [],
    }


def _make_hypothesis(name, hyp_type, body=None):
    """Create a Hypothesis dict."""
    return {"name": name, "type": hyp_type, "body": body}


def _make_premise(name, kind="lemma"):
    """Create a Premise dict with name and kind."""
    return {"name": name, "kind": kind}


def _make_step(step_index, tactic, goals, premises=None):
    """Create an ExtractionStep dict matching the data model.

    goals: list of Goal dicts (from _make_goal)
    premises: list of Premise dicts (from _make_premise), defaults to []
    """
    return {
        "step_index": step_index,
        "tactic": tactic,
        "goals": goals,
        "focused_goal_index": 0 if goals else None,
        "premises": premises or [],
    }


def _make_extraction_record(source_file, steps):
    """Create a minimal ExtractionRecord dict for testing."""
    return {
        "schema_version": 1,
        "record_type": "proof_trace",
        "theorem_name": f"{source_file}.test_thm",
        "source_file": source_file,
        "project_id": "test-project",
        "total_steps": len(steps) - 1,  # N tactics for N+1 steps
        "steps": steps,
    }


def _make_simple_proof(source_file, initial_goal, tactic_steps):
    """Create a complete proof record with initial state + tactic steps.

    tactic_steps: list of (tactic_text, goal_after, premises_list)
    where premises_list is [(name, kind), ...]
    """
    steps = [
        _make_step(0, None, [_make_goal(initial_goal)]),
    ]
    for i, (tactic, goal_after, premises) in enumerate(tactic_steps, 1):
        premise_dicts = [_make_premise(n, k) for n, k in premises]
        steps.append(
            _make_step(i, tactic, [_make_goal(goal_after)], premise_dicts)
        )
    return _make_extraction_record(source_file, steps)


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
# 1. serialize_goals — Proof State Text Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestSerializeGoals:
    """spec §4.1: serialize_goals converts Goal objects to text for encoder input."""

    def test_single_goal_no_hypotheses(self):
        """A single goal with no hypotheses serializes to just the goal type."""
        goals = [_make_goal("forall n : nat, n + 0 = n")]
        result = serialize_goals(goals)
        assert "forall n : nat, n + 0 = n" in result

    def test_single_goal_with_hypotheses(self):
        """Hypotheses are serialized as 'name : type' before the goal."""
        goals = [_make_goal(
            "n + 0 = n",
            [_make_hypothesis("n", "nat"), _make_hypothesis("m", "nat")]
        )]
        result = serialize_goals(goals)
        assert "n : nat" in result
        assert "m : nat" in result
        assert "n + 0 = n" in result

    def test_multiple_goals_separated(self):
        """Multiple goals are separated (by blank line or delimiter)."""
        goals = [
            _make_goal("n + 0 = n"),
            _make_goal("m + 0 = m"),
        ]
        result = serialize_goals(goals)
        assert "n + 0 = n" in result
        assert "m + 0 = m" in result

    def test_deterministic(self):
        """Same goals produce identical text."""
        goals = [_make_goal("n = n", [_make_hypothesis("n", "nat")])]
        assert serialize_goals(goals) == serialize_goals(goals)

    def test_empty_goals_returns_empty_string(self):
        """Empty goal list produces empty string."""
        assert serialize_goals([]) == ""


# ═══════════════════════════════════════════════════════════════════════════
# 2. TrainingDataLoader — Pair Extraction (Step Pairing)
# ═══════════════════════════════════════════════════════════════════════════


class TestPairExtraction:
    """spec §4.1: Pair extraction from ExtractionRecords.

    Training pairs use goals from step k-1 paired with premises from step k.
    """

    def test_pairs_previous_step_goals_with_current_step_premises(self, tmp_path):
        """spec §4.1: proof_state = steps[k-1].goals, premises = steps[k].premises.

        Given a 3-step proof (step 0 = initial, steps 1-2 = tactics):
        - Step 0: initial goals = "forall n : nat, n + 0 = n"
        - Step 1: tactic "intros n.", goals after = "n + 0 = n", premises = [Nat.add_0_r]
        - Step 2: tactic "apply Nat.add_comm.", goals after = [], premises = [Nat.add_comm]

        Pair for step 1: (serialize(step[0].goals), step[1].premises) = ("forall n...", [Nat.add_0_r])
        Pair for step 2: (serialize(step[1].goals), step[2].premises) = ("n + 0 = n", [Nat.add_comm])
        """
        record = _make_simple_proof(
            "Stdlib.Init.Nat",
            "forall n : nat, n + 0 = n",
            [
                ("intros n.", "n + 0 = n", [("Nat.add_0_r", "lemma")]),
                ("apply Nat.add_comm.", "", [("Nat.add_comm", "lemma")]),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "Nat.add_0_r", "stmt1", "Stdlib.Init.Nat"),
            (2, "Nat.add_comm", "stmt2", "Stdlib.Init.Nat"),
        ])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test

        assert len(all_pairs) == 2

        # Pair 1: state before step 1 = step 0's goals
        state_1, premises_1 = all_pairs[0]
        assert "forall n : nat, n + 0 = n" in state_1
        assert premises_1 == ["Nat.add_0_r"]

        # Pair 2: state before step 2 = step 1's goals
        state_2, premises_2 = all_pairs[1]
        assert "n + 0 = n" in state_2
        assert premises_2 == ["Nat.add_comm"]

    def test_skips_steps_with_empty_premises(self, tmp_path):
        """spec §4.1: Steps with empty premise lists shall be skipped."""
        record = _make_simple_proof(
            "Stdlib.Init.Nat",
            "forall n : nat, n = n",
            [
                ("intros n.", "n = n", []),  # reflexivity — no premises
                ("reflexivity.", "", []),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 0

    def test_step_0_is_never_used_as_source_of_premises(self, tmp_path):
        """spec §4.1: Step 0 has no tactic and no premises — only used as state source."""
        record = _make_extraction_record(
            "Stdlib.Init.Nat",
            [
                _make_step(0, None, [_make_goal("initial goal")]),
                _make_step(1, "apply P.", [_make_goal("subgoal")],
                           [_make_premise("P", "lemma")]),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "P", "stmt", "mod")])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        # Only 1 pair: (step[0].goals, step[1].premises)
        assert len(all_pairs) == 1
        state, premises = all_pairs[0]
        assert "initial goal" in state
        assert premises == ["P"]

    def test_handles_multiple_jsonl_files(self, tmp_path):
        """spec §4.1: load accepts a list of JSONL paths."""
        file1 = _write_full_and_convert(tmp_path, [
            _make_simple_proof("FileA", "goal_a",
                               [("t1.", "g1", [("P1", "lemma")])]),
        ], name="a")
        file2 = _write_full_and_convert(tmp_path, [
            _make_simple_proof("FileB", "goal_b",
                               [("t2.", "g2", [("P2", "lemma")])]),
        ], name="b")

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "P1", "stmt1", "FileA"),
            (2, "P2", "stmt2", "FileB"),
        ])

        dataset = TrainingDataLoader.load([file1, file2], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 2

    def test_gwt_example_from_spec(self, tmp_path):
        """spec §4.1 GWT: 6 steps (0=initial, 1-5=tactics), steps 1,3,4 have global premises.

        Given an ExtractionRecord with 6 steps, steps 1, 3, 4 have non-empty
        global premises after hypothesis filtering
        When pairs are extracted
        Then 3 training pairs are emitted
        """
        steps = [
            _make_step(0, None, [_make_goal("initial")]),
            _make_step(1, "t1.", [_make_goal("g1")], [_make_premise("P1", "lemma")]),
            _make_step(2, "t2.", [_make_goal("g2")], []),  # empty
            _make_step(3, "t3.", [_make_goal("g3")], [_make_premise("P3", "lemma")]),
            _make_step(4, "t4.", [_make_goal("g4")], [_make_premise("P4", "definition")]),
            _make_step(5, "t5.", [_make_goal("g5")], []),  # empty
        ]
        record = _make_extraction_record("Stdlib.Init.Nat", steps)
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "P1", "s1", "mod"), (3, "P3", "s3", "mod"), (4, "P4", "s4", "mod"),
        ])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 3


# ═══════════════════════════════════════════════════════════════════════════
# 3. TrainingDataLoader — Hypothesis Filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisFiltering:
    """spec §4.1: Premises with kind == 'hypothesis' shall be excluded."""

    def test_filters_out_hypothesis_kind_premises(self, tmp_path):
        """spec §4.1: Local hypotheses are excluded from premises_used."""
        record = _make_simple_proof(
            "Stdlib.Init.Nat",
            "forall n : nat, n + 0 = n",
            [
                ("rewrite H.", "subgoal", [
                    ("Nat.add_comm", "lemma"),
                    ("H", "hypothesis"),  # should be filtered
                ]),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "Nat.add_comm", "stmt", "Stdlib.Init.Nat"),
        ])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 1
        _, premises = all_pairs[0]
        assert premises == ["Nat.add_comm"]
        assert "H" not in premises

    def test_skips_steps_where_all_premises_are_hypotheses(self, tmp_path):
        """spec §4.1 GWT: Step with only hypothesis premises is skipped."""
        record = _make_simple_proof(
            "Stdlib.Init.Nat",
            "forall n : nat, n = n",
            [
                ("exact H.", "done", [
                    ("H", "hypothesis"),
                    ("H2", "hypothesis"),
                ]),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 0

    def test_keeps_non_hypothesis_premise_kinds(self, tmp_path):
        """Premises of kind lemma, definition, constructor are kept."""
        record = _make_simple_proof(
            "Stdlib.Init.Nat",
            "goal",
            [
                ("t1.", "g1", [("L", "lemma"), ("D", "definition"), ("C", "constructor")]),
            ],
        )
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "L", "s1", "m"), (2, "D", "s2", "m"), (3, "C", "s3", "m"),
        ])

        dataset = TrainingDataLoader.load([jsonl_path], db_path)
        all_pairs = dataset.train + dataset.val + dataset.test
        assert len(all_pairs) == 1
        _, premises = all_pairs[0]
        assert set(premises) == {"L", "D", "C"}


# ═══════════════════════════════════════════════════════════════════════════
# 4. TrainingDataLoader — File-Level Split
# ═══════════════════════════════════════════════════════════════════════════


class TestFileLevelSplit:
    """spec §4.1: Deterministic train/val/test split by source file position."""

    def test_split_positions_for_10_files(self, tmp_path):
        """spec §4.1: position % 10 == 8 → val, == 9 → test, else → train."""
        records = []
        for i in range(10):
            records.append(_make_simple_proof(
                f"file_{i:02d}", f"goal_{i}",
                [(f"t{i}.", f"g{i}", [(f"premise_{i}", "lemma")])],
            ))
        jsonl_path = _write_full_and_convert(tmp_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"premise_{i}", f"stmt_{i}", f"file_{i:02d}") for i in range(10)]
        _make_minimal_index_db(db_path, decls)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)

        # Files sorted: file_00..file_09; position 8→val, 9→test, 0-7→train
        assert len(dataset.train) == 8
        assert len(dataset.val) == 1
        assert len(dataset.test) == 1

    def test_split_positions_for_100_files(self, tmp_path):
        """spec §4.1: Given 100 files, indices 8,18,28,...→val; 9,19,29,...→test."""
        records = []
        for i in range(100):
            records.append(_make_simple_proof(
                f"file_{i:03d}", f"goal_{i}",
                [(f"t{i}.", f"g{i}", [(f"premise_{i}", "lemma")])],
            ))
        jsonl_path = _write_full_and_convert(tmp_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"premise_{i}", f"stmt_{i}", f"file_{i:03d}") for i in range(100)]
        _make_minimal_index_db(db_path, decls)

        dataset = TrainingDataLoader.load([jsonl_path], db_path)

        assert len(dataset.train) == 80
        assert len(dataset.val) == 10
        assert len(dataset.test) == 10

    def test_no_pair_in_multiple_splits(self, tmp_path):
        """spec §4.1 MAINTAINS: No pair from same file in more than one split."""
        records = []
        for i in range(20):
            # Multiple tactic steps per proof
            records.append(_make_simple_proof(
                f"file_{i:02d}", f"goal_{i}",
                [
                    (f"t{i}a.", f"ga_{i}", [(f"premise_{i}", "lemma")]),
                    (f"t{i}b.", f"gb_{i}", [(f"premise_{i}", "lemma")]),
                ],
            ))
        jsonl_path = _write_full_and_convert(tmp_path, records)

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
        records = [
            _make_simple_proof(f"file_{i:02d}", f"g{i}",
                               [(f"t{i}.", f"ga{i}", [(f"p{i}", "lemma")])])
            for i in range(15)
        ]
        jsonl_path = _write_full_and_convert(tmp_path, records)

        db_path = tmp_path / "index.db"
        decls = [(i + 1, f"p{i}", f"stmt_{i}", f"file_{i:02d}") for i in range(15)]
        _make_minimal_index_db(db_path, decls)

        d1 = TrainingDataLoader.load([jsonl_path], db_path)
        d2 = TrainingDataLoader.load([jsonl_path], db_path)

        assert d1.train == d2.train
        assert d1.val == d2.val
        assert d1.test == d2.test


# ═══════════════════════════════════════════════════════════════════════════
# 5. Hard Negative Sampling
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
# 6. BiEncoderTrainer — Hyperparameters
# ═══════════════════════════════════════════════════════════════════════════


class TestBiEncoderTrainerHyperparams:
    """spec §4.3: Default hyperparameters and constraints."""

    def test_default_hyperparameters(self):
        """spec §4.3: Verify default hyperparameter values."""
        trainer = BiEncoderTrainer()
        assert trainer.hyperparams["batch_size"] == 128
        assert trainer.hyperparams["learning_rate"] == 5e-5
        assert trainer.hyperparams["weight_decay"] == 1e-2
        assert trainer.hyperparams["temperature"] == 0.05
        assert trainer.hyperparams["hard_negatives_per_state"] == 3
        assert trainer.hyperparams["max_seq_length"] == 256
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
# 7. BiEncoderTrainer — Early Stopping
# ═══════════════════════════════════════════════════════════════════════════


class TestEarlyStopping:
    """spec §4.3: Early stopping based on validation Recall@32."""

    def test_stops_after_patience_epochs_without_improvement(self):
        """spec §4.3: Given patience=3, stops after 3 epochs with no R@32 improvement.

        Given patience=3 and validation R@32 does not improve for epochs 8, 9, 10
        When epoch 10 completes
        Then training stops and the checkpoint from epoch 7 is retained.
        """
        from Poule.neural.training.trainer import EarlyStoppingTracker

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
        from Poule.neural.training.trainer import EarlyStoppingTracker

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
# 8. BiEncoderTrainer — Checkpoint Format
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckpointFormat:
    """spec §4.3: Checkpoint includes required fields."""

    def test_checkpoint_contains_required_fields(self, tmp_path):
        """spec §4.3: Checkpoint shall include model state, optimizer state,
        epoch number, best validation R@32, and hyperparameters."""
        from Poule.neural.training.trainer import save_checkpoint, load_checkpoint

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
# 9. Fine-Tuning
# ═══════════════════════════════════════════════════════════════════════════


class TestFineTuning:
    """spec §4.4: Fine-tuning hyperparameter overrides."""

    def test_fine_tune_default_overrides(self):
        """spec §4.4: Fine-tuning defaults to lr=5e-6 and max_epochs=10."""
        from Poule.neural.training.trainer import get_fine_tune_hyperparams

        params = get_fine_tune_hyperparams()
        assert params["learning_rate"] == 5e-6
        assert params["max_epochs"] == 10
        # Other defaults remain from base
        assert params["batch_size"] == 128
        assert params["temperature"] == 0.05

    def test_fine_tune_accepts_custom_overrides(self):
        """spec §4.4: Caller can still override fine-tuning defaults."""
        from Poule.neural.training.trainer import get_fine_tune_hyperparams

        params = get_fine_tune_hyperparams(overrides={"learning_rate": 1e-6})
        assert params["learning_rate"] == 1e-6
        assert params["max_epochs"] == 10  # fine-tune default retained


# ═══════════════════════════════════════════════════════════════════════════
# 10. RetrievalEvaluator — Evaluation Report
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
# 11. RetrievalEvaluator — Comparison Report
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
# 12. ModelQuantizer
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
        err = QuantizationError(max_distance=0.025)
        assert err.max_distance == 0.025
        assert "0.02" in str(err) or "distance" in str(err).lower()


# ═══════════════════════════════════════════════════════════════════════════
# 13. TrainingDataValidator
# ═══════════════════════════════════════════════════════════════════════════


class TestTrainingDataValidator:
    """spec §4.7: TrainingDataValidator warning conditions.

    The validator scans ExtractionRecords for training data quality.
    It reads the goals field (not state_before) from each step.
    """

    def _make_validator_record(self, source_file, step_data):
        """Create an ExtractionRecord for validator testing.

        step_data: list of (goals_list, premises_list)
        where goals_list is list of Goal dicts, premises_list is list of Premise dicts.
        """
        steps = [_make_step(0, None, [_make_goal("initial")])]
        for i, (goals, premises) in enumerate(step_data, 1):
            steps.append(_make_step(i, f"t{i}.", goals, premises))
        return _make_extraction_record(source_file, steps)

    def test_report_fields(self, tmp_path):
        """spec §4.7: ValidationReport has all specified fields."""
        record = self._make_validator_record("file_a", [
            ([_make_goal("g1")], [_make_premise("P1"), _make_premise("P2")]),
            ([_make_goal("g2")], []),  # empty premises
            ([_make_goal("g3")], [_make_premise("P1")]),
        ])
        jsonl_path = _write_full_and_convert(tmp_path, [record])

        report = TrainingDataValidator.validate([jsonl_path])

        # Compact format: empty-premise steps are filtered during conversion
        assert report.total_pairs == 2
        assert report.empty_premise_pairs == 0
        assert isinstance(report.malformed_pairs, int)
        assert isinstance(report.unique_premises, int)
        assert isinstance(report.unique_states, int)
        assert isinstance(report.top_premises, list)
        assert isinstance(report.warnings, list)

    def test_no_empty_premise_warning_in_compact_format(self, tmp_path):
        """Compact format: empty-premise steps are filtered during conversion,
        so the validator never sees them and no empty-premise warning fires."""
        step_data = [
            ([_make_goal(f"g{i}")], [_make_premise(f"P{i}")]) for i in range(9)
        ] + [
            ([_make_goal("empty1")], []),
            ([_make_goal("empty2")], []),
        ]
        records = [self._make_validator_record("file_a", step_data)]
        jsonl_path = _write_full_and_convert(tmp_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        # Only 9 pairs survive conversion (2 empty-premise steps filtered out)
        assert report.total_pairs == 9
        assert report.empty_premise_pairs == 0
        assert not any("empty premise" in w.lower() for w in report.warnings)

    def test_warning_malformed_pairs(self, tmp_path):
        """spec §4.7: Warning when malformed_pairs > 0."""
        jsonl_path = tmp_path / "data.jsonl"
        with open(jsonl_path, "w") as f:
            f.write(json.dumps({"t": "p", "f": "file_a", "s": "g1", "p": ["P1"]}) + "\n")
            f.write("not valid json\n")

        report = TrainingDataValidator.validate([jsonl_path])
        assert report.malformed_pairs > 0
        assert any("malformed" in w.lower() for w in report.warnings)

    def test_warning_too_few_pairs(self, tmp_path):
        """spec §4.7: Warning when total_pairs < 5000."""
        records = [
            self._make_validator_record(f"file_{i}", [
                ([_make_goal(f"g{i}")], [_make_premise(f"P{i}")]),
            ]) for i in range(100)
        ]
        jsonl_path = _write_full_and_convert(tmp_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("training pairs" in w.lower() for w in report.warnings)

    def test_warning_too_few_unique_premises(self, tmp_path):
        """spec §4.7: Warning when unique_premises < 1000."""
        records = [
            self._make_validator_record(f"file_{i}", [
                ([_make_goal(f"g{i}")], [_make_premise("CommonPremise")]),
            ]) for i in range(100)
        ]
        jsonl_path = _write_full_and_convert(tmp_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("unique premises" in w.lower() for w in report.warnings)

    def test_warning_dominant_premise(self, tmp_path):
        """spec §4.7: Warning when any premise > 5% of all occurrences."""
        jsonl_path = tmp_path / "data.jsonl"
        records = []
        for i in range(100):
            if i < 10:
                premises = [_make_premise("DominantPremise")]
            else:
                premises = [_make_premise(f"premise_{i}")]
            records.append(self._make_validator_record(
                f"file_{i:03d}",
                [([_make_goal(f"g{i}")], premises)],
            ))
        jsonl_path = _write_full_and_convert(tmp_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert any("DominantPremise" in w for w in report.warnings)

    def test_top_premises_returns_10(self, tmp_path):
        """spec §4.7: top_premises contains 10 most frequently referenced premises."""
        records = []
        for i in range(50):
            records.append(self._make_validator_record(
                f"file_{i:03d}",
                [([_make_goal(f"g{i}")], [_make_premise(f"premise_{i % 15}")])],
            ))
        jsonl_path = _write_full_and_convert(tmp_path, records)

        report = TrainingDataValidator.validate([jsonl_path])
        assert len(report.top_premises) <= 10
        for name, count in report.top_premises:
            assert isinstance(name, str)
            assert isinstance(count, int)
            assert count > 0


# ═══════════════════════════════════════════════════════════════════════════
# 14. Error Hierarchy
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
# 15. Insufficient Data Guard
# ═══════════════════════════════════════════════════════════════════════════


class TestInsufficientDataGuard:
    """spec §4.3/§5: Training requires at least 1,000 pairs."""

    def test_train_raises_on_too_few_pairs(self, tmp_path):
        """spec §4.3: REQUIRES dataset with at least 1,000 training pairs."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(10)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        with pytest.raises(InsufficientDataError):
            trainer.train(dataset, tmp_path / "model.pt")

    def test_train_raises_on_too_few_pairs_after_sampling(self, tmp_path):
        """spec §4.3: Minimum 1,000 pairs checked after sampling."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(2000)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        # sample=0.1 → 200 pairs, below the 1,000 minimum
        with pytest.raises(InsufficientDataError):
            trainer.train(dataset, tmp_path / "model.pt", sample=0.1)


class TestTrainSampleParameter:
    """spec §4.3: --sample sub-samples the training split for test runs."""

    def test_sample_reduces_training_pairs(self):
        """sample=0.5 should halve the training set."""
        original = [("state", ["premise"]) for _ in range(10000)]
        dataset = TrainingDataset(
            train=original,
            val=[("v", ["p"])],
            test=[("t", ["p"])],
            premise_corpus={"premise": "stmt"},
        )
        trainer = BiEncoderTrainer()
        with patch.object(trainer, "_train_impl") as mock_impl:
            trainer.train(dataset, Path("/fake/out.pt"), sample=0.5)
            called_dataset = mock_impl.call_args[0][0]
            assert len(called_dataset.train) == 5000

    def test_sample_does_not_affect_val_or_test(self):
        """Validation and test splits are not affected by --sample."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(5000)],
            val=[("v", ["p"]) for _ in range(500)],
            test=[("t", ["p"]) for _ in range(500)],
            premise_corpus={"premise": "stmt"},
        )
        trainer = BiEncoderTrainer()
        with patch.object(trainer, "_train_impl") as mock_impl:
            trainer.train(dataset, Path("/fake/out.pt"), sample=0.5)
            called_dataset = mock_impl.call_args[0][0]
            assert len(called_dataset.val) == 500
            assert len(called_dataset.test) == 500

    def test_sample_none_uses_full_dataset(self):
        """sample=None uses the full training set."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(5000)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        with patch.object(trainer, "_train_impl") as mock_impl:
            trainer.train(dataset, Path("/fake/out.pt"), sample=None)
            called_dataset = mock_impl.call_args[0][0]
            assert len(called_dataset.train) == 5000

    def test_sample_one_uses_full_dataset(self):
        """sample=1.0 uses the full training set."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(5000)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        with patch.object(trainer, "_train_impl") as mock_impl:
            trainer.train(dataset, Path("/fake/out.pt"), sample=1.0)
            called_dataset = mock_impl.call_args[0][0]
            assert len(called_dataset.train) == 5000

    def test_sample_rounds_up(self):
        """sample should use ceil to avoid rounding to zero."""
        dataset = TrainingDataset(
            train=[("state", ["premise"]) for _ in range(3000)],
            val=[],
            test=[],
            premise_corpus={},
        )
        trainer = BiEncoderTrainer()
        # 0.5 * 3000 = 1500 — exact
        with patch.object(trainer, "_train_impl") as mock_impl:
            trainer.train(dataset, Path("/fake/out.pt"), sample=0.5)
            called_dataset = mock_impl.call_args[0][0]
            assert len(called_dataset.train) == 1500


# ═══════════════════════════════════════════════════════════════════════════
# 16. VocabularyBuilder — Closed Vocabulary Construction
# ═══════════════════════════════════════════════════════════════════════════


class TestVocabularyBuilderSpecialTokens:
    """spec §4.0: Special tokens [PAD], [UNK], [CLS], [SEP], [MASK] at IDs 0–4."""

    def test_special_tokens_at_fixed_ids(self, tmp_path):
        """spec §4.0: Special tokens are always at IDs 0–4."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "Nat.add", "stmt", "Stdlib.Init.Nat")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        assert vocab["[PAD]"] == 0
        assert vocab["[UNK]"] == 1
        assert vocab["[CLS]"] == 2
        assert vocab["[SEP]"] == 3
        assert vocab["[MASK]"] == 4

    def test_special_tokens_always_present(self, tmp_path):
        """spec §4.0: Special tokens are always present regardless of input data."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "X.y", "stmt", "X")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]:
            assert token in vocab


class TestVocabularyBuilderFixedTokens:
    """spec §4.0: Fixed token sets (punctuation, Unicode, Greek, etc.)."""

    def test_punctuation_tokens_present(self, tmp_path):
        """spec §4.0: Punctuation and delimiters are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["(", ")", "{", "}", "[", "]", ":", ";", ",", ".", "|",
                       "@", "!", "?", "_", "'", "#", "=", "+", "-", "*", "/",
                       "<", ">", "~"]:
            assert token in vocab, f"Missing punctuation token: {token}"

    def test_unicode_math_symbols_present(self, tmp_path):
        """spec §4.0: Unicode mathematical symbols are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["∀", "∃", "→", "←", "↔", "⊢", "≤", "≥", "≠", "≡",
                       "∧", "∨", "¬", "⊆", "ℕ", "ℤ"]:
            assert token in vocab, f"Missing Unicode symbol: {token}"

    def test_greek_letters_present(self, tmp_path):
        """spec §4.0: Greek letters are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["α", "β", "γ", "δ", "ε", "λ", "π", "σ", "ω",
                       "Γ", "Δ", "Σ", "Ω"]:
            assert token in vocab, f"Missing Greek letter: {token}"

    def test_ssreflect_tacticals_present(self, tmp_path):
        """spec §4.0: SSReflect tacticals are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["/=", "//", "//=", "=>", "->", "<-"]:
            assert token in vocab, f"Missing SSReflect tactical: {token}"

    def test_scope_delimiters_present(self, tmp_path):
        """spec §4.0: Scope delimiters are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in ["%N", "%Z", "%R", "%Q", "%positive", "%type"]:
            assert token in vocab, f"Missing scope delimiter: {token}"

    def test_digits_present(self, tmp_path):
        """spec §4.0: Individual digits 0–9 are always included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for digit in "0123456789":
            assert digit in vocab, f"Missing digit: {digit}"

    def test_fixed_tokens_after_special_tokens(self, tmp_path):
        """spec §4.0: Fixed token IDs start after special tokens (ID >= 5)."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        # All fixed tokens (non-special) should have IDs >= 5
        for token, token_id in vocab.items():
            if token.startswith("[") and token.endswith("]"):
                continue  # skip special tokens
            assert token_id >= 5, f"Fixed token {token} has ID {token_id} < 5"


class TestVocabularyBuilderIndexExtraction:
    """spec §4.0: Token extraction from the search index declarations."""

    def test_all_declaration_names_in_vocabulary(self, tmp_path):
        """spec §4.0: Every declaration name in the index appears in the vocabulary."""
        declarations = [
            (1, "Nat.add_comm", "stmt1", "Stdlib.Init.Nat"),
            (2, "List.forall2_cons", "stmt2", "Stdlib.Lists.List"),
            (3, "ssralg.GRing.mul", "stmt3", "mathcomp.algebra.ssralg"),
        ]
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, declarations)
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for _, name, _, _ in declarations:
            assert name in vocab, f"Declaration {name} missing from vocabulary"

    def test_declaration_ids_after_fixed_tokens(self, tmp_path):
        """spec §4.0: Declaration names get IDs after all fixed token sets."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "Nat.add", "stmt", "Stdlib.Init.Nat")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        # Fixed tokens include special (5) + punctuation (~25) + tacticals (6) +
        # scope delimiters (6) + unicode (~30) + greek (~33) + digits (10) = ~115
        # Declaration IDs should be after all fixed tokens
        fixed_count = sum(1 for _, v in vocab.items()
                          if v < vocab["Nat.add"])
        assert fixed_count >= 5 + 25  # at least special + punctuation

    def test_declarations_sorted_lexicographically(self, tmp_path):
        """spec §4.0: Declaration names are sorted lexicographically."""
        declarations = [
            (1, "Z.add", "stmt1", "Stdlib.ZArith"),
            (2, "A.foo", "stmt2", "Stdlib.Init"),
            (3, "M.bar", "stmt3", "Stdlib.Lists"),
        ]
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, declarations)
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        assert vocab["A.foo"] < vocab["M.bar"] < vocab["Z.add"]


class TestVocabularyBuilderTrainingDataExtraction:
    """spec §4.0: Token extraction from serialized proof states in training data."""

    def test_hypothesis_variable_names_added(self, tmp_path):
        """spec §4.0: Hypothesis variable names from proof states are included."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "Nat.add", "stmt", "Stdlib.Init.Nat")])

        # Compact format: "s" contains the serialized proof state text
        # that serialize_goals would produce, with hypothesis names as tokens.
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [
            {"t": "p", "f": "Stdlib.Init.Nat", "s": "myvar : nat\nH_special : myvar > 0\nforall n : nat, n + 0 = n", "p": ["Nat.add"]},
        ])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        assert "myvar" in vocab
        assert "H_special" in vocab

    def test_training_data_tokens_no_duplicates(self, tmp_path):
        """spec §4.0: Tokens from training data already in vocab are not duplicated."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "nat", "stmt", "Stdlib.Init")])

        # "nat" appears both in the index and in proof state text
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [
            {"t": "p", "f": "Stdlib.Init.Nat", "s": "forall n : nat, n = n", "p": ["nat"]},
        ])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        # "nat" should appear exactly once
        nat_occurrences = [k for k in vocab if k == "nat"]
        assert len(nat_occurrences) == 1

    def test_training_data_tokens_sorted_lexicographically(self, tmp_path):
        """spec §4.0: Tokens from training data are sorted lexicographically."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "X.y", "stmt", "X")])

        # Compact format: "s" contains hypothesis names and goal type as tokens.
        # serialize_goals would produce "zebra : animal\nalpha_var : nat\nforall zebra : animal, True"
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [
            {"t": "p", "f": "X", "s": "zebra : animal\nalpha_var : nat\nforall zebra : animal, True", "p": ["X.y"]},
        ])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        # Tokens from training data (not already in index/fixed) should be sorted
        # "alpha_var" < "zebra" lexicographically
        if "alpha_var" in vocab and "zebra" in vocab:
            assert vocab["alpha_var"] < vocab["zebra"]

    def test_skips_non_proof_trace_records(self, tmp_path):
        """spec §4.0: Non-pair/goal records (metadata, summary) are skipped."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "X.y", "stmt", "X")])

        records = [
            {"record_type": "campaign_metadata", "coq_version": "8.18"},
            {"t": "p", "f": "X", "s": "True", "p": ["X.y"]},
            {"record_type": "extraction_summary", "found": 1, "extracted": 1},
        ]
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, records)
        output_path = tmp_path / "vocab.json"

        report = VocabularyBuilder.build(db_path, [jsonl_path], output_path)
        # Should not crash and should still produce a valid vocabulary
        vocab = json.loads(output_path.read_text())
        assert "[PAD]" in vocab


class TestVocabularyBuilderUnicodeNormalization:
    """spec §4.0: NFC Unicode normalization applied before insertion."""

    def test_nfc_normalization_applied(self, tmp_path):
        """spec §4.0: All keys in the output JSON are NFC-normalized."""
        import unicodedata

        db_path = tmp_path / "index.db"
        # Use a declaration name that might have non-NFC form
        _make_minimal_index_db(db_path, [(1, "A.b", "stmt", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token in vocab:
            assert token == unicodedata.normalize("NFC", token), \
                f"Token {token!r} is not NFC-normalized"


class TestVocabularyBuilderContiguousIDs:
    """spec §4.0: IDs are contiguous with no gaps; bijective mapping."""

    def test_ids_contiguous(self, tmp_path):
        """spec §4.0: IDs are contiguous (no gaps)."""
        declarations = [
            (1, "A.x", "s1", "A"),
            (2, "B.y", "s2", "B"),
            (3, "C.z", "s3", "C"),
        ]
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, declarations)
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        ids = sorted(vocab.values())
        assert ids == list(range(len(ids))), "IDs are not contiguous"

    def test_ids_are_unique(self, tmp_path):
        """spec §4.0: Each ID maps to exactly one token."""
        declarations = [
            (1, "A.x", "s1", "A"),
            (2, "B.y", "s2", "B"),
        ]
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, declarations)
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        ids = list(vocab.values())
        assert len(ids) == len(set(ids)), "Duplicate IDs found"

    def test_tokens_are_unique(self, tmp_path):
        """spec §4.0: Each token maps to exactly one ID."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.x", "s1", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        tokens = list(vocab.keys())
        assert len(tokens) == len(set(tokens)), "Duplicate tokens found"


class TestVocabularyBuilderReport:
    """spec §4.0: VocabularyReport fields."""

    def test_report_fields(self, tmp_path):
        """spec §4.0: build returns a VocabularyReport with correct counts."""
        declarations = [
            (1, "Nat.add", "s1", "Stdlib.Init.Nat"),
            (2, "List.map", "s2", "Stdlib.Lists.List"),
        ]
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, declarations)

        # Compact format: "s" contains tokens that serialize_goals would produce.
        # "unique_test_var" must appear as a token the vocab builder can discover.
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [
            {"t": "p", "f": "Stdlib.Init.Nat", "s": "unique_test_var : nat\nforall n : nat, True", "p": ["Nat.add"]},
        ])
        output_path = tmp_path / "vocab.json"

        report = VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        assert isinstance(report, VocabularyReport)
        assert report.special_tokens == 5
        assert report.index_tokens == 2  # Nat.add, List.map
        assert report.fixed_tokens > 0
        assert report.training_data_tokens >= 1  # at least "unique_test_var"
        assert report.total_tokens == (
            report.special_tokens + report.fixed_tokens +
            report.index_tokens + report.training_data_tokens
        )
        assert str(report.output_path) == str(output_path)

    def test_report_total_matches_vocab_size(self, tmp_path):
        """spec §4.0: total_tokens matches the number of entries in the JSON."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.x", "s1", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        report = VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        assert report.total_tokens == len(vocab)


class TestVocabularyBuilderErrors:
    """spec §5: Error conditions for vocabulary building."""

    def test_raises_on_empty_index(self, tmp_path):
        """spec §5: No declarations in index raises InsufficientDataError."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [])  # empty declarations
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        with pytest.raises(InsufficientDataError, match="No declarations"):
            VocabularyBuilder.build(db_path, [jsonl_path], output_path)

    def test_raises_on_missing_index_db(self, tmp_path):
        """spec §5: Missing index database raises FileNotFoundError."""
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        with pytest.raises(FileNotFoundError):
            VocabularyBuilder.build(
                tmp_path / "nonexistent.db", [jsonl_path], output_path
            )

    def test_raises_on_missing_jsonl_file(self, tmp_path):
        """spec §5: Missing JSONL file raises FileNotFoundError."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.x", "s1", "A")])
        output_path = tmp_path / "vocab.json"

        with pytest.raises(FileNotFoundError):
            VocabularyBuilder.build(
                db_path, [tmp_path / "nonexistent.jsonl"], output_path
            )


class TestVocabularyBuilderOutputFormat:
    """spec §4.0: Output format — valid JSON, UTF-8."""

    def test_output_is_valid_json(self, tmp_path):
        """spec §4.0: The output is valid JSON."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.x", "s1", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        # Should not raise
        vocab = json.loads(output_path.read_text(encoding="utf-8"))
        assert isinstance(vocab, dict)

    def test_output_values_are_integers(self, tmp_path):
        """spec §4.0: All values in the JSON are integer IDs."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "A.x", "s1", "A")])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        output_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], output_path)

        vocab = json.loads(output_path.read_text())
        for token, token_id in vocab.items():
            assert isinstance(token_id, int), \
                f"Token {token} has non-integer ID: {type(token_id)}"


# ═══════════════════════════════════════════════════════════════════════════
# 17. CoqTokenizer — Closed Vocabulary Tokenization
# ═══════════════════════════════════════════════════════════════════════════


def _write_vocab(path, tokens):
    """Write a minimal vocabulary JSON file from a list of token strings.

    Special tokens [PAD], [UNK], [CLS], [SEP], [MASK] are always included
    at IDs 0–4. Additional tokens get sequential IDs starting from 5.
    """
    vocab = {
        "[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "[MASK]": 4,
    }
    next_id = 5
    for t in tokens:
        if t not in vocab:
            vocab[t] = next_id
            next_id += 1
    path.write_text(json.dumps(vocab), encoding="utf-8")
    return vocab


class TestCoqTokenizerInit:
    """spec §4.0.1: CoqTokenizer loads vocabulary and sets special token IDs."""

    def test_loads_vocabulary(self, tmp_path):
        """spec §4.0.1: Loads the vocabulary mapping into memory."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["nat", "bool"])
        tok = CoqTokenizer(vocab_path)
        assert tok.vocab_size == 7  # 5 special + 2 custom

    def test_special_token_ids(self, tmp_path):
        """spec §4.0.1: pad=0, unk=1, cls=2, sep=3, mask=4."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, [])
        tok = CoqTokenizer(vocab_path)
        assert tok.pad_token_id == 0
        assert tok.unk_token_id == 1
        assert tok.cls_token_id == 2
        assert tok.sep_token_id == 3
        assert tok.mask_token_id == 4

    def test_raises_on_missing_file(self):
        """spec §4.0.1: FileNotFoundError if path does not exist."""
        with pytest.raises(FileNotFoundError):
            CoqTokenizer(Path("/nonexistent/vocab.json"))

    def test_raises_on_malformed_json(self, tmp_path):
        """spec §4.0.1: DataFormatError if JSON is malformed."""
        vocab_path = tmp_path / "vocab.json"
        vocab_path.write_text("not json", encoding="utf-8")
        from Poule.neural.training.errors import DataFormatError
        with pytest.raises(DataFormatError):
            CoqTokenizer(vocab_path)


class TestCoqTokenizerEncode:
    """spec §4.0.1: encode() tokenizes text with whitespace split + lookup."""

    def test_basic_encoding(self, tmp_path):
        """spec §4.0.1: Whitespace split, lookup, prepend CLS, append SEP."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["n", ":", "nat"])
        tok = CoqTokenizer(vocab_path)

        ids, mask = tok.encode("n : nat", max_length=8)

        assert ids[0] == 2  # [CLS]
        assert ids[1] == tok._vocab["n"]
        assert ids[2] == tok._vocab[":"]
        assert ids[3] == tok._vocab["nat"]
        assert ids[4] == 3  # [SEP]
        # Padding
        assert ids[5] == 0
        assert len(ids) == 8
        assert mask == [1, 1, 1, 1, 1, 0, 0, 0]

    def test_unknown_token_maps_to_unk(self, tmp_path):
        """spec §4.0.1: Unknown tokens map to unk_token_id."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["nat"])
        tok = CoqTokenizer(vocab_path)

        ids, mask = tok.encode("unknown_token", max_length=6)
        assert ids[1] == 1  # [UNK]

    def test_truncation(self, tmp_path):
        """spec §4.0.1: Truncate to max_length, keeping CLS and SEP."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["a", "b", "c", "d", "e"])
        tok = CoqTokenizer(vocab_path)

        ids, mask = tok.encode("a b c d e", max_length=4)
        assert len(ids) == 4
        assert ids[0] == 2  # [CLS]
        assert ids[-1] == 3  # [SEP]
        assert all(m == 1 for m in mask)

    def test_empty_text(self, tmp_path):
        """Encoding empty string produces CLS + SEP + padding."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, [])
        tok = CoqTokenizer(vocab_path)

        ids, mask = tok.encode("", max_length=4)
        assert ids[0] == 2  # [CLS]
        assert ids[1] == 3  # [SEP]
        assert mask == [1, 1, 0, 0]

    def test_nfc_normalization(self, tmp_path):
        """spec §4.0.1: NFC normalization applied before lookup."""
        import unicodedata
        vocab_path = tmp_path / "vocab.json"
        # Store the NFC form in the vocab
        _write_vocab(vocab_path, ["é"])  # precomposed
        tok = CoqTokenizer(vocab_path)

        # Use decomposed form (e + combining accent)
        decomposed = unicodedata.normalize("NFD", "é")
        ids, _ = tok.encode(decomposed, max_length=4)
        # Should find it (NFC normalizes decomposed → precomposed)
        assert ids[1] != 1  # not UNK


class TestCoqTokenizerEncodeBatch:
    """spec §4.0.1: encode_batch() encodes multiple texts with dynamic padding."""

    def test_batch_encoding_shapes(self, tmp_path):
        """spec §4.0.1: Returns dict with input_ids and attention_mask arrays."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["a", "b", "c"])
        tok = CoqTokenizer(vocab_path)

        result = tok.encode_batch(["a b", "c"], max_length=512)
        assert "input_ids" in result
        assert "attention_mask" in result
        # Shape: (2, padded_length)
        assert result["input_ids"].shape[0] == 2
        assert result["attention_mask"].shape[0] == 2

    def test_dynamic_padding(self, tmp_path):
        """spec §4.0.1: Padding is to the longest sequence in batch, not max_length."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["a", "b", "c"])
        tok = CoqTokenizer(vocab_path)

        result = tok.encode_batch(["a b", "c"], max_length=512)
        # Longest is "a b" = CLS + a + b + SEP = 4 tokens
        assert result["input_ids"].shape[1] == 4

    def test_batch_attention_mask_correct(self, tmp_path):
        """Shorter sequences have 0s in attention_mask for padding positions."""
        vocab_path = tmp_path / "vocab.json"
        _write_vocab(vocab_path, ["a", "b"])
        tok = CoqTokenizer(vocab_path)

        result = tok.encode_batch(["a b", "a"], max_length=512)
        # First: CLS a b SEP -> all 1s
        assert list(result["attention_mask"][0]) == [1, 1, 1, 1]
        # Second: CLS a SEP PAD -> 1,1,1,0
        assert list(result["attention_mask"][1]) == [1, 1, 1, 0]


class TestCoqTokenizerIntegration:
    """Integration: CoqTokenizer works with VocabularyBuilder output."""

    def test_roundtrip_with_vocabulary_builder(self, tmp_path):
        """Vocabulary built by VocabularyBuilder can be loaded by CoqTokenizer."""
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "Nat.add", "stmt1", "Stdlib.Init.Nat"),
            (2, "nat", "stmt2", "Stdlib.Init.Datatypes"),
        ])
        jsonl_path = tmp_path / "data.jsonl"
        _write_jsonl(jsonl_path, [])
        vocab_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [jsonl_path], vocab_path)
        tok = CoqTokenizer(vocab_path)

        # Both declaration names should tokenize to known IDs
        ids, _ = tok.encode("Nat.add nat", max_length=10)
        assert ids[1] != tok.unk_token_id  # Nat.add known
        assert ids[2] != tok.unk_token_id  # nat known


# ═══════════════════════════════════════════════════════════════════════════
# Compact Training Data Format (spec §4.0.5)
# ═══════════════════════════════════════════════════════════════════════════


def _write_full_and_convert(tmp_path, records, name="data"):
    """Convert full proof-trace records to compact JSONL inline.

    Extracts training pairs and goal states from ExtractionRecord dicts,
    writes them as compact "p" and "g" records. Returns the JSONL path.
    """
    compact_path = tmp_path / f"{name}.jsonl"
    with open(compact_path, "w") as f:
        for record in records:
            rt = record.get("record_type")
            if rt in ("campaign_metadata", "extraction_error", "extraction_summary"):
                f.write(json.dumps(record) + "\n")
                continue
            if rt not in ("proof_trace", "partial_proof_trace", None):
                f.write(json.dumps(record) + "\n")
                continue
            steps = record.get("steps", [])
            source_file = record.get("source_file", "")
            covered: set[str] = set()
            for k in range(1, len(steps)):
                prev_goals = steps[k - 1].get("goals", [])
                raw_premises = steps[k].get("premises", [])
                premises = []
                for p in raw_premises:
                    if isinstance(p, dict):
                        if p.get("kind") != "hypothesis":
                            premises.append(p.get("name", ""))
                    elif isinstance(p, str):
                        premises.append(p)
                if not premises:
                    continue
                state_text = serialize_goals(prev_goals)
                covered.add(state_text)
                f.write(json.dumps(
                    {"t": "p", "f": source_file, "s": state_text, "p": premises},
                ) + "\n")
            for step in steps:
                goals = step.get("goals", [])
                if goals:
                    state_text = serialize_goals(goals)
                    if state_text and state_text not in covered:
                        covered.add(state_text)
                        f.write(json.dumps({"t": "g", "s": state_text}) + "\n")
    return compact_path


def _write_compact_jsonl(path, pairs, goals=None):
    """Write compact training data JSONL with pair and goal records."""
    with open(path, "w") as f:
        for source_file, state_text, premises in pairs:
            f.write(json.dumps(
                {"t": "p", "f": source_file, "s": state_text, "p": premises},
                ensure_ascii=False,
            ) + "\n")
        for state_text in (goals or []):
            f.write(json.dumps(
                {"t": "g", "s": state_text},
                ensure_ascii=False,
            ) + "\n")


class TestLoadCompactFormat:
    """spec §4.1: TrainingDataLoader.load reads compact training data."""

    def test_loads_pairs(self, tmp_path):
        """Pairs from compact JSONL are loaded into the dataset."""
        pairs = [
            ("file_a.v", "state1", ["lem1"]),
            ("file_a.v", "state2", ["lem2"]),
        ]
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "lem1", "stmt1", "Mod")])

        dataset = TrainingDataLoader.load([data_path], db_path)

        total = len(dataset.train) + len(dataset.val) + len(dataset.test)
        assert total == 2

    def test_file_level_split(self, tmp_path):
        """File-level split assigns pairs by source_file position % 10."""
        # Create pairs across 10 distinct files to cover all split positions
        pairs = []
        for i in range(10):
            pairs.append((f"file_{i:02d}.v", f"state_{i}", [f"lem_{i}"]))
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "lem_0", "s", "M")])

        dataset = TrainingDataLoader.load([data_path], db_path)

        # position % 10 == 8 → val, == 9 → test, rest → train
        assert len(dataset.val) == 1
        assert len(dataset.test) == 1
        assert len(dataset.train) == 8

    def test_ignores_goal_records(self, tmp_path):
        """'g' records are ignored by the data loader (only 'p' matters)."""
        pairs = [("file_a.v", "state1", ["lem1"])]
        goals = ["extra_goal_state"]
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs, goals)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "lem1", "s", "M")])

        dataset = TrainingDataLoader.load([data_path], db_path)

        total = len(dataset.train) + len(dataset.val) + len(dataset.test)
        assert total == 1  # only the pair, not the goal

    def test_loads_premise_corpus(self, tmp_path):
        """Premise corpus is loaded from the index DB."""
        pairs = [("file_a.v", "state1", ["lem1"])]
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [
            (1, "lem1", "forall n, n = n", "Mod"),
        ])

        dataset = TrainingDataLoader.load([data_path], db_path)

        assert "lem1" in dataset.premise_corpus
        assert dataset.premise_corpus["lem1"] == "forall n, n = n"


class TestVocabularyBuilderCompactFormat:
    """spec §4.0: VocabularyBuilder reads 's' from both 'p' and 'g' records."""

    def test_vocab_from_compact_pairs(self, tmp_path):
        """Tokens from pair state_text appear in vocabulary."""
        pairs = [("file_a.v", "custom_token_xyz", ["lem1"])]
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "lem1", "s", "M")])
        vocab_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [data_path], vocab_path)

        vocab = json.loads(vocab_path.read_text())
        assert "custom_token_xyz" in vocab

    def test_vocab_from_compact_goals(self, tmp_path):
        """Tokens from supplementary 'g' records appear in vocabulary."""
        pairs = [("file_a.v", "pair_token", ["lem1"])]
        goals = ["supplementary_token_abc"]
        data_path = tmp_path / "data.jsonl"
        _write_compact_jsonl(data_path, pairs, goals)
        db_path = tmp_path / "index.db"
        _make_minimal_index_db(db_path, [(1, "lem1", "s", "M")])
        vocab_path = tmp_path / "vocab.json"

        VocabularyBuilder.build(db_path, [data_path], vocab_path)

        vocab = json.loads(vocab_path.read_text())
        assert "supplementary_token_abc" in vocab


# ═══════════════════════════════════════════════════════════════════════════
# SplitReport — Split Diagnostic Report
# ═══════════════════════════════════════════════════════════════════════════


class TestSplitReport:
    """spec §4.1: Split diagnostic report on train/val/test distributions."""

    def _make_dataset(self, file_premise_map):
        """Build a TrainingDataset from {file: [(state, [premises])]} map.

        Uses position % 10 split: 8 → val, 9 → test, else → train.
        """
        sorted_files = sorted(file_premise_map.keys())
        train, val, test = [], [], []
        train_f, val_f, test_f = [], [], []
        for pos, f in enumerate(sorted_files):
            pairs = file_premise_map[f]
            mod = pos % 10
            if mod == 8:
                val.extend(pairs)
                val_f.extend([f] * len(pairs))
            elif mod == 9:
                test.extend(pairs)
                test_f.extend([f] * len(pairs))
            else:
                train.extend(pairs)
                train_f.extend([f] * len(pairs))
        return TrainingDataset(
            train=train, val=val, test=test,
            premise_corpus={},
            train_files=train_f, val_files=val_f, test_files=test_f,
        )

    def test_per_split_counts(self):
        """spec §4.1: 10 files → 8 train, 1 val, 1 test."""
        fpm = {
            f"file_{i:02d}": [(f"state_{i}", [f"premise_{i}"])]
            for i in range(10)
        }
        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        assert report.train_files == 8
        assert report.val_files == 1
        assert report.test_files == 1
        assert report.train_pairs == 8
        assert report.val_pairs == 1
        assert report.test_pairs == 1

    def test_premise_overlap(self):
        """Verify cross-split premise overlap counts."""
        # shared_premise in all files; file_08 (val) has val_only;
        # file_09 (test) has test_only; train files have train_only
        fpm = {}
        for i in range(10):
            premises = ["shared_premise"]
            if i == 8:
                premises.append("val_only_premise")
            elif i == 9:
                premises.append("test_only_premise")
            else:
                premises.append("train_only_premise")
            fpm[f"file_{i:02d}"] = [(f"state_{i}", premises)]

        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        assert report.premises_in_all_splits == 1  # shared_premise
        assert report.premises_train_only == 1  # train_only_premise
        assert report.premises_val_only == 1  # val_only_premise
        assert report.premises_test_only == 1  # test_only_premise

    def test_coverage_fraction(self):
        """test_premise_train_coverage = |test ∩ train| / |test|."""
        # Test file has 2 premises: one in train, one not
        fpm = {}
        for i in range(8):
            fpm[f"file_{i:02d}"] = [(f"s{i}", ["common"])]
        fpm["file_08"] = [("s8", ["val_p"])]
        fpm["file_09"] = [("s9", ["common", "test_exclusive"])]

        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        # test premises: {common, test_exclusive}, train has {common}
        assert report.test_premise_train_coverage == pytest.approx(0.5)

    def test_warning_low_coverage(self):
        """Warning when <50% of test premises appear in training."""
        fpm = {}
        for i in range(8):
            fpm[f"file_{i:02d}"] = [(f"s{i}", [f"train_p_{i}"])]
        fpm["file_08"] = [("s8", ["val_p"])]
        fpm["file_09"] = [("s9", ["unseen_a", "unseen_b", "unseen_c"])]

        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        assert report.test_premise_train_coverage == 0.0
        assert any("Less than 50%" in w for w in report.warnings)

    def test_warning_test_exclusive(self):
        """Warning when >30% of test premises are unseen in training."""
        fpm = {}
        for i in range(8):
            fpm[f"file_{i:02d}"] = [(f"s{i}", [f"train_p_{i}"])]
        fpm["file_08"] = [("s8", ["val_p"])]
        # 3 premises, all exclusive to test → 100% > 30%
        fpm["file_09"] = [("s9", ["only_a", "only_b", "only_c"])]

        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        assert any("Over 30%" in w for w in report.warnings)

    def test_no_warnings_healthy(self):
        """No warnings when all premises are well-distributed."""
        # All files share the same premise, lots of pairs
        fpm = {}
        for i in range(10):
            pairs = [(f"s{i}_{j}", ["shared"]) for j in range(200)]
            fpm[f"file_{i:02d}"] = pairs

        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        # coverage is 1.0, no test-only premises, high frequency, enough pairs
        assert report.test_premise_train_coverage == 1.0
        assert report.warnings == []

    def test_to_dict_json_serializable(self):
        """to_dict() produces JSON-serializable output."""
        fpm = {
            f"file_{i:02d}": [(f"state_{i}", [f"premise_{i}"])]
            for i in range(10)
        }
        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        d = report.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        # Roundtrip
        parsed = json.loads(serialized)
        assert parsed["train_files"] == 8

    def test_empty_split_no_crash(self):
        """Report handles fewer than 10 files without division by zero."""
        fpm = {
            f"file_{i:02d}": [(f"state_{i}", [f"premise_{i}"])]
            for i in range(5)
        }
        dataset = self._make_dataset(fpm)
        report = SplitReport.generate(dataset)

        # With 5 files (positions 0-4), no file hits mod==8 or mod==9
        assert report.val_files == 0
        assert report.test_files == 0
        assert report.test_premise_train_coverage == 0.0
        assert report.test_premise_mean_train_freq == 0.0
