"""Build system integration package (specification/build-system-integration.md)."""

import asyncio  # exposed so tests can patch poule.build.asyncio.create_subprocess_exec

from poule.build.adapter import (
    add_dependency,
    check_dependency_conflicts,
    execute_build,
    install_package,
    parse_build_errors,
    query_installed_packages,
    query_package_info,
)
from poule.build.detection import detect_build_system
from poule.build.generation import (
    generate_coq_project,
    generate_dune_project,
    generate_opam_file,
    migrate_to_dune,
    update_coq_project,
)

__all__ = [
    "detect_build_system",
    "execute_build",
    "generate_coq_project",
    "update_coq_project",
    "generate_dune_project",
    "generate_opam_file",
    "migrate_to_dune",
    "parse_build_errors",
    "query_installed_packages",
    "query_package_info",
    "install_package",
    "add_dependency",
    "check_dependency_conflicts",
]
