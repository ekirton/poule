"""Dependency scanner for convoy pattern assistant."""

from __future__ import annotations

import re
from graphlib import TopologicalSorter
from typing import Any

from .errors import ConvoyError
from .types import DependencyReport, DependentHypothesis, IndexInfo


class DependencyScanner:
    """Scans proof state for index dependencies."""

    async def scan(
        self,
        session_id: str,
        target: str,
        session_manager: Any,
        proof_state: dict[str, Any],
    ) -> DependencyReport:
        """Build a DependencyReport for the given target."""
        # 1. Get target type
        target_type = await session_manager.execute_vernacular(
            session_id, f"Check {target}"
        )
        if not target_type or not target_type.strip():
            raise ConvoyError("TARGET_NOT_FOUND", f"Term `{target}` not found in the current proof state.")

        # 2. Parse inductive type from target type
        inductive_name = self._extract_inductive_name(target_type.strip())
        if not inductive_name:
            raise ConvoyError(
                "NOT_INDEXED",
                f"`{target}` has type `{target_type.strip()}`, which is not an indexed inductive type. "
                "Standard `destruct` should work.",
            )

        # 3. Get inductive definition
        print_output = await session_manager.execute_vernacular(
            session_id, f"Print {inductive_name}"
        )
        if not print_output or "Inductive" not in print_output:
            raise ConvoyError(
                "PARSE_ERROR",
                f"Could not parse the definition of `{inductive_name}`. Raw output: {print_output}",
            )

        # 4. Distinguish parameters from indices
        parameters, index_names, index_types = self._parse_inductive_def(
            inductive_name, print_output
        )

        if not index_names:
            raise ConvoyError(
                "NOT_INDEXED",
                f"`{target}` has type `{target_type.strip()}`, which is not an indexed inductive type. "
                "Standard `destruct` should work.",
            )

        # 5. Extract concrete index values from target_type
        concrete_indices = self._extract_concrete_indices(
            target_type.strip(), inductive_name, len(parameters), len(index_names)
        )

        # 6. Detect decidable equality for each index type
        indices: list[IndexInfo] = []
        for i, itype in enumerate(index_types):
            eqdec_output = await session_manager.execute_vernacular(
                session_id, f"Search EqDec {itype}"
            )
            has_dec_eq = bool(eqdec_output and eqdec_output.strip())
            # Use concrete value as name when available
            iname = concrete_indices[i] if i < len(concrete_indices) else f"_idx_{i}"
            indices.append(IndexInfo(name=iname, type=itype, has_decidable_eq=has_dec_eq))

        # 7. Scan hypotheses
        hypotheses = proof_state.get("hypotheses", [])
        dependent_hyps: list[DependentHypothesis] = []
        for hyp in hypotheses:
            hname = hyp.get("name", "")
            htype = hyp.get("type", "")
            if hname == target:
                continue
            mentioned = []
            for ci in concrete_indices:
                if ci in htype:
                    mentioned.append(ci)
            if mentioned:
                dependent_hyps.append(
                    DependentHypothesis(
                        name=hname,
                        type=htype,
                        indices_mentioned=mentioned,
                        depends_on=[],
                    )
                )

        # 8. Build inter-hypothesis dependencies and order
        dep_names = {h.name for h in dependent_hyps}
        ordered_hyps: list[DependentHypothesis] = []
        for hyp in dependent_hyps:
            deps = []
            for other in dep_names:
                if other != hyp.name and re.search(r'\b' + re.escape(other) + r'\b', hyp.type):
                    deps.append(other)
            ordered_hyps.append(
                DependentHypothesis(
                    name=hyp.name,
                    type=hyp.type,
                    indices_mentioned=hyp.indices_mentioned,
                    depends_on=deps,
                )
            )

        # Topological sort for revert order
        ordered_hyps = self._topo_sort_revert_order(ordered_hyps)

        # 9. Check goal
        goal = proof_state.get("goal", "")
        goal_depends = any(ci in goal for ci in concrete_indices)

        # Check if we should raise NO_DEPENDENCY
        has_error = bool(proof_state.get("messages"))
        if not ordered_hyps and not has_error:
            raise ConvoyError(
                "NO_DEPENDENCY",
                f"No hypotheses depend on the indices of `{target}`. Standard `destruct` should work.",
            )

        return DependencyReport(
            target=target,
            target_type=target_type.strip(),
            inductive_name=inductive_name,
            parameters=parameters,
            indices=indices,
            dependent_hypotheses=ordered_hyps,
            goal_depends_on_index=goal_depends,
            error_message=None,
        )

    def _extract_inductive_name(self, type_str: str) -> str | None:
        """Extract the inductive type name from a type string like 'Fin (S n)' or 'vec nat 3'."""
        # Strip leading/trailing whitespace
        s = type_str.strip()
        # The first token is the inductive name
        match = re.match(r'([A-Za-z_][A-Za-z0-9_\'\.]*)', s)
        if match:
            name = match.group(1)
            # Filter out obviously non-indexed types
            return name
        return None

    def _parse_inductive_def(
        self, name: str, output: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Parse Print output to distinguish parameters from indices.

        Handles formats like:
          Inductive Fin : nat -> Set :=
          Inductive vec (A : Type) : nat -> Type :=

        Returns (parameters, index_names, index_types).
        """
        parameters: list[str] = []
        index_names: list[str] = []
        index_types: list[str] = []

        # Extract everything between "Inductive <name>" and ":="
        header_match = re.search(
            r'Inductive\s+' + re.escape(name) + r'\s*(.*?)\s*:=',
            output, re.DOTALL,
        )
        if not header_match:
            return parameters, index_names, index_types

        header_body = header_match.group(1).strip()

        # Split on the FIRST top-level colon that is not inside parens
        # This separates "(params) : index_sig"
        param_part, type_part = self._split_on_colon(header_body)

        # Extract parameters from parens
        param_matches = re.findall(r'\(([^)]+)\)', param_part)
        for pm in param_matches:
            parts = pm.split(':')
            if parts:
                pname = parts[0].strip()
                parameters.append(pname)

        # Extract index types from arrows in the type part
        # "nat -> Set" means one index of type nat, result sort Set
        if type_part:
            arrows = [a.strip() for a in type_part.split('->')]
            # Last arrow target is the sort (Set, Type, Prop); preceding are index types
            if len(arrows) > 1:
                for idx_type in arrows[:-1]:
                    idx_type = idx_type.strip()
                    if idx_type:
                        index_types.append(idx_type)
                        index_names.append(f"_idx_{len(index_names)}")

        return parameters, index_names, index_types

    def _split_on_colon(self, s: str) -> tuple[str, str]:
        """Split a string on the first top-level colon (not inside parens)."""
        depth = 0
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ':' and depth == 0:
                return s[:i].strip(), s[i + 1:].strip()
        # No colon found — entire string is the type part
        return "", s

    def _extract_concrete_indices(
        self, type_str: str, inductive_name: str, n_params: int, n_indices: int
    ) -> list[str]:
        """Extract concrete index values from an applied type like 'Fin (S n)' or 'vec nat 3'."""
        # Remove the inductive name
        rest = type_str
        if rest.startswith(inductive_name):
            rest = rest[len(inductive_name):].strip()

        # Tokenize respecting parentheses
        tokens = self._tokenize_args(rest)

        # Skip parameters, take indices
        index_tokens = tokens[n_params:n_params + n_indices]
        return index_tokens if index_tokens else tokens[n_params:]

    def _tokenize_args(self, s: str) -> list[str]:
        """Tokenize a Coq argument list respecting parentheses."""
        tokens: list[str] = []
        depth = 0
        current = ""
        for ch in s:
            if ch == '(' :
                if depth == 0 and current.strip():
                    tokens.append(current.strip())
                    current = ""
                depth += 1
                current += ch
            elif ch == ')':
                current += ch
                depth -= 1
                if depth == 0:
                    tokens.append(current.strip())
                    current = ""
            elif ch == ' ' and depth == 0:
                if current.strip():
                    tokens.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            tokens.append(current.strip())
        return tokens

    def _topo_sort_revert_order(
        self, hyps: list[DependentHypothesis]
    ) -> list[DependentHypothesis]:
        """Topological sort: hypotheses with most dependencies first (revert order)."""
        name_to_hyp = {h.name: h for h in hyps}
        graph: dict[str, set[str]] = {}
        for h in hyps:
            # In the topo sort, h depends_on means h must come BEFORE its deps in revert order
            # revert order: most dependent first
            graph[h.name] = set(h.depends_on)

        try:
            sorter = TopologicalSorter(graph)
            sorted_names = list(sorter.static_order())
        except Exception:
            raise ConvoyError(
                "DEPENDENCY_CYCLE",
                "Circular dependency among hypotheses. Please report this as a bug.",
            )

        # Reverse: topo sort gives leaves first, but we want most-dependent first for revert
        sorted_names = list(reversed(sorted_names))
        return [name_to_hyp[n] for n in sorted_names if n in name_to_hyp]
