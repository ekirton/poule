# Poule à Coq

*"Un coq a bien besoin d'une poule."
(A rooster really needs a hen.)*

Poule ("Hen") supports the Coq ("Rooster") procedural logic community.

Semantic lemma search, interactive proof exploration, and proof visualization for Coq/Rocq libraries — delivered as an MCP server for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Poule indexes compiled Coq `.vo` libraries into a SQLite database and provides multi-channel retrieval (structural, symbol, lexical, neural, type-based) with reciprocal rank fusion. It also supports interactive proof sessions and Mermaid-based visualization of proof states, proof trees, and dependency graphs.

Six Coq libraries are available as prebuilt indexes: **stdlib**, **MathComp**, **std++**, **Flocq**, **Coquelicot**, and **CoqInterval**. All 6 are downloaded and merged into a single searchable index — no configuration required.

> 👉 **TL;DR — [See examples of what you can ask Poule](examples/README.md)**

## Features

### Search

- **Structural** — Weisfeiler-Lehman graph kernels, tree edit distance, and collapse matching
- **Symbol** — MePo-style iterative relevance filtering with weighted symbol overlap
- **Lexical** — FTS5 full-text search over names, statements, and modules
- **Neural** *(NYI)* — bi-encoder embeddings (INT8, CPU-only) fused with symbolic channels via RRF
- **Type** — multi-channel fusion combining all of the above
- **Dependency navigation** — `uses`, `used_by`, `same_module`, `same_typeclass`

### Neural Premise Selection *(NYI)*

- Train a bi-encoder on proof traces with masked contrastive loss and hard negative mining
- Evaluate with Recall@k and MRR; compare neural vs. symbolic retrieval
- Fine-tune on project-specific proofs; export to INT8 ONNX for <10ms CPU inference
- Graceful degradation — search works identically without a model checkpoint

### Proof Interaction

- Open interactive proof sessions against `.v` files
- Observe proof states, submit tactics, step forward/backward
- Extract full proof traces with per-step premise annotations
- Batch tactic submission and concurrent sessions

### Proof Profiling

- Profile individual proofs or entire files — per-tactic timing ranked from slowest to fastest
- Separate `Qed` kernel re-checking time from tactic execution time
- Identify bottlenecks with natural-language explanations and concrete optimization suggestions
- Ltac call-tree profiling for complex custom tactics
- Compare timing between runs for regression detection
- Project-wide profiling with ranked summaries of slowest files and lemmas

### Proof Assistants

- **Auto/eauto trace explanation** — diagnose why `auto` or `eauto` failed to solve a goal: which hints were tried, why each was rejected, and what to do instead
- **Convoy pattern assistant** — detect dependent pattern matching failures, recommend repair techniques (`revert`-before-`destruct`, `dependent destruction`, convoy pattern, Equations `depelim`), generate boilerplate, and warn about axiom implications
- **Setoid rewriting assistant** — diagnose `setoid_rewrite` failures, identify missing `Proper` instances, generate `Instance Proper ...` declarations with correct `respectful` signatures, and suggest `setoid_rewrite` when `rewrite` fails under binders

### Visualization

- Proof state, proof tree, dependency subgraph, and step-by-step sequence diagrams
- Generated as Mermaid syntax; each visualization tool call writes a self-contained `proof-diagram.html` to your project directory
- Open `proof-diagram.html` in your browser and bookmark it — refresh after each visualization to see the latest diagram
- Poule always overwrites the same `proof-diagram.html` path — rename or copy the file if you want to keep a diagram

**Example:** proof tree for `app_nil_r` (`forall (A : Type) (l : list A), l ++ [] = l`)

```mermaid
flowchart TD
    s0g0["forall (A : Type) (l : list A), l ++ [] = l"]
    s0g0 -->|"intros A l."| s1g0["l ++ [] = l"]
    s1g0 -->|"induction l as [| h t IH]."| s2g0["[] ++ [] = []"]
    s1g0 -->|"induction l as [| h t IH]."| s2g1["(h :: t) ++ [] = h :: t"]
    s2g0 -->|"- simpl."| s3g0["[] = []"]
    s3g0 -->|"reflexivity."| s4g0["(h :: t) ++ [] = h :: t"]
    s4g0 -->|"- simpl."| s5g0["h :: t ++ [] = h :: t"]
    s5g0 -->|"rewrite IH."| s6g0["h :: t = h :: t"]
    s6g0 -->|"reflexivity."| s7g0["✓"]:::discharged
    classDef discharged fill:#d4edda,stroke:#28a745,stroke-dasharray:5 5
```

