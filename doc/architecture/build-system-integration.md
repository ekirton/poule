# Build System Integration

The adapter layer between the MCP Server and the external build tools (`coq_makefile`, Dune, opam). It detects which build system a project uses, generates and updates configuration files, executes builds as subprocesses, parses build errors into structured data for LLM interpretation, and queries/manages opam dependencies.

**Feature**: [Build System Integration](../features/build-system-integration.md)

---

## Component Diagram

```
Claude Code / LLM
  │
  │ MCP tool calls (stdio)
  ▼
MCP Server
  │
  │ internal function calls (in-process)
  ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Build System Adapter                           │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Build System      │  │ Project File     │  │ Error Parser   │  │
│  │ Detector          │  │ Generator        │  │                │  │
│  │                   │  │                  │  │ Coq errors     │  │
│  │ Probe project dir │  │ _CoqProject      │  │ Dune errors    │  │
│  │ for marker files  │  │ dune-project     │  │ opam errors    │  │
│  │                   │  │ dune (per-dir)   │  │                │  │
│  │                   │  │ .opam            │  │ → BuildError[] │  │
│  └──────────────────┘  └──────────────────┘  └────────────────┘  │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Build Executor    │  │ Package Query    │  │ Dependency     │  │
│  │                   │  │ Handler          │  │ Manager        │  │
│  │ Subprocess spawn  │  │                  │  │                │  │
│  │ Output capture    │  │ opam list        │  │ opam install   │  │
│  │ Timeout enforce   │  │ opam show        │  │ Conflict check │  │
│  │                   │  │ → PackageInfo[]  │  │ Dep addition   │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
└───────────┼──────────────────────┼────────────────────┼───────────┘
            │                      │                    │
            ▼                      ▼                    ▼
     ┌─────────────┐        ┌───────────┐        ┌───────────┐
     │ coq_makefile │        │   opam    │        │   opam    │
     │ / make       │        │ list/show │        │ install   │
     │ / dune build │        │           │        │           │
     └─────────────┘        └───────────┘        └───────────┘
       (subprocesses)        (subprocesses)       (subprocesses)
```

The Build System Adapter is invoked by the MCP Server in-process. All interactions with `coq_makefile`, `make`, `dune`, and `opam` are via subprocess execution — the adapter never links against or imports these tools.

---

## Build System Detection

The adapter determines which build system a project uses by probing for marker files in the project root directory. Detection is deterministic and based on file presence, not file content.

### Detection Algorithm

```
detect_build_system(project_dir)
  │
  ├─ If dune-project exists → DUNE
  ├─ Else if _CoqProject exists → COQ_MAKEFILE
  ├─ Else → UNKNOWN
  │
  └─ Additionally (independent of above):
     If any .opam file exists → has_opam = true
```

Detection returns a record with:
- The primary build system (`DUNE`, `COQ_MAKEFILE`, or `UNKNOWN`)
- Whether opam metadata is present
- The paths to detected configuration files

When the build system is `UNKNOWN`, generation tools can still be invoked (they create files from scratch). Build execution tools require a detected build system and return `BUILD_SYSTEM_NOT_DETECTED` otherwise.

### Precedence

Dune takes precedence over `coq_makefile` because Dune projects may also contain a `_CoqProject` for editor integration. The `_CoqProject` in a Dune project is not the build driver — `dune build` is.

---

## Project File Generation

### _CoqProject Generation

Given a project directory, the generator:

1. Recursively enumerates `.v` files
2. Groups files by directory
3. Infers logical path mappings:
   - Each source directory maps to a logical path segment derived from the directory name
   - The project root maps to the top-level logical name (provided by the caller or inferred from the directory name)
4. Emits `-Q` flags (one per source directory), source file listings, and any additional Coq flags specified by the caller

The generated `_CoqProject` is ordered: flags first, then `-Q`/`-R` mappings, then source file paths (alphabetically within each directory).

When updating an existing `_CoqProject`, the generator parses the existing file, identifies new directories and files not yet listed, inserts them in the appropriate position, and preserves existing custom flags and comments.

### Dune File Generation

Given a project directory, the generator produces:

1. A `dune-project` file at the root with:
   - `(lang dune ...)` declaration
   - `(using coq ...)` declaration
2. Per-directory `dune` files wherever `.v` files exist, each containing a `(coq.theory ...)` stanza with:
   - `(name ...)` — logical library name
   - `(theories ...)` — inter-library dependencies (populated from caller-provided dependency list or inferred from `Require` statements if available)

