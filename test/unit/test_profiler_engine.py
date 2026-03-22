"""TDD tests for the Proof Profiling Engine async functions.

Spec: specification/proof-profiling.md, Sections 4.4, 4.9, 4.10, 4.13.
Tests use mocked subprocesses and session managers — no real Coq required.
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_engine():
    from Poule.profiler.engine import (
        profile_file,
        profile_single_proof,
        profile_ltac,
        compare_profiles,
        profile_proof,
        _aggregate_proofs,
    )
    return profile_file, profile_single_proof, profile_ltac, compare_profiles, profile_proof, _aggregate_proofs


def _import_types():
    from Poule.profiler.types import (
        FileProfile,
        LtacProfile,
        ProfileRequest,
        ProofProfile,
        TimingComparison,
    )
    return FileProfile, LtacProfile, ProfileRequest, ProofProfile, TimingComparison


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SOURCE = textwrap.dedent("""\
    Require Import Coq.Arith.Arith.
    Lemma slow_add : forall n, n + 0 = n.
    Proof.
    simpl in *.
    lia.
    Qed.
""")

SAMPLE_TIMING = textwrap.dedent("""\
    Chars 0 - 31 [Require~Import~Coq.Arith.Arith.] 0.120 secs (0.110u,0.010s)
    Chars 32 - 69 [Lemma~slow_add~:~forall~n,~n~+~...] 0.001 secs (0.001u,0.000s)
    Chars 70 - 76 [Proof.] 0.000 secs (0.000u,0.000s)
    Chars 77 - 88 [simpl~in~*.] 0.003 secs (0.003u,0.000s)
    Chars 89 - 93 [lia.] 0.050 secs (0.050u,0.000s)
    Chars 94 - 98 [Qed.] 15.200 secs (15.100u,0.100s)
""")


@pytest.fixture
def coq_v_file(tmp_path):
    """Create a sample .v file."""
    f = tmp_path / "SlowProof.v"
    f.write_text(SAMPLE_SOURCE)
    return f


@pytest.fixture
def timing_file_content():
    return SAMPLE_TIMING


def _make_mock_process(returncode=0, stdout=b"", stderr=b"", timing_content=""):
    """Create a mock for asyncio.create_subprocess_exec."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ===================================================================
# Section 4.4: File Profiling
# ===================================================================


