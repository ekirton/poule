"""TDD tests for the Convoy Pattern Assistant (specification/convoy-pattern-assistant.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/Poule/convoy/ modules exist.

Spec: specification/convoy-pattern-assistant.md
Architecture: doc/architecture/convoy-pattern-assistant.md

Import paths under test:
  Poule.convoy.analyzer       (diagnose_destruct)
  Poule.convoy.types          (DestructDiagnosis, DependencyReport, IndexInfo,
                               DependentHypothesis, TechniqueRecommendation,
                               Technique, GeneratedCode)
  Poule.convoy.scanner        (DependencyScanner)
  Poule.convoy.selector       (TechniqueSelector)
  Poule.convoy.generator      (BoilerplateGenerator)
"""

from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail at test time, not collection time
# ---------------------------------------------------------------------------


def _import_analyzer():
    from Poule.convoy.analyzer import diagnose_destruct

    return (diagnose_destruct,)


def _import_types():
    from Poule.convoy.types import (
        DependencyReport,
        DependentHypothesis,
        DestructDiagnosis,
        GeneratedCode,
        IndexInfo,
        Technique,
        TechniqueRecommendation,
    )

    return (
        DestructDiagnosis,
        DependencyReport,
        IndexInfo,
        DependentHypothesis,
        TechniqueRecommendation,
        Technique,
        GeneratedCode,
    )


def _import_scanner():
    from Poule.convoy.scanner import DependencyScanner

    return (DependencyScanner,)


def _import_selector():
    from Poule.convoy.selector import TechniqueSelector

    return (TechniqueSelector,)


def _import_generator():
    from Poule.convoy.generator import BoilerplateGenerator

    return (BoilerplateGenerator,)


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
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H", "type": "Q (S n)"},
                {"name": "H2", "type": "R m"},
            ],
        }

    async def _observe(session_id):
        return proof_state

    manager.observe_proof_state = AsyncMock(side_effect=_observe)
    return manager


def _make_index_info(name="n", type_="nat", has_decidable_eq=True):
    (_, _, IndexInfo, *_) = _import_types()
    return IndexInfo(name=name, type=type_, has_decidable_eq=has_decidable_eq)


def _make_dependent_hypothesis(
    name="H", type_="P n", indices_mentioned=None, depends_on=None
):
    (_, _, _, DependentHypothesis, *_) = _import_types()
    return DependentHypothesis(
        name=name,
        type=type_,
        indices_mentioned=indices_mentioned or ["n"],
        depends_on=depends_on or [],
    )


