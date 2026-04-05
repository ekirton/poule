# Coq Tactic Reference

A reference for the tactic families observed in the tactic prediction training corpus (140,358 steps across six Coq libraries). Tactics are grouped by role. Where SSReflect provides a materially different version of a standard tactic, both are listed.

This document covers the state of the art in Coq/Rocq tactic language — it does not discuss or propose the product.

---

## 1. Introduction Tactics

Tactics that build proof terms by supplying constructors, witnesses, or direct proof terms.

**intros / intro** — Moves hypotheses and universally quantified variables from the goal into the proof context. `intro x` introduces one name; `intros x y H` introduces several. The primary tactic for stripping the outermost `forall` or implication from the goal. (Training frequency: 7.6%, rank 3.)

**split** — When the goal is a conjunction `A /\ B` (or any inductive with exactly one multi-argument constructor), replaces the goal with one subgoal per argument. (Training frequency: 1.3%.)

**left / right** — When the goal is a disjunction `A \/ B`, selects the left or right disjunct as the new goal, discarding the other.

**exists** — When the goal is an existential `exists x, P x`, supplies a witness `t` and replaces the goal with `P t`. (Training frequency: 1.7%.)

**eexists** — Like `exists` but introduces an existential variable as the witness, deferring instantiation to later unification.

**constructor / econstructor** — Applies the first matching constructor of an inductive goal. `econstructor` allows constructor arguments to remain as existential variables.

**exact** — Closes the goal by providing a proof term whose type matches the goal exactly. (Training frequency: 1.5%.)

---

## 2. Elimination Tactics

Tactics that decompose hypotheses or terms of inductive type.

**destruct** — Performs case analysis on a term of inductive type, generating one subgoal per constructor. Does not generate induction hypotheses. (Training frequency: 2.7%.)

**induction** — Performs structural induction on a term of inductive type. Generates one subgoal per constructor and adds an induction hypothesis in recursive cases.

**case (Ltac)** — Case analysis by applying the term's recursor. Unlike `destruct`, does not automatically introduce constructor arguments into the context.

**elim (Ltac)** — Applies the appropriate elimination principle (`_ind`, `_rec`, `_rect`) to a term. Lower-level than `induction`; the user must manage introduction of resulting variables. (Training frequency: 1.5%.)

**inversion** — Analyzes a hypothesis of inductive type by unifying with each constructor, deriving equalities between indices. Adds equalities and constructor arguments to the context; eliminates impossible cases automatically.

**discriminate** — Closes a goal when the context contains a hypothesis equating terms built from different constructors (e.g., `S n = O`). Exploits disjointness of constructors.

**injection** — When a hypothesis equates terms built from the same constructor, derives equalities between corresponding arguments (exploiting injectivity) and adds them to the context.

---

## 3. Rewriting Tactics

Tactics that transform the goal or hypotheses by replacing subterms.

**rewrite** — Given a lemma of the form `a = b` (or an iff), replaces occurrences of `a` with `b` in the goal. `rewrite <-` rewrites right-to-left. Accepts a list of rewrite rules applied in sequence. (Training frequency: 19.2%, rank 1.)

**replace** — Replaces a subterm `t1` in the goal with `t2`, generating a subgoal `t1 = t2` to justify the replacement. (Training frequency: 1.5%.)

**simpl** — Reduces the goal using beta-iota-zeta-delta reduction with heuristics to avoid over-expansion. Prefers terms that look "simpler." (Training frequency: 1.4%.)

**unfold** — Delta-reduces specified constants in the goal, replacing them with their definitions. (Training frequency: 3.7%.)

**change** — Replaces the goal (or a subterm) with a definitionally equal term. Coq verifies convertibility; no subgoal is generated.

**pattern** — Beta-expands a subterm: transforms `G[t]` into `(fun x => G[x]) t`. Used to prepare the goal for `apply` or `rewrite`.

**subst** — Finds hypotheses of the form `x = e` where `x` is a variable, substitutes `e` for `x` everywhere, and clears the hypothesis and variable.

**f_equal** — When the goal is `f a = f b`, reduces it to `a = b`. Generalizes to multi-argument functions.

**congruence** — A decision procedure for equalities in the theory of uninterpreted functions with constructors. Also handles discriminate- and injection-like reasoning automatically.

**reflexivity** — Closes a goal of the form `t = t`, including goals that are reflexive up to computation (definitional equality).

**symmetry** — Transforms a goal `a = b` into `b = a`. Can target hypotheses with `symmetry in H`.

**transitivity** — Replaces a goal `a = c` with two subgoals `a = b` and `b = c`, where `b` is a user-supplied intermediate term.

---

## 4. Hypothesis and Context Management

Tactics that manipulate hypotheses, introduce intermediate results, or restructure the proof context.

