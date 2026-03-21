# Literate Documentation

The component that wraps Alectryon to generate interactive proof documentation from Coq source files. The MCP Server delegates documentation generation requests to the Alectryon Adapter, which shells out to the Alectryon CLI as a subprocess.

**Feature**: [Literate Documentation](../features/literate-documentation.md)

---

## Component Diagram

```
MCP Server
  │
  │ generate_documentation(request)
  │ generate_proof_documentation(request)
  │ generate_batch_documentation(request)
  ▼
┌───────────────────────────────────────────────────────────┐
│                   Alectryon Adapter                        │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Availability Check                                  │  │
│  │   Runs once on first invocation; caches result      │  │
│  │   Executes: alectryon --version                     │  │
│  │   Validates: binary found, version ≥ minimum        │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Single-File Generation                              │  │
│  │   Builds argument list from DocumentationRequest    │  │
│  │   Spawns alectryon subprocess                       │  │
│  │   Captures stdout/stderr, exit code                 │  │
│  │   Returns DocumentationResult                       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Proof-Scoped Generation                             │  │
│  │   Extracts proof and surrounding context from .v    │  │
│  │   Writes temporary .v file                          │  │
│  │   Delegates to Single-File Generation               │  │
│  │   Cleans up temporary file                          │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Batch Generation                                    │  │
│  │   Enumerates .v files in directory tree             │  │
│  │   Invokes Single-File Generation per file           │  │
│  │   Generates index page                              │  │
│  │   Collects per-file outcomes                        │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
  │
  │ subprocess: alectryon [flags] <input.v>
  ▼
Alectryon CLI
  │
  │ coq-lsp / SerAPI (Alectryon's own Coq interaction)
  ▼
Coq
```

## Alectryon Invocation

The adapter shells out to Alectryon as a subprocess rather than importing it as a library. Each invocation spawns a new process.

### Argument Construction

The adapter builds a command-line argument list from a `DocumentationRequest`:

```
alectryon
  --frontend coq            # always: input is a .v file
  --backend <backend>       # "webpage" (default), "webpage-no-header", or "latex"
  --output-directory <dir>  # where generated files are placed
  [--long-line-threshold N] # optional: from custom_flags
  [--cache-directory <dir>] # optional: from custom_flags
  [<additional flags>...]   # optional: passthrough from custom_flags
  <input_file.v>            # positional: the .v source file
```

Backend selection maps from the output format field in `DocumentationRequest`:

| Format | Alectryon Backend |
|--------|-------------------|
| `html` | `webpage` |
| `html-fragment` | `webpage-no-header` |
| `latex` | `latex` |

### Subprocess Execution

The adapter spawns the process, captures stdout, stderr, and the exit code. A per-invocation timeout (configurable, default 120 seconds) kills the process if it exceeds the limit. The timeout accounts for Coq compilation time, which dominates wall-clock duration.

The adapter does not set Coq-specific environment variables or load paths. Alectryon inherits the server process environment, including `PATH`, `COQPATH`, and any project-local `_CoqProject` configuration. This keeps the adapter transparent — it does not interpret or transform Coq project configuration.

## Single-File Generation Flow

```
1. Validate DocumentationRequest
     - Input file exists and has .v extension
     - Output directory exists (or will be created)
     - Format is a recognized value

2. Check Alectryon availability (cached after first call)

3. Build argument list (see Argument Construction)

4. Spawn alectryon subprocess
     - Working directory: parent directory of the input file
     - Timeout: request timeout or default (120s)

5. Wait for completion
     - Exit code 0 → success
     - Exit code non-zero → parse stderr for Coq errors

6. Locate output file
     - Alectryon writes <basename>.<ext> in the output directory
     - Extension depends on backend: .html for webpage/webpage-no-header, .tex for latex

7. If output_path specified in request:
     - Move generated file to the requested path
   Else:
     - Read file content into memory

8. Return DocumentationResult
     - On success: output path or content, format
     - On failure: error details from stderr
```

## Proof-Scoped Generation

Generating documentation for a single proof requires isolating the proof and its context from the source file, because Alectryon processes entire files.

