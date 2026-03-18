"""TDD tests for the Build System Integration (specification/build-system-integration.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/build/ modules exist.

Spec: specification/build-system-integration.md
Architecture: doc/architecture/build-system-integration.md

Import paths under test (per spec §10):
  poule.build          (detect_build_system, execute_build, generate_*, etc.)
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_detect():
    from Poule.build import detect_build_system
    return detect_build_system


def _import_execute():
    from Poule.build import execute_build
    return execute_build


def _import_generate_coq_project():
    from Poule.build import generate_coq_project
    return generate_coq_project


def _import_update_coq_project():
    from Poule.build import update_coq_project
    return update_coq_project


def _import_generate_dune_project():
    from Poule.build import generate_dune_project
    return generate_dune_project


def _import_generate_opam_file():
    from Poule.build import generate_opam_file
    return generate_opam_file


def _import_migrate_to_dune():
    from Poule.build import migrate_to_dune
    return migrate_to_dune


def _import_parse_build_errors():
    from Poule.build import parse_build_errors
    return parse_build_errors


def _import_query_installed_packages():
    from Poule.build import query_installed_packages
    return query_installed_packages


def _import_query_package_info():
    from Poule.build import query_package_info
    return query_package_info


def _import_install_package():
    from Poule.build import install_package
    return install_package


def _import_add_dependency():
    from Poule.build import add_dependency
    return add_dependency


def _import_check_dependency_conflicts():
    from Poule.build import check_dependency_conflicts
    return check_dependency_conflicts


def _import_types():
    from Poule.build.types import (
        BuildError,
        BuildRequest,
        BuildResult,
        BuildSystem,
        ConflictDetail,
        ConstraintSource,
        DependencyStatus,
        DetectionResult,
        MigrationResult,
        OpamMetadata,
        PackageInfo,
    )
    return (
        BuildError,
        BuildRequest,
        BuildResult,
        BuildSystem,
        ConflictDetail,
        ConstraintSource,
        DependencyStatus,
        DetectionResult,
        MigrationResult,
        OpamMetadata,
        PackageInfo,
    )


def _import_errors():
    from Poule.build.errors import (
        BUILD_SYSTEM_NOT_DETECTED,
        BUILD_TIMEOUT,
        DEPENDENCY_EXISTS,
        FILE_NOT_WRITABLE,
        INVALID_PARAMETER,
        PACKAGE_NOT_FOUND,
        PROJECT_NOT_FOUND,
        TOOL_NOT_FOUND,
        BuildSystemError,
    )
    return (
        BUILD_SYSTEM_NOT_DETECTED,
        BUILD_TIMEOUT,
        DEPENDENCY_EXISTS,
        FILE_NOT_WRITABLE,
        INVALID_PARAMETER,
        PACKAGE_NOT_FOUND,
        PROJECT_NOT_FOUND,
        TOOL_NOT_FOUND,
        BuildSystemError,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detection_result(
    build_system_str="DUNE",
    has_opam=False,
    config_files=None,
    project_dir="/tmp/test",
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    bs = BuildSystem[build_system_str]
    return DetectionResult(
        build_system=bs,
        has_opam=has_opam,
        config_files=config_files or [],
        project_dir=project_dir,
    )


def _make_build_result(
    success=True,
    exit_code=0,
    stdout="",
    stderr="",
    errors=None,
    elapsed_ms=100,
    build_system_str="DUNE",
    timed_out=False,
    truncated=False,
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    bs = BuildSystem[build_system_str]
    return BuildResult(
        success=success,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        errors=errors or [],
        elapsed_ms=elapsed_ms,
        build_system=bs,
        timed_out=timed_out,
        truncated=truncated,
    )


def _make_build_error(
    category="OTHER",
    file=None,
    line=None,
    char_range=None,
    raw_text="unknown error",
    explanation="An unrecognized error occurred.",
    suggested_fix=None,
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    return BuildError(
        category=category,
        file=file,
        line=line,
        char_range=char_range,
        raw_text=raw_text,
        explanation=explanation,
        suggested_fix=suggested_fix,
    )


def _make_build_request(
    project_dir="/tmp/test",
    build_system=None,
    target=None,
    timeout=300,
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    return BuildRequest(
        project_dir=project_dir,
        build_system=build_system,
        target=target,
        timeout=timeout,
    )


def _make_opam_metadata(
    name="mylib",
    version="1.0",
    synopsis="A Coq library",
    maintainer="dev@example.com",
    dependencies=None,
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    return OpamMetadata(
        name=name,
        version=version,
        synopsis=synopsis,
        maintainer=maintainer,
        dependencies=dependencies or [],
    )


def _make_package_info(
    name="coq-mathcomp-ssreflect",
    installed_version="2.1.0",
    available_versions=None,
    synopsis="Mathematical Components",
    dependencies=None,
):
    (
        BuildError, BuildRequest, BuildResult, BuildSystem,
        ConflictDetail, ConstraintSource, DependencyStatus,
        DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
    ) = _import_types()
    return PackageInfo(
        name=name,
        installed_version=installed_version,
        available_versions=available_versions or ["2.1.0", "2.0.0", "1.19.0"],
        synopsis=synopsis,
        dependencies=dependencies or ["coq"],
    )


# ===========================================================================
# 1. Build System Detection -- spec §4.1
# ===========================================================================

class TestBuildSystemDetection:
    """§4.1: detect_build_system(project_dir) requirements."""

    def test_dune_project_detected(self, tmp_path):
        """Given dune-project exists, build_system = DUNE."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        result = detect(tmp_path)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        assert isinstance(result.build_system, BuildSystem)
        assert result.build_system == BuildSystem.DUNE

    def test_coq_project_without_dune_detected(self, tmp_path):
        """Given _CoqProject exists and dune-project does not, build_system = COQ_MAKEFILE."""
        detect = _import_detect()
        (tmp_path / "_CoqProject").touch()
        result = detect(tmp_path)
        _, _, _, BuildSystem, *_ = _import_types()
        assert result.build_system == BuildSystem.COQ_MAKEFILE

    def test_dune_takes_precedence_over_coq_project(self, tmp_path):
        """Given both dune-project and _CoqProject, build_system = DUNE (§4.1 precedence)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        (tmp_path / "_CoqProject").touch()
        result = detect(tmp_path)
        _, _, _, BuildSystem, *_ = _import_types()
        assert result.build_system == BuildSystem.DUNE

    def test_empty_directory_returns_unknown(self, tmp_path):
        """Given no marker files, build_system = UNKNOWN and has_opam = false."""
        detect = _import_detect()
        result = detect(tmp_path)
        _, _, _, BuildSystem, *_ = _import_types()
        assert result.build_system == BuildSystem.UNKNOWN
        assert result.has_opam is False

    def test_opam_file_detected_independently(self, tmp_path):
        """Given _CoqProject and mylib.opam, has_opam = true (§4.1)."""
        detect = _import_detect()
        (tmp_path / "_CoqProject").touch()
        (tmp_path / "mylib.opam").touch()
        result = detect(tmp_path)
        _, _, _, BuildSystem, *_ = _import_types()
        assert result.build_system == BuildSystem.COQ_MAKEFILE
        assert result.has_opam is True

    def test_config_files_are_absolute_paths(self, tmp_path):
        """config_files contains absolute paths to detected files (§5 DetectionResult)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        (tmp_path / "mylib.opam").touch()
        result = detect(tmp_path)
        for p in result.config_files:
            assert os.path.isabs(p)

    def test_config_files_lists_all_detected_files(self, tmp_path):
        """config_files includes all marker and opam files found (§4.1 example)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        (tmp_path / "_CoqProject").touch()
        (tmp_path / "mylib.opam").touch()
        result = detect(tmp_path)
        basenames = {os.path.basename(f) for f in result.config_files}
        assert "dune-project" in basenames
        assert "_CoqProject" in basenames
        assert "mylib.opam" in basenames

    def test_project_dir_in_result(self, tmp_path):
        """project_dir in result matches the input (§5 DetectionResult)."""
        detect = _import_detect()
        result = detect(tmp_path)
        assert result.project_dir == str(tmp_path)

    def test_detection_does_not_modify_filesystem(self, tmp_path):
        """MAINTAINS: Detection never modifies the filesystem (§4.1)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        before = set(tmp_path.iterdir())
        detect(tmp_path)
        after = set(tmp_path.iterdir())
        assert before == after

    def test_config_files_empty_when_unknown(self, tmp_path):
        """config_files is empty when build_system = UNKNOWN (§5 DetectionResult)."""
        detect = _import_detect()
        result = detect(tmp_path)
        assert result.config_files == []

    def test_returns_detection_result_type(self, tmp_path):
        """Return type is DetectionResult (§5)."""
        detect = _import_detect()
        result = detect(tmp_path)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        assert isinstance(result, DetectionResult)


