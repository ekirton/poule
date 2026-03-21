# Hammer Automation

CoqHammer is one of the most effective automated proving tools in the Coq ecosystem, but it remains underused because it requires plugin knowledge, tactic syntax familiarity, and the ability to interpret opaque failure output. Hammer Automation wraps CoqHammer's tactics (`hammer`, `sauto`, `qauto`) so that Claude can invoke them on behalf of the user during active proof sessions. The user experience shifts from "read the CoqHammer docs and figure out the right tactic" to "try to prove this automatically."

---

## Problem

Claude Code with the Proof Interaction Protocol can already submit individual tactics to Coq and reason about the results conversationally. But when a user wants to discharge a goal automatically, Claude must guess which tactic to try, wait for the result, and iterate — essentially performing manual proof search one tactic at a time. The user, meanwhile, would need to know that CoqHammer exists, which of its three tactics to try, what options to pass, and how to interpret its failure output. Newcomers rarely get this far; experienced users waste time on mechanical invocations they could skip.

What's missing is the ability for Claude to say "let me try automated proving" and have CoqHammer's full power applied to the current goal — with the right tactic chosen automatically, timeouts managed, and results reported in terms the user can act on.

## Solution

Hammer automation lets Claude invoke CoqHammer tactics within an active proof session through the existing proof interaction tools. When the user asks Claude to try proving a goal automatically, Claude submits hammer tactics to Coq and reports the outcome: either a verified proof script ready to insert, or a clear explanation of why automation did not succeed and what to try next.

### Multi-Strategy Fallback

The user should not need to know whether `hammer`, `sauto`, or `qauto` is the right tactic for their goal. When Claude invokes hammer automation without a specific tactic, the system tries multiple strategies in sequence — starting with the most powerful (`hammer`, which uses external ATP solvers) and falling back to lighter-weight alternatives (`sauto`, `qauto`). The first strategy that succeeds ends the sequence immediately. If all strategies fail, the user gets diagnostics from each attempt rather than a single opaque failure.

Users who do know which tactic they want can still request a specific one. Lemma hints can be supplied when the user or Claude has context about which lemmas might be relevant, guiding CoqHammer toward proofs it might not find on its own.

### Timeout Handling

Hammer tactics — especially `hammer` with external ATP solvers — can be slow. Every invocation respects a configurable timeout with a sensible default. When a multi-strategy sequence is running, the timeout governs the total time budget: if `hammer` exhausts most of the budget, the remaining strategies get whatever time is left rather than restarting the clock. When a timeout is reached, the result reports that the timeout was hit and what value was used, so the user can decide whether to retry with a larger budget.

### Result Reporting

When a hammer tactic succeeds, the result is a verified proof script — a sequence of Coq-native tactics that closes the goal. The user can insert this script directly into their development with confidence that it will be accepted by Coq. When `hammer` succeeds via ATP reconstruction, both the high-level ATP proof and the low-level reconstructed tactic script are available, so the user can choose which form to keep.

When a hammer tactic fails, the result includes structured diagnostics: why it failed (timeout, no proof found, reconstruction failure), any partial progress (e.g., the ATP solver found a proof but Coq reconstruction failed), and enough context for Claude to explain the failure and suggest alternatives.

## Scope

Hammer automation provides:

- Invocation of `hammer`, `sauto`, and `qauto` in active proof sessions
- Multi-strategy fallback when the user does not specify a tactic
- Configurable timeouts and tactic options
- Verified proof scripts on success, structured diagnostics on failure
- Lemma hint passthrough to guide premise selection

Hammer automation does not provide:

- Installation or management of CoqHammer or its ATP solver dependencies — these must be pre-installed in the user's Coq environment
- Proof search beyond what CoqHammer offers (see [Proof Search](proof-search.md) for tree-search-based exploration)
- Modifications to CoqHammer itself
- Statistics collection or success rate tracking across proof developments

---

## Design Rationale

### Why expose as a mode of existing tools

Poule already exposes 22 MCP tools, and research indicates that LLM accuracy degrades past 20-30 tools. Adding new top-level tools for each hammer variant would push past this budget. Exposing hammer automation as a mode of the existing proof interaction tools keeps the tool count stable while expanding capability. From Claude's perspective, invoking hammer is just another way to use a tool it already knows.

### Why try multiple strategies

CoqHammer's three tactics cover different points in the power-speed tradeoff. `hammer` is the most powerful (it invokes external ATP solvers and reconstructs proofs) but also the slowest. `sauto` provides strong automation without external solvers. `qauto` is the fastest but handles fewer goals. No single tactic dominates — the right choice depends on the goal structure, and users should not need to make that choice themselves. Trying strategies in sequence from most powerful to least powerful maximizes the chance of success while letting the user specify a single intent: "prove this automatically."

### Why CoqHammer is the right foundation

CoqHammer is the most mature automated proving tool in the Coq ecosystem. It combines premise selection with external ATP solvers (E, Vampire, Z3) and proof reconstruction, covering a large fraction of first-order goals. Its `sauto` and `qauto` tactics complement the main `hammer` tactic by handling goals that do not require external ATPs. The tool is actively maintained and battle-tested across major formalization projects. Rather than building new automation from scratch, wrapping CoqHammer gives users access to years of engineering and research through a natural language interface.

---

## Acceptance Criteria

