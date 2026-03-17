# User Stories: Proof Obligation Tracking

Derived from [doc/requirements/proof-obligation-tracking.md](../proof-obligation-tracking.md).

---

## Epic 1: Scanning and Detection

### 1.1 Scan a Project for Proof Obligations

**As a** project maintainer,
**I want to** run `/proof-obligations` and have Claude scan my entire Coq project for `admit`, `Admitted`, and `Axiom` declarations,
**so that** I have a complete inventory of all unfinished proof obligations in the codebase.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq project with `.v` files WHEN `/proof-obligations` is invoked THEN every occurrence of `admit`, `Admitted`, and `Axiom` across all `.v` files is detected
- GIVEN a project with no `admit`, `Admitted`, or `Axiom` declarations WHEN `/proof-obligations` is invoked THEN the report indicates zero obligations found
- GIVEN a project with obligations in nested subdirectories WHEN `/proof-obligations` is invoked THEN obligations in all subdirectories are detected

**Traces to:** RPO-P0-1

### 1.2 Report Location and Context for Each Obligation

**As a** project maintainer,
**I want** each detected obligation to include its file path, line number, surrounding code context, and enclosing definition or proof name,
**so that** I can navigate directly to the obligation and understand what it belongs to.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a detected `Admitted` in a proof WHEN the report is generated THEN it includes the file path, line number, the enclosing proof name, and at least 3 lines of surrounding context
- GIVEN a detected `Axiom` declaration WHEN the report is generated THEN it includes the axiom name, file path, and line number
- GIVEN a detected `admit` tactic WHEN the report is generated THEN it includes the enclosing proof name and the goal context at the point of admission

**Traces to:** RPO-P0-2

### 1.3 Exclude False Positives

**As a** project maintainer,
**I want** occurrences of `admit` or `Admitted` inside comments or strings to be excluded from the report,
**so that** the obligation inventory is accurate and does not include noise.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an `admit` appearing inside a Coq comment `(* ... *)` WHEN the project is scanned THEN that occurrence is not included in the report
- GIVEN an `Admitted` appearing inside a string literal WHEN the project is scanned THEN that occurrence is not included in the report
- GIVEN an `admit` used as a tactic in active proof code WHEN the project is scanned THEN that occurrence is included in the report

**Traces to:** RPO-P2-3

---

## Epic 2: Classification

### 2.1 Classify Obligation Intent

**As a** formalization team member,
**I want** each detected obligation to be classified by intent — intentional axiom, TODO placeholder, or unknown,
**so that** I can distinguish between deliberate design decisions and unfinished work.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an `Axiom` declaration with a comment indicating it is a design choice (e.g., "We assume classical logic") WHEN classified THEN it is labeled as an intentional axiom
- GIVEN an `Admitted` with a preceding `(* TODO *)` comment WHEN classified THEN it is labeled as a TODO placeholder
- GIVEN an `admit` with no contextual signals about intent WHEN classified THEN it is labeled as unknown
- GIVEN the full set of classified obligations WHEN reviewed by a domain expert THEN at least 90% of classifications agree with expert judgment

**Traces to:** RPO-P0-3

### 2.2 Assign Severity to Each Obligation

**As a** project maintainer,
**I want** each obligation to receive a severity level (high, medium, low) based on its classification, dependency impact, and contextual signals,
**so that** I can prioritize which obligations to address first.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an `admit` classified as a TODO in a theorem that many other theorems depend on WHEN severity is assigned THEN it receives high severity
- GIVEN an `Axiom` classified as an intentional axiom WHEN severity is assigned THEN it receives low severity
- GIVEN two obligations with different severity levels WHEN the report is generated THEN higher-severity obligations are always ranked above lower-severity ones
- GIVEN an obligation with unknown intent WHEN severity is assigned THEN it receives at least medium severity to ensure it receives attention

**Traces to:** RPO-P0-4

---

## Epic 3: Reporting

### 3.1 Produce a Structured Summary Report

