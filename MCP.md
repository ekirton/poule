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
| `submit_tactic` | `tactic` (string), optional `options` (object) | Apply a tactic and see the resulting proof state |
| `step_backward` | — | Undo the last tactic |
| `step_forward` | — | Replay the next tactic from the original proof script |
| `submit_tactic_batch` | `tactics` (string[]) | Apply a sequence of tactics. Stops on the first failure and reports what went wrong |
| `get_proof_premises` | — | List all lemmas and definitions used across the entire proof |
| `get_step_premises` | `step` (integer, 1-based) | List lemmas and definitions used by a specific proof step |
| `suggest_tactics` | `session_id` (string) | Get ranked tactic hints for the current goal — neural and rule-based suggestions with rationale. Use these to explain to the student *why* a tactic makes sense. This is a teaching tool, not a solver. |
| `try_automation` | `session_id` (string), optional `strategy`, `options` | Attempt to close the current goal automatically using CoqHammer solvers. This is a solver — use for routine subgoals. See **Automated Solving** below. |

## Tactic Suggestion vs. Automated Solving

Poule separates two kinds of proof assistance:

- **`suggest_tactics`** — a teaching tool. Returns ranked tactic hints that Claude uses to explain *why* each tactic makes sense, linking to textbook material and proof techniques. The student stays in the loop and builds proof intuition.
- **`try_automation`** — a solver. Runs CoqHammer to try to close the goal without human involvement. Use for routine subgoals where the pedagogical value is low.

## Automated Solving (`try_automation`)

[CoqHammer](https://github.com/lukaszcz/coqhammer) is a powerful automation tool that can often close proof goals automatically. You access it through the `try_automation` tool:

| Strategy | What it does | Default timeout |
|----------|-------------|-----------------|
| `hammer` | Sends the goal to external provers (E, Vampire, Z3, CVC4) and reconstructs a Coq proof from the result | 30 s |
| `sauto` | Searches for a proof using Coq's own automation with extended depth | 10 s |
| `qauto` | A faster, shallower variant of `sauto` | 5 s |
| `auto_hammer` (default) | Tries all three strategies in sequence, stopping as soon as one succeeds | 90 s total |

**Options** — pass these in the `options` parameter to customize behavior:

| Option | Type | What it does |
|--------|------|--------------|
| `timeout` | number | Override the default timeout (seconds) |
| `hints` | string[] | Lemma names to suggest as hints to the prover |
| `sauto_depth` | integer | How deep `sauto` should search |
| `qauto_depth` | integer | How deep `qauto` should search |
| `unfold` | string[] | Definitions to unfold before searching (for `sauto`/`qauto`) |

When automation succeeds, the response includes the `proof_script` (the tactic that worked) and which `strategy_used`. When it fails, `diagnostics` explains what each strategy tried and why it didn't work — useful for understanding what to try next.

## Vernacular Query Tools

These tools execute Coq vernacular introspection commands in a live session.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `coq_query` | `command` (string), `argument` (string) | `session_id` | Execute a vernacular command: `Print`, `Check`, `About`, `Locate`, `Search`, `Compute`, or `Eval` |
| `notation_query` | `subcommand` (string), `session_id` (string) | `input` (string) | Inspect notations, scopes, and notation visibility |

## Assumption Auditing Tools

These tools inspect what axioms your theorems depend on — useful for checking constructivity, comparing formulations, and catching unintended classical assumptions.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `audit_assumptions` | `name` (string), `session_id` (string) | — | Audit axiom dependencies for a theorem via `Print Assumptions`. Returns classified axioms (classical, extensionality, choice, proof irrelevance, custom) |
| `audit_module` | `module` (string), `session_id` (string) | `flag_categories` (string[]) | Audit all theorems in a module for axiom dependencies. Flags theorems using specified axiom categories |
| `compare_assumptions` | `names` (string[]), `session_id` (string) | — | Compare axiom profiles across multiple theorems — shows shared and unique assumptions |

## Universe Inspection Tools

These tools help debug universe polymorphism issues — one of the trickiest error categories in Coq.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `inspect_universes` | `session_id` (string) | — | Retrieve the full universe constraint graph from the current environment |
| `inspect_definition_constraints` | `name` (string), `session_id` (string) | — | Get universe constraints for a specific definition |
| `diagnose_universe_error` | `error_message` (string), `session_id` (string) | — | Diagnose a universe inconsistency error — explains what conflicting constraints mean and suggests fixes |

## Typeclass Inspection Tools

These tools help understand and debug typeclass resolution — useful when instance search is slow, fails, or picks the wrong instance.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `list_instances` | `typeclass_name` (string), `session_id` (string) | — | List all registered instances of a typeclass |
| `list_typeclasses` | `session_id` (string) | — | List all registered typeclasses in the current session |
| `trace_resolution` | `session_id` (string) | — | Trace typeclass instance resolution — shows the search path and which instances were tried |

## Tactic Introspection Tools

These tools let you look up tactic definitions, inspect hint databases, and compare tactics side by side.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `tactic_lookup` | `name` (string) | `session_id` | Look up an Ltac tactic definition. Returns the definition body, or `kind=primitive` for built-in tactics |
| `inspect_hint_db` | `db_name` (string) | `session_id` | Inspect a hint database — lists Resolve, Unfold, Constructors, and Extern hints |
| `compare_tactics` | `names` (string[]) | `session_id` | Compare two or more tactics — shows structural differences, performance characteristics, and applicability |

## Dependency Analysis Tools

These tools work with the prebuilt dependency graph to analyze how declarations relate to each other at project scale.

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `transitive_closure` | `name` (string) | `max_depth` (int), `scope_filter` (string[]), `dot_file_path` (string) | Compute everything a declaration transitively depends on |
| `impact_analysis` | `name` (string) | `max_depth` (int), `scope_filter` (string[]), `dot_file_path` (string) | Find everything that transitively depends on a declaration — the blast radius of a change |
| `detect_cycles` | — | `dot_file_path` (string) | Detect circular dependencies in the indexed project |
| `module_summary` | — | `dot_file_path` (string) | Dependency summary grouped by module — shows fan-in, fan-out, and coupling |

## Documentation & Extraction Tools

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `generate_documentation` | `file_path` (string) | `format` (html\|rst\|latex, default html), `output_path` | Generate literate documentation from a Coq source file using Alectryon |
| `extract_code` | `session_id` (string), `definition_name` (string), `language` (ocaml\|haskell\|scheme) | `recursive` (bool, default false), `output_path` | Extract a Coq definition to OCaml, Haskell, or Scheme |

## Project Management Tools

| Tool | Required params | Optional params | What it does |
|------|----------------|-----------------|--------------|
| `build_project` | `project_dir` (string) | `target` (string), `timeout` (int, default 300s) | Build a Coq project using make or dune |
| `check_proof` | `file_path` (string) | `include_paths` (string[]), `load_paths` (string[][]), `timeout` (int, default 300s) | Run the independent proof checker (coqchk) on a compiled file |
| `query_packages` | — | — | List installed opam packages |
| `add_dependency` | `project_dir` (string), `package_name` (string) | `version` (string) | Add an opam dependency to the project's .opam file |

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