class TestProfileFile:
    """profile_file — Spec 4.4."""

    @pytest.mark.asyncio
    async def test_successful_profiling(self, coq_v_file, timing_file_content):
        """Given a .v file that compiles, returns FileProfile with timing data."""
        profile_file, *_ = _import_engine()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            # Write timing data to the timing file
            # Find the -time-file argument to get the path
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(coq_v_file), timeout_seconds=60)

        assert result.compilation_succeeded is True
        assert result.error_message is None
        assert len(result.sentences) == 6
        assert result.total_time_s == pytest.approx(15.374, abs=0.01)
        # Proofs should be populated
        assert len(result.proofs) >= 1
        assert result.proofs[0].lemma_name == "slow_add"

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Given a non-existent file, returns error FileProfile."""
        profile_file, *_ = _import_engine()
        result = await profile_file("/tmp/nonexistent_abc_xyz.v")
        assert result.compilation_succeeded is False
        assert "FILE_NOT_FOUND" in result.error_message

    @pytest.mark.asyncio
    async def test_coqc_not_found(self, coq_v_file):
        """Given coqc not on PATH, returns TOOL_MISSING."""
        profile_file, *_ = _import_engine()
        with patch("Poule.profiler.engine.locate_coqc", return_value="TOOL_MISSING: coqc not found on PATH"):
            result = await profile_file(str(coq_v_file))
        assert result.compilation_succeeded is False
        assert "TOOL_MISSING" in result.error_message

    @pytest.mark.asyncio
    async def test_compilation_failure(self, coq_v_file, timing_file_content):
        """Non-zero exit code → compilation_succeeded=False with partial timing."""
        profile_file, *_ = _import_engine()

        proc = _make_mock_process(returncode=1, stderr=b"Error: Unknown tactic.")

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    # Write partial timing (only first 3 lines)
                    partial = "\n".join(timing_file_content.splitlines()[:3])
                    Path(args_list[i + 1]).write_text(partial)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(coq_v_file))

        assert result.compilation_succeeded is False
        assert "Unknown tactic" in result.error_message
        # Partial timing data should still be present
        assert len(result.sentences) == 3

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, coq_v_file):
        """On timeout, process is killed and partial timing is parsed."""
        profile_file, *_ = _import_engine()

        proc = AsyncMock()
        proc.returncode = -9
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def slow_communicate():
            raise asyncio.TimeoutError()

        proc.communicate = slow_communicate

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text("")
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(coq_v_file), timeout_seconds=1)

        assert result.compilation_succeeded is False
        assert "timed out" in result.error_message.lower()
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_timing_file(self, coq_v_file):
        """Empty timing file → FileProfile with empty sentences."""
        profile_file, *_ = _import_engine()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text("")
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(coq_v_file))

        assert result.compilation_succeeded is True
        assert result.sentences == []
        assert result.total_time_s == 0.0

    @pytest.mark.asyncio
    async def test_proofs_sorted_by_total_time(self, tmp_path):
        """Proofs in FileProfile sorted by total_time_s descending."""
        profile_file, *_ = _import_engine()

        source = (
            "Lemma fast : True. Proof. exact I. Qed.\n"
            "Lemma slow : True. Proof. exact I. Qed.\n"
        )
        f = tmp_path / "TwoProofs.v"
        f.write_text(source)

        timing = (
            "Chars 0 - 18 [Lemma~fast~:~True.] 0.001 secs (0.001u,0.000s)\n"
            "Chars 19 - 25 [Proof.] 0.000 secs (0.000u,0.000s)\n"
            "Chars 26 - 34 [exact~I.] 0.010 secs (0.010u,0.000s)\n"
            "Chars 35 - 39 [Qed.] 0.020 secs (0.020u,0.000s)\n"
            "Chars 40 - 58 [Lemma~slow~:~True.] 0.001 secs (0.001u,0.000s)\n"
            "Chars 59 - 65 [Proof.] 0.000 secs (0.000u,0.000s)\n"
            "Chars 66 - 74 [exact~I.] 5.000 secs (4.900u,0.100s)\n"
            "Chars 75 - 79 [Qed.] 10.000 secs (9.800u,0.200s)\n"
        )

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(f))

        assert len(result.proofs) == 2
        assert result.proofs[0].lemma_name == "slow"
        assert result.proofs[1].lemma_name == "fast"

    @pytest.mark.asyncio
    async def test_bottleneck_classification_in_proofs(self, coq_v_file, timing_file_content):
        """Proofs include bottleneck classifications."""
        profile_file, *_ = _import_engine()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_file(str(coq_v_file))

        # slow_add has Qed at 15.2s with tactic time ~0.05s → SlowQed
        slow_add = result.proofs[0]
        assert slow_add.lemma_name == "slow_add"
        assert len(slow_add.bottlenecks) >= 1
        assert slow_add.bottlenecks[0].category == "SlowQed"

    @pytest.mark.asyncio
    async def test_timing_file_cleaned_up(self, coq_v_file):
        """Temporary timing file is cleaned up after profiling."""
        profile_file, *_ = _import_engine()

        timing_paths_captured = []
        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    timing_paths_captured.append(args_list[i + 1])
                    Path(args_list[i + 1]).write_text("")
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            await profile_file(str(coq_v_file))

        assert len(timing_paths_captured) == 1
        assert not os.path.exists(timing_paths_captured[0])


# ===================================================================
# Section 4.9: Single-Proof Profiling
# ===================================================================


class TestProfileSingleProof:
    """profile_single_proof — Spec 4.9."""

    @pytest.mark.asyncio
    async def test_returns_matching_proof(self, coq_v_file, timing_file_content):
        _, profile_single_proof, *_ = _import_engine()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_single_proof(str(coq_v_file), "slow_add")

        assert result.lemma_name == "slow_add"
        assert result.total_time_s > 0

    @pytest.mark.asyncio
    async def test_lemma_not_found_raises(self, coq_v_file, timing_file_content):
        """NOT_FOUND when lemma doesn't exist in the file."""
        _, profile_single_proof, *_ = _import_engine()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            with pytest.raises(ValueError, match="NOT_FOUND"):
                await profile_single_proof(str(coq_v_file), "nonexistent")


# ===================================================================
# Section 4.10: Ltac Profiling
# ===================================================================