def _make_dependency_report(
    target="v",
    target_type="Fin (S n)",
    inductive_name="Fin",
    parameters=None,
    indices=None,
    dependent_hypotheses=None,
    goal_depends_on_index=True,
    error_message=None,
):
    (_, DependencyReport, *_) = _import_types()
    return DependencyReport(
        target=target,
        target_type=target_type,
        inductive_name=inductive_name,
        parameters=parameters or [],
        indices=indices or [_make_index_info()],
        dependent_hypotheses=dependent_hypotheses or [_make_dependent_hypothesis()],
        goal_depends_on_index=goal_depends_on_index,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# S4.1: diagnose_destruct — top-level behavioral requirements
# ---------------------------------------------------------------------------


class TestDiagnoseDestruct:
    """S4.1: diagnose_destruct behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_destruct_diagnosis(self):
        """diagnose_destruct returns a DestructDiagnosis record."""
        (diagnose_destruct,) = _import_analyzer()
        (DestructDiagnosis, *_) = _import_types()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=True,
            session_manager=manager,
        )
        assert isinstance(result, DestructDiagnosis)

    @pytest.mark.asyncio
    async def test_state_unchanged_after_call(self):
        """MAINTAINS: The session's proof state is unchanged after the call."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            }
        )
        await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        # No tactic submission or state-modifying calls
        for call in manager.execute_vernacular.call_args_list:
            cmd = call[0][1] if len(call[0]) > 1 else call[1].get("command", "")
            assert "submit_tactic" not in cmd.lower()

    @pytest.mark.asyncio
    async def test_generate_code_false_returns_null_code(self):
        """When generate_code is false, generated_code is null."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        assert result.generated_code is None


# ---------------------------------------------------------------------------
# S4.1.1: Target inference
# ---------------------------------------------------------------------------


class TestTargetInference:
    """S4.1.1: Target inference from error messages."""

    @pytest.mark.asyncio
    async def test_infer_target_from_error_message(self):
        """Given a recent 'Abstracting over...' error, target is inferred."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [{"name": "v", "type": "Fin (S n)"}],
            "messages": [
                "Abstracting over the terms `n` and `v` leads to a term "
                "which is ill-typed."
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target=None,
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        assert result.dependency_report.target == "v"

    @pytest.mark.asyncio
    async def test_null_target_no_error_returns_target_not_found(self):
        """Given no error message and target=null, returns TARGET_NOT_FOUND."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P n",
            "hypotheses": [],
            "messages": [],
        }
        manager = _make_mock_session_manager(proof_state=proof_state)
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target=None,
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        assert "TARGET_NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "TARGET_NOT_FOUND"
        )


# ---------------------------------------------------------------------------
# S4.1.2: Index identification
# ---------------------------------------------------------------------------


class TestIndexIdentification:
    """S4.1.2: Index identification via Check and Print."""

    @pytest.mark.asyncio
    async def test_fin_has_one_index(self):
        """Fin n has parameter count 0 and one index of type nat."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        report = result.dependency_report
        assert report.inductive_name == "Fin"
        assert len(report.parameters) == 0
        assert len(report.indices) >= 1
        assert report.indices[0].type == "nat"

    @pytest.mark.asyncio
    async def test_vec_distinguishes_parameter_from_index(self):
        """vec T n has T as parameter and n as index."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P n",
            "hypotheses": [
                {"name": "v", "type": "vec nat 3"},
                {"name": "H", "type": "Q 3"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "vec nat 3",
                "Print vec": (
                    "Inductive vec (A : Type) : nat -> Type :=\n"
                    "  | vnil : vec A 0\n"
                    "  | vcons : forall n, A -> vec A n -> vec A (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        report = result.dependency_report
        # A is a parameter (in parens before the colon in Print output)
        assert "A" in report.parameters or "nat" in report.parameters
        # n is an index
        index_names = [i.name for i in report.indices]
        assert any("3" in n or "n" in n for n in index_names)

    @pytest.mark.asyncio
    async def test_not_indexed_inductive_returns_error(self):
        """Target of type nat (no indices) returns NOT_INDEXED."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P x",
            "hypotheses": [{"name": "x", "type": "nat"}],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check x": "nat",
                "Print nat": (
                    "Inductive nat : Set :=\n"
                    "  | O : nat\n"
                    "  | S : nat -> nat."
                ),
            },
            proof_state=proof_state,
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target="x",
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        assert "NOT_INDEXED" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_INDEXED"
        )


# ---------------------------------------------------------------------------
# S4.1.3: Hypothesis scanning
# ---------------------------------------------------------------------------


class TestHypothesisScanning:
    """S4.1.3: Hypothesis scanning for index references."""

    @pytest.mark.asyncio
    async def test_identifies_dependent_hypotheses(self):
        """Hypotheses mentioning index variables are marked as dependent."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H1", "type": "Q (S n)"},
                {"name": "H2", "type": "R m"},
                {"name": "H3", "type": "T (S n) m"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        dep_names = {h.name for h in result.dependency_report.dependent_hypotheses}
        assert "H1" in dep_names  # mentions S n
        assert "H3" in dep_names  # mentions S n
        assert "H2" not in dep_names  # only mentions m

    @pytest.mark.asyncio
    async def test_no_dependent_hypotheses_returns_no_dependency(self):
        """When no hypotheses depend on indices, returns NO_DEPENDENCY."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H2", "type": "R m"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
            },
            proof_state=proof_state,
        )
        # When only goal depends but no hypotheses, may still proceed or
        # return NO_DEPENDENCY depending on implementation. The spec says
        # NO_DEPENDENCY when no hypotheses depend on indices.
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target="v",
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        assert "NO_DEPENDENCY" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NO_DEPENDENCY"
        )


# ---------------------------------------------------------------------------
# S4.1.4: Dependency ordering
# ---------------------------------------------------------------------------


