# CLI

Command-line interface for indexing, search, proof replay, and batch extraction operations against the Coq/Rocq declaration index and proof developments.

**Architecture**: [cli.md](../doc/architecture/cli.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [response-types.md](../doc/architecture/data-models/response-types.md), [extraction-types.md](../doc/architecture/data-models/extraction-types.md)

---

## 1. Purpose

Define the CLI layer that accepts user commands from the terminal, validates input, delegates to the retrieval pipeline, and formats results for stdout.

## 2. Scope

**In scope**: 7 search subcommands, 1 proof replay subcommand, 1 distribution subcommand, 3 extraction subcommands, 7 neural subcommands, shared option handling, input validation, human-readable and JSON output formatting, index state checks, error reporting.

**Out of scope**: Search logic (owned by pipeline/channels), storage management (owned by storage), Coq expression parsing (owned by pipeline), MCP protocol handling (owned by MCP server), extraction logic (owned by extraction-campaign), output serialization (owned by extraction-output), download client internals (owned by prebuilt-distribution).

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

### 4.7 extract(project_dirs, output_path, options)

- REQUIRES: `project_dirs` is a non-empty list of directory paths. `output_path` is a non-empty string. All project directories exist on disk.
- ENSURES: Creates an Extraction Campaign Orchestrator. Delegates campaign execution to `run_campaign(project_dirs, output_path, options)`. Prints a human-readable extraction summary to stderr on completion. Exits with code 0 on success (including partial success with some failures). Exits with code 1 when all proofs fail or a project directory does not exist. Exits with code 2 on invalid usage.
- Delegates to: `ExtractionCampaignOrchestrator.run_campaign`.

**Options:**

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--output` | path | required | Parent directory must exist |
| `--name-pattern` | string | null | Must be a valid glob or regex when provided (P1) |
| `--modules` | comma-separated string | null | Each module prefix must be non-empty (P1) |
| `--incremental` | flag | false | Requires existing output file and checkpoint (P1) |
| `--resume` | flag | false | Requires existing output file and checkpoint (P1) |
| `--include-diffs` | flag | false | — (P1) |
| `--timeout` | integer | 60 | Must be positive; per-proof timeout in seconds |

- MAINTAINS: `--incremental` and `--resume` are mutually exclusive. When both are set, the CLI shall print an error to stderr and exit with code 2.

> **Given** two project directories `/stdlib` and `/mathcomp`
> **When** `extract /stdlib /mathcomp --output combined.jsonl` is run
> **Then** a JSON Lines output file is written at `combined.jsonl`, a summary is printed to stderr, and exit code is 0

> **Given** a project directory `/nonexistent` that does not exist
> **When** `extract /nonexistent --output out.jsonl` is run
> **Then** an error is printed to stderr and exit code is 1

> **Given** `--incremental` and `--resume` are both set
> **When** `extract /stdlib --output out.jsonl --incremental --resume` is run
> **Then** an error is printed to stderr and exit code is 2

**Output behavior:**

- The JSON Lines output file is written to `--output`. The CLI does not write extraction records to stdout.
- Progress information is printed to stderr during extraction (e.g., `Extracting theorem 42/1000...`).
- On completion, a human-readable summary is printed to stderr:

```
Extraction complete.
  Theorems found:    1000
  Extracted:          950
  Failed:              45
  Skipped:              5
  Output: /path/to/output.jsonl
```

### 4.8 extract-deps(extraction_output_path, output_path)

- REQUIRES: `extraction_output_path` is a non-empty string pointing to a valid JSON Lines extraction output file. `output_path` is a non-empty string.
- ENSURES: Reads ExtractionRecords from the input. Computes a DependencyEntry for each. Writes DependencyEntries as JSON Lines to `output_path`. Prints a summary to stderr. Exits with code 0.
- On invalid input file: prints error to stderr, exits with code 1.
- Delegates to: `extract_dependency_graph(extraction_output_path, output_path)`.

> **Given** an extraction output with 100 ExtractionRecords
> **When** `extract-deps extraction.jsonl --output deps.jsonl` is run
> **Then** `deps.jsonl` contains 100 DependencyEntry lines and exit code is 0

> **Given** an extraction output that is not valid JSON Lines
> **When** `extract-deps bad_input.jsonl --output deps.jsonl` is run
> **Then** an error with the invalid line number is printed to stderr and exit code is 1

### 4.9 quality-report(extraction_output_path)

- REQUIRES: `extraction_output_path` is a non-empty string pointing to a valid JSON Lines extraction output file.
- ENSURES: Reads ExtractionRecords from the input. Computes a QualityReport. Formats and prints the report to stdout (or to `--output` file if specified). Exits with code 0.
- On invalid input file: prints error to stderr, exits with code 1.
- Delegates to: `generate_quality_report(extraction_output_path)`.

**Options:**

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--json` | flag | false | — |
| `--output` | path | null | Parent directory must exist when provided |

**Output formatting:**

Human-readable (default):
```
Quality Report
==============
Premise coverage: 87.0%
Proof length: min=1, max=342, mean=12.4, median=8.0, p25=4.0, p75=16.0, p95=45.0

Top tactics:
  apply       24500
  rewrite     18200
  simpl       15800

Per-project:
  coq-stdlib  (4500 theorems, 89.0% premise coverage)
```

JSON (`--json`): a single QualityReport JSON object (compact format).

> **Given** an extraction output with 1000 ExtractionRecords
> **When** `quality-report extraction.jsonl` is run
> **Then** a human-readable quality report is printed to stdout and exit code is 0

> **Given** an extraction output with 1000 ExtractionRecords
> **When** `quality-report extraction.jsonl --json` is run
> **Then** a QualityReport JSON object is printed to stdout and exit code is 0

### 4.10 build-vocabulary(db, data, output)

- REQUIRES: `db` points to a valid index database. `data` is a non-empty list of paths to JSON Lines extraction output files. `output` is a writable path.
- ENSURES: Builds a closed vocabulary from the search index and training data. Writes a JSON file mapping tokens to integer IDs to `output`. Prints a VocabularyReport summary to stderr. Exits with code 0.
- Delegates to: `VocabularyBuilder.build`.

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--db` | path | required | File must exist |
| `--data` | path(s) | required | Each file must exist |
| `--output` | path | required | Parent directory must exist |

**Output (stderr):**

```
Vocabulary built.
  Total tokens:       15,425
  Special tokens:          5
  Fixed tokens:          120
  Index declarations: 15,000
  Training data:         300
  Output: coq-vocabulary.json
```

> **Given** a valid index database and extraction files
> **When** `build-vocabulary --db index.db --data stdlib.jsonl --output coq-vocabulary.json` is run
> **Then** a vocabulary JSON file is written, a summary is printed to stderr, and exit code is 0

> **Given** an index database with no declarations
> **When** `build-vocabulary --db empty.db --data stdlib.jsonl --output coq-vocabulary.json` is run
> **Then** `"No declarations found in index database"` is printed to stderr and exit code is 1

### 4.11 train(traces, vocabulary, db, output, hyperparams)

- REQUIRES: `traces` is a non-empty list of paths to JSON Lines extraction output files. `vocabulary` points to a valid vocabulary JSON file. `db` points to a valid index database. `output` is a writable path.
- ENSURES: Validates training data. Loads dataset with train/val/test split. Trains a hierarchical tactic classifier using the closed vocabulary. Saves the best checkpoint to `output`. Prints training progress (epoch, loss, validation acc@5) to stderr. Exits with code 0.
- Delegates to: `TrainingDataValidator.validate`, `TrainingDataLoader.load`, `TacticClassifierTrainer.train`.

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--vocabulary` | path | required | File must exist |
| `--db` | path | required | File must exist |
| `--output` | path | required | Parent directory must exist |
| `--epochs` | integer | 20 | Must be positive |
| `--batch-size` | integer | 256 | Must be positive |
| `--lr` | float | 2e-5 | Must be positive |

> **Given** valid extraction files, vocabulary, and index database
> **When** `train stdlib.jsonl --vocabulary coq-vocabulary.json --db index.db --output model.pt` is run
> **Then** training progress is printed to stderr, model checkpoint is saved, exit code is 0

> **Given** an extraction file with < 1,000 valid training pairs
> **When** `train small.jsonl --vocabulary coq-vocabulary.json --db index.db --output model.pt` is run
> **Then** `"Insufficient training data"` is printed to stderr and exit code is 1

### 4.12 evaluate(checkpoint, test_data, db)

- REQUIRES: `checkpoint` points to a valid model checkpoint. `test_data` points to a JSON Lines extraction file. `db` points to a valid index database.
- ENSURES: Prints an EvaluationReport (accuracy@1, accuracy@5, category accuracy@1, per-family precision/recall) to stdout. Exits with code 0.
- Delegates to: `TacticEvaluator.evaluate`.

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--checkpoint` | path | required | File must exist |
| `--test-data` | path | required | File must exist |
| `--db` | path | required | File must exist |
| `--json` | flag | false | — |

> **Given** a trained model and test data
> **When** `evaluate --checkpoint model.pt --test-data test.jsonl --db index.db` is run
> **Then** retrieval metrics are printed to stdout and exit code is 0

### 4.13 quantize(checkpoint, output)

- REQUIRES: `checkpoint` points to a valid PyTorch training checkpoint. `output` is a writable path.
- ENSURES: Exports to ONNX, applies INT8 quantization, validates quality (max cosine distance < 0.02), writes ONNX model to `output`. Exits with code 0.
- Delegates to: `ModelQuantizer.quantize`.

| Option | Type | Default | Validation |
|--------|------|---------|------------|
| `--checkpoint` | path | required | File must exist |
| `--output` | path | required | Parent directory must exist |

> **Given** a valid model checkpoint
> **When** `quantize --checkpoint model.pt --output model.onnx` is run
> **Then** an INT8 ONNX model is written and exit code is 0

> **Given** a model that fails quantization validation (cosine distance ≥ 0.02)
> **When** `quantize --checkpoint model.pt --output model.onnx` is run
> **Then** the max cosine distance is printed to stderr and exit code is 1

### 4.14 validate-training-data(traces)

- REQUIRES: `traces` is a non-empty list of paths to JSON Lines extraction output files.
- ENSURES: Prints a ValidationReport to stdout. Exits with code 0 (even when warnings are present — validation warnings are informational, not failures).
- Delegates to: `TrainingDataValidator.validate`.

> **Given** extraction files with 50,000 steps
> **When** `validate-training-data stdlib.jsonl mathcomp.jsonl` is run
> **Then** a validation report is printed to stdout and exit code is 0

### 4.15 download-index(output, include_model, model_dir, force)

Specified in [prebuilt-distribution.md](prebuilt-distribution.md) §4.7. This subcommand downloads prebuilt index databases and model checkpoints from GitHub Releases. It does not require `--db` or any index state checks — it produces the index rather than consuming it.

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
| Project directory not found (extract) | 1 | `Project directory not found: {path}` |
| All proofs failed (extract) | 1 | `Extraction failed: all {n} proofs failed.` |
| Some proofs failed (extract) | 0 | Summary printed to stderr with failure count |
| No proofs found (extract) | 0 | `Warning: no proofs found in the specified projects.` |
| Invalid extraction input (extract-deps, quality-report) | 1 | `Invalid JSON Lines at line {n}: {details}` |
| Checkpoint corrupted (extract --resume) | 0 | `Warning: checkpoint corrupted, falling back to full extraction.` |
| Mutually exclusive flags (extract) | 2 | `--incremental and --resume cannot be used together.` |
| Model checkpoint not found (evaluate, compare, quantize, fine-tune) | 1 | `Model checkpoint not found: {path}` |
| Insufficient training data (train, fine-tune) | 1 | `Insufficient training data: {n} pairs found, minimum 1,000 required.` |
| GPU out of memory (train, fine-tune) | 1 | `GPU out of memory. Try reducing --batch-size (current: {n}).` |
| Quantization validation failure (quantize) | 1 | `Quantization quality check failed: max cosine distance {d:.4f} >= 0.02 threshold.` |
| Training data file not found (train, fine-tune, validate-training-data, build-vocabulary) | 1 | `Training data file not found: {path}` |
| No declarations in index (build-vocabulary) | 1 | `No declarations found in index database.` |
| Vocabulary file not found (train) | 1 | `Vocabulary file not found: {path}` |
| Output file exists, no --force (download-index) | 1 | `{path} already exists. Use --force to overwrite.` |
| No matching release (download-index) | 1 | `No index release found on GitHub.` |
| Checksum mismatch (download-index) | 1 | `Checksum verification failed for {label}. Expected {expected}, got {actual}. File deleted.` |
| Network failure (download-index) | 1 | `Failed to reach GitHub API: {details}` |

Errors are always printed to stderr. Successful output is always printed to stdout. This separation supports piping and redirection.

## 6. Non-Functional Requirements

- Startup time includes loading `PipelineContext` into memory (same overhead as MCP server startup).
- The CLI does not persist a long-running process; each invocation creates and destroys its own `PipelineContext`.
- The CLI shall not import MCP-specific dependencies.

## 7. Examples

### search-by-name (human-readable)

```
$ poule search-by-name --db index.db "Nat.add_comm" --limit 3
Coq.Arith.PeanoNat.Nat.add_comm  lemma  0.9500
  forall n m : nat, n + m = m + n
  module: Coq.Arith.PeanoNat

Coq.Arith.PeanoNat.Nat.add_comm_l  lemma  0.8200
  forall n m : nat, n + m = m + n
  module: Coq.Arith.PeanoNat
```

### search-by-name (JSON)

```
$ poule search-by-name --db index.db "Nat.add_comm" --limit 3 --json
[{"name":"Coq.Arith.PeanoNat.Nat.add_comm","statement":"forall n m : nat, n + m = m + n","type":"forall n m : nat, n + m = m + n","module":"Coq.Arith.PeanoNat","kind":"lemma","score":0.95}]
```

### get-lemma (error)

```
$ poule get-lemma --db index.db "nonexistent.declaration"
Declaration nonexistent.declaration not found in the index.
$ echo $?
1
```

### Missing index

```
$ poule search-by-name --db missing.db "test"
Index database not found at missing.db. Run the indexing command to create it.
$ echo $?
1
```

### replay-proof (human-readable)

```
$ poule replay-proof test.v add_comm
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
$ poule replay-proof test.v add_comm --json
{"schema_version":1,"session_id":"...","proof_name":"add_comm","file_path":"test.v","total_steps":2,"steps":[...]}
```

### replay-proof (JSON with premises)

```
$ poule replay-proof test.v add_comm --json --premises
{"trace":{"schema_version":1,...},"premises":[{"step_index":1,"tactic":"intros n m.","premises":[]},...]}
```

### replay-proof (error)

```
$ poule replay-proof nonexistent.v add_comm
File not found: nonexistent.v
$ echo $?
1
```

### extract (success)

```
$ poule extract /path/to/stdlib --output stdlib.jsonl
Extracting theorem 1/4550...
Extracting theorem 2/4550...
...
Extraction complete.
  Theorems found:    4550
  Extracted:         4500
  Failed:              50
  Skipped:              0
  Output: /path/to/stdlib.jsonl
$ echo $?
0
```

### extract (project not found)

```
$ poule extract /nonexistent --output out.jsonl
Project directory not found: /nonexistent
$ echo $?
1
```

### extract-deps

```
$ poule extract-deps stdlib.jsonl --output deps.jsonl
Processed 4500 extraction records.
Wrote 4500 dependency entries to deps.jsonl.
$ echo $?
0
```

### quality-report (JSON)

```
$ poule quality-report stdlib.jsonl --json
{"premise_coverage":0.87,"proof_length_distribution":{"min":1,"max":342,"mean":12.4,"median":8.0,"p25":4.0,"p75":16.0,"p95":45.0},"tactic_vocabulary":[{"tactic":"apply","count":24500}],"per_project":[{"project_id":"coq-stdlib","premise_coverage":0.89,"proof_length_distribution":{"min":1,"max":200,"mean":10.2,"median":7.0,"p25":3.0,"p75":14.0,"p95":38.0},"theorem_count":4500}]}
```

### build-vocabulary

```
$ poule build-vocabulary --db index.db --data stdlib.jsonl --output coq-vocabulary.json
Vocabulary built.
  Total tokens:       15,425
  Special tokens:          5
  Fixed tokens:          120
  Index declarations: 15,000
  Training data:         300
  Output: coq-vocabulary.json
$ echo $?
0
```

### train (success)

```
$ poule train stdlib.jsonl mathcomp.jsonl --db index.db --output model.pt
Validating training data...
  35,000 training pairs, 4,200 unique premises — OK
Training bi-encoder (batch_size=256, lr=2e-5, epochs=20)...
  Epoch 1/20: loss=4.21, val_R@32=0.18
  Epoch 2/20: loss=3.14, val_R@32=0.32
  ...
  Epoch 12/20: loss=1.42, val_R@32=0.54 (best)
  Epoch 15/20: early stopping (no improvement for 3 epochs)
Model saved to model.pt (best val_R@32=0.54)
$ echo $?
0
```

### evaluate (JSON)

```
$ poule evaluate --checkpoint model.pt --test-data test.jsonl --db index.db --json
{"recall_at_1":0.22,"recall_at_10":0.41,"recall_at_32":0.52,"mrr":0.35,"test_count":4500,"mean_premises_per_state":2.3,"mean_query_latency_ms":12.4}
```

### compare

```
$ poule compare --checkpoint model.pt --test-data test.jsonl --db index.db
Neural vs. Symbolic Comparison
==============================
Neural R@32:    0.52
Symbolic R@32:  0.38
Union R@32:     0.55
Improvement:    44.7%
Overlap:        37.5%
Neural only:    25.0%
Symbolic only:  37.5%
```

### validate-training-data

```
$ poule validate-training-data stdlib.jsonl
Training Data Validation
========================
Total pairs:     35,000
Empty premises:  15,000 (30.0%)
Malformed:       0
Unique premises: 4,200
Unique states:   32,100

Top premises:
  Coq.Init.Logic.eq_refl          1,200
  Coq.Arith.PeanoNat.Nat.add_0_r    850
  ...
```

## 8. Language-Specific Notes (Python)

- Use `click` for argument parsing (consistent with the existing extraction CLI).
- Use `click.Group` to organize search subcommands under a single entry point.
- Reuse `PipelineContext` and `create_context` from `poule.pipeline.context`.
- Reuse pipeline search functions from `poule.pipeline.search`.
- Reuse `SearchResult`, `LemmaDetail`, `Module` from `poule.models.responses`.
- JSON serialization via `dataclasses.asdict()` + `json.dumps()` (same as MCP server).
- For proof replay: use `SessionManager` from `poule.session.manager`, `serialize_proof_trace` and `serialize_premise_annotation` from `poule.serialization.serialize`.
- For extraction: use `ExtractionCampaignOrchestrator` from `poule.extraction.campaign`, `extract_dependency_graph` from `poule.extraction.dependency_graph`, `generate_quality_report` from `poule.extraction.reporting`.
- Use `asyncio.run()` to bridge Click's sync execution model to the async `SessionManager` API.
- For neural subcommands: use `VocabularyBuilder`, `TrainingDataValidator`, `TrainingDataLoader`, `TacticClassifierTrainer`, `TacticEvaluator`, `ModelQuantizer` from `poule.neural.training`.
- Neural subcommands do not require `PipelineContext` (except `compare`, which needs the symbolic retrieval pipeline for comparison).
- Package location: `src/poule/cli/`.
