"""TDD tests for extraction output serialization (specification/extraction-output.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/extraction/.

Spec: specification/extraction-output.md
Architecture: doc/architecture/extraction-output.md

Import paths under test:
  poule.extraction.output
  poule.extraction.types
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------

def _import_types():
    from Poule.extraction.types import (
        CampaignMetadata,
        ExtractionDiff,
        ExtractionError,
        ExtractionRecord,
        ExtractionStep,
        ExtractionSummary,
        FileSummary,
        Goal,
        Hypothesis,
        Premise,
        ProjectMetadata,
        ProjectSummary,
    )
    return (
        CampaignMetadata, ExtractionDiff, ExtractionError,
        ExtractionRecord, ExtractionStep, ExtractionSummary,
        FileSummary, Goal, Hypothesis, Premise,
        ProjectMetadata, ProjectSummary,
    )


def _import_output():
    from Poule.extraction.output import (
        serialize_campaign_metadata,
        serialize_extraction_diff,
        serialize_extraction_error,
        serialize_extraction_record,
        serialize_extraction_step,
        serialize_extraction_summary,
        serialize_premise,
        serialize_project_metadata,
    )
    return (
        serialize_campaign_metadata, serialize_extraction_diff,
        serialize_extraction_error, serialize_extraction_record,
        serialize_extraction_step, serialize_extraction_summary,
        serialize_premise, serialize_project_metadata,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hypothesis(name="n", type_="nat", body=None):
    (_, _, _, _, _, _, _, _, Hypothesis, _, _, _) = _import_types()
    return Hypothesis(name=name, type=type_, body=body)


def _make_goal(index=0, type_="n + m = m + n", hypotheses=None):
    (_, _, _, _, _, _, _, Goal, _, _, _, _) = _import_types()
    if hypotheses is None:
        hypotheses = [
            _make_hypothesis(name="n", type_="nat"),
            _make_hypothesis(name="m", type_="nat"),
        ]
    return Goal(index=index, type=type_, hypotheses=hypotheses)


def _make_premise(name="Nat.add_comm", kind="lemma"):
    (_, _, _, _, _, _, _, _, _, Premise, _, _) = _import_types()
    return Premise(name=name, kind=kind)


def _make_extraction_diff(
    goals_added=None,
    goals_removed=None,
    goals_changed=None,
    hypotheses_added=None,
    hypotheses_removed=None,
    hypotheses_changed=None,
):
    (_, ExtractionDiff, *_) = _import_types()
    return ExtractionDiff(
        goals_added=goals_added or [],
        goals_removed=goals_removed or [],
        goals_changed=goals_changed or [],
        hypotheses_added=hypotheses_added or [],
        hypotheses_removed=hypotheses_removed or [],
        hypotheses_changed=hypotheses_changed or [],
    )


def _make_step_0():
    (_, _, _, _, ExtractionStep, _, _, _, _, _, _, _) = _import_types()
    return ExtractionStep(
        step_index=0,
        tactic=None,
        goals=[_make_goal()],
        focused_goal_index=0,
        premises=[],
        diff=None,
    )


def _make_step(index=1, tactic="reflexivity.", goals=None,
               focused_goal_index=None, premises=None, diff=None):
    (_, _, _, _, ExtractionStep, _, _, _, _, _, _, _) = _import_types()
    return ExtractionStep(
        step_index=index,
        tactic=tactic,
        goals=goals if goals is not None else [],
        focused_goal_index=focused_goal_index,
        premises=premises or [],
        diff=diff,
    )


def _make_project_metadata(
    project_id="coq-stdlib",
    project_path="/home/user/.opam/default/lib/coq/theories",
    coq_version="8.19.1",
    commit_hash=None,
):
    (_, _, _, _, _, _, _, _, _, _, ProjectMetadata, _) = _import_types()
    return ProjectMetadata(
        project_id=project_id,
        project_path=project_path,
        coq_version=coq_version,
        commit_hash=commit_hash,
    )


def _make_campaign_metadata(
    extraction_tool_version="0.3.0",
    extraction_timestamp="2026-03-17T14:30:00Z",
    projects=None,
):
    (CampaignMetadata, *_) = _import_types()
    if projects is None:
        projects = [_make_project_metadata()]
    return CampaignMetadata(
        schema_version=1,
        record_type="campaign_metadata",
        extraction_tool_version=extraction_tool_version,
        extraction_timestamp=extraction_timestamp,
        projects=projects,
    )


def _make_extraction_record(
    theorem_name="Stdlib.Init.Logic.eq_refl",
    source_file="theories/Init/Logic.v",
    project_id="coq-stdlib",
    total_steps=1,
    steps=None,
):
    (_, _, _, ExtractionRecord, _, _, _, _, _, _, _, _) = _import_types()
    if steps is None:
        steps = [_make_step_0(), _make_step()]
    return ExtractionRecord(
        schema_version=1,
        record_type="proof_trace",
        theorem_name=theorem_name,
        source_file=source_file,
        project_id=project_id,
        total_steps=total_steps,
        steps=steps,
    )


def _make_extraction_error(
    theorem_name="Stdlib.Arith.PeanoNat.Nat.sub_diag",
    source_file="theories/Arith/PeanoNat.v",
    project_id="coq-stdlib",
    error_kind="timeout",
    error_message="Proof extraction exceeded 60s time limit",
):
    (_, _, ExtractionError, *_) = _import_types()
    return ExtractionError(
        schema_version=1,
        record_type="extraction_error",
        theorem_name=theorem_name,
        source_file=source_file,
        project_id=project_id,
        error_kind=error_kind,
        error_message=error_message,
    )


def _make_file_summary(
    source_file="theories/Init/Logic.v",
    theorems_found=1,
    extracted=1,
    failed=0,
    skipped=0,
):
    (_, _, _, _, _, _, FileSummary, _, _, _, _, _) = _import_types()
    return FileSummary(
        source_file=source_file,
        theorems_found=theorems_found,
        extracted=extracted,
        failed=failed,
        skipped=skipped,
    )


def _make_project_summary(
    project_id="coq-stdlib",
    theorems_found=2,
    extracted=1,
    failed=1,
    skipped=0,
    per_file=None,
):
    (_, _, _, _, _, _, _, _, _, _, _, ProjectSummary) = _import_types()
    if per_file is None:
        per_file = [
            _make_file_summary(
                source_file="theories/Init/Logic.v",
                theorems_found=1, extracted=1, failed=0, skipped=0,
            ),
            _make_file_summary(
                source_file="theories/Arith/PeanoNat.v",
                theorems_found=1, extracted=0, failed=1, skipped=0,
            ),
        ]
    return ProjectSummary(
        project_id=project_id,
        theorems_found=theorems_found,
        extracted=extracted,
        failed=failed,
        skipped=skipped,
        per_file=per_file,
    )


def _make_extraction_summary(
    total_theorems_found=2,
    total_extracted=1,
    total_failed=1,
    total_skipped=0,
    per_project=None,
):
    (_, _, _, _, _, ExtractionSummary, _, _, _, _, _, _) = _import_types()
    if per_project is None:
        per_project = [_make_project_summary()]
    return ExtractionSummary(
        schema_version=1,
        record_type="extraction_summary",
        total_theorems_found=total_theorems_found,
        total_extracted=total_extracted,
        total_failed=total_failed,
        total_skipped=total_skipped,
        per_project=per_project,
    )


# ═══════════════════════════════════════════════════════════════════════════
# §4.1 Output Stream Structure
# ═══════════════════════════════════════════════════════════════════════════


class TestOutputStreamStructure:
    """Spec §4.1: JSON Lines stream — metadata first, summary last."""

    def test_every_record_has_record_type_field(self):
        """Every JSON object contains a record_type string field."""
        (
            serialize_campaign_metadata, _, serialize_extraction_error,
            serialize_extraction_record, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        metadata = _make_campaign_metadata()
        record = _make_extraction_record()
        error = _make_extraction_error()
        summary = _make_extraction_summary()

        for obj, serializer in [
            (metadata, serialize_campaign_metadata),
            (record, serialize_extraction_record),
            (error, serialize_extraction_error),
            (summary, serialize_extraction_summary),
        ]:
            parsed = json.loads(serializer(obj))
            assert "record_type" in parsed
            assert isinstance(parsed["record_type"], str)

    def test_every_record_has_schema_version_field(self):
        """Every JSON object contains a schema_version positive integer."""
        (
            serialize_campaign_metadata, _, serialize_extraction_error,
            serialize_extraction_record, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        metadata = _make_campaign_metadata()
        record = _make_extraction_record()
        error = _make_extraction_error()
        summary = _make_extraction_summary()

        for obj, serializer in [
            (metadata, serialize_campaign_metadata),
            (record, serialize_extraction_record),
            (error, serialize_extraction_error),
            (summary, serialize_extraction_summary),
        ]:
            parsed = json.loads(serializer(obj))
            assert "schema_version" in parsed
            assert isinstance(parsed["schema_version"], int)
            assert parsed["schema_version"] > 0

    def test_stream_order_with_traces_and_errors(self):
        """10 proofs, 2 failures: 1 metadata + 8 traces + 2 errors + 1 summary = 12 lines."""
        (
            serialize_campaign_metadata, _, serialize_extraction_error,
            serialize_extraction_record, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        lines = []
        lines.append(serialize_campaign_metadata(_make_campaign_metadata()))
        for i in range(8):
            lines.append(serialize_extraction_record(
                _make_extraction_record(theorem_name=f"Thm.t{i}"),
            ))
        for i in range(2):
            lines.append(serialize_extraction_error(
                _make_extraction_error(theorem_name=f"Thm.err{i}"),
            ))
        lines.append(serialize_extraction_summary(
            _make_extraction_summary(
                total_theorems_found=10, total_extracted=8, total_failed=2,
            ),
        ))

        assert len(lines) == 12
        assert json.loads(lines[0])["record_type"] == "campaign_metadata"
        assert json.loads(lines[-1])["record_type"] == "extraction_summary"
        for line in lines[1:-1]:
            parsed = json.loads(line)
            assert parsed["record_type"] in ("proof_trace", "extraction_error")

    def test_empty_campaign_produces_two_lines(self):
        """Zero theorems: 1 metadata + 1 summary = 2 lines."""
        (
            serialize_campaign_metadata, _, _,
            _, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        lines = []
        lines.append(serialize_campaign_metadata(_make_campaign_metadata()))
        lines.append(serialize_extraction_summary(
            _make_extraction_summary(
                total_theorems_found=0, total_extracted=0,
                total_failed=0, total_skipped=0,
                per_project=[_make_project_summary(
                    theorems_found=0, extracted=0, failed=0, skipped=0,
                    per_file=[],
                )],
            ),
        ))

        assert len(lines) == 2
        assert json.loads(lines[0])["record_type"] == "campaign_metadata"
        assert json.loads(lines[1])["record_type"] == "extraction_summary"


# ═══════════════════════════════════════════════════════════════════════════
# §4.2 CampaignMetadata Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestCampaignMetadataSerialization:
    """Spec §4.2: CampaignMetadata has exactly 5 fields in order."""

    def test_field_ordering(self):
        """Fields appear in spec-defined order."""
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        result = json.loads(serialize_campaign_metadata(meta))
        assert list(result.keys()) == [
            "schema_version",
            "record_type",
            "extraction_tool_version",
            "extraction_timestamp",
            "projects",
        ]

    def test_exactly_five_fields(self):
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        result = json.loads(serialize_campaign_metadata(meta))
        assert len(result) == 5

    def test_record_type_is_campaign_metadata(self):
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        result = json.loads(serialize_campaign_metadata(meta))
        assert result["record_type"] == "campaign_metadata"

    def test_timestamp_format_iso8601_with_z(self):
        """extraction_timestamp uses ISO 8601 with seconds precision and Z suffix."""
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata(
            extraction_timestamp="2026-03-17T14:30:00Z",
        )
        result = json.loads(serialize_campaign_metadata(meta))
        ts = result["extraction_timestamp"]
        assert ts.endswith("Z")
        # ISO 8601 with seconds precision: YYYY-MM-DDTHH:MM:SSZ
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)

    def test_projects_array_with_two_projects(self):
        """Given 2 projects, projects array has 2 elements in order."""
        (serialize_campaign_metadata, *_) = _import_output()
        p1 = _make_project_metadata(project_id="proj-a")
        p2 = _make_project_metadata(project_id="proj-b")
        meta = _make_campaign_metadata(projects=[p1, p2])
        result = json.loads(serialize_campaign_metadata(meta))
        assert len(result["projects"]) == 2
        assert result["projects"][0]["project_id"] == "proj-a"
        assert result["projects"][1]["project_id"] == "proj-b"


# ═══════════════════════════════════════════════════════════════════════════
# §4.3 ProjectMetadata Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestProjectMetadataSerialization:
    """Spec §4.3: ProjectMetadata has exactly 4 fields."""

    def test_field_ordering(self):
        (_, _, _, _, _, _, _, serialize_project_metadata) = _import_output()
        pm = _make_project_metadata()
        result = json.loads(serialize_project_metadata(pm))
        assert list(result.keys()) == [
            "project_id",
            "project_path",
            "coq_version",
            "commit_hash",
        ]

    def test_exactly_four_fields(self):
        (_, _, _, _, _, _, _, serialize_project_metadata) = _import_output()
        pm = _make_project_metadata()
        result = json.loads(serialize_project_metadata(pm))
        assert len(result) == 4

    def test_commit_hash_null_when_unavailable(self):
        """commit_hash is explicitly null, not omitted."""
        (_, _, _, _, _, _, _, serialize_project_metadata) = _import_output()
        pm = _make_project_metadata(commit_hash=None)
        raw = serialize_project_metadata(pm)
        result = json.loads(raw)
        assert "commit_hash" in result
        assert result["commit_hash"] is None
        # Verify it's literally null in JSON, not omitted
        assert '"commit_hash":null' in raw

    def test_commit_hash_present_when_available(self):
        (_, _, _, _, _, _, _, serialize_project_metadata) = _import_output()
        pm = _make_project_metadata(commit_hash="abc123def456")
        result = json.loads(serialize_project_metadata(pm))
        assert result["commit_hash"] == "abc123def456"


# ═══════════════════════════════════════════════════════════════════════════
# §4.4 ExtractionRecord Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionRecordSerialization:
    """Spec §4.4: ExtractionRecord has 7 fields, step count validation."""

    def test_field_ordering(self):
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        result = json.loads(serialize_extraction_record(record))
        assert list(result.keys()) == [
            "schema_version",
            "record_type",
            "theorem_name",
            "source_file",
            "project_id",
            "total_steps",
            "steps",
        ]

    def test_exactly_seven_fields(self):
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        result = json.loads(serialize_extraction_record(record))
        assert len(result) == 7

    def test_record_type_is_proof_trace(self):
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        result = json.loads(serialize_extraction_record(record))
        assert result["record_type"] == "proof_trace"

    def test_steps_length_equals_total_steps_plus_one(self):
        """Given total_steps=3, steps array has 4 elements."""
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        steps = [_make_step_0()]
        for i in range(1, 4):
            steps.append(_make_step(index=i))
        record = _make_extraction_record(total_steps=3, steps=steps)
        result = json.loads(serialize_extraction_record(record))
        assert len(result["steps"]) == 4
        assert result["total_steps"] == 3

    def test_step_count_mismatch_raises_value_error(self):
        """len(steps) != total_steps + 1 raises ValueError."""
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        # total_steps=3 but only 2 steps provided
        steps = [_make_step_0(), _make_step(index=1)]
        record = _make_extraction_record(total_steps=3, steps=steps)
        with pytest.raises(ValueError):
            serialize_extraction_record(record)

    def test_step_0_has_null_tactic(self):
        """steps[0].tactic is null in serialized output."""
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        result = json.loads(serialize_extraction_record(record))
        assert result["steps"][0]["tactic"] is None

    def test_steps_ordered_by_step_index_ascending(self):
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        steps = [_make_step_0()]
        for i in range(1, 4):
            steps.append(_make_step(index=i))
        record = _make_extraction_record(total_steps=3, steps=steps)
        result = json.loads(serialize_extraction_record(record))
        indices = [s["step_index"] for s in result["steps"]]
        assert indices == [0, 1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════
# §4.5 ExtractionStep Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionStepSerialization:
    """Spec §4.5: ExtractionStep has 6 fields, null diff when absent."""

    def test_field_ordering(self):
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        step = _make_step(index=1, tactic="intro.")
        result = json.loads(serialize_extraction_step(step))
        assert list(result.keys()) == [
            "step_index",
            "tactic",
            "goals",
            "focused_goal_index",
            "premises",
            "diff",
        ]

    def test_exactly_six_fields(self):
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        step = _make_step(index=1, tactic="intro.")
        result = json.loads(serialize_extraction_step(step))
        assert len(result) == 6

    def test_step_0_tactic_null_premises_empty_diff_null(self):
        """Step 0: tactic is null, premises is [], diff is null."""
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        step = _make_step_0()
        result = json.loads(serialize_extraction_step(step))
        assert result["tactic"] is None
        assert result["premises"] == []
        assert result["diff"] is None

    def test_diff_null_when_not_present(self):
        """diff is explicitly null, not omitted, when diffs disabled."""
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        step = _make_step(index=2, tactic="simpl.", diff=None)
        raw = serialize_extraction_step(step)
        result = json.loads(raw)
        assert "diff" in result
        assert result["diff"] is None
        assert '"diff":null' in raw

    def test_diff_present_when_provided(self):
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        diff = _make_extraction_diff()
        step = _make_step(index=1, tactic="intro.", diff=diff)
        result = json.loads(serialize_extraction_step(step))
        assert result["diff"] is not None
        assert isinstance(result["diff"], dict)


# ═══════════════════════════════════════════════════════════════════════════
# §4.6 Premise Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestPremiseSerialization:
    """Spec §4.6: Premise has 2 fields, valid kind values."""

    def test_field_ordering(self):
        (_, _, _, _, _, _, serialize_premise, _) = _import_output()
        p = _make_premise()
        result = json.loads(serialize_premise(p))
        assert list(result.keys()) == ["name", "kind"]

    def test_exactly_two_fields(self):
        (_, _, _, _, _, _, serialize_premise, _) = _import_output()
        p = _make_premise()
        result = json.loads(serialize_premise(p))
        assert len(result) == 2

    @pytest.mark.parametrize("kind", ["lemma", "hypothesis", "constructor", "definition"])
    def test_valid_kind_values(self, kind):
        (_, _, _, _, _, _, serialize_premise, _) = _import_output()
        p = _make_premise(kind=kind)
        result = json.loads(serialize_premise(p))
        assert result["kind"] == kind

    def test_invalid_kind_raises_value_error(self):
        (_, _, _, _, _, _, serialize_premise, _) = _import_output()
        p = _make_premise(kind="invalid_kind")
        with pytest.raises(ValueError):
            serialize_premise(p)


# ═══════════════════════════════════════════════════════════════════════════
# §4.7 ExtractionDiff Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionDiffSerialization:
    """Spec §4.7: ExtractionDiff has 6 array fields, all present when empty."""

    def test_field_ordering(self):
        (_, serialize_extraction_diff, *_) = _import_output()
        diff = _make_extraction_diff()
        result = json.loads(serialize_extraction_diff(diff))
        assert list(result.keys()) == [
            "goals_added",
            "goals_removed",
            "goals_changed",
            "hypotheses_added",
            "hypotheses_removed",
            "hypotheses_changed",
        ]

    def test_all_six_fields_present(self):
        (_, serialize_extraction_diff, *_) = _import_output()
        diff = _make_extraction_diff()
        result = json.loads(serialize_extraction_diff(diff))
        assert len(result) == 6

    def test_empty_arrays_serialized_not_omitted(self):
        """All array fields present as [] even when empty."""
        (_, serialize_extraction_diff, *_) = _import_output()
        diff = _make_extraction_diff()
        result = json.loads(serialize_extraction_diff(diff))
        for field in [
            "goals_added", "goals_removed", "goals_changed",
            "hypotheses_added", "hypotheses_removed", "hypotheses_changed",
        ]:
            assert field in result
            assert result[field] == []

    def test_non_empty_goals_added(self):
        (_, serialize_extraction_diff, *_) = _import_output()
        goal = _make_goal(index=1, type_="P -> Q")
        diff = _make_extraction_diff(goals_added=[goal])
        result = json.loads(serialize_extraction_diff(diff))
        assert len(result["goals_added"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# §4.8 ExtractionError Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionErrorSerialization:
    """Spec §4.8: ExtractionError has 7 fields, valid error_kind values."""

    def test_field_ordering(self):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error()
        result = json.loads(serialize_extraction_error(err))
        assert list(result.keys()) == [
            "schema_version",
            "record_type",
            "theorem_name",
            "source_file",
            "project_id",
            "error_kind",
            "error_message",
        ]

    def test_exactly_seven_fields(self):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error()
        result = json.loads(serialize_extraction_error(err))
        assert len(result) == 7

    def test_record_type_is_extraction_error(self):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error()
        result = json.loads(serialize_extraction_error(err))
        assert result["record_type"] == "extraction_error"

    @pytest.mark.parametrize(
        "error_kind",
        ["timeout", "backend_crash", "tactic_failure", "load_failure", "unknown"],
    )
    def test_valid_error_kind_values(self, error_kind):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error(error_kind=error_kind)
        result = json.loads(serialize_extraction_error(err))
        assert result["error_kind"] == error_kind

    def test_invalid_error_kind_raises_value_error(self):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error(error_kind="invalid_kind")
        with pytest.raises(ValueError):
            serialize_extraction_error(err)

    def test_timeout_error_message_template(self):
        """Timeout error_message follows template 'Proof extraction exceeded {n}s time limit'."""
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error(
            error_kind="timeout",
            error_message="Proof extraction exceeded 60s time limit",
        )
        result = json.loads(serialize_extraction_error(err))
        assert result["error_kind"] == "timeout"
        assert result["error_message"] == "Proof extraction exceeded 60s time limit"


# ═══════════════════════════════════════════════════════════════════════════
# §4.8 PartialExtractionRecord Serialization
# ═══════════════════════════════════════════════════════════════════════════


def _make_partial_extraction_record(
    theorem_name="Nat.sub_add",
    source_file="theories/Arith/PeanoNat.v",
    project_id="coq-stdlib",
    total_steps=12,
    completed_steps=4,
    failure_at_step=5,
    failure_kind="tactic_failure",
    failure_message="Tactic apply failed",
):
    from Poule.extraction.types import PartialExtractionRecord, ExtractionStep
    steps = []
    for i in range(completed_steps + 1):
        steps.append(ExtractionStep(
            step_index=i,
            tactic=None if i == 0 else f"tactic_{i}.",
            goals=[],
            focused_goal_index=0,
            premises=[],
            diff=None,
        ))
    return PartialExtractionRecord(
        schema_version=1,
        record_type="partial_proof_trace",
        theorem_name=theorem_name,
        source_file=source_file,
        project_id=project_id,
        total_steps=total_steps,
        completed_steps=completed_steps,
        failure_at_step=failure_at_step,
        failure_kind=failure_kind,
        failure_message=failure_message,
        steps=steps,
    )


class TestPartialExtractionRecordSerialization:
    """Spec §4.8: PartialExtractionRecord has 11 fields."""

    def test_field_ordering(self):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record()
        result = json.loads(serialize_partial_extraction_record(rec))
        assert list(result.keys()) == [
            "schema_version",
            "record_type",
            "theorem_name",
            "source_file",
            "project_id",
            "total_steps",
            "completed_steps",
            "failure_at_step",
            "failure_kind",
            "failure_message",
            "steps",
        ]

    def test_exactly_eleven_fields(self):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record()
        result = json.loads(serialize_partial_extraction_record(rec))
        assert len(result) == 11

    def test_record_type_is_partial_proof_trace(self):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record()
        result = json.loads(serialize_partial_extraction_record(rec))
        assert result["record_type"] == "partial_proof_trace"

    def test_steps_count_matches_completed_plus_one(self):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record(completed_steps=4)
        result = json.loads(serialize_partial_extraction_record(rec))
        assert len(result["steps"]) == 5  # completed_steps + 1

    @pytest.mark.parametrize("failure_kind", ["tactic_failure", "backend_crash"])
    def test_valid_failure_kind_values(self, failure_kind):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record(failure_kind=failure_kind)
        result = json.loads(serialize_partial_extraction_record(rec))
        assert result["failure_kind"] == failure_kind

    def test_invalid_failure_kind_raises_value_error(self):
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record(failure_kind="invalid")
        with pytest.raises(ValueError):
            serialize_partial_extraction_record(rec)

    def test_completed_steps_less_than_one_raises_value_error(self):
        """Spec §5: partial records require at least one completed tactic step."""
        from Poule.extraction.output import serialize_partial_extraction_record
        rec = _make_partial_extraction_record(completed_steps=0, failure_at_step=1)
        # Override steps to have only step 0
        from Poule.extraction.types import PartialExtractionRecord, ExtractionStep
        rec = PartialExtractionRecord(
            schema_version=1, record_type="partial_proof_trace",
            theorem_name="t", source_file="f.v", project_id="p",
            total_steps=5, completed_steps=0, failure_at_step=1,
            failure_kind="tactic_failure", failure_message="fail",
            steps=[ExtractionStep(step_index=0, tactic=None, goals=[], premises=[])],
        )
        with pytest.raises(ValueError):
            serialize_partial_extraction_record(rec)


# ═══════════════════════════════════════════════════════════════════════════
# §4.10 ExtractionSummary Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionSummarySerialization:
    """Spec §4.9: ExtractionSummary field ordering, per_project and per_file."""

    def test_field_ordering(self):
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        assert list(result.keys()) == [
            "schema_version",
            "record_type",
            "total_theorems_found",
            "total_extracted",
            "total_partial",
            "total_failed",
            "total_skipped",
            "per_project",
        ]

    def test_record_type_is_extraction_summary(self):
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        assert result["record_type"] == "extraction_summary"

    def test_per_project_field_ordering(self):
        """ProjectSummary fields: project_id, theorems_found, extracted, partial, failed, skipped, per_file."""
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        proj = result["per_project"][0]
        assert list(proj.keys()) == [
            "project_id",
            "theorems_found",
            "extracted",
            "partial",
            "failed",
            "skipped",
            "per_file",
        ]

    def test_per_file_field_ordering(self):
        """FileSummary fields: source_file, theorems_found, extracted, partial, failed, skipped."""
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        file_entry = result["per_project"][0]["per_file"][0]
        assert list(file_entry.keys()) == [
            "source_file",
            "theorems_found",
            "extracted",
            "partial",
            "failed",
            "skipped",
        ]

    def test_per_project_contains_per_file_breakdowns(self):
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        assert len(result["per_project"]) == 1
        assert len(result["per_project"][0]["per_file"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# §4.10 Determinism Contract
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminismContract:
    """Spec §4.10: Byte-identical output for identical input."""

    def test_campaign_metadata_deterministic(self):
        """Serialize same CampaignMetadata twice, get byte-identical output."""
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        output1 = serialize_campaign_metadata(meta)
        output2 = serialize_campaign_metadata(meta)
        assert output1 == output2

    def test_extraction_record_deterministic(self):
        """Serialize same ExtractionRecord twice, get byte-identical output."""
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        output1 = serialize_extraction_record(record)
        output2 = serialize_extraction_record(record)
        assert output1 == output2

    def test_extraction_error_deterministic(self):
        """Serialize same ExtractionError twice, get byte-identical output."""
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error()
        output1 = serialize_extraction_error(err)
        output2 = serialize_extraction_error(err)
        assert output1 == output2

    def test_extraction_summary_deterministic(self):
        """Serialize same ExtractionSummary twice, get byte-identical output."""
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        output1 = serialize_extraction_summary(summary)
        output2 = serialize_extraction_summary(summary)
        assert output1 == output2

    def test_compact_json_no_whitespace(self):
        """JSON output uses compact format (no whitespace)."""
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        output = serialize_campaign_metadata(meta)
        # Compact JSON has no spaces after separators
        assert ": " not in output
        assert ", " not in output

    def test_null_fields_explicitly_present(self):
        """Nullable fields are explicitly null, never omitted."""
        (_, _, _, _, serialize_extraction_step, *_) = _import_output()
        step = _make_step_0()
        raw = serialize_extraction_step(step)
        parsed = json.loads(raw)
        # tactic and diff are null for step 0
        assert "tactic" in parsed
        assert parsed["tactic"] is None
        assert "diff" in parsed
        assert parsed["diff"] is None
        # Verify literal null in JSON
        assert '"tactic":null' in raw
        assert '"diff":null' in raw

    def test_output_is_valid_utf8_without_bom(self):
        """Output is UTF-8 encoded without BOM."""
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        output = serialize_campaign_metadata(meta)
        encoded = output.encode("utf-8")
        # No BOM
        assert not encoded.startswith(b"\xef\xbb\xbf")

    def test_output_is_newline_terminated(self):
        """Each serialized record ends with a newline."""
        (
            serialize_campaign_metadata, _, serialize_extraction_error,
            serialize_extraction_record, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        for obj, serializer in [
            (_make_campaign_metadata(), serialize_campaign_metadata),
            (_make_extraction_record(), serialize_extraction_record),
            (_make_extraction_error(), serialize_extraction_error),
            (_make_extraction_summary(), serialize_extraction_summary),
        ]:
            output = serializer(obj)
            assert output.endswith("\n")

    def test_integer_formatting_no_decimals(self):
        """Integers without leading zeros or decimal points."""
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary(
            total_theorems_found=10, total_extracted=8,
            total_failed=2, total_skipped=0,
        )
        raw = serialize_extraction_summary(summary)
        parsed = json.loads(raw)
        # schema_version, total_theorems_found, etc. are ints
        assert isinstance(parsed["schema_version"], int)
        assert isinstance(parsed["total_theorems_found"], int)
        assert isinstance(parsed["total_extracted"], int)
        assert isinstance(parsed["total_failed"], int)
        assert isinstance(parsed["total_skipped"], int)


# ═══════════════════════════════════════════════════════════════════════════
# §4.11 Schema Version
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaVersion:
    """Spec §4.11: Initial extraction schema version is 1."""

    def test_campaign_metadata_schema_version_is_1(self):
        (serialize_campaign_metadata, *_) = _import_output()
        meta = _make_campaign_metadata()
        result = json.loads(serialize_campaign_metadata(meta))
        assert result["schema_version"] == 1

    def test_extraction_record_schema_version_is_1(self):
        (_, _, _, serialize_extraction_record, *_) = _import_output()
        record = _make_extraction_record()
        result = json.loads(serialize_extraction_record(record))
        assert result["schema_version"] == 1

    def test_extraction_error_schema_version_is_1(self):
        (_, _, serialize_extraction_error, *_) = _import_output()
        err = _make_extraction_error()
        result = json.loads(serialize_extraction_error(err))
        assert result["schema_version"] == 1

    def test_extraction_summary_schema_version_is_1(self):
        (_, _, _, _, _, serialize_extraction_summary, _, _) = _import_output()
        summary = _make_extraction_summary()
        result = json.loads(serialize_extraction_summary(summary))
        assert result["schema_version"] == 1

    def test_all_records_share_same_schema_version(self):
        """All record types in a single output share the same schema version."""
        (
            serialize_campaign_metadata, _, serialize_extraction_error,
            serialize_extraction_record, _, serialize_extraction_summary,
            _, _,
        ) = _import_output()

        versions = set()
        for obj, serializer in [
            (_make_campaign_metadata(), serialize_campaign_metadata),
            (_make_extraction_record(), serialize_extraction_record),
            (_make_extraction_error(), serialize_extraction_error),
            (_make_extraction_summary(), serialize_extraction_summary),
        ]:
            result = json.loads(serializer(obj))
            versions.add(result["schema_version"])

        assert len(versions) == 1
        assert versions.pop() == 1
