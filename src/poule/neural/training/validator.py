"""Pre-training data quality validation."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationReport:
    """Results from scanning training data for quality issues."""

    total_pairs: int
    empty_premise_pairs: int
    malformed_pairs: int
    unique_premises: int
    unique_states: int
    top_premises: list[tuple[str, int]]
    warnings: list[str] = field(default_factory=list)


class TrainingDataValidator:
    """Validates JSONL extraction output before training."""

    @staticmethod
    def validate(jsonl_paths: list[Path]) -> ValidationReport:
        total_pairs = 0
        empty_premise_pairs = 0
        malformed_pairs = 0
        all_premises: Counter[str] = Counter()
        all_states: set[str] = set()

        for path in jsonl_paths:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        malformed_pairs += 1
                        continue

                    steps = record.get("steps", [])
                    for step in steps:
                        state = step.get("state_before")
                        premises = step.get("premises")

                        if state is None or premises is None:
                            malformed_pairs += 1
                            continue

                        if len(premises) == 0:
                            empty_premise_pairs += 1
                            continue

                        total_pairs += 1
                        all_states.add(state)
                        for p in premises:
                            all_premises[p] += 1

        # Compute warnings
        warnings: list[str] = []

        total_steps = total_pairs + empty_premise_pairs
        if total_steps > 0 and empty_premise_pairs / total_steps > 0.10:
            warnings.append(
                f"Over 10% of steps have empty premise lists — "
                f"check extraction quality"
            )

        if malformed_pairs > 0:
            warnings.append(
                f"Found {malformed_pairs} malformed pairs — "
                f"check extraction output format"
            )

        if total_pairs < 5000:
            warnings.append(
                f"Only {total_pairs} training pairs — model quality may be limited"
            )

        unique_premises = len(all_premises)
        if unique_premises < 1000:
            warnings.append(
                f"Only {unique_premises} unique premises — "
                f"embedding space may be under-constrained"
            )

        # Check for dominant premises (> 5% of all occurrences)
        total_occurrences = sum(all_premises.values())
        if total_occurrences > 0:
            for name, count in all_premises.most_common():
                pct = count / total_occurrences * 100
                if pct > 5.0:
                    warnings.append(
                        f"Premise {name} accounts for {pct:.1f}% of all occurrences — "
                        f"may dominate training"
                    )

        top_premises = all_premises.most_common(10)

        return ValidationReport(
            total_pairs=total_pairs,
            empty_premise_pairs=empty_premise_pairs,
            malformed_pairs=malformed_pairs,
            unique_premises=unique_premises,
            unique_states=len(all_states),
            top_premises=top_premises,
            warnings=warnings,
        )
