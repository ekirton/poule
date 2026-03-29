"""Training data loading: JSONL parsing, pair extraction, file-level split.

Supports two JSONL formats:
- Compact format (spec §4.0.5): "p" (pair) and "g" (goal-state) records,
  produced by convert_training_data() or the extraction pipeline.
- Full proof-trace format (legacy): ExtractionRecord with nested steps.

Pair extraction follows specification/neural-training.md §4.1.
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
    train_files: list[str] = field(default_factory=list)
    val_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    file_deps: dict[str, set[str]] = field(default_factory=dict)
    file_premises: dict[str, set[str]] = field(default_factory=dict)


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


def _extract_pairs_from_record(record):
    """Extract (source_file, state_text, premises) triples from a proof trace."""
    source_file = record.get("source_file", "")
    steps = record.get("steps", [])
    pairs = []

    for k in range(1, len(steps)):
        prev_step = steps[k - 1]
        curr_step = steps[k]

        raw_premises = curr_step.get("premises", [])
        premises = []
        for p in raw_premises:
            if isinstance(p, dict):
                if p.get("kind") != "hypothesis":
                    premises.append(p.get("name", ""))
            elif isinstance(p, str):
                premises.append(p)

        if not premises:
            continue

        prev_goals = prev_step.get("goals", [])
        state_text = serialize_goals(prev_goals)
        pairs.append((source_file, state_text, premises))

    return pairs


# ---------------------------------------------------------------------------
# Compact format conversion (spec §4.0.5)
# ---------------------------------------------------------------------------


def convert_training_data(
    jsonl_paths: list[Path], output_path: Path
) -> dict:
    """Convert full proof-trace JSONL to compact training data format.

    spec §4.0.5: Extracts training pairs and supplementary goal states.
    Non-proof records (campaign_metadata, extraction_summary, extraction_error)
    are passed through unchanged.

    Returns a dict with counts: {pairs, goals, other}.
    """
    pairs_written = 0
    goals_written = 0
    other_written = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    rt = record.get("record_type")

                    # Pass through metadata, errors, summary unchanged
                    if rt in (
                        "campaign_metadata", "extraction_error",
                        "extraction_summary",
                    ):
                        out.write(line + "\n")
                        other_written += 1
                        continue

                    # Skip unknown record types
                    if rt not in ("proof_trace", "partial_proof_trace", None):
                        out.write(line + "\n")
                        other_written += 1
                        continue

                    # Extract pairs
                    pairs = _extract_pairs_from_record(record)
                    covered_states: set[str] = set()
                    for source_file, state_text, premises in pairs:
                        covered_states.add(state_text)
                        out.write(json.dumps(
                            {"t": "p", "f": source_file,
                             "s": state_text, "p": premises},
                            separators=(",", ":"), ensure_ascii=False,
                        ) + "\n")
                        pairs_written += 1

                    # Supplementary goal states for vocabulary builder
                    steps = record.get("steps", [])
                    for step in steps:
                        goals = step.get("goals", [])
                        if goals:
                            state_text = serialize_goals(goals)
                            if state_text and state_text not in covered_states:
                                covered_states.add(state_text)
                                out.write(json.dumps(
                                    {"t": "g", "s": state_text},
                                    separators=(",", ":"), ensure_ascii=False,
                                ) + "\n")
                                goals_written += 1

                    del record, steps, pairs

    return {"pairs": pairs_written, "goals": goals_written, "other": other_written}


# ---------------------------------------------------------------------------
# Data loading (spec §4.1)
# ---------------------------------------------------------------------------


class TrainingDataLoader:
    """Loads and splits training data from compact JSONL."""

    @staticmethod
    def load(jsonl_paths: list[Path], index_db_path: Path) -> TrainingDataset:
        """Load training pairs from compact training data JSONL files.

        spec §4.1: Reads "p" records, groups by source_file, applies
        deterministic file-level split (position % 10).
        """
        # Read pairs from compact JSONL
        file_pairs: dict[str, list[tuple[str, list[str]]]] = {}

        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("t") != "p":
                        continue

                    source_file = record["f"]
                    state_text = record["s"]
                    premises = record["p"]

                    if source_file not in file_pairs:
                        file_pairs[source_file] = []
                    file_pairs[source_file].append((state_text, premises))

        # Load premise corpus and accessibility from index database
        premise_corpus: dict[str, str] = {}
        file_deps: dict[str, set[str]] = {}
        file_premises: dict[str, set[str]] = {}
        try:
            conn = sqlite3.connect(str(index_db_path))

            decl_id_to_module: dict[int, str] = {}
            for decl_id, name, stmt, module in conn.execute(
                "SELECT id, name, statement, module FROM declarations"
            ):
                premise_corpus[name] = stmt
                decl_id_to_module[decl_id] = module
                if module not in file_premises:
                    file_premises[module] = set()
                file_premises[module].add(name)

            try:
                module_adj: dict[str, set[str]] = {}
                for src_id, dst_id in conn.execute(
                    "SELECT src, dst FROM dependencies WHERE relation = 'uses'"
                ):
                    src_mod = decl_id_to_module.get(src_id)
                    dst_mod = decl_id_to_module.get(dst_id)
                    if src_mod and dst_mod and src_mod != dst_mod:
                        if src_mod not in module_adj:
                            module_adj[src_mod] = set()
                        module_adj[src_mod].add(dst_mod)

                for module in file_premises:
                    visited = {module}
                    queue = [module]
                    while queue:
                        current = queue.pop(0)
                        for dep in module_adj.get(current, set()):
                            if dep not in visited:
                                visited.add(dep)
                                queue.append(dep)
                    file_deps[module] = visited

                del module_adj
            except Exception:
                pass

            del decl_id_to_module
            conn.close()
        except Exception:
            pass

        # File-level deterministic split (spec §4.1)
        sorted_files = sorted(file_pairs.keys())

        train_pairs: list[tuple[str, list[str]]] = []
        val_pairs: list[tuple[str, list[str]]] = []
        test_pairs: list[tuple[str, list[str]]] = []
        train_files: list[str] = []
        val_files: list[str] = []
        test_files: list[str] = []

        for position, filepath in enumerate(sorted_files):
            pairs = file_pairs[filepath]
            mod = position % 10
            if mod == 8:
                val_pairs.extend(pairs)
                val_files.extend([filepath] * len(pairs))
            elif mod == 9:
                test_pairs.extend(pairs)
                test_files.extend([filepath] * len(pairs))
            else:
                train_pairs.extend(pairs)
                train_files.extend([filepath] * len(pairs))

        del file_pairs

        return TrainingDataset(
            train=train_pairs,
            val=val_pairs,
            test=test_pairs,
            premise_corpus=premise_corpus,
            train_files=train_files,
            val_files=val_files,
            test_files=test_files,
            file_deps=file_deps,
            file_premises=file_premises,
        )
