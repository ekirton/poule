"""Signature generator for setoid rewriting assistant."""

from __future__ import annotations

import re
from typing import Any

from .types import ProperSignature, RelationSlot


class SignatureGenerator:
    """Constructs Proper instance signatures from function types."""

    async def generate(
        self,
        function_name: str,
        partial_slots: list[RelationSlot],
        target_relation: str | None,
        session_id: str,
        session_manager: Any,
    ) -> ProperSignature:
        """Generate a ProperSignature for the given function."""
        # Get function type
        func_type = ""
        try:
            func_type = await session_manager.execute_vernacular(
                session_id, f"Check {function_name}"
            )
            func_type = func_type.strip() if func_type else ""
        except Exception:
            pass

        # Check if function is opaque
        is_opaque = False
        try:
            print_output = await session_manager.execute_vernacular(
                session_id, f"Print {function_name}"
            )
            if print_output and ("opaque" in print_output.lower()):
                is_opaque = True
        except Exception:
            is_opaque = True

        # Decompose type into argument types
        arg_types = self._decompose_type(func_type)

        # Build slots
        slots: list[RelationSlot] = []
        return_relation = "eq"

        for i, arg_type in enumerate(arg_types):
            # Check if partial_slots has info for this position
            existing_rel = None
            for ps in partial_slots:
                if ps.position == i and ps.relation is not None:
                    existing_rel = ps.relation
                    break

            if existing_rel:
                relation = existing_rel
            elif target_relation and (i == len(arg_types) - 1 or arg_type == func_type.split("->")[-1].strip()):
                relation = target_relation
            else:
                relation = "eq"

            slots.append(
                RelationSlot(
                    position=i,
                    relation=relation,
                    argument_type=arg_type,
                    variance="covariant",  # default; opaque always covariant
                )
            )

        # Determine return relation
        if partial_slots:
            # Last slot in partial_signature is often the output relation
            last_partial = max(partial_slots, key=lambda s: s.position) if partial_slots else None
            if last_partial and last_partial.relation:
                return_relation = last_partial.relation

        if target_relation:
            return_relation = target_relation

        # Build declaration
        if slots:
            sig_parts = " ==> ".join(s.relation or "eq" for s in slots)
            sig_str = f"({sig_parts} ==> {return_relation})"
        else:
            sig_str = f"({return_relation})"

        declaration = f"Instance {function_name}_proper : Proper {sig_str} {function_name}."

        return ProperSignature(
            function_name=function_name,
            slots=slots,
            return_relation=return_relation,
            declaration=declaration,
        )

    def _decompose_type(self, type_str: str) -> list[str]:
        """Decompose a function type into argument types."""
        if not type_str:
            return []

        # Split on -> at the top level (not inside parens)
        parts: list[str] = []
        depth = 0
        current = ""
        for ch in type_str:
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == '-' and depth == 0:
                # Check for ->
                pass  # handled below
            else:
                current += ch

        # Simpler approach: split on " -> " outside parens
        parts = []
        depth = 0
        current = ""
        i = 0
        while i < len(type_str):
            ch = type_str[i]
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif type_str[i:i+4] == ' -> ' and depth == 0:
                parts.append(current.strip())
                current = ""
                i += 4
                continue
            else:
                current += ch
            i += 1
        if current.strip():
            parts.append(current.strip())

        # All but the last are argument types
        if len(parts) > 1:
            return parts[:-1]
        return []
