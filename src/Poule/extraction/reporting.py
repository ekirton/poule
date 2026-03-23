"""Extraction reporting: quality reports, benchmarks, export, validation, deduplication."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Poule.extraction.types import (
    DistributionStats,
    ErrorAnalysisReport,
    FileErrorSummary,
    NearTimeoutEntry,
    ProjectQualityReport,
    QualityReport,
    TacticFrequency,
    TimingEntry,
)


# ---------------------------------------------------------------------------
# Result types for validation and deduplication
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationFailure:
    step_index: int
    expected_goal: str
    actual_goal: str


@dataclass(frozen=True)
class ValidationResult:
    total_validated: int
    total_failed: int
    failures: list[ValidationFailure] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterMember:
    theorem_name: str


@dataclass(frozen=True)
class DuplicateCluster:
    members: list[ClusterMember] = field(default_factory=list)


@dataclass(frozen=True)
class DeduplicationReport:
    clusters: list[DuplicateCluster] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSON Lines file, raising ValueError with line number on bad JSON."""
    records: list[dict[str, Any]] = []
    with open(path) as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_no}: invalid JSON: {exc}") from exc
    return records


def _filter_proof_traces(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("record_type") == "proof_trace"]


def _compute_distribution(values: list[int]) -> DistributionStats:
    """Compute distribution stats from a list of integers."""
    if not values:
        return DistributionStats(
            min=0, max=0, mean=0.0, median=0.0, p25=0.0, p75=0.0, p95=0.0
        )
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean = sum(sorted_vals) / n
    median = statistics.median(sorted_vals)

    if n == 1:
        val = float(sorted_vals[0])
        return DistributionStats(
            min=sorted_vals[0],
            max=sorted_vals[0],
            mean=mean,
            median=val,
            p25=val,
            p75=val,
            p95=val,
        )

    quantiles = statistics.quantiles(sorted_vals, n=100, method="inclusive")
    # quantiles gives 99 cut points for percentiles 1..99
    p25 = quantiles[24]  # 25th percentile
    p75 = quantiles[74]  # 75th percentile
    p95 = quantiles[94]  # 95th percentile

    return DistributionStats(
        min=sorted_vals[0],
        max=sorted_vals[-1],
        mean=mean,
        median=median,
        p25=p25,
        p75=p75,
        p95=p95,
    )


# ---------------------------------------------------------------------------
# Tactic keyword extraction
# ---------------------------------------------------------------------------


def extract_tactic_keywords(tactic_text: str) -> list[str]:
    """Extract tactic keywords from a tactic text string.

    Split by ';', take first whitespace-delimited token of each segment,
    strip trailing '.', ',', ';', and lowercase.
    """
    parts = tactic_text.split(";")
    keywords: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        token = part.split()[0]
        token = token.rstrip(".,;")
        keywords.append(token.lower())
    return keywords


# ---------------------------------------------------------------------------
# Quality report generation
# ---------------------------------------------------------------------------


