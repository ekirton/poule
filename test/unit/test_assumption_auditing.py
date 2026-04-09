"""Unit tests for the Assumption Auditing Engine (specification/assumption-auditing.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/auditing/ modules exist.

Spec: specification/assumption-auditing.md
Architecture: doc/architecture/assumption-auditing.md

Import paths under test:
  poule.auditing.engine       (audit_assumptions, audit_module, compare_assumptions)
  poule.auditing.parser       (parse_print_assumptions)
  poule.auditing.classifier   (classify_axiom)
  poule.auditing.registry     (KNOWN_AXIOMS, MODULE_PREFIXES)
  poule.auditing.types        (AssumptionResult, ClassifiedAxiom, OpaqueDependency,
                                AxiomCategory, ModuleAuditResult, AxiomUsageSummary,
                                FlaggedTheorem, ComparisonResult, MatrixRow)
  poule.auditing.errors       (AuditError)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_engine():
    from Poule.auditing.engine import (
        audit_assumptions,
        audit_module,
        compare_assumptions,
    )
    return audit_assumptions, audit_module, compare_assumptions


def _import_parser():
    from Poule.auditing.parser import parse_print_assumptions
    return parse_print_assumptions


def _import_classifier():
    from Poule.auditing.classifier import classify_axiom
    return classify_axiom


def _import_registry():
    from Poule.auditing.registry import KNOWN_AXIOMS, MODULE_PREFIXES
    return KNOWN_AXIOMS, MODULE_PREFIXES


def _import_types():
    from Poule.auditing.types import (
        AssumptionResult,
        ClassifiedAxiom,
        OpaqueDependency,
        AxiomCategory,
        ModuleAuditResult,
        AxiomUsageSummary,
        FlaggedTheorem,
        ComparisonResult,
        MatrixRow,
    )
    return (
        AssumptionResult, ClassifiedAxiom, OpaqueDependency, AxiomCategory,
        ModuleAuditResult, AxiomUsageSummary, FlaggedTheorem,
        ComparisonResult, MatrixRow,
    )


def _import_errors():
    from Poule.auditing.errors import AuditError
    return AuditError


def _import_session_errors():
    from Poule.session.errors import (
        SESSION_NOT_FOUND,
        BACKEND_CRASHED,
        SessionError,
    )
    return SESSION_NOT_FOUND, BACKEND_CRASHED, SessionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assumption_result(
    name="test_theorem",
    is_closed=True,
    axioms=None,
    opaque_dependencies=None,
    error=None,
):
    """Build an AssumptionResult using the real dataclass."""
    (
        AssumptionResult, ClassifiedAxiom, OpaqueDependency, AxiomCategory,
        *_rest,
    ) = _import_types()
    return AssumptionResult(
        name=name,
        is_closed=is_closed,
        axioms=axioms or [],
        opaque_dependencies=opaque_dependencies or [],
        error=error,
    )


def _make_classified_axiom(
    name="Stdlib.Logic.Classical_Prop.classic",
    type_str="forall P : Prop, P \\/ ~ P",
    category=None,
    explanation="Law of excluded middle",
):
    """Build a ClassifiedAxiom using the real dataclass."""
    (
        _AR, ClassifiedAxiom, _OD, AxiomCategory, *_rest,
    ) = _import_types()
    if category is None:
        category = AxiomCategory("classical")
    return ClassifiedAxiom(
        name=name,
        type=type_str,
        category=category,
        explanation=explanation,
    )


def _make_opaque_dependency(
    name="helper_lemma",
    type_str="nat -> nat -> Prop",
):
    """Build an OpaqueDependency using the real dataclass."""
    (
        _AR, _CA, OpaqueDependency, *_rest,
    ) = _import_types()
    return OpaqueDependency(name=name, type=type_str)


def _make_mock_session_manager(
    print_assumptions_output=None,
    print_module_output=None,
    declaration_kinds=None,
    errors=None,
):
    """Create a mock session manager for auditing tests.

    print_assumptions_output: dict mapping theorem name to Coq response string.
    print_module_output: dict mapping module name to Coq response string.
    declaration_kinds: dict mapping qualified name to kind string
        ("Axiom", "Parameter", "Opaque", or None for unknown).
    errors: dict mapping command string to exception to raise.
    """
    manager = AsyncMock()
    print_assumptions_output = print_assumptions_output or {}
    print_module_output = print_module_output or {}
    declaration_kinds = declaration_kinds or {}
    errors = errors or {}

    async def _send_command(session_id, command, *, prefer_coqtop=False):
        if command in errors:
            raise errors[command]
        # Match Print Assumptions commands
        for thm_name, output in print_assumptions_output.items():
            if command == f"Print Assumptions {thm_name}.":
                return output
        # Match Print Module commands
        for mod_name, output in print_module_output.items():
            if command == f"Print Module {mod_name}.":
                return output
        return ""

    manager.send_command.side_effect = _send_command

    async def _query_declaration_kind(session_id, name):
        return declaration_kinds.get(name)

    manager.query_declaration_kind.side_effect = _query_declaration_kind
    return manager


# ===========================================================================
# 1. Output Parsing -- Section 4.2
# ===========================================================================

class TestOutputParsing:
    """Section 4.2: Print Assumptions output parsing."""

    def test_closed_theorem_output(self):
        """Given 'Closed under the global context', parse to is_closed=true, empty lists."""
        parse = _import_parser()
        result = parse("Closed under the global context")
        assert result.is_closed is True
        assert result.axioms == []
        assert result.opaque_dependencies == []

    def test_closed_theorem_output_multiline(self):
        """Coq may line-wrap 'Closed under the global\\n  context'; parser must still recognise it."""
        parse = _import_parser()
        result = parse("Closed under the global\n  context")
        assert result.is_closed is True
        assert result.axioms == []
        assert result.opaque_dependencies == []

    def test_closed_theorem_with_rocq_prompt(self):
        """coqtop may prefix output with 'Rocq < '; parser must strip it."""
        parse = _import_parser()
        result = parse("Rocq < Closed under the global context")
        assert result.is_closed is True
        assert result.axioms == []
        assert result.opaque_dependencies == []

    def test_closed_theorem_with_coq_prompt(self):
        """coqtop may prefix output with 'Coq < '; parser must strip it."""
        parse = _import_parser()
        result = parse("Coq < Closed under the global context")
        assert result.is_closed is True
        assert result.axioms == []
        assert result.opaque_dependencies == []

    def test_dependency_lines_with_rocq_prompt(self):
        """Dependency lines prefixed with 'Rocq < ' are parsed correctly."""
        parse = _import_parser()
        output = "Rocq < Classic : forall P : Prop, P \\/ ~ P"
        result = parse(output)
        assert result.is_closed is False
        assert len(result.dependencies) == 1
        assert result.dependencies[0].name == "Classic"

    def test_two_dependency_lines(self):
        """Given two dependency lines, extract name and type for each."""
        parse = _import_parser()
        output = (
            "Classic : forall P : Prop, P \\/ ~ P\n"
            "my_lemma : nat -> nat"
        )
        result = parse(output)
        assert result.is_closed is False
        names = [d.name for d in result.dependencies]
        types = [d.type for d in result.dependencies]
        assert "Classic" in names
        assert "my_lemma" in names
        assert "forall P : Prop, P \\/ ~ P" in types
        assert "nat -> nat" in types

    def test_split_on_first_colon_space(self):
        """Parser splits on first ' : ' so types containing ' : ' are preserved."""
        parse = _import_parser()
        output = "foo : forall A : Type, A -> A"
        result = parse(output)
        deps = result.dependencies
        assert len(deps) == 1
        assert deps[0].name == "foo"
        assert deps[0].type == "forall A : Type, A -> A"

    def test_empty_output_raises_parse_error(self):
        """Empty or unexpected output raises a PARSE_ERROR."""
        AuditError = _import_errors()
        parse = _import_parser()
        with pytest.raises(AuditError) as exc_info:
            parse("")
        assert exc_info.value.code == "PARSE_ERROR"


# ===========================================================================
# 2. Axiom/Opaque Separation -- Section 4.3
# ===========================================================================

class TestAxiomOpaqueSeparation:
    """Section 4.3: Classification of dependencies as axiom vs opaque."""

    @pytest.mark.asyncio
    async def test_axiom_declaration_classified_as_axiom(self):
        """A dependency with declaration kind 'Axiom' goes into axioms list."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_thm": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
            },
        )
        result = await audit_assumptions(manager, "my_thm")
        assert len(result.axioms) == 1
        assert result.axioms[0].name == "Stdlib.Logic.Classical_Prop.classic"
        assert result.opaque_dependencies == []

    @pytest.mark.asyncio
    async def test_parameter_declaration_classified_as_axiom(self):
        """A dependency with declaration kind 'Parameter' goes into axioms list."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_thm": "my_param : nat -> Prop",
            },
            declaration_kinds={
                "my_param": "Parameter",
            },
        )
        result = await audit_assumptions(manager, "my_thm")
        assert len(result.axioms) == 1
        assert result.axioms[0].name == "my_param"

    @pytest.mark.asyncio
    async def test_opaque_declaration_classified_as_opaque(self):
        """A dependency with opaque kind (Qed) goes into opaque_dependencies."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_thm": "helper_lemma : nat -> nat",
            },
            declaration_kinds={
                "helper_lemma": "Opaque",
            },
        )
        result = await audit_assumptions(manager, "my_thm")
        assert result.axioms == []
        assert len(result.opaque_dependencies) == 1
        assert result.opaque_dependencies[0].name == "helper_lemma"

    @pytest.mark.asyncio
    async def test_unknown_kind_defaults_to_axiom(self):
        """When declaration kind cannot be determined, treat as axiom (conservative)."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_thm": "unknown_dep : some_type",
            },
            declaration_kinds={
                # kind is None (unknown)
            },
        )
        result = await audit_assumptions(manager, "my_thm")
        assert len(result.axioms) == 1
        assert result.axioms[0].name == "unknown_dep"


# ===========================================================================
# 3. Axiom Classification -- Section 4.4
# ===========================================================================

class TestAxiomClassification:
    """Section 4.4: Three-stage axiom classification cascade."""

    def test_stage1_exact_match_classic(self):
        """Stage 1: 'Coq.Logic.Classical_Prop.classic' -> classical."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, explanation = classify(
            "Stdlib.Logic.Classical_Prop.classic",
            "forall P : Prop, P \\/ ~ P",
        )
        assert category == AxiomCategory("classical")
        assert len(explanation) > 0

    def test_stage1_exact_match_functional_extensionality(self):
        """Stage 1: functional_extensionality_dep -> extensionality."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep",
            "forall (A : Type) (B : A -> Type) (f g : forall x, B x), "
            "(forall x, f x = g x) -> f = g",
        )
        assert category == AxiomCategory("extensionality")

    def test_stage1_exact_match_proof_irrelevance(self):
        """Stage 1: proof_irrelevance -> proof_irrelevance."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.ProofIrrelevance.proof_irrelevance",
            "forall (P : Prop) (p1 p2 : P), p1 = p2",
        )
        assert category == AxiomCategory("proof_irrelevance")

    def test_stage1_exact_match_choice(self):
        """Stage 1: constructive_indefinite_description -> choice."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.IndefiniteDescription.constructive_indefinite_description",
            "forall (A : Type) (P : A -> Prop), (exists x, P x) -> {x : A | P x}",
        )
        assert category == AxiomCategory("choice")

    def test_stage2_prefix_match_classical(self):
        """Stage 2: unknown axiom under Coq.Logic.Classical_Prop -> classical."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.Classical_Prop.some_new_variant",
            "some_type",
        )
        assert category == AxiomCategory("classical")

    def test_stage2_prefix_match_choice_facts(self):
        """Stage 2: axiom under Coq.Logic.ChoiceFacts -> choice."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.ChoiceFacts.new_choice_lemma",
            "some_type",
        )
        assert category == AxiomCategory("choice")

    def test_stage2_prefix_match_proof_irrelevance_facts(self):
        """Stage 2: axiom under Coq.Logic.ProofIrrelevanceFacts -> proof_irrelevance."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "Stdlib.Logic.ProofIrrelevanceFacts.some_lemma",
            "some_type",
        )
        assert category == AxiomCategory("proof_irrelevance")

    def test_stage3_type_heuristic_excluded_middle(self):
        """Stage 3: type 'forall P : Prop, P \\/ ~ P' -> classical."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, _ = classify(
            "MyLib.custom_em",
            "forall P : Prop, P \\/ ~ P",
        )
        assert category == AxiomCategory("classical")

    def test_default_category_custom(self):
        """No stage matches: category='custom', standard explanation."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        category, explanation = classify(
            "MyLib.my_axiom",
            "nat -> nat",
        )
        assert category == AxiomCategory("custom")
        assert explanation == "User-defined axiom. Review manually for consistency."

    def test_classification_is_deterministic(self):
        """Same (name, type) pair always yields same (category, explanation)."""
        classify = _import_classifier()
        result1 = classify("MyLib.my_axiom", "nat -> nat")
        result2 = classify("MyLib.my_axiom", "nat -> nat")
        assert result1 == result2

    def test_exact_match_takes_priority_over_prefix(self):
        """Stage 1 exact match fires before Stage 2 prefix match."""
        classify = _import_classifier()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        # classic is both an exact entry and under Classical_Prop prefix
        category, explanation = classify(
            "Stdlib.Logic.Classical_Prop.classic",
            "forall P : Prop, P \\/ ~ P",
        )
        assert category == AxiomCategory("classical")
        # The explanation should be the specific exact-match one, not a generic prefix one
        assert "excluded middle" in explanation.lower() or "classic" in explanation.lower()


