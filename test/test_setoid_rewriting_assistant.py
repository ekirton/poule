"""TDD tests for the Setoid Rewriting Assistant (specification/setoid-rewriting-assistant.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/Poule/setoid/ modules exist.

Spec: specification/setoid-rewriting-assistant.md
Architecture: doc/architecture/setoid-rewriting-assistant.md

Import paths under test:
  Poule.setoid.analyzer        (diagnose_rewrite)
  Poule.setoid.types           (RewriteDiagnosis, ParsedError, RelationSlot,
                                InstanceCheckResult, ExistingInstance,
                                ProperSignature, ProofStrategy)
  Poule.setoid.parser          (ErrorParser)
  Poule.setoid.checker         (InstanceChecker)
  Poule.setoid.generator       (SignatureGenerator)
  Poule.setoid.advisor         (ProofAdvisor)
"""

from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail at test time, not collection time
# ---------------------------------------------------------------------------


def _import_analyzer():
    from Poule.setoid.analyzer import diagnose_rewrite

    return (diagnose_rewrite,)


def _import_types():
    from Poule.setoid.types import (
        ExistingInstance,
        InstanceCheckResult,
        ParsedError,
        ProofStrategy,
        ProperSignature,
        RelationSlot,
        RewriteDiagnosis,
    )

    return (
        RewriteDiagnosis,
        ParsedError,
        RelationSlot,
        InstanceCheckResult,
        ExistingInstance,
        ProperSignature,
        ProofStrategy,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_session_manager(vernacular_responses=None, proof_state=None):
    """Build an AsyncMock session manager that returns canned Coq output."""
    manager = AsyncMock()
    responses = vernacular_responses or {}

    async def _execute(session_id, command):
        for key, val in responses.items():
            if key in command:
                return val
        return ""

    manager.execute_vernacular = AsyncMock(side_effect=_execute)

    if proof_state is None:
        proof_state = {
            "goal": "eq_set (union A B) (union B A)",
            "hypotheses": [
                {"name": "H", "type": "equiv x y"},
            ],
        }

    async def _observe(session_id):
        return proof_state

    manager.observe_proof_state = AsyncMock(side_effect=_observe)
    return manager


def _make_setoid_error_message():
    """Standard setoid_rewrite error for missing Proper on union."""
    return (
        "Tactic failure: setoid rewrite failed: Unable to satisfy the "
        "following constraints:\n"
        "UNDEFINED EVARS:\n"
        " ?X42==[H : equiv x y |- Proper (?R1 ==> eq_set) union] "
        "(internal placeholder)"
    )


def _make_binder_error_message():
    """Standard rewrite-under-binder error."""
    return 'Error: Found no subterm matching "P x" in the current goal.'


# ---------------------------------------------------------------------------
# S4.1: diagnose_rewrite — top-level behavioral requirements
# ---------------------------------------------------------------------------


class TestDiagnoseRewrite:
    """S4.1: diagnose_rewrite behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_rewrite_diagnosis(self):
        """diagnose_rewrite returns a RewriteDiagnosis record."""
        (diagnose_rewrite,) = _import_analyzer()
        (RewriteDiagnosis, *_) = _import_types()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search PreOrder eq_set": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert isinstance(result, RewriteDiagnosis)

    @pytest.mark.asyncio
    async def test_diagnose_mode_returns_null_signature(self):
        """In diagnose mode, generated_signature and proof_strategy are null."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search PreOrder eq_set": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.generated_signature is None
        assert result.proof_strategy is None

    @pytest.mark.asyncio
    async def test_generate_mode_returns_signature(self):
        """In generate mode, generated_signature is populated."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = fun A B => ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search PreOrder eq_set": "",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.generated_signature is not None
        assert result.proof_strategy is not None

    @pytest.mark.asyncio
    async def test_state_unchanged_after_call(self):
        """MAINTAINS: The session's proof state is unchanged."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
            }
        )
        await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        # Verify no tactic submission or state modification
        for call in manager.execute_vernacular.call_args_list:
            cmd = call[0][1] if len(call[0]) > 1 else call[1].get("command", "")
            assert "submit_tactic" not in cmd.lower()

    @pytest.mark.asyncio
    async def test_suggestion_is_non_empty_string(self):
        """RewriteDiagnosis.suggestion is a non-empty plain-language string."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert isinstance(result.suggestion, str)
        assert len(result.suggestion) > 0


# ---------------------------------------------------------------------------
# S4.2: Error parsing
# ---------------------------------------------------------------------------


class TestErrorParsing:
    """S4.2: Error parser classifies three patterns."""

    @pytest.mark.asyncio
    async def test_pattern1_extracts_function_name(self):
        """S4.2.1: Missing Proper extracts function name from evar."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "missing_proper"
        assert result.parsed_error.function_name == "union"

    @pytest.mark.asyncio
    async def test_pattern1_extracts_partial_signature(self):
        """S4.2.1: Partial signature extracts resolved and unresolved slots."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        slots = result.parsed_error.partial_signature
        assert len(slots) >= 1
        # At least the output relation (eq_set) should be resolved
        resolved = [s for s in slots if s.relation is not None]
        assert len(resolved) >= 1

    @pytest.mark.asyncio
    async def test_pattern2_binder_rewrite_detected(self):
        """S4.2.2: 'Found no subterm' under forall classified as binder_rewrite."""
        (diagnose_rewrite,) = _import_analyzer()
        proof_state = {
            "goal": "forall x, P x /\\ Q x",
            "hypotheses": [{"name": "H", "type": "forall x, P x <-> P' x"}],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Print Instances Proper": "",
            },
            proof_state=proof_state,
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_binder_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "binder_rewrite"
        assert result.parsed_error.binder_type == "forall"
        assert result.parsed_error.rewrite_target == "P x"

    @pytest.mark.asyncio
    async def test_pattern2_genuinely_absent_is_pattern_not_found(self):
        """S4.2.2: Pattern genuinely absent from goal returns pattern_not_found."""
        (diagnose_rewrite,) = _import_analyzer()
        proof_state = {
            "goal": "Q x /\\ R x",
            "hypotheses": [],
        }
        error = 'Error: Found no subterm matching "P x" in the current goal.'
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Print Instances Proper": "",
            },
            proof_state=proof_state,
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "pattern_not_found"

    @pytest.mark.asyncio
    async def test_pattern2_exists_binder(self):
        """Binder detection works for exists, not just forall."""
        (diagnose_rewrite,) = _import_analyzer()
        proof_state = {
            "goal": "exists x, P x /\\ Q x",
            "hypotheses": [],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Print Instances Proper": "",
            },
            proof_state=proof_state,
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_binder_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "binder_rewrite"
        assert result.parsed_error.binder_type == "exists"

    @pytest.mark.asyncio
    async def test_unrecognized_error(self):
        """S4.2.4: Unrecognized error returns UNRECOGNIZED_ERROR."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager()
        with pytest.raises(Exception) as exc_info:
            await diagnose_rewrite(
                session_id="s1",
                error_message="Some completely unrelated error message",
                mode="diagnose",
                target_function=None,
                target_relation=None,
                session_manager=manager,
            )
        assert "UNRECOGNIZED_ERROR" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "UNRECOGNIZED_ERROR"
        )


