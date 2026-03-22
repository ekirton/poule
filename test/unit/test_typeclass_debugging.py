"""TDD tests for the Typeclass Debugging component (specification/typeclass-debugging.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/typeclass/ modules exist.

Spec: specification/typeclass-debugging.md
Architecture: doc/architecture/typeclass-debugging.md

Import paths under test:
  poule.typeclass.debugging    (list_instances, list_typeclasses, trace_resolution,
                                explain_failure, detect_conflicts, explain_instance)
  poule.typeclass.types        (TypeclassInfo, TypeclassSummary, ResolutionTrace,
                                ResolutionNode, FailureExplanation, InstanceConflict,
                                InstanceExplanation)
  poule.typeclass.parser       (TraceParser)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


def _import_parser():
    from Poule.typeclass.parser import TraceParser
    return TraceParser


def _import_session_errors():
    from Poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError


def _import_constants():
    from Poule.typeclass.debugging import (
        MAX_TYPECLASSES_FOR_INSTANCE_COUNT,
        TYPECLASS_COMMAND_TIMEOUT_SECONDS,
    )
    return MAX_TYPECLASSES_FOR_INSTANCE_COUNT, TYPECLASS_COMMAND_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_typeclass_info(
    instance_name="Eq_nat",
    typeclass_name="Eq",
    type_signature="Eq nat",
    defining_module="Stdlib.Classes",
):
    TypeclassInfo, *_ = _import_types()
    return TypeclassInfo(
        instance_name=instance_name,
        typeclass_name=typeclass_name,
        type_signature=type_signature,
        defining_module=defining_module,
    )


def _make_resolution_node(
    instance_name="Eq_nat",
    goal="Eq nat",
    outcome="success",
    failure_detail=None,
    children=None,
    depth=0,
):
    _, _, _, ResolutionNode, *_ = _import_types()
    return ResolutionNode(
        instance_name=instance_name,
        goal=goal,
        outcome=outcome,
        failure_detail=failure_detail,
        children=children or [],
        depth=depth,
    )


def _make_resolution_trace(
    goal="Eq nat",
    root_nodes=None,
    succeeded=True,
    failure_mode=None,
    raw_output="",
):
    _, _, ResolutionTrace, *_ = _import_types()
    return ResolutionTrace(
        goal=goal,
        root_nodes=root_nodes or [],
        succeeded=succeeded,
        failure_mode=failure_mode,
        raw_output=raw_output,
    )


def _make_failure_explanation(**kwargs):
    _, _, _, _, FailureExplanation, *_ = _import_types()
    defaults = dict(
        failure_mode="no_instance",
        typeclass=None,
        type_arguments=None,
        goal_context=None,
        closest_instance=None,
        successful_unifications=None,
        mismatch_expected=None,
        mismatch_actual=None,
        resolution_path=None,
        cycle_detected=None,
        cycle_typeclasses=None,
        max_depth_reached=None,
        raw_output=None,
    )
    defaults.update(kwargs)
    return FailureExplanation(**defaults)


def _make_mock_session_manager(vernacular_responses=None):
    """Create a mock session manager with send_command support.

    vernacular_responses: dict mapping command string to response string.
    Per spec §6, typeclass debugging uses submit_command (coqtop routing).
    """
    manager = AsyncMock()
    vernacular_responses = vernacular_responses or {}

    async def _send(session_id, command, *, prefer_coqtop=False):
        if command in vernacular_responses:
            return vernacular_responses[command]
        return ""

    manager.send_command.side_effect = _send
    return manager


# ===========================================================================
# 1. Instance Listing -- S4.1 list_instances
# ===========================================================================

class TestListInstances:
    """S4.1: list_instances behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_typeclass_info_records(self):
        """Given EqDec with two instances, returns two TypeclassInfo records."""
        list_instances, *_ = _import_debugging()
        TypeclassInfo, *_ = _import_types()

        manager = _make_mock_session_manager({
            "Print Instances EqDec.": (
                "EqDec_nat : EqDec nat\n"
                "EqDec_bool : EqDec bool"
            ),
        })
        result = await list_instances(
            session_id="abc123",
            typeclass_name="EqDec",
            session_manager=manager,
        )
        assert len(result) == 2
        assert all(isinstance(r, TypeclassInfo) for r in result)
        names = {r.instance_name for r in result}
        assert "EqDec_nat" in names
        assert "EqDec_bool" in names
        for r in result:
            assert r.typeclass_name == "EqDec"
            assert r.type_signature != ""
            assert r.defining_module != ""

    @pytest.mark.asyncio
    async def test_empty_list_when_no_instances(self):
        """Given EqDec registered but no instances, returns empty list."""
        list_instances, *_ = _import_debugging()

        manager = _make_mock_session_manager({
            "Print Instances EqDec.": "",
        })
        result = await list_instances(
            session_id="abc123",
            typeclass_name="EqDec",
            session_manager=manager,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_not_a_typeclass_error(self):
        """Given not_a_class is not a typeclass, returns NOT_A_TYPECLASS error."""
        list_instances, *_ = _import_debugging()
        _, _, SessionError = _import_session_errors()

        manager = _make_mock_session_manager({
            "Print Instances not_a_class.": "Error: not_a_class is not a typeclass.",
        })
        with pytest.raises(Exception) as exc_info:
            await list_instances(
                session_id="abc123",
                typeclass_name="not_a_class",
                session_manager=manager,
            )
        assert "NOT_A_TYPECLASS" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_A_TYPECLASS"
        )

    @pytest.mark.asyncio
    async def test_empty_name_returns_invalid_input(self):
        """S7.1: Empty typeclass_name returns INVALID_INPUT error."""
        list_instances, *_ = _import_debugging()

        manager = _make_mock_session_manager()
        with pytest.raises(Exception) as exc_info:
            await list_instances(
                session_id="abc123",
                typeclass_name="",
                session_manager=manager,
            )
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    @pytest.mark.asyncio
    async def test_session_not_found_error(self):
        """S7.2: Non-existent session returns SESSION_NOT_FOUND."""
        list_instances, *_ = _import_debugging()
        _, SESSION_NOT_FOUND, SessionError = _import_session_errors()

        manager = AsyncMock()
        manager.send_command.side_effect = SessionError(
            SESSION_NOT_FOUND, "not found"
        )
        with pytest.raises(SessionError) as exc_info:
            await list_instances(
                session_id="nonexistent",
                typeclass_name="Eq",
                session_manager=manager,
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_state_unchanged_after_call(self):
        """MAINTAINS: The session's proof state is unchanged after the call."""
        list_instances, *_ = _import_debugging()

        manager = _make_mock_session_manager({
            "Print Instances Eq.": "Eq_nat : Eq nat",
        })
        await list_instances(
            session_id="abc123",
            typeclass_name="Eq",
            session_manager=manager,
        )
        # Only Print Instances should be called -- no state-altering commands
        for call in manager.send_command.call_args_list:
            cmd = call[0][1] if len(call[0]) > 1 else call[1].get("command", "")
            assert "Print Instances" in cmd or "Print" in cmd



# ===========================================================================
# 2. Instance Listing -- S4.1 list_typeclasses
# ===========================================================================

class TestListTypeclasses:
    """S4.1: list_typeclasses behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_typeclass_summaries(self):
        """Given 3 registered typeclasses, returns 3 TypeclassSummary records."""
        _, list_typeclasses, *_ = _import_debugging()
        _, TypeclassSummary, *_ = _import_types()

        manager = _make_mock_session_manager({
            "Print Typeclasses.": "Eq\nOrd\nShow",
            "Print Instances Eq.": "Eq_nat : Eq nat\nEq_bool : Eq bool",
            "Print Instances Ord.": "Ord_nat : Ord nat",
            "Print Instances Show.": "",
        })
        result = await list_typeclasses(
            session_id="abc123",
            session_manager=manager,
        )
        assert len(result) == 3
        assert all(isinstance(r, TypeclassSummary) for r in result)
        names = {r.typeclass_name for r in result}
        assert names == {"Eq", "Ord", "Show"}

    @pytest.mark.asyncio
    async def test_instance_count_populated(self):
        """Each record has instance_count from follow-up Print Instances."""
        _, list_typeclasses, *_ = _import_debugging()

        manager = _make_mock_session_manager({
            "Print Typeclasses.": "Eq\nOrd",
            "Print Instances Eq.": "Eq_nat : Eq nat\nEq_bool : Eq bool",
            "Print Instances Ord.": "Ord_nat : Ord nat",
        })
        result = await list_typeclasses(
            session_id="abc123",
            session_manager=manager,
        )
        counts = {r.typeclass_name: r.instance_count for r in result}
        assert counts["Eq"] == 2
        assert counts["Ord"] == 1

    @pytest.mark.asyncio
    async def test_over_200_typeclasses_null_count(self):
        """When > 200 typeclasses, instance_count is null for all."""
        _, list_typeclasses, *_ = _import_debugging()

        tc_names = "\n".join(f"TC_{i}" for i in range(500))
        manager = _make_mock_session_manager({
            "Print Typeclasses.": tc_names,
        })
        result = await list_typeclasses(
            session_id="abc123",
            session_manager=manager,
        )
        assert len(result) == 500
        for r in result:
            assert r.instance_count is None

    @pytest.mark.asyncio
    async def test_over_200_no_follow_up_calls(self):
        """When > 200 typeclasses, no Print Instances calls are made."""
        _, list_typeclasses, *_ = _import_debugging()

        tc_names = "\n".join(f"TC_{i}" for i in range(201))
        manager = _make_mock_session_manager({
            "Print Typeclasses.": tc_names,
        })
        await list_typeclasses(
            session_id="abc123",
            session_manager=manager,
        )
        # Only Print Typeclasses should be called, not any Print Instances
        for call in manager.send_command.call_args_list:
            cmd = call[0][1] if len(call[0]) > 1 else call[1].get("command", "")
            assert "Print Instances" not in cmd



# ===========================================================================
# 3. Resolution Tracing -- S4.2
# ===========================================================================

class TestTraceResolution:
    """S4.2: trace_resolution behavioral requirements."""

    @pytest.mark.asyncio
    async def test_successful_resolution_returns_trace(self):
        """Given a goal with typeclass resolution, returns ResolutionTrace with succeeded=true."""
        _, _, trace_resolution, *_ = _import_debugging()
        _, _, ResolutionTrace, *_ = _import_types()

        debug_output = (
            "1: looking for Decidable (eq_nat 3 4)\n"
            "  1.1: trying Decidable_eq_nat -- success\n"
        )
        manager = _make_mock_session_manager({
            "Set Typeclasses Debug Verbosity 2.": "",
            "Unset Typeclasses Debug.": "",
        })
        # The trace_resolution captures debug output during goal resolution re-trigger
        manager.send_command.side_effect = None
        call_count = 0

        async def _execute(session_id, command, *, prefer_coqtop=False):
            nonlocal call_count
            call_count += 1
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            # The re-trigger command captures debug output
            return debug_output

        manager.send_command.side_effect = _execute

        result = await trace_resolution(
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, ResolutionTrace)
        assert result.succeeded is True

    @pytest.mark.asyncio
    async def test_no_typeclass_goal_error(self):
        """Given a goal without typeclass resolution, returns NO_TYPECLASS_GOAL error."""
        _, _, trace_resolution, *_ = _import_debugging()

        async def _execute(session_id, command, *, prefer_coqtop=False):
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            # No typeclass debug output -- goal doesn't involve typeclasses
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        with pytest.raises(Exception) as exc_info:
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        assert "NO_TYPECLASS_GOAL" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NO_TYPECLASS_GOAL"
        )

    @pytest.mark.asyncio
    async def test_no_typeclass_goal_includes_goal_text(self):
        """Given a goal with resolved typeclass methods, NO_TYPECLASS_GOAL includes goal text (S4.2, S7.2)."""
        _, _, trace_resolution, *_ = _import_debugging()

        from Poule.session.types import Goal, ProofState

        goal_text = "measure (l1 ++ l2) = measure l1 + measure l2"

        call_count = {"n": 0}

        async def _execute(session_id, command, *, prefer_coqtop=False):
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            # typeclasses eauto produces no output on non-typeclass goal
            return ""

        manager = AsyncMock()
        manager.send_command.side_effect = _execute
        manager.observe_proof_state.return_value = ProofState(
            schema_version=1,
            session_id="abc123",
            step_index=0,
            is_complete=False,
            focused_goal_index=0,
            goals=[Goal(index=0, type=goal_text)],
        )

        with pytest.raises(Exception) as exc_info:
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        err = exc_info.value
        assert hasattr(err, "code") and err.code == "NO_TYPECLASS_GOAL"
        # Error message must include the goal text per S7.2
        assert goal_text in err.message

    @pytest.mark.asyncio
    async def test_backend_crash_error(self):
        """Given a backend crash during debug capture, returns BACKEND_CRASHED."""
        _, _, trace_resolution, *_ = _import_debugging()
        BACKEND_CRASHED, _, SessionError = _import_session_errors()

        call_count = 0

        async def _execute(session_id, command, *, prefer_coqtop=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""  # Set Debug succeeds
            raise SessionError(BACKEND_CRASHED, "backend crashed")

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        with pytest.raises(SessionError) as exc_info:
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_debug_flag_cleanup_on_success(self):
        """MAINTAINS: Unset Typeclasses Debug is always sent after operation."""
        _, _, trace_resolution, *_ = _import_debugging()

        commands_sent = []

        async def _execute(session_id, command, *, prefer_coqtop=False):
            commands_sent.append(command)
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            return "1: looking for Eq nat\n  1.1: trying Eq_nat -- success\n"

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        await trace_resolution(
            session_id="abc123",
            session_manager=manager,
        )
        unset_commands = [c for c in commands_sent if "Unset Typeclasses Debug" in c]
        assert len(unset_commands) >= 1

    @pytest.mark.asyncio
    async def test_debug_flag_cleanup_on_error(self):
        """S7.4: Debug flag cleanup even when error occurs mid-operation."""
        _, _, trace_resolution, *_ = _import_debugging()

        commands_sent = []
        call_count = 0

        async def _execute(session_id, command, *, prefer_coqtop=False):
            nonlocal call_count
            commands_sent.append(command)
            call_count += 1
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            # Simulate a timeout on the re-trigger command
            raise asyncio.TimeoutError()

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        with pytest.raises(Exception):
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        # Unset must have been sent despite the error
        unset_commands = [c for c in commands_sent if "Unset Typeclasses Debug" in c]
        assert len(unset_commands) >= 1

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """S7.3: Command timeout returns TIMEOUT error after cleanup."""
        _, _, trace_resolution, *_ = _import_debugging()

        async def _execute(session_id, command, *, prefer_coqtop=False):
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            raise asyncio.TimeoutError()

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        with pytest.raises(Exception) as exc_info:
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        assert "TIMEOUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "TIMEOUT"
        )



# ===========================================================================
# 4. Debug Output Parsing -- S4.3
# ===========================================================================

class TestTraceParser:
    """S4.3: Debug output parsing requirements."""

    def test_three_level_tree_structure(self):
        """Given 3 levels of indentation, parser produces tree with depth up to 3."""
        TraceParser = _import_parser()
        _, _, _, ResolutionNode, *_ = _import_types()

        debug_output = (
            "1: looking for Eq (nat * bool)\n"
            "  1.1: trying Eq_prod\n"
            "    1.1.1: looking for Eq nat\n"
            "      1.1.1.1: trying Eq_nat -- success\n"
            "    1.1.2: looking for Eq bool\n"
            "      1.1.2.1: trying Eq_bool -- success\n"
            "  1.1: Eq_prod -- success\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        # Root node should have children
        root = nodes[0]
        assert isinstance(root, ResolutionNode)
        assert root.outcome == "success"
        # Tree should have depth up to 3 (root=0, children=1, grandchildren=2)
        max_depth = _max_depth(root)
        assert max_depth >= 2  # At least depth 0, 1, 2

    def test_success_outcome_on_leaf(self):
        """Leaf nodes with success pattern have outcome='success'."""
        TraceParser = _import_parser()

        debug_output = (
            "1: looking for Eq nat\n"
            "  1.1: trying Eq_nat -- success\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        # Find the leaf node
        leaf = _find_leaf(nodes[0])
        assert leaf.outcome == "success"

    def test_unification_failure_outcome(self):
        """Lines matching failure pattern set outcome to unification_failure."""
        TraceParser = _import_parser()

        debug_output = (
            "1: looking for Eq string\n"
            "  1.1: trying Eq_nat -- failed (unification)\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        leaf = _find_leaf(nodes[0])
        assert leaf.outcome in ("unification_failure", "subgoal_failure")

    def test_depth_exceeded_outcome(self):
        """Lines matching depth-limit pattern set outcome to depth_exceeded."""
        TraceParser = _import_parser()

        debug_output = (
            "1: looking for Monad M\n"
            "  1.1: trying Monad_from_Applicative\n"
            "    depth limit exceeded\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        has_depth_exceeded = _has_outcome(nodes[0], "depth_exceeded")
        assert has_depth_exceeded

    def test_unrecognized_line_preserved_as_raw_text(self):
        """Unrecognized lines are preserved as raw text, no parse error raised."""
        TraceParser = _import_parser()

        debug_output = (
            "1: looking for Eq nat\n"
            "  some unrecognized debug line format\n"
            "  1.1: trying Eq_nat -- success\n"
        )
        parser = TraceParser()
        # Should not raise
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        # The unrecognized line should be preserved somewhere
        root = nodes[0]
        assert (
            root.failure_detail is not None
            and "unrecognized" in root.failure_detail
        ) or _has_raw_text(root, "unrecognized")

    def test_indentation_unit_detection(self):
        """Parser detects indentation unit from first indented line."""
        TraceParser = _import_parser()

        # Use 4-space indentation
        debug_output = (
            "1: looking for Eq nat\n"
            "    1.1: trying Eq_nat -- success\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        # Child should be at depth 1, not depth 4
        if nodes[0].children:
            assert nodes[0].children[0].depth == 1

    def test_child_at_deeper_depth(self):
        """S4.3 rule 7: Line at depth N+1 following depth N becomes a child."""
        TraceParser = _import_parser()

        debug_output = (
            "1: looking for Eq nat\n"
            "  1.1: trying Eq_nat\n"
            "    1.1.1: looking for sub_goal -- success\n"
        )
        parser = TraceParser()
        nodes = parser.parse(debug_output)
        assert len(nodes) >= 1
        root = nodes[0]
        assert len(root.children) >= 1
        child = root.children[0]
        assert len(child.children) >= 1

    def test_empty_input_returns_empty_list(self):
        """Empty debug output produces empty node list."""
        TraceParser = _import_parser()
        parser = TraceParser()
        nodes = parser.parse("")
        assert nodes == []


# Parser test helpers

def _max_depth(node) -> int:
    """Compute maximum depth in the tree rooted at node."""
    if not node.children:
        return node.depth
    return max(_max_depth(c) for c in node.children)


def _find_leaf(node):
    """Find first leaf node in tree."""
    if not node.children:
        return node
    return _find_leaf(node.children[0])


def _has_outcome(node, outcome: str) -> bool:
    """Check if any node in tree has the given outcome."""
    if node.outcome == outcome:
        return True
    return any(_has_outcome(c, outcome) for c in node.children)


def _has_raw_text(node, text: str) -> bool:
    """Check if any node contains the given text in failure_detail."""
    if node.failure_detail and text in node.failure_detail:
        return True
    return any(_has_raw_text(c, text) for c in node.children)


# ===========================================================================
# 5. Failure Explanation -- S4.4
# ===========================================================================

class TestExplainFailure:
    """S4.4: explain_failure behavioral requirements."""

    def test_no_instance_failure(self):
        """Given root with zero children, returns no_instance failure mode."""
        _, _, _, explain_failure, *_ = _import_debugging()
        _, _, _, _, FailureExplanation, *_ = _import_types()

        trace = _make_resolution_trace(
            goal="Show (list (list nat))",
            root_nodes=[],  # Zero children => no instance tried
            succeeded=False,
            failure_mode="no_instance",
            raw_output="",
        )
        result = explain_failure(trace)
        assert isinstance(result, FailureExplanation)
        assert result.failure_mode == "no_instance"
        assert result.typeclass == "Show"
        assert "list (list nat)" in result.type_arguments

    def test_unification_failure_closest_match(self):
        """Given multiple failed instances, returns the closest match."""
        _, _, _, explain_failure, *_ = _import_debugging()
        _, _, _, _, FailureExplanation, *_ = _import_types()

        eq_nat_node = _make_resolution_node(
            instance_name="Eq_nat",
            goal="Eq (nat * string)",
            outcome="unification_failure",
            failure_detail="unified 2 of 3 args; mismatch at arg 3: expected nat, got string",
            depth=0,
        )
        eq_bool_node = _make_resolution_node(
            instance_name="Eq_bool",
            goal="Eq (nat * string)",
            outcome="unification_failure",
            failure_detail="unified 0 of 3 args; mismatch at arg 1: expected bool, got nat",
            depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq (nat * string)",
            root_nodes=[eq_nat_node, eq_bool_node],
            succeeded=False,
            failure_mode="unification",
            raw_output="",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "unification"
        assert result.closest_instance == "Eq_nat"
        assert result.successful_unifications == 2

    def test_depth_exceeded_with_cycle(self):
        """Given a trace with depth-limit node and cycle, detects cycle."""
        _, _, _, explain_failure, *_ = _import_debugging()
        _, _, _, _, FailureExplanation, *_ = _import_types()

        # Build a deep chain: Monad -> Applicative -> Functor -> Applicative -> ...
        functor_node = _make_resolution_node(
            instance_name="Functor_default",
            goal="Functor F",
            outcome="depth_exceeded",
            depth=4,
        )
        applicative_node2 = _make_resolution_node(
            instance_name="Applicative_default",
            goal="Applicative F",
            outcome="depth_exceeded",
            children=[functor_node],
            depth=3,
        )
        functor_node_first = _make_resolution_node(
            instance_name="Functor_from_Applicative",
            goal="Functor F",
            outcome="depth_exceeded",
            children=[applicative_node2],
            depth=2,
        )
        applicative_node = _make_resolution_node(
            instance_name="Applicative_from_Monad",
            goal="Applicative F",
            outcome="depth_exceeded",
            children=[functor_node_first],
            depth=1,
        )
        monad_node = _make_resolution_node(
            instance_name="Monad_default",
            goal="Monad F",
            outcome="depth_exceeded",
            children=[applicative_node],
            depth=0,
        )
        trace = _make_resolution_trace(
            goal="Monad F",
            root_nodes=[monad_node],
            succeeded=False,
            failure_mode="depth_exceeded",
            raw_output="",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "depth_exceeded"
        assert result.cycle_detected is True
        assert "Applicative" in result.cycle_typeclasses
        assert "Functor" in result.cycle_typeclasses
        assert result.resolution_path is not None
        assert len(result.resolution_path) >= 3

    def test_depth_exceeded_no_cycle(self):
        """Given depth exceeded without repeated typeclasses, no cycle detected."""
        _, _, _, explain_failure, *_ = _import_debugging()

        node_c = _make_resolution_node(
            instance_name="C_default", goal="C x", outcome="depth_exceeded", depth=2,
        )
        node_b = _make_resolution_node(
            instance_name="B_default", goal="B x", outcome="depth_exceeded",
            children=[node_c], depth=1,
        )
        node_a = _make_resolution_node(
            instance_name="A_default", goal="A x", outcome="depth_exceeded",
            children=[node_b], depth=0,
        )
        trace = _make_resolution_trace(
            goal="A x",
            root_nodes=[node_a],
            succeeded=False,
            failure_mode="depth_exceeded",
            raw_output="",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "depth_exceeded"
        assert result.cycle_detected is False
        assert result.cycle_typeclasses == []

    def test_unclassified_fallback(self):
        """Given empty/malformed trace, returns unclassified with raw output."""
        _, _, _, explain_failure, *_ = _import_debugging()

        trace = _make_resolution_trace(
            goal="?",
            root_nodes=[],
            succeeded=False,
            failure_mode=None,
            raw_output="some garbage output",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "unclassified"
        assert result.raw_output is not None
        assert "some garbage output" in result.raw_output

    def test_no_instance_goal_context(self):
        """No-instance explanation includes goal_context (hypotheses)."""
        _, _, _, explain_failure, *_ = _import_debugging()

        # Root node with zero children to trigger no_instance
        root = _make_resolution_node(
            instance_name="",
            goal="Show (list (list nat))",
            outcome="subgoal_failure",
            children=[],
            depth=0,
        )
        trace = _make_resolution_trace(
            goal="Show (list (list nat))",
            root_nodes=[root],
            succeeded=False,
            failure_mode="no_instance",
            raw_output="H : Show nat\n",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "no_instance"
        assert result.goal_context is not None

    def test_unification_mismatch_fields(self):
        """Unification failure includes mismatch_expected and mismatch_actual."""
        _, _, _, explain_failure, *_ = _import_debugging()

        node = _make_resolution_node(
            instance_name="Eq_nat",
            goal="Eq (nat * string)",
            outcome="unification_failure",
            failure_detail="expected nat, got string",
            depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq (nat * string)",
            root_nodes=[node],
            succeeded=False,
            failure_mode="unification",
            raw_output="",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "unification"
        assert result.mismatch_expected is not None
        assert result.mismatch_actual is not None


# ===========================================================================
# 6. Conflict Detection -- S4.5
# ===========================================================================

class TestDetectConflicts:
    """S4.5: detect_conflicts behavioral requirements."""

    def test_two_successful_instances_conflict(self):
        """Given two successful root children, returns one InstanceConflict."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()
        _, _, _, _, _, InstanceConflict, *_ = _import_types()

        node1 = _make_resolution_node(
            instance_name="Eq_nat_stdlib", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="Eq_nat_custom", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2],
            succeeded=True,
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert len(result) == 1
        conflict = result[0]
        assert isinstance(conflict, InstanceConflict)
        assert "Eq_nat_stdlib" in conflict.matching_instances
        assert "Eq_nat_custom" in conflict.matching_instances
        assert conflict.selected_instance in conflict.matching_instances
        assert conflict.goal == "Eq nat"

    def test_one_successful_instance_no_conflict(self):
        """Given exactly one successful instance, returns empty list."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()

        node1 = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="Eq_bool", goal="Eq nat", outcome="unification_failure", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2],
            succeeded=True,
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert result == []

    def test_zero_successful_instances_no_conflict(self):
        """Given zero successful instances, returns empty list."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()

        node = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="unification_failure", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node],
            succeeded=False,
            failure_mode="unification",
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert result == []

    def test_conflict_selection_basis(self):
        """InstanceConflict includes selection_basis field."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()
        _, _, _, _, _, InstanceConflict, *_ = _import_types()

        node1 = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="Eq_nat_fast", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2],
            succeeded=True,
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert len(result) == 1
        assert result[0].selection_basis in (
            "declaration_order", "priority_hint", "specificity"
        )

    def test_conflict_matching_instances_at_least_two(self):
        """InstanceConflict.matching_instances has at least 2 entries."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()

        node1 = _make_resolution_node(
            instance_name="A", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="B", goal="Eq nat", outcome="success", depth=0,
        )
        node3 = _make_resolution_node(
            instance_name="C", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2, node3],
            succeeded=True,
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert len(result) >= 1
        for conflict in result:
            assert len(conflict.matching_instances) >= 2


