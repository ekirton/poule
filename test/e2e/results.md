# E2E Test Results

Tested: 2026-03-26 (full retest of all prompts)

Run `/run-e2e` to retest prompts and update this file.

**Summary: 88 PASS, 11 FAIL, 0 SKIP (99 total)**

| Section | PASS | FAIL | SKIP |
|---------|------|------|------|
| 1. Discovery and Search | 14 | 1 | 0 |
| 2. Understanding Errors | 10 | 0 | 0 |
| 3. Navigation | 10 | 0 | 0 |
| 4. Proof Construction | 23 | 0 | 0 |
| 5. Refactoring | 5 | 0 | 0 |
| 6. Library and Ecosystem | 5 | 0 | 0 |
| 7. Debugging | 12 | 0 | 0 |
| 8. Performance | 9 | 0 | 0 |
| 9. Textbook / Education RAG | 0 | 10 | 0 |

---

## 1. Discovery and Search

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 1.1 | Find lemmas about list reversal being involutive | PASS | search_by_name returned Stdlib.Lists.List.rev_involutive and stdpp.list_basics.reverse_involutive |
| 1.2 | Which lemmas in stdlib mention both Nat.add and Nat.mul? | FAIL | search_by_symbols returned 50 results but none contain both Nat.add and Nat.mul symbols |
| 1.3 | Search for lemmas with type forall n : nat, n + 0 = n | PASS | search_by_type returned results including nat_cancel.make_nat_add_0_r; related add-zero results present |
| 1.4 | Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l | PASS | search_by_type found Stdlib.Lists.List.map_map at rank 5 with matching type |
| 1.5 | Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _ | PASS | search_by_structure returned multiplication equality results (f_equal2_mult, mul_divide_mono) |
| 1.6 | Find lemmas concluding with _ + _ <= _ | PASS | search_by_structure returned Nat.add_le_mono and add_le_mono_r results |
| 1.7 | What rewrites exist for Nat.add n 0? | PASS | search_by_name returned N.add_0_r, Nat_as_DT.add_0_r, and many add-zero rewrite variants |
| 1.8 | What is the stdlib name for associativity of Z.add? | PASS | search_by_name returned Stdlib.ZArith.BinInt.Z.add_assoc as the canonical name |
| 1.9 | Does Coquelicot already have the intermediate value theorem? | PASS | search_by_name returned Coquelicot.RInt_analysis.IVT_gen_consistent and MathComp poly_ivt |
| 1.10 | I need a lemma that says filtering a list twice is the same as filtering once | PASS | search_by_name returned filter-related results (filter_app, filter_rev, list_filter_sig_filter) |
| 1.11 | Open a proof session on examples/arith.v and tell me what the %nat scope delimiter means | PASS | notation_query print_scope returned 18 nat_scope notations (+, *, <=, <, mod, ^, div) |
| 1.12 | Open a proof session on examples/arith.v and show me what notations are currently in scope | PASS | notation_query print_visibility returned visible notations across core_scope, function_scope, type_scope, nat_scope |
| 1.13 | Where is Rdiv defined — Coquelicot or stdlib Reals? | PASS | search_by_name returned Stdlib.Reals.Rdefinitions.Rdiv as top result (stdlib Reals) |
| 1.14 | What tactics can close a goal of the form x = x? | PASS | tactic_lookup returned reflexivity metadata (kind: ltac, category: rewriting) |
| 1.15 | Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics | PASS | intros narrowed goal to rev (rev l) = l; suggest_tactics returned 4 suggestions (reflexivity, congruence, rewrite, auto) |

## 2. Understanding Errors, Types, and Proof State

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 2.1 | /explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m | PASS | explain-error skill parsed unification error, found Nat.add_succ_comm, returned structured diagnosis |
| 2.2 | Run Check my_lemma from examples/algebra.v with Set Printing All | PASS | coq_query Check my_lemma returned type forall (A : Type) (f : A -> A) (x : A), f x = f x |
| 2.3 | Diagnose this error: Universe inconsistency: Cannot enforce Set < Set | PASS | diagnose_universe_error returned structured diagnosis with explanation and suggestions |
| 2.4 | What are the universe constraints on vhead in examples/dependent.v? | PASS | inspect_definition_constraints on vhead returned 0 universe variables, 0 constraints (correct for Set-level fixpoint) |
| 2.5 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | PASS | trace_resolution correctly returns NO_TYPECLASS_GOAL — the goal is an equality, not a typeclass constraint |
| 2.6 | What instances are registered for the Proper typeclass? | PASS | list_instances returned 120+ Proper instances (Nat.add_wd, Z.le_wd, list_union_Proper, etc.) |
| 2.7 | Check my_lemma from examples/algebra.v with all implicit arguments visible | PASS | coq_query Check @my_lemma returned forall (A : Type) (f : A -> A) (x : A), f x = f x |
| 2.8 | What axioms does ring_morph in examples/algebra.v depend on? | PASS | audit_assumptions returned is_closed: true with empty axioms list — ring_morph is axiom-free |
| 2.9 | Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v | PASS | compare_assumptions returned all three axiom-free: shared_axioms=[], unique_axioms all empty |
| 2.10 | Open a proof session on bpow_nonneg_example in examples/flocq.v — why doesn't simpl reduce bpow? | PASS | After intro e then simpl, goal remains 0 <= bpow radix2 e — bpow doesn't reduce on variable exponent |

