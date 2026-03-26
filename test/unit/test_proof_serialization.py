"""TDD tests for proof serialization (specification/proof-serialization.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/serialization/ modules exist.

Spec: specification/proof-serialization.md
Architecture: doc/architecture/proof-serialization.md
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.serialization.serialize
  poule.serialization.diff
  poule.session.types
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------

def _import_types():
    from Poule.session.types import (
        Goal,
        GoalChange,
        Hypothesis,
        HypothesisChange,
        Premise,
        PremiseAnnotation,
        ProofState,
        ProofStateDiff,
        ProofTrace,
        Session,
        TraceStep,
    )
    return (
        Goal, GoalChange, Hypothesis, HypothesisChange, Premise,
        PremiseAnnotation, ProofState, ProofStateDiff, ProofTrace,
        Session, TraceStep,
    )


def _import_serialize():
    from Poule.serialization.serialize import (
        serialize_goal,
        serialize_hypothesis,
        serialize_premise,
        serialize_premise_annotation,
        serialize_proof_state,
        serialize_proof_trace,
        serialize_session,
        serialize_trace_step,
        serialize_proof_state_diff,
        serialize_goal_change,
        serialize_hypothesis_change,
    )
    return (
        serialize_goal, serialize_hypothesis, serialize_premise,
        serialize_premise_annotation, serialize_proof_state,
        serialize_proof_trace, serialize_session, serialize_trace_step,
        serialize_proof_state_diff, serialize_goal_change,
        serialize_hypothesis_change,
    )


def _import_diff():
    from Poule.serialization.diff import compute_diff
    return compute_diff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hypothesis(name="n", type_="nat", body=None):
    _, _, Hypothesis, *_ = _import_types()
    return Hypothesis(name=name, type=type_, body=body)


def _make_goal(index=0, type_="n + m = m + n", hypotheses=None):
    Goal, *_ = _import_types()
    _, _, Hypothesis, *_ = _import_types()
    if hypotheses is None:
        hypotheses = [
            Hypothesis(name="n", type="nat", body=None),
            Hypothesis(name="m", type="nat", body=None),
        ]
    return Goal(index=index, type=type_, hypotheses=hypotheses)


def _make_proof_state(
    session_id="abc-123",
    step_index=1,
    is_complete=False,
    focused_goal_index=0,
    goals=None,
):
    (
        Goal, _, Hypothesis, _, _, _, ProofState, _, _, _, _,
    ) = _import_types()
    if goals is None:
        goals = [_make_goal()]
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=focused_goal_index,
        goals=goals,
    )


def _make_completed_state(session_id="abc-123", step_index=5):
    (
        Goal, _, Hypothesis, _, _, _, ProofState, _, _, _, _,
    ) = _import_types()
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=True,
        focused_goal_index=None,
        goals=[],
    )


# ═══════════════════════════════════════════════════════════════════════════
# §4.4 Hypothesis Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisSerialization:
    """Spec §4.4: Hypothesis → JSON with fields name, type, body."""

    def test_non_let_bound_has_null_body(self):
        """body is explicitly null, not omitted."""
        (
            _, serialize_hypothesis, *_,
        ) = _import_serialize()
        h = _make_hypothesis(name="n", type_="nat", body=None)
        result = serialize_hypothesis(h)
        assert result == '{"name":"n","type":"nat","body":null}'

    def test_let_bound_has_body_value(self):
        (
            _, serialize_hypothesis, *_,
        ) = _import_serialize()
        h = _make_hypothesis(name="x", type_="nat", body="S O")
        result = serialize_hypothesis(h)
        assert result == '{"name":"x","type":"nat","body":"S O"}'

    def test_field_order_is_name_type_body(self):
        (
            _, serialize_hypothesis, *_,
        ) = _import_serialize()
        h = _make_hypothesis(name="a", type_="bool", body=None)
        parsed = json.loads(serialize_hypothesis(h))
        assert list(parsed.keys()) == ["name", "type", "body"]

    def test_body_null_is_json_null_not_string(self):
        (
            _, serialize_hypothesis, *_,
        ) = _import_serialize()
        h = _make_hypothesis(name="n", type_="nat", body=None)
        parsed = json.loads(serialize_hypothesis(h))
        assert parsed["body"] is None


# ═══════════════════════════════════════════════════════════════════════════
# §4.3 Goal Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestGoalSerialization:
    """Spec §4.3: Goal → JSON with fields index, type, hypotheses."""

    def test_goal_with_two_hypotheses(self):
        (
            serialize_goal, *_,
        ) = _import_serialize()
        g = _make_goal(index=0, type_="n + m = m + n")
        result = serialize_goal(g)
        parsed = json.loads(result)
        assert parsed["index"] == 0
        assert parsed["type"] == "n + m = m + n"
        assert len(parsed["hypotheses"]) == 2

    def test_goal_with_no_hypotheses(self):
        (
            serialize_goal, *_,
        ) = _import_serialize()
        Goal, *_ = _import_types()
        g = Goal(index=1, type="True", hypotheses=[])
        result = serialize_goal(g)
        parsed = json.loads(result)
        assert parsed["hypotheses"] == []

    def test_field_order_is_index_type_hypotheses(self):
        (
            serialize_goal, *_,
        ) = _import_serialize()
        g = _make_goal()
        parsed = json.loads(serialize_goal(g))
        assert list(parsed.keys()) == ["index", "type", "hypotheses"]


# ═══════════════════════════════════════════════════════════════════════════
# §4.2 ProofState Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestProofStateSerialization:
    """Spec §4.2: ProofState → JSON with 6 fields in order."""

    def test_active_state_has_all_fields(self):
        """Given a ProofState with one goal, JSON has exactly 6 ordered fields."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_proof_state(step_index=3, focused_goal_index=0)
        result = serialize_proof_state(state)
        parsed = json.loads(result)
        assert list(parsed.keys()) == [
            "schema_version", "session_id", "step_index",
            "is_complete", "focused_goal_index", "goals",
        ]

    def test_completed_state_has_null_focused_and_empty_goals(self):
        """Given completed ProofState, focused_goal_index=null and goals=[]."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_completed_state()
        result = serialize_proof_state(state)
        parsed = json.loads(result)
        assert parsed["focused_goal_index"] is None
        assert parsed["goals"] == []
        assert parsed["is_complete"] is True

    def test_schema_version_is_1(self):
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_proof_state()
        parsed = json.loads(serialize_proof_state(state))
        assert parsed["schema_version"] == 1

    def test_focused_goal_index_out_of_bounds_raises(self):
        """Spec §4.2: focused_goal_index=5 with only 3 goals → ValueError."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, _, _, _, _,
        ) = _import_types()
        goals = [
            Goal(index=0, type="A", hypotheses=[]),
            Goal(index=1, type="B", hypotheses=[]),
            Goal(index=2, type="C", hypotheses=[]),
        ]
        state = ProofState(
            schema_version=1,
            session_id="s1",
            step_index=0,
            is_complete=False,
            focused_goal_index=5,
            goals=goals,
        )
        with pytest.raises(ValueError, match="focused_goal_index out of bounds"):
            serialize_proof_state(state)

    def test_exact_json_output_one_goal(self):
        """Spec §7 example: exact byte-level output."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_proof_state(
            session_id="abc-123",
            step_index=1,
            is_complete=False,
            focused_goal_index=0,
        )
        expected = (
            '{"schema_version":1,"session_id":"abc-123","step_index":1,'
            '"is_complete":false,"focused_goal_index":0,'
            '"goals":[{"index":0,"type":"n + m = m + n",'
            '"hypotheses":[{"name":"n","type":"nat","body":null},'
            '{"name":"m","type":"nat","body":null}]}]}'
        )
        assert serialize_proof_state(state) == expected

    def test_exact_json_output_completed(self):
        """Spec §7 example: completed proof state."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_completed_state(session_id="abc-123", step_index=5)
        expected = (
            '{"schema_version":1,"session_id":"abc-123","step_index":5,'
            '"is_complete":true,"focused_goal_index":null,"goals":[]}'
        )
        assert serialize_proof_state(state) == expected

    def test_compact_output_no_whitespace(self):
        """Spec §6 NFR: compact output, no pretty-printing whitespace."""
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_proof_state()
        result = serialize_proof_state(state)
        assert "\n" not in result
        assert "  " not in result  # no indentation


