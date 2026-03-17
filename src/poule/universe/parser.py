"""Constraint parsing from raw Coq output.

Spec: specification/universe-inspection.md section 4.3.
"""

from __future__ import annotations

import re
from typing import List

from poule.universe.types import UniverseConstraint, UniverseExpression

# Precompiled patterns for the three constraint formats.
# Matches lines like: u.1 <= u.2, u.2 < u.3, u.3 = u.4
# Universe variable names can be like u.1, u.42, Top.37, Set, Prop, etc.
_CONSTRAINT_RE = re.compile(
    r"^\s*(\S+)\s+(<=|<|=)\s+(\S+)\s*$"
)

# Comment pattern
_COMMENT_RE = re.compile(r"^\s*\(\*.*\*\)\s*$")

# Type annotation pattern for print_definition source
_TYPE_ANNOT_RE = re.compile(r"Type@\{([^}]+)\}")

# Polymorphic instantiation pattern: @name@{levels}
_INSTANTIATION_RE = re.compile(r"@?(\w+)@\{([^}]+)\}")


_RELATION_MAP = {
    "<=": "le",
    "<": "lt",
    "=": "eq",
}


def _make_variable(name: str) -> UniverseExpression:
    """Create a UniverseExpression of kind 'variable'."""
    return UniverseExpression(
        kind="variable",
        name=name,
        base=None,
        offset=None,
        operands=None,
    )


def parse_constraints(
    raw_text: str,
    source_command: str,
) -> List[UniverseConstraint]:
    """Parse raw Coq output into a list of UniverseConstraint records.

    Args:
        raw_text: The string output from a Coq vernacular command.
        source_command: Either "print_universes" or "print_definition".

    Returns:
        A list of UniverseConstraint records. Blank lines, comments, and
        Coq informational messages are skipped. Lines matching no known
        format are recorded in a diagnostic field (as the source attribute).
    """
    if not raw_text.strip():
        return []

    constraints: List[UniverseConstraint] = []
    diagnostics: List[str] = []

    if source_command == "print_definition":
        return _parse_definition_output(raw_text)

    for line in raw_text.split("\n"):
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            continue

        # Skip comment lines
        if _COMMENT_RE.match(stripped):
            continue

        # Try to parse as a constraint
        m = _CONSTRAINT_RE.match(stripped)
        if m:
            left_name, op, right_name = m.group(1), m.group(2), m.group(3)
            constraints.append(
                UniverseConstraint(
                    left=_make_variable(left_name),
                    relation=_RELATION_MAP[op],
                    right=_make_variable(right_name),
                    source=None,
                )
            )
        else:
            # Record unparseable line in diagnostics
            diagnostics.append(stripped)

    return constraints


def _parse_definition_output(raw_text: str) -> List[UniverseConstraint]:
    """Parse annotated definition output to extract universe constraints.

    Extracts constraints from comment-style annotations like (* u.5 <= u.6 *)
    and Type@{u.N} annotations.
    """
    constraints: List[UniverseConstraint] = []

    # Look for constraint annotations in comments
    constraint_comment_re = re.compile(
        r"\(\*\s*(\S+)\s+(<=|<|=)\s+(\S+)\s*\*\)"
    )

    for line in raw_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        for m in constraint_comment_re.finditer(stripped):
            left_name, op, right_name = m.group(1), m.group(2), m.group(3)
            constraints.append(
                UniverseConstraint(
                    left=_make_variable(left_name),
                    relation=_RELATION_MAP[op],
                    right=_make_variable(right_name),
                    source=None,
                )
            )

    return constraints


def parse_instantiations(raw_text: str) -> list:
    """Parse annotated definition output to extract polymorphic instantiations.

    Returns a list of (definition_name, {param: level}) tuples.
    """
    results = []
    for m in _INSTANTIATION_RE.finditer(raw_text):
        def_name = m.group(1)
        levels_str = m.group(2)
        # For simplicity, map a single universe parameter "u" to the level
        levels = levels_str.strip().split()
        if len(levels) == 1:
            mapping = {"u": levels[0]}
        else:
            mapping = {f"u{i}": lv for i, lv in enumerate(levels)}
        results.append((def_name, mapping))
    return results