# ===========================================================================
# 4. Known-Axiom Registry -- Section 4.5
# ===========================================================================

class TestKnownAxiomRegistry:
    """Section 4.5: Static registry structure and required entries."""

    def test_registry_contains_all_required_exact_entries(self):
        """All 11 axioms listed in section 4.5 table are present."""
        KNOWN_AXIOMS, _ = _import_registry()
        required_entries = [
            "Stdlib.Logic.Classical_Prop.classic",
            "Stdlib.Logic.Classical_Prop.NNPP",
            "Stdlib.Logic.ClassicalEpsilon.excluded_middle_informative",
            "Stdlib.Logic.Decidable.dec_not_not",
            "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep",
            "Stdlib.Logic.PropExtensionality.propositional_extensionality",
            "Stdlib.Logic.IndefiniteDescription.constructive_indefinite_description",
            "Stdlib.Logic.ClassicalChoice.choice",
            "Stdlib.Logic.Epsilon.epsilon",
            "Stdlib.Logic.ProofIrrelevance.proof_irrelevance",
            "Stdlib.Logic.JMeq.JMeq_eq",
        ]
        for entry in required_entries:
            assert entry in KNOWN_AXIOMS, f"Missing registry entry: {entry}"

    def test_registry_entry_structure(self):
        """Each entry maps to (AxiomCategory, explanation_string)."""
        KNOWN_AXIOMS, _ = _import_registry()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        for name, (category, explanation) in KNOWN_AXIOMS.items():
            assert isinstance(category, AxiomCategory), f"Bad category type for {name}"
            assert isinstance(explanation, str), f"Bad explanation type for {name}"
            assert len(explanation) > 0, f"Empty explanation for {name}"

    def test_registry_categories_are_correct(self):
        """Spot-check that categories match the spec table."""
        KNOWN_AXIOMS, _ = _import_registry()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        assert KNOWN_AXIOMS["Stdlib.Logic.Classical_Prop.classic"][0] == AxiomCategory("classical")
        assert KNOWN_AXIOMS["Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep"][0] == AxiomCategory("extensionality")
        assert KNOWN_AXIOMS["Stdlib.Logic.IndefiniteDescription.constructive_indefinite_description"][0] == AxiomCategory("choice")
        assert KNOWN_AXIOMS["Stdlib.Logic.ProofIrrelevance.proof_irrelevance"][0] == AxiomCategory("proof_irrelevance")

    def test_module_prefixes_contains_all_required(self):
        """All 10 module prefixes from section 4.5 table are present."""
        _, MODULE_PREFIXES = _import_registry()
        required_prefixes = [
            "Stdlib.Logic.Classical_Prop",
            "Stdlib.Logic.ClassicalEpsilon",
            "Stdlib.Logic.FunctionalExtensionality",
            "Stdlib.Logic.PropExtensionality",
            "Stdlib.Logic.ChoiceFacts",
            "Stdlib.Logic.IndefiniteDescription",
            "Stdlib.Logic.ClassicalChoice",
            "Stdlib.Logic.Epsilon",
            "Stdlib.Logic.ProofIrrelevance",
            "Stdlib.Logic.ProofIrrelevanceFacts",
        ]
        prefix_names = [p[0] for p in MODULE_PREFIXES]
        for prefix in required_prefixes:
            assert prefix in prefix_names, f"Missing prefix: {prefix}"

    def test_module_prefixes_is_ordered_list_of_tuples(self):
        """MODULE_PREFIXES is a list of (prefix, category) tuples (Section 10)."""
        _, MODULE_PREFIXES = _import_registry()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        assert isinstance(MODULE_PREFIXES, list)
        for entry in MODULE_PREFIXES:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            prefix, category = entry
            assert isinstance(prefix, str)
            assert isinstance(category, AxiomCategory)