# ═══════════════════════════════════════════════════════════════════════════
# §4.5 ProofTrace Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestProofTraceSerialization:
    """Spec §4.5: ProofTrace → JSON with schema_version, steps, etc."""

    def _make_trace(self, total_steps=2):
        (
            Goal, _, Hypothesis, _, _, _, ProofState, _, ProofTrace, _, TraceStep,
        ) = _import_types()

        steps = []
        for i in range(total_steps + 1):
            tactic = None if i == 0 else f"tactic_{i}."
            is_complete = i == total_steps
            state = ProofState(
                schema_version=1,
                session_id="abc-123",
                step_index=i,
                is_complete=is_complete,
                focused_goal_index=None if is_complete else 0,
                goals=[] if is_complete else [
                    Goal(index=0, type=f"goal_at_{i}", hypotheses=[]),
                ],
            )
            steps.append(TraceStep(step_index=i, tactic=tactic, state=state))

        return ProofTrace(
            schema_version=1,
            session_id="abc-123",
            proof_name="Nat.add_comm",
            file_path="/path/to/Nat.v",
            total_steps=total_steps,
            steps=steps,
        )

    def test_trace_field_order(self):
        (
            _, _, _, _, _, serialize_proof_trace, *_,
        ) = _import_serialize()
        trace = self._make_trace(total_steps=2)
        parsed = json.loads(serialize_proof_trace(trace))
        assert list(parsed.keys()) == [
            "schema_version", "session_id", "proof_name",
            "file_path", "total_steps", "steps",
        ]

    def test_trace_total_steps_and_step_count(self):
        (
            _, _, _, _, _, serialize_proof_trace, *_,
        ) = _import_serialize()
        trace = self._make_trace(total_steps=2)
        parsed = json.loads(serialize_proof_trace(trace))
        assert parsed["total_steps"] == 2
        assert len(parsed["steps"]) == 3  # total_steps + 1

    def test_step_0_has_null_tactic(self):
        (
            _, _, _, _, _, serialize_proof_trace, *_,
        ) = _import_serialize()
        trace = self._make_trace(total_steps=2)
        parsed = json.loads(serialize_proof_trace(trace))
        assert parsed["steps"][0]["tactic"] is None

    def test_step_1_plus_have_tactic_strings(self):
        (
            _, _, _, _, _, serialize_proof_trace, *_,
        ) = _import_serialize()
        trace = self._make_trace(total_steps=2)
        parsed = json.loads(serialize_proof_trace(trace))
        for i in range(1, 3):
            assert isinstance(parsed["steps"][i]["tactic"], str)

    def test_step_count_mismatch_raises(self):
        """Spec §4.5: total_steps=3 but only 3 steps (not 4) → ValueError."""
        (
            _, _, _, _, _, serialize_proof_trace, *_,
        ) = _import_serialize()
        trace = self._make_trace(total_steps=2)
        # Mutate total_steps to cause mismatch
        (
            _, _, _, _, _, _, _, _, ProofTrace, _, _,
        ) = _import_types()
        bad_trace = ProofTrace(
            schema_version=1,
            session_id="abc-123",
            proof_name="test",
            file_path="/test.v",
            total_steps=3,
            steps=trace.steps,  # only 3 steps, not 4
        )
        with pytest.raises(ValueError, match="step count mismatch"):
            serialize_proof_trace(bad_trace)


