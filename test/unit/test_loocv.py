"""Tests for leave-one-library-out cross-validation.

Covers: TrainingDataLoader.load_by_library (library-level split),
LibraryLOOCV orchestration (FoldResult, LOOCVReport).

spec §4.1: Library-level split and LOOCV contracts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Poule.neural.training.data import (
    TrainingDataLoader,
    TacticDataset,
    undersample_train,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_step_records(path: Path, steps: list[tuple[str, str, str]]) -> None:
    """Write compact training data JSONL with step records.

    steps: list of (source_file, state_text, tactic_text)
    """
    with open(path, "w") as f:
        for source_file, state_text, tactic_text in steps:
            f.write(
                json.dumps(
                    {"t": "s", "f": source_file, "s": state_text, "c": tactic_text},
                    ensure_ascii=False,
                )
                + "\n"
            )


def _make_library_files(
    tmp_path: Path,
    library_name: str,
    num_files: int,
    steps_per_file: int,
    tactic: str = "intros n.",
) -> list[Path]:
    """Create JSONL files for a mock library with deterministic content."""
    paths = []
    jsonl_path = tmp_path / f"{library_name}.jsonl"
    steps = []
    for i in range(num_files):
        for j in range(steps_per_file):
            source_file = f"{library_name}/File{i:02d}.v"
            state_text = f"{library_name}_file{i}_goal{j}"
            steps.append((source_file, state_text, tactic))
    _write_step_records(jsonl_path, steps)
    paths.append(jsonl_path)
    return paths


# ---------------------------------------------------------------------------
# load_by_library tests
# ---------------------------------------------------------------------------


class TestLoadByLibrary:
    """spec §4.1: Library-level split via load_by_library."""

    def test_held_out_library_only_in_test(self, tmp_path):
        """spec §4.1 MAINTAINS: No file from the held-out library in train or val."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=2
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libB"
        )

        # All test files should be from libB
        for f in dataset.test_files:
            assert f.startswith("libB/"), f"Test file {f} not from held-out library"

        # No train or val file should be from libB
        for f in dataset.train_files:
            assert not f.startswith("libB/"), f"Train file {f} from held-out library"
        for f in dataset.val_files:
            assert not f.startswith("libB/"), f"Val file {f} from held-out library"

    def test_val_from_non_held_out_libraries(self, tmp_path):
        """spec §4.1: Validation files come only from non-held-out libraries."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=2
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libA"
        )

        val_libs = {f.split("/")[0] for f in dataset.val_files}
        assert "libA" not in val_libs
        # Val should have files from remaining libraries
        assert len(dataset.val_pairs) > 0

    def test_all_steps_accounted_for(self, tmp_path):
        """Every step appears in exactly one split."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=3
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libB"
        )

        total = len(dataset.train_pairs) + len(dataset.val_pairs) + len(dataset.test_pairs)
        # libB has 10*3=30 test, libA+libC have 20*3=60 train+val
        assert total == 90

    def test_no_overlap_between_splits(self, tmp_path):
        """spec §4.1 MAINTAINS: No file appears in more than one split."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=2
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libC"
        )

        train_states = {s for s, *_ in dataset.train_pairs}
        val_states = {s for s, *_ in dataset.val_pairs}
        test_states = {s for s, *_ in dataset.test_pairs}

        assert train_states.isdisjoint(val_states)
        assert train_states.isdisjoint(test_states)
        assert val_states.isdisjoint(test_states)

    def test_deterministic(self, tmp_path):
        """spec §4.1 MAINTAINS: Same inputs produce same splits."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=2
            )

        d1 = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libA", seed=42
        )
        d2 = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libA", seed=42
        )

        assert d1.train_pairs == d2.train_pairs
        assert d1.val_pairs == d2.val_pairs
        assert d1.test_pairs == d2.test_pairs

    def test_different_seeds_produce_different_val(self, tmp_path):
        """Different seeds should shuffle files differently."""
        lib_paths = {}
        for lib_name in ("libA", "libB", "libC"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=20, steps_per_file=2
            )

        d1 = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libA", seed=42
        )
        d2 = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libA", seed=99
        )

        # Test split should be the same (same held-out library)
        assert set(d1.test_files) == set(d2.test_files)
        # Val split should differ (different shuffles)
        assert set(d1.val_files) != set(d2.val_files)

    def test_val_fraction(self, tmp_path):
        """val_fraction controls the train/val ratio of non-held-out files."""
        lib_paths = {}
        for lib_name in ("libA", "libB"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=20, steps_per_file=1
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libB", val_fraction=0.2
        )

        # 20 files from libA; 20% = 4 val files, 16 train files
        unique_val_files = set(dataset.val_files)
        unique_train_files = set(dataset.train_files)
        assert len(unique_val_files) == 4
        assert len(unique_train_files) == 16

    def test_returns_valid_tactic_dataset(self, tmp_path):
        """Result should be a proper TacticDataset with hierarchical labels."""
        lib_paths = {}
        for lib_name in ("libA", "libB"):
            lib_paths[lib_name] = _make_library_files(
                tmp_path, lib_name, num_files=10, steps_per_file=2
            )

        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libB"
        )

        assert isinstance(dataset, TacticDataset)
        assert len(dataset.category_names) > 0
        assert len(dataset.label_map) > 0
        assert dataset.num_classes > 0

    def test_compatible_with_undersample(self, tmp_path):
        """Output of load_by_library can be passed to undersample_train."""
        lib_paths = {}
        # Use multiple tactics so undersampling has something to cap
        steps_a = []
        for i in range(50):
            steps_a.append((f"libA/File{i:02d}.v", f"state_a_{i}", "intros n."))
        path_a = tmp_path / "libA.jsonl"
        _write_step_records(path_a, steps_a)

        steps_b = []
        for i in range(10):
            steps_b.append((f"libB/File{i:02d}.v", f"state_b_{i}", "apply H."))
        path_b = tmp_path / "libB.jsonl"
        _write_step_records(path_b, steps_b)

        lib_paths = {"libA": [path_a], "libB": [path_b]}
        dataset = TrainingDataLoader.load_by_library(
            lib_paths, held_out_library="libB"
        )

        # Should not raise
        undersampled = undersample_train(dataset, cap=10, seed=42)
        assert len(undersampled.train_pairs) <= len(dataset.train_pairs)
        # Test split unchanged
        assert undersampled.test_pairs == dataset.test_pairs


