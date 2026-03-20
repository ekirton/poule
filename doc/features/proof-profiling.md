# Proof Profiling

Identifies performance bottlenecks in Coq proof scripts by wrapping Coq's existing profiling infrastructure, synthesizing results across multiple profiling backends, ranking findings by impact, and providing natural-language explanations with actionable optimization suggestions. The user asks Claude to profile a proof; Claude invokes the appropriate tools, interprets the results, and returns a ranked breakdown that answers "what is slow, why is it slow, and how do I fix it."

**Stories:** [Epic 1: Single-Proof Profiling](../requirements/stories/proof-profiling.md#epic-1-single-proof-profiling), [Epic 2: Bottleneck Explanation and Optimization Guidance](../requirements/stories/proof-profiling.md#epic-2-bottleneck-explanation-and-optimization-guidance), [Epic 3: Ltac Profiling](../requirements/stories/proof-profiling.md#epic-3-ltac-profiling), [Epic 4: Timing Comparison and Regression Detection](../requirements/stories/proof-profiling.md#epic-4-timing-comparison-and-regression-detection), [Epic 5: Timeout and Safety](../requirements/stories/proof-profiling.md#epic-5-timeout-and-safety), [Epic 6: CI Integration](../requirements/stories/proof-profiling.md#epic-6-ci-integration), [Epic 7: Visualization](../requirements/stories/proof-profiling.md#epic-7-visualization)

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