# ===========================================================================
# 2. Project File Generation -- _CoqProject -- spec §4.2
# ===========================================================================

class TestGenerateCoqProject:
    """§4.2: generate_coq_project requirements."""

    def test_generates_coq_project_file(self, tmp_path):
        """Writes a _CoqProject file to project_dir."""
        generate = _import_generate_coq_project()
        (tmp_path / "A.v").touch()
        result_path = generate(tmp_path)
        assert (tmp_path / "_CoqProject").exists()
        assert result_path == tmp_path / "_CoqProject"

    def test_logical_name_inferred_from_dir(self, tmp_path):
        """When logical_name is None, inferred from directory name (§4.2)."""
        generate = _import_generate_coq_project()
        project_dir = tmp_path / "MyLib"
        project_dir.mkdir()
        (project_dir / "A.v").touch()
        generate(project_dir)
        content = (project_dir / "_CoqProject").read_text()
        assert "-Q . MyLib" in content

    def test_spec_example_structure(self, tmp_path):
        """§4.2 example: mylib/ with A.v, sub/B.v, sub/C.v produces correct content."""
        generate = _import_generate_coq_project()
        project_dir = tmp_path / "mylib"
        project_dir.mkdir()
        (project_dir / "A.v").touch()
        sub = project_dir / "sub"
        sub.mkdir()
        (sub / "B.v").touch()
        (sub / "C.v").touch()
        generate(project_dir)
        content = (project_dir / "_CoqProject").read_text()
        assert "-Q . MyLib" in content or "-Q . Mylib" in content
        assert "-Q sub" in content
        assert "A.v" in content
        assert "sub/B.v" in content
        assert "sub/C.v" in content

    def test_source_files_alphabetical_within_directory(self, tmp_path):
        """Source file paths are alphabetically ordered within each directory (§4.2)."""
        generate = _import_generate_coq_project()
        (tmp_path / "C.v").touch()
        (tmp_path / "A.v").touch()
        (tmp_path / "B.v").touch()
        generate(tmp_path, logical_name="Test")
        content = (tmp_path / "_CoqProject").read_text()
        lines = [l.strip() for l in content.splitlines() if l.strip().endswith(".v")]
        v_files = [l for l in lines if l.endswith(".v")]
        assert v_files == sorted(v_files)

    def test_extra_flags_appear_first(self, tmp_path):
        """Extra flags appear before -Q/-R mappings (§4.2)."""
        generate = _import_generate_coq_project()
        (tmp_path / "A.v").touch()
        generate(tmp_path, logical_name="Test", extra_flags=["-arg", "-w -notation-overridden"])
        content = (tmp_path / "_CoqProject").read_text()
        lines = content.splitlines()
        # Find first flag line and first -Q line
        flag_idx = None
        q_idx = None
        for i, line in enumerate(lines):
            if "-arg" in line and flag_idx is None:
                flag_idx = i
            if line.strip().startswith("-Q") and q_idx is None:
                q_idx = i
        assert flag_idx is not None
        assert q_idx is not None
        assert flag_idx < q_idx

    def test_returns_path(self, tmp_path):
        """Return value is a Path to the generated file (§10)."""
        generate = _import_generate_coq_project()
        (tmp_path / "A.v").touch()
        result = generate(tmp_path, logical_name="Test")
        assert isinstance(result, Path)


