# Proof Profiling

Identifies performance bottlenecks in Coq proof scripts by wrapping Coq's existing profiling infrastructure, synthesizing results across multiple profiling backends, ranking findings by impact, and providing natural-language explanations with actionable optimization suggestions. The user asks Claude to profile a proof; Claude invokes the appropriate tools, interprets the results, and returns a ranked breakdown that answers "what is slow, why is it slow, and how do I fix it."

---

## Problem

Coq proof scripts frequently contain performance bottlenecks that are invisible to the user. The most common complaint is "Qed takes 30 seconds but every tactic ran instantly" — the kernel re-checks the entire proof term during `Qed`, and the cost of that re-checking depends on what the tactics produced, not how long they took to run. A tactic like `simpl in *` executes in milliseconds but can produce a bloated proof term that the kernel takes minutes to verify. The user sees only the `Qed` time and has no idea which tactic is responsible.

Today's debugging workflow is manual binary search: comment out half the proof, recompile, narrow down the offending step, repeat. This is tedious, error-prone, and discourages systematic performance work. It also requires expertise that many Coq users lack — knowing that `Qed` slowness is usually caused by reduction tactics in hypotheses, or that typeclass resolution can search exponentially large spaces, or that `eauto` with high depth is a common source of hangs.

Coq provides several profiling mechanisms — per-sentence timing (`coqc -time`), Ltac call trees (`Set Ltac Profiling`), and Chrome trace output (`coqc -profile`, Coq 8.19+). These tools are mature and capable, but each has a different invocation method, output format, and set of limitations. No single tool gives a complete picture, and none of them explain *why* something is slow or *what to do about it*. The gap is not in measurement — it is in accessibility, synthesis, and actionable guidance.

## Solution

### Single-Proof Profiling

A user points Claude at a specific lemma and asks "why is this proof slow?" Claude profiles the proof and returns per-step timing, ranked from slowest to fastest. The slowest steps are flagged as bottlenecks with explanations of what makes them expensive. The user does not need to manually add `Time` to every tactic, learn `coqc -time` output format, or know how to invoke Ltac profiling.

When a user profiles an entire file rather than a single lemma, the result is a per-sentence timing summary covering everything in the file — imports, definitions, tactics, and proof-closing commands. The summary highlights the slowest lemmas and their share of total compilation time, so the user can prioritize which proofs to optimize first.

### Qed vs Tactic Time

Profiling results separate tactic execution time from `Qed` kernel re-checking time. This distinction is critical because the two have fundamentally different causes and solutions. When tactics are slow, the fix is usually to choose a different tactic or reduce search depth. When `Qed` is slow, the fix is to change how the proof term is constructed — using `abstract` to encapsulate expensive sub-proofs, replacing `simpl in H` with an eval/replace pattern, or adding `Opaque` directives to prevent unnecessary unfolding.

When `Qed` dominates total time, the explanation makes clear that the bottleneck is not in the tactic script but in the proof term the kernel must verify. When a proof ends with `Defined` (transparent) rather than `Qed` (opaque), the explanation notes the downstream performance implications — transparent definitions can cause slowdowns in later proofs that depend on them.

### Bottleneck Explanation and Optimization Guidance

Raw timing data tells the user *what* is slow but not *why* or *what to do*. This feature closes that gap. When a bottleneck is identified, the result includes a natural-language explanation of the root cause and concrete optimization suggestions drawn from well-documented performance patterns.

For example: when `simpl in *` is the bottleneck, the explanation describes how `simpl` unfolds definitions recursively and how applying it to all hypotheses multiplies the cost, and suggests alternatives like `lazy`, `cbv`, targeted `change`, or `Arguments ... : simpl never`. When typeclass resolution is the bottleneck, it explains exponential instance search and suggests adjusting priorities, using `Hint Cut`, or replacing `auto`/`eauto` with explicit tactic sequences. These patterns are drawn from years of community experience, documented in Jason Gross's PhD thesis, the Coq performance wiki, and the `slow-coq-examples` repository.

This is the feature's core differentiator: not just measurement, but diagnosis and treatment.

### Ltac Call-Tree Profiling

For users writing complex Ltac automation, sentence-level timing is too coarse — they need to know which sub-tactic within a compound Ltac tactic is expensive. Ltac profiling provides a call-tree breakdown showing time per tactic in its calling context: tactic name, local and cumulative percentage of total time, number of invocations, and maximum single-call time.

