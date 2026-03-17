"""Proof Checker Adapter — subprocess wrapper for coqchk.

Spec: specification/independent-proof-checking.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union

from poule.checker.discovery import discover_vo_files, parse_coqproject
from poule.checker.parser import parse_output
from poule.checker.paths import build_command, resolve_library_name
from poule.checker.types import CheckFailure, CheckRequest, CheckResult

logger = logging.getLogger(__name__)


def validate_request(request: CheckRequest) -> Optional[CheckResult]:
    """Validate a CheckRequest. Returns None if valid, or a CheckResult with
    status='error' describing the validation failure."""

    if request.mode == "single":
        if request.file_path is None:
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path="",
                        failure_kind="unknown",
                        raw_message="file_path is required when mode='single'",
                    )
                ],
            )
        p = Path(request.file_path)
        if p.suffix != ".vo":
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path=request.file_path,
                        failure_kind="unknown",
                        raw_message=f"file_path must end with .vo, got '{p.suffix}'",
                    )
                ],
            )
        if not p.exists():
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path=request.file_path,
                        failure_kind="missing_dependency",
                        raw_message=f"file not found: {request.file_path}",
                    )
                ],
            )
    elif request.mode == "project":
        if request.project_dir is None:
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path="",
                        failure_kind="unknown",
                        raw_message="project_dir is required when mode='project'",
                    )
                ],
            )
        if not Path(request.project_dir).exists():
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path="",
                        failure_kind="unknown",
                        raw_message=f"directory not found: {request.project_dir}",
                    )
                ],
            )

    return None


def locate_coqchk() -> Union[str, CheckResult]:
    """Locate the coqchk binary on PATH.

    Returns the absolute path as a string if found, or a CheckResult
    with status='error' if not found.
    """
    path = shutil.which("coqchk")
    if path is None:
        return CheckResult(
            status="error",
            failures=[
                CheckFailure(
                    file_path="",
                    failure_kind="unknown",
                    raw_message="coqchk not found",
                )
            ],
        )
    return os.path.abspath(path)


def _clamp_timeout(timeout_seconds: int) -> int:
    """Clamp timeout to [1, 3600]."""
    return max(1, min(3600, timeout_seconds))


def _detect_staleness(vo_path: str) -> Optional[str]:
    """Check if a .vo file is stale relative to its .v source.

    Returns the vo_path if stale, None otherwise.
    """
    v_path = vo_path[:-1]  # strip trailing 'o' from '.vo' -> '.v'
    if os.path.exists(v_path):
        if os.path.getmtime(v_path) > os.path.getmtime(vo_path):
            return vo_path
    return None


async def check_single(
    file_path: str,
    include_paths: List[str],
    load_paths: List[Tuple[str, str]],
    timeout_seconds: int = 300,
) -> CheckResult:
    """Check a single .vo file with coqchk."""
    start = time.monotonic()
    timeout_seconds = _clamp_timeout(timeout_seconds)

    # Validate
    req = CheckRequest(
        mode="single",
        file_path=file_path,
        include_paths=include_paths,
        load_paths=load_paths,
        timeout_seconds=timeout_seconds,
    )
    validation_error = validate_request(req)
    if validation_error is not None:
        validation_error.wall_time_ms = int((time.monotonic() - start) * 1000)
        return validation_error

    # Locate coqchk
    coqchk = locate_coqchk()
    if isinstance(coqchk, CheckResult):
        coqchk.wall_time_ms = int((time.monotonic() - start) * 1000)
        # Set file_path on failures
        for f in coqchk.failures:
            if not f.file_path:
                f.file_path = file_path
        return coqchk

    # Detect staleness
    stale_files: List[str] = []
    stale = _detect_staleness(file_path)
    if stale is not None:
        stale_files.append(stale)

    # Resolve library name
    library_name = resolve_library_name(file_path, load_paths)

    # Build command
    cmd = build_command(coqchk, load_paths, include_paths, [library_name])

    # Spawn subprocess
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            # Try to read any partial output
            stdout_str = ""
            stderr_str = ""
            try:
                if process.stdout:
                    partial_out = await process.stdout.read()
                    stdout_str = partial_out.decode("utf-8", errors="replace")
                if process.stderr:
                    partial_err = await process.stderr.read()
                    stderr_str = partial_err.decode("utf-8", errors="replace")
            except Exception:
                pass

            wall_time_ms = int((time.monotonic() - start) * 1000)
            raw_output = (stdout_str + "\n" + stderr_str).strip()

            # Parse any partial output
            _, files_passed, _, partial_failures = parse_output(
                stdout_str, stderr_str, None, [library_name]
            )

            # Add synthetic timeout failure
            timeout_failure = CheckFailure(
                file_path=file_path,
                module_name=None,
                definition=None,
                failure_kind="unknown",
                raw_message=f"Timeout after {timeout_seconds} seconds",
            )
            failures = partial_failures + [timeout_failure]

            return CheckResult(
                status="error",
                files_checked=1,
                files_passed=files_passed,
                files_failed=0,
                failures=failures,
                stale_files=stale_files,
                wall_time_ms=wall_time_ms,
                raw_output=raw_output,
            )

    except Exception as e:
        wall_time_ms = int((time.monotonic() - start) * 1000)
        return CheckResult(
            status="error",
            failures=[
                CheckFailure(
                    file_path=file_path,
                    failure_kind="unknown",
                    raw_message=str(e),
                )
            ],
            wall_time_ms=wall_time_ms,
        )

    # Parse output
    raw_output = (stdout_str + "\n" + stderr_str).strip()
    files_checked, files_passed, files_failed, failures = parse_output(
        stdout_str, stderr_str, exit_code, [library_name]
    )

    # Set file_path on all failures
    for f in failures:
        if not f.file_path:
            f.file_path = file_path

    if exit_code == 0:
        status = "pass"
    else:
        status = "fail"

    wall_time_ms = int((time.monotonic() - start) * 1000)

    return CheckResult(
        status=status,
        files_checked=files_checked,
        files_passed=files_passed,
        files_failed=files_failed,
        failures=failures,
        stale_files=stale_files,
        wall_time_ms=wall_time_ms,
        raw_output=raw_output,
    )


async def check_project(
    project_dir: str,
    include_paths: List[str],
    load_paths: List[Tuple[str, str]],
    timeout_seconds: int = 300,
) -> CheckResult:
    """Check all .vo files in a project directory."""
    start = time.monotonic()
    timeout_seconds = _clamp_timeout(timeout_seconds)

    # Validate
    req = CheckRequest(
        mode="project",
        project_dir=project_dir,
        include_paths=include_paths,
        load_paths=load_paths,
        timeout_seconds=timeout_seconds,
    )
    validation_error = validate_request(req)
    if validation_error is not None:
        validation_error.wall_time_ms = int((time.monotonic() - start) * 1000)
        return validation_error

    # Parse _CoqProject if it exists
    project_path = Path(project_dir)
    coqproject_file = project_path / "_CoqProject"
    discovered_load_paths: List[Tuple[str, str]] = []
    discovered_include_paths: List[str] = []
    use_coqproject = False

    if coqproject_file.exists():
        try:
            content = coqproject_file.read_text()
            parsed_load, parsed_include = parse_coqproject(content)
            # Make parsed paths absolute relative to project_dir
            discovered_load_paths = [
                (logical, str((project_path / physical).resolve()) if not Path(physical).is_absolute() else physical)
                for logical, physical in parsed_load
            ]
            discovered_include_paths = [
                str((project_path / p).resolve()) if not Path(p).is_absolute() else p
                for p in parsed_include
            ]
            use_coqproject = True
        except Exception as e:
            logger.warning("Failed to parse _CoqProject: %s; falling back to recursive walk", e)
            use_coqproject = False

    # Merge paths: request paths take precedence
    # Use request load_paths + discovered (request first for precedence)
    merged_load_paths = list(load_paths) + discovered_load_paths
    merged_include_paths = list(include_paths) + discovered_include_paths

    # Discover .vo files
    if use_coqproject and discovered_load_paths:
        vo_files = discover_vo_files(project_dir, discovered_load_paths)
    else:
        vo_files = discover_vo_files(project_dir)

    # No .vo files found
    if not vo_files:
        wall_time_ms = int((time.monotonic() - start) * 1000)
        return CheckResult(
            status="pass",
            files_checked=0,
            wall_time_ms=wall_time_ms,
        )

    # Detect staleness for all files
    stale_files: List[str] = []
    for vo in vo_files:
        stale = _detect_staleness(vo)
        if stale is not None:
            stale_files.append(stale)

    # Resolve library names
    library_names = [
        resolve_library_name(vo, merged_load_paths) for vo in vo_files
    ]

    # Locate coqchk
    coqchk = locate_coqchk()
    if isinstance(coqchk, CheckResult):
        coqchk.wall_time_ms = int((time.monotonic() - start) * 1000)
        coqchk.stale_files = stale_files
        return coqchk

    # Build command
    cmd = build_command(coqchk, merged_load_paths, merged_include_paths, library_names)

    # Spawn subprocess
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            stdout_str = ""
            stderr_str = ""
            try:
                if process.stdout:
                    partial_out = await process.stdout.read()
                    stdout_str = partial_out.decode("utf-8", errors="replace")
                if process.stderr:
                    partial_err = await process.stderr.read()
                    stderr_str = partial_err.decode("utf-8", errors="replace")
            except Exception:
                pass

            wall_time_ms = int((time.monotonic() - start) * 1000)
            raw_output = (stdout_str + "\n" + stderr_str).strip()

            _, files_passed, _, partial_failures = parse_output(
                stdout_str, stderr_str, None, library_names
            )

            timeout_failure = CheckFailure(
                file_path=project_dir,
                failure_kind="unknown",
                raw_message=f"Timeout after {timeout_seconds} seconds",
            )
            failures = partial_failures + [timeout_failure]

            return CheckResult(
                status="error",
                files_checked=len(vo_files),
                files_passed=files_passed,
                files_failed=0,
                failures=failures,
                stale_files=stale_files,
                wall_time_ms=wall_time_ms,
                raw_output=raw_output,
            )

    except Exception as e:
        wall_time_ms = int((time.monotonic() - start) * 1000)
        return CheckResult(
            status="error",
            failures=[
                CheckFailure(
                    file_path=project_dir,
                    failure_kind="unknown",
                    raw_message=str(e),
                )
            ],
            stale_files=stale_files,
            wall_time_ms=wall_time_ms,
        )

    # Parse output
    raw_output = (stdout_str + "\n" + stderr_str).strip()
    files_checked, files_passed, files_failed, failures = parse_output(
        stdout_str, stderr_str, exit_code, library_names
    )

    # Set file_path on failures
    for f in failures:
        if not f.file_path:
            f.file_path = project_dir

    if exit_code == 0:
        status = "pass"
    else:
        status = "fail"

    wall_time_ms = int((time.monotonic() - start) * 1000)

    return CheckResult(
        status=status,
        files_checked=files_checked,
        files_passed=files_passed,
        files_failed=files_failed,
        failures=failures,
        stale_files=stale_files,
        wall_time_ms=wall_time_ms,
        raw_output=raw_output,
    )


async def check_proof(request: CheckRequest) -> CheckResult:
    """Entry point: check proof(s) according to the request mode.

    Dispatches to check_single or check_project based on request.mode.
    Never raises exceptions; all errors are captured in the CheckResult.
    """
    try:
        # Validate first
        validation_error = validate_request(request)
        if validation_error is not None:
            return validation_error

        timeout = _clamp_timeout(request.timeout_seconds)

        if request.mode == "single":
            return await check_single(
                file_path=request.file_path,
                include_paths=request.include_paths,
                load_paths=request.load_paths,
                timeout_seconds=timeout,
            )
        elif request.mode == "project":
            return await check_project(
                project_dir=request.project_dir,
                include_paths=request.include_paths,
                load_paths=request.load_paths,
                timeout_seconds=timeout,
            )
        else:
            return CheckResult(
                status="error",
                failures=[
                    CheckFailure(
                        file_path="",
                        failure_kind="unknown",
                        raw_message=f"Unknown mode: {request.mode}",
                    )
                ],
            )
    except Exception as e:
        return CheckResult(
            status="error",
            failures=[
                CheckFailure(
                    file_path=request.file_path or request.project_dir or "",
                    failure_kind="unknown",
                    raw_message=str(e),
                )
            ],
        )
