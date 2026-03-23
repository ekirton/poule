"""Extraction campaign orchestrator.

Plans and executes batch proof extraction across multiple Coq projects.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional, Union

from Poule.extraction.types import (
    CampaignMetadata,
    ExtractionError,
    ExtractionRecord,
    ExtractionStep,
    ExtractionSummary,
    FileSummary,
    PartialExtractionRecord,
    ProjectMetadata,
    ProjectSummary,
)
from Poule.session.errors import (
    BACKEND_CRASHED,
    FILE_NOT_FOUND,
    PROOF_NOT_FOUND,
    STEP_OUT_OF_RANGE,
    TACTIC_ERROR,
    SessionError,
)


# ---------------------------------------------------------------------------
# Campaign plan
# ---------------------------------------------------------------------------


@dataclass
class CampaignPlan:
    """Result of campaign planning: projects, targets, and skip count."""

    projects: list[ProjectMetadata] = field(default_factory=list)
    targets: list[tuple[str, str, str]] = field(default_factory=list)
    skipped_count: int = 0


# ---------------------------------------------------------------------------
# Index-based declaration enumeration
# ---------------------------------------------------------------------------


def fqn_to_proof_name(fqn: str, source_file: str) -> str:
    """Convert a fully-qualified index name to a document-internal proof name.

    Petanque's ``start`` command needs a name resolvable within the loaded
    document, not the full index FQN.  For example, the index stores
    ``Coq.Arith.PeanoNat.Nat.add_comm`` but Petanque needs ``Nat.add_comm``.

    The *source_file* (e.g. ``Arith/PeanoNat.v``) encodes the module suffix.
    Stripping that suffix from the FQN yields the document-internal name.
    """
    if "." not in fqn:
        return fqn
    # Derive module suffix from source_file: "Arith/PeanoNat.v" → "Arith.PeanoNat"
    module_suffix = source_file.replace("/", ".").removesuffix(".v")
    # Find module_suffix in the FQN and strip everything up to it
    idx = fqn.find(module_suffix)
    if idx >= 0:
        after = idx + len(module_suffix)
        if after < len(fqn) and fqn[after] == ".":
            return fqn[after + 1:]
        # module_suffix is at the end — no internal name beyond it
        # fall through to short-name fallback
    # Fallback: return the last dot-separated component
    return fqn.rsplit(".", 1)[-1]


def module_to_source_file(module: str, module_prefix: str) -> str:
    """Convert a dot-separated module path to a relative source file path.

    Strips *module_prefix* (e.g. ``"Coq."``) from *module*, replaces dots
    with ``/``, and appends ``.v``.  Handles ``Corelib.`` as an alias for
    ``Coq.`` (Rocq 9.x compatibility).
    """
    # Handle Corelib alias for stdlib
    if module_prefix == "Coq." and module.startswith("Corelib."):
        module = module[len("Corelib."):]
    elif module.startswith(module_prefix):
        module = module[len(module_prefix):]
    return module.replace(".", "/") + ".v"


def _enumerate_from_index(
    index_db_path: str,
    project_dirs: list[str],
    module_prefix: str,
) -> list[tuple[str, str, str, str]]:
    """Enumerate provable declarations from the SQLite index.

    Returns a list of ``(project_id, source_file, fqn, decl_kind)`` tuples,
    ordered by ``(module, name)`` within each project.
    """
    from Poule.storage.reader import IndexReader

    reader = IndexReader.open(index_db_path)
    try:
        decls = reader.get_provable_declarations(module_prefix=module_prefix)
    finally:
        reader.close()

    # For single-project use, map all declarations to the first project.
    # Multi-project enumeration with per-project prefixes is future work.
    project_id = Path(project_dirs[0]).name
    targets: list[tuple[str, str, str, str]] = []
    for decl in decls:
        source_file = module_to_source_file(decl["module"], module_prefix)
        targets.append((project_id, source_file, decl["name"], decl["kind"]))
    return targets


# ---------------------------------------------------------------------------
# build_campaign_plan
# ---------------------------------------------------------------------------


def build_campaign_plan(
    project_dirs: list[str],
    scope_filter=None,
    index_db_path: str | None = None,
    module_prefix: str | None = None,
) -> CampaignPlan:
    """Build a deterministic campaign plan from project directories.

    When *index_db_path* is provided, declarations are enumerated from
    the SQLite index.  Otherwise falls back to legacy regex enumeration
    (deprecated).

    Raises ``ValueError`` for empty *project_dirs* and a
    ``DIRECTORY_NOT_FOUND`` exception for nonexistent directories.
    """
    if not project_dirs:
        raise ValueError("project_dirs must not be empty")

    # Validate all directories exist before doing anything else.
    for d in project_dirs:
        if not Path(d).is_dir():
            raise RuntimeError(f"DIRECTORY_NOT_FOUND: {d}")

    # Assign project IDs with disambiguation for duplicate basenames.
    id_counts: dict[str, int] = {}
    projects: list[ProjectMetadata] = []
    dir_to_id: list[str] = []

    for d in project_dirs:
        base = Path(d).name
        id_counts[base] = id_counts.get(base, 0) + 1
        count = id_counts[base]
        project_id = base if count == 1 else f"{base}-{count}"
        projects.append(ProjectMetadata(
            project_id=project_id,
            project_path=str(Path(d).resolve()),
            coq_version="unknown",
        ))
        dir_to_id.append(project_id)

    if index_db_path is not None:
        return _build_plan_from_index(
            project_dirs, projects, dir_to_id,
            index_db_path, module_prefix or "", scope_filter,
        )

    # Legacy regex fallback — kept for backward compatibility with existing
    # tests that don't provide an index.  Will be removed in a future release.
    return _build_plan_from_regex(project_dirs, projects, dir_to_id, scope_filter)


def _build_plan_from_index(
    project_dirs: list[str],
    projects: list[ProjectMetadata],
    dir_to_id: list[str],
    index_db_path: str,
    module_prefix: str,
    scope_filter,
) -> CampaignPlan:
    """Build campaign plan using index-based enumeration."""
    from Poule.storage.reader import IndexReader

    reader = IndexReader.open(index_db_path)
    try:
        decls = reader.get_provable_declarations(
            module_prefix=module_prefix if module_prefix else None,
        )
    finally:
        reader.close()

    # Build targets, assigning each declaration to its project.
    targets: list[tuple[str, str, str, str]] = []
    skipped = 0
    prefix = module_prefix or ""

    for decl in decls:
        source_file = module_to_source_file(decl["module"], prefix)
        fqn = decl["name"]
        decl_kind = decl["kind"]

        # Use the first project's ID (single-project case) or match by prefix.
        project_id = dir_to_id[0]

        if scope_filter is not None and _should_skip(scope_filter, fqn):
            skipped += 1
            continue
        targets.append((project_id, source_file, fqn, decl_kind))

    return CampaignPlan(
        projects=projects,
        targets=targets,
        skipped_count=skipped,
    )


def _build_plan_from_regex(
    project_dirs: list[str],
    projects: list[ProjectMetadata],
    dir_to_id: list[str],
    scope_filter,
) -> CampaignPlan:
    """Legacy regex-based campaign plan builder (deprecated)."""
    import re

    _THEOREM_RE = re.compile(
        r"^\s*(?:Theorem|Lemma|Proposition|Corollary|Fact)\s+(\w+)\b",
        re.MULTILINE,
    )

    targets: list[tuple[str, str, str]] = []
    skipped = 0

    for idx, d in enumerate(project_dirs):
        project_id = dir_to_id[idx]
        v_files = sorted(Path(d).rglob("*.v"))

        for vf in v_files:
            rel = str(vf.relative_to(d))
            try:
                text = vf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            all_theorems = [m.group(1) for m in _THEOREM_RE.finditer(text)]

            for thm in all_theorems:
                if scope_filter is not None and _should_skip(scope_filter, thm):
                    skipped += 1
                    continue
                targets.append((project_id, rel, thm))

    return CampaignPlan(
        projects=projects,
        targets=targets,
        skipped_count=skipped,
    )


def _should_skip(scope_filter, theorem_name: str) -> bool:
    """Check if a theorem should be skipped based on the scope filter."""
    name_pattern = getattr(scope_filter, "name_pattern", None)
    if name_pattern is not None:
        if not fnmatch(theorem_name, name_pattern):
            return True
    module_prefixes = getattr(scope_filter, "module_prefixes", None)
    if module_prefixes is not None:
        # Module prefix filtering would require module context; skip for now
        pass
    return False


# ---------------------------------------------------------------------------
# extract_single_proof
# ---------------------------------------------------------------------------

# Map SessionError codes to ExtractionError error_kind values.
_ERROR_KIND_MAP = {
    BACKEND_CRASHED: "backend_crash",
    TACTIC_ERROR: "tactic_failure",
    FILE_NOT_FOUND: "load_failure",
    PROOF_NOT_FOUND: "no_proof_body",
    STEP_OUT_OF_RANGE: "no_proof_body",
}


async def extract_single_proof(
    session_manager,
    project_id: str,
    source_file: str,
    theorem_name: str,
    project_path: str = "",
) -> Union[ExtractionRecord, ExtractionError]:
    """Extract a single proof trace, returning a record or error.

    The session is always closed in a finally block.
    Backend liveness is enforced by the CoqBackend's watchdog (§7.4),
    not by a campaign-level budget timeout.
    """
    session_id: Optional[str] = None
    try:
        result = await _do_extraction(session_manager, project_id, source_file, theorem_name, project_path)
        return result
    except SessionError as e:
        error_kind = _ERROR_KIND_MAP.get(e.code, "unknown")
        return ExtractionError(
            schema_version=1,
            record_type="extraction_error",
            theorem_name=theorem_name,
            source_file=source_file,
            project_id=project_id,
            error_kind=error_kind,
            error_message=str(e),
        )
    except KeyboardInterrupt:
        raise
    except Exception as e:
        return ExtractionError(
            schema_version=1,
            record_type="extraction_error",
            theorem_name=theorem_name,
            source_file=source_file,
            project_id=project_id,
            error_kind="unknown",
            error_message=str(e),
        )


async def _do_extraction(
    session_manager,
    project_id: str,
    source_file: str,
    theorem_name: str,
    project_path: str = "",
) -> Union[ExtractionRecord, PartialExtractionRecord]:
    """Core extraction logic with guaranteed session cleanup."""
    session_id = None
    try:
        # Resolve to absolute path for the backend (§4.2, §10).
        abs_file = str(Path(project_path) / source_file) if project_path else source_file
        # Convert FQN to document-internal name for Petanque (§4.2).
        # The index stores "Coq.Arith.PeanoNat.Nat.add_comm" but Petanque
        # needs "Nat.add_comm" — the name resolvable within the document.
        proof_name = fqn_to_proof_name(theorem_name, source_file)
        session_id, _initial_state = await session_manager.create_session(
            abs_file, proof_name,
        )
        trace = await session_manager.extract_trace(session_id)
        premise_annotations = await session_manager.get_premises(session_id)

        # Build extraction steps from trace.
        steps: list[ExtractionStep] = []
        total_steps = getattr(trace, "total_steps", 0)
        if not isinstance(total_steps, int):
            total_steps = 0

        trace_steps = getattr(trace, "steps", [])
        try:
            trace_steps_list = list(trace_steps)
        except TypeError:
            trace_steps_list = []

        premise_map: dict = {}
        if premise_annotations:
            try:
                for pa in premise_annotations:
                    premise_map[pa.step_index] = pa.premises
            except TypeError:
                pass

        from Poule.extraction.types import (
            Goal as ExtGoal,
            Hypothesis as ExtHyp,
            Premise as ExtPremise,
        )

        for ts in trace_steps_list:
            step_idx = getattr(ts, "step_index", 0)
            premises_for_step = premise_map.get(step_idx, [])
            ext_premises = []
            try:
                ext_premises = [
                    ExtPremise(name=p.name, kind=p.kind)
                    for p in premises_for_step
                ]
            except (TypeError, AttributeError):
                pass

            goals = []
            state = getattr(ts, "state", None)
            focused = None
            if state is not None:
                focused = getattr(state, "focused_goal_index", None)
                state_goals = getattr(state, "goals", [])
                try:
                    for g in state_goals:
                        hyps_raw = getattr(g, "hypotheses", [])
                        hyps = []
                        try:
                            hyps = [
                                ExtHyp(name=h.name, type=h.type, body=getattr(h, "body", None))
                                for h in hyps_raw
                            ]
                        except (TypeError, AttributeError):
                            pass
                        goals.append(ExtGoal(index=g.index, type=g.type, hypotheses=hyps))
                except (TypeError, AttributeError):
                    pass

            steps.append(ExtractionStep(
                step_index=step_idx,
                tactic=getattr(ts, "tactic", None),
                goals=goals,
                focused_goal_index=focused,
                premises=ext_premises,
                diff=None,
            ))

        # Check if this is a partial trace
        is_partial = getattr(trace, "partial", False) is True
        if is_partial:
            failure_step = getattr(trace, "failure_step", None)
            failure_msg = getattr(trace, "failure_message", "")
            completed_steps = len(steps) - 1  # subtract step 0
            # Failure at step 1 (only initial state) → not worth recording
            if completed_steps < 1:
                raise SessionError(TACTIC_ERROR, failure_msg or "First tactic failed")
            return PartialExtractionRecord(
                schema_version=1,
                record_type="partial_proof_trace",
                theorem_name=theorem_name,
                source_file=source_file,
                project_id=project_id,
                total_steps=total_steps,
                completed_steps=completed_steps,
                failure_at_step=failure_step if failure_step is not None else completed_steps + 1,
                failure_kind="tactic_failure",
                failure_message=failure_msg,
                steps=steps,
            )

        return ExtractionRecord(
            schema_version=1,
            record_type="proof_trace",
            theorem_name=theorem_name,
            source_file=source_file,
            project_id=project_id,
            total_steps=total_steps,
            steps=steps,
        )
    finally:
        if session_id is not None:
            await session_manager.close_session(session_id)


# ---------------------------------------------------------------------------
# run_campaign
# ---------------------------------------------------------------------------


def _record_to_dict(record) -> dict:
    """Convert a dataclass record to a JSON-serializable dict."""
    from dataclasses import asdict
    return asdict(record)


async def run_campaign(
    project_dirs: list[str],
    output_path: str,
    kwargs: dict,
    **extra_kwargs,
) -> ExtractionSummary:
    """Run a full extraction campaign.

    Emits JSONL to *output_path*: CampaignMetadata first, then
    ExtractionRecord/ExtractionError per theorem, then ExtractionSummary.
    """
    # Merge kwargs
    all_kwargs = {**kwargs, **extra_kwargs}

    # Plan the campaign (validates dirs, may raise).
    plan = build_campaign_plan(
        project_dirs,
        scope_filter=all_kwargs.get("scope_filter"),
        index_db_path=all_kwargs.get("index_db_path"),
        module_prefix=all_kwargs.get("module_prefix"),
    )

    # Prepare per-project / per-file tracking.
    # project_id -> {file -> {extracted, failed, no_proof_body}}
    project_file_stats: dict[str, dict[str, dict[str, int]]] = {}
    for proj in plan.projects:
        project_file_stats[proj.project_id] = {}

    # Track total theorems found per project per file.
    project_file_found: dict[str, dict[str, int]] = {}
    for proj in plan.projects:
        project_file_found[proj.project_id] = {}

    # Count targets per project per file.
    # Targets may be 3-tuples (legacy) or 4-tuples (index-based).
    for target in plan.targets:
        project_id, source_file = target[0], target[1]
        pf = project_file_found.setdefault(project_id, {})
        pf[source_file] = pf.get(source_file, 0) + 1
        ps = project_file_stats.setdefault(project_id, {})
        if source_file not in ps:
            ps[source_file] = {"extracted": 0, "failed": 0, "no_proof_body": 0}

    # Also track files with no theorems for per-file summary.
    for proj in plan.projects:
        proj_path = Path(proj.project_path)
        for vf in sorted(proj_path.rglob("*.v")):
            rel = str(vf.relative_to(proj_path))
            pf = project_file_found.setdefault(proj.project_id, {})
            if rel not in pf:
                pf[rel] = 0
            ps = project_file_stats.setdefault(proj.project_id, {})
            if rel not in ps:
                ps[rel] = {"extracted": 0, "failed": 0, "no_proof_body": 0}

    # Emit campaign metadata.
    metadata = CampaignMetadata(
        schema_version=1,
        record_type="campaign_metadata",
        extraction_tool_version="0.1.0",
        extraction_timestamp=datetime.now(timezone.utc).isoformat(),
        projects=plan.projects,
    )

    # Build project_id -> project_path mapping for path resolution.
    project_path_map = {p.project_id: p.project_path for p in plan.projects}

    total_targets = len(plan.targets)
    print(f"Campaign: {total_targets} theorems to extract", file=sys.stderr)

    # Stream results to JSONL file incrementally so progress is visible.
    outfile = open(output_path, "w", encoding="utf-8")
    outfile.write(json.dumps(_record_to_dict(metadata), default=str) + "\n")
    outfile.flush()

    # Extract each target.
    interrupted = False
    extracted_count = 0
    failed_count = 0
    no_proof_body_count = 0
    current_file = None
    for idx, target in enumerate(plan.targets, 1):
        project_id, source_file, theorem_name = target[0], target[1], target[2]
        if source_file != current_file:
            current_file = source_file
            print(f"  [{idx}/{total_targets}] {source_file}", file=sys.stderr)

        try:
            result = await extract_single_proof(
                all_kwargs.get("session_manager", _NullSessionManager()),
                project_id,
                source_file,
                theorem_name,
                project_path=project_path_map.get(project_id, ""),
            )
        except KeyboardInterrupt:
            interrupted = True
            break

        # Write result to disk immediately.
        outfile.write(json.dumps(_record_to_dict(result), default=str) + "\n")
        outfile.flush()

        # Update stats.
        fs = project_file_stats[project_id][source_file]
        if isinstance(result, ExtractionRecord):
            fs["extracted"] += 1
            extracted_count += 1
        elif isinstance(result, ExtractionError) and result.error_kind == "no_proof_body":
            fs["no_proof_body"] += 1
            no_proof_body_count += 1
        else:
            fs["failed"] += 1
            failed_count += 1

        if idx % 100 == 0:
            print(
                f"  Progress: {idx}/{total_targets}"
                f" ({extracted_count} ok, {failed_count} err,"
                f" {no_proof_body_count} no body)",
                file=sys.stderr,
            )

    # Build summary.
    per_project: list[ProjectSummary] = []
    total_found = 0
    total_extracted = 0
    total_failed = 0
    total_no_proof_body = 0
    total_skipped = plan.skipped_count

    for proj in plan.projects:
        pid = proj.project_id
        file_stats = project_file_stats.get(pid, {})
        file_found = project_file_found.get(pid, {})

        per_file: list[FileSummary] = []
        proj_found = 0
        proj_extracted = 0
        proj_failed = 0
        proj_no_proof_body = 0

        for sf in sorted(file_found.keys()):
            found = file_found[sf]
            stats = file_stats.get(sf, {"extracted": 0, "failed": 0, "no_proof_body": 0})
            extracted = stats["extracted"]
            failed = stats["failed"]
            npb = stats["no_proof_body"]
            skipped = found - extracted - failed - npb
            if skipped < 0:
                skipped = 0

            per_file.append(FileSummary(
                source_file=sf,
                theorems_found=found,
                extracted=extracted,
                failed=failed,
                no_proof_body=npb,
                skipped=skipped,
            ))

            proj_found += found
            proj_extracted += extracted
            proj_failed += failed
            proj_no_proof_body += npb

        proj_skipped = proj_found - proj_extracted - proj_failed - proj_no_proof_body
        if proj_skipped < 0:
            proj_skipped = 0

        per_project.append(ProjectSummary(
            project_id=pid,
            theorems_found=proj_found,
            extracted=proj_extracted,
            failed=proj_failed,
            no_proof_body=proj_no_proof_body,
            skipped=proj_skipped,
            per_file=per_file,
        ))

        total_found += proj_found
        total_extracted += proj_extracted
        total_failed += proj_failed
        total_no_proof_body += proj_no_proof_body

    # Adjust total_skipped to maintain the invariant.
    total_skipped = total_found - total_extracted - total_failed - total_no_proof_body
    if total_skipped < 0:
        total_skipped = 0

    summary = ExtractionSummary(
        schema_version=1,
        record_type="extraction_summary",
        total_theorems_found=total_found,
        total_extracted=total_extracted,
        total_failed=total_failed,
        total_no_proof_body=total_no_proof_body,
        total_skipped=total_skipped,
        per_project=per_project,
    )

    # Write final summary record and close the output file.
    outfile.write(json.dumps(_record_to_dict(summary), default=str) + "\n")
    outfile.close()

    return summary


class _NullSessionManager:
    """Fallback session manager that always returns errors."""

    async def create_session(self, file_path, proof_name):
        raise SessionError(FILE_NOT_FOUND, f"No session manager configured")

    async def extract_trace(self, session_id):
        raise SessionError(FILE_NOT_FOUND, "No session manager configured")

    async def get_premises(self, session_id):
        raise SessionError(FILE_NOT_FOUND, "No session manager configured")

    async def close_session(self, session_id):
        pass
