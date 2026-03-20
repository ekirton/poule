"""Proof Profiling Engine — entry points and subprocess management.

Spec: specification/proof-profiling.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union

from Poule.profiler.boundaries import (
    classify_sentence,
    detect_proof_boundaries,
    resolve_line_numbers,
)
from Poule.profiler.bottleneck import classify_bottlenecks
from Poule.profiler.comparison import match_sentences
from Poule.profiler.parser import parse_ltac_profile, parse_timing_output
from Poule.profiler.types import (
    FileProfile,
    LtacProfile,
    ProfileRequest,
    ProofBoundary,
    ProofProfile,
    TimingComparison,
    TimingDiff,
    TimingSentence,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 4.1 Request Validation
# ---------------------------------------------------------------------------

def validate_request(request: ProfileRequest) -> Optional[str]:
    """Validate a ProfileRequest.

    Returns None if valid, or an error message string describing the failure.
    """
    p = Path(request.file_path)
    if not p.suffix == ".v":
        return f"INVALID_FILE: file_path must end with .v, got '{p.suffix}'"

    if request.mode == "ltac" and request.lemma_name is None:
        return "INVALID_REQUEST: Ltac profiling requires a lemma name"

    if request.mode == "compare":
        if request.baseline_path is None:
            return "INVALID_REQUEST: Compare mode requires a baseline timing file"
        if not Path(request.baseline_path).exists():
            return f"FILE_NOT_FOUND: baseline file not found: {request.baseline_path}"

    if not p.exists():
        return f"FILE_NOT_FOUND: file not found: {request.file_path}"

    return None


# ---------------------------------------------------------------------------
# 4.2 Binary Discovery
# ---------------------------------------------------------------------------

def locate_coqc() -> Union[str, str]:
    """Locate the coqc binary on PATH.

    Returns the absolute path as a string if found, or an error message
    string if not found.
    """
    path = shutil.which("coqc")
    if path is None:
        return "TOOL_MISSING: coqc not found on PATH"
    return path


# ---------------------------------------------------------------------------
# 4.3 Path Resolution
# ---------------------------------------------------------------------------

def resolve_paths(file_path: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Resolve include paths and load paths from _CoqProject.

    Searches for _CoqProject in the file's directory and ancestors.
    Returns (load_paths, include_paths) where load_paths is a list of
    (logical_prefix, physical_directory) tuples.
    """
    p = Path(file_path).resolve()
    directory = p.parent

    # Walk up to find _CoqProject
    coqproject_path = None
    current = directory
    while True:
        candidate = current / "_CoqProject"
        if candidate.exists():
            coqproject_path = candidate
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    if coqproject_path is None:
        return [], []

    project_dir = coqproject_path.parent
    load_paths: List[Tuple[str, str]] = []
    include_paths: List[str] = []

    try:
        lines = coqproject_path.read_text().splitlines()
        tokens: List[str] = []
        for line in lines:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            tokens.extend(line.split())

        i = 0
        while i < len(tokens):
            if tokens[i] in ("-Q", "-R") and i + 2 < len(tokens):
                physical = tokens[i + 1]
                logical = tokens[i + 2]
                # Resolve relative paths against _CoqProject location
                physical_abs = str((project_dir / physical).resolve())
                load_paths.append((logical, physical_abs))
                i += 3
            elif tokens[i] == "-I" and i + 1 < len(tokens):
                inc = tokens[i + 1]
                include_paths.append(str((project_dir / inc).resolve()))
                i += 2
            else:
                i += 1
    except Exception as e:
        logger.warning("Failed to parse _CoqProject at %s: %s", coqproject_path, e)

    return load_paths, include_paths


# ---------------------------------------------------------------------------
# 4.4 File Profiling
# ---------------------------------------------------------------------------

