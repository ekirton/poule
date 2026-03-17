# Poule à Coq

*Poule ("Hen") is utilities for Coq ("Rooster")*

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

## Installation

See [INSTALLATION.md](INSTALLATION.md) for requirements, setup (pip, Docker), index download, and Claude Code configuration.

## Use with Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) is Anthropic's agentic coding tool — you interact with it in natural language from your terminal. Poule extends Claude's capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/): when you ask Claude a question about Coq, it automatically calls the right Poule tools behind the scenes and presents the results in plain language. You never need to invoke Poule tools directly.

For example, you can ask Claude things like:

**Search:**
- *"Find lemmas about list reversal being involutive"*
- *"Search for lemmas with type `forall n : nat, n + 0 = n`"*
- *"What's in the Coq.Arith module?"*

**Proof interaction:**
- *"Open a proof session on `rev_involutive` in `examples/lists.v` and show me the current goal"*
- *"Step through the proof of `add_comm` in `examples/arith.v` and explain each tactic"*
- *"Try applying `intros` then `induction n` in my current proof session"*

**Dependencies:**
- *"What lemmas does `Nat.add_comm` depend on?"*
- *"Which lemmas use `Nat.add_0_r`?"*
- *"Show me other lemmas in the same module as `List.rev_append`"*

**Visualization:**
- *"Visualize the proof tree for `app_nil_r` in `examples/lists.v`"*
- *"Show me the dependency graph around `Nat.add_comm`"*
- *"Render the step-by-step proof evolution of `modus_ponens` in `examples/logic.v`"*

Claude will search the index, manage proof sessions, and generate diagrams on your behalf.

**Capabilities provided to Claude:**

| Category | What Claude can do |
|----------|--------------------|
| **Search** | Find lemmas by name, type signature, structural similarity, or symbol usage; navigate dependencies; browse modules |
| **Proof interaction** | Open interactive proof sessions, observe goal states, submit tactics, step through proofs, extract traces with premise annotations |
| **Visualization** | Render proof states, proof trees, dependency graphs, and step-by-step proof evolution as Mermaid diagrams |

For the full list of MCP tools and their parameters, see [MCP Tools Reference](doc/MCP_TOOLS.md).

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
