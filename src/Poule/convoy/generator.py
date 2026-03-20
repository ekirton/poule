"""Boilerplate generator for convoy pattern assistant."""

from __future__ import annotations

from typing import Any

from .types import DependencyReport, GeneratedCode, TechniqueRecommendation


class BoilerplateGenerator:
    """Generates code for the recommended repair technique."""

    async def generate(
        self,
        report: DependencyReport,
        recommendation: TechniqueRecommendation,
        session_id: str,
        session_manager: Any,
    ) -> GeneratedCode:
        """Generate boilerplate for the primary technique."""
        technique_name = recommendation.primary.name

        if technique_name == "revert_destruct":
            return self._gen_revert_destruct(report)
        elif technique_name == "dependent_destruction":
            return await self._gen_dependent_destruction(report, session_id, session_manager)
        elif technique_name == "inversion":
            return self._gen_inversion(report)
        elif technique_name == "convoy_pattern":
            return self._gen_convoy_pattern(report)
        elif technique_name == "equations_depelim":
            return await self._gen_equations(report, session_id, session_manager)
        else:
            return self._gen_revert_destruct(report)

    def _gen_revert_destruct(self, report: DependencyReport) -> GeneratedCode:
        """Generate revert/destruct tactic sequence."""
        hyp_names = " ".join(h.name for h in report.dependent_hypotheses)
        code = f"revert {hyp_names}. destruct {report.target}."
        return GeneratedCode(
            technique="revert_destruct",
            imports=[],
            setup=[],
            code=code,
            validation_result=None,
        )

    async def _gen_dependent_destruction(
        self, report: DependencyReport, session_id: str, session_manager: Any
    ) -> GeneratedCode:
        """Generate dependent destruction tactic."""
        imports: list[str] = []
        try:
            locate_output = await session_manager.execute_vernacular(
                session_id, "Locate dependent_destruction"
            )
            if not locate_output or "not found" in locate_output.lower():
                imports.append("Require Import Coq.Program.Equality.")
        except Exception:
            imports.append("Require Import Coq.Program.Equality.")

        code = f"dependent destruction {report.target}."
        return GeneratedCode(
            technique="dependent_destruction",
            imports=imports,
            setup=[],
            code=code,
            validation_result=None,
        )

    def _gen_inversion(self, report: DependencyReport) -> GeneratedCode:
        """Generate inversion tactic."""
        code = f"inversion {report.target}; subst."
        return GeneratedCode(
            technique="inversion",
            imports=[],
            setup=[],
            code=code,
            validation_result=None,
        )

    def _gen_convoy_pattern(self, report: DependencyReport) -> GeneratedCode:
        """Generate convoy pattern match expression skeleton."""
        hyp_args = ", ".join(f"({h.name} : {h.type})" for h in report.dependent_hypotheses)
        code = (
            f"match {report.target} as _x in {report.inductive_name} _ "
            f"return ({hyp_args} -> _) with\n"
            f"| _ => fun {' '.join(h.name for h in report.dependent_hypotheses)} => _\n"
            f"end {' '.join(h.name for h in report.dependent_hypotheses)}"
        )
        return GeneratedCode(
            technique="convoy_pattern",
            imports=[],
            setup=[],
            code=code,
            validation_result=None,
        )

    async def _gen_equations(
        self, report: DependencyReport, session_id: str, session_manager: Any
    ) -> GeneratedCode:
        """Generate Equations definition skeleton."""
        imports: list[str] = ["From Equations Require Import Equations."]
        setup: list[str] = []

        try:
            locate_output = await session_manager.execute_vernacular(
                session_id, f"Locate NoConfusion_{report.inductive_name}"
            )
            if not locate_output or "not found" in locate_output.lower():
                setup.append(f"Derive NoConfusion for {report.inductive_name}.")
                setup.append(f"Derive Signature for {report.inductive_name}.")
        except Exception:
            setup.append(f"Derive NoConfusion for {report.inductive_name}.")
            setup.append(f"Derive Signature for {report.inductive_name}.")

        code = f"depelim {report.target}."
        return GeneratedCode(
            technique="equations_depelim",
            imports=imports,
            setup=setup,
            code=code,
            validation_result=None,
        )
