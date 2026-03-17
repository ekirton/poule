"""Build execution, error parsing, package queries, and dependency management.

Spec sections 4.6, 4.7, 4.8, 4.9.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path

from poule.build.detection import detect_build_system
from poule.build.errors import (
    BUILD_SYSTEM_NOT_DETECTED,
    BUILD_TIMEOUT,
    DEPENDENCY_EXISTS,
    INVALID_PARAMETER,
    PACKAGE_NOT_FOUND,
    PROJECT_NOT_FOUND,
    TOOL_NOT_FOUND,
    BuildSystemError,
)
from poule.build.types import (
    BuildError,
    BuildRequest,
    BuildResult,
    BuildSystem,
    ConflictDetail,
    ConstraintSource,
    DependencyStatus,
    PackageInfo,
)

# Maximum output capture size: 1 MB
MAX_OUTPUT_BYTES = 1024 * 1024

# --------------------------------------------------------------------------
# Error pattern definitions (spec section 4.7)
# --------------------------------------------------------------------------

# Coq compiler file location pattern
_COQ_FILE_PATTERN = re.compile(
    r'File "([^"]+)", line (\d+), characters (\d+)-(\d+):'
)

# Category detection patterns with (pattern, category) pairs
_COQ_ERROR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Cannot find a physical path bound to logical path"), "LOGICAL_PATH_NOT_FOUND"),
    (re.compile(r"Required library.*not found"), "REQUIRED_LIBRARY_NOT_FOUND"),
    (re.compile(r"has type.*while it is expected to have type"), "TYPE_ERROR"),
    (re.compile(r"Syntax error"), "SYNTAX_ERROR"),
    (re.compile(r"No matching clauses for match"), "TACTIC_FAILURE"),
    (re.compile(r"(?:Tactic failure|No applicable tactic|Unable to unify)"), "TACTIC_FAILURE"),
]

_DUNE_ERROR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Theory.*not found"), "THEORY_NOT_FOUND"),
    (re.compile(r"Invalid field.*in stanza|stanza syntax|Error.*stanza"), "DUNE_CONFIG_ERROR"),
]

_OPAM_ERROR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[Ii]ncompatible version constraints"), "VERSION_CONFLICT"),
    (re.compile(r"No package named.*found|not found in repositories"), "PACKAGE_NOT_FOUND"),
    (re.compile(r"Package build failed during installation"), "BUILD_FAILURE"),
]

# Explanation and fix templates
_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "LOGICAL_PATH_NOT_FOUND": (
        "The Coq compiler cannot find a directory mapped to the logical path mentioned in the error. "
        "This path must be declared with a -Q or -R flag in _CoqProject.",
        "Add '-Q <directory> <logical_path>' to _CoqProject, where <directory> is the filesystem "
        "path containing the corresponding module.",
    ),
    "REQUIRED_LIBRARY_NOT_FOUND": (
        "A required Coq library could not be found in the load path.",
        "Ensure the library is installed and its path is included in the project configuration.",
    ),
    "TYPE_ERROR": (
        "A type checking error occurred. The term has an unexpected type.",
        "Check the types of the expressions involved and ensure they match.",
    ),
    "SYNTAX_ERROR": (
        "A syntax error was encountered while parsing the Coq source file.",
        "Check the syntax at the indicated location for missing or extra tokens.",
    ),
    "TACTIC_FAILURE": (
        "A tactic failed during proof construction.",
        "Review the proof state and try a different tactic or approach.",
    ),
    "THEORY_NOT_FOUND": (
        "Dune could not find a coq.theory dependency.",
        "Add the missing theory to the (theories ...) field in the dune file.",
    ),
    "DUNE_CONFIG_ERROR": (
        "A Dune configuration error was detected in the stanza syntax or fields.",
        "Check the dune file syntax and field names.",
    ),
    "VERSION_CONFLICT": (
        "Incompatible version constraints were detected between packages.",
        "Review the version constraints and find compatible versions.",
    ),
    "PACKAGE_NOT_FOUND": (
        "The requested package was not found in any opam repository.",
        "Check the package name and ensure the correct opam repositories are configured.",
    ),
    "BUILD_FAILURE": (
        "A package build failed during opam installation.",
        "Check the build logs for the failing package.",
    ),
    "OTHER": (
        "An unrecognized error occurred.",
        None,
    ),
}


def _truncate_output(data: bytes) -> tuple[str, bool]:
    """Truncate output to MAX_OUTPUT_BYTES, preserving the tail."""
    if len(data) <= MAX_OUTPUT_BYTES:
        return data.decode("utf-8", errors="replace"), False
    # Truncate from the beginning (preserve tail)
    truncated = data[-MAX_OUTPUT_BYTES:]
    return truncated.decode("utf-8", errors="replace"), True


def parse_build_errors(
    stdout: str,
    stderr: str,
    build_system: BuildSystem,
) -> list[BuildError]:
    """Parse build output into structured BuildError records (spec section 4.7).

    REQUIRES: stdout and stderr are strings. build_system is DUNE or COQ_MAKEFILE.
    ENSURES: Returns an ordered list of BuildError records.
    """
    if not stderr and not stdout:
        return []

    combined = stderr if stderr else stdout
    if not combined.strip():
        return []

    errors: list[BuildError] = []

    # Split into error blocks using the Coq file location pattern
    # Each block starts with 'File "...", line ..., characters ...:' followed by error text
    blocks: list[tuple[str | None, int | None, tuple[int, int] | None, str]] = []

    # Try to split by Coq file location pattern
    parts = _COQ_FILE_PATTERN.split(combined)

    if len(parts) > 1:
        # parts[0] is text before first match, then groups of 5: (pre, file, line, start, end, text, ...)
        # Actually: split with groups gives [before, g1, g2, g3, g4, between, g1, g2, ...]
        i = 0
        prefix = parts[0].strip()
        i = 1
        while i + 3 < len(parts):
            file_path = parts[i]
            line_num = int(parts[i + 1])
            char_start = int(parts[i + 2])
            char_end = int(parts[i + 3])
            # The text after the match until the next match
            text_after = parts[i + 4] if i + 4 < len(parts) else ""
            raw_text = f'File "{file_path}", line {line_num}, characters {char_start}-{char_end}:\n{text_after.strip()}'
            blocks.append((file_path, line_num, (char_start, char_end), raw_text))
            i += 5

        # Handle prefix text that doesn't match the pattern
        if prefix and not blocks:
            blocks.append((None, None, None, prefix))
    else:
        # No Coq file location found; treat the whole thing as one block
        blocks.append((None, None, None, combined.strip()))

    # Classify each block
    for file_path, line_num, char_range, raw_text in blocks:
        category = _classify_error(raw_text, build_system)
        explanation, suggested_fix = _EXPLANATIONS.get(category, _EXPLANATIONS["OTHER"])

        errors.append(BuildError(
            category=category,
            file=file_path,
            line=line_num,
            char_range=char_range,
            raw_text=raw_text,
            explanation=explanation,
            suggested_fix=suggested_fix,
        ))

    return errors


def _classify_error(text: str, build_system: BuildSystem) -> str:
    """Classify an error text into a category."""
    # Check Coq compiler patterns (applicable to both build systems)
    for pattern, category in _COQ_ERROR_PATTERNS:
        if pattern.search(text):
            return category

    # Check build-system-specific patterns
    if build_system == BuildSystem.DUNE:
        for pattern, category in _DUNE_ERROR_PATTERNS:
            if pattern.search(text):
                return category

    # Check opam patterns
    for pattern, category in _OPAM_ERROR_PATTERNS:
        if pattern.search(text):
            return category

    return "OTHER"


def _check_tool(tool_name: str) -> None:
    """Check that a tool is available on PATH."""
    if shutil.which(tool_name) is None:
        raise BuildSystemError(
            TOOL_NOT_FOUND,
            f"Required tool '{tool_name}' not found on PATH.",
            {"tool": tool_name},
        )


async def execute_build(request: BuildRequest) -> BuildResult:
    """Execute a build as a subprocess (spec section 4.6).

    REQUIRES: project_dir is an absolute path to an existing directory.
    ENSURES: Returns a BuildResult with exit code, captured output, parsed errors, etc.
    MAINTAINS: No persistent build daemon. Each invocation is self-contained.
    """
    project_dir = Path(request.project_dir)

    if not project_dir.exists() or not project_dir.is_dir():
        raise BuildSystemError(
            PROJECT_NOT_FOUND,
            f"Project directory does not exist: {project_dir}",
        )

    # Clamp timeout to minimum of 10
    timeout = max(request.timeout, 10)

    # Determine build system
    build_system = request.build_system
    if build_system is None:
        detection = detect_build_system(project_dir)
        build_system = detection.build_system
        if build_system == BuildSystem.UNKNOWN:
            raise BuildSystemError(
                BUILD_SYSTEM_NOT_DETECTED,
                "No build system detected and none specified.",
            )

    start_time = time.monotonic()
    timed_out = False
    truncated = False
    stdout_str = ""
    stderr_str = ""
    exit_code = -1

    try:
        if build_system == BuildSystem.COQ_MAKEFILE:
            # First generate Makefile if it doesn't exist
            makefile = project_dir / "Makefile"
            if not makefile.exists():
                proc = await asyncio.create_subprocess_exec(
                    "coq_makefile", "-f", "_CoqProject", "-o", "Makefile",
                    cwd=str(project_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.communicate(), timeout=timeout)

            # Then run make
            cmd = ["make"]
            if request.target:
                cmd.append(request.target)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
        else:  # DUNE
            cmd = ["dune", "build", "--root", str(project_dir)]
            if request.target:
                cmd.append(request.target)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )

        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            timed_out = True
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            exit_code = proc.returncode or -1
            stdout_raw = b""
            stderr_raw = b""

    except asyncio.TimeoutError:
        timed_out = True
        stdout_raw = b""
        stderr_raw = b""

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # Truncate output if needed
    stdout_str, stdout_truncated = _truncate_output(stdout_raw)
    stderr_str, stderr_truncated = _truncate_output(stderr_raw)
    truncated = stdout_truncated or stderr_truncated

    success = (exit_code == 0) and not timed_out

    # Parse errors from output
    errors: list[BuildError] = []
    if not success:
        errors = parse_build_errors(stdout_str, stderr_str, build_system)

    return BuildResult(
        success=success,
        exit_code=exit_code,
        stdout=stdout_str,
        stderr=stderr_str,
        errors=errors,
        elapsed_ms=elapsed_ms,
        build_system=build_system,
        timed_out=timed_out,
        truncated=truncated,
    )


async def query_installed_packages() -> list[tuple[str, str]]:
    """Query installed opam packages (spec section 4.8).

    REQUIRES: opam is on PATH.
    ENSURES: Returns a list of (name, version) pairs sorted alphabetically by name.
    """
    _check_tool("opam")

    proc = await asyncio.create_subprocess_exec(
        "opam", "list", "--installed", "--columns=name,version", "--short",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, _ = await proc.communicate()
    output = stdout_raw.decode("utf-8", errors="replace")

    packages: list[tuple[str, str]] = []
    for line in output.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            packages.append((parts[0], parts[1]))

    packages.sort(key=lambda p: p[0])
    return packages


async def query_package_info(package_name: str) -> PackageInfo:
    """Query information about an opam package (spec section 4.8).

    REQUIRES: package_name is a non-empty string. opam is on PATH.
    ENSURES: Returns a PackageInfo record.
    """
    if not package_name:
        raise BuildSystemError(
            INVALID_PARAMETER,
            "package_name must be non-empty.",
        )

    _check_tool("opam")

    proc = await asyncio.create_subprocess_exec(
        "opam", "show", package_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, stderr_raw = await proc.communicate()

    if proc.returncode != 0:
        raise BuildSystemError(
            PACKAGE_NOT_FOUND,
            f"Package '{package_name}' not found.",
            {"package": package_name},
        )

    output = stdout_raw.decode("utf-8", errors="replace")

    # Parse opam show output
    fields: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

    name = fields.get("name", package_name)
    version = fields.get("version")
    synopsis = fields.get("synopsis", "")
    depends_str = fields.get("depends", "")
    all_versions_str = fields.get("all-versions", "")

    dependencies = [d.strip() for d in depends_str.split() if d.strip()] if depends_str else []
    available_versions = [v.strip() for v in all_versions_str.split() if v.strip()] if all_versions_str else []
    # Sort descending
    available_versions = sorted(available_versions, reverse=True)

    return PackageInfo(
        name=name,
        installed_version=version,
        available_versions=available_versions,
        synopsis=synopsis,
        dependencies=dependencies,
    )


async def install_package(
    package_name: str,
    version_constraint: str | None = None,
) -> BuildResult:
    """Install an opam package (spec section 4.9).

    REQUIRES: package_name is a non-empty string. opam is on PATH.
    ENSURES: Returns a BuildResult.
    """
    if not package_name:
        raise BuildSystemError(
            INVALID_PARAMETER,
            "package_name must be non-empty.",
        )

    _check_tool("opam")

    cmd = ["opam", "install", package_name, "-y"]
    if version_constraint:
        cmd = ["opam", "install", f"{package_name}.{version_constraint}", "-y"]

    start_time = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            proc.communicate(), timeout=600
        )
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return BuildResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            errors=[],
            elapsed_ms=elapsed_ms,
            build_system=BuildSystem.UNKNOWN,
            timed_out=True,
            truncated=False,
        )

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    exit_code = proc.returncode or 0
    stdout_str = stdout_raw.decode("utf-8", errors="replace")
    stderr_str = stderr_raw.decode("utf-8", errors="replace")
    success = exit_code == 0

    errors: list[BuildError] = []
    if not success:
        errors = parse_build_errors(stdout_str, stderr_str, BuildSystem.UNKNOWN)

    return BuildResult(
        success=success,
        exit_code=exit_code,
        stdout=stdout_str,
        stderr=stderr_str,
        errors=errors,
        elapsed_ms=elapsed_ms,
        build_system=BuildSystem.UNKNOWN,
        timed_out=False,
        truncated=False,
    )


def add_dependency(
    project_dir: Path,
    package_name: str,
    version_constraint: str | None = None,
) -> None:
    """Add a dependency to the project configuration (spec section 4.9).

    REQUIRES: project_dir is an absolute path. package_name is non-empty.
    ENSURES: Adds dependency to the appropriate configuration file.
    """
    project_dir = Path(project_dir)

    detection = detect_build_system(project_dir)
    if detection.build_system == BuildSystem.UNKNOWN:
        raise BuildSystemError(
            BUILD_SYSTEM_NOT_DETECTED,
            "No build system detected. Cannot add dependency.",
        )

    if detection.build_system == BuildSystem.DUNE:
        dune_project = project_dir / "dune-project"
        content = dune_project.read_text()

        # Check if dependency already exists
        if package_name in content:
            raise BuildSystemError(
                DEPENDENCY_EXISTS,
                f"Dependency '{package_name}' already exists.",
            )

        # Add dependency
        if "(depends" in content:
            # Append to existing depends block
            content = content.replace(
                "(depends",
                f"(depends {package_name}",
            )
        else:
            # Add a new depends block
            if version_constraint:
                content += f"\n(depends ({package_name} {version_constraint}))\n"
            else:
                content += f"\n(depends {package_name})\n"
        dune_project.write_text(content)

    else:
        # For coq_makefile, add to .opam file
        opam_files = list(project_dir.glob("*.opam"))
        if opam_files:
            opam_file = opam_files[0]
            content = opam_file.read_text()
            if package_name in content:
                raise BuildSystemError(
                    DEPENDENCY_EXISTS,
                    f"Dependency '{package_name}' already exists.",
                )
            content += f'  "{package_name}"\n'
            opam_file.write_text(content)


async def check_dependency_conflicts(
    dependencies: list[tuple[str, str | None]],
) -> DependencyStatus:
    """Check for dependency conflicts using opam dry-run (spec section 4.9).

    REQUIRES: dependencies is a non-empty list.
    ENSURES: Returns DependencyStatus indicating if dependencies are satisfiable.
    """
    _check_tool("opam")

    # Build the opam install command with --dry-run
    cmd = ["opam", "install", "--dry-run", "--show-actions"]
    for name, constraint in dependencies:
        if constraint:
            cmd.append(f"{name}{constraint}")
        else:
            cmd.append(name)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, stderr_raw = await proc.communicate()

    if proc.returncode == 0:
        return DependencyStatus(satisfiable=True, conflicts=[])

    # Parse conflicts from stderr
    stderr_str = stderr_raw.decode("utf-8", errors="replace")
    conflicts = _parse_conflicts(stderr_str)

    return DependencyStatus(satisfiable=False, conflicts=conflicts)


def _parse_conflicts(stderr: str) -> list[ConflictDetail]:
    """Parse conflict details from opam dry-run output."""
    conflicts: list[ConflictDetail] = []

    # Pattern: "- <pkg> <constraint> (conflict with <pkg> <constraint> required by <pkg>)"
    conflict_pattern = re.compile(
        r"-\s+(\S+)\s+(.*?)\(conflict with\s+(\S+)\s+(.*?)\s+required by\s+(\S+)\)"
    )

    for match in conflict_pattern.finditer(stderr):
        pkg = match.group(1)
        constraint1 = match.group(2).strip()
        conflict_pkg = match.group(3)
        constraint2 = match.group(4).strip()
        required_by = match.group(5)

        constraints = [
            ConstraintSource(required_by=pkg, constraint=constraint1),
            ConstraintSource(required_by=required_by, constraint=constraint2),
        ]
        conflicts.append(ConflictDetail(package=conflict_pkg, constraints=constraints))

    # If no specific conflicts parsed but we know it's unsatisfiable, add a generic one
    if not conflicts:
        # Try a simpler parse
        lines = stderr.strip().splitlines()
        for line in lines:
            line = line.strip()
            if "conflict" in line.lower() or "dependencies" in line.lower():
                conflicts.append(ConflictDetail(
                    package="unknown",
                    constraints=[ConstraintSource(required_by="unknown", constraint=line)],
                ))
                break

    if not conflicts:
        conflicts.append(ConflictDetail(
            package="unknown",
            constraints=[ConstraintSource(required_by="unknown", constraint=stderr.strip())],
        ))

    return conflicts