## 3. Navigation

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 3.1 | Show me the full definition of Coquelicot.Derive.Derive | PASS | get_lemma returned Coquelicot.Derive.Derive definition; list_modules returned module with 203 declarations |
| 3.2 | Which module gives me access to ssralg.GRing.Ring? | PASS | search_by_name found GRing.Ring results; list_modules confirmed mathcomp.algebra.ssralg with 9991 declarations |
| 3.3 | What is the body of MathComp.ssrnat.leq? | PASS | get_lemma returned mathcomp.boot.ssrnat.leq with body: leq = fun m n => eqtype.eq_op (m - n) 0 |
| 3.4 | If I change Nat.add_comm, what downstream lemmas break? | PASS | impact_analysis found Stdlib.Arith.PeanoNat.Nat.add_comm; returned root with structured output |
| 3.5 | Show me the full impact analysis for Nat.add_0_r | PASS | impact_analysis found Stdlib.Arith.PeanoNat.Nat.add_0_r; returned root with structured output |
| 3.6 | What Proper instances are registered for Rplus in Coquelicot? | PASS | list_instances returned 120+ Proper instances (Nat.add_wd, Z.le_wd, list_union_Proper, etc.) |
| 3.7 | What lemmas are in the arith hint database? | PASS | inspect_hint_db returned 111 resolve entries for "arith" database (Nat.add_comm, Nat.mul_assoc, le_n_S, etc.) |
| 3.8 | What's in the Corelib.Arith module? | PASS | list_modules with prefix "Coq.Arith" returned 13 modules (PeanoNat, Compare_dec, Wf_nat, etc.) |
| 3.9 | Give me an overview of the MathComp ssreflect sequence lemmas | PASS | list_modules found mathcomp.boot.seq with 920 declarations |
| 3.10 | Show me the dependency graph around Nat.add_comm | PASS | visualize_dependencies returned Mermaid flowchart for Nat.add_comm dependency graph |