**apply** — Matches the conclusion of a lemma against the current goal. If it unifies, replaces the goal with subgoals for the lemma's premises. This is backward reasoning. (Training frequency: 17.5%, rank 2.)

**eapply** — Like `apply` but leaves unresolvable arguments as existential variables rather than failing.

**have (Ltac)** — Forward reasoning: `have H : T` generates a subgoal to prove `T`, then adds `H : T` to the context for the remaining proof. (Training frequency: 3.0%.)

**assert** — Introduces a new hypothesis by requiring the user to prove it. `assert (H : P)` creates two subgoals: prove `P`, then continue with `H : P` in the context. (Training frequency: 2.0%.)

**enough** — Like `assert` but with reversed subgoal order: continue with `H : P` assumed first, prove `P` second.

**pose** — Introduces a local definition `x := t` into the context without creating a proof obligation. The body remains transparent.

**set** — Like `pose`, but also replaces occurrences of the defined term in the goal with the new name.

**specialize** — Instantiates a universally quantified hypothesis with given arguments. `specialize (H a b)` replaces `H` with `H a b`.

**generalize** — The inverse of `intro`: moves a term from the goal back into a universally quantified position. `generalize t` transforms `G[t]` into `forall x, G[x]`. Often used before `induction` to strengthen the induction hypothesis.

**revert** — Moves a named hypothesis from the context back into the goal as a universal quantification or implication. The inverse of `intros`.

**remember** — Replaces a subterm `t` with a fresh variable `x` and adds the equation `x = t` to the context. Useful before `destruct` or `induction` to preserve information about the original term.

**cut** — Transforms a goal `G` into two subgoals: `P -> G` and `P`. Less commonly used than `assert` or `have`.

**clear** — Removes named hypotheses from the proof context. Fails if any remaining hypothesis or the goal depends on the cleared name.

**rename** — Renames a hypothesis in the context. `rename H into H'`.

---

## 5. Automation Tactics

Tactics that search for proofs automatically.

**auto** — Searches for a proof by combining `intros`, `apply`, and hint databases (default: `core`). Bounded depth search (default 5). Fails silently if no proof is found. (Training frequency: 4.1%.)

**eauto** — Like `auto` but uses `eapply`, allowing existential variables during search. Strictly more powerful but potentially slower.

**trivial** — A restricted `auto` that only tries depth-1 searches. Intended for goals solvable by a single hint application.

**tauto** — A decision procedure for intuitionistic propositional logic. Handles conjunctions, disjunctions, implications, negation, `True`, and `False` without user-supplied lemmas.

**intuition** — Extends `tauto` by decomposing propositional structure, then applying a solver (default `auto`) to remaining atomic goals.

**firstorder** — A decision procedure for first-order intuitionistic logic. Extends `tauto`/`intuition` with quantifier handling. Can be slow on large goals.

**decide** — Solves goals whose type is decidable by computing a boolean decision procedure.

**now** — Runs a tactic then immediately calls `easy` on all resulting subgoals. Fails if any subgoal remains.

**easy** — A composite solver that tries `trivial`, `reflexivity`, `symmetry`, `assumption`, `contradiction`, `discriminate`, and recursive decomposition.

**assumption** — Closes the goal if it exactly matches a hypothesis in the context (up to definitional equality).

---

## 6. Arithmetic and Algebraic Decision Procedures

**lia** — (Linear Integer Arithmetic.) A complete decision procedure for linear arithmetic over `Z` and `nat`. Handles equalities, inequalities, addition, subtraction, and multiplication by constants.

**omega** — Deprecated predecessor of `lia`. A decision procedure for Presburger arithmetic. Removed in recent Coq versions; `lia` is the replacement.

**ring** — Solves equalities in commutative (semi)rings by normalizing both sides to a canonical form. Works for `nat`, `Z`, `Q`, `R`, and user-declared ring structures. Does not handle inequalities.

**field** — Extends `ring` to field structures, handling division. Generates side conditions requiring denominators to be nonzero.

---

## 7. Contradiction and Absurdity

**exfalso** — Replaces the current goal with `False`. Used when the goal is provable only via a contradiction in the hypotheses.

**absurd** — Given a proposition `P`, generates two subgoals: prove `P` and prove `~ P`. The contradiction closes the original goal.

**contradiction** — Searches the context for `H : P` and `H' : ~ P`, or `H : False`, and closes the goal.

---

## 8. Proof Structure and Management

### Vernacular Commands

**Proof** — Opens the proof body of a theorem, lemma, or definition. Marks the transition from statement to proof.

**Qed** — Closes and saves a completed proof, making the proof term opaque (not reducible). Fails if obligations remain.

**Defined** — Like `Qed` but makes the proof term transparent (reducible). Used when the proof term is needed for computation.

