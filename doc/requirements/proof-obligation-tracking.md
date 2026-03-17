# Proof Obligation Tracking — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) §4 for ecosystem context.

## 1. Business Goals

Large Coq developments accumulate proof obligations in various states of completion. Developers use `admit` and `Admitted` as placeholders during incremental development, and `Axiom` declarations to postulate facts that may or may not be proven later. Over time, the distinction between "intentional axiom," "temporary placeholder," and "forgotten TODO" blurs. Without a systematic way to inventory and classify these obligations, projects drift toward states where no one knows how much unfinished work remains or how risky the remaining assumptions are.

This initiative provides a Claude Code slash command (`/proof-obligations`) that scans an entire Coq project, identifies all proof obligations (`admit`, `Admitted`, `Axiom`), classifies each by intent and severity using natural language reasoning, and produces a structured report. Because classification requires understanding context — comments, naming conventions, surrounding code, and project history — this is fundamentally an agentic workflow that no static analysis tool or IDE feature can replicate. The slash command orchestrates MCP tools from §3 (vernacular introspection, assumption auditing, build system integration) as building blocks, combining codebase-wide file analysis with LLM-driven interpretation.

This is an agentic workflow implemented as a Claude Code slash command, not an MCP tool. It lives in `.claude/commands/` and composes existing MCP tools as primitives. It does not add to the MCP tool count budget.

**Success metrics:**
- 100% of `admit`, `Admitted`, and `Axiom` declarations in a scanned project are detected and reported
- >= 90% of detected obligations are correctly classified by intent (intentional axiom vs. TODO placeholder vs. unknown) when evaluated against human judgment on a representative test corpus
- Severity ranking is consistent: obligations classified as high severity are always ranked above those classified as low severity
- A full project scan completes within 5 minutes for projects with up to 50,000 lines of Coq code
- Progress tracking shows meaningful delta when obligations are resolved between successive scans

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Project maintainers | Inventory of all unfinished proof obligations across a codebase, with severity ranking to prioritize work | Primary |
| Formalization teams | Track progress toward completion milestones; ensure no forgotten admits slip into releases | Primary |
| Code reviewers | Quickly assess the proof obligation landscape of a project or pull request before reviewing | Secondary |
| Newcomers to an existing project | Understand which parts of a codebase are fully proven and which still have gaps | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- Lean 4 provides `#check` and `sorry` as the primary incomplete-proof marker. IDE tooling (Lean Infoview) highlights `sorry` in individual files but does not provide project-wide scanning, classification, or progress tracking.
- No existing Lean tool classifies the intent behind a `sorry` — whether it is a temporary placeholder, a known gap, or an intentional axiom.

**Coq ecosystem (current state):**
- `Print Assumptions` lists axioms a specific theorem depends on, but requires invoking it per-theorem and does not scan a project.
- `grep` can find `admit`, `Admitted`, and `Axiom` textually, but cannot distinguish intentional axioms from TODOs, cannot assess severity, and cannot track progress over time.
- coq-dpdgraph provides dependency analysis but does not specifically track proof obligations or classify their intent.
- No existing tool combines project-wide scanning with natural language classification of intent and severity.

**Key insight:** The detection of proof obligations is trivial (text search). The value lies in classification (is this `Axiom` intentional or a TODO?), severity ranking (which obligations are most urgent?), and progress tracking (are we making progress toward completion?). These require natural language reasoning over code context — exactly what an agentic workflow with LLM interpretation provides.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPO-P0-1 | Scan all `.v` files in a Coq project and detect every occurrence of `admit`, `Admitted`, and `Axiom` declarations |
| RPO-P0-2 | For each detected obligation, report the file path, line number, surrounding context, and the enclosing definition or proof name |
| RPO-P0-3 | Classify each detected obligation by intent: intentional axiom (deliberately postulated), TODO placeholder (intended to be proven later), or unknown |
| RPO-P0-4 | Assign a severity level to each obligation (e.g., high, medium, low) based on its classification, position in the dependency graph, and contextual signals |
| RPO-P0-5 | Produce a structured summary report listing all obligations grouped by severity, with counts and file locations |
| RPO-P0-6 | Implement as a Claude Code slash command (`/proof-obligations`) that orchestrates existing MCP tools, not as a new MCP tool |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPO-P1-1 | Track obligation counts over time and report progress delta between successive scans (e.g., "3 admits resolved since last scan, 2 new admits introduced") |
| RPO-P1-2 | Persist scan results so that progress can be compared across sessions |
| RPO-P1-3 | For each obligation classified as a TODO, suggest a prioritized order for resolution based on dependency impact and severity |
| RPO-P1-4 | Support filtering the report by file, directory, severity level, or classification |
| RPO-P1-5 | For each `Axiom` declaration, use assumption auditing to report which theorems transitively depend on it |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPO-P2-1 | Generate a machine-readable output format (e.g., JSON) suitable for integration with CI pipelines or dashboards |
| RPO-P2-2 | For obligations classified as TODOs, attempt to discharge them automatically using hammer or proof search and report which ones could be resolved |
| RPO-P2-3 | Detect `admit` or `Admitted` occurrences inside comments or strings and exclude them from the report to avoid false positives |

---

## 5. Scope Boundaries

**In scope:**
- Project-wide scanning of `.v` files for `admit`, `Admitted`, and `Axiom` declarations
- Natural language classification of each obligation's intent (intentional vs. TODO vs. unknown)
- Severity ranking based on classification and contextual signals
- Structured summary reporting with grouping and counts
- Progress tracking across successive scans
- Implementation as a Claude Code slash command composing existing MCP tools
- Filtering and sorting of results

**Out of scope:**
- Automated resolution of proof obligations (covered by Proof Search & Automation and Hammer Automation initiatives)
- Modifications to Coq source files (the command is read-only; it reports, it does not fix)
- IDE plugin development or editor integration
- Build system integration beyond what is needed to locate project files
- Real-time or continuous monitoring (scans are user-initiated via the slash command)
- Visualization widgets (covered by Proof Visualization Widgets initiative)