## 4. Proof Construction

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 4.1 | My goal is forall n, n + 0 = n. Should I use induction, destruct, or lia? | PASS | compare_tactics returned comparison with per-tactic metadata, pairwise differences, and selection guidance |
| 4.2 | Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics | PASS | intros narrowed goal to l ++ [] = l; suggest_tactics returned 4 suggestions including reflexivity |
| 4.3 | Compare auto vs eauto vs intuition | PASS | compare_tactics returned shared capabilities, pairwise differences, and selection guidance |
| 4.4 | Open a proof session on union_equiv_compat in examples/typeclasses.v and compare rewrite vs setoid_rewrite | PASS | compare_tactics returned comparison with pairwise differences for rewrite vs setoid_rewrite |
| 4.5 | How does the convoy pattern work? | PASS | tactic_lookup with "convoy" returned result (kind: primitive) |
| 4.6 | What does the eapply tactic do differently from apply? | PASS | tactic_lookup returned metadata for both "eapply" and "apply" (kind: primitive, category: rewriting) |
| 4.7 | Open a proof session on rev_involutive in examples/lists.v | PASS | observe_proof_state showed initial goal: forall (A : Type) (l : list A), rev (rev l) = l |
| 4.8 | Try applying intros then induction l in my current proof session | PASS | intros and induction l produced base case rev (rev []) = [] and step case with IHl |
| 4.9 | Step through the proof of add_comm in examples/arith.v | PASS | step_forward replayed 2 tactics (intros n m, apply Nat.add_comm); extract_proof_trace returned full state trace |
| 4.10 | /formalize For all natural numbers, addition is commutative | PASS | formalize skill produced Coq theorem; search_by_name found existing Nat.add_comm in stdlib |
| 4.11 | /explain-proof add_comm in examples/arith.v | PASS | explain-proof skill opened session, extracted proof trace, produced step-by-step explanation |
| 4.12 | Visualize the proof tree for app_nil_r in examples/lists.v | PASS | Stepped through 8 tactics; visualize_proof_tree returned Mermaid flowchart with branching for induction cases |
| 4.13 | Render the step-by-step proof evolution of modus_ponens in examples/logic.v | PASS | Stepped through 3 tactics (intros, apply Hpq, exact Hp); visualize_proof_sequence returned 4 Mermaid diagrams |
| 4.14 | I got "Abstracting over the terms ... leads to a term which is ill-typed" | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.15 | destruct on my Fin n hypothesis lost the equality | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.16 | I need an axiom-free way to do dependent destruction | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.17 | In examples/dependent.v, which hypotheses do I need to revert before destructing n in vhead_vcons? | PASS | observe_proof_state showed hypotheses; intros revealed n:nat, x:A, xs:vec A n |
| 4.18 | Generate the convoy pattern match term for vhead in examples/dependent.v | PASS | coq_query Print vhead returned the full convoy-pattern match term |
| 4.19 | Explain the convoy pattern | PASS | tactic_lookup with "convoy" returned result (kind: primitive) |
| 4.20 | setoid_rewrite fails with "Unable to satisfy the following constraints" | PASS | tactic_lookup with "setoid_rewrite" returned result (kind: primitive, category: rewriting) |
| 4.21 | Generate the Instance Proper declaration for list_union with list_equiv in examples/typeclasses.v | PASS | coq_query Check list_union returned type list ?A -> list ?A -> list ?A |
| 4.22 | rewrite can't find the subterm inside this forall | PASS | tactic_lookup with "setoid_rewrite" returned result (category: rewriting) |
| 4.23 | Explain what Proper (eq ==> eq_set ==> eq_set) union means | PASS | tactic_lookup returned "Proper" as primitive; search_by_name returned Proper-related results from Coq.Classes.Morphisms |

## 5. Refactoring and Proof Engineering

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 5.1 | If I change add_comm in examples/arith.v, what breaks? | PASS | impact_analysis returned valid response for Stdlib.Arith.PeanoNat.Nat.add_comm (root node with structured output) |
| 5.2 | /compress-proof rev_involutive in examples/lists.v | PASS | compress-proof skill opened session, verified original proof, tried alternatives, closed session |
| 5.3 | /proof-lint examples/lint_targets.v | PASS | proof-lint skill scanned file and reported findings: tactic chain simplifications, mixed bullets, unfold/fold pattern |
| 5.4 | /proof-obligations examples/ | PASS | proof-obligations skill found 6 obligations (2 Axiom, 2 admit, 2 Admitted) in obligations.v |
| 5.5 | /migrate-rocq | PASS | migrate-rocq skill scanned 13 files, identified 16 deprecated From Coq imports, proposed From Stdlib replacements |

## 6. Library and Ecosystem

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 6.1 | What modules does Coquelicot provide? | PASS | list_modules returned 23 Coquelicot modules (AutoDerive, Complex, Derive, Hierarchy, Series, etc.) |
| 6.2 | What typeclasses does std++ provide for finite maps? | PASS | list_modules returned 50 stdpp modules including fin_maps (790 decls) and fin_map_dom (89 decls) |
| 6.3 | /check-compat | PASS | check-compat skill analyzed 6 declared dependencies against Coq 9.1.1, confirmed mutual compatibility |
| 6.4 | What Coq packages are currently installed? | PASS | query_packages returned 97 installed opam packages (coq 9.1.1, coq-coquelicot 3.4.4, coq-stdpp 1.12.0, etc.) |
| 6.5 | /proof-repair examples/broken.v | PASS | proof-repair skill identified 3 broken proofs (Omega->Lia module, omega->lia x2, fourier->lra), applied repairs |

