"""Project file generation functions (spec sections 4.2, 4.3, 4.4, 4.5)."""

from __future__ import annotations

import re
from pathlib import Path

from poule.build.detection import detect_build_system
from poule.build.errors import (
    BUILD_SYSTEM_NOT_DETECTED,
    FILE_NOT_WRITABLE,
    BuildSystemError,
)
from poule.build.types import BuildSystem, MigrationResult, OpamMetadata


def _infer_logical_name(directory: Path) -> str:
    """Infer a logical name from the directory name, capitalizing the first letter."""
    name = directory.resolve().name
    if name:
        return name[0].upper() + name[1:]
    return "Project"


def _find_v_files(root: Path) -> dict[Path, list[Path]]:
    """Find all .v files grouped by their parent directory, relative to root.

    Returns a dict mapping relative directory paths to sorted lists of
    relative .v file paths.
    """
    result: dict[Path, list[Path]] = {}
    for v_file in sorted(root.rglob("*.v")):
        rel = v_file.relative_to(root)
        parent = rel.parent
        result.setdefault(parent, []).append(rel)
    return result


def _dir_to_logical_path(
    base_name: str,
    rel_dir: Path,
    source_root: Path | None = None,
) -> str:
    """Convert a relative directory path to a logical path.

    The ``source_root`` is the shallowest directory with .v files. It maps to
    ``base_name`` directly; subdirectories use only components *below* it.

    E.g., base_name="MyLib", source_root=Path("src"):
      - rel_dir=Path("src")      -> "MyLib"
      - rel_dir=Path("src/util") -> "MyLib.Util"
    """
    if source_root is None:
        source_root = Path(".")
    if rel_dir == source_root:
        return base_name
    try:
        rel_to_root = rel_dir.relative_to(source_root)
    except ValueError:
        # rel_dir is not under source_root; fall back to full path
        rel_to_root = rel_dir
    parts = [base_name] + [p[0].upper() + p[1:] for p in rel_to_root.parts]
    return ".".join(parts)


def _write_file_safe(path: Path, content: str) -> None:
    """Write content to a file, raising FILE_NOT_WRITABLE on permission error."""
    try:
        path.write_text(content)
    except PermissionError:
        raise BuildSystemError(
            FILE_NOT_WRITABLE,
            f"Cannot write to file: {path}",
        )


def generate_coq_project(
    project_dir: Path,
    logical_name: str | None = None,
    extra_flags: list[str] | None = None,
) -> Path:
    """Generate a _CoqProject file (spec section 4.2).

    REQUIRES: project_dir is an absolute path to an existing directory.
    ENSURES: Writes a _CoqProject file. Returns the path to it.
    """
    project_dir = Path(project_dir)
    if logical_name is None:
        logical_name = _infer_logical_name(project_dir)

    v_files_by_dir = _find_v_files(project_dir)
    dirs_sorted = sorted(v_files_by_dir.keys(), key=lambda d: (len(d.parts), str(d)))
    source_root = dirs_sorted[0] if dirs_sorted else Path(".")
    lines: list[str] = []

    # Extra flags first
    if extra_flags:
        for flag in extra_flags:
            lines.append(flag)

    # -Q mappings
    for rel_dir in dirs_sorted:
        logical_path = _dir_to_logical_path(logical_name, rel_dir, source_root)
        dir_str = "." if rel_dir == Path(".") else str(rel_dir)
        lines.append(f"-Q {dir_str} {logical_path}")

    # Source files (alphabetical within each directory)
    for rel_dir in dirs_sorted:
        for v_file in v_files_by_dir[rel_dir]:
            lines.append(str(v_file))

    output_path = project_dir / "_CoqProject"
    content = "\n".join(lines) + "\n"
    _write_file_safe(output_path, content)
    return output_path


