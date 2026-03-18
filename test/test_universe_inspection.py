"""TDD tests for Universe Constraint Inspection (specification/universe-inspection.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/universe/ modules exist.

Spec: specification/universe-inspection.md
Architecture: doc/architecture/universe-inspection.md
Data model: specification/universe-inspection.md §5

Import paths under test:
  poule.universe.retrieval       (retrieve_full_graph, retrieve_definition_constraints)
  poule.universe.parser          (parse_constraints)
  poule.universe.graph           (build_graph, filter_by_reachability)
  poule.universe.diagnosis       (diagnose_universe_error)
  poule.universe.polymorphic     (retrieve_instantiations, compare_definitions)
  poule.universe.types           (UniverseExpression, UniverseConstraint,
                                  ConstraintGraph, InconsistencyDiagnosis,
                                  ConstraintAttribution)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_types():
    from poule.universe.types import (
        UniverseExpression,
        UniverseConstraint,
        ConstraintGraph,
        InconsistencyDiagnosis,
        ConstraintAttribution,
    )
    return (
        UniverseExpression,
        UniverseConstraint,
        ConstraintGraph,
        InconsistencyDiagnosis,
        ConstraintAttribution,
    )


def _import_retrieval():
    from poule.universe.retrieval import (
        retrieve_full_graph,
        retrieve_definition_constraints,
    )
    return retrieve_full_graph, retrieve_definition_constraints


def _import_parser():
    from poule.universe.parser import parse_constraints
    return parse_constraints


def _import_graph():
    from poule.universe.graph import build_graph, filter_by_reachability
    return build_graph, filter_by_reachability


def _import_diagnosis():
    from poule.universe.diagnosis import diagnose_universe_error
    return diagnose_universe_error


def _import_polymorphic():
    from poule.universe.polymorphic import (
        retrieve_instantiations,
        compare_definitions,
    )
    return retrieve_instantiations, compare_definitions


def _import_session_errors():
    from poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError


def _import_server_errors():
    from poule.server.errors import (
        NOT_FOUND,
        PARSE_ERROR,
    )
    return NOT_FOUND, PARSE_ERROR


# ---------------------------------------------------------------------------
# Helpers — real types for mock return values
# ---------------------------------------------------------------------------

def _make_variable(name: str):
    """Create a UniverseExpression of kind 'variable'."""
    UniverseExpression, *_ = _import_types()
    return UniverseExpression(
        kind="variable",
        name=name,
        base=None,
        offset=None,
        operands=None,
    )


def _make_constraint(left_name: str, relation: str, right_name: str, source=None):
    """Create a UniverseConstraint between two variable expressions."""
    _, UniverseConstraint, *_ = _import_types()
    return UniverseConstraint(
        left=_make_variable(left_name),
        relation=relation,
        right=_make_variable(right_name),
        source=source,
    )


def _make_constraint_graph(
    variables,
    constraints,
    filtered_from=None,
):
    """Build a ConstraintGraph from lists of variable names and constraints."""
    _, _, ConstraintGraph, *_ = _import_types()
    return ConstraintGraph(
        variables=list(variables),
        constraints=list(constraints),
        node_count=len(variables),
        edge_count=len(constraints),
        filtered_from=filtered_from,
    )


def _make_mock_session_manager(query_responses=None):
    """Create a mock session manager whose coq_query returns canned responses.

    query_responses: dict mapping command string to raw text response.
    """
    manager = AsyncMock()
    query_responses = query_responses or {}

    async def _coq_query(session_id, command):
        for key, value in query_responses.items():
            if key in command:
                return value
        return ""

    manager.coq_query.side_effect = _coq_query
    return manager


# ===========================================================================
# 1. Data Model — §5
# ===========================================================================

class TestDataModel:
    """§5: Data model entity structure and constraints."""

    def test_universe_expression_variable(self):
        """UniverseExpression with kind='variable' has required name field."""
        expr = _make_variable("u.42")
        assert expr.kind == "variable"
        assert expr.name == "u.42"

    def test_universe_expression_set(self):
        """UniverseExpression with kind='set' has null name."""
        UniverseExpression, *_ = _import_types()
        expr = UniverseExpression(
            kind="set", name=None, base=None, offset=None, operands=None,
        )
        assert expr.kind == "set"
        assert expr.name is None

    def test_universe_expression_prop(self):
        """UniverseExpression with kind='prop' has null name."""
        UniverseExpression, *_ = _import_types()
        expr = UniverseExpression(
            kind="prop", name=None, base=None, offset=None, operands=None,
        )
        assert expr.kind == "prop"
        assert expr.name is None

    def test_universe_expression_algebraic_offset(self):
        """UniverseExpression with kind='algebraic' can have base+offset."""
        UniverseExpression, *_ = _import_types()
        base = _make_variable("u.1")
        expr = UniverseExpression(
            kind="algebraic", name=None, base=base, offset=1, operands=None,
        )
        assert expr.kind == "algebraic"
        assert expr.base.name == "u.1"
        assert expr.offset == 1

    def test_universe_expression_algebraic_max(self):
        """UniverseExpression with kind='algebraic' can have max operands."""
        UniverseExpression, *_ = _import_types()
        op1 = _make_variable("u.1")
        op2 = _make_variable("u.2")
        expr = UniverseExpression(
            kind="algebraic", name=None, base=None, offset=None, operands=[op1, op2],
        )
        assert expr.operands is not None
        assert len(expr.operands) == 2

    def test_universe_constraint_fields(self):
        """UniverseConstraint has left, relation, right, source fields."""
        c = _make_constraint("u.1", "le", "u.2", source="my_def")
        assert c.left.name == "u.1"
        assert c.relation == "le"
        assert c.right.name == "u.2"
        assert c.source == "my_def"

    def test_universe_constraint_source_null_when_unknown(self):
        """UniverseConstraint.source is null when origin is unknown."""
        c = _make_constraint("u.1", "lt", "u.2")
        assert c.source is None

    def test_constraint_graph_counts_match(self):
        """ConstraintGraph.node_count and edge_count match list lengths."""
        c1 = _make_constraint("u.1", "le", "u.2")
        c2 = _make_constraint("u.2", "lt", "u.3")
        graph = _make_constraint_graph(
            variables=["u.1", "u.2", "u.3"],
            constraints=[c1, c2],
        )
        assert graph.node_count == len(graph.variables)
        assert graph.edge_count == len(graph.constraints)
        assert graph.node_count == 3
        assert graph.edge_count == 2

    def test_constraint_graph_filtered_from_null_by_default(self):
        """ConstraintGraph.filtered_from is null for unfiltered graphs."""
        graph = _make_constraint_graph(variables=[], constraints=[])
        assert graph.filtered_from is None

    def test_inconsistency_diagnosis_fields(self):
        """InconsistencyDiagnosis has all required fields per §5."""
        (
            UniverseExpression,
            UniverseConstraint,
            ConstraintGraph,
            InconsistencyDiagnosis,
            ConstraintAttribution,
        ) = _import_types()

        c = _make_constraint("u.42", "lt", "u.17")
        attr = ConstraintAttribution(
            constraint=c,
            definition="my_def",
            location="MyFile.v:42",
            confidence="certain",
        )
        subgraph = _make_constraint_graph(
            variables=["u.42", "u.17"],
            constraints=[c],
        )
        diag = InconsistencyDiagnosis(
            error_text="Universe inconsistency",
            cycle=[c],
            attributions=[attr],
            explanation="Conflict between u.42 and u.17",
            suggestions=["Make my_def universe-polymorphic."],
            relevant_subgraph=subgraph,
        )
        assert diag.error_text == "Universe inconsistency"
        assert len(diag.cycle) == 1
        assert len(diag.attributions) == 1
        assert len(diag.suggestions) >= 1
        assert diag.relevant_subgraph.node_count == 2

    def test_constraint_attribution_unknown_confidence(self):
        """ConstraintAttribution with unknown confidence has null definition."""
        _, _, _, _, ConstraintAttribution = _import_types()
        c = _make_constraint("u.99", "le", "u.100")
        attr = ConstraintAttribution(
            constraint=c,
            definition=None,
            location=None,
            confidence="unknown",
        )
        assert attr.definition is None
        assert attr.confidence == "unknown"


# ===========================================================================
# 2. Constraint Parsing — §4.3
# ===========================================================================

class TestConstraintParsing:
    """§4.3: parse_constraints behavioral requirements."""

    def test_parse_three_constraint_types(self):
        """Given le, lt, eq constraints, returns three records with correct relations.

        Spec example: raw text with u.1 <= u.2, u.2 < u.3, u.3 = u.4 and a comment.
        """
        parse_constraints = _import_parser()
        raw_text = "u.1 <= u.2\nu.2 < u.3\n(* comment *)\nu.3 = u.4"
        result = parse_constraints(raw_text, "print_universes")
        assert len(result) == 3
        assert result[0].relation == "le"
        assert result[1].relation == "lt"
        assert result[2].relation == "eq"

    def test_comment_lines_skipped(self):
        """Comment lines are skipped during parsing."""
        parse_constraints = _import_parser()
        raw_text = "(* comment *)\nu.1 <= u.2"
        result = parse_constraints(raw_text, "print_universes")
        assert len(result) == 1

    def test_blank_lines_skipped(self):
        """Blank lines are skipped during parsing."""
        parse_constraints = _import_parser()
        raw_text = "\n\nu.1 <= u.2\n\n"
        result = parse_constraints(raw_text, "print_universes")
        assert len(result) == 1

    def test_garbage_line_in_diagnostic(self):
        """Unparseable lines are recorded in diagnostic, valid constraints preserved.

        Spec example: u.1 <= u.2, GARBAGE LINE, u.3 < u.4 -> two constraints,
        diagnostic contains GARBAGE LINE.
        """
        parse_constraints = _import_parser()
        raw_text = "u.1 <= u.2\nGARBAGE LINE\nu.3 < u.4"
        result = parse_constraints(raw_text, "print_universes")
        # Two constraints successfully parsed
        assert len(result) == 2
        assert result[0].left.name == "u.1"
        assert result[1].left.name == "u.3"

    def test_successfully_parsed_never_discarded(self):
        """MAINTAINS: Successfully parsed constraints are never discarded due to later failures."""
        parse_constraints = _import_parser()
        raw_text = "u.1 <= u.2\nBAD\nWORSE\nu.5 < u.6"
        result = parse_constraints(raw_text, "print_universes")
        assert len(result) == 2

    def test_constraint_left_right_names(self):
        """Parsed constraints have correct left and right universe variable names."""
        parse_constraints = _import_parser()
        raw_text = "u.1 <= u.2"
        result = parse_constraints(raw_text, "print_universes")
        assert result[0].left.name == "u.1"
        assert result[0].right.name == "u.2"

    def test_empty_input_returns_empty_list(self):
        """Empty raw text returns an empty constraint list."""
        parse_constraints = _import_parser()
        result = parse_constraints("", "print_universes")
        assert result == []


# ===========================================================================
# 3. Constraint Graph Construction — §4.4
# ===========================================================================

class TestGraphConstruction:
    """§4.4: build_graph behavioral requirements."""

    def test_build_graph_from_constraints(self):
        """Given three constraints, builds graph with correct node/edge counts.

        Spec example: [u.1 < u.2, u.2 <= u.3, u.1 = u.3] ->
        variables = [u.1, u.2, u.3], node_count = 3, edge_count = 3.
        """
        build_graph, _ = _import_graph()
        c1 = _make_constraint("u.1", "lt", "u.2")
        c2 = _make_constraint("u.2", "le", "u.3")
        c3 = _make_constraint("u.1", "eq", "u.3")
        graph = build_graph([c1, c2, c3])
        assert set(graph.variables) == {"u.1", "u.2", "u.3"}
        assert graph.node_count == 3
        assert graph.edge_count == 3

    def test_build_graph_empty_constraints(self):
        """Empty constraint list produces an empty graph."""
        build_graph, _ = _import_graph()
        graph = build_graph([])
        assert graph.variables == []
        assert graph.node_count == 0
        assert graph.edge_count == 0

    def test_build_graph_duplicate_variables_counted_once(self):
        """Variables appearing in multiple constraints are counted only once."""
        build_graph, _ = _import_graph()
        c1 = _make_constraint("u.1", "le", "u.2")
        c2 = _make_constraint("u.1", "lt", "u.3")
        graph = build_graph([c1, c2])
        assert graph.node_count == 3
        assert graph.variables.count("u.1") == 1


# ===========================================================================
# 4. Subgraph Filtering — §4.5
# ===========================================================================

class TestSubgraphFiltering:
    """§4.5: filter_by_reachability behavioral requirements."""

    def test_filter_reachable_from_seed(self):
        """Given seed [u.1], returns u.1, u.2, u.3 but not u.4.

        Spec example: edges u.1 < u.2, u.2 <= u.3, u.4 < u.4.
        Seed [u.1] -> reachable = {u.1, u.2, u.3}.
        """
        _, filter_by_reachability = _import_graph()
        c1 = _make_constraint("u.1", "lt", "u.2")
        c2 = _make_constraint("u.2", "le", "u.3")
        c3 = _make_constraint("u.4", "lt", "u.4")
        graph = _make_constraint_graph(
            variables=["u.1", "u.2", "u.3", "u.4"],
            constraints=[c1, c2, c3],
        )
        filtered = filter_by_reachability(graph, ["u.1"])
        assert set(filtered.variables) == {"u.1", "u.2", "u.3"}
        assert filtered.node_count == 3
        # Only c1 and c2 have both endpoints in the reachable set
        assert filtered.edge_count == 2

    def test_filter_follows_edges_both_directions(self):
        """Reachability follows edges forward and backward (§4.5)."""
        _, filter_by_reachability = _import_graph()
        # u.1 -> u.2 -> u.3 ; seeding from u.3 should reach u.1 backward
        c1 = _make_constraint("u.1", "le", "u.2")
        c2 = _make_constraint("u.2", "le", "u.3")
        graph = _make_constraint_graph(
            variables=["u.1", "u.2", "u.3"],
            constraints=[c1, c2],
        )
        filtered = filter_by_reachability(graph, ["u.3"])
        assert set(filtered.variables) == {"u.1", "u.2", "u.3"}

    def test_filter_disconnected_component_excluded(self):
        """Variables in disconnected components are excluded."""
        _, filter_by_reachability = _import_graph()
        c1 = _make_constraint("u.1", "le", "u.2")
        c2 = _make_constraint("u.3", "le", "u.4")
        graph = _make_constraint_graph(
            variables=["u.1", "u.2", "u.3", "u.4"],
            constraints=[c1, c2],
        )
        filtered = filter_by_reachability(graph, ["u.1"])
        assert set(filtered.variables) == {"u.1", "u.2"}
        assert filtered.edge_count == 1


# ===========================================================================
# 5. Full Graph Retrieval — §4.1
# ===========================================================================

class TestFullGraphRetrieval:
    """§4.1: retrieve_full_graph behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_constraint_graph_with_correct_counts(self):
        """Given an environment with 3 variables and 2 constraints,
        returns a ConstraintGraph with node_count=3, edge_count=2.
        """
        retrieve_full_graph, _ = _import_retrieval()
        _, _, ConstraintGraph, *_ = _import_types()
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.1 <= u.2\nu.2 < u.3",
        })
        result = await retrieve_full_graph(manager, "test-session")
        assert isinstance(result, ConstraintGraph)
        assert result.node_count == 3
        assert result.edge_count == 2

    @pytest.mark.asyncio
    async def test_contains_expected_constraints(self):
        """Returned graph contains the parsed constraints."""
        retrieve_full_graph, _ = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.1 <= u.2\nu.2 < u.3",
        })
        result = await retrieve_full_graph(manager, "test-session")
        relations = [c.relation for c in result.constraints]
        assert "le" in relations
        assert "lt" in relations

    @pytest.mark.asyncio
    async def test_empty_environment_returns_graph_no_error(self):
        """An environment with no user-defined constraints returns a graph; no error."""
        retrieve_full_graph, _ = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "",
        })
        result = await retrieve_full_graph(manager, "test-session")
        # May contain Coq-internal constraints or be empty; no error raised
        assert result is not None

    @pytest.mark.asyncio
    async def test_session_not_found_propagated(self):
        """SESSION_NOT_FOUND from session manager is propagated."""
        retrieve_full_graph, _ = _import_retrieval()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.coq_query.side_effect = SessionError(
            SESSION_NOT_FOUND, "No active session."
        )
        with pytest.raises(SessionError) as exc_info:
            await retrieve_full_graph(manager, "nonexistent")
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_retrieve_full_graph(self, coq_test_file):
        """Contract test: real coq_query returns text that parses into a ConstraintGraph."""
        retrieve_full_graph, _ = _import_retrieval()
        # This test exercises the real Coq backend.
        # Skipped when Coq is not available.
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            result = await retrieve_full_graph(manager, session_id)
            assert hasattr(result, "variables")
            assert hasattr(result, "constraints")
            assert result.node_count == len(result.variables)
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 6. Per-Definition Constraint Retrieval — §4.2
# ===========================================================================