When generating for a project with multiple sub-libraries, each directory with `.v` files gets its own `dune` file. The dependency relationships between sub-libraries are declared in the `(theories ...)` field.

### .opam File Generation

Given package metadata (name, version, synopsis, maintainer, dependencies), the generator produces an `.opam` file with:

- `opam-version: "2.0"`
- `name`, `maintainer`, `synopsis`, `description` fields
- `depends` field with each dependency and version constraints
- `build` field with the appropriate build command (`["dune" "build" ...]` for Dune projects, `["make" "-j" jobs]` for `coq_makefile` projects)

### coq_makefile-to-Dune Migration

Given an existing `_CoqProject`:

1. Parse `-Q` and `-R` flags to extract logical path mappings
2. Parse source file listings
3. Generate equivalent `dune-project` and per-directory `dune` files
4. Report any `_CoqProject` flags that have no Dune equivalent (returned as a list of untranslatable flags in the result)

---

## Build Execution

### Subprocess Management

Each build invocation spawns a fresh subprocess. There is no persistent build daemon or long-lived process.

```
execute_build(project_dir, build_system, target?, timeout?)
  │
  ├─ Resolve command:
  │    COQ_MAKEFILE → ["make", "-C", project_dir] (+ [target] if specified)
  │    DUNE         → ["dune", "build"] (+ ["--root", project_dir])
  │
  ├─ Spawn subprocess with:
  │    - Working directory: project_dir
  │    - stdout and stderr: captured (piped)
  │    - stdin: closed (no interactive input)
  │    - Environment: inherited from server process
  │
  ├─ Wait for completion with timeout (default: 300 seconds)
  │    - On timeout → terminate subprocess (SIGTERM), wait 5 seconds,
  │      then kill (SIGKILL) if still running
  │
  └─ Return BuildResult with exit code, stdout, stderr, elapsed time
```

For `coq_makefile` projects, if no Makefile exists, the adapter first runs `coq_makefile -f _CoqProject -o Makefile` to generate it, then runs `make`.

### Output Capture

stdout and stderr are captured separately and in full. No streaming — the complete output is returned after the subprocess exits. Output size is bounded by a configurable maximum (default: 1 MB per stream); output exceeding the limit is truncated from the beginning (tail preserved, since errors typically appear at the end).

### Timeout Handling

The default timeout is 300 seconds (5 minutes). The caller may specify a shorter timeout. The minimum accepted timeout is 10 seconds. Timeout expiry produces a `BUILD_TIMEOUT` error that includes whatever output was captured before termination.

---

## Error Parsing

Build errors are parsed from stderr/stdout into structured `BuildError` records. Each build system has its own error format; the adapter applies system-specific parsers.

### Coq Compiler Errors

Parsed from `coqc` output (used by both `coq_makefile` and Dune builds):

- **Pattern**: `File "{file}", line {line}, characters {start}-{end}:`
- Extracts: file path, line number, character range, error message
- Categorizes by error class:
  - `LOGICAL_PATH_NOT_FOUND` — "Cannot find a physical path bound to logical path"
  - `REQUIRED_LIBRARY_NOT_FOUND` — "Required library ... not found"
  - `TYPE_ERROR` — type checking failures
  - `SYNTAX_ERROR` — parsing failures
  - `TACTIC_FAILURE` — tactic-related build errors
  - `OTHER` — unrecognized errors (full text preserved)

### Dune Errors

Parsed from `dune build` stderr:

- **Pattern**: `Error:` prefix lines
- Categorizes:
  - `THEORY_NOT_FOUND` — missing `coq.theory` dependency
  - `DUNE_CONFIG_ERROR` — stanza syntax or field errors
  - `OTHER` — unrecognized

### opam Errors

Parsed from `opam install` stderr:

- **Pattern**: version conflict diagnostics, dependency resolution failures
- Categorizes:
  - `VERSION_CONFLICT` — incompatible version constraints
  - `PACKAGE_NOT_FOUND` — package not in any configured repository
  - `BUILD_FAILURE` — package's own build failed during installation
  - `OTHER` — unrecognized

### Structuring for LLM Interpretation

Each `BuildError` includes:
- The raw error text (for fidelity)
- The parsed category (for programmatic handling)
- A plain-language explanation of what went wrong
- A suggested fix (when the category is recognized)

The explanations and fix suggestions are generated by the adapter using templates keyed to the error category. They are not LLM-generated — they are deterministic, predictable, and testable. The LLM (Claude Code) may choose to present them as-is, rephrase them, or use them as context for a more detailed explanation.

---

## Package Queries

