"""Pre-training data quality validation.

Validates compact JSONL extraction output for tactic prediction training.
Checks "s" (step) records for completeness, tactic family distribution,
and class imbalance.

Spec: specification/neural-training.md §4.7
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from Poule.neural.training.data import extract_tactic_family


@dataclass
class ValidationReport:
    """Results from scanning training data for quality issues."""

    total_steps: int
    missing_tactic: int
    malformed_records: int
    unique_states: int
    num_families: int
    family_distribution: list[tuple[str, int]]
    warnings: list[str] = field(default_factory=list)


class TrainingDataValidator:
    """Validates JSONL extraction output before training."""

    @staticmethod
    def validate(jsonl_paths: list[Path]) -> ValidationReport:
        total_steps = 0
        missing_tactic = 0
        malformed_records = 0
        family_counts: Counter[str] = Counter()
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
                        malformed_records += 1
                        continue

                    # Only validate "s" (step) records
                    if record.get("t") == "s":
                        state_text = record.get("s", "")
                        tactic_text = record.get("c", "")
                        if not tactic_text:
                            missing_tactic += 1
                            continue
                        total_steps += 1
                        all_states.add(state_text)
                        family = extract_tactic_family(tactic_text)
                        family_counts[family] += 1
                        continue

                    # Skip non-step records ("g", metadata, errors, etc.)
                    if record.get("t") == "g" or "record_type" in record:
                        continue

        # Compute warnings
        warnings: list[str] = []

        if malformed_records > 0:
            warnings.append(
                f"Found {malformed_records} malformed records -- "
                f"check extraction output format"
            )

        if missing_tactic > 0:
            warnings.append(
                f"Found {missing_tactic} step records with missing tactic text"
            )

        if total_steps < 10000:
            warnings.append(
                f"Only {total_steps} training steps -- model quality may be limited"
            )

        # Check for dominant families (> 30% of all steps)
        if total_steps > 0:
            for name, count in family_counts.most_common():
                pct = count / total_steps
                if pct > 0.30:
                    warnings.append(
                        f"Tactic family '{name}' accounts for {pct:.0%} of all "
                        f"steps -- class weighting recommended"
                    )

        # Warn about families with very few examples
        small_families = [
            name for name, count in family_counts.items() if count < 50
        ]
        if small_families:
            warnings.append(
                f"{len(small_families)} tactic families have < 50 examples: "
                f"{', '.join(sorted(small_families)[:5])}"
                + (" ..." if len(small_families) > 5 else "")
            )

        family_distribution = family_counts.most_common()

        return ValidationReport(
            total_steps=total_steps,
            missing_tactic=missing_tactic,
            malformed_records=malformed_records,
            unique_states=len(all_states),
            num_families=len(family_counts),
            family_distribution=family_distribution,
            warnings=warnings,
        )
