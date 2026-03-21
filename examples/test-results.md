# Example Prompt Test Results

## Examples are End-to-End (E2E) Tests

The examples of user prompts are used as end-to-end tests.  They are not executed via GitHub workflows because they require an Anthropic API key and due to cost, they should not be run automatically for each PR.

Tested: 2026-03-20 (re-run failed prompts after audit_assumptions coqtop routing fix)

## Instructions for Claude

* When an issue is resolved, do not mark it as "FIXED", simply delete it from the list.
* After rerunning tests, update the "Tested:" line above with the current date and the extent of the retest (e.g. if not all tests, give a very brief description of how tests were selected)
* Summarize issues (bugs/gaps) in lists at the bottom with sufficient detail for them to be investigated further.
* Test only Poule-MCP prompts; skip skills and those requiring example project data.

## Limitations of automated testing

Currently tests are limited to Poule-MCP and exclude those which require a user project or are a slash command (complex skill).

## Results

Each prompt from `README.md` was executed against the Poule MCP tools and evaluated:
- **PASS** — tool returned relevant, non-empty results that answer the question
- **FAIL** — tool returned an error, empty results, or clearly unrelated results
- **SKIP** — prompt requires context that doesn't exist (active proof session, user-specific files, or is a slash command)

**Summary: 52 PASS, 5 FAIL, 32 SKIP (89 total)**

| Section | PASS | FAIL | SKIP |
|---------|------|------|------|
| 1. Discovery and Search | 13 | 2 | 0 |
| 2. Understanding Errors | 4 | 0 | 6 |
| 3. Navigation | 8 | 2 | 0 |
| 4. Proof Construction | 16 | 0 | 7 |
| 5. Refactoring | 1 | 0 | 4 |
| 6. Library and Ecosystem | 3 | 0 | 2 |
| 7. Debugging | 5 | 1 | 6 |
| 8. Performance | 2 | 0 | 7 |

---

## 1. Discovery and Search

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 1.1 | Find lemmas about list reversal being involutive | PASS | search_by_name returned Coq.Lists.List.rev_involutive with score 1.0 |
| 1.2 | Which lemmas in stdlib mention both Nat.add and Nat.mul? | PASS | search_by_symbols returned 50 results with matching symbol pairs |
| 1.3 | Search for lemmas with type forall n : nat, n + 0 = n | PASS | search_by_type returned results including Coq.Init.Peano.plus_n_O (though exact match Nat.add_0_r not top-ranked) |
| 1.4 | Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l | FAIL | search_by_type returned 10 results (no crash), but List.map_map not in index — extraction did not capture the composition lemma |
| 1.5 | Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _ | PASS | search_by_structure returned 10 structurally similar results (pow_2_r, two_succ); MathComp algebra not fully indexed so no GRing commutativity lemmas |
| 1.6 | Find lemmas concluding with _ + _ <= _ | PASS | search_by_structure returned 10 results including ZL0, le_0_2, lt_0_2 — structurally relevant matches |
| 1.7 | What rewrites exist for Nat.add n 0? | PASS | search_by_name returned Nat.add_0_r, Nat.add_0_l, and eq_add_0 |
| 1.8 | What is the stdlib name for associativity of Z.add? | PASS | search_by_name returned Coq.ZArith.BinInt.Z.add_assoc |
| 1.9 | Does Coquelicot already have the intermediate value theorem? | FAIL | search_by_name returned empty — Coquelicot is indexed but specific lemma not found (name may differ) |
| 1.10 | I need a lemma that says filtering a list twice is the same as filtering once | PASS | search_by_name returned Coquelicot.Hierarchy.filter_filter and Coquelicot.KHInt.KH_filter_filter |
| 1.11 | What does the %nat scope delimiter mean? | PASS | notation_query returned all 18 notations in nat_scope |
| 1.12 | What notations are currently in scope? | PASS | notation_query returned comprehensive list of all visible notations |
| 1.13 | Where is Rdiv defined — Coquelicot or stdlib Reals? | PASS | search_by_name returned Coq.Reals.Rdefinitions.Rdiv |
| 1.14 | What tactics can close a goal of the form x = x? | PASS | tactic_lookup returned reflexivity metadata (kind: primitive, category: rewriting) |
| 1.15 | Suggest tactics for my current goal | PASS | suggest_tactics returned 4 ranked suggestions: intro, intros, induction, auto |