When Ltac profiling results may be unreliable — because the proof uses multi-success/backtracking tactics or compiled Ltac2 tactics that bypass the profiler — the result includes a caveat so the user does not waste time optimizing the wrong tactic based on misleading data.

### Timing Comparison and Regression Detection

After making a change, the user asks Claude to compare timing before and after. The result shows which steps improved, which regressed, and which are unchanged. When no step changed by more than the noise margin, the result says so — confirming stability is as valuable as detecting regressions.

At project scale, profiling aggregates per-file and per-lemma timing across an entire Coq development, producing a ranked summary of the slowest files and lemmas. This gives formalization team leads a prioritized list of optimization targets — the top 10 slowest files, the top 10 slowest lemmas — with enough context to allocate effort to the highest-impact areas.

### CI Integration

For teams that want performance gates in CI, profiling produces structured, machine-readable output alongside the human-readable summary. CI pipelines can compare against a baseline and flag regressions that exceed a configurable threshold. The human-readable summary appears in pipeline logs for developers reviewing the results.

## What This Feature Does Not Provide

- **Automatic proof optimization.** Profiling identifies bottlenecks and suggests fixes, but does not apply changes without user approval. Automated optimization is the responsibility of the proof compression and proof repair features.
- **Style linting for performance anti-patterns.** The proof-lint feature detects *stylistic* issues (deprecated tactics, bullet inconsistency, unnecessarily complex tactic chains). Proof profiling detects *performance* issues by measuring actual execution time. A tactic can be stylistically fine but slow, or stylistically questionable but fast. The two features are complementary: proof-lint catches patterns that *might* be slow based on static analysis; proof profiling measures what *is* slow based on execution.
- **OCaml-level profiling of Coq internals.** Profiling operates at the Coq command and tactic level, not at the OCaml function level. Tools like `perf` and Landmarks are useful for Coq developers debugging the implementation itself, but are out of scope for users profiling their proof scripts.
- **Build system integration.** Profiling does not modify `Makefile`, `dune-project`, or `_CoqProject` files. It invokes Coq's profiling tools directly and parses their output. Users who want `TIMING=1` in their build system can set that up separately through the build system integration feature.

## Design Rationale

### Why wrap existing tools rather than build new instrumentation

Coq's profiling infrastructure — `coqc -time`, `Set Ltac Profiling`, `coqc -profile` — is mature, well-tested, and already measures the right things at the right granularity. Building alternative instrumentation would duplicate effort and introduce a separate trust boundary (are the profiler's numbers accurate?). By wrapping existing tools, the feature inherits their correctness and coverage while adding the synthesis and explanation layer that they lack.

### Why combine multiple profiling backends

No single Coq profiling tool gives a complete picture. `coqc -time` provides per-sentence wall-clock timing but no call-tree breakdown. `Set Ltac Profiling` provides call trees but only for Ltac tactics, not for `Qed` or non-tactic commands. `coqc -profile` (Coq 8.19+) provides component-level Chrome traces but requires a newer Coq version and produces raw data that needs interpretation. Each tool has blind spots that the others fill. The feature selects the right backend for the situation — and when multiple backends are appropriate, synthesizes their results into a unified view.

### Why explanation and optimization suggestions are core, not optional

Knowing that a tactic takes 15 seconds is only useful if you know what to do about it. The Coq community has accumulated years of performance knowledge — documented in Jason Gross's PhD thesis, the Coq wiki, and community forums — that maps symptom patterns to root causes and fixes. This knowledge is exactly what an LLM can synthesize and deliver in context. Without it, the user sees a number and must independently research the cause. With it, the user receives a diagnosis and a treatment plan in the same response.

### Why Qed time must be reported separately

The "fast tactics, slow Qed" pattern is the single most common performance complaint in the Coq community. It confuses users because they observe fast tactic execution and conclude that the proof is efficient, only to find that `Qed` takes orders of magnitude longer. The root cause — kernel re-checking of the proof term — is invisible in standard tactic-level profiling. By explicitly separating `Qed` time and explaining what it measures, the feature prevents the most common misdiagnosis: blaming the wrong tactic when the real problem is in the proof term.

### Why Ltac profiling is secondary to sentence-level profiling