async def profile_file(
    file_path: str,
    timeout_seconds: int = 300,
) -> FileProfile:
    """Profile a .v file by compiling with coqc -time-file.

    Returns a FileProfile with per-sentence timing, proof aggregations,
    and bottleneck classifications.
    """
    p = Path(file_path)
    if not p.exists():
        return FileProfile(
            file_path=file_path,
            compilation_succeeded=False,
            error_message=f"FILE_NOT_FOUND: {file_path}",
        )

    # Check for coqc
    coqc_path = locate_coqc()
    if coqc_path.startswith("TOOL_MISSING"):
        return FileProfile(
            file_path=file_path,
            compilation_succeeded=False,
            error_message=coqc_path,
        )

    # Resolve paths
    load_paths, include_paths = resolve_paths(file_path)

    # Build command
    timing_fd = tempfile.NamedTemporaryFile(
        suffix=".timing", delete=False, mode="w",
    )
    timing_path = timing_fd.name
    timing_fd.close()

    cmd = [coqc_path]
    for logical, physical in load_paths:
        cmd.extend(["-Q", physical, logical])
    for inc in include_paths:
        cmd.extend(["-I", inc])
    cmd.extend(["-time-file", timing_path, file_path])

    # Run subprocess
    start = time.monotonic()
    error_message = None
    compilation_succeeded = True

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            compilation_succeeded = False
            error_message = f"Compilation timed out after {timeout_seconds} seconds"
            stdout, stderr = b"", b""

        if proc.returncode != 0 and error_message is None:
            compilation_succeeded = False
            error_message = stderr.decode("utf-8", errors="replace").strip()
            if not error_message:
                error_message = f"coqc exited with code {proc.returncode}"

    except Exception as e:
        compilation_succeeded = False
        error_message = str(e)

    # Parse timing file
    timing_text = ""
    try:
        timing_text = Path(timing_path).read_text(errors="replace")
    except Exception:
        pass
    finally:
        try:
            os.unlink(timing_path)
        except OSError:
            pass

    sentences = parse_timing_output(timing_text)

    # Read source and resolve metadata
    try:
        source_bytes = p.read_bytes()
        source_text = source_bytes.decode("utf-8", errors="replace")
    except Exception:
        source_bytes = b""
        source_text = ""

    resolve_line_numbers(sentences, source_bytes)
    boundaries = detect_proof_boundaries(source_text)

    for sentence in sentences:
        classify_sentence(sentence, boundaries)

    # Aggregate into ProofProfiles
    proofs = _aggregate_proofs(sentences, boundaries)

    total_time = sum(s.real_time_s for s in sentences)

    return FileProfile(
        file_path=file_path,
        sentences=sentences,
        proofs=proofs,
        total_time_s=total_time,
        compilation_succeeded=compilation_succeeded,
        error_message=error_message,
    )


def _aggregate_proofs(
    sentences: List[TimingSentence],
    boundaries: List[ProofBoundary],
) -> List[ProofProfile]:
    """Aggregate sentences into ProofProfile records."""
    proof_map: dict[str, ProofProfile] = {}

    for boundary in boundaries:
        proof_map[boundary.name] = ProofProfile(
            lemma_name=boundary.name,
            line_number=1,  # Will be updated
        )

    for sentence in sentences:
        if sentence.containing_proof and sentence.containing_proof in proof_map:
            pp = proof_map[sentence.containing_proof]
            if sentence.sentence_kind == "ProofClose":
                pp.proof_close = sentence
                pp.close_time_s = sentence.real_time_s
            elif sentence.sentence_kind == "Tactic":
                pp.tactic_sentences.append(sentence)
            elif sentence.sentence_kind == "Definition":
                pp.line_number = sentence.line_number

    for pp in proof_map.values():
        pp.tactic_time_s = sum(s.real_time_s for s in pp.tactic_sentences)
        pp.total_time_s = pp.tactic_time_s + pp.close_time_s
        # Add declaration and proof-open time
        all_items = list(pp.tactic_sentences)
        if pp.proof_close:
            all_items.append(pp.proof_close)
        pp.bottlenecks = classify_bottlenecks(all_items, pp.total_time_s)

    proofs = sorted(proof_map.values(), key=lambda p: p.total_time_s, reverse=True)
    return proofs


# ---------------------------------------------------------------------------
# 4.9 Single-Proof Profiling
# ---------------------------------------------------------------------------

async def profile_single_proof(
    file_path: str,
    lemma_name: str,
    timeout_seconds: int = 300,
) -> Union[ProofProfile, str]:
    """Profile a specific proof within a file.

    Returns the ProofProfile or raises ValueError if lemma not found.
    """
    fp = await profile_file(file_path, timeout_seconds)

    for pp in fp.proofs:
        if pp.lemma_name == lemma_name:
            return pp

    available = [p.lemma_name for p in fp.proofs]
    raise ValueError(
        f"NOT_FOUND: Lemma '{lemma_name}' not found in {file_path}. "
        f"Available proofs: {', '.join(available)}"
    )


# ---------------------------------------------------------------------------
# 4.10 Ltac Profiling
# ---------------------------------------------------------------------------