# ===========================================================================
# 7. Explain Instance -- S4.5
# ===========================================================================

class TestExplainInstance:
    """S4.5: explain_instance behavioral requirements."""

    def test_instance_succeeded_and_selected(self):
        """Given instance succeeded and was selected, reports selected status."""
        *_, explain_instance = _import_debugging()
        _, _, _, _, _, _, InstanceExplanation = _import_types()

        node = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node],
            succeeded=True,
            raw_output="",
        )
        result = explain_instance(trace, "Eq_nat")
        assert isinstance(result, InstanceExplanation)
        assert result.instance_name == "Eq_nat"
        assert result.status == "selected"

    def test_instance_succeeded_but_overridden(self):
        """Given instance succeeded but was overridden, reports overridden status."""
        *_, explain_instance = _import_debugging()
        _, _, _, _, _, _, InstanceExplanation = _import_types()

        node1 = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="Eq_nat_fast", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2],
            succeeded=True,
            raw_output="",
        )
        result = explain_instance(trace, "Eq_nat")
        assert result.status == "succeeded_overridden"
        assert result.overridden_by is not None

    def test_instance_failed(self):
        """Given instance was tried and failed, reports failure reason."""
        *_, explain_instance = _import_debugging()
        _, _, _, _, _, _, InstanceExplanation = _import_types()

        node = _make_resolution_node(
            instance_name="Eq_nat",
            goal="Eq string",
            outcome="unification_failure",
            failure_detail="type mismatch: expected nat, got string",
            depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq string",
            root_nodes=[node],
            succeeded=False,
            failure_mode="unification",
            raw_output="",
        )
        result = explain_instance(trace, "Eq_nat")
        assert result.status == "failed"
        assert result.failure_reason is not None

    def test_instance_not_considered(self):
        """Given instance not in trace, reports not_considered status."""
        *_, explain_instance = _import_debugging()
        _, _, _, _, _, _, InstanceExplanation = _import_types()

        node = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node],
            succeeded=True,
            raw_output="",
        )
        result = explain_instance(trace, "Eq_string")
        assert result.status == "not_considered"
        assert result.not_considered_reason is not None

    def test_empty_instance_name_returns_invalid_input(self):
        """S7.1: Empty instance_name returns INVALID_INPUT error."""
        *_, explain_instance = _import_debugging()

        trace = _make_resolution_trace(goal="Eq nat", succeeded=True, raw_output="")
        with pytest.raises(Exception) as exc_info:
            explain_instance(trace, "")
        assert "INVALID_INPUT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_INPUT"
        )

    def test_overridden_by_null_when_not_overridden(self):
        """InstanceExplanation.overridden_by is null when status != succeeded_overridden."""
        *_, explain_instance = _import_debugging()

        node = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat", root_nodes=[node], succeeded=True, raw_output="",
        )
        result = explain_instance(trace, "Eq_nat")
        assert result.status == "selected"
        assert result.overridden_by is None

    def test_failure_reason_null_when_not_failed(self):
        """InstanceExplanation.failure_reason is null when status != failed."""
        *_, explain_instance = _import_debugging()

        node = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat", root_nodes=[node], succeeded=True, raw_output="",
        )
        result = explain_instance(trace, "Eq_nat")
        assert result.failure_reason is None


