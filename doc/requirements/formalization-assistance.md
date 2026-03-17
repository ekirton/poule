# Formalization Assistance — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) §4 for ecosystem context.

## 1. Business Goals

The gap between mathematical intuition and formal proof is the single largest barrier to Coq adoption. Mathematicians, students, and even experienced developers routinely know *what* they want to prove but struggle to express it in Coq's type theory. They know a result "should follow from compactness" but cannot locate the right library lemma, do not know how to state the formal version, and cannot navigate the proof interaction loop to build the proof term. Each of these steps — natural language to formal statement, lemma discovery, interactive proof construction — is individually difficult. Together, they make formalization feel like translating between two foreign languages at once.

No existing IDE can address this because the workflow is inherently multi-step and requires natural language reasoning at every stage: interpreting the user's mathematical intent, searching for relevant existing results, proposing a formal statement, and then guiding an interactive proof session where each step depends on the evolving proof state. This is not a feature that can be added to a menu — it is a guided dialogue.

This initiative implements a `/formalize` slash command for Claude Code that orchestrates the MCP tools from §3 of the ecosystem opportunities document as building blocks. The user describes a theorem in plain language; Claude searches for relevant existing lemmas, suggests a formal Coq statement, and helps build the proof interactively. The slash command is the script; the MCP tools (vernacular introspection, semantic lemma search, proof interaction, hammer automation) are the primitives.

**Success metrics:**
- ≥ 70% of formal statements suggested by Claude are accepted by the user (with at most minor edits) on the first attempt
- ≥ 80% of `/formalize` sessions that reach the proof-building phase produce a type-correct proof within the session
- Users report that `/formalize` reduces time-to-first-formal-statement by ≥ 50% compared to manual formalization (survey-based)
- ≥ 90% of lemma search results surfaced during a `/formalize` session are judged relevant by the user
- The `/formalize` workflow is usable by someone with no prior Coq experience, given a correct mathematical description of the desired theorem

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq newcomers and students | Bridge the gap between textbook mathematics and formal proof; get started without memorizing Coq syntax or library structure | Primary |
| Mathematicians exploring formalization | Translate known results into Coq without becoming Coq experts; discover what is already formalized | Primary |
| Experienced Coq developers | Accelerate routine formalization tasks; discover relevant lemmas faster; reduce boilerplate in statement construction | Secondary |
| Formalization teams | Onboard new contributors who have mathematical expertise but limited Coq experience | Secondary |
| Educators | Demonstrate the formalization process interactively; create exercises that start from natural language | Tertiary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- Lean's Mathlib has extensive search tools (`exact?`, `apply?`, `rw?`) that help users find relevant lemmas, but they require a partially constructed proof state — the user must already have a formal statement.
- LeanChat and LLM-based Lean assistants can suggest tactic steps, but they do not offer an end-to-end natural-language-to-formal-proof workflow.
- No Lean tool combines natural language understanding, lemma search, statement suggestion, and interactive proof building in a single guided dialogue.

**Coq ecosystem (current state):**
- `Search` and `SearchPattern` commands exist but require knowledge of Coq's query syntax and return unranked, often overwhelming result sets.
- CoqHammer can discharge goals automatically but cannot help formulate statements or guide proof construction.
- No existing Coq tool accepts natural language descriptions and produces formal statements.
- The Coq community has long identified "where do I start?" as a top barrier for newcomers.

**Key insight:** Every existing tool assumes the user already has a formal statement. The formalization assistance workflow addresses the step *before* all other tools become useful — getting from mathematical intent to a well-typed Coq statement with the right imports and dependencies. This is the highest-leverage intervention point for adoption.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RFA-P0-1 | Accept a natural language description of a theorem, lemma, or definition and produce a candidate formal Coq statement |
| RFA-P0-2 | Search existing Coq libraries and the current project for lemmas relevant to the user's described theorem, and present the results with explanations of relevance |
| RFA-P0-3 | When the user accepts (or edits) a suggested formal statement, initiate an interactive proof session for that statement |
| RFA-P0-4 | During the proof session, suggest tactic steps based on the current proof state and the mathematical intent described by the user |
| RFA-P0-5 | Verify that any suggested formal statement is syntactically valid and well-typed by checking it against the active Coq environment |
| RFA-P0-6 | Present lemma search results in a way that explains *why* each result is relevant to the user's intent, not just listing names and types |
| RFA-P0-7 | Implement as a Claude Code slash command (`/formalize`) that orchestrates existing MCP tools, not as a new MCP tool |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RFA-P1-1 | When the suggested formal statement does not match the user's intent, support an iterative refinement dialogue where the user describes corrections in natural language |
| RFA-P1-2 | Suggest relevant `Require Import` statements needed for the formalization, based on the libraries where relevant lemmas were found |
| RFA-P1-3 | During proof building, attempt automated proof strategies (hammer, auto, omega, etc.) before falling back to manual tactic suggestions |
| RFA-P1-4 | When a proof step fails, explain the failure in terms of the mathematical content, not just the Coq error message |
| RFA-P1-5 | Support partial formalization: the user describes part of a theorem and Claude helps complete the rest based on context and conventions |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RFA-P2-1 | Suggest alternative formalizations when there are multiple reasonable ways to state the same mathematical result (e.g., classical vs constructive, bundled vs unbundled) |
| RFA-P2-2 | Learn from the user's project conventions (naming schemes, proof style, preferred libraries) to make suggestions that fit the codebase |
| RFA-P2-3 | Generate documentation comments for the formalized statement explaining the correspondence between the natural language description and the formal version |
| RFA-P2-4 | When relevant, suggest generalizations of the user's stated theorem based on patterns found in existing libraries |

---

## 5. Scope Boundaries

**In scope:**
- Natural language input describing a theorem, lemma, or definition
- Lemma and definition search across loaded libraries and the current project
- Formal statement suggestion with type-checking validation
- Iterative refinement of the formal statement through dialogue
- Interactive proof building with tactic suggestions
- Automated proving attempts during the proof-building phase
- Import/dependency suggestions
- Implementation as a Claude Code slash command composing existing MCP tools

**Out of scope:**
- Training or fine-tuning ML models for formalization
- Modifications to the Coq kernel or type checker
- Batch formalization of entire papers or textbooks (single-theorem focus)
- Formal verification of the correspondence between natural language and formal statement (the user is the arbiter of correctness)
- IDE plugin development
- Creation of new Coq tactics or automation procedures
- Proof visualization (covered by the Proof Visualization Widgets initiative)
