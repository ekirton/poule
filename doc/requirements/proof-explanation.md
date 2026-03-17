# Proof Explanation and Teaching — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context (section 4, agentic workflows).

## 1. Business Goals

Coq proofs are notoriously opaque. A proof script is a sequence of tactic invocations that transform an invisible proof state — the reader sees the commands but not the intermediate goals, hypotheses, or the mathematical reasoning that motivates each step. This makes Coq proofs difficult to learn from, difficult to teach with, and difficult to review. Students encounter a wall of tactics with no explanation of what each one accomplishes or why it was chosen. Educators must manually annotate proof scripts with comments, a process that is tedious and quickly becomes stale as proofs evolve.

This initiative provides a `/explain-proof` slash command that steps through a Coq proof interactively, explains each tactic in natural language, shows how the proof state evolves at each step, and connects the formal manipulation to the underlying mathematical intuition. By orchestrating proof interaction, proof state inspection, and contextual explanation, the command transforms an opaque tactic script into a readable, pedagogically useful narrative.

Because this is an agentic workflow — requiring multi-step proof interaction with LLM reasoning between steps — it is implemented as a Claude Code slash command that composes MCP tools from the Poule tool suite as building blocks.

**Success metrics:**
- Users can invoke `/explain-proof` on any Coq proof and receive a step-by-step explanation within a reasonable time (< 30 seconds for proofs of 20 tactics or fewer)
- Each tactic explanation includes: what the tactic does in general, what it accomplishes in this specific context, and how the proof state changed
- >= 80% of student and newcomer users report that the explanation made the proof easier to understand
- Educators can use the generated explanations as a starting point for teaching materials with minimal editing
- The command handles proofs of varying complexity, from simple introductions to multi-step rewrites and automation tactics

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq newcomers and self-learners | Understand what each tactic does and why it is used, without needing to mentally simulate the proof state | Primary |
| Educators and course instructors | Generate readable, annotated proof walkthroughs for lectures, textbooks, and assignments | Primary |
| Students in formal methods courses | Step through assigned proofs to build intuition for tactic-based proving and understand how goals evolve | Primary |
| Experienced developers reviewing unfamiliar proofs | Quickly understand the structure and intent of a proof written by someone else, without replaying it in an IDE | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)

**Lean ecosystem (comparative baseline):**
- Lean 4's infoview shows goal state at cursor position, but provides no narrative explanation of tactics or mathematical intuition. The user must interpret raw goal states themselves.
- No existing Lean tool generates step-by-step natural-language proof explanations.

**Coq ecosystem (current state):**
- CoqIDE and Proof General (Emacs) allow users to step through proofs and inspect the proof state at each point. However, the user must interpret the raw proof state, understand what each tactic does, and infer the mathematical reasoning — exactly the skills that newcomers lack.
- jsCoq and similar web-based tools provide proof stepping in a browser, but offer no explanation layer.
- Alectryon generates static proof state annotations alongside source code, producing readable documents. It shows the proof state but does not explain tactics or provide mathematical intuition.
- No existing tool combines proof stepping with natural-language explanation and mathematical context.

**Key insight:** The proof state is available through existing tools, but the explanation layer — translating formal state changes into human-understandable reasoning — requires an LLM. This is a capability that no IDE or static tool can replicate, and it directly addresses the most common complaint from Coq newcomers: "I can see the proof compiles, but I don't understand why it works."

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPE-P0-1 | Step through a Coq proof tactic by tactic, capturing the proof state before and after each step |
| RPE-P0-2 | For each tactic, provide a natural-language explanation of what the tactic does in general and what it accomplishes in the current proof context |
| RPE-P0-3 | Show the proof state evolution at each step: display the current goal(s) and hypotheses before and after the tactic fires |
| RPE-P0-4 | Handle compound tactics (e.g., semicolons, `try`, `repeat`) by explaining the composite behavior and, where possible, breaking down sub-steps |
| RPE-P0-5 | Accept a proof identified by theorem or lemma name, or by file location, and locate it in the source for stepping |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPE-P1-1 | Provide mathematical intuition alongside the formal explanation: connect each tactic to the proof strategy it implements (e.g., "this applies induction on the natural number n, creating a base case and an inductive step") |
| RPE-P1-2 | Support adjustable detail levels: brief mode (one-line summary per tactic), standard mode (explanation with proof state), and verbose mode (full mathematical context and alternative approaches) |
| RPE-P1-3 | When a tactic invokes automation (e.g., `auto`, `omega`, `lia`), explain what the automation found and why it succeeded |
| RPE-P1-4 | Provide a summary at the end of the proof walkthrough: overall proof strategy, key lemmas used, and the logical structure of the argument |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPE-P2-1 | Suggest alternative tactics that could achieve the same step, helping users understand that proofs are not unique |
| RPE-P2-2 | Generate a structured document (e.g., markdown) from the explanation, suitable for inclusion in course materials or documentation |
| RPE-P2-3 | Highlight common proof patterns (e.g., "this is a standard induction-then-rewrite pattern") to help users recognize recurring strategies |
| RPE-P2-4 | Support explaining proofs that use Ltac2 or custom tactic notations by expanding them to their underlying behavior |

---

## 5. Scope Boundaries

**In scope:**
- Claude Code slash command (`/explain-proof`) that orchestrates MCP tools to step through and explain proofs
- Step-by-step tactic explanation with proof state display
- Natural-language descriptions of tactic behavior, both general and context-specific
- Mathematical intuition connecting formal tactics to proof strategies
- Adjustable verbosity levels for different audiences
- Summary of overall proof structure after walkthrough

**Out of scope:**
- Installation or management of Coq (assumed to be available in the user's environment)
- Proof generation or repair (covered by other initiatives)
- Interactive proof tutoring with exercises or quizzes
- Video or animated proof visualization
- IDE plugin development
- Modifications to Coq's proof engine or tactic language
- Translation of proofs between proof assistants
