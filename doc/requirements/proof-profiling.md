# Proof Profiling — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context; see [common-questions.md](../background/common-questions.md) §7 (Performance) for user pain points.

## 1. Business Goals

Coq proof scripts frequently contain performance bottlenecks that are invisible to the user. The most common complaint — "Qed takes 30 seconds but every tactic ran instantly" — arises because the kernel re-checks the entire proof term, and there is no easy way to determine which tactic produced the expensive term. Users resort to manual binary search: commenting out half the proof, re-running, and narrowing down the offending step. This is tedious, error-prone, and discourages performance work.

Coq provides several low-level timing mechanisms — the `Time` vernacular command, `coqc -time` per-sentence timing, `Set Ltac Profiling` for Ltac call trees, and the newer `coqc -profile` for Chrome trace JSON (Coq 8.19+). These tools are powerful but fragmented: each has a different invocation method, output format, and set of limitations. No existing tool unifies them, ranks results, or explains what the timing data means in context. The gap is not in measurement — it is in accessibility, synthesis, and actionable guidance.

This initiative wraps Coq's existing profiling infrastructure as MCP-accessible functionality so that Claude can profile proof scripts on behalf of the user, identify bottlenecks, rank tactics by cost, and suggest concrete optimizations. The user says "profile this proof" and receives a ranked breakdown with explanations — no need to learn `coqc -time` syntax, parse timing files, or manually instrument their proof script.

Performance is the #1 category of GitHub issues filed against Coq (25% of all issues) and a top-3 concern in the Coq Community Survey 2022. Jason Gross's PhD thesis ("Performance Engineering of Proof-Based Software Systems at Scale," MIT 2021) and his `slow-coq-examples` repository document hundreds of real-world performance regressions. The community has been asking for better profiling tooling for years.

Because Poule already exposes 22+ MCP tools and research suggests accuracy degrades past 20–30 tools, this initiative should expose profiling as a mode of existing tools or as a minimal addition to the tool surface, rather than proliferating new top-level tools.

**Success metrics:**
- Users can identify the slowest tactic in a proof script within a single interaction, without manually instrumenting code
- Per-tactic timing results are returned within 2x the raw `coqc -time` execution time (MCP overhead is minimal)
- When a bottleneck is identified, the response includes an actionable optimization suggestion in ≥ 80% of cases (based on known patterns: slow `simpl`/`cbn`, typeclass resolution blowup, expensive `Qed` re-checking)
- Timing regression detection between two runs surfaces regressions of ≥ 20% with ≤ 5% false positive rate
- ≥ 85% of users who profile a slow proof report that the results helped them improve performance

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers with slow proof scripts | Identify which tactics are bottlenecks and how to fix them, without learning profiling tool syntax | Primary |
| Formalization teams maintaining large developments | Detect timing regressions between commits, identify which files and lemmas regressed, prioritize optimization work | Primary |
| Library authors (MathComp, Flocq, std++) | Profile typeclass resolution, `simpl`/`cbn` behavior, and `Qed` times to keep compilation fast for downstream users | Secondary |
| Coq newcomers using Claude Code | Understand why their proof is slow and learn performance best practices through contextual guidance | Secondary |
| CI pipeline maintainers | Automated performance gates that flag regressions before merging | Tertiary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)

