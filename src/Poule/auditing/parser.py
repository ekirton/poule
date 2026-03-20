"""Parser for Coq Print Assumptions output."""

from __future__ import annotations

import re

from Poule.auditing.errors import AuditError
from Poule.auditing.types import ParsedDependency, ParsedOutput

# coqtop prepends a REPL prompt like "Rocq < " or "Coq < " to output lines.
_PROMPT_RE = re.compile(r"^(?:Rocq|Coq)\s*<\s*")


def _strip_prompt(text: str) -> str:
    """Strip REPL prompt prefix from each line of coqtop output."""
    lines = text.split("\n")
    return "\n".join(_PROMPT_RE.sub("", line) for line in lines)


def parse_print_assumptions(output: str) -> ParsedOutput:
    """Parse the output of Coq's Print Assumptions command.

    Returns a ParsedOutput with is_closed, dependencies, and empty
    axioms/opaque_dependencies (separation happens in the engine).

    Raises AuditError with PARSE_ERROR on empty or unparseable output.
    """
    if not output or not output.strip():
        raise AuditError("PARSE_ERROR", "Empty Print Assumptions output.")

    stripped = _strip_prompt(output).strip()

    # Closed theorem (Coq may wrap the line, e.g. "Closed under the global\n  context")
    if " ".join(stripped.split()) == "Closed under the global context":
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
