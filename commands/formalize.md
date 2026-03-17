Formalization Assistance: guide a user from a natural language theorem description to a completed, type-checked Coq proof in a single conversational session.

## Step 1: Understand the User's Intent

The user will describe what they want to prove in natural language or mathematical prose. Your job is to extract the precise mathematical intent.

- If the description is clear and complete, proceed to Step 2.
- If the description is ambiguous, underspecified, or could refer to multiple formalizations, ask clarifying questions before proceeding. Do not guess. Examples of things to clarify: which types are involved (nat vs Z vs R), whether a property is over a specific structure or general, what the quantifier structure should be.
- If the description is partial (e.g., "associativity of append"), infer the missing pieces from the current file context, loaded libraries, and naming conventions. State what you inferred so the user can confirm or correct.

## Step 2: Search for Relevant Existing Results

Before proposing any formal statement, search the loaded libraries and the user's project for relevant existing lemmas, definitions, and types. Use these tools:

- `search_by_name` for results matching likely names
- `search_by_type` or `search_by_structure` if you can anticipate the type shape
- `search_by_symbols` for results involving specific constants or constructors
- `find_related` to discover related results from a known starting point
- `list_modules` to understand what libraries are available
- `Grep` and `Glob` to search the user's local project files

For each relevant result you find, explain to the user why it matters:
- Does it already state exactly what the user wants to prove? If so, tell them immediately -- no need to re-derive a known result.
- Does it generalize the user's theorem?
- Is it a building block that will be useful in the proof?

Also note which libraries and imports are needed. The user should not have to track down dependencies.

## Step 3: Propose a Formal Coq Statement

Construct a candidate `Theorem`, `Lemma`, or `Definition` declaration in Coq syntax. Ground it in what you learned from the search results: use the same types, naming conventions, and proof patterns that the relevant libraries use.

Before presenting the statement to the user, type-check it using `vernacular_query` with a `Check` or `Definition` command. Never show the user a statement that Coq would reject.

If the statement fails to type-check:
1. Read the error message and diagnose the problem (missing import, wrong types, universe issue, etc.).
2. Fix the statement and re-check.
3. Repeat until it type-checks.
4. Only then present it to the user.

When presenting the statement, explain it in terms of the user's original natural language description. Map each part of the formal statement back to the mathematical concept it captures.

## Step 4: Refine the Statement

The user may say the statement does not match their intent. When they describe a correction in natural language:

1. Produce a revised formal statement.
2. Type-check it before presenting.
3. Explain what changed and why.

Iterate until the user accepts the statement. Maintain context across rounds -- do not re-derive from scratch each time.

## Step 5: Build the Proof Interactively

Once the user accepts the formal statement, open a proof session with `open_proof_session`.

### Try automation first

Before manual proof construction, attempt automated strategies on the initial goal:

1. Try `submit_tactic` with `hammer` (CoqHammer).
2. If hammer fails or times out, try `sauto` or `qauto` with reasonable parameters.
3. If automation solves the goal, present the completed proof and skip to Step 6.

### Guide manual proof construction

If automation does not fully solve the goal:

1. Use `observe_proof_state` to see the current goals.
2. Suggest a tactic, explaining what it does and why it is appropriate given the mathematical content.
3. Apply it with `submit_tactic`.
4. If the tactic fails, explain the failure in mathematical terms (not just the raw Coq error). Suggest alternatives.
5. If a step leads to a dead end, use `step_backward` to backtrack.
6. For subgoals that are routine (arithmetic, simple rewriting, decidability), try automation (`auto`, `lia`, `omega`, `intuition`, `sauto`) to discharge them without burdening the user.
7. Use `get_proof_premises` or `get_step_premises` to identify which lemmas are being used, and inform the user.
8. Continue until all goals are closed.

Throughout the proof, explain your reasoning in terms of the user's original mathematical description. The user should understand the proof strategy, not just the tactic sequence.

### If the proof gets stuck

- Search for additional lemmas that might help, using the search tools from Step 2.
- Consider whether the statement itself needs adjustment (go back to Step 4).
- Suggest alternative proof strategies (induction vs case analysis, classical vs constructive, direct vs contradiction).

## Step 6: Present the Final Result

Once all goals are closed, close the proof session with `close_proof_session`. Present the complete, proven theorem as a self-contained block of Coq code that the user can insert into their development. Include:

- Any `Require Import` statements needed
- The theorem statement
- The complete proof

Use `Read` and `Edit` or `Write` to insert the result into the user's file if they ask for it.
