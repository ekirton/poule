# Independent Proof Checking

The component that wraps `coqchk` for independent verification of compiled `.vo` files. It constructs `coqchk` invocations, manages the subprocess lifecycle, and parses output into structured results that the MCP server returns to Claude Code.

**Feature**: [Independent Proof Checking](../features/independent-proof-checking.md)

---

## Component Diagram

```
MCP Server
  │
  │ check_proof(request: CheckRequest)
  ▼
┌───────────────────────────────────────────────────────────────┐
│                  Proof Checker Adapter                         │
│                                                               │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────┐  │
│  │ Command Builder  │  │ Output Parser    │  │ File        │  │
│  │                  │  │                  │  │ Discovery   │  │
│  │ Constructs       │  │ Parses stdout/   │  │             │  │
│  │ coqchk argv      │  │ stderr into      │  │ Enumerates  │  │
│  │ from CheckRequest│  │ CheckResult      │  │ .vo files   │  │
│  │                  │  │                  │  │ from project │  │
│  └────────┬─────────┘  └───────▲──────────┘  └──────┬──────┘  │
│           │                    │                     │         │
│           │ argv               │ raw output          │ paths   │
│           ▼                    │                     ▼         │
│  ┌─────────────────────────────┴──────────────────────────┐   │
│  │              Subprocess Runner                          │   │
│  │                                                         │   │
│  │  Spawns coqchk, enforces timeout, captures streams     │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                   │
└────────────────────────────┼───────────────────────────────────┘
                             │
                             ▼
                          coqchk
                       (host binary)
```

## Boundary Contract

The Proof Checker Adapter is invoked by the MCP server and returns structured results. It does not:
- Manage proof sessions or interact with `coqtop`/`coqidetop`
- Compile `.v` files to `.vo`
- Modify any files on disk
- Access the search index or retrieval pipeline

It depends only on the `coqchk` binary being available on the host system's `PATH` (or at a configured path).

---

## Data Structures

**CheckRequest** — input to the adapter:

| Field | Type | Description |
|-------|------|-------------|
| `mode` | `"single"` or `"project"` | Whether to check one file or an entire project |
| `file_path` | string or null | Absolute path to a `.vo` file (required when mode is `"single"`) |
| `project_dir` | string or null | Absolute path to the project root (required when mode is `"project"`) |
| `include_paths` | list of string | Additional `-I` paths for `coqchk` |
| `load_paths` | list of (string, string) | Logical-to-physical path mappings (`-Q` flags) |
| `timeout_seconds` | positive integer | Wall-clock timeout for the `coqchk` process (default: 300) |

**CheckResult** — output from the adapter:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"pass"` or `"fail"` or `"error"` | Overall verdict |
| `files_checked` | non-negative integer | Number of `.vo` files submitted to `coqchk` |
| `files_passed` | non-negative integer | Number of files that passed |
| `files_failed` | non-negative integer | Number of files that failed |
| `failures` | list of CheckFailure | Per-file failure details (empty on full pass) |
| `stale_files` | list of string | Paths to `.vo` files older than their `.v` source |
| `wall_time_ms` | non-negative integer | Wall-clock time for the entire check |
| `raw_output` | string | Full `coqchk` stdout + stderr (for debugging) |

**CheckFailure** — one failed file:

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Absolute path to the `.vo` file that failed |
| `module_name` | string or null | Logical module name where the inconsistency was found |
| `definition` | string or null | Name of the definition or theorem that failed |
| `failure_kind` | `"inconsistency"` or `"missing_dependency"` or `"axiom_mismatch"` or `"type_error"` or `"unknown"` | Classified failure type |
| `raw_message` | string | The raw `coqchk` error text |

---

## coqchk Invocation

### Command Construction

The Command Builder assembles the `coqchk` argument vector from a CheckRequest:

```
coqchk [load_path_flags] [include_flags] [library_names]
```

Where:
- **load_path_flags**: Each `(logical, physical)` pair in `load_paths` becomes `-Q physical logical`
- **include_flags**: Each path in `include_paths` becomes `-I path`
- **library_names**: The logical library name(s) derived from the `.vo` file path and load path mappings

### Library Path Resolution

To derive the logical library name from a `.vo` file path:

1. Strip the `.vo` extension to get the base path
2. Find the load path entry whose physical directory is a prefix of the file path
3. Replace the physical prefix with the logical prefix, substituting path separators with dots
4. Example: file `/project/theories/Arith/Plus.vo` with load path `("MyLib", "/project/theories")` yields logical name `MyLib.Arith.Plus`

If no load path entry matches, fall back to the bare file name without a logical prefix and issue a warning. This fallback handles ad-hoc files outside a structured project.

### Flag Selection

The adapter passes no flags beyond load paths and include paths. In particular:
- No `-silent` flag: the adapter needs full output for parsing
- No `-norec` flag by default: recursive checking of dependencies is the intended behavior for defense-in-depth
- No `-admit` flags: the purpose is full independent verification; selectively admitting modules defeats the goal

---

## Single-File Checking Flow

```
check_single(file_path, include_paths, load_paths, timeout)
  │
  ├─ Validate that file_path exists and has .vo extension
  │    If not → return CheckResult(status="error") immediately
  │
  ├─ Detect staleness:
  │    Derive .v path by replacing .vo extension with .v
  │    If .v exists and mtime(.v) > mtime(.vo) → add to stale_files
  │
  ├─ Resolve logical library name from file_path + load_paths
  │
  ├─ Build command: coqchk [load_path_flags] [include_flags] <library_name>
  │
  ├─ Spawn subprocess with timeout
  │    Capture stdout and stderr
  │
  ├─ On exit code 0 → status = "pass"
  │  On non-zero exit code → parse output for failures
  │  On timeout → status = "error", failure_kind = timeout (see Error Handling)
  │
  └─ Return CheckResult
