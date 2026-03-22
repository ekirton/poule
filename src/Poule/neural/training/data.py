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

        # Load premise corpus and accessibility from index database
        premise_corpus: dict[str, str] = {}
        file_deps: dict[str, set[str]] = {}
        file_premises: dict[str, set[str]] = {}
        try:
            conn = sqlite3.connect(str(index_db_path))

            # Load premises with module info
            rows = conn.execute(
                "SELECT id, name, statement, module FROM declarations"
            ).fetchall()
            decl_id_to_module: dict[int, str] = {}
            for decl_id, name, stmt, module in rows:
                premise_corpus[name] = stmt
                decl_id_to_module[decl_id] = module
                if module not in file_premises:
                    file_premises[module] = set()
                file_premises[module].add(name)

            # Build module-level dependency graph from declaration-level edges
            try:
                dep_rows = conn.execute(
                    "SELECT src, dst FROM dependencies WHERE relation = 'uses'"
                ).fetchall()
                module_adj: dict[str, set[str]] = {}
                for src_id, dst_id in dep_rows:
                    src_mod = decl_id_to_module.get(src_id)
                    dst_mod = decl_id_to_module.get(dst_id)
                    if src_mod and dst_mod and src_mod != dst_mod:
                        if src_mod not in module_adj:
                            module_adj[src_mod] = set()
                        module_adj[src_mod].add(dst_mod)

                # Transitive closure per module (BFS)
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
            except Exception:
                pass  # dependencies table missing or empty

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