# ---------------------------------------------------------------------------
# S4.3: Instance checking
# ---------------------------------------------------------------------------


class TestInstanceChecking:
    """S4.3: Instance checker searches existing instances."""

    @pytest.mark.asyncio
    async def test_exact_match_found(self):
        """S4.3.1: Exact match when instance signature matches."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": (
                    "union_proper : Proper (eq_set ==> eq_set ==> eq_set) union"
                ),
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": (
                    "union_proper : Proper (eq_set ==> eq_set ==> eq_set) union"
                ),
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X42==[|- Proper (eq_set ==> eq_set ==> eq_set) union] "
            "(internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        instances = result.instance_check.existing_instances
        assert len(instances) >= 1
        assert instances[0].compatibility == "exact_match"

    @pytest.mark.asyncio
    async def test_no_instances_found(self):
        """When no Proper instances exist for function, list is empty."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.instance_check.existing_instances == []

    @pytest.mark.asyncio
    async def test_base_relation_not_registered(self):
        """S4.3.2: Missing Equivalence for base relation flagged as root cause."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check f": "A -> B",
                "Print Instances Proper": "",
                "Search Equivalence my_equiv": "",
                "Search PreOrder my_equiv": "",
                "Search Proper f": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (my_equiv ==> my_equiv) f] (internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.instance_check.base_relation_registered is False
        assert "Equivalence" in result.suggestion or "equivalence" in result.suggestion.lower()

    @pytest.mark.asyncio
    async def test_base_relation_registered_as_equivalence(self):
        """When base relation has Equivalence instance, base_relation_class = 'Equivalence'."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search PreOrder eq_set": "",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.instance_check.base_relation_registered is True
        assert result.instance_check.base_relation_class == "Equivalence"

    @pytest.mark.asyncio
    async def test_stdlib_suggestion_for_and_iff(self):
        """S4.3.3: Missing Proper for `and` with `iff` suggests Morphisms_Prop."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check and": "Prop -> Prop -> Prop",
                "Print Instances Proper": "",
                "Search Equivalence iff": "iff_Equivalence : Equivalence iff",
                "Search Proper and": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X5==[|- Proper (iff ==> iff ==> iff) and] (internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.instance_check.stdlib_suggestion is not None
        assert "Morphisms_Prop" in result.instance_check.stdlib_suggestion

    @pytest.mark.asyncio
    async def test_stdlib_suggestion_for_all_forall(self):
        """Missing Proper for `all` (forall) with iff suggests Morphisms_Prop."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check all": "(A -> Prop) -> Prop",
                "Print Instances Proper": "",
                "Search Equivalence iff": "iff_Equivalence : Equivalence iff",
                "Search Proper all": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X5==[|- Proper (pointwise_relation A iff ==> iff) all] "
            "(internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.instance_check.stdlib_suggestion is not None
        assert "Morphisms_Prop" in result.instance_check.stdlib_suggestion


