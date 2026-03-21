# CLI

The command-line interface for indexing, search, proof replay, and batch extraction operations.

**Features**: [CLI Search](../features/cli-search.md), [CLI Proof Replay](../features/cli-proof-replay.md), [Batch Extraction CLI](../features/batch-extraction-cli.md), [Extraction Quality Reports](../features/extraction-quality-reports.md), [Model Training CLI](../features/model-training-cli.md), [Pre-trained Model](../features/pre-trained-model.md)

---

## Entry Point

A single CLI entry point exposes five command groups:

- **`index`** — library extraction and index construction (existing)
- **Search subcommands** — `search-by-name`, `search-by-type`, `search-by-structure`, `search-by-symbols`, `get-lemma`, `find-related`, `list-modules`
- **Proof subcommands** — `replay-proof`
- **Distribution subcommands** — `download-index` (see [prebuilt-distribution.md](prebuilt-distribution.md))
- **Extraction subcommands** (Phase 3) — `extract`, `extract-deps`, `quality-report`
- **Neural subcommands** (Neural Premise Selection) — `train`, `fine-tune`, `evaluate`, `compare`, `quantize`, `validate-training-data`

All search subcommands share common options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | path | required | Path to the SQLite index database |
| `--json` | flag | false | Output results as JSON instead of human-readable format |
| `--limit` | integer | 50 | Maximum number of results (clamped to [1, 200]) |

## Search Subcommand Signatures

### search-by-name

```
poule search-by-name --db <path> <pattern> [--limit N] [--json]
```

Positional argument: `pattern` — the name search query.

### search-by-type

```
poule search-by-type --db <path> <type_expr> [--limit N] [--json]
```

Positional argument: `type_expr` — a Coq type expression.

### search-by-structure

```
poule search-by-structure --db <path> <expression> [--limit N] [--json]
```

Positional argument: `expression` — a Coq expression.

### search-by-symbols

```
poule search-by-symbols --db <path> <symbol> [<symbol> ...] [--limit N] [--json]
```

Positional arguments: one or more symbol names.

### get-lemma

```
poule get-lemma --db <path> <name> [--json]
```

Positional argument: `name` — fully qualified declaration name. `--limit` does not apply.

### find-related

```
poule find-related --db <path> <name> --relation <rel> [--limit N] [--json]
```

Positional argument: `name` — fully qualified declaration name.
Required option: `--relation` — one of `uses`, `used_by`, `same_module`, `same_typeclass`.

### list-modules

```
poule list-modules --db <path> [<prefix>] [--json]
```

Optional positional argument: `prefix` — module prefix to filter by (default: empty, lists all top-level modules).

## Proof Subcommand Signatures

### replay-proof

```
poule replay-proof <file_path> <proof_name> [--json] [--premises]
```

Positional arguments: `file_path` — path to a .v file; `proof_name` — name of the proof to replay.

Options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--json` | flag | false | Output as JSON instead of human-readable format |
| `--premises` | flag | false | Include per-step premise annotations |

No `--db` option — proof replay is independent of the search index.

## Pipeline Integration (Search)

```
CLI subcommand
  │
  │ create_context(db_path)
  ▼
PipelineContext
  │
  │ pipeline.search_by_*(ctx, ..., limit)
  ▼
Ranked results
  │
  │ format_*(results, json_mode)
  ▼
stdout
```

Each CLI subcommand:
1. Opens the index database and creates a `PipelineContext` (same as MCP server startup)
2. Calls the corresponding `pipeline.search_by_*` function with validated parameters
3. Formats results and writes to stdout

The CLI reuses `PipelineContext` and all pipeline functions identically to the MCP server. No search logic lives in the CLI layer.

## Pipeline Integration (Proof Replay)

```
CLI replay-proof subcommand
  │
  │ asyncio.run(_replay_proof_async(...))
  ▼
SessionManager
  │
  │ create_session → extract_trace → get_premises (optional) → close_session
  ▼