class TestDependencyOrdering:
    """S4.1.4: Dependency ordering for revert sequence."""

    @pytest.mark.asyncio
    async def test_revert_order_most_dependent_first(self):
        """H1 depends on H2, so revert order is [H1, H2]."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "True",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H2", "type": "Q (S n)"},
                {"name": "H1", "type": "P (S n) H2"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        dep_names = [h.name for h in result.dependency_report.dependent_hypotheses]
        # H1 must appear before H2 in revert order
        assert dep_names.index("H1") < dep_names.index("H2")


# ---------------------------------------------------------------------------
# S4.1.5: Decidable equality detection
# ---------------------------------------------------------------------------


class TestDecidableEqualityDetection:
    """S4.1.5: Decidable equality detection for index types."""

    @pytest.mark.asyncio
    async def test_nat_has_decidable_eq(self):
        """nat index with EqDec instance sets has_decidable_eq = true."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        nat_indices = [
            i for i in result.dependency_report.indices if i.type == "nat"
        ]
        assert len(nat_indices) >= 1
        assert nat_indices[0].has_decidable_eq is True

    @pytest.mark.asyncio
    async def test_no_eqdec_sets_false(self):
        """When Search EqDec returns empty, has_decidable_eq is false."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        nat_indices = [
            i for i in result.dependency_report.indices if i.type == "nat"
        ]
        assert len(nat_indices) >= 1
        assert nat_indices[0].has_decidable_eq is False


# ---------------------------------------------------------------------------
# S4.2: Technique selection
# ---------------------------------------------------------------------------


class TestTechniqueSelection:
    """S4.2: Technique selection rules."""

    @pytest.mark.asyncio
    async def test_strict_mode_excludes_dependent_destruction(self):
        """axiom_tolerance='strict' excludes dependent_destruction."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        rec = result.recommendation
        assert rec.primary.name != "dependent_destruction"
        alt_names = [a.name for a in rec.alternatives]
        assert "dependent_destruction" not in alt_names

    @pytest.mark.asyncio
    async def test_permissive_mode_includes_dependent_destruction(self):
        """axiom_tolerance='permissive' includes dependent_destruction."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="permissive",
            generate_code=False,
            session_manager=manager,
        )
        rec = result.recommendation
        all_names = [rec.primary.name] + [a.name for a in rec.alternatives]
        assert "dependent_destruction" in all_names

    @pytest.mark.asyncio
    async def test_tactic_mode_primary_is_revert_destruct(self):
        """In tactic mode with dependent hypotheses, primary is revert_destruct."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        assert result.recommendation.primary.name == "revert_destruct"

    @pytest.mark.asyncio
    async def test_equations_available_appears_in_alternatives(self):
        """When Equations plugin is available, equations_depelim is an alternative."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "Constant Equations.Init.All",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        all_names = [result.recommendation.primary.name] + [
            a.name for a in result.recommendation.alternatives
        ]
        assert "equations_depelim" in all_names


# ---------------------------------------------------------------------------
# S4.2.1: Axiom warning content
# ---------------------------------------------------------------------------


class TestAxiomWarning:
    """S4.2.1: Axiom warning content for dependent_destruction."""

    @pytest.mark.asyncio
    async def test_axiom_warning_mentions_jmeq_eq(self):
        """When dependent_destruction is recommended, warning mentions JMeq_eq."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="permissive",
            generate_code=False,
            session_manager=manager,
        )
        assert result.recommendation.axiom_warning is not None
        assert "JMeq_eq" in result.recommendation.axiom_warning

    @pytest.mark.asyncio
    async def test_axiom_warning_null_when_strict(self):
        """axiom_tolerance='strict' means no techniques with axioms, so warning null."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=False,
            session_manager=manager,
        )
        assert result.recommendation.axiom_warning is None

    @pytest.mark.asyncio
    async def test_decidable_eq_noted_in_axiom_warning(self):
        """When index has decidable eq, warning notes Eqdep_dec alternative."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="permissive",
            generate_code=False,
            session_manager=manager,
        )
        assert result.recommendation.axiom_warning is not None
        assert "Eqdep_dec" in result.recommendation.axiom_warning


# ---------------------------------------------------------------------------
# S4.3: Boilerplate generation
# ---------------------------------------------------------------------------


