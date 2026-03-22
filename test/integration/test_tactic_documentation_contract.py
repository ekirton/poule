"""Contract tests for Tactic Documentation — requires a live Coq instance.

Extracted from test/test_tactic_documentation.py. These tests verify that
the mock assumptions in the unit tests hold against real Coq backends.

The ``requires_coq`` marker is applied automatically by conftest.py.
"""

from __future__ import annotations

import pytest


class TestContractTacticLookup:
    """Contract: real coq_query returns parseable output for Print Ltac."""

    @pytest.mark.asyncio
    async def test_contract_coq_query_print_ltac(self):
        """Contract test: real coq_query returns parseable output for Print Ltac."""
        from Poule.tactics.lookup import tactic_lookup
        result = await tactic_lookup("auto")
        assert result.name == "auto"
        assert result.kind in ("ltac", "primitive", "ltac2")


class TestContractStrategyInspection:
    """Contract: real coq_query for Print Strategy."""

    @pytest.mark.asyncio
    async def test_contract_coq_query_print_strategy(self):
        """Contract test: real coq_query for Print Strategy."""
        from Poule.tactics.lookup import strategy_inspect
        result = await strategy_inspect("Nat.add")
        assert len(result) >= 1
        assert result[0].constant == "Nat.add"
        assert result[0].level in ("transparent", "opaque") or isinstance(result[0].level, int)


class TestContractTacticComparison:
    """Contract: real tactic_compare with live Coq."""

    @pytest.mark.asyncio
    async def test_contract_tactic_compare_real(self):
        """Contract test: real tactic_compare with live Coq."""
        from Poule.tactics.compare import tactic_compare
        result = await tactic_compare(["auto", "eauto"])
        assert len(result.tactics) == 2


class TestContractContextualSuggestion:
    """Contract: real observe_proof_state returns a ProofState."""

    @pytest.mark.asyncio
    async def test_contract_observe_proof_state(self, coq_test_file):
        """Contract test: real observe_proof_state returns a ProofState."""
        from Poule.session.types import ProofState
        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id, _ = await manager.create_session(
            str(coq_test_file), "test_proof",
        )
        try:
            state = await manager.observe_state(session_id)
            assert isinstance(state, ProofState)
        finally:
            await manager.close_session(session_id)


class TestContractHintDatabaseInspection:
    """Contract: real coq_query for Print HintDb."""

    @pytest.mark.asyncio
    async def test_contract_coq_query_print_hintdb(self):
        """Contract test: real coq_query for Print HintDb."""
        from Poule.tactics.hints import hint_inspect
        result = await hint_inspect("core")
        assert result.name == "core"
        assert result.total_entries >= 0

    @pytest.mark.asyncio
    async def test_contract_file_local_hintdb_in_proof_session(self):
        """Contract test: file-local hint databases are visible in proof sessions.

        Spec: tactic-documentation.md §4.5 delegates to coq_query, which per
        vernacular-introspection.md §4.3 executes in the session's file context.
        automation.v defines 'my_hints' via Create HintDb before double_2."""
        from Poule.session.manager import SessionManager
        from Poule.tactics.hints import hint_inspect

        mgr = SessionManager()
        sid, _ = await mgr.create_session(
            "/poule/examples/automation.v", "double_2",
        )
        try:
            async def session_coq_query(command, argument, session_id=None):
                from Poule.query.handler import coq_query as _coq_query
                from Poule.query.process_pool import ProcessPool
                return await _coq_query(
                    command, argument,
                    session_id=sid,
                    session_manager=mgr,
                    process_pool=ProcessPool(),
                )

            result = await hint_inspect("my_hints", session_id=sid, coq_query=session_coq_query)
            assert result.name == "my_hints"
            assert result.total_entries >= 0
        finally:
            await mgr.close_session(sid)
