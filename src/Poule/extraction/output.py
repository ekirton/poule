"""JSON Lines serialization for extraction types.

Each serialize function takes a typed object and returns a compact JSON string
ending with a newline character. Field ordering matches the specification.

Spec: specification/extraction-output.md
"""

from __future__ import annotations

import json
from typing import Any

from Poule.extraction.types import (
    CampaignMetadata,
    ExtractionDiff,
    ExtractionError,
    ExtractionRecord,
    ExtractionStep,
    ExtractionSummary,
    FileSummary,
    Goal,
    GoalChange,
    Hypothesis,
    HypothesisChange,
    PartialExtractionRecord,
    Premise,
    ProjectMetadata,
    ProjectSummary,
)

_VALID_PREMISE_KINDS = frozenset({"lemma", "hypothesis", "constructor", "definition"})
_VALID_ERROR_KINDS = frozenset(
    {"timeout", "backend_crash", "tactic_failure", "load_failure", "unknown"}
)
_VALID_FAILURE_KINDS = frozenset({"tactic_failure", "backend_crash"})


def _compact(obj: dict[str, Any]) -> str:
    """Serialize dict to compact JSON with newline terminator."""
    return json.dumps(obj, separators=(",", ":")) + "\n"


def _hypothesis_to_dict(h: Hypothesis) -> dict[str, Any]:
    return {
        "name": h.name,
        "type": h.type,
        "body": h.body,
    }


def _goal_to_dict(g: Goal) -> dict[str, Any]:
    return {
        "index": g.index,
        "type": g.type,
        "hypotheses": [_hypothesis_to_dict(h) for h in g.hypotheses],
    }


def _goal_change_to_dict(gc: GoalChange) -> dict[str, Any]:
    return {
        "index": gc.index,
        "before": gc.before,
        "after": gc.after,
    }


def _hypothesis_change_to_dict(hc: HypothesisChange) -> dict[str, Any]:
    return {
        "name": hc.name,
        "type_before": hc.type_before,
        "type_after": hc.type_after,
        "body_before": hc.body_before,
        "body_after": hc.body_after,
    }


def _premise_to_dict(p: Premise) -> dict[str, Any]:
    return {
        "name": p.name,
        "kind": p.kind,
    }


def _diff_to_dict(d: ExtractionDiff) -> dict[str, Any]:
    return {
        "goals_added": [_goal_to_dict(g) for g in d.goals_added],
        "goals_removed": [_goal_to_dict(g) for g in d.goals_removed],
        "goals_changed": [_goal_change_to_dict(gc) for gc in d.goals_changed],
        "hypotheses_added": [_hypothesis_to_dict(h) for h in d.hypotheses_added],
        "hypotheses_removed": [_hypothesis_to_dict(h) for h in d.hypotheses_removed],
        "hypotheses_changed": [
            _hypothesis_change_to_dict(hc) for hc in d.hypotheses_changed
        ],
    }


def _step_to_dict(step: ExtractionStep) -> dict[str, Any]:
    return {
        "step_index": step.step_index,
        "tactic": step.tactic,
        "goals": [_goal_to_dict(g) for g in step.goals],
        "focused_goal_index": step.focused_goal_index,
        "premises": [_premise_to_dict(p) for p in step.premises],
        "diff": _diff_to_dict(step.diff) if step.diff is not None else None,
    }


def _file_summary_to_dict(fs: FileSummary) -> dict[str, Any]:
    return {
        "source_file": fs.source_file,
        "theorems_found": fs.theorems_found,
        "extracted": fs.extracted,
        "partial": fs.partial,
        "failed": fs.failed,
        "skipped": fs.skipped,
    }


def _project_summary_to_dict(ps: ProjectSummary) -> dict[str, Any]:
    return {
        "project_id": ps.project_id,
        "theorems_found": ps.theorems_found,
        "extracted": ps.extracted,
        "partial": ps.partial,
        "failed": ps.failed,
        "skipped": ps.skipped,
        "per_file": [_file_summary_to_dict(fs) for fs in ps.per_file],
    }


def _project_metadata_to_dict(pm: ProjectMetadata) -> dict[str, Any]:
    return {
        "project_id": pm.project_id,
        "project_path": pm.project_path,
        "coq_version": pm.coq_version,
        "commit_hash": pm.commit_hash,
    }


def serialize_campaign_metadata(meta: CampaignMetadata) -> str:
    """Serialize CampaignMetadata to a compact JSON line."""
    obj = {
        "schema_version": meta.schema_version,
        "record_type": meta.record_type,
        "extraction_tool_version": meta.extraction_tool_version,
        "extraction_timestamp": meta.extraction_timestamp,
        "projects": [_project_metadata_to_dict(p) for p in meta.projects],
    }
    return _compact(obj)