```
1. Read the input .v file

2. Parse to locate the named proof
     - Scan for theorem/lemma/definition declaration matching the requested name
     - If not found → return error listing available proof names

3. Extract the proof and surrounding context
     - Include: the declaration statement, the proof body (through Qed/Defined/Admitted),
       and any immediately preceding context needed for the proof to compile
       (e.g., local definitions, section variables, imports)
     - The extraction is textual — it locates sentence boundaries in the .v source,
       not in a parsed AST

4. Write extracted content to a temporary .v file
     - Temporary file is placed in the same directory as the source file
       so that relative imports and load paths resolve correctly

5. Delegate to Single-File Generation with the temporary file as input

6. Clean up the temporary file (always, regardless of success or failure)

7. Return the DocumentationResult
```

The extraction step is conservative: when in doubt about whether a preceding declaration is needed, it includes it. A proof that fails to compile in isolation produces a Coq compilation error, which the adapter reports as a structured error.

## Batch Generation

```
1. Validate BatchDocumentationRequest
     - Source directory exists
     - Output directory exists or can be created

2. Enumerate all .v files in the source directory tree (recursive)

3. For each .v file:
     a. Compute relative path from source root
     b. Create corresponding subdirectory in output directory
     c. Invoke Single-File Generation
     d. Record outcome (success with output path, or failure with error)
     - A failure does not abort the batch

4. Generate index page
     - List all .v files with their documentation status
     - Successful files link to their generated HTML
     - Failed files show the error summary
     - Write index.html to output directory root

5. Return BatchDocumentationResult
     - List of per-file outcomes
     - Path to index page
     - Summary counts (total, succeeded, failed)
```

Batch generation does not invoke Alectryon's own multi-file mode. Each file is processed independently so that failures are isolated and per-file outcomes are tracked. Cross-file navigation links are injected by the adapter when generating the index page, not by Alectryon.

## Output Handling

Generated files are placed according to the following rules:

| Scenario | Output Location |
|----------|----------------|
| Single file, `output_path` specified | File written to `output_path` exactly |
| Single file, no `output_path` | Content returned in `DocumentationResult.content`; no file persisted |
| Proof-scoped | Same rules as single file; temporary .v is cleaned up |
| Batch | Files written to `output_directory`, mirroring source directory structure; index.html at root |

The adapter returns absolute paths in all results. When content is returned inline (no `output_path`), the result includes the content string and the format, but no path.

## Availability Detection

The adapter checks for Alectryon before the first documentation generation and caches the result for the lifetime of the server process.

```
1. Attempt to execute: alectryon --version
     - Search the system PATH (no hardcoded paths)

2. If the binary is not found:
     → Cache status as "not_installed"
     → All subsequent documentation requests return ALECTRYON_NOT_FOUND error

3. If the binary is found, parse the version string:
     - Compare against minimum supported version
     - If below minimum → cache status as "version_too_old"
       → Subsequent requests return ALECTRYON_VERSION_UNSUPPORTED error
     - If at or above minimum → cache status as "available"
       → Subsequent requests proceed normally
```

The check is lazy (not at server startup) so that the server starts quickly and tools unrelated to documentation are unaffected by Alectryon's absence.

## Data Structures

**DocumentationRequest** — input for single-file and proof-scoped generation:

| Field | Type | Description |
|-------|------|-------------|
| `input_file` | string | Absolute path to the .v source file |
| `proof_name` | string or null | If set, generate documentation scoped to this proof |
| `output_path` | string or null | If set, write output to this path; otherwise return content inline |
| `format` | `"html"` or `"html-fragment"` or `"latex"` | Output format (default: `"html"`) |
| `custom_flags` | list of string | Additional Alectryon CLI flags passed through verbatim |
| `timeout` | positive integer or null | Per-invocation timeout in seconds (default: 120) |

**BatchDocumentationRequest** — input for batch generation:

| Field | Type | Description |
|-------|------|-------------|
| `source_directory` | string | Absolute path to project root containing .v files |
| `output_directory` | string | Absolute path where generated documentation tree is written |
| `format` | `"html"` or `"html-fragment"` or `"latex"` | Output format for all files (default: `"html"`) |
| `custom_flags` | list of string | Additional Alectryon CLI flags applied to every file |
| `timeout_per_file` | positive integer or null | Per-file timeout in seconds (default: 120) |

