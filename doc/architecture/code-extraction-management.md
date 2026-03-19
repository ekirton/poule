# Code Extraction Management

The component that manages extraction of verified Coq/Rocq definitions to executable OCaml, Haskell, or Scheme code. Claude Code invokes extraction as an MCP tool; the Extraction Handler constructs the appropriate Coq command, executes it within a proof session, and returns the extracted code for preview or writes it to disk.

**Feature**: [Code Extraction Management](../features/code-extraction-management.md)
**Stories**: [Epics 1--4](../requirements/stories/code-extraction.md)
**PRD**: [Code Extraction](../requirements/code-extraction.md)

---

## Component Diagram

```
MCP Server
  |
  | extract_code(definition, language, recursive, output_path?)
  v
+---------------------------------------------------------------+
|                   Extraction Handler                           |
|                                                               |
|  +---------------------------+  +---------------------------+ |
|  | Command Constructor       |  | Result Parser             | |
|  |                           |  |                           | |
|  | Builds Coq Extraction or  |  | Classifies lines in      | |
|  | Recursive Extraction      |  | merged command output    | |
|  | command from request      |  | by pattern               | |
|  +---------------------------+  +---------------------------+ |
|                                                               |
|  +---------------------------+                                |
|  | Output Writer             |                                |
|  |                           |                                |
|  | Writes extracted code to  |                                |
|  | target file on user       |                                |
|  | confirmation              |                                |
|  +---------------------------+                                |
+---------------------------------------------------------------+
  |                                     |
  | submit_command (returns str)        | file write (write mode only)
  v                                     v
Proof Session Manager               Filesystem
  |
  v
Coq Backend Process (stdout+stderr merged)
```

## Boundary Contract

The Extraction Handler is invoked by the MCP Server and delegates command execution to the Proof Session Manager. It does **not**:

- Parse Coq expressions or resolve definition names -- that is the Coq backend's responsibility
- Manage session lifecycle -- sessions are opened and closed by the MCP Server
- Compile or type-check extracted output in the target language
- Modify Coq source files to make definitions extractable

The MCP Server is responsible for validating inputs (non-empty definition name, supported language enum) before delegating to the Extraction Handler.

## Extraction Command Construction

The Command Constructor maps an ExtractionRequest to a Coq command string. The mapping is deterministic and depends on two request fields: the target language and whether extraction is recursive.

### Target Language Mapping

| Target Language | Coq Language Directive |
|-----------------|----------------------|
| OCaml           | `Extraction Language OCaml.` (default; may be omitted) |
| Haskell         | `Extraction Language Haskell.` |
| Scheme          | `Extraction Language Scheme.` |

The language directive is issued before the extraction command to configure Coq's extraction backend.

### Command Templates

| Mode | Coq Command |
|------|-------------|
| Single extraction | `Extraction {definition_name}.` |
| Recursive extraction | `Recursive Extraction {definition_name}.` |

The full command sequence submitted to the Coq backend is:

```
Extraction Language {language}.
{Extraction | Recursive Extraction} {definition_name}.
```

The definition name is passed verbatim to Coq. Fully qualified names (e.g., `Coq.Init.Nat.add`) and short names (e.g., `add`) are both valid -- Coq resolves the reference within the current environment.

## Single Extraction Flow

```
extract_code(definition="my_fn", language="OCaml", recursive=false)
  |
  +-- Command Constructor builds:
  |     "Extraction Language OCaml. Extraction my_fn."
  |
  +-- Submit command sequence to Proof Session Manager
  |     (via submit_command, which returns a single output string)
  |
  +-- Result Parser classifies output lines by pattern:
  |     |
  |     +-- output contains error pattern (e.g., line starting with "Error:")?
  |     |     -> ExtractionError with raw_error, category, explanation, suggestions
  |     |
  |     +-- no error pattern; remaining lines are extracted code
  |           -> ExtractionResult with code, language, definition_name
  |           (lines matching warning patterns captured separately in warnings)
  |
  +-- Return ExtractionResult or ExtractionError to MCP Server
```

Single extraction produces the extracted code for exactly one definition. Dependencies referenced by the definition are not included -- the output may reference external names that must be provided separately.

