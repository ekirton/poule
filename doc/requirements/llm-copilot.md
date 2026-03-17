# LLM Copilot for Coq/Rocq — Product Requirements Document

Cross-reference: see [coq-ecosystem-gaps.md](coq-ecosystem-gaps.md) for ecosystem context and initiative sequencing.

Lineage: Phase 4 initiative. Depends on Semantic Lemma Search (Phase 1), Proof Interaction Protocol (Phase 2), and Training Data Extraction (Phase 3). Consumes retrieval infrastructure from Semantic Lemma Search, proof state observation and tactic submission from the Proof Interaction Protocol, and few-shot examples from Training Data Extraction.

## 1. Business Goals

Coq/Rocq users lack an integrated AI proof assistant. Lean has LeanCopilot with tactic suggestion, proof search, and premise selection — all verified in-editor. Coq has CoqPilot, an early-stage VS Code plugin that collects `admit` holes and generates candidate completions, but it lacks tight integration with the proof state, has no premise retrieval, and does not verify suggestions before presenting them.

This initiative delivers an LLM-powered copilot for Coq/Rocq, exposed as MCP tools for Claude Code. The copilot observes the current proof state, retrieves relevant premises from indexed libraries, generates tactic suggestions and multi-step proof sketches, and verifies all suggestions against Coq before presenting them. It combines the retrieval infrastructure from Semantic Lemma Search with the proof interaction capabilities from Phase 2 to provide an end-to-end proof assistance experience.

**Success metrics:**
- ≥ 30% of suggested tactics are accepted by Coq on the first attempt (verified before presentation)
- ≥ 15% of proof search attempts produce a complete, Coq-verified proof for standard library–level goals
- Tactic suggestion latency (from request to verified suggestions presented) < 5 seconds for single-tactic suggestions
- Proof search latency < 30 seconds per attempt for proofs up to 10 tactic steps
- Users report measurable reduction in time spent on routine proof obligations in qualitative evaluation

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using Claude Code | Tactic suggestions and proof sketches during interactive proof development, verified before presentation | Primary |
| Coq developers working on routine proofs | Automated discharge of simple proof obligations (arithmetic, rewriting, case analysis) | Primary |
| Coq newcomers and students | Guided proof exploration with explanations of suggested tactics | Secondary |
| AI researchers | Evaluation platform for Coq-focused tactic prediction and proof synthesis models | Tertiary |

---

## 3. Competitive Context

Cross-references:
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)
- [Premise selection and retrieval survey](../background/coq-premise-retrieval.md)
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)

**Lean ecosystem (comparative baseline):**
- LeanCopilot: `suggest_tactics`, `search_proof`, `select_premises` — all verified in-editor before presentation. Integrates with multiple LLM backends.
- llmstep: Lightweight LLM tactic suggestion for Lean 4 with in-editor verification.
- AlphaProof, Seed-Prover, DeepSeek-Prover, BFS-Prover: Frontier proof search systems (all Lean-only).

**Coq ecosystem (current state):**
- CoqPilot: VS Code plugin, collects `admit` holes, generates completions via LLMs and non-ML methods, checks candidates against Coq. Early-stage, limited scope.
- CoqHammer + `sauto`: Mature automation but no LLM integration, no neural premise selection.
- Tactician (Graph2Tac): GNN-based tactic prediction with online learning. Architecturally sophisticated but niche adoption.
- AutoRocq: LLM agent for autonomous proving. Research prototype.

