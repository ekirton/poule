# Proof Style Linting and Refactoring — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) §4 for ecosystem context.

## 1. Business Goals

Large Coq formalizations accumulate stylistic debt over time. Proof scripts written by different contributors use different bullet conventions, rely on tactics deprecated across Coq versions, and contain unnecessarily complex tactic chains that obscure the proof's intent. Style inconsistency makes proofs harder to read, harder to maintain, and more fragile when upgrading Coq versions. Today there is no automated tool that understands both proof structure and stylistic conventions well enough to lint and refactor proof scripts safely.

This initiative delivers a Claude Code slash command (`/proof-lint`) that analyzes proof scripts for style issues and applies safe, automated improvements. The slash command orchestrates MCP tools from §3 — vernacular introspection, proof interaction, tactic documentation — to understand proof structure, detect problems, and verify that refactored proofs still compile. Because the workflow requires multi-step reasoning (parse proof structure, identify issues, propose rewrites, verify correctness), it cannot be expressed as a single MCP tool; it requires the agentic orchestration that a slash command provides.

**Success metrics:**
- Detect ≥ 90% of deprecated tactics listed in the current Coq/Rocq migration guides when scanning a proof development
- Identify bullet style inconsistencies across a project with ≥ 95% precision (no false positives on intentional style variations)
- Tactic chain simplification suggestions compile successfully in ≥ 85% of cases when applied
- Users report that `/proof-lint` reduces manual style review time by ≥ 50% compared to unaided review
- Automated refactoring preserves proof validity in 100% of applied changes (no refactoring is applied that breaks a proof)

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Formalization teams | Enforce consistent proof style across multiple contributors; catch deprecated tactics before they cause upgrade failures | Primary |
| Library maintainers | Clean up accumulated stylistic debt; prepare codebases for Coq version upgrades; ensure proofs follow community conventions | Primary |
| Individual Coq developers | Improve personal proof style; learn idiomatic tactic usage; simplify unnecessarily verbose proof scripts | Secondary |
| Coq newcomers | Learn good proof style by example; understand why certain tactics are preferred over others | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- Lean 4 has a built-in linter framework that checks for common issues (unused variables, deprecated syntax). However, it operates at the syntax level and does not reason about proof style, bullet conventions, or tactic chain complexity. There is no Lean tool that suggests proof refactorings.
- Mathlib has project-specific linting rules enforced through CI, but these are hand-written checks for a single project's conventions, not a general-purpose tool.

**Coq ecosystem (current state):**
- Coq has no built-in proof style linter. The `coq-lint` community project is abandoned and only checked superficial formatting issues.
- Some teams enforce style through code review and contributor guidelines, but this is manual and inconsistent.
- The Coq deprecation mechanism emits warnings for deprecated tactics and notations, but these warnings appear only during compilation and are not aggregated, classified, or actionable.
- No existing tool combines proof structure analysis with stylistic reasoning and safe automated rewriting.

**Key insight:** Proof style linting requires understanding both the syntactic structure of proof scripts and the semantic intent behind tactic choices. An LLM can reason about why a particular tactic chain is unnecessarily complex, propose a simpler alternative, and then verify the alternative through the proof interaction protocol. This combination of stylistic reasoning and verified rewriting is uniquely suited to an agentic workflow.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPL-P0-1 | Detect deprecated tactics in proof scripts by scanning source files and cross-referencing against known deprecation lists for the target Coq version |
| RPL-P0-2 | Detect inconsistent bullet style within a file (e.g., mixing `+`/`-`/`*` bullets with `{}`/`}` braces, or inconsistent bullet nesting depth conventions) |
| RPL-P0-3 | Detect inconsistent bullet style across a project, identifying the dominant convention and flagging deviations |
| RPL-P0-4 | Generate a structured lint report listing all detected issues, classified by category (deprecated tactic, bullet style, tactic complexity) and severity |
| RPL-P0-5 | For each detected issue, provide a human-readable explanation of why it is flagged and what the recommended alternative is |
| RPL-P0-6 | Operate on individual files, directories, or entire projects as specified by the user |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPL-P1-1 | Detect unnecessarily complex tactic chains that can be simplified (e.g., `simpl; reflexivity` where `auto` suffices, or repeated `rewrite` sequences replaceable by a single `autorewrite`) |
| RPL-P1-2 | Suggest concrete replacement text for each detected issue (deprecated tactic replacement, bullet normalization, simplified tactic chain) |
| RPL-P1-3 | Apply suggested refactorings automatically when the user approves, modifying the source file in place |
| RPL-P1-4 | Verify that each applied refactoring preserves proof validity by re-checking the modified proof through the proof interaction protocol before finalizing the change |
| RPL-P1-5 | Support a configuration mechanism for project-specific style preferences (e.g., preferred bullet style, allowed tactic patterns) |
| RPL-P1-6 | Provide a summary view showing issue counts by category and severity across the scanned scope |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPL-P2-1 | Detect proof scripts that could benefit from increased use of automation (e.g., manual case analyses that `decide` or `lia` could handle) |
| RPL-P2-2 | Detect dead code within proof scripts (tactic invocations that have no effect on the proof state) |
| RPL-P2-3 | Track style debt over time, showing improvement or regression between runs |
| RPL-P2-4 | Integrate with CI pipelines to enforce style standards on pull requests |

---

## 5. Scope Boundaries

**In scope:**
- Detection of deprecated tactics, inconsistent bullet styles, and unnecessarily complex tactic chains in Coq proof scripts
- Structured reporting of detected issues with explanations and severity classification
- Suggested replacements for detected issues
- Automated application of approved refactorings with proof validity verification
- File-level, directory-level, and project-level scanning
- Implementation as a Claude Code slash command (`/proof-lint`) that orchestrates existing MCP tools

**Out of scope:**
- Enforcement of formatting rules unrelated to proof structure (indentation, line length, whitespace) — these are better served by a standalone formatter
- Modifications to Coq's built-in deprecation warning system
- Custom tactic development or tactic library creation
- Proof rewriting that changes the mathematical argument (only style-preserving refactorings are in scope)
- IDE plugin development
- Real-time, keystroke-level linting (the slash command operates on saved files, not live editing)