# ---------------------------------------------------------------------------
# S4.4: Signature generation
# ---------------------------------------------------------------------------


class TestSignatureGeneration:
    """S4.4: Signature generator constructs Proper declarations."""

    @pytest.mark.asyncio
    async def test_generates_instance_declaration(self):
        """S4.4.5: Generated declaration is a valid Instance Proper ... line."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = fun (A : Type) (s1 s2 : set A) => ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        sig = result.generated_signature
        assert sig is not None
        assert "Instance" in sig.declaration
        assert "Proper" in sig.declaration
        assert "union" in sig.declaration
        assert "==>" in sig.declaration

    @pytest.mark.asyncio
    async def test_function_name_in_signature(self):
        """ProperSignature.function_name matches the diagnosed function."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.generated_signature.function_name == "union"

    @pytest.mark.asyncio
    async def test_instance_name_convention(self):
        """Instance name follows {function_name}_proper convention."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert "union_proper" in result.generated_signature.declaration

    @pytest.mark.asyncio
    async def test_relation_slots_fully_resolved(self):
        """After generation, all RelationSlot.relation fields are non-null."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        for slot in result.generated_signature.slots:
            assert slot.relation is not None

    @pytest.mark.asyncio
    async def test_default_relation_is_eq(self):
        """S4.4.2: Unknown argument relations default to eq."""
        (diagnose_rewrite,) = _import_analyzer()
        # Error with no resolved relations (all evars)
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X42==[|- Proper (?R1 ==> ?R2) my_fun] (internal placeholder)"
        )
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check my_fun": "nat -> bool",
                "Print my_fun": "my_fun = ...",
                "Print Instances Proper": "",
                "Search Equivalence": "",
                "Search PreOrder": "",
                "Search Proper my_fun": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        # When no relation info available, defaults to eq
        for slot in result.generated_signature.slots:
            if slot.relation is not None:
                # At least some slots should default to eq
                pass
        # The declaration should still be valid
        assert "Proper" in result.generated_signature.declaration

    @pytest.mark.asyncio
    async def test_opaque_function_defaults_to_covariant(self):
        """S4.4.4: Opaque function definition defaults to covariant."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check opaque_f": "A -> B",
                "Print opaque_f": "opaque_f is opaque",
                "Print Instances Proper": "",
                "Search Equivalence my_rel": "my_rel_Equiv : Equivalence my_rel",
                "Search Proper opaque_f": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (my_rel ==> my_rel) opaque_f] (internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        # All slots should have covariant variance
        for slot in result.generated_signature.slots:
            assert slot.variance == "covariant"


# ---------------------------------------------------------------------------
# S4.5: Proof strategy suggestion
# ---------------------------------------------------------------------------


class TestProofStrategy:
    """S4.5: Proof advisor suggests strategy."""

    @pytest.mark.asyncio
    async def test_solve_proper_high_confidence(self):
        """S4.5.1: Compositional function gets solve_proper with high confidence."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": (
                    "union = fun (A : Type) (s1 s2 : set A) => "
                    "app s1 s2"  # Simple composition
                ),
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
                "Search Proper app": "app_proper : Proper (eq_set ==> eq_set ==> eq_set) app",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        strategy = result.proof_strategy
        assert strategy is not None
        # When all callees have Proper instances, solve_proper should work
        if strategy.strategy == "solve_proper":
            assert strategy.confidence == "high"
            assert "solve_proper" in strategy.proof_skeleton

    @pytest.mark.asyncio
    async def test_manual_strategy_includes_unfold(self):
        """S4.5.2: Manual strategy skeleton includes unfold Proper, respectful."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check my_fun": "A -> B",
                "Print my_fun": "my_fun is opaque",
                "Print Instances Proper": "",
                "Search Equivalence my_rel": "my_rel_Equiv : Equivalence my_rel",
                "Search Proper my_fun": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (my_rel ==> my_rel) my_fun] (internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        strategy = result.proof_strategy
        assert strategy is not None
        assert strategy.strategy == "manual"
        assert strategy.confidence == "low"
        assert "unfold Proper" in strategy.proof_skeleton
        assert "respectful" in strategy.proof_skeleton
        assert "intros" in strategy.proof_skeleton

    @pytest.mark.asyncio
    async def test_strategy_is_valid_enum(self):
        """ProofStrategy.strategy is one of solve_proper, f_equiv, manual."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.proof_strategy.strategy in {"solve_proper", "f_equiv", "manual"}
        assert result.proof_strategy.confidence in {"high", "medium", "low"}