# ---------------------------------------------------------------------------
# FoldResult / LOOCVReport tests
# ---------------------------------------------------------------------------


class TestLOOCVDataclasses:
    """spec §4.1: FoldResult and LOOCVReport structure."""

    def test_fold_result_fields(self):
        """FoldResult has all required fields."""
        from Poule.neural.training.loocv import FoldResult

        fr = FoldResult(
            held_out_library="stdlib",
            train_samples=1000,
            val_samples=100,
            test_samples=200,
            accuracy_at_1=0.35,
            accuracy_at_5=0.60,
            category_accuracy_at_1=0.50,
            dead_families=20,
            total_families=65,
            per_family_recall={"intros": 0.8, "apply": 0.5},
            training_time_s=120.0,
        )

        assert fr.held_out_library == "stdlib"
        assert fr.accuracy_at_5 == 0.60
        assert fr.dead_families == 20

    def test_loocv_report_fields(self):
        """LOOCVReport aggregates FoldResults correctly."""
        from Poule.neural.training.loocv import FoldResult, LOOCVReport

        folds = [
            FoldResult(
                held_out_library="libA",
                train_samples=100, val_samples=10, test_samples=20,
                accuracy_at_1=0.3, accuracy_at_5=0.5,
                category_accuracy_at_1=0.4,
                dead_families=10, total_families=30,
                per_family_recall={}, training_time_s=60.0,
            ),
            FoldResult(
                held_out_library="libB",
                train_samples=80, val_samples=10, test_samples=30,
                accuracy_at_1=0.4, accuracy_at_5=0.7,
                category_accuracy_at_1=0.5,
                dead_families=8, total_families=30,
                per_family_recall={}, training_time_s=50.0,
            ),
        ]

        report = LOOCVReport(
            folds=folds,
            undersample_cap=1000,
            mean_test_acc_at_5=0.6,
            std_test_acc_at_5=0.1,
            mean_dead_families=9.0,
            per_library_acc_at_5={"libA": 0.5, "libB": 0.7},
        )

        assert len(report.folds) == 2
        assert report.mean_test_acc_at_5 == 0.6
        assert report.per_library_acc_at_5["libB"] == 0.7

    def test_loocv_report_to_dict(self):
        """LOOCVReport.to_dict() produces JSON-serializable output."""
        from Poule.neural.training.loocv import FoldResult, LOOCVReport

        fold = FoldResult(
            held_out_library="libA",
            train_samples=100, val_samples=10, test_samples=20,
            accuracy_at_1=0.3, accuracy_at_5=0.5,
            category_accuracy_at_1=0.4,
            dead_families=10, total_families=30,
            per_family_recall={"intros": 0.8}, training_time_s=60.0,
        )

        report = LOOCVReport(
            folds=[fold],
            undersample_cap=1000,
            mean_test_acc_at_5=0.5,
            std_test_acc_at_5=0.0,
            mean_dead_families=10.0,
            per_library_acc_at_5={"libA": 0.5},
        )

        d = report.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert "libA" in json_str
        assert d["undersample_cap"] == 1000