```

---

## Project-Wide Checking

### File Enumeration

When `mode` is `"project"`, the adapter discovers all `.vo` files to check:

1. Look for `_CoqProject` in `project_dir`
2. If `_CoqProject` exists:
   - Parse `-Q` and `-R` directives to extract load path mappings
   - Parse `-I` directives to extract include paths
   - These parsed paths are merged with any paths provided in the CheckRequest (request paths take precedence on conflict)
3. Recursively walk the directories referenced by load path entries, collecting all `.vo` files
4. If no `_CoqProject` exists, recursively walk `project_dir` collecting all `.vo` files and use the request-provided paths only

### Staleness Detection

Before invoking `coqchk`, compare modification times for every discovered `.vo` file against its corresponding `.v` source. All stale files are collected into `CheckResult.stale_files`. The check proceeds regardless — staleness is a warning, not a blocker.

### Invocation Strategy

All discovered library names are passed to a single `coqchk` invocation:

```
coqchk [load_path_flags] [include_flags] Lib.Module1 Lib.Module2 Lib.Module3 ...
```

A single invocation is preferred over per-file invocations because `coqchk` resolves the full dependency graph internally. Invoking once lets `coqchk` load each dependency exactly once, avoiding redundant re-checking. If the single invocation fails, the output parser extracts per-file failure information from the error messages.

---

## Output Parsing

### Success Detection

`coqchk` exits with code 0 on success. Successful output typically contains lines like:

```
<module> has been checked
```

The parser counts these lines to populate `files_checked` and `files_passed`.

### Failure Parsing

On non-zero exit, the parser scans stderr for structured error patterns. `coqchk` error messages follow recognizable formats:

| Pattern | Extracted Fields | Maps to `failure_kind` |
|---------|-----------------|----------------------|
| `Error: ... is not consistent with ...` | module name from context | `inconsistency` |
| `Error: Missing library ...` or `Cannot find library ...` | library name | `missing_dependency` |
| `Error: Anomaly ...` or `Type error ...` | definition name if present | `type_error` |
| `Error: ... (axiom) ...` mismatch patterns | axiom name | `axiom_mismatch` |
| Any other `Error:` line | raw text | `unknown` |

The parser walks stderr line by line, matching against these patterns in priority order. Each matched error produces one CheckFailure entry. When a pattern includes a module or definition name, it is extracted via the surrounding context lines (typically the line preceding `Error:` identifies the module being checked).

### Mapping Checked Files to Results

For project-wide checks, the parser correlates success lines (`has been checked`) and error lines to individual files. Files that appear in neither success nor error output are reported as unchecked — this can occur if `coqchk` aborts early on a dependency failure before reaching downstream files.

---

## Error Handling

| Condition | Behavior | CheckResult |
|-----------|----------|-------------|
| `.vo` file not found | Return immediately, no subprocess spawned | `status="error"`, single CheckFailure with `failure_kind="missing_dependency"` |
| `.vo` file path has wrong extension | Return immediately | `status="error"`, failure message identifies the bad path |
| `coqchk` binary not found on PATH | Return immediately | `status="error"`, failure message: `coqchk not found` |
| Subprocess times out | Kill the process, capture partial output | `status="error"`, failures parsed from partial output, plus a synthetic CheckFailure with `failure_kind="unknown"` and message indicating timeout |
| Subprocess exits with non-zero code | Parse output normally | `status="fail"`, failures populated from parsed output |
| `_CoqProject` parse error | Log warning, fall back to directory walk | Checking proceeds with available paths |
| No `.vo` files found in project | Return immediately | `status="pass"`, `files_checked=0`, empty failures |
| `coqchk` stderr contains unrecognized output | Capture in `raw_output`, do not create spurious CheckFailure entries | Parser only creates CheckFailure for lines matching known error patterns |

---

## Design Rationale

### Why subprocess invocation rather than library integration

`coqchk` is a standalone binary that deliberately shares no code with the main Coq compiler. Its independence is the source of its value — it provides an entirely separate verification path. Linking against `coqchk` as a library (if that were even possible) would complicate builds, couple the adapter to `coqchk` internals, and risk undermining the tool's independence guarantees. Subprocess invocation preserves the clean trust boundary: the adapter treats `coqchk` as an opaque oracle.

### Why independent from the Proof Session Manager

The Proof Session Manager wraps `coqtop`/`coqidetop` for interactive proof development — stepping through tactics, observing proof state, managing sessions. `coqchk` serves a fundamentally different purpose: it re-verifies already-compiled artifacts against a separate kernel. There is no session to manage, no interactive state, and no tactic submission. The two components share no subprocess, no protocol, and no lifecycle. Coupling them would add complexity without benefit.

### Why a single coqchk invocation for project-wide checks

`coqchk` builds an internal dependency graph and loads each `.vo` file once. Invoking it once with all library names lets it share this work. Per-file invocations would re-load shared dependencies repeatedly, multiplying I/O and kernel re-checking time. The single-invocation approach matches how `coqchk` is designed to be used.

### Why staleness detection is a warning, not a blocker

The adapter's job is to invoke `coqchk` and report results. Whether to recompile before checking is the user's decision — Claude can relay the warning and suggest recompilation, but blocking the check would remove user agency and prevent legitimate use cases (e.g., intentionally checking an older build).