# ═══════════════════════════════════════════════════════════════════════════
# §4.6 TraceStep Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestTraceStepSerialization:
    """Spec §4.6: TraceStep → JSON with step_index, tactic, state."""

    def test_step_0_has_null_tactic_in_output(self):
        """tactic field present as null, not omitted."""
        (
            _, _, _, _, _, _, _, serialize_trace_step, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, ProofState, _, _, _, TraceStep,
        ) = _import_types()
        state = _make_completed_state(step_index=0)
        ts = TraceStep(step_index=0, tactic=None, state=state)
        parsed = json.loads(serialize_trace_step(ts))
        assert "tactic" in parsed
        assert parsed["tactic"] is None

    def test_field_order_is_step_index_tactic_state(self):
        (
            _, _, _, _, _, _, _, serialize_trace_step, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, ProofState, _, _, _, TraceStep,
        ) = _import_types()
        state = _make_proof_state(step_index=1)
        ts = TraceStep(step_index=1, tactic="intro n.", state=state)
        parsed = json.loads(serialize_trace_step(ts))
        assert list(parsed.keys()) == ["step_index", "tactic", "state"]

    def test_step_0_with_non_null_tactic_raises(self):
        """Spec §4.6: step 0 with tactic="intro n." → ValueError."""
        (
            _, _, _, _, _, _, _, serialize_trace_step, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, ProofState, _, _, _, TraceStep,
        ) = _import_types()
        state = _make_proof_state(step_index=0)
        ts = TraceStep(step_index=0, tactic="intro n.", state=state)
        with pytest.raises(ValueError, match="step 0 must have null tactic"):
            serialize_trace_step(ts)

    def test_step_positive_with_null_tactic_raises(self):
        """Spec §4.6: step 3 with tactic=None → ValueError."""
        (
            _, _, _, _, _, _, _, serialize_trace_step, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, ProofState, _, _, _, TraceStep,
        ) = _import_types()
        state = _make_proof_state(step_index=3)
        ts = TraceStep(step_index=3, tactic=None, state=state)
        with pytest.raises(ValueError, match="steps 1..N must have non-null tactic"):
            serialize_trace_step(ts)


