"""Tactic lookup and strategy inspection.

Spec: specification/tactic-documentation.md sections 4.1, 4.2.
"""

from __future__ import annotations

import re
from typing import Optional

from Poule.tactics.types import StrategyEntry, TacticInfo


# Known tactic names for reference extraction.
_KNOWN_TACTICS = {
    "auto", "eauto", "intuition", "tauto", "firstorder",
    "reflexivity", "symmetry", "transitivity", "congruence",
    "rewrite", "apply", "exact", "assumption",
    "intros", "intro", "destruct", "induction", "inversion",
    "split", "left", "right", "constructor", "exists", "eexists",
    "unfold", "simpl", "cbn", "cbv", "compute", "hnf", "red",
    "lia", "omega", "ring", "field",
    "try", "repeat", "progress", "fail", "idtac",
    "assert", "pose", "set", "remember", "clear",
    "trivial", "discriminate", "injection", "f_equal",
    "elim", "case", "generalize", "specialize",
}

# Tactic category mapping for known primitives.
_PRIMITIVE_CATEGORIES = {
    # automation
    "auto": "automation",
    "eauto": "automation",
    "trivial": "automation",
    "intuition": "automation",
    "tauto": "automation",
    "firstorder": "automation",
    # rewriting
    "reflexivity": "rewriting",
    "symmetry": "rewriting",
    "transitivity": "rewriting",
    "congruence": "rewriting",
    "rewrite": "rewriting",
    "apply": "rewriting",
    "eapply": "rewriting",
    "exact": "rewriting",
    "eexact": "rewriting",
    "assumption": "rewriting",
    "unfold": "rewriting",
    "simpl": "rewriting",
    "cbn": "rewriting",
    "cbv": "rewriting",
    "compute": "rewriting",
    "hnf": "rewriting",
    "red": "rewriting",
    "setoid_rewrite": "rewriting",
    # introduction
    "intro": "introduction",
    "intros": "introduction",
    # case analysis
    "destruct": "case_analysis",
    "induction": "case_analysis",
    "inversion": "case_analysis",
    "case": "case_analysis",
    "elim": "case_analysis",
    "split": "case_analysis",
    "left": "case_analysis",
    "right": "case_analysis",
    "constructor": "case_analysis",
    "exists": "case_analysis",
    "eexists": "case_analysis",
    # arithmetic
    "lia": "arithmetic",
    "omega": "arithmetic",
    "ring": "arithmetic",
    "field": "arithmetic",
    # equality
    "discriminate": "equality",
    "injection": "equality",
    "f_equal": "equality",
    # context management
    "assert": "context_management",
    "pose": "context_management",
    "set": "context_management",
    "remember": "context_management",
    "clear": "context_management",
    "generalize": "context_management",
    "specialize": "context_management",
    # control flow
    "try": "control",
    "repeat": "control",
    "progress": "control",
    "fail": "control",
    "idtac": "control",
}

# Patterns in QueryError messages that indicate a primitive tactic.
_PRIMITIVE_ERROR_PATTERNS = (
    "not an ltac definition",
    "not a user defined tactic",
)


