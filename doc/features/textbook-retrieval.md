# Textbook Content Retrieval

Coq learners frequently need to consult pedagogical material while working on proofs — understanding what a tactic does, why a proof strategy works, or how a concept connects to the broader mathematical picture. The *Software Foundations* series is the canonical open-source textbook for learning Coq, but consulting it today requires leaving the proof environment, breaking flow. Textbook Content Retrieval makes the full Software Foundations corpus searchable from within Poule, providing a `/textbook` slash command for direct queries and an `education_context` MCP tool that Claude uses to enrich proof explanations and error diagnoses with brief, cited educational annotations.

---

## Problem

Students working through Coq proofs hit conceptual walls — they need to understand induction, rewriting, data types, or automation tactics at a pedagogical level, not just as tactic documentation. Today they must leave Poule, open a browser, navigate to the correct Software Foundations volume and chapter, and find the relevant section. By the time they return, they have lost context on the proof they were working on.

Meanwhile, Claude's `/explain-proof` and `/explain-error` commands generate explanations from training data alone. These explanations are generally correct but cannot cite specific textbook passages or point the user to a definitive pedagogical source for further reading. Adding retrieval-augmented generation over Software Foundations gives Claude access to the authoritative teaching material, improving citation accuracy and giving users a path from brief inline annotations to full textbook coverage.

## Solution

### User-Facing Search via `/textbook`

The `/textbook` slash command accepts a natural-language query — "how does induction work in Coq", "what is a proposition", "rewrite tactic" — and returns the most relevant passages from Software Foundations. Each result includes the passage text, any Coq code examples it contains, a source citation (volume, chapter, section), and a local file path so the user can open the full chapter in their browser for extended reading.

Users can optionally filter by volume (e.g., `/textbook --volume lf what is induction`) to narrow results to a specific book.

### Claude-Facing Retrieval via MCP Tool

The `education_context` MCP tool provides the same retrieval capability to Claude during other workflows. When `/explain-proof` finishes walking through a proof, it calls `education_context` with a query describing the proof strategy and appends a brief "Further reading" note — one to two sentences plus a citation and an invitation to use `/textbook` for more detail. The same pattern applies to `/explain-error`: after diagnosing an error, Claude retrieves any relevant SF teaching on the underlying concept and adds a brief "See also" note.

These annotations are always present but deliberately brief. The user is never overwhelmed with textbook content they did not ask for — they are informed that it exists and told how to access it.

### Browsable Textbook HTML

The Software Foundations HTML books are available in the user's persistent home directory at `~/software-foundations/`. When the `/textbook` command returns results, each includes a path like `~/software-foundations/lf/Basics.html#lab26` that the user can open in their host browser. This bridges the gap between quick inline retrieval and full reading — the user can start with a retrieved passage and seamlessly continue reading the chapter.

## Scope

Textbook Content Retrieval provides:

- A `/textbook` slash command for querying Software Foundations by concept, tactic, or topic
- An `education_context` MCP tool for Claude to retrieve educational context during other workflows
- Brief educational annotations in `/explain-proof` and `/explain-error` output
- Browsable SF HTML books in the user's persistent home directory
- Offline operation with no external API keys, GPU, or network access

Textbook Content Retrieval does not provide:

- Loading additional books or corpora beyond Software Foundations
- Generating new educational content or exercises
- Interactive tutoring, quizzes, or graded assignments
- Configurable verbosity for educational annotations — always brief with an option for more via `/textbook`

---

## Acceptance Criteria

### P0 — Must Have

| ID | Criterion | Traces to |
|----|-----------|-----------|
| AC-1 | GIVEN the Poule Docker container is running, WHEN the user invokes `/textbook induction`, THEN relevant passages from Software Foundations about induction are returned with volume, chapter, section citations and a local file path | RTB-P0-5, RTB-P0-4 |
| AC-2 | GIVEN a proof that uses induction, WHEN the user runs `/explain-proof` on it, THEN the explanation includes a brief educational annotation (1-2 sentences) citing a Software Foundations passage and suggesting `/textbook` for more detail | RTB-P0-10 |
| AC-3 | GIVEN a type mismatch error, WHEN the user runs `/explain-error`, THEN the diagnosis includes a brief "See also" note citing relevant SF content if available | RTB-P0-10 |
| AC-4 | GIVEN the container is running with a persistent home mount, WHEN the user checks `~/software-foundations/`, THEN the SF HTML files are present and openable in a browser | RTB-P0-9 |
| AC-5 | GIVEN a query to `education_context`, WHEN the education database is loaded, THEN results are returned in under 2 seconds | RTB-P0-7 |
| AC-6 | GIVEN the container starts without network access, WHEN the user invokes `/textbook`, THEN retrieval works using the bundled vector database and embedding model | RTB-P0-8 |
| AC-7 | GIVEN the full SF corpus is indexed, WHEN evaluated against a hand-curated set of Coq learning questions, THEN chapter-level recall@3 exceeds 80% | RTB-P0-3 |

### P1 — Should Have

| ID | Criterion | Traces to |
|----|-----------|-----------|
| AC-8 | GIVEN a `/textbook` query with `--volume lf`, WHEN results are returned, THEN all results come from the Logical Foundations volume | RTB-P1-2 |
| AC-9 | GIVEN a retrieved passage that contains a Coq code block, WHEN displayed to the user, THEN the code block is preserved intact and formatted as Coq code | RTB-P1-3 |
| AC-10 | GIVEN a `/textbook` query, WHEN multiple relevant passages exist, THEN results are ranked by relevance with the top-5 shown by default | RTB-P1-1 |

### P2 — Nice to Have

| ID | Criterion | Traces to |
|----|-----------|-----------|
| AC-11 | GIVEN a keyword query like "simpl tactic", WHEN semantic search returns no strong matches, THEN FTS5 keyword fallback returns results containing the exact term | RTB-P2-1 |
| AC-12 | GIVEN a tactic name query like `/textbook rewrite`, WHEN results are returned, THEN the SF sections that introduce and explain the `rewrite` tactic appear in the results | RTB-P2-3 |
