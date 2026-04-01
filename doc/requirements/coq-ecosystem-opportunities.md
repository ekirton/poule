# Coq/Rocq Ecosystem — Opportunity Landscape

## 1. Ecosystem Overview

The Coq/Rocq ecosystem has several unmet needs that hinder adoption and productivity. The Lean ecosystem has surged ahead with purpose-built tooling for search, proof interaction, and AI integration. But the opportunity for Poule is not merely to replicate Lean's tooling for Coq. Poule delivers capabilities through MCP with Claude Code as the primary interface — an agentic paradigm that is fundamentally different from traditional IDE tooling. This opens three categories of opportunity:

1. **Lean-parity gaps** — capabilities the Lean ecosystem has that Coq lacks entirely.
2. **Low-cost MCP wrappers for mature Coq tools** — existing, battle-tested tools (CoqHammer, coq-dpdgraph, Alectryon, Coq's own vernacular commands) that already work but are hard to discover, invoke, or interpret. Wrapping them as MCP tools makes them accessible through natural language at minimal development cost.
3. **Agentic workflows with no IDE equivalent** — compound, multi-step operations that require orchestrating several tools, interpreting intermediate results, and adapting strategy. No traditional IDE — Lean or Coq — can offer these because they require natural language reasoning and multi-tool coordination. These are the highest-differentiation opportunities.

This document captures the full opportunity set; per-initiative PRDs contain detailed requirements where they exist.

---

## 2. Lean-Parity Gaps

Capabilities where Lean has mature tooling and Coq has nothing comparable. These are the gaps most visible to the community.

| Opportunity | Gap Severity | Dependencies | Primary Beneficiary | Initiative PRD |
|-------------|-------------|-------------|---------------------|----------------|
| Semantic Lemma Search | High | None | All Coq users | [semantic-lemma-search.md](semantic-lemma-search.md) |
| Proof Interaction Protocol | Medium-High | None | Tool builders, AI researchers | [proof-interaction-protocol.md](proof-interaction-protocol.md) |
| Training Data Extraction | High | Interaction Protocol | AI researchers, tool builders | [training-data-extraction.md](training-data-extraction.md) |
| Proof Search & Automation | High | Interaction Protocol, Search | All Coq users | [proof-search-automation.md](proof-search-automation.md) |
| Neural Tactic Prediction | Medium | Extraction | All Coq users, researchers | [neural-tactic-prediction.md](neural-tactic-prediction.md) |
| Proof Visualization Widgets | High | None | Educators, formalization developers | [proof-visualization-widgets.md](proof-visualization-widgets.md) |
| CI/CD Tooling | Medium | None | All Coq project maintainers | — (out of scope) |
| Package Registry | Medium | None (benefits from CI/CD) | All Coq users, especially newcomers | — (out of scope) |

---

## 3. Low-Cost MCP Wrappers for Mature Coq Tools

These are existing, production-quality tools that already solve real problems. Today they are underused because they require command-line expertise, version-specific setup, or opaque output that users struggle to interpret. Wrapping them as MCP tools makes Claude the interface — Claude invokes the tool, parses the output, and explains the result in context. Development cost is low because the hard work (the tool itself) is already done.

| Opportunity | Underlying Tool | What MCP Enables | Effort | Primary Beneficiary | Initiative PRD |
|-------------|----------------|-----------------|--------|---------------------|----------------|
| Automated proving via hammer | CoqHammer (`hammer`, `sauto`, `qauto`) | User says "try to prove this"; Claude invokes hammer in the active proof session, reports success or explains failure | Low | All Coq users | [hammer-automation.md](hammer-automation.md) |
| Vernacular introspection | Coq built-ins: `Print`, `Check`, `About`, `Locate`, `Search`, `Compute`, `Eval` | Claude can inspect types, unfold definitions, evaluate expressions, and locate names on demand without the user switching to a Coq toplevel | Low | All Coq users | [vernacular-introspection.md](vernacular-introspection.md) |
| Assumption auditing | `Print Assumptions` | Claude lists axioms a theorem depends on (e.g., classical logic, functional extensionality) and explains their implications | Low | Formalization developers, reviewers | [assumption-auditing.md](assumption-auditing.md) |
| Universe constraint inspection | `Print Universes`, `Set Printing Universes` | Claude surfaces universe constraints and explains inconsistency errors — one of the hardest Coq debugging tasks | Low | Advanced users, library authors | [universe-inspection.md](universe-inspection.md) |
| Typeclass instance debugging | `Set Typeclasses Debug`, `Print Instances` | Claude traces instance resolution failures and explains why a particular instance was or was not selected | Low | All Coq users (typeclass errors are a top pain point) | [typeclass-debugging.md](typeclass-debugging.md) |
| Dependency graph extraction | coq-dpdgraph | Richer transitive dependency analysis beyond what Poule's `find_related` provides; useful for understanding proof structure at scale | Low | Library maintainers, formalization developers | [dependency-graph-extraction.md](dependency-graph-extraction.md) |
| Literate documentation generation | Alectryon | Claude generates interactive proof documentation from source files; particularly valuable for educational content | Low-Medium | Educators, documentation authors | [literate-documentation.md](literate-documentation.md) |
| Code extraction management | Coq `Extraction`, `Recursive Extraction` | Claude manages extraction of verified Coq code to OCaml, Haskell, or Scheme; explains extraction failures and suggests fixes | Low | Verified software developers | [code-extraction.md](code-extraction.md) |
| Independent proof checking | coqchk | Claude runs the independent checker on compiled files and reports any kernel-level inconsistencies | Low | Formalization developers, CI pipelines | [proof-checking.md](proof-checking.md) |
| Build system integration | coq_makefile, dune, opam | Claude generates `_CoqProject` / `dune-project` / `.opam` files, runs builds, interprets errors, manages dependencies | Low-Medium | All Coq project maintainers | [build-system-integration.md](build-system-integration.md) |
| Notation inspection | `Print Notation`, `Locate Notation`, `Print Scope` | Claude explains what a notation means, where it is defined, and how to create or modify notations | Low | All Coq users (notations are a frequent source of confusion) | [notation-inspection.md](notation-inspection.md) |
| Tactic documentation | `Print Ltac`, `Print Strategy`, tactic reference | Claude explains what a tactic does, when to use it, and how it differs from alternatives — contextual to the current proof state | Low | Newcomers, intermediate users | [tactic-documentation.md](tactic-documentation.md) |

### Why this category matters

The Lean community focuses on building new tools. But Coq already has a deep bench of mature tools — CoqHammer alone has years of refinement and covers a large fraction of first-order goals. The problem is not that these tools do not exist; it is that they are hard to discover, hard to invoke correctly, and hard to interpret. An MCP wrapper turns "read the CoqHammer docs, install the plugin, figure out the right tactic" into "prove this for me." The cost is a thin adapter layer; the value is making a decade of existing tooling accessible through natural language.

---

## 4. Agentic Workflows with No IDE Equivalent

These are compound, multi-step workflows that no traditional IDE can provide. They require Claude to orchestrate multiple tools, interpret intermediate results, make decisions, and adapt. They represent the highest differentiation for Poule because they cannot be replicated by point tools.

### Implementation model: Claude Code slash commands

Unlike §3's MCP wrappers, these workflows are not atomic request/response operations. They require multi-step orchestration with LLM reasoning between steps — branching decisions, intermediate interpretation, and adaptive strategy. MCP tools cannot express this; they are single-turn primitives.

These workflows are implemented as **Claude Code slash commands** (custom skills): markdown prompt files in `.claude/commands/` that instruct Claude how to orchestrate the workflow. Each slash command composes the MCP tools from §3 as building blocks — the slash command is the "script" and the MCP tools are the "primitives."

| Opportunity | What It Does | Why No IDE Can Do It | Slash Command | Effort | Primary Beneficiary | Initiative PRD |
|-------------|-------------|---------------------|---------------|--------|---------------------|----------------|
| Proof obligation tracking | Scan a project for all `admit`, `Admitted`, `Axiom` declarations; classify by severity; track progress over time | Requires codebase-wide analysis + natural language classification of intent (some admits are intentional axioms, some are TODOs) | `/proof-obligations` | Low-Medium | Project maintainers, formalization teams | [proof-obligation-tracking.md](proof-obligation-tracking.md) |
| Proof repair on version upgrade | When upgrading Coq versions, systematically attempt to fix broken proofs: try hammer, search for renamed lemmas, apply known migration patterns | Requires chaining build → error parsing → search → proof interaction → retry in a feedback loop | `/proof-repair` | Medium | All Coq users upgrading versions | [proof-repair.md](proof-repair.md) |
| Type error explanation | Parse Coq type errors, fetch relevant type definitions and coercions, explain in plain language what went wrong and suggest fixes | Requires combining error output with contextual type inspection and natural language explanation | `/explain-error` | Low-Medium | All Coq users (especially newcomers) | [type-error-explanation.md](type-error-explanation.md) |
| Proof style linting and refactoring | Analyze proof scripts for deprecated tactics, inconsistent bullet style, unnecessarily complex tactic chains; suggest and apply improvements | Requires understanding proof structure + stylistic conventions + safe automated rewriting | `/proof-lint` | Medium | Formalization teams, library maintainers | [proof-lint.md](proof-lint.md) |
| Formalization assistance | User describes a theorem in natural language; Claude searches for relevant existing lemmas, suggests a formal statement, and helps build the proof interactively | Requires natural language understanding → search → proof interaction in a guided dialogue | `/formalize` | Medium | All Coq users | [formalization-assistance.md](formalization-assistance.md) |
| Proof compression | Given a working proof, find shorter or cleaner alternatives by trying hammer, searching for more direct lemmas, or simplifying tactic chains | Requires analyzing existing proof → extracting the goal → attempting alternative proof strategies → comparing results | `/compress-proof` | Medium | Formalization developers | [proof-compression.md](proof-compression.md) |
| Cross-library compatibility analysis | Check whether a project's declared dependencies are mutually compatible; detect version conflicts before the user hits opaque build failures | Requires querying opam metadata + understanding Coq version constraints + interpreting results | `/check-compat` | Low-Medium | All Coq project maintainers | [compatibility-analysis.md](compatibility-analysis.md) |
| Coq-to-Rocq migration | Automated assistance with the ongoing Coq-to-Rocq namespace rename: scan for deprecated names, suggest replacements, apply bulk renames | Requires pattern matching over a large rename map + safe multi-file refactoring | `/migrate-rocq` | Low-Medium | All Coq users migrating to Rocq | [rocq-migration.md](rocq-migration.md) |
| Proof explanation and teaching | Step through a proof and explain each tactic in natural language, referencing the mathematical intuition and the proof state evolution | Requires proof interaction + visualization + contextual explanation at each step — exactly what an LLM excels at | `/explain-proof` | Low | Educators, students, newcomers | [proof-explanation.md](proof-explanation.md) |
| Project scaffolding | Generate complete project skeletons: directory structure, build files, CI configuration, boilerplate module structure, README templates | Requires knowledge of Coq project conventions + build system specifics + CI best practices | `/scaffold` | Low | Newcomers, anyone starting a new project | [project-scaffolding.md](project-scaffolding.md) |

### Why this category matters

Traditional PL tooling is built around point interactions: the user positions a cursor, invokes a command, reads a result. Agentic workflows dissolve this constraint. The user states an intent ("fix the broken proofs after upgrading to Rocq 9.1") and Claude orchestrates dozens of tool invocations across files, sessions, and search queries. This is not an incremental improvement over IDE tooling — it is a different category of capability. The Lean ecosystem, for all its tooling investment, has no equivalent because the interaction model does not exist in their IDE-centric paradigm.
