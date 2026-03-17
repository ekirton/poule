# User Stories: Proof Style Linting and Refactoring

Derived from [doc/requirements/proof-lint.md](../proof-lint.md).

---

## Epic 1: Deprecated Tactic Detection

### 1.1 Detect Deprecated Tactics in a File

**As a** library maintainer,
**I want to** scan a Coq source file for uses of deprecated tactics,
**so that** I can update them before they are removed in a future Coq version.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq source file containing deprecated tactics WHEN `/proof-lint` is invoked on that file THEN all deprecated tactic uses are identified with their line numbers and the tactic name
- GIVEN a Coq source file containing no deprecated tactics WHEN `/proof-lint` is invoked on that file THEN no deprecated tactic issues are reported
- GIVEN a deprecated tactic WHEN it is detected THEN the report includes the recommended replacement tactic for the target Coq version

**Traces to:** RPL-P0-1, RPL-P0-5

### 1.2 Detect Deprecated Tactics Across a Project

**As a** formalization team lead,
**I want to** scan an entire Coq project for deprecated tactics,
**so that** I can assess the scope of migration work needed before a Coq version upgrade.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a directory containing multiple Coq source files WHEN `/proof-lint` is invoked on the directory THEN all deprecated tactic uses across all `.v` files are reported
- GIVEN a project with a `_CoqProject` file WHEN `/proof-lint` is invoked on the project root THEN it scans exactly the files listed in the project configuration
- GIVEN a large project WHEN `/proof-lint` completes THEN the summary reports the total count of deprecated tactic uses broken down by tactic name

**Traces to:** RPL-P0-1, RPL-P0-6

---

## Epic 2: Bullet Style Analysis

### 2.1 Detect Inconsistent Bullet Style Within a File

**As a** formalization developer,
**I want to** identify inconsistent bullet style usage within a single file,
**so that** I can normalize the proof structure to follow a single convention.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a file that mixes `+`/`-`/`*` bullets with `{}`/`}` braces for subgoal structuring WHEN `/proof-lint` is invoked THEN the inconsistency is flagged with the locations of each style
- GIVEN a file that uses a single consistent bullet convention throughout WHEN `/proof-lint` is invoked THEN no bullet style issues are reported
- GIVEN a file with inconsistent bullet nesting depth (e.g., some proofs nest three levels deep with `- -- ---` while others use `- + *`) WHEN `/proof-lint` is invoked THEN the nesting inconsistency is reported

**Traces to:** RPL-P0-2

### 2.2 Detect Inconsistent Bullet Style Across a Project

**As a** formalization team lead,
**I want to** identify the dominant bullet convention in my project and see which files deviate from it,
**so that** I can enforce a uniform style across all contributors' work.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with multiple Coq source files WHEN `/proof-lint` is invoked at the project level THEN it identifies the dominant bullet convention used across the project
- GIVEN a project with a dominant convention WHEN files deviate from that convention THEN those files are listed with the specific deviations
- GIVEN a project where no single convention dominates WHEN `/proof-lint` is invoked THEN it reports the distribution of styles and recommends the most common one

**Traces to:** RPL-P0-3

---

## Epic 3: Tactic Chain Simplification

### 3.1 Detect Unnecessarily Complex Tactic Chains

**As a** formalization developer,
**I want to** identify tactic chains that can be replaced by simpler alternatives,
**so that** my proofs are more readable and more robust to changes in definitions.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof containing `simpl; reflexivity` WHEN `/proof-lint` is invoked THEN it suggests replacing the chain with `auto` or `easy` where applicable
- GIVEN a proof containing a sequence of manual `rewrite` tactics using lemmas from a known rewrite database WHEN `/proof-lint` is invoked THEN it suggests using `autorewrite` with the appropriate database
- GIVEN a tactic chain that cannot be simplified WHEN `/proof-lint` is invoked THEN no false simplification suggestion is generated for that chain

**Traces to:** RPL-P1-1

### 3.2 Suggest Concrete Replacements for Complex Chains

**As a** library maintainer,
**I want to** see the exact replacement tactic text for each simplification suggestion,
**so that** I can evaluate whether the simplification is appropriate before applying it.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a detected tactic chain simplification WHEN the suggestion is displayed THEN it includes the original tactic sequence and the proposed replacement
- GIVEN a simplification suggestion WHEN the replacement is shown THEN it is syntactically valid Coq tactic syntax
- GIVEN multiple possible simplifications for the same tactic chain WHEN the suggestion is displayed THEN the simplest replacement is recommended first