# ═══════════════════════════════════════════════════════════════════════════
# §4.8 Premise Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestPremiseSerialization:
    """Spec §4.8: Premise → JSON with name, kind."""

    def test_valid_premise_serializes(self):
        (
            _, _, serialize_premise, *_,
        ) = _import_serialize()
        (
            _, _, _, _, Premise, *_,
        ) = _import_types()
        p = Premise(name="Stdlib.Arith.PeanoNat.Nat.add_comm", kind="lemma")
        result = serialize_premise(p)
        assert result == '{"name":"Stdlib.Arith.PeanoNat.Nat.add_comm","kind":"lemma"}'

    def test_field_order_is_name_kind(self):
        (
            _, _, serialize_premise, *_,
        ) = _import_serialize()
        (
            _, _, _, _, Premise, *_,
        ) = _import_types()
        p = Premise(name="test", kind="hypothesis")
        parsed = json.loads(serialize_premise(p))
        assert list(parsed.keys()) == ["name", "kind"]

    @pytest.mark.parametrize("kind", ["lemma", "hypothesis", "constructor", "definition"])
    def test_valid_kinds_accepted(self, kind):
        (
            _, _, serialize_premise, *_,
        ) = _import_serialize()
        (
            _, _, _, _, Premise, *_,
        ) = _import_types()
        p = Premise(name="test", kind=kind)
        parsed = json.loads(serialize_premise(p))
        assert parsed["kind"] == kind

    def test_invalid_kind_raises(self):
        """Spec §4.8: kind="axiom" → ValueError."""
        (
            _, _, serialize_premise, *_,
        ) = _import_serialize()
        (
            _, _, _, _, Premise, *_,
        ) = _import_types()
        p = Premise(name="test", kind="axiom")
        with pytest.raises(ValueError, match="kind must be one of"):
            serialize_premise(p)


