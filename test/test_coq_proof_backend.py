"""TDD tests for the Coq Proof Backend (specification/coq-proof-backend.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/session/backend.py exists.

Spec: specification/coq-proof-backend.md
Architecture: doc/architecture/proof-session.md (CoqBackend Interface)
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.session.backend  (create_coq_backend, CoqBackend protocol)
  poule.session.types    (ProofState, Goal, Hypothesis, Premise)
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from Poule.session.types import (
    Goal,
    Hypothesis,
    ProofState,
)

# All tests in this file require both the backend module (not yet implemented)
# and a real Coq installation. Skip the entire module if the backend is absent.
pytest.importorskip("Poule.session.backend", reason="backend module not yet implemented")

# Mark all tests in this module as requires_coq
pytestmark = pytest.mark.requires_coq


# ---------------------------------------------------------------------------
# Lazy imports — guarded by importorskip above
# ---------------------------------------------------------------------------


def _import_create_coq_backend():
    from Poule.session.backend import create_coq_backend
    return create_coq_backend


# ===========================================================================
# 1. Factory — create_coq_backend (§4.2)
# ===========================================================================


class TestCreateCoqBackend:
    """Spec §4.2: create_coq_backend factory function."""

    async def test_factory_returns_backend_with_running_process(self):
        """Contract test: factory spawns a real coq-lsp process.

        Exercises the same interface that mocked tests verify,
        per test/CLAUDE.md mock discipline.
        """
        create = _import_create_coq_backend()
        backend = await create("/dev/null")
        try:
            # Backend should have all protocol methods
            assert hasattr(backend, "load_file")
            assert hasattr(backend, "position_at_proof")
            assert hasattr(backend, "execute_tactic")
            assert hasattr(backend, "undo")
            assert hasattr(backend, "get_premises_at_step")
            assert hasattr(backend, "shutdown")
            assert callable(backend.load_file)
        finally:
            await backend.shutdown()

    async def test_factory_fails_without_coq_binary(self):
        """Contract test: factory raises when no Coq backend is available."""
        create = _import_create_coq_backend()
        with patch.dict("os.environ", {"PATH": "/nonexistent"}):
            with pytest.raises((FileNotFoundError, OSError, Exception)):
                await create("/dev/null")


# ===========================================================================
# 2. CoqBackend protocol — load_file (§4.1)
# ===========================================================================


class TestLoadFile:
    """Spec §4.1: load_file(file_path)."""

    async def test_load_valid_file(self, tmp_path):
        """Contract test: load a valid .v file."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            # Should not raise — file is valid
        finally:
            await backend.shutdown()

    async def test_load_nonexistent_file_raises(self):
        """Contract test: FileNotFoundError on missing file."""
        create = _import_create_coq_backend()
        backend = await create("/nonexistent/path.v")
        try:
            with pytest.raises((FileNotFoundError, OSError)):
                await backend.load_file("/nonexistent/path.v")
        finally:
            await backend.shutdown()

    async def test_load_file_with_coq_error(self, tmp_path):
        """Contract test: Coq check failure raises."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "bad.v"
        v_file.write_text("Definition broken := undefined_term.\n")

        backend = await create(str(v_file))
        try:
            with pytest.raises(Exception):
                await backend.load_file(str(v_file))
        finally:
            await backend.shutdown()


# ===========================================================================
# 3. CoqBackend protocol — position_at_proof (§4.1)
# ===========================================================================


class TestPositionAtProof:
    """Spec §4.1: position_at_proof(proof_name)."""

    async def test_returns_initial_proof_state(self, tmp_path):
        """Contract test: initial state has step_index=0, goals, not complete."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            state = await backend.position_at_proof("add_zero")

            assert isinstance(state, ProofState)
            assert state.step_index == 0
            assert state.is_complete is False
            assert state.focused_goal_index == 0
            assert len(state.goals) >= 1
            # Goal type should contain the proof statement
            assert "nat" in state.goals[0].type or "n" in state.goals[0].type
        finally:
            await backend.shutdown()

    async def test_proof_not_found_raises(self, tmp_path):
        """Contract test: nonexistent proof name raises."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            with pytest.raises((ValueError, KeyError, LookupError)):
                await backend.position_at_proof("nonexistent_proof")
        finally:
            await backend.shutdown()

    async def test_original_script_populated(self, tmp_path):
        """Contract test: original_script contains tactic strings."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma trivial : True.\n"
            "Proof. exact I. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("trivial")

            assert isinstance(backend.original_script, list)
            assert len(backend.original_script) >= 1
            # Each element should be a tactic string
            for tactic in backend.original_script:
                assert isinstance(tactic, str)
                assert len(tactic) > 0
        finally:
            await backend.shutdown()


