# Proof Compression — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) §4 for ecosystem context.

## 1. Business Goals

Working proofs are not finished proofs. In large formalization projects, proof scripts accumulate tactical debt: chains of rewrites that could be a single lemma application, sequences of `intros; destruct; auto` that hammer dispatches in one step, or intermediate assertions that a more direct path renders unnecessary. Long proofs are harder to read, harder to maintain, and more likely to break when upstream definitions change. Proof compression addresses this by taking a working proof and systematically searching for shorter or cleaner alternatives.

This initiative provides a Claude Code slash command (`/compress-proof`) that orchestrates MCP tools from §3 as building blocks. Given a working proof, the command analyzes the proof structure, extracts the goal and context, attempts alternative proof strategies — including hammer tactics, direct lemma application, and tactic chain simplification — and presents ranked alternatives for the user to review. The original proof is always preserved; the user decides whether to adopt a compressed alternative.

The value proposition is threefold: (1) shorter proofs are easier to understand and review, (2) proofs that rely on fewer intermediate steps are more resilient to upstream changes, and (3) exploring alternative strategies often reveals more direct mathematical arguments that deepen the developer's understanding of the formalization.

**Success metrics:**
- For ≥ 40% of proofs submitted to `/compress-proof`, at least one shorter alternative is found
- Compressed alternatives reduce tactic count by ≥ 25% on average compared to the original proof
- 100% of compressed alternatives are verified as valid Coq proofs before being presented to the user
- The original proof is preserved in all cases — no user work is lost
- Time to produce compression results is < 60 seconds for proofs under 30 tactic steps
- ≥ 70% of users who try `/compress-proof` adopt at least one suggested alternative in their first session

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Formalization developers | Reduce proof maintenance burden by shortening and simplifying proof scripts after initial development | Primary |
| Library maintainers | Clean up contributed proofs to meet style and maintainability standards before merging | Primary |
| Formalization teams | Enforce consistent proof quality across a shared codebase | Secondary |
| Educators | Demonstrate that multiple proof strategies exist for the same theorem, helping students develop proof intuition | Secondary |
| Coq newcomers | Learn more idiomatic proof patterns by seeing compressed alternatives to their verbose first attempts | Tertiary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- No equivalent tool exists. Lean's `simp?` and `exact?` suggest single-tactic replacements but do not analyze and compress entire proof scripts.
- Lean's code actions provide local tactic suggestions but cannot orchestrate multi-step compression across a full proof.

**Coq ecosystem (current state):**
- CoqHammer can sometimes replace multi-step proofs with a single `hammer` call, but the user must manually identify which proofs to attempt and manually compare results.
- `auto`, `eauto`, and `firstorder` can sometimes replace tactic chains, but knowing when to try them and with what hints requires expertise.
- No existing tool takes a complete working proof and systematically searches for shorter alternatives.
- Manual proof compression is a common practice in mature formalizations (e.g., MathComp) but is entirely manual and time-consuming.

**Key insight:** The individual tools for finding shorter proofs already exist — hammer, lemma search, tactic simplification. What does not exist is the orchestration layer that combines them into a systematic compression workflow. This is precisely the kind of multi-step, reasoning-intensive operation that an agentic slash command can provide and no IDE can replicate.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPC-P0-1 | Accept a working proof (identified by theorem name or proof script location) and verify that it currently compiles before attempting compression |
| RPC-P0-2 | Extract the proof goal and context from the active proof state at the start of the proof |
| RPC-P0-3 | Attempt hammer-based compression: try `hammer`, `sauto`, and `qauto` as single-tactic replacements for the entire proof |
| RPC-P0-4 | Attempt lemma-search-based compression: search for direct lemmas that close the goal without the intermediate steps in the original proof |
| RPC-P0-5 | Verify that every candidate alternative proof is accepted by Coq before presenting it to the user |
| RPC-P0-6 | Preserve the original proof — never overwrite or delete the user's working proof without explicit user consent |
| RPC-P0-7 | Present compression results with a clear comparison: original proof length versus alternative proof length, and the alternative proof script |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPC-P1-1 | Attempt tactic chain simplification: identify sequences of tactics that can be collapsed into fewer steps (e.g., `intros x; intros y` to `intros x y`) |
| RPC-P1-2 | Rank alternative proofs by multiple criteria: tactic count, estimated readability, and resilience to upstream changes |
| RPC-P1-3 | When multiple alternatives are found, present them in ranked order with brief explanations of the strategy used |
| RPC-P1-4 | Support compressing a single proof step or subproof, not only entire proofs |
| RPC-P1-5 | Allow the user to select an alternative and apply it to the source file in place of the original proof |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPC-P2-1 | Batch mode: compress all proofs in a file or module, producing a summary report of compression opportunities |
| RPC-P2-2 | Learn from user choices — track which compression strategies are most frequently adopted to prioritize them in future runs |
| RPC-P2-3 | Integrate with proof style linting to prefer alternatives that also satisfy project style conventions |
| RPC-P2-4 | Report when a proof cannot be compressed, with an explanation of why (e.g., each tactic step is already minimal) |

---

## 5. Scope Boundaries

**In scope:**
- Claude Code slash command (`/compress-proof`) that orchestrates existing MCP tools
- Proof analysis: extracting the goal, context, and structure of a working proof
- Alternative strategy exploration: hammer tactics, lemma search, tactic chain simplification
- Verification of all candidate alternatives against the Coq kernel
- Comparison and ranking of alternatives against the original proof
- Safe replacement with user consent
- Single-proof and sub-proof granularity

**Out of scope:**
- Modifications to any underlying MCP tools (hammer, proof interaction, lemma search)
- Proof synthesis for unproven goals (covered by the Proof Search & Automation initiative)
- Proof style linting beyond what informs compression ranking (covered by the Proof Style Linting initiative)
- Semantic equivalence checking beyond Coq kernel acceptance
- Training or fine-tuning any ML models
- IDE plugin development
- Automated application without user review and consent