### Installed Package Listing

```
query_installed_packages()
  │
  ├─ Run: ["opam", "list", "--installed", "--columns=name,version", "--short"]
  │
  ├─ Parse output: one line per package, split on whitespace
  │    → list of (name, version) pairs
  │
  └─ Return sorted alphabetically by name
```

### Package Availability

```
query_package_info(package_name)
  │
  ├─ Run: ["opam", "show", package_name, "--field=version,synopsis,depends"]
  │    - If exit code != 0 → PACKAGE_NOT_FOUND
  │
  ├─ Run: ["opam", "show", package_name, "--field=all-versions"]
  │    → list of available versions
  │
  └─ Return PackageInfo with name, installed version (if any),
     available versions (descending), synopsis, dependencies
```

---

## Dependency Management

### Adding a Dependency

```
add_dependency(project_dir, package_name, version_constraint?)
  │
  ├─ Detect build system
  │
  ├─ Locate the target file:
  │    DUNE → dune-project (depends stanza)
  │    COQ_MAKEFILE → .opam file (depends field)
  │
  ├─ Parse the existing dependency list
  │
  ├─ If package_name already present → return DEPENDENCY_EXISTS
  │
  ├─ Insert the new dependency with version constraint
  │    (default constraint: no constraint if none specified)
  │
  └─ Write updated file, preserving formatting and comments where possible
```

### Dependency Conflict Detection

```
check_dependency_conflicts(dependencies: list of (name, constraint))
  │
  ├─ Run: ["opam", "install", "--dry-run", "--show-actions"]
  │    with all specified dependencies
  │
  ├─ Parse output:
  │    - If exit code = 0 → no conflicts
  │    - If exit code != 0 → parse conflict diagnostics
  │      Extract: conflicting package names, their constraints,
  │      and which dependency introduced each constraint
  │
  └─ Return DependencyStatus (satisfiable or conflict details)
```

### Package Installation

```
install_package(package_name, version_constraint?)
  │
  ├─ Run: ["opam", "install", package_name] (with version pin if specified)
  │    - timeout: 600 seconds (package builds can be slow)
  │    - stdout/stderr captured
  │
  ├─ On success → return success with installed version
  │
  └─ On failure → parse error output through opam error parser,
     return structured BuildError[]
```

opam operations that modify the switch (`install`) require explicit invocation — the adapter never installs packages as a side effect of another operation. This is a safety constraint: opam install can take significant time, consume disk space, and alter the global switch state.

---

## Data Structures

**BuildSystem** — detected build system type:
- `COQ_MAKEFILE`, `DUNE`, `UNKNOWN`

**DetectionResult** — build system detection output:

| Field | Type | Description |
|-------|------|-------------|
| `build_system` | BuildSystem | Detected primary build system |
| `has_opam` | boolean | Whether `.opam` file(s) exist |
| `config_files` | list of string | Paths to detected configuration files |
| `project_dir` | string | Absolute path to the project directory |

**BuildRequest** — input to build execution:

| Field | Type | Description |
|-------|------|-------------|
| `project_dir` | string | Absolute path to the project directory |
| `build_system` | BuildSystem or null | Override detection (null = auto-detect) |
| `target` | string or null | Build target (null = default target) |
| `timeout` | positive integer | Timeout in seconds (default: 300, minimum: 10) |

**BuildResult** — output of build execution:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the build exited with code 0 |
| `exit_code` | integer | Subprocess exit code |
| `stdout` | string | Captured standard output |
| `stderr` | string | Captured standard error |
| `errors` | list of BuildError | Parsed errors (empty on success) |
| `elapsed_ms` | non-negative integer | Wall-clock time in milliseconds |
| `build_system` | BuildSystem | Which build system was used |
| `timed_out` | boolean | Whether the build was terminated due to timeout |

**BuildError** — a single parsed build error:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Error category (e.g., `LOGICAL_PATH_NOT_FOUND`, `TYPE_ERROR`) |
| `file` | string or null | Source file path (when parseable) |
| `line` | positive integer or null | Line number (when parseable) |
| `char_range` | pair of non-negative integers or null | Character range (when parseable) |
| `raw_text` | string | The original error text from the build output |
| `explanation` | string | Plain-language description of the error |
| `suggested_fix` | string or null | Actionable fix suggestion (null for unrecognized errors) |

**PackageInfo** — opam package metadata:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Package name |
| `installed_version` | string or null | Currently installed version (null if not installed) |
| `available_versions` | list of string | All available versions, descending order |
| `synopsis` | string | One-line package description |
| `dependencies` | list of string | Direct dependency names |