**As a** project maintainer,
**I want** a summary report that groups all obligations by severity, with counts and file locations,
**so that** I can quickly assess the overall state of proof completion in the project.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with obligations at multiple severity levels WHEN the report is generated THEN obligations are grouped by severity (high, medium, low) with a count for each group
- GIVEN a project with 15 obligations across 8 files WHEN the report is generated THEN every obligation appears in the report with its file location
- GIVEN a project scan WHEN the summary is presented THEN it includes a total obligation count, a breakdown by classification (intentional axiom / TODO / unknown), and a breakdown by severity

**Traces to:** RPO-P0-5

### 3.2 Filter the Report

**As a** formalization team member,
**I want to** filter the obligation report by file, directory, severity level, or classification,
**so that** I can focus on the obligations most relevant to my current work.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a report with obligations across multiple directories WHEN filtered by a specific directory THEN only obligations in that directory (and its subdirectories) are shown
- GIVEN a report with obligations at all severity levels WHEN filtered to high severity THEN only high-severity obligations are shown
- GIVEN a report with multiple classifications WHEN filtered to TODO obligations THEN only obligations classified as TODOs are shown

**Traces to:** RPO-P1-4

### 3.3 Report Axiom Dependencies

**As a** formalization team member,
**I want** each `Axiom` declaration to show which theorems transitively depend on it,
**so that** I can assess the blast radius of each assumption.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an `Axiom` declaration in a compiled project WHEN the report is generated THEN it lists the theorems that transitively depend on that axiom
- GIVEN an `Axiom` that no theorem depends on WHEN the report is generated THEN it is flagged as unused
- GIVEN an `Axiom` with a large number of dependents WHEN severity is assessed THEN the dependency count contributes to a higher severity ranking

**Traces to:** RPO-P1-5

### 3.4 Generate Machine-Readable Output

**As a** project maintainer,
**I want** the obligation report to be available in a machine-readable format (e.g., JSON),
**so that** I can integrate it with CI pipelines or project dashboards.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a project scan WHEN machine-readable output is requested THEN the report is produced in valid JSON format
- GIVEN the JSON output WHEN parsed THEN each obligation entry includes file path, line number, classification, severity, and enclosing definition name
- GIVEN a CI pipeline WHEN it consumes the JSON output THEN it can fail the build if high-severity TODO obligations exceed a configurable threshold

**Traces to:** RPO-P2-1

---

## Epic 4: Progress Tracking

### 4.1 Track Progress Between Scans

**As a** formalization team member,
**I want** the slash command to compare current scan results against previous results and report the delta,
**so that** I can see whether the project is making progress toward completion.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a previous scan recorded 20 obligations and the current scan finds 17 WHEN the report is generated THEN it shows "3 obligations resolved since last scan"
- GIVEN a previous scan and a current scan where 2 new `admit` declarations were introduced WHEN the report is generated THEN it shows "2 new obligations introduced since last scan"
- GIVEN no previous scan data exists WHEN the slash command is run THEN it produces the full report without progress delta and notes that this is the first recorded scan

**Traces to:** RPO-P1-1

### 4.2 Persist Scan Results

**As a** project maintainer,
**I want** scan results to be persisted between sessions,
**so that** progress tracking works across multiple invocations over days or weeks.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a completed scan WHEN it finishes THEN the results are persisted to a location within the project (e.g., a `.poule/` directory or similar)
- GIVEN persisted scan data from a previous session WHEN `/proof-obligations` is run in a new session THEN the previous data is loaded and used for progress comparison
- GIVEN persisted scan data WHEN the project is checked into version control THEN the persisted data format is suitable for committing alongside the project (human-readable, diff-friendly)

**Traces to:** RPO-P1-2

### 4.3 Suggest Resolution Priority

**As a** formalization team member,
**I want** the report to suggest a prioritized order for resolving TODO obligations based on dependency impact and severity,
**so that** I can work on the highest-value obligations first.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN multiple TODO obligations with different severity levels WHEN prioritization is requested THEN obligations are ordered by severity (high first), with ties broken by dependency impact
- GIVEN a TODO obligation that blocks many downstream theorems WHEN prioritized THEN it appears higher in the suggested order than an isolated obligation of the same severity
- GIVEN the prioritized list WHEN each entry is reviewed THEN it includes a brief rationale for its position (e.g., "blocks 12 downstream theorems")

**Traces to:** RPO-P1-3