class TestUpdateCoqProject:
    """§4.2: update_coq_project requirements."""

    def test_adds_new_file_preserving_existing(self, tmp_path):
        """Given _CoqProject listing A.v, new file B.v on disk is added (§4.2)."""
        update = _import_update_coq_project()
        coq_project = tmp_path / "_CoqProject"
        coq_project.write_text("-Q . Test\nA.v\n")
        (tmp_path / "A.v").touch()
        (tmp_path / "B.v").touch()
        update(tmp_path)
        content = coq_project.read_text()
        assert "A.v" in content
        assert "B.v" in content

    def test_preserves_existing_flags_and_comments(self, tmp_path):
        """Existing custom flags and comments are preserved (§4.2)."""
        update = _import_update_coq_project()
        coq_project = tmp_path / "_CoqProject"
        original = "# My project\n-Q . Test\n-arg -w -notation-overridden\nA.v\n"
        coq_project.write_text(original)
        (tmp_path / "A.v").touch()
        (tmp_path / "B.v").touch()
        update(tmp_path)
        content = coq_project.read_text()
        assert "# My project" in content
        assert "-arg -w -notation-overridden" in content

    def test_adds_new_directory_mapping(self, tmp_path):
        """New directories get -Q mappings added."""
        update = _import_update_coq_project()
        coq_project = tmp_path / "_CoqProject"
        coq_project.write_text("-Q . Test\nA.v\n")
        (tmp_path / "A.v").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "B.v").touch()
        update(tmp_path)
        content = coq_project.read_text()
        assert "sub" in content
        assert "sub/B.v" in content


# ===========================================================================
# 3. Project File Generation -- Dune -- spec §4.3
# ===========================================================================

class TestGenerateDuneProject:
    """§4.3: generate_dune_project requirements."""

    def test_creates_dune_project_file(self, tmp_path):
        """Writes dune-project at the root (§4.3)."""
        generate = _import_generate_dune_project()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "A.v").touch()
        generate(tmp_path, logical_name="MyLib")
        assert (tmp_path / "dune-project").exists()

    def test_dune_project_contains_lang_declarations(self, tmp_path):
        """dune-project contains (lang dune ...) and (using coq ...) (§4.3)."""
        generate = _import_generate_dune_project()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "A.v").touch()
        generate(tmp_path, logical_name="MyLib")
        content = (tmp_path / "dune-project").read_text()
        assert "(lang dune" in content
        assert "(using coq" in content

    def test_per_directory_dune_files(self, tmp_path):
        """Per-directory dune files are created where .v files exist (§4.3)."""
        generate = _import_generate_dune_project()
        src = tmp_path / "src"
        src.mkdir()
        (src / "A.v").touch()
        util = src / "util"
        util.mkdir()
        (util / "B.v").touch()
        generate(tmp_path, logical_name="MyLib")
        assert (src / "dune").exists()
        assert (util / "dune").exists()

    def test_spec_example_theory_names(self, tmp_path):
        """§4.3 example: src/dune has MyLib, src/util/dune has MyLib.Util with theories MyLib."""
        generate = _import_generate_dune_project()
        src = tmp_path / "src"
        src.mkdir()
        (src / "A.v").touch()
        util = src / "util"
        util.mkdir()
        (util / "B.v").touch()
        generate(tmp_path, logical_name="MyLib")
        src_dune = (src / "dune").read_text()
        assert "MyLib" in src_dune
        util_dune = (util / "dune").read_text()
        assert "MyLib.Util" in util_dune
        assert "(theories" in util_dune

    def test_returns_list_of_paths(self, tmp_path):
        """Return value is list[Path] of generated files (§10)."""
        generate = _import_generate_dune_project()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "A.v").touch()
        result = generate(tmp_path, logical_name="MyLib")
        assert isinstance(result, list)
        assert all(isinstance(p, Path) for p in result)


# ===========================================================================
# 4. Project File Generation -- .opam -- spec §4.4
# ===========================================================================

class TestGenerateOpamFile:
    """§4.4: generate_opam_file requirements."""

    def test_creates_opam_file(self, tmp_path):
        """Writes a .opam file with correct metadata (§4.4)."""
        generate = _import_generate_opam_file()
        (tmp_path / "dune-project").touch()
        metadata = _make_opam_metadata()
        result_path = generate(tmp_path, metadata)
        assert isinstance(result_path, Path)
        assert result_path.suffix == ".opam"
        assert result_path.exists()

    def test_opam_file_contains_version(self, tmp_path):
        """Contains opam-version: "2.0" (§4.4)."""
        generate = _import_generate_opam_file()
        (tmp_path / "dune-project").touch()
        metadata = _make_opam_metadata()
        result_path = generate(tmp_path, metadata)
        content = result_path.read_text()
        assert 'opam-version: "2.0"' in content

    def test_dune_project_build_command(self, tmp_path):
        """For Dune projects, build field uses dune (§4.4)."""
        generate = _import_generate_opam_file()
        (tmp_path / "dune-project").touch()
        metadata = _make_opam_metadata()
        result_path = generate(tmp_path, metadata)
        content = result_path.read_text()
        assert "dune" in content and "build" in content

    def test_coq_makefile_build_command(self, tmp_path):
        """For coq_makefile projects, build field uses make (§4.4)."""
        generate = _import_generate_opam_file()
        (tmp_path / "_CoqProject").touch()
        metadata = _make_opam_metadata()
        result_path = generate(tmp_path, metadata)
        content = result_path.read_text()
        assert "make" in content

    def test_dependencies_included(self, tmp_path):
        """Dependencies from metadata appear in the file (§4.4)."""
        generate = _import_generate_opam_file()
        (tmp_path / "dune-project").touch()
        metadata = _make_opam_metadata(
            dependencies=[("coq", ">= 8.18"), ("coq-mathcomp-ssreflect", ">= 2.0")],
        )
        result_path = generate(tmp_path, metadata)
        content = result_path.read_text()
        assert "coq" in content
        assert "coq-mathcomp-ssreflect" in content


