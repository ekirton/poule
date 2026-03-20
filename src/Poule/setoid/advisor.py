"""Proof advisor for setoid rewriting assistant."""

from __future__ import annotations

import re
from typing import Any

from .types import ProofStrategy, ProperSignature


class ProofAdvisor:
    """Suggests proof strategies for Proper obligations."""

    async def advise(
        self,
        signature: ProperSignature,
        session_id: str,
        session_manager: Any,
    ) -> ProofStrategy:
        """Suggest a proof strategy for the Proper obligation."""
        # Check if function definition is transparent and compositional
        is_opaque = False
        callees_have_proper = False

        try:
            print_output = await session_manager.execute_vernacular(
                session_id, f"Print {signature.function_name}"
            )
            if print_output and "opaque" in print_output.lower():
                is_opaque = True
            elif print_output:
                # Extract function calls from the definition
                callees = self._extract_callees(print_output)
                if callees:
                    callees_have_proper = await self._check_callees_proper(
                        callees, session_id, session_manager
                    )
        except Exception:
            is_opaque = True

        if not is_opaque and callees_have_proper:
            return ProofStrategy(
                strategy="solve_proper",
                confidence="high",
                proof_skeleton="Proof. solve_proper. Qed.",
            )

        if is_opaque:
            return self._manual_skeleton(signature)

        # Try f_equiv as medium confidence
        return self._manual_skeleton(signature)

    def _manual_skeleton(self, signature: ProperSignature) -> ProofStrategy:
        """Generate a manual proof skeleton."""
        intros_parts: list[str] = []
        hyp_comments: list[str] = []

        for i, slot in enumerate(signature.slots):
            x = f"x{i + 1}"
            y = f"y{i + 1}"
            h = f"H{i + 1}"
            intros_parts.extend([x, y, h])
            rel = slot.relation or "eq"
            hyp_comments.append(f"{h} : {rel} {x} {y}")

        intros_str = " ".join(intros_parts)
        hyp_str = ", ".join(hyp_comments)

        skeleton = (
            f"Proof.\n"
            f"  unfold Proper, respectful.\n"
            f"  intros {intros_str}.\n"
            f"  (* prove: {signature.return_relation} "
            f"({signature.function_name} {' '.join(f'x{i+1}' for i in range(len(signature.slots)))}) "
            f"({signature.function_name} {' '.join(f'y{i+1}' for i in range(len(signature.slots)))}) *)\n"
            f"  (* using: {hyp_str} *)\n"
            f"Admitted."
        )

        return ProofStrategy(
            strategy="manual",
            confidence="low",
            proof_skeleton=skeleton,
        )

    def _extract_callees(self, print_output: str) -> list[str]:
        """Extract function names called in a definition."""
        # Simple heuristic: find identifiers after "=" in the definition
        match = re.search(r'=\s*(.*)', print_output, re.DOTALL)
        if not match:
            return []

        body = match.group(1)
        # Extract identifiers
        identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_\']*)\b', body)
        # Filter common keywords
        keywords = {
            "fun", "let", "in", "match", "with", "end", "if", "then", "else",
            "return", "forall", "exists", "Type", "Set", "Prop", "true", "false",
        }
        return [i for i in identifiers if i not in keywords]

    async def _check_callees_proper(
        self,
        callees: list[str],
        session_id: str,
        session_manager: Any,
    ) -> bool:
        """Check if all callees have Proper instances."""
        for callee in callees:
            try:
                output = await session_manager.execute_vernacular(
                    session_id, f"Search Proper {callee}"
                )
                if output and output.strip():
                    continue
                return False
            except Exception:
                return False
        return True
