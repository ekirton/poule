"""Technique selector for convoy pattern assistant."""

from __future__ import annotations

from typing import Any

from .types import (
    DependencyReport,
    Technique,
    TechniqueRecommendation,
)


class TechniqueSelector:
    """Selects repair technique based on context."""

    REVERT_DESTRUCT = Technique(
        name="revert_destruct",
        description="Revert dependent hypotheses before destructing.",
        axioms_introduced=[],
        requires_plugin=None,
    )

    DEPENDENT_DESTRUCTION = Technique(
        name="dependent_destruction",
        description="Use dependent destruction from Program.Equality.",
        axioms_introduced=["Coq.Logic.JMeq.JMeq_eq"],
        requires_plugin=None,
    )

    INVERSION = Technique(
        name="inversion",
        description="Use inversion for concrete constructor indices.",
        axioms_introduced=[],
        requires_plugin=None,
    )

    CONVOY_PATTERN = Technique(
        name="convoy_pattern",
        description="Use the convoy pattern with match return-clause annotations.",
        axioms_introduced=[],
        requires_plugin=None,
    )

    EQUATIONS_DEPELIM = Technique(
        name="equations_depelim",
        description="Use Equations plugin dependent elimination.",
        axioms_introduced=[],
        requires_plugin="Equations",
    )

    async def select(
        self,
        report: DependencyReport,
        axiom_tolerance: str,
        session_id: str,
        session_manager: Any,
    ) -> TechniqueRecommendation:
        """Select the best technique and alternatives."""
        # Check Equations availability
        equations_available = False
        try:
            locate_output = await session_manager.execute_vernacular(
                session_id, "Locate Equations.Init"
            )
            if locate_output and "not found" not in locate_output.lower():
                equations_available = True
        except Exception:
            pass

        primary = None
        alternatives: list[Technique] = []

        # Rule 1: Inversion candidate
        concrete_indices = all(
            not i.name.startswith("_") and not any(c.isalpha() and c.islower() for c in i.name)
            for i in report.indices
        )
        if len(report.dependent_hypotheses) <= 2 and concrete_indices:
            if primary is None:
                primary = self.INVERSION
            else:
                alternatives.append(self.INVERSION)

        # Rule 2: Revert-before-destruct (tactic mode default)
        if report.dependent_hypotheses:
            if primary is None:
                primary = self.REVERT_DESTRUCT
            else:
                alternatives.append(self.REVERT_DESTRUCT)

        # Rule 3: Dependent destruction (permissive only)
        if axiom_tolerance == "permissive":
            if primary is None:
                primary = self.DEPENDENT_DESTRUCTION
            else:
                alternatives.append(self.DEPENDENT_DESTRUCTION)

        # Rule 5: Equations depelim
        if equations_available:
            if primary is None:
                primary = self.EQUATIONS_DEPELIM
            else:
                alternatives.append(self.EQUATIONS_DEPELIM)

        if primary is None:
            primary = self.REVERT_DESTRUCT

        # Build axiom warning
        axiom_warning = self._build_axiom_warning(
            primary, alternatives, report
        )

        return TechniqueRecommendation(
            primary=primary,
            alternatives=alternatives,
            axiom_warning=axiom_warning,
        )

    def _build_axiom_warning(
        self,
        primary: Technique,
        alternatives: list[Technique],
        report: DependencyReport,
    ) -> str | None:
        """Build axiom warning if any technique introduces axioms."""
        all_techniques = [primary] + alternatives
        has_axiom_technique = any(t.axioms_introduced for t in all_techniques)

        if not has_axiom_technique:
            return None

        warning_parts = [
            "dependent destruction introduces the axiom Coq.Logic.JMeq.JMeq_eq. "
            "Print Assumptions will show this axiom after the proof is closed. "
            "This axiom is consistent with Coq's theory but not provable in it. "
            "Axiom-free alternatives: revert-before-destruct, Equations depelim."
        ]

        # Check for decidable equality
        all_decidable = all(i.has_decidable_eq for i in report.indices)
        if all_decidable and report.indices:
            warning_parts.append(
                " Since all index types have decidable equality, "
                "Eqdep_dec.eq_rect_eq_dec can eliminate the axiom dependency."
            )

        return "".join(warning_parts)
