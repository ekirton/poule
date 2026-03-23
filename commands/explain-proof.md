Walk through a completed Coq proof tactic by tactic, explaining each step in plain English with mathematical intuition, showing how the proof state evolves, and summarizing the overall proof strategy. This command is read-only — it never modifies source files.

The user provides a target proof in one of these forms:

- A lemma or theorem name (e.g., `plus_comm`)
- A file path and line number (e.g., `Arithmetic.v:42`)
- No argument, meaning "the proof I'm currently looking at" — use surrounding conversation context to identify it

The user may also specify a detail level:

- `--brief` — one line per tactic, minimal context, for experienced developers scanning a proof
- `--verbose` — full pedagogical explanation with mathematical background, for students and newcomers
- Default (no flag) — balanced explanation suitable for most readers

## Step 1: Locate the target proof

Resolve the user's input to a specific theorem, lemma, definition, or other proof-bearing construct:

- **By name:** Use `search_by_name` to find the definition. If multiple results match, ask the user to disambiguate.
- **By file:line:** Use Read to open the file at the given line and identify the enclosing proof-bearing declaration.
- **By context:** Identify the proof from the current conversation. If ambiguous, ask the user to clarify.

Once located, use `get_lemma` to retrieve the full statement and proof script. Note the qualified name for use in subsequent steps.

## Step 2: Open a proof session

Call `open_proof_session` on the target lemma or theorem. This gives you an interactive session where you can observe proof state at each step.

If the session fails to open (e.g., the proof is not found or the file has errors), report the error clearly and stop.

## Step 3: Extract the proof trace

Call `extract_proof_trace` on the open session to get the full sequence of tactic steps. This returns every tactic application in order, including compound tactics.

If the proof trace is empty or the proof uses a single `Qed` with no tactic body (e.g., a `Defined` term-mode proof), explain this to the user and provide what information you can from the proof term instead.

## Step 4: Walk through each tactic step

For each tactic step in the trace, produce an explanation block with three parts:

### 4a: Proof state before

Call `get_proof_state_at_step` or `observe_proof_state` to retrieve the proof state immediately before this tactic fires. Display it in a Coq code block showing:

- All current hypotheses (the context)
- The current goal(s)
- If there are multiple goals, indicate which goal this tactic targets

### 4b: Explain the tactic

Explain what the tactic does at two levels:

1. **Mechanical effect** — What this tactic does in general terms. For example: "`intros` moves the leading universally quantified variables and hypotheses from the goal into the proof context."

2. **Contextual effect** — What it accomplished in this specific proof. For example: "Here, `intros n IHn` introduced the natural number `n` and the induction hypothesis `IHn : P n` into the context, leaving us to prove `P (S n)`."

3. **Mathematical intuition** — Connect the step to the underlying mathematical reasoning. For example: "This is the inductive step: we assume the property holds for `n` and must show it holds for `n + 1`."

For **compound tactics** (semicolons, `try`, `repeat`, `[> | ]` goal selectors):

- Break the compound tactic into its component parts.
- Explain each part individually.
- Then explain the combined effect and why the compound form was used (e.g., "`rewrite H; simpl` rewrites and then simplifies in one step, avoiding an intermediate goal the user doesn't need to see").

For **automation tactics** (`auto`, `omega`, `lia`, `nia`, `ring`, `field`, `tauto`, `intuition`, `firstorder`, `hammer`, `decide`, `easy`, `now`):

- State what the automation tactic is designed to do in general.
- Explain what it achieved here — what goal did it close, and why was that goal within the tactic's capabilities?
- If feasible, describe briefly what a manual proof of this step would have looked like (e.g., "A manual proof would require unfolding the definition, applying associativity twice, and then reflexivity").
- Use `get_step_premises` if available to identify which lemmas or hypotheses the automation relied on.

For **rewrite and application tactics** (`rewrite`, `apply`, `exact`, `refine`, `eapply`):

- Identify the lemma, hypothesis, or equation being used.
- Use `vernacular_query` with `Check` or `Print` to retrieve its statement if it is not already in the context.
- Explain how the referenced term connects to the current goal.

### 4c: Proof state after

Display the proof state after the tactic fires, in the same format as 4a. Highlight what changed:

- New hypotheses that appeared
- Hypotheses that were modified or removed
- How the goal changed
- New subgoals that were created, or subgoals that were discharged

### 4d: Adjust for detail level

- **Brief:** Collapse each step to a single line: the tactic, a dash, and a short phrase describing its contextual effect. Omit proof state display and mathematical intuition. Example: "`induction n` — sets up induction on `n`, creating base case and inductive step."
- **Verbose:** Include all three explanation levels (mechanical, contextual, mathematical). Add pedagogical notes where helpful, such as: "If you're new to this tactic, think of it as..." or "This is a common Coq idiom for...". Mention alternative tactics that could have been used if that adds insight.
- **Default:** Include contextual effect and mathematical intuition. Include proof state before/after. Omit pedagogical asides and alternative-tactic discussion.

## Step 5: Close the proof session

After walking through all steps, call `close_proof_session` to release the session resources.

## Step 6: Summarize the proof strategy

After the step-by-step walkthrough, provide a high-level summary covering:

1. **Proof approach** — Name the overall strategy (e.g., "proof by induction on `n`", "case analysis on the structure of `t`", "forward reasoning from hypotheses", "proof by contradiction").

2. **Key lemmas and hypotheses** — List the external lemmas, theorems, or axioms that the proof relied on. Use `get_proof_premises` to retrieve these. For each one, state its name and what it contributes in one phrase.

3. **Proof structure** — Describe the shape of the proof: how many subgoals were generated, how they were discharged, and whether any branches shared a common strategy.

4. **Recognizable patterns** — If the proof follows a well-known pattern (e.g., "strengthen the induction hypothesis", "generalize before inducting", "rewrite into a normal form then decide", "unfold and compute"), name it.

For **brief** mode, compress the summary to 2-3 sentences. For **verbose** mode, expand each point with additional context.

## Step 7: Add educational context

After the summary, call `education_context` with a query describing the overall proof strategy identified in the walkthrough (e.g., "proof by induction on natural numbers", "case analysis on boolean expressions", "rewriting with associativity and commutativity").

If results are returned, append a brief **Further reading** note at the end:
- Cite the most relevant Software Foundations passage in one to two sentences.
- Include the browser path so the user can open the chapter.
- Tell the user: "Use `/textbook` to explore this topic further in Software Foundations."

Keep the educational annotation brief — do not reproduce the full passage. If `education_context` returns an error or no results, skip this step silently.

## Edge cases

- **Very long proofs (>30 tactic steps):** Produce the full walkthrough but offer to group consecutive similar steps (e.g., a sequence of `simpl; rewrite` pairs) into summarized blocks. Ask the user before truncating.
- **Proof terms instead of tactic proofs:** If the proof is written in term mode (no tactics), explain the proof term structure instead. Break it into subexpressions and explain each one.
- **Proofs with `Admitted` or `admit`:** Walk through as far as the proof goes, then clearly note where and why the proof is incomplete.
- **Dependent or generated proofs:** If the proof was generated by a tactic like `Program` or `Equations`, note this and explain the generated proof obligations.
- **Proofs with `Opaque` or `Abstract`:** Note which parts are opaque and cannot be inspected.
- **Session errors mid-walkthrough:** If a proof state query fails during the walkthrough, report the error for that step and continue with remaining steps rather than aborting entirely.