### Invoke Hammer in an Active Proof Session

**Priority:** P0
**Stability:** Stable

- GIVEN an active proof session with an open goal WHEN hammer automation is invoked THEN the `hammer` tactic is submitted through the proof interaction protocol and the result is returned
- GIVEN no active proof session WHEN hammer automation is invoked THEN a clear error is returned indicating that a proof session must be active
- GIVEN a proof session with multiple open goals WHEN hammer automation is invoked THEN it targets the current focused goal

**Traces to:** RH-P0-1

### Invoke sauto and qauto Variants

**Priority:** P0
**Stability:** Stable

- GIVEN an active proof session with an open goal WHEN `sauto` automation is invoked THEN the `sauto` tactic is submitted through the proof interaction protocol and the result is returned
- GIVEN an active proof session with an open goal WHEN `qauto` automation is invoked THEN the `qauto` tactic is submitted through the proof interaction protocol and the result is returned
- GIVEN a choice between `sauto` and `qauto` WHEN the user does not specify which to use THEN Claude can choose based on context or try both

**Traces to:** RH-P0-2

### Expose as Mode of Existing Tools

**Priority:** P0
**Stability:** Stable

- GIVEN the MCP server's tool list WHEN it is inspected THEN hammer automation does not appear as a new top-level tool
- GIVEN an existing proof interaction tool WHEN it is invoked with a hammer mode or tactic parameter THEN it executes the hammer tactic and returns the result
- GIVEN a user who has never used CoqHammer WHEN they ask Claude to "try to prove this automatically" THEN Claude can invoke hammer through the existing tool interface without additional setup

**Traces to:** RH-P0-6

### Handle Success — Return Verified Proof Script

**Priority:** P0
**Stability:** Stable

- GIVEN a hammer invocation that succeeds WHEN the result is returned THEN it includes the complete tactic script that closes the goal
- GIVEN a successful proof script returned by hammer WHEN it is submitted to Coq independently THEN it is accepted without error
- GIVEN a successful `hammer` invocation WHEN it finds a proof via ATP reconstruction THEN the returned script uses only Coq-native tactics (the reconstruction, not the ATP proof)

**Traces to:** RH-P0-3

### Handle Failure — Return Diagnostics

**Priority:** P0
**Stability:** Stable

- GIVEN a hammer invocation that fails WHEN the result is returned THEN it includes a structured failure reason (e.g., timeout, no proof found, reconstruction failure)
- GIVEN a hammer failure due to timeout WHEN the diagnostic is returned THEN it indicates that the timeout was reached and reports the timeout value used
- GIVEN a hammer failure WHEN the diagnostic is returned THEN it includes any partial progress information available (e.g., ATP solver found a proof but reconstruction failed)

**Traces to:** RH-P0-4

### Configure Timeout

**Priority:** P0
**Stability:** Stable

- GIVEN a hammer invocation with a specified timeout WHEN the tactic runs THEN it respects the specified timeout
- GIVEN a hammer invocation without a specified timeout WHEN the tactic runs THEN a sensible default timeout is applied
- GIVEN a timeout value WHEN it is specified THEN it is passed through to the underlying CoqHammer tactic

**Traces to:** RH-P0-5

### Configure sauto and qauto Options

**Priority:** P1
**Stability:** Draft

- GIVEN a `sauto` invocation with a search depth parameter WHEN the tactic runs THEN the specified depth limit is applied
- GIVEN a `qauto` invocation with unfolding hints WHEN the tactic runs THEN the specified definitions are unfolded during search
- GIVEN a `sauto` or `qauto` invocation without options WHEN the tactic runs THEN sensible defaults are applied

**Traces to:** RH-P1-4

### Try Multiple Strategies Sequentially

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof session with an open goal WHEN multi-strategy automation is invoked THEN `hammer`, `sauto`, and `qauto` are tried in sequence
- GIVEN a multi-strategy invocation WHEN one of the tactics succeeds THEN the successful result is returned immediately without trying remaining tactics
- GIVEN a multi-strategy invocation WHEN all tactics fail THEN the result includes diagnostics from each attempt
- GIVEN a multi-strategy invocation WHEN the combined time exceeds the timeout THEN the sequence is terminated and the diagnostics collected so far are returned

**Traces to:** RH-P1-1

### Pass Lemma Hints to Hammer

**Priority:** P1
**Stability:** Stable

- GIVEN a hammer invocation with specified lemma hints WHEN the tactic runs THEN the hints are passed to the underlying CoqHammer tactic
- GIVEN a `sauto` invocation with lemma hints WHEN the tactic runs THEN the hints are included in the search
- GIVEN a hammer invocation without hints WHEN the tactic runs THEN it proceeds with CoqHammer's default premise selection

**Traces to:** RH-P1-2

### Return Both ATP and Reconstructed Proof

**Priority:** P1
**Stability:** Draft

- GIVEN a successful `hammer` invocation that used an ATP solver WHEN the result is returned THEN it includes the reconstructed Coq tactic script
- GIVEN a successful `hammer` invocation WHEN the ATP-level proof is available THEN it is also included in the result alongside the reconstructed script
- GIVEN a successful `sauto` or `qauto` invocation WHEN the result is returned THEN only the Coq tactic script is included (no ATP proof exists)

**Traces to:** RH-P1-3