**DocumentationResult** — output for single-file and proof-scoped generation:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"success"` or `"failure"` | Whether documentation was generated |
| `output_path` | string or null | Absolute path to the generated file, if written to disk |
| `content` | string or null | Generated content, if no output_path was specified |
| `format` | `"html"` or `"html-fragment"` or `"latex"` | Format of the generated output |
| `error` | structured error or null | On failure: error code and message |

**BatchDocumentationResult** — output for batch generation:

| Field | Type | Description |
|-------|------|-------------|
| `index_path` | string | Absolute path to the generated index.html |
| `output_directory` | string | Absolute path to the output root |
| `results` | list of FileOutcome | Per-file outcomes |
| `total` | non-negative integer | Total .v files found |
| `succeeded` | non-negative integer | Files documented successfully |
| `failed` | non-negative integer | Files that failed |

**FileOutcome** — per-file result within a batch:

| Field | Type | Description |
|-------|------|-------------|
| `input_file` | string | Absolute path to the source .v file |
| `output_file` | string or null | Absolute path to the generated file, on success |
| `status` | `"success"` or `"failure"` | Whether this file was documented |
| `error` | structured error or null | On failure: error code and message |

## Error Handling

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Alectryon binary not found on PATH | `ALECTRYON_NOT_FOUND` | Alectryon is not installed or not on the system PATH. Install it with: `pip install alectryon` |
| Alectryon version below minimum supported | `ALECTRYON_VERSION_UNSUPPORTED` | Alectryon version `{found}` is below the minimum required version `{minimum}`. Upgrade with: `pip install --upgrade alectryon` |
| Input .v file does not exist | `FILE_NOT_FOUND` | File not found: `{file_path}` |
| Input file is not a .v file | `INVALID_INPUT` | Expected a .v file, got: `{file_path}` |
| Output directory does not exist (single file) | `OUTPUT_DIR_NOT_FOUND` | Output directory does not exist: `{dir_path}` |
| Proof name not found in file | `PROOF_NOT_FOUND` | Proof `{proof_name}` not found in `{file_path}`. Available proofs: `{names}` |
| Coq compilation error during generation | `COQ_ERROR` | Coq error in `{file_path}` at line `{line}`: `{coq_message}` |
| Alectryon process timed out | `GENERATION_TIMEOUT` | Documentation generation timed out after `{timeout}` seconds for `{file_path}` |
| Alectryon process crashed (non-zero exit, not a Coq error) | `ALECTRYON_ERROR` | Alectryon failed with exit code `{code}`: `{stderr}` |
| Source directory does not exist (batch) | `SOURCE_DIR_NOT_FOUND` | Source directory does not exist: `{dir_path}` |
| No .v files found in source directory (batch) | `NO_INPUT_FILES` | No .v files found in `{dir_path}` |

All errors use the MCP standard error format defined in [mcp-server.md](mcp-server.md) § Error Contract. In batch mode, per-file errors are collected in `FileOutcome` entries; the batch itself returns success with a summary unless a pre-flight check (availability, source directory) fails.

## Design Rationale

### Why subprocess invocation rather than library import

Alectryon is a Python package with its own dependency tree (Coq interaction via SerAPI or coq-lsp, Pygments, docutils). Importing it as a library would couple the server process to Alectryon's dependencies and Python version constraints. Subprocess invocation keeps the boundary clean: the adapter depends only on the Alectryon CLI contract (arguments in, files and exit codes out), not on its internal API. This also means Alectryon can be upgraded independently without changing the adapter, and the server process is not affected by Alectryon bugs or memory leaks — each invocation is an isolated process.

### Why lazy availability detection rather than startup check

Alectryon is an optional dependency. Many users will use Poule's search and proof interaction tools without ever generating documentation. Checking for Alectryon at server startup would add latency to every session and produce confusing warnings for users who do not need the feature. Lazy detection defers the check to the first documentation request, when the user has clearly expressed intent to use the feature.

### Why per-file subprocess invocation for batch mode rather than Alectryon's multi-file mode

Alectryon can process multiple files in a single invocation, but a failure in one file can affect the processing of subsequent files. Per-file invocation isolates failures: each file is an independent subprocess, and a Coq compilation error in one file cannot prevent documentation generation for others. This also simplifies timeout enforcement (per-file rather than per-batch) and progress reporting (each file completion is a discrete event).

### Why textual proof extraction rather than AST-based

Proof-scoped generation extracts proof text by scanning for sentence boundaries in the source file rather than parsing the Coq AST. This avoids requiring a Coq process for the extraction step itself (Coq is only invoked by Alectryon during documentation generation). Textual extraction is sufficient because Coq's sentence structure is regular: declarations begin with keywords (`Theorem`, `Lemma`, `Definition`, etc.) and proofs end with terminators (`Qed.`, `Defined.`, `Admitted.`). Edge cases (nested modules, notation scopes) may include more context than strictly necessary, but the conservative approach ensures the extracted fragment compiles.