## Recursive Extraction Flow

```
extract_code(definition="serialize", language="OCaml", recursive=true)
  |
  +-- Command Constructor builds:
  |     "Extraction Language OCaml. Recursive Extraction serialize."
  |
  +-- Submit command sequence to Proof Session Manager
  |     (via submit_command, which returns a single output string)
  |
  +-- Result Parser classifies output lines by pattern:
  |     |
  |     +-- output contains error pattern?
  |     |     -> ExtractionError
  |     |
  |     +-- no error pattern; remaining lines are extracted code
  |           -> ExtractionResult with code containing all transitive dependencies
  |           (warning lines captured separately)
  |
  +-- Return ExtractionResult or ExtractionError to MCP Server
```

Recursive extraction includes the definition and all its transitive dependencies in a single self-contained output. If the definition has no dependencies beyond Coq's built-in types, the output is equivalent to single extraction.

## Preview Mode

Preview is the default mode. When `output_path` is not specified (or the request is the initial extraction), the Extraction Handler returns the extracted code in the ExtractionResult without writing to disk.

The flow is identical to the single or recursive extraction flows above. The extracted code is returned in the `code` field of ExtractionResult. The MCP Server includes it in the tool response so the user can review it.

No temporary files are created. The extracted code exists only in memory as part of the response.

## Write Mode

When the user confirms a previewed extraction and provides an `output_path`, the Extraction Handler writes the extracted code to disk.

```
write_extraction(code, output_path)
  |
  +-- Validate output_path is an absolute path
  |
  +-- Validate parent directory exists
  |
  +-- Write extracted code to output_path
  |     (overwrite if file exists; create if it does not)
  |
  +-- Return confirmation with output_path and bytes written
```

Write mode operates on previously extracted code. It does not re-execute extraction -- it writes the `code` string from a prior ExtractionResult. This separation ensures that the user reviews exactly the code that gets written.

## Failure Diagnosis

When extraction fails, the Result Parser classifies the Coq error into one of five categories and generates a structured ExtractionError with a plain-language explanation and suggested fixes.

### Error Classification

The Result Parser matches patterns in the command output against known error signatures:

| Category | Coq Error Pattern | Explanation | Suggested Fixes |
|----------|------------------|-------------|-----------------|
| `opaque_term` | `is not a defined object` or opacity-related message | The definition or one of its dependencies is opaque (marked `Qed` instead of `Defined`, or behind an abstraction barrier). Coq cannot extract computational content from opaque terms. | 1. Change `Qed` to `Defined` if the proof is computational. 2. Use `Transparent {name}.` to expose the term. 3. Provide an `Extract Constant` directive mapping the opaque term to target language code. |
| `axiom_without_realizer` | `has no body` or axiom-related extraction warning | An axiom used by the definition has no computational realizer. Extraction produces a stub (`assert false` in OCaml, `error` in Haskell) that will fail at runtime. | 1. Provide `Extract Constant {axiom} => "{implementation}".` to bind the axiom to target language code. 2. Replace the axiom with a proven definition. |
| `universe_inconsistency` | `Universe inconsistency` | A universe constraint conflict prevents extraction. This typically arises from mixing universe-polymorphic and monomorphic definitions. | 1. Check for universe-polymorphic definitions that conflict with monomorphic ones. 2. Restructure the definition to avoid the inconsistency. |
| `unsupported_match` | `Cannot extract` with match-related context | Coq's extraction mechanism does not support the match pattern used in the definition. Deep pattern matching on dependent types is a common trigger. | 1. Refactor the match to use simpler patterns. 2. Introduce an auxiliary function that eliminates the problematic pattern. |
| `module_type_mismatch` | `Module type` or functor-related error | A module type mismatch prevents extraction. This occurs when module functors or signatures do not align during extraction. | 1. Verify module signatures match the expected types. 2. Simplify module structure to avoid functor application issues. |
| `unknown` | Any unrecognized error | Extraction failed for a reason not in the known categories. The raw Coq error is included for manual diagnosis. | 1. Consult the Coq reference manual for the specific error. 2. Simplify the definition and retry extraction to isolate the cause. |