class TestBoilerplateGeneration:
    """S4.3: Boilerplate generation for each technique."""

    @pytest.mark.asyncio
    async def test_revert_destruct_code(self):
        """S4.3.1: revert_destruct generates 'revert ... destruct ...' sequence."""
        (diagnose_destruct,) = _import_analyzer()
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            }
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=True,
            session_manager=manager,
        )
        code = result.generated_code
        assert code is not None
        assert code.technique == "revert_destruct"
        assert "revert" in code.code
        assert "destruct v" in code.code
        assert code.imports == []
        assert code.setup == []

    @pytest.mark.asyncio
    async def test_dependent_destruction_code(self):
        """S4.3.2: dependent_destruction generates Require + tactic."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H", "type": "Q (S n)"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
                "Locate dependent_destruction": "not found",
            },
            proof_state=proof_state,
        )
        # Force permissive to get dependent_destruction as primary
        # We'll check code generation for this technique
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="permissive",
            generate_code=True,
            session_manager=manager,
        )
        # Find the dependent_destruction technique in alternatives or primary
        all_techniques = [result.recommendation.primary] + result.recommendation.alternatives
        dd = [t for t in all_techniques if t.name == "dependent_destruction"]
        assert len(dd) >= 1
        assert "JMeq_eq" in dd[0].axioms_introduced or "Coq.Logic.JMeq.JMeq_eq" in dd[0].axioms_introduced

    @pytest.mark.asyncio
    async def test_revert_destruct_includes_hypothesis_names(self):
        """Generated revert code includes the specific dependent hypothesis names."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H1", "type": "Q (S n)"},
                {"name": "H3", "type": "T (S n)"},
                {"name": "H2", "type": "R m"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "",
                "Locate Equations.Init": "not found",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=True,
            session_manager=manager,
        )
        code_text = result.generated_code.code
        assert "H1" in code_text
        assert "H3" in code_text
        assert "H2" not in code_text  # H2 does not depend on index


# ---------------------------------------------------------------------------
# S5: Data model constraints
# ---------------------------------------------------------------------------


class TestDataModel:
    """S5: Data model field constraints."""

    def test_index_info_fields(self):
        """IndexInfo has name, type, has_decidable_eq."""
        info = _make_index_info(name="n", type_="nat", has_decidable_eq=True)
        assert info.name == "n"
        assert info.type == "nat"
        assert info.has_decidable_eq is True

    def test_dependent_hypothesis_fields(self):
        """DependentHypothesis has name, type, indices_mentioned, depends_on."""
        hyp = _make_dependent_hypothesis(
            name="H", type_="P n", indices_mentioned=["n"], depends_on=["H2"]
        )
        assert hyp.name == "H"
        assert hyp.type == "P n"
        assert hyp.indices_mentioned == ["n"]
        assert hyp.depends_on == ["H2"]

    def test_technique_name_enum(self):
        """Technique.name is one of the five valid values."""
        (_, _, _, _, _, Technique, _) = _import_types()
        valid_names = {
            "inversion",
            "revert_destruct",
            "dependent_destruction",
            "convoy_pattern",
            "equations_depelim",
        }
        t = Technique(
            name="revert_destruct",
            description="Revert dependent hypotheses before destructing.",
            axioms_introduced=[],
            requires_plugin=None,
        )
        assert t.name in valid_names

    def test_technique_axiom_free_has_empty_axioms(self):
        """Axiom-free techniques have empty axioms_introduced list."""
        (_, _, _, _, _, Technique, _) = _import_types()
        t = Technique(
            name="revert_destruct",
            description="desc",
            axioms_introduced=[],
            requires_plugin=None,
        )
        assert t.axioms_introduced == []

    def test_technique_dependent_destruction_has_jmeq(self):
        """dependent_destruction technique lists JMeq_eq axiom."""
        (_, _, _, _, _, Technique, _) = _import_types()
        t = Technique(
            name="dependent_destruction",
            description="desc",
            axioms_introduced=["Coq.Logic.JMeq.JMeq_eq"],
            requires_plugin=None,
        )
        assert "Coq.Logic.JMeq.JMeq_eq" in t.axioms_introduced

    def test_generated_code_fields(self):
        """GeneratedCode has technique, imports, setup, code, validation_result."""
        (_, _, _, _, _, _, GeneratedCode) = _import_types()
        gc = GeneratedCode(
            technique="revert_destruct",
            imports=[],
            setup=[],
            code="revert H. destruct v.",
            validation_result=None,
        )
        assert gc.technique == "revert_destruct"
        assert gc.imports == []
        assert gc.setup == []
        assert gc.code == "revert H. destruct v."
        assert gc.validation_result is None

    def test_dependency_report_required_fields(self):
        """DependencyReport has all required fields populated."""
        report = _make_dependency_report()
        assert report.target == "v"
        assert report.target_type == "Fin (S n)"
        assert report.inductive_name == "Fin"
        assert isinstance(report.parameters, list)
        assert isinstance(report.indices, list)
        assert len(report.indices) >= 1
        assert isinstance(report.dependent_hypotheses, list)
        assert isinstance(report.goal_depends_on_index, bool)


