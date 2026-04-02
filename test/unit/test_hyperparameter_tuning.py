"""TDD tests for hyperparameter optimization (specification/neural-training.md §4.8, §4.9).

Tests are written BEFORE implementation. Covers: TuningError in error hierarchy,
_get_device() priority logic, epoch_callback propagation in TacticClassifierTrainer,
TUNABLE_HYPERPARAMS search space, TuningResult fields, HyperparameterTuner.tune()
(objective function, pruning, resume, memory cleanup, zero-completion error).
"""

from __future__ import annotations

import gc
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

import pytest

# ---------------------------------------------------------------------------
# Imports from production code (TDD — will fail until implemented)
# ---------------------------------------------------------------------------

from Poule.neural.training.errors import (
    NeuralTrainingError,
    TuningError,
    TrainingResourceError,
    InsufficientDataError,
)
from Poule.neural.training.trainer import (
    TacticClassifierTrainer,
    DEFAULT_HYPERPARAMS,
    EarlyStoppingTracker,
    save_checkpoint,
    load_checkpoint,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. TuningError — Error Hierarchy
# ═══════════════════════════════════════════════════════════════════════════


class TestTuningError:
    """spec §5: TuningError is a NeuralTrainingError subclass."""

    def test_tuning_error_inherits_from_neural_training_error(self):
        assert issubclass(TuningError, NeuralTrainingError)

    def test_tuning_error_is_raisable_with_message(self):
        with pytest.raises(TuningError, match="0 of 5 trials"):
            raise TuningError(
                "Hyperparameter optimization failed: 0 of 5 trials completed successfully"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Device Detection — _get_device()
# ═══════════════════════════════════════════════════════════════════════════


class TestGetDevice:
    """spec §4.9: Device priority is CUDA > MPS > CPU."""

    def _make_mock_torch(self, cuda_available=False, mps_available=False, has_mps=True):
        """Create a mock torch module with device class and backend stubs."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = cuda_available
        if has_mps:
            mock_torch.backends.mps.is_available.return_value = mps_available
        else:
            del mock_torch.backends.mps
        # Make torch.device return a real-like object
        mock_torch.device = lambda t: type("device", (), {"type": t})()
        return mock_torch

    def test_returns_cuda_when_available(self):
        mock_torch = self._make_mock_torch(cuda_available=True)
        with patch.dict("sys.modules", {"torch": mock_torch}):
            import importlib
            from Poule.neural.training import trainer
            importlib.reload(trainer)
            device = trainer._get_device()
            assert device.type == "cuda"
            importlib.reload(trainer)

    def test_returns_cpu_when_only_mps_available(self):
        """MPS is intentionally skipped (memory leak issues). Falls back to CPU."""
        mock_torch = self._make_mock_torch(mps_available=True)
        with patch.dict("sys.modules", {"torch": mock_torch}):
            import importlib
            from Poule.neural.training import trainer
            importlib.reload(trainer)
            device = trainer._get_device()
            assert device.type == "cpu"
            importlib.reload(trainer)

    def test_returns_cpu_as_fallback(self):
        mock_torch = self._make_mock_torch()
        with patch.dict("sys.modules", {"torch": mock_torch}):
            import importlib
            from Poule.neural.training import trainer
            importlib.reload(trainer)
            device = trainer._get_device()
            assert device.type == "cpu"
            importlib.reload(trainer)

    def test_returns_cpu_when_mps_attr_missing(self):
        """Older PyTorch without MPS support."""
        mock_torch = self._make_mock_torch(has_mps=False)
        with patch.dict("sys.modules", {"torch": mock_torch}):
            import importlib
            from Poule.neural.training import trainer
            importlib.reload(trainer)
            device = trainer._get_device()
            assert device.type == "cpu"
            importlib.reload(trainer)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Epoch Callback — Integration Point for Pruning
# ═══════════════════════════════════════════════════════════════════════════


class TestEpochCallback:
    """spec §4.3: train() accepts epoch_callback and invokes it after each epoch."""

    def test_train_accepts_epoch_callback_parameter(self):
        """TacticClassifierTrainer.train() must accept epoch_callback kwarg."""
        import inspect
        sig = inspect.signature(TacticClassifierTrainer.train)
        assert "epoch_callback" in sig.parameters

    @pytest.mark.skip(reason="fine_tune removed in tactic prediction pivot")
    def test_fine_tune_accepts_epoch_callback_parameter(self):
        """TacticClassifierTrainer.fine_tune() must accept epoch_callback kwarg."""
        pass

    def test_callback_invoked_with_epoch_and_recall(self):
        """spec §4.3: callback is called with (epoch, val_accuracy) after each epoch's validation."""
        callback = Mock()

        # Create a minimal mock training that runs 2 epochs and calls the callback
        trainer = TacticClassifierTrainer()

        # We need to mock _train_impl to verify callback propagation
        original_train_impl = trainer._train_impl

        def mock_train_impl(**kwargs):
            # Simulate 2 epochs
            cb = kwargs.get("epoch_callback")
            if cb is not None:
                cb(1, 0.35)
                cb(2, 0.42)
            return kwargs.get("output_path", Path("/tmp/test.pt"))

        trainer._train_impl = mock_train_impl

        dataset = Mock()
        dataset.train_pairs = [(f"state_{i}", i % 10) for i in range(1000)]
        dataset.val_pairs = []
        dataset.label_map = {f"family_{i}": i for i in range(10)}
        dataset.label_names = [f"family_{i}" for i in range(10)]
        dataset.family_counts = {f"family_{i}": 100 for i in range(10)}

        trainer.train(dataset, Mock(), Path("/tmp/test.pt"), epoch_callback=callback)

        assert callback.call_count == 2
        callback.assert_any_call(1, 0.35)
        callback.assert_any_call(2, 0.42)

    def test_callback_exception_terminates_training(self):
        """spec §4.3: if callback raises, training loop terminates and exception propagates."""

        class PruneSignal(Exception):
            pass

        def pruning_callback(epoch, val_accuracy):
            if epoch >= 2:
                raise PruneSignal("pruned at epoch 2")

        trainer = TacticClassifierTrainer()

        calls = []
        def mock_train_impl(**kwargs):
            cb = kwargs.get("epoch_callback")
            for epoch in range(1, 6):
                calls.append(epoch)
                if cb is not None:
                    cb(epoch, 0.1 * epoch)
            return kwargs.get("output_path", Path("/tmp/test.pt"))

        trainer._train_impl = mock_train_impl
        dataset = Mock()
        dataset.train_pairs = [(f"state_{i}", i % 10) for i in range(1000)]
        dataset.val_pairs = []
        dataset.label_map = {f"family_{i}": i for i in range(10)}
        dataset.label_names = [f"family_{i}" for i in range(10)]
        dataset.family_counts = {f"family_{i}": 100 for i in range(10)}

        with pytest.raises(PruneSignal):
            trainer.train(dataset, Mock(), Path("/tmp/test.pt"), epoch_callback=pruning_callback)

        # Training should have stopped at epoch 2
        assert calls == [1, 2]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Tunable Hyperparameters — Search Space Definition
# ═══════════════════════════════════════════════════════════════════════════


class TestTunableHyperparams:
    """spec §4.8: search space covers 5 hyperparameters with specified ranges."""

    def test_search_space_contains_all_tunable_params(self):
        from Poule.neural.training.tuner import TUNABLE_HYPERPARAMS

        expected = {
            "num_hidden_layers", "learning_rate", "batch_size",
            "weight_decay", "class_weight_alpha",
        }
        assert set(TUNABLE_HYPERPARAMS.keys()) == expected

    def test_learning_rate_range(self):
        """spec §4.8: learning_rate is log-uniform in [1e-6, 1e-4]."""
        from Poule.neural.training.tuner import TUNABLE_HYPERPARAMS

        lr = TUNABLE_HYPERPARAMS["learning_rate"]
        assert lr["low"] == 1e-6
        assert lr["high"] == 1e-4
        assert lr["log"] is True

    def test_class_weight_alpha_range(self):
        """spec §4.8: class_weight_alpha is uniform in [0.0, 1.0]."""
        from Poule.neural.training.tuner import TUNABLE_HYPERPARAMS

        cwa = TUNABLE_HYPERPARAMS["class_weight_alpha"]
        assert cwa["low"] == 0.0
        assert cwa["high"] == 1.0

    def test_batch_size_choices(self):
        """spec §4.8: batch_size is categorical {16, 32, 64}."""
        from Poule.neural.training.tuner import TUNABLE_HYPERPARAMS

        bs = TUNABLE_HYPERPARAMS["batch_size"]
        assert set(bs["choices"]) == {16, 32, 64}

    def test_weight_decay_range(self):
        """spec §4.8: weight_decay is log-uniform in [1e-4, 1e-1]."""
        from Poule.neural.training.tuner import TUNABLE_HYPERPARAMS

        wd = TUNABLE_HYPERPARAMS["weight_decay"]
        assert wd["low"] == 1e-4
        assert wd["high"] == 1e-1
        assert wd["log"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. TuningResult — Data Class Fields
# ═══════════════════════════════════════════════════════════════════════════


class TestTuningResult:
    """spec §4.8: TuningResult has all required fields."""

    def test_tuning_result_fields(self):
        from Poule.neural.training.tuner import TuningResult

        result = TuningResult(
            best_hyperparams={"learning_rate": 3e-5},
            best_value=0.56,
            n_trials=20,
            n_pruned=5,
            study_path="/tmp/hpo-study.db",
            all_trials=[],
        )
        assert result.best_hyperparams == {"learning_rate": 3e-5}
        assert result.best_value == 0.56
        assert result.n_trials == 20
        assert result.n_pruned == 5
        assert result.study_path == "/tmp/hpo-study.db"
        assert result.all_trials == []

    def test_all_trials_entry_structure(self):
        """spec §4.8: each trial entry has number, value, state, hyperparams."""
        from Poule.neural.training.tuner import TuningResult

        trial_entry = {
            "number": 0,
            "value": 0.51,
            "state": "COMPLETE",
            "hyperparams": {"learning_rate": 3e-5, "class_weight_alpha": 0.5},
        }
        result = TuningResult(
            best_hyperparams={},
            best_value=0.51,
            n_trials=1,
            n_pruned=0,
            study_path="/tmp/hpo-study.db",
            all_trials=[trial_entry],
        )
        entry = result.all_trials[0]
        assert "number" in entry
        assert "value" in entry
        assert "state" in entry
        assert "hyperparams" in entry


# ═══════════════════════════════════════════════════════════════════════════
# 6. HyperparameterTuner.tune() — Core HPO Logic
# ═══════════════════════════════════════════════════════════════════════════


class TestHyperparameterTuner:
    """spec §4.8: HyperparameterTuner.tune() runs Optuna study.

    Strategy: let Optuna run for real, mock only TacticClassifierTrainer and load_checkpoint.
    """

    def _make_dataset(self, n=1000):
        dataset = Mock()
        dataset.train_pairs = [(f"s{i}", i % 10) for i in range(n)]
        return dataset

    def _run_tune(self, tmp_path, n_trials=1, resume=False, trainer_side_effect=None):
        """Run tune with mocked training. Returns (result, output_dir)."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        from Poule.neural.training.tuner import HyperparameterTuner

        output_dir = tmp_path / "hpo"
        output_dir.mkdir(exist_ok=True)
        dataset = self._make_dataset()

        mock_trainer_instance = MagicMock()
        if trainer_side_effect:
            mock_trainer_instance.train.side_effect = trainer_side_effect
        mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

        with patch("Poule.neural.training.tuner.TacticClassifierTrainer", mock_trainer_cls), \
             patch("Poule.neural.training.tuner.load_checkpoint",
                    return_value={"best_accuracy_5": 0.5}):
            result = HyperparameterTuner.tune(
                dataset, output_dir, n_trials=n_trials, resume=resume,
            )
        return result, output_dir, mock_trainer_cls

    def test_tune_returns_tuning_result(self, tmp_path):
        """spec §4.8: returns TuningResult with all required fields."""
        from Poule.neural.training.tuner import TuningResult

        result, _, _ = self._run_tune(tmp_path, n_trials=2)
        assert isinstance(result, TuningResult)
        assert result.best_value == 0.5
        assert result.n_trials == 2
        assert isinstance(result.best_hyperparams, dict)
        assert "hpo-study.db" in result.study_path
        assert len(result.all_trials) == 2

    def test_tune_trial_entry_structure(self, tmp_path):
        """spec §4.8: all_trials entries have number, value, state, hyperparams."""
        result, _, _ = self._run_tune(tmp_path, n_trials=1)
        entry = result.all_trials[0]
        assert "number" in entry
        assert "value" in entry
        assert "state" in entry
        assert "hyperparams" in entry

    def test_tune_samples_all_hyperparams(self, tmp_path):
        """spec §4.8: each trial samples all 5 tunable hyperparameters."""
        result, _, _ = self._run_tune(tmp_path, n_trials=1)
        params = result.all_trials[0]["hyperparams"]
        assert "learning_rate" in params
        assert "class_weight_alpha" in params
        assert "batch_size" in params
        assert "weight_decay" in params
        assert "class_weight_alpha" in params

    def test_tune_hyperparams_in_valid_ranges(self, tmp_path):
        """spec §4.8: sampled values fall within specified ranges."""
        result, _, _ = self._run_tune(tmp_path, n_trials=3)
        for trial in result.all_trials:
            hp = trial["hyperparams"]
            assert hp["num_hidden_layers"] in {4, 6, 8, 12}
            assert 1e-6 <= hp["learning_rate"] <= 1e-4
            assert hp["batch_size"] in {16, 32, 64}
            assert 1e-4 <= hp["weight_decay"] <= 1e-1
            assert 0.0 <= hp["class_weight_alpha"] <= 1.0

    def test_tune_uses_sqlite_storage(self, tmp_path):
        """spec §4.8: study persists in SQLite at output_dir/hpo-study.db."""
        _, output_dir, _ = self._run_tune(tmp_path, n_trials=1)
        assert (output_dir / "hpo-study.db").exists()

    def test_tune_best_checkpoint_copied(self, tmp_path):
        """spec §4.8: best trial's checkpoint is copied to best-model.pt."""
        _, output_dir, _ = self._run_tune(tmp_path, n_trials=1)
        # The trainer is mocked so no real checkpoint is written by train(),
        # but the copy is attempted. Verify the path is correct by checking
        # the copy target exists or was attempted.
        # Since trainer is mocked, trial-0.pt won't exist and copy2 will fail
        # silently (shutil.copy2 called on non-existent file). That's OK —
        # what matters is the copy logic is in place. We test this by creating
        # the file first.
        pass  # Covered by test_tune_copies_existing_checkpoint below

    def test_tune_copies_existing_checkpoint(self, tmp_path):
        """spec §4.8: when trial checkpoint exists, it's copied to best-model.pt."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        from Poule.neural.training.tuner import HyperparameterTuner

        output_dir = tmp_path / "hpo"
        output_dir.mkdir()
        dataset = self._make_dataset()

        # Pre-create the trial checkpoint that the trainer would write
        def fake_train(ds, path, **kwargs):
            Path(path).write_text("fake checkpoint data")

        mock_trainer_instance = MagicMock()
        mock_trainer_instance.train.side_effect = fake_train
        mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

        with patch("Poule.neural.training.tuner.TacticClassifierTrainer", mock_trainer_cls), \
             patch("Poule.neural.training.tuner.load_checkpoint",
                    return_value={"best_accuracy_5": 0.5}):
            HyperparameterTuner.tune(dataset, output_dir, n_trials=1)

        assert (output_dir / "best-model.pt").exists()

    def test_tune_insufficient_data_raises(self, tmp_path):
        """spec §4.8: requires dataset with >= 1,000 training pairs."""
        from Poule.neural.training.tuner import HyperparameterTuner

        output_dir = tmp_path / "hpo"
        output_dir.mkdir()
        dataset = self._make_dataset(n=500)

        with pytest.raises(InsufficientDataError):
            HyperparameterTuner.tune(dataset, output_dir, n_trials=5)

    def test_tune_raises_tuning_error_on_zero_completions(self, tmp_path):
        """spec §4.8: raises TuningError when all trials fail."""
        from Poule.neural.training.tuner import HyperparameterTuner
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        output_dir = tmp_path / "hpo"
        output_dir.mkdir()
        dataset = self._make_dataset()

        def always_fail(*args, **kwargs):
            raise RuntimeError("Simulated failure")

        mock_trainer_instance = MagicMock()
        mock_trainer_instance.train.side_effect = always_fail
        mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

        with patch("Poule.neural.training.tuner.TacticClassifierTrainer", mock_trainer_cls), \
             pytest.raises(TuningError, match="0 of"):
            HyperparameterTuner.tune(dataset, output_dir, n_trials=3)

    def test_tune_resume_continues_study(self, tmp_path):
        """spec §4.8: resume=True continues from existing study."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Run 2 trials
        result1, output_dir, _ = self._run_tune(tmp_path, n_trials=2)
        assert result1.n_trials == 2

        # Resume with 3 more
        from Poule.neural.training.tuner import HyperparameterTuner

        dataset = self._make_dataset()
        mock_trainer_instance = MagicMock()
        mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

        with patch("Poule.neural.training.tuner.TacticClassifierTrainer", mock_trainer_cls), \
             patch("Poule.neural.training.tuner.load_checkpoint",
                    return_value={"best_accuracy_5": 0.5}):
            result2 = HyperparameterTuner.tune(
                dataset, output_dir, n_trials=3, resume=True,
            )
        assert result2.n_trials == 5  # 2 + 3

    def test_tune_direction_is_maximize(self, tmp_path):
        """spec §4.8: study maximizes val R@32 (higher is better)."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        from Poule.neural.training.tuner import HyperparameterTuner

        output_dir = tmp_path / "hpo"
        output_dir.mkdir()
        dataset = self._make_dataset()

        # Use varying return values to verify maximize direction
        call_count = [0]
        def varying_checkpoint(*args, **kwargs):
            call_count[0] += 1
            return {"best_accuracy_5": 0.3 if call_count[0] == 1 else 0.7}

        mock_trainer_instance = MagicMock()
        mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

        with patch("Poule.neural.training.tuner.TacticClassifierTrainer", mock_trainer_cls), \
             patch("Poule.neural.training.tuner.load_checkpoint", side_effect=varying_checkpoint):
            result = HyperparameterTuner.tune(dataset, output_dir, n_trials=2)

        assert result.best_value == 0.7  # Maximized