**Traces to:** RPL-P1-2

---

## Epic 4: Reporting

### 4.1 Generate Structured Lint Report

**As a** formalization team lead,
**I want to** receive a structured report of all detected style issues,
**so that** I can prioritize which issues to address and track progress over time.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a scan that finds issues WHEN the report is generated THEN each issue includes: file path, line number, issue category (deprecated tactic, bullet style, tactic complexity), severity, and description
- GIVEN a scan of multiple files WHEN the report is generated THEN issues are grouped by file
- GIVEN a scan that finds no issues WHEN the report is generated THEN it confirms that no style issues were detected

**Traces to:** RPL-P0-4, RPL-P0-5

### 4.2 Provide Summary Statistics

**As a** formalization team lead,
**I want to** see a summary of issue counts by category and severity,
**so that** I can quickly assess the overall style health of the project.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed scan WHEN the summary is displayed THEN it shows total issue count broken down by category (deprecated tactics, bullet style, tactic complexity)
- GIVEN a completed scan WHEN the summary is displayed THEN it shows total issue count broken down by severity
- GIVEN a project-level scan WHEN the summary is displayed THEN it lists the files with the most issues in descending order

**Traces to:** RPL-P1-6

---

## Epic 5: Automated Refactoring

### 5.1 Apply Deprecated Tactic Replacements

**As a** library maintainer,
**I want to** automatically replace deprecated tactics with their recommended alternatives,
**so that** I can migrate large codebases without editing each proof by hand.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a detected deprecated tactic with a known replacement WHEN the user approves the refactoring THEN the source file is modified to use the replacement tactic
- GIVEN an applied tactic replacement WHEN the modified proof is checked through the proof interaction protocol THEN it compiles successfully
- GIVEN an applied tactic replacement that causes a proof failure WHEN the verification step detects the failure THEN the change is reverted and the user is notified that manual intervention is required

**Traces to:** RPL-P1-3, RPL-P1-4

### 5.2 Apply Bullet Style Normalization

**As a** formalization team lead,
**I want to** automatically normalize bullet style across a project to match the dominant convention,
**so that** all files follow a consistent proof structuring style without manual editing.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a file with bullet style deviations from the project convention WHEN the user approves bullet normalization THEN the file is rewritten to use the target bullet style
- GIVEN a bullet style normalization WHEN the modified file is checked THEN all proofs still compile successfully
- GIVEN a bullet normalization that would create ambiguous proof structure WHEN the refactoring is attempted THEN it is skipped for that proof and the user is notified

**Traces to:** RPL-P1-3, RPL-P1-4

### 5.3 Apply Tactic Chain Simplifications

**As a** formalization developer,
**I want to** automatically apply tactic chain simplifications that have been verified to preserve proof validity,
**so that** my proofs become cleaner without risk of breakage.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a detected tactic chain simplification WHEN the user approves the refactoring THEN the source file is modified to use the simplified tactic
- GIVEN an applied simplification WHEN it is verified through the proof interaction protocol THEN the simplified tactic closes the same goal as the original chain
- GIVEN an applied simplification that fails verification WHEN the failure is detected THEN the change is reverted and the original tactic chain is preserved

**Traces to:** RPL-P1-3, RPL-P1-4

---

## Epic 6: Configuration

### 6.1 Configure Project-Specific Style Preferences

**As a** formalization team lead,
**I want to** configure project-specific style rules (preferred bullet style, allowed deprecated tactics, ignored patterns),
**so that** `/proof-lint` respects my team's conventions rather than imposing a one-size-fits-all standard.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a project with a style configuration specifying the preferred bullet convention WHEN `/proof-lint` is invoked THEN it uses the configured convention as the baseline instead of inferring the dominant style
- GIVEN a style configuration that marks certain deprecated tactics as intentionally retained WHEN `/proof-lint` is invoked THEN those tactics are excluded from the deprecated tactic report
- GIVEN no style configuration file WHEN `/proof-lint` is invoked THEN it uses sensible defaults and infers the dominant style from the codebase

**Traces to:** RPL-P1-5
