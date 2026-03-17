# Proof Repair on Version Upgrade — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) section 4 (Agentic Workflows) for ecosystem context and initiative sequencing.

## 1. Business Goals

Upgrading Coq versions is one of the most painful recurring tasks in the Coq/Rocq ecosystem. Between major versions, lemmas are renamed, tactics are deprecated or removed, type inference behavior changes, and implicit argument defaults shift. A single version bump can break dozens to hundreds of proofs across a project, each requiring manual diagnosis and repair. Developers report spending days to weeks on version upgrades for large formalizations, and some projects simply stop upgrading — accumulating technical debt that eventually makes the codebase unmaintainable.

This initiative delivers a `/proof-repair` slash command for Claude Code that automates the core upgrade repair loop: build the project, parse errors, search for renamed lemmas and replacement tactics, attempt automated fixes (including hammer), and retry — iterating until all proofs compile or a human-actionable report is produced. The workflow orchestrates MCP tools from the Poule toolchain as building blocks, chaining build system integration, semantic lemma search, vernacular introspection, hammer automation, and proof interaction in a feedback loop that no traditional IDE can replicate.

**Success metrics:**
- Automatically resolve at least 60% of version-upgrade proof breakages without human intervention on a representative set of open-source Coq projects
- Reduce total developer time spent on version upgrades by at least 50% compared to manual repair, as measured by timed trials on projects of 5,000+ lines
- Produce an actionable diagnostic report for every proof that cannot be automatically repaired, including the specific error, attempted fixes, and suggested next steps
- Complete the full repair loop (build, diagnose, attempt fixes, report) for a 10,000-line project within 30 minutes of wall-clock time

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers upgrading Coq versions | Automated repair of broken proofs after a version bump, minimizing manual effort | Primary |
| Formalization teams maintaining large libraries | Bulk repair across hundreds of files with progress tracking and a summary of remaining issues | Primary |
| Open-source Coq project maintainers | Keeping projects compatible with the latest Coq release to avoid contributor attrition | Primary |
| Coq newcomers inheriting older projects | Getting a legacy project to compile on a current Coq version without deep expertise in migration patterns | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [Coq AI theorem proving background](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- Lean's toolchain versioning is tightly coupled with its package manager (Lake). Breaking changes are documented with automated migration scripts for common renames. The `lean4-cli` tooling and Lean's backward-compatibility policy reduce the frequency and severity of breakages. No equivalent of an automated proof repair agent exists, but the problem is less severe due to deliberate toolchain stability.

**Coq ecosystem (current state):**
- The Coq changelog documents breaking changes, but migration is entirely manual. Developers must read the changelog, identify relevant entries, grep their codebase for affected names, and fix each proof individually.
- No automated tool exists to attempt bulk proof repair after a version upgrade. The closest tooling is `coq-prover/coq`'s compatibility scripts, which handle simple renames but do not address broken proof scripts.
- CoqHammer can sometimes re-prove goals that broke due to minor changes, but users must manually identify each broken goal and invoke hammer — there is no orchestration layer.
- Community-maintained migration guides (e.g., for the Coq-to-Rocq transition) provide rename maps but require manual application.

**Gap:** No tool in any proof assistant ecosystem provides an automated, agentic feedback loop for version-upgrade proof repair. The closest analogs are language-level migration tools (e.g., Python 2-to-3, Rust edition migration) that handle syntactic transforms but not semantic proof repair. This initiative fills a gap that is unique to the formal verification domain.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPR-P0-1 | Build the project and capture the complete set of compilation errors, associating each error with its source file, line number, and proof context |
| RPR-P0-2 | Parse each compilation error to classify it by category: renamed lemma, removed tactic, changed type signature, universe inconsistency, implicit argument change, or unclassified |
| RPR-P0-3 | For renamed-lemma errors, search for the replacement lemma by querying semantic lemma search with the old name, type signature, and containing module |
| RPR-P0-4 | For deprecated-tactic errors, consult a knowledge base of known tactic migrations (e.g., `omega` to `lia`, `intuition` parameter changes) and apply the corresponding replacement |
| RPR-P0-5 | For proof goals that remain after applying targeted fixes, attempt automated proving via CoqHammer (`hammer`, `sauto`, `qauto`) as a fallback strategy |
| RPR-P0-6 | After each batch of fix attempts, rebuild the project and re-parse errors to determine which fixes succeeded and which proofs remain broken |
| RPR-P0-7 | Iterate the build-diagnose-fix-rebuild loop until either all proofs compile or no further progress is made in a full iteration |
| RPR-P0-8 | Produce a structured report at completion listing: proofs repaired automatically (with the applied fix), proofs still broken (with the error and all attempted fixes), and an overall success rate |
| RPR-P0-9 | Implement the workflow as a Claude Code slash command (`/proof-repair`) that orchestrates MCP tools from the Poule toolchain |
| RPR-P0-10 | Accept the target Coq version as input and use version-specific migration knowledge when diagnosing errors |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPR-P1-1 | Maintain a knowledge base of known migration patterns across Coq version pairs (e.g., 8.18 to 8.19, 8.19 to 9.0) including renamed lemmas, removed tactics, and changed defaults |
| RPR-P1-2 | For changed implicit argument errors, inspect the old and new type signatures and adjust call sites to supply explicit arguments where needed |
| RPR-P1-3 | Prioritize repair attempts by dependency order — fix upstream files first so downstream errors that are cascading consequences resolve automatically on rebuild |
| RPR-P1-4 | Support partial repair: allow the user to specify a subset of files or directories to repair rather than the entire project |
| RPR-P1-5 | Display real-time progress during the repair loop, including the current file being processed, the number of proofs repaired so far, and the number remaining |
| RPR-P1-6 | For each automatically repaired proof, present the diff to the user for review before committing the change |
| RPR-P1-7 | When a renamed lemma is found, verify that the replacement has a compatible type signature before applying the substitution |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPR-P2-1 | Learn from successful repairs within a session: if the same rename pattern appears in multiple files, apply it proactively without re-searching |
| RPR-P2-2 | Support multi-version migration (e.g., 8.16 to 9.0) by chaining migration knowledge across intermediate version pairs |
| RPR-P2-3 | Generate a machine-readable migration map from the repairs applied in a session, exportable for use by other developers on the same project |
| RPR-P2-4 | Integrate with version control to create one commit per repaired file or per repair category, with descriptive commit messages |

---

## 5. Scope Boundaries

**In scope:**
- Automated detection and classification of version-upgrade proof breakages via build error parsing
- Automated repair attempts for renamed lemmas, deprecated tactics, and known migration patterns
- Fallback to CoqHammer for goals that resist targeted fixes
- Iterative feedback loop: build, diagnose, fix, rebuild, repeat
- Structured reporting of repair outcomes (successes, failures, attempted strategies)
- Implementation as a Claude Code slash command orchestrating existing MCP tools
- Support for standard Coq build systems (`coq_makefile`, Dune)

**Out of scope:**
- Fixing errors unrelated to version upgrades (e.g., logic errors in new proof developments)
- Modifying the Coq compiler or its error reporting
- Providing a standalone tool outside the Claude Code environment
- Guaranteeing correctness of repaired proofs beyond successful compilation (the user must review changes)
- Supporting alternative proof assistants (Lean, Isabelle, Agda)
- Handling changes to OCaml plugin APIs or Coq plugin compatibility
- Automating the opam switch creation or Coq installation process itself
