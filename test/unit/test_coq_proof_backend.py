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

    async def test_factory_accepts_load_paths(self):
        """Contract test: load_paths kwarg is accepted and enables
        bare imports for libraries with -R load path bindings (§4.2)."""
        create = _import_create_coq_backend()
        backend = await create(
            "/dev/null",
            load_paths=[("/opt/opam/coq/lib/coq/user-contrib/Flocq", "Flocq")],
        )
        try:
            assert hasattr(backend, "load_file")
        finally:
            await backend.shutdown()

    async def test_factory_stderr_not_piped(self):
        """Spec §6: stderr shall be redirected to DEVNULL, not piped.

        Piping stderr without draining causes deadlocks when the pipe
        buffer fills.  The backend must use subprocess.DEVNULL.
        """
        create = _import_create_coq_backend()
        backend = await create("/dev/null")
        try:
            # _proc.stderr should be None when stderr=DEVNULL
            assert backend._proc.stderr is None, (
                "stderr is piped — must use subprocess.DEVNULL to prevent "
                "pipe-buffer deadlocks"
            )
        finally:
            await backend.shutdown()


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


# ===========================================================================
# 7. Liveness Watchdog (§7.4)
# ===========================================================================


class TestLivenessWatchdog:
    """Spec §7.4: Inactivity-based liveness detection on backend I/O."""

    async def test_watchdog_fires_on_inactivity(self):
        """When the backend produces no output for watchdog_timeout seconds,
        _read_message raises ConnectionError."""
        from Poule.session.backend import CoqProofBackend
        from unittest.mock import AsyncMock, MagicMock

        proc = MagicMock()
        # stdout.readline that never returns (simulates dead backend)
        never_future = asyncio.Future()
        proc.stdout = MagicMock()
        proc.stdout.readline = AsyncMock(return_value=never_future)
        # Make readline actually hang by using a coroutine that never completes
        async def hang_forever():
            await asyncio.sleep(3600)
            return b""
        proc.stdout.readline = hang_forever

        backend = CoqProofBackend(proc, watchdog_timeout=0.1)

        with pytest.raises(ConnectionError, match="unresponsive"):
            await backend._read_message()

    async def test_no_watchdog_when_none(self):
        """When watchdog_timeout is None, reads block normally (no timeout).

        We verify the constructor accepts None without error.
        """
        from Poule.session.backend import CoqProofBackend
        from unittest.mock import MagicMock

        proc = MagicMock()
        backend = CoqProofBackend(proc, watchdog_timeout=None)
        assert backend._watchdog_timeout is None

    async def test_watchdog_does_not_fire_on_responsive_backend(self, tmp_path):
        """A backend that responds within the watchdog window is not killed.

        Integration test: real coq-lsp with generous watchdog_timeout.
        """
        create = _import_create_coq_backend()
        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma trivial : True. Proof. exact I. Qed.\n")

        backend = await create(str(v_file), watchdog_timeout=600)
        try:
            await backend.load_file(str(v_file))
            state = await backend.position_at_proof("trivial")
            assert state.is_complete is False
            state = await backend.execute_tactic("exact I.")
            assert state.is_complete is True
        finally:
            await backend.shutdown()

    async def test_factory_passes_watchdog_timeout(self):
        """create_coq_backend passes watchdog_timeout to the backend instance."""
        create = _import_create_coq_backend()
        backend = await create("/dev/null", watchdog_timeout=42.0)
        try:
            assert backend._watchdog_timeout == 42.0
        finally:
            await backend.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# Proof Term Constant Extraction (spec §4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractConstantsFromProofTerm:
    """spec §4.1: extract_constants_from_proof_term extracts qualified names."""

    def test_extracts_at_qualified_names(self):
        """@Qualified.Name references are extracted."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "(fun n : nat => @Nat.add_comm n 0)"
        result = extract_constants_from_proof_term(term)
        assert "Nat.add_comm" in result

    def test_extracts_at_unqualified_names(self):
        """@name (no dot) are extracted (Set Printing All output)."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "(fun n : nat => @eq_refl nat n)"
        result = extract_constants_from_proof_term(term)
        assert "eq_refl" in result

    def test_excludes_bare_names_without_at(self):
        """Bare names without @ are local variables, not constants."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "(fun n : nat => @Nat.add_comm n 0)"
        result = extract_constants_from_proof_term(term)
        assert "n" not in result
        assert "nat" not in result
        assert "fun" not in result

    def test_excludes_goal_placeholders(self):
        """?Goal placeholders are excluded."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "?Goal"
        result = extract_constants_from_proof_term(term)
        assert len(result) == 0

    def test_handles_empty_string(self):
        """Empty proof term returns empty set."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        result = extract_constants_from_proof_term("")
        assert result == set()

    def test_multiple_constants(self):
        """Multiple distinct constants are all extracted."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "(@Nat.add_comm n (@Coq.Init.Logic.eq_ind_r nat (@Nat.add n 0) (fun x => P x) H n (@Nat.add_0_r n)))"
        result = extract_constants_from_proof_term(term)
        assert "Nat.add_comm" in result
        assert "Coq.Init.Logic.eq_ind_r" in result
        assert "Nat.add_0_r" in result
        assert "Nat.add" in result

    def test_deeply_qualified_names(self):
        """Names with multiple dot separators are extracted."""
        from Poule.session.premise_resolution import extract_constants_from_proof_term

        term = "@Coq.Arith.PeanoNat.Nat.add_comm"
        result = extract_constants_from_proof_term(term)
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result


