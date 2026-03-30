"""Training data loading: JSONL parsing, pair extraction, file-level split.

Reads compact training data JSONL (spec §4.0.5): "p" (pair) and "g"
(goal-state) records produced by the extraction pipeline.

Pair extraction follows specification/neural-training.md §4.1.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Premise statements beyond this length are truncated on read.
# The tokenizer truncates to max_seq_length tokens (~256), so text
# beyond ~4K chars is never used.
_MAX_STMT = 4096


class SQLitePremiseCorpus:
    """Dict-like mapping of premise name → statement, backed by SQLite.

    Keeps only the set of names in RAM.  Statement text is fetched from
    the database on demand so that the full 118K-entry corpus (500 MB+
    in Python UCS-2 strings) never resides in process memory.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        conn = sqlite3.connect(self._db_path)
        self._names: frozenset[str] = frozenset(
            row[0] for row in conn.execute("SELECT name FROM declarations")
        )
        conn.close()

    # -- dict-like interface used by trainer / evaluator --

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def __len__(self) -> int:
        return len(self._names)

    def keys(self):
        return self._names

    def __getitem__(self, name: str) -> str:
        if name not in self._names:
            raise KeyError(name)
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT statement FROM declarations WHERE name = ?", (name,)
        ).fetchone()
        conn.close()
        if row is None:
            raise KeyError(name)
        stmt = row[0]
        return stmt[:_MAX_STMT] if len(stmt) > _MAX_STMT else stmt

    def get_batch(self, names: list[str]) -> list[str]:
        """Fetch statements for a list of names in one DB round-trip."""
        if not names:
            return []
        conn = sqlite3.connect(self._db_path)
        placeholders = ",".join("?" * len(names))
        rows = dict(conn.execute(
            f"SELECT name, statement FROM declarations WHERE name IN ({placeholders})",
            names,
        ).fetchall())
        conn.close()
        results = []
        for n in names:
            stmt = rows.get(n, "")
            results.append(stmt[:_MAX_STMT] if len(stmt) > _MAX_STMT else stmt)
        return results

    def iter_batched(self, batch_size: int = 1024):
        """Yield (name, statement) pairs from the DB in batches."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute("SELECT name, statement FROM declarations")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for name, stmt in rows:
                yield name, (stmt[:_MAX_STMT] if len(stmt) > _MAX_STMT else stmt)
        conn.close()


@dataclass
class TrainingDataset:
    """Holds train/val/test splits of (proof_state_text, premises_used_names) pairs."""

    train: list[tuple[str, list[str]]]
    val: list[tuple[str, list[str]]]
    test: list[tuple[str, list[str]]]
    premise_corpus: SQLitePremiseCorpus | dict
    train_files: list[str] = field(default_factory=list)
    val_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    file_deps: dict[str, set[str]] = field(default_factory=dict)
    file_premises: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class SplitReport:
    """Diagnostic report on train/val/test split distributions.

    spec §4.1: Generated from a populated TrainingDataset to diagnose
    distribution shift between splits.
    """

    train_files: int
    val_files: int
    test_files: int
    train_pairs: int
    val_pairs: int
    test_pairs: int
    train_mean_pairs_per_file: float
    train_median_pairs_per_file: float
    val_mean_pairs_per_file: float
    val_median_pairs_per_file: float
    test_mean_pairs_per_file: float
    test_median_pairs_per_file: float
    train_unique_premises: int
    val_unique_premises: int
    test_unique_premises: int
    premises_in_all_splits: int
    premises_train_only: int
    premises_val_only: int
    premises_test_only: int
    test_premise_train_coverage: float
    train_top_premises: list[tuple[str, int]]
    val_top_premises: list[tuple[str, int]]
    test_top_premises: list[tuple[str, int]]
    test_premise_mean_train_freq: float
    test_premise_median_train_freq: float
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def generate(dataset: "TrainingDataset") -> "SplitReport":
        """Generate a split diagnostic report from a populated dataset."""

        def _premise_counter(pairs: list[tuple[str, list[str]]]) -> Counter:
            c: Counter[str] = Counter()
            for _, premises in pairs:
                for p in premises:
                    c[p] += 1
            return c

        def _pairs_per_file_stats(
            file_list: list[str],
        ) -> tuple[int, float, float]:
            if not file_list:
                return 0, 0.0, 0.0
            counts = Counter(file_list)
            values = list(counts.values())
            n_files = len(counts)
            mean = sum(values) / n_files
            med = float(statistics.median(values))
            return n_files, mean, med

        train_counter = _premise_counter(dataset.train)
        val_counter = _premise_counter(dataset.val)
        test_counter = _premise_counter(dataset.test)

        train_premises = set(train_counter)
        val_premises = set(val_counter)
        test_premises = set(test_counter)

        all_splits = train_premises & val_premises & test_premises
        train_only = train_premises - val_premises - test_premises
        val_only = val_premises - train_premises - test_premises
        test_only = test_premises - train_premises - val_premises

        test_unique = len(test_premises)
        coverage = (
            len(test_premises & train_premises) / test_unique
            if test_unique > 0
            else 0.0
        )

        # Training-set frequency of test ground-truth premises
        if test_premises:
            freqs = [train_counter.get(p, 0) for p in test_premises]
            mean_freq = sum(freqs) / len(freqs)
            median_freq = float(statistics.median(freqs))
        else:
            mean_freq = 0.0
            median_freq = 0.0

        tr_nf, tr_mean, tr_med = _pairs_per_file_stats(dataset.train_files)
        va_nf, va_mean, va_med = _pairs_per_file_stats(dataset.val_files)
        te_nf, te_mean, te_med = _pairs_per_file_stats(dataset.test_files)

        # Warnings
        warnings: list[str] = []
        if test_unique > 0 and coverage < 0.50:
            warnings.append(
                "Less than 50% of test ground-truth premises "
                "appear in training data"
            )
        if test_unique > 0 and len(test_only) / test_unique > 0.30:
            warnings.append(
                "Over 30% of test premises are unseen in training"
            )
        if test_unique > 0 and median_freq < 5:
            warnings.append(
                "Test ground-truth premises have low training-set "
                f"frequency (median {median_freq:.0f})"
            )
        if len(dataset.test) < 100:
            warnings.append(
                "Test split has fewer than 100 pairs -- "
                "metrics will be noisy"
            )
        if len(dataset.val) < 100:
            warnings.append(
                "Validation split has fewer than 100 pairs -- "
                "metrics will be noisy"
            )

        return SplitReport(
            train_files=tr_nf,
            val_files=va_nf,
            test_files=te_nf,
            train_pairs=len(dataset.train),
            val_pairs=len(dataset.val),
            test_pairs=len(dataset.test),
            train_mean_pairs_per_file=tr_mean,
            train_median_pairs_per_file=tr_med,
            val_mean_pairs_per_file=va_mean,
            val_median_pairs_per_file=va_med,
            test_mean_pairs_per_file=te_mean,
            test_median_pairs_per_file=te_med,
            train_unique_premises=len(train_premises),
            val_unique_premises=len(val_premises),
            test_unique_premises=test_unique,
            premises_in_all_splits=len(all_splits),
            premises_train_only=len(train_only),
            premises_val_only=len(val_only),
            premises_test_only=len(test_only),
            test_premise_train_coverage=coverage,
            train_top_premises=train_counter.most_common(10),
            val_top_premises=val_counter.most_common(10),
            test_top_premises=test_counter.most_common(10),
            test_premise_mean_train_freq=mean_freq,
            test_premise_median_train_freq=median_freq,
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
                    # Fast pre-filter: only JSON-parse lines that are
                    # "p" records.  The other 163 K lines (g, errors,
                    # metadata) would allocate large temporary strings
                    # that fragment Python's heap without ever being
                    # retained — pymalloc never returns that memory.
                    if '"t":"p"' not in line[:25] and '"t": "p"' not in line[:25]:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("t") != "p":
                        continue

                    source_file = record["f"]
                    state_text = record["s"]
                    if len(state_text) > _MAX_STMT:
                        state_text = state_text[:_MAX_STMT]
                    # Intern premise names: 27M references to only ~22K
                    # unique strings.  Without interning, each json.loads
                    # creates a fresh str object per name, inflating
                    # memory from <1 MB to ~2.7 GB.
                    premises = [sys.intern(p) for p in record["p"]]

                    if source_file not in file_pairs:
                        file_pairs[source_file] = []
                    file_pairs[source_file].append((state_text, premises))

        # Return freed JSON-parse memory to the OS.  Python's pymalloc
        # keeps large-object arenas allocated even after objects are
        # freed; malloc_trim asks glibc to release them.
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        # Premise corpus: only names live in RAM; statement text is
        # fetched from SQLite on demand (saves ~500 MB+ of UCS-2 strings).
        premise_corpus = SQLitePremiseCorpus(index_db_path)

        # Load file-level dependency graph for hard-negative sampling
        file_deps: dict[str, set[str]] = {}
        file_premises: dict[str, set[str]] = {}
        try:
            conn = sqlite3.connect(str(index_db_path))

            decl_id_to_module: dict[int, str] = {}
            for decl_id, name, module in conn.execute(
                "SELECT id, name, module FROM declarations"
            ):
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
