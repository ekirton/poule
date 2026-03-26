"""Instance checker for setoid rewriting assistant."""

from __future__ import annotations

import re
from typing import Any

from .types import ExistingInstance, InstanceCheckResult


# Static lookup table for standard library Proper instances (§4.3.3)
STDLIB_PROPER_INSTANCES: dict[str, tuple[str, str]] = {
    "and": ("iff ==> iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
    "or": ("iff ==> iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
    "not": ("iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
    "impl": ("iff ==> iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
    "all": ("pointwise_relation A iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
    "ex": ("pointwise_relation A iff ==> iff", "Stdlib.Classes.Morphisms_Prop"),
}


class InstanceChecker:
    """Checks for existing Proper instances and base relation registration."""

    async def check(
        self,
        function_name: str | None,
        relation_names: list[str],
        session_id: str,
        session_manager: Any,
    ) -> InstanceCheckResult:
        """Check existing instances and base relation registration."""
        existing_instances: list[ExistingInstance] = []
        stdlib_suggestion: str | None = None

        # Check stdlib table
        if function_name and function_name in STDLIB_PROPER_INSTANCES:
            sig, module = STDLIB_PROPER_INSTANCES[function_name]
            stdlib_suggestion = f"Require Import {module}."

        # Search for existing Proper instances
        if function_name:
            try:
                output = await session_manager.execute_vernacular(
                    session_id, f"Search Proper {function_name}"
                )
                if output and output.strip():
                    existing_instances = self._parse_search_proper(output, function_name, relation_names)
            except Exception:
                pass

            # Also check Print Instances Proper
            if not existing_instances:
                try:
                    output = await session_manager.execute_vernacular(
                        session_id, "Print Instances Proper"
                    )
                    if output and function_name in output:
                        existing_instances = self._parse_print_instances(output, function_name, relation_names)
                except Exception:
                    pass

        # Check base relation registration
        base_registered = False
        base_class: str | None = None

        for rel in relation_names:
            if not rel or rel == "eq":
                continue
            try:
                equiv_output = await session_manager.execute_vernacular(
                    session_id, f"Search Equivalence {rel}"
                )
                if equiv_output and equiv_output.strip():
                    base_registered = True
                    base_class = "Equivalence"
                    break
            except Exception:
                pass

            try:
                preorder_output = await session_manager.execute_vernacular(
                    session_id, f"Search PreOrder {rel}"
                )
                if preorder_output and preorder_output.strip():
                    base_registered = True
                    base_class = "PreOrder"
                    break
            except Exception:
                pass

        return InstanceCheckResult(
            existing_instances=existing_instances,
            base_relation_registered=base_registered,
            base_relation_class=base_class,
            stdlib_suggestion=stdlib_suggestion,
        )

    def _parse_search_proper(
        self,
        output: str,
        function_name: str,
        expected_relations: list[str],
    ) -> list[ExistingInstance]:
        """Parse Search Proper output into ExistingInstance records."""
        instances: list[ExistingInstance] = []
        for line in output.strip().splitlines():
            line = line.strip()
            if not line or function_name not in line:
                continue

            # Pattern: instance_name : Proper (sig) function
            match = re.match(r'(\S+)\s*:\s*(Proper\s*\(.+\)\s*\S+)', line)
            if match:
                inst_name = match.group(1)
                sig = match.group(2)

                # Determine compatibility
                compat = self._check_compatibility(sig, expected_relations)

                instances.append(
                    ExistingInstance(
                        instance_name=inst_name,
                        signature=sig,
                        compatibility=compat[0],
                        incompatibility_detail=compat[1],
                    )
                )
        return instances

    def _parse_print_instances(
        self,
        output: str,
        function_name: str,
        expected_relations: list[str],
    ) -> list[ExistingInstance]:
        """Parse Print Instances Proper output."""
        instances: list[ExistingInstance] = []
        for line in output.strip().splitlines():
            line = line.strip()
            if function_name not in line:
                continue

            match = re.match(r'(\S+)\s*:\s*(Proper\s*\(.+\)\s*\S+)', line)
            if match:
                inst_name = match.group(1)
                sig = match.group(2)
                compat = self._check_compatibility(sig, expected_relations)
                instances.append(
                    ExistingInstance(
                        instance_name=inst_name,
                        signature=sig,
                        compatibility=compat[0],
                        incompatibility_detail=compat[1],
                    )
                )
        return instances

    def _check_compatibility(
        self, sig: str, expected_relations: list[str]
    ) -> tuple[str, str | None]:
        """Check if a signature is compatible with expected relations."""
        if not expected_relations:
            return ("exact_match", None)

        # Extract relations from the signature
        sig_relations = re.findall(r'(\w+)\s*==>', sig)
        # Add the output relation (last one before the function name)
        last_match = re.search(r'==>\s*(\w+)\)', sig)
        if last_match:
            sig_relations.append(last_match.group(1))

        # Compare
        for i, expected in enumerate(expected_relations):
            if expected and i < len(sig_relations):
                if sig_relations[i] != expected:
                    if sig_relations[i] == "eq":
                        # eq is always compatible (weaker)
                        continue
                    return (
                        "incompatible",
                        f"Instance uses `{sig_relations[i]}` for argument {i} but `{expected}` is required",
                    )

        return ("exact_match", None)
