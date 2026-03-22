"""TDD tests for the Proof Profiling Engine (specification/proof-profiling.md).

Tests cover all pure functions and data model types. Engine tests requiring
async subprocess mocking are in test_profiler_engine.py.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Lazy import helpers (TDD pattern: tests importable before impl exists)
# ---------------------------------------------------------------------------

def _import_types():
    from Poule.profiler.types import (
        BottleneckClassification,
        FileProfile,
        LtacProfile,
        LtacProfileEntry,
        ProfileRequest,
        ProofBoundary,
        ProofProfile,
        TimingComparison,
        TimingDiff,
        TimingSentence,
    )
    return (
        BottleneckClassification,
        FileProfile,
        LtacProfile,
        LtacProfileEntry,
        ProfileRequest,
        ProofBoundary,
        ProofProfile,
        TimingComparison,
        TimingDiff,
        TimingSentence,
    )


def _import_parser():
    from Poule.profiler.parser import parse_timing_output, parse_ltac_profile
    return parse_timing_output, parse_ltac_profile


def _import_boundaries():
    from Poule.profiler.boundaries import (
        classify_sentence,
        detect_proof_boundaries,
        resolve_line_numbers,
    )
    return classify_sentence, detect_proof_boundaries, resolve_line_numbers


def _import_bottleneck():
    from Poule.profiler.bottleneck import classify_bottlenecks
    return classify_bottlenecks


def _import_comparison():
    from Poule.profiler.comparison import match_sentences
    return match_sentences


def _import_engine():
    from Poule.profiler.engine import validate_request, locate_coqc, resolve_paths
    return validate_request, locate_coqc, resolve_paths


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_timing_sentence(
    char_start=0,
    char_end=10,
    snippet="[auto.]",
    real_time_s=0.1,
    user_time_s=0.1,
    sys_time_s=0.0,
    sentence_kind="Tactic",
    containing_proof=None,
    line_number=1,
):
    _, _, _, _, _, _, _, _, _, TimingSentence = _import_types()
    return TimingSentence(
        char_start=char_start,
        char_end=char_end,
        snippet=snippet,
        real_time_s=real_time_s,
        user_time_s=user_time_s,
        sys_time_s=sys_time_s,
        sentence_kind=sentence_kind,
        containing_proof=containing_proof,
        line_number=line_number,
    )


def _make_ltac_entry(
    tactic_name="auto",
    local_pct=50.0,
    total_pct=50.0,
    calls=10,
    max_time_s=0.5,
):
    _, _, _, LtacProfileEntry, *_ = _import_types()
    return LtacProfileEntry(
        tactic_name=tactic_name,
        local_pct=local_pct,
        total_pct=total_pct,
        calls=calls,
        max_time_s=max_time_s,
    )


# ===================================================================
# Section 5: Data Model Types
# ===================================================================


class TestProfileRequest:
    """ProfileRequest — input validation and timeout clamping."""

    def test_default_values(self):
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/test.v")
        assert req.mode == "timing"
        assert req.lemma_name is None
        assert req.baseline_path is None
        assert req.timeout_seconds == 300

    def test_timeout_clamped_below_minimum(self):
        """Spec 7.1: timeout_seconds < 1 → clamp to 1."""
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/test.v", timeout_seconds=0)
        assert req.timeout_seconds == 1

    def test_timeout_clamped_above_maximum(self):
        """Spec 7.1: timeout_seconds > 3600 → clamp to 3600."""
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/test.v", timeout_seconds=9999)
        assert req.timeout_seconds == 3600

    def test_timeout_negative_clamped(self):
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/test.v", timeout_seconds=-5)
        assert req.timeout_seconds == 1

    def test_timeout_within_range_unchanged(self):
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/test.v", timeout_seconds=60)
        assert req.timeout_seconds == 60


class TestTimingSentence:
    """TimingSentence — core timing record."""

    def test_default_sentence_kind_is_other(self):
        _, _, _, _, _, _, _, _, _, TimingSentence = _import_types()
        s = TimingSentence(char_start=0, char_end=10)
        assert s.sentence_kind == "Other"

    def test_containing_proof_default_none(self):
        _, _, _, _, _, _, _, _, _, TimingSentence = _import_types()
        s = TimingSentence(char_start=0, char_end=10)
        assert s.containing_proof is None


class TestProofProfile:
    """ProofProfile — per-proof timing aggregation."""

    def test_empty_profile(self):
        _, _, _, _, _, _, ProofProfile, _, _, _ = _import_types()
        pp = ProofProfile(lemma_name="foo")
        assert pp.tactic_time_s == 0.0
        assert pp.close_time_s == 0.0
        assert pp.total_time_s == 0.0
        assert pp.bottlenecks == []
        assert pp.tactic_sentences == []
        assert pp.proof_close is None


# ===================================================================
# Section 4.5: Timing Output Parsing
# ===================================================================


class TestParseTimingOutput:
    """parse_timing_output — Spec 4.5."""

    def test_single_line(self):
        """Given timing text for one sentence, return one TimingSentence."""
        parse_timing_output, _ = _import_parser()
        text = 'Chars 0 - 26 [Require~Coq.ZArith.BinInt.] 0.157 secs (0.128u,0.028s)'
        result = parse_timing_output(text)
        assert len(result) == 1
        s = result[0]
        assert s.char_start == 0
        assert s.char_end == 26
        assert s.snippet == "[Require~Coq.ZArith.BinInt.]"
        assert s.real_time_s == pytest.approx(0.157)
        assert s.user_time_s == pytest.approx(0.128)
        assert s.sys_time_s == pytest.approx(0.028)

    def test_empty_input(self):
        """Given empty text, return empty list."""
        parse_timing_output, _ = _import_parser()
        assert parse_timing_output("") == []

    def test_non_matching_lines_skipped(self):
        """Lines not matching the timing regex are skipped."""
        parse_timing_output, _ = _import_parser()
        text = "some random line\nChars 0 - 10 [auto.] 1.000 secs (0.900u,0.100s)\nmore noise"
        result = parse_timing_output(text)
        assert len(result) == 1
        assert result[0].char_start == 0

    def test_multiple_lines_sorted_by_char_start(self):
        """Results are returned in source order (ascending char_start)."""
        parse_timing_output, _ = _import_parser()
        text = (
            "Chars 100 - 110 [Qed.] 5.000 secs (4.800u,0.200s)\n"
            "Chars 0 - 26 [Require~Import~Arith.] 0.120 secs (0.110u,0.010s)\n"
            "Chars 50 - 60 [auto.] 0.050 secs (0.050u,0.000s)\n"
        )
        result = parse_timing_output(text)
        assert len(result) == 3
        assert result[0].char_start == 0
        assert result[1].char_start == 50
        assert result[2].char_start == 100

    def test_truncated_final_line_skipped(self):
        """Truncated final lines from timeout are skipped."""
        parse_timing_output, _ = _import_parser()
        text = "Chars 0 - 10 [auto.] 1.000 secs (0.900u,0.100s)\nChars 20 - 30 [sim"
        result = parse_timing_output(text)
        assert len(result) == 1


# ===================================================================
# Section 4.11: Ltac Profile Parsing
# ===================================================================


class TestParseLtacProfile:
    """parse_ltac_profile — Spec 4.11."""

    def test_empty_input(self):
        """Empty input returns profile with caveat."""
        _, parse_ltac_profile = _import_parser()
        result = parse_ltac_profile("")
        assert result.total_time_s == 0.0
        assert result.entries == []
        assert len(result.caveats) > 0

    def test_parses_total_time(self):
        _, parse_ltac_profile = _import_parser()
        text = (
            "total time: 2.500s\n"
            "\n"
            " tactic                    local  total   calls       max\n"
            "────────────────────────────────┴──────┴──────┴───────┴─────────┘\n"
            "─omega ------------------- 45.0%  45.0%      12    0.200s\n"
        )
        result = parse_ltac_profile(text)
        assert result.total_time_s == pytest.approx(2.5)

    def test_parses_entries(self):
        _, parse_ltac_profile = _import_parser()
        text = (
            "total time: 3.200s\n"
            "\n"
            " tactic                    local  total   calls       max\n"
            "────────────────────────────────┴──────┴──────┴───────┴─────────┘\n"
            "─omega ------------------- 45.0%  45.0%      12    0.200s\n"
            "─eauto ------------------- 30.0%  30.0%       8    0.300s\n"
        )
        result = parse_ltac_profile(text)
        assert len(result.entries) == 2
        # Sorted by total_pct descending
        assert result.entries[0].tactic_name == "omega"
        assert result.entries[0].total_pct == pytest.approx(45.0)
        assert result.entries[0].calls == 12
        assert result.entries[0].max_time_s == pytest.approx(0.2)
        assert result.entries[1].tactic_name == "eauto"

    def test_detects_backtracking_caveat(self):
        """Detects 'may be inaccurate' warning."""
        _, parse_ltac_profile = _import_parser()
        text = (
            "total time: 1.000s\n"
            "\n"
            "─auto -------------------- 50.0%  50.0%       5    0.100s\n"
            "\n"
            "Warning: Ltac profiler encountered backtracking into a tactic;\n"
            "profiling results may be inaccurate.\n"
        )
        result = parse_ltac_profile(text)
        assert any("inaccurate" in c for c in result.caveats)
        assert any("#12196" in c for c in result.caveats)

    def test_no_caveat_when_clean(self):
        _, parse_ltac_profile = _import_parser()
        text = (
            "total time: 1.000s\n"
            "\n"
            "─auto -------------------- 50.0%  50.0%       5    0.100s\n"
        )
        result = parse_ltac_profile(text)
        assert result.caveats == []

    def test_entries_sorted_by_total_pct_descending(self):
        _, parse_ltac_profile = _import_parser()
        text = (
            "total time: 2.000s\n"
            "\n"
            "─intro -------------------  5.0%   5.0%      10    0.001s\n"
            "─omega ------------------- 80.0%  80.0%       3    0.500s\n"
            "─simpl ------------------- 15.0%  15.0%      20    0.050s\n"
        )
        result = parse_ltac_profile(text)
        assert result.entries[0].tactic_name == "omega"
        assert result.entries[1].tactic_name == "simpl"
        assert result.entries[2].tactic_name == "intro"


# ===================================================================
# Section 4.7: Proof Boundary Detection
# ===================================================================


class TestDetectProofBoundaries:
    """detect_proof_boundaries — Spec 4.7."""

    def test_simple_lemma(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Lemma foo : True.\nProof.\nexact I.\nQed.\n"
        result = detect_proof_boundaries(source)
        assert len(result) == 1
        assert result[0].name == "foo"
        assert result[0].decl_char_start == 0
        # close_char_end should be past the Qed.
        assert result[0].close_char_end > source.index("Qed")

    def test_definition_without_proof_body(self):
        """Definitions without proof body produce no boundary."""
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Definition x := 5.\nLemma bar : False -> True.\nProof.\nintro H. exact I.\nQed.\n"
        result = detect_proof_boundaries(source)
        # x has no proof body (no closer before next decl), so only bar
        names = [b.name for b in result]
        assert "bar" in names
        # x may or may not appear depending on impl — but should NOT have a boundary
        # if it does, it should not include Qed from bar
        for b in result:
            if b.name == "x":
                # The boundary for x should not extend past bar's declaration
                assert False, "Definition x := 5. should not produce a boundary"

    def test_multiple_proofs(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = (
            "Lemma a : True. Proof. exact I. Qed.\n"
            "Lemma b : True. Proof. exact I. Qed.\n"
        )
        result = detect_proof_boundaries(source)
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_theorem_keyword(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Theorem my_thm : True.\nProof.\nexact I.\nQed.\n"
        result = detect_proof_boundaries(source)
        assert len(result) == 1
        assert result[0].name == "my_thm"

    def test_defined_closer(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Definition foo : nat. exact 0. Defined.\n"
        result = detect_proof_boundaries(source)
        assert len(result) == 1
        assert result[0].name == "foo"

    def test_admitted_closer(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Lemma todo : False. Admitted.\n"
        result = detect_proof_boundaries(source)
        assert len(result) == 1
        assert result[0].name == "todo"

    def test_empty_source(self):
        _, detect_proof_boundaries, _ = _import_boundaries()
        assert detect_proof_boundaries("") == []

    def test_no_proofs(self):
        """File with only imports/definitions and no proofs."""
        _, detect_proof_boundaries, _ = _import_boundaries()
        source = "Require Import Coq.Init.Nat.\nDefinition x := 5.\n"
        result = detect_proof_boundaries(source)
        # x has no closer, so no boundary
        assert len(result) == 0


# ===================================================================
# Section 4.6: Line Number Resolution
# ===================================================================


class TestResolveLineNumbers:
    """resolve_line_numbers — Spec 4.6."""

    def test_first_line(self):
        _, _, resolve_line_numbers = _import_boundaries()
        s = _make_timing_sentence(char_start=5)
        resolve_line_numbers([s], b"Hello world\n")
        assert s.line_number == 1

    def test_second_line(self):
        """Byte offset past first newline → line 2."""
        _, _, resolve_line_numbers = _import_boundaries()
        source = b"first line\nsecond line\n"
        # first newline at byte 10, so byte 11+ is line 2
        s = _make_timing_sentence(char_start=11)
        resolve_line_numbers([s], source)
        assert s.line_number == 2

    def test_multiple_sentences(self):
        _, _, resolve_line_numbers = _import_boundaries()
        source = b"line1\nline2\nline3\n"
        s1 = _make_timing_sentence(char_start=0)
        s2 = _make_timing_sentence(char_start=6)
        s3 = _make_timing_sentence(char_start=12)
        resolve_line_numbers([s1, s2, s3], source)
        assert s1.line_number == 1
        assert s2.line_number == 2
        assert s3.line_number == 3

    def test_byte_offset_at_newline(self):
        """Offset exactly at a newline character is still on the current line."""
        _, _, resolve_line_numbers = _import_boundaries()
        source = b"abc\ndef\n"
        s = _make_timing_sentence(char_start=3)  # at the \n
        resolve_line_numbers([s], source)
        assert s.line_number == 1

    def test_empty_source(self):
        _, _, resolve_line_numbers = _import_boundaries()
        s = _make_timing_sentence(char_start=0)
        resolve_line_numbers([s], b"")
        assert s.line_number == 1


# ===================================================================
# Section 4.8: Sentence Kind Classification
# ===================================================================


class TestClassifySentence:
    """classify_sentence — Spec 4.8."""

    def _make_boundary(self, name="foo", start=0, end=200):
        _, _, _, _, _, ProofBoundary, _, _, _, _ = _import_types()
        return ProofBoundary(name=name, decl_char_start=start, close_char_end=end)

    def test_require_classified_as_import(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Require~Import~Arith.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Import"

    def test_import_classified_as_import(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Import~Nat.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Import"

    def test_export_classified_as_import(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Export~Nat.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Import"

    def test_lemma_classified_as_definition(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Lemma~foo~:~True.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Definition"

    def test_theorem_classified_as_definition(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Theorem~bar~:~True.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Definition"

    def test_proof_classified_as_proof_open(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Proof.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "ProofOpen"

    def test_qed_classified_as_proof_close(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Qed.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "ProofClose"

    def test_defined_classified_as_proof_close(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Defined.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "ProofClose"

    def test_admitted_classified_as_proof_close(self):
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Admitted.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "ProofClose"

    def test_tactic_within_boundary(self):
        classify_sentence, _, _ = _import_boundaries()
        boundary = self._make_boundary("foo", start=0, end=200)
        s = _make_timing_sentence(char_start=50, snippet="[auto.]")
        classify_sentence(s, [boundary])
        assert s.sentence_kind == "Tactic"
        assert s.containing_proof == "foo"

    def test_other_outside_boundary(self):
        classify_sentence, _, _ = _import_boundaries()
        boundary = self._make_boundary("foo", start=0, end=100)
        s = _make_timing_sentence(char_start=150, snippet="[Check~nat.]")
        classify_sentence(s, [boundary])
        assert s.sentence_kind == "Other"
        assert s.containing_proof is None

    def test_tilde_in_snippet_normalized(self):
        """Snippet ~ is replaced with space for prefix matching."""
        classify_sentence, _, _ = _import_boundaries()
        s = _make_timing_sentence(snippet="[Require~Import~Coq.Init.]")
        classify_sentence(s, [])
        assert s.sentence_kind == "Import"

    def test_containing_proof_assigned_for_import_in_proof(self):
        """Even imports within a proof boundary get containing_proof assigned."""
        classify_sentence, _, _ = _import_boundaries()
        boundary = self._make_boundary("foo", start=0, end=200)
        s = _make_timing_sentence(char_start=50, snippet="[Require~Import~X.]")
        classify_sentence(s, [boundary])
        assert s.sentence_kind == "Import"
        assert s.containing_proof == "foo"


# ===================================================================
# Section 4.12: Bottleneck Classification
# ===================================================================


class TestClassifyBottlenecks:
    """classify_bottlenecks — Spec 4.12."""

    def test_empty_items(self):
        classify_bottlenecks = _import_bottleneck()
        assert classify_bottlenecks([], 10.0) == []

    def test_no_bottlenecks_below_thresholds(self):
        """All items below thresholds → empty list."""
        classify_bottlenecks = _import_bottleneck()
        items = [
            _make_timing_sentence(real_time_s=0.1, snippet="[auto.]"),
            _make_timing_sentence(real_time_s=0.2, snippet="[simpl.]"),
        ]
        result = classify_bottlenecks(items, 0.3)
        assert result == []

    def test_slow_qed_detected(self):
        """Priority 1: ProofClose where close_time > 5×tactic_time and > 2s."""
        classify_bottlenecks = _import_bottleneck()
        qed = _make_timing_sentence(
            real_time_s=30.0, snippet="[Qed.]", sentence_kind="ProofClose",
        )
        # total_time_s should be such that qed > 5 × (total - qed)
        # 30 > 5 × (32 - 30) = 5 × 2 = 10? Yes, 30 > 10
        result = classify_bottlenecks([qed], 32.0)
        assert len(result) >= 1
        assert result[0].category == "SlowQed"
        assert result[0].severity == "critical"

    def test_slow_reduction_detected(self):
        """Priority 2: simpl with time > 2s."""
        classify_bottlenecks = _import_bottleneck()
        simpl = _make_timing_sentence(
            real_time_s=8.0, snippet="[simpl~in~*.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([simpl], 10.0)
        assert len(result) >= 1
        assert result[0].category == "SlowReduction"

    def test_slow_cbn_detected(self):
        """cbn also triggers SlowReduction."""
        classify_bottlenecks = _import_bottleneck()
        cbn = _make_timing_sentence(
            real_time_s=5.0, snippet="[cbn.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([cbn], 8.0)
        assert len(result) >= 1
        assert result[0].category == "SlowReduction"

    def test_typeclass_blowup_detected(self):
        """Priority 3: typeclasses eauto with time > 2s."""
        classify_bottlenecks = _import_bottleneck()
        tc = _make_timing_sentence(
            real_time_s=5.0,
            snippet="[typeclasses~eauto.]",
            sentence_kind="Tactic",
        )
        result = classify_bottlenecks([tc], 8.0)
        assert len(result) >= 1
        assert result[0].category == "TypeclassBlowup"

    def test_high_search_depth_detected(self):
        """Priority 4: eauto with depth > 6 and time > 1s."""
        classify_bottlenecks = _import_bottleneck()
        eauto = _make_timing_sentence(
            real_time_s=3.0, snippet="[eauto~10.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([eauto], 5.0)
        assert len(result) >= 1
        assert result[0].category == "HighSearchDepth"

    def test_eauto_low_depth_not_flagged(self):
        """eauto with depth <= 6 does not trigger HighSearchDepth."""
        classify_bottlenecks = _import_bottleneck()
        eauto = _make_timing_sentence(
            real_time_s=3.0, snippet="[eauto~5.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([eauto], 5.0)
        # Should not be HighSearchDepth — could be General if > 5s but 3s < 5s
        for r in result:
            assert r.category != "HighSearchDepth"

    def test_expensive_match_detected(self):
        """Priority 5: match goal with time > 3s."""
        classify_bottlenecks = _import_bottleneck()
        mg = _make_timing_sentence(
            real_time_s=4.0,
            snippet="[match~goal~with~|~_~=>~auto~end.]",
            sentence_kind="Tactic",
        )
        result = classify_bottlenecks([mg], 6.0)
        assert len(result) >= 1
        assert result[0].category == "ExpensiveMatch"

    def test_general_bottleneck_detected(self):
        """Priority 6: any sentence > 5s not matching other categories."""
        classify_bottlenecks = _import_bottleneck()
        slow = _make_timing_sentence(
            real_time_s=10.0, snippet="[some_custom_tactic.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([slow], 15.0)
        assert len(result) >= 1
        assert result[0].category == "General"

    def test_max_five_bottlenecks(self):
        """Returns at most 5 bottlenecks."""
        classify_bottlenecks = _import_bottleneck()
        items = [
            _make_timing_sentence(real_time_s=6.0 + i, snippet=f"[tactic_{i}.]", sentence_kind="Tactic")
            for i in range(8)
        ]
        result = classify_bottlenecks(items, 100.0)
        assert len(result) <= 5

    def test_ranked_by_time_descending(self):
        """Bottlenecks are ranked by time, highest first."""
        classify_bottlenecks = _import_bottleneck()
        items = [
            _make_timing_sentence(real_time_s=6.0, snippet="[slow1.]", sentence_kind="Tactic"),
            _make_timing_sentence(real_time_s=20.0, snippet="[slow2.]", sentence_kind="Tactic"),
        ]
        result = classify_bottlenecks(items, 30.0)
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2
        # First should be the 20s one
        assert result[0].sentence.real_time_s > result[1].sentence.real_time_s

    def test_severity_critical_over_50_pct(self):
        """Critical when item accounts for > 50% of total time."""
        classify_bottlenecks = _import_bottleneck()
        slow = _make_timing_sentence(
            real_time_s=6.0, snippet="[slow.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([slow], 10.0)
        assert len(result) >= 1
        assert result[0].severity == "critical"

    def test_suggestion_hints_for_slow_qed(self):
        """SlowQed has correct suggestion hints."""
        classify_bottlenecks = _import_bottleneck()
        qed = _make_timing_sentence(
            real_time_s=30.0, snippet="[Qed.]", sentence_kind="ProofClose",
        )
        result = classify_bottlenecks([qed], 32.0)
        assert len(result) >= 1
        hints = result[0].suggestion_hints
        assert any("abstract" in h for h in hints)
        assert any("Opaque" in h for h in hints)

    def test_suggestion_hints_for_slow_reduction(self):
        classify_bottlenecks = _import_bottleneck()
        simpl = _make_timing_sentence(
            real_time_s=5.0, snippet="[simpl.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([simpl], 8.0)
        assert len(result) >= 1
        hints = result[0].suggestion_hints
        assert any("lazy" in h or "cbv" in h for h in hints)

    def test_general_has_empty_hints(self):
        classify_bottlenecks = _import_bottleneck()
        slow = _make_timing_sentence(
            real_time_s=10.0, snippet="[custom_tactic.]", sentence_kind="Tactic",
        )
        result = classify_bottlenecks([slow], 15.0)
        assert len(result) >= 1
        assert result[0].category == "General"
        assert result[0].suggestion_hints == []

    def test_ltac_entries_classified(self):
        """LtacProfileEntry items can also be classified."""
        classify_bottlenecks = _import_bottleneck()
        entry = _make_ltac_entry(
            tactic_name="typeclasses eauto", max_time_s=5.0,
        )
        result = classify_bottlenecks([entry], 10.0)
        assert len(result) >= 1
        assert result[0].category == "TypeclassBlowup"


# ===================================================================
# Section 4.14: Sentence Matching
# ===================================================================


class TestMatchSentences:
    """match_sentences — Spec 4.14."""

    def test_snippet_match(self):
        """Sentences matched by identical snippet."""
        match_sentences = _import_comparison()
        b = [_make_timing_sentence(char_start=100, snippet="[auto.]")]
        c = [_make_timing_sentence(char_start=105, snippet="[auto.]")]
        matched, unmatched_b, unmatched_c = match_sentences(b, c)
        assert len(matched) == 1
        assert len(unmatched_b) == 0
        assert len(unmatched_c) == 0

    def test_positional_ordering_for_duplicate_snippets(self):
        """Multiple same snippets matched positionally: 1st→1st, 2nd→2nd."""
        match_sentences = _import_comparison()
        b = [
            _make_timing_sentence(char_start=10, snippet="[auto.]"),
            _make_timing_sentence(char_start=50, snippet="[auto.]"),
            _make_timing_sentence(char_start=90, snippet="[auto.]"),
        ]
        c = [
            _make_timing_sentence(char_start=12, snippet="[auto.]"),
            _make_timing_sentence(char_start=55, snippet="[auto.]"),
            _make_timing_sentence(char_start=95, snippet="[auto.]"),
        ]
        matched, unmatched_b, unmatched_c = match_sentences(b, c)
        assert len(matched) == 3
        # Verify positional ordering
        assert matched[0][0].char_start == 10
        assert matched[0][1].char_start == 12

    def test_fuzz_match_for_unmatched(self):
        """Unmatched sentences matched by char_start within fuzz tolerance."""
        match_sentences = _import_comparison()
        b = [_make_timing_sentence(char_start=100, snippet="[old_tactic.]")]
        c = [_make_timing_sentence(char_start=150, snippet="[new_tactic.]")]
        matched, unmatched_b, unmatched_c = match_sentences(b, c, fuzz_bytes=500)
        assert len(matched) == 1

    def test_fuzz_match_exceeds_tolerance(self):
        """Sentences beyond fuzz tolerance are unmatched."""
        match_sentences = _import_comparison()
        b = [_make_timing_sentence(char_start=100, snippet="[old.]")]
        c = [_make_timing_sentence(char_start=700, snippet="[new.]")]
        matched, unmatched_b, unmatched_c = match_sentences(b, c, fuzz_bytes=500)
        assert len(matched) == 0
        assert len(unmatched_b) == 1
        assert len(unmatched_c) == 1

    def test_removed_sentences(self):
        """Baseline sentences with no match are unmatched."""
        match_sentences = _import_comparison()
        b = [
            _make_timing_sentence(char_start=0, snippet="[auto.]"),
            _make_timing_sentence(char_start=1000, snippet="[removed.]"),
        ]
        c = [_make_timing_sentence(char_start=0, snippet="[auto.]")]
        matched, unmatched_b, unmatched_c = match_sentences(b, c)
        assert len(matched) == 1
        assert len(unmatched_b) == 1
        assert unmatched_b[0].snippet == "[removed.]"

    def test_new_sentences(self):
        """Current sentences with no match are unmatched."""
        match_sentences = _import_comparison()
        b = [_make_timing_sentence(char_start=0, snippet="[auto.]")]
        c = [
            _make_timing_sentence(char_start=0, snippet="[auto.]"),
            _make_timing_sentence(char_start=5000, snippet="[new_tactic.]"),
        ]
        matched, unmatched_b, unmatched_c = match_sentences(b, c)
        assert len(matched) == 1
        assert len(unmatched_c) == 1
        assert unmatched_c[0].snippet == "[new_tactic.]"

    def test_empty_inputs(self):
        match_sentences = _import_comparison()
        matched, ub, uc = match_sentences([], [])
        assert matched == []
        assert ub == []
        assert uc == []


# ===================================================================
# Section 4.1: Request Validation
# ===================================================================


class TestValidateRequest:
    """validate_request — Spec 4.1."""

    def test_valid_timing_request(self, tmp_path):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        f = tmp_path / "test.v"
        f.write_text("Lemma foo : True. Proof. exact I. Qed.")
        req = ProfileRequest(file_path=str(f))
        assert validate_request(req) is None

    def test_invalid_extension(self, tmp_path):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        f = tmp_path / "test.ml"
        f.write_text("")
        req = ProfileRequest(file_path=str(f))
        result = validate_request(req)
        assert result is not None
        assert "INVALID_FILE" in result

    def test_file_not_found(self):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        req = ProfileRequest(file_path="/tmp/nonexistent_abc123.v")
        result = validate_request(req)
        assert result is not None
        assert "FILE_NOT_FOUND" in result

    def test_ltac_mode_requires_lemma_name(self, tmp_path):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        f = tmp_path / "test.v"
        f.write_text("")
        req = ProfileRequest(file_path=str(f), mode="ltac", lemma_name=None)
        result = validate_request(req)
        assert result is not None
        assert "INVALID_REQUEST" in result
        assert "lemma name" in result.lower()

    def test_compare_mode_requires_baseline(self, tmp_path):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        f = tmp_path / "test.v"
        f.write_text("")
        req = ProfileRequest(file_path=str(f), mode="compare", baseline_path=None)
        result = validate_request(req)
        assert result is not None
        assert "INVALID_REQUEST" in result

    def test_compare_mode_baseline_not_found(self, tmp_path):
        validate_request, _, _ = _import_engine()
        *_, ProfileRequest, _, _, _, _, _ = _import_types()
        f = tmp_path / "test.v"
        f.write_text("")
        req = ProfileRequest(
            file_path=str(f),
            mode="compare",
            baseline_path="/tmp/nonexistent_baseline.timing",
        )
        result = validate_request(req)
        assert result is not None
        assert "FILE_NOT_FOUND" in result


# ===================================================================
# Section 4.3: Path Resolution
# ===================================================================


class TestResolvePaths:
    """resolve_paths — Spec 4.3."""

    def test_coqproject_found(self, tmp_path):
        _, _, resolve_paths = _import_engine()
        theories = tmp_path / "theories"
        theories.mkdir()
        (tmp_path / "_CoqProject").write_text("-Q theories MyLib\n")
        vfile = theories / "Foo.v"
        vfile.write_text("")
        load_paths, include_paths = resolve_paths(str(vfile))
        assert len(load_paths) == 1
        assert load_paths[0][0] == "MyLib"
        assert load_paths[0][1] == str(theories.resolve())

    def test_no_coqproject(self, tmp_path):
        _, _, resolve_paths = _import_engine()
        vfile = tmp_path / "Scratch.v"
        vfile.write_text("")
        load_paths, include_paths = resolve_paths(str(vfile))
        assert load_paths == []
        assert include_paths == []

    def test_include_paths_parsed(self, tmp_path):
        _, _, resolve_paths = _import_engine()
        inc_dir = tmp_path / "include"
        inc_dir.mkdir()
        (tmp_path / "_CoqProject").write_text("-I include\n")
        vfile = tmp_path / "Foo.v"
        vfile.write_text("")
        load_paths, include_paths = resolve_paths(str(vfile))
        assert len(include_paths) == 1
        assert inc_dir.resolve().as_posix() in include_paths[0]

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        _, _, resolve_paths = _import_engine()
        theories = tmp_path / "theories"
        theories.mkdir()
        (tmp_path / "_CoqProject").write_text(
            "# comment\n\n-Q theories Lib\n"
        )
        vfile = theories / "Foo.v"
        vfile.write_text("")
        load_paths, _ = resolve_paths(str(vfile))
        assert len(load_paths) == 1
        assert load_paths[0][0] == "Lib"

    def test_ancestor_directory_search(self, tmp_path):
        """_CoqProject in parent directory is found."""
        _, _, resolve_paths = _import_engine()
        (tmp_path / "_CoqProject").write_text("-Q . Root\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        vfile = sub / "Foo.v"
        vfile.write_text("")
        load_paths, _ = resolve_paths(str(vfile))
        assert len(load_paths) == 1
        assert load_paths[0][0] == "Root"
