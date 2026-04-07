# MCP Tools Reference

These are the tools Claude can use behind the scenes when you interact with Poule. You don't need to call them directly — Claude picks the right tool based on your question. This reference is here so you know what's available and can ask for it by name if you want to.

See also [SKILLS.md](SKILLS.md) for compound workflows (slash commands that combine multiple tools).

All search tools accept an optional `limit` (integer, default 50, max 200).
All proof interaction tools require a `session_id` (string) — returned by `open_proof_session`.

## Search Tools

These tools search across the prebuilt index of Coq libraries (stdlib, MathComp, std++, Flocq, Coquelicot, CoqInterval).

| Tool | Required params | What it does |
|------|----------------|--------------|
| `search_by_name` | `pattern` (string) | Find lemmas by name — supports `*` wildcards and substring matching |
| `search_by_type` | `type_expr` (string) | Find lemmas whose type signature matches an expression |
| `search_by_structure` | `expression` (string) | Find lemmas with a similar shape or structure to an expression |
| `search_by_symbols` | `symbols` (string[]) | Find lemmas that mention specific fully qualified names |
| `get_lemma` | `name` (string) | Look up a single lemma — returns its statement, type, module, and dependencies |
| `find_related` | `name` (string), `relation` (string) | Find related lemmas. Relations: `uses`, `used_by`, `same_module`, `same_typeclass` |
| `list_modules` | — | List available modules. Optional `prefix` filter, e.g. `Coq.Arith` |

## Proof Interaction Tools

These tools let Claude work with a live Coq process — opening proof sessions, stepping through proofs, and submitting tactics.

| Tool | Additional params | What it does |
|------|-----------------|--------------|
| `open_proof_session` | `file_path` (string), `proof_name` (string) | Start an interactive session on a proof. Returns a `session_id` for use with other tools |
| `close_proof_session` | — | End a session and release resources |
| `list_proof_sessions` | — | Show all active sessions |
| `observe_proof_state` | — | See the current goals and hypotheses |
| `get_proof_state_at_step` | `step` (integer, 0-based) | Peek at the proof state at a specific step without changing position |
| `extract_proof_trace` | — | Get the full history of tactics and proof states from start to current position |
| `submit_tactic` | `tactic` (string), optional `options` (object) | Apply a tactic and see the resulting proof state. Also supports CoqHammer keywords — see **Hammer Automation** below |
| `step_backward` | — | Undo the last tactic |
| `step_forward` | — | Replay the next tactic from the original proof script |
| `submit_tactic_batch` | `tactics` (string[]) | Apply a sequence of tactics. Stops on the first failure and reports what went wrong |
| `get_proof_premises` | — | List all lemmas and definitions used across the entire proof |
| `get_step_premises` | `step` (integer, 1-based) | List lemmas and definitions used by a specific proof step |
| `suggest_tactics` | `session_id` (string) | Get ranked tactic suggestions for the current goal |

## Hammer Automation

[CoqHammer](https://github.com/lukaszcz/coqhammer) is a powerful automation tool that can often close proof goals automatically. You access it through `submit_tactic` by using one of these special keywords as the tactic:

| Keyword | What it does | Default timeout |
|---------|-------------|-----------------|
| `hammer` | Sends the goal to external provers (E, Vampire, Z3, CVC4) and reconstructs a Coq proof from the result | 30 s |
| `sauto` | Searches for a proof using Coq's own automation with extended depth | 10 s |
| `qauto` | A faster, shallower variant of `sauto` | 5 s |
| `auto_hammer` | Tries all three strategies in sequence, stopping as soon as one succeeds | 90 s total |

**Options** — pass these in the `options` parameter to customize behavior:

| Option | Type | What it does |
|--------|------|--------------|
| `timeout` | number | Override the default timeout (seconds) |
| `hints` | string[] | Lemma names to suggest as hints to the prover |
| `sauto_depth` | integer | How deep `sauto` should search |
| `qauto_depth` | integer | How deep `qauto` should search |
| `unfold` | string[] | Definitions to unfold before searching (for `sauto`/`qauto`) |

When a hammer tactic succeeds, the response includes the `proof_script` (the tactic that worked) and which `strategy_used`. When it fails, `diagnostics` explains what each strategy tried and why it didn't work — useful for understanding what to try next.

## Profiling Tools

These tools help you find slow proofs and understand where time is being spent.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `profile_proof` | `file_path` (string) | `lemma_name`, `mode`, `baseline_path`, `timeout_seconds` | Profile compilation time — see modes below |

**Modes:**

| Mode | What it does | Requirements |
|------|-------------|--------------|
| `timing` (default) | Time every sentence in the file, ranked slowest-first. If `lemma_name` is set, focuses on that proof. | — |
| `ltac` | Break down time spent inside Ltac tactic calls for a specific proof | `lemma_name` required |
| `compare` | Compare current timing against a previous run and flag regressions | `baseline_path` required |

All modes classify bottlenecks by category (e.g. slow `Qed`, expensive type class search, deep `auto` search) and suggest concrete optimizations.

## Education Tools

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `education_context` | `query` (string) | `limit` (default 3, max 10), `volume` | Search the bundled *Software Foundations* textbook. Returns relevant passages with source citations and links you can open in your browser. `volume` filters by book: `lf`, `plf`, `vfa`, `qc`, `secf`, `slf`, `vc`. |

## Visualization Tools

These tools generate proof diagrams that are written to `proof-diagram.html` in your project directory. Open it in your browser and refresh after each visualization.

| Tool | Additional params | What it does |
|------|-----------------|--------------|
| `visualize_proof_state` | `step` (optional), `detail_level` (optional: `summary`/`standard`/`detailed`) | Diagram of the proof state at the current or specified step |
| `visualize_proof_tree` | — | Tree diagram showing how the proof branches and resolves (proof must be complete) |
| `visualize_dependencies` | `name` (string), `max_depth` (default 2), `max_nodes` (default 50) | Dependency graph for a lemma — what it uses and what uses it |
| `visualize_proof_sequence` | `detail_level` (optional) | Step-by-step animation of how the proof evolves, with diffs highlighted |