# ═══════════════════════════════════════════════════════════════════════════
# §4.7 PremiseAnnotation Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestPremiseAnnotationSerialization:
    """Spec §4.7: PremiseAnnotation → JSON."""

    def test_annotation_with_one_premise(self):
        (
            _, _, _, serialize_premise_annotation, *_,
        ) = _import_serialize()
        (
            _, _, _, _, Premise, PremiseAnnotation, *_,
        ) = _import_types()
        ann = PremiseAnnotation(
            step_index=3,
            tactic="rewrite Nat.add_comm.",
            premises=[Premise(name="Stdlib.Arith.PeanoNat.Nat.add_comm", kind="lemma")],
        )
        result = serialize_premise_annotation(ann)
        expected = (
            '{"step_index":3,"tactic":"rewrite Nat.add_comm.",'
            '"premises":[{"name":"Stdlib.Arith.PeanoNat.Nat.add_comm","kind":"lemma"}]}'
        )
        assert result == expected

    def test_annotation_with_no_premises(self):
        """A tactic like reflexivity uses no premises → premises=[]."""
        (
            _, _, _, serialize_premise_annotation, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, PremiseAnnotation, *_,
        ) = _import_types()
        ann = PremiseAnnotation(
            step_index=1,
            tactic="reflexivity.",
            premises=[],
        )
        parsed = json.loads(serialize_premise_annotation(ann))
        assert parsed["premises"] == []

    def test_field_order(self):
        (
            _, _, _, serialize_premise_annotation, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, PremiseAnnotation, *_,
        ) = _import_types()
        ann = PremiseAnnotation(step_index=1, tactic="intro.", premises=[])
        parsed = json.loads(serialize_premise_annotation(ann))
        assert list(parsed.keys()) == ["step_index", "tactic", "premises"]


# ═══════════════════════════════════════════════════════════════════════════
# §4.9 Session Metadata Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionSerialization:
    """Spec §4.9: Session → JSON with 7 fields."""

    def test_session_with_total_steps(self):
        (
            _, _, _, _, _, _, serialize_session, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, _, _, _, Session, _,
        ) = _import_types()
        s = Session(
            session_id="abc-123",
            file_path="/path/to/Nat.v",
            proof_name="Nat.add_comm",
            current_step=3,
            total_steps=5,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:05:00Z",
        )
        expected = (
            '{"session_id":"abc-123","file_path":"/path/to/Nat.v",'
            '"proof_name":"Nat.add_comm","current_step":3,"total_steps":5,'
            '"created_at":"2026-03-17T14:00:00Z","last_active_at":"2026-03-17T14:05:00Z"}'
        )
        assert serialize_session(s) == expected

    def test_session_with_null_total_steps(self):
        (
            _, _, _, _, _, _, serialize_session, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, _, _, _, Session, _,
        ) = _import_types()
        s = Session(
            session_id="s1",
            file_path="/test.v",
            proof_name="test",
            current_step=0,
            total_steps=None,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:00:00Z",
        )
        parsed = json.loads(serialize_session(s))
        assert parsed["total_steps"] is None

    def test_field_order(self):
        (
            _, _, _, _, _, _, serialize_session, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, _, _, _, Session, _,
        ) = _import_types()
        s = Session(
            session_id="s1",
            file_path="/test.v",
            proof_name="test",
            current_step=0,
            total_steps=None,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:00:00Z",
        )
        parsed = json.loads(serialize_session(s))
        assert list(parsed.keys()) == [
            "session_id", "file_path", "proof_name",
            "current_step", "total_steps", "created_at", "last_active_at",
        ]

    def test_timestamp_format_utc_z_suffix(self):
        """Spec §4.13: timestamps with seconds precision and Z suffix."""
        (
            _, _, _, _, _, _, serialize_session, *_,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, _, _, _, Session, _,
        ) = _import_types()
        s = Session(
            session_id="s1",
            file_path="/test.v",
            proof_name="test",
            current_step=0,
            total_steps=None,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:00:00Z",
        )
        parsed = json.loads(serialize_session(s))
        assert parsed["created_at"].endswith("Z")
        assert parsed["last_active_at"].endswith("Z")


# ═══════════════════════════════════════════════════════════════════════════
# §4.10 ProofStateDiff Serialization (P1)
# ═══════════════════════════════════════════════════════════════════════════


