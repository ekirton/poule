# Educational Content Retrieval — Product Requirements Document

Cross-reference: see [proof-explanation.md](proof-explanation.md) for the `/explain-proof` slash command that benefits from educational context retrieval.
Cross-reference: see [semantic-lemma-search.md](semantic-lemma-search.md) for the existing retrieval infrastructure in poule-MCP.

## 1. Business Goals

Coq/Rocq has a steep learning curve. Students and self-learners working through proofs need more than tactic documentation — they need pedagogical explanations that connect formal concepts to mathematical intuition. The *Software Foundations* series by Benjamin C. Pierce et al. is the canonical open-source textbook for learning Coq, covering seven volumes from basic functional programming through separation logic and verified C. Today, students must leave their proof environment to consult the textbook, breaking flow and losing context.

This initiative makes the full Software Foundations corpus searchable from within Poule via a `/textbook` slash command. A locally installed vector database, populated from the SF HTML books and bundled in the Docker container, powers retrieval-augmented generation (RAG) for both user-facing educational queries and Claude's own explanations. When Claude explains a proof, suggests a tactic, or assists with formalization, it can ground its response in the authoritative pedagogical source rather than relying solely on training data. The SF HTML books are also made available in the user's persistent home directory so they can open chapters directly in their browser.

**Success metrics:**
- Users can retrieve relevant SF passages for any core Coq concept (induction, rewriting, tactics, data types, logic) via `/textbook`
- Retrieved passages include source attribution (volume, chapter, section) and a local file path so users can read further in their browser
- Claude's proof explanations (via `/explain-proof`) include brief educational annotations with SF citations, with an invitation to use `/textbook` for more detail
- Retrieval latency < 2 seconds for queries against the full SF corpus (~150 HTML pages across 7 volumes)
- >80% recall@3 at chapter level on a hand-curated evaluation set of common Coq learning questions

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Students in formal methods courses | Look up explanations of Coq concepts and tactics while working on proofs, without leaving Poule | Primary |
| Self-learners working through Software Foundations | Search across all seven volumes by concept rather than reading linearly; open chapters in a browser for extended reading | Primary |
| Educators and course instructors | Find canonical explanations and exercises to reference in teaching materials | Primary |
| Claude (as an agent) | Retrieve authoritative pedagogical context to improve the quality and citation accuracy of proof explanations, tactic suggestions, and formalization assistance | Secondary |

---

## 3. Competitive Context

**Google NotebookLM:**
Students can upload the SF PDFs/HTML into NotebookLM and query them conversationally. However, NotebookLM is a general-purpose tool with no Coq awareness — it cannot connect retrieved passages to the user's current proof state, invoke Coq tooling, or compose with proof explanation workflows. Poule integrates retrieval directly with proof interaction tools, making the educational context actionable rather than merely readable.

**ChatGPT / Claude web chat with file upload:**
Similar to NotebookLM — users can upload SF content and ask questions. Lacks integration with Coq proof state, MCP tools, or the user's project context.

**IDE documentation hovers (CoqIDE, Proof General):**
Show type signatures and brief docstrings for tactics and lemmas. No pedagogical explanation, no worked examples, no connection to textbook material.

**Key differentiator:** No existing tool combines Coq-aware proof interaction with pedagogical content retrieval. Poule already has the proof interaction layer; this initiative adds the educational content layer.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RTB-P0-1 | Populate a local vector database from the HTML content of all seven Software Foundations volumes (LF, PLF, QC, SECF, SLF, VC, VFA) |
| RTB-P0-2 | Bundle the populated vector database in the Poule Docker container so it is available offline without additional setup |
| RTB-P0-3 | Chunk HTML content at section-level boundaries with a target of ~1000 tokens per chunk, preserving pedagogical coherence |
| RTB-P0-4 | Store source attribution metadata with each chunk: volume abbreviation, chapter name, chapter filename, section title, section path, and anchor ID for deep linking |
| RTB-P0-5 | Expose a `/textbook` slash command that accepts a natural-language query and returns relevant SF passages with source attribution and a local file path for browser viewing |
| RTB-P0-6 | Expose an `education_context` MCP tool in the poule-MCP server that Claude can call to retrieve educational context during proof explanation, error diagnosis, or other workflows |
| RTB-P0-7 | Retrieval latency under 2 seconds for the full SF corpus |
| RTB-P0-8 | No external API keys, GPU, or network access required for retrieval (the vector database and embedding model must run locally) |
| RTB-P0-9 | Make the SF HTML books available in the user's persistent home directory (`~/software-foundations/`) so users can open chapters in their host browser |
| RTB-P0-10 | Existing `/explain-proof` and `/explain-error` commands always call the education RAG but keep annotations brief (1-2 sentences + citation), telling the user they can use `/textbook` for more detail |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RTB-P1-1 | Rank results by relevance and present the top-k passages (configurable, default 5) with clear source citations |
| RTB-P1-2 | Support filtering by volume (e.g., "search only in Logical Foundations") |
| RTB-P1-3 | Preserve Coq code blocks within retrieved passages so that examples remain intact and runnable |
| RTB-P1-4 | When Claude invokes the retrieval tool during `/explain-proof`, include the retrieved passage inline in the explanation with a citation |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RTB-P2-1 | Support keyword and exact-phrase search as a fallback alongside semantic search |
| RTB-P2-2 | Display a "related chapters" list alongside retrieved passages to encourage further reading |
| RTB-P2-3 | Allow users to query by tactic name (e.g., "induction") and retrieve the SF sections that introduce and explain that tactic |

---

## 5. Scope Boundaries

**In scope:**
- RAG pipeline over the seven Software Foundations volumes (MIT-licensed HTML)
- Local vector database bundled in the Docker container
- `/textbook` slash command for user-facing queries
- MCP tool for Claude-facing retrieval during other workflows
- SF HTML books accessible in the user's persistent home directory for browser viewing
- Brief educational annotations in `/explain-proof` and `/explain-error` output
- Offline operation with no external dependencies
- Hand-curated evaluation set for retrieval quality measurement

**Out of scope:**
- Loading additional books or corpora into the vector database (future initiative)
- Generating new educational content or exercises
- Interactive tutoring, quizzes, or graded assignments
- Modifications to the Software Foundations source material
- Web-based or IDE-based interfaces for the educational content
- Configurable verbosity settings for educational annotations (always brief with option for more via `/textbook`)