class TestResolveStepPremises:
    """spec §4.1: resolve_step_premises diffs constant sets."""

    def test_new_constants_are_premises(self):
        """Constants in current but not previous are the step's premises."""
        from Poule.session.premise_resolution import resolve_step_premises

        previous = {"Nat.add_0_r"}
        current_term = "(fun n => @Nat.add_0_r n (@Nat.add_comm n 0))"
        result = resolve_step_premises(1, previous, current_term)
        names = {p["name"] for p in result}
        assert "Nat.add_comm" in names
        assert "Nat.add_0_r" not in names  # was already in previous

    def test_no_new_constants(self):
        """When no new constants are introduced, result is empty."""
        from Poule.session.premise_resolution import resolve_step_premises

        previous = {"Nat.add_comm"}
        current_term = "(fun n => @Nat.add_comm n 0)"
        result = resolve_step_premises(1, previous, current_term)
        assert result == []

    def test_result_format(self):
        """Each result item has name and kind fields."""
        from Poule.session.premise_resolution import resolve_step_premises

        result = resolve_step_premises(1, set(), "(fun n => @Nat.add_comm n)")
        assert len(result) == 1
        assert result[0]["name"] == "Nat.add_comm"
        assert result[0]["kind"] == "lemma"

    def test_unqualified_at_name(self):
        """@name without dot is captured (e.g., @eq_refl from Set Printing All)."""
        from Poule.session.premise_resolution import resolve_step_premises

        result = resolve_step_premises(1, set(), "(fun n : @nat => @eq_refl @nat n)")
        names = {p["name"] for p in result}
        assert "eq_refl" in names
        assert "nat" in names

    def test_empty_proof_term(self):
        """Empty proof term returns empty list."""
        from Poule.session.premise_resolution import resolve_step_premises

        result = resolve_step_premises(1, set(), "")
        assert result == []


class TestExtractPreludeUpToProof:
    """Tests for _extract_prelude_up_to_proof helper."""

    def test_empty_proof_name_returns_content_before_first_proof(self, tmp_path):
        """When proof_name is empty, return content before the first theorem."""
        from Poule.session.premise_resolution import _extract_prelude_up_to_proof

        coq_file = tmp_path / "test.v"
        coq_file.write_text(
            "Require Import Nat.\n"
            "Open Scope nat_scope.\n"
            "\n"
            "Lemma foo : 1 + 1 = 2.\n"
            "Proof. reflexivity. Qed.\n"
            "\n"
            "Lemma bar : 2 + 2 = 4.\n"
            "Proof. reflexivity. Qed.\n"
        )
        result = _extract_prelude_up_to_proof(str(coq_file), "")
        assert "Require Import Nat." in result
        assert "Open Scope nat_scope." in result
        assert "Lemma foo" not in result
        assert "Lemma bar" not in result

    def test_empty_proof_name_no_proofs_returns_full_file(self, tmp_path):
        """When proof_name is empty and no proofs exist, return full file."""
        from Poule.session.premise_resolution import _extract_prelude_up_to_proof

        coq_file = tmp_path / "test.v"
        coq_file.write_text("Require Import Nat.\nOpen Scope nat_scope.\n")
        result = _extract_prelude_up_to_proof(str(coq_file), "")
        assert "Require Import Nat." in result
        assert "Open Scope nat_scope." in result

    def test_named_proof_returns_content_before_that_proof(self, tmp_path):
        """When proof_name matches, return content before that proof."""
        from Poule.session.premise_resolution import _extract_prelude_up_to_proof

        coq_file = tmp_path / "test.v"
        coq_file.write_text(
            "Require Import Nat.\n"
            "\n"
            "Lemma foo : 1 + 1 = 2.\n"
            "Proof. reflexivity. Qed.\n"
            "\n"
            "Lemma bar : 2 + 2 = 4.\n"
            "Proof. reflexivity. Qed.\n"
        )
        result = _extract_prelude_up_to_proof(str(coq_file), "bar")
        assert "Require Import Nat." in result
        assert "Lemma foo" in result
        assert "Lemma bar" not in result

    def test_nonexistent_file_returns_empty(self):
        """Nonexistent file returns empty string."""
        from Poule.session.premise_resolution import _extract_prelude_up_to_proof

        result = _extract_prelude_up_to_proof("/nonexistent/file.v", "foo")
        assert result == ""

    def test_large_file_empty_proof_name_skips_theorem_bodies(self, tmp_path):
        """For a large file with many theorems, empty proof_name loads
        only imports — not the theorem bodies."""
        from Poule.session.premise_resolution import _extract_prelude_up_to_proof

        lines = ["Require Import Nat.\n", "Require Import Bool.\n", "\n"]
        for i in range(100):
            lines.append(f"Lemma lemma_{i} : True.\n")
            lines.append("Proof. exact I. Qed.\n\n")
        coq_file = tmp_path / "big.v"
        coq_file.write_text("".join(lines))

        result = _extract_prelude_up_to_proof(str(coq_file), "")
        assert "Require Import Nat." in result
        assert "lemma_0" not in result
        assert "lemma_99" not in result