class TestProofStateDiffSerialization:
    """Spec §4.10: ProofStateDiff → JSON with 8 fields."""

    def test_empty_diff_all_arrays_empty(self):
        """No changes → all 6 array fields are []."""
        (
            *_, serialize_proof_state_diff, _, _,
        ) = _import_serialize()
        (
            _, GoalChange, _, HypothesisChange, _, _, _, ProofStateDiff, *_,
        ) = _import_types()
        diff = ProofStateDiff(
            from_step=2,
            to_step=3,
            goals_added=[],
            goals_removed=[],
            goals_changed=[],
            hypotheses_added=[],
            hypotheses_removed=[],
            hypotheses_changed=[],
        )
        parsed = json.loads(serialize_proof_state_diff(diff))
        assert parsed["goals_added"] == []
        assert parsed["goals_removed"] == []
        assert parsed["goals_changed"] == []
        assert parsed["hypotheses_added"] == []
        assert parsed["hypotheses_removed"] == []
        assert parsed["hypotheses_changed"] == []

    def test_diff_field_order(self):
        (
            *_, serialize_proof_state_diff, _, _,
        ) = _import_serialize()
        (
            _, _, _, _, _, _, _, ProofStateDiff, *_,
        ) = _import_types()
        diff = ProofStateDiff(
            from_step=0,
            to_step=1,
            goals_added=[],
            goals_removed=[],
            goals_changed=[],
            hypotheses_added=[],
            hypotheses_removed=[],
            hypotheses_changed=[],
        )
        parsed = json.loads(serialize_proof_state_diff(diff))
        assert list(parsed.keys()) == [
            "from_step", "to_step", "goals_added", "goals_removed",
            "goals_changed", "hypotheses_added", "hypotheses_removed",
            "hypotheses_changed",
        ]

    def test_diff_with_added_goal_and_removed_hypotheses(self):
        (
            *_, serialize_proof_state_diff, _, _,
        ) = _import_serialize()
        (
            Goal, _, Hypothesis, _, _, _, _, ProofStateDiff, *_,
        ) = _import_types()
        diff = ProofStateDiff(
            from_step=1,
            to_step=2,
            goals_added=[Goal(index=1, type="new_goal", hypotheses=[])],
            goals_removed=[],
            goals_changed=[],
            hypotheses_added=[],
            hypotheses_removed=[
                Hypothesis(name="h1", type="nat", body=None),
                Hypothesis(name="h2", type="bool", body=None),
            ],
            hypotheses_changed=[],
        )
        parsed = json.loads(serialize_proof_state_diff(diff))
        assert len(parsed["goals_added"]) == 1
        assert len(parsed["hypotheses_removed"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# §4.11 GoalChange Serialization (P1)
# ═══════════════════════════════════════════════════════════════════════════


class TestGoalChangeSerialization:
    """Spec §4.11: GoalChange → JSON with index, before, after."""

    def test_goal_change_exact_output(self):
        (
            *_, _, serialize_goal_change, _,
        ) = _import_serialize()
        (
            _, GoalChange, *_,
        ) = _import_types()
        gc = GoalChange(
            index=0,
            before="S n + m = m + S n",
            after="S (n + m) = m + S n",
        )
        result = serialize_goal_change(gc)
        assert result == (
            '{"index":0,"before":"S n + m = m + S n",'
            '"after":"S (n + m) = m + S n"}'
        )

    def test_goal_change_field_order(self):
        (
            *_, _, serialize_goal_change, _,
        ) = _import_serialize()
        (
            _, GoalChange, *_,
        ) = _import_types()
        gc = GoalChange(index=1, before="A", after="B")
        parsed = json.loads(serialize_goal_change(gc))
        assert list(parsed.keys()) == ["index", "before", "after"]


# ═══════════════════════════════════════════════════════════════════════════
# §4.12 HypothesisChange Serialization (P1)
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisChangeSerialization:
    """Spec §4.12: HypothesisChange → JSON with 5 fields."""

    def test_type_change_with_null_bodies(self):
        (
            *_, serialize_hypothesis_change,
        ) = _import_serialize()
        (
            _, _, _, HypothesisChange, *_,
        ) = _import_types()
        hc = HypothesisChange(
            name="IHn",
            type_before="n + m = m + n",
            type_after="S n + m = m + S n",
            body_before=None,
            body_after=None,
        )
        parsed = json.loads(serialize_hypothesis_change(hc))
        assert parsed["body_before"] is None
        assert parsed["body_after"] is None

    def test_body_change_with_same_type(self):
        (
            *_, serialize_hypothesis_change,
        ) = _import_serialize()
        (
            _, _, _, HypothesisChange, *_,
        ) = _import_types()
        hc = HypothesisChange(
            name="x",
            type_before="nat",
            type_after="nat",
            body_before="O",
            body_after="S O",
        )
        parsed = json.loads(serialize_hypothesis_change(hc))
        assert parsed["type_before"] == parsed["type_after"]
        assert parsed["body_before"] == "O"
        assert parsed["body_after"] == "S O"

    def test_field_order(self):
        (
            *_, serialize_hypothesis_change,
        ) = _import_serialize()
        (
            _, _, _, HypothesisChange, *_,
        ) = _import_types()
        hc = HypothesisChange(
            name="x", type_before="A", type_after="B",
            body_before=None, body_after=None,
        )
        parsed = json.loads(serialize_hypothesis_change(hc))
        assert list(parsed.keys()) == [
            "name", "type_before", "type_after", "body_before", "body_after",
        ]


# ═══════════════════════════════════════════════════════════════════════════
# §4.13 Determinism
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Spec §4.13: identical input → byte-identical output."""

    def test_identical_proof_states_produce_identical_json(self):
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        s1 = _make_proof_state(session_id="x", step_index=2)
        s2 = _make_proof_state(session_id="x", step_index=2)
        assert serialize_proof_state(s1) == serialize_proof_state(s2)

    def test_repeated_serialization_is_stable(self):
        (
            _, _, _, _, serialize_proof_state, *_,
        ) = _import_serialize()
        state = _make_proof_state()
        results = [serialize_proof_state(state) for _ in range(10)]
        assert len(set(results)) == 1


# ═══════════════════════════════════════════════════════════════════════════
# §4.14 Diff Computation (P1)
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeDiff:
    """Spec §4.14: compute_diff algorithm."""

    def test_goal_type_changed(self):
        """Goal at same index with different type → goals_changed."""
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=2,
            is_complete=False, focused_goal_index=0,
            goals=[
                Goal(index=0, type="S n + m = m + S n", hypotheses=[
                    Hypothesis(name="IHn", type="n + m = m + n", body=None),
                ]),
                Goal(index=1, type="other_goal", hypotheses=[]),
            ],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=3,
            is_complete=False, focused_goal_index=0,
            goals=[
                Goal(index=0, type="S (n + m) = m + S n", hypotheses=[
                    Hypothesis(name="IHn", type="n + m = m + n", body=None),
                ]),
            ],
        )
        diff = compute_diff(before, after)
        assert diff.from_step == 2
        assert diff.to_step == 3
        assert len(diff.goals_changed) == 1
        assert diff.goals_changed[0].index == 0
        assert diff.goals_changed[0].before == "S n + m = m + S n"
        assert diff.goals_changed[0].after == "S (n + m) = m + S n"
        assert len(diff.goals_removed) == 1
        assert diff.goals_removed[0].index == 1

    def test_goal_added(self):
        """Goal index present only in after → goals_added."""
        compute_diff = _import_diff()
        (
            Goal, _, _, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[])],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[
                Goal(index=0, type="A", hypotheses=[]),
                Goal(index=1, type="B", hypotheses=[]),
            ],
        )
        diff = compute_diff(before, after)
        assert len(diff.goals_added) == 1
        assert diff.goals_added[0].index == 1
        assert diff.goals_changed == []

    def test_goal_removed(self):
        """Goal index present only in before → goals_removed."""
        compute_diff = _import_diff()
        (
            Goal, _, _, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=False, focused_goal_index=0,
            goals=[
                Goal(index=0, type="A", hypotheses=[]),
                Goal(index=1, type="B", hypotheses=[]),
            ],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[])],
        )
        diff = compute_diff(before, after)
        assert len(diff.goals_removed) == 1
        assert diff.goals_removed[0].index == 1

    def test_hypothesis_added_in_focused_goal(self):
        """New hypothesis in focused goal → hypotheses_added."""
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=2,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="n", type="nat", body=None),
                Hypothesis(name="m", type="nat", body=None),
                Hypothesis(name="IHn", type="n + m = m + n", body=None),
            ])],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=3,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="n", type="nat", body=None),
                Hypothesis(name="m", type="nat", body=None),
                Hypothesis(name="IHn", type="n + m = m + n", body=None),
                Hypothesis(name="H", type="n + m = m + n", body=None),
            ])],
        )
        diff = compute_diff(before, after)
        assert len(diff.hypotheses_added) == 1
        assert diff.hypotheses_added[0].name == "H"
        assert diff.hypotheses_removed == []
        assert diff.hypotheses_changed == []

    def test_hypothesis_removed_in_focused_goal(self):
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="n", type="nat", body=None),
                Hypothesis(name="H", type="bool", body=None),
            ])],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="n", type="nat", body=None),
            ])],
        )
        diff = compute_diff(before, after)
        assert len(diff.hypotheses_removed) == 1
        assert diff.hypotheses_removed[0].name == "H"

    def test_hypothesis_changed_in_focused_goal(self):
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="IHn", type="n + m = m + n", body=None),
            ])],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="IHn", type="S n + m = m + S n", body=None),
            ])],
        )
        diff = compute_diff(before, after)
        assert len(diff.hypotheses_changed) == 1
        assert diff.hypotheses_changed[0].name == "IHn"
        assert diff.hypotheses_changed[0].type_before == "n + m = m + n"
        assert diff.hypotheses_changed[0].type_after == "S n + m = m + S n"

    def test_non_consecutive_steps_raises(self):
        """Spec §5: non-consecutive steps → ValueError."""
        compute_diff = _import_diff()
        before = _make_proof_state(step_index=0)
        after = _make_proof_state(step_index=5)
        with pytest.raises(ValueError, match="states must be consecutive"):
            compute_diff(before, after)

    def test_complete_before_state_empty_hypothesis_diff(self):
        """When before is complete (no focused goal), hyp diffs are all empty."""
        compute_diff = _import_diff()
        (
            Goal, _, _, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=True, focused_goal_index=None, goals=[],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[])],
        )
        diff = compute_diff(before, after)
        assert diff.hypotheses_added == []
        assert diff.hypotheses_removed == []
        assert diff.hypotheses_changed == []
        assert len(diff.goals_added) == 1

    def test_focused_goal_removed_empty_hypothesis_diff(self):
        """When the focused goal from before doesn't exist in after, hyp diffs empty."""
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=0,
            is_complete=False, focused_goal_index=1,
            goals=[
                Goal(index=0, type="A", hypotheses=[]),
                Goal(index=1, type="B", hypotheses=[
                    Hypothesis(name="x", type="nat", body=None),
                ]),
            ],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=1,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="A", hypotheses=[])],
        )
        diff = compute_diff(before, after)
        assert diff.hypotheses_added == []
        assert diff.hypotheses_removed == []
        assert diff.hypotheses_changed == []

    def test_exact_diff_output_from_spec_example(self):
        """Spec §7 diff example: step 2→3 with goal type change and new hypothesis."""
        compute_diff = _import_diff()
        (
            Goal, _, Hypothesis, _, _, _, ProofState, *_,
        ) = _import_types()
        before = ProofState(
            schema_version=1, session_id="s1", step_index=2,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="S n + m = m + S n", hypotheses=[
                Hypothesis(name="IHn", type="n + m = m + n", body=None),
            ])],
        )
        after = ProofState(
            schema_version=1, session_id="s1", step_index=3,
            is_complete=False, focused_goal_index=0,
            goals=[Goal(index=0, type="S (n + m) = m + S n", hypotheses=[
                Hypothesis(name="IHn", type="n + m = m + n", body=None),
                Hypothesis(name="H", type="n + m = m + n", body=None),
            ])],
        )
        diff = compute_diff(before, after)
        assert diff.from_step == 2
        assert diff.to_step == 3
        assert diff.goals_added == []
        assert diff.goals_removed == []
        assert len(diff.goals_changed) == 1
        assert diff.goals_changed[0].before == "S n + m = m + S n"
        assert diff.goals_changed[0].after == "S (n + m) = m + S n"
        assert len(diff.hypotheses_added) == 1
        assert diff.hypotheses_added[0].name == "H"
        assert diff.hypotheses_removed == []
        assert diff.hypotheses_changed == []