# ===========================================================================
# 8. Data Model -- S5
# ===========================================================================

class TestDataModel:
    """S5: Data model constraints."""

    def test_typeclass_info_required_fields(self):
        """TypeclassInfo has instance_name, typeclass_name, type_signature, defining_module."""
        TypeclassInfo, *_ = _import_types()
        info = TypeclassInfo(
            instance_name="Eq_nat",
            typeclass_name="Eq",
            type_signature="Eq nat",
            defining_module="Stdlib.Classes",
        )
        assert info.instance_name == "Eq_nat"
        assert info.typeclass_name == "Eq"
        assert info.type_signature == "Eq nat"
        assert info.defining_module == "Stdlib.Classes"

    def test_typeclass_summary_nullable_count(self):
        """TypeclassSummary.instance_count can be null."""
        _, TypeclassSummary, *_ = _import_types()
        summary = TypeclassSummary(
            typeclass_name="Eq",
            instance_count=None,
        )
        assert summary.instance_count is None

    def test_resolution_trace_fields(self):
        """ResolutionTrace has goal, root_nodes, succeeded, failure_mode, raw_output."""
        _, _, ResolutionTrace, *_ = _import_types()
        trace = ResolutionTrace(
            goal="Eq nat",
            root_nodes=[],
            succeeded=True,
            failure_mode=None,
            raw_output="raw",
        )
        assert trace.goal == "Eq nat"
        assert trace.root_nodes == []
        assert trace.succeeded is True
        assert trace.failure_mode is None
        assert trace.raw_output == "raw"

    def test_resolution_trace_failure_mode_null_when_succeeded(self):
        """failure_mode is null when succeeded is true."""
        trace = _make_resolution_trace(succeeded=True, failure_mode=None)
        assert trace.failure_mode is None

    def test_resolution_node_required_fields(self):
        """ResolutionNode has all required fields."""
        _, _, _, ResolutionNode, *_ = _import_types()
        node = ResolutionNode(
            instance_name="Eq_nat",
            goal="Eq nat",
            outcome="success",
            failure_detail=None,
            children=[],
            depth=0,
        )
        assert node.instance_name == "Eq_nat"
        assert node.goal == "Eq nat"
        assert node.outcome == "success"
        assert node.failure_detail is None
        assert node.children == []
        assert node.depth == 0

    def test_resolution_node_failure_detail_null_on_success(self):
        """failure_detail is null when outcome is success."""
        node = _make_resolution_node(outcome="success", failure_detail=None)
        assert node.failure_detail is None

    def test_resolution_node_valid_outcomes(self):
        """outcome must be one of the four specified values."""
        valid_outcomes = {"success", "unification_failure", "subgoal_failure", "depth_exceeded"}
        for outcome in valid_outcomes:
            node = _make_resolution_node(outcome=outcome)
            assert node.outcome in valid_outcomes

    def test_failure_explanation_required_fields_no_instance(self):
        """FailureExplanation for no_instance has typeclass, type_arguments, goal_context."""
        _, _, _, _, FailureExplanation, *_ = _import_types()
        exp = FailureExplanation(
            failure_mode="no_instance",
            typeclass="Show",
            type_arguments=["list (list nat)"],
            goal_context=["H : Show nat"],
            closest_instance=None,
            successful_unifications=None,
            mismatch_expected=None,
            mismatch_actual=None,
            resolution_path=None,
            cycle_detected=None,
            cycle_typeclasses=None,
            max_depth_reached=None,
            raw_output=None,
        )
        assert exp.typeclass == "Show"
        assert exp.type_arguments == ["list (list nat)"]
        assert exp.goal_context == ["H : Show nat"]

    def test_failure_explanation_required_fields_unification(self):
        """FailureExplanation for unification has closest_instance, counts, mismatch."""
        _, _, _, _, FailureExplanation, *_ = _import_types()
        exp = FailureExplanation(
            failure_mode="unification",
            typeclass=None,
            type_arguments=None,
            goal_context=None,
            closest_instance="Eq_nat",
            successful_unifications=2,
            mismatch_expected="nat",
            mismatch_actual="string",
            resolution_path=None,
            cycle_detected=None,
            cycle_typeclasses=None,
            max_depth_reached=None,
            raw_output=None,
        )
        assert exp.closest_instance == "Eq_nat"
        assert exp.successful_unifications == 2
        assert exp.mismatch_expected == "nat"
        assert exp.mismatch_actual == "string"

    def test_failure_explanation_required_fields_depth_exceeded(self):
        """FailureExplanation for depth_exceeded has path, cycle, max_depth."""
        _, _, _, _, FailureExplanation, *_ = _import_types()
        exp = FailureExplanation(
            failure_mode="depth_exceeded",
            typeclass=None,
            type_arguments=None,
            goal_context=None,
            closest_instance=None,
            successful_unifications=None,
            mismatch_expected=None,
            mismatch_actual=None,
            resolution_path=["Monad", "Applicative", "Functor"],
            cycle_detected=True,
            cycle_typeclasses=["Applicative", "Functor"],
            max_depth_reached=100,
            raw_output=None,
        )
        assert exp.resolution_path == ["Monad", "Applicative", "Functor"]
        assert exp.cycle_detected is True
        assert exp.cycle_typeclasses == ["Applicative", "Functor"]
        assert exp.max_depth_reached == 100

    def test_instance_conflict_required_fields(self):
        """InstanceConflict has goal, matching_instances (>=2), selected_instance, selection_basis."""
        _, _, _, _, _, InstanceConflict, *_ = _import_types()
        conflict = InstanceConflict(
            goal="Eq nat",
            matching_instances=["Eq_nat", "Eq_nat_fast"],
            selected_instance="Eq_nat_fast",
            selection_basis="priority_hint",
        )
        assert conflict.goal == "Eq nat"
        assert len(conflict.matching_instances) >= 2
        assert conflict.selected_instance in conflict.matching_instances
        assert conflict.selection_basis in (
            "declaration_order", "priority_hint", "specificity"
        )

    def test_instance_explanation_required_fields(self):
        """InstanceExplanation has instance_name, status, and conditional fields."""
        _, _, _, _, _, _, InstanceExplanation = _import_types()
        exp = InstanceExplanation(
            instance_name="Eq_nat",
            status="selected",
            overridden_by=None,
            failure_reason=None,
            not_considered_reason=None,
        )
        assert exp.instance_name == "Eq_nat"
        assert exp.status == "selected"

    def test_instance_explanation_valid_statuses(self):
        """status must be one of the four specified values."""
        _, _, _, _, _, _, InstanceExplanation = _import_types()
        valid = {"selected", "succeeded_overridden", "failed", "not_considered"}
        for status in valid:
            exp = InstanceExplanation(
                instance_name="test",
                status=status,
                overridden_by="other" if status == "succeeded_overridden" else None,
                failure_reason="reason" if status == "failed" else None,
                not_considered_reason="reason" if status == "not_considered" else None,
            )
            assert exp.status in valid