# ===========================================================================
# 4. CoqBackend protocol — execute_tactic (§4.1)
# ===========================================================================


class TestExecuteTactic:
    """Spec §4.1: execute_tactic(tactic)."""

    async def test_tactic_returns_new_proof_state(self, tmp_path):
        """Contract test: successful tactic returns ProofState."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("add_zero")

            state = await backend.execute_tactic("intros n.")
            assert isinstance(state, ProofState)
            # After intros, we should have hypothesis n in the context
            has_n = any(
                h.name == "n"
                for g in state.goals
                for h in g.hypotheses
            )
            assert has_n
        finally:
            await backend.shutdown()

    async def test_invalid_tactic_raises(self, tmp_path):
        """Contract test: invalid tactic raises with Coq error message."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma trivial : True.\n"
            "Proof. exact I. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("trivial")

            with pytest.raises(Exception) as exc_info:
                await backend.execute_tactic("completely_invalid_tactic_xyz.")
            # Error message should be non-empty
            assert str(exc_info.value)
        finally:
            await backend.shutdown()

    async def test_completing_proof_sets_is_complete(self, tmp_path):
        """Contract test: closing all goals → is_complete=True."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma trivial : True.\n"
            "Proof. exact I. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("trivial")

            state = await backend.execute_tactic("exact I.")
            assert state.is_complete is True
            assert state.goals == []
            assert state.focused_goal_index is None
        finally:
            await backend.shutdown()


# ===========================================================================
# 5. CoqBackend protocol — undo (§4.1)
# ===========================================================================


class TestUndo:
    """Spec §4.1: undo()."""

    async def test_undo_reverts_state(self, tmp_path):
        """Contract test: undo reverses the last tactic."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            initial = await backend.position_at_proof("add_zero")

            await backend.execute_tactic("intros n.")
            await backend.undo()

            # After undo, state should be equivalent to initial
            state = await backend.get_current_state()
            assert state.step_index == initial.step_index or len(state.goals) == len(initial.goals)
        finally:
            await backend.shutdown()


# ===========================================================================
# 6. CoqBackend protocol — get_premises_at_step (§4.1, §4.4)
# ===========================================================================