# ===========================================================================
# 5. Single-Theorem Auditing -- Section 4.1
# ===========================================================================

class TestSingleTheoremAuditing:
    """Section 4.1: audit_assumptions entry point."""

    @pytest.mark.asyncio
    async def test_closed_theorem_returns_is_closed_true(self):
        """Given a closed theorem, return is_closed=true with empty lists."""
        audit_assumptions, _, _ = _import_engine()
        (
            AssumptionResult, *_rest,
        ) = _import_types()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "Stdlib.Arith.PeanoNat.Nat.add_comm": "Closed under the global context",
            },
        )
        result = await audit_assumptions(manager, "Stdlib.Arith.PeanoNat.Nat.add_comm")
        assert isinstance(result, AssumptionResult)
        assert result.is_closed is True
        assert result.axioms == []
        assert result.opaque_dependencies == []
        assert result.error is None

    @pytest.mark.asyncio
    async def test_classical_dependency_classified(self):
        """Given a theorem depending on classic, return classified axiom."""
        audit_assumptions, _, _ = _import_engine()
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_theorem": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
            },
        )
        result = await audit_assumptions(manager, "my_theorem")
        assert result.is_closed is False
        assert len(result.axioms) == 1
        assert result.axioms[0].category == AxiomCategory("classical")
        assert len(result.axioms[0].explanation) > 0

    @pytest.mark.asyncio
    async def test_session_not_found_error(self):
        """Given no active session, return SESSION_NOT_FOUND."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        SESSION_NOT_FOUND, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.send_command.side_effect = SessionError(
            SESSION_NOT_FOUND, "No active Coq session."
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "anything")
        assert exc_info.value.code == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_name_raises_invalid_input(self):
        """Empty name raises INVALID_INPUT."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        manager = AsyncMock()
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "")
        assert exc_info.value.code == "INVALID_INPUT"
        assert "non-empty" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_theorem_not_found_error(self):
        """Given a non-existent theorem, return NOT_FOUND."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        manager = _make_mock_session_manager(
            errors={
                "Print Assumptions no_such_theorem.": AuditError(
                    "NOT_FOUND",
                    "Declaration `no_such_theorem` not found in the current Coq environment.",
                ),
            },
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "no_such_theorem")
        assert exc_info.value.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_result_name_matches_input(self):
        """The returned AssumptionResult.name matches the input theorem name."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "Foo.bar": "Closed under the global context",
            },
        )
        result = await audit_assumptions(manager, "Foo.bar")
        assert result.name == "Foo.bar"

    @pytest.mark.asyncio
    async def test_mixed_axiom_and_opaque(self):
        """A theorem with both axiom and opaque deps separates them correctly."""
        audit_assumptions, _, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_classical_theorem": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P\n"
                    "helper_lemma : nat -> nat -> Prop"
                ),
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
                "helper_lemma": "Opaque",
            },
        )
        result = await audit_assumptions(manager, "my_classical_theorem")
        assert result.is_closed is False
        assert len(result.axioms) == 1
        assert result.axioms[0].name == "Stdlib.Logic.Classical_Prop.classic"
        assert len(result.opaque_dependencies) == 1
        assert result.opaque_dependencies[0].name == "helper_lemma"