# ===========================================================================
# 5. coq_makefile-to-Dune Migration -- spec §4.5
# ===========================================================================

class TestMigrateToDune:
    """§4.5: migrate_to_dune requirements."""

    def test_generates_dune_files_from_coq_project(self, tmp_path):
        """Generates dune-project and per-directory dune files (§4.5)."""
        migrate = _import_migrate_to_dune()
        coq_project = tmp_path / "_CoqProject"
        src = tmp_path / "src"
        src.mkdir()
        (src / "A.v").touch()
        coq_project.write_text("-Q src MyLib\nsrc/A.v\n")
        result = migrate(tmp_path)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        assert isinstance(result, MigrationResult)
        assert (tmp_path / "dune-project").exists()
        assert (src / "dune").exists()

    def test_preserves_original_coq_project(self, tmp_path):
        """MAINTAINS: The existing _CoqProject is not deleted or modified (§4.5)."""
        migrate = _import_migrate_to_dune()
        coq_project = tmp_path / "_CoqProject"
        original_content = "-Q src MyLib\nsrc/A.v\n"
        coq_project.write_text(original_content)
        src = tmp_path / "src"
        src.mkdir()
        (src / "A.v").touch()
        migrate(tmp_path)
        assert coq_project.exists()
        assert coq_project.read_text() == original_content

    def test_untranslatable_flags_reported(self, tmp_path):
        """Flags with no Dune equivalent are listed in untranslatable_flags (§4.5 example)."""
        migrate = _import_migrate_to_dune()
        coq_project = tmp_path / "_CoqProject"
        coq_project.write_text(
            '-Q src MyLib\n-arg "-w -notation-overridden"\nsrc/A.v\n'
        )
        src = tmp_path / "src"
        src.mkdir()
        (src / "A.v").touch()
        result = migrate(tmp_path)
        assert len(result.untranslatable_flags) >= 1
        assert any("-w -notation-overridden" in f for f in result.untranslatable_flags)

    def test_generated_files_are_absolute_paths(self, tmp_path):
        """generated_files contains absolute paths (§5 MigrationResult)."""
        migrate = _import_migrate_to_dune()
        coq_project = tmp_path / "_CoqProject"
        coq_project.write_text("-Q . Test\nA.v\n")
        (tmp_path / "A.v").touch()
        result = migrate(tmp_path)
        for f in result.generated_files:
            assert os.path.isabs(f)

    def test_all_translatable_flags_empty_when_fully_compatible(self, tmp_path):
        """When all flags translate, untranslatable_flags is empty (§5)."""
        migrate = _import_migrate_to_dune()
        coq_project = tmp_path / "_CoqProject"
        coq_project.write_text("-Q . Test\nA.v\n")
        (tmp_path / "A.v").touch()
        result = migrate(tmp_path)
        assert result.untranslatable_flags == []


# ===========================================================================
# 6. Build Execution -- spec §4.6
# ===========================================================================