Sentence-level timing (`coqc -time`) is universally applicable: it works for every Coq command, every tactic engine (Ltac1, Ltac2, SSReflect, Equations), and every Coq version. Ltac call-tree profiling is narrower: it only covers Ltac1 (with partial Ltac2 support in newer versions), has known accuracy issues with backtracking tactics, and introduces profiler overhead that can distort measurements. Sentence-level profiling is the right default; Ltac profiling is a deeper investigation tool for users who need call-tree granularity.

## Acceptance Criteria

### Single-Proof Profiling

**Priority:** P0
**Stability:** Stable

- GIVEN a `.v` file and a lemma name WHEN profiling is invoked for that lemma THEN per-tactic timing is collected and returned, ranked from slowest to fastest
- GIVEN a proof with 10 tactics where one takes 5 seconds and the rest take < 0.1 seconds WHEN profiling results are returned THEN the 5-second tactic is listed first and flagged as the primary bottleneck
- GIVEN a lemma name that does not exist in the file WHEN profiling is invoked THEN a clear error is returned indicating the lemma was not found
- GIVEN a `.v` file WHEN file-level profiling is invoked THEN per-sentence timing is collected using `coqc -time` or equivalent and results are ranked from slowest to fastest
- GIVEN a file with 50 lemmas WHEN profiling completes THEN a summary shows the top 5 slowest lemmas with their times and percentage of total compilation time
- GIVEN a file that fails to compile WHEN profiling is invoked THEN the error is reported with the location of the failure, and timing for successfully processed sentences is still returned

**Traces to:** PP-P0-1, PP-P0-2

### Qed vs Tactic Time Separation

**Priority:** P1
**Stability:** Stable

- GIVEN a proof where tactics complete in 0.5 seconds but `Qed` takes 30 seconds WHEN profiling results are returned THEN tactic time (0.5s) and `Qed` time (30s) are reported separately
- GIVEN a proof where `Qed` dominates total time WHEN the result is presented THEN the explanation notes that `Qed` re-checks the entire proof term and that the issue is likely a large or poorly-reduced term, not the tactic script itself
- GIVEN a proof ending with `Defined` instead of `Qed` WHEN profiling results are returned THEN `Defined` time is reported and the explanation notes that `Defined` produces a transparent term (which affects downstream performance)

**Traces to:** PP-P1-4

### Bottleneck Explanation and Optimization Guidance

**Priority:** P0
**Stability:** Stable

- GIVEN a profiling result where `simpl in *` is the top bottleneck WHEN the explanation is presented THEN it describes how `simpl` unfolds definitions recursively and that applying it to all hypotheses (`in *`) multiplies the cost
- GIVEN a profiling result where typeclass resolution (`typeclasses eauto`) is the top bottleneck WHEN the explanation is presented THEN it describes how instance search can explore an exponentially large space and suggests using `Set Typeclasses Debug` to trace the search
- GIVEN a profiling result where `Qed` is the top bottleneck WHEN the explanation is presented THEN it describes the kernel re-checking process and distinguishes it from tactic execution
- GIVEN a bottleneck in `simpl` or `cbn` WHEN optimization suggestions are returned THEN they include alternatives such as `lazy`, `cbv`, targeted `change`, or `Arguments ... : simpl never`
- GIVEN a bottleneck in `Qed` WHEN optimization suggestions are returned THEN they include using `abstract (tactic)` to encapsulate expensive sub-proofs, replacing `simpl in H` with an eval/replace pattern, or using `Opaque` directives
- GIVEN a bottleneck in typeclass resolution WHEN optimization suggestions are returned THEN they include adjusting instance priorities, using `Hint Cut`, or replacing `auto`/`eauto` with explicit tactic sequences
- GIVEN a bottleneck in `eauto` with high depth WHEN optimization suggestions are returned THEN they include reducing search depth or switching to `auto` where backtracking is not needed

**Traces to:** PP-P0-3, PP-P0-4

### Ltac Profiling

**Priority:** P1
**Stability:** Stable

- GIVEN a proof that uses custom Ltac tactics WHEN Ltac profiling is invoked THEN `Set Ltac Profiling` is enabled, the proof is executed, and the call-tree from `Show Ltac Profile` is returned
- GIVEN an Ltac profile result WHEN it is presented THEN each entry shows the tactic name, percentage of total time (local and cumulative), number of calls, and maximum single-call time
- GIVEN an Ltac profile with a tactic consuming > 50% of total time WHEN the result is presented THEN that tactic is highlighted as the dominant bottleneck

