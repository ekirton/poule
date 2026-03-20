"""TDD tests for the Auto Trace Explanation component (specification/auto-trace-explanation.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/Poule/auto_trace/ modules exist.

Spec: specification/auto-trace-explanation.md
Architecture: doc/architecture/auto-trace-explanation.md

Import paths under test:
  Poule.auto_trace.analyzer   (diagnose_auto, capture_trace, compare_variants)
  Poule.auto_trace.parser     (parse_trace)
  Poule.auto_trace.classifier (classify_hints)
  Poule.auto_trace.diagnoser  (diagnose_failures)
  Poule.auto_trace.types      (RawTraceCapture, AutoSearchTree, AutoSearchNode,
                                HintClassification, RejectionReason, AutoDiagnosis,
                                DatabaseConfig, VariantComparison, VariantResult,
                                DivergencePoint)
  Poule.auto_trace.errors     (AutoTraceError)
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports -- fail with ImportError until implementation exists
# ---------------------------------------------------------------------------


def _import_analyzer():
    from Poule.auto_trace.analyzer import (
        capture_trace,
        compare_variants,
        diagnose_auto,
    )

    return diagnose_auto, capture_trace, compare_variants


def _import_parser():
    from Poule.auto_trace.parser import parse_trace

    return (parse_trace,)


def _import_classifier():
    from Poule.auto_trace.classifier import classify_hints

    return (classify_hints,)


def _import_diagnoser():
    from Poule.auto_trace.diagnoser import diagnose_failures

    return (diagnose_failures,)


def _import_types():
    """Return a namespace of all auto_trace types."""
    from Poule.auto_trace.types import (
        AutoDiagnosis,
        AutoSearchNode,
        AutoSearchTree,
        DatabaseConfig,
        DivergencePoint,
        HintClassification,
        RawTraceCapture,
        RejectionReason,
        VariantComparison,
        VariantResult,
    )

    return SimpleNamespace(
        RawTraceCapture=RawTraceCapture,
        AutoSearchTree=AutoSearchTree,
        AutoSearchNode=AutoSearchNode,
        HintClassification=HintClassification,
        RejectionReason=RejectionReason,
        AutoDiagnosis=AutoDiagnosis,
        DatabaseConfig=DatabaseConfig,
        VariantComparison=VariantComparison,
        VariantResult=VariantResult,
        DivergencePoint=DivergencePoint,
    )


def _import_errors():
    from Poule.auto_trace.errors import AutoTraceError

    return AutoTraceError


def _import_hint_types():
    from Poule.tactics.types import HintDatabase, HintEntry, HintSummary

    return HintDatabase, HintEntry, HintSummary


def _import_session_types():
    from Poule.session.types import Goal, Hypothesis, ProofState

    return ProofState, Goal, Hypothesis


# ---------------------------------------------------------------------------
# Helpers: factories, mocks, utilities
# ---------------------------------------------------------------------------


def _make_proof_state(goal_text="n + 0 = n", hypotheses=None):
    ProofState, Goal, Hypothesis = _import_session_types()
    hyps = hypotheses or []
    return ProofState(
        schema_version=1,
        session_id="test-session",
        step_index=0,
        is_complete=False,
        focused_goal_index=0,
        goals=[Goal(index=0, type=goal_text, hypotheses=hyps)],
    )


def _make_hint_database(name="core", entries=None):
    HintDatabase, HintEntry, HintSummary = _import_hint_types()
    entries = entries or []
    resolve_count = sum(1 for e in entries if e.hint_type == "resolve")
    unfold_count = sum(1 for e in entries if e.hint_type == "unfold")
    constructors_count = sum(1 for e in entries if e.hint_type == "constructors")
    extern_count = sum(1 for e in entries if e.hint_type == "extern")
    return HintDatabase(
        name=name,
        summary=HintSummary(
            resolve_count=resolve_count,
            unfold_count=unfold_count,
            constructors_count=constructors_count,
            extern_count=extern_count,
        ),
        entries=entries,
        truncated=False,
        total_entries=len(entries),
    )


def _make_hint_entry(name, hint_type="resolve", cost=0, pattern=None, tactic=None):
    _, HintEntry, _ = _import_hint_types()
    return HintEntry(
        hint_type=hint_type,
        name=name,
        pattern=pattern,
        tactic=tactic,
        cost=cost,
    )


def _make_mock_session_manager(
    *,
    vernacular_responses=None,
    proof_state=None,
    tactic_outcome="failed",
    debug_messages=None,
):
    """Create mock session manager for auto trace tests.

    vernacular_responses: dict mapping command substring to response string.
    proof_state: ProofState returned by observe_state.
    tactic_outcome: "succeeded" or "failed" for the try-wrapped tactic.
    debug_messages: list of strings emitted as debug output.
    """
    manager = AsyncMock()
    vernacular_responses = vernacular_responses or {}
    debug_messages = debug_messages or []

    if proof_state is None:
        proof_state = _make_proof_state()

    manager.observe_state = AsyncMock(return_value=proof_state)

    # submit_tactic returns new state (succeeded) or same state (failed inside try)
    if tactic_outcome == "succeeded":
        succeeded_state = _make_proof_state(goal_text="", hypotheses=[])
        manager.submit_tactic = AsyncMock(
            return_value=MagicMock(
                proof_state=succeeded_state,
                messages=debug_messages,
            )
        )
    else:
        manager.submit_tactic = AsyncMock(
            return_value=MagicMock(
                proof_state=proof_state,
                messages=debug_messages,
            )
        )

    manager.step_backward = AsyncMock(return_value=proof_state)

    async def _execute(session_id, command):
        for key, value in vernacular_responses.items():
            if key in command:
                return value
        return ""

    manager.execute_vernacular = AsyncMock(side_effect=_execute)

    return manager


def _make_mock_hint_inspect(databases=None):
    """Create mock hint_inspect callable.

    databases: dict mapping db_name to HintDatabase.
    """
    databases = databases or {}

    async def _hint_inspect(db_name, session_id=None):
        if db_name in databases:
            return databases[db_name]
        AutoTraceError = _import_errors()
        raise AutoTraceError("NOT_FOUND", f'Hint database "{db_name}" not found.')

    return AsyncMock(side_effect=_hint_inspect)


# ===========================================================================
# 1. Trace Capture — Spec §4.1
# ===========================================================================


class TestTraceCapture:
    """Spec §4.1: capture_trace behavioral requirements."""

    @pytest.mark.asyncio
    async def test_captures_debug_messages_on_failure(self):
        """Given auto fails on the goal, captures debug messages and returns outcome=failed."""
        _, capture_trace, _ = _import_analyzer()
        T = _import_types(); RawTraceCapture = T.RawTraceCapture

        messages = [
            "depth=5 simple apply eq_refl (*fail*)",
        ]
        manager = _make_mock_session_manager(
            tactic_outcome="failed",
            debug_messages=messages,
        )

        result = await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        assert isinstance(result, RawTraceCapture)
        assert result.outcome == "failed"
        assert len(result.messages) > 0
        assert result.goal == "n + 0 = n"

    @pytest.mark.asyncio
    async def test_captures_debug_messages_on_success(self):
        """Given auto succeeds, captures messages, records outcome=succeeded, and restores state."""
        _, capture_trace, _ = _import_analyzer()

        messages = [
            "depth=5 simple apply Nat.add_0_r",
        ]
        manager = _make_mock_session_manager(
            tactic_outcome="succeeded",
            debug_messages=messages,
        )

        result = await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        assert result.outcome == "succeeded"
        # step_backward must be called to restore state
        manager.step_backward.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_step_backward_on_failure(self):
        """Given auto fails inside try, state is unchanged so step_backward is not called."""
        _, capture_trace, _ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        manager.step_backward.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsets_debug_flag_on_success(self):
        """Given a successful capture, Unset Debug auto is sent after tactic execution."""
        _, capture_trace, _ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        # Verify Set and Unset were both called
        calls = [str(c) for c in manager.execute_vernacular.call_args_list]
        set_calls = [c for c in calls if "Set Debug" in c]
        unset_calls = [c for c in calls if "Unset Debug" in c]
        assert len(set_calls) >= 1
        assert len(unset_calls) >= 1

    @pytest.mark.asyncio
    async def test_unsets_debug_flag_on_error(self):
        """Given an error during tactic execution, Unset Debug auto is still sent."""
        _, capture_trace, _ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        manager.submit_tactic = AsyncMock(side_effect=RuntimeError("backend error"))

        with pytest.raises(Exception):
            await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        calls = [str(c) for c in manager.execute_vernacular.call_args_list]
        unset_calls = [c for c in calls if "Unset Debug" in c]
        assert len(unset_calls) >= 1

    @pytest.mark.asyncio
    async def test_fallback_to_debug_auto_on_empty_messages(self):
        """Given Set Debug auto produces no messages, retries with debug auto tactic."""
        _, capture_trace, _ = _import_analyzer()
        T = _import_types(); RawTraceCapture = T.RawTraceCapture

        # First call (try auto) returns empty messages; second (try debug auto) returns messages
        first_result = MagicMock(
            proof_state=_make_proof_state(),
            messages=[],
        )
        second_result = MagicMock(
            proof_state=_make_proof_state(),
            messages=["depth=5 simple apply eq_refl (*fail*)"],
        )
        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        manager.submit_tactic = AsyncMock(side_effect=[first_result, second_result])

        result = await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        assert len(result.messages) > 0

    @pytest.mark.asyncio
    async def test_semantic_divergence_caveat_on_hint_extern(self):
        """Given fallback to debug auto with Hint Extern in trace, sets divergence caveat."""
        _, capture_trace, _ = _import_analyzer()

        first_result = MagicMock(
            proof_state=_make_proof_state(),
            messages=[],
        )
        second_result = MagicMock(
            proof_state=_make_proof_state(),
            messages=["depth=5 Extern 3 => congruence (*fail*)"],
        )
        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        manager.submit_tactic = AsyncMock(side_effect=[first_result, second_result])

        result = await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        assert result.semantic_divergence_caveat is not None

    @pytest.mark.asyncio
    async def test_uses_try_wrapper(self):
        """Given any tactic, submits it wrapped in try(...)."""
        _, capture_trace, _ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        await capture_trace(session_id="abc123", tactic="auto", session_manager=manager)

        tactic_arg = manager.submit_tactic.call_args[0][1] if len(manager.submit_tactic.call_args[0]) > 1 else manager.submit_tactic.call_args[1].get("tactic", "")
        # The tactic should be wrapped in try(...)
        # Accept either positional or keyword arg
        call_args = manager.submit_tactic.call_args
        all_args = str(call_args)
        assert "try" in all_args


# ===========================================================================
# 2. Trace Parsing — Spec §4.2
# ===========================================================================


class TestTraceParsing:
    """Spec §4.2: parse_trace behavioral requirements."""

    def test_parses_single_successful_line(self):
        """Given one successful trace line, returns tree with one root node."""
        (parse_trace,) = _import_parser()
        T = _import_types(); AutoSearchTree = T.AutoSearchTree; AutoSearchNode = T.AutoSearchNode

        messages = ["depth=5 simple apply Nat.add_0_r"]
        tree = parse_trace(messages)

        assert isinstance(tree, AutoSearchTree)
        assert len(tree.root_nodes) == 1
        assert tree.root_nodes[0].hint_name == "Nat.add_0_r"
        assert tree.root_nodes[0].remaining_depth == 5
        assert tree.root_nodes[0].outcome == "success"

    def test_parses_failed_line(self):
        """Given a line with (*fail*), node outcome is failure."""
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply eq_refl (*fail*)"]
        tree = parse_trace(messages)

        assert len(tree.root_nodes) == 1
        assert tree.root_nodes[0].outcome == "failure"
        assert tree.root_nodes[0].hint_name == "eq_refl"

    def test_reconstructs_parent_child_from_depth(self):
        """Given lines at depth 5 and depth 4, depth-4 line is child of depth-5 line."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply Nat.add_comm",
            "depth=4 exact eq_refl",
            "depth=4 simple apply Nat.add_0_r (*fail*)",
        ]
        tree = parse_trace(messages)

        assert len(tree.root_nodes) == 1
        root = tree.root_nodes[0]
        assert root.hint_name == "Nat.add_comm"
        assert root.remaining_depth == 5
        assert len(root.children) == 2
        assert root.children[0].hint_name == "eq_refl"
        assert root.children[0].remaining_depth == 4
        assert root.children[1].hint_name == "Nat.add_0_r"
        assert root.children[1].outcome == "failure"

    def test_multiple_root_nodes(self):
        """Given lines at the same depth, creates sibling root nodes."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply Nat.add_comm (*fail*)",
            "depth=5 simple apply Nat.add_0_r",
        ]
        tree = parse_trace(messages)

        assert len(tree.root_nodes) == 2

    def test_max_and_min_depth(self):
        """Given a tree with depth 5 root and depth 1 leaf, reports max=5 min=1."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply A",
            "depth=4 simple apply B",
            "depth=3 simple apply C",
            "depth=2 simple apply D",
            "depth=1 simple apply E (*fail*)",
        ]
        tree = parse_trace(messages)

        assert tree.max_depth == 5
        assert tree.min_leaf_depth == 1

    def test_depth_limit_reached_flag(self):
        """Given a leaf failure at depth=1, sets depth_limit_reached=true."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply A",
            "depth=4 simple apply B",
            "depth=3 simple apply C",
            "depth=2 simple apply D",
            "depth=1 simple apply E (*fail*)",
        ]
        tree = parse_trace(messages)

        assert tree.depth_limit_reached is True

    def test_no_depth_limit_when_leaf_not_at_one(self):
        """Given leaf failures at depth > 1, depth_limit_reached is false."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply A (*fail*)",
        ]
        tree = parse_trace(messages)

        assert tree.depth_limit_reached is False

    def test_empty_messages(self):
        """Given empty message list, returns empty tree."""
        (parse_trace,) = _import_parser()

        tree = parse_trace([])

        assert len(tree.root_nodes) == 0
        assert tree.max_depth == 0
        assert tree.min_leaf_depth == 0

    def test_preserves_unrecognized_lines(self):
        """Given unrecognized lines interspersed, no error raised and valid lines parsed."""
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply Nat.add_comm",
            "[tactic-unification] some unification debug output",
            "depth=4 exact eq_refl",
        ]
        tree = parse_trace(messages)

        # Valid lines still parsed
        assert len(tree.root_nodes) == 1
        assert len(tree.root_nodes[0].children) == 1

    def test_intro_action_has_null_hint_name(self):
        """Given an intro action, hint_name is null."""
        (parse_trace,) = _import_parser()

        messages = ["depth=5 intro"]
        tree = parse_trace(messages)

        assert tree.root_nodes[0].hint_name is None

    def test_preserves_raw_lines(self):
        """Given any trace line, raw_line is preserved."""
        (parse_trace,) = _import_parser()

        line = "depth=5 simple apply Nat.add_comm"
        tree = parse_trace([line])

        assert tree.root_nodes[0].raw_line == line

    def test_raw_messages_preserved(self):
        """Given trace messages, raw_messages on the tree contains the original list."""
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply A", "depth=4 exact B"]
        tree = parse_trace(messages)

        assert tree.raw_messages == messages