# ===========================================================================
# 5b. Module Declaration Parsing -- _parse_module_theorems
# ===========================================================================

class TestParseModuleTheorems:
    """Test _parse_module_theorems with realistic Print Module output."""

    def test_definition_keyword_extracted(self):
        """Real Coq Print Module uses 'Definition' for all declarations."""
        from Poule.auditing.engine import _parse_module_theorems
        output = (
            "Module\nInit.Nat\n:= Struct\n"
            "     Definition add : nat -> nat -> nat.\n"
            "     Definition mul : nat -> nat -> nat.\n"
            "     Definition sub : nat -> nat -> nat.\n"
            "   End"
        )
        result = _parse_module_theorems("Init.Nat", output)
        assert result == ["Init.Nat.add", "Init.Nat.mul", "Init.Nat.sub"]

    def test_submodule_declarations_excluded(self):
        """Sub-module entries (Module X) should not appear as declarations."""
        from Poule.auditing.engine import _parse_module_theorems
        output = (
            "Module\nPeanoNat\n:= Struct\n"
            "     Module Nat\n"
            "     Definition lt_n_Sm_le : forall n m : nat, n < S m -> n <= m.\n"
            "   End"
        )
        result = _parse_module_theorems("PeanoNat", output)
        assert "PeanoNat.Nat" not in result
        assert "PeanoNat.lt_n_Sm_le" in result

    def test_parameter_keyword_extracted(self):
        """'Parameter' declarations (abstract module types) should be extracted."""
        from Poule.auditing.engine import _parse_module_theorems
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Parameter my_axiom : forall P : Prop, P \\/ ~ P.\n"
            "   End"
        )
        result = _parse_module_theorems("MyLib", output)
        assert result == ["MyLib.my_axiom"]

    def test_empty_module(self):
        """Empty module produces empty list."""
        from Poule.auditing.engine import _parse_module_theorems
        output = "Module\nEmpty\n:= Struct\n   End"
        result = _parse_module_theorems("Empty", output)
        assert result == []

    def test_inductive_and_record_extracted(self):
        """Inductive and Record declarations are also extracted."""
        from Poule.auditing.engine import _parse_module_theorems
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Inductive color : Set.\n"
            "     Record point : Set.\n"
            "     Definition foo : nat.\n"
            "   End"
        )
        result = _parse_module_theorems("MyLib", output)
        assert "MyLib.color" in result
        assert "MyLib.point" in result
        assert "MyLib.foo" in result


