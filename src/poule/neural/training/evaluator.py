"""Retrieval evaluation and comparison reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    def evaluate(checkpoint_path, test_data, index_db_path) -> EvaluationReport:
        raise NotImplementedError("Full evaluation requires torch")

    @staticmethod
    def compare(checkpoint_path, test_data, index_db_path) -> ComparisonReport:
        raise NotImplementedError("Full comparison requires torch and pipeline")
