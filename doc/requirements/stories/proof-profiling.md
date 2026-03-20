# User Stories: Proof Profiling

Derived from [doc/requirements/proof-profiling.md](../proof-profiling.md).

---

## Epic 1: Single-Proof Profiling

### 1.1 Profile a Proof by Name

**As a** Coq developer with a slow proof,
**I want to** ask Claude to profile a specific lemma in my file and show me per-tactic timing,
**so that** I can identify which step is the bottleneck without manually adding `Time` to every tactic.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `.v` file and a lemma name WHEN profiling is invoked for that lemma THEN per-tactic timing is collected and returned, ranked from slowest to fastest
- GIVEN a proof with 10 tactics where one takes 5 seconds and the rest take < 0.1 seconds WHEN profiling results are returned THEN the 5-second tactic is listed first and flagged as the primary bottleneck
- GIVEN a lemma name that does not exist in the file WHEN profiling is invoked THEN a clear error is returned indicating the lemma was not found

**Traces to:** PP-P0-2

### 1.2 Profile an Entire File

**As a** Coq developer investigating compilation time,
**I want to** profile all sentences in a `.v` file and see which lemmas and commands are slowest,
**so that** I can prioritize which proofs to optimize first.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `.v` file WHEN file-level profiling is invoked THEN per-sentence timing is collected using `coqc -time` or equivalent and results are ranked from slowest to fastest
- GIVEN a file with 50 lemmas WHEN profiling completes THEN a summary shows the top 5 slowest lemmas with their times and percentage of total compilation time
- GIVEN a file that fails to compile WHEN profiling is invoked THEN the error is reported with the location of the failure, and timing for successfully processed sentences is still returned

**Traces to:** PP-P0-1

### 1.3 Separate Qed Time from Tactic Time

**As a** Coq developer whose proof runs fast interactively but `Qed` takes minutes,
**I want** profiling results that separate tactic execution time from `Qed` kernel re-checking time,
**so that** I understand whether the bottleneck is in my tactic script or in the proof term the kernel must verify.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof where tactics complete in 0.5 seconds but `Qed` takes 30 seconds WHEN profiling results are returned THEN tactic time (0.5s) and `Qed` time (30s) are reported separately
- GIVEN a proof where `Qed` dominates total time WHEN the result is presented THEN the explanation notes that `Qed` re-checks the entire proof term and that the issue is likely a large or poorly-reduced term, not the tactic script itself
- GIVEN a proof ending with `Defined` instead of `Qed` WHEN profiling results are returned THEN `Defined` time is reported and the explanation notes that `Defined` produces a transparent term (which affects downstream performance)

**Traces to:** PP-P1-4

---

## Epic 2: Bottleneck Explanation and Optimization Guidance

### 2.1 Explain Why a Tactic Is Slow

**As a** Coq developer who sees that `simpl in *` takes 15 seconds,
**I want** Claude to explain why that tactic is slow in this context,
**so that** I understand the root cause rather than just seeing a number.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a profiling result where `simpl in *` is the top bottleneck WHEN the explanation is presented THEN it describes how `simpl` unfolds definitions recursively and that applying it to all hypotheses (`in *`) multiplies the cost
- GIVEN a profiling result where typeclass resolution (`typeclasses eauto`) is the top bottleneck WHEN the explanation is presented THEN it describes how instance search can explore an exponentially large space and suggests using `Set Typeclasses Debug` to trace the search
- GIVEN a profiling result where `Qed` is the top bottleneck WHEN the explanation is presented THEN it describes the kernel re-checking process and distinguishes it from tactic execution

**Traces to:** PP-P0-3

### 2.2 Suggest Concrete Optimizations

**As a** Coq developer who has identified a bottleneck,
**I want** Claude to suggest specific code changes that would improve performance,
**so that** I can act on the profiling results immediately.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a bottleneck in `simpl` or `cbn` WHEN optimization suggestions are returned THEN they include alternatives such as `lazy`, `cbv`, targeted `change`, or `Arguments ... : simpl never`
- GIVEN a bottleneck in `Qed` WHEN optimization suggestions are returned THEN they include using `abstract (tactic)` to encapsulate expensive sub-proofs, replacing `simpl in H` with an eval/replace pattern, or using `Opaque` directives
- GIVEN a bottleneck in typeclass resolution WHEN optimization suggestions are returned THEN they include adjusting instance priorities, using `Hint Cut`, or replacing `auto`/`eauto` with explicit tactic sequences
- GIVEN a bottleneck in `eauto` with high depth WHEN optimization suggestions are returned THEN they include reducing search depth or switching to `auto` where backtracking is not needed

**Traces to:** PP-P0-4

---

## Epic 3: Ltac Profiling

### 3.1 Profile Ltac Execution

**As a** Coq developer using complex custom Ltac tactics,
**I want to** see a call-tree breakdown of which Ltac sub-tactics are consuming the most time,
**so that** I can optimize the right sub-tactic rather than guessing.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof that uses custom Ltac tactics WHEN Ltac profiling is invoked THEN `Set Ltac Profiling` is enabled, the proof is executed, and the call-tree from `Show Ltac Profile` is returned
- GIVEN an Ltac profile result WHEN it is presented THEN each entry shows the tactic name, percentage of total time (local and cumulative), number of calls, and maximum single-call time
- GIVEN an Ltac profile with a tactic consuming > 50% of total time WHEN the result is presented THEN that tactic is highlighted as the dominant bottleneck

