# Independent Proof Checking

Wraps Coq's independent proof checker (`coqchk`) so that Claude Code can re-validate compiled `.vo` files against the kernel on the user's behalf. The user asks Claude to independently verify a proof; the tool invokes `coqchk`, interprets its output, and returns a clear verdict — either confirmation that the proof is kernel-valid, or a plain-language explanation of what went wrong.

---

## Problem

Coq's main compiler (`coqc`) type-checks proof scripts and produces compiled `.vo` files. The entire development workflow trusts this single pipeline — if `coqc` accepts a proof, the proof is considered valid. But the type checker is a large, complex piece of software, and kernel bugs have occurred in practice. For high-assurance work — certified compilers, cryptographic protocol proofs, safety-critical systems — a single point of trust is insufficient.

`coqchk` exists precisely to address this. It re-verifies compiled `.vo` files against a minimal, standalone kernel implementation that shares no code with the main compiler pipeline. If a bug in `coqc` silently accepts an invalid proof, `coqchk` will catch the inconsistency. Running `coqchk` is considered best practice for any project where proof validity is critical.

Yet `coqchk` remains underused. It requires manual invocation from the command line, its flags and path configuration are non-obvious, and its error messages assume familiarity with Coq kernel internals. Most developers only run it — if at all — before major releases or audits. The result is a valuable defense-in-depth mechanism that sits idle during everyday development, exactly when catching problems early would be most useful.

## Solution

### Single-File Checking

A user points Claude at a compiled `.vo` file and asks for independent verification. The tool invokes `coqchk` against that file and returns a verdict: either a confirmation that the module's proofs are kernel-valid, or a structured explanation of any inconsistency found. The user does not need to know `coqchk` command-line syntax, flag conventions, or how to configure include paths — the tool handles all of that.

When checking succeeds, the result confirms what was verified: which module, how many definitions were checked. When checking fails, the result identifies the specific module and definition where the inconsistency was detected, explains the nature of the problem in plain language, and distinguishes between different failure modes (axiom mismatches, proof-level errors, missing dependencies).

### Project-Wide Checking

Rather than checking files one at a time, the user asks Claude to verify an entire Coq project. The tool discovers all compiled `.vo` files in the project, derives include paths and logical path mappings from the project configuration (e.g., `_CoqProject`), and invokes `coqchk` across the full dependency graph. When the check completes, a summary report shows the total number of files checked, how many passed, how many failed, and per-file status for any failures.

Before checking, the tool compares modification times of `.vo` files against their corresponding `.v` source files. If any compiled files are stale — older than their source — the user is warned before the check proceeds, so they can recompile first rather than draw false conclusions from outdated artifacts.

### Failure Reporting

When `coqchk` reports an inconsistency, the user receives more than a raw error message. The response identifies the failing module and definition, explains what the inconsistency means, and suggests concrete next steps: recompile the file, check its dependencies first, investigate specific axioms, or increase the timeout if the checker ran out of time. The goal is to make every failure actionable, even for users who have never seen a `coqchk` error before.

### CI Integration

For teams that want independent proof checking as a merge gate, the tool produces output suitable for CI pipelines: a structured result format with per-file status, overall pass/fail, and timing information. CI systems can inspect the result programmatically to block merges when any file fails independent checking, while developers reviewing the pipeline log see a human-readable summary alongside the machine-readable payload.

## Design Rationale

### Why defense in depth matters

The Coq kernel is small by design, but it is not trivial — and kernel bugs have been found and fixed over the years. Any single implementation can harbor subtle errors. `coqchk` provides an independent second opinion by re-checking proofs against a separate kernel implementation. This is the same principle that drives N-version programming in safety-critical systems: when the cost of an undetected error is high, you do not rely on a single verification path.

For most everyday Coq development, trusting `coqc` alone is perfectly reasonable. But for high-assurance formalizations — proofs that underpin certified software, security protocols, or regulatory compliance — the marginal cost of running `coqchk` is negligible compared to the cost of an unsound proof slipping through. Making `coqchk` easy to invoke removes the friction that keeps it out of these workflows.

### When to recommend independent checking