class TestProfileLtac:
    """profile_ltac — Spec 4.10."""

    def _make_mock_session_manager(self, ltac_output=""):
        mgr = AsyncMock()
        mgr.open_proof_session = AsyncMock(return_value=("session-1", {}))
        mgr.submit_command = AsyncMock(return_value=ltac_output)
        mgr.submit_tactic = AsyncMock()
        mgr.close_proof_session = AsyncMock()
        mgr.get_original_script = MagicMock(return_value=[])
        return mgr

    @pytest.mark.asyncio
    async def test_requires_session_manager(self):
        _, _, profile_ltac, *_ = _import_engine()
        with pytest.raises(ValueError, match="session_manager"):
            await profile_ltac("/tmp/test.v", "foo", session_manager=None)

    @pytest.mark.asyncio
    async def test_enables_ltac_profiling(self):
        """Submits Set Ltac Profiling and Reset Ltac Profile."""
        _, _, profile_ltac, *_ = _import_engine()

        ltac_output = "total time: 1.000s\n\n─auto -------------------- 50.0%  50.0%       5    0.100s\n"
        mgr = self._make_mock_session_manager(ltac_output)

        result = await profile_ltac("/tmp/test.v", "foo", session_manager=mgr)

        # Verify profiling was enabled
        calls = [str(c) for c in mgr.submit_command.call_args_list]
        assert any("Set Ltac Profiling" in c for c in calls)
        assert any("Reset Ltac Profile" in c for c in calls)

    @pytest.mark.asyncio
    async def test_returns_ltac_profile(self):
        _, _, profile_ltac, *_ = _import_engine()

        ltac_output = (
            "total time: 3.200s\n"
            "\n"
            "─omega ------------------- 45.0%  45.0%      12    0.200s\n"
            "─eauto ------------------- 30.0%  30.0%       8    0.300s\n"
        )
        mgr = self._make_mock_session_manager(ltac_output)

        result = await profile_ltac("/tmp/test.v", "my_lemma", session_manager=mgr)

        assert result.lemma_name == "my_lemma"
        assert result.total_time_s == pytest.approx(3.2)
        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_session_always_closed(self):
        """Session is closed even on error."""
        _, _, profile_ltac, *_ = _import_engine()

        mgr = AsyncMock()
        mgr.open_proof_session = AsyncMock(return_value=("session-1", {}))
        mgr.submit_command = AsyncMock(side_effect=RuntimeError("boom"))
        mgr.close_proof_session = AsyncMock()
        mgr.get_original_script = MagicMock(return_value=[])

        with pytest.raises(RuntimeError, match="boom"):
            await profile_ltac("/tmp/test.v", "foo", session_manager=mgr)

        mgr.close_proof_session.assert_called_once_with("session-1")

    @pytest.mark.asyncio
    async def test_captures_show_ltac_profile(self):
        """Submits 'Show Ltac Profile CutOff 0.' to capture the profile."""
        _, _, profile_ltac, *_ = _import_engine()

        ltac_output = "total time: 0.500s\n\n─intro ------------------- 100.0% 100.0%     1    0.500s\n"
        mgr = self._make_mock_session_manager(ltac_output)

        await profile_ltac("/tmp/test.v", "foo", session_manager=mgr)

        calls = [str(c) for c in mgr.submit_command.call_args_list]
        assert any("Show Ltac Profile CutOff 0" in c for c in calls)


# ===================================================================
# Section 4.13: Timing Comparison
# ===================================================================