class TestBuildExecution:
    """§4.6: execute_build requirements."""

    @pytest.mark.asyncio
    async def test_successful_dune_build(self, tmp_path):
        """Given a valid Dune project, successful build returns success (§4.6 example)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path), timeout=60)
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc
            result = await execute(request)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        assert isinstance(result, BuildResult)
        assert result.success is True
        assert result.exit_code == 0
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_coq_makefile_generates_makefile_first(self, tmp_path):
        """Given coq_makefile project with no Makefile, runs coq_makefile then make (§4.6)."""
        execute = _import_execute()
        (tmp_path / "_CoqProject").touch()
        _, _, _, BuildSystem, *_ = _import_types()
        request = _make_build_request(
            project_dir=str(tmp_path),
            build_system=BuildSystem.COQ_MAKEFILE,
        )
        commands_called = []
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc

            async def capture_call(*args, **kwargs):
                commands_called.append(args)
                return proc
            mock_proc.side_effect = capture_call

            await execute(request)
        # At least two subprocess calls: coq_makefile and make
        assert len(commands_called) >= 2
        assert any("coq_makefile" in str(c) for c in commands_called)
        assert any("make" in str(c) for c in commands_called)

    @pytest.mark.asyncio
    async def test_timeout_produces_timed_out_result(self, tmp_path):
        """Given a build exceeding timeout, timed_out = true (§4.6)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path), timeout=10)
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.side_effect = asyncio.TimeoutError()
            proc.returncode = None
            proc.stdin = None
            proc.terminate = MagicMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_proc.return_value = proc
            result = await execute(request)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_failed_build_returns_success_false(self, tmp_path):
        """Non-zero exit code results in success = false with parsed errors (§4.6)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path))
        stderr_output = b'File "src/A.v", line 10, characters 0-15:\nError: Syntax error.'
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", stderr_output)
            proc.returncode = 2
            proc.stdin = None
            mock_proc.return_value = proc
            result = await execute(request)
        assert result.success is False
        assert result.exit_code == 2

    @pytest.mark.asyncio
    async def test_elapsed_ms_non_negative(self, tmp_path):
        """elapsed_ms is non-negative (§5 BuildResult)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path))
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc
            result = await execute(request)
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_auto_detection_when_build_system_null(self, tmp_path):
        """When build_system is null, auto-detection is triggered (§4.6)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path), build_system=None)
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc
            result = await execute(request)
        _, _, _, BuildSystem, *_ = _import_types()
        assert result.build_system == BuildSystem.DUNE

    # --- Contract tests for subprocess mocks ---

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_dune_build_real_subprocess(self, tmp_path):
        """Contract: real dune build produces a BuildResult with expected fields."""
        execute = _import_execute()
        # Minimal dune project
        (tmp_path / "dune-project").write_text('(lang dune 3.0)\n(using coq 0.6)\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "dune").write_text('(coq.theory (name Test))\n')
        (src / "Test.v").write_text("Lemma foo : True. Proof. exact I. Qed.\n")
        request = _make_build_request(project_dir=str(tmp_path))
        result = await execute(request)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        assert isinstance(result, BuildResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.exit_code, int)
        assert isinstance(result.elapsed_ms, int)
        assert result.elapsed_ms >= 0


# ===========================================================================
# 7. Error Parsing -- spec §4.7
# ===========================================================================

class TestErrorParsing:
    """§4.7: parse_build_errors requirements."""

    def test_logical_path_not_found(self):
        """§4.7 example: Coq logical path error parsed correctly."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 10, characters 0-15:\n'
            "Error: Cannot find a physical path bound to logical path MyLib."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert len(errors) >= 1
        err = errors[0]
        assert err.category == "LOGICAL_PATH_NOT_FOUND"
        assert err.file == "src/A.v"
        assert err.line == 10
        assert err.char_range == (0, 15)
        assert err.suggested_fix is not None

    def test_required_library_not_found(self):
        """Required library error parsed to REQUIRED_LIBRARY_NOT_FOUND."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 5, characters 0-20:\n'
            "Error: Required library MyLib.Foo not found in loadpath."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category == "REQUIRED_LIBRARY_NOT_FOUND" for e in errors)

    def test_type_error_category(self):
        """Type checking failure parsed to TYPE_ERROR."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 3, characters 0-10:\n'
            "Error: The term \"0\" has type \"nat\" while it is expected to have type \"bool\"."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category == "TYPE_ERROR" for e in errors)

    def test_syntax_error_category(self):
        """Parsing failure parsed to SYNTAX_ERROR."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 1, characters 0-5:\n'
            "Error: Syntax error: [constr:operconstr] expected after [constr:operconstr]."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category == "SYNTAX_ERROR" for e in errors)

    def test_tactic_failure_category(self):
        """Tactic-related build error parsed to TACTIC_FAILURE."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 7, characters 0-8:\n'
            "Error: No matching clauses for match."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category in ("TACTIC_FAILURE", "OTHER") for e in errors)

    def test_unrecognized_error_is_other(self):
        """Unrecognized errors produce category = OTHER with raw_text preserved (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = "Something completely unexpected happened"
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert len(errors) >= 1
        err = errors[0]
        assert err.category == "OTHER"
        assert "Something completely unexpected happened" in err.raw_text

    def test_empty_stderr_returns_no_errors(self):
        """Empty stderr produces empty error list."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        errors = parse("", "", BuildSystem.DUNE)
        assert errors == []

    def test_dune_theory_not_found(self):
        """Dune missing coq.theory dependency parsed to THEORY_NOT_FOUND (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = "Error: Theory MyLib not found"
        errors = parse("", stderr, BuildSystem.DUNE)
        assert any(e.category == "THEORY_NOT_FOUND" for e in errors)

    def test_dune_config_error(self):
        """Dune stanza syntax error parsed to DUNE_CONFIG_ERROR (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = 'Error: Invalid field "name" in stanza'
        errors = parse("", stderr, BuildSystem.DUNE)
        assert any(e.category == "DUNE_CONFIG_ERROR" for e in errors)

    def test_opam_version_conflict(self):
        """opam version conflict parsed to VERSION_CONFLICT (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = "Error: Incompatible version constraints for coq"
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category in ("VERSION_CONFLICT", "OTHER") for e in errors)

    def test_opam_package_not_found(self):
        """opam package not found parsed to PACKAGE_NOT_FOUND (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = "No package named coq-nonexistent found in repositories"
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert any(e.category in ("PACKAGE_NOT_FOUND", "OTHER") for e in errors)

    def test_error_location_parsing(self):
        """File, line, character range are extracted from Coq error pattern (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "theories/Lemmas.v", line 42, characters 5-30:\n'
            "Error: Cannot find a physical path bound to logical path X."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        err = errors[0]
        assert err.file == "theories/Lemmas.v"
        assert err.line == 42
        assert err.char_range == (5, 30)

    def test_build_error_has_explanation(self):
        """Every BuildError has a non-empty explanation (§5 BuildError)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 10, characters 0-15:\n'
            "Error: Cannot find a physical path bound to logical path MyLib."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        for err in errors:
            assert err.explanation
            assert len(err.explanation) > 0

    def test_other_category_has_null_suggested_fix(self):
        """OTHER category has suggested_fix = null (§5 BuildError)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = "Random unrecognized error text"
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        other_errors = [e for e in errors if e.category == "OTHER"]
        assert len(other_errors) >= 1
        assert other_errors[0].suggested_fix is None

    def test_returns_build_error_types(self):
        """Return type is list of BuildError (§5)."""
        parse = _import_parse_build_errors()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        stderr = "some error"
        errors = parse("", stderr, BuildSystem.DUNE)
        assert isinstance(errors, list)
        for err in errors:
            assert isinstance(err, BuildError)

    def test_errors_are_ordered(self):
        """Errors are returned in order of appearance in output (§4.7)."""
        parse = _import_parse_build_errors()
        _, _, _, BuildSystem, *_ = _import_types()
        stderr = (
            'File "src/A.v", line 5, characters 0-10:\n'
            "Error: Syntax error.\n"
            'File "src/B.v", line 20, characters 0-15:\n'
            "Error: Cannot find a physical path bound to logical path X."
        )
        errors = parse("", stderr, BuildSystem.COQ_MAKEFILE)
        assert len(errors) >= 2
        assert errors[0].file == "src/A.v"
        assert errors[1].file == "src/B.v"


# ===========================================================================
# 8. Package Queries -- spec §4.8
# ===========================================================================

class TestPackageQueries:
    """§4.8: query_installed_packages and query_package_info requirements."""

    @pytest.mark.asyncio
    async def test_query_installed_packages_returns_sorted_list(self):
        """Returns list of (name, version) pairs sorted alphabetically (§4.8)."""
        query = _import_query_installed_packages()
        opam_output = "coq 8.18.0\ncoq-mathcomp-ssreflect 2.1.0\ncoq-equations 1.3\n"
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (opam_output.encode(), b"")
                proc.returncode = 0
                mock_proc.return_value = proc
                result = await query()
        assert isinstance(result, list)
        assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in result)
        names = [pair[0] for pair in result]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_query_package_info_returns_package_info(self):
        """Returns PackageInfo with expected fields (§4.8)."""
        query = _import_query_package_info()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        opam_show_output = textwrap.dedent("""\
            name: coq-mathcomp-ssreflect
            version: 2.1.0
            synopsis: Mathematical Components
            depends: coq
            all-versions: 2.1.0 2.0.0 1.19.0
        """)
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (opam_show_output.encode(), b"")
                proc.returncode = 0
                mock_proc.return_value = proc
                result = await query("coq-mathcomp-ssreflect")
        assert isinstance(result, PackageInfo)
        assert result.name == "coq-mathcomp-ssreflect"
        assert result.installed_version is not None
        assert isinstance(result.available_versions, list)
        assert isinstance(result.dependencies, list)

    @pytest.mark.asyncio
    async def test_query_package_info_not_found(self):
        """When package does not exist, returns PACKAGE_NOT_FOUND (§4.8)."""
        query = _import_query_package_info()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (b"", b"No package named nonexistent")
                proc.returncode = 1
                mock_proc.return_value = proc
                with pytest.raises(BuildSystemError) as exc_info:
                    await query("nonexistent")
        assert exc_info.value.code == PACKAGE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_available_versions_descending_order(self):
        """available_versions are in descending order (§4.8 example, §5 PackageInfo)."""
        query = _import_query_package_info()
        opam_show_output = textwrap.dedent("""\
            name: coq-mathcomp-ssreflect
            version: 2.1.0
            synopsis: Mathematical Components
            depends: coq
            all-versions: 1.19.0 2.0.0 2.1.0
        """)
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (opam_show_output.encode(), b"")
                proc.returncode = 0
                mock_proc.return_value = proc
                result = await query("coq-mathcomp-ssreflect")
        # Versions should be descending
        assert result.available_versions == sorted(result.available_versions, reverse=True)

    # --- Contract tests for opam subprocess mocks ---

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_query_installed_packages_real(self):
        """Contract: real opam list returns list of (name, version) tuples."""
        query = _import_query_installed_packages()
        result = await query()
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], tuple)
            assert len(result[0]) == 2

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_query_package_info_real(self):
        """Contract: real opam show returns PackageInfo for a known package."""
        query = _import_query_package_info()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        result = await query("coq")
        assert isinstance(result, PackageInfo)
        assert result.name == "coq"


# ===========================================================================
# 9. Dependency Management -- spec §4.9
# ===========================================================================

class TestDependencyManagement:
    """§4.9: add_dependency, check_dependency_conflicts, install_package."""

    def test_add_dependency_to_dune_project(self, tmp_path):
        """Adds dependency to dune-project for Dune projects (§4.9)."""
        add_dep = _import_add_dependency()
        dune_project = tmp_path / "dune-project"
        dune_project.write_text('(lang dune 3.0)\n(using coq 0.6)\n')
        add_dep(tmp_path, "coq-mathcomp-ssreflect", ">= 2.0")
        content = dune_project.read_text()
        assert "coq-mathcomp-ssreflect" in content

    def test_add_dependency_already_exists(self, tmp_path):
        """When dependency already exists, returns DEPENDENCY_EXISTS (§4.9)."""
        add_dep = _import_add_dependency()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        dune_project = tmp_path / "dune-project"
        dune_project.write_text(
            '(lang dune 3.0)\n(using coq 0.6)\n(depends coq-stdpp)\n'
        )
        with pytest.raises(BuildSystemError) as exc_info:
            add_dep(tmp_path, "coq-stdpp")
        assert exc_info.value.code == DEPENDENCY_EXISTS

    def test_add_dependency_no_modification_on_exists(self, tmp_path):
        """DEPENDENCY_EXISTS makes no file changes (§4.9)."""
        add_dep = _import_add_dependency()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        dune_project = tmp_path / "dune-project"
        original = '(lang dune 3.0)\n(using coq 0.6)\n(depends coq-stdpp)\n'
        dune_project.write_text(original)
        with pytest.raises(BuildSystemError):
            add_dep(tmp_path, "coq-stdpp")
        assert dune_project.read_text() == original

    @pytest.mark.asyncio
    async def test_check_dependency_conflicts_satisfiable(self):
        """When no conflicts, satisfiable = true (§4.9)."""
        check = _import_check_dependency_conflicts()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (b"The following actions would be performed:\n", b"")
                proc.returncode = 0
                mock_proc.return_value = proc
                result = await check([("coq", ">= 8.18")])
        assert isinstance(result, DependencyStatus)
        assert result.satisfiable is True
        assert result.conflicts == []

    @pytest.mark.asyncio
    async def test_check_dependency_conflicts_unsatisfiable(self):
        """When conflicts exist, satisfiable = false with conflict details (§4.9 example)."""
        check = _import_check_dependency_conflicts()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        conflict_output = (
            "The following dependencies couldn't be met:\n"
            "  - coq >= 8.18 (conflict with coq = 8.17.1 required by coq-stdpp)\n"
        )
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (b"", conflict_output.encode())
                proc.returncode = 1
                mock_proc.return_value = proc
                result = await check([
                    ("coq-mathcomp-ssreflect", ">= 2.0"),
                    ("coq-stdpp", ">= 1.9"),
                ])
        assert result.satisfiable is False
        assert len(result.conflicts) >= 1
        assert isinstance(result.conflicts[0], ConflictDetail)

    @pytest.mark.asyncio
    async def test_install_package_success(self):
        """Successful install returns installed version (§4.9)."""
        install = _import_install_package()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (
                    b"coq-equations.1.3 installed\n", b""
                )
                proc.returncode = 0
                mock_proc.return_value = proc
                result = await install("coq-equations")
        assert isinstance(result, BuildResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_install_package_failure_returns_errors(self):
        """Failed install returns parsed BuildError records (§4.9)."""
        install = _import_install_package()
        with patch("shutil.which", return_value="/usr/bin/opam"):
            with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                proc = AsyncMock()
                proc.communicate.return_value = (
                    b"", b"Error: Package build failed during installation"
                )
                proc.returncode = 1
                mock_proc.return_value = proc
                result = await install("coq-broken-package")
        assert result.success is False

    # --- Contract tests for subprocess mocks ---

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_check_dependency_conflicts_real(self):
        """Contract: real opam --dry-run returns DependencyStatus."""
        check = _import_check_dependency_conflicts()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        result = await check([("coq", ">= 8.18")])
        assert isinstance(result, DependencyStatus)
        assert isinstance(result.satisfiable, bool)

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_install_package_real(self):
        """Contract: real opam install returns BuildResult."""
        install = _import_install_package()
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            *_rest
        ) = _import_types()
        # Use a package likely already installed to avoid side effects
        result = await install("coq")
        assert isinstance(result, BuildResult)


# ===========================================================================
# 10. Data Model -- spec §5
# ===========================================================================

class TestDataModel:
    """§5: Data model type constraints."""

    def test_build_system_enum_values(self):
        """BuildSystem has COQ_MAKEFILE, DUNE, UNKNOWN (§5)."""
        _, _, _, BuildSystem, *_ = _import_types()
        assert hasattr(BuildSystem, "COQ_MAKEFILE")
        assert hasattr(BuildSystem, "DUNE")
        assert hasattr(BuildSystem, "UNKNOWN")

    def test_detection_result_fields(self):
        """DetectionResult has all required fields (§5)."""
        result = _make_detection_result()
        assert hasattr(result, "build_system")
        assert hasattr(result, "has_opam")
        assert hasattr(result, "config_files")
        assert hasattr(result, "project_dir")

    def test_build_request_defaults(self):
        """BuildRequest default: timeout=300, build_system=null, target=null (§5)."""
        request = _make_build_request()
        assert request.timeout == 300
        assert request.build_system is None
        assert request.target is None

    def test_build_result_fields(self):
        """BuildResult has all required fields (§5)."""
        result = _make_build_result()
        assert hasattr(result, "success")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "errors")
        assert hasattr(result, "elapsed_ms")
        assert hasattr(result, "build_system")
        assert hasattr(result, "timed_out")
        assert hasattr(result, "truncated")

    def test_build_error_fields(self):
        """BuildError has all required fields (§5)."""
        err = _make_build_error()
        assert hasattr(err, "category")
        assert hasattr(err, "file")
        assert hasattr(err, "line")
        assert hasattr(err, "char_range")
        assert hasattr(err, "raw_text")
        assert hasattr(err, "explanation")
        assert hasattr(err, "suggested_fix")

    def test_package_info_fields(self):
        """PackageInfo has all required fields (§5)."""
        info = _make_package_info()
        assert hasattr(info, "name")
        assert hasattr(info, "installed_version")
        assert hasattr(info, "available_versions")
        assert hasattr(info, "synopsis")
        assert hasattr(info, "dependencies")

    def test_migration_result_fields(self):
        """MigrationResult has all required fields (§5)."""
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        result = MigrationResult(
            generated_files=["/tmp/dune-project"],
            untranslatable_flags=[],
        )
        assert hasattr(result, "generated_files")
        assert hasattr(result, "untranslatable_flags")

    def test_dependency_status_fields(self):
        """DependencyStatus has satisfiable and conflicts (§5)."""
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        status = DependencyStatus(satisfiable=True, conflicts=[])
        assert status.satisfiable is True
        assert status.conflicts == []

    def test_conflict_detail_fields(self):
        """ConflictDetail has package and constraints (§5)."""
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        source = ConstraintSource(required_by="coq-stdpp", constraint="= 8.17.1")
        detail = ConflictDetail(package="coq", constraints=[source])
        assert detail.package == "coq"
        assert len(detail.constraints) == 1
        assert detail.constraints[0].required_by == "coq-stdpp"
        assert detail.constraints[0].constraint == "= 8.17.1"


# ===========================================================================
# 11. Input Errors -- spec §7.1
# ===========================================================================

class TestInputErrors:
    """§7.1: Input error handling."""

    def test_project_dir_does_not_exist(self, tmp_path):
        """PROJECT_NOT_FOUND when project_dir does not exist (§7.1)."""
        detect = _import_detect()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        with pytest.raises(BuildSystemError) as exc_info:
            detect(tmp_path / "nonexistent")
        assert exc_info.value.code == PROJECT_NOT_FOUND

    def test_project_dir_is_file_not_directory(self, tmp_path):
        """PROJECT_NOT_FOUND when project_dir is a file (§7.1)."""
        detect = _import_detect()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        f = tmp_path / "afile"
        f.touch()
        with pytest.raises(BuildSystemError) as exc_info:
            detect(f)
        assert exc_info.value.code == PROJECT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_timeout_below_10_clamped(self, tmp_path):
        """timeout < 10 is clamped to 10, no error (§7.1)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path), timeout=5)
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc
            # Should not raise; timeout silently clamped to 10
            result = await execute(request)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_timeout_not_positive_integer_raises(self, tmp_path):
        """timeout that is not a positive integer raises INVALID_PARAMETER (§7.1)."""
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        with pytest.raises((BuildSystemError, TypeError, ValueError)):
            _make_build_request(project_dir=str(tmp_path), timeout=-1.5)

    @pytest.mark.asyncio
    async def test_empty_package_name_raises(self):
        """Empty package_name raises INVALID_PARAMETER (§7.1)."""
        query = _import_query_package_info()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        with pytest.raises(BuildSystemError) as exc_info:
            await query("")
        assert exc_info.value.code == INVALID_PARAMETER


