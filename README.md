# Poule (Hen)

*Utilities for Coq (Rooster)*

Semantic lemma search, interactive proof exploration, and proof visualization for Coq/Rocq libraries — delivered as an MCP server for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Poule indexes compiled Coq `.vo` libraries into a SQLite database and provides multi-channel retrieval (structural, symbol, lexical, neural, type-based) with reciprocal rank fusion. It also supports interactive proof sessions and Mermaid-based visualization of proof states, proof trees, and dependency graphs.

## Features

### Search

- **Structural** — Weisfeiler-Lehman graph kernels, tree edit distance, and collapse matching
- **Symbol** — MePo-style iterative relevance filtering with weighted symbol overlap
- **Lexical** — FTS5 full-text search over names, statements, and modules
- **Neural** — bi-encoder embeddings (INT8, CPU-only) fused with symbolic channels via RRF
- **Type** — multi-channel fusion combining all of the above
- **Dependency navigation** — `uses`, `used_by`, `same_module`, `same_typeclass`

### Neural Premise Selection

- Train a bi-encoder on proof traces with masked contrastive loss and hard negative mining
- Evaluate with Recall@k and MRR; compare neural vs. symbolic retrieval
- Fine-tune on project-specific proofs; export to INT8 ONNX for <10ms CPU inference
- Graceful degradation — search works identically without a model checkpoint

### Proof Interaction

- Open interactive proof sessions against `.v` files
- Observe proof states, submit tactics, step forward/backward
- Extract full proof traces with per-step premise annotations
- Batch tactic submission and concurrent sessions

### Visualization

- Proof state, proof tree, dependency subgraph, and step-by-step sequence diagrams
- Generated as Mermaid syntax, rendered via the [Mermaid Chart MCP](https://github.com/Mermaid-Chart/mermaid-mcp-server)

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- Coq/Rocq 8.19+ with coq-lsp or SerAPI

## Installation

### Coq Toolchain

Install [opam](https://opam.ocaml.org/), then:

```bash
opam init
opam install coq coq-lsp
opam repo add coq-released https://coq.inria.fr/opam/released
opam install coq-mathcomp-ssreflect   # optional, for MathComp indexing
eval $(opam env)
```

See the [opam install guide](https://opam.ocaml.org/doc/Install.html) for platform-specific opam installation (macOS via Homebrew, Linux distros, WSL2).

### Python Package

```bash
git clone https://github.com/ekirton/poule.git
cd poule
uv sync
```

## Quick Start

### 1. Index a Coq Library

```bash
uv run python -m poule.extraction --target stdlib+mathcomp --db index.db --progress
```

### 2. Configure Claude Code

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "coq-search": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/poule", "python", "-m", "poule.server", "--db", "/path/to/poule/index.db"]
    },
    "mermaid": {
      "command": "npx",
      "args": ["-y", "@mermaidchart/mcp-server"]
    }
  }
}
```

Replace `/path/to/poule` with the absolute path to your clone.

### 3. Use with Claude Code

Once configured, Claude Code has access to all Poule tools:

| Category | Tools | Examples |
|----------|-------|---------|
| **Search** (7) | `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules` | Find lemmas by name, type signature, or structural similarity |
| **Proof** (12) | `open_proof_session`, `observe_proof_state`, `submit_tactic`, `extract_proof_trace`, `get_proof_premises`, ... | Interactively explore and modify proofs |
| **Visualization** (4) | `visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence` | Render proof structures as Mermaid diagrams |

Search tools accept `limit` (default 50, max 200). Proof tools work independently of the search index.

### CLI

All search and proof replay features are also available as standalone commands for scripting or quick lookups:

```bash
uv run python -m poule.cli search-by-name --db index.db "Nat.add_comm"
uv run python -m poule.cli search-by-type --db index.db "nat -> nat -> nat"
uv run python -m poule.cli replay-proof examples/arith.v add_comm --json --premises
```

Run `uv run python -m poule.cli --help` for the full command list.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, project structure, testing, and documentation layers.

## License

See [LICENSE](LICENSE) and [NOTICE](NOTICE).
