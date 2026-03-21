# Proof State Visualization

Visual diagrams of Coq proof states — goals, hypotheses, and local context — rendered as Mermaid diagrams for educators explaining proof structure and developers navigating complex proof obligations.

---

## Problem

A Coq proof state is a list of goals, each with hypotheses and a target type. In text form, a proof state with 4 goals and 12 hypotheses is a wall of names and types that takes significant mental effort to parse — especially for students seeing formal proofs for the first time, or for developers working with AI assistants where the proof state must be communicated across a conversational interface.

Lean's ProofWidgets4 solves this in the IDE with custom React widgets. Coq has no visual representation of proof state during development — only the raw text in the goals panel.

## Solution

A Mermaid diagram that renders the current proof state as a structured visual: goals as distinct visual regions, hypotheses grouped under each goal with their types, local context bindings (let-bound variables) visually distinguished from assumptions. The diagram makes the structure of what remains to be proved immediately legible.

For step-by-step proof walkthroughs, a sequence of diagrams shows how the proof state evolves after each tactic — with visual highlighting of what changed (new hypotheses, modified goals, discharged subgoals). This is the primary tool for educators walking students through a proof one step at a time.

## Detail Levels

Not every audience needs the same amount of information. Three detail levels control diagram density:

- **Summary** — goal count and top-level structure only. For quick orientation: "this proof has 3 remaining goals."
- **Standard** — all goals with hypothesis names and types. The default for working developers.
- **Detailed** — full context with type abbreviations expanded and local let-bindings shown. For deep inspection when a proof is stuck.

## Design Rationale

### Why Mermaid rather than a table or structured text

Tables and structured text are better than raw proof state, but they still require sequential reading. A diagram with spatial grouping lets a user see at a glance: how many goals remain, which goal has the most hypotheses (likely the hardest), and where shared assumptions appear. Spatial layout carries information that linear text cannot.

### Why step-by-step evolution is part of proof state visualization

Step-by-step diagrams are not a separate feature — they are proof state diagrams arranged in sequence with diff highlighting. The same rendering logic produces each frame; the only addition is marking what changed between consecutive states. Splitting this into a separate feature would create an artificial boundary.

### Why diff highlighting rather than side-by-side comparison

Side-by-side comparison of two proof states is useful (and is a P2 requirement), but the primary use case is sequential: "I applied this tactic, what changed?" Highlighting diffs within each step's diagram answers that question directly without requiring the user to visually compare two diagrams.

### Why three detail levels rather than continuous configurability

Three levels cover the real use cases: quick check, working view, deep dive. Continuous configurability (hide these hypotheses, expand only these types) would require a complex parameter surface that the LLM must navigate. Three named levels are easy to request: "show me the summary" or "show me the detailed view."

## Scope Boundaries

Proof state visualization provides:

- Mermaid diagrams of proof states (goals, hypotheses, local context)
- Three detail levels (summary, standard, detailed)
- Step-by-step proof evolution with diff highlighting
- Support for standard Ltac and ssreflect proof states

It does **not** provide:

- Visualization of proof terms or Gallina expressions (focus is tactic-level proof structure)
- Interactive proof state editing or tactic suggestion through diagrams
- Animation or transitions between steps (each step is a static diagram)
- Custom visual styling per proof or per library (a P2 consideration)

## Acceptance Criteria

### Render Current Proof State as a Diagram

**Priority:** P0
**Stability:** Stable

- GIVEN a proof state with 2 goals and 3 hypotheses WHEN the proof state visualization MCP tool is called with this state THEN it returns valid Mermaid syntax that renders a diagram showing both goals and all 3 hypotheses with their types
- GIVEN a proof state with local context bindings (let-bound variables) WHEN the visualization tool is called THEN the diagram includes the local bindings visually grouped with the hypotheses
- GIVEN a proof state from an ssreflect tactic step WHEN the visualization tool is called THEN it renders correctly, not only standard Ltac states

**Traces to:** R4-P0-1, R4-P0-3, R4-P0-9

### Validate Mermaid Output

**Priority:** P0
**Stability:** Stable

- GIVEN a proof state visualization produced by the MCP tool WHEN the Mermaid syntax is submitted to the Mermaid Chart MCP rendering service THEN it renders without syntax errors
- GIVEN a proof state with special characters in hypothesis names or goal types (e.g., subscripts, primes, Unicode) WHEN the visualization tool generates Mermaid syntax THEN special characters are escaped or transliterated so rendering succeeds

**Traces to:** R4-P0-5, R4-P0-7

### Latency Target

**Priority:** P0
**Stability:** Stable

- GIVEN a proof state with up to 10 goals and 20 hypotheses WHEN the visualization MCP tool is called THEN the Mermaid diagram text is returned in under 2 seconds on a standard development machine
- GIVEN a proof state from a MathComp proof with ssreflect-heavy context WHEN the visualization tool is called THEN it completes within the same 2-second latency target

**Traces to:** R4-P0-8

### Step-by-Step Proof Evolution Diagrams

**Priority:** P1
**Stability:** Stable

- GIVEN a proof trace with 6 tactic steps WHEN the proof sequence MCP tool is called THEN it returns 7 Mermaid diagrams (initial state plus one per tactic step)
- GIVEN consecutive proof states in the sequence WHEN the diagrams are compared THEN each diagram reflects the effect of the corresponding tactic (new subgoals introduced, goals discharged, hypotheses added)

**Traces to:** R4-P1-1

### Highlight Changes Between Proof Steps

**Priority:** P1
**Stability:** Draft

- GIVEN two consecutive proof states where a tactic introduced a new hypothesis H WHEN the step diagram is rendered THEN hypothesis H is visually highlighted as new (e.g., distinct styling or annotation)
- GIVEN two consecutive proof states where a tactic discharged a subgoal WHEN the step diagram is rendered THEN the discharged goal is visually marked as resolved
- GIVEN two consecutive proof states where a tactic split a goal into two subgoals WHEN the step diagram is rendered THEN both new subgoals are highlighted as newly introduced

**Traces to:** R4-P1-2

### Configure Diagram Detail Level

**Priority:** P1
**Stability:** Draft

- GIVEN a proof state with 3 goals and 5 hypotheses WHEN the summary detail level is requested THEN the diagram shows goal count and top-level structure only, without listing individual hypotheses
- GIVEN the same proof state WHEN the standard detail level is requested THEN the diagram shows all goals and hypotheses with their names and types
- GIVEN the same proof state WHEN the detailed level is requested THEN the diagram additionally expands type abbreviations and shows full local context

**Traces to:** R4-P1-3