The classifier attempts pattern matching in order from most specific to least specific. If no known pattern matches, the error is classified as `unknown`.

## Data Structures

### ExtractionRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | Active proof session with the definition in scope |
| `definition_name` | string | yes | Coq definition to extract (short or fully qualified name) |
| `language` | `"OCaml"` or `"Haskell"` or `"Scheme"` | yes | Target extraction language |
| `recursive` | boolean | no (default: false) | Whether to use `Recursive Extraction` to include transitive dependencies |
| `output_path` | string | no | Absolute file path to write extracted code; omit for preview mode |

### ExtractionResult

| Field | Type | Description |
|-------|------|-------------|
| `definition_name` | string | The definition that was extracted |
| `language` | `"OCaml"` or `"Haskell"` or `"Scheme"` | Target language of the extracted code |
| `recursive` | boolean | Whether recursive extraction was used |
| `code` | string | The extracted source code |
| `warnings` | list of string | Non-fatal warnings from Coq (e.g., axiom realizer warnings) |
| `output_path` | string or null | File path if code was written to disk; null for preview |

### ExtractionError

| Field | Type | Description |
|-------|------|-------------|
| `definition_name` | string | The definition that failed to extract |
| `language` | `"OCaml"` or `"Haskell"` or `"Scheme"` | Requested target language |
| `category` | `"opaque_term"` or `"axiom_without_realizer"` or `"universe_inconsistency"` or `"unsupported_match"` or `"module_type_mismatch"` or `"unknown"` | Classified failure category |
| `raw_error` | string | The verbatim Coq error message |
| `explanation` | string | Plain-language explanation of the failure cause |
| `suggestions` | list of string | One or more actionable fix suggestions |

## Error Handling

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Session not found or expired | `SESSION_NOT_FOUND` | Return structured error immediately; no extraction attempted |
| Definition not found in environment | `DEFINITION_NOT_FOUND` | Return error identifying the unknown name |
| Unsupported target language | `INVALID_LANGUAGE` | Return error listing the three supported languages |
| Extraction command fails in Coq | `EXTRACTION_FAILED` | Parse error into ExtractionError with category, explanation, and suggestions |
| Backend process crashed during extraction | `BACKEND_CRASHED` | Return error advising the user to close and reopen the session |
| Output path parent directory does not exist (write mode) | `INVALID_OUTPUT_PATH` | Return error identifying the missing directory |
| Output path is not absolute (write mode) | `INVALID_OUTPUT_PATH` | Return error requiring an absolute path |
| File write fails (permissions, disk full) | `WRITE_FAILED` | Return error with the filesystem error message |

All error responses use the MCP standard error format defined in [mcp-server.md](mcp-server.md).

## Design Rationale

### Why session-based execution

Extraction requires definitions to be in scope in a Coq environment. The Proof Session Manager already manages Coq backend processes with loaded environments. Reusing an active session means the user's definitions, imports, and extraction directives are already available -- no separate environment setup is needed. This avoids spawning a new Coq process for each extraction request and keeps extraction consistent with the proof state the user is working in.

### Why preview before write

Extraction output varies significantly by target language, extraction options, and definition structure. Writing directly to a file forces the user into a generate-inspect-delete cycle when the output is wrong. Returning the code in the response first lets the user evaluate it before committing. This is especially valuable when comparing extraction across target languages or iterating on extraction directives -- no files are created or overwritten during exploration.

### Why classify errors rather than forwarding raw output

Coq's extraction errors assume familiarity with extraction internals. The five known categories cover the most common failure modes encountered in practice. Classifying the error and attaching a plain-language explanation with actionable suggestions closes the gap between the error and the fix. Users who need the raw error can still access it in the `raw_error` field; the classification is additive, not lossy.

### Relationship to assumption auditing

Definitions that depend on axioms without realizers extract to stubs that fail at runtime. The extraction handler surfaces axiom-related warnings in the `warnings` field of ExtractionResult, connecting extraction quality to proof hygiene. This complements assumption auditing: axiom-free definitions extract cleanly, while axiom-dependent definitions produce warnings that guide the user toward providing realizers or eliminating the axiom dependency.