**Traces to:** PP-P1-1

### Ltac Profile Limitations

**Priority:** P1
**Stability:** Draft

- GIVEN a proof that uses multi-success tactics (e.g., `eauto`, `typeclasses eauto`) WHEN Ltac profiling results are returned THEN a caveat notes that Coq's Ltac profiler does not accurately account for backtracking and the reported times for these tactics may be misleading
- GIVEN a proof using compiled Ltac2 tactics WHEN Ltac profiling results are returned THEN a caveat notes that compiled Ltac2 tactics bypass the profiler and their time will not appear in the profile

**Traces to:** PP-P1-1

### Timing Comparison

**Priority:** P1
**Stability:** Stable

- GIVEN two profiling runs of the same file (before and after a change) WHEN comparison is invoked THEN a diff is returned showing which tactics improved, which regressed, and which are unchanged
- GIVEN a comparison where one tactic improved by 10 seconds and another regressed by 2 seconds WHEN the result is presented THEN the net improvement is reported alongside the per-tactic diff
- GIVEN a comparison where no tactic changed by more than 10% WHEN the result is presented THEN it reports that performance is stable within noise margin

**Traces to:** PP-P1-2

### Project-Wide Timing Summary

**Priority:** P1
**Stability:** Stable

- GIVEN a Coq project directory WHEN project-wide profiling is invoked THEN all `.v` files are compiled with timing and results are aggregated into a ranked summary
- GIVEN a project with 100 files WHEN the summary is returned THEN it shows the top 10 slowest files with their compilation times and the top 10 slowest individual lemmas across the entire project
- GIVEN a project-wide profiling run WHEN the summary is returned THEN total compilation time and a breakdown by phase (compilation, `Qed` checking) are included where available

**Traces to:** PP-P1-3

### Configurable Profiling Timeout

**Priority:** P0
**Stability:** Stable

- GIVEN a profiling invocation with a timeout of 60 seconds WHEN a single proof exceeds 60 seconds THEN profiling of that proof is interrupted and timing for completed proofs is still returned
- GIVEN no explicit timeout WHEN profiling is invoked THEN a sensible default timeout of 300 seconds per file is applied
- GIVEN a timeout interruption WHEN results are returned THEN the interrupted proof is flagged with its partial timing and a note that it exceeded the timeout

**Traces to:** PP-P0-5

### CI Integration

**Priority:** P1
**Stability:** Draft

- GIVEN a profiling run invoked in a CI context WHEN it completes THEN a structured JSON payload is available with per-file and per-tactic timing, overall totals, and regression annotations (if a baseline is provided)
- GIVEN a structured profiling result with a baseline WHEN any tactic has regressed by ≥ 20% and ≥ 0.5 seconds absolute THEN the regression is flagged in the output
- GIVEN a profiling run where no regressions exceed the threshold WHEN the result is inspected programmatically THEN the overall status is "pass"

**Traces to:** PP-P1-5

### Visualization

**Priority:** P2
**Stability:** Draft

- GIVEN a profiling result for a single proof WHEN visualization is requested THEN a local HTML file is generated showing a timeline or flame graph of tactic execution
- GIVEN a visualization WHEN the user opens it in a browser THEN each tactic is represented as a block whose width is proportional to its execution time, with the slowest tactics visually prominent
- GIVEN a proof with nested Ltac calls WHEN the flame graph is generated THEN the nesting structure is preserved, showing which parent tactic contains which sub-calls

**Traces to:** PP-P2-1

### Static Anti-Pattern Detection

**Priority:** P2
**Stability:** Draft

- GIVEN a proof script containing `simpl in *` WHEN static analysis is run THEN it flags the use and suggests targeting specific hypotheses instead
- GIVEN a proof script with `eauto 20` (high search depth) WHEN static analysis is run THEN it flags the depth as likely excessive and suggests reducing it or using `auto` where backtracking is unnecessary
- GIVEN a proof script with no known anti-patterns WHEN static analysis is run THEN it reports that no obvious performance issues were detected

**Traces to:** PP-P2-4