# ===========================================================================
# 5c. Search Fallback Parsing -- _parse_search_results
# ===========================================================================

class TestParseSearchResults:
    """Test _parse_search_results with realistic Search _ inside output."""

    def test_basic_search_output(self):
        """Parse standard Search output: 'name: type' per line."""
        from Poule.auditing.engine import _parse_search_results
        output = (
            "my_lemma: forall (A : Type) (f : A -> A) (x : A), f x = f x\n"
            "add_0_r_v1: forall n : nat, (n + 0)%nat = n\n"
            "ring_morph: forall a b c : nat, (a * (b + c))%nat = (a * b + a * c)%nat"
        )
        result = _parse_search_results(output)
        assert result == ["my_lemma", "add_0_r_v1", "ring_morph"]

    def test_empty_output(self):
        """Empty search output returns empty list."""
        from Poule.auditing.engine import _parse_search_results
        assert _parse_search_results("") == []

    def test_coq_error_message_skipped(self):
        """Coq error messages like 'Error: ...' must not be parsed as declarations."""
        from Poule.auditing.engine import _parse_search_results
        output = "Error: Module/Section algebra not found."
        result = _parse_search_results(output)
        assert result == []

    def test_rocq_prefix_stripped(self):
        """Lines prefixed with 'Rocq < ' are handled."""
        from Poule.auditing.engine import _parse_search_results
        output = "Rocq < my_lemma: forall n : nat, n = n\nadd_0_r: forall n : nat, n + 0 = n"
        result = _parse_search_results(output)
        assert "my_lemma" in result
        assert "add_0_r" in result


# ===========================================================================
# 5d. Audit Module Fallback -- Search fallback cascade
# ===========================================================================

