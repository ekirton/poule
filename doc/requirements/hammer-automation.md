# Automated Proving via Hammer — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context.

## 1. Business Goals

CoqHammer is one of the most effective automation tools in the Coq ecosystem — it combines automated reasoning with lemma retrieval to discharge a large fraction of first-order goals. Its tactics (`hammer`, `sauto`, `qauto`) are mature and battle-tested. Yet they remain underused because they require plugin installation knowledge, familiarity with tactic syntax and options, and the ability to interpret failure output. The gap is not capability but accessibility.

This initiative wraps CoqHammer's tactics as an MCP-accessible mode so that Claude can invoke automated proving on behalf of the user during active proof sessions. The wrapper is thin: it submits hammer/sauto/qauto tactics through the existing Proof Interaction Protocol and interprets the results. When the tactic succeeds, Claude reports the verified proof script. When it fails, Claude explains why and suggests alternatives. The user experience shifts from "read the CoqHammer docs, install the plugin, figure out the right tactic" to "try to prove this automatically."

Hammer automation is exposed as a dedicated `try_automation` tool, separate from the pedagogical `suggest_tactics` tool. `suggest_tactics` provides explained tactic hints for teaching — Claude uses neural predictions to explain *why* a tactic makes sense and links to textbook material. `try_automation` is a solver — it attempts to close goals without human involvement. Keeping these separate ensures the student-facing and automation-facing tools have clearly different intents.

**Success metrics:**
- ≥ 80% of hammer invocations through MCP return a result (success or structured failure) within the configured timeout
- When hammer succeeds, the returned proof script is valid Coq that closes the goal in 100% of cases
- Users can invoke hammer automation without any knowledge of CoqHammer syntax or configuration
- Time from user intent ("try to prove this") to hammer result is < 2x the raw CoqHammer execution time (i.e., MCP overhead is minimal)
- ≥ 30% of first-order proof obligations in a representative test corpus are discharged by hammer without manual intervention

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using Claude Code | Automatic discharge of proof obligations during conversational proof development, without learning CoqHammer syntax | Primary |
| Coq newcomers | Access to powerful automation without needing to know which tactic to use or how to configure it | Primary |
| Formalization developers | Rapid disposal of routine lemmas so they can focus on the hard parts of a proof development | Secondary |
| AI researchers | Baseline automation to compare against learned proof search strategies | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Lean ecosystem (comparative baseline):**
- LeanHammer: recent port of hammer-style automation to Lean 4. Integrates with external ATP solvers (Zipperposition, E, Vampire). Accessible from Lean code but still requires manual tactic invocation.
- Lean's `aesop`: extensible tactic for rule-based proof search. No external ATP integration but well-integrated into the IDE workflow.

**Coq ecosystem (current state):**
- CoqHammer: mature, well-maintained tool combining premise selection with external ATP solvers and proof reconstruction. Covers a large fraction of first-order goals. Includes `sauto` (smart auto) and `qauto` (quick auto) for goals that do not require external ATPs.
- Despite its power, CoqHammer is underused because: (1) users must install the plugin and its ATP solver dependencies, (2) users must know which variant to try (`hammer` vs `sauto` vs `qauto`) and with what options, (3) failure messages are opaque without domain expertise.
- No existing tool wraps CoqHammer for LLM-driven invocation or interprets its results in natural language.

**Key insight:** The underlying automation already exists and is excellent. The gap is purely in the interface layer — making it accessible through natural language and interpreting results for the user. This is a high-value, low-effort opportunity.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RH-P0-1 | Invoke the `hammer` tactic in an active proof session through the existing proof interaction protocol and return the result |
| RH-P0-2 | Invoke `sauto` and `qauto` tactics in an active proof session through the existing proof interaction protocol and return the result |
| RH-P0-3 | When a hammer tactic succeeds, return the verified proof script that closes the goal |
| RH-P0-4 | When a hammer tactic fails, return structured diagnostic information including the failure reason and any partial progress |
| RH-P0-5 | Support a configurable timeout for hammer invocations, with a sensible default |
| RH-P0-6 | Expose hammer automation as a dedicated `try_automation` tool, separate from the pedagogical `suggest_tactics` tool, so that solver and teaching intents are clearly distinguished |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RH-P1-1 | Try multiple hammer strategies sequentially (e.g., `hammer`, then `sauto`, then `qauto`) and return the first success, so the user does not need to know which variant to use |
| RH-P1-2 | Support passing hints (lemma names, database names) to hammer tactics when the user or Claude has context about which lemmas might be relevant |
| RH-P1-3 | When hammer succeeds with a reconstructed proof, return both the high-level proof found by the ATP solver and the low-level Coq tactic script, so the user can choose which to keep |
| RH-P1-4 | Support configurable options for `sauto` and `qauto` (e.g., search depth, unfolding hints) to allow tuning when the defaults do not work |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RH-P2-1 | Integrate with Semantic Lemma Search to automatically supply relevant lemma hints to hammer when available |
| RH-P2-2 | Collect statistics on hammer success rates across a proof development to help users understand which types of goals benefit from automation |
| RH-P2-3 | When hammer fails, suggest alternative tactics or proof strategies based on the failure diagnostic |

---

## 5. Scope Boundaries

**In scope:**
- Thin MCP wrapper around CoqHammer tactics (`hammer`, `sauto`, `qauto`)
- Submission of hammer tactics through the existing Proof Interaction Protocol
- Result interpretation: success with proof script, failure with diagnostics
- Timeout configuration
- Sequential strategy fallback (try multiple tactics)
- Exposure as a mode of existing tools (not new top-level tools)

**Out of scope:**
- Installation or management of CoqHammer or its ATP solver dependencies (assumed to be pre-installed in the user's Coq environment)
- Training or fine-tuning any ML models
- Proof search beyond what CoqHammer provides (covered by the Proof Search & Automation initiative)
- Modifications to CoqHammer itself
- IDE plugin development
- Proof visualization (covered by Proof Visualization Widgets initiative)