## Quick Start

Requires [Docker](https://docs.docker.com/get-docker/) and an [Anthropic API key](https://console.anthropic.com/).

**1. Get the launcher script**

```bash
curl -fsSL https://raw.githubusercontent.com/ekirton/Poule/main/bin/poule -o ~/bin/poule && chmod +x ~/bin/poule
```

Or, if you prefer to clone the repo:

```bash
git clone https://github.com/ekirton/Poule.git
cp poule/bin/poule ~/bin/poule
chmod +x ~/bin/poule
```

Make sure `~/bin` is on your `PATH` (add `export PATH="$HOME/bin:$PATH"` to your `~/.zshrc` if needed).

**2. Run**

```bash
poule          # run this from your project dir
```

To always start with the same project regardless of your current directory, set `POULE_PROJECT_DIR` (e.g. add `export POULE_PROJECT_DIR=~/Projects/my-coq-project` to your `~/.zshrc`).

Everything runs inside the container — no local Coq, Python, or opam installation required. All six supported libraries are pre-installed in the container for proof interaction. Claude Code and the search index are baked into the image for instant startup. On first run, the launcher pulls the image and initializes a persistent home directory at `~/poule-home`.

### Library indexes

All supported libraries (**stdlib**, **MathComp**, **std++**, **Flocq**, **Coquelicot**, **CoqInterval**) are indexed and baked into the container image at build time. The index is validated against the installed Coq and library versions during the Docker build — a version mismatch fails the build. A startup message confirms which libraries are currently indexed.

### Updating

The launcher automatically pulls the latest container image each time you run `poule`. The image includes Claude Code, the search index, and all Coq libraries — everything updates together.

## Use with Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) is Anthropic's agentic coding tool — you interact with it in natural language from your terminal. Poule extends Claude's capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/): when you ask Claude a question about Coq, it automatically calls the right Poule tools behind the scenes and presents the results in plain language. You never need to invoke Poule tools directly.

For example, you can ask Claude things like:

**Search — find lemmas you didn't know existed:**
- *"Find lemmas about list reversal being involutive"*
- *"Search for lemmas with type `forall n : nat, n + 0 = n`"*
- *"I need a lemma that says filtering a list twice is the same as filtering once"*
- *"What MathComp lemmas deal with matrix determinants?"*
- *"Find something in Flocq about rounding errors on addition"*

**Exploration — navigate unfamiliar libraries:**
- *"What's in the Corelib.Arith module?"*
- *"Give me an overview of the MathComp ssreflect sequence lemmas"*
- *"What typeclasses does std++ provide for finite maps?"*
- *"How does Coquelicot define integration?"*

**Proof interaction:**
- *"Open a proof session on `rev_involutive` in `examples/lists.v` and show me the current goal"*
- *"Step through the proof of `add_comm` in `examples/arith.v` and explain each tactic"*
- *"Try applying `intros` then `induction l` in my current proof session"*

**Profiling — find and fix performance bottlenecks:**
- *"Profile the proof of `ring_morph` in `examples/algebra.v` — what's making it slow?"*
- *"Profile `examples/algebra.v` and show me the slowest lemmas"*
- *"Why does `Qed` take 30 seconds on this proof? Is it the tactics or the kernel re-checking?"*
- *"Compare timing before and after my optimization"*

**Debugging automation — understand why tactics fail:**
- *"Why doesn't `auto` solve this goal? The lemma is right there in the hint database"*
- *"Why wasn't `bpow_ge_0` used by `auto`? I registered it as a hint"*
- *"Compare `auto`, `eauto`, and `typeclasses eauto` on my current goal"*

**Dependent pattern matching — fix `destruct` failures:**
- *"I got 'Abstracting over ... leads to an ill-typed term' — what went wrong?"*
- *"`destruct` lost the equality between my index and the constructor — how do I fix this?"*
- *"Generate the convoy pattern boilerplate for this match"*

**Setoid rewriting — fix `Proper` constraint errors:**
- *"Why does `setoid_rewrite` fail with 'Unable to satisfy Proper constraint'?"*
- *"Generate the `Proper` instance I need for `union` with `eq_set`"*
- *"`rewrite` can't find the subterm inside this `forall` — what do I do?"*

**Dependencies — understand how lemmas connect:**
- *"What lemmas does `Nat.add_comm` depend on?"*
- *"Which lemmas use `Nat.add_0_r`?"*
- *"Show me other lemmas in the same module as `List.rev_append`"*

**Visualization:**
- *"Visualize the proof tree for `app_nil_r` in `examples/lists.v`"*
- *"Show me the dependency graph around `Nat.add_comm`"*
- *"Render the step-by-step proof evolution of `modus_ponens` in `examples/logic.v`"*

Claude will search the index, manage proof sessions, and generate diagrams on your behalf. When Claude calls a visualization tool, it writes `proof-diagram.html` to your project directory (the folder you started `poule` from, or `POULE_PROJECT_DIR` if set) — open it in your browser to see the rendered diagram. Bookmark the file and refresh after each visualization call.

**Skills (slash commands):**

Poule also provides compound workflows that orchestrate multiple tools in a single command:

- *`/formalize For all natural numbers, addition is commutative`* — Claude searches for existing lemmas, proposes a formal Coq statement, type-checks it, and helps build the proof interactively
- *`/explain-proof Nat.add_comm`* — step through a proof with plain-language explanations of each tactic, including mathematical intuition
- *`/compress-proof rev_involutive in examples/lists.v`* — find shorter proof alternatives, verify each one, present ranked options
- *`/proof-obligations`* — scan your project for `admit`/`Admitted`/`Axiom`, classify intent, rank by severity
- *`/proof-repair`* — after a Coq version upgrade, systematically fix broken proofs through a build→fix→rebuild loop
- *`/proof-lint examples/lint_targets.v`* — detect deprecated tactics, inconsistent bullets, and complex tactic chains; optionally auto-fix
- *`/explain-error`* — parse a Coq type error, fetch relevant definitions, explain the root cause in plain language with fix suggestions
- *`/migrate-rocq`* — bulk-rename deprecated `Coq.*` namespaces to `Rocq.*` with build verification
- *`/check-compat`* — check dependency compatibility before you hit opaque build failures
- *`/scaffold`* — generate a complete project skeleton (Dune, opam, CI, boilerplate)

For the full list of skills and their details, see [Skills Reference](doc/claude-skills.md).

**Capabilities provided to Claude:**

| Category | What Claude can do |
|----------|--------------------|
| **Search** | Find lemmas by name, type signature, structural similarity, or symbol usage; navigate dependencies; browse modules |
| **Proof interaction** | Open interactive proof sessions, observe goal states, submit tactics, step through proofs, extract traces with premise annotations |
| **Profiling** | Profile proofs and files for per-tactic timing, separate Qed from tactic time, explain bottlenecks, suggest optimizations, compare runs for regressions |
| **Proof assistants** | Diagnose `auto`/`eauto` hint failures, fix dependent pattern matching (`destruct`/convoy pattern), resolve `setoid_rewrite` `Proper` constraint errors |
| **Visualization** | Render proof states, proof trees, dependency graphs, and step-by-step proof evolution as Mermaid diagrams — written to `proof-diagram.html` in your project directory for browser viewing |
| **Skills** | Compound agentic workflows: formalization, proof compression, explanation, linting, repair, migration, compatibility analysis, error diagnosis, scaffolding |

For the full list of MCP tools and their parameters, see [MCP Tools Reference](doc/poule-mcp.md).

### CLI

All search and proof replay features are also available as standalone commands inside the container:

```bash
poule search-by-name "Nat.add_comm"
poule search-by-type "nat -> nat -> nat"
poule --help
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, project structure, testing, and documentation layers.

## FAQ

See [FAQ.md](FAQ.md).

## License

See [LICENSE](LICENSE) and [NOTICE](NOTICE).
