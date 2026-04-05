"""Training data loading: JSONL parsing, tactic family extraction, file-level split.

Reads compact training data JSONL (spec §4.0.5): "s" (step) and "g"
(goal-state) records produced by the extraction pipeline.

Tactic family extraction and data loading follows specification/neural-training.md §4.1.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# Proof state text beyond this length is truncated on read.
_MAX_STMT = 4096

# Tactic family aliases: normalize variant spellings to canonical names.
_ALIASES: dict[str, str] = {
    "intro": "intros",
    "Proof": "intros",  # "Proof." is effectively a no-op; skip or map
    "now": "auto",  # 'now tac' wraps tac + auto
}


def extract_tactic_family(tactic_text: str) -> str:
    """Extract the tactic family name from raw tactic text.

    spec §4.1: Parse the first whitespace-delimited token, normalize
    SSReflect prefixes, strip trailing punctuation, apply aliases.
    """
    text = tactic_text.strip()
    if not text:
        return "other"

    # Handle SSReflect: strip 'by' prefix
    if text.startswith("by "):
        text = text[3:].strip()
        if not text:
            return "other"

    # Handle compound tactics: take the first segment before ';'
    first_segment = text.split(";")[0].strip()
    if not first_segment:
        return "other"

    # Extract the first token
    first_token = first_segment.split()[0]

    # Strip trailing punctuation
    first_token = first_token.rstrip(".,;:")

    # Strip SSReflect intro pattern operator: move=> -> move
    if first_token.endswith("=>"):
        first_token = first_token[:-2]

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

    # Handle SSReflect compound: move=>/rewrite/apply with modifiers
    if family in ("move", "case", "elim", "have", "suff", "wlog"):
        # These are SSReflect tactics -- keep as-is
        pass

    return family


def serialize_goals(goals: list[dict]) -> str:
    """Serialize a list of Goal dicts to a single text string.

    Canonical implementation is in Poule.extraction.output.serialize_goals.
    This re-export preserves backward compatibility.
    """
    from Poule.extraction.output import serialize_goals as _impl

    return _impl(goals)


@dataclass
class TrainingDataset:
    """Holds train/val/test splits of (proof_state_text, premise_names) pairs
    for bi-encoder premise retrieval training."""

    train: list[tuple[str, list[str]]]
    val: list[tuple[str, list[str]]]
    test: list[tuple[str, list[str]]]
    premise_corpus: dict[str, str]
    train_files: list[str] = field(default_factory=list)
    val_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    file_deps: dict[str, list[str]] = field(default_factory=dict)
    file_premises: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class TacticDataset:
    """Holds train/val/test splits of (proof_state_text, category_idx, within_idx) triples.

    Hierarchical classification: each sample has a category label and a
    within-category tactic label.
    """

    train_pairs: list[tuple[str, int, int]]
    val_pairs: list[tuple[str, int, int]]
    test_pairs: list[tuple[str, int, int]]
    label_map: dict[str, int]
    label_names: list[str]
    family_counts: dict[str, int]
    train_files: list[str] = field(default_factory=list)
    val_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    # Hierarchical fields
    category_names: list[str] = field(default_factory=list)
    per_category_label_maps: dict[str, dict[str, int]] = field(default_factory=dict)
    per_category_label_names: dict[str, list[str]] = field(default_factory=dict)
    per_category_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def num_classes(self) -> int:
        return len(self.label_names)

    @property
    def num_categories(self) -> int:
        return len(self.category_names)

    @property
    def per_category_sizes(self) -> dict[str, int]:
        """Number of tactic families per category."""
        return {
            cat: len(names)
            for cat, names in self.per_category_label_names.items()
        }


@dataclass
class SplitReport:
    """Diagnostic report on train/val/test split distributions.

    spec §4.1: Generated from a populated TacticDataset to diagnose
    distribution shift between splits.
    """

    train_files: int
    val_files: int
    test_files: int
    train_steps: int
    val_steps: int
    test_steps: int
    num_classes: int
    family_distribution: list[tuple[str, int]]
    train_top_families: list[tuple[str, int]]
    val_top_families: list[tuple[str, int]]
    test_top_families: list[tuple[str, int]]
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def generate(dataset: TacticDataset) -> SplitReport:
        """Generate a split diagnostic report from a populated dataset."""

        def _family_counter(
            pairs, label_names: list[str],
        ) -> Counter:
            c: Counter[str] = Counter()
            for item in pairs:
                if len(item) == 3 and dataset.category_names:
                    # Hierarchical triple: (state, category_idx, within_idx)
                    cat_idx = item[1]
                    if cat_idx < len(dataset.category_names):
                        cat_name = dataset.category_names[cat_idx]
                        within_idx = item[2]
                        within_names = dataset.per_category_label_names.get(cat_name, [])
                        if within_idx < len(within_names):
                            c[within_names[within_idx]] += 1
                        else:
                            c[cat_name] += 1
                    else:
                        c["unknown"] += 1
                elif len(item) >= 2:
                    # Flat pair: (state, label_idx)
                    label_idx = item[1]
                    if label_idx < len(label_names):
                        c[label_names[label_idx]] += 1
                    else:
                        c["unknown"] += 1
            return c

        train_counter = _family_counter(dataset.train_pairs, dataset.label_names)
        val_counter = _family_counter(dataset.val_pairs, dataset.label_names)
        test_counter = _family_counter(dataset.test_pairs, dataset.label_names)

        total_counter = train_counter + val_counter + test_counter

        # Unique file counts
        train_file_set = set(dataset.train_files)
        val_file_set = set(dataset.val_files)
        test_file_set = set(dataset.test_files)

        # Warnings
        warnings: list[str] = []
        if len(dataset.test_pairs) < 100:
            warnings.append(
                "Test split has fewer than 100 steps -- metrics will be noisy"
            )
        if len(dataset.val_pairs) < 100:
            warnings.append(
                "Validation split has fewer than 100 steps -- metrics will be noisy"
            )
        # Check for dominant class
        if total_counter:
            top_family, top_count = total_counter.most_common(1)[0]
            total = sum(total_counter.values())
            if total > 0 and top_count / total > 0.30:
                warnings.append(
                    f"Dominant tactic family '{top_family}' accounts for "
                    f"{top_count / total:.0%} of all steps"
                )

        return SplitReport(
            train_files=len(train_file_set),
            val_files=len(val_file_set),
            test_files=len(test_file_set),
            train_steps=len(dataset.train_pairs),
            val_steps=len(dataset.val_pairs),
            test_steps=len(dataset.test_pairs),
            num_classes=dataset.num_classes,
            family_distribution=total_counter.most_common(),
            train_top_families=train_counter.most_common(10),
            val_top_families=val_counter.most_common(10),
            test_top_families=test_counter.most_common(10),
            warnings=warnings,
        )

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        d = {}
        for fld in self.__dataclass_fields__:
            val = getattr(self, fld)
            if isinstance(val, list) and val and isinstance(val[0], tuple):
                val = [[name, count] for name, count in val]
            d[fld] = val
        return d


# ---------------------------------------------------------------------------
# Data loading (spec §4.1)
# ---------------------------------------------------------------------------


class TrainingDataLoader:
    """Loads and splits training data from compact JSONL."""

    @staticmethod
    def load(
        jsonl_paths: list[Path],
    ) -> TacticDataset:
        """Load training steps from compact training data JSONL files.

        Hierarchical labels: each sample is a triple
        (proof_state_text, category_idx, within_category_idx).

        Proof structure tokens are excluded. Every tactic maps to a
        known category -- there is no "other" catch-all.
        """
        from Poule.neural.training.taxonomy import (
            CATEGORY_NAMES,
            EXCLUDED_TOKENS,
            TACTIC_CATEGORIES,
            TACTIC_TO_CATEGORY,
        )

        # Build per-category label maps
        per_category_label_maps: dict[str, dict[str, int]] = {}
        per_category_label_names: dict[str, list[str]] = {}
        for cat in CATEGORY_NAMES:
            tactics = TACTIC_CATEGORIES[cat]
            per_category_label_names[cat] = list(tactics)
            per_category_label_maps[cat] = {t: i for i, t in enumerate(tactics)}

        category_index = {cat: i for i, cat in enumerate(CATEGORY_NAMES)}

        # Build a flat label map (for backward compat / reporting)
        flat_label_names: list[str] = []
        flat_label_map: dict[str, int] = {}
        for cat in CATEGORY_NAMES:
            for tac in TACTIC_CATEGORIES[cat]:
                flat_label_map[tac] = len(flat_label_names)
                flat_label_names.append(tac)

        # Phase 1: Read all steps
        file_steps: dict[str, list[tuple[str, str]]] = {}
        raw_family_counts: Counter[str] = Counter()

        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if '"t":"s"' not in line[:25] and '"t": "s"' not in line[:25]:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("t") != "s":
                        continue

                    source_file = record["f"]
                    state_text = record["s"]
                    tactic_text = record.get("c", "")
                    if not tactic_text:
                        continue

                    if len(state_text) > _MAX_STMT:
                        state_text = state_text[:_MAX_STMT]

                    family = extract_tactic_family(tactic_text)

                    # Skip excluded tokens (proof structure)
                    if family in EXCLUDED_TOKENS:
                        continue

                    # Skip tactics not in the taxonomy
                    if family not in TACTIC_TO_CATEGORY:
                        continue

                    raw_family_counts[family] += 1

                    if source_file not in file_steps:
                        file_steps[source_file] = []
                    file_steps[source_file].append((state_text, family))

        # Return freed JSON-parse memory to the OS.
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        # Build per-category counts
        per_category_counts: dict[str, dict[str, int]] = {}
        for cat in CATEGORY_NAMES:
            cat_counts: dict[str, int] = {}
            for tac in TACTIC_CATEGORIES[cat]:
                count = raw_family_counts.get(tac, 0)
                if count > 0:
                    cat_counts[tac] = count
            per_category_counts[cat] = cat_counts

        # Phase 2: File-level deterministic split (spec §4.1)
        sorted_files = sorted(file_steps.keys())

        train_pairs: list[tuple[str, int, int]] = []
        val_pairs: list[tuple[str, int, int]] = []
        test_pairs: list[tuple[str, int, int]] = []
        train_files: list[str] = []
        val_files: list[str] = []
        test_files: list[str] = []

        for position, filepath in enumerate(sorted_files):
            steps = file_steps[filepath]
            labeled_steps: list[tuple[str, int, int]] = []
            for state, family in steps:
                cat = TACTIC_TO_CATEGORY[family]
                cat_idx = category_index[cat]
                within_idx = per_category_label_maps[cat][family]
                labeled_steps.append((state, cat_idx, within_idx))

            mod = position % 10
            if mod == 8:
                val_pairs.extend(labeled_steps)
                val_files.extend([filepath] * len(labeled_steps))
            elif mod == 9:
                test_pairs.extend(labeled_steps)
                test_files.extend([filepath] * len(labeled_steps))
            else:
                train_pairs.extend(labeled_steps)
                train_files.extend([filepath] * len(labeled_steps))

        del file_steps

        return TacticDataset(
            train_pairs=train_pairs,
            val_pairs=val_pairs,
            test_pairs=test_pairs,
            label_map=flat_label_map,
            label_names=flat_label_names,
            family_counts=dict(raw_family_counts),
            train_files=train_files,
            val_files=val_files,
            test_files=test_files,
            category_names=list(CATEGORY_NAMES),
            per_category_label_maps=per_category_label_maps,
            per_category_label_names=per_category_label_names,
            per_category_counts=per_category_counts,
        )
