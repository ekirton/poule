"""Collapse per-library training JSONL into a single file with normalized tactic families.

Addresses class imbalance by merging rare and malformed tactic families
into their parent tactic or "other".  The original per-library files are
never modified.

Specification: specification/neural-training.md §4.0.6
Architecture:  doc/architecture/neural-training.md — Training Data Collapse
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from Poule.neural.training.data import _ALIASES


# Goal-selector prefix, e.g. "1:", "2:", "10:"
_GOAL_SELECTOR_RE = re.compile(r"^\d+:")


def normalize_tactic_family(tactic_text: str) -> str:
    """Normalize raw tactic text to a canonical tactic family name.

    Extends extract_tactic_family with additional rules for compound
    tactic fragments (spec §4.0.6).
    """
    text = tactic_text.strip()
    if not text:
        return "other"

    # Strip SSReflect 'by' prefix
    if text.startswith("by "):
        text = text[3:].strip()
        if not text:
            return "other"

    # Strip leading parentheses: "(apply ..." → "apply ..."
    text = text.lstrip("(")
    if not text:
        return "other"

    # Strip goal-selector prefix: "1:lia" → "lia"
    text = _GOAL_SELECTOR_RE.sub("", text)
    if not text:
        return "other"

    # Compound tactic: take the first segment before ';'
    first_segment = text.split(";")[0].strip()
    if not first_segment:
        return "other"

    # First whitespace-delimited token
    first_token = first_segment.split()[0]

    # Truncate at first '(' to handle "destruct(q_dec" → "destruct"
    paren_idx = first_token.find("(")
    if paren_idx > 0:
        first_token = first_token[:paren_idx]

    # Strip trailing punctuation
    first_token = first_token.rstrip(".,;:?-")
    if not first_token:
        return "other"

    # Strip SSReflect intro pattern operator: move=> → move
    if first_token.endswith("=>"):
        first_token = first_token[:-2]
    if not first_token:
        return "other"

    # Strip SSReflect '/' suffix: apply/eqp -> apply, case/andp -> case
    slash_idx = first_token.find("/")
    if slash_idx > 0:
        first_token = first_token[:slash_idx]
    if not first_token:
        return "other"

    # Lowercase
    family = first_token.lower()

    # Apply aliases
    family = _ALIASES.get(family, family)

    return family


@dataclass
class CollapseReport:
    """Diagnostic report from a collapse operation."""

    total_records: int
    input_files: int
    families_before: int
    families_after: int
    collapsed_to_other: int
    family_distribution: list[tuple[str, int]]
    output_path: str | None

    def to_dict(self) -> dict:
        return {
            "total_records": self.total_records,
            "input_files": self.input_files,
            "families_before": self.families_before,
            "families_after": self.families_after,
            "collapsed_to_other": self.collapsed_to_other,
            "family_distribution": [
                {"family": name, "count": count}
                for name, count in self.family_distribution
            ],
            "output_path": self.output_path,
        }


class TacticCollapser:
    """Merge per-library training JSONL with normalized tactic families."""

    @staticmethod
    def collapse(
        input_paths: list[Path],
        output_path: Path,
        min_count: int = 50,
        dry_run: bool = False,
    ) -> CollapseReport:
        """Read all step records, normalize families, write merged output.

        spec §4.0.6: normalize_tactic_family + min_count thresholding.
        """
        # Phase 1: Read all step records and normalize families
        records: list[tuple[dict, str]] = []  # (raw_record, normalized_family)
        family_counts: Counter[str] = Counter()

        for path in input_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    # Fast pre-filter: only parse "s" records
                    if '"t":"s"' not in line[:25] and '"t": "s"' not in line[:25]:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("t") != "s":
                        continue

                    tactic_text = record.get("c", "")
                    family = normalize_tactic_family(tactic_text)
                    family_counts[family] += 1
                    records.append((record, family))

        families_before = len(family_counts)

        # Phase 2: Determine which families survive the min_count threshold
        surviving: set[str] = set()
        for family, count in family_counts.items():
            if count >= min_count and family != "other":
                surviving.add(family)
        surviving.add("other")

        collapsed_to_other = families_before - len(surviving)
        if "other" in family_counts and family_counts["other"] >= min_count:
            collapsed_to_other += 1  # "other" was already a raw family

        # Recount with thresholding applied
        final_counts: Counter[str] = Counter()
        for _, family in records:
            final_family = family if family in surviving else "other"
            final_counts[final_family] += 1

        distribution = final_counts.most_common()

        report = CollapseReport(
            total_records=len(records),
            input_files=len(input_paths),
            families_before=families_before,
            families_after=len(final_counts),
            collapsed_to_other=collapsed_to_other,
            family_distribution=distribution,
            output_path=str(output_path) if not dry_run else None,
        )

        if dry_run:
            return report

        # Phase 3: Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as out:
            for record, family in records:
                final_family = family if family in surviving else "other"
                record["c"] = final_family
                out.write(json.dumps(record, ensure_ascii=False) + "\n")

        return report