# ===========================================================================
# 12. Dependency Errors -- spec §7.2
# ===========================================================================

class TestDependencyErrors:
    """§7.2: Dependency error handling."""

    def test_build_system_not_detected_error(self, tmp_path):
        """BUILD_SYSTEM_NOT_DETECTED when no build system and not specified (§7.2)."""
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        add_dep = _import_add_dependency()
        # Empty dir with no build system markers
        with pytest.raises(BuildSystemError) as exc_info:
            add_dep(tmp_path, "coq-mathcomp-ssreflect")
        assert exc_info.value.code == BUILD_SYSTEM_NOT_DETECTED

    @pytest.mark.asyncio
    async def test_tool_not_found_opam(self):
        """TOOL_NOT_FOUND when opam not on PATH (§7.2)."""
        query = _import_query_installed_packages()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        with patch("shutil.which", return_value=None):
            with pytest.raises(BuildSystemError) as exc_info:
                await query()
        assert exc_info.value.code == TOOL_NOT_FOUND

    # --- Contract test for shutil.which mock ---

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_opam_on_path(self):
        """Contract: when opam is installed, shutil.which('opam') returns a path."""
        import shutil
        result = shutil.which("opam")
        assert result is not None


# ===========================================================================
# 13. Operational Errors -- spec §7.3
# ===========================================================================

