"""Assumption auditing engine: audit, batch audit, and compare."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from Poule.auditing.classifier import classify_axiom
from Poule.auditing.errors import AuditError
from Poule.auditing.parser import parse_print_assumptions
from Poule.auditing.types import (
    AssumptionResult,
    AxiomCategory,
    AxiomUsageSummary,
    ClassifiedAxiom,
    ComparisonResult,
    FlaggedTheorem,
    MatrixRow,
    ModuleAuditResult,
    OpaqueDependency,
)

# Valid AxiomCategory values for validation.
_VALID_CATEGORIES = {cat.value for cat in AxiomCategory}

# Default flag categories per spec section 4.6.
_DEFAULT_FLAG_CATEGORIES = ["classical", "choice", "proof_irrelevance", "custom"]

# Detect Coq error output in coqtop responses (spec §7.3).
_COQ_ERROR_RE = re.compile(r"^Error:", re.MULTILINE)
_NOT_FOUND_RE = re.compile(r"not found in the current environment", re.IGNORECASE)


async def audit_assumptions(
    session_manager: Any,
    name: str,
    session_id: str = "default",
) -> AssumptionResult:
    """Audit axiom dependencies for a single theorem.

    Sends Print Assumptions to the Coq backend, parses output,
    separates axioms from opaque dependencies, classifies each axiom.
    """
    if not name or not name.strip():
        raise AuditError("INVALID_INPUT", "Theorem name must be non-empty.")

    try:
        output = await session_manager.send_command(
            session_id, f"Print Assumptions {name}.", prefer_coqtop=True,
        )
    except AuditError:
        raise
    except Exception as exc:
        # Propagate session errors as AuditError
        code = getattr(exc, "code", "UNKNOWN")
        message = getattr(exc, "message", str(exc))
        raise AuditError(code, message) from exc

    # Detect Coq error output before parsing (spec §7.3).
    if _COQ_ERROR_RE.search(output):
        if _NOT_FOUND_RE.search(output):
            raise AuditError(
                "NOT_FOUND",
                f"Declaration `{name}` not found in the current Coq environment.",
            )
        raise AuditError(
            "PARSE_ERROR",
            f"Coq error in `Print Assumptions` output for `{name}`: {output.strip()}",
        )

    # Parse the output
    try:
        parsed = parse_print_assumptions(output)
    except AuditError as exc:
        # Wrap parse errors with theorem name context
        raise AuditError(
            "PARSE_ERROR",
            f"Failed to parse `Print Assumptions` output for `{name}`: {exc.message}",
        ) from exc

    if parsed.is_closed:
        return AssumptionResult(
            name=name,
            is_closed=True,
            axioms=[],
            opaque_dependencies=[],
            error=None,
        )

    # Separate axioms from opaque dependencies
    axioms: list[ClassifiedAxiom] = []
    opaque_deps: list[OpaqueDependency] = []

    for dep in parsed.dependencies:
        # Query declaration kind
        kind = await session_manager.query_declaration_kind(session_id, dep.name)

        if kind == "Opaque":
            opaque_deps.append(OpaqueDependency(name=dep.name, type=dep.type))
        else:
            # Axiom, Parameter, or unknown (None) -> treat as axiom
            category, explanation = classify_axiom(dep.name, dep.type)
            axioms.append(
                ClassifiedAxiom(
                    name=dep.name,
                    type=dep.type,
                    category=category,
                    explanation=explanation,
                )
            )

    return AssumptionResult(
        name=name,
        is_closed=False,
        axioms=axioms,
        opaque_dependencies=opaque_deps,
        error=None,
    )


def _parse_module_theorems(module: str, output: str) -> list[str]:
    """Extract declaration names from Print Module output.

    Coq's ``Print Module`` nests sub-modules as ``Module <Name> ... End``
    blocks. Declarations inside a sub-module must be qualified with the
    sub-module path, so we walk the output line-by-line with a stack of
    active sub-module names. The outer module header is printed as
    ``Module\\n<Name>\\n:= Struct`` across three lines, so matching
    ``Module <Name>`` on a single line only fires for inner sub-modules.
    """
    decl_re = re.compile(
        r"^\s*(?:Definition|Parameter|Inductive|Record|Fixpoint|CoFixpoint"
        r"|Theorem|Lemma)\s+(\w+)\s*:"
    )
    module_re = re.compile(r"^\s*Module\s+(?:Type\s+)?(\w+)\b")
    end_re = re.compile(r"^\s*End(?:\s+\w+)?\s*\.?\s*$")

    declarations: list[str] = []
    submodule_stack: list[str] = []

    for line in output.splitlines():
        if end_re.match(line):
            if submodule_stack:
                submodule_stack.pop()
            continue

        m = module_re.match(line)
        if m:
            # Functor application `Module M := F(X).` opens no body.
            if ":=" in line:
                continue
            submodule_stack.append(m.group(1))
            continue

        d = decl_re.match(line)
        if d:
            parts = [module, *submodule_stack, d.group(1)]
            declarations.append(".".join(parts))

    return declarations


def _parse_search_results(output: str) -> list[str]:
    """Extract declaration names from ``Search _ inside`` output.

    Each result line has the form ``name: type``.  Continuation lines
    (indented) are skipped.  A leading ``Rocq < `` prompt prefix is
    stripped if present.  Coq error lines (starting with ``Error:``)
    are skipped.
    """
    declarations: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip indented continuation lines (multi-line types)
        if line and line[0] in (" ", "\t"):
            continue
        # Strip Rocq prompt prefix
        if stripped.startswith("Rocq < "):
            stripped = stripped[len("Rocq < "):]
        # Skip Coq error/warning lines
        if stripped.startswith("Error:") or stripped.startswith("Warning:"):
            continue
        # Match name: type
        colon_idx = stripped.find(":")
        if colon_idx > 0:
            name = stripped[:colon_idx].strip()
            if name and name.isidentifier():
                declarations.append(name)
    return declarations


async def _enumerate_declarations(
    session_manager: Any,
    module: str,
    session_id: str,
) -> list[str]:
    """Enumerate declarations using a three-strategy cascade.

    1. ``Print Module <module>.`` — for compiled modules
    2. ``Search _ inside <module>.`` — for named modules/sections in scope
    3. ``Search _ inside Top.`` — for local .v files without a logical path
    """
    # Strategy 1: Print Module
    try:
        module_output = await session_manager.send_command(
            session_id, f"Print Module {module}.", prefer_coqtop=True,
        )
        names = _parse_module_theorems(module, module_output)
        if names:
            return names
    except Exception:
        pass  # Fall through to strategy 2

    # Strategy 2: Search _ inside <module>
    try:
        search_output = await session_manager.send_command(
            session_id, f"Search _ inside {module}.", prefer_coqtop=True,
        )
        names = _parse_search_results(search_output)
        if names:
            return names
    except Exception:
        pass  # Fall through to strategy 3

    # Strategy 3: Search _ inside Top (for local .v files)
    try:
        top_output = await session_manager.send_command(
            session_id, "Search _ inside Top.", prefer_coqtop=True,
        )
        names = _parse_search_results(top_output)
        if names:
            return names
    except Exception:
        pass

    return []


async def audit_module(
    session_manager: Any,
    module: str,
    flag_categories: Optional[List[str]] = None,
    session_id: str = "default",
) -> ModuleAuditResult:
    """Audit all theorems in a module.

    Enumerates declarations using a three-strategy cascade, calls
    audit_assumptions for each, aggregates results.
    """
    if not module or not module.strip():
        raise AuditError("INVALID_INPUT", "Module name must be non-empty.")

    # Validate flag_categories
    if flag_categories is None:
        flag_categories = list(_DEFAULT_FLAG_CATEGORIES)

    for cat in flag_categories:
        if cat not in _VALID_CATEGORIES:
            raise AuditError(
                "INVALID_INPUT",
                f"Unknown axiom category: `{cat}`. Valid categories: "
                "classical, extensionality, choice, proof_irrelevance, custom.",
            )

    # Enumerate module declarations via three-strategy cascade
    theorem_names = await _enumerate_declarations(
        session_manager, module, session_id,
    )

    if not theorem_names:
        raise AuditError(
            "NOT_FOUND",
            f"Module `{module}` not found in the current Coq environment.",
        )

    # Audit each theorem with error isolation
    per_theorem: list[AssumptionResult] = []
    axiom_free_count = 0
    # Track axiom usage: axiom_name -> (category, set of theorem names)
    axiom_usage: Dict[str, tuple[AxiomCategory, set[str]]] = {}
    flagged_theorems: list[FlaggedTheorem] = []

    for thm_name in theorem_names:
        try:
            try:
                result = await audit_assumptions(session_manager, thm_name, session_id)
            except Exception:
                # FQN may use a deprecated path — retry with short name
                short_name = thm_name.rsplit(".", 1)[-1] if "." in thm_name else thm_name
                if short_name != thm_name:
                    result = await audit_assumptions(
                        session_manager, short_name, session_id,
                    )
                else:
                    raise
            per_theorem.append(result)

            if result.is_closed:
                axiom_free_count += 1
            else:
                # Track axiom usage
                for axiom in result.axioms:
                    if axiom.name not in axiom_usage:
                        axiom_usage[axiom.name] = (axiom.category, set())
                    axiom_usage[axiom.name][1].add(thm_name)

                # Check for flagged axioms
                flagged_axioms = [
                    a for a in result.axioms if a.category.value in flag_categories
                ]
                if flagged_axioms:
                    flagged_theorems.append(
                        FlaggedTheorem(name=thm_name, flagged_axioms=flagged_axioms)
                    )
        except (AuditError, Exception) as exc:
            # Record error and continue
            error_code = getattr(exc, "code", "UNKNOWN")
            error_message = getattr(exc, "message", str(exc))
            error_str = f"{error_code}: {error_message}"
            per_theorem.append(
                AssumptionResult(
                    name=thm_name,
                    is_closed=False,
                    axioms=[],
                    opaque_dependencies=[],
                    error=error_str,
                )
            )

    # Build axiom summary sorted by dependent_count descending
    axiom_summary = sorted(
        [
            AxiomUsageSummary(
                axiom_name=ax_name,
                category=cat,
                dependent_count=len(thm_set),
            )
            for ax_name, (cat, thm_set) in axiom_usage.items()
        ],
        key=lambda s: s.dependent_count,
        reverse=True,
    )

    return ModuleAuditResult(
        module=module,
        theorem_count=len(theorem_names),
        axiom_free_count=axiom_free_count,
        axiom_summary=axiom_summary,
        flagged_theorems=flagged_theorems,
        per_theorem=per_theorem,
    )


async def compare_assumptions(
    session_manager: Any,
    names: List[str],
    session_id: str = "default",
) -> ComparisonResult:
    """Compare assumption profiles of two or more theorems."""
    if len(names) < 2:
        raise AuditError(
            "INVALID_INPUT",
            "Comparison requires at least 2 theorem names.",
        )

    # Audit each theorem
    results: Dict[str, AssumptionResult] = {}
    for name in names:
        results[name] = await audit_assumptions(session_manager, name, session_id)

    # Build axiom sets per theorem (name -> set of axiom names)
    axiom_sets: Dict[str, Set[str]] = {}
    # Also keep the ClassifiedAxiom objects indexed by name
    axiom_objects: Dict[str, ClassifiedAxiom] = {}

    for name in names:
        result = results[name]
        axiom_names: Set[str] = set()
        for axiom in result.axioms:
            axiom_names.add(axiom.name)
            axiom_objects[axiom.name] = axiom
        axiom_sets[name] = axiom_names

    # All axiom names across all theorems
    all_axiom_names: Set[str] = set()
    for s in axiom_sets.values():
        all_axiom_names |= s

    # Shared axioms: present in every theorem
    if names:
        shared_set = axiom_sets[names[0]].copy()
        for name in names[1:]:
            shared_set &= axiom_sets[name]
    else:
        shared_set = set()

    shared_axioms = [axiom_objects[n] for n in sorted(shared_set) if n in axiom_objects]

    # Unique axioms per theorem: in this theorem but not in all others
    unique_axioms: Dict[str, list[ClassifiedAxiom]] = {}
    for name in names:
        unique_set = axiom_sets[name] - shared_set
        # For 2-theorem case: unique means in this one but not the other
        if len(names) == 2:
            other = [n for n in names if n != name][0]
            unique_set = axiom_sets[name] - axiom_sets[other]
        else:
            # For N-theorem: unique means only in this theorem
            other_union: Set[str] = set()
            for other_name in names:
                if other_name != name:
                    other_union |= axiom_sets[other_name]
            unique_set = axiom_sets[name] - other_union
        unique_axioms[name] = [
            axiom_objects[n] for n in sorted(unique_set) if n in axiom_objects
        ]

    # Matrix (only for 3+ theorems)
    matrix: Optional[list[MatrixRow]] = None
    if len(names) >= 3:
        matrix = []
        for axiom_name in sorted(all_axiom_names):
            present_in = [
                thm_name for thm_name in names if axiom_name in axiom_sets[thm_name]
            ]
            matrix.append(
                MatrixRow(axiom=axiom_objects[axiom_name], present_in=present_in)
            )

    # Determine weakest
    weakest = _determine_weakest(names, axiom_sets)

    return ComparisonResult(
        theorems=list(names),
        shared_axioms=shared_axioms,
        unique_axioms=unique_axioms,
        matrix=matrix,
        weakest=weakest,
    )


def _determine_weakest(
    names: List[str], axiom_sets: Dict[str, Set[str]]
) -> List[str]:
    """Determine which theorems are weakest.

    Strict subset inclusion is the primary criterion.
    Cardinality is the tiebreaker.
    """
    # Check for strict subset relationships.
    # A theorem is "dominated" if its axiom set is a strict superset of another's.
    dominated: Set[str] = set()
    for i, name_i in enumerate(names):
        for j, name_j in enumerate(names):
            if i == j:
                continue
            # If name_j's axioms are a strict subset of name_i's axioms,
            # then name_i is dominated.
            if axiom_sets[name_j] < axiom_sets[name_i]:
                dominated.add(name_i)
                break

    # Non-dominated theorems
    candidates = [n for n in names if n not in dominated]

    if not candidates:
        # All are dominated by each other (shouldn't happen with strict subset),
        # fall back to cardinality
        candidates = list(names)

    # Among non-dominated, pick those with minimum cardinality
    min_count = min(len(axiom_sets[n]) for n in candidates)
    weakest = [n for n in candidates if len(axiom_sets[n]) == min_count]

    return weakest