class TestCompareProfiles:
    """compare_profiles — Spec 4.13."""

    @pytest.mark.asyncio
    async def test_regression_detected(self, coq_v_file):
        """Regression flagged when delta_pct > 20 and delta_s > 0.5."""
        _, _, _, compare_profiles, *_ = _import_engine()

        # Create baseline timing file
        baseline_path = coq_v_file.parent / "baseline.timing"
        baseline_path.write_text(
            "Chars 0 - 10 [auto.] 1.000 secs (0.900u,0.100s)\n"
        )

        # Current run returns auto. at 2.5s
        current_timing = "Chars 0 - 10 [auto.] 2.500 secs (2.400u,0.100s)\n"
        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(current_timing)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await compare_profiles(str(coq_v_file), str(baseline_path))

        assert len(result.regressions) == 1
        assert result.regressions[0].status == "regressed"
        assert result.regressions[0].delta_s == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_stable_when_within_noise(self, coq_v_file):
        """Small changes classified as stable (dual threshold)."""
        _, _, _, compare_profiles, *_ = _import_engine()

        baseline_path = coq_v_file.parent / "baseline.timing"
        baseline_path.write_text(
            "Chars 0 - 10 [simpl.] 0.010 secs (0.010u,0.000s)\n"
        )

        current_timing = "Chars 0 - 10 [simpl.] 0.020 secs (0.020u,0.000s)\n"
        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(current_timing)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await compare_profiles(str(coq_v_file), str(baseline_path))

        # 100% increase but only 0.01s absolute → stable
        assert len(result.regressions) == 0
        assert result.diffs[0].status == "stable"

    @pytest.mark.asyncio
    async def test_improvement_detected(self, coq_v_file):
        _, _, _, compare_profiles, *_ = _import_engine()

        baseline_path = coq_v_file.parent / "baseline.timing"
        baseline_path.write_text(
            "Chars 0 - 10 [auto.] 5.000 secs (4.800u,0.200s)\n"
        )

        current_timing = "Chars 0 - 10 [auto.] 1.000 secs (0.900u,0.100s)\n"
        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(current_timing)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await compare_profiles(str(coq_v_file), str(baseline_path))

        assert len(result.improvements) == 1
        assert result.improvements[0].status == "improved"
        assert result.net_delta_s < 0

    @pytest.mark.asyncio
    async def test_new_and_removed_sentences(self, coq_v_file):
        _, _, _, compare_profiles, *_ = _import_engine()

        baseline_path = coq_v_file.parent / "baseline.timing"
        baseline_path.write_text(
            "Chars 0 - 10 [old_tactic.] 1.000 secs (0.900u,0.100s)\n"
        )

        current_timing = "Chars 5000 - 5010 [new_tactic.] 0.500 secs (0.400u,0.100s)\n"
        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(current_timing)
                    break
            return proc

        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await compare_profiles(str(coq_v_file), str(baseline_path))

        statuses = {d.status for d in result.diffs}
        assert "removed" in statuses
        assert "new" in statuses


# ===================================================================
# Entry Point Routing
# ===================================================================


class TestProfileProofEntryPoint:
    """profile_proof entry point — routes by mode."""

    @pytest.mark.asyncio
    async def test_invalid_request_returns_error(self):
        *_, profile_proof, _ = _import_engine()
        _, _, ProfileRequest, _, _ = _import_types()

        req = ProfileRequest(file_path="/tmp/test.ml")  # wrong extension
        result = await profile_proof(req)
        assert result.compilation_succeeded is False
        assert "INVALID_FILE" in result.error_message

    @pytest.mark.asyncio
    async def test_timing_mode_routes_to_file_profiling(self, coq_v_file, timing_file_content):
        *_, profile_proof, _ = _import_engine()
        _, _, ProfileRequest, _, _ = _import_types()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        req = ProfileRequest(file_path=str(coq_v_file), mode="timing")
        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_proof(req)

        FileProfile, *_ = _import_types()
        assert isinstance(result, FileProfile)
        assert result.compilation_succeeded is True

    @pytest.mark.asyncio
    async def test_timing_mode_with_lemma_routes_to_single_proof(self, coq_v_file, timing_file_content):
        *_, profile_proof, _ = _import_engine()
        _, _, ProfileRequest, ProofProfile, _ = _import_types()

        proc = _make_mock_process(returncode=0)

        async def mock_create_subprocess(*args, **kwargs):
            args_list = list(args)
            for i, a in enumerate(args_list):
                if str(a) == "-time-file" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_text(timing_file_content)
                    break
            return proc

        req = ProfileRequest(file_path=str(coq_v_file), mode="timing", lemma_name="slow_add")
        with patch("Poule.profiler.engine.locate_coqc", return_value="/usr/bin/coqc"), \
             patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            result = await profile_proof(req)

        assert isinstance(result, ProofProfile)
        assert result.lemma_name == "slow_add"

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_error(self, coq_v_file):
        *_, profile_proof, _ = _import_engine()
        _, _, ProfileRequest, _, _ = _import_types()

        req = ProfileRequest(file_path=str(coq_v_file), mode="unknown")
        result = await profile_proof(req)
        assert result.compilation_succeeded is False
        assert "Unknown mode" in result.error_message
