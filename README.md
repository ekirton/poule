# Wily Rooster

Semantic lemma search for Coq/Rocq libraries, exposed as an MCP server for Claude Code.

Wily Rooster indexes compiled Coq `.vo` libraries into a SQLite database and provides structural, symbol-based, lexical, and type-based search through a multi-channel retrieval pipeline with reciprocal rank fusion.

## Features

- **Structural search** — find declarations with similar expression tree structure using Weisfeiler-Lehman graph kernels, tree edit distance, and collapse matching
- **Symbol search** — MePo-style iterative relevance filtering based on weighted symbol overlap
- **Lexical search** — FTS5 full-text search over declaration names, statements, and modules
- **Type search** — multi-channel fusion combining structural, symbol, and lexical results
- **Dependency navigation** — explore `uses`, `used_by`, `same_module`, and `same_typeclass` relationships
- **Module browsing** — list and filter indexed Coq modules

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- Coq/Rocq 8.19+ (for indexing)
- coq-lsp or SerAPI (for `.vo` file extraction)

## Installation

### Coq Toolchain

Install [opam](https://opam.ocaml.org/) (OCaml's package manager), then use it to install Coq:

```bash
# macOS
brew install opam hg darcs

# Linux (Debian/Ubuntu)
sudo apt-get update && sudo apt-get install -y bubblewrap mercurial darcs
bash -c "sh <(curl -fsSL https://opam.ocaml.org/install.sh)"

# Linux (Fedora/RHEL)
sudo dnf install -y bubblewrap mercurial darcs
bash -c "sh <(curl -fsSL https://opam.ocaml.org/install.sh)"

# Linux (Arch)
sudo pacman -S opam bubblewrap mercurial darcs

# Windows — use WSL2 with a Ubuntu distribution, then follow the Debian/Ubuntu
# instructions above. Native Windows is not supported by opam.
# See https://learn.microsoft.com/en-us/windows/wsl/install
```

Then initialise opam and install Coq (all platforms, including WSL2):

```bash
opam init

# Install Coq and the extraction backend
opam install coq coq-lsp

# Add the Coq package repository (required for MathComp)
opam repo add coq-released https://coq.inria.fr/opam/released

# For MathComp indexing
opam install coq-mathcomp-ssreflect

# Make coqc available in your shell (add to .zshrc / .bashrc for persistence)
eval $(opam env)
```

Verify the installation:

```bash
coqc --version
```

### Python Package

```bash
# Clone the repository
git clone https://github.com/ekirton/wily-rooster.git
cd wily-rooster

# Install with uv
uv sync

# Install dev dependencies (for testing)
uv sync --group dev
```

## Quick Start

### 1. Index a Coq Library

Build the search index from your installed Coq standard library and MathComp:

```bash
uv run python -m wily_rooster.extraction --target stdlib+mathcomp --db index.db --progress
```

This runs the offline extraction pipeline:
1. Discovers `.vo` files from installed Coq libraries
2. Extracts declarations via coq-lsp or SerAPI
3. Normalizes expression trees (currification, cast stripping, CSE)
4. Computes WL histogram vectors and symbol sets
5. Resolves dependency edges
6. Writes everything to a single SQLite database

Pass `--progress` to see extraction status on stderr:
```
Discovering libraries...
Discovered 312 .vo files
Collecting declarations [1/312]
Extracting declarations [1234/5678]
Resolving dependencies [1234/5678]
Computing symbol frequencies...
Finalizing index...
```

### 2. Search from the Command Line

All search tools are available as standalone CLI commands via `python -m wily_rooster.cli`:

```bash
# Search by name (glob or substring)
uv run python -m wily_rooster.cli search-by-name --db index.db "Nat.add_comm"

# Search by type signature (multi-channel fusion)
uv run python -m wily_rooster.cli search-by-type --db index.db "nat -> nat -> nat"

# Search by structural similarity
uv run python -m wily_rooster.cli search-by-structure --db index.db "forall n, n + 0 = n"

# Search by symbol names (space-separated)
uv run python -m wily_rooster.cli search-by-symbols --db index.db Coq.Init.Nat.add Coq.Init.Datatypes.nat

# Get full details for a specific declaration
uv run python -m wily_rooster.cli get-lemma --db index.db "Coq.Arith.PeanoNat.Nat.add_comm"

# Navigate the dependency graph
uv run python -m wily_rooster.cli find-related --db index.db --relation uses "Coq.Arith.PeanoNat.Nat.add_comm"

# Browse the module hierarchy
uv run python -m wily_rooster.cli list-modules --db index.db "Coq.Arith"
```

All search commands accept `--limit N` (default 50, max 200) and `--json` for machine-readable output.

### 3. Start the MCP Server

```bash
uv run python -m wily_rooster.server --db index.db
```

The server communicates via stdio, compatible with Claude Code's MCP configuration.

### 4. Configure Claude Code

Add to your Claude Code MCP config (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "coq-search": {
      "command": "uv",
      "args": ["run", "python", "-m", "wily_rooster.server", "--db", "/path/to/index.db"]
    }
  }
}
```

## MCP Tools

Once configured, Claude Code has access to 7 search tools:

| Tool | Description | Example |
|------|-------------|---------|
| `search_by_name` | Find declarations by name pattern | `"Nat.add_comm"` |
| `search_by_type` | Find declarations matching a type signature | `"nat -> nat -> nat"` |
| `search_by_structure` | Find structurally similar declarations | `"forall n, n + 0 = n"` |
| `search_by_symbols` | Find declarations using specific symbols | `["Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"]` |
| `get_lemma` | Get full details for a named declaration | `"Coq.Arith.PeanoNat.Nat.add_comm"` |
| `find_related` | Navigate the dependency graph | `relation: "uses" \| "used_by" \| "same_module" \| "same_typeclass"` |
| `list_modules` | Browse indexed module hierarchy | `prefix: "Coq.Arith"` |

All search tools accept an optional `limit` parameter (default 50, max 200).

## Architecture

```
Claude Code / LLM
  │ MCP tool calls (stdio)
  ▼