async def profile_ltac(
    file_path: str,
    lemma_name: str,
    timeout_seconds: int = 300,
    session_manager: object = None,
) -> LtacProfile:
    """Profile Ltac tactic execution for a specific proof.

    Uses the Proof Session Manager to instrument profiling commands.
    The session_manager parameter must provide open_proof_session,
    submit_command, submit_tactic, and close_proof_session methods.
    """
    if session_manager is None:
        raise ValueError("session_manager is required for Ltac profiling")

    session_id = None
    try:
        session_id, _initial_state = await session_manager.open_proof_session(
            file_path, lemma_name,
        )

        # Enable Ltac profiling
        await session_manager.submit_command(session_id, "Set Ltac Profiling.")
        await session_manager.submit_command(session_id, "Reset Ltac Profile.")

        # Replay proof tactics
        # The session manager should provide the original script
        original_script = getattr(
            session_manager, "get_original_script",
            lambda sid: [],
        )
        tactics = original_script(session_id) if callable(original_script) else []

        for tactic in tactics:
            await session_manager.submit_tactic(session_id, tactic)

        # Capture profile
        output = await session_manager.submit_command(
            session_id, "Show Ltac Profile CutOff 0.",
        )

        profile = parse_ltac_profile(output or "")
        profile.lemma_name = lemma_name

        # Run bottleneck classifier
        profile.bottlenecks = classify_bottlenecks(
            profile.entries, profile.total_time_s,
        )

        return profile

    finally:
        if session_id is not None:
            try:
                await session_manager.close_proof_session(session_id)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 4.13 Timing Comparison
# ---------------------------------------------------------------------------

async def compare_profiles(
    current_file_path: str,
    baseline_timing_path: str,
    timeout_seconds: int = 300,
) -> TimingComparison:
    """Compare timing between a baseline .v.timing file and a fresh run."""
    baseline_text = Path(baseline_timing_path).read_text(errors="replace")
    baseline_sentences = parse_timing_output(baseline_text)

    current_fp = await profile_file(current_file_path, timeout_seconds)
    current_sentences = current_fp.sentences

    matched, unmatched_b, unmatched_c = match_sentences(
        baseline_sentences, current_sentences, fuzz_bytes=500,
    )

    diffs: List[TimingDiff] = []

    for bs, cs in matched:
        delta_s = cs.real_time_s - bs.real_time_s
        delta_pct = (
            (delta_s / bs.real_time_s * 100) if bs.real_time_s > 0 else None
        )
        if delta_pct is not None and delta_pct > 20 and delta_s > 0.5:
            status = "regressed"
        elif delta_pct is not None and delta_pct < -20 and delta_s < -0.5:
            status = "improved"
        else:
            status = "stable"

        diffs.append(TimingDiff(
            sentence_snippet=bs.snippet,
            line_before=bs.line_number,
            line_after=cs.line_number,
            time_before_s=bs.real_time_s,
            time_after_s=cs.real_time_s,
            delta_s=delta_s,
            delta_pct=delta_pct,
            status=status,
        ))

    for bs in unmatched_b:
        diffs.append(TimingDiff(
            sentence_snippet=bs.snippet,
            line_before=bs.line_number,
            line_after=None,
            time_before_s=bs.real_time_s,
            time_after_s=None,
            delta_s=-bs.real_time_s,
            delta_pct=-100.0,
            status="removed",
        ))

    for cs in unmatched_c:
        diffs.append(TimingDiff(
            sentence_snippet=cs.snippet,
            line_before=0,
            line_after=cs.line_number,
            time_before_s=0.0,
            time_after_s=cs.real_time_s,
            delta_s=cs.real_time_s,
            delta_pct=None,
            status="new",
        ))

    diffs.sort(key=lambda d: abs(d.delta_s), reverse=True)

    baseline_total = sum(s.real_time_s for s in baseline_sentences)
    current_total = current_fp.total_time_s

    return TimingComparison(
        file_path=current_file_path,
        baseline_total_s=baseline_total,
        current_total_s=current_total,
        net_delta_s=current_total - baseline_total,
        diffs=diffs,
        regressions=[d for d in diffs if d.status == "regressed"],
        improvements=[d for d in diffs if d.status == "improved"],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def profile_proof(
    request: ProfileRequest,
) -> Union[FileProfile, ProofProfile, LtacProfile, TimingComparison]:
    """Main entry point for the profiling engine."""
    err = validate_request(request)
    if err is not None:
        return FileProfile(
            file_path=request.file_path,
            compilation_succeeded=False,
            error_message=err,
        )

    if request.mode == "timing":
        if request.lemma_name is not None:
            return await profile_single_proof(
                request.file_path, request.lemma_name, request.timeout_seconds,
            )
        return await profile_file(request.file_path, request.timeout_seconds)

    elif request.mode == "ltac":
        return await profile_ltac(
            request.file_path,
            request.lemma_name,
            request.timeout_seconds,
        )

    elif request.mode == "compare":
        return await compare_profiles(
            request.file_path,
            request.baseline_path,
            request.timeout_seconds,
        )

    return FileProfile(
        file_path=request.file_path,
        compilation_succeeded=False,
        error_message=f"Unknown mode: {request.mode}",
    )