class TestAuditModuleFallback:
    """Section 4.6: audit_module falls back from Print Module to Search."""

    @pytest.mark.asyncio
    async def test_fallback_to_search_inside_top(self):
        """When Print Module and Search inside <module> both fail,
        fall back to Search _ inside Top."""
        _, audit_module, _ = _import_engine()

        call_log = []

        async def _send_command(session_id, command, *, prefer_coqtop=False):
            call_log.append(command)
            if command == "Print Module algebra.":
                raise Exception("Unknown Module algebra")
            if command == "Search _ inside algebra.":
                raise Exception("Module/Section algebra not found")
            if command == "Search _ inside Top.":
                return (
                    "my_lemma: forall (A : Type) (f : A -> A) (x : A), f x = f x\n"
                    "add_0_r_v1: forall n : nat, (n + 0)%nat = n"
                )
            if "Print Assumptions" in command:
                return "Closed under the global context"
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _send_command
        manager.query_declaration_kind = AsyncMock(return_value=None)

        result = await audit_module(manager, "algebra")
        assert result.theorem_count == 2
        assert result.axiom_free_count == 2
        assert "Print Module algebra." in call_log
        assert "Search _ inside algebra." in call_log
        assert "Search _ inside Top." in call_log

    @pytest.mark.asyncio
    async def test_not_found_when_all_strategies_fail(self):
        """When all three strategies return no results, raise NOT_FOUND."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()

        async def _send_command(session_id, command, *, prefer_coqtop=False):
            if "Print Module" in command:
                raise Exception("Unknown Module")
            if "Search" in command:
                raise Exception("Module/Section not found")
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _send_command

        with pytest.raises(AuditError) as exc_info:
            await audit_module(manager, "NoSuch.Module")
        assert exc_info.value.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_print_module_success_no_fallback(self):
        """When Print Module succeeds, no fallback is needed."""
        _, audit_module, _ = _import_engine()

        call_log = []

        async def _send_command(session_id, command, *, prefer_coqtop=False):
            call_log.append(command)
            if command == "Print Module Stdlib.Arith.PeanoNat.":
                return (
                    "Module\nPeanoNat\n:= Struct\n"
                    "     Definition lt_n_Sm_le : forall n m : nat, n < S m -> n <= m.\n"
                    "   End"
                )
            if "Print Assumptions" in command:
                return "Closed under the global context"
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _send_command
        manager.query_declaration_kind = AsyncMock(return_value=None)

        result = await audit_module(manager, "Stdlib.Arith.PeanoNat")
        assert result.theorem_count == 1
        assert not any("Search" in cmd for cmd in call_log)

    @pytest.mark.asyncio
    async def test_fqn_retry_with_short_name(self):
        """When Print Assumptions fails with a FQN, retry with short name."""
        _, audit_module, _ = _import_engine()

        async def _send_command(session_id, command, *, prefer_coqtop=False):
            if command == "Print Module Coq.Arith.PeanoNat.":
                return (
                    "Module\nPeanoNat\n:= Struct\n"
                    "     Definition lt_n_Sm_le : forall n m : nat, n < S m -> n <= m.\n"
                    "   End"
                )
            if command == "Print Assumptions Coq.Arith.PeanoNat.lt_n_Sm_le.":
                raise Exception("not found in the current environment")
            if command == "Print Assumptions lt_n_Sm_le.":
                return "Closed under the global context"
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _send_command
        manager.query_declaration_kind = AsyncMock(return_value=None)

        result = await audit_module(manager, "Coq.Arith.PeanoNat")
        assert result.theorem_count == 1
        assert result.axiom_free_count == 1
        assert result.per_theorem[0].error is None


# ===========================================================================
# 6. Batch Module Auditing -- Section 4.6
# ===========================================================================

class TestBatchModuleAuditing:
    """Section 4.6: audit_module batch auditing."""

    @pytest.mark.asyncio
    async def test_basic_module_audit(self):
        """Given a module with 3 theorems (2 using classic), flag correctly."""
        _, audit_module, _ = _import_engine()
        (
            _AR, _CA, _OD, AxiomCategory,
            ModuleAuditResult, AxiomUsageSummary, FlaggedTheorem,
            *_rest,
        ) = _import_types()
        # Build a manager that:
        # - Print Module returns 3 theorems
        # - 2 depend on classic, 1 is closed
        manager = _make_mock_session_manager(
            print_module_output={
                "MyLib.Foo": (
                    "Module\nMyLib.Foo\n:= Struct\n"
                    "     Definition thm_a : nat -> Prop.\n"
                    "     Definition thm_b : nat -> Prop.\n"
                    "     Definition thm_c : nat -> Prop.\n"
                    "   End"
                ),
            },
            print_assumptions_output={
                "MyLib.Foo.thm_a": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
                "MyLib.Foo.thm_b": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
                "MyLib.Foo.thm_c": "Closed under the global context",
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
            },
        )
        result = await audit_module(manager, "MyLib.Foo", flag_categories=["classical"])
        assert isinstance(result, ModuleAuditResult)
        assert result.module == "MyLib.Foo"
        assert result.theorem_count == 3
        assert result.axiom_free_count == 1
        assert len(result.flagged_theorems) == 2
        # axiom_summary sorted by dependent_count descending
        assert len(result.axiom_summary) >= 1
        assert result.axiom_summary[0].axiom_name == "Stdlib.Logic.Classical_Prop.classic"
        assert result.axiom_summary[0].dependent_count == 2

    @pytest.mark.asyncio
    async def test_single_theorem_error_does_not_abort_batch(self):
        """Section 7.4: A single theorem error does not abort the batch."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()
        manager = _make_mock_session_manager(
            print_module_output={
                "MyLib.Bar": (
                    "Module\nMyLib.Bar\n:= Struct\n"
                    "     Definition thm_ok : nat -> Prop.\n"
                    "     Definition thm_bad : nat -> Prop.\n"
                    "   End"
                ),
            },
            print_assumptions_output={
                "MyLib.Bar.thm_ok": "Closed under the global context",
            },
            errors={
                "Print Assumptions MyLib.Bar.thm_bad.": AuditError(
                    "PARSE_ERROR",
                    "Failed to parse Print Assumptions output for MyLib.Bar.thm_bad: unexpected format",
                ),
            },
        )
        result = await audit_module(manager, "MyLib.Bar")
        assert result.theorem_count == 2
        # thm_ok should be fine
        ok_results = [r for r in result.per_theorem if r.error is None]
        err_results = [r for r in result.per_theorem if r.error is not None]
        assert len(ok_results) == 1
        assert len(err_results) == 1
        assert "PARSE_ERROR" in err_results[0].error

    @pytest.mark.asyncio
    async def test_axiom_free_count_excludes_errors(self):
        """Section 7.4: axiom_free_count excludes failed theorems."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()
        manager = _make_mock_session_manager(
            print_module_output={
                "MyLib.Baz": (
                    "Module\nMyLib.Baz\n:= Struct\n"
                    "     Definition thm_closed : nat -> Prop.\n"
                    "     Definition thm_err : nat -> Prop.\n"
                    "   End"
                ),
            },
            print_assumptions_output={
                "MyLib.Baz.thm_closed": "Closed under the global context",
            },
            errors={
                "Print Assumptions MyLib.Baz.thm_err.": AuditError(
                    "PARSE_ERROR", "bad output",
                ),
            },
        )
        result = await audit_module(manager, "MyLib.Baz")
        assert result.axiom_free_count == 1  # only thm_closed

    @pytest.mark.asyncio
    async def test_empty_module_name_raises_invalid_input(self):
        """Empty module name raises INVALID_INPUT."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()
        manager = AsyncMock()
        with pytest.raises(AuditError) as exc_info:
            await audit_module(manager, "")
        assert exc_info.value.code == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_nonexistent_module_raises_not_found(self):
        """Non-existent module raises NOT_FOUND."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()
        manager = _make_mock_session_manager(
            errors={
                "Print Module NoSuch.Module.": AuditError(
                    "NOT_FOUND",
                    "Module `NoSuch.Module` not found in the current Coq environment.",
                ),
            },
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_module(manager, "NoSuch.Module")
        assert exc_info.value.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_default_flag_categories(self):
        """Default flag_categories includes classical, choice, proof_irrelevance, custom."""
        _, audit_module, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_module_output={
                "MyLib.Defaults": (
                    "Module\nMyLib.Defaults\n:= Struct\n"
                    "     Definition thm_ext : nat -> Prop.\n"
                    "   End"
                ),
            },
            print_assumptions_output={
                # extensionality is NOT in the defaults
                "MyLib.Defaults.thm_ext": (
                    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep : "
                    "forall (A : Type) (B : A -> Type) (f g : forall x, B x), "
                    "(forall x, f x = g x) -> f = g"
                ),
            },
            declaration_kinds={
                "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep": "Axiom",
            },
        )
        # Call without explicit flag_categories to use defaults
        result = await audit_module(manager, "MyLib.Defaults")
        # extensionality is NOT in the default flag_categories, so no flagged theorems
        assert result.flagged_theorems == []

    @pytest.mark.asyncio
    async def test_invalid_flag_category_raises_invalid_input(self):
        """Invalid value in flag_categories raises INVALID_INPUT."""
        _, audit_module, _ = _import_engine()
        AuditError = _import_errors()
        manager = AsyncMock()
        with pytest.raises(AuditError) as exc_info:
            await audit_module(manager, "SomeModule", flag_categories=["bogus_category"])
        assert exc_info.value.code == "INVALID_INPUT"
        assert "bogus_category" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_axiom_summary_sorted_by_dependent_count_desc(self):
        """axiom_summary is sorted by dependent_count descending."""
        _, audit_module, _ = _import_engine()
        manager = _make_mock_session_manager(
            print_module_output={
                "MyLib.Sorted": (
                    "Module\nMyLib.Sorted\n:= Struct\n"
                    "     Definition t1 : nat -> Prop.\n"
                    "     Definition t2 : nat -> Prop.\n"
                    "     Definition t3 : nat -> Prop.\n"
                    "   End"
                ),
            },
            print_assumptions_output={
                "MyLib.Sorted.t1": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P\n"
                    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep : some_type"
                ),
                "MyLib.Sorted.t2": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P"
                ),
                "MyLib.Sorted.t3": (
                    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep : some_type\n"
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P"
                ),
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
                "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep": "Axiom",
            },
        )
        result = await audit_module(
            manager, "MyLib.Sorted", flag_categories=["classical", "extensionality"],
        )
        # classic appears in 3 theorems, func_ext in 2
        counts = [s.dependent_count for s in result.axiom_summary]
        assert counts == sorted(counts, reverse=True)
        assert result.axiom_summary[0].dependent_count >= result.axiom_summary[-1].dependent_count


# ===========================================================================
# 7. Assumption Comparison -- Section 4.7
# ===========================================================================

class TestAssumptionComparison:
    """Section 4.7: compare_assumptions behavior."""

    @pytest.mark.asyncio
    async def test_two_theorem_comparison_shared_and_unique(self):
        """Two-theorem: shared axioms, unique axioms, weakest identified."""
        _, _, compare_assumptions = _import_engine()
        (
            _AR, ClassifiedAxiom, _OD, AxiomCategory,
            _MAR, _AUS, _FT, ComparisonResult, _MR,
        ) = _import_types()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "A": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P\n"
                    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep : some_type"
                ),
                "B": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P"
                ),
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
                "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep": "Axiom",
            },
        )
        result = await compare_assumptions(manager, ["A", "B"])
        assert isinstance(result, ComparisonResult)
        assert result.theorems == ["A", "B"]
        # shared: classic
        shared_names = [a.name for a in result.shared_axioms]
        assert "Stdlib.Logic.Classical_Prop.classic" in shared_names
        # unique to A: func_ext
        unique_a_names = [a.name for a in result.unique_axioms["A"]]
        assert "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep" in unique_a_names
        # unique to B: empty
        assert result.unique_axioms["B"] == []
        # weakest: B (subset of A's axioms)
        assert result.weakest == ["B"]
        # matrix is null for 2 theorems
        assert result.matrix is None

    @pytest.mark.asyncio
    async def test_three_theorem_comparison_with_matrix(self):
        """N-theorem (N>=3): matrix included, weakest by cardinality with ties."""
        _, _, compare_assumptions = _import_engine()
        (
            _AR, _CA, _OD, AxiomCategory,
            _MAR, _AUS, _FT, ComparisonResult, MatrixRow,
        ) = _import_types()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "T1": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
                "T2": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P\n"
                    "Stdlib.Logic.ClassicalChoice.choice : some_type"
                ),
                "T3": "Stdlib.Logic.ClassicalChoice.choice : some_type",
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
                "Stdlib.Logic.ClassicalChoice.choice": "Axiom",
            },
        )
        result = await compare_assumptions(manager, ["T1", "T2", "T3"])
        # shared: no axiom is in all three
        assert result.shared_axioms == []
        # matrix present for 3+ theorems
        assert result.matrix is not None
        assert len(result.matrix) == 2  # classic and choice
        for row in result.matrix:
            assert isinstance(row, MatrixRow)
            assert len(row.present_in) > 0
        # weakest: T1 and T3 (each 1 axiom, neither subset of other)
        assert sorted(result.weakest) == ["T1", "T3"]

    @pytest.mark.asyncio
    async def test_fewer_than_two_names_raises_invalid_input(self):
        """Fewer than 2 names raises INVALID_INPUT."""
        _, _, compare_assumptions = _import_engine()
        AuditError = _import_errors()
        manager = AsyncMock()
        with pytest.raises(AuditError) as exc_info:
            await compare_assumptions(manager, ["only_one"])
        assert exc_info.value.code == "INVALID_INPUT"
        assert "at least 2" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_empty_names_raises_invalid_input(self):
        """Empty names list raises INVALID_INPUT."""
        _, _, compare_assumptions = _import_engine()
        AuditError = _import_errors()
        manager = AsyncMock()
        with pytest.raises(AuditError) as exc_info:
            await compare_assumptions(manager, [])
        assert exc_info.value.code == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_weakest_uses_subset_over_cardinality(self):
        """Strict subset inclusion takes priority over cardinality for weakest."""
        _, _, compare_assumptions = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                # A has {classic, func_ext}, B has {classic}
                # B is a strict subset of A
                "A": (
                    "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P\n"
                    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep : some_type"
                ),
                "B": "Stdlib.Logic.Classical_Prop.classic : forall P : Prop, P \\/ ~ P",
            },
            declaration_kinds={
                "Stdlib.Logic.Classical_Prop.classic": "Axiom",
                "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep": "Axiom",
            },
        )
        result = await compare_assumptions(manager, ["A", "B"])
        assert result.weakest == ["B"]

    @pytest.mark.asyncio
    async def test_preserves_input_order(self):
        """ComparisonResult.theorems preserves the input order."""
        _, _, compare_assumptions = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "Z_thm": "Closed under the global context",
                "A_thm": "Closed under the global context",
            },
        )
        result = await compare_assumptions(manager, ["Z_thm", "A_thm"])
        assert result.theorems == ["Z_thm", "A_thm"]

    @pytest.mark.asyncio
    async def test_both_closed_theorems_both_weakest(self):
        """Two closed theorems: both have 0 axioms, both are weakest."""
        _, _, compare_assumptions = _import_engine()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "closed_a": "Closed under the global context",
                "closed_b": "Closed under the global context",
            },
        )
        result = await compare_assumptions(manager, ["closed_a", "closed_b"])
        assert result.shared_axioms == []
        assert sorted(result.weakest) == ["closed_a", "closed_b"]


# ===========================================================================
# 8. Data Model -- Section 5
# ===========================================================================

class TestDataModel:
    """Section 5: Data model constraints."""

    def test_axiom_category_has_exactly_five_values(self):
        """AxiomCategory enum has exactly 5 values."""
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        values = set(member.value for member in AxiomCategory)
        assert values == {"classical", "extensionality", "choice", "proof_irrelevance", "custom"}

    def test_assumption_result_is_frozen_dataclass(self):
        """AssumptionResult is a frozen dataclass."""
        (
            AssumptionResult, *_rest,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(AssumptionResult)
        result = _make_assumption_result()
        with pytest.raises(AttributeError):
            result.name = "other"  # type: ignore[misc]

    def test_classified_axiom_is_frozen_dataclass(self):
        """ClassifiedAxiom is a frozen dataclass."""
        (
            _AR, ClassifiedAxiom, *_rest,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(ClassifiedAxiom)
        axiom = _make_classified_axiom()
        with pytest.raises(AttributeError):
            axiom.name = "other"  # type: ignore[misc]

    def test_opaque_dependency_is_frozen_dataclass(self):
        """OpaqueDependency is a frozen dataclass."""
        (
            _AR, _CA, OpaqueDependency, *_rest,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(OpaqueDependency)
        dep = _make_opaque_dependency()
        with pytest.raises(AttributeError):
            dep.name = "other"  # type: ignore[misc]

    def test_assumption_result_error_null_on_success(self):
        """AssumptionResult.error is None on success."""
        result = _make_assumption_result(error=None)
        assert result.error is None

    def test_assumption_result_error_set_on_failure(self):
        """AssumptionResult.error is a string on failure."""
        result = _make_assumption_result(error="PARSE_ERROR: bad output")
        assert result.error is not None
        assert isinstance(result.error, str)

    def test_module_audit_result_is_frozen_dataclass(self):
        """ModuleAuditResult is a frozen dataclass."""
        (
            _AR, _CA, _OD, _AC,
            ModuleAuditResult, *_rest,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(ModuleAuditResult)

    def test_comparison_result_is_frozen_dataclass(self):
        """ComparisonResult is a frozen dataclass."""
        (
            _AR, _CA, _OD, _AC,
            _MAR, _AUS, _FT, ComparisonResult, _MR,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(ComparisonResult)

    def test_matrix_row_is_frozen_dataclass(self):
        """MatrixRow is a frozen dataclass."""
        (
            _AR, _CA, _OD, _AC,
            _MAR, _AUS, _FT, _CR, MatrixRow,
        ) = _import_types()
        import dataclasses
        assert dataclasses.is_dataclass(MatrixRow)

    def test_axiom_category_is_str_enum(self):
        """AxiomCategory values are usable as strings (Section 10: StrEnum)."""
        (
            _AR, _CA, _OD, AxiomCategory, *_rest,
        ) = _import_types()
        cat = AxiomCategory("classical")
        assert isinstance(cat, str)
        assert cat == "classical"


# ===========================================================================
# 9. Error Specification -- Section 7
# ===========================================================================

class TestErrorSpecification:
    """Section 7: Error codes and messages."""

    @pytest.mark.asyncio
    async def test_backend_crashed_propagated(self):
        """BACKEND_CRASHED from session manager is propagated."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        _, BACKEND_CRASHED, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.send_command.side_effect = SessionError(
            BACKEND_CRASHED, "The Coq backend has crashed."
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "some_theorem")
        assert exc_info.value.code == "BACKEND_CRASHED"

    @pytest.mark.asyncio
    async def test_parse_error_includes_details(self):
        """PARSE_ERROR message includes the theorem name and details."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "bad_thm": "totally unparseable garbage !@#$",
            },
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "bad_thm")
        assert exc_info.value.code == "PARSE_ERROR"
        assert "bad_thm" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_coq_error_output_raises_not_found(self):
        """Spec §7.3: When coqtop returns a 'not found' error in the output
        string (not as an exception), audit_assumptions raises NOT_FOUND.

        This happens when send_command returns the raw Coq error output
        as a string rather than raising an exception — e.g., when a
        file-local theorem name is not in the coqtop environment."""
        audit_assumptions, _, _ = _import_engine()
        AuditError = _import_errors()
        # Simulate coqtop returning error output as a string
        coq_error = (
            "Rocq < Toplevel input, characters 18-27:\n"
            "> Print Assumptions my_lemma.\n"
            ">                   ^^^^^^^^^\n"
            "Error: The reference my_lemma was not found "
            "in the current environment."
        )
        manager = _make_mock_session_manager(
            print_assumptions_output={
                "my_lemma": coq_error,
            },
        )
        with pytest.raises(AuditError) as exc_info:
            await audit_assumptions(manager, "my_lemma")
        assert exc_info.value.code == "NOT_FOUND"
        assert "my_lemma" in exc_info.value.message

    def test_audit_error_has_code_and_message(self):
        """AuditError has code and message attributes."""
        AuditError = _import_errors()
        err = AuditError("INVALID_INPUT", "Theorem name must be non-empty.")
        assert err.code == "INVALID_INPUT"
        assert err.message == "Theorem name must be non-empty."


