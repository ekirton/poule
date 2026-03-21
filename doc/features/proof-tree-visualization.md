# Proof Tree Visualization

Visual diagrams of Coq proof trees — the branching structure of tactic applications and subgoals — rendered as Mermaid diagrams for understanding proof strategy at a glance.

---

## Problem

A completed Coq proof is a sequence of tactic invocations, but the interesting structure is the tree: which tactics split the proof into subgoals, which branches were easy (one tactic) and which were deep (many steps), and where the proof strategy made critical choices. Reading a flat tactic script, this tree structure must be reconstructed mentally — a task that is difficult even for experienced users and nearly impossible for students.

Lean's ProofWidgets4 can render proof trees inline. Coq has no equivalent. Alectryon interleaves proof states with tactic text but does not visualize the tree structure.

## Solution

A Mermaid diagram that renders a completed proof as a tree: tactic applications as labeled edges, subgoals as nodes, discharged goals visually distinct from open goals. The root is the original theorem statement. Branching tactics (like `split`, `destruct`, `induction`) produce multiple child nodes. Leaf nodes are goals resolved by terminal tactics (like `exact`, `assumption`, `reflexivity`).

The diagram answers questions like: "How deep is this proof?", "Where does the proof branch?", "Which branch was the hardest?", and "What are the leaf tactics?"

## Design Rationale

### Why tree diagrams rather than linear step lists

A linear list of tactic steps hides the branching structure — the most important structural feature of a proof. A proof that splits into 4 subgoals, each solved by 1 tactic, looks identical in a flat list to a 4-step linear proof. The tree reveals that these are fundamentally different proof strategies.

### Why focus on completed proofs rather than in-progress proofs

A proof tree is meaningful only when the full structure is known. An in-progress proof has open goals — which appear as leaf nodes, but the tree shape may change drastically as the proof continues. Proof state visualization (not proof tree visualization) is the right tool for in-progress work. Proof trees are retrospective: "here is how this proof worked."

### Why distinguish discharged goals visually

In a proof tree, discharged (solved) goals are the success signal — they show where the proof closed off obligations. When all leaf nodes are discharged, the proof is complete. Making this visible lets users immediately see if any obligations remain, and during teaching, walk through which tactic closed each branch.

### Why Mermaid tree diagrams scale to practical proofs

Most Coq proofs in standard libraries have 3–30 tactic steps. Mermaid's top-down tree layout handles this comfortably. For the P1 readability requirement (up to 50 tactic steps), Mermaid's layout engine still produces readable trees — though very wide branching may require horizontal scrolling. Proofs beyond 50 steps are rare in practice and are better served by summary views or subtree extraction, which are separate concerns.

## Scope Boundaries

Proof tree visualization provides:

- Mermaid tree diagrams of completed proof traces
- Tactic applications as labeled edges, subgoals as nodes
- Visual distinction between discharged and open goals
- Correct representation of branching tactics and nested combinators

It does **not** provide:

- Visualization of in-progress (incomplete) proof trees
- Subtree extraction or selective tree rendering (future consideration)
- Comparison of two different proof trees for the same theorem (P2 requirement in the PRD)
- Proof term trees (the Curry-Howard view) — focus is on the tactic-level tree

## Acceptance Criteria

### Render Proof Tree for a Completed Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a completed proof trace with 8 tactic steps WHEN the proof tree visualization MCP tool is called THEN it returns valid Mermaid syntax showing tactic applications as edges and subgoals as nodes
- GIVEN a proof tree where 3 of 5 subgoals are discharged WHEN the diagram is rendered THEN discharged goals are visually distinct from open goals (e.g., different node style or color)
- GIVEN a proof that uses nested tactic combinators (e.g., `split; [apply H1 | apply H2]`) WHEN the proof tree is rendered THEN branching structure is correctly represented

**Traces to:** R4-P0-2, R4-P0-4, R4-P0-5

### Render Proof Trees for Standard Library Proofs

**Priority:** P0
**Stability:** Stable

- GIVEN a completed proof trace from a Coq standard library theorem with at least 5 tactic steps WHEN the proof tree tool is called THEN it produces a valid, renderable Mermaid diagram
- GIVEN proof traces from 10 distinct standard library theorems WHEN proof tree diagrams are generated for each THEN at least 9 out of 10 render successfully

**Traces to:** R4-P0-2, R4-P0-9
