Given a working Coq proof, systematically search for shorter or cleaner alternatives using hammer tactics, lemma search, and tactic chain simplification. Present verified alternatives ranked against the original. Never modify the original file unless the user explicitly chooses a replacement.

## Identify the target proof

The user will specify a proof by name (e.g., `my_lemma`), by file location (e.g., `src/Foo.v:42`), or by asking you to compress the proof at point in the current context. If the user gives a name without a file, use `search_by_name` to locate it. If the user specifies a sub-proof or specific step range, note that scope for later — you will target only that portion.

Read the source file with `Read` to get the full proof script. Identify the `Proof. ... Qed.` (or `Defined.`) block. Record the original proof text exactly — you will need it for comparison and to restore it if anything goes wrong.

## Understand the existing proof

Before attempting compression, understand what the proof does:

1. Use `get_lemma` to retrieve the lemma statement and its full proof.
2. Count the number of tactic steps in the original proof. This is your baseline.
3. Note the proof structure: is it a single chain, does it use bullets, does it have nested sub-proofs? This informs which strategies are worth trying.

## Open a proof session and extract the goal

1. Call `open_proof_session` on the file containing the proof.
2. Use `observe_proof_state` or `get_proof_state_at_step` to obtain the goal state at the point where the proof begins (right after `Proof.`). Record this goal — all compression candidates must close exactly this goal.
3. If the user targeted a sub-proof or step range, navigate to that point and extract the goal there instead.

## Try compression strategies

Run these strategies independently. A failure in one does not affect the others. For each candidate that appears to work, you must verify it before recording it.

### Strategy 1: Automated solvers

Try replacing the entire proof (or targeted sub-proof) with automation:

1. Call `try_automation` with `strategy="auto_hammer"` — this tries hammer, sauto, and qauto in sequence.
2. If `auto_hammer` fails, try each strategy individually with `try_automation` using `strategy="hammer"`, `strategy="sauto"`, and `strategy="qauto"` with longer timeouts.

If automation closes the goal (check with `observe_proof_state`), record it as a candidate. Then call `step_backward` to restore the goal state.

If the full proof has multiple goals (e.g., from `split`), try automation on individual subgoals too — navigate to each subgoal and attempt there.

### Strategy 2: Direct lemma search

1. From the goal state, identify the head symbols and types involved.
2. Use `search_by_type` with the goal type to find lemmas that match the goal directly.
3. Use `vernacular_query` with `Search` patterns based on the goal's structure to find relevant lemmas.
4. Use `find_related` on key identifiers in the goal to discover nearby lemmas.
5. For each promising lemma found, try `submit_tactic` with `apply <lemma>.` or `exact <lemma>.` If it closes the goal, record it as a candidate. Reset with `step_backward`.

If the original proof uses intermediate lemmas or rewrites, search for lemmas that bridge directly from hypothesis to conclusion, skipping the intermediate steps.

### Strategy 3: Tactic chain simplification

Analyze the original proof script for collapsible patterns:

- Consecutive `intros` that can merge into one `intros x y z`.
- Sequences of `rewrite` that can become `rewrite lem1, lem2, lem3`.
- `destruct`/`induction` followed by identical tactics in each branch — replace with `destruct ...; tactic`.
- `simpl` or `unfold` followed by `reflexivity` — try `auto`, `easy`, or `now simpl`.
- Chains that `assert` an intermediate result then immediately use it — try removing the assertion and applying the final step directly.

Construct a candidate proof script from these simplifications. Submit the full tactic sequence via `submit_tactic` calls. If it closes all goals, record it as a candidate.

### Strategy 4: Combined approaches

If hammer alone did not close the full proof but closed some subgoals, and tactic simplification handled others, try combining them: keep the structural tactics (split, destruct, induction) but replace individual branches with hammer calls or direct lemma applications.

## Verify every candidate

For each candidate proof recorded above:

1. Reset the proof state to the beginning of the proof (use `step_backward` as needed or re-navigate).
2. Submit the candidate tactic sequence step by step.
3. Confirm the proof is fully closed (no remaining goals).
4. If verification fails, discard the candidate silently. Do not present unverified alternatives.

## Compare and rank alternatives

For each verified candidate, record:

- **Step count**: number of tactic steps.
- **Strategy**: which approach produced it (hammer, lemma, simplification, combined).
- **Proof script**: the full text.

Rank candidates by:

1. Fewest tactic steps (primary).
2. Readability — prefer named lemma applications over opaque hammer calls when step counts are equal.
3. Robustness — prefer proofs that reference stable library lemmas over proofs that depend on automation heuristics.

## Present results

Format your response as follows:

**If alternatives were found:**

Show the original proof first with its step count. Then show each alternative in rank order. For each alternative, show:

- The full proof script, ready to paste.
- The step count and how it compares to the original (e.g., "3 steps vs. original 8").
- Which strategy produced it.
- A brief note on tradeoffs (e.g., "Uses hammer — shorter but may break if hint databases change" or "Applies List.app_assoc directly — robust and readable").

**If no compression was found:**

Say so plainly. List which strategies were tried and why they did not produce a shorter proof.

## Handle user's choice

After presenting alternatives, wait for the user's decision:

- If the user selects an alternative (e.g., "use option 2"), replace the proof in the source file using `Edit`. Replace only the tactic body between `Proof.` and `Qed.`/`Defined.`, preserving the lemma statement and terminator.
- If the user wants to keep the original, do nothing.
- If the user asks to try again with different parameters or on a different sub-proof, restart the relevant steps.

Never modify the source file without explicit user instruction.

## Clean up

When finished (whether the user adopted an alternative or not), call `close_proof_session` to release the session.