**DependencyStatus** — result of conflict detection:

| Field | Type | Description |
|-------|------|-------------|
| `satisfiable` | boolean | Whether all constraints can be satisfied |
| `conflicts` | list of ConflictDetail | Empty when satisfiable is true |

**ConflictDetail** — a single version conflict:

| Field | Type | Description |
|-------|------|-------------|
| `package` | string | Package with conflicting constraints |
| `constraints` | list of ConstraintSource | The incompatible constraints |

**ConstraintSource** — one side of a version conflict:

| Field | Type | Description |
|-------|------|-------------|
| `required_by` | string | Package that imposes this constraint |
| `constraint` | string | Version constraint expression |

---

## Error Handling

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Project directory does not exist | `PROJECT_NOT_FOUND` | Return error immediately; no subprocess spawned |
| Build system not detected and not specified | `BUILD_SYSTEM_NOT_DETECTED` | Return error with list of files probed |
| `coq_makefile` not found on PATH | `TOOL_NOT_FOUND` | Return error naming the missing tool |
| `dune` not found on PATH | `TOOL_NOT_FOUND` | Return error naming the missing tool |
| `opam` not found on PATH | `TOOL_NOT_FOUND` | Return error naming the missing tool |
| Build timeout exceeded | `BUILD_TIMEOUT` | Terminate subprocess; return partial output captured before termination |
| Build failed (non-zero exit) | (normal response) | Not an adapter error — returned as `BuildResult` with `success: false` and parsed `errors` |
| Output exceeds size limit | (normal response) | Truncate from beginning; set truncation flag in result |
| opam dry-run detects conflict | (normal response) | Returned as `DependencyStatus` with `satisfiable: false` |
| Target file not writable | `FILE_NOT_WRITABLE` | Return error; no modification attempted |
| Dependency already exists (add) | `DEPENDENCY_EXISTS` | Return informational response; no modification |
| Package not found (opam show) | `PACKAGE_NOT_FOUND` | Return error naming the package queried |

All errors use the MCP standard error format defined in [mcp-server.md](mcp-server.md) when surfaced through MCP tools.

---

## Design Rationale

### Subprocess per invocation

Each build or opam command spawns a fresh subprocess rather than maintaining a persistent connection to a build daemon. This is the correct model because:

- `coq_makefile`, `make`, `dune`, and `opam` are all designed as CLI tools invoked per-command. None of them expose a persistent RPC or daemon interface suitable for long-lived connections.
- Subprocess isolation means a hung or crashed build cannot corrupt the adapter's state. The adapter simply observes the exit code and output.
- Environment inheritance (PATH, OPAMSWITCH, etc.) is captured at invocation time, which is the correct behavior — the user may change their opam switch between invocations.

### Build system detection heuristics

Detection is based on file presence (`dune-project`, `_CoqProject`) rather than file content because:

- File existence is a cheap, reliable signal. Parsing file content to determine the build system would be fragile and circular (the adapter would need to understand the file format before knowing which format to parse).
- Dune takes precedence over `coq_makefile` because Dune projects commonly contain a `_CoqProject` for editor integration (e.g., `coqtop` flags for CoqIDE/Proof General). The presence of `_CoqProject` in a Dune project does not mean `coq_makefile` is the build driver.
- `UNKNOWN` is a valid detection result, not an error. It allows generation tools to create configuration files from scratch for new projects.

### Safety constraints for opam operations

opam operations are partitioned into read-only queries and write operations:

- **Read-only** (`opam list`, `opam show`, `opam install --dry-run`): safe to run at any time. No user confirmation needed.
- **Write** (`opam install`): modifies the switch. Only invoked when explicitly requested. Never triggered as a side effect.

Switch management (`opam switch create`, `opam switch set`) is out of scope entirely. Switch operations affect the global development environment in ways that are difficult to reverse and dangerous to automate without explicit user control.

### Deterministic error explanations

Error explanations and fix suggestions are template-based, not LLM-generated, because:

- Determinism: the same error always produces the same explanation. This makes the adapter testable and predictable.
- Speed: no LLM round-trip for error interpretation. The structured `BuildError` is available immediately after parsing.
- Composability: the LLM (Claude Code) receives structured error data and may enhance, rephrase, or contextualize the explanation. The adapter provides the factual foundation; the LLM adds conversational polish.

### Output truncation strategy

Build output is truncated from the beginning (preserving the tail) because build errors and the final status summary appear at the end of the output. Truncating from the end would discard the most actionable information.
