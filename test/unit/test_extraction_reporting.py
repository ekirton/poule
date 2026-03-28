"""TDD tests for extraction reporting (specification/extraction-reporting.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/extraction/.

Covers: quality report generation, premise coverage, proof length distribution,
tactic keyword extraction, tactic vocabulary frequency, scope filter, benchmark
subset generation, ML framework export, proof trace validation, and dataset
deduplication.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_extraction_record(
    *,
    theorem_name: str = "Test.theorem",
    project_id: str = "test-project",
    module_path: str = "Test.Module",
    source_file: str = "Test/Module.v",
    total_steps: int = 3,
    steps: list[dict] | None = None,
) -> dict:
    """Build a minimal ExtractionRecord dict for test fixtures."""
    if steps is None:
        steps = [
            {
                "step_index": 0,
                "tactic": "",
                "goals": [{"type": "nat -> nat"}],
                "premises": [],
            },
        ] + [
            {
                "step_index": i,
                "tactic": "simpl.",
                "goals": [{"type": f"goal_{i}"}],
                "premises": [{"name": f"prem_{i}"}] if i % 2 == 1 else [],
            }
            for i in range(1, total_steps + 1)
        ]
    return {
        "record_type": "proof_trace",
        "theorem_name": theorem_name,
        "project_id": project_id,
        "module_path": module_path,
        "source_file": source_file,
        "total_steps": total_steps,
        "steps": steps,
    }


def _make_extraction_error(
    *,
    theorem_name: str = "Test.failed_theorem",
    source_file: str = "Test/Module.v",
    project_id: str = "test-project",
    error_kind: str = "timeout",
    error_message: str = "Proof extraction exceeded 60s time limit",
) -> dict:
    """Build a minimal ExtractionError dict for test fixtures."""
    return {
        "schema_version": 1,
        "record_type": "extraction_error",
        "theorem_name": theorem_name,
        "source_file": source_file,
        "project_id": project_id,
        "error_kind": error_kind,
        "error_message": error_message,
    }


def _make_timed_extraction_record(
    *,
    theorem_name: str = "Test.timed_theorem",
    source_file: str = "Test/Module.v",
    project_id: str = "test-project",
    step_durations_ms: list[int] | None = None,
) -> dict:
    """Build an ExtractionRecord with duration_ms fields in steps."""
    if step_durations_ms is None:
        step_durations_ms = [1000, 2000, 3000]
    steps = [
        {
            "step_index": 0,
            "tactic": "",
            "goals": [{"type": "T"}],
            "premises": [],
            "duration_ms": 0,
        },
    ]
    for i, dur in enumerate(step_durations_ms, start=1):
        steps.append(
            {
                "step_index": i,
                "tactic": "auto.",
                "goals": [{"type": f"g{i}"}],
                "premises": [],
                "duration_ms": dur,
            }
        )
    return {
        "record_type": "proof_trace",
        "theorem_name": theorem_name,
        "project_id": project_id,
        "source_file": source_file,
        "total_steps": len(step_durations_ms),
        "steps": steps,
    }


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    """Write records as JSON Lines to *path* and return the path."""
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Quality Report Generation
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateQualityReport:
    """generate_quality_report reads ExtractionRecords and returns a QualityReport."""

    def test_returns_quality_report_with_aggregate_metrics(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        records = [_make_extraction_record(project_id="proj-a") for _ in range(6)]
        records += [_make_extraction_record(project_id="proj-b") for _ in range(4)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert hasattr(report, "premise_coverage")
        assert hasattr(report, "proof_length_distribution")
        assert hasattr(report, "tactic_vocabulary")
        assert hasattr(report, "per_project")

    def test_per_project_entries_match_distinct_project_ids(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        records = [_make_extraction_record(project_id="proj-a") for _ in range(6)]
        records += [_make_extraction_record(project_id="proj-b") for _ in range(4)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert len(report.per_project) == 2
        project_ids = {p.project_id for p in report.per_project}
        assert project_ids == {"proj-a", "proj-b"}

    def test_filters_by_proof_trace_record_type(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        records = [_make_extraction_record()]
        # Add a non-proof-trace record that should be ignored.
        records.append({"record_type": "metadata", "version": "1.0"})
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert len(report.per_project) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Premise Coverage Computation
# ═══════════════════════════════════════════════════════════════════════════


class TestPremiseCoverage:
    """Premise coverage = steps_with_premises / total_tactic_steps (excluding step 0)."""

    def test_spec_example_85_of_100_steps(self, tmp_path):
        """Given 100 tactic steps where 85 have premises, coverage is 0.85."""
        from Poule.extraction.reporting import generate_quality_report

        # Build a single record with 100 tactic steps (step_index 1..100).
        steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
        ]
        for i in range(1, 101):
            has_premise = i <= 85
            steps.append(
                {
                    "step_index": i,
                    "tactic": "auto.",
                    "goals": [{"type": f"g{i}"}],
                    "premises": [{"name": "p"}] if has_premise else [],
                }
            )
        records = [
            _make_extraction_record(total_steps=100, steps=steps),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        # 85 / 100 = 0.85
        assert report.premise_coverage == pytest.approx(0.85)

    def test_returns_float_in_unit_interval(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        records = [_make_extraction_record()]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert 0.0 <= report.premise_coverage <= 1.0

    def test_zero_when_no_tactic_steps(self, tmp_path):
        """Returns 0.0 when no tactic steps exist (only step 0)."""
        from Poule.extraction.reporting import generate_quality_report

        steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
        ]
        records = [_make_extraction_record(total_steps=0, steps=steps)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert report.premise_coverage == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Proof Length Distribution
# ═══════════════════════════════════════════════════════════════════════════


class TestProofLengthDistribution:
    """DistributionStats from total_steps: min, max, mean, median, p25, p75, p95."""

    def test_single_record_all_stats_equal(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        records = [_make_extraction_record(total_steps=7)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)
        dist = report.proof_length_distribution

        assert dist.min == 7
        assert dist.max == 7
        assert dist.mean == pytest.approx(7.0)
        assert dist.median == pytest.approx(7.0)
        assert dist.p25 == pytest.approx(7.0)
        assert dist.p75 == pytest.approx(7.0)
        assert dist.p95 == pytest.approx(7.0)

    def test_multiple_records_stats_populated(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        step_counts = [1, 3, 5, 8, 12, 20, 50, 100, 200, 342]
        records = [
            _make_extraction_record(total_steps=s, steps=None)
            for s in step_counts
        ]
        # Regenerate steps to avoid mismatch — only total_steps matters
        # for distribution; steps content is for premise/tactic analysis.
        for rec, s in zip(records, step_counts):
            rec["steps"] = [
                {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
            ] + [
                {
                    "step_index": i,
                    "tactic": "auto.",
                    "goals": [{"type": "g"}],
                    "premises": [],
                }
                for i in range(1, s + 1)
            ]

        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)
        dist = report.proof_length_distribution

        assert dist.min == 1
        assert dist.max == 342
        assert dist.mean == pytest.approx(74.1)  # sum=741, n=10
        assert dist.median is not None
        assert dist.p25 is not None
        assert dist.p75 is not None
        assert dist.p95 is not None


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Tactic Keyword Extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestTacticKeywordExtraction:
    """Extract tactic keywords: split by ';', first token, strip trailing punctuation, lowercase."""

    @pytest.mark.parametrize(
        "tactic_text,expected",
        [
            ("rewrite Nat.add_comm.", ["rewrite"]),
            ("simpl; reflexivity.", ["simpl", "reflexivity"]),
            ("apply (f_equal S).", ["apply"]),
        ],
        ids=["simple-rewrite", "compound-semicolon", "apply-with-parens"],
    )
    def test_spec_examples(self, tactic_text, expected):
        from Poule.extraction.reporting import extract_tactic_keywords

        result = extract_tactic_keywords(tactic_text)

        assert result == expected

    def test_result_is_always_lowercase(self):
        from Poule.extraction.reporting import extract_tactic_keywords

        result = extract_tactic_keywords("Rewrite foo.")

        assert result == ["rewrite"]

    def test_strips_trailing_comma_and_semicolon(self):
        from Poule.extraction.reporting import extract_tactic_keywords

        result = extract_tactic_keywords("intro,")

        assert result == ["intro"]

    def test_compound_produces_multiple_keywords(self):
        from Poule.extraction.reporting import extract_tactic_keywords

        result = extract_tactic_keywords("simpl; rewrite H; reflexivity.")

        assert result == ["simpl", "rewrite", "reflexivity"]


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Tactic Vocabulary Frequency
# ═══════════════════════════════════════════════════════════════════════════


class TestTacticVocabularyFrequency:
    """Count tactic keywords sorted by count descending, ties by lexicographic order."""

    def test_sorted_by_count_descending(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        # Create steps with known tactic distribution.
        steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
        ]
        # 3 apply, 2 simpl, 1 rewrite
        for tactic in ["apply H.", "apply H.", "apply H.", "simpl.", "simpl.", "rewrite H."]:
            steps.append(
                {
                    "step_index": len(steps),
                    "tactic": tactic,
                    "goals": [{"type": "g"}],
                    "premises": [],
                }
            )
        records = [_make_extraction_record(total_steps=6, steps=steps)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)
        vocab = report.tactic_vocabulary

        assert vocab[0].tactic == "apply"
        assert vocab[0].count == 3
        assert vocab[1].tactic == "simpl"
        assert vocab[1].count == 2
        assert vocab[2].tactic == "rewrite"
        assert vocab[2].count == 1

    def test_ties_broken_by_lexicographic_order(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
        ]
        # 2 each: simpl, auto — tie → "auto" before "simpl" lexicographically.
        for tactic in ["simpl.", "auto.", "simpl.", "auto."]:
            steps.append(
                {
                    "step_index": len(steps),
                    "tactic": tactic,
                    "goals": [{"type": "g"}],
                    "premises": [],
                }
            )
        records = [_make_extraction_record(total_steps=4, steps=steps)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)
        vocab = report.tactic_vocabulary

        assert vocab[0].tactic == "auto"
        assert vocab[1].tactic == "simpl"
        assert vocab[0].count == vocab[1].count == 2

    def test_one_entry_per_distinct_keyword(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []}
        ]
        for tactic in ["auto.", "auto.", "simpl."]:
            steps.append(
                {
                    "step_index": len(steps),
                    "tactic": tactic,
                    "goals": [{"type": "g"}],
                    "premises": [],
                }
            )
        records = [_make_extraction_record(total_steps=3, steps=steps)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        keywords = [v.tactic for v in report.tactic_vocabulary]
        assert len(keywords) == len(set(keywords))


# ═══════════════════════════════════════════════════════════════════════════
# 4.2 Scope Filter
# ═══════════════════════════════════════════════════════════════════════════


class TestScopeFilter:
    """ScopeFilter with name_pattern and module_prefixes — conjunction semantics."""

    def test_both_filters_match_includes_theorem(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=".*comm.*", module_prefixes=["Stdlib.Arith"])

        assert sf.matches(
            name="Stdlib.Arith.PeanoNat.Nat.add_comm",
            module="Stdlib.Arith.PeanoNat",
        )

    def test_name_pattern_mismatch_excludes_theorem(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=".*comm.*", module_prefixes=["Stdlib.Arith"])

        # "classic" does not match ".*comm.*"
        assert not sf.matches(
            name="Stdlib.Logic.Classical.classic",
            module="Stdlib.Logic.Classical",
        )

    def test_module_prefix_mismatch_excludes_theorem(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=".*comm.*", module_prefixes=["Stdlib.Arith"])

        # Module "Stdlib.Logic" does not start with "Stdlib.Arith".
        assert not sf.matches(
            name="Stdlib.Logic.SomeModule.add_comm",
            module="Stdlib.Logic.SomeModule",
        )

    def test_neither_filter_set_matches_all(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=None, module_prefixes=None)

        assert sf.matches(name="Anything.Goes", module="Any.Module")

    def test_only_name_pattern_set(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=".*comm.*", module_prefixes=None)

        assert sf.matches(name="Foo.add_comm", module="Foo")
        assert not sf.matches(name="Foo.add_zero", module="Foo")

    def test_only_module_prefixes_set(self):
        from Poule.extraction.types import ScopeFilter

        sf = ScopeFilter(name_pattern=None, module_prefixes=["Stdlib.Arith"])

        assert sf.matches(name="Stdlib.Arith.Nat.add", module="Stdlib.Arith.Nat")
        assert not sf.matches(name="Stdlib.Logic.Foo", module="Stdlib.Logic")


# ═══════════════════════════════════════════════════════════════════════════
# 4.3 Benchmark Subset Generation
# ═══════════════════════════════════════════════════════════════════════════


class TestBenchmarkDifficultySplit:
    """Difficulty split: short<=5, medium 6-20, long>20."""

    def test_spec_example_30_50_20(self, tmp_path):
        """Given 100 proofs: 30 short, 50 medium, 20 long."""
        from Poule.extraction.reporting import generate_benchmarks

        records = []
        # 30 short (total_steps 1..5)
        for _ in range(30):
            records.append(_make_extraction_record(total_steps=3))
        # 50 medium (total_steps 6..20)
        for _ in range(50):
            records.append(_make_extraction_record(total_steps=10))
        # 20 long (total_steps > 20)
        for _ in range(20):
            records.append(_make_extraction_record(total_steps=25))

        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "difficulty", output_dir)

        short_path = output_dir / "short.jsonl"
        medium_path = output_dir / "medium.jsonl"
        long_path = output_dir / "long.jsonl"

        assert short_path.exists()
        assert medium_path.exists()
        assert long_path.exists()

        short_count = sum(1 for _ in open(short_path))
        medium_count = sum(1 for _ in open(medium_path))
        long_count = sum(1 for _ in open(long_path))

        assert short_count == 30
        assert medium_count == 50
        assert long_count == 20

    @pytest.mark.parametrize(
        "total_steps,expected_bin",
        [
            (1, "short"),
            (5, "short"),
            (6, "medium"),
            (20, "medium"),
            (21, "long"),
            (100, "long"),
        ],
        ids=["min-short", "max-short", "min-medium", "max-medium", "min-long", "large-long"],
    )
    def test_boundary_classification(self, tmp_path, total_steps, expected_bin):
        from Poule.extraction.reporting import generate_benchmarks

        records = [_make_extraction_record(total_steps=total_steps)]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "difficulty", output_dir)

        output_file = output_dir / f"{expected_bin}.jsonl"
        assert output_file.exists()
        assert sum(1 for _ in open(output_file)) == 1


class TestBenchmarkProjectSplit:
    """Project split groups ExtractionRecords by project_id."""

    def test_one_file_per_project(self, tmp_path):
        from Poule.extraction.reporting import generate_benchmarks

        records = [
            _make_extraction_record(project_id="alpha"),
            _make_extraction_record(project_id="alpha"),
            _make_extraction_record(project_id="beta"),
        ]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "project", output_dir)

        assert (output_dir / "alpha.jsonl").exists()
        assert (output_dir / "beta.jsonl").exists()
        assert sum(1 for _ in open(output_dir / "alpha.jsonl")) == 2
        assert sum(1 for _ in open(output_dir / "beta.jsonl")) == 1


class TestBenchmarkDomainSplit:
    """Domain split classifies by module path prefix heuristic."""

    @pytest.mark.parametrize(
        "module_path,expected_domain",
        [
            ("Stdlib.Arith.PeanoNat", "arithmetic"),
            ("Stdlib.NatDef.Basics", "arithmetic"),
            ("Stdlib.ZArith.Zdiv", "arithmetic"),
            ("Stdlib.Algebra.Ring", "algebra"),
            ("Stdlib.Ring.Theory", "algebra"),
            ("Stdlib.Field.Axioms", "algebra"),
            ("Stdlib.Logic.Classical", "logic"),
            ("Stdlib.Prop.Decidable", "logic"),
            ("Stdlib.Lists.List", "other"),
        ],
        ids=[
            "arith", "nat", "zarith",
            "algebra", "ring", "field",
            "logic", "prop",
            "other",
        ],
    )
    def test_domain_classification(self, tmp_path, module_path, expected_domain):
        from Poule.extraction.reporting import generate_benchmarks

        records = [_make_extraction_record(module_path=module_path)]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "domain", output_dir)

        output_file = output_dir / f"{expected_domain}.jsonl"
        assert output_file.exists()
        assert sum(1 for _ in open(output_file)) == 1

    def test_case_insensitive_matching(self, tmp_path):
        from Poule.extraction.reporting import generate_benchmarks

        records = [_make_extraction_record(module_path="coq.arith.lowered")]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "domain", output_dir)

        assert (output_dir / "arithmetic.jsonl").exists()

    def test_first_match_wins_for_multiple_patterns(self, tmp_path):
        """A proof matching multiple patterns is assigned to the first match."""
        from Poule.extraction.reporting import generate_benchmarks

        # "Arith" matches arithmetic (first), should not also appear in other bins.
        records = [_make_extraction_record(module_path="Stdlib.ArithAlgebra.Foo")]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(input_path, "domain", output_dir)

        assert (output_dir / "arithmetic.jsonl").exists()
        assert sum(1 for _ in open(output_dir / "arithmetic.jsonl")) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 4.4 ML Framework Export
# ═══════════════════════════════════════════════════════════════════════════


class TestExportToHuggingFace:
    """export_to_huggingface preserves all fields and produces loadable dataset."""

    def test_preserves_all_fields(self, tmp_path):
        pytest.importorskip("datasets")
        from Poule.extraction.reporting import export_to_huggingface

        records = [_make_extraction_record(theorem_name="T.foo", total_steps=5)]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "hf_dataset"

        export_to_huggingface(input_path, output_dir)

        # Output directory should exist and contain dataset files.
        assert output_dir.exists()

    def test_loadable_by_datasets_library(self, tmp_path):
        pytest.importorskip("datasets")
        from datasets import load_from_disk

        from Poule.extraction.reporting import export_to_huggingface

        records = [
            _make_extraction_record(theorem_name="A.a", total_steps=2),
            _make_extraction_record(theorem_name="B.b", total_steps=4),
        ]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "hf_dataset"

        export_to_huggingface(input_path, output_dir)

        ds = load_from_disk(str(output_dir))
        assert len(ds) == 2

    def test_field_preservation_round_trip(self, tmp_path):
        pytest.importorskip("datasets")
        from datasets import load_from_disk

        from Poule.extraction.reporting import export_to_huggingface

        records = [_make_extraction_record(theorem_name="X.thm", project_id="proj-x")]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "hf_dataset"

        export_to_huggingface(input_path, output_dir)

        ds = load_from_disk(str(output_dir))
        assert ds[0]["theorem_name"] == "X.thm"
        assert ds[0]["project_id"] == "proj-x"


# ═══════════════════════════════════════════════════════════════════════════
# 4.5 Proof Trace Validation
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateTraces:
    """validate_traces replays tactics and compares states."""

    def test_reports_total_validated_and_failed(self, tmp_path):
        from Poule.extraction.reporting import validate_traces

        records = [_make_extraction_record()]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)

        result = validate_traces(input_path)

        assert hasattr(result, "total_validated")
        assert hasattr(result, "total_failed")
        assert hasattr(result, "failures")

    def test_failure_includes_step_index_and_goals(self, tmp_path):
        from Poule.extraction.reporting import validate_traces

        # We cannot actually replay against Coq in unit tests, so we verify
        # the report structure. A failure entry should contain step_index,
        # expected_goal, and actual_goal.
        records = [_make_extraction_record()]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)

        result = validate_traces(input_path)

        # Structural check: failures list should be iterable.
        assert isinstance(result.failures, list)
        # If there are failures, each should have step_index, expected_goal,
        # actual_goal.
        for failure in result.failures:
            assert hasattr(failure, "step_index")
            assert hasattr(failure, "expected_goal")
            assert hasattr(failure, "actual_goal")


# ═══════════════════════════════════════════════════════════════════════════
# 4.6 Dataset Deduplication
# ═══════════════════════════════════════════════════════════════════════════


class TestDeduplicate:
    """Deduplication by initial goal + tactic sequence after whitespace normalization."""

    def test_identical_goal_and_tactics_clustered(self, tmp_path):
        from Poule.extraction.reporting import deduplicate

        shared_steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "nat = nat"}], "premises": []},
            {"step_index": 1, "tactic": "reflexivity.", "goals": [{"type": ""}], "premises": []},
        ]
        rec_a = _make_extraction_record(
            theorem_name="X.a", project_id="proj-x", total_steps=1, steps=shared_steps,
        )
        rec_b = _make_extraction_record(
            theorem_name="Y.b", project_id="proj-y", total_steps=1, steps=shared_steps,
        )
        input_path = _write_jsonl(tmp_path / "input.jsonl", [rec_a, rec_b])

        report = deduplicate(input_path)

        # Should have at least one cluster containing both theorems.
        assert len(report.clusters) >= 1
        cluster_sizes = [len(c.members) for c in report.clusters]
        assert 2 in cluster_sizes

    def test_different_tactics_not_clustered(self, tmp_path):
        from Poule.extraction.reporting import deduplicate

        steps_a = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "nat = nat"}], "premises": []},
            {"step_index": 1, "tactic": "reflexivity.", "goals": [{"type": ""}], "premises": []},
        ]
        steps_b = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "nat = nat"}], "premises": []},
            {"step_index": 1, "tactic": "auto.", "goals": [{"type": ""}], "premises": []},
        ]
        rec_a = _make_extraction_record(
            theorem_name="X.a", total_steps=1, steps=steps_a,
        )
        rec_b = _make_extraction_record(
            theorem_name="Y.b", total_steps=1, steps=steps_b,
        )
        input_path = _write_jsonl(tmp_path / "input.jsonl", [rec_a, rec_b])

        report = deduplicate(input_path)

        # No cluster should contain both — they should be separate.
        for cluster in report.clusters:
            names = {m.theorem_name for m in cluster.members}
            assert not ({"X.a", "Y.b"} <= names)

    def test_whitespace_normalization(self, tmp_path):
        """Tactic sequences identical after whitespace normalization are clustered."""
        from Poule.extraction.reporting import deduplicate

        steps_a = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []},
            {"step_index": 1, "tactic": "simpl.  ", "goals": [{"type": "g"}], "premises": []},
        ]
        steps_b = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []},
            {"step_index": 1, "tactic": "simpl.", "goals": [{"type": "g"}], "premises": []},
        ]
        rec_a = _make_extraction_record(theorem_name="A", total_steps=1, steps=steps_a)
        rec_b = _make_extraction_record(theorem_name="B", total_steps=1, steps=steps_b)
        input_path = _write_jsonl(tmp_path / "input.jsonl", [rec_a, rec_b])

        report = deduplicate(input_path)

        cluster_sizes = [len(c.members) for c in report.clusters]
        assert 2 in cluster_sizes

    def test_symmetric_and_transitive_clustering(self, tmp_path):
        """If A~B and B~C, then A, B, C are in the same cluster."""
        from Poule.extraction.reporting import deduplicate

        shared_steps = [
            {"step_index": 0, "tactic": "", "goals": [{"type": "T"}], "premises": []},
            {"step_index": 1, "tactic": "auto.", "goals": [{"type": "g"}], "premises": []},
        ]
        records = [
            _make_extraction_record(theorem_name="A", total_steps=1, steps=shared_steps),
            _make_extraction_record(theorem_name="B", total_steps=1, steps=shared_steps),
            _make_extraction_record(theorem_name="C", total_steps=1, steps=shared_steps),
        ]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)

        report = deduplicate(input_path)

        # All three should be in one cluster.
        found = False
        for cluster in report.clusters:
            names = {m.theorem_name for m in cluster.members}
            if {"A", "B", "C"} <= names:
                found = True
                break
        assert found, "A, B, C should be in the same cluster (transitive)"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Error Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorInvalidJsonLines:
    """Invalid JSON Lines raises ValueError with line number."""

    def test_invalid_json_raises_value_error_with_line_number(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        content = '{"record_type": "campaign_metadata"}\n{bad json\n'
        path = tmp_path / "bad.jsonl"
        path.write_text(content)

        with pytest.raises(ValueError, match=r"[Ll]ine\s*2"):
            generate_quality_report(path)


class TestErrorNoExtractionRecords:
    """No ExtractionRecords produces zero metrics."""

    def test_empty_input_returns_zero_metrics(self, tmp_path):
        from Poule.extraction.reporting import generate_quality_report

        path = _write_jsonl(tmp_path / "empty.jsonl", [])

        report = generate_quality_report(path)

        assert report.premise_coverage == 0.0

    def test_empty_input_benchmark_produces_empty_output(self, tmp_path):
        from Poule.extraction.reporting import generate_benchmarks

        path = _write_jsonl(tmp_path / "empty.jsonl", [])
        output_dir = tmp_path / "benchmarks"
        output_dir.mkdir()

        generate_benchmarks(path, "difficulty", output_dir)

        # Files may or may not be created, but should have zero records.
        for name in ["short.jsonl", "medium.jsonl", "long.jsonl"]:
            f = output_dir / name
            if f.exists():
                assert sum(1 for _ in open(f)) == 0


class TestErrorMissingDatasetsLibrary:
    """Missing datasets library raises ImportError with installation instructions."""

    def test_import_error_with_install_instructions(self, tmp_path, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "datasets" or (
                isinstance(name, str) and name.startswith("datasets.")
            ):
                raise ImportError("No module named 'datasets'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from Poule.extraction.reporting import export_to_huggingface

        records = [_make_extraction_record()]
        input_path = _write_jsonl(tmp_path / "input.jsonl", records)
        output_dir = tmp_path / "hf_out"

        with pytest.raises(ImportError, match=r"[Ii]nstall"):
            export_to_huggingface(input_path, output_dir)


# ═══════════════════════════════════════════════════════════════════════════
# 4.7 Extraction Error Analysis
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeErrorsBasicCounts:
    """analyze_errors returns correct total_theorems, total_extracted, total_failed."""

    def test_counts_traces_and_errors(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_record(theorem_name="A.ok1"),
            _make_extraction_record(theorem_name="A.ok2"),
            _make_extraction_error(theorem_name="A.fail1", error_kind="timeout"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.total_extracted == 2
        assert report.total_failed == 1
        assert report.total_theorems == 3

    def test_skips_non_trace_non_error_records(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            {"record_type": "campaign_metadata", "schema_version": 1},
            _make_extraction_record(),
            _make_extraction_error(),
            {"record_type": "extraction_summary", "schema_version": 1},
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.total_theorems == 2  # only trace + error
        assert report.total_extracted == 1
        assert report.total_failed == 1

    def test_multi_file_aggregation(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records_a = [
            _make_extraction_record(theorem_name="A.ok"),
            _make_extraction_error(theorem_name="A.fail", error_kind="timeout"),
        ]
        records_b = [
            _make_extraction_record(theorem_name="B.ok"),
            _make_extraction_error(theorem_name="B.fail", error_kind="tactic_failure"),
        ]
        path_a = _write_jsonl(tmp_path / "a.jsonl", records_a)
        path_b = _write_jsonl(tmp_path / "b.jsonl", records_b)

        report = analyze_errors([path_a, path_b])

        assert report.files_analyzed == 2
        assert report.total_theorems == 4
        assert report.total_extracted == 2
        assert report.total_failed == 2

    def test_files_analyzed_equals_path_count(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        for name in ["x.jsonl", "y.jsonl", "z.jsonl"]:
            _write_jsonl(tmp_path / name, [_make_extraction_record()])

        paths = [tmp_path / name for name in ["x.jsonl", "y.jsonl", "z.jsonl"]]
        report = analyze_errors(paths)

        assert report.files_analyzed == 3


class TestAnalyzeErrorsByKind:
    """Errors aggregated by error_kind with correct counts."""

    def test_aggregates_distinct_error_kinds(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_error(error_kind="timeout"),
            _make_extraction_error(error_kind="timeout"),
            _make_extraction_error(error_kind="timeout"),
            _make_extraction_error(error_kind="tactic_failure"),
            _make_extraction_error(error_kind="tactic_failure"),
            _make_extraction_error(error_kind="load_failure"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.by_error_kind == {
            "timeout": 3,
            "tactic_failure": 2,
            "load_failure": 1,
        }

    def test_sum_equals_total_failed(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_error(error_kind="timeout"),
            _make_extraction_error(error_kind="backend_crash"),
            _make_extraction_error(error_kind="unknown"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert sum(report.by_error_kind.values()) == report.total_failed

    def test_no_errors_returns_empty_dict(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [_make_extraction_record()]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.by_error_kind == {}
        assert report.total_failed == 0


class TestAnalyzeErrorsByFile:
    """Errors aggregated by source_file, sorted by error_count descending."""

    def test_sorted_by_error_count_descending(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_error(source_file="A.v", error_kind="timeout"),
            _make_extraction_error(source_file="B.v", error_kind="timeout"),
            _make_extraction_error(source_file="B.v", error_kind="tactic_failure"),
            _make_extraction_error(source_file="B.v", error_kind="timeout"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert len(report.by_file) == 2
        assert report.by_file[0].source_file == "B.v"
        assert report.by_file[0].error_count == 3
        assert report.by_file[1].source_file == "A.v"
        assert report.by_file[1].error_count == 1

    def test_per_file_by_kind_breakdown(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_error(source_file="Reals/R.v", error_kind="timeout"),
            _make_extraction_error(source_file="Reals/R.v", error_kind="timeout"),
            _make_extraction_error(source_file="Reals/R.v", error_kind="tactic_failure"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.by_file[0].by_kind == {"timeout": 2, "tactic_failure": 1}

    def test_ties_broken_by_filename_ascending(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_extraction_error(source_file="Z.v", error_kind="timeout"),
            _make_extraction_error(source_file="A.v", error_kind="timeout"),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        # Both have 1 error, tie broken by filename ascending
        assert report.by_file[0].source_file == "A.v"
        assert report.by_file[1].source_file == "Z.v"

    def test_no_errors_returns_empty_list(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [_make_extraction_record()]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.by_file == []


class TestAnalyzeErrorsNearTimeout:
    """Near-timeout: successful proofs within 10% of timeout threshold."""

    def test_proof_above_threshold_is_near_timeout(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        # timeout=60, threshold=54.0s; total duration = 55.0s
        records = [
            _make_timed_extraction_record(
                theorem_name="Near.proof",
                step_durations_ms=[20000, 15000, 20000],  # total 55s
            ),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path], timeout_threshold=60)

        assert len(report.near_timeout) == 1
        assert report.near_timeout[0].theorem_name == "Near.proof"
        assert report.near_timeout[0].total_duration_s == pytest.approx(55.0)

    def test_proof_below_threshold_not_near_timeout(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        # timeout=60, threshold=54.0s; total duration = 53.0s
        records = [
            _make_timed_extraction_record(
                theorem_name="Fast.proof",
                step_durations_ms=[20000, 13000, 20000],  # total 53s
            ),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path], timeout_threshold=60)

        assert len(report.near_timeout) == 0

    def test_near_timeout_sorted_by_duration_descending(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_timed_extraction_record(
                theorem_name="Slow",
                step_durations_ms=[30000, 28000],  # 58s
            ),
            _make_timed_extraction_record(
                theorem_name="Medium",
                step_durations_ms=[27000, 28000],  # 55s
            ),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path], timeout_threshold=60)

        assert len(report.near_timeout) == 2
        assert report.near_timeout[0].theorem_name == "Slow"
        assert report.near_timeout[1].theorem_name == "Medium"

    def test_no_timing_data_returns_empty_list(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        # Records without duration_ms fields
        records = [_make_extraction_record()]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.near_timeout == []

    def test_default_timeout_threshold_is_60(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [_make_extraction_record()]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.timeout_threshold == 60


class TestAnalyzeErrorsSlowestSuccessful:
    """Top-20 slowest successful extractions by total duration."""

    def test_returns_top_20_slowest(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = []
        for i in range(25):
            records.append(
                _make_timed_extraction_record(
                    theorem_name=f"T.t{i}",
                    step_durations_ms=[i * 1000],  # 0s, 1s, ..., 24s
                )
            )
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert len(report.slowest_successful) == 20
        # Fastest excluded should be 0..4s (5 records)
        assert report.slowest_successful[0].total_duration_s == pytest.approx(24.0)
        assert report.slowest_successful[-1].total_duration_s == pytest.approx(5.0)

    def test_fewer_than_20_returns_all(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_timed_extraction_record(
                theorem_name="Only.one",
                step_durations_ms=[5000],
            ),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert len(report.slowest_successful) == 1

    def test_sorted_by_duration_descending(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [
            _make_timed_extraction_record(theorem_name="Fast", step_durations_ms=[1000]),
            _make_timed_extraction_record(theorem_name="Slow", step_durations_ms=[10000]),
            _make_timed_extraction_record(theorem_name="Mid", step_durations_ms=[5000]),
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        names = [e.theorem_name for e in report.slowest_successful]
        assert names == ["Slow", "Mid", "Fast"]


class TestAnalyzeErrorsEdgeCases:
    """Edge cases: zero errors, all errors, single file."""

    def test_all_successful_no_errors(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [_make_extraction_record() for _ in range(5)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.total_failed == 0
        assert report.by_error_kind == {}
        assert report.by_file == []

    def test_all_errors_no_successes(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        records = [_make_extraction_error() for _ in range(5)]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.total_extracted == 0
        assert report.total_failed == 5
        assert report.near_timeout == []
        assert report.slowest_successful == []

    def test_empty_file(self, tmp_path):
        from Poule.extraction.reporting import analyze_errors

        path = _write_jsonl(tmp_path / "empty.jsonl", [])

        report = analyze_errors([path])

        assert report.total_theorems == 0
        assert report.total_extracted == 0
        assert report.total_failed == 0


# ═══════════════════════════════════════════════════════════════════════════
# Streaming behavior (§6/§8)
# ═══════════════════════════════════════════════════════════════════════════


class TestIterJsonlStreaming:
    """_iter_jsonl yields records one at a time without loading all into memory."""

    def test_iter_jsonl_is_generator(self, tmp_path):
        """_iter_jsonl returns a generator, not a list."""
        from Poule.extraction.reporting import _iter_jsonl
        from collections.abc import Generator

        records = [_make_extraction_record() for _ in range(3)]
        path = _write_jsonl(tmp_path / "test.jsonl", records)

        result = _iter_jsonl(path)
        assert isinstance(result, Generator)
        # Consume and verify count
        items = list(result)
        assert len(items) == 3

    def test_iter_jsonl_raises_on_bad_json(self, tmp_path):
        """_iter_jsonl raises ValueError with line number on invalid JSON."""
        from Poule.extraction.reporting import _iter_jsonl

        path = tmp_path / "bad.jsonl"
        path.write_text('{"ok": true}\nnot json\n')

        gen = _iter_jsonl(path)
        next(gen)  # first line is fine
        with pytest.raises(ValueError, match="Line 2"):
            next(gen)


class TestAnalyzeErrorsStreaming:
    """analyze_errors processes files without bulk-loading (§6/§8)."""

    def test_produces_correct_results_via_streaming(self, tmp_path):
        """Streaming analyze_errors produces identical results to what the
        old bulk-load version would produce."""
        from Poule.extraction.reporting import analyze_errors

        records = (
            [_make_extraction_record(theorem_name=f"T.thm{i}") for i in range(5)]
            + [_make_extraction_error(theorem_name=f"T.fail{i}") for i in range(3)]
        )
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = analyze_errors([path])

        assert report.total_extracted == 5
        assert report.total_failed == 3
        assert report.total_theorems == 8


class TestGenerateQualityReportStreaming:
    """generate_quality_report uses streaming reads (§6/§8)."""

    def test_produces_correct_results_via_streaming(self, tmp_path):
        """Streaming quality report produces correct metrics."""
        from Poule.extraction.reporting import generate_quality_report

        records = [
            _make_extraction_record(theorem_name="T.a", total_steps=3),
            _make_extraction_record(theorem_name="T.b", total_steps=5),
            _make_extraction_error(),  # should be skipped
        ]
        path = _write_jsonl(tmp_path / "output.jsonl", records)

        report = generate_quality_report(path)

        assert report.proof_length_distribution.min == 3
        assert report.proof_length_distribution.max == 5
        assert len(report.per_project) == 1
        assert report.per_project[0].theorem_count == 2
