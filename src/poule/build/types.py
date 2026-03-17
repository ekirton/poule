"""Data model types for the build system integration layer."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class BuildSystem(enum.Enum):
    """Build system enumeration (spec section 5)."""

    COQ_MAKEFILE = "COQ_MAKEFILE"
    DUNE = "DUNE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DetectionResult:
    """Result of build system detection (spec section 5)."""

    build_system: BuildSystem
    has_opam: bool
    config_files: list[str]
    project_dir: str


@dataclass
class BuildRequest:
    """Request parameters for a build execution (spec section 5)."""

    project_dir: str
    build_system: Optional[BuildSystem] = None
    target: Optional[str] = None
    timeout: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool):
            raise TypeError(f"timeout must be a positive integer, got {type(self.timeout).__name__}")
        if self.timeout != int(self.timeout) or self.timeout < 0:
            raise ValueError(f"timeout must be a positive integer, got {self.timeout}")
        self.timeout = int(self.timeout)


@dataclass
class BuildError:
    """A structured error parsed from build output (spec section 5)."""

    category: str
    file: Optional[str] = None
    line: Optional[int] = None
    char_range: Optional[tuple[int, int]] = None
    raw_text: str = ""
    explanation: str = ""
    suggested_fix: Optional[str] = None


@dataclass
class BuildResult:
    """Result of a build execution (spec section 5)."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    errors: list[BuildError]
    elapsed_ms: int
    build_system: BuildSystem
    timed_out: bool
    truncated: bool


@dataclass
class OpamMetadata:
    """Metadata for generating an .opam file (spec section 4.4)."""

    name: str
    version: str
    synopsis: str
    maintainer: str
    dependencies: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class PackageInfo:
    """Information about an opam package (spec section 5)."""

    name: str
    installed_version: Optional[str]
    available_versions: list[str]
    synopsis: str
    dependencies: list[str]


@dataclass
class MigrationResult:
    """Result of coq_makefile-to-Dune migration (spec section 5)."""

    generated_files: list[str]
    untranslatable_flags: list[str]


@dataclass
class DependencyStatus:
    """Result of dependency conflict check (spec section 5)."""

    satisfiable: bool
    conflicts: list[ConflictDetail]


@dataclass
class ConflictDetail:
    """Details of a dependency conflict (spec section 5)."""

    package: str
    constraints: list[ConstraintSource]


@dataclass
class ConstraintSource:
    """A version constraint imposed by a package (spec section 5)."""

    required_by: str
    constraint: str