def update_coq_project(project_dir: Path) -> Path:
    """Update an existing _CoqProject file with new files and directories (spec section 4.2).

    REQUIRES: project_dir contains an existing _CoqProject file.
    ENSURES: Parses existing file, adds new directories and .v files, preserves
             existing custom flags and comments.
    """
    project_dir = Path(project_dir)
    coq_project_path = project_dir / "_CoqProject"
    existing_content = coq_project_path.read_text()
    existing_lines = existing_content.splitlines()

    # Parse existing content
    existing_v_files: set[str] = set()
    existing_q_dirs: set[str] = set()
    comment_and_flag_lines: list[str] = []
    q_lines: list[str] = []
    v_lines: list[str] = []

    # Extract logical name from existing -Q mappings
    logical_name = None
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("-Q ") or stripped.startswith("-R "):
            parts = stripped.split()
            if len(parts) >= 3:
                dir_part = parts[1]
                logical_part = parts[2]
                existing_q_dirs.add(dir_part)
                if dir_part == ".":
                    logical_name = logical_part
                q_lines.append(stripped)
        elif stripped.endswith(".v"):
            existing_v_files.add(stripped)
            v_lines.append(stripped)
        elif stripped:
            comment_and_flag_lines.append(stripped)

    if logical_name is None:
        logical_name = _infer_logical_name(project_dir)

    # Discover new files and directories
    v_files_by_dir = _find_v_files(project_dir)

    # Add new -Q mappings
    for rel_dir in sorted(v_files_by_dir.keys(), key=lambda d: str(d)):
        dir_str = "." if rel_dir == Path(".") else str(rel_dir)
        if dir_str not in existing_q_dirs:
            logical_path = _dir_to_logical_path(logical_name, rel_dir)
            q_lines.append(f"-Q {dir_str} {logical_path}")

    # Add new .v files
    for rel_dir in sorted(v_files_by_dir.keys(), key=lambda d: str(d)):
        for v_file in v_files_by_dir[rel_dir]:
            v_str = str(v_file)
            if v_str not in existing_v_files:
                v_lines.append(v_str)

    # Reconstruct file: comments/flags, then -Q lines, then .v files
    result_lines = comment_and_flag_lines + q_lines + sorted(v_lines)
    content = "\n".join(result_lines) + "\n"
    _write_file_safe(coq_project_path, content)
    return coq_project_path


def generate_dune_project(
    project_dir: Path,
    logical_name: str | None = None,
    dune_lang_version: str | None = None,
    coq_lang_version: str | None = None,
) -> list[Path]:
    """Generate dune-project and per-directory dune files (spec section 4.3).

    REQUIRES: project_dir is an absolute path to an existing directory.
    ENSURES: Writes dune-project at root, per-directory dune files where .v files exist.
    Returns list of generated file paths.
    """
    project_dir = Path(project_dir)
    if logical_name is None:
        logical_name = _infer_logical_name(project_dir)
    if dune_lang_version is None:
        dune_lang_version = "3.0"
    if coq_lang_version is None:
        coq_lang_version = "0.6"

    generated_files: list[Path] = []

    # Write dune-project
    dune_project_path = project_dir / "dune-project"
    dune_project_content = (
        f"(lang dune {dune_lang_version})\n"
        f"(using coq {coq_lang_version})\n"
    )
    _write_file_safe(dune_project_path, dune_project_content)
    generated_files.append(dune_project_path)

    # Find all directories with .v files
    v_files_by_dir = _find_v_files(project_dir)

    dirs_sorted = sorted(v_files_by_dir.keys(), key=lambda d: (len(d.parts), str(d)))
    source_root = dirs_sorted[0] if dirs_sorted else Path(".")

    # Build a list of (absolute_dir, theory_name, parent_theory_name_or_None)
    dir_theories: list[tuple[Path, str, str | None]] = []
    for rel_dir in dirs_sorted:
        abs_dir = project_dir / rel_dir
        theory_name = _dir_to_logical_path(logical_name, rel_dir, source_root)

        # Find parent theory
        parent_theory = None
        if rel_dir != source_root:
            parent_rel = rel_dir.parent
            parent_theory = _dir_to_logical_path(logical_name, parent_rel, source_root)
            # If parent is above source_root or not in v_files, use root logical name
            if parent_rel not in v_files_by_dir:
                parent_theory = logical_name

        dir_theories.append((abs_dir, theory_name, parent_theory))

    # Write per-directory dune files
    for abs_dir, theory_name, parent_theory in dir_theories:
        if parent_theory:
            dune_content = (
                f"(coq.theory\n"
                f" (name {theory_name})\n"
                f" (theories {parent_theory}))\n"
            )
        else:
            dune_content = (
                f"(coq.theory\n"
                f" (name {theory_name}))\n"
            )
        dune_path = abs_dir / "dune"
        _write_file_safe(dune_path, dune_content)
        generated_files.append(dune_path)

    return generated_files


