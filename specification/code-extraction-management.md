# Code Extraction Management

Wraps Coq's Extraction and Recursive Extraction commands to extract verified definitions to OCaml, Haskell, or Scheme — with preview mode, disk write, and structured failure diagnosis.

**Architecture**: [code-extraction-management.md](../doc/architecture/code-extraction-management.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the extraction handler that, given an active proof session with a definition in scope, constructs and executes a Coq extraction command, parses the result into a structured success or classified failure, and optionally writes the extracted code to disk after user confirmation.

## 2. Scope

**In scope**: Extraction command construction (language directive + extraction command), single and recursive extraction, preview mode (return code without writing), write mode (persist to disk), error classification into six categories with explanations and suggestions, ExtractionRequest/ExtractionResult/CodeExtractionError data model.

**Out of scope**: Session lifecycle management (owned by proof-session), MCP protocol handling and input validation (owned by mcp-server), Coq expression parsing and name resolution (owned by Coq backend), type-checking or compilation of extracted output in the target language, modification of Coq source files to make definitions extractable.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Extraction | The Coq mechanism that translates a verified Gallina definition into executable code in a target language |
| Single extraction | `Extraction {name}.` — extracts one definition without its transitive dependencies |
| Recursive extraction | `Recursive Extraction {name}.` — extracts a definition and all its transitive dependencies |
| Target language | One of OCaml, Haskell, or Scheme — the output language for extraction |
| Language directive | `Extraction Language {lang}.` — configures the Coq extraction backend before the extraction command |
| Preview mode | Extraction where the result is returned in-memory without writing to disk |
| Write mode | Persisting previously extracted code to a file at a user-specified path |
| Opaque term | A Coq definition closed with `Qed` or behind an abstraction barrier, from which no computational content can be extracted |
| Axiom realizer | A binding (`Extract Constant`) that maps an axiom to target language code |

## 4. Behavioral Requirements

### 4.1 Extraction Entry Point

#### extract_code(session_id, definition_name, language, recursive, output_path?)

- REQUIRES: `session_id` references an active proof session in the Proof Session Manager. `definition_name` is a non-empty string (short or fully qualified Coq name). `language` is one of `"OCaml"`, `"Haskell"`, or `"Scheme"`. `recursive` is a boolean (default: `false`). `output_path`, when provided, is an absolute path whose parent directory exists.
- ENSURES: Constructs the extraction command sequence, submits it to the Coq backend via the Proof Session Manager, parses the result, and returns an ExtractionResult on success or a CodeExtractionError on failure. When `output_path` is omitted, operates in preview mode (no file written). When `output_path` is provided, writes the extracted code to disk and includes the path in the result.
- MAINTAINS: The extraction handler does not modify the Coq environment state beyond the side effects of the extraction command itself. The definition name is passed verbatim to Coq without transformation.

> **Given** a session with `my_fn` defined and `language = "OCaml"`, `recursive = false`, no `output_path`
> **When** `extract_code(session_id, "my_fn", "OCaml", false)` is called
> **Then** the handler submits `Extraction Language OCaml. Extraction my_fn.` to Coq, and returns an ExtractionResult with the extracted OCaml code and `output_path = null`

> **Given** a session with `serialize` defined and `language = "Haskell"`, `recursive = true`
> **When** `extract_code(session_id, "serialize", "Haskell", true)` is called
> **Then** the handler submits `Extraction Language Haskell. Recursive Extraction serialize.` and returns an ExtractionResult containing `serialize` and all its transitive dependencies

> **Given** a session where `opaque_fn` is closed with `Qed`
> **When** `extract_code(session_id, "opaque_fn", "OCaml", false)` is called
> **Then** a CodeExtractionError is returned with `category = "opaque_term"`, a plain-language explanation, and suggestions including changing `Qed` to `Defined`

### 4.2 Command Construction

The command constructor shall build a two-part command sequence from the request fields.

**Language directive mapping:**

| Target Language | Coq Directive |
|-----------------|---------------|
| OCaml | `Extraction Language OCaml.` |
| Haskell | `Extraction Language Haskell.` |
| Scheme | `Extraction Language Scheme.` |

**Extraction command mapping:**

| Recursive | Coq Command |
|-----------|-------------|
| `false` | `Extraction {definition_name}.` |
| `true` | `Recursive Extraction {definition_name}.` |

The full command sequence is the language directive followed by the extraction command. The definition name is included verbatim — no quoting, escaping, or qualification is applied.

> **Given** `language = "Scheme"`, `recursive = true`, `definition_name = "Coq.Init.Nat.add"`
> **When** the command is constructed
> **Then** the result is `Extraction Language Scheme. Recursive Extraction Coq.Init.Nat.add.`

### 4.3 Result Parsing

The result parser shall inspect the command output after extraction command execution. The session manager returns command output as a single string (merged stdout and stderr from the Coq backend).

The parser shall classify output lines by pattern:
- **Error lines**: lines matching `Error:` at the start. Presence of any error line indicates extraction failure.
- **Warning lines**: lines matching `Warning:` at the start. These are non-fatal diagnostics.
- **Code lines**: all remaining non-empty lines. These constitute the extracted source code.

Parsing rules:
- When the output contains code lines and no error lines: the parser shall return an ExtractionResult with the `code` field set to the extracted source code (the code lines joined).
- When the output contains code lines, no error lines, and one or more warning lines: the parser shall return an ExtractionResult with the `code` field populated and warnings captured in the `warnings` list.
- When the output contains one or more error lines: the parser shall classify the error (see section 4.5) and return a CodeExtractionError. Partial code in the output is discarded.

> **Given** command output is `let my_fn x = x + 1` (no error or warning lines)
> **When** the result is parsed
> **Then** an ExtractionResult is returned with `code = "let my_fn x = x + 1"`

> **Given** command output contains extracted code followed by `Warning: axiom_name has no body`
> **When** the result is parsed
> **Then** an ExtractionResult is returned with `code` populated and `warnings` containing the axiom warning text

### 4.4 Write Mode

#### write_extraction(code, output_path)

- REQUIRES: `code` is a non-empty string (from a prior ExtractionResult). `output_path` is an absolute path. The parent directory of `output_path` exists.
- ENSURES: Writes `code` to `output_path`. When the file exists, it is overwritten. When the file does not exist, it is created. Returns confirmation with `output_path` and the number of bytes written.
- MAINTAINS: Write mode does not re-execute extraction. The code written is exactly the string from the prior ExtractionResult.

> **Given** a prior ExtractionResult with `code = "let add x y = x + y"` and `output_path = "/project/extracted/add.ml"`
> **When** `write_extraction(code, "/project/extracted/add.ml")` is called
> **Then** the file `/project/extracted/add.ml` is created with the exact contents `let add x y = x + y`, and the response includes `bytes_written = 19`

> **Given** `output_path = "relative/path.ml"` (not absolute)
> **When** `write_extraction(code, "relative/path.ml")` is called
> **Then** an `INVALID_OUTPUT_PATH` error is returned requiring an absolute path

### 4.5 Error Classification

When extraction fails, the result parser shall classify the Coq error by matching patterns in the command output in order from most specific to least specific. The first matching category is selected.

| Category | Coq Error Pattern | Explanation | Suggestions |
|----------|------------------|-------------|-------------|
| `opaque_term` | `is not a defined object` or opacity-related message | The definition or a dependency is opaque (`Qed` instead of `Defined`, or behind an abstraction barrier). Coq cannot extract computational content from opaque terms. | 1. Change `Qed` to `Defined` if the proof is computational. 2. Use `Transparent {name}.` to expose the term. 3. Provide an `Extract Constant` directive mapping the opaque term to target language code. |
| `axiom_without_realizer` | `has no body` or axiom-related extraction warning | An axiom used by the definition has no computational realizer. Extraction produces a stub that fails at runtime. | 1. Provide `Extract Constant {axiom} => "{implementation}".` to bind the axiom to target language code. 2. Replace the axiom with a proven definition. |
| `universe_inconsistency` | `Universe inconsistency` | A universe constraint conflict prevents extraction, typically from mixing universe-polymorphic and monomorphic definitions. | 1. Check for universe-polymorphic definitions that conflict with monomorphic ones. 2. Restructure the definition to avoid the inconsistency. |
| `unsupported_match` | `Cannot extract` with match-related context | Coq's extraction mechanism does not support the match pattern used. Deep pattern matching on dependent types is a common trigger. | 1. Refactor the match to use simpler patterns. 2. Introduce an auxiliary function that eliminates the problematic pattern. |
| `module_type_mismatch` | `Module type` or functor-related error | A module type mismatch prevents extraction due to misaligned module functors or signatures. | 1. Verify module signatures match expected types. 2. Simplify module structure to avoid functor application issues. |
| `unknown` | Any unrecognized error | Extraction failed for a reason not in the known categories. The raw Coq error is included for manual diagnosis. | 1. Consult the Coq reference manual for the specific error. 2. Simplify the definition and retry extraction to isolate the cause. |

> **Given** command output contains `Error: Universe inconsistency`
> **When** the error is classified
> **Then** category is `universe_inconsistency` with the corresponding explanation and suggestions

> **Given** command output contains an unrecognized message `Error: something unexpected`
> **When** the error is classified
> **Then** category is `unknown` with the raw error preserved in `raw_error`

## 5. Data Model

### ExtractionRequest

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `session_id` | string | yes | References an active proof session |
| `definition_name` | string | yes | Non-empty; short or fully qualified Coq name |
| `language` | enum: `"OCaml"`, `"Haskell"`, `"Scheme"` | yes | Exactly one of the three supported languages |
| `recursive` | boolean | no | Default: `false` |
| `output_path` | string | no | When present, must be an absolute path with an existing parent directory |

### ExtractionResult

| Field | Type | Constraints |
|-------|------|-------------|
| `definition_name` | string | The definition that was extracted |
| `language` | enum: `"OCaml"`, `"Haskell"`, `"Scheme"` | Target language of the extracted code |
| `recursive` | boolean | Whether recursive extraction was used |
| `code` | string | Non-empty; the extracted source code |
| `warnings` | list of string | Non-fatal warnings from Coq; empty list when no warnings |
| `output_path` | string or null | Absolute file path if code was written to disk; null for preview mode |

### CodeExtractionError

| Field | Type | Constraints |
|-------|------|-------------|
| `definition_name` | string | The definition that failed to extract |
| `language` | enum: `"OCaml"`, `"Haskell"`, `"Scheme"` | Requested target language |
| `category` | enum: `"opaque_term"`, `"axiom_without_realizer"`, `"universe_inconsistency"`, `"unsupported_match"`, `"module_type_mismatch"`, `"unknown"` | Classified failure category |
| `raw_error` | string | Non-empty; verbatim Coq error message |
| `explanation` | string | Non-empty; plain-language explanation of the failure cause |
| `suggestions` | list of string | Non-empty; at least one actionable fix suggestion |

## 6. Interface Contracts

### Extraction Handler → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | Command submission (language directive + extraction command as a sequence). `submit_command(session_id, command)` returns `str` — the merged Coq output as a single string. |
| Concurrency | Serialized — one command sequence at a time per session |
| Error strategy | `SESSION_NOT_FOUND` → return error immediately, no extraction attempted. `BACKEND_CRASHED` → return error advising session restart. Extraction-level Coq errors → parse into CodeExtractionError. |
| Idempotency | Extraction commands are idempotent — re-executing the same extraction produces the same output. |

### Extraction Handler → Filesystem (write mode only)

| Property | Value |
|----------|-------|
| Operations used | File write (create or overwrite) |
| Error strategy | Parent directory missing → `INVALID_OUTPUT_PATH`. Permission denied or disk full → `WRITE_FAILED` with filesystem error message. |
| Idempotency | Write is idempotent — writing the same code to the same path produces the same file content. |

### MCP Server → Extraction Handler

| Property | Value |
|----------|-------|
| Input validation | MCP Server validates: `definition_name` is non-empty, `language` is a supported enum value, `output_path` (when present) is an absolute path. |
| Output format | ExtractionResult or CodeExtractionError, formatted per MCP standard error format defined in [mcp-server.md](mcp-server.md). |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Session not found or expired | `SESSION_NOT_FOUND` | Return error immediately; no extraction attempted |
| Definition not found in Coq environment | `DEFINITION_NOT_FOUND` | Return error identifying the unknown name |
| Unsupported target language value | `INVALID_LANGUAGE` | Return error listing the three supported languages: OCaml, Haskell, Scheme |

### 7.2 Extraction Errors

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Extraction command fails in Coq | `EXTRACTION_FAILED` | Parse error into CodeExtractionError with category, explanation, and suggestions |
| Backend process crashes during extraction | `BACKEND_CRASHED` | Return error advising the user to close and reopen the session |

### 7.3 Write Errors

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Output path parent directory does not exist | `INVALID_OUTPUT_PATH` | Return error identifying the missing directory |
| Output path is not absolute | `INVALID_OUTPUT_PATH` | Return error requiring an absolute path |
| File write fails (permissions, disk full) | `WRITE_FAILED` | Return error with the filesystem error message |

### 7.4 Edge Cases

| Condition | Behavior |
|-----------|----------|
| Extraction output is empty and matches no error pattern | Return ExtractionResult with empty `code` string and a warning indicating empty extraction output |
| Extraction output contains both code lines and error lines | Treat as error — return CodeExtractionError. Partial extraction output is not returned. |
| Definition name contains spaces or special characters | Pass verbatim to Coq; Coq's parser determines validity |
| Same definition extracted twice in one session | Second extraction succeeds identically (idempotent) |
| Write to a path that already exists | Overwrite the existing file |

All error responses use the MCP standard error format defined in [mcp-server spec](mcp-server.md).

## 8. Non-Functional Requirements

- The command constructor shall produce the command sequence in < 1 ms (no I/O, no parsing).
- Error classification shall complete in < 5 ms per error message (pattern matching only).
- Write mode shall support output files up to 10 MB without degradation.
- The extraction handler shall not buffer more than one extraction result in memory at a time.
- The extraction handler shall not spawn subprocesses — all Coq interaction is delegated to the Proof Session Manager.

## 9. Examples

### Preview — single extraction to OCaml

```
extract_code(session_id="s1", definition_name="double", language="OCaml", recursive=false)

Command submitted: "Extraction Language OCaml. Extraction double."
Coq output: "let double n = n + n"

Result:
{
  "definition_name": "double",
  "language": "OCaml",
  "recursive": false,
  "code": "let double n = n + n",
  "warnings": [],
  "output_path": null
}
```

### Preview — recursive extraction to Haskell

```
extract_code(session_id="s2", definition_name="serialize", language="Haskell", recursive=true)

Command submitted: "Extraction Language Haskell. Recursive Extraction serialize."
Coq output: "module Serialize where\n  serialize :: Tree -> String\n  serialize = ..."

Result:
{
  "definition_name": "serialize",
  "language": "Haskell",
  "recursive": true,
  "code": "module Serialize where\n  serialize :: Tree -> String\n  serialize = ...",
  "warnings": [],
  "output_path": null
}
```

### Write — persist extracted code

```
write_extraction(code="let double n = n + n", output_path="/project/extracted/double.ml")

Result:
{
  "output_path": "/project/extracted/double.ml",
  "bytes_written": 20
}
```

### Failure — opaque term

```
extract_code(session_id="s3", definition_name="opaque_lemma", language="OCaml", recursive=false)

Command submitted: "Extraction Language OCaml. Extraction opaque_lemma."
Coq output: "Error: opaque_lemma is not a defined object."

Result:
{
  "definition_name": "opaque_lemma",
  "language": "OCaml",
  "category": "opaque_term",
  "raw_error": "Error: opaque_lemma is not a defined object.",
  "explanation": "The definition or one of its dependencies is opaque (marked Qed instead of Defined, or behind an abstraction barrier). Coq cannot extract computational content from opaque terms.",
  "suggestions": [
    "Change Qed to Defined if the proof is computational.",
    "Use Transparent opaque_lemma. to expose the term.",
    "Provide an Extract Constant directive mapping the opaque term to target language code."
  ]
}
```

### Failure — axiom without realizer (warning in successful extraction)

```
extract_code(session_id="s4", definition_name="uses_axiom", language="OCaml", recursive=false)

Command submitted: "Extraction Language OCaml. Extraction uses_axiom."
Coq output: "let uses_axiom = ... (assert false (* AXIOM TO BE REALIZED *))\nWarning: my_axiom has no body."

Result:
{
  "definition_name": "uses_axiom",
  "language": "OCaml",
  "recursive": false,
  "code": "let uses_axiom = ... (assert false (* AXIOM TO BE REALIZED *))",
  "warnings": ["Warning: my_axiom has no body."],
  "output_path": null
}
```

## 10. Language-Specific Notes (Python)

- Package location: `src/poule/extraction/`.
- All public functions are module-level functions, not methods on a class.
- Command construction is a pure function: `build_command(definition_name: str, language: str, recursive: bool) -> str`.
- Error classification uses compiled regular expressions matched in priority order against the command output.
- File writing uses `pathlib.Path` for path validation (`is_absolute()`, `parent.exists()`) and atomic write semantics where the platform supports it.
- Entry point: `async def extract_code(session_manager, session_id: str, definition_name: str, language: str, recursive: bool = False, output_path: str | None = None) -> ExtractionResult | CodeExtractionError`.
- Write entry point: `def write_extraction(code: str, output_path: str) -> WriteConfirmation`.
- Use `dataclasses` or `pydantic` for ExtractionRequest, ExtractionResult, CodeExtractionError, and WriteConfirmation.