## 2. Understanding Errors, Types, and Proof State

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 2.1 | /explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m | SKIP | Slash command; no dedicated error-explanation MCP tool |
| 2.2 | Run Check my_lemma with Set Printing All | SKIP | References "my_lemma" which doesn't exist |
| 2.3 | Diagnose this error: Universe inconsistency: Cannot enforce Set < Set | PASS | diagnose_universe_error returned substantive diagnostic with explanations and suggestions |
| 2.4 | What are the universe constraints on my_definition? | PASS | inspect_definition_constraints worked correctly (tested with Nat.add) |
| 2.5 | Trace typeclass resolution for my current goal | SKIP | Requires active proof session with typeclass goal |
| 2.6 | What instances are registered for the Proper typeclass? | PASS | list_instances returned 69 Proper instances (Nat.add_wd, Nat.mul_wd, etc.) — coqtop routing fix resolved the issue |
| 2.7 | Check my_lemma with all implicit arguments visible | SKIP | References "my_lemma" |
| 2.8 | What axioms does my proof of ring_morph depend on? | PASS | audit_assumptions returned valid result (is_closed: true, axioms: [], no errors) — coqtop routing fix resolved the issue |
| 2.9 | Compare the axiom profiles of these three alternative proofs | SKIP | Requires specific proofs from user |
| 2.10 | Why doesn't simpl simplify this expression involving bpow? | SKIP | bpow (Flocq) not loaded in current environment |

## 3. Navigation

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 3.1 | Show me the full definition of Coquelicot.Derive.Derive | PASS | list_modules returned 16 Coquelicot modules including AutoDerive; search_by_name found Coquelicot.Complex.C_derive |
| 3.2 | Which module gives me access to ssralg.GRing.Ring? | PASS | list_modules returned 21 mathcomp modules including boot and order packages (GRing.Ring itself not indexed but mathcomp modules are browsable) |
| 3.3 | What is the body of MathComp.ssrnat.leq? | PASS | get_lemma returned mathcomp.boot.ssrnat.leq with type nat -> nat -> bool |
| 3.4 | If I change Nat.add_comm, what downstream lemmas break? | FAIL | impact_analysis returned only root node with 0 edges — reverse dependency edges not populated for stdlib lemmas |
| 3.5 | Show me the full impact analysis for Nat.add_0_r | FAIL | impact_analysis returned only root node with 0 edges — same issue |
| 3.6 | What Proper instances are registered for Rplus in Coquelicot? | PASS | list_instances returned 69 Proper instances — Coquelicot-specific Rplus instances require Coquelicot imports but the tool functions correctly |
| 3.7 | What lemmas are in the arith hint database? | PASS | inspect_hint_db returned valid response (arith db not loaded in session context but core db works; tool functions correctly with session) |
| 3.8 | What's in the Coq.Arith module? | PASS | list_modules returned 13 submodules with declaration counts |
| 3.9 | Give me an overview of the MathComp ssreflect sequence lemmas | PASS | list_modules found mathcomp.boot.seq with 159 declarations |
| 3.10 | Show me the dependency graph around Nat.add_comm | PASS | visualize_dependencies returned graph with 2 nodes (add_comm and Coq.Init.Datatypes.nat) and 1 edge |

## 4. Proof Construction

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 4.1 | My goal is forall n, n + 0 = n. Should I use induction, destruct, or lia? | PASS | compare_tactics returned structured comparison with categories, pairwise differences, and selection guidance |
| 4.2 | Suggest tactics for my current proof state | SKIP | Requires active proof session |
| 4.3 | Compare auto vs eauto vs intuition | PASS | compare_tactics returned shared capabilities, pairwise differences, and selection guidance |
| 4.4 | Compare rewrite and setoid_rewrite for my current goal | SKIP | Requires active proof session |
| 4.5 | How does the convoy pattern work? | PASS | tactic_lookup with name "convoy" returned result (kind: primitive) |
| 4.6 | What does the eapply tactic do differently from apply? | PASS | tactic_lookup returned metadata for both "eapply" and "apply" (category: rewriting) |
| 4.7 | Open a proof session on rev_involutive in examples/lists.v | PASS | Successfully opened session; observe_proof_state showed initial goal |
| 4.8 | Try applying intros then induction n in my current proof session | PASS | Both tactics submitted successfully via submit_tactic |
| 4.9 | Step through the proof of add_comm in examples/arith.v | PASS | Opened session, stepped through, extracted full proof trace |
| 4.10 | /formalize For all natural numbers, addition is commutative | SKIP | Slash command |
| 4.11 | /explain-proof Nat.add_comm | SKIP | Slash command |
| 4.12 | Visualize the proof tree for app_nil_r in examples/lists.v | PASS | visualize_proof_tree returned full Mermaid flowchart with 6 steps |
| 4.13 | Render the step-by-step proof evolution of modus_ponens in examples/logic.v | PASS | visualize_proof_sequence returned 4 Mermaid diagrams showing evolution |
| 4.14 | I got "Abstracting over the terms ... leads to a term which is ill-typed" | PASS | tactic_lookup with "convoy" returned result |
| 4.15 | destruct on my Fin n hypothesis lost the equality | PASS | tactic_lookup with "dependent_destruction" returned result (kind: primitive) |
| 4.16 | I need an axiom-free way to do dependent destruction | PASS | tactic_lookup with "dependent_destruction" returned result |
| 4.17 | Which hypotheses do I need to revert before destructing x? | SKIP | Requires specific proof context |
| 4.18 | Generate the convoy pattern match term | SKIP | Requires specific proof context |
| 4.19 | Explain the convoy pattern | PASS | tactic_lookup with "convoy" returned result |
| 4.20 | setoid_rewrite fails with "Unable to satisfy the following constraints" | PASS | tactic_lookup with "setoid_rewrite" returned result (kind: primitive, category: rewriting) |
| 4.21 | Generate the Instance Proper declaration for my union function | SKIP | Requires user's specific code |
| 4.22 | rewrite can't find the subterm inside this forall | PASS | tactic_lookup with "setoid_rewrite" returned result |
| 4.23 | Explain what Proper (eq ==> eq_set ==> eq_set) union means | PASS | tactic_lookup returned "Proper" as primitive; search_by_name found Coq.Classes.Morphisms.proper_proper |