def generate_opam_file(
    project_dir: Path,
    metadata: OpamMetadata,
) -> Path:
    """Generate an .opam file (spec section 4.4).

    REQUIRES: project_dir is an absolute path. metadata contains required fields.
    ENSURES: Writes a .opam file with opam-version, metadata, depends, and build fields.
    """
    project_dir = Path(project_dir)

    # Detect build system to determine build command
    detection = detect_build_system(project_dir)

    lines: list[str] = []
    lines.append('opam-version: "2.0"')
    lines.append(f'name: "{metadata.name}"')
    lines.append(f'version: "{metadata.version}"')
    lines.append(f'synopsis: "{metadata.synopsis}"')
    lines.append(f'maintainer: "{metadata.maintainer}"')

    # Dependencies
    if metadata.dependencies:
        lines.append("depends: [")
        for dep_name, dep_constraint in metadata.dependencies:
            if dep_constraint:
                lines.append(f'  "{dep_name}" {{{dep_constraint}}}')
            else:
                lines.append(f'  "{dep_name}"')
        lines.append("]")

    # Build command based on detected build system
    if detection.build_system == BuildSystem.DUNE:
        lines.append('build: [["dune" "build" "-p" name "-j" jobs]]')
    else:
        lines.append('build: [["make" "-j" jobs]]')

    output_path = project_dir / f"{metadata.name}.opam"
    content = "\n".join(lines) + "\n"
    _write_file_safe(output_path, content)
    return output_path


def migrate_to_dune(project_dir: Path) -> MigrationResult:
    """Migrate a coq_makefile project to Dune (spec section 4.5).

    REQUIRES: project_dir contains a _CoqProject file.
    ENSURES: Parses _CoqProject, generates equivalent dune-project and per-directory
             dune files. Returns MigrationResult with untranslatable flags.
    MAINTAINS: The existing _CoqProject file is not deleted or modified.
    """
    project_dir = Path(project_dir)
    coq_project_path = project_dir / "_CoqProject"
    content = coq_project_path.read_text()
    lines = content.splitlines()

    # Parse _CoqProject
    q_mappings: list[tuple[str, str]] = []  # (dir, logical_name)
    untranslatable_flags: list[str] = []
    logical_name = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("-Q ") or stripped.startswith("-R "):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                dir_part = parts[1]
                logical_part = parts[2]
                q_mappings.append((dir_part, logical_part))
                if dir_part == "." or dir_part == "src":
                    if logical_name is None:
                        logical_name = logical_part
        elif stripped.startswith("-arg"):
            # -arg flags are untranslatable
            # Extract the argument value
            rest = stripped[len("-arg"):].strip()
            # Remove surrounding quotes if present
            if rest.startswith('"') and rest.endswith('"'):
                rest = rest[1:-1]
            untranslatable_flags.append(rest)
        elif stripped.startswith("-") and not stripped.endswith(".v"):
            # Other flags that aren't -Q/-R and aren't source files
            untranslatable_flags.append(stripped)
        # .v file lines are ignored for migration purposes

    if logical_name is None:
        logical_name = _infer_logical_name(project_dir)

    # Generate dune-project and per-directory dune files
    generated = generate_dune_project(project_dir, logical_name=logical_name)
    generated_files = [str(p) for p in generated]

    return MigrationResult(
        generated_files=generated_files,
        untranslatable_flags=untranslatable_flags,
    )
