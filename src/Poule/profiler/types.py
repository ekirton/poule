"""Data model types for the Proof Profiling Engine.

Spec: specification/proof-profiling.md, Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Union


@dataclass
class ProfileRequest:
    """Input to the profiling engine."""

    file_path: str
    lemma_name: Optional[str] = None
    mode: str = "timing"  # "timing", "ltac", or "compare"
    baseline_path: Optional[str] = None
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            self.timeout_seconds = 1
        if self.timeout_seconds > 3600:
            self.timeout_seconds = 3600


@dataclass
class TimingSentence:
    """One sentence from coqc -time output, enriched with source metadata."""

    char_start: int
    char_end: int
    line_number: int = 1
    snippet: str = ""
    real_time_s: float = 0.0
    user_time_s: float = 0.0
    sys_time_s: float = 0.0
    sentence_kind: str = "Other"  # Import, Definition, ProofOpen, ProofClose, Tactic, Other
    containing_proof: Optional[str] = None


@dataclass
class ProofProfile:
    """Timing for a single proof, aggregated from constituent sentences."""

    lemma_name: str
    line_number: int = 1
    tactic_sentences: List[TimingSentence] = field(default_factory=list)
    proof_close: Optional[TimingSentence] = None
    tactic_time_s: float = 0.0
    close_time_s: float = 0.0
    total_time_s: float = 0.0
    bottlenecks: List[BottleneckClassification] = field(default_factory=list)


@dataclass
class FileProfile:
    """Timing for an entire .v file."""

    file_path: str
    sentences: List[TimingSentence] = field(default_factory=list)
    proofs: List[ProofProfile] = field(default_factory=list)
    total_time_s: float = 0.0
    compilation_succeeded: bool = True
    error_message: Optional[str] = None


@dataclass
class LtacProfileEntry:
    """One row from Show Ltac Profile output."""

    tactic_name: str
    local_pct: float = 0.0
    total_pct: float = 0.0
    calls: int = 1
    max_time_s: float = 0.0


@dataclass
class LtacProfile:
    """Complete Ltac profiling result for a single proof."""

    lemma_name: str = ""
    total_time_s: float = 0.0
    entries: List[LtacProfileEntry] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    bottlenecks: List[BottleneckClassification] = field(default_factory=list)


@dataclass
class BottleneckClassification:
    """A classified performance bottleneck."""

    rank: int
    category: str  # SlowQed, SlowReduction, TypeclassBlowup, HighSearchDepth, ExpensiveMatch, General
    sentence: Any = None  # TimingSentence or LtacProfileEntry
    severity: str = "info"  # critical, warning, info
    suggestion_hints: List[str] = field(default_factory=list)


@dataclass
class TimingDiff:
    """One sentence's timing change between two profiling runs."""

    sentence_snippet: str
    line_before: int = 0
    line_after: Optional[int] = None
    time_before_s: float = 0.0
    time_after_s: Optional[float] = None
    delta_s: float = 0.0
    delta_pct: Optional[float] = None
    status: str = "stable"  # improved, regressed, stable, new, removed


@dataclass
class TimingComparison:
    """Result of comparing two profiling runs."""

    file_path: str = ""
    baseline_total_s: float = 0.0
    current_total_s: float = 0.0
    net_delta_s: float = 0.0
    diffs: List[TimingDiff] = field(default_factory=list)
    regressions: List[TimingDiff] = field(default_factory=list)
    improvements: List[TimingDiff] = field(default_factory=list)


@dataclass
class ProofBoundary:
    """A proof boundary detected from source text."""

    name: str
    decl_char_start: int
    close_char_end: int
