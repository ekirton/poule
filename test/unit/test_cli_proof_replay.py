"""TDD tests for the replay-proof CLI command.

Tests are written BEFORE implementation. They will fail with ImportError
until the replay-proof command is implemented.

Spec: specification/cli.md §4.6
Architecture: doc/architecture/cli.md
Feature: doc/features/cli-proof-replay.md

Import paths under test:
  poule.cli.commands (cmd_replay_proof)
  poule.cli.formatting (format_proof_trace)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from Poule.session.types import (
    Goal,
    Hypothesis,
    Premise,
    PremiseAnnotation,
    ProofState,
    ProofTrace,
    TraceStep,
)
from Poule.session.errors import (
    BACKEND_CRASHED,
    FILE_NOT_FOUND,
    PROOF_NOT_FOUND,
    SessionError,
)


# ---------------------------------------------------------------------------
# Sample data helpers — use real types per test/CLAUDE.md
# ---------------------------------------------------------------------------


def _make_goal(index=0, type_="forall n m, n + m = m + n", hyps=None):
    if hyps is None:
        hyps = [
            Hypothesis(name="n", type="nat"),
            Hypothesis(name="m", type="nat"),
        ]
    return Goal(index=index, type=type_, hypotheses=hyps)


def _make_state(step_index=0, is_complete=False, goals=None, session_id="test-session"):
    if goals is None:
        goals = [] if is_complete else [_make_goal()]
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=0 if goals else None,
        goals=goals,
    )


def _make_trace(total_steps=2, session_id="test-session"):
    """Create a 2-step proof trace: initial → intros → ring."""
    steps = [
        TraceStep(
            step_index=0,
            tactic=None,
            state=_make_state(step_index=0, session_id=session_id),
        ),
        TraceStep(
            step_index=1,
            tactic="intros n m.",
            state=_make_state(
                step_index=1,
                session_id=session_id,
                goals=[_make_goal(type_="n + m = m + n")],
            ),
        ),
        TraceStep(
            step_index=2,
            tactic="ring.",
            state=_make_state(step_index=2, is_complete=True, session_id=session_id),
        ),
    ]
    return ProofTrace(
        schema_version=1,
        session_id=session_id,
        proof_name="add_comm",
        file_path="test.v",
        total_steps=total_steps,
        steps=steps,
    )


def _make_premises():
    """Premise annotations for a 2-step proof."""
    return [
        PremiseAnnotation(
            step_index=1,
            tactic="intros n m.",
            premises=[],
        ),
        PremiseAnnotation(
            step_index=2,
            tactic="ring.",
            premises=[
                Premise(name="Stdlib.setoid_ring.Ring_theory.ring_theory", kind="lemma"),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------


def _import_cli():
    from Poule.cli.commands import cli
    return cli


def _import_format_proof_trace():
    from Poule.cli.formatting import format_proof_trace
    return format_proof_trace


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


def _make_mock_manager(trace=None, premises=None, create_error=None):
    """Build a mock SessionManager with async methods."""
    mgr = MagicMock()
    if create_error:
        mgr.create_session = AsyncMock(side_effect=create_error)
    else:
        mgr.create_session = AsyncMock(
            return_value=("test-session", _make_state())
        )
    mgr.extract_trace = AsyncMock(return_value=trace or _make_trace())
    mgr.get_premises = AsyncMock(return_value=premises or _make_premises())
    mgr.close_session = AsyncMock()
    return mgr


# ===========================================================================
# 1. Formatting — format_proof_trace
# ===========================================================================


class TestFormatProofTrace:
    """format_proof_trace: human-readable and JSON output."""

    def test_human_readable_header(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=False)
        assert "Proof: add_comm" in output
        assert "File:  test.v" in output
        assert "Steps: 2" in output

    def test_human_readable_steps(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=False)
        assert "Step 0 (initial)" in output
        assert "Step 1: intros n m." in output
        assert "Step 2: ring." in output

    def test_human_readable_goals_and_hypotheses(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=False)
        assert "n : nat" in output
        assert "m : nat" in output

    def test_human_readable_complete_marker(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=False)
        assert "(proof complete)" in output

    def test_human_readable_with_premises(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        premises = _make_premises()
        output = fmt(trace, premises=premises, json_mode=False)
        assert "Premises:" in output
        assert "ring_theory" in output

    def test_json_mode_without_premises(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=True)
        parsed = json.loads(output)
        assert parsed["schema_version"] == 1
        assert parsed["proof_name"] == "add_comm"
        assert parsed["total_steps"] == 2
        assert len(parsed["steps"]) == 3  # N+1 steps: 0..N

    def test_json_mode_with_premises(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        premises = _make_premises()
        output = fmt(trace, premises=premises, json_mode=True)
        parsed = json.loads(output)
        assert "trace" in parsed
        assert "premises" in parsed
        assert parsed["trace"]["proof_name"] == "add_comm"
        assert len(parsed["premises"]) == 2
        assert parsed["premises"][1]["tactic"] == "ring."

    def test_json_mode_produces_valid_json(self):
        fmt = _import_format_proof_trace()
        trace = _make_trace()
        output = fmt(trace, json_mode=True)
        # Must not raise
        parsed = json.loads(output)
        assert isinstance(parsed, dict)


# ===========================================================================
# 2. replay-proof command — happy paths
# ===========================================================================


class TestReplayProofCommand:
    """CLI replay-proof subcommand happy paths."""

    def test_happy_path_human_readable(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        assert result.exit_code == 0
        assert "Proof: add_comm" in result.output
        assert "Steps: 2" in result.output

    def test_happy_path_json(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "test.v", "add_comm", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["proof_name"] == "add_comm"
        assert parsed["total_steps"] == 2

    def test_with_premises_flag(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "test.v", "add_comm", "--premises"])
        assert result.exit_code == 0
        assert "Premises:" in result.output
        mgr.get_premises.assert_called_once()

    def test_json_with_premises(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(
                cli, ["replay-proof", "test.v", "add_comm", "--json", "--premises"]
            )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "trace" in parsed
        assert "premises" in parsed

    def test_session_manager_called_correctly(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        mgr.create_session.assert_called_once_with("test.v", "add_comm")
        mgr.extract_trace.assert_called_once_with("test-session")

    def test_session_always_closed(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        mgr.close_session.assert_called_once_with("test-session")

    def test_premises_not_fetched_without_flag(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        mgr.get_premises.assert_not_called()


# ===========================================================================
# 3. replay-proof command — error handling
# ===========================================================================


class TestReplayProofErrors:
    """CLI replay-proof error scenarios."""

    def test_file_not_found_exits_1(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager(
            create_error=SessionError(FILE_NOT_FOUND, "File not found: missing.v")
        )
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "missing.v", "add_comm"])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_proof_not_found_exits_1(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager(
            create_error=SessionError(PROOF_NOT_FOUND, "Proof not found: bad_name")
        )
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "test.v", "bad_name"])
        assert result.exit_code == 1
        assert "Proof not found" in result.output

    def test_backend_crashed_exits_1(self, runner):
        cli = _import_cli()
        mgr = _make_mock_manager()
        mgr.extract_trace = AsyncMock(
            side_effect=SessionError(BACKEND_CRASHED, "test-session")
        )
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            result = runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        assert result.exit_code == 1
        assert "crashed" in result.output.lower() or "Backend" in result.output

    def test_missing_args_exits_2(self, runner):
        cli = _import_cli()
        result = runner.invoke(cli, ["replay-proof"])
        assert result.exit_code == 2

    def test_missing_proof_name_exits_2(self, runner):
        cli = _import_cli()
        result = runner.invoke(cli, ["replay-proof", "test.v"])
        assert result.exit_code == 2

    def test_session_closed_on_error(self, runner):
        """Session must be closed even when extract_trace fails."""
        cli = _import_cli()
        mgr = _make_mock_manager()
        mgr.extract_trace = AsyncMock(
            side_effect=SessionError(BACKEND_CRASHED, "test-session")
        )
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            runner.invoke(cli, ["replay-proof", "test.v", "add_comm"])
        mgr.close_session.assert_called_once_with("test-session")

    def test_session_not_closed_when_create_fails(self, runner):
        """When create_session fails, no session exists to close."""
        cli = _import_cli()
        mgr = _make_mock_manager(
            create_error=SessionError(FILE_NOT_FOUND, "File not found: missing.v")
        )
        with patch("Poule.cli.commands._get_backend_factory") as mock_bf, \
             patch("Poule.cli.commands.SessionManager", return_value=mgr):
            runner.invoke(cli, ["replay-proof", "missing.v", "add_comm"])
        mgr.close_session.assert_not_called()