def serialize_project_metadata(pm: ProjectMetadata) -> str:
    """Serialize ProjectMetadata to a compact JSON line."""
    return _compact(_project_metadata_to_dict(pm))


def serialize_extraction_record(record: ExtractionRecord) -> str:
    """Serialize ExtractionRecord to a compact JSON line.

    Raises ValueError if len(steps) != total_steps + 1.
    """
    if len(record.steps) != record.total_steps + 1:
        raise ValueError(
            f"Step count mismatch: expected {record.total_steps + 1} steps "
            f"(total_steps + 1), got {len(record.steps)}"
        )
    obj = {
        "schema_version": record.schema_version,
        "record_type": record.record_type,
        "theorem_name": record.theorem_name,
        "source_file": record.source_file,
        "project_id": record.project_id,
        "total_steps": record.total_steps,
        "steps": [_step_to_dict(s) for s in record.steps],
    }
    return _compact(obj)


def serialize_extraction_step(step: ExtractionStep) -> str:
    """Serialize ExtractionStep to a compact JSON line."""
    return _compact(_step_to_dict(step))


def serialize_partial_extraction_record(record: PartialExtractionRecord) -> str:
    """Serialize PartialExtractionRecord to a compact JSON line.

    Raises ValueError if completed_steps < 1 or failure_kind is invalid.
    """
    if record.completed_steps < 1:
        raise ValueError(
            f"Partial records require at least one completed tactic step, "
            f"got completed_steps={record.completed_steps}"
        )
    if len(record.steps) != record.completed_steps + 1:
        raise ValueError(
            f"Step count mismatch: expected {record.completed_steps + 1} steps "
            f"(completed_steps + 1), got {len(record.steps)}"
        )
    if record.failure_kind not in _VALID_FAILURE_KINDS:
        raise ValueError(
            f"Invalid failure_kind: {record.failure_kind!r}. "
            f"Must be one of {sorted(_VALID_FAILURE_KINDS)}"
        )
    obj = {
        "schema_version": record.schema_version,
        "record_type": record.record_type,
        "theorem_name": record.theorem_name,
        "source_file": record.source_file,
        "project_id": record.project_id,
        "total_steps": record.total_steps,
        "completed_steps": record.completed_steps,
        "failure_at_step": record.failure_at_step,
        "failure_kind": record.failure_kind,
        "failure_message": record.failure_message,
        "steps": [_step_to_dict(s) for s in record.steps],
    }
    return _compact(obj)


def serialize_extraction_error(err: ExtractionError) -> str:
    """Serialize ExtractionError to a compact JSON line.

    Raises ValueError if error_kind is not a valid value.
    """
    if err.error_kind not in _VALID_ERROR_KINDS:
        raise ValueError(
            f"Invalid error_kind: {err.error_kind!r}. "
            f"Must be one of {sorted(_VALID_ERROR_KINDS)}"
        )
    obj = {
        "schema_version": err.schema_version,
        "record_type": err.record_type,
        "theorem_name": err.theorem_name,
        "source_file": err.source_file,
        "project_id": err.project_id,
        "error_kind": err.error_kind,
        "error_message": err.error_message,
    }
    return _compact(obj)


def serialize_extraction_summary(summary: ExtractionSummary) -> str:
    """Serialize ExtractionSummary to a compact JSON line."""
    obj = {
        "schema_version": summary.schema_version,
        "record_type": summary.record_type,
        "total_theorems_found": summary.total_theorems_found,
        "total_extracted": summary.total_extracted,
        "total_partial": summary.total_partial,
        "total_failed": summary.total_failed,
        "total_skipped": summary.total_skipped,
        "per_project": [_project_summary_to_dict(ps) for ps in summary.per_project],
    }
    return _compact(obj)


def serialize_extraction_diff(diff: ExtractionDiff) -> str:
    """Serialize ExtractionDiff to a compact JSON line."""
    return _compact(_diff_to_dict(diff))


def serialize_premise(p: Premise) -> str:
    """Serialize Premise to a compact JSON line.

    Raises ValueError if kind is not a valid premise kind.
    """
    if p.kind not in _VALID_PREMISE_KINDS:
        raise ValueError(
            f"Invalid premise kind: {p.kind!r}. "
            f"Must be one of {sorted(_VALID_PREMISE_KINDS)}"
        )
    return _compact(_premise_to_dict(p))
