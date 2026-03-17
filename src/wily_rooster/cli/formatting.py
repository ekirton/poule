"""Output formatting for CLI search results and proof traces."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wily_rooster.models.responses import LemmaDetail, Module, SearchResult
    from wily_rooster.session.types import PremiseAnnotation, ProofTrace


def format_search_results(
    results: list[SearchResult], *, json_mode: bool
) -> str:
    if json_mode:
        return json.dumps([asdict(r) for r in results])

    if not results:
        return ""

    blocks = []
    for r in results:
        block = (
            f"{r.name}  {r.kind}  {r.score:.4f}\n"
            f"  {r.statement}\n"
            f"  module: {r.module}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def format_lemma_detail(detail: LemmaDetail, *, json_mode: bool) -> str:
    if json_mode:
        return json.dumps(asdict(detail))

    symbols_str = ", ".join(detail.symbols) if detail.symbols else ""
    return (
        f"{detail.name}  ({detail.kind})\n"
        f"  {detail.statement}\n"
        f"  module:       {detail.module}\n"
        f"  dependencies: {len(detail.dependencies) if detail.dependencies else 0}\n"
        f"  dependents:   {len(detail.dependents) if detail.dependents else 0}\n"
        f"  symbols:      {symbols_str}\n"
        f"  node_count:   {detail.node_count}"
    )


def format_modules(modules: list[Module], *, json_mode: bool) -> str:
    if json_mode:
        return json.dumps([asdict(m) for m in modules])

    if not modules:
        return ""

    lines = []
    for m in modules:
        lines.append(f"{m.name}  ({m.decl_count} declarations)")
    return "\n".join(lines)


def format_proof_trace(
    trace: ProofTrace,
    *,
    premises: list[PremiseAnnotation] | None = None,
    json_mode: bool,
) -> str:
    if json_mode:
        return _format_proof_trace_json(trace, premises)
    return _format_proof_trace_human(trace, premises)


def _format_proof_trace_json(
    trace: ProofTrace,
    premises: list[PremiseAnnotation] | None,
) -> str:
    from wily_rooster.serialization.serialize import (
        serialize_premise_annotation,
        serialize_proof_trace,
    )

    trace_str = serialize_proof_trace(trace)
    if premises is None:
        return trace_str

    # Wrap as {"trace": ..., "premises": [...]} with parsed objects (not strings)
    trace_obj = json.loads(trace_str)
    premises_objs = [
        json.loads(serialize_premise_annotation(p)) for p in premises
    ]
    return json.dumps({"trace": trace_obj, "premises": premises_objs})


def _format_proof_trace_human(
    trace: ProofTrace,
    premises: list[PremiseAnnotation] | None,
) -> str:
    # Build premise lookup: step_index → PremiseAnnotation
    premise_map: dict[int, PremiseAnnotation] = {}
    if premises:
        for p in premises:
            premise_map[p.step_index] = p

    lines = [
        f"Proof: {trace.proof_name}",
        f"File:  {trace.file_path}",
        f"Steps: {trace.total_steps}",
        "",
    ]

    for step in trace.steps:
        if step.step_index == 0:
            lines.append("--- Step 0 (initial) ---")
        else:
            lines.append(f"--- Step {step.step_index}: {step.tactic} ---")

        state = step.state
        if state.is_complete:
            lines.append("(proof complete)")
        else:
            for goal in state.goals:
                lines.append(f"Goal {goal.index + 1}: {goal.type}")
                for hyp in goal.hypotheses:
                    lines.append(f"  {hyp.name} : {hyp.type}")

        # Premise annotations for this step
        if step.step_index in premise_map:
            ann = premise_map[step.step_index]
            if ann.premises:
                prem_strs = [f"{p.name} ({p.kind})" for p in ann.premises]
                lines.append(f"  Premises: {', '.join(prem_strs)}")

        lines.append("")

    return "\n".join(lines).rstrip()
