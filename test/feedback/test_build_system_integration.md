---
name: test_build_system_integration implicit opam dependency
description: 8 tests implicitly require opam on PATH despite not being marked @pytest.mark.requires_coq
type: feedback
severity: medium
---

## Issue

Eight tests in `TestPackageQueries` and `TestDependencyManagement` mock
`asyncio.create_subprocess_exec` but do NOT mock `shutil.which`. The
implementation calls `_check_tool("opam")` — which uses `shutil.which("opam")`
— **before** the subprocess is created. In an environment without opam, the
tool check raises `BuildSystemError(TOOL_NOT_FOUND, ...)` before the mocked
subprocess is ever reached.

Affected tests:
- `TestPackageQueries::test_query_installed_packages_returns_sorted_list`
- `TestPackageQueries::test_query_package_info_returns_package_info`
- `TestPackageQueries::test_query_package_info_not_found`
- `TestPackageQueries::test_available_versions_descending_order`
- `TestDependencyManagement::test_check_dependency_conflicts_satisfiable`
- `TestDependencyManagement::test_check_dependency_conflicts_unsatisfiable`
- `TestDependencyManagement::test_install_package_success`
- `TestDependencyManagement::test_install_package_failure_returns_errors`

## Conflict

`TestDependencyErrors::test_tool_not_found_opam` correctly patches
`shutil.which` to simulate opam absence — this test passes in all
environments. The 8 failing tests were apparently written for an environment
where opam IS installed so that `shutil.which("opam")` returns a path, allowing
the mock subprocess to be reached.

## Suggested Resolution

Either:
1. Mark these 8 tests `@pytest.mark.requires_opam` (or `@pytest.mark.requires_coq`)
   so they are skipped when opam is not present, OR
2. Add `patch("shutil.which", return_value="/usr/bin/opam")` alongside the
   `asyncio.create_subprocess_exec` mock in each of these tests so they
   work without requiring opam to actually be installed.

Filed by: TDD implementation agent (2026-03-17)