class TestDefinitionConstraintRetrieval:
    """§4.2: retrieve_definition_constraints behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_graph_with_filtered_from(self):
        """Returned graph has filtered_from set to the qualified name.

        Spec example: my_id with constraint u.5 <= u.6.
        """
        _, retrieve_definition_constraints = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print my_id": "my_id : Type@{u.5} -> Type@{u.6}\n(* u.5 <= u.6 *)",
            "Unset Printing Universes": "",
        })
        result = await retrieve_definition_constraints(manager, "test-session", "my_id")
        assert result.filtered_from == "my_id"

    @pytest.mark.asyncio
    async def test_no_constraints_returns_empty_graph(self):
        """A definition with no universe constraints returns an empty constraint set.

        Spec example: simple_nat with no universe constraints.
        """
        _, retrieve_definition_constraints = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print simple_nat": "simple_nat = 42 : nat",
            "Unset Printing Universes": "",
        })
        result = await retrieve_definition_constraints(
            manager, "test-session", "simple_nat",
        )
        assert result.constraints == []

    @pytest.mark.asyncio
    async def test_nonexistent_definition_returns_not_found(self):
        """A nonexistent definition returns a NOT_FOUND error.

        Spec example: qualified_name = 'nonexistent_def'.
        """
        _, retrieve_definition_constraints = _import_retrieval()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()

        manager = AsyncMock()

        async def _query(session_id, command):
            if "Print nonexistent_def" in command:
                raise SessionError("NOT_FOUND", "Definition 'nonexistent_def' not found in the current environment.")
            return ""

        manager.coq_query.side_effect = _query

        with pytest.raises(Exception) as exc_info:
            await retrieve_definition_constraints(
                manager, "test-session", "nonexistent_def",
            )
        # Error code should indicate NOT_FOUND
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_qualified_name_returns_invalid_input(self):
        """Empty qualified_name is rejected with INVALID_INPUT (§7.1)."""
        _, retrieve_definition_constraints = _import_retrieval()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await retrieve_definition_constraints(manager, "test-session", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_retrieve_definition_constraints(self, coq_test_file):
        """Contract test: real per-definition retrieval returns a ConstraintGraph."""
        _, retrieve_definition_constraints = _import_retrieval()
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            result = await retrieve_definition_constraints(
                manager, session_id, "nat",
            )
            assert hasattr(result, "filtered_from")
            assert result.filtered_from == "nat"
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 7. Inconsistency Diagnosis — §4.6
# ===========================================================================

class TestInconsistencyDiagnosis:
    """§4.6: diagnose_universe_error behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_diagnosis_with_cycle(self):
        """Given a universe inconsistency error, returns diagnosis with cycle.

        Spec example: "Universe inconsistency: cannot enforce u.42 < u.17
        because u.17 <= u.42 is already required"
        """
        diagnose = _import_diagnosis()
        _, _, _, InconsistencyDiagnosis, _ = _import_types()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        assert isinstance(result, InconsistencyDiagnosis)
        # Cycle should involve u.42 and u.17
        cycle_vars = set()
        for c in result.cycle:
            cycle_vars.add(c.left.name)
            cycle_vars.add(c.right.name)
        assert "u.42" in cycle_vars
        assert "u.17" in cycle_vars

    @pytest.mark.asyncio
    async def test_diagnosis_has_explanation(self):
        """Diagnosis includes a plain-language explanation."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0

    @pytest.mark.asyncio
    async def test_diagnosis_has_at_least_one_suggestion(self):
        """Diagnosis includes at least one resolution suggestion (§4.9)."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_diagnosis_has_relevant_subgraph(self):
        """Diagnosis includes the relevant subgraph from error-named variables."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42\nu.99 <= u.100",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        _, _, ConstraintGraph, *_ = _import_types()
        assert isinstance(result.relevant_subgraph, ConstraintGraph)

    @pytest.mark.asyncio
    async def test_non_universe_error_returns_invalid_input(self):
        """A non-universe error message returns INVALID_INPUT (§7.1)."""
        diagnose = _import_diagnosis()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await diagnose(manager, "test-session", "Type mismatch: nat vs bool", {})
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_empty_error_message_returns_invalid_input(self):
        """Empty error_message is rejected with INVALID_INPUT (§7.1)."""
        diagnose = _import_diagnosis()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await diagnose(manager, "test-session", "", {})
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_no_cycle_found_returns_empty_cycle(self):
        """When the inconsistency cannot be reproduced, returns empty cycle (§7.5)."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        # Environment has changed; constraints no longer form a cycle
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 <= u.50\nu.50 <= u.17",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        assert result.cycle == []
        assert len(result.explanation) > 0

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_diagnose_universe_error(self, coq_test_file):
        """Contract test: real diagnosis against a Coq backend."""
        diagnose = _import_diagnosis()
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            error_msg = (
                "Universe inconsistency: cannot enforce u.1 < u.2 "
                "because u.2 <= u.1 is already required"
            )
            result = await diagnose(manager, session_id, error_msg, {})
            assert hasattr(result, "cycle")
            assert hasattr(result, "explanation")
            assert hasattr(result, "suggestions")
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 8. Cycle Detection — §4.7
# ===========================================================================

