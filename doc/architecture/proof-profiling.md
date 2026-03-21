# Proof Profiling Engine

The component that wraps Coq's profiling infrastructure (`coqc -time-file`, `Set Ltac Profiling`, `Show Ltac Profile`) to collect per-sentence and per-tactic timing data, classify bottlenecks by known performance patterns, and return structured profiling results that Claude interprets and explains. The MCP Server delegates profiling tool calls to this component; Ltac profiling uses the Proof Session Manager for interactive instrumentation.

**Feature**: [Proof Profiling](../features/proof-profiling.md)

---

## Component Diagram

```
Claude Code / LLM
  │
  │ MCP tool calls (stdio)
  ▼
MCP Server
  │
  │ profile request
  ▼
┌───────────────────────────────────────────────────────────────────┐
│                     Proof Profiling Engine                         │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ File Profiler     │  │ Timing Parser    │  │ Proof Boundary │  │
│  │                   │  │                  │  │ Detector       │  │
│  │ Spawns coqc with  │  │ Parses .timing   │  │                │  │
│  │ -time-file flag   │  │ files into       │  │ Maps char      │  │
│  │ Enforces timeout  │  │ TimingSentence[] │  │ offsets to      │  │
│  │                   │  │                  │  │ proof names    │  │
│  └────────┬─────────┘  └───────▲──────────┘  └───────▲────────┘  │
│           │                    │                      │           │
│           │ .v.timing file     │ raw timing text      │ source    │
│           ▼                    │                      │           │
│  ┌─────────────────────────────┴──────────────────────┴────────┐  │
│  │                    Subprocess Runner                          │  │
│  │    Spawns coqc, enforces timeout, captures streams           │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Ltac Profiler     │  │ Bottleneck       │  │ Timing         │  │
│  │                   │  │ Classifier       │  │ Comparator     │  │
│  │ Instruments proof │  │                  │  │                │  │
│  │ via session mgr,  │  │ Pattern-matches  │  │ Diffs two      │  │
│  │ parses Ltac       │  │ timing data →    │  │ FileProfiles   │  │
│  │ profile output    │  │ classifications  │  │ → regressions  │  │
│  └────────┬─────────┘  └──────────────────┘  └────────────────┘  │
│           │                                                       │
└───────────┼───────────────────────────────────────────────────────┘
            │ session operations
            ▼
     Proof Session Manager
            │
            ▼
     CoqBackend (per-session)
```

The Proof Profiling Engine sits between the MCP Server and the host `coqc` binary. For sentence-level timing it spawns `coqc` directly as a subprocess. For Ltac profiling it delegates to the Proof Session Manager, which owns the Coq process lifecycle. The engine does not modify any source files or build configurations.

## Boundary Contract

The Proof Profiling Engine is invoked by the MCP Server and returns structured results. It does not:

