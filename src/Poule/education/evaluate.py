"""Evaluate textbook RAG retrieval quality against a curated question set.

Usage:
    uv run python -m Poule.education.evaluate \\
        --db /data/education.db \\
        --model /data/models/education/encoder.onnx \\
        --tokenizer /data/models/education/tokenizer.json

Questions are loaded from test/data/education_eval_questions.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parents[3] / "test" / "data" / "education_eval_questions.json"


def load_questions(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def evaluate(
    db_path: Path,
    model_path: Path,
    tokenizer_path: Path,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> dict:
    """Run evaluation and return metrics.

    Returns a dict with:
      - chapter_recall_at_k: {k: float} — fraction of questions where the
        expected chapter appears in the top-k results
      - section_recall_at_k: {k: float} — fraction where expected section
        appears in top-k
      - per_question: list of per-question details
    """
    from Poule.education import EducationRAG

    rag = EducationRAG(db_path, model_path, tokenizer_path)
    if not rag.is_available():
        raise RuntimeError("Education RAG not available — check DB and model paths")

    questions = load_questions(questions_path)
    max_k = max(k_values)

    chapter_hits = {k: 0 for k in k_values}
    section_hits = {k: 0 for k in k_values}
    per_question = []

    for q in questions:
        query = q["query"]
        expected_vol = q["expected_volume"]
        expected_chapter = q["expected_chapter"]
        expected_section = q.get("expected_section")

        results = rag.search(query, limit=max_k)

        chapter_found_at = None
        section_found_at = None

        for rank, r in enumerate(results, 1):
            if (
                chapter_found_at is None
                and r.metadata.volume == expected_vol
                and expected_chapter.lower() in r.metadata.chapter.lower()
            ):
                chapter_found_at = rank

            if (
                expected_section
                and section_found_at is None
                and r.metadata.volume == expected_vol
                and expected_section.lower() in r.metadata.section_title.lower()
            ):
                section_found_at = rank

        for k in k_values:
            if chapter_found_at is not None and chapter_found_at <= k:
                chapter_hits[k] += 1
            if section_found_at is not None and section_found_at <= k:
                section_hits[k] += 1

        detail = {
            "query": query,
            "expected": f"{expected_vol}/{expected_chapter}",
            "chapter_found_at": chapter_found_at,
            "section_found_at": section_found_at,
        }
        if results:
            detail["top_result"] = f"{results[0].metadata.volume}/{results[0].metadata.chapter} > {results[0].metadata.section_title}"
        per_question.append(detail)

    n = len(questions)
    chapter_recall = {k: chapter_hits[k] / n for k in k_values}
    section_recall = {k: section_hits[k] / n for k in k_values}

    return {
        "total_questions": n,
        "chapter_recall_at_k": chapter_recall,
        "section_recall_at_k": section_recall,
        "per_question": per_question,
    }


def print_report(metrics: dict) -> None:
    n = metrics["total_questions"]
    print(f"\nEvaluation: {n} questions\n")

    print("Chapter-level recall:")
    for k, recall in metrics["chapter_recall_at_k"].items():
        status = "PASS" if recall >= 0.8 else "FAIL"
        print(f"  recall@{k}: {recall:.1%} ({int(recall * n)}/{n}) [{status}]")

    print("\nSection-level recall:")
    for k, recall in metrics["section_recall_at_k"].items():
        status = "PASS" if recall >= 0.6 else "----"
        print(f"  recall@{k}: {recall:.1%} ({int(recall * n)}/{n}) [{status}]")

    # Show misses
    misses = [q for q in metrics["per_question"] if q["chapter_found_at"] is None]
    if misses:
        print(f"\nChapter misses ({len(misses)}):")
        for m in misses:
            top = m.get("top_result", "no results")
            print(f"  query: {m['query']}")
            print(f"    expected: {m['expected']}, got: {top}")
    else:
        print("\nNo chapter misses.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate education RAG retrieval quality")
    parser.add_argument("--db", required=True, help="Path to education.db")
    parser.add_argument("--model", required=True, help="Path to ONNX encoder model")
    parser.add_argument("--tokenizer", required=True, help="Path to tokenizer.json")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH), help="Path to questions JSON")
    parser.add_argument("--verbose", action="store_true", help="Show per-question details")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    metrics = evaluate(
        Path(args.db), Path(args.model), Path(args.tokenizer),
        questions_path=Path(args.questions),
    )
    print_report(metrics)

    if args.verbose:
        print("\nPer-question details:")
        for q in metrics["per_question"]:
            ch = q["chapter_found_at"] or "MISS"
            sec = q["section_found_at"] or "MISS"
            print(f"  [{ch}/{sec}] {q['query']} — expected: {q['expected']}")
