"""Contract tests for the Typeclass Debugging component.

These tests exercise the real Coq backend to verify mock/real parity.

Spec: specification/typeclass-debugging.md
Architecture: doc/architecture/typeclass-debugging.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Lazy imports -- will fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_debugging():
    from Poule.typeclass.debugging import (
        list_instances,
        list_typeclasses,
        trace_resolution,
        explain_failure,
        detect_conflicts,
        explain_instance,
    )
    return (
        list_instances,
        list_typeclasses,
        trace_resolution,
        explain_failure,
        detect_conflicts,
        explain_instance,
    )


def _import_types():
    from Poule.typeclass.types import (
        TypeclassInfo,
        TypeclassSummary,
        ResolutionTrace,
        ResolutionNode,
        FailureExplanation,
        InstanceConflict,
        InstanceExplanation,
    )
    return (
        TypeclassInfo,
        TypeclassSummary,
        ResolutionTrace,
        ResolutionNode,
        FailureExplanation,
        InstanceConflict,
        InstanceExplanation,
    )


# ===========================================================================
# Contract: Instance Listing -- S4.1 list_instances
# ===========================================================================

class TestListInstancesContract:
    """Contract tests for list_instances against real Coq backend."""

    @pytest.mark.asyncio
    async def test_contract_list_instances_real_backend(self):
        """Contract test: list_instances returns populated TypeclassInfo records (S4.1)."""
        list_instances, *_ = _import_debugging()
        TypeclassInfo, *_ = _import_types()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            # Import a library with known typeclass instances
            await manager.execute_vernacular(
                session_id, "Require Import Coq.Classes.RelationClasses."
            )
            result = await list_instances(
                session_id=session_id,
                typeclass_name="Equivalence",
                session_manager=manager,
            )
            assert isinstance(result, list)
            assert len(result) > 0, (
                "Equivalence should have instances (e.g. eq_equivalence) "
                "after importing RelationClasses"
            )
            for info in result:
                assert isinstance(info, TypeclassInfo)
                assert info.instance_name, "instance_name must be non-empty (S5)"
                assert info.typeclass_name == "Equivalence"
                assert info.type_signature, "type_signature must be non-empty (S5)"
                assert info.defining_module, "defining_module must be non-empty (S5)"
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_contract_list_instances_not_a_typeclass(self):
        """Contract test: list_instances raises NOT_A_TYPECLASS for a non-typeclass (S7.1)."""
        list_instances, *_ = _import_debugging()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            with pytest.raises(Exception) as exc_info:
                await list_instances(
                    session_id=session_id,
                    typeclass_name="nat",
                    session_manager=manager,
                )
            assert "NOT_A_TYPECLASS" in str(exc_info.value) or (
                hasattr(exc_info.value, "code")
                and exc_info.value.code == "NOT_A_TYPECLASS"
            )
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# Contract: Typeclass Listing -- S4.1 list_typeclasses
# ===========================================================================

class TestListTypeclassesContract:
    """Contract tests for list_typeclasses against real Coq backend."""

    @pytest.mark.asyncio
    async def test_contract_list_typeclasses_real_backend(self):
        """Contract test: list_typeclasses returns populated TypeclassSummary records (S4.1)."""
        _, list_typeclasses, *_ = _import_debugging()
        _, TypeclassSummary, *_ = _import_types()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            # Import a library to ensure typeclasses are in scope
            await manager.execute_vernacular(
                session_id, "Require Import Coq.Classes.RelationClasses."
            )
            result = await list_typeclasses(
                session_id=session_id,
                session_manager=manager,
            )
            assert isinstance(result, list)
            assert len(result) > 0, (
                "Rocq environment should have typeclasses after importing RelationClasses"
            )
            for summary in result:
                assert isinstance(summary, TypeclassSummary)
                assert summary.typeclass_name, "typeclass_name must be non-empty (S5)"
                assert isinstance(summary.instance_count, (int, type(None)))
            # With fewer than 200 typeclasses, instance_count should be populated (S4.1)
            if len(result) <= 200:
                for summary in result:
                    assert summary.instance_count is not None, (
                        f"instance_count should be non-null for {summary.typeclass_name} "
                        "when total typeclasses <= 200 (S4.1)"
                    )
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# Contract: Resolution Tracing -- S4.2
# ===========================================================================

class TestTraceResolutionContract:
    """Contract tests for trace_resolution against real Coq backend."""

    @pytest.mark.asyncio
    async def test_contract_trace_resolution_no_typeclass_goal(self):
        """Contract test: trace_resolution at non-typeclass goal returns NO_TYPECLASS_GOAL (S4.2)."""
        _, _, trace_resolution, *_ = _import_debugging()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            # Start a proof whose goal does not involve typeclass resolution
            await manager.execute_vernacular(
                session_id, "Lemma add_0_r : forall n : nat, n + 0 = n."
            )
            await manager.execute_vernacular(session_id, "Proof.")
            with pytest.raises(Exception) as exc_info:
                await trace_resolution(
                    session_id=session_id,
                    session_manager=manager,
                )
            assert "NO_TYPECLASS_GOAL" in str(exc_info.value) or (
                hasattr(exc_info.value, "code") and exc_info.value.code == "NO_TYPECLASS_GOAL"
            )
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_contract_trace_resolution_embedded_typeclass_method(self):
        """Contract test: trace_resolution at goal with resolved typeclass methods returns
        NO_TYPECLASS_GOAL with goal text in the message (S4.2, S7.2).

        The goal `measure (l1 ++ l2) = measure l1 + measure l2` has head `=`, not
        a typeclass, even though `measure` is a typeclass projection.  The error
        message must include the goal text so the user understands why.
        """
        _, _, trace_resolution, *_ = _import_debugging()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            # Load the Measurable class and instances from the example file
            await manager.execute_vernacular(
                session_id,
                "From Coq Require Import PeanoNat List. Import ListNotations.",
            )
            await manager.execute_vernacular(
                session_id,
                "Class Measurable (A : Type) := { "
                "measure : A -> nat; "
                "measure_nonneg : forall x, 0 <= measure x }.",
            )
            await manager.execute_vernacular(
                session_id,
                "Instance list_Measurable (A : Type) : Measurable (list A) := { "
                "measure := @length A; "
                "measure_nonneg := fun _ => Nat.le_0_l _ }.",
            )
            await manager.execute_vernacular(
                session_id,
                "Lemma measure_app_length : "
                "forall (A : Type) (l1 l2 : list A), "
                "measure (l1 ++ l2) = measure l1 + measure l2.",
            )
            await manager.execute_vernacular(session_id, "Proof.")
            await manager.execute_vernacular(session_id, "intros A l1 l2.")

            with pytest.raises(Exception) as exc_info:
                await trace_resolution(
                    session_id=session_id,
                    session_manager=manager,
                )
            err = exc_info.value
            assert hasattr(err, "code") and err.code == "NO_TYPECLASS_GOAL", (
                f"Expected NO_TYPECLASS_GOAL, got: {err}"
            )
            # Error message must include the goal text per S7.2
            assert "measure" in err.message, (
                f"Error message should include goal text with 'measure', got: {err.message}"
            )
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_contract_trace_resolution_cleanup_guarantee(self):
        """Contract test: debug flag is cleaned up even after NO_TYPECLASS_GOAL (S7.4).

        After trace_resolution raises NO_TYPECLASS_GOAL, sending a subsequent
        vernacular command should succeed without debug output leaking.
        """
        _, _, trace_resolution, *_ = _import_debugging()

        from Poule.session.manager import ProofSessionManager
        manager = ProofSessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            await manager.execute_vernacular(
                session_id, "Lemma cleanup_test : forall n : nat, n = n."
            )
            await manager.execute_vernacular(session_id, "Proof.")
            with pytest.raises(Exception):
                await trace_resolution(
                    session_id=session_id,
                    session_manager=manager,
                )
            # Session should still be usable after the error -- debug flag was cleaned up
            response = await manager.execute_vernacular(session_id, "Check nat.")
            assert isinstance(response, str)
        finally:
            await manager.close_session(session_id)