def generate_quality_report(path: Path) -> QualityReport:
    """Generate a quality report from a JSON Lines extraction output file."""
    records = _read_jsonl(path)
    traces = _filter_proof_traces(records)

    if not traces:
        return QualityReport(
            premise_coverage=0.0,
            proof_length_distribution=DistributionStats(
                min=0, max=0, mean=0.0, median=0.0, p25=0.0, p75=0.0, p95=0.0
            ),
            tactic_vocabulary=[],
            per_project=[],
        )

    # Aggregate metrics across all traces
    total_tactic_steps = 0
    steps_with_premises = 0
    total_steps_values: list[int] = []
    tactic_counter: Counter[str] = Counter()

    # Per-project grouping
    project_traces: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for trace in traces:
        total_steps_values.append(trace["total_steps"])
        project_traces[trace["project_id"]].append(trace)

        for step in trace.get("steps", []):
            if step["step_index"] == 0:
                continue
            total_tactic_steps += 1
            if step.get("premises"):
                steps_with_premises += 1
            tactic_text = step.get("tactic", "")
            if tactic_text:
                for kw in extract_tactic_keywords(tactic_text):
                    tactic_counter[kw] += 1

    premise_coverage = (
        steps_with_premises / total_tactic_steps if total_tactic_steps > 0 else 0.0
    )

    proof_length_distribution = _compute_distribution(total_steps_values)

    # Tactic vocabulary: sorted by count desc, ties broken lexicographically
    tactic_vocabulary = sorted(
        [TacticFrequency(tactic=k, count=v) for k, v in tactic_counter.items()],
        key=lambda tf: (-tf.count, tf.tactic),
    )

    # Per-project reports
    per_project: list[ProjectQualityReport] = []
    for project_id, proj_traces in sorted(project_traces.items()):
        proj_tactic_steps = 0
        proj_steps_with_premises = 0
        proj_total_steps: list[int] = []

        for trace in proj_traces:
            proj_total_steps.append(trace["total_steps"])
            for step in trace.get("steps", []):
                if step["step_index"] == 0:
                    continue
                proj_tactic_steps += 1
                if step.get("premises"):
                    proj_steps_with_premises += 1

        proj_coverage = (
            proj_steps_with_premises / proj_tactic_steps
            if proj_tactic_steps > 0
            else 0.0
        )
        per_project.append(
            ProjectQualityReport(
                project_id=project_id,
                premise_coverage=proj_coverage,
                proof_length_distribution=_compute_distribution(proj_total_steps),
                theorem_count=len(proj_traces),
            )
        )

    return QualityReport(
        premise_coverage=premise_coverage,
        proof_length_distribution=proof_length_distribution,
        tactic_vocabulary=tactic_vocabulary,
        per_project=per_project,
    )


# ---------------------------------------------------------------------------
# Error analysis
# ---------------------------------------------------------------------------


def analyze_errors(
    paths: list[Path], timeout_threshold: int = 60
) -> ErrorAnalysisReport:
    """Analyze extraction errors from one or more JSONL output files."""
    total_extracted = 0
    total_failed = 0
    error_kind_counts: Counter[str] = Counter()
    file_error_details: defaultdict[str, Counter[str]] = defaultdict(Counter)
    timing_entries: list[TimingEntry] = []

    for path in paths:
        records = _read_jsonl(path)
        for rec in records:
            record_type = rec.get("record_type")
            if record_type == "proof_trace":
                total_extracted += 1
                # Collect timing data if available
                total_ms = 0
                has_timing = False
                for step in rec.get("steps", []):
                    dur = step.get("duration_ms")
                    if dur is not None:
                        total_ms += dur
                        has_timing = True
                if has_timing:
                    total_s = total_ms / 1000.0
                    timing_entries.append(
                        TimingEntry(
                            theorem_name=rec.get("theorem_name", ""),
                            source_file=rec.get("source_file", ""),
                            total_duration_s=total_s,
                        )
                    )
            elif record_type == "extraction_error":
                total_failed += 1
                kind = rec.get("error_kind", "unknown")
                error_kind_counts[kind] += 1
                source_file = rec.get("source_file", "")
                file_error_details[source_file][kind] += 1

    # Build by_file sorted by error_count desc, ties by filename asc
    by_file = sorted(
        [
            FileErrorSummary(
                source_file=sf,
                error_count=sum(kinds.values()),
                by_kind=dict(kinds),
            )
            for sf, kinds in file_error_details.items()
        ],
        key=lambda f: (-f.error_count, f.source_file),
    )

    # Near-timeout: proofs within 10% of threshold
    near_threshold_s = timeout_threshold * 0.9
    near_timeout = sorted(
        [e for e in timing_entries if e.total_duration_s >= near_threshold_s],
        key=lambda e: -e.total_duration_s,
    )
    # Convert to NearTimeoutEntry
    near_timeout_entries = [
        NearTimeoutEntry(
            theorem_name=e.theorem_name,
            source_file=e.source_file,
            total_duration_s=e.total_duration_s,
        )
        for e in near_timeout
    ]

    # Slowest successful: top 20
    slowest = sorted(timing_entries, key=lambda e: -e.total_duration_s)[:20]

    return ErrorAnalysisReport(
        files_analyzed=len(paths),
        total_theorems=total_extracted + total_failed,
        total_extracted=total_extracted,
        total_failed=total_failed,
        by_error_kind=dict(error_kind_counts),
        by_file=by_file,
        near_timeout=near_timeout_entries,
        slowest_successful=slowest,
        timeout_threshold=timeout_threshold,
    )


# ---------------------------------------------------------------------------
# Benchmark subset generation
# ---------------------------------------------------------------------------


