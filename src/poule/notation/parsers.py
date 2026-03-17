"""Output parsers for Coq notation commands (specification §10)."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from poule.notation.types import (
    NotationInfo,
    NotationInterpretation,
    ScopeInfo,
)


class ParseError(Exception):
    """Raised when Coq output cannot be parsed (§7.3)."""

    def __init__(self, message: str, code: str = "PARSE_ERROR") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def parse_print_notation(raw: str) -> NotationInfo:
    """Parse raw output from ``Print Notation`` into a NotationInfo.

    Expected format (Coq 8.19+)::

        "<notation_string>" := <expansion>
          (at level <N>, <arg1> at level <M>, ..., <assoc> associativity)
          : <scope>

    Raises ParseError if the format is not recognized (§7.3).
    """
    if not raw or not raw.strip():
        raise ParseError(
            f"Failed to parse Coq output for print_notation: empty output"
        )

    # Extract notation_string: text between first pair of double quotes on line 1
    first_line_match = re.match(r'^"([^"]*)"', raw)
    if not first_line_match:
        raise ParseError(
            f"Failed to parse Coq output for print_notation: "
            f"cannot extract notation string. Raw output: {raw}"
        )
    notation_string = first_line_match.group(1)

    # Extract expansion: text after := on the first line, trimmed
    expansion_match = re.search(r':=\s*(.+)', raw.split('\n')[0])
    if not expansion_match:
        raise ParseError(
            f"Failed to parse Coq output for print_notation: "
            f"cannot extract expansion. Raw output: {raw}"
        )
    expansion = expansion_match.group(1).strip()

    # Extract level
    level_match = re.search(r'at level\s+(\d+)', raw)
    if not level_match:
        raise ParseError(
            f"Failed to parse Coq output for print_notation: "
            f"cannot extract level. Raw output: {raw}"
        )
    level = int(level_match.group(1))

    # Extract associativity
    assoc_match = re.search(r'(left|right|no)\s+associativity', raw)
    if not assoc_match:
        raise ParseError(
            f"Failed to parse Coq output for print_notation: "
            f"cannot extract associativity. Raw output: {raw}"
        )
    assoc_raw = assoc_match.group(1)
    associativity = "none" if assoc_raw == "no" else assoc_raw

    # Extract arg_levels: "<name> at level <N>" pairs from the metadata section
    # The metadata section is the parenthesized block starting with "at level"
    arg_levels: List[Tuple[str, int]] = []
    meta_match = re.search(r'\(\s*at\s+level\s+\d+([^)]*)\)', raw, re.DOTALL)
    if meta_match:
        meta_content = meta_match.group(1)  # content after "at level N"
        # Find "<name> at level <N>" patterns
        arg_matches = re.findall(r',\s*(\w+)\s+at\s+level\s+(\d+)', meta_content)
        for name, lvl in arg_matches:
            arg_levels.append((name, int(lvl)))

    # Extract scope: text after the last ":"
    scope_match = re.search(r':\s*(\S+)\s*$', raw.strip())
    if not scope_match:
        raise ParseError(
            f"Failed to parse Coq output for print_notation: "
            f"cannot extract scope. Raw output: {raw}"
        )
    scope = scope_match.group(1)

    # Extract flags
    only_parsing = "only parsing" in raw
    only_printing = "only printing" in raw

    # Extract format (null when absent)
    format_match = re.search(r'format\s+"([^"]*)"', raw)
    fmt = format_match.group(1) if format_match else None

    return NotationInfo(
        notation_string=notation_string,
        expansion=expansion,
        level=level,
        associativity=associativity,
        arg_levels=arg_levels,
        format=fmt,
        scope=scope,
        defining_module=None,
        only_parsing=only_parsing,
        only_printing=only_printing,
    )


def parse_locate_notation(raw: str) -> List[NotationInterpretation]:
    """Parse raw output from ``Locate`` into a list of NotationInterpretation.

    Expected format::

        Notation "<notation_string>" := <expansion> : <scope>
          (default interpretation)

    Multiple blocks may appear. The block marked ``(default interpretation)``
    is the currently active one.

    Raises ParseError if the format is not recognized (§7.3).
    """
    if not raw or not raw.strip():
        raise ParseError(
            f"Failed to parse Coq output for locate_notation: empty output"
        )

    # Split into blocks: each starts with "Notation"
    entries: List[NotationInterpretation] = []
    # Find all Notation lines
    notation_pattern = re.compile(
        r'Notation\s+"([^"]+)"\s*:=\s*(.+?)\s*:\s*(\S+)'
    )

    lines = raw.split('\n')
    i = 0
    rank = 0
    while i < len(lines):
        line = lines[i].strip()
        match = notation_pattern.match(line)
        if match:
            expansion = match.group(2).strip()
            scope = match.group(3).strip()
            # Check if next line is "(default interpretation)"
            is_default = False
            if i + 1 < len(lines) and "default interpretation" in lines[i + 1]:
                is_default = True
            entries.append(NotationInterpretation(
                expansion=expansion,
                scope=scope,
                defining_module=None,
                priority_rank=rank,
                is_default=is_default,
            ))
            rank += 1
        i += 1

    if not entries:
        raise ParseError(
            f"Failed to parse Coq output for locate_notation: "
            f"no notation entries found. Raw output: {raw}"
        )

    return entries


def parse_print_scope(raw: str) -> ScopeInfo:
    """Parse raw output from ``Print Scope`` into a ScopeInfo.

    Expected format::

        <scope_name>
        "<notation1>" := <expansion1>
        "<notation2>" := <expansion2>
        ...

    Raises ParseError if the format is not recognized (§7.3).
    """
    if not raw or not raw.strip():
        raise ParseError(
            f"Failed to parse Coq output for print_scope: empty output"
        )

    lines = [l for l in raw.strip().split('\n') if l.strip()]
    if not lines:
        raise ParseError(
            f"Failed to parse Coq output for print_scope: no lines found. Raw output: {raw}"
        )

    scope_name = lines[0].strip()

    notations: List[NotationInfo] = []
    for line in lines[1:]:
        line = line.strip()
        # Match "<notation>" := <expansion>
        match = re.match(r'"([^"]+)"\s*:=\s*(.+)', line)
        if match:
            notation_string = match.group(1)
            expansion = match.group(2).strip()
            notations.append(NotationInfo(
                notation_string=notation_string,
                expansion=expansion,
                level=0,
                associativity="none",
                arg_levels=[],
                format=None,
                scope=scope_name,
                defining_module=None,
                only_parsing=False,
                only_printing=False,
            ))

    return ScopeInfo(
        scope_name=scope_name,
        bound_type=None,
        notations=notations,
    )


def parse_print_visibility(raw: str) -> List[Tuple[str, Optional[str]]]:
    """Parse raw output from ``Print Visibility`` into an ordered scope list.

    Expected format::

        <scope1> (bound to <type1>)
        <scope2>
        <scope3> (bound to <type3>)

    Returns an ordered list of ``(scope_name, bound_type_or_null)`` pairs,
    with index 0 = highest priority.

    Raises ParseError if the format is not recognized (§7.3).
    """
    if not raw or not raw.strip():
        raise ParseError(
            f"Failed to parse Coq output for print_visibility: empty output"
        )

    result: List[Tuple[str, Optional[str]]] = []
    bound_pattern = re.compile(r'^(\S+)\s+\(bound to\s+(\S+)\)\s*$')

    for line in raw.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        bound_match = bound_pattern.match(line)
        if bound_match:
            result.append((bound_match.group(1), bound_match.group(2)))
        else:
            result.append((line, None))

    if not result:
        raise ParseError(
            f"Failed to parse Coq output for print_visibility: "
            f"no scope entries found. Raw output: {raw}"
        )

    return result