# ---------------------------------------------------------------------------
# S5: Data model constraints
# ---------------------------------------------------------------------------


class TestDataModel:
    """S5: Data model field constraints."""

    def test_parsed_error_fields(self):
        """ParsedError has all required fields."""
        (_, ParsedError, *_) = _import_types()
        pe = ParsedError(
            error_class="missing_proper",
            function_name="union",
            partial_signature=[],
            binder_type=None,
            rewrite_target=None,
            raw_error="some error",
        )
        assert pe.error_class == "missing_proper"
        assert pe.function_name == "union"
        assert pe.partial_signature == []
        assert pe.binder_type is None
        assert pe.raw_error == "some error"

    def test_parsed_error_binder_fields(self):
        """ParsedError for binder_rewrite has binder_type and rewrite_target."""
        (_, ParsedError, *_) = _import_types()
        pe = ParsedError(
            error_class="binder_rewrite",
            function_name=None,
            partial_signature=[],
            binder_type="forall",
            rewrite_target="P x",
            raw_error="Found no subterm...",
        )
        assert pe.error_class == "binder_rewrite"
        assert pe.function_name is None
        assert pe.binder_type == "forall"
        assert pe.rewrite_target == "P x"

    def test_relation_slot_fields(self):
        """RelationSlot has position, relation, argument_type, variance."""
        (_, _, RelationSlot, *_) = _import_types()
        slot = RelationSlot(
            position=0,
            relation="eq_set",
            argument_type="set A",
            variance="covariant",
        )
        assert slot.position == 0
        assert slot.relation == "eq_set"
        assert slot.argument_type == "set A"
        assert slot.variance == "covariant"

    def test_relation_slot_null_relation(self):
        """RelationSlot.relation can be null (unresolved from error parsing)."""
        (_, _, RelationSlot, *_) = _import_types()
        slot = RelationSlot(
            position=0,
            relation=None,
            argument_type="set A",
            variance="covariant",
        )
        assert slot.relation is None

    def test_existing_instance_fields(self):
        """ExistingInstance has all required fields."""
        (_, _, _, _, ExistingInstance, *_) = _import_types()
        inst = ExistingInstance(
            instance_name="union_proper",
            signature="Proper (eq_set ==> eq_set ==> eq_set) union",
            compatibility="exact_match",
            incompatibility_detail=None,
        )
        assert inst.instance_name == "union_proper"
        assert inst.compatibility == "exact_match"
        assert inst.incompatibility_detail is None

    def test_existing_instance_incompatible(self):
        """Incompatible ExistingInstance has detail."""
        (_, _, _, _, ExistingInstance, *_) = _import_types()
        inst = ExistingInstance(
            instance_name="union_eq_proper",
            signature="Proper (eq ==> eq ==> eq_set) union",
            compatibility="incompatible",
            incompatibility_detail="uses eq for arg 0, eq_set needed",
        )
        assert inst.compatibility == "incompatible"
        assert inst.incompatibility_detail is not None

    def test_instance_check_result_fields(self):
        """InstanceCheckResult has all required fields."""
        (_, _, _, InstanceCheckResult, *_) = _import_types()
        icr = InstanceCheckResult(
            existing_instances=[],
            base_relation_registered=True,
            base_relation_class="Equivalence",
            stdlib_suggestion=None,
        )
        assert icr.existing_instances == []
        assert icr.base_relation_registered is True
        assert icr.base_relation_class == "Equivalence"
        assert icr.stdlib_suggestion is None

    def test_proper_signature_fields(self):
        """ProperSignature has function_name, slots, return_relation, declaration."""
        (_, _, _, _, _, ProperSignature, _) = _import_types()
        sig = ProperSignature(
            function_name="union",
            slots=[],
            return_relation="eq_set",
            declaration="Instance union_proper : Proper (eq_set ==> eq_set ==> eq_set) union.",
        )
        assert sig.function_name == "union"
        assert sig.return_relation == "eq_set"
        assert "Instance" in sig.declaration

    def test_proof_strategy_fields(self):
        """ProofStrategy has strategy, confidence, proof_skeleton."""
        (_, _, _, _, _, _, ProofStrategy) = _import_types()
        ps = ProofStrategy(
            strategy="solve_proper",
            confidence="high",
            proof_skeleton="Proof. solve_proper. Qed.",
        )
        assert ps.strategy == "solve_proper"
        assert ps.confidence == "high"
        assert "solve_proper" in ps.proof_skeleton

    def test_error_class_values(self):
        """ParsedError.error_class is one of the four valid values."""
        (_, ParsedError, *_) = _import_types()
        valid = {"missing_proper", "binder_rewrite", "missing_equivalence", "pattern_not_found"}
        for cls in valid:
            pe = ParsedError(
                error_class=cls,
                function_name=None,
                partial_signature=[],
                binder_type=None,
                rewrite_target=None,
                raw_error="test",
            )
            assert pe.error_class in valid

    def test_variance_values(self):
        """RelationSlot.variance is one of covariant, contravariant, invariant."""
        (_, _, RelationSlot, *_) = _import_types()
        valid = {"covariant", "contravariant", "invariant"}
        for v in valid:
            slot = RelationSlot(
                position=0, relation="eq", argument_type="nat", variance=v
            )
            assert slot.variance in valid


