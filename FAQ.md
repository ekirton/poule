# FAQ

### Why Claude Code?

Coq proof development involves a lot of context-switching: searching for lemmas across large libraries, reading documentation, navigating unfamiliar modules, understanding proof states, and figuring out which tactic to apply next. Claude Code lets you do all of this in natural language from your terminal — you describe what you need, and it searches the index, opens proof sessions, explains tactics, and generates visualizations on your behalf. Instead of memorizing `Search` patterns or manually browsing module hierarchies, you just ask.

The key enabler is MCP (Model Context Protocol): Poule exposes its search engine, proof interaction, and visualization as MCP tools that Claude calls automatically. You get the benefits of a sophisticated retrieval system without learning a new query language or leaving your workflow.

Poule also provides skills — compound workflows like `/formalize`, `/proof-repair`, `/compress-proof`, and `/explain-proof` that orchestrate multiple tools into multi-step agentic tasks. These automate work that would otherwise require dozens of manual steps: repairing broken proofs after a Coq upgrade, searching for shorter proof alternatives, or going from a natural-language theorem statement to a verified proof.

### Who is Poule for?

Anyone working with Coq/Rocq. Students benefit from natural-language search, proof explanations (`/explain-proof`), and error diagnosis (`/explain-error`) — you can ask Claude what a tactic does or why a proof fails instead of deciphering error messages alone. Experienced users benefit from cross-library lemma discovery, proof compression, automated repair after version upgrades, and the ability to explore unfamiliar libraries (MathComp, std++, etc.) conversationally rather than by reading source files.

### Why does Poule run in a container?

The container serves two purposes:

1. **Safe autonomous operation.** Claude Code runs with `--dangerously-skip-permissions`, which lets it operate without confirmation prompts. The container isolates this — Claude has full access inside the container but cannot touch anything on your host outside the mounted project directory.

2. **Batteries included.** The container ships with Coq, all supported libraries, the search index, coq-lsp, and the MCP server pre-installed. No local opam, Coq, or Python setup required.

### How do I contribute?

See [DEVELOPMENT.md](DEVELOPMENT.md) for project structure, build instructions, and testing. Open an issue on [GitHub](https://github.com/ekirton/Poule/issues) to report bugs or request features.

### Can you add library X?

We currently support libraries that follow the standard Coq library format: **stdlib**, **MathComp**, **std++**, **Flocq**, **Coquelicot**, and **CoqInterval**. Libraries with non-standard packaging or build systems are not supported at this time.

### Can I use an older version of a particular library?

No. Poule ships a single set of library versions that are tested together. The search index, installed `.vo` files, and proof interaction all depend on the same versions matching. You cannot mix and match individual library versions.

### How is this different from Coq's built-in `Search` command?

Coq's `Search` is purely syntactic — you need to already know the approximate shape of what you're looking for. Poule provides multi-channel retrieval: structural similarity (tree kernels, edit distance), symbol-based relevance filtering, full-text search, and type-based fusion. You can describe what you need in natural language and Claude will find relevant lemmas across all six indexed libraries, not just what's currently in scope.

### Does Poule work with Lean?

No. Poule is built specifically for the Coq/Rocq ecosystem. Lean has its own search tools (Loogle, Moogle, LeanSearch, exact?) that serve a similar purpose.

### Do I need a GPU?

No. Everything runs on CPU. The symbolic search channels (structural, symbol, lexical) require no ML inference at all. The neural channel (when implemented) will use an INT8 ONNX model designed for CPU-only inference.

### Can Claude write proofs for me?

Claude can help you build proofs interactively — it can search for relevant lemmas, suggest tactics, step through proof states, and explain what's happening at each step. It works best as a collaborator: you guide the proof strategy, and Claude helps you find the right lemmas and tactics. Use `/formalize` to go from a natural-language statement to a complete proof interactively.
