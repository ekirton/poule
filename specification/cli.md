# CLI

Command-line interface for indexing and search operations against the Coq/Rocq declaration index.

**Architecture**: [cli.md](../doc/architecture/cli.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [response-types.md](../doc/architecture/data-models/response-types.md)

---

## 1. Purpose

Define the CLI layer that accepts user commands from the terminal, validates input, delegates to the retrieval pipeline, and formats results for stdout.

## 2. Scope

**In scope**: 7 search subcommands, 1 proof replay subcommand, shared option handling, input validation, human-readable and JSON output formatting, index state checks, error reporting.

**Out of scope**: Search logic (owned by pipeline/channels), storage management (owned by storage), Coq expression parsing (owned by pipeline), MCP protocol handling (owned by MCP server).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Subcommand | A named CLI operation (e.g., `search-by-name`) that maps to a pipeline function |
| Human-readable format | The default text output designed for terminal viewing |
| JSON format | Machine-readable output activated by `--json`, using the same field names as MCP response types |

## 4. Behavioral Requirements

### 4.1 Shared Options

All search subcommands shall accept:

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--db` | path | required | File must exist; schema version must match |
| `--json` | flag | false | — |
| `--limit` | integer | 50 | Clamped to [1, 200] (same as MCP server) |

Exception: `get-lemma` does not accept `--limit`.

### 4.2 Subcommand Signatures

#### search-by-name(pattern, limit=50)

- REQUIRES: `pattern` is a non-empty string. `--db` points to a valid index.
- ENSURES: Prints up to `limit` `SearchResult` items ranked by BM25 relevance.
- Delegates to: `pipeline.search_by_name(ctx, pattern, limit)`

#### search-by-type(type_expr, limit=50)

- REQUIRES: `type_expr` is a non-empty string. `--db` points to a valid index.
- ENSURES: Prints up to `limit` `SearchResult` items ranked by RRF-fused score.
- Delegates to: `pipeline.search_by_type(ctx, type_expr, limit)`

#### search-by-structure(expression, limit=50)

- REQUIRES: `expression` is a non-empty string. `--db` points to a valid index.
- ENSURES: Prints up to `limit` `SearchResult` items ranked by structural score.
- Delegates to: `pipeline.search_by_structure(ctx, expression, limit)`

#### search-by-symbols(symbols, limit=50)

- REQUIRES: `symbols` is a non-empty list of strings. `--db` points to a valid index.
- ENSURES: Prints up to `limit` `SearchResult` items ranked by MePo relevance.
- Delegates to: `pipeline.search_by_symbols(ctx, symbols, limit)`

#### get-lemma(name)

- REQUIRES: `name` is a non-empty string. `--db` points to a valid index.
- ENSURES: Prints a single `LemmaDetail` for the named declaration.
- On not found: prints error to stderr, exits with code 1.
- Delegates to: pipeline queries for declaration row, dependencies, dependents, symbols, node count.

#### find-related(name, relation, limit=50)

- REQUIRES: `name` is a non-empty string. `relation` is one of: `"uses"`, `"used_by"`, `"same_module"`, `"same_typeclass"`. `--db` points to a valid index.
- ENSURES: Prints up to `limit` `SearchResult` items for related declarations.
- On unknown declaration name: prints error to stderr, exits with code 1.
- Delegates to: the same query strategies as the MCP server's `find_related` handler.

#### list-modules(prefix="", limit=50)

- REQUIRES: `--db` points to a valid index. `prefix` is a string (may be empty or omitted).
- ENSURES: Prints `Module` objects for all modules matching the prefix.

### 4.3 Input Validation

The CLI shall validate all inputs before delegating to the pipeline:

| Validation | Rule |
|-----------|------|
| `--db` path | Must be an existing file |
| String positional arguments | Must be non-empty after stripping whitespace |
| `--limit` | Clamped to [1, 200] |
| `symbols` list | Must contain at least one non-empty element |
| `--relation` | Must be one of the four recognized values |

Invalid inputs shall print an error to stderr and exit with code 2 (usage error).

### 4.4 Index State Checks

On startup, each search subcommand shall:

1. Verify the database file exists at `--db` path. If not → print `Index database not found at {path}. Run the indexing command to create it.` to stderr, exit 1.
2. Open the database and verify `schema_version` in `index_meta` matches the expected version. If not → print `Index schema version {found} is incompatible with tool version {expected}. Re-index to update.` to stderr, exit 1.
3. Create `PipelineContext` from the validated database.

### 4.5 Output Formatting

#### Human-Readable (default)

For `SearchResult` lists, each result shall be formatted as:
```
<name>  <kind>  <score formatted to 4 decimal places>
  <statement>
  module: <module>
```
Results are separated by blank lines. When the result list is empty, nothing is printed.

For `LemmaDetail`, the output shall be:
```
<name>  (<kind>)
  <statement>
  module:       <module>
  dependencies: <count>
  dependents:   <count>
  symbols:      <comma-separated list>
  node_count:   <n>
```

For `Module` lists, each module shall be formatted as:
```
<module_name>  (<declaration_count> declarations)
```

#### JSON (`--json`)

For search commands: a JSON array printed to stdout. Each element uses the same field names and types as the MCP `SearchResult` response type.

For `get-lemma`: a single JSON object using `LemmaDetail` field names.

For `list-modules`: a JSON array of `Module` objects.

JSON output shall be compact (no pretty-printing) to support piping to `jq` and other tools.

### 4.6 replay-proof(file_path, proof_name)

- REQUIRES: `file_path` is a non-empty string. `proof_name` is a non-empty string.
- ENSURES: Opens a proof session, extracts the complete proof trace, formats and prints the trace to stdout, closes the session, and exits with code 0.
- On file not found: prints error to stderr, exits with code 1.
- On proof not found: prints error to stderr, exits with code 1.
- On backend crash: prints error to stderr, exits with code 1.
- Session is always closed (even on error) to prevent resource leaks.
- Delegates to: `SessionManager.create_session`, `SessionManager.extract_trace`, `SessionManager.get_premises` (if `--premises`), `SessionManager.close_session`.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--json` | flag | false | Output as JSON instead of human-readable format |
| `--premises` | flag | false | Include per-step premise annotations |

**Output formatting:**

Human-readable (default):
```
Proof: <proof_name>
File:  <file_path>
Steps: <total_steps>

--- Step 0 (initial) ---
Goal 1: <goal_type>
  <hyp_name> : <hyp_type>

--- Step 1: <tactic> ---
Goal 1: <goal_type>
  <hyp_name> : <hyp_type>
```

When `--premises` is active, each step block with a tactic appends a premises line:
```
  Premises: <name> (<kind>), <name> (<kind>)
```

JSON without `--premises`: the output of `serialize_proof_trace(trace)`.

JSON with `--premises`: `{"trace": <parsed trace object>, "premises": [<parsed premise annotation objects>]}`. Both values are JSON objects (not embedded strings).

**Given/When/Then examples:**

1. GIVEN `test.v` contains proof `add_comm` with 3 steps WHEN `replay-proof test.v add_comm` is run THEN stdout contains "Proof: add_comm", "Steps: 3", and three step blocks, and exit code is 0.

2. GIVEN `test.v` contains proof `add_comm` WHEN `replay-proof test.v add_comm --json` is run THEN stdout is valid JSON matching the `ProofTrace` schema with `total_steps` and `steps` fields.

3. GIVEN `test.v` does not exist WHEN `replay-proof test.v add_comm` is run THEN stderr contains "File not found" and exit code is 1.

## 5. Error Specification

| Condition | Exit code | stderr message |
|-----------|-----------|---------------|
| Missing `--db` file | 1 | `Index database not found at {path}. Run the indexing command to create it.` |
| Schema version mismatch | 1 | `Index schema version {found} is incompatible with tool version {expected}. Re-index to update.` |
| Declaration not found | 1 | `Declaration {name} not found in the index.` |
| Parse failure | 1 | `Failed to parse expression: {details}` |
| Invalid usage (missing args, bad option) | 2 | Usage error from argument parser |
| Empty results | 0 | (no output in human-readable; `[]` in JSON) |
| File not found (replay-proof) | 1 | `File not found: {path}` |
| Proof not found (replay-proof) | 1 | `Proof not found: {name}` |
| Backend crashed (replay-proof) | 1 | `Backend crashed during proof replay.` |

Errors are always printed to stderr. Successful output is always printed to stdout. This separation supports piping and redirection.

## 6. Non-Functional Requirements

- Startup time includes loading `PipelineContext` into memory (same overhead as MCP server startup).
- The CLI does not persist a long-running process; each invocation creates and destroys its own `PipelineContext`.
- The CLI shall not import MCP-specific dependencies.

## 7. Examples

### search-by-name (human-readable)

```
$ wily-rooster search-by-name --db index.db "Nat.add_comm" --limit 3
Coq.Arith.PeanoNat.Nat.add_comm  lemma  0.9500
  forall n m : nat, n + m = m + n
  module: Coq.Arith.PeanoNat

Coq.Arith.PeanoNat.Nat.add_comm_l  lemma  0.8200
  forall n m : nat, n + m = m + n
  module: Coq.Arith.PeanoNat
```

### search-by-name (JSON)

```
$ wily-rooster search-by-name --db index.db "Nat.add_comm" --limit 3 --json
[{"name":"Coq.Arith.PeanoNat.Nat.add_comm","statement":"forall n m : nat, n + m = m + n","type":"forall n m : nat, n + m = m + n","module":"Coq.Arith.PeanoNat","kind":"lemma","score":0.95}]
```

### get-lemma (error)

```
$ wily-rooster get-lemma --db index.db "nonexistent.declaration"
Declaration nonexistent.declaration not found in the index.
$ echo $?
1
```

### Missing index

```
$ wily-rooster search-by-name --db missing.db "test"
Index database not found at missing.db. Run the indexing command to create it.
$ echo $?
1
```

### replay-proof (human-readable)

```
$ wily-rooster replay-proof test.v add_comm
Proof: add_comm
File:  test.v
Steps: 2

--- Step 0 (initial) ---
Goal 1: forall n m : nat, n + m = m + n
  n : nat
  m : nat

--- Step 1: intros n m. ---
Goal 1: n + m = m + n
  n : nat
  m : nat

--- Step 2: ring. ---
(proof complete)
```

### replay-proof (JSON)

```
$ wily-rooster replay-proof test.v add_comm --json
{"schema_version":1,"session_id":"...","proof_name":"add_comm","file_path":"test.v","total_steps":2,"steps":[...]}
```

### replay-proof (JSON with premises)

```
$ wily-rooster replay-proof test.v add_comm --json --premises
{"trace":{"schema_version":1,...},"premises":[{"step_index":1,"tactic":"intros n m.","premises":[]},...]}
```

### replay-proof (error)

```
$ wily-rooster replay-proof nonexistent.v add_comm
File not found: nonexistent.v
$ echo $?
1
```

## 8. Language-Specific Notes (Python)

- Use `click` for argument parsing (consistent with the existing extraction CLI).
- Use `click.Group` to organize search subcommands under a single entry point.
- Reuse `PipelineContext` and `create_context` from `wily_rooster.pipeline.context`.
- Reuse pipeline search functions from `wily_rooster.pipeline.search`.
- Reuse `SearchResult`, `LemmaDetail`, `Module` from `wily_rooster.models.responses`.
- JSON serialization via `dataclasses.asdict()` + `json.dumps()` (same as MCP server).
- For proof replay: use `SessionManager` from `wily_rooster.session.manager`, `serialize_proof_trace` and `serialize_premise_annotation` from `wily_rooster.serialization.serialize`.
- Use `asyncio.run()` to bridge Click's sync execution model to the async `SessionManager` API.
- Package location: `src/wily_rooster/cli/`.