**Traces to:** PP-P1-1

### 3.2 Interpret Ltac Profile Limitations

**As a** Coq developer using backtracking tactics,
**I want** Claude to warn me when Ltac profiling results may be inaccurate due to known limitations,
**so that** I do not waste time optimizing the wrong tactic.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof that uses multi-success tactics (e.g., `eauto`, `typeclasses eauto`) WHEN Ltac profiling results are returned THEN a caveat notes that Coq's Ltac profiler does not accurately account for backtracking and the reported times for these tactics may be misleading
- GIVEN a proof using compiled Ltac2 tactics WHEN Ltac profiling results are returned THEN a caveat notes that compiled Ltac2 tactics bypass the profiler and their time will not appear in the profile

**Traces to:** PP-P1-1

---

## Epic 4: Timing Comparison and Regression Detection

### 4.1 Compare Two Profiling Runs

**As a** Coq developer who has made an optimization,
**I want to** compare profiling results before and after the change,
**so that** I can confirm the optimization worked and did not introduce regressions elsewhere.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN two profiling runs of the same file (before and after a change) WHEN comparison is invoked THEN a diff is returned showing which tactics improved, which regressed, and which are unchanged
- GIVEN a comparison where one tactic improved by 10 seconds and another regressed by 2 seconds WHEN the result is presented THEN the net improvement is reported alongside the per-tactic diff
- GIVEN a comparison where no tactic changed by more than 10% WHEN the result is presented THEN it reports that performance is stable within noise margin

**Traces to:** PP-P1-2

### 4.2 Project-Wide Timing Summary

**As a** formalization team lead,
**I want to** profile all files in my Coq project and see which files and lemmas are slowest,
**so that** I can allocate optimization effort to the highest-impact areas.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq project directory WHEN project-wide profiling is invoked THEN all `.v` files are compiled with timing and results are aggregated into a ranked summary
- GIVEN a project with 100 files WHEN the summary is returned THEN it shows the top 10 slowest files with their compilation times and the top 10 slowest individual lemmas across the entire project
- GIVEN a project-wide profiling run WHEN the summary is returned THEN total compilation time and a breakdown by phase (compilation, `Qed` checking) are included where available

**Traces to:** PP-P1-3

---

## Epic 5: Timeout and Safety

### 5.1 Configurable Profiling Timeout

**As a** Coq developer profiling a file that may contain pathologically slow proofs,
**I want** profiling to respect a configurable timeout,
**so that** a single slow proof does not cause profiling to hang indefinitely.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a profiling invocation with a timeout of 60 seconds WHEN a single proof exceeds 60 seconds THEN profiling of that proof is interrupted and timing for completed proofs is still returned
- GIVEN no explicit timeout WHEN profiling is invoked THEN a sensible default timeout of 300 seconds per file is applied
- GIVEN a timeout interruption WHEN results are returned THEN the interrupted proof is flagged with its partial timing and a note that it exceeded the timeout

**Traces to:** PP-P0-5

---

## Epic 6: CI Integration

### 6.1 Structured Profiling Output for CI

**As a** CI pipeline maintainer,
**I want** profiling results in a structured, machine-readable format,
**so that** I can build automated performance gates that flag regressions before merging.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a profiling run invoked in a CI context WHEN it completes THEN a structured JSON payload is available with per-file and per-tactic timing, overall totals, and regression annotations (if a baseline is provided)
- GIVEN a structured profiling result with a baseline WHEN any tactic has regressed by ≥ 20% and ≥ 0.5 seconds absolute THEN the regression is flagged in the output
- GIVEN a profiling run where no regressions exceed the threshold WHEN the result is inspected programmatically THEN the overall status is "pass"

**Traces to:** PP-P1-5

---

## Epic 7: Visualization

### 7.1 Visual Timing Breakdown

**As a** Coq developer who wants to see the performance profile of a proof at a glance,
**I want** a visual timeline or flame graph of tactic execution,
**so that** I can intuitively see where time is spent without reading through a table of numbers.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a profiling result for a single proof WHEN visualization is requested THEN a local HTML file is generated showing a timeline or flame graph of tactic execution
- GIVEN a visualization WHEN the user opens it in a browser THEN each tactic is represented as a block whose width is proportional to its execution time, with the slowest tactics visually prominent
- GIVEN a proof with nested Ltac calls WHEN the flame graph is generated THEN the nesting structure is preserved, showing which parent tactic contains which sub-calls

**Traces to:** PP-P2-1

### 7.2 Detect Slow Patterns Without Profiling

**As a** Coq developer who wants a quick check before committing,
**I want** Claude to scan my proof script for known anti-patterns that cause slow compilation,
**so that** I can fix obvious issues without running the full profiler.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof script containing `simpl in *` WHEN static analysis is run THEN it flags the use and suggests targeting specific hypotheses instead
- GIVEN a proof script with `eauto 20` (high search depth) WHEN static analysis is run THEN it flags the depth as likely excessive and suggests reducing it or using `auto` where backtracking is unnecessary
- GIVEN a proof script with no known anti-patterns WHEN static analysis is run THEN it reports that no obvious performance issues were detected

**Traces to:** PP-P2-4