ProofTrace (+ PremiseAnnotation list)
  │
  │ format_proof_trace(trace, premises, json_mode)
  ▼
stdout
```

The proof replay command uses `asyncio.run()` to bridge Click's synchronous world to the async `SessionManager` API. The session is always closed in a `finally` block, even on error.

## Index State Checks

On startup, the CLI performs the same index checks as the MCP server:
1. Database file existence → error message to stderr, exit code 1
2. Schema version match → error message to stderr, exit code 1

## Output Formats

### Human-Readable (default)

For `SearchResult` lists:
```
<name>  <kind>  <score>
  <statement>
  module: <module>
```

One block per result, separated by blank lines.

For `LemmaDetail`:
```
<name>  (<kind>)
  <statement>
  module:       <module>
  dependencies: <count>
  dependents:   <count>
  symbols:      <comma-separated list>
  node_count:   <n>
```

For `Module` lists:
```
<module_name>  (<declaration_count> declarations)
```

### JSON (`--json`)

For search commands: a JSON array of `SearchResult` or `Module` objects, one per line (compact format).

For `get-lemma`: a single JSON `LemmaDetail` object.

JSON field names and value types match the MCP response types defined in [data-models/response-types.md](data-models/response-types.md).

### Proof Replay Output

#### Human-Readable (default)

```
Proof: <proof_name>
File:  <file_path>
Steps: <total_steps>

--- Step 0 (initial) ---
Goal 1: <goal_type>
  <hypothesis_name> : <hypothesis_type>

--- Step 1: <tactic> ---
Goal 1: <goal_type>
  <hypothesis_name> : <hypothesis_type>
  Premises: <premise_name> (<kind>), ...
```

Header with proof metadata, then one block per step showing the tactic applied, goals with hypotheses, and optionally premise annotations.

#### JSON (`--json`)

Without `--premises`: the output of `serialize_proof_trace(trace)`.

With `--premises`: `{"trace": <serialize_proof_trace output>, "premises": [<serialize_premise_annotation output>, ...]}`.

## Extraction Subcommand Signatures (Phase 3)

### extract

```
poule extract <project_dir> [<project_dir> ...] --output <path> [--name-pattern <pattern>] [--modules <mod,...>] [--incremental] [--resume] [--include-diffs]
```

Positional arguments: one or more Coq project directories.

Options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | path | required | Path for JSON Lines output file |
| `--name-pattern` | glob/regex | none | Only extract proofs matching this name pattern (P1) |
| `--modules` | comma-separated | none | Only extract proofs in these modules (P1) |
| `--incremental` | flag | false | Re-extract only changed files, merge with prior output (P1) |
| `--resume` | flag | false | Resume an interrupted extraction from checkpoint (P1) |
| `--include-diffs` | flag | false | Include proof state diffs in output (P1) |

No `--db` option — extraction is independent of the search index.

### extract-deps

```
poule extract-deps <extraction_output> --output <path>
```

Positional argument: path to a JSON Lines extraction output file.

Reads ExtractionRecords and produces a dependency graph (JSON Lines, one DependencyEntry per line). Can also run inline during `extract` via `--deps` flag (P1).

### quality-report

```
poule quality-report <extraction_output> [--output <path>] [--json]
```

Positional argument: path to a JSON Lines extraction output file.

Generates a QualityReport from the extraction output. Defaults to human-readable output on stdout; `--json` produces JSON; `--output` writes to a file.

## Pipeline Integration (Extraction)

```
CLI extract subcommand
  │
  │ validate project dirs, parse options
  ▼
ExtractionCampaignOrchestrator
  │
  │ enumerate projects → files → theorems
  │ For each theorem:
  │   SessionManager.create_session → replay → extract_trace
  │   → get_premises → close_session
  │   On failure: emit ExtractionError
  │
  │ Write CampaignMetadata, ExtractionRecords/Errors, ExtractionSummary
  ▼
