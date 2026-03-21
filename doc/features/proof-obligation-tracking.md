# Proof Obligation Tracking

Large Coq developments accumulate incomplete proofs — `admit`, `Admitted`, and `Axiom` declarations that start as temporary scaffolding and quietly become permanent fixtures. Over time, no one remembers which axioms are intentional design decisions, which admits are forgotten TODOs, and which gaps pose real risk to the soundness of downstream theorems. Proof Obligation Tracking provides a `/proof-obligations` slash command that scans an entire project, classifies every obligation by intent and severity, and tracks progress toward completion across successive scans.

---

## Problem

Developers working on Coq formalizations routinely use `admit` and `Admitted` to defer proofs and `Axiom` to postulate facts. This is normal and necessary during incremental development. The problem is what happens next: there is no project-wide way to understand the state of all these obligations. A developer can grep for `admit`, but that tells them nothing about whether a given `Axiom functional_extensionality` is a deliberate foundation of the project or a shortcut someone took six months ago. It tells them nothing about which of twenty admits are most urgent to resolve, or whether the project is making progress toward completion.

Existing tools operate at the wrong granularity. `Print Assumptions` reports axioms for a single theorem, one at a time. IDE tooling highlights admits in individual files. Neither provides a project-wide inventory, and neither can answer the question that actually matters: "what is the intent behind this obligation?" Answering that question requires reading surrounding comments, understanding naming conventions, examining how the obligation fits into the dependency graph, and applying judgment — exactly the kind of contextual reasoning that static analysis cannot do.

## Solution

The `/proof-obligations` slash command gives users a complete picture of every incomplete proof obligation in their project, with each obligation classified by intent and ranked by severity.

### Project-Wide Scanning

A single invocation of `/proof-obligations` scans every `.v` file in the project and identifies all occurrences of `admit`, `Admitted`, and `Axiom`. Each obligation is reported with its file location, the enclosing definition or proof, and enough surrounding context to understand what it belongs to. Nothing is missed because the user forgot to check a subdirectory or a file they didn't know existed.

### Intent Classification

