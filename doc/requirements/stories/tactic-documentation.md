# User Stories: Tactic Documentation

Derived from [doc/requirements/tactic-documentation.md](../tactic-documentation.md).

---

## Epic 1: Tactic Lookup and Explanation

### 1.1 Look Up a Tactic Definition

**As a** Coq developer using Claude Code,
**I want to** ask Claude to look up the definition of a tactic and receive its Ltac source,
**so that** I can understand how a tactic is implemented without leaving my development workflow.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid tactic name WHEN the tactic lookup tool is invoked THEN it returns the Ltac definition as produced by `Print Ltac` in the running Coq session
- GIVEN a tactic name that does not exist in the current session WHEN the tool is invoked THEN it returns a clear error indicating the tactic was not found
- GIVEN an Ltac2 tactic or a primitive tactic with no Ltac definition WHEN the tool is invoked THEN it returns an appropriate message indicating the tactic is not defined in Ltac
- GIVEN a built-in primitive tactic name (e.g., `apply`, `destruct`, `simpl`, `setoid_rewrite`) WHEN the tactic lookup tool is invoked and Coq returns an error such as "not an Ltac definition" or "not a user defined tactic" THEN the tool returns a valid TacticInfo with `kind = "primitive"`, `body = null`, and the appropriate `category` — not an error
- GIVEN a multi-word input containing whitespace (e.g., "convoy pattern", "dependent destruction") WHEN the tactic lookup tool is invoked THEN it returns an `INVALID_ARGUMENT` error indicating that tactic names must be single identifiers

**Traces to:** R-P0-1, R-P0-5, R-P0-6

### 1.2 Explain a Tactic

**As a** Coq newcomer or intermediate developer using Claude Code,
**I want to** ask Claude to explain what a tactic does in plain language,
**so that** I can understand its behavior without reading the reference manual.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic name WHEN an explanation is requested THEN Claude returns a plain-language description covering what the tactic does, what types of goals it applies to, and common use cases
- GIVEN a tactic with optional arguments or variants WHEN an explanation is requested THEN the explanation describes the effect of key arguments and common invocation patterns
- GIVEN a project-local Ltac tactic WHEN an explanation is requested THEN the explanation is grounded in the actual Ltac definition retrieved from the Coq session, not solely from general knowledge

**Traces to:** R-P0-2

### 1.3 Tactic Documentation MCP Tools

**As a** Coq developer using Claude Code,
**I want** tactic documentation capabilities exposed as MCP tools,
**so that** Claude can invoke them during our conversational workflow without manual setup.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a running MCP server WHEN its tool list is inspected THEN tactic lookup and explanation tools are present with documented schemas
- GIVEN an MCP tool invocation WHEN the Coq session is active THEN the tool executes against the live session and returns results within 3 seconds
- GIVEN an MCP tool invocation WHEN no Coq session is active THEN the tool returns a clear error indicating a session is required

**Traces to:** R-P0-4

---

## Epic 2: Tactic Comparison

### 2.1 Compare Related Tactics

**As an** intermediate Coq developer using Claude Code,
**I want to** ask Claude to compare two or more related tactics (e.g., `auto` vs `eauto` vs `typeclasses eauto`),
**so that** I can understand their differences and choose the right one for my proof obligation.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN two or more tactic names WHEN a comparison is requested THEN Claude returns a structured comparison covering behavior differences, performance characteristics, applicability overlap, and guidance on when to prefer each
- GIVEN tactics `auto` and `eauto` WHEN compared THEN the comparison explains that `eauto` can apply lemmas with existential variables in their conclusions while `auto` cannot, and notes the performance trade-off
- GIVEN tactics `auto`, `eauto`, and `typeclasses eauto` WHEN compared THEN the comparison distinguishes the hint databases each consults and the search strategies each employs
- GIVEN a tactic name that does not exist WHEN included in a comparison request THEN the comparison indicates which tactic was not found and proceeds with the remaining valid tactics

**Traces to:** R-P0-3

---

## Epic 3: Contextual Tactic Suggestion

### 3.1 Suggest Tactics for the Current Goal

**As a** Coq developer stuck on a proof step,
**I want** Claude to suggest tactics that are likely to make progress on my current goal,
**so that** I can discover applicable tactics without guessing or searching documentation.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof state with at least one open goal WHEN tactic suggestion is invoked THEN it returns a ranked list of tactics likely to make progress, each with a brief rationale explaining why it may apply
- GIVEN a goal that is a propositional logic formula WHEN tactic suggestion is invoked THEN the suggestions include tactics such as `intuition`, `tauto`, or `firstorder` with an explanation of their relevance
- GIVEN a goal involving arithmetic WHEN tactic suggestion is invoked THEN the suggestions include decision procedures such as `lia`, `omega`, or `ring` as appropriate
- GIVEN a goal with no obvious applicable tactic WHEN tactic suggestion is invoked THEN the result indicates that no strong candidates were identified and suggests general strategies (e.g., "try unfolding definitions" or "consider case analysis on a hypothesis")

**Traces to:** R-P1-1

---

## Epic 4: Tactic Usage Examples and Reference

### 4.1 Show Tactic Usage Examples

**As a** Coq developer learning a new tactic,
**I want** Claude to show me concrete examples of how a tactic is used in proofs,
**so that** I can see the tactic applied in realistic contexts rather than only reading an abstract description.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic name and a project with indexed source files WHEN usage examples are requested THEN the tool returns excerpts from the current project showing the tactic in use, including the surrounding proof context
- GIVEN a tactic name with no occurrences in the current project WHEN usage examples are requested THEN the tool falls back to standard library examples or indicates that no project-local examples were found
- GIVEN a tactic with multiple usage patterns WHEN usage examples are requested THEN the examples cover distinct patterns (e.g., `rewrite ->` vs `rewrite <-` vs `rewrite ... in ...`)

**Traces to:** R-P1-2

### 4.2 Inspect Hint Databases

**As an** advanced Coq developer using Claude Code,
**I want to** ask Claude to show me the contents of a hint database,
**so that** I can understand what `auto` and `eauto` will try when consulting that database.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid hint database name WHEN the hint database inspection tool is invoked THEN it returns the contents of the database as produced by `Print HintDb`, grouped by hint type (Resolve, Unfold, Constructors, Extern)
- GIVEN a hint database name that does not exist WHEN the tool is invoked THEN it returns a clear error indicating the database was not found
- GIVEN a large hint database WHEN the tool is invoked THEN the output includes a summary count of hints by type before the detailed listing

**Traces to:** R-P1-3

### 4.3 Inspect Unfolding Strategies

**As an** advanced Coq developer trying to understand `simpl` or `cbn` behavior,
**I want to** ask Claude to retrieve the unfolding strategy for specific constants,
**so that** I can predict and control how simplification tactics will reduce my goal.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a constant name WHEN the strategy inspection tool is invoked THEN it returns the current unfolding strategy (opaque, transparent, or level) as produced by `Print Strategy`
- GIVEN a tactic name such as `simpl` or `cbn` WHEN strategy inspection is requested in the context of explaining that tactic THEN the tool retrieves strategies for constants relevant to the current goal

**Traces to:** R-P1-4
