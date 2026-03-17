"""Build system detection (spec section 4.1)."""

from __future__ import annotations

from pathlib import Path

from poule.build.errors import PROJECT_NOT_FOUND, BuildSystemError
from poule.build.types import BuildSystem, DetectionResult


def detect_build_system(project_dir: Path) -> DetectionResult:
    """Detect which build system a Coq/Rocq project uses.

    REQUIRES: project_dir is an absolute path to an existing directory.
    ENSURES: Returns a DetectionResult identifying the primary build system,
             opam presence, and paths to detected configuration files.
    MAINTAINS: Never modifies the filesystem. Never spawns subprocesses.
    """
    project_dir = Path(project_dir)

    if not project_dir.exists() or not project_dir.is_dir():
        raise BuildSystemError(
            PROJECT_NOT_FOUND,
            f"Project directory does not exist or is not a directory: {project_dir}",
        )

    config_files: list[str] = []
    has_dune_project = False
    has_coq_project = False
    has_opam = False

    dune_project = project_dir / "dune-project"
    if dune_project.exists():
        has_dune_project = True
        config_files.append(str(dune_project.resolve()))

    coq_project = project_dir / "_CoqProject"
    if coq_project.exists():
        has_coq_project = True
        config_files.append(str(coq_project.resolve()))

    # Check for .opam files
    for p in project_dir.iterdir():
        if p.suffix == ".opam" and p.is_file():
            has_opam = True
            config_files.append(str(p.resolve()))

    # Precedence: dune-project > _CoqProject > UNKNOWN
    if has_dune_project:
        build_system = BuildSystem.DUNE
    elif has_coq_project:
        build_system = BuildSystem.COQ_MAKEFILE
    else:
        build_system = BuildSystem.UNKNOWN
        config_files = []

    return DetectionResult(
        build_system=build_system,
        has_opam=has_opam,
        config_files=config_files,
        project_dir=str(project_dir),
    )