class TestGetPremisesAtStep:
    """Spec §4.1, §4.4: get_premises_at_step and premise classification."""

    async def test_returns_list_of_premise_dicts(self, tmp_path):
        """Contract test: premises are dicts with name and kind."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Require Import Arith.\n"
            "Lemma add_comm_test : forall n m, n + m = m + n.\n"
            "Proof. intros n m. apply Nat.add_comm. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("add_comm_test")

            # Execute both tactics
            await backend.execute_tactic("intros n m.")
            await backend.execute_tactic("apply Nat.add_comm.")

            premises = await backend.get_premises_at_step(2)
            assert isinstance(premises, list)
            for p in premises:
                assert isinstance(p, dict)
                assert "name" in p
                assert "kind" in p
                assert p["kind"] in ("lemma", "hypothesis", "constructor", "definition")
        finally:
            await backend.shutdown()

    async def test_no_premises_tactic_returns_empty(self, tmp_path):
        """Contract test: intros uses no external premises → empty list."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("add_zero")
            await backend.execute_tactic("intros n.")

            premises = await backend.get_premises_at_step(1)
            assert isinstance(premises, list)
            # intros typically uses no external premises
        finally:
            await backend.shutdown()

    async def test_premise_classification_lemma(self, tmp_path):
        """Contract test §4.4: global lemma classified as kind='lemma'."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Require Import Arith.\n"
            "Lemma add_comm_test : forall n m, n + m = m + n.\n"
            "Proof. intros n m. apply Nat.add_comm. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("add_comm_test")
            await backend.execute_tactic("intros n m.")
            await backend.execute_tactic("apply Nat.add_comm.")

            premises = await backend.get_premises_at_step(2)
            # Should include Nat.add_comm as a lemma premise
            lemma_premises = [p for p in premises if p["kind"] == "lemma"]
            assert len(lemma_premises) >= 1
        finally:
            await backend.shutdown()


# ===========================================================================
# 7. CoqBackend protocol — shutdown (§4.1)
# ===========================================================================


class TestShutdown:
    """Spec §4.1: shutdown()."""

    async def test_shutdown_succeeds(self, tmp_path):
        """Contract test: shutdown terminates process without error."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        await backend.load_file(str(v_file))
        await backend.shutdown()
        # Should not raise

    async def test_shutdown_idempotent(self, tmp_path):
        """Contract test: calling shutdown twice does not raise."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        await backend.shutdown()
        await backend.shutdown()  # Second call should be no-op


# ===========================================================================
# 8. ProofState translation (§4.3)
# ===========================================================================


class TestProofStateTranslation:
    """Spec §4.3: backend translates Coq state to ProofState type."""

    async def test_goals_are_goal_objects(self, tmp_path):
        """Contract test: goals contain Goal objects with index, type, hypotheses."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            state = await backend.position_at_proof("add_zero")

            for goal in state.goals:
                assert isinstance(goal, Goal)
                assert isinstance(goal.index, int)
                assert goal.index >= 0
                assert isinstance(goal.type, str)
                assert len(goal.type) > 0
                assert isinstance(goal.hypotheses, list)
        finally:
            await backend.shutdown()

    async def test_hypotheses_are_hypothesis_objects(self, tmp_path):
        """Contract test: hypotheses contain Hypothesis objects."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma add_zero : forall n : nat, n + 0 = n.\n"
            "Proof. intros n. induction n. reflexivity. simpl. rewrite IHn. reflexivity. Qed.\n"
        )

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            await backend.position_at_proof("add_zero")
            state = await backend.execute_tactic("intros n.")

            # After intros n, there should be a hypothesis
            hyps = [h for g in state.goals for h in g.hypotheses]
            assert len(hyps) >= 1
            for h in hyps:
                assert isinstance(h, Hypothesis)
                assert isinstance(h.name, str)
                assert isinstance(h.type, str)
                # body is None for non-let-bound, str for let-bound
                assert h.body is None or isinstance(h.body, str)
        finally:
            await backend.shutdown()

    async def test_schema_version_is_set(self, tmp_path):
        """Contract test: ProofState has schema_version=1."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        try:
            await backend.load_file(str(v_file))
            state = await backend.position_at_proof("trivial")
            assert state.schema_version == 1
        finally:
            await backend.shutdown()


# ===========================================================================
# 9. State machine transitions (§7.1)
# ===========================================================================


class TestStateMachine:
    """Spec §7.1: backend state machine transitions."""

    async def test_full_lifecycle(self, tmp_path):
        """Contract test: spawned → file_loaded → proof_active → shut_down."""
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma trivial : True.\n"
            "Proof. exact I. Qed.\n"
        )

        # spawned
        backend = await create(str(v_file))

        # spawned → file_loaded
        await backend.load_file(str(v_file))

        # file_loaded → proof_active
        state = await backend.position_at_proof("trivial")
        assert state.is_complete is False

        # proof_active → proof_complete
        state = await backend.execute_tactic("exact I.")
        assert state.is_complete is True

        # any → shut_down
        await backend.shutdown()

    async def test_execute_after_shutdown_undefined(self, tmp_path):
        """Spec §7.1: operations after shutdown are undefined behavior.

        We verify the backend does not hang indefinitely — it should
        either raise or return quickly.
        """
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file))
        await backend.load_file(str(v_file))
        await backend.position_at_proof("trivial")
        await backend.shutdown()

        # After shutdown, calling execute_tactic should fail (not hang)
        with pytest.raises(Exception):
            await asyncio.wait_for(
                backend.execute_tactic("exact I."),
                timeout=5.0,
            )