**Key research findings informing design:**
- Explicit retrieval provides ~12pp improvement even for large LLMs (REAL-Prover), motivating tight integration with Semantic Lemma Search
- Best-first search with a strong policy model outperforms MCTS without requiring a separate value model (BFS-Prover)
- Neuro-symbolic hybridization (LLM tactics interleaved with symbolic solvers) is the dominant pattern in frontier systems
- Diversity-aware tactic selection avoids near-duplicate exploration (CARTS, 3D-Prover)
- Retrieval from curated libraries is more valuable than generating new lemmas (LEGO-Prover)
- CoqHammer + Tactician combined solve 56.7% of theorems, showing strong complementarity between symbolic automation and learned tactics

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R4-P0-1 | Given a proof state (goals, hypotheses, local context), generate a ranked list of candidate next tactics |
| R4-P0-2 | Verify each candidate tactic against Coq via the Proof Interaction Protocol before presenting it to the user |
| R4-P0-3 | Retrieve relevant premises from indexed libraries via Semantic Lemma Search and include them as context for tactic generation |
| R4-P0-4 | Expose tactic suggestion as an MCP tool compatible with Claude Code (stdio transport) |
| R4-P0-5 | Given a proof state, attempt a multi-step proof search that produces a complete, Coq-verified proof |
| R4-P0-6 | Expose proof search as an MCP tool compatible with Claude Code (stdio transport) |
| R4-P0-7 | Return the verified proof script when proof search succeeds, including each tactic and its effect on the proof state |
| R4-P0-8 | Report structured failure information when proof search does not find a complete proof, including the best partial progress achieved |
| R4-P0-9 | Single-tactic suggestion latency < 5 seconds from request to verified suggestions presented |
| R4-P0-10 | Proof search timeout configurable by the user, with a default of 30 seconds |
| R4-P0-11 | All suggested tactics and proof scripts must be verified against Coq before presentation — never present unverified suggestions |
| R4-P0-12 | Operate without a GPU; use hosted LLM APIs (Claude) for generation |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R4-P1-1 | Use few-shot examples from extracted training data to improve tactic suggestion quality for the current proof context |
| R4-P1-2 | Support sketch-then-prove: generate a natural-language proof plan, convert it to a formal sketch with intermediate lemmas as admit stubs, then attempt to fill each stub independently |
| R4-P1-3 | Interleave LLM-generated tactics with symbolic automation (CoqHammer, `auto`, `omega`) to combine LLM strategy with solver precision |
| R4-P1-4 | Apply diversity-aware tactic selection during proof search to avoid exploring near-duplicate tactic candidates |
| R4-P1-5 | Provide a premise selection tool that, given a proof goal, returns a ranked list of potentially useful lemmas from indexed libraries |
| R4-P1-6 | When suggesting tactics, include a brief natural-language explanation of what each tactic does and why it may help |
| R4-P1-7 | Support configurable search depth and breadth limits for proof search |
| R4-P1-8 | Cache proof states during search to avoid redundant Coq interactions for previously explored states |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R4-P2-1 | Support pluggable LLM backends beyond Claude (e.g., open-source models for offline use) |
| R4-P2-2 | Provide a fill-admits mode that scans a proof script for `admit` calls and attempts to discharge each one |
| R4-P2-3 | Learn from user acceptance and rejection of suggestions within a session to improve subsequent suggestions |
| R4-P2-4 | Support subgoal decomposition: break complex goals into sequences of intermediate subgoals and attempt each independently |
| R4-P2-5 | Estimate proof difficulty and remaining proof distance to guide search allocation and user expectations |

---

## 5. Scope Boundaries

**In scope:**
- LLM-powered tactic suggestion with Coq verification for Coq/Rocq proofs
- Multi-step proof search with verification
- Premise retrieval from Semantic Lemma Search to augment generation context
- MCP server deployment for Claude Code integration (stdio transport)
- Integration with the Proof Interaction Protocol for proof state observation and tactic submission
- Few-shot prompting using extracted training data

**Out of scope:**
- Training or fine-tuning ML models (this initiative consumes models, it does not train them)
- IDE plugin development (VS Code, Emacs, etc.) — copilot is accessed via Claude Code's MCP integration
- Replacement of CoqHammer or Tactician — copilot complements existing automation
- Real-time continuous suggestion (copilot is invoked on demand, not streaming suggestions continuously)
- Custom model hosting infrastructure
- Proof visualization (covered by Proof Visualization Widgets initiative)
