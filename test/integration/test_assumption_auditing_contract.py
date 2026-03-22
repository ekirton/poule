"""Contract tests for Assumption Auditing Engine against real Coq backend.

These tests verify that mocked session manager behavior in the unit tests
matches the real Coq backend interface.

Spec: specification/assumption-auditing.md
"""

from __future__ import annotations

import pytest


class TestContractSessionManager:
    """Contract tests verifying mocked session manager behavior against real Coq.

    These tests exercise the real Proof Session Manager to confirm
    that the mock return values in the unit tests match reality.
    """

    @pytest.mark.asyncio
    async def test_print_assumptions_closed_theorem(self):
        """Verify 'Closed under the global context' output for a closed theorem."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            await manager.send_command(
                session_id, "From Coq Require Import PeanoNat.", prefer_coqtop=True,
            )
            output = await manager.send_command(
                session_id, "Print Assumptions Nat.add_0_r.", prefer_coqtop=True,
            )
            assert "Closed under the global context" in output
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_print_assumptions_classical_theorem(self):
        """Verify that classic appears in output for a classical theorem."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            # Load Classical and define a simple theorem
            await manager.send_command(
                session_id, "Require Import Coq.Logic.Classical_Prop.", prefer_coqtop=True,
            )
            await manager.send_command(
                session_id,
                "Theorem test_em : forall P : Prop, P \\/ ~ P. Proof. apply classic. Qed.",
                prefer_coqtop=True,
            )
            output = await manager.send_command(
                session_id, "Print Assumptions test_em.", prefer_coqtop=True,
            )
            assert "classic" in output
            assert " : " in output
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_query_declaration_kind_axiom(self):
        """Verify that querying kind of an axiom returns 'Axiom' or 'Parameter'."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            await manager.send_command(
                session_id, "Require Import Coq.Logic.Classical_Prop.", prefer_coqtop=True,
            )
            kind = await manager.query_declaration_kind(
                session_id, "Coq.Logic.Classical_Prop.classic",
            )
            assert kind in ("Axiom", "Parameter")
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_query_declaration_kind_opaque(self):
        """Verify that querying kind of a Qed lemma returns opaque indicator."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            await manager.send_command(
                session_id,
                "Lemma trivial_lemma : True. Proof. exact I. Qed.",
                prefer_coqtop=True,
            )
            kind = await manager.query_declaration_kind(session_id, "trivial_lemma")
            assert kind == "Opaque"
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_audit_file_local_theorem_in_proof_session(self):
        """Contract: audit_assumptions finds file-local theorems in proof sessions.

        Spec §4.1 + proof-session.md §4.4.1: file context is loaded into
        the coqtop subprocess, so Print Assumptions can resolve same-file names."""
        from Poule.auditing.engine import audit_assumptions
        from Poule.session.manager import SessionManager

        manager = SessionManager()
        # algebra.v: my_lemma at line 14, add_0_r_v3 at line 38
        sid, _ = await manager.create_session(
            "/poule/examples/algebra.v", "add_0_r_v3",
        )
        try:
            result = await audit_assumptions(manager, "my_lemma", sid)
            assert result.name == "my_lemma"
            assert result.is_closed is True  # reflexivity uses no axioms
        finally:
            await manager.close_session(sid)

    @pytest.mark.asyncio
    async def test_print_module_lists_declarations(self):
        """Verify Print Module output contains theorem names."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            output = await manager.send_command(
                session_id, "Print Module Coq.Init.Nat.", prefer_coqtop=True,
            )
            # Should contain at least some declaration keywords
            assert "Theorem" in output or "Lemma" in output or "Definition" in output or "Fixpoint" in output
        finally:
            await manager.close_session(session_id)