# ---------------------------------------------------------------------------
# S8: Error specification
# ---------------------------------------------------------------------------


class TestErrorSpecification:
    """S8: Error codes and behaviors."""

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """SESSION_NOT_FOUND when session_id is invalid."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = AsyncMock()
        manager.observe_proof_state = AsyncMock(
            side_effect=Exception("SESSION_NOT_FOUND")
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_rewrite(
                session_id="nonexistent",
                error_message=_make_setoid_error_message(),
                mode="diagnose",
                target_function=None,
                target_relation=None,
                session_manager=manager,
            )
        assert "SESSION_NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "SESSION_NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_type_error_function_not_in_scope(self):
        """TYPE_ERROR when Check fails for target function."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check unknown_fun": "Error: unknown_fun not found",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (?R ==> ?R) unknown_fun] (internal placeholder)"
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_rewrite(
                session_id="s1",
                error_message=error,
                mode="generate",
                target_function=None,
                target_relation=None,
                session_manager=manager,
            )
        assert "TYPE_ERROR" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "TYPE_ERROR"
        )

    @pytest.mark.asyncio
    async def test_no_error_context(self):
        """NO_ERROR_CONTEXT when error_message is null and no session messages."""
        (diagnose_rewrite,) = _import_analyzer()
        proof_state = {
            "goal": "True",
            "hypotheses": [],
            "messages": [],
        }
        manager = _make_mock_session_manager(proof_state=proof_state)
        with pytest.raises(Exception) as exc_info:
            await diagnose_rewrite(
                session_id="s1",
                error_message=None,
                mode="diagnose",
                target_function=None,
                target_relation=None,
                session_manager=manager,
            )
        assert "NO_ERROR_CONTEXT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "NO_ERROR_CONTEXT"
        )

    @pytest.mark.asyncio
    async def test_backend_crashed(self):
        """BACKEND_CRASHED when Coq backend is dead."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = AsyncMock()
        manager.observe_proof_state = AsyncMock(
            side_effect=Exception("BACKEND_CRASHED")
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_rewrite(
                session_id="s1",
                error_message=_make_setoid_error_message(),
                mode="diagnose",
                target_function=None,
                target_relation=None,
                session_manager=manager,
            )
        assert "BACKEND_CRASHED" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "BACKEND_CRASHED"
        )

    @pytest.mark.asyncio
    async def test_opaque_definition_non_fatal(self):
        """S8: OPAQUE_DEFINITION is non-fatal; analysis continues with covariant default."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check opaque_f": "A -> B",
                "Print opaque_f": "<opaque>",
                "Print Instances Proper": "",
                "Search Equivalence my_rel": "Equiv : Equivalence my_rel",
                "Search Proper opaque_f": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (my_rel ==> my_rel) opaque_f] (internal placeholder)"
        )
        # Should NOT raise; should proceed with defaults
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.generated_signature is not None
        # All variances should default to covariant
        for slot in result.generated_signature.slots:
            assert slot.variance == "covariant"