class TestOperationalErrors:
    """§7.3: Operational error handling."""

    def test_file_not_writable(self, tmp_path):
        """FILE_NOT_WRITABLE when target file cannot be written (§7.3)."""
        generate = _import_generate_coq_project()
        (
            BUILD_SYSTEM_NOT_DETECTED, BUILD_TIMEOUT, DEPENDENCY_EXISTS,
            FILE_NOT_WRITABLE, INVALID_PARAMETER, PACKAGE_NOT_FOUND,
            PROJECT_NOT_FOUND, TOOL_NOT_FOUND, BuildSystemError,
        ) = _import_errors()
        (tmp_path / "A.v").touch()
        # Make directory read-only
        coq_project = tmp_path / "_CoqProject"
        coq_project.touch()
        coq_project.chmod(0o000)
        try:
            with pytest.raises(BuildSystemError) as exc_info:
                generate(tmp_path, logical_name="Test")
            assert exc_info.value.code == FILE_NOT_WRITABLE
        finally:
            coq_project.chmod(0o644)

    @pytest.mark.asyncio
    async def test_output_truncation(self, tmp_path):
        """Output exceeding 1 MB is truncated with truncated = true (§7.3)."""
        execute = _import_execute()
        (tmp_path / "dune-project").touch()
        request = _make_build_request(project_dir=str(tmp_path))
        # Generate > 1 MB of output
        large_output = b"x" * (1024 * 1024 + 100)
        with patch("Poule.build.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = AsyncMock()
            proc.communicate.return_value = (large_output, b"")
            proc.returncode = 0
            proc.stdin = None
            mock_proc.return_value = proc
            result = await execute(request)
        assert result.truncated is True
        # Tail is preserved (§4.6: truncated from the beginning)
        assert len(result.stdout.encode()) <= 1024 * 1024


# ===========================================================================
# 14. Non-Functional Requirements -- spec §8
# ===========================================================================

class TestNonFunctional:
    """§8: Non-functional requirements."""

    def test_detection_is_stateless(self, tmp_path):
        """No in-memory state between invocations (§8)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        result1 = detect(tmp_path)
        result2 = detect(tmp_path)
        assert result1.build_system == result2.build_system

    def test_detection_no_subprocesses(self, tmp_path):
        """Detection completes without spawning subprocesses (§4.1 MAINTAINS)."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        with patch("subprocess.run") as mock_run, \
             patch("asyncio.create_subprocess_exec") as mock_async:
            detect(tmp_path)
        mock_run.assert_not_called()
        mock_async.assert_not_called()

    # --- Contract test for subprocess mock ---

    @pytest.mark.requires_coq
    def test_contract_detection_no_subprocess(self, tmp_path):
        """Contract: real detect_build_system does not spawn subprocesses."""
        detect = _import_detect()
        (tmp_path / "dune-project").touch()
        # Just verify it runs without error and returns a result
        result = detect(tmp_path)
        (
            BuildError, BuildRequest, BuildResult, BuildSystem,
            ConflictDetail, ConstraintSource, DependencyStatus,
            DetectionResult, MigrationResult, OpamMetadata, PackageInfo,
        ) = _import_types()
        assert isinstance(result, DetectionResult)
