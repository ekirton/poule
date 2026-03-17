"""Parser for Coq Print Assumptions output."""

from __future__ import annotations

from poule.auditing.errors import AuditError
from poule.auditing.types import ParsedDependency, ParsedOutput


def parse_print_assumptions(output: str) -> ParsedOutput:
    """Parse the output of Coq's Print Assumptions command.

    Returns a ParsedOutput with is_closed, dependencies, and empty
    axioms/opaque_dependencies (separation happens in the engine).

    Raises AuditError with PARSE_ERROR on empty or unparseable output.
    """
    if not output or not output.strip():
        raise AuditError("PARSE_ERROR", "Empty Print Assumptions output.")

    stripped = output.strip()

    # Closed theorem
    if stripped == "Closed under the global context":
        return ParsedOutput(is_closed=True, dependencies=[])

    # Parse dependency lines
    dependencies: list[ParsedDependency] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        if " : " not in line:
            raise AuditError(
                "PARSE_ERROR",
                f"Cannot parse dependency line: {line!r}",
            )
        name, dep_type = line.split(" : ", maxsplit=1)
        dependencies.append(ParsedDependency(name=name.strip(), type=dep_type.strip()))

    if not dependencies:
        raise AuditError("PARSE_ERROR", "No dependencies parsed from non-closed output.")

    return ParsedOutput(is_closed=False, dependencies=dependencies)