**Lean ecosystem (comparative baseline):**
- Lean 4 provides per-tactic timing via `set_option profiler true` and `set_option trace.profiler true`, with results displayed inline in the editor.
- Lake (Lean's build system) supports `--profile` for build-level timing.
- The Lean community has no equivalent of Coq's Ltac profiling call tree or Chrome trace output.

**Coq ecosystem (current state):**
- `Time <tactic>` provides wall-clock timing for a single command. Tedious to apply systematically — the user must add it to each tactic manually.
- `coqc -time` / `-time-file` outputs per-sentence timing to stdout or a file. Format: `Chars 0 - 26 [Require~Coq.ZArith.BinInt.] 0.157 secs (0.128u,0.028s)`. Useful but requires manual parsing to find bottlenecks.
- `Set Ltac Profiling` / `Show Ltac Profile` provides a call-tree breakdown of Ltac tactic execution. Known limitation: does not handle multi-success/backtracking tactics correctly (Coq issue #12196). Ltac2 profiling was added in 2023 (PR #17371) but compiled Ltac2 tactics bypass profiling.
- `coqc -profile foo.json` (Coq 8.19+) generates Chrome trace JSON viewable at ui.perfetto.dev. `COQ_PROFILE_COMPONENTS` env var allows selective profiling. Dune does not yet support this flag (Dune issue #20401).
- `coq_makefile` supports `TIMING=1` for per-line timing, `TIMED=1` for per-file build times, and `pretty-timed` / `pretty-timed-diff` targets for human-readable comparisons.
- coq-lsp shows per-sentence timing and memory on hover, and its `fcc` compiler provides machine-friendly access.
- Jason Gross's `coq-performance-tests` repository provides regression test infrastructure.

**Key insight:** The measurement infrastructure exists and is mature. What is missing is an integrated workflow that invokes the right profiling tool for the situation, synthesizes results across tools, ranks findings by impact, and provides actionable optimization guidance. This is exactly the kind of multi-tool orchestration that an MCP-based agentic workflow can deliver and that no IDE can.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| PP-P0-1 | Profile a single proof script file and return per-sentence timing (including imports, definitions, tactics, and `Qed`), ranked from slowest to fastest |
| PP-P0-2 | Profile a specific proof (by lemma name) within a file and return per-step timing for that proof only |
| PP-P0-3 | Identify and highlight the top bottlenecks in a profiling result, with natural-language explanation of why each step is slow |
| PP-P0-4 | Suggest concrete optimizations for identified bottlenecks based on known performance patterns (slow `simpl`/`cbn` → use `lazy`/`cbv`; expensive `Qed` → use `abstract`; typeclass blowup → adjust priorities) |
| PP-P0-5 | Support a configurable timeout so that profiling of pathologically slow files does not hang indefinitely |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| PP-P1-1 | Profile Ltac tactic execution using `Set Ltac Profiling` and return the call-tree breakdown, explaining which sub-tactics dominate |
| PP-P1-2 | Compare timing between two profiling runs (e.g., before and after an optimization) and report which tactics improved, regressed, or are unchanged |
| PP-P1-3 | Profile all files in a Coq project and return a project-wide summary ranked by compilation time, identifying the slowest files and lemmas |
| PP-P1-4 | Separate `Qed` time from tactic execution time in profiling results, since `Qed` re-checking is a distinct and commonly misunderstood bottleneck |
| PP-P1-5 | Produce output suitable for CI integration: structured result format with per-tactic and per-file timing, suitable for automated regression detection |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| PP-P2-1 | Generate a visual timeline or flame graph of tactic execution for a proof, rendered as a local HTML file |
| PP-P2-2 | Profile memory usage per tactic in addition to wall-clock time |
| PP-P2-3 | Track profiling history so the user can see performance trends over time for specific lemmas |
| PP-P2-4 | Detect common anti-patterns that cause slow proofs (e.g., `simpl in *`, repeated `rewrite` chains, unbounded `eauto` depth) without running the profiler, using static analysis of the proof script |

---

## 5. Scope Boundaries

**In scope:**
- MCP wrapper around Coq's existing profiling tools (`coqc -time`, `-time-file`, `Set Ltac Profiling`, `coqc -profile`)
- Per-tactic and per-file timing collection, parsing, and ranking
- Bottleneck identification with natural-language explanation and optimization suggestions
- Timing comparison between runs for regression detection
- Project-wide profiling with summary reporting
- CI-friendly structured output

**Out of scope:**
- Installation or management of Coq (assumed to be available in the user's environment)
- Modifications to Coq's profiling infrastructure itself
- OCaml-level profiling of Coq internals (e.g., `perf record`, Landmarks)
- Automatic proof optimization (applying fixes without user approval — that is the responsibility of proof repair/compression initiatives)
- IDE plugin development
- Build system modifications (Dune, coq_makefile — those are build system integration concerns)
- Profiling of Lean, Agda, or other proof assistants