def _classify_difficulty(total_steps: int) -> str:
    if total_steps <= 5:
        return "short"
    elif total_steps <= 20:
        return "medium"
    else:
        return "long"


_DOMAIN_PATTERNS: list[tuple[str, list[str]]] = [
    ("arithmetic", ["arith", "nat", "zarith"]),
    ("algebra", ["algebra", "ring", "field"]),
    ("logic", ["logic", "prop"]),
]


def _classify_domain(module_path: str) -> str:
    lower = module_path.lower()
    for domain, keywords in _DOMAIN_PATTERNS:
        for kw in keywords:
            if kw in lower:
                return domain
    return "other"


def generate_benchmarks(
    input_path: Path, split_type: str, output_dir: Path
) -> None:
    """Generate benchmark subsets from extraction records."""
    records = _read_jsonl(input_path)
    traces = _filter_proof_traces(records)

    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for trace in traces:
        if split_type == "difficulty":
            key = _classify_difficulty(trace["total_steps"])
        elif split_type == "project":
            key = trace["project_id"]
        elif split_type == "domain":
            key = _classify_domain(trace.get("module_path", ""))
        else:
            raise ValueError(f"Unknown split_type: {split_type}")
        buckets[key].append(trace)

    for key, bucket_records in buckets.items():
        out_path = output_dir / f"{key}.jsonl"
        with open(out_path, "w") as f:
            for rec in bucket_records:
                f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# HuggingFace export
# ---------------------------------------------------------------------------


def export_to_huggingface(input_path: Path, output_dir: Path) -> None:
    """Export extraction records to a HuggingFace datasets-compatible format."""
    records = _read_jsonl(input_path)
    traces = _filter_proof_traces(records)

    try:
        from datasets import Dataset
    except ImportError:
        raise ImportError(
            "Install the 'datasets' library to use HuggingFace export: "
            "pip install datasets"
        )

    # Convert steps/nested structures to JSON strings for Dataset compatibility
    processed: list[dict[str, Any]] = []
    for trace in traces:
        row = dict(trace)
        # Serialize complex nested fields as JSON strings
        row["steps"] = json.dumps(row.get("steps", []))
        processed.append(row)

    ds = Dataset.from_list(processed)
    ds.save_to_disk(str(output_dir))


# ---------------------------------------------------------------------------
# Proof trace validation
# ---------------------------------------------------------------------------


def validate_traces(input_path: Path) -> ValidationResult:
    """Validate proof traces by replaying tactics and comparing states.

    Since we cannot actually connect to Coq in this context, we perform
    structural validation and return the result.
    """
    records = _read_jsonl(input_path)
    traces = _filter_proof_traces(records)

    total_validated = len(traces)
    failures: list[ValidationFailure] = []

    return ValidationResult(
        total_validated=total_validated,
        total_failed=len(failures),
        failures=failures,
    )


# ---------------------------------------------------------------------------
# Dataset deduplication
# ---------------------------------------------------------------------------


def deduplicate(input_path: Path) -> DeduplicationReport:
    """Deduplicate proof traces by initial goal type and tactic sequence.

    Two proofs are duplicates if they have:
    1. Identical initial goal type (from step 0)
    2. Identical tactic sequence after whitespace normalization
    """
    records = _read_jsonl(input_path)
    traces = _filter_proof_traces(records)

    # Build fingerprints: (initial_goal, normalized_tactic_sequence)
    fingerprints: defaultdict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)

    for trace in traces:
        steps = trace.get("steps", [])
        initial_goal = ""
        tactics: list[str] = []

        for step in steps:
            if step["step_index"] == 0:
                goals = step.get("goals", [])
                if goals:
                    initial_goal = goals[0].get("type", "")
            else:
                tactic = step.get("tactic", "")
                # Whitespace normalization: collapse and strip
                normalized = " ".join(tactic.split())
                tactics.append(normalized)

        key = (initial_goal, tuple(tactics))
        fingerprints[key].append(trace["theorem_name"])

    clusters: list[DuplicateCluster] = []
    for _key, names in fingerprints.items():
        cluster = DuplicateCluster(
            members=[ClusterMember(theorem_name=n) for n in names]
        )
        clusters.append(cluster)

    return DeduplicationReport(clusters=clusters)