Independent checking is most valuable for high-assurance formalizations: projects where proof validity has real-world consequences. Certified compilers like CompCert, cryptographic protocol verifications, and safety-critical system models are canonical examples. For these projects, running `coqchk` before releases, after major refactors, and as a CI gate is straightforward best practice.

For exploratory development and learning exercises, independent checking is less urgent — but still useful as a teaching tool. When a newcomer's proof passes `coqc` but fails `coqchk`, the explanation of why provides a window into how Coq's trust model works. The feature supports both use cases, but its primary value is in the high-assurance context where defense in depth is not optional.

---

## Acceptance Criteria

### Check a Single Compiled File

**Priority:** P0
**Stability:** Stable

- GIVEN a compiled `.vo` file WHEN independent checking is invoked for that file THEN `coqchk` is executed against the file and the result (pass or fail) is returned
- GIVEN a `.vo` file that passes `coqchk` WHEN the result is returned THEN it confirms that the proofs in the module are independently verified as kernel-valid
- GIVEN a `.vo` file path that does not exist WHEN checking is invoked THEN a clear error is returned indicating the file was not found

**Traces to:** RC-P0-1

### Interpret Checker Output

**Priority:** P0
**Stability:** Stable

- GIVEN a successful `coqchk` run WHEN the result is presented THEN it includes a plain-language confirmation of what was verified (e.g., which module, how many definitions checked)
- GIVEN a `coqchk` failure WHEN the result is presented THEN it includes the module name, the nature of the inconsistency, and a plain-language explanation of what it means and why it matters
- GIVEN a `coqchk` failure involving an axiom inconsistency WHEN the result is presented THEN the explanation distinguishes between an axiom mismatch and a proof-level error

**Traces to:** RC-P0-3

### Check an Entire Project

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project directory containing compiled `.vo` files WHEN project-wide checking is invoked THEN `coqchk` is executed across all `.vo` files respecting the dependency graph
- GIVEN a project with a `_CoqProject` file WHEN project-wide checking is invoked THEN include paths and logical path mappings are derived from the project configuration
- GIVEN a project-wide check WHEN it completes THEN every `.vo` file in the project has been checked

**Traces to:** RC-P0-2, RC-P1-3

### Batch Checking with Summary Report

**Priority:** P1
**Stability:** Stable

- GIVEN a project-wide check that completes WHEN the summary is returned THEN it includes the total number of files checked, the number that passed, and the number that failed
- GIVEN a project-wide check with failures WHEN the summary is returned THEN each failed file is listed with its specific failure reason
- GIVEN a project-wide check where all files pass WHEN the summary is returned THEN it confirms that the entire project is independently verified

**Traces to:** RC-P1-1

### Handle Checker Failures

**Priority:** P0
**Stability:** Stable

- GIVEN a `coqchk` run that reports an inconsistency WHEN the failure is presented THEN the response includes the specific module and definition where the inconsistency was detected
- GIVEN a `coqchk` failure due to a missing dependency WHEN the failure is presented THEN the response identifies the missing dependency and suggests compiling or checking it first
- GIVEN a `coqchk` timeout WHEN the failure is presented THEN the response indicates the timeout was reached and suggests increasing the timeout or checking fewer files

**Traces to:** RC-P0-3, RC-P0-4, RC-P2-1

### Detect Stale Compiled Files

**Priority:** P1
**Stability:** Stable

- GIVEN a `.vo` file whose modification time is older than its corresponding `.v` file WHEN checking is invoked THEN a warning is returned indicating the compiled file may be stale
- GIVEN stale files detected during a project-wide check WHEN the summary is returned THEN the stale files are listed separately from pass/fail results
- GIVEN a stale file warning WHEN it is presented THEN the response suggests recompiling the source file before checking

**Traces to:** RC-P1-2

### CI-Friendly Output

**Priority:** P1
**Stability:** Draft

- GIVEN a project-wide check invoked in a CI context WHEN it completes THEN the result includes a structured JSON payload with per-file status, overall pass/fail, and timing information
- GIVEN a project-wide check where any file fails WHEN the result is inspected programmatically THEN the overall status is "fail" and the failing files are enumerable
- GIVEN a project-wide check where all files pass WHEN the result is inspected programmatically THEN the overall status is "pass"

**Traces to:** RC-P1-4