MCP Server (thin adapter)
  │ Internal function calls
  ▼
Retrieval Pipeline
  │ SQLite queries
  ▼
Storage (SQLite database)
  ▲
  │ Writes during indexing
Coq Library Extraction
  │ coq-lsp / SerAPI
  ▼
Compiled .vo files
```

### Retrieval Channels

| Channel | Method | Use Case |
|---------|--------|----------|
| WL Kernel | Weisfeiler-Lehman histogram cosine similarity | Fast structural screening (100K → 500 candidates) |
| MePo | Iterative symbol-relevance with inverse-frequency weighting | Symbol-based discovery |
| FTS5 | SQLite full-text search with BM25 | Name and text matching |
| TED | Zhang-Shasha tree edit distance | Fine structural ranking (≤ 50 nodes) |
| Const Jaccard | Jaccard similarity of constant name sets | Lightweight complement |

Channels are combined via:
- **Fine-ranking weighted sum** for `search_by_structure`
- **Reciprocal Rank Fusion** (k=60) for `search_by_type`

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run tests for a specific module
uv run pytest test/test_data_structures.py -v

# Run with coverage
uv run pytest --cov=wily_rooster
```

### Project Structure

```
src/wily_rooster/
├── models/          # Core data types (labels, trees, enums, responses)
├── normalization/   # Coq term normalization + CSE
├── storage/         # SQLite read/write layer
├── channels/        # Retrieval channels (WL, MePo, FTS, TED, Jaccard)
├── fusion/          # Score fusion (weighted sum, RRF, collapse match)
├── pipeline/        # Query orchestration
├── extraction/      # Offline .vo file extraction
└── server/          # MCP server (handlers, validation, errors)
```

### Documentation Layers

| Layer | Location | Purpose |
|-------|----------|---------|
| Requirements | `doc/requirements/` | Business goals, user needs |
| Features | `doc/features/` | What and why |
| Architecture | `doc/architecture/` | How (language-agnostic design) |
| Specifications | `specification/` | Implementable contracts |
| Tasks | `tasks/` | Detailed implementation plans |

## License

See [LICENSE](LICENSE) and [NOTICE](NOTICE).