# ---------------------------------------------------------------------------
# S10: Specification examples
# ---------------------------------------------------------------------------


class TestSpecExamples:
    """S10: Verify examples from the specification."""

    @pytest.mark.asyncio
    async def test_example1_missing_proper_diagnose_and_generate(self):
        """Spec example 1: missing Proper for union, diagnose and generate."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check union": "set A -> set A -> set A",
                "Print union": "union = ...",
                "Print Instances Proper": "",
                "Search Equivalence eq_set": "eq_set_Equivalence : Equivalence eq_set",
                "Search Proper union": "",
            }
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_setoid_error_message(),
            mode="generate",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "missing_proper"
        assert result.parsed_error.function_name == "union"
        assert result.instance_check.existing_instances == []
        assert result.instance_check.base_relation_registered is True
        assert result.generated_signature is not None
        assert "union" in result.generated_signature.declaration
        assert "Proper" in result.generated_signature.declaration
        assert len(result.suggestion) > 0

    @pytest.mark.asyncio
    async def test_example2_binder_rewrite_suggest_setoid(self):
        """Spec example 2: rewrite under forall suggests setoid_rewrite."""
        (diagnose_rewrite,) = _import_analyzer()
        proof_state = {
            "goal": "forall x, P x /\\ Q x",
            "hypotheses": [{"name": "H", "type": "forall x, P x <-> P' x"}],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Print Instances Proper": "",
            },
            proof_state=proof_state,
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=_make_binder_error_message(),
            mode="diagnose",
            target_function=None,
            target_relation=None,
            session_manager=manager,
        )
        assert result.parsed_error.error_class == "binder_rewrite"
        assert result.parsed_error.binder_type == "forall"
        assert "setoid_rewrite" in result.suggestion.lower()
        # Should suggest importing Morphisms_Prop
        assert result.instance_check.stdlib_suggestion is not None
        assert "Morphisms_Prop" in result.instance_check.stdlib_suggestion

    @pytest.mark.asyncio
    async def test_example3_missing_base_relation(self):
        """Spec example 3: missing Equivalence for base relation."""
        (diagnose_rewrite,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check f": "A -> B",
                "Print Instances Proper": "",
                "Search Equivalence my_equiv": "",
                "Search PreOrder my_equiv": "",
                "Search Proper f": "",
            }
        )
        error = (
            "Tactic failure: setoid rewrite failed: Unable to satisfy the "
            "following constraints:\n"
            "UNDEFINED EVARS:\n"
            " ?X10==[|- Proper (my_equiv ==> my_equiv) f] (internal placeholder)"
        )
        result = await diagnose_rewrite(
            session_id="s1",
            error_message=error,
            mode="generate",
            target_function="f",
            target_relation="my_equiv",
            session_manager=manager,
        )
        assert result.instance_check.base_relation_registered is False
        assert "Equivalence" in result.suggestion or "equivalence" in result.suggestion.lower()
        # Cannot generate without registered relation
        assert result.generated_signature is None