**Admitted** — Closes an incomplete proof by accepting the statement as an axiom. Compromises soundness. Used as a development placeholder.

**admit** — A tactic that closes the current subgoal without proof. Unlike `Admitted` (which closes the entire proof), `admit` handles a single subgoal.

### Bullets and Braces

These are not tactics but proof structuring notations that control subgoal focusing. They appear in the training data as tactic-position tokens.

**- (bullet)** — Focuses on the first subgoal among siblings. Each `-` handles exactly one subgoal; the proof must use one bullet per sibling. (Training frequency: 2.3%.)

**+ (bullet)** — A second-level bullet for subgoals nested within a `-` block. (Training frequency: 1.0%.)

**\* (bullet)** — A third-level bullet for further nesting within `+` blocks. Deeper nesting uses `--`, `++`, `**`, etc.

**{ } (curly braces)** — Focus the first subgoal inside `{ ... }`. The closing `}` fails if the subgoal is not fully solved. Can nest to arbitrary depth. (Training frequency: 2.0%.)

---

## 9. SSReflect Tactics

SSReflect (Small Scale Reflection) is a tactic language developed for the Mathematical Components library. It emphasizes positional (stack-based) reasoning and boolean reflection. SSReflect tactics operate on the top of the goal stack and are combined with switches (suffixes) for introduction, simplification, and view application.

**move** — The identity tactic, used as a vehicle for switches. `move=> x H` introduces variables; `move: H` reverts hypotheses. By itself, `move` does nothing. (Training frequency: `move=>` 2.8%, `move` 1.2%.)

**case (SSReflect)** — Case analysis on the top element of the goal stack. Unlike Ltac `destruct`, operates positionally and is combined with `=>` to name or decompose results. (Training frequency: 2.7%.)

**elim (SSReflect)** — Applies the induction principle to the top element of the goal stack. Combined with switches for naming and simplification.

**apply (SSReflect)** — Bidirectional application: can apply a lemma backward (matching the goal) or forward (matching a hypothesis). Supports views and chaining with `in`.

**rewrite (SSReflect)** — Extended rewriting supporting multiple rewrite steps, occurrence selection, conditional rewriting, and pattern targeting in a single invocation. `rewrite /t` unfolds `t`; `rewrite -/t` folds it.

**have (SSReflect)** — Forward reasoning. `have H : T` opens a subgoal for `T`, then adds `H : T` to the context. Supports inline proof with `have H : T by tac` and forward application with `have := lemma arg1 arg2`.

**suff** — ("suffices") Reverses the burden of proof. `suff H : P` proves the main goal assuming `P` first, then proves `P` second. The dual of `have`.

**wlog** — ("without loss of generality") Introduces a generalization step: `wlog H : x y / P` asks you to prove the general case reduces to the case where `P` holds, then prove the goal under `P`.

**congr** — Reduces a goal `f a1 ... an = f b1 ... bn` to equalities between corresponding arguments. Supports a numeric depth argument for deeper congruence.

**unlock** — Unfolds definitions locked with the SSReflect `lock`/`locked` mechanism. Locked definitions are opaque to normal reduction; `unlock` selectively restores transparency.

---

## 10. SSReflect Tacticals and View Modifiers

SSReflect tacticals are suffixes appended to tactics that control post-processing of the proof state.

**/= (simplification)** — Applies `simpl` after the tactic executes. `case/=` performs case analysis then simplifies.

**// (trivial closer)** — Attempts to close trivial subgoals using a default solver (typically `done`). Subgoals it cannot solve remain.

**//= (simplify and close)** — Combines `/=` and `//`: simplifies, then attempts to close trivial subgoals. A common SSReflect idiom for dispatching easy cases.

**=> (introduction pattern)** — Names or decomposes results produced by the preceding tactic. `move=> x [H1 H2]` introduces a variable then destructs the next hypothesis.

**-> (rewrite right)** — An introduction pattern that rewrites an introduced equality left-to-right and clears it. `move=> ->` introduces `x = t` and substitutes throughout.

**<- (rewrite left)** — Like `->` but rewrites right-to-left.

**/eqP (view)** — Applies the `eqP` reflection lemma, converting between boolean equality (`x == y = true`) and propositional equality (`x = y`).

**/andP (view)** — Applies the `andP` reflection lemma, converting `b1 && b2 = true` to the propositional conjunction.

**/orP (view)** — Applies the `orP` reflection lemma, converting `b1 || b2 = true` to a propositional disjunction for case splitting.

---

## References

- The Coq/Rocq Reference Manual, "Tactics" chapter. https://coq.inria.fr/doc/
- Gonthier, G. and Mahboubi, A. "An introduction to small scale reflection in Coq." *Journal of Formalized Reasoning*, 3(2), 2010.
- Mathematical Components library documentation. https://math-comp.github.io/