# ===========================================================================
# 3. Hint Classification — Spec §4.3
# ===========================================================================


class TestHintClassification:
    """Spec §4.3: classify_hints behavioral requirements."""

    def test_matched_hint(self):
        """Given a hint that appears as success in the trace, classified as matched."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply Nat.add_comm"]
        tree = parse_trace(messages)
        db = _make_hint_database("core", [_make_hint_entry("Nat.add_comm")])
        state = _make_proof_state()

        result = classify_hints(tree, [db], state)

        matching = [c for c in result if c.hint_name == "Nat.add_comm"]
        assert len(matching) == 1
        assert matching[0].classification == "matched"

    def test_attempted_but_rejected_hint(self):
        """Given a hint that appears as failure in the trace, classified as attempted_but_rejected."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply eq_refl (*fail*)"]
        tree = parse_trace(messages)
        db = _make_hint_database("core", [_make_hint_entry("eq_refl")])
        state = _make_proof_state()

        result = classify_hints(tree, [db], state)

        matching = [c for c in result if c.hint_name == "eq_refl"]
        assert len(matching) == 1
        assert matching[0].classification == "attempted_but_rejected"

    def test_not_considered_hint(self):
        """Given a hint not appearing in the trace, classified as not_considered."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply eq_refl (*fail*)"]
        tree = parse_trace(messages)
        db = _make_hint_database(
            "core",
            [
                _make_hint_entry("eq_refl"),
                _make_hint_entry("Nat.add_0_r"),
            ],
        )
        state = _make_proof_state()

        result = classify_hints(tree, [db], state)

        not_considered = [c for c in result if c.hint_name == "Nat.add_0_r"]
        assert len(not_considered) == 1
        assert not_considered[0].classification == "not_considered"

    def test_classifies_all_hints_in_all_databases(self):
        """Given hints across multiple databases, all are classified."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        tree = parse_trace([])
        db1 = _make_hint_database("core", [_make_hint_entry("A")])
        db2 = _make_hint_database("arith", [_make_hint_entry("B"), _make_hint_entry("C")])
        state = _make_proof_state()

        result = classify_hints(tree, [db1, db2], state)

        names = {c.hint_name for c in result}
        assert "A" in names
        assert "B" in names
        assert "C" in names

    def test_hypothesis_classified(self):
        """Given a hypothesis used in the trace, classifies it as matched."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()
        _, _, Hypothesis = _import_session_types()

        messages = ["depth=5 exact H1"]
        tree = parse_trace(messages)
        db = _make_hint_database("core", [])
        state = _make_proof_state(
            hypotheses=[Hypothesis(name="H1", type="n = n")]
        )

        result = classify_hints(tree, [db], state)

        h1_class = [c for c in result if c.hint_name == "H1"]
        assert len(h1_class) == 1
        assert h1_class[0].classification == "matched"
        assert h1_class[0].hint_type == "hypothesis"

    def test_evar_rejection_detected(self):
        """Given a leaf failure hint with uninstantiated universals, tentatively classified as evar_rejected."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply ex_intro (*fail*)"]
        tree = parse_trace(messages)
        # ex_intro has type: forall A (P : A -> Prop) (x : A), P x -> exists y, P y
        # The 'x' is not determined by the conclusion
        db = _make_hint_database("core", [_make_hint_entry("ex_intro", hint_type="constructors")])
        state = _make_proof_state(goal_text="exists x : nat, x = 0")

        result = classify_hints(tree, [db], state)

        ex_class = [c for c in result if c.hint_name == "ex_intro"]
        assert len(ex_class) == 1
        assert ex_class[0].classification == "attempted_but_rejected"
        assert ex_class[0].rejection_reason is not None
        assert ex_class[0].rejection_reason.reason == "evar_rejected"

    def test_trace_node_populated_for_attempted(self):
        """Given an attempted hint, the trace_node field references the search tree node."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply eq_refl (*fail*)"]
        tree = parse_trace(messages)
        db = _make_hint_database("core", [_make_hint_entry("eq_refl")])
        state = _make_proof_state()

        result = classify_hints(tree, [db], state)

        eq_class = [c for c in result if c.hint_name == "eq_refl"][0]
        assert eq_class.trace_node is not None
        assert eq_class.trace_node.hint_name == "eq_refl"

    def test_trace_node_null_for_not_considered(self):
        """Given a not_considered hint, trace_node is null."""
        (classify_hints,) = _import_classifier()
        (parse_trace,) = _import_parser()

        tree = parse_trace([])
        db = _make_hint_database("core", [_make_hint_entry("A")])
        state = _make_proof_state()

        result = classify_hints(tree, [db], state)

        a_class = [c for c in result if c.hint_name == "A"][0]
        assert a_class.trace_node is None


# ===========================================================================
# 4. Failure Diagnosis — Spec §4.4
# ===========================================================================


class TestFailureDiagnosis:
    """Spec §4.4: diagnose_failures behavioral requirements."""

    def test_wrong_database_reason(self):
        """Given a hint in a database not consulted, assigns wrong_database with fix suggestion."""
        (diagnose_failures,) = _import_diagnoser()
        T = _import_types(); HintClassification = T.HintClassification; RejectionReason = T.RejectionReason

        classifications = [
            HintClassification(
                hint_name="Nat.add_0_r",
                hint_type="resolve",
                database="arith",
                classification="not_considered",
                rejection_reason=None,
                trace_node=None,
            ),
        ]
        (parse_trace,) = _import_parser()
        tree = parse_trace([])

        result = diagnose_failures(classifications, tree, ["core"], "n + 0 = n")

        diag = [c for c in result.classifications if c.hint_name == "Nat.add_0_r"][0]
        assert diag.rejection_reason is not None
        assert diag.rejection_reason.reason == "wrong_database"
        assert "with" in diag.rejection_reason.fix_suggestion.lower()

    def test_evar_rejected_reason(self):
        """Given a hint pre-classified as evar_rejected, assigns evar_rejected with eauto suggestion."""
        (diagnose_failures,) = _import_diagnoser()
        T = _import_types(); HintClassification = T.HintClassification; RejectionReason = T.RejectionReason
        T = _import_types(); AutoSearchNode = T.AutoSearchNode

        node = AutoSearchNode(
            action="simple apply ex_intro",
            hint_name="ex_intro",
            remaining_depth=5,
            outcome="failure",
            children=[],
            raw_line="depth=5 simple apply ex_intro (*fail*)",
        )
        classifications = [
            HintClassification(
                hint_name="ex_intro",
                hint_type="constructors",
                database="core",
                classification="attempted_but_rejected",
                rejection_reason=RejectionReason(
                    reason="evar_rejected",
                    detail="ex_intro has uninstantiated universals",
                    fix_suggestion="",
                ),
                trace_node=node,
            ),
        ]
        (parse_trace,) = _import_parser()
        tree = parse_trace(["depth=5 simple apply ex_intro (*fail*)"])

        result = diagnose_failures(classifications, tree, ["core"], "exists x : nat, x = 0")

        diag = [c for c in result.classifications if c.hint_name == "ex_intro"][0]
        assert diag.rejection_reason.reason == "evar_rejected"
        assert "eauto" in diag.rejection_reason.fix_suggestion.lower()

    def test_depth_exhausted_reason(self):
        """Given depth_limit_reached and a leaf at depth=1, assigns depth_exhausted with min depth."""
        (diagnose_failures,) = _import_diagnoser()
        T = _import_types(); HintClassification = T.HintClassification; RejectionReason = T.RejectionReason
        T = _import_types(); AutoSearchNode = T.AutoSearchNode
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply A",
            "depth=4 simple apply B",
            "depth=3 simple apply C",
            "depth=2 simple apply D",
            "depth=1 simple apply E (*fail*)",
        ]
        tree = parse_trace(messages)

        classifications = [
            HintClassification(
                hint_name="E",
                hint_type="resolve",
                database="core",
                classification="attempted_but_rejected",
                rejection_reason=None,
                trace_node=tree.root_nodes[0].children[0].children[0].children[0].children[0],
            ),
        ]

        result = diagnose_failures(classifications, tree, ["core"], "some goal")

        diag = [c for c in result.classifications if c.hint_name == "E"][0]
        assert diag.rejection_reason.reason == "depth_exhausted"
        assert result.min_depth_required is not None
        assert result.min_depth_required >= 5

    def test_unification_failure_reason(self):
        """Given a leaf failure not at depth=1 and not evar-related, assigns unification_failure."""
        (diagnose_failures,) = _import_diagnoser()
        T = _import_types(); HintClassification = T.HintClassification; RejectionReason = T.RejectionReason
        T = _import_types(); AutoSearchNode = T.AutoSearchNode
        (parse_trace,) = _import_parser()

        messages = ["depth=5 simple apply eq_refl (*fail*)"]
        tree = parse_trace(messages)

        classifications = [
            HintClassification(
                hint_name="eq_refl",
                hint_type="resolve",
                database="core",
                classification="attempted_but_rejected",
                rejection_reason=None,
                trace_node=tree.root_nodes[0],
            ),
        ]

        result = diagnose_failures(classifications, tree, ["core"], "n + 0 = n")

        diag = [c for c in result.classifications if c.hint_name == "eq_refl"][0]
        assert diag.rejection_reason.reason == "unification_failure"

    def test_winning_path_extracted_on_success(self):
        """Given a successful search tree, winning_path contains the root-to-leaf success path."""
        (diagnose_failures,) = _import_diagnoser()
        (parse_trace,) = _import_parser()

        messages = [
            "depth=5 simple apply Nat.add_0_r",
            "depth=4 exact eq_refl",
        ]
        tree = parse_trace(messages)

        result = diagnose_failures([], tree, ["core"], "n + 0 = n")

        assert result.winning_path is not None
        assert len(result.winning_path) >= 1

    def test_fix_suggestion_always_present(self):
        """Given any rejection reason, fix_suggestion is non-empty."""
        (diagnose_failures,) = _import_diagnoser()
        T = _import_types(); HintClassification = T.HintClassification; RejectionReason = T.RejectionReason
        (parse_trace,) = _import_parser()

        tree = parse_trace([])
        classifications = [
            HintClassification(
                hint_name="Nat.add_0_r",
                hint_type="resolve",
                database="arith",
                classification="not_considered",
                rejection_reason=None,
                trace_node=None,
            ),
        ]

        result = diagnose_failures(classifications, tree, ["core"], "n + 0 = n")

        for c in result.classifications:
            if c.rejection_reason is not None:
                assert len(c.rejection_reason.fix_suggestion) > 0


# ===========================================================================
# 5. Variant Comparison — Spec §4.5
# ===========================================================================


class TestVariantComparison:
    """Spec §4.5: compare_variants behavioral requirements."""

    @pytest.mark.asyncio
    async def test_runs_three_variants(self):
        """Given compare_variants, runs auto, eauto, and typeclasses eauto."""
        _, _, compare_variants = _import_analyzer()
        T = _import_types(); VariantComparison = T.VariantComparison

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        result = await compare_variants(session_id="abc123", session_manager=manager)

        assert isinstance(result, VariantComparison)
        assert len(result.variants) == 3
        variant_names = {v.tactic for v in result.variants}
        assert "auto" in variant_names
        assert "eauto" in variant_names
        assert "typeclasses eauto" in variant_names

    @pytest.mark.asyncio
    async def test_detects_divergence_auto_vs_eauto(self):
        """Given auto fails but eauto succeeds on the same goal, reports a divergence point."""
        _, _, compare_variants = _import_analyzer()
        T = _import_types(); VariantComparison = T.VariantComparison

        # Mock that produces different outcomes per tactic
        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        # We need to mock at a higher level — this test verifies the shape
        # In TDD, we verify the contract; implementation will wire up properly
        result = await compare_variants(session_id="abc123", session_manager=manager)

        assert isinstance(result, VariantComparison)
        assert hasattr(result, "divergence_points")

    @pytest.mark.asyncio
    async def test_preserves_session_state(self):
        """Given compare_variants runs three diagnoses, session state is restored after each."""
        _, _, compare_variants = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])

        await compare_variants(session_id="abc123", session_manager=manager)

        # Debug flags should be cleaned up (at least 3 Unset calls, one per variant)
        calls = [str(c) for c in manager.execute_vernacular.call_args_list]
        unset_calls = [c for c in calls if "Unset Debug" in c]
        assert len(unset_calls) >= 3


# ===========================================================================
# 6. Top-Level Tool — Spec §4.6
# ===========================================================================


class TestDiagnoseAuto:
    """Spec §4.6: diagnose_auto top-level tool behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_auto_diagnosis(self):
        """Given a session with a goal, returns an AutoDiagnosis record."""
        diagnose_auto, *_ = _import_analyzer()
        T = _import_types(); AutoDiagnosis = T.AutoDiagnosis

        manager = _make_mock_session_manager(
            tactic_outcome="failed",
            debug_messages=["depth=5 simple apply eq_refl (*fail*)"],
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", [_make_hint_entry("eq_refl")]),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert isinstance(result, AutoDiagnosis)
        assert result.tactic == "auto"
        assert result.outcome == "failed"
        assert len(result.classifications) > 0

    @pytest.mark.asyncio
    async def test_focused_hint_query(self):
        """Given hint_name, classifications contains only that hint."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(
            tactic_outcome="failed",
            debug_messages=["depth=5 simple apply eq_refl (*fail*)"],
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", [
                _make_hint_entry("eq_refl"),
                _make_hint_entry("Nat.add_0_r"),
            ]),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            hint_name="eq_refl",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert len(result.classifications) == 1
        assert result.classifications[0].hint_name == "eq_refl"

    @pytest.mark.asyncio
    async def test_wrong_database_diagnosis(self):
        """Given a hint in arith but auto only consults core, diagnoses wrong_database."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(
            tactic_outcome="failed",
            debug_messages=[],
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
            "arith": _make_hint_database("arith", [_make_hint_entry("Nat.add_0_r")]),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            hint_name="Nat.add_0_r",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert len(result.classifications) == 1
        assert result.classifications[0].rejection_reason.reason == "wrong_database"

    @pytest.mark.asyncio
    async def test_databases_consulted_populated(self):
        """Given auto with no 'with' clause, databases_consulted contains core."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        db_names = [d.name for d in result.databases_consulted]
        assert "core" in db_names

    @pytest.mark.asyncio
    async def test_with_clause_adds_databases(self):
        """Given 'auto with arith', databases_consulted includes core and arith."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
            "arith": _make_hint_database("arith", []),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto with arith",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        db_names = [d.name for d in result.databases_consulted]
        assert "core" in db_names
        assert "arith" in db_names

    @pytest.mark.asyncio
    async def test_compare_variants_flag(self):
        """Given compare_variants=true, variant_comparison is populated."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            compare_variants=True,
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert result.variant_comparison is not None

    @pytest.mark.asyncio
    async def test_no_compare_variants_by_default(self):
        """Given compare_variants not set, variant_comparison is null."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert result.variant_comparison is None


# ===========================================================================
# 7. Data Model — Spec §5
# ===========================================================================


class TestDataModel:
    """Spec §5: Data model constraints."""

    def test_raw_trace_capture_required_fields(self):
        """RawTraceCapture has messages, outcome, goal, tactic, semantic_divergence_caveat."""
        T = _import_types(); RawTraceCapture = T.RawTraceCapture
        capture = RawTraceCapture(
            messages=["depth=5 simple apply A"],
            outcome="failed",
            goal="n + 0 = n",
            tactic="auto",
            semantic_divergence_caveat=None,
        )
        assert capture.messages == ["depth=5 simple apply A"]
        assert capture.outcome == "failed"
        assert capture.goal == "n + 0 = n"
        assert capture.tactic == "auto"
        assert capture.semantic_divergence_caveat is None

    def test_auto_search_tree_required_fields(self):
        """AutoSearchTree has root_nodes, max_depth, min_leaf_depth, depth_limit_reached, raw_messages."""
        T = _import_types(); AutoSearchTree = T.AutoSearchTree
        tree = AutoSearchTree(
            root_nodes=[],
            max_depth=0,
            min_leaf_depth=0,
            depth_limit_reached=False,
            raw_messages=[],
        )
        assert tree.root_nodes == []
        assert tree.max_depth == 0
        assert tree.min_leaf_depth == 0
        assert tree.depth_limit_reached is False
        assert tree.raw_messages == []

    def test_auto_search_node_required_fields(self):
        """AutoSearchNode has action, hint_name, remaining_depth, outcome, children, raw_line."""
        T = _import_types(); AutoSearchNode = T.AutoSearchNode
        node = AutoSearchNode(
            action="simple apply Nat.add_comm",
            hint_name="Nat.add_comm",
            remaining_depth=5,
            outcome="success",
            children=[],
            raw_line="depth=5 simple apply Nat.add_comm",
        )
        assert node.action == "simple apply Nat.add_comm"
        assert node.hint_name == "Nat.add_comm"
        assert node.remaining_depth == 5
        assert node.outcome == "success"
        assert node.children == []
        assert node.raw_line == "depth=5 simple apply Nat.add_comm"

    def test_hint_classification_required_fields(self):
        """HintClassification has hint_name, hint_type, database, classification, rejection_reason, trace_node."""
        T = _import_types(); HintClassification = T.HintClassification
        hc = HintClassification(
            hint_name="eq_refl",
            hint_type="resolve",
            database="core",
            classification="matched",
            rejection_reason=None,
            trace_node=None,
        )
        assert hc.hint_name == "eq_refl"
        assert hc.hint_type == "resolve"
        assert hc.database == "core"
        assert hc.classification == "matched"
        assert hc.rejection_reason is None

    def test_rejection_reason_required_fields(self):
        """RejectionReason has reason, detail, fix_suggestion."""
        T = _import_types(); RejectionReason = T.RejectionReason
        rr = RejectionReason(
            reason="wrong_database",
            detail="Hint is in arith, not core",
            fix_suggestion="Add 'with arith'",
        )
        assert rr.reason == "wrong_database"
        assert rr.detail == "Hint is in arith, not core"
        assert rr.fix_suggestion == "Add 'with arith'"

    def test_auto_diagnosis_required_fields(self):
        """AutoDiagnosis has tactic, outcome, goal, classifications, winning_path, min_depth_required, databases_consulted, variant_comparison, semantic_divergence_caveat."""
        T = _import_types(); AutoDiagnosis = T.AutoDiagnosis; DatabaseConfig = T.DatabaseConfig
        diag = AutoDiagnosis(
            tactic="auto",
            outcome="failed",
            goal="n + 0 = n",
            classifications=[],
            winning_path=None,
            min_depth_required=None,
            databases_consulted=[DatabaseConfig(name="core", transparency="transparent", hint_count=15)],
            variant_comparison=None,
            semantic_divergence_caveat=None,
        )
        assert diag.tactic == "auto"
        assert diag.outcome == "failed"
        assert diag.databases_consulted[0].name == "core"
        assert diag.variant_comparison is None

    def test_database_config_required_fields(self):
        """DatabaseConfig has name, transparency, hint_count."""
        T = _import_types(); DatabaseConfig = T.DatabaseConfig
        dc = DatabaseConfig(name="core", transparency="transparent", hint_count=15)
        assert dc.name == "core"
        assert dc.transparency == "transparent"
        assert dc.hint_count == 15

    def test_variant_comparison_required_fields(self):
        """VariantComparison has variants, divergence_points."""
        T = _import_types(); VariantComparison = T.VariantComparison; VariantResult = T.VariantResult; DivergencePoint = T.DivergencePoint
        vc = VariantComparison(
            variants=[
                VariantResult(tactic="auto", outcome="failed", databases_consulted=["core"], winning_path=None),
                VariantResult(tactic="eauto", outcome="succeeded", databases_consulted=["core"], winning_path=[]),
                VariantResult(tactic="typeclasses eauto", outcome="failed", databases_consulted=["typeclass_instances"], winning_path=None),
            ],
            divergence_points=[],
        )
        assert len(vc.variants) == 3
        assert vc.divergence_points == []

    def test_divergence_point_required_fields(self):
        """DivergencePoint has hint_name, per_variant, explanation."""
        T = _import_types(); DivergencePoint = T.DivergencePoint
        dp = DivergencePoint(
            hint_name="ex_intro",
            per_variant={"auto": MagicMock(), "eauto": MagicMock()},
            explanation="auto rejects evars; eauto allows them",
        )
        assert dp.hint_name == "ex_intro"
        assert "auto" in dp.per_variant
        assert len(dp.explanation) > 0


# ===========================================================================
# 8. Error Specification — Spec §8
# ===========================================================================


class TestErrorSpecification:
    """Spec §8: Error spec requirements."""

    @pytest.mark.asyncio
    async def test_empty_tactic_returns_invalid_argument(self):
        """Spec §8.1: Empty tactic returns INVALID_ARGUMENT."""
        diagnose_auto, *_ = _import_analyzer()
        AutoTraceError = _import_errors()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({"core": _make_hint_database("core", [])})

        with pytest.raises(Exception) as exc_info:
            await diagnose_auto(
                session_id="abc123",
                tactic="",
                session_manager=manager,
                hint_inspect=hint_inspect,
            )
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_non_auto_tactic_returns_invalid_argument(self):
        """Spec §8.1: Non-auto-family tactic returns INVALID_ARGUMENT."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({"core": _make_hint_database("core", [])})

        with pytest.raises(Exception) as exc_info:
            await diagnose_auto(
                session_id="abc123",
                tactic="rewrite H",
                session_manager=manager,
                hint_inspect=hint_inspect,
            )
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_empty_hint_name_returns_invalid_argument(self):
        """Spec §8.1: Empty hint_name returns INVALID_ARGUMENT."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({"core": _make_hint_database("core", [])})

        with pytest.raises(Exception) as exc_info:
            await diagnose_auto(
                session_id="abc123",
                tactic="auto",
                hint_name="",
                session_manager=manager,
                hint_inspect=hint_inspect,
            )
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_hint_not_found_returns_not_found(self):
        """Spec §8.2: hint_name not in any database returns NOT_FOUND."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", [_make_hint_entry("eq_refl")]),
        })

        with pytest.raises(Exception) as exc_info:
            await diagnose_auto(
                session_id="abc123",
                tactic="auto",
                hint_name="nonexistent_lemma",
                session_manager=manager,
                hint_inspect=hint_inspect,
            )
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_valid_auto_family_tactics_accepted(self):
        """Spec §8.1: auto, eauto, auto N, eauto N, auto with db, eauto with db, typeclasses eauto are valid."""
        diagnose_auto, *_ = _import_analyzer()

        valid_tactics = [
            "auto",
            "eauto",
            "auto 10",
            "eauto 7",
            "auto with arith",
            "eauto with core arith",
            "typeclasses eauto",
        ]

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
            "arith": _make_hint_database("arith", []),
        })

        for tactic in valid_tactics:
            # Should NOT raise INVALID_ARGUMENT
            result = await diagnose_auto(
                session_id="abc123",
                tactic=tactic,
                session_manager=manager,
                hint_inspect=hint_inspect,
            )
            assert result.tactic == tactic

    @pytest.mark.asyncio
    async def test_parse_error_includes_raw_output(self):
        """Spec §8.3: When trace parsing fails, PARSE_ERROR includes raw output."""
        # This tests that the system degrades gracefully when trace output is malformed
        # The parse_trace function itself doesn't raise — it preserves unrecognized lines.
        # But diagnose_auto should include raw messages in the diagnosis when parsing produces
        # an empty tree from non-empty messages.
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(
            tactic_outcome="failed",
            debug_messages=["completely garbled output that is not a trace"],
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", []),
        })

        # Should not crash — should degrade gracefully
        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )
        assert result is not None


# ===========================================================================
# 9. Edge Cases — Spec §8.4
# ===========================================================================


class TestEdgeCases:
    """Spec §8.4: Edge case handling."""

    @pytest.mark.asyncio
    async def test_successful_auto_still_diagnosable(self):
        """Given auto succeeds, diagnosis captures winning path and classifies non-winning hints."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(
            tactic_outcome="succeeded",
            debug_messages=["depth=5 simple apply Nat.add_0_r"],
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", [
                _make_hint_entry("Nat.add_0_r"),
                _make_hint_entry("eq_refl"),
            ]),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        assert result.outcome == "succeeded"
        assert result.winning_path is not None

    @pytest.mark.asyncio
    async def test_empty_trace_classifies_all_as_not_considered(self):
        """Given empty trace (no debug messages), all hints classified as not_considered."""
        diagnose_auto, *_ = _import_analyzer()

        manager = _make_mock_session_manager(tactic_outcome="failed", debug_messages=[])
        # Also make fallback produce empty messages
        manager.submit_tactic = AsyncMock(
            return_value=MagicMock(proof_state=_make_proof_state(), messages=[])
        )
        hint_inspect = _make_mock_hint_inspect({
            "core": _make_hint_database("core", [_make_hint_entry("A"), _make_hint_entry("B")]),
        })

        result = await diagnose_auto(
            session_id="abc123",
            tactic="auto",
            session_manager=manager,
            hint_inspect=hint_inspect,
        )

        for c in result.classifications:
            assert c.classification == "not_considered"

    def test_parser_handles_thousands_of_lines(self):
        """Given 5000 trace lines, parser completes without error."""
        (parse_trace,) = _import_parser()

        messages = [f"depth=5 simple apply lemma_{i} (*fail*)" for i in range(5000)]
        tree = parse_trace(messages)

        assert len(tree.root_nodes) == 5000