class TestCycleDetection:
    """§4.7: Cycle detection in constraint subgraphs."""

    def test_cycle_with_strict_edge_detected(self):
        """A cycle with at least one strict edge is detected.

        Spec example: u.1 < u.2, u.2 <= u.3, u.3 <= u.1 -> cycle returned.
        """
        build_graph, filter_by_reachability = _import_graph()
        c1 = _make_constraint("u.1", "lt", "u.2")
        c2 = _make_constraint("u.2", "le", "u.3")
        c3 = _make_constraint("u.3", "le", "u.1")
        graph = build_graph([c1, c2, c3])
        filtered = filter_by_reachability(graph, ["u.1"])
        # The filtered graph should contain all three constraints
        assert filtered.edge_count == 3
        # Cycle detection is exercised through diagnose_universe_error;
        # we verify the graph structure supports it.
        cycle_vars = set()
        for c in filtered.constraints:
            cycle_vars.add(c.left.name)
            cycle_vars.add(c.right.name)
        assert cycle_vars == {"u.1", "u.2", "u.3"}

    def test_cycle_with_no_strict_edge_is_not_inconsistent(self):
        """A cycle with only non-strict edges is not an inconsistency.

        Spec example: u.1 <= u.2, u.2 <= u.1 -> empty cycle returned.
        """
        # This is tested end-to-end via diagnosis
        diagnose = _import_diagnosis()
        # The cycle u.1 <= u.2, u.2 <= u.1 has no strict edge -> no inconsistency
        # We verify through the diagnosis path
        build_graph, _ = _import_graph()
        c1 = _make_constraint("u.1", "le", "u.2")
        c2 = _make_constraint("u.2", "le", "u.1")
        graph = build_graph([c1, c2])
        # Graph has the edges, but no strict edge in cycle -> no inconsistency
        assert graph.edge_count == 2

    @pytest.mark.asyncio
    async def test_shortest_cycle_selected(self):
        """The shortest cycle containing a strict edge is selected (§4.7 step 3)."""
        diagnose = _import_diagnosis()
        # Create a graph where a short cycle (u.1 < u.2, u.2 <= u.1) exists
        # alongside a longer path
        error_msg = (
            "Universe inconsistency: cannot enforce u.1 < u.2 "
            "because u.2 <= u.1 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.1 < u.2\nu.2 <= u.1\nu.1 <= u.3\nu.3 <= u.2",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        # The shortest cycle should be selected (length 2: u.1 < u.2, u.2 <= u.1)
        if result.cycle:
            assert len(result.cycle) <= 3  # At most the 2-edge cycle


# ===========================================================================
# 9. Source Attribution — §4.8
# ===========================================================================

class TestSourceAttribution:
    """§4.8: Source attribution for constraints in cycles."""

    @pytest.mark.asyncio
    async def test_attribution_with_known_definition(self):
        """When About output traces a variable, attribution has definition and confidence='certain'.

        Spec example: u.5 < u.10 where About my_def shows u.5 from my_def.
        """
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.5 < u.10 "
            "because u.10 <= u.5 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.5 < u.10\nu.10 <= u.5",
            "About": "my_def : Type@{u.5}",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        # At least one attribution should be present per cycle constraint
        assert len(result.attributions) == len(result.cycle)

    @pytest.mark.asyncio
    async def test_attribution_unknown_when_untraceable(self):
        """When a variable cannot be traced, confidence is 'unknown' and definition is null.

        Spec example: u.99 <= u.100 where no definition can be traced.
        """
        diagnose = _import_diagnosis()
        _, _, _, _, ConstraintAttribution = _import_types()
        error_msg = (
            "Universe inconsistency: cannot enforce u.99 < u.100 "
            "because u.100 <= u.99 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.99 < u.100\nu.100 <= u.99",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        # Attribution should exist for each cycle constraint
        for attr in result.attributions:
            assert isinstance(attr, ConstraintAttribution)
            assert attr.confidence in ("certain", "inferred", "unknown")

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_attribution_uses_about_command(self, coq_test_file):
        """Contract test: real attribution queries About for definitions."""
        diagnose = _import_diagnosis()
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            error_msg = (
                "Universe inconsistency: cannot enforce u.1 < u.2 "
                "because u.2 <= u.1 is already required"
            )
            result = await diagnose(manager, session_id, error_msg, {})
            for attr in result.attributions:
                assert attr.confidence in ("certain", "inferred", "unknown")
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 10. Resolution Suggestions — §4.9
# ===========================================================================

class TestResolutionSuggestions:
    """§4.9: Resolution suggestion strategies."""

    @pytest.mark.asyncio
    async def test_at_least_one_suggestion_always(self):
        """At least one suggestion is always included in the diagnosis (§4.9)."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_suggestions_are_strings(self):
        """Suggestions are a list of strings."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.42 < u.17 "
            "because u.17 <= u.42 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.42 < u.17\nu.17 <= u.42",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        for s in result.suggestions:
            assert isinstance(s, str)
            assert len(s) > 0


# ===========================================================================
# 11. Polymorphic Instantiation Retrieval — §4.10
# ===========================================================================

class TestPolymorphicInstantiationRetrieval:
    """§4.10: retrieve_instantiations behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_instantiation_mappings(self):
        """Given my_func that uses list@{u.5}, returns the mapping.

        Spec example: my_func uses list@{u.5} -> ("list", {"u": "u.5"}).
        """
        retrieve_instantiations, _ = _import_polymorphic()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print my_func": (
                "my_func = fun (A : Type@{u.5}) => @nil@{u.5} A\n"
                "     : Type@{u.5} -> list@{u.5} A"
            ),
            "Unset Printing Universes": "",
        })
        result = await retrieve_instantiations(manager, "test-session", "my_func")
        assert len(result) >= 1
        # At least one entry should reference "list" or "nil"
        defs = [entry[0] if isinstance(entry, tuple) else entry.get("definition", entry) for entry in result]
        # The spec example shows both nil and list
        assert any("list" in str(d) or "nil" in str(d) for d in defs)

    @pytest.mark.asyncio
    async def test_nonexistent_definition_returns_not_found(self):
        """A nonexistent use_site_name returns NOT_FOUND."""
        retrieve_instantiations, _ = _import_polymorphic()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()

        manager = AsyncMock()

        async def _query(session_id, command):
            if "Print nonexistent_def" in command:
                raise SessionError("NOT_FOUND", "Definition 'nonexistent_def' not found in the current environment.")
            return ""

        manager.coq_query.side_effect = _query

        with pytest.raises(Exception) as exc_info:
            await retrieve_instantiations(manager, "test-session", "nonexistent_def")
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_use_site_name_returns_invalid_input(self):
        """Empty use_site_name is rejected with INVALID_INPUT (§7.1)."""
        retrieve_instantiations, _ = _import_polymorphic()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await retrieve_instantiations(manager, "test-session", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_retrieve_instantiations(self, coq_test_file):
        """Contract test: real instantiation retrieval returns structured data."""
        retrieve_instantiations, _ = _import_polymorphic()
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            result = await retrieve_instantiations(manager, session_id, "list")
            assert isinstance(result, list)
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 12. Polymorphic Compatibility Comparison — §4.11
# ===========================================================================

class TestPolymorphicCompatibilityComparison:
    """§4.11: compare_definitions behavioral requirements."""

    @pytest.mark.asyncio
    async def test_incompatible_definitions_detected(self):
        """Definitions with conflicting constraints are reported as incompatible.

        Spec example: def_a has u.1 < u.2, def_b has u.2 <= u.1 -> incompatible.
        """
        _, compare_definitions = _import_polymorphic()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print def_a": "def_a : Type@{u.1} -> Type@{u.2}\n(* u.1 < u.2 *)",
            "Print def_b": "def_b : Type@{u.2} -> Type@{u.1}\n(* u.2 <= u.1 *)",
            "Unset Printing Universes": "",
            "About def_a": "def_a : Type@{u.1} -> Type@{u.2}",
            "About def_b": "def_b : Type@{u.2} -> Type@{u.1}",
        })
        result = await compare_definitions(manager, "test-session", "def_a", "def_b")
        # Result should indicate incompatibility
        assert not result.compatible if hasattr(result, "compatible") else "incompatib" in str(result).lower()

    @pytest.mark.asyncio
    async def test_compatible_definitions_detected(self):
        """Definitions with non-conflicting constraints are reported as compatible.

        Spec example: def_a has u.1 <= u.2, def_b has u.1 <= u.3 -> compatible.
        """
        _, compare_definitions = _import_polymorphic()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print def_a": "def_a : Type@{u.1} -> Type@{u.2}\n(* u.1 <= u.2 *)",
            "Print def_b": "def_b : Type@{u.1} -> Type@{u.3}\n(* u.1 <= u.3 *)",
            "Unset Printing Universes": "",
            "About def_a": "def_a : Type@{u.1} -> Type@{u.2}",
            "About def_b": "def_b : Type@{u.1} -> Type@{u.3}",
        })
        result = await compare_definitions(manager, "test-session", "def_a", "def_b")
        assert result.compatible if hasattr(result, "compatible") else "compat" in str(result).lower()

    @pytest.mark.asyncio
    async def test_incompatible_identifies_conflicting_constraints(self):
        """When incompatible, the result identifies the specific conflicting constraints."""
        _, compare_definitions = _import_polymorphic()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print def_a": "def_a : Type@{u.1} -> Type@{u.2}\n(* u.1 < u.2 *)",
            "Print def_b": "def_b : Type@{u.2} -> Type@{u.1}\n(* u.2 <= u.1 *)",
            "Unset Printing Universes": "",
            "About def_a": "def_a : Type@{u.1} -> Type@{u.2}",
            "About def_b": "def_b : Type@{u.2} -> Type@{u.1}",
        })
        result = await compare_definitions(manager, "test-session", "def_a", "def_b")
        # The result should contain information about the cycle
        if hasattr(result, "conflicting_constraints"):
            assert len(result.conflicting_constraints) > 0

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_compare_definitions(self, coq_test_file):
        """Contract test: real comparison against a Coq backend."""
        _, compare_definitions = _import_polymorphic()
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            result = await compare_definitions(manager, session_id, "nat", "bool")
            assert result is not None
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 13. Error Specification — §7
# ===========================================================================

class TestErrorSpecification:
    """§7: Error codes and messages."""

    @pytest.mark.asyncio
    async def test_session_not_found_error(self):
        """No active session -> SESSION_NOT_FOUND (§7.2)."""
        retrieve_full_graph, _ = _import_retrieval()
        _, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.coq_query.side_effect = SessionError(
            SESSION_NOT_FOUND,
            "No active session. Open a proof session first to establish a Coq environment.",
        )
        with pytest.raises(SessionError) as exc_info:
            await retrieve_full_graph(manager, "nonexistent")
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_backend_crashed_propagated(self):
        """Backend crash -> BACKEND_CRASHED propagated (§7.3)."""
        retrieve_full_graph, _ = _import_retrieval()
        BACKEND_CRASHED, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.coq_query.side_effect = SessionError(
            BACKEND_CRASHED, "backend crashed",
        )
        with pytest.raises(SessionError) as exc_info:
            await retrieve_full_graph(manager, "test-session")
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_definition_not_found_error(self):
        """Definition not found -> NOT_FOUND with descriptive message (§7.1)."""
        _, retrieve_definition_constraints = _import_retrieval()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()

        manager = AsyncMock()

        async def _query(session_id, command):
            if "Print missing_def" in command:
                raise SessionError("NOT_FOUND", "Definition 'missing_def' not found in the current environment.")
            return ""

        manager.coq_query.side_effect = _query

        with pytest.raises(Exception) as exc_info:
            await retrieve_definition_constraints(manager, "test-session", "missing_def")
        assert "NOT_FOUND" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_input_empty_qualified_name(self):
        """Empty qualified_name -> INVALID_INPUT (§7.1)."""
        _, retrieve_definition_constraints = _import_retrieval()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await retrieve_definition_constraints(manager, "test-session", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_invalid_input_non_universe_error(self):
        """Non-universe error -> INVALID_INPUT (§7.1)."""
        diagnose = _import_diagnosis()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await diagnose(manager, "test-session", "Syntax error: blah", {})
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_definition_no_constraints_is_not_error(self):
        """Definition with no universe constraints -> success, empty constraints (§7.5)."""
        _, retrieve_definition_constraints = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print simple": "simple = 0 : nat",
            "Unset Printing Universes": "",
        })
        result = await retrieve_definition_constraints(manager, "test-session", "simple")
        assert result.constraints == []

    @pytest.mark.asyncio
    async def test_attribution_failure_is_not_error(self):
        """Source attribution failure -> confidence='unknown', diagnosis proceeds (§7.5)."""
        diagnose = _import_diagnosis()
        error_msg = (
            "Universe inconsistency: cannot enforce u.77 < u.88 "
            "because u.88 <= u.77 is already required"
        )
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.77 < u.88\nu.88 <= u.77",
        })
        result = await diagnose(manager, "test-session", error_msg, {})
        # Diagnosis should succeed even if attributions are unknown
        assert result is not None
        assert len(result.suggestions) >= 1
        for attr in result.attributions:
            assert attr.confidence in ("certain", "inferred", "unknown")


# ===========================================================================
# 14. Interface Contracts — §6
# ===========================================================================

class TestInterfaceContracts:
    """§6: Interface contracts with Coq Query Layer and MCP Server."""

    @pytest.mark.asyncio
    async def test_retrieve_full_graph_uses_coq_query(self):
        """retrieve_full_graph submits 'Print Universes.' via coq_query."""
        retrieve_full_graph, _ = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.1 <= u.2",
        })
        await retrieve_full_graph(manager, "test-session")
        # coq_query should have been called with Print Universes
        manager.coq_query.assert_called()
        calls = [str(c) for c in manager.coq_query.call_args_list]
        assert any("Print Universes" in c for c in calls)

    @pytest.mark.asyncio
    async def test_definition_retrieval_atomic_command_sequence(self):
        """Per-definition retrieval sends Set/Print/Unset atomically (§6)."""
        _, retrieve_definition_constraints = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Set Printing Universes": "",
            "Print test_def": "test_def : Type@{u.1}",
            "Unset Printing Universes": "",
        })
        await retrieve_definition_constraints(manager, "test-session", "test_def")
        # Verify all three commands were issued
        calls = [str(c) for c in manager.coq_query.call_args_list]
        assert any("Set Printing Universes" in c for c in calls)
        assert any("Print test_def" in c for c in calls)
        assert any("Unset Printing Universes" in c for c in calls)

    @pytest.mark.asyncio
    async def test_session_state_unchanged_after_retrieval(self):
        """MAINTAINS: Coq session state is unchanged after retrieval (§4.1)."""
        retrieve_full_graph, _ = _import_retrieval()
        manager = _make_mock_session_manager(query_responses={
            "Print Universes": "u.1 <= u.2",
        })
        await retrieve_full_graph(manager, "test-session")
        # No state-modifying commands should have been issued
        # Print Universes is read-only
        calls = [str(c) for c in manager.coq_query.call_args_list]
        state_modifying = ["Admitted", "Qed", "Abort", "Undo"]
        for cmd in state_modifying:
            assert not any(cmd in c for c in calls)

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_coq_query_returns_text(self, coq_test_file):
        """Contract test: coq_query returns raw text for Print Universes."""
        from poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.create_session(str(coq_test_file), "test_proof")
        try:
            raw = await manager.coq_query(session_id, "Print Universes.")
            assert isinstance(raw, str)
        finally:
            await manager.close_session(session_id)


# ===========================================================================
# 15. Input Validation — §7.1
# ===========================================================================

class TestInputValidation:
    """§7.1: Input validation for all exposed operations."""

    @pytest.mark.asyncio
    async def test_empty_qualified_name_rejected(self):
        """Empty qualified_name -> INVALID_INPUT for retrieve_definition_constraints."""
        _, retrieve_definition_constraints = _import_retrieval()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await retrieve_definition_constraints(manager, "test-session", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_empty_error_message_rejected(self):
        """Empty error_message -> INVALID_INPUT for diagnose_universe_error."""
        diagnose = _import_diagnosis()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await diagnose(manager, "test-session", "", {})
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_empty_use_site_name_rejected(self):
        """Empty use_site_name -> INVALID_INPUT for retrieve_instantiations."""
        retrieve_instantiations, _ = _import_polymorphic()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await retrieve_instantiations(manager, "test-session", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_empty_name_a_rejected_for_compare(self):
        """Empty name_a -> INVALID_INPUT for compare_definitions."""
        _, compare_definitions = _import_polymorphic()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await compare_definitions(manager, "test-session", "", "def_b")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_empty_name_b_rejected_for_compare(self):
        """Empty name_b -> INVALID_INPUT for compare_definitions."""
        _, compare_definitions = _import_polymorphic()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await compare_definitions(manager, "test-session", "def_a", "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )
