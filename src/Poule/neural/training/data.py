"""Training data loading: JSONL parsing, pair extraction, file-level split.

Pair extraction follows specification/neural-training.md §4.1:
- Goals from step k-1 are paired with premises from step k
- Premises with kind 'hypothesis' are filtered out
- Steps with empty premises (after filtering) are skipped
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrainingDataset:
    """Holds train/val/test splits of (proof_state_text, premises_used_names) pairs."""

    train: list[tuple[str, list[str]]]
    val: list[tuple[str, list[str]]]
    test: list[tuple[str, list[str]]]
    premise_corpus: dict


def serialize_goals(goals: list[dict]) -> str:
    """Serialize a list of Goal dicts to a single text string.

    spec §4.1: For each goal, format hypotheses as 'name : type',
    then the goal type, separated by newlines. Multiple goals are
    separated by a blank line.
    """
    if not goals:
        return ""

    parts = []
    for goal in goals:
        lines = []
        for hyp in goal.get("hypotheses", []):
            name = hyp.get("name", "")
            hyp_type = hyp.get("type", "")
            lines.append(f"{name} : {hyp_type}")
        goal_type = goal.get("type", "")
        if goal_type:
            lines.append(goal_type)
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


class TrainingDataLoader:
    """Loads and splits training data from JSONL extraction output."""

    @staticmethod
    def load(jsonl_paths: list[Path], index_db_path: Path) -> TrainingDataset:
        """Load training pairs from ExtractionRecord JSONL files.

        Pair extraction (spec §4.1):
        - For step k (k >= 1): pair goals from steps[k-1] with premises from steps[k]
        - Filter out hypothesis-kind premises
        - Skip steps where all premises are hypotheses or empty
        """
        file_pairs: dict[str, list[tuple[str, list[str]]]] = {}

        for path in jsonl_paths:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Skip non-proof records (metadata, summary, errors)
                    if record.get("record_type") not in ("proof_trace", None):
                        continue

                    source_file = record.get("source_file", "")
                    steps = record.get("steps", [])

                    # Extract pairs: goals from step k-1, premises from step k
                    for k in range(1, len(steps)):
                        prev_step = steps[k - 1]
                        curr_step = steps[k]

                        # Get premises, filtering out hypotheses
                        raw_premises = curr_step.get("premises", [])
                        premises = []
                        for p in raw_premises:
                            if isinstance(p, dict):
                                if p.get("kind") != "hypothesis":
                                    premises.append(p.get("name", ""))
                            elif isinstance(p, str):
                                # Legacy format: plain string premise names
                                premises.append(p)

                        if not premises:
                            continue

                        # Serialize proof state from previous step's goals
                        prev_goals = prev_step.get("goals", [])
                        state_text = serialize_goals(prev_goals)

                        if source_file not in file_pairs:
                            file_pairs[source_file] = []
                        file_pairs[source_file].append((state_text, premises))

        # Load premise corpus from index database
        premise_corpus = {}
        try:
            conn = sqlite3.connect(str(index_db_path))
            rows = conn.execute("SELECT name, statement FROM declarations").fetchall()
            for name, stmt in rows:
                premise_corpus[name] = stmt
            conn.close()
        except Exception:
            pass

        # File-level deterministic split (spec §4.1)
        sorted_files = sorted(file_pairs.keys())

        train_pairs: list[tuple[str, list[str]]] = []
        val_pairs: list[tuple[str, list[str]]] = []
        test_pairs: list[tuple[str, list[str]]] = []

        for position, filepath in enumerate(sorted_files):
            pairs = file_pairs[filepath]
            mod = position % 10
            if mod == 8:
                val_pairs.extend(pairs)
            elif mod == 9:
                test_pairs.extend(pairs)
            else:
                train_pairs.extend(pairs)

        return TrainingDataset(
            train=train_pairs,
            val=val_pairs,
            test=test_pairs,
            premise_corpus=premise_corpus,
        )
