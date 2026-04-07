# FAQ

### Why Claude Code?

Coq proof development involves a lot of context-switching: searching for lemmas across large libraries, reading documentation, navigating unfamiliar modules, understanding proof states, and figuring out which tactic to apply next. Claude Code lets you do all of this in natural language from your terminal — you describe what you need, and it searches the index, opens proof sessions, explains tactics, and generates visualizations on your behalf. Instead of memorizing `Search` patterns or manually browsing module hierarchies, you just ask.

Poule also provides skills — compound workflows like `/formalize`, `/proof-repair`, `/compress-proof`, and `/explain-proof` that orchestrate multiple tools into multi-step tasks. These automate work that would otherwise require dozens of manual steps: repairing broken proofs after a Coq upgrade, searching for shorter proof alternatives, or going from a natural-language theorem statement to a verified proof.

### Who is Poule for?

Anyone working with Coq/Rocq. Students benefit from natural-language search, proof explanations (`/explain-proof`), and error diagnosis (`/explain-error`) — you can ask Claude what a tactic does or why a proof fails instead of deciphering error messages alone. Experienced users benefit from cross-library lemma discovery, proof compression, automated repair after version upgrades, and the ability to explore unfamiliar libraries (MathComp, std++, etc.) conversationally rather than by reading source files.

### Do I need to know Coq already?

No. Poule is designed for students who are learning Coq for the first time. The [Software Foundations](https://softwarefoundations.cis.upenn.edu) textbook is bundled and searchable via `/textbook`, Claude explains tactics and errors in plain language, and you can ask questions at any level. That said, Poule is a tool for *learning* Coq, not a replacement for it — the goal is to help you understand what's happening, not to hide the formalism.

### What is MCP?

MCP stands for [Model Context Protocol](https://modelcontextprotocol.io/). It's a standard way for AI assistants like Claude to use external tools. When you ask Claude a question about Coq, MCP is how Claude calls Poule's search engine, proof interaction system, and visualization tools behind the scenes. You never interact with MCP directly — it's the plumbing that makes everything work together.

### What is RAG?

RAG stands for Retrieval-Augmented Generation. It means that when Claude answers your question, it first searches a database of relevant information (in Poule's case, the Software Foundations textbook and the Coq library index) and includes what it finds in its answer. This is why Claude can cite specific textbook passages and find lemmas you didn't know existed — it's not just relying on its training data, it's actively looking things up.

### How much does it cost?

Poule itself is free and open source. However, Claude Code requires a paid Anthropic plan. There are two options:

- **Claude Pro ($20/month)** — the easiest way to get started. If you already have a Pro subscription, Claude Code will simply ask you to log in — no API keys or extra setup. If you don't have one yet, subscribe at [claude.com/pricing](https://claude.com/pricing).
- **API pay-per-use** — if you prefer to pay per question, create an [API key](https://console.anthropic.com/) and pay based on usage. This can be cheaper for light use or more expensive for heavy use.

For most students, the Pro plan is the better choice — predictable monthly cost and no surprises.

### Why does Poule run in a container?

The container serves two purposes:

1. **Safe autonomous operation.** Claude Code runs with `--dangerously-skip-permissions`, which lets it operate without confirmation prompts. The container isolates this — Claude has full access inside the container but cannot touch anything on your host outside the mounted project directory.

2. **Batteries included.** The container ships with Coq, all supported libraries, the search index, coq-lsp, and the MCP server pre-installed. No local opam, Coq, or Python setup required.

### Can I use my own `.v` files?

Yes. When you run `poule` from your project directory, your project is mounted inside the container. Claude can open proof sessions on your files, search for lemmas relevant to your goals, and help you build proofs interactively. Your files live on your host machine and are never copied or uploaded anywhere.

### What Coq version does it use?

The container ships with a specific Coq version and matching library versions. Run `coqc --version` inside the container to check. You cannot change the Coq version independently — the search index, installed libraries, and proof interaction all depend on matching versions.

### How is this different from Coq's built-in `Search` command?

Coq's `Search` is purely syntactic — you need to already know the approximate shape of what you're looking for. Poule searches across all six indexed libraries simultaneously using multiple strategies: name patterns, type signatures, structural similarity, and symbol usage. You can describe what you need in natural language ("a lemma about list reversal being its own inverse") and Claude will find relevant results, not just what's currently in scope.

### Can Claude write proofs for me?

Claude can help you build proofs interactively — it can search for relevant lemmas, suggest tactics, step through proof states, and explain what's happening at each step. It works best as a collaborator: you guide the proof strategy, and Claude helps you find the right lemmas and tactics. Use `/formalize` to go from a natural-language statement to a complete proof interactively.

For fully automated proving, CoqHammer (`hammer`, `sauto`, `qauto`) is available through the proof interaction tools and can often close goals without manual guidance. But even when automation succeeds, asking Claude to explain *why* the proof works is where the learning happens.

### What if Claude gives wrong advice?

Claude can make mistakes — it might suggest a tactic that doesn't apply, misidentify a lemma, or give an incorrect explanation. Always verify Claude's suggestions by actually running them in a proof session (which Poule does automatically). If a tactic fails, Claude will see the error and adjust. For explanations, cross-reference with the textbook (`/textbook`) or ask Claude to show its reasoning step by step. Developing a healthy skepticism of AI-generated advice is a valuable skill in itself.

### Does Poule work with Lean?

No. Poule is built specifically for the Coq/Rocq ecosystem. Lean has its own search tools (Loogle, Moogle, LeanSearch, exact?) that serve a similar purpose.

### Do I need a GPU?

No. Everything runs on CPU. The search engine uses efficient indexing algorithms, and the tactic suggestion model is optimized for CPU inference. No GPU, no CUDA, no special hardware.

### Can you add library X?

We currently support libraries that follow the standard Coq library format: **stdlib**, **MathComp**, **std++**, **Flocq**, **Coquelicot**, and **CoqInterval**. Libraries with non-standard packaging or build systems are not supported at this time.

### Can I use an older version of a particular library?

No. Poule ships a single set of library versions that are tested together. The search index, installed `.vo` files, and proof interaction all depend on the same versions matching. You cannot mix and match individual library versions.

### How do I contribute?

See [DEVELOPMENT.md](DEVELOPMENT.md) for project structure, build instructions, and testing. Open an issue on [GitHub](https://github.com/ekirton/Poule/issues) to report bugs or request features.