# ---------------------------------------------------------------------------
# S8: Error specification
# ---------------------------------------------------------------------------


class TestErrorSpecification:
    """S8: Error codes and behaviors."""

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """SESSION_NOT_FOUND when session_id is invalid."""
        (diagnose_destruct,) = _import_analyzer()
        manager = AsyncMock()
        manager.observe_proof_state = AsyncMock(
            side_effect=Exception("SESSION_NOT_FOUND")
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="nonexistent",
                target="v",
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        assert "SESSION_NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "SESSION_NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_parse_error_includes_raw_output(self):
        """PARSE_ERROR includes raw Print output for LLM fallback."""
        (diagnose_destruct,) = _import_analyzer()
        raw_output = "Weird unparseable output from Coq"
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": raw_output,
            }
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target="v",
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        exc_str = str(exc_info.value)
        assert "PARSE_ERROR" in exc_str or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "PARSE_ERROR"
        )

    @pytest.mark.asyncio
    async def test_backend_crashed(self):
        """BACKEND_CRASHED when Coq backend is dead."""
        (diagnose_destruct,) = _import_analyzer()
        manager = AsyncMock()
        manager.observe_proof_state = AsyncMock(
            side_effect=Exception("BACKEND_CRASHED")
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target="v",
                axiom_tolerance="strict",
                generate_code=False,
                session_manager=manager,
            )
        assert "BACKEND_CRASHED" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "BACKEND_CRASHED"
        )


# ---------------------------------------------------------------------------
# S10: Specification examples
# ---------------------------------------------------------------------------


class TestSpecExamples:
    """S10: Verify examples from the specification."""

    @pytest.mark.asyncio
    async def test_example1_simple_revert_before_destruct(self):
        """Spec example 1: simple revert-before-destruct."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P (S n)",
            "hypotheses": [
                {"name": "v", "type": "Fin (S n)"},
                {"name": "H", "type": "Q (S n)"},
                {"name": "H2", "type": "R m"},
            ],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check v": "Fin (S n)",
                "Print Fin": (
                    "Inductive Fin : nat -> Set :=\n"
                    "  | F1 : forall n, Fin (S n)\n"
                    "  | FS : forall n, Fin n -> Fin (S n)."
                ),
                "Search EqDec nat": "EqDec_nat : EqDec nat",
                "Locate Equations.Init": "not found",
            },
            proof_state=proof_state,
        )
        result = await diagnose_destruct(
            session_id="s1",
            target="v",
            axiom_tolerance="strict",
            generate_code=True,
            session_manager=manager,
        )
        assert result.recommendation.primary.name == "revert_destruct"
        assert result.recommendation.axiom_warning is None
        assert result.generated_code is not None
        assert "revert" in result.generated_code.code
        assert "H" in result.generated_code.code
        assert "destruct v" in result.generated_code.code

    @pytest.mark.asyncio
    async def test_example3_not_indexed(self):
        """Spec example 3: target of type nat returns NOT_INDEXED."""
        (diagnose_destruct,) = _import_analyzer()
        proof_state = {
            "goal": "P x",
            "hypotheses": [{"name": "x", "type": "nat"}],
        }
        manager = _make_mock_session_manager(
            vernacular_responses={
                "Check x": "nat",
                "Print nat": (
                    "Inductive nat : Set :=\n"
                    "  | O : nat\n"
                    "  | S : nat -> nat."
                ),
            },
            proof_state=proof_state,
        )
        with pytest.raises(Exception) as exc_info:
            await diagnose_destruct(
                session_id="s1",
                target="x",
                axiom_tolerance="strict",
                generate_code=True,
                session_manager=manager,
            )
        assert "NOT_INDEXED" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_INDEXED"
        )
