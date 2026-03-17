"""Training data loading: JSONL parsing, pair extraction, file-level split."""

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


class TrainingDataLoader:
    """Loads and splits training data from JSONL extraction output."""

    @staticmethod
    def load(jsonl_paths: list[Path], index_db_path: Path) -> TrainingDataset:
        # Parse all records from JSONL files
        file_pairs: dict[str, list[tuple[str, list[str]]]] = {}

        for path in jsonl_paths:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    source_file = record["source_file"]
                    for step in record.get("steps", []):
                        premises = step.get("premises", [])
                        if len(premises) > 0:
                            state_text = step["state_before"]
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

        # File-level deterministic split
        sorted_files = sorted(file_pairs.keys())

        train_pairs = []
        val_pairs = []
        test_pairs = []

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