# ===========================================================================
# 9. Error Specification -- S7
# ===========================================================================

class TestErrorSpecification:
    """S7: Error specification requirements."""

    @pytest.mark.asyncio
    async def test_not_found_typeclass(self):
        """S7.1: Typeclass not found returns NOT_FOUND error."""
        list_instances, *_ = _import_debugging()

        manager = _make_mock_session_manager({
            "Print Instances UnknownClass.": "Error: UnknownClass not found.",
        })
        with pytest.raises(Exception) as exc_info:
            await list_instances(
                session_id="abc123",
                typeclass_name="UnknownClass",
                session_manager=manager,
            )
        err_str = str(exc_info.value)
        assert "NOT_FOUND" in err_str or "NOT_A_TYPECLASS" in err_str or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code in ("NOT_FOUND", "NOT_A_TYPECLASS")
        )

    @pytest.mark.asyncio
    async def test_parse_error_includes_raw_output(self):
        """S7.3: Parse error includes raw output for LLM interpretation."""
        _, _, trace_resolution, *_ = _import_debugging()

        async def _execute(session_id, command, *, prefer_coqtop=False):
            if "Set Typeclasses Debug Verbosity 2" in command:
                return ""
            if "Unset Typeclasses Debug" in command:
                return ""
            # Return completely unparseable output
            return "\x00\x01\x02 binary garbage"

        manager = AsyncMock()
        manager.send_command.side_effect = _execute

        with pytest.raises(Exception) as exc_info:
            await trace_resolution(
                session_id="abc123",
                session_manager=manager,
            )
        # Should be PARSE_ERROR or NO_TYPECLASS_GOAL with raw output
        err = exc_info.value
        assert (
            "PARSE_ERROR" in str(err)
            or "NO_TYPECLASS_GOAL" in str(err)
            or (hasattr(err, "code") and err.code in ("PARSE_ERROR", "NO_TYPECLASS_GOAL"))
        )


