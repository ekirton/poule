# Proof Profiling

Subprocess adapter wrapping `coqc -time-file` for per-sentence timing collection, interactive Ltac profiling via the Proof Session Manager, bottleneck classification against known performance patterns, and timing comparison between profiling runs.

**Architecture**: [proof-profiling.md](../doc/architecture/proof-profiling.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the Proof Profiling Engine that compiles `.v` files with `coqc -time-file` to collect per-sentence timing, parses the timing output into structured records, detects proof boundaries in source files to group sentences by lemma, classifies bottlenecks against known performance anti-patterns, instruments proof sessions with `Set Ltac Profiling` for call-tree analysis, compares timing between profiling runs to detect regressions, and returns structured profiling results to the MCP Server.

## 2. Scope

**In scope**: ProfileRequest validation, `coqc` binary discovery, `_CoqProject` path resolution, subprocess lifecycle (spawn, timeout, kill), timing output parsing, character-offset-to-line-number resolution, proof boundary detection, sentence kind classification, proof-level aggregation, Ltac profiling via Proof Session Manager, Ltac profile output parsing, bottleneck classification, severity assignment, timing comparison with sentence matching, regression/improvement detection.

**Out of scope**: MCP protocol handling (owned by mcp-server), proof session lifecycle management (owned by proof-session), build execution and build system detection (owned by build-system-integration), proof optimization or rewriting (owned by proof compression/repair), natural-language explanation generation (performed by Claude Code), project-wide profiling orchestration (performed by Claude Code using build_project), visualization (owned by mermaid-renderer).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Sentence | A single Coq vernacular command terminated by a period — the granularity unit of `coqc -time` output |
| Proof boundary | The byte-offset range from a declaration keyword (`Lemma`, `Theorem`, etc.) to its closing keyword (`Qed`, `Defined`, `Admitted`, `Abort`) |
| Timing file | A `.v.timing` file produced by `coqc -time-file`, containing one `Chars` line per sentence |
| Snippet | The truncated code text from a timing line, with spaces replaced by `~` |
| Bottleneck | A sentence or Ltac entry whose timing exceeds a category-specific threshold and matches a known performance anti-pattern |
| Fuzz tolerance | The maximum byte-offset difference allowed when matching sentences between two profiling runs whose source has changed |
| Ltac call tree | The hierarchical tactic timing output from `Show Ltac Profile`, showing per-tactic self time, cumulative time, call count, and max single-call time |

## 4. Behavioral Requirements

### 4.1 Request Validation

#### validate_request(request: ProfileRequest)

- REQUIRES: `request` is a ProfileRequest.
- ENSURES: When `file_path` does not exist or does not end with `.v`, the engine returns a `FILE_NOT_FOUND` or `INVALID_FILE` error immediately without spawning a subprocess. When `mode` is `"ltac"` and `lemma_name` is null, the engine returns an `INVALID_REQUEST` error. When `mode` is `"compare"` and `baseline_path` is null or does not exist, the engine returns a `FILE_NOT_FOUND` error.

> **Given** a ProfileRequest with `file_path="/tmp/Missing.v"` where the file does not exist
> **When** `validate_request` is called
> **Then** a `FILE_NOT_FOUND` error is returned and no subprocess is spawned

> **Given** a ProfileRequest with `mode="ltac"` and `lemma_name=null`
> **When** `validate_request` is called
> **Then** an `INVALID_REQUEST` error is returned with message "Ltac profiling requires a lemma name"

> **Given** a ProfileRequest with `mode="compare"` and `baseline_path="/tmp/old.timing"` where the file does not exist
> **When** `validate_request` is called
> **Then** a `FILE_NOT_FOUND` error is returned identifying the missing baseline path

### 4.2 Binary Discovery

#### locate_coqc()

- REQUIRES: None.
- ENSURES: Returns the absolute path to the `coqc` binary by searching the system `PATH`. When `coqc` is not found, the engine returns a `TOOL_MISSING` error with message `"coqc not found on PATH"` without spawning a subprocess.

> **Given** `coqc` is not on the system PATH
> **When** `locate_coqc` is called
> **Then** a `TOOL_MISSING` error with message `"coqc not found on PATH"` is returned

### 4.3 Path Resolution

#### resolve_paths(file_path)

- REQUIRES: `file_path` is an absolute path to an existing `.v` file.
- ENSURES: Searches for a `_CoqProject` file in the directory containing `file_path` and ancestor directories. When found, parses `-Q`, `-R`, and `-I` directives to extract load path mappings and include paths. Returns a tuple of `(load_paths, include_paths)`. When no `_CoqProject` is found, returns empty lists for both.
- MAINTAINS: Reuses the Build System Adapter's `_CoqProject` parser. Does not invoke build execution or dependency management. Parse errors in `_CoqProject` are logged as warnings; the engine returns empty paths on parse failure.

> **Given** a `.v` file at `/project/theories/Foo.v` with a `_CoqProject` in `/project/` containing `-Q theories MyLib`
> **When** `resolve_paths` is called
> **Then** `load_paths` is `[("MyLib", "/project/theories")]` and `include_paths` is `[]`

> **Given** a `.v` file at `/tmp/Scratch.v` with no `_CoqProject` in any ancestor directory
> **When** `resolve_paths` is called
> **Then** both `load_paths` and `include_paths` are empty lists

### 4.4 File Profiling

#### profile_file(file_path, timeout_seconds)

- REQUIRES: `file_path` is an absolute path to an existing `.v` file. `timeout_seconds` is a positive integer (default 300).
- ENSURES: Resolves include paths via `resolve_paths`. Generates a temporary path for the timing output. Builds the command `coqc [load_path_flags] [include_flags] -time-file <timing_path> <file_path>`. Spawns the subprocess with the wall-clock timeout. On completion (any exit code), parses the timing file via `parse_timing_output`, reads the source file to resolve line numbers via `resolve_line_numbers`, detects proof boundaries via `detect_proof_boundaries`, classifies sentence kinds, aggregates sentences into ProofProfile records, runs the bottleneck classifier, sorts proofs by `total_time_s` descending, and returns a FileProfile. Cleans up the temporary timing file before returning.
- MAINTAINS: On compilation failure (non-zero exit), `compilation_succeeded` is `false`, `error_message` contains the compiler error, and timing data for sentences processed before the error is still populated. On timeout, the subprocess is killed, partial timing data is parsed, `compilation_succeeded` is `false`, and `error_message` indicates the timeout.

> **Given** a `.v` file with 3 lemmas where `slow_lemma` takes 15s and the other two take 0.1s each
> **When** `profile_file` is called with `timeout_seconds=300`
> **Then** the returned FileProfile has `compilation_succeeded=true`, `proofs` sorted with `slow_lemma` first, and `total_time_s` approximately 15.2

> **Given** a `.v` file that fails to compile at line 50
> **When** `profile_file` is called
> **Then** the returned FileProfile has `compilation_succeeded=false`, `error_message` containing the Coq error, and `sentences` populated for all lines before line 50

> **Given** a `.v` file whose compilation exceeds `timeout_seconds=10`
> **When** the timeout triggers
> **Then** the subprocess is killed, partial timing data is parsed, and the FileProfile has `compilation_succeeded=false` and `error_message="Compilation timed out after 10 seconds"`

### 4.5 Timing Output Parsing

#### parse_timing_output(timing_text)

- REQUIRES: `timing_text` is a string (possibly empty, possibly truncated).
- ENSURES: Parses each line matching the regex `^Chars (\d+) - (\d+) (\S+) ([\d.]+) secs \(([\d.]+)u,([\d.]+)s\)$` into a TimingSentence with `char_start`, `char_end`, `snippet`, `real_time_s`, `user_time_s`, `sys_time_s`. Lines not matching the regex are skipped. Returns a list of TimingSentence in source order (ascending `char_start`).
- MAINTAINS: The regex is identical to the one used by Coq's `TimeFileMaker.py`. Empty input produces an empty list. Truncated final lines (from timeout) are skipped without error.

> **Given** timing text `Chars 0 - 26 [Require~Coq.ZArith.BinInt.] 0.157 secs (0.128u,0.028s)`
> **When** `parse_timing_output` is called
> **Then** one TimingSentence is returned with `char_start=0`, `char_end=26`, `snippet="[Require~Coq.ZArith.BinInt.]"`, `real_time_s=0.157`, `user_time_s=0.128`, `sys_time_s=0.028`

> **Given** empty timing text
> **When** `parse_timing_output` is called
> **Then** an empty list is returned

### 4.6 Line Number Resolution

#### resolve_line_numbers(sentences, source_bytes)

- REQUIRES: `sentences` is a list of TimingSentence with populated `char_start`. `source_bytes` is the raw bytes of the source `.v` file.
- ENSURES: Builds a byte-offset-to-line-number map by scanning `source_bytes` for newline characters. For each sentence, sets `line_number` to the 1-based line number corresponding to `char_start`. Handles UTF-8 files correctly because `coqc -time` reports byte offsets.

> **Given** a source file whose first newline is at byte 25 and a sentence with `char_start=30`
> **When** `resolve_line_numbers` is called
> **Then** the sentence's `line_number` is 2

### 4.7 Proof Boundary Detection

#### detect_proof_boundaries(source_text)

- REQUIRES: `source_text` is the full text content of a `.v` file.
- ENSURES: Scans `source_text` for declaration keywords (`Lemma`, `Theorem`, `Proposition`, `Corollary`, `Fact`, `Remark`, `Example`, `Definition`, `Fixpoint`, `CoFixpoint`, `Let`, `Instance`, `Program`) and proof-closing keywords (`Qed`, `Defined`, `Admitted`, `Abort`) that appear as complete sentences (followed by `.`). Extracts the declaration name as the first identifier after each declaration keyword. Pairs each declaration with the next closer that follows it. Returns a list of ProofBoundary records `{ name, decl_char_start, close_char_end }`.
- MAINTAINS: This is a heuristic source-level scan, not a full Coq parser. Nested `Section`/`Module` proofs are handled by tracking nesting depth. Definitions without proof bodies (e.g., `Definition x := 5.`) produce no boundary because no closer follows before the next declaration.

> **Given** source text `Lemma foo : True.\nProof.\nexact I.\nQed.\n`
> **When** `detect_proof_boundaries` is called
> **Then** one ProofBoundary is returned with `name="foo"`, `decl_char_start=0`, and `close_char_end` pointing past the period of `Qed.`

> **Given** source text with `Definition x := 5.` followed by `Lemma bar : False -> True.`
> **When** `detect_proof_boundaries` is called
> **Then** `x` does not appear in the boundaries (no closer follows before the next declaration)

### 4.8 Sentence Kind Classification

#### classify_sentence(sentence, proof_boundaries)

- REQUIRES: `sentence` is a TimingSentence. `proof_boundaries` is a list of ProofBoundary.
- ENSURES: Sets `sentence_kind` and `containing_proof` based on snippet prefix matching and proof boundary membership per the classification table:

| Snippet prefix (after `~` → space normalization) | `sentence_kind` |
|--------------------------------------------------|-----------------|
| `Require`, `Import`, `Export` | `Import` |
| `Lemma`, `Theorem`, `Proposition`, `Corollary`, `Fact`, `Remark`, `Example`, `Definition`, `Fixpoint`, `CoFixpoint`, `Let`, `Instance`, `Program` | `Definition` |
| `Proof` | `ProofOpen` |
| `Qed`, `Defined`, `Admitted`, `Abort` | `ProofClose` |
| Within a proof boundary and none of the above | `Tactic` |
| All other | `Other` |

When `char_start` falls within `[decl_char_start, close_char_end]` of a ProofBoundary, `containing_proof` is set to that boundary's `name`. Otherwise `containing_proof` is null.

### 4.9 Single-Proof Profiling

#### profile_single_proof(file_path, lemma_name, timeout_seconds)

- REQUIRES: `file_path` is an absolute path to an existing `.v` file. `lemma_name` is a non-null string. `timeout_seconds` is a positive integer.
- ENSURES: Calls `profile_file` to obtain a FileProfile. Searches `FileProfile.proofs` for a ProofProfile whose `lemma_name` matches the request (case-sensitive on the short name). Returns the matching ProofProfile with bottleneck classifications. When no match is found, returns a `NOT_FOUND` error listing the available proof names.

> **Given** a file containing lemmas `foo`, `bar`, `baz` and a request for `lemma_name="bar"`
> **When** `profile_single_proof` is called
> **Then** the ProofProfile for `bar` is returned with timing for its tactic sentences and proof-close sentence

> **Given** a file containing lemmas `foo` and `bar` and a request for `lemma_name="nonexistent"`
> **When** `profile_single_proof` is called
> **Then** a `NOT_FOUND` error is returned with message listing `foo` and `bar` as available proofs

### 4.10 Ltac Profiling

#### profile_ltac(file_path, lemma_name, timeout_seconds)

- REQUIRES: `file_path` is an absolute path to an existing `.v` file. `lemma_name` is a non-null string. `timeout_seconds` is a positive integer.
- ENSURES: Opens a proof session for the specified lemma via `open_proof_session`. Submits `Set Ltac Profiling.` and `Reset Ltac Profile.` via `submit_command`. Retrieves `original_script` from the session and replays each tactic via `submit_tactic`. After replay (or on tactic failure, with partial replay), submits `Show Ltac Profile CutOff 0.` via `submit_command`. Parses the output via `parse_ltac_profile`. Detects caveats by scanning output for the `"may be inaccurate"` warning and checking for compiled Ltac2 entries. Closes the proof session. Runs the bottleneck classifier on the LtacProfile entries. Returns the LtacProfile.
- MAINTAINS: On tactic failure during replay, the profile is captured for the tactics that executed successfully. The session is always closed, even on failure (via finally/cleanup). Caveats are informational and do not prevent the profile from being returned.

> **Given** a proof with 5 Ltac tactics where `my_solver` uses 80% of total time
> **When** `profile_ltac` is called
> **Then** the LtacProfile has `entries` with `my_solver` first (sorted by `total_pct`), a bottleneck classification for `my_solver`, and `caveats` is empty

> **Given** a proof that uses `eauto` (a multi-success tactic)
> **When** `profile_ltac` is called
> **Then** the LtacProfile includes a caveat: `"Ltac profiler may report inaccurate times for backtracking tactics (eauto, typeclasses eauto). See Coq issue #12196."`

### 4.11 Ltac Profile Parsing

#### parse_ltac_profile(output_text)

- REQUIRES: `output_text` is the string output from `Show Ltac Profile CutOff 0.`
- ENSURES: Extracts `total_time_s` from the `total time: <N.NNN>s` header. Parses each table row to extract `tactic_name` (stripping leading `─` characters and trailing padding), `local_pct`, `total_pct`, `calls`, and `max_time_s`. Returns an LtacProfile with entries sorted by `total_pct` descending.
- MAINTAINS: Tree nesting (indicated by indentation depth of `─` prefix) is flattened in the entries list. When `output_text` is empty or unparseable, returns an LtacProfile with `total_time_s=0`, empty `entries`, and a caveat noting the parse failure.

> **Given** Ltac profile output with header `total time: 2.500s` and rows for `omega` (23.6%, 28 calls) and `tauto` (5.2%, 3 calls)
> **When** `parse_ltac_profile` is called
> **Then** `total_time_s=2.5`, entries has `omega` first with `total_pct=23.6`, `calls=28`

### 4.12 Bottleneck Classification

#### classify_bottlenecks(items, total_time_s)

- REQUIRES: `items` is a list of TimingSentence or LtacProfileEntry. `total_time_s` is the total profiling time.
- ENSURES: Evaluates each item against the classification rules in priority order (1 = highest). Each item matches at most one rule (the highest-priority match). Returns up to 5 BottleneckClassification records, ranked by `real_time_s` (or `total_pct × total_time_s` for Ltac entries) descending.

**Classification rules** (evaluated in priority order):

| Priority | Category | Trigger condition | Severity thresholds |
|----------|----------|-------------------|-------------------|
| 1 | `SlowQed` | `sentence_kind == ProofClose` AND `close_time_s > 5 × tactic_time_s` AND `close_time_s > 2s` | critical > 10s, warning > 2s |
| 2 | `SlowReduction` | snippet matches `simpl` or `cbn` AND `real_time_s > 2s` | critical > 10s, warning > 2s |
| 3 | `TypeclassBlowup` | snippet or tactic name matches `typeclasses eauto` AND time > 2s | critical > 10s, warning > 2s |
| 4 | `HighSearchDepth` | snippet matches `eauto \d+` with depth > 6 AND `real_time_s > 1s` | critical > 5s, warning > 1s |
| 5 | `ExpensiveMatch` | snippet matches `match goal` or `repeat` AND `real_time_s > 3s` | warning > 3s |
| 6 | `General` | `real_time_s > 5s` and no higher-priority match | critical > 30s, warning > 5s |

**Severity assignment:**

| Level | Criteria |
|-------|----------|
| `critical` | Item accounts for > 50% of `total_time_s`, OR exceeds the category's critical threshold |
| `warning` | Item exceeds the category's warning threshold but not the critical criteria |
| `info` | Item is in the top 5 by time but does not exceed any threshold |

**Suggestion hints per category:**

| Category | `suggestion_hints` |
|----------|-------------------|
| `SlowQed` | `["use abstract to encapsulate expensive sub-proofs", "replace simpl in H with eval/replace pattern", "add Opaque directives for definitions not needed in reduction"]` |
| `SlowReduction` | `["use lazy or cbv for controlled reduction", "use change with an explicit target term", "set Arguments ... : simpl never for expensive definitions"]` |
| `TypeclassBlowup` | `["use Set Typeclasses Debug to trace the search", "adjust instance priorities", "use Hint Cut to prune search branches"]` |
| `HighSearchDepth` | `["reduce search depth", "use auto where backtracking is unnecessary", "provide explicit witnesses with eapply"]` |
| `ExpensiveMatch` | `["simplify the match pattern", "add early termination guards"]` |
| `General` | `[]` (Claude generates context-specific suggestions) |

> **Given** a ProofProfile where Qed takes 30s and total tactic time is 2s
> **When** `classify_bottlenecks` is called
> **Then** one BottleneckClassification is returned with `category=SlowQed`, `severity="critical"`, `rank=1`

> **Given** a ProofProfile where `simpl in *.` takes 8s and `auto.` takes 3s
> **When** `classify_bottlenecks` is called
> **Then** two BottleneckClassifications are returned: rank 1 is `SlowReduction` (8s, warning), rank 2 is `General` (3s, info if under 5s)

### 4.13 Timing Comparison

#### compare_profiles(current_file_path, baseline_timing_path, timeout_seconds)

- REQUIRES: `current_file_path` is an absolute path to an existing `.v` file. `baseline_timing_path` is an absolute path to an existing `.v.timing` file. `timeout_seconds` is a positive integer.
- ENSURES: Parses the baseline timing file via `parse_timing_output`. Runs `profile_file` on the current file. Matches baseline sentences to current sentences via `match_sentences`. Computes `delta_s` and `delta_pct` for each matched pair. Classifies each pair as `"regressed"` (delta_pct > 20 AND delta_s > 0.5), `"improved"` (delta_pct < -20 AND delta_s < -0.5), or `"stable"`. Unmatched baseline sentences are `"removed"`; unmatched current sentences are `"new"`. Sorts diffs by absolute `delta_s` descending. Returns a TimingComparison.

> **Given** a baseline where `auto.` takes 1.0s and a current run where `auto.` takes 2.5s
> **When** `compare_profiles` is called
> **Then** the TimingDiff for `auto.` has `delta_s=1.5`, `delta_pct=150.0`, `status="regressed"`

> **Given** a baseline where `simpl.` takes 0.01s and a current run where `simpl.` takes 0.02s
> **When** `compare_profiles` is called
> **Then** the TimingDiff for `simpl.` has `delta_pct=100.0` but `delta_s=0.01`, so `status="stable"` (below the 0.5s absolute threshold)

> **Given** a baseline with 10 sentences and a current run with 12 sentences (2 new)
> **When** `compare_profiles` is called
> **Then** the 2 unmatched current sentences have `status="new"` with `time_before_s=null`

### 4.14 Sentence Matching

#### match_sentences(baseline_sentences, current_sentences, fuzz_bytes)

- REQUIRES: `baseline_sentences` and `current_sentences` are lists of TimingSentence. `fuzz_bytes` is a non-negative integer (default 500).
- ENSURES: Matches sentences between the two lists using a two-pass strategy:
  1. **Snippet match**: For each baseline sentence, find a current sentence with an identical `snippet`. When a snippet appears N times in the baseline, match the Kth baseline occurrence to the Kth current occurrence (positional ordering within duplicate snippets).
  2. **Fuzz match**: For unmatched baseline sentences, find a current sentence whose `char_start` is within `±fuzz_bytes` of the baseline sentence's `char_start`, and whose `snippet` has not already been matched.
- Returns a list of matched pairs plus lists of unmatched baseline and unmatched current sentences.

> **Given** baseline with `[auto.]` at char 100 and current with `[auto.]` at char 105
> **When** `match_sentences` is called
> **Then** the two sentences are matched by snippet

> **Given** baseline with three `[auto.]` sentences and current with three `[auto.]` sentences
> **When** `match_sentences` is called
> **Then** the first baseline `auto.` matches the first current `auto.`, second to second, third to third

## 5. Data Model

### ProfileRequest

| Field | Type | Constraints |
|-------|------|-------------|
| `file_path` | string | Required; absolute path ending in `.v` |
| `lemma_name` | string or null | Required when mode is `"ltac"`; optional for `"timing"` (null profiles entire file) |
| `mode` | `"timing"` or `"ltac"` or `"compare"` | Optional; default `"timing"` |
| `baseline_path` | string or null | Required when mode is `"compare"`; absolute path to a `.v.timing` file |
| `timeout_seconds` | positive integer | Optional; default 300; minimum 1; maximum 3600 |

### TimingSentence

| Field | Type | Constraints |
|-------|------|-------------|
| `char_start` | non-negative integer | Required; byte offset in source |
| `char_end` | non-negative integer | Required; `char_end > char_start` |
| `line_number` | positive integer | Required; resolved from `char_start` and source content |
| `snippet` | string | Required; non-empty; spaces replaced with `~`, truncated by `coqc` |
| `real_time_s` | non-negative float | Required |
| `user_time_s` | non-negative float | Required |
| `sys_time_s` | non-negative float | Required |
| `sentence_kind` | `Import`, `Definition`, `ProofOpen`, `ProofClose`, `Tactic`, `Other` | Required |
| `containing_proof` | string or null | Null for top-level sentences; lemma name for sentences within a proof |

### ProofProfile

| Field | Type | Constraints |
|-------|------|-------------|
| `lemma_name` | string | Required; non-empty |
| `line_number` | positive integer | Required |
| `tactic_sentences` | list of TimingSentence | Required; may be empty (for proofs with no tactics before `Qed`) |
| `proof_close` | TimingSentence or null | Null when proof was not closed (e.g., compilation failed mid-proof) |
| `tactic_time_s` | non-negative float | Required; sum of `real_time_s` for all `tactic_sentences` |
| `close_time_s` | non-negative float | Required; `proof_close.real_time_s` or 0 if `proof_close` is null |
| `total_time_s` | non-negative float | Required; `tactic_time_s + close_time_s` plus declaration/proof-open time |
| `bottlenecks` | list of BottleneckClassification | Required; up to 5 entries; empty when no bottleneck thresholds are met |

### FileProfile

| Field | Type | Constraints |
|-------|------|-------------|
| `file_path` | string | Required; absolute path |
| `sentences` | list of TimingSentence | Required; in source order (ascending `char_start`); may be empty |
| `proofs` | list of ProofProfile | Required; sorted by `total_time_s` descending; may be empty |
| `total_time_s` | non-negative float | Required; sum of `real_time_s` for all sentences |
| `compilation_succeeded` | boolean | Required |
| `error_message` | string or null | Null when compilation succeeded |

### LtacProfileEntry

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic_name` | string | Required; non-empty |
| `local_pct` | non-negative float | Required; 0.0 to 100.0 |
| `total_pct` | non-negative float | Required; 0.0 to 100.0; `total_pct >= local_pct` |
| `calls` | positive integer | Required |
| `max_time_s` | non-negative float | Required |

### LtacProfile

| Field | Type | Constraints |
|-------|------|-------------|
| `lemma_name` | string | Required; non-empty |
| `total_time_s` | non-negative float | Required |
| `entries` | list of LtacProfileEntry | Required; sorted by `total_pct` descending; may be empty |
| `caveats` | list of string | Required; may be empty |
| `bottlenecks` | list of BottleneckClassification | Required; up to 5 entries |

### BottleneckClassification

| Field | Type | Constraints |
|-------|------|-------------|
| `rank` | positive integer | Required; 1 = worst bottleneck; unique within a profiling result |
| `category` | `SlowQed`, `SlowReduction`, `TypeclassBlowup`, `HighSearchDepth`, `ExpensiveMatch`, `General` | Required |
| `sentence` | TimingSentence or LtacProfileEntry | Required; the flagged item |
| `severity` | `"critical"` or `"warning"` or `"info"` | Required |
| `suggestion_hints` | list of string | Required; may be empty (for `General` category) |

### TimingDiff

| Field | Type | Constraints |
|-------|------|-------------|
| `sentence_snippet` | string | Required |
| `line_before` | positive integer | Required |
| `line_after` | positive integer or null | Null when sentence was removed |
| `time_before_s` | non-negative float | Required |
| `time_after_s` | non-negative float or null | Null when sentence was removed |
| `delta_s` | float | Required; `time_after_s - time_before_s` |
| `delta_pct` | float or null | Null when `time_before_s` is 0 |
| `status` | `"improved"`, `"regressed"`, `"stable"`, `"new"`, `"removed"` | Required |

### TimingComparison

| Field | Type | Constraints |
|-------|------|-------------|
| `file_path` | string | Required |
| `baseline_total_s` | non-negative float | Required |
| `current_total_s` | non-negative float | Required |
| `net_delta_s` | float | Required; `current_total_s - baseline_total_s` |
| `diffs` | list of TimingDiff | Required; sorted by absolute `delta_s` descending |
| `regressions` | list of TimingDiff | Required; subset of `diffs` with `status="regressed"` |
| `improvements` | list of TimingDiff | Required; subset of `diffs` with `status="improved"` |

### Invariants

- `FileProfile.total_time_s` equals the sum of `real_time_s` for all entries in `sentences`.
- `ProofProfile.total_time_s >= ProofProfile.tactic_time_s + ProofProfile.close_time_s`.
- `ProofProfile.bottlenecks` has at most 5 entries; each has a unique `rank` from 1 to N.
- `TimingComparison.regressions` and `TimingComparison.improvements` are disjoint subsets of `TimingComparison.diffs`.
- When `FileProfile.compilation_succeeded` is true, `error_message` is null.

## 6. Interface Contracts

### MCP Server → Proof Profiling Engine

| Property | Value |
|----------|-------|
| Operation | `profile_proof(request: ProfileRequest) -> FileProfile or ProofProfile or LtacProfile or TimingComparison` |
| Input | A ProfileRequest (MCP server performs protocol-level validation; engine performs domain-level validation) |
| Output | One of FileProfile, ProofProfile, LtacProfile, or TimingComparison depending on mode and lemma_name |
| Concurrency | Serialized per file; concurrent requests for different files may run independent subprocesses |
| Error strategy | Validation errors and tool-missing errors are returned as MCP standard errors. Compilation failures are captured in the FileProfile (not raised as exceptions). |
| Idempotency | Yes for timing mode; the same file with the same Coq version produces equivalent timing (modulo wall-clock noise). Ltac mode may produce slightly different profiles due to profiler overhead. |

### Proof Profiling Engine → coqc Binary

| Property | Value |
|----------|-------|
| Invocation | Single subprocess per profile_file call |
| Streams captured | stdout and stderr (both fully buffered until process exit or timeout) |
| Timing output | Written to a temporary `.v.timing` file via `-time-file` flag |
| Timeout enforcement | Wall-clock timeout; on expiry the process is killed (SIGKILL after grace period) |
| Exit code interpretation | 0 = successful compilation with full timing; non-zero = compilation error with partial timing |

### Proof Profiling Engine → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `open_proof_session`, `submit_command`, `submit_tactic`, `close_proof_session` |
| Concurrency | Serialized — one tactic submission at a time per session |
| Session lifecycle | One session per Ltac profiling request; created, instrumented, replayed, profiled, and closed within a single `profile_ltac` call |
| Session state on completion | Session is always closed (via cleanup/finally), whether profiling succeeds or fails |
| Error strategy | `SESSION_NOT_FOUND` → propagate as `SESSION_ERROR`. `BACKEND_CRASHED` → propagate as `SESSION_ERROR`. `TACTIC_ERROR` during replay → capture partial Ltac profile before closing. |

### Proof Profiling Engine → Build System Adapter (shared logic)

| Property | Value |
|----------|-------|
| Mechanism | Shared `_CoqProject` parser function (in-process) |
| Direction | Call |
| Purpose | Resolve include paths and load path mappings from `_CoqProject` |
| Scope | Path parsing only — does not invoke build execution |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Behavior |
|-----------|----------|
| `file_path` does not exist | Return `FILE_NOT_FOUND` error |
| `file_path` does not end in `.v` | Return `INVALID_FILE` error with message identifying the wrong extension |
| `lemma_name` is null when mode is `"ltac"` | Return `INVALID_REQUEST` error: "Ltac profiling requires a lemma name" |
| `baseline_path` is null when mode is `"compare"` | Return `INVALID_REQUEST` error: "Compare mode requires a baseline timing file" |
| `baseline_path` does not exist when mode is `"compare"` | Return `FILE_NOT_FOUND` error identifying the baseline path |
| `timeout_seconds` < 1 | Clamp to 1 |
| `timeout_seconds` > 3600 | Clamp to 3600 |

### 7.2 Dependency Errors

| Condition | Behavior |
|-----------|----------|
| `coqc` binary not found on PATH | Return `TOOL_MISSING` error: "coqc not found on PATH" |
| `coqc` subprocess crashes (signal, not exit code) | Kill process, parse partial timing, return FileProfile with `compilation_succeeded=false` |
| `coqc` subprocess times out | Kill process, parse partial timing, return FileProfile with `compilation_succeeded=false` and `error_message` indicating timeout |
| Proof session fails to open (Ltac mode) | Return `SESSION_ERROR` propagating the session manager's error |
| Proof session backend crashes during Ltac replay | Capture partial Ltac profile, close session, return LtacProfile with caveat noting the crash |

### 7.3 Parse Errors

| Condition | Behavior |
|-----------|----------|
| Timing file empty or missing after `coqc` exits | Return FileProfile with empty `sentences` and `error_message` noting no timing data |
| Timing file contains no parseable lines | Return FileProfile with empty `sentences` and `error_message` noting parse failure |
| Ltac profile output unparseable | Return LtacProfile with `total_time_s=0`, empty `entries`, and caveat noting parse failure |
| `_CoqProject` contains parse errors | Log warning; proceed with empty paths |

### 7.4 Edge Cases

| Condition | Behavior |
|-----------|----------|
| `.v` file with no proofs (only definitions/imports) | Return FileProfile with empty `proofs` list; `sentences` populated normally |
| Lemma name not found in file (single-proof mode) | Return `NOT_FOUND` error listing available proof names |
| File compiles to zero sentences (empty file) | Return FileProfile with empty `sentences`, `total_time_s=0`, `compilation_succeeded=true` |
| Proof has no tactics (e.g., `Lemma foo : True. Proof. exact I. Qed.` — single tactic) | ProofProfile has 1 entry in `tactic_sentences` |
| Multiple proofs with the same name in one file | Return the first match; this mirrors Coq's own behavior for duplicate names |
| Baseline and current files have different numbers of sentences | Unmatched sentences classified as `"new"` or `"removed"` in TimingComparison |
| All sentences below bottleneck thresholds | `bottlenecks` list is empty |

## 8. Non-Functional Requirements

- The engine shall impose no more than 100 ms of overhead beyond the `coqc` subprocess execution time for timing output parsing, line number resolution, proof boundary detection, sentence classification, and aggregation combined.
- Timing output parsing shall complete in under 50 ms for files producing up to 10,000 timing lines.
- Proof boundary detection shall complete in under 50 ms for source files up to 100,000 lines.
- Bottleneck classification shall complete in under 10 ms for up to 10,000 sentences.
- Sentence matching (for comparison) shall complete in under 100 ms for files with up to 10,000 sentences each.
- The engine shall not buffer more than 64 MB of `coqc` output in memory. When output exceeds this limit, stdout/stderr are truncated.
- The engine shall not spawn more than one `coqc` process per profiling request.
- Temporary `.v.timing` files shall be cleaned up on all exit paths (success, failure, timeout).

## 9. Examples

### File profiling — slow Qed

```
profile_proof(ProfileRequest(
  file_path="/project/theories/SlowProof.v",
  lemma_name=null,
  mode="timing",
  timeout_seconds=300
))

coqc invocation:
  coqc -Q /project/theories MyLib -time-file /tmp/abc123.timing /project/theories/SlowProof.v

coqc exit code: 0
Timing file contents:
  Chars 0 - 35 [Require~Import~Coq.Arith.Arith.] 0.120 secs (0.110u,0.010s)
  Chars 37 - 80 [Lemma~slow_add~:~forall~n,~n~+~...] 0.001 secs (0.001u,0.000s)
  Chars 82 - 88 [Proof.] 0.000 secs (0.000u,0.000s)
  Chars 90 - 102 [simpl~in~*.] 0.003 secs (0.003u,0.000s)
  Chars 104 - 110 [lia.] 0.050 secs (0.050u,0.000s)
  Chars 112 - 116 [Qed.] 15.200 secs (15.100u,0.100s)

Source file: 6 lines, proof boundary detected for "slow_add" (chars 37-116)

Result:
{
  "file_path": "/project/theories/SlowProof.v",
  "sentences": [... 6 TimingSentence records ...],
  "proofs": [
    {
      "lemma_name": "slow_add",
      "line_number": 2,
      "tactic_sentences": [
        {"snippet": "[simpl~in~*.]", "real_time_s": 0.003, "sentence_kind": "Tactic", ...},
        {"snippet": "[lia.]", "real_time_s": 0.050, "sentence_kind": "Tactic", ...}
      ],
      "proof_close": {"snippet": "[Qed.]", "real_time_s": 15.200, "sentence_kind": "ProofClose", ...},
      "tactic_time_s": 0.053,
      "close_time_s": 15.200,
      "total_time_s": 15.254,
      "bottlenecks": [
        {
          "rank": 1,
          "category": "SlowQed",
          "severity": "critical",
          "suggestion_hints": [
            "use abstract to encapsulate expensive sub-proofs",
            "replace simpl in H with eval/replace pattern",
            "add Opaque directives for definitions not needed in reduction"
          ]
        }
      ]
    }
  ],
  "total_time_s": 15.374,
  "compilation_succeeded": true,
  "error_message": null
}
```

### Single-proof profiling — lemma not found

```
profile_proof(ProfileRequest(
  file_path="/project/theories/Foo.v",
  lemma_name="nonexistent",
  mode="timing"
))

File compiles successfully. Proofs found: ["add_comm", "add_assoc", "mul_comm"]

Result: NOT_FOUND error
{
  "error_code": "NOT_FOUND",
  "message": "Lemma 'nonexistent' not found in /project/theories/Foo.v. Available proofs: add_comm, add_assoc, mul_comm"
}
```

### Ltac profiling — backtracking caveat

```
profile_proof(ProfileRequest(
  file_path="/project/theories/Auto.v",
  lemma_name="auto_example",
  mode="ltac",
  timeout_seconds=60
))

Session opened, Ltac profiling enabled, proof replayed.
Show Ltac Profile CutOff 0. output:

  total time: 3.200s

   tactic                    local  total   calls       max
  ─omega ------------------- 45.0%  45.0%      12    0.200s
  ─eauto ------------------- 30.0%  30.0%       8    0.300s
  ─simpl ------------------- 15.0%  15.0%      20    0.050s
  ─intro --------------------  5.0%   5.0%      15    0.002s

  Warning: Ltac profiler encountered backtracking into a tactic;
  profiling results may be inaccurate.

Result:
{
  "lemma_name": "auto_example",
  "total_time_s": 3.200,
  "entries": [
    {"tactic_name": "omega", "local_pct": 45.0, "total_pct": 45.0, "calls": 12, "max_time_s": 0.200},
    {"tactic_name": "eauto", "local_pct": 30.0, "total_pct": 30.0, "calls": 8, "max_time_s": 0.300},
    {"tactic_name": "simpl", "local_pct": 15.0, "total_pct": 15.0, "calls": 20, "max_time_s": 0.050},
    {"tactic_name": "intro", "local_pct": 5.0, "total_pct": 5.0, "calls": 15, "max_time_s": 0.002}
  ],
  "caveats": [
    "Ltac profiler may report inaccurate times for backtracking tactics (eauto, typeclasses eauto). See Coq issue #12196."
  ],
  "bottlenecks": [
    {"rank": 1, "category": "General", "severity": "warning", "suggestion_hints": []}
  ]
}
```

### Timing comparison — regression detected

```
profile_proof(ProfileRequest(
  file_path="/project/theories/Foo.v",
  mode="compare",
  baseline_path="/project/theories/Foo.v.before-timing",
  timeout_seconds=300
))

Baseline parsed: 5 sentences, total 2.5s
Current profiled: 5 sentences, total 8.3s
Sentence matching: all 5 matched by snippet

Result:
{
  "file_path": "/project/theories/Foo.v",
  "baseline_total_s": 2.5,
  "current_total_s": 8.3,
  "net_delta_s": 5.8,
  "diffs": [
    {"sentence_snippet": "[Qed.]", "time_before_s": 1.0, "time_after_s": 6.5, "delta_s": 5.5, "delta_pct": 550.0, "status": "regressed"},
    {"sentence_snippet": "[simpl.]", "time_before_s": 0.5, "time_after_s": 0.8, "delta_s": 0.3, "delta_pct": 60.0, "status": "stable"},
    {"sentence_snippet": "[auto.]", "time_before_s": 0.5, "time_after_s": 0.5, "delta_s": 0.0, "delta_pct": 0.0, "status": "stable"},
    {"sentence_snippet": "[Proof.]", "time_before_s": 0.0, "time_after_s": 0.0, "delta_s": 0.0, "delta_pct": null, "status": "stable"},
    {"sentence_snippet": "[Require~Import~Arith.]", "time_before_s": 0.5, "time_after_s": 0.5, "delta_s": 0.0, "delta_pct": 0.0, "status": "stable"}
  ],
  "regressions": [
    {"sentence_snippet": "[Qed.]", "delta_s": 5.5, "delta_pct": 550.0, "status": "regressed"}
  ],
  "improvements": []
}
```

## 10. Language-Specific Notes (Python)

- Use `asyncio.create_subprocess_exec` to spawn `coqc`, enabling non-blocking stdout/stderr capture and timeout enforcement via `asyncio.wait_for`.
- Use `shutil.which("coqc")` for binary discovery on PATH.
- Use `pathlib.Path` for all path manipulation: suffix checking (`.suffix == ".v"`), parent traversal for `_CoqProject` discovery.
- Use `tempfile.NamedTemporaryFile(suffix=".timing", delete=False)` for the timing output file; clean up in a `finally` block.
- Compile the timing regex `re.compile(r'^Chars (\d+) - (\d+) (\S+) ([\d.]+) secs \(([\d.]+)u,([\d.]+)s\)$')` once at module load time.
- For proof boundary detection, compile keyword regexes once: `re.compile(r'\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Example|Definition|Fixpoint|CoFixpoint|Let|Instance|Program)\s+(\w+)')` and `re.compile(r'\b(Qed|Defined|Admitted|Abort)\s*\.')`.
- For Ltac profile parsing, compile the header regex `re.compile(r'total time:\s*([\d.]+)s')` and row regex `re.compile(r'─(\S+)\s+─*\s+([\d.]+)%\s+([\d.]+)%\s+(\d+)\s+([\d.]+)s')` once at module load time.
- Use `time.monotonic()` for wall-clock measurement; do not use `time.time()`.
- Subprocess timeout: use `process.kill()` followed by `process.wait()` on timeout. Read partial timing file before cleanup.
- Memory limit on `coqc` output: read stdout/stderr incrementally via `asyncio.StreamReader`; stop buffering at 64 MB.
- Package location: `src/poule/profiler/`.
- Entry point: `async def profile_proof(request: ProfileRequest) -> FileProfile | ProofProfile | LtacProfile | TimingComparison`.
- Pure functions: `parse_timing_output(text) -> list[TimingSentence]`, `detect_proof_boundaries(text) -> list[ProofBoundary]`, `classify_bottlenecks(items, total_time) -> list[BottleneckClassification]`, `parse_ltac_profile(text) -> LtacProfile`, `match_sentences(baseline, current, fuzz) -> MatchResult`.