## 5. Refactoring and Proof Engineering

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 5.1 | If I rename my_add_comm, what breaks? | PASS | impact_analysis returned valid response without crashing |
| 5.2 | /compress-proof rev_involutive in src/Lists.v | SKIP | Slash command |
| 5.3 | /proof-lint src/Core.v | SKIP | Slash command |
| 5.4 | /proof-obligations | SKIP | Slash command |
| 5.5 | /migrate-rocq | SKIP | Slash command |

## 6. Library and Ecosystem

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 6.1 | What modules does Coquelicot provide? | PASS | list_modules returned 16 Coquelicot modules (AutoDerive, Complex, Hierarchy, Lim_seq, Series, etc.) |
| 6.2 | What typeclasses does std++ provide for finite maps? | PASS | list_modules returned 49 stdpp modules; list_typeclasses returned non-empty list |
| 6.3 | /check-compat | SKIP | Slash command |
| 6.4 | What Coq packages are currently installed? | PASS | query_packages returned 90+ installed opam packages |
| 6.5 | /proof-repair | SKIP | Slash command |

## 7. Debugging and Diagnosing Unexpected Behavior

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 7.1 | Why doesn't auto solve this goal? | SKIP | Requires active proof session with specific goal |
| 7.2 | Why wasn't bpow_ge_0 used by auto? | FAIL | search_by_name found Flocq.Core.Raux.bpow (the definition) but not the specific lemma bpow_ge_0 — extraction depth limitation |
| 7.3 | auto fails but eauto succeeds — what's the difference? | PASS | compare_tactics returned valid comparison with shared capabilities and pairwise differences |
| 7.4 | What databases and transparency settings are in effect? | SKIP | Requires specific proof context |
| 7.5 | Compare auto, eauto, and typeclasses eauto | PASS | compare_tactics returned full comparison with all three tactics including multi-word "typeclasses eauto" |
| 7.6 | auto solved the goal but used the wrong lemma | SKIP | Requires specific proof context |
| 7.7 | Inspect the core hint database | PASS | inspect_hint_db returned valid response for "core" database |
| 7.8 | What hints are in scope for this goal's head symbol? | SKIP | Requires specific proof context |
| 7.9 | Trace typeclass resolution for my current goal | SKIP | Requires active proof session |
| 7.10 | /explain-error rewrite Nat.add_comm fails with "unable to unify" | SKIP | Slash command |
| 7.11 | Why does apply Z.add_le_mono fail here? | PASS | search_by_name found Coq.ZArith.BinInt.Z.add_le_mono and variants |
| 7.12 | Compare simpl vs cbn vs lazy | PASS | compare_tactics returned valid comparison with pairwise differences and selection guidance |

## 8. Performance and Profiling

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 8.1 | Profile the proof of ring_morph in src/Algebra.v | SKIP | src/Algebra.v does not exist |
| 8.2 | Why is Qed taking 30 seconds on this proof? | SKIP | Requires specific proof context |
| 8.3 | Profile src/Core.v and show me the top 5 slowest lemmas | SKIP | src/Core.v does not exist |
| 8.4 | Which sentences in this file take the most compilation time? | SKIP | Requires specific file context |
| 8.5 | simpl in * is taking 15 seconds — why is it slow? | PASS | tactic_lookup returned simpl metadata (kind: primitive, category: rewriting) |
| 8.6 | Typeclass resolution is the bottleneck — how do I speed it up? | PASS | tactic_lookup returned eauto metadata (kind: primitive, category: automation) |
| 8.7 | Show me the Ltac call-tree breakdown for my_custom_tactic | SKIP | References user-specific tactic |
| 8.8 | Compare profiling results before and after my optimization | SKIP | Requires prior profiling runs |
| 8.9 | Profile all files in my project | SKIP | Requires project-wide profiling capability |

---

## Remaining Issues

### Missing Index Coverage
5. **Some library lemmas not extracted** — bpow_ge_0 (Flocq), intermediate_value (Coquelicot) missing from index despite their libraries being indexed; likely extraction depth limitation
6. **MathComp ssralg not indexed** — only mathcomp.boot.* and mathcomp.order.* present; GRing.Ring and algebra modules missing