# ===========================================================================
# 10. Constants -- S10 (Language-Specific Notes)
# ===========================================================================

class TestConstants:
    """S10: Language-specific constants."""

    def test_max_typeclasses_threshold(self):
        """MAX_TYPECLASSES_FOR_INSTANCE_COUNT is 200."""
        MAX_TYPECLASSES, _ = _import_constants()
        assert MAX_TYPECLASSES == 200

    def test_command_timeout(self):
        """TYPECLASS_COMMAND_TIMEOUT_SECONDS is 5."""
        _, TIMEOUT = _import_constants()
        assert TIMEOUT == 5


# ===========================================================================
# 11. Spec Example -- S9
# ===========================================================================

class TestSpecExamples:
    """S9: Verify examples from the specification."""

    @pytest.mark.asyncio
    async def test_instance_listing_example(self):
        """Spec example: list_instances for Eq returns 3 records with correct fields."""
        list_instances, *_ = _import_debugging()
        TypeclassInfo, *_ = _import_types()

        manager = _make_mock_session_manager({
            "Print Instances Eq.": (
                "Eq_nat : Eq nat\n"
                "Eq_bool : Eq bool\n"
                "Eq_prod : forall A B, Eq A -> Eq B -> Eq (A * B)"
            ),
        })
        result = await list_instances(
            session_id="abc123",
            typeclass_name="Eq",
            session_manager=manager,
        )
        assert len(result) == 3
        names = [r.instance_name for r in result]
        assert "Eq_nat" in names
        assert "Eq_bool" in names
        assert "Eq_prod" in names

    def test_conflict_detection_example(self):
        """Spec example: detect_conflicts with Eq_nat and Eq_nat_fast."""
        _, _, _, _, detect_conflicts, *_ = _import_debugging()
        _, _, _, _, _, InstanceConflict, *_ = _import_types()

        node1 = _make_resolution_node(
            instance_name="Eq_nat", goal="Eq nat", outcome="success", depth=0,
        )
        node2 = _make_resolution_node(
            instance_name="Eq_nat_fast", goal="Eq nat", outcome="success", depth=0,
        )
        trace = _make_resolution_trace(
            goal="Eq nat",
            root_nodes=[node1, node2],
            succeeded=True,
            raw_output="",
        )
        result = detect_conflicts(trace)
        assert len(result) == 1
        conflict = result[0]
        assert set(conflict.matching_instances) == {"Eq_nat", "Eq_nat_fast"}

    def test_failure_explanation_no_instance_example(self):
        """Spec example: explain_failure for Show (list (list nat))."""
        _, _, _, explain_failure, *_ = _import_debugging()

        trace = _make_resolution_trace(
            goal="Show (list (list nat))",
            root_nodes=[],
            succeeded=False,
            failure_mode="no_instance",
            raw_output="",
        )
        result = explain_failure(trace)
        assert result.failure_mode == "no_instance"
        assert result.typeclass == "Show"
        assert result.closest_instance is None
        assert result.resolution_path is None