class TacticDocError(Exception):
    """Error raised by tactic documentation operations."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


def _parse_ltac_output(name: str, output: str) -> TacticInfo:
    """Parse the output of Print Ltac into a TacticInfo."""
    # Check for "not found" errors
    if re.search(r"Error:.*not found", output, re.IGNORECASE):
        raise TacticDocError(
            "NOT_FOUND",
            f'Tactic "{name}" not found in the current environment.',
        )

    # Check for "not an Ltac definition" => primitive or ltac2
    if re.search(r"not an Ltac definition", output, re.IGNORECASE):
        category = _PRIMITIVE_CATEGORIES.get(name)
        return TacticInfo(
            name=name,
            qualified_name=None,
            kind="primitive",
            category=category,
            body=None,
            is_recursive=False,
            referenced_tactics=[],
            referenced_constants=[],
            strategy_entries=[],
        )

    # Parse Ltac definition: "Ltac <qualified_name> := <body>"
    m = re.match(r"Ltac\s+([\w.]+)\s*:=\s*(.*)", output, re.DOTALL)
    if m:
        qualified_name = m.group(1)
        body = m.group(2).strip()

        # Extract the base name for recursion check
        base_name = name
        # Check recursion: does the body reference the tactic's own name?
        is_recursive = bool(re.search(r'\b' + re.escape(base_name) + r'\b', body))

        # Extract referenced tactics
        referenced_tactics = _extract_referenced_tactics(body, base_name)

        # Extract referenced constants (arguments to unfold, rewrite, apply)
        referenced_constants = _extract_referenced_constants(body)

        # Determine category from body content
        category = _categorize_ltac_body(body)

        return TacticInfo(
            name=name,
            qualified_name=qualified_name,
            kind="ltac",
            category=category,
            body=body,
            is_recursive=is_recursive,
            referenced_tactics=referenced_tactics,
            referenced_constants=referenced_constants,
            strategy_entries=[],
        )

    # Fallback: if output doesn't match known patterns, treat as primitive
    category = _PRIMITIVE_CATEGORIES.get(name)
    return TacticInfo(
        name=name,
        qualified_name=None,
        kind="primitive",
        category=category,
        body=None,
        is_recursive=False,
        referenced_tactics=[],
        referenced_constants=[],
        strategy_entries=[],
    )


def _extract_referenced_tactics(body: str, own_name: str) -> list[str]:
    """Extract tactic names referenced in the body."""
    # Find all word-like identifiers in the body
    identifiers = re.findall(r'\b([a-zA-Z_]\w*)\b', body)
    found = []
    seen = set()
    for ident in identifiers:
        if ident in _KNOWN_TACTICS and ident != own_name and ident not in seen:
            seen.add(ident)
            found.append(ident)
    return found


def _extract_referenced_constants(body: str) -> list[str]:
    """Extract non-tactic identifiers used as arguments to unfold, rewrite, apply, etc."""
    constants = []
    seen = set()
    # Match arguments to unfold, rewrite, apply, exact
    for pattern in [
        r'\bunfold\s+([\w.]+)',
        r'\brewrite\s+([\w.]+)',
        r'\bapply\s+([\w.]+)',
        r'\bexact\s+([\w.]+)',
    ]:
        for m in re.finditer(pattern, body):
            const = m.group(1)
            if const not in _KNOWN_TACTICS and const not in seen:
                seen.add(const)
                constants.append(const)
    return constants


def _categorize_ltac_body(body: str) -> Optional[str]:
    """Determine the category of an Ltac tactic from its body."""
    body_lower = body.lower()
    if any(t in body_lower for t in ["auto", "eauto", "trivial", "intuition", "tauto"]):
        return "automation"
    if any(t in body_lower for t in ["rewrite", "reflexivity", "congruence", "symmetry"]):
        return "rewriting"
    if any(t in body_lower for t in ["destruct", "induction", "inversion", "case"]):
        return "case_analysis"
    if any(t in body_lower for t in ["intro", "intros"]):
        return "introduction"
    if any(t in body_lower for t in ["lia", "omega", "ring", "field"]):
        return "arithmetic"
    return None


def _parse_strategy_output(constant_name: str, output: str) -> list[StrategyEntry]:
    """Parse the output of Print Strategy into StrategyEntry records."""
    if re.search(r"Error:.*not found", output, re.IGNORECASE):
        raise TacticDocError(
            "NOT_FOUND",
            f'Constant "{constant_name}" not found in the current environment.',
        )

    entries = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Match "constant_name : level"
        m = re.match(r'([\w.]+)\s*:\s*(\S+)', line)
        if m:
            const = m.group(1)
            level_str = m.group(2)
            if level_str == "transparent":
                level = "transparent"
            elif level_str == "opaque":
                level = "opaque"
            else:
                try:
                    level = int(level_str)
                except ValueError:
                    level = level_str
            entries.append(StrategyEntry(constant=const, level=level))

    if not entries:
        raise TacticDocError(
            "NOT_FOUND",
            f'Constant "{constant_name}" not found in the current environment.',
        )

    return entries


def _is_primitive_error(message: str) -> bool:
    """Check if a QueryError message indicates a primitive (non-Ltac) tactic."""
    msg_lower = message.lower()
    return any(pat in msg_lower for pat in _PRIMITIVE_ERROR_PATTERNS)


def _make_primitive_info(name: str) -> TacticInfo:
    """Build a TacticInfo for a primitive tactic."""
    return TacticInfo(
        name=name,
        qualified_name=None,
        kind="primitive",
        category=_PRIMITIVE_CATEGORIES.get(name),
        body=None,
        is_recursive=False,
        referenced_tactics=[],
        referenced_constants=[],
        strategy_entries=[],
    )


async def tactic_lookup(
    name: str,
    session_id: Optional[str] = None,
    coq_query=None,
) -> TacticInfo:
    """Look up a tactic by name and return structured TacticInfo.

    Spec: section 4.1.
    """
    if not name:
        raise TacticDocError("INVALID_ARGUMENT", "Tactic name must not be empty.")

    if re.search(r"\s", name):
        raise TacticDocError(
            "INVALID_ARGUMENT",
            f'Tactic name must be a single identifier (no whitespace). Got: "{name}".',
        )

    if coq_query is None:
        from Poule.query.handler import coq_query as _coq_query
        from Poule.query.process_pool import ProcessPool

        _pool = ProcessPool()

        async def coq_query(command, argument, session_id=None):
            return await _coq_query(
                command, argument, session_id=session_id, process_pool=_pool,
            )

    try:
        result = await coq_query("Print", f"Ltac {name}", session_id=session_id)
    except Exception as exc:
        # Intercept QueryError for primitive tactics: coq_query raises when
        # Coq output contains "Error:", but for primitives the error message
        # is "not an Ltac definition" or "not a user defined tactic".
        if hasattr(exc, "code") and hasattr(exc, "message"):
            if _is_primitive_error(exc.message):
                return _make_primitive_info(name)
        raise

    return _parse_ltac_output(name, result.output)


async def strategy_inspect(
    constant_name: str,
    session_id: Optional[str] = None,
    coq_query=None,
) -> list[StrategyEntry]:
    """Inspect the unfolding strategy for a constant.

    Spec: section 4.2.
    """
    if not constant_name:
        raise TacticDocError("INVALID_ARGUMENT", "Constant name must not be empty.")

    if coq_query is None:
        from Poule.query.handler import coq_query as _coq_query
        from Poule.query.process_pool import ProcessPool

        _pool = ProcessPool()

        async def coq_query(command, argument, session_id=None):
            return await _coq_query(
                command, argument, session_id=session_id, process_pool=_pool,
            )

    result = await coq_query("Print", f"Strategy {constant_name}", session_id=session_id)
    return _parse_strategy_output(constant_name, result.output)