- Compile `.v` files for purposes other than profiling (that is `build_project`)
- Modify source files, Makefiles, or project configurations
- Apply optimizations or rewrite proof scripts (that is proof compression/repair)
- Persist profiling results across server restarts
- Manage proof sessions directly (it uses the Proof Session Manager's API)

It depends on:
- The `coqc` binary being available on `PATH` (for file-level profiling)
- The Proof Session Manager (for Ltac profiling)
- The Build System Adapter's detection logic (for resolving include/load paths from `_CoqProject`)

---

## MCP Tool Surface

Profiling is exposed as a single MCP tool, `profile_proof`, to minimize tool surface growth per the PRD constraint.

**ProfileRequest** — input to the tool:

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Absolute path to the `.v` file to profile |
| `lemma_name` | string or null | Profile a specific lemma; null profiles the entire file |
| `mode` | `"timing"` or `"ltac"` or `"compare"` | Profiling backend to use (default: `"timing"`) |
| `baseline_path` | string or null | Path to a `.v.timing` file for comparison (required when mode is `"compare"`) |
| `timeout_seconds` | positive integer | Wall-clock timeout for the coqc subprocess (default: 300) |

The `"timing"` mode compiles the file with `coqc -time-file` and returns per-sentence timing. The `"ltac"` mode opens a proof session, instruments with `Set Ltac Profiling`, replays the proof, and returns the call-tree. The `"compare"` mode parses a baseline `.v.timing` file, runs a fresh timing pass, and returns a diff.

---

## Data Structures

### TimingSentence

One sentence from the `coqc -time` output, enriched with source-level metadata.

| Field | Type | Description |
|-------|------|-------------|
| `char_start` | non-negative integer | Byte offset of sentence start in the source file |
| `char_end` | non-negative integer | Byte offset of sentence end |
| `line_number` | positive integer | Line number in the source file (resolved from char_start) |
| `snippet` | string | Truncated code text from the timing output (spaces replaced with `~`) |
| `real_time_s` | non-negative float | Wall-clock time in seconds |
| `user_time_s` | non-negative float | User CPU time in seconds |
| `sys_time_s` | non-negative float | System CPU time in seconds |
| `sentence_kind` | enumeration | `Import`, `Definition`, `Tactic`, `ProofOpen`, `ProofClose`, `Other` |
| `containing_proof` | string or null | Lemma name of the enclosing proof, or null for top-level sentences |

### ProofProfile

Timing for a single proof, aggregated from its constituent sentences.

| Field | Type | Description |
|-------|------|-------------|
| `lemma_name` | string | Fully qualified name of the lemma/theorem |
| `line_number` | positive integer | Line where the declaration starts |
| `tactic_sentences` | list of TimingSentence | All tactic sentences within this proof |
| `proof_close` | TimingSentence or null | The `Qed`/`Defined`/`Admitted` sentence |
| `tactic_time_s` | non-negative float | Sum of real_time_s for all tactic sentences |
| `close_time_s` | non-negative float | real_time_s for the proof-closing sentence |
| `total_time_s` | non-negative float | Sum of all sentences in this proof |
| `bottlenecks` | list of BottleneckClassification | Classified bottlenecks, if any |

### FileProfile

Timing for an entire `.v` file.

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Absolute path to the profiled `.v` file |
| `sentences` | list of TimingSentence | All sentences, in source order |
| `proofs` | list of ProofProfile | Per-proof aggregations, sorted by total_time_s descending |
| `total_time_s` | non-negative float | Total compilation time |
| `compilation_succeeded` | boolean | Whether `coqc` exited with code 0 |
| `error_message` | string or null | Compilation error, if any (timing for sentences before the error is still populated) |

### LtacProfileEntry

One row from the `Show Ltac Profile` output.

| Field | Type | Description |
|-------|------|-------------|
| `tactic_name` | string | Tactic name (may be fully qualified, e.g., `Coq.Init.Tauto.tauto_gen`) |
| `local_pct` | non-negative float | Percentage of total time in this tactic only (self time) |
| `total_pct` | non-negative float | Percentage of total time including callees |
| `calls` | positive integer | Number of invocations |
| `max_time_s` | non-negative float | Maximum wall-clock time for a single invocation |

### LtacProfile

Complete Ltac profiling result for a single proof.

| Field | Type | Description |
|-------|------|-------------|
| `lemma_name` | string | Name of the profiled lemma |
| `total_time_s` | non-negative float | Total Ltac execution time |
| `entries` | list of LtacProfileEntry | Call-tree entries, sorted by total_pct descending |
| `caveats` | list of string | Warnings about profiling accuracy (e.g., backtracking tactics, compiled Ltac2) |
| `bottlenecks` | list of BottleneckClassification | Classified bottlenecks, if any |

### BottleneckClassification

A classified performance bottleneck with pattern identification and suggestion hints.

| Field | Type | Description |
|-------|------|-------------|
| `rank` | positive integer | 1 = worst bottleneck |
| `category` | enumeration | `SlowQed`, `SlowReduction`, `TypeclassBlowup`, `HighSearchDepth`, `ExpensiveMatch`, `General` |
| `sentence` | TimingSentence or LtacProfileEntry | The flagged sentence or Ltac entry |
| `severity` | `"critical"` or `"warning"` or `"info"` | Based on time and proportion of total |
| `suggestion_hints` | list of string | Concrete optimization patterns (e.g., `"replace simpl in H with eval/replace pattern"`, `"use abstract to encapsulate sub-proof"`) |

The engine provides `category` and `suggestion_hints` as structured data. Claude generates the full natural-language explanation using these hints plus the proof context. This division mirrors how other components (assumption auditing, typeclass debugging) return classified data for Claude to interpret.

### TimingDiff

One sentence's timing change between two profiling runs.

| Field | Type | Description |
|-------|------|-------------|
| `sentence_snippet` | string | Code snippet identifying the sentence |
| `line_before` | positive integer | Line number in the baseline file |
| `line_after` | positive integer or null | Line number in the current file (null if sentence removed) |
| `time_before_s` | non-negative float | Wall-clock time in the baseline |
| `time_after_s` | non-negative float or null | Wall-clock time in the current run (null if removed) |
| `delta_s` | float | time_after - time_before |
| `delta_pct` | float or null | Percentage change (null when time_before is 0) |
| `status` | `"improved"` or `"regressed"` or `"stable"` or `"new"` or `"removed"` | Classification |

### TimingComparison

Result of comparing two profiling runs.

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Path to the profiled file |
| `baseline_total_s` | non-negative float | Total time in the baseline |
| `current_total_s` | non-negative float | Total time in the current run |
| `net_delta_s` | float | current_total - baseline_total |
| `diffs` | list of TimingDiff | Per-sentence diffs, sorted by absolute delta descending |
| `regressions` | list of TimingDiff | Sentences that regressed beyond the threshold |
| `improvements` | list of TimingDiff | Sentences that improved beyond the threshold |

---

## File Profiling

### Invocation

```
profile_file(file_path, timeout_seconds)
  │
  ├─ Validate file exists and has .v extension
  │    If not → FILE_NOT_FOUND or INVALID_FILE error
  │
  ├─ Resolve include paths:
  │    Search for _CoqProject in file's directory and ancestors
  │    If found → parse -Q, -R, -I directives
  │    (Reuses Build System Adapter's _CoqProject parser)
  │
  ├─ Generate temporary path for .timing output file
  │
  ├─ Build command:
  │    coqc [load_path_flags] [include_flags] -time-file <timing_path> <file_path>
  │
  ├─ Spawn subprocess with timeout_seconds wall-clock limit
  │    Capture stdout + stderr for error detection
  │
  ├─ On completion (any exit code):
  │    ├─ Parse timing file → list of TimingSentence (raw)
  │    ├─ Read source file → build char-offset-to-line-number map
  │    ├─ Run proof boundary detection → annotate containing_proof
  │    ├─ Classify sentence kinds from snippets
  │    ├─ Aggregate sentences into ProofProfile records
  │    ├─ Run bottleneck classifier on all sentences
  │    ├─ Sort proofs by total_time_s descending
  │    └─ Return FileProfile
  │
  ├─ On timeout:
  │    Kill process, parse partial .timing file
  │    Return FileProfile with compilation_succeeded=false
  │    and error_message indicating timeout
  │
  └─ Clean up temporary .timing file
```

### Timing Output Parsing

The `coqc -time-file` output format is one line per sentence:

```
Chars <start> - <end> [<snippet>] <real> secs (<user>u,<sys>s)
```

The parser uses the regex:

```
^Chars (\d+) - (\d+) (\S+) ([\d.]+) secs \(([\d.]+)u,([\d.]+)s\)$
```

This is the same regex used by Coq's own `TimeFileMaker.py`. Fields extracted:
- `char_start`, `char_end`: byte offsets into the source file
- `snippet`: bracket-free code text with `~` replacing spaces, truncated
- `real_time_s`, `user_time_s`, `sys_time_s`: timing values

When the timing file is truncated (due to compilation failure or timeout), the parser processes all complete lines and ignores the truncated final line.

### Character Offset to Line Number Resolution

The source file is read into memory and a byte-offset-to-line-number map is built by scanning for newline characters. For each TimingSentence, `char_start` is looked up in this map to produce `line_number`. This resolution handles UTF-8 files correctly because `coqc -time` reports byte offsets, not character offsets.

### Proof Boundary Detection

The engine identifies proof boundaries to group timing sentences by lemma. This is a source-level scan, not a full Coq parser.

```
detect_proof_boundaries(source_text)
  │
  ├─ Scan source for declaration keywords:
  │    Lemma, Theorem, Proposition, Corollary, Fact, Remark, Example,
  │    Definition, Fixpoint, CoFixpoint, Let, Instance, Program
  │
  ├─ For each match:
  │    Extract the declaration name (first identifier after keyword)
  │    Record byte offset of keyword start
  │
  ├─ Scan source for proof-closing keywords:
  │    Qed, Defined, Admitted, Abort
  │    (Must appear as a full sentence — i.e., followed by `.`)
  │
  ├─ Pair declarations with closers:
  │    Each declaration is paired with the next closer that follows it
  │    Handles nested proofs by tracking nesting depth
  │
  └─ Return list of ProofBoundary:
       { name, decl_char_start, close_char_end }
```

A TimingSentence whose `char_start` falls within `[decl_char_start, close_char_end]` of a ProofBoundary is assigned that boundary's name as its `containing_proof`. Sentences outside all boundaries have `containing_proof = null`.

### Sentence Kind Classification

The `snippet` field is used to classify each sentence:

| Snippet pattern | `sentence_kind` |
|-----------------|-----------------|
| Starts with `Require` or `Import` or `Export` | `Import` |
| Starts with `Lemma`, `Theorem`, `Definition`, etc. | `Definition` |
| Starts with `Proof` | `ProofOpen` |
| Starts with `Qed` or `Defined` or `Admitted` or `Abort` | `ProofClose` |
| Falls within a proof boundary and is none of the above | `Tactic` |
| All other | `Other` |

The snippet text has spaces replaced with `~` and is truncated, so matching uses prefix comparison on the cleaned text.

---

## Single-Proof Profiling

```
profile_single_proof(file_path, lemma_name, timeout_seconds)
  │
  ├─ Run profile_file(file_path, timeout_seconds) → FileProfile
  │
  ├─ Search FileProfile.proofs for lemma_name match
  │    Match is case-sensitive on the short name
  │    If not found → NOT_FOUND error listing available proof names
  │
  ├─ Extract the matching ProofProfile
  │
  └─ Return ProofProfile (already includes bottleneck classifications)
```

This approach profiles the entire file and filters — rather than compiling only up to the target lemma — because later sentences may affect earlier ones through `Opaque`/`Transparent` declarations, and because the overhead of compiling the full file is the same `coqc` invocation either way.

---

## Ltac Profiling

Ltac profiling requires an interactive proof session to instrument profiling commands around tactic execution.

```
profile_ltac(file_path, lemma_name, timeout_seconds)
  │
  ├─ Validate lemma_name is not null
  │    Ltac profiling requires a specific proof target
  │
  ├─ Open proof session:
  │    session_id = open_proof_session(file_path, lemma_name)
  │    Capture initial ProofState
  │
  ├─ Enable Ltac profiling:
  │    submit_command(session_id, "Set Ltac Profiling.")
  │    submit_command(session_id, "Reset Ltac Profile.")
  │
  ├─ Replay the proof:
  │    Retrieve original_script from session
  │    For each tactic in original_script:
  │      submit_tactic(session_id, tactic)
  │      On failure → stop, record partial profile
  │
  ├─ Capture Ltac profile:
  │    output = submit_command(session_id, "Show Ltac Profile CutOff 0.")
  │    Parse output → LtacProfile
  │
  ├─ Detect caveats:
  │    If output contains "may be inaccurate" warning → add backtracking caveat
  │    If any tactic is a known compiled Ltac2 entry → add Ltac2 caveat
  │
  ├─ Close proof session:
  │    close_proof_session(session_id)
  │
  ├─ Run bottleneck classifier on LtacProfile entries
  │
  └─ Return LtacProfile
```

### Ltac Profile Output Parsing

The `Show Ltac Profile` output follows this format:

```
total time: <N.NNN>s

 tactic                                   local  total   calls       max
────────────────────────────────────────┴──────┴──────┴───────┴─────────┘
─<name> -------------------------------- <L>% <T>%     <C>    <M>s
```

The parser extracts:
1. `total_time_s` from the `total time:` header line
2. For each table row: tactic name (strip leading `─` and trailing ` -+`), local percentage, total percentage, call count, and max time
3. Entries below the cutoff threshold (default 0% with `CutOff 0`) are still reported

Tree nesting is indicated by indentation depth of the `─` prefix. The parser preserves nesting structure for Claude's interpretation but flattens it in the `entries` list, sorted by `total_pct` descending.

---

## Bottleneck Classification

The Bottleneck Classifier pattern-matches against profiling results to identify known performance anti-patterns. Classification runs on both sentence-level timing and Ltac profiles.

### Classification Rules

Rules are evaluated in priority order. A sentence may match multiple rules; only the highest-priority match is reported.

| Priority | Pattern | Category | Severity Threshold | Suggestion Hints |
|----------|---------|----------|-------------------|------------------|
| 1 | `ProofClose` sentence where `close_time_s > 5 × tactic_time_s` AND `close_time_s > 2s` | `SlowQed` | critical if > 10s, warning if > 2s | `"use abstract to encapsulate expensive sub-proofs"`, `"replace simpl in H with eval/replace pattern"`, `"add Opaque directives for definitions not needed in reduction"` |
| 2 | Tactic snippet matches `simpl` or `cbn` AND `real_time_s > 2s` | `SlowReduction` | critical if > 10s, warning if > 2s | `"use lazy or cbv for controlled reduction"`, `"use change with an explicit target term"`, `"set Arguments ... : simpl never for expensive definitions"` |
| 3 | Tactic snippet matches `typeclasses eauto` or Ltac entry is `typeclasses eauto` AND time > 2s | `TypeclassBlowup` | critical if > 10s, warning if > 2s | `"use Set Typeclasses Debug to trace the search"`, `"adjust instance priorities"`, `"use Hint Cut to prune search branches"` |
| 4 | Tactic snippet matches `eauto \d+` where depth > 6 AND time > 1s | `HighSearchDepth` | critical if > 5s, warning if > 1s | `"reduce search depth"`, `"use auto where backtracking is unnecessary"`, `"provide explicit witnesses with eapply"` |
| 5 | Tactic snippet matches `match goal` or `repeat` AND time > 3s | `ExpensiveMatch` | warning if > 3s | `"simplify the match pattern"`, `"add early termination guards"` |
| 6 | Any sentence with `real_time_s > 5s` not matching above | `General` | critical if > 30s, warning if > 5s | (none — Claude generates context-specific suggestions) |

The classifier returns up to 5 bottlenecks per profiling result, ranked by `real_time_s` descending. When fewer than 5 sentences exceed the minimum threshold (2 seconds for most categories), only the qualifying sentences are classified.

### Severity Assignment

| Level | Criteria |
|-------|----------|
| `critical` | The sentence accounts for > 50% of total proof time, OR exceeds the category's critical threshold |
| `warning` | The sentence exceeds the category's warning threshold |
| `info` | The sentence is in the top 5 by time but does not exceed any threshold |

---

## Timing Comparison

```
compare_profiles(current_file_path, baseline_timing_path, timeout_seconds)
  │
  ├─ Parse baseline .v.timing file → list of baseline TimingSentence
  │    (Same parser as for fresh profiling results)
  │
  ├─ Run profile_file(current_file_path, timeout_seconds) → current FileProfile
  │
  ├─ Match baseline sentences to current sentences:
  │    Primary key: snippet text (exact match)
  │    Fallback: character offset within ±fuzz tolerance (default: 500 bytes)
  │    Unmatched baseline sentences → status = "removed"
  │    Unmatched current sentences → status = "new"
  │
  ├─ For each matched pair:
  │    delta_s = current.real_time_s - baseline.real_time_s
  │    delta_pct = delta_s / baseline.real_time_s × 100 (null if baseline is 0)
  │    status:
  │      "regressed" if delta_pct > 20 AND delta_s > 0.5
  │      "improved" if delta_pct < -20 AND delta_s < -0.5
  │      "stable" otherwise
  │
  ├─ Sort diffs by absolute delta_s descending
  │
  ├─ Partition into regressions and improvements lists
  │
  └─ Return TimingComparison
```

The 20% / 0.5s dual threshold prevents noise from dominating the report. Wall-clock timing is inherently noisy; the absolute threshold filters out sentences where a 20% change represents less than half a second of actual time.

### Snippet-Based Matching

Sentences are matched between runs by their code snippet. The snippet text from `coqc -time` includes enough of the command to uniquely identify most sentences within a file. When a snippet appears multiple times (e.g., repeated `auto.` calls), the matcher falls back to positional ordering — the Nth occurrence of a snippet in the baseline matches the Nth occurrence in the current run.

When source code changes between runs, character offsets shift. The `±fuzz` tolerance (500 bytes by default, configurable) allows approximate positional matching when snippet matching fails. This mirrors the `--fuzz` parameter in Coq's own `make-both-single-timing-files.py`.

---

## Project-Wide Profiling

Project-wide profiling is not handled by this component directly. It is orchestrated by Claude Code, which:

1. Uses `build_project` with the appropriate timing flags to compile all files with timing data (`make TIMING=1` for coq_makefile projects)
2. Collects the generated `.v.timing` files
3. Passes each to the Profiling Engine's timing parser
4. Aggregates results across files

This avoids duplicating build system logic in the Profiling Engine. The Build System Adapter already knows how to detect build systems, construct build commands, and manage subprocesses. Project-wide profiling reuses that infrastructure.

---

## Error Handling

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| `.v` file not found | `FILE_NOT_FOUND` | Return immediately, no subprocess spawned |
| File has wrong extension | `INVALID_FILE` | Return immediately with message |
| `coqc` binary not found on PATH | `TOOL_MISSING` | Return immediately: `coqc not found on PATH` |
| Compilation fails (non-zero exit, not timeout) | — | `compilation_succeeded = false`, timing data for sentences processed before the error is still returned, `error_message` populated |
| Subprocess times out | — | Kill process, parse partial timing file, `compilation_succeeded = false`, `error_message` indicates timeout |
| `.timing` file empty or missing after coqc exits | `PARSE_ERROR` | Return FileProfile with empty sentences, `error_message` indicates no timing data was produced |
| Lemma not found in file (single-proof mode) | `NOT_FOUND` | Return error listing available proof names from the file |
| Baseline `.v.timing` file not found (compare mode) | `FILE_NOT_FOUND` | Return error identifying the missing baseline path |
| Proof session fails to open (Ltac mode) | `SESSION_ERROR` | Propagate session error from Proof Session Manager |
| Ltac profile output unparseable | `PARSE_ERROR` | Return partial LtacProfile with `caveats` noting parse failure, include raw output |

All errors use the MCP standard error format defined in [mcp-server.md](mcp-server.md) § Error Contract.

---

## Design Rationale

### Why a new component rather than extending Build System Integration

Build System Integration owns the build lifecycle — invoking `make`, `dune build`, and managing project configurations. Profiling is a different concern: it collects fine-grained timing data, parses tool-specific output formats, classifies bottlenecks, and produces profiling-specific data structures. Folding this into Build System Integration would overload that component's responsibilities. The Profiling Engine is a focused adapter: it takes a `.v` file, produces a FileProfile, and returns. It reuses the Build System Adapter's `_CoqProject` parser for path resolution, but otherwise has no build system concerns.

### Why subprocess invocation for file-level profiling

`coqc -time-file` is the canonical way to collect per-sentence timing. It produces machine-parseable output in a stable format with a regex documented in Coq's own codebase (`TimeFileMaker.py`). Invoking `coqc` as a subprocess preserves the same trust model as the user's normal workflow — the timing data comes from the same compiler, with the same flags, producing the same results. No custom instrumentation is needed.

### Why Ltac profiling goes through the Proof Session Manager

`Set Ltac Profiling` and `Show Ltac Profile` are Coq vernacular commands that must be executed within an interactive Coq session, interleaved with tactic execution. The Proof Session Manager already manages Coq sessions and provides `submit_command` for vernacular commands and `submit_tactic` for tactic dispatch. Spawning a separate Coq process for Ltac profiling would duplicate session management logic and prevent sharing the file-load cost when the user also wants to interact with the proof session.

### Why classification and hints rather than full natural-language explanations

Other components in the system — assumption auditing, typeclass debugging, universe inspection — return structured, classified data that Claude interprets in context. Following the same pattern keeps the Profiling Engine focused on measurement and classification (deterministic, testable operations) while leveraging Claude's strength at contextual explanation and natural-language synthesis. The `suggestion_hints` provide domain-specific optimization patterns that Claude incorporates into its explanations; Claude adds context about the specific proof, the specific definitions involved, and the user's situation.

### Why profile the entire file even for single-proof queries

`coqc` compiles files linearly from top to bottom; there is no way to compile only a single proof in isolation. The file must be compiled in full to establish the environment the proof depends on. Compiling the whole file with `-time-file` and filtering the results to the target proof is both simpler and more accurate than attempting to compile a partial file.

### Why the dual threshold for regression detection

Wall-clock timing is noisy — system load, memory pressure, and GC timing introduce variance. A pure percentage threshold (e.g., 20%) would flag a sentence that changed from 0.01s to 0.02s as a 100% regression, even though the absolute change is negligible. A pure absolute threshold (e.g., 0.5s) would miss a proportionally large regression in a cheap sentence. The dual threshold (`delta_pct > 20% AND delta_s > 0.5s`) filters out both noise-dominated percentage swings and absolute changes that are too small to matter. This mirrors the approach used in Coq's own `pretty-timed-diff` scripts with the `TIMING_FUZZ` parameter.

### Why project-wide profiling is orchestrated by Claude, not the engine

Project-wide profiling involves build system detection, build execution with timing flags, and collecting timing files from the build output directory. The Build System Adapter already handles build detection and execution; the Profiling Engine handles timing file parsing. Orchestrating the two is a multi-step workflow that Claude handles naturally — there is no benefit to embedding this orchestration in the engine, and doing so would create a dependency from the Profiling Engine to the Build System Adapter that violates the single-responsibility boundary.

## Boundary Contracts

### MCP Server → Proof Profiling Engine

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | ProfileRequest (file path, optional lemma name, mode, timeout) |
| Output | FileProfile, ProofProfile, LtacProfile, or TimingComparison |
| Dependencies | `coqc` binary (for timing mode), Proof Session Manager (for ltac mode) |

### Proof Profiling Engine → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), reuses same SessionManager API as MCP Server |
| Direction | Request-response |
| Operations used | `open_proof_session`, `submit_command`, `submit_tactic`, `close_proof_session` |
| Lifecycle | One session per Ltac profiling request; created, used, and closed within a single profiling call |

### Proof Profiling Engine → Build System Adapter (shared logic)

| Property | Value |
|----------|-------|
| Mechanism | Shared `_CoqProject` parser function (in-process) |
| Direction | Call |
| Purpose | Resolve include paths and load path mappings from the project's `_CoqProject` file |
| Scope | Path parsing only — does not invoke build execution or dependency management functions |