For each detected obligation, the command classifies its intent as one of three categories: an intentional axiom (a deliberate design decision that the project is built on), a TODO placeholder (something the developer intends to prove but hasn't yet), or unknown (insufficient context to determine intent). Classification draws on surrounding comments, naming conventions, the role of the obligation in the codebase, and any other contextual signals. This is where the feature provides value that no existing tool can match — turning a flat list of text matches into an annotated inventory that distinguishes finished architectural decisions from unfinished work.

### Severity Ranking

Each obligation receives a severity level — high, medium, or low — based on its classification, its position in the project's dependency graph, and contextual signals about urgency. A TODO admit in a theorem that dozens of other results depend on is more severe than an isolated admit in a leaf lemma. An intentional axiom that the entire project is built on is a known foundation, not an urgent problem. Severity ranking lets users focus their effort where it matters most.

### Progress Tracking

When the command is run repeatedly over the course of a development effort, it compares current results against previous scans and reports the delta: how many obligations were resolved, how many new ones were introduced, and whether the project is trending toward completion. This turns a point-in-time snapshot into a tool for managing long-running formalization efforts.

### Filtering

Users can narrow the report to a specific file, directory, severity level, or classification. A team member working on a particular module can see just the obligations relevant to their work. A reviewer preparing for a release can filter to high-severity TODOs to understand what still needs attention.

## Scope

Proof Obligation Tracking provides:

- Project-wide detection of all `admit`, `Admitted`, and `Axiom` declarations across `.v` files
- Classification of each obligation by intent: intentional axiom, TODO placeholder, or unknown
- Severity ranking based on classification, dependency impact, and contextual signals
- A structured summary report grouped by severity with counts and file locations
- Progress tracking across successive scans, with delta reporting
- Filtering by file, directory, severity, or classification
- Dependency reporting for axioms, showing which theorems transitively rely on each assumption

Proof Obligation Tracking does not provide:

- Automated resolution of proof obligations — it reports what is incomplete, it does not attempt to finish proofs (see [Hammer Automation](hammer-automation.md) and [Proof Search](proof-search.md) for automated proving)
- Modifications to Coq source files — the command is strictly read-only
- Real-time or continuous monitoring — scans are initiated by the user
- IDE integration or editor plugins
- Visualization of obligation data (see [Proof Visualization Widgets](proof-visualization-widgets.md) for visual representations)

---

## Design Rationale

### Why a slash command rather than an MCP tool

Proof obligation tracking is an inherently multi-step workflow: scan files, parse results, classify each obligation using contextual reasoning, rank by severity, compare against historical data, and produce a report. This is a conversation-level orchestration task, not a single tool invocation. Implementing it as a slash command lets Claude coordinate multiple MCP tools — file reading, vernacular introspection, assumption auditing — in a flexible sequence, applying natural language reasoning at each step. It also avoids adding to the MCP tool count, which matters because LLM accuracy degrades as the number of available tools grows.

### Why intent classification requires an LLM

A grep for `Axiom` finds every axiom declaration, but it cannot tell you whether `Axiom classical_logic : forall P, P \/ ~P` is a foundational assumption the project deliberately adopts or a placeholder someone used because they couldn't figure out the proof. That distinction lives in comments ("We assume classical logic here"), naming conventions (axioms prefixed with `Ax_` vs. lemmas named `todo_`), surrounding code structure, and implicit conventions that vary across projects. No static rule set can reliably make this judgment across diverse codebases. Natural language reasoning over the full context of each obligation is what makes classification accurate enough to be useful.

### Why severity ranking matters more than raw counts

A project with 50 admits is not necessarily in worse shape than a project with 10. What matters is the nature and impact of each obligation. A single admit in a core lemma that the entire development depends on is more urgent than a dozen admits in standalone examples. Severity ranking captures this by incorporating dependency information and classification: high-severity TODO obligations in high-impact positions surface first, while low-severity intentional axioms sink to the bottom. This lets users act on the report rather than being overwhelmed by a flat list.

### Why track progress over time

Formalization projects span months or years. Without progress tracking, each scan is an isolated snapshot that tells the user how much work remains but not whether the trend is positive. By persisting scan results and computing deltas, the command transforms from a diagnostic tool into a project management tool. Teams can see that they resolved 15 obligations this sprint, that 3 new ones were introduced, and that total obligation count is trending downward. This is especially valuable for formalization efforts with completion milestones or deadlines.

## Acceptance Criteria

### Scanning and Detection

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project with `.v` files WHEN `/proof-obligations` is invoked THEN every occurrence of `admit`, `Admitted`, and `Axiom` across all `.v` files is detected
- GIVEN a project with no `admit`, `Admitted`, or `Axiom` declarations WHEN `/proof-obligations` is invoked THEN the report indicates zero obligations found
- GIVEN a project with obligations in nested subdirectories WHEN `/proof-obligations` is invoked THEN obligations in all subdirectories are detected
- GIVEN a detected `Admitted` in a proof WHEN the report is generated THEN it includes the file path, line number, the enclosing proof name, and at least 3 lines of surrounding context
- GIVEN a detected `Axiom` declaration WHEN the report is generated THEN it includes the axiom name, file path, and line number
- GIVEN a detected `admit` tactic WHEN the report is generated THEN it includes the enclosing proof name and the goal context at the point of admission

**Traces to:** RPO-P0-1, RPO-P0-2

### False Positive Exclusion

**Priority:** P2
**Stability:** Draft

- GIVEN an `admit` appearing inside a Coq comment `(* ... *)` WHEN the project is scanned THEN that occurrence is not included in the report
- GIVEN an `Admitted` appearing inside a string literal WHEN the project is scanned THEN that occurrence is not included in the report
- GIVEN an `admit` used as a tactic in active proof code WHEN the project is scanned THEN that occurrence is included in the report

**Traces to:** RPO-P2-3

### Classification

**Priority:** P0
**Stability:** Stable

- GIVEN an `Axiom` declaration with a comment indicating it is a design choice (e.g., "We assume classical logic") WHEN classified THEN it is labeled as an intentional axiom
- GIVEN an `Admitted` with a preceding `(* TODO *)` comment WHEN classified THEN it is labeled as a TODO placeholder
- GIVEN an `admit` with no contextual signals about intent WHEN classified THEN it is labeled as unknown
- GIVEN the full set of classified obligations WHEN reviewed by a domain expert THEN at least 90% of classifications agree with expert judgment
- GIVEN an `admit` classified as a TODO in a theorem that many other theorems depend on WHEN severity is assigned THEN it receives high severity
- GIVEN an `Axiom` classified as an intentional axiom WHEN severity is assigned THEN it receives low severity
- GIVEN two obligations with different severity levels WHEN the report is generated THEN higher-severity obligations are always ranked above lower-severity ones
- GIVEN an obligation with unknown intent WHEN severity is assigned THEN it receives at least medium severity to ensure it receives attention

**Traces to:** RPO-P0-3, RPO-P0-4

### Reporting

**Priority:** P0
**Stability:** Stable

- GIVEN a project with obligations at multiple severity levels WHEN the report is generated THEN obligations are grouped by severity (high, medium, low) with a count for each group
- GIVEN a project with 15 obligations across 8 files WHEN the report is generated THEN every obligation appears in the report with its file location
- GIVEN a project scan WHEN the summary is presented THEN it includes a total obligation count, a breakdown by classification (intentional axiom / TODO / unknown), and a breakdown by severity

**Traces to:** RPO-P0-5

### Report Filtering

**Priority:** P1
**Stability:** Draft

- GIVEN a report with obligations across multiple directories WHEN filtered by a specific directory THEN only obligations in that directory (and its subdirectories) are shown
- GIVEN a report with obligations at all severity levels WHEN filtered to high severity THEN only high-severity obligations are shown
- GIVEN a report with multiple classifications WHEN filtered to TODO obligations THEN only obligations classified as TODOs are shown

**Traces to:** RPO-P1-4

### Axiom Dependency Reporting

**Priority:** P1
**Stability:** Draft

- GIVEN an `Axiom` declaration in a compiled project WHEN the report is generated THEN it lists the theorems that transitively depend on that axiom
- GIVEN an `Axiom` that no theorem depends on WHEN the report is generated THEN it is flagged as unused
- GIVEN an `Axiom` with a large number of dependents WHEN severity is assessed THEN the dependency count contributes to a higher severity ranking

**Traces to:** RPO-P1-5

### Machine-Readable Output

**Priority:** P2
**Stability:** Draft

- GIVEN a project scan WHEN machine-readable output is requested THEN the report is produced in valid JSON format
- GIVEN the JSON output WHEN parsed THEN each obligation entry includes file path, line number, classification, severity, and enclosing definition name
- GIVEN a CI pipeline WHEN it consumes the JSON output THEN it can fail the build if high-severity TODO obligations exceed a configurable threshold

**Traces to:** RPO-P2-1

### Progress Tracking

**Priority:** P1
**Stability:** Stable

- GIVEN a previous scan recorded 20 obligations and the current scan finds 17 WHEN the report is generated THEN it shows "3 obligations resolved since last scan"
- GIVEN a previous scan and a current scan where 2 new `admit` declarations were introduced WHEN the report is generated THEN it shows "2 new obligations introduced since last scan"
- GIVEN no previous scan data exists WHEN the slash command is run THEN it produces the full report without progress delta and notes that this is the first recorded scan

**Traces to:** RPO-P1-1

### Scan Persistence

**Priority:** P1
**Stability:** Draft

- GIVEN a completed scan WHEN it finishes THEN the results are persisted to a location within the project (e.g., a `.poule/` directory or similar)
- GIVEN persisted scan data from a previous session WHEN `/proof-obligations` is run in a new session THEN the previous data is loaded and used for progress comparison
- GIVEN persisted scan data WHEN the project is checked into version control THEN the persisted data format is suitable for committing alongside the project (human-readable, diff-friendly)

**Traces to:** RPO-P1-2

### Resolution Priority Suggestion

**Priority:** P1
**Stability:** Draft

- GIVEN multiple TODO obligations with different severity levels WHEN prioritization is requested THEN obligations are ordered by severity (high first), with ties broken by dependency impact
- GIVEN a TODO obligation that blocks many downstream theorems WHEN prioritized THEN it appears higher in the suggested order than an isolated obligation of the same severity
- GIVEN the prioritized list WHEN each entry is reviewed THEN it includes a brief rationale for its position (e.g., "blocks 12 downstream theorems")

**Traces to:** RPO-P1-3
