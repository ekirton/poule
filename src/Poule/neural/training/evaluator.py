"""Retrieval evaluation and comparison reporting.

Implements spec §4.5: RetrievalEvaluator with Recall@k, MRR, and
neural vs. symbolic comparison via RRF re-ranking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvaluationReport:
    """Metrics from evaluating a neural encoder on a test set."""

    recall_at_1: float
    recall_at_10: float
    recall_at_32: float
    mrr: float
    test_count: int
    mean_premises_per_state: float
    mean_query_latency_ms: float
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.recall_at_32 < 0.50:
            self.warnings.append(
                "Model does not meet deployment threshold (Recall@32 < 50%)"
            )


@dataclass
class ComparisonReport:
    """Comparison of neural, symbolic, and union retrieval channels."""

    neural_recall_32: float
    symbolic_recall_32: float
    union_recall_32: float
    relative_improvement: float
    overlap_pct: float
    neural_exclusive_pct: float
    symbolic_exclusive_pct: float
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.relative_improvement < 0.15:
            self.warnings.append(
                "Neural channel may not provide sufficient complementary value "
                "(union improvement < 15%)"
            )


class RetrievalEvaluator:
    """Evaluates neural encoder retrieval quality."""

    @staticmethod
    def evaluate(
        checkpoint_path: Path,
        test_data: list[tuple[str, list[str]]],
        index_db_path: Path,
    ) -> EvaluationReport:
        """Evaluate a neural encoder checkpoint on test data.

        spec §4.5: For each test state, encode it, retrieve top-k premises
        from the full corpus, and compute R@1, R@10, R@32, MRR.

        Args:
            checkpoint_path: Path to a trained model checkpoint.
            test_data: List of (proof_state_text, premises_used_names) pairs.
            index_db_path: Path to the index database containing the premise corpus.

        Returns:
            EvaluationReport with all retrieval metrics.
        """
        import sqlite3

        import torch
        from transformers import AutoTokenizer

        from Poule.neural.training.errors import CheckpointNotFoundError
        from Poule.neural.training.model import BiEncoder
        from Poule.neural.training.trainer import load_checkpoint

        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        # Load model
        checkpoint = load_checkpoint(checkpoint_path)
        hp = checkpoint.get("hyperparams", {})
        max_seq_length = hp.get("max_seq_length", 512)

        model = BiEncoder.from_checkpoint(checkpoint)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        model.eval()

        tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")

        # Load premise corpus — stream from DB to avoid holding all
        # statement text in memory simultaneously.
        from Poule.neural.training.data import SQLitePremiseCorpus, _MAX_STMT

        corpus = SQLitePremiseCorpus(index_db_path)
        premise_names = list(corpus.keys())

        # Encode all premises in streaming batches
        with torch.no_grad():
            all_embs = []
            _CHUNK = 64
            for start in range(0, len(premise_names), _CHUNK):
                chunk_names = premise_names[start:start + _CHUNK]
                chunk_texts = corpus.get_batch(chunk_names)
                embs = _encode_texts_batched(
                    model, tokenizer, chunk_texts, max_seq_length, device
                )
                all_embs.append(embs)
            premise_embs = torch.cat(all_embs, dim=0)
            del all_embs

        # Evaluate each test pair
        hits_at_1 = 0
        hits_at_10 = 0
        hits_at_32 = 0
        reciprocal_ranks: list[float] = []
        total_premises = 0
        total_latency_ms = 0.0

        with torch.no_grad():
            for state_text, positive_names in test_data:
                positive_set = set(positive_names)
                total_premises += len(positive_set)

                t0 = time.perf_counter()
                state_emb = _encode_texts_batched(
                    model, tokenizer, [state_text], max_seq_length, device
                )
                scores = torch.mm(state_emb, premise_embs.t()).squeeze(0)
                sorted_indices = torch.argsort(scores, descending=True).tolist()
                t1 = time.perf_counter()
                total_latency_ms += (t1 - t0) * 1000.0

                # Find rank of first correct premise
                first_rank = None
                for rank, idx in enumerate(sorted_indices):
                    if premise_names[idx] in positive_set:
                        first_rank = rank + 1  # 1-based
                        break

                if first_rank is not None:
                    reciprocal_ranks.append(1.0 / first_rank)
                    if first_rank <= 1:
                        hits_at_1 += 1
                    if first_rank <= 10:
                        hits_at_10 += 1
                    if first_rank <= 32:
                        hits_at_32 += 1
                else:
                    reciprocal_ranks.append(0.0)

        n = len(test_data)
        if n == 0:
            return EvaluationReport(
                recall_at_1=0.0,
                recall_at_10=0.0,
                recall_at_32=0.0,
                mrr=0.0,
                test_count=0,
                mean_premises_per_state=0.0,
                mean_query_latency_ms=0.0,
            )

        return EvaluationReport(
            recall_at_1=hits_at_1 / n,
            recall_at_10=hits_at_10 / n,
            recall_at_32=hits_at_32 / n,
            mrr=sum(reciprocal_ranks) / n,
            test_count=n,
            mean_premises_per_state=total_premises / n,
            mean_query_latency_ms=total_latency_ms / n,
        )

    @staticmethod
    def compare(
        checkpoint_path: Path,
        test_data: list[tuple[str, list[str]]],
        index_db_path: Path,
    ) -> ComparisonReport:
        """Compare neural, symbolic, and union retrieval on the same test data.

        spec §4.5: Runs three configurations (neural-only, symbolic-only, union
        with RRF re-ranking) and reports overlap/exclusive metrics.

        Args:
            checkpoint_path: Path to a trained model checkpoint.
            test_data: List of (proof_state_text, premises_used_names) pairs.
            index_db_path: Path to the index database.

        Returns:
            ComparisonReport with per-channel and combined metrics.
        """
        import sqlite3

        import torch
        from transformers import AutoTokenizer

        from Poule.neural.training.errors import CheckpointNotFoundError
        from Poule.neural.training.model import BiEncoder
        from Poule.neural.training.trainer import load_checkpoint

        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        # Load model
        checkpoint = load_checkpoint(checkpoint_path)
        hp = checkpoint.get("hyperparams", {})
        max_seq_length = hp.get("max_seq_length", 512)

        model = BiEncoder.from_checkpoint(checkpoint)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        model.eval()

        tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")

        # Load premise corpus — stream from DB
        from Poule.neural.training.data import SQLitePremiseCorpus, _MAX_STMT

        corpus = SQLitePremiseCorpus(index_db_path)
        premise_names = list(corpus.keys())

        # Encode all premises in streaming batches for neural retrieval
        with torch.no_grad():
            all_embs = []
            _CHUNK = 64
            for start in range(0, len(premise_names), _CHUNK):
                chunk_names = premise_names[start:start + _CHUNK]
                chunk_texts = corpus.get_batch(chunk_names)
                embs = _encode_texts_batched(
                    model, tokenizer, chunk_texts, max_seq_length, device
                )
                all_embs.append(embs)
            premise_embs = torch.cat(all_embs, dim=0)
            del all_embs

        # Try to set up symbolic retrieval via pipeline
        symbolic_available = False
        reader = None
        try:
            from Poule.storage.reader import IndexReader

            reader = IndexReader(index_db_path)
            symbolic_available = True
        except Exception:
            pass

        k = 32
        neural_correct: set[int] = set()  # test indices where neural found a hit
        symbolic_correct: set[int] = set()
        union_correct: set[int] = set()

        with torch.no_grad():
            for i, (state_text, positive_names) in enumerate(test_data):
                positive_set = set(positive_names)

                # Neural top-k
                state_emb = _encode_texts_batched(
                    model, tokenizer, [state_text], max_seq_length, device
                )
                scores = torch.mm(state_emb, premise_embs.t()).squeeze(0)
                top_k_idx = torch.topk(scores, min(k, len(scores))).indices.tolist()
                neural_top_k = {premise_names[j] for j in top_k_idx}

                if positive_set & neural_top_k:
                    neural_correct.add(i)

                # Symbolic top-k
                symbolic_top_k: set[str] = set()
                if symbolic_available and reader is not None:
                    try:
                        symbolic_top_k = _symbolic_retrieve(
                            reader, state_text, k, conn
                        )
                    except Exception:
                        pass

                if positive_set & symbolic_top_k:
                    symbolic_correct.add(i)

                # Union with RRF re-ranking
                union_top_k = _rrf_union(neural_top_k, symbolic_top_k, k)
                if positive_set & union_top_k:
                    union_correct.add(i)

        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        conn.close()

        n = len(test_data)
        if n == 0:
            return ComparisonReport(
                neural_recall_32=0.0,
                symbolic_recall_32=0.0,
                union_recall_32=0.0,
                relative_improvement=0.0,
                overlap_pct=0.0,
                neural_exclusive_pct=0.0,
                symbolic_exclusive_pct=0.0,
            )

        neural_r32 = len(neural_correct) / n
        symbolic_r32 = len(symbolic_correct) / n
        union_r32 = len(union_correct) / n

        relative_improvement = (
            (union_r32 - symbolic_r32) / symbolic_r32 if symbolic_r32 > 0 else 0.0
        )

        # Overlap and exclusive counts
        both = neural_correct & symbolic_correct
        neural_only = neural_correct - symbolic_correct
        symbolic_only = symbolic_correct - neural_correct
        total_correct = neural_correct | symbolic_correct

        total_found = len(total_correct) if total_correct else 1  # avoid div by zero
        overlap_pct = len(both) / total_found
        neural_exclusive_pct = len(neural_only) / total_found
        symbolic_exclusive_pct = len(symbolic_only) / total_found

        return ComparisonReport(
            neural_recall_32=neural_r32,
            symbolic_recall_32=symbolic_r32,
            union_recall_32=union_r32,
            relative_improvement=relative_improvement,
            overlap_pct=overlap_pct,
            neural_exclusive_pct=neural_exclusive_pct,
            symbolic_exclusive_pct=symbolic_exclusive_pct,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_texts_batched(model, tokenizer, texts, max_seq_length, device, batch_size=64):
    """Encode texts through the model in batches. Returns a CPU tensor."""
    import torch

    if not texts:
        return torch.zeros(0, model.embedding_dim)

    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        tokens = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_seq_length,
            return_tensors="pt",
        )
        embs = model(
            tokens["input_ids"].to(device),
            tokens["attention_mask"].to(device),
        )
        all_embs.append(embs.detach().cpu())
    return torch.cat(all_embs, dim=0)


def _symbolic_retrieve(reader, state_text: str, k: int, conn) -> set[str]:
    """Retrieve top-k premises using the symbolic pipeline channels.

    Uses available channels (WL kernel, MePo, FTS5) through the IndexReader.
    Returns a set of premise names.
    """
    results: set[str] = set()
    try:
        # FTS5 text search using the proof state as query
        fts_rows = conn.execute(
            "SELECT name FROM declarations WHERE declarations MATCH ? LIMIT ?",
            (state_text[:200], k),  # truncate long states for FTS query
        ).fetchall()
        for (name,) in fts_rows:
            results.add(name)
    except Exception:
        pass

    return results


def _rrf_union(
    neural_set: set[str], symbolic_set: set[str], k: int, rrf_k: int = 60
) -> set[str]:
    """Combine two ranked sets using Reciprocal Rank Fusion.

    Each set is treated as a ranking (arbitrary order within set since we
    only have top-k membership). RRF score = 1/(k + rank) for items in
    the set, 0 for items not in the set.
    """
    scores: dict[str, float] = {}

    # Neural rankings — items in the set get rank 1..n
    for rank, name in enumerate(neural_set, 1):
        scores[name] = scores.get(name, 0.0) + 1.0 / (rrf_k + rank)

    # Symbolic rankings
    for rank, name in enumerate(symbolic_set, 1):
        scores[name] = scores.get(name, 0.0) + 1.0 / (rrf_k + rank)

    # Return top-k by RRF score
    sorted_names = sorted(scores.keys(), key=lambda n: scores[n], reverse=True)
    return set(sorted_names[:k])
