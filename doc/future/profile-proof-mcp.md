# Future Work: `profile_proof` MCP Tool

**Status:** Not started
**Prerequisite:** `extract_proof_trace` now provides wall-clock `duration_ms` per tactic step (replay timing). This document describes the next level: a dedicated profiling tool that wraps Coq's native profiling infrastructure.

**Parent feature:** [doc/features/proof-profiling.md](../features/proof-profiling.md)

---

## Motivation

`extract_proof_trace` times each tactic during session replay. This gives useful per-step wall-clock data but has limitations:

1. **No `Qed` / `Defined` timing.** Replay stops after the last tactic; the kernel re-checking step (`Qed`) is not executed, so the most common bottleneck in Coq proofs — "fast tactics, slow `Qed`" — is invisible.
2. **No Ltac call-tree breakdown.** Compound Ltac tactics (e.g., `my_crush`) are treated as opaque single steps. There is no sub-tactic expansion or profiling.
3. **Replay timing ≠ compilation timing.** Replay occurs inside an already-initialized session with all imports loaded. Compilation timing (`coqc -time`) includes import resolution, universe checking, and other overheads that replay skips.
4. **No file-level or project-level profiling.** `extract_proof_trace` operates on a single proof within a session. There is no aggregation across lemmas or files.

A dedicated `profile_proof` MCP tool would address all four gaps by wrapping Coq's existing profiling backends.

---

## Proposed MCP Tool

### `profile_proof`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | yes | Path to the `.v` file |
| `lemma_name` | string | no | Target lemma; if omitted, profile the entire file |
| `backend` | enum | no | `"time"` (default), `"ltac"`, or `"chrome"` |
| `timeout_s` | integer | no | Per-file timeout in seconds (default: 300) |

**Returns:** A structured profiling result (see data model below).

### Profiling Backends

#### 1. Sentence-level timing (`coqc -time`)

- Universally available (all Coq versions, all tactic engines).
- Parses `coqc -time` output to extract per-sentence wall-clock time.
- Reports `Qed` / `Defined` time separately from tactic time.
- When `lemma_name` is specified, filters to that proof's sentences.
- When omitted, returns file-level summary ranked by time.

#### 2. Ltac call-tree profiling (`Set Ltac Profiling`)

- Enabled via `Set Ltac Profiling. <proof> Show Ltac Profile.`
- Returns a call tree: tactic name, local %, cumulative %, call count, max single-call time.
- Limited to Ltac1 tactics; compiled Ltac2 bypasses the profiler.
- Includes caveats for multi-success / backtracking tactics where profiler accuracy is known to degrade.

#### 3. Chrome trace profiling (`coqc -profile`, Coq 8.19+)

- Produces a Chrome trace JSON with component-level timing.
- Requires Coq 8.19 or later; tool should detect version and fail gracefully on older Coq.
- Returns raw trace path for the user to open in `chrome://tracing` or Perfetto.

---

## Proposed Data Model

### ProfilingResult

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | The profiled file |
| `lemma_name` | string or null | The profiled lemma, or null for file-level |
| `backend` | string | Which backend was used |
| `total_time_ms` | float | Total wall-clock time |
| `tactic_time_ms` | float | Time in tactic execution (excludes `Qed`) |
| `qed_time_ms` | float or null | Time in `Qed` / `Defined` kernel checking |
| `steps` | list of ProfilingStep | Per-sentence timing, sorted slowest first |
| `ltac_profile` | LtacProfile or null | Call-tree data (only for `backend="ltac"`) |
| `truncated` | boolean | True if timeout interrupted profiling |

### ProfilingStep

| Field | Type | Description |
|-------|------|-------------|
| `sentence` | string | The Coq sentence (tactic, command, or `Qed`) |
| `line` | integer | Line number in the source file |
| `time_ms` | float | Wall-clock milliseconds |
| `is_qed` | boolean | True for `Qed` / `Defined` / `Admitted` |
| `is_bottleneck` | boolean | True if this step is flagged as a bottleneck |

### LtacProfile

| Field | Type | Description |
|-------|------|-------------|
| `entries` | list of LtacProfileEntry | Call-tree entries |
| `caveats` | list of string | Accuracy warnings (backtracking, Ltac2, etc.) |

### LtacProfileEntry

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | Tactic name |
| `local_pct` | float | Percentage of total time (local) |
| `cumulative_pct` | float | Percentage of total time (cumulative) |
| `calls` | integer | Number of invocations |
| `max_time_ms` | float | Maximum single-call time |

---

## Implementation Strategy

### Phase 1: Sentence-level timing (addresses e2e 8.1-8.4, 8.8-8.9)

1. Add a `profile_proof` handler to `src/Poule/server/handlers.py`.
2. Implement a `CoqProfiler` class in `src/Poule/profiling/` that:
   - Invokes `coqc -time <file>` with a timeout.
   - Parses the timing output (format: `<sentence> <chars> <time>secs`).
   - Separates `Qed` / `Defined` time from tactic time.
   - Optionally filters to a single lemma.
3. Add data model types to `src/Poule/profiling/types.py`.
4. Register the tool in the MCP server.

### Phase 2: Ltac profiling (addresses e2e 8.7)

1. Extend `CoqProfiler` with an Ltac backend that:
   - Wraps the target proof in `Set Ltac Profiling` / `Show Ltac Profile`.
   - Parses the profile table output.
   - Detects multi-success tactics and adds caveats.
2. Surface in the same `profile_proof` tool via `backend="ltac"`.

### Phase 3: Project-wide aggregation (addresses e2e 8.9)

1. Add a `profile_project` MCP tool (or extend `profile_proof` with a directory parameter).
2. Iterate over `.v` files, invoke sentence-level profiling on each.
3. Aggregate into ranked summaries: top N slowest files, top N slowest lemmas.

### Phase 4: Comparison and CI (addresses e2e 8.8)

1. Add a `compare_profiles` MCP tool that diffs two profiling results.
2. Flag regressions exceeding a configurable threshold.
3. Output structured JSON for CI consumption.

---

## E2E Test Coverage

| E2E Test | Description | Addressed By |
|----------|-------------|--------------|
| 8.1 | Profile ring_morph | Phase 1 |
| 8.2 | Tactic vs kernel time | Phase 1 |
| 8.3 | Top 5 slowest lemmas in a file | Phase 1 |
| 8.4 | Slowest sentences by compilation time | Phase 1 |
| 8.7 | Ltac call-tree for custom tactic | Phase 2 |
| 8.8 | Compare timings between proofs | Phase 4 (Phase 1 enables partial) |
| 8.9 | Project-wide profiling | Phase 3 |

---

## Dependencies

- Coq must be available in the container (`coqc` on `PATH`).
- For Chrome traces: Coq 8.19+ required.
- `build_project` serialization bug must be fixed first for file-level profiling (see e2e results, "Object of type BuildSystem is not JSON serializable").

## Relationship to `extract_proof_trace`

`extract_proof_trace` provides **interactive session replay timing** — useful for quick per-tactic estimates during live proof exploration. `profile_proof` provides **compilation-accurate profiling** — useful for performance optimization, bottleneck diagnosis, and CI gates. The two are complementary; neither replaces the other.
