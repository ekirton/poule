"""Extraction campaign orchestrator.

Plans and executes batch proof extraction across multiple Coq projects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from itertools import groupby
from pathlib import Path
from typing import Optional, Union

from Poule.extraction.types import (
    CampaignMetadata,
    ExtractionError,
    ExtractionRecord,
    ExtractionStep,
    ExtractionSummary,
    FileSummary,
    Goal as ExtGoal,
    Hypothesis as ExtHyp,
    PartialExtractionRecord,
    Premise as ExtPremise,
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

logger = logging.getLogger(__name__)


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

    Strips *module_prefix* (e.g. ``"Stdlib."``) from *module*, replaces dots
    with ``/``, and appends ``.v``.  Handles ``Corelib.`` as an alias for
    ``Stdlib.`` (Rocq 9.x compatibility).
    """
    # Handle Corelib alias for stdlib
    if module_prefix == "Stdlib." and module.startswith("Corelib."):
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
    from Poule.storage.errors import StorageError

    try:
        reader = IndexReader.open(index_db_path)
    except StorageError as e:
        raise RuntimeError(f"INDEX_NOT_FOUND: {e}") from e
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

    Declarations are enumerated from the SQLite index at *index_db_path*.

    Raises ``ValueError`` for empty *project_dirs* or missing
    *index_db_path*, and a ``DIRECTORY_NOT_FOUND`` exception for
    nonexistent directories.
    """
    if not project_dirs:
        raise ValueError("project_dirs must not be empty")
    if index_db_path is None:
        raise ValueError("index_db_path is required")

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

    return _build_plan_from_index(
        project_dirs, projects, dir_to_id,
        index_db_path, module_prefix or "", scope_filter,
    )


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
    from Poule.storage.errors import StorageError

    try:
        reader = IndexReader.open(index_db_path)
    except StorageError as e:
        raise RuntimeError(f"INDEX_NOT_FOUND: {e}") from e
    try:
        # Try with has_proof_body filter first (indexes built with annotation).
        prefix_arg = module_prefix if module_prefix else None
        decls = reader.get_provable_declarations(
            module_prefix=prefix_arg,
            has_proof_body=True,
        )
        # Fallback: if no results (older index without annotations), retry unfiltered.
        if not decls:
            decls = reader.get_provable_declarations(
                module_prefix=prefix_arg,
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
# File-grouped extraction (§4.3)
# ---------------------------------------------------------------------------


def _group_targets_by_file(
    targets: list[tuple],
) -> list[tuple[str, str, list[str]]]:
    """Group contiguous targets by (project_id, source_file).

    Returns list of ``(project_id, source_file, [theorem_name, ...])``.
    Targets are already ordered by ``(module, name)`` from the index, so
    same-file targets are contiguous.
    """
    groups: list[tuple[str, str, list[str]]] = []
    for (pid, sf), items in groupby(targets, key=lambda t: (t[0], t[1])):
        theorems = [t[2] for t in items]
        groups.append((pid, sf, theorems))
    return groups


def _convert_proof_state(state) -> tuple[list[ExtGoal], int | None]:
    """Convert a session-level ProofState into extraction-level goals."""
    focused = getattr(state, "focused_goal_index", None)
    goals: list[ExtGoal] = []
    for g in getattr(state, "goals", []):
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
    return goals, focused


async def _extract_one_on_backend(
    backend,
    project_id: str,
    source_file: str,
    theorem_name: str,
) -> Union[ExtractionRecord, PartialExtractionRecord, ExtractionError]:
    """Extract a single proof trace from an already-loaded backend.

    The backend must already have the file loaded via ``load_file``.
    This function calls ``position_at_proof`` (which resets per-proof state),
    queries goals for each pre-computed state token, queries premises per
    step, and assembles an ExtractionRecord.
    """
    proof_name = fqn_to_proof_name(theorem_name, source_file)

    # Position at proof — resets original_script and _original_states
    try:
        initial_state = await backend.position_at_proof(proof_name)
    except (ValueError, KeyError, LookupError) as exc:
        return ExtractionError(
            schema_version=1, record_type="extraction_error",
            theorem_name=theorem_name, source_file=source_file,
            project_id=project_id, error_kind="no_proof_body",
            error_message=str(exc),
        )

    original_script = getattr(backend, "original_script", []) or []
    total_steps = len(original_script)
    original_states = getattr(backend, "_original_states", [])

    # Step 0: initial state
    goals_0, focused_0 = _convert_proof_state(initial_state)
    steps: list[ExtractionStep] = [ExtractionStep(
        step_index=0, tactic=None, goals=goals_0,
        focused_goal_index=focused_0, premises=[], diff=None,
    )]

    failure_step: int | None = None
    failure_message = ""

    # Steps 1..N via pre-computed state tokens
    for i in range(1, min(len(original_states), total_steps + 1)):
        st_token = original_states[i]
        try:
            goals_result = await backend._petanque_goals(st_token)
            state = backend._translate_petanque_goals(goals_result, step_index=i)
        except Exception as exc:
            failure_step = i
            failure_message = str(exc)
            break

        goals_i, focused_i = _convert_proof_state(state)

        # Premises for this step
        ext_premises: list[ExtPremise] = []
        try:
            raw = await backend.get_premises_at_step(i)
            ext_premises = [
                ExtPremise(name=p["name"], kind=p["kind"]) for p in raw
            ]
        except Exception:
            pass

        steps.append(ExtractionStep(
            step_index=i, tactic=original_script[i - 1], goals=goals_i,
            focused_goal_index=focused_i, premises=ext_premises, diff=None,
        ))

    # If original_states is shorter than total_steps, some tactics failed
    if failure_step is None and len(original_states) <= total_steps:
        if len(original_states) < total_steps + 1:
            failure_step = len(original_states)
            failure_message = "Backend replay failed during positioning"

    # Handle partial trace
    if failure_step is not None:
        completed = len(steps) - 1  # subtract step 0
        if completed < 1:
            return ExtractionError(
                schema_version=1, record_type="extraction_error",
                theorem_name=theorem_name, source_file=source_file,
                project_id=project_id, error_kind="tactic_failure",
                error_message=failure_message or "First tactic failed",
            )
        return PartialExtractionRecord(
            schema_version=1, record_type="partial_proof_trace",
            theorem_name=theorem_name, source_file=source_file,
            project_id=project_id, total_steps=total_steps,
            completed_steps=completed,
            failure_at_step=failure_step,
            failure_kind="tactic_failure",
            failure_message=failure_message,
            steps=steps,
        )

    return ExtractionRecord(
        schema_version=1, record_type="proof_trace",
        theorem_name=theorem_name, source_file=source_file,
        project_id=project_id, total_steps=total_steps,
        steps=steps,
    )


async def _extract_file_group(
    backend_factory,
    watchdog_timeout: float | None,
    project_id: str,
    source_file: str,
    theorem_names: list[str],
    project_path: str,
    rss_threshold: int | None = None,
    load_paths: list[tuple[str, str]] | None = None,
) -> list[Union[ExtractionRecord, PartialExtractionRecord, ExtractionError]]:
    """Extract all proofs from one file using a single backend.

    Creates one backend, loads the file once, then extracts each theorem.
    The backend is shut down in a ``finally`` block.

    When *rss_threshold* is set (bytes), the backend's RSS is checked
    after each proof.  If it exceeds the threshold the backend is
    restarted and the file reloaded for the remaining theorems.

    When *load_paths* is provided, each ``(directory, prefix)`` pair is
    passed to the backend factory as ``-R`` flags so bare imports resolve.
    """
    abs_file = str(Path(project_path) / source_file) if project_path else source_file
    results: list[Union[ExtractionRecord, PartialExtractionRecord, ExtractionError]] = []
    backend = None

    async def _spawn_and_load():
        factory_kwargs: dict = {}
        if watchdog_timeout:
            factory_kwargs["watchdog_timeout"] = watchdog_timeout
        if load_paths:
            factory_kwargs["load_paths"] = load_paths
        b = await backend_factory(abs_file, **factory_kwargs)
        try:
            await b.load_file(abs_file)
        except Exception:
            await b.shutdown()
            raise
        return b

    try:
        try:
            backend = await _spawn_and_load()
        except Exception as exc:
            # File load failed — all theorems get load_failure
            for thm in theorem_names:
                results.append(ExtractionError(
                    schema_version=1, record_type="extraction_error",
                    theorem_name=thm, source_file=source_file,
                    project_id=project_id, error_kind="load_failure",
                    error_message=str(exc),
                ))
            return results

        # Post-load RSS check: warn if type-checking alone exceeds threshold.
        if rss_threshold is not None and backend is not None:
            rss = getattr(backend, "get_rss_bytes", lambda: 0)()
            if rss > rss_threshold:
                logger.warning(
                    "RSS after loading %s already exceeds threshold "
                    "(%.0f MiB > %.0f MiB); extraction will proceed but "
                    "OOM risk is elevated",
                    source_file, rss / (1024 * 1024),
                    rss_threshold / (1024 * 1024),
                )

        for thm in theorem_names:
            try:
                result = await _extract_one_on_backend(
                    backend, project_id, source_file, thm,
                )
                results.append(result)
            except ConnectionError as exc:
                # Backend crashed — fail current + remaining theorems
                results.append(ExtractionError(
                    schema_version=1, record_type="extraction_error",
                    theorem_name=thm, source_file=source_file,
                    project_id=project_id, error_kind="backend_crash",
                    error_message=str(exc),
                ))
                remaining_start = len(results)
                for remaining_thm in theorem_names[remaining_start:]:
                    results.append(ExtractionError(
                        schema_version=1, record_type="extraction_error",
                        theorem_name=remaining_thm, source_file=source_file,
                        project_id=project_id, error_kind="backend_crash",
                        error_message="Backend crashed on earlier proof",
                    ))
                break
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                results.append(ExtractionError(
                    schema_version=1, record_type="extraction_error",
                    theorem_name=thm, source_file=source_file,
                    project_id=project_id, error_kind="unknown",
                    error_message=str(exc),
                ))

            # RSS check: restart backend if memory usage exceeds threshold.
            if rss_threshold is not None and backend is not None:
                rss = getattr(backend, "get_rss_bytes", lambda: 0)()
                if rss > rss_threshold:
                    logger.debug(
                        "Restarting coq-lsp for %s (RSS=%.0f MiB, threshold=%.0f MiB)",
                        source_file, rss / (1024 * 1024),
                        rss_threshold / (1024 * 1024),
                    )
                    try:
                        await backend.shutdown()
                    except Exception:
                        pass
                    try:
                        backend = await _spawn_and_load()
                    except Exception as exc:
                        # Restart failed — fail remaining theorems
                        remaining_start = len(results)
                        for remaining_thm in theorem_names[remaining_start:]:
                            results.append(ExtractionError(
                                schema_version=1, record_type="extraction_error",
                                theorem_name=remaining_thm, source_file=source_file,
                                project_id=project_id, error_kind="load_failure",
                                error_message=f"Backend restart failed: {exc}",
                            ))
                        backend = None
                        break
    finally:
        if backend is not None:
            try:
                await backend.shutdown()
            except Exception:
                pass

    return results


# ---------------------------------------------------------------------------
# extract_single_proof (legacy per-proof path)
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
        # The index stores "Stdlib.Arith.PeanoNat.Nat.add_comm" but Petanque
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

    # Extract targets.
    interrupted = False
    extracted_count = 0
    failed_count = 0
    no_proof_body_count = 0
    idx = 0

    backend_factory = all_kwargs.get("backend_factory")
    watchdog_timeout = all_kwargs.get("watchdog_timeout")
    workers = all_kwargs.get("workers", 1)
    rss_threshold = all_kwargs.get("rss_threshold")

    # Derive load_paths from module_prefix + project_path for bare imports.
    module_prefix = all_kwargs.get("module_prefix")
    load_paths: list[tuple[str, str]] | None = None
    if module_prefix and plan.projects:
        prefix_bare = module_prefix.rstrip(".")
        proj_path = plan.projects[0].project_path
        load_paths = [(proj_path, prefix_bare)]

    if backend_factory is not None:
        # File-grouped extraction: one backend per source file (§4.3).
        file_groups = _group_targets_by_file(plan.targets)

        async def _process_group(pid, sf, thms):
            return await _extract_file_group(
                backend_factory, watchdog_timeout,
                pid, sf, thms,
                project_path=project_path_map.get(pid, ""),
                rss_threshold=rss_threshold,
                load_paths=load_paths,
            )

        if workers > 1:
            # Parallel file processing with bounded concurrency.
            sem = asyncio.Semaphore(workers)

            async def _bounded(pid, sf, thms):
                async with sem:
                    return await _process_group(pid, sf, thms)

            # Process all file groups concurrently, write results in plan order.
            tasks = [
                asyncio.ensure_future(_bounded(pid, sf, thms))
                for pid, sf, thms in file_groups
            ]
            group_results = await asyncio.gather(*tasks)
            for (pid, sf, thms), results in zip(file_groups, group_results):
                print(f"  [{idx + 1}/{total_targets}] {sf}", file=sys.stderr)
                for result in results:
                    idx += 1
                    outfile.write(json.dumps(_record_to_dict(result), default=str) + "\n")
                    outfile.flush()
                    fs = project_file_stats[pid][sf]
                    if isinstance(result, ExtractionRecord):
                        fs["extracted"] += 1
                        extracted_count += 1
                    elif isinstance(result, ExtractionError) and result.error_kind == "no_proof_body":
                        fs["no_proof_body"] += 1
                        no_proof_body_count += 1
                    else:
                        fs["failed"] += 1
                        failed_count += 1
        else:
            # Sequential file processing (default).
            for pid, sf, thms in file_groups:
                idx += 1
                print(f"  [{idx}/{total_targets}] {sf} ({len(thms)} theorems)", file=sys.stderr)
                try:
                    results = await _process_group(pid, sf, thms)
                except KeyboardInterrupt:
                    interrupted = True
                    break

                for result in results:
                    outfile.write(json.dumps(_record_to_dict(result), default=str) + "\n")
                    outfile.flush()
                    fs = project_file_stats[pid][sf]
                    if isinstance(result, ExtractionRecord):
                        fs["extracted"] += 1
                        extracted_count += 1
                    elif isinstance(result, ExtractionError) and result.error_kind == "no_proof_body":
                        fs["no_proof_body"] += 1
                        no_proof_body_count += 1
                    else:
                        fs["failed"] += 1
                        failed_count += 1

                idx += len(thms) - 1
                if idx % 100 < len(thms):
                    print(
                        f"  Progress: {idx}/{total_targets}"
                        f" ({extracted_count} ok, {failed_count} err,"
                        f" {no_proof_body_count} no body)",
                        file=sys.stderr,
                    )
    else:
        # Legacy per-proof extraction via SessionManager.
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

            outfile.write(json.dumps(_record_to_dict(result), default=str) + "\n")
            outfile.flush()

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