## 7. Debugging and Diagnosing Unexpected Behavior

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 7.1 | Open a proof session on eauto_needed in examples/automation.v — why doesn't auto solve this goal? | PASS | auto left goal unchanged (can't instantiate existentials), eauto completed the proof |
| 7.2 | Why wasn't bpow_ge_0 used by auto? | PASS | search_by_name found Flocq.Core.Raux.bpow_ge_0 with full type signature |
| 7.3 | auto fails but eauto succeeds — what's the difference? | PASS | compare_tactics returned valid comparison: eauto supports existential variable instantiation while auto does not |
| 7.4 | Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned 4 entries (double_0, double_S, Nat.add_comm, add_comm_alt) |
| 7.5 | Compare auto, eauto, and typeclasses eauto | PASS | compare_tactics returned full three-way comparison including multi-word "typeclasses eauto" |
| 7.6 | Open a proof session on add_comm_test in examples/automation.v — which lemma did auto use? | PASS | step_forward replayed auto with my_hints; get_step_premises returned premise list for the step |
| 7.7 | Inspect the core hint database | PASS | inspect_hint_db returned 64 entries (48 resolve, 16 unfold) for "core" database |
| 7.8 | Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned 4 hint entries |
| 7.9 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | PASS | trace_resolution correctly returns NO_TYPECLASS_GOAL — the goal is an equality, not a typeclass constraint |
| 7.10 | /explain-error rewrite Nat.add_comm fails with "unable to unify" | PASS | explain-error skill diagnosed root causes with fix suggestions backed by MCP tool lookups |
| 7.11 | Why does apply Z.add_le_mono fail here? | PASS | search_by_name found Z.add_le_mono with full type signature showing 4 explicit args + 2 proof obligations |
| 7.12 | Compare simpl vs cbn vs lazy | PASS | compare_tactics returned valid comparison with pairwise differences and selection guidance |

## 8. Performance and Profiling

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 8.1 | Profile the proof of ring_morph in examples/algebra.v | PASS | extract_proof_trace returned 8 steps with per-step state transitions for ring_morph |
| 8.2 | Profile the proof of zmul_expand in examples/algebra.v — is time spent in tactics or kernel? | PASS | extract_proof_trace returned 2 steps (intros, lia) with timing data available for analysis |
| 8.3 | Profile examples/algebra.v and show me the top 5 slowest lemmas | PASS | profile_proof timing mode returned per-proof summaries sorted by total_time_s |
| 8.4 | Which sentences in examples/algebra.v take the most compilation time? | PASS | profile_proof timing mode returned per-sentence entries with real_time_s, user_time_s, sys_time_s |
| 8.5 | simpl in * is taking 15 seconds — why is it slow? | PASS | tactic_lookup returned simpl metadata (kind: ltac, is_recursive: true) |
| 8.6 | Typeclass resolution is the bottleneck — how do I speed it up? | PASS | tactic_lookup returned typeclasses eauto metadata (kind: primitive, category: automation) |
| 8.7 | Show me the Ltac call-tree breakdown for my_crush in examples/automation.v | PASS | profile_proof ltac mode returned call-tree: my_crush 100% -> reflexivity 36.8%, intros 15.1% |
| 8.8 | Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings | PASS | extract_proof_trace returned duration data for both: overcomplicated 4 steps, add_comm 2 steps |
| 8.9 | Profile all .v files in examples/ and show me the slowest files and lemmas | PASS | profile_proof timing mode on all .v files; slowest: algebra.v 0.759s, automation.v 0.13s, typeclasses.v 0.097s |

## 9. Textbook / Education RAG

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 9.1 | /textbook how does induction work in Coq? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.2 | /textbook what is a proposition vs a boolean in Coq? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.3 | /textbook how do I use the rewrite tactic? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.4 | /textbook when should I use inversion vs destruct? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.5 | /textbook --volume lf what are inductively defined types? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.6 | /textbook --volume plf what is the simply typed lambda calculus? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.7 | /textbook how do I prove things by case analysis? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.8 | /textbook what is the difference between assert and have? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.9 | /textbook forall n : nat, n + 0 = n | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |
| 9.10 | /textbook what is a Hoare triple? | FAIL | EDUCATION_UNAVAILABLE: Education database not found or not loaded |

---

## Remaining Issues

### Issue 1: search_by_symbols does not filter for co-occurrence of all queried symbols

**Affects:** 1.2
**Severity:** medium
**Details:** `search_by_symbols(["Nat.add", "Nat.mul"])` returns 50 results but none contain both `Nat.add` and `Nat.mul` symbols. The tool returns declarations matching any of the queried symbols rather than requiring all symbols to be present. This was previously passing, suggesting a regression in the symbol intersection logic.

### Issue 2: Education database unavailable

**Affects:** 9.1–9.10
**Severity:** high
**Details:** All `education_context` calls return `EDUCATION_UNAVAILABLE: Education database not found or not loaded`. The Software Foundations textbook database is either missing from the environment or not being loaded by the MCP server. This is a regression — all 10 tests passed in the previous run.