JSON Lines output file
```

The extraction CLI creates the Extraction Campaign Orchestrator, which reuses the same `SessionManager` used by proof replay and the MCP server. No extraction logic lives in the CLI layer — the CLI is responsible for argument parsing, output path management, and exit code handling.

### Extraction Output

The `extract` command writes JSON Lines to `--output`. Progress is reported to stderr during extraction. On completion, a human-readable summary is printed to stderr. The JSON Lines output file contains only machine-readable records.

## Neural Subcommand Signatures (Neural Premise Selection)

See [neural-training.md](neural-training.md) for the full training pipeline design.

### train

```
poule train <traces.jsonl> [<traces.jsonl> ...] --db <index.db> --output <checkpoint.pt> [--epochs N] [--batch-size N] [--lr F]
```

Positional arguments: one or more JSON Lines extraction output files.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | path | required | Path to the SQLite index database (provides premise corpus) |
| `--output` | path | required | Path for the trained model checkpoint |
| `--epochs` | integer | 20 | Maximum training epochs |
| `--batch-size` | integer | 256 | Proof states per batch |
| `--lr` | float | 2e-5 | Learning rate |

### fine-tune

```
poule fine-tune --checkpoint <pre-trained.pt> --data <traces.jsonl> --db <index.db> --output <fine-tuned.pt> [--epochs N] [--lr F]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--checkpoint` | path | required | Pre-trained model checkpoint to initialize from |
| `--data` | path | required | JSON Lines extraction output for the target project |
| `--db` | path | required | Path to the SQLite index database |
| `--output` | path | required | Path for the fine-tuned model checkpoint |
| `--epochs` | integer | 10 | Maximum fine-tuning epochs |
| `--lr` | float | 5e-6 | Learning rate (lower than training to avoid catastrophic forgetting) |

### evaluate

```
poule evaluate --checkpoint <model.pt> --test-data <test.jsonl> --db <index.db> [--json]
```

Reports Recall@1, Recall@10, Recall@32, MRR, and evaluation latency.

### compare

```
poule compare --checkpoint <model.pt> --test-data <test.jsonl> --db <index.db> [--json]
```

Reports neural-only, symbolic-only, and union Recall@32 with overlap and exclusivity statistics.

### quantize

```
poule quantize --checkpoint <model.pt> --output <model.onnx>
```

Converts a PyTorch checkpoint to INT8 ONNX with validation.

### validate-training-data

```
poule validate-training-data <traces.jsonl> [<traces.jsonl> ...]
```

Validates extracted data for training readiness. Reports pair counts, premise distributions, and data quality warnings.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Database file missing | Print error to stderr, exit 1 |
| Schema version mismatch | Print error to stderr, exit 1 |
| Declaration not found (`get-lemma`, `find-related`) | Print error to stderr, exit 1 |
| Parse failure (type/structure queries) | Print parse error to stderr, exit 1 |
| Empty results | Print nothing (human-readable) or `[]` (JSON), exit 0 |
| File not found (proof replay) | Print error to stderr, exit 1 |
| Proof not found (proof replay) | Print error to stderr, exit 1 |
| Backend crashed (proof replay) | Print error to stderr, exit 1 |
| Project directory not found (extract) | Print error to stderr, exit 1 |
| All proofs fail in extract | Print summary to stderr, exit 1 |
| Some proofs fail in extract | Print summary to stderr (with failure count), exit 0 (partial success) |
| No proofs found in extract | Print warning to stderr, exit 0 |
| Checkpoint file corrupted (resume) | Print warning to stderr, fall back to full extraction |
| Missing required args (extract) | Print usage to stderr, exit 2 |
| Model checkpoint not found (evaluate, compare, quantize) | Print error to stderr, exit 1 |
| Training data validation failure (train, fine-tune) | Print validation report to stderr, exit 1 |
| GPU out of memory (train, fine-tune) | Print suggestion to reduce batch size to stderr, exit 1 |
| Quantization validation failure (quantize) | Print max cosine distance to stderr, exit 1 |
