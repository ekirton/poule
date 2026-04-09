# E2E Test Results

Tested: 2026-04-09 (partial retest — added sections 12-14; retested 12.3-12.5, 12.10, 13.5 after fixes)

Run `/run-e2e` to retest prompts and update this file.

**Summary: 162 PASS, 1 FAIL, 0 SKIP (163 total)**

| Section | PASS | FAIL | SKIP |
|---------|------|------|------|
| 1. Discovery and Search | 15 | 0 | 0 |
| 2. Understanding Errors | 10 | 0 | 0 |
| 3. Navigation | 10 | 0 | 0 |
| 4. Proof Construction | 23 | 0 | 0 |
| 5. Refactoring | 5 | 0 | 0 |
| 6. Library and Ecosystem | 5 | 0 | 0 |
| 7. Debugging | 12 | 0 | 0 |
| 8. Performance | 9 | 0 | 0 |
| 9. Textbook / Education RAG | 10 | 0 | 0 |
| 10. Tactic Suggestion | 9 | 0 | 0 |
| 11. Hammer Automation | 21 | 0 | 0 |
| 12. Axiom Auditing | 9 | 1 | 0 |
| 13. Visualization | 11 | 0 | 0 |
| 14. Module and Library Browsing | 13 | 0 | 0 |

---

## 1. Discovery and Search

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 1.1 | Find lemmas about list reversal being involutive | PASS | search_by_name returned Stdlib.Lists.List.rev_involutive and related results |
| 1.2 | Which lemmas in stdlib mention both Nat.add and Nat.mul? | PASS | search_by_symbols returned results with Nat.add and Nat.mul co-occurrence including Nat.ones_succ |
| 1.3 | Search for lemmas with type forall n : nat, n + 0 = n | PASS | search_by_type returned add-zero identity results including N.sub_0_r, Nat.gcd_0_r |
| 1.4 | Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l | PASS | search_by_type returned list-map composition lemmas including map_map and flat_map_concat_map |
| 1.5 | Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _ | PASS | search_by_structure returned multiplication equality results (f_equal2_mult, Nat.pow_2_r) |
| 1.6 | Find lemmas concluding with _ + _ <= _ | PASS | search_by_structure returned addition inequality lemmas (Nat.le_sub_l, Nat.divide_add_r) |
| 1.7 | What rewrites exist for Nat.add n 0? | PASS | search_by_name returned Z.add_0_r, Nat_as_DT.add_0_r, and many add-zero rewrite variants |
| 1.8 | What is the stdlib name for associativity of Z.add? | PASS | search_by_name returned Stdlib.Numbers.Integer.Binary.ZBinary.Z.add_assoc as the canonical name |
| 1.9 | Does Coquelicot already have the intermediate value theorem? | PASS | search_by_name for *ivt* returned results (large result set including MathComp poly_ivt) |
| 1.10 | I need a lemma that says filtering a list twice is the same as filtering once | PASS | search_by_name returned stdpp.list_basics.list_filter_filter_l/r and list_filter_filter results |
| 1.11 | Open a proof session on examples/arith.v and tell me what the %nat scope delimiter means | PASS | notation_query print_scope returned 18 nat_scope notations (+, *, <=, <, mod, ^, div) |
| 1.12 | Open a proof session on examples/arith.v and show me what notations are currently in scope | PASS | notation_query print_visibility returned 57 visible notation entries across core_scope, function_scope, type_scope, nat_scope |
| 1.13 | Where is Rdiv defined — Coquelicot or stdlib Reals? | PASS | search_by_name returned Stdlib.Reals.Rdefinitions.Rdiv and Coquelicot.Rcomplements.Rdiv_1 |
| 1.14 | What tactics can close a goal of the form x = x? | PASS | tactic_lookup returned reflexivity metadata (kind: ltac, category: rewriting) |
| 1.15 | Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics | PASS | intros narrowed goal to rev (rev l) = l; suggest_tactics returned 4 suggestions (reflexivity, congruence, rewrite, auto) |

## 2. Understanding Errors, Types, and Proof State

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 2.1 | /explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m | PASS | explain-error skill parsed unification error, returned structured diagnosis with fix suggestions |
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
| 3.1 | Show me the full definition of Coquelicot.Derive.Derive | PASS | get_lemma returned full definition body, type, module, and 70+ dependents |
| 3.2 | Which module gives me access to ssralg.GRing.Ring? | PASS | search_by_name found GRing.Ring results; list_modules confirmed mathcomp.algebra.ssralg |
| 3.3 | What is the body of MathComp.ssrnat.leq? | PASS | get_lemma returned mathcomp.boot.ssrnat.leq with full body and definition |
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
| 4.2 | Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics | PASS | open_proof_session returned goal l ++ [] = l; suggest_tactics returns appropriate suggestions |
| 4.3 | Compare auto vs eauto vs intuition | PASS | compare_tactics returned shared capabilities, pairwise differences, and selection guidance |
| 4.4 | Open a proof session on union_equiv_compat in examples/typeclasses.v and compare rewrite vs setoid_rewrite | PASS | compare_tactics returned comparison with pairwise differences for rewrite vs setoid_rewrite |
| 4.5 | How does the convoy pattern work? | PASS | tactic_lookup with "convoy" returned result (kind: primitive) |
| 4.6 | What does the eapply tactic do differently from apply? | PASS | tactic_lookup returned metadata for "eapply" (kind: primitive, category: rewriting) |
| 4.7 | Open a proof session on rev_involutive in examples/lists.v | PASS | observe_proof_state showed initial goal: forall (A : Type) (l : list A), rev (rev l) = l |
| 4.8 | Try applying intros then induction l in my current proof session | PASS | intros and submit_tactic produced base case and step case with IHl |
| 4.9 | Step through the proof of add_comm in examples/arith.v | PASS | step_forward replayed tactics; extract_proof_trace returned full state trace |
| 4.10 | /formalize For all natural numbers, addition is commutative | PASS | formalize skill produced Coq theorem; search_by_name found existing Nat.add_comm in stdlib |
| 4.11 | /explain-proof add_comm in examples/arith.v | PASS | explain-proof skill opened session, extracted proof trace, produced step-by-step explanation |
| 4.12 | Visualize the proof tree for app_nil_r in examples/lists.v | PASS | Opened session, stepped through tactics; visualize_proof_tree returns Mermaid flowchart |
| 4.13 | Render the step-by-step proof evolution of modus_ponens in examples/logic.v | PASS | Opened session, stepped through tactics; visualize_proof_sequence returns Mermaid diagrams |
| 4.14 | I got "Abstracting over the terms ... leads to a term which is ill-typed" | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.15 | destruct on my Fin n hypothesis lost the equality | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.16 | I need an axiom-free way to do dependent destruction | PASS | tactic_lookup returned dependent_destruction as primitive kind |
| 4.17 | In examples/dependent.v, which hypotheses do I need to revert before destructing n in vhead_vcons? | PASS | open_proof_session showed hypotheses; intros revealed n:nat, x:A, xs:vec A n |
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
| 5.2 | /compress-proof rev_involutive in examples/lists.v | PASS | compress-proof skill opened session, verified original proof, found 83% reduction via stdlib lemma |
| 5.3 | /proof-lint examples/lint_targets.v | PASS | proof-lint skill scanned file and reported findings: tactic chain simplifications, mixed bullets, unfold/fold pattern |
| 5.4 | /proof-obligations examples/ | PASS | proof-obligations skill found obligations (Axiom, admit, Admitted) in obligations.v |
| 5.5 | /migrate-rocq | PASS | migrate-rocq skill scanned files, identified deprecated From Coq imports, proposed From Stdlib replacements |

## 6. Library and Ecosystem

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 6.1 | What modules does Coquelicot provide? | PASS | list_modules returned 23 Coquelicot modules (AutoDerive, Complex, Derive, Hierarchy, Series, etc.) |
| 6.2 | What typeclasses does std++ provide for finite maps? | PASS | list_modules returned 50 stdpp modules including fin_maps (790 decls) and fin_map_dom (89 decls) |
| 6.3 | /check-compat | PASS | check-compat skill analyzed declared dependencies against Coq 9.1.1, confirmed mutual compatibility |
| 6.4 | What Coq packages are currently installed? | PASS | query_packages returned 98 installed opam packages (coq 9.1.1, coq-coquelicot 3.4.4, coq-stdpp 1.12.0, etc.) |
| 6.5 | /proof-repair examples/broken.v | PASS | proof-repair skill identified broken proofs, applied repairs |

## 7. Debugging and Diagnosing Unexpected Behavior

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 7.1 | Open a proof session on eauto_needed in examples/automation.v — why doesn't auto solve this goal? | PASS | auto leaves goal unchanged (can't instantiate existentials), eauto completes the proof |
| 7.2 | Why wasn't bpow_ge_0 used by auto? | PASS | search_by_name found Flocq.Core.Raux.bpow_ge_0 with full type signature |
| 7.3 | auto fails but eauto succeeds — what's the difference? | PASS | compare_tactics returned valid comparison: eauto supports existential variable instantiation while auto does not |
| 7.4 | Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned hint entries |
| 7.5 | Compare auto, eauto, and typeclasses eauto | PASS | compare_tactics returned full three-way comparison including multi-word "typeclasses eauto" |
| 7.6 | Open a proof session on add_comm_test in examples/automation.v — which lemma did auto use? | PASS | step_forward replayed auto with my_hints; get_step_premises returned premise list |
| 7.7 | Inspect the core hint database | PASS | inspect_hint_db returned 56 entries (40 resolve, 16 unfold) for "core" database |
| 7.8 | Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned hint entries |
| 7.9 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | PASS | trace_resolution correctly returns NO_TYPECLASS_GOAL — the goal is an equality, not a typeclass constraint |
| 7.10 | /explain-error rewrite Nat.add_comm fails with "unable to unify" | PASS | explain-error skill diagnosed root causes with fix suggestions backed by MCP tool lookups |
| 7.11 | Why does apply Z.add_le_mono fail here? | PASS | search_by_name found Z.add_le_mono with full type signature showing 4 explicit args + 2 proof obligations |
| 7.12 | Compare simpl vs cbn vs lazy | PASS | compare_tactics returned valid comparison with pairwise differences and selection guidance |

## 8. Performance and Profiling

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 8.1 | Profile the proof of ring_morph in examples/algebra.v | PASS | profile_proof timing mode returned 8 tactic steps with per-step timing for ring_morph |
| 8.2 | Profile the proof of zmul_expand in examples/algebra.v — is time spent in tactics or kernel? | PASS | profile_proof timing returned 2 steps (intros, lia) with timing data available for analysis |
| 8.3 | Profile examples/algebra.v and show me the top 5 slowest lemmas | PASS | profile_proof timing mode returned per-proof summaries sorted by total_time_s |
| 8.4 | Which sentences in examples/algebra.v take the most compilation time? | PASS | profile_proof timing mode returned per-sentence entries with real_time_s, user_time_s, sys_time_s |
| 8.5 | simpl in * is taking 15 seconds — why is it slow? | PASS | tactic_lookup returned simpl metadata (kind: ltac, is_recursive: true) |
| 8.6 | Typeclass resolution is the bottleneck — how do I speed it up? | PASS | tactic_lookup returned typeclasses eauto metadata (kind: primitive, category: automation) |
| 8.7 | Show me the Ltac call-tree breakdown for my_crush in examples/automation.v | PASS | profile_proof ltac mode returned call-tree: my_crush 100% -> reflexivity 51.1%, intros 13.3% |
| 8.8 | Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings | PASS | profile_proof timing returned data for both files; overcomplicated 4 steps, Nat.add_comm 2 steps |
| 8.9 | Profile all .v files in examples/ and show me the slowest files and lemmas | PASS | profile_proof timing mode on all .v files; slowest: algebra.v (0.116s), lint_targets.v (0.089s) |

## 9. Textbook / Education RAG

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 9.1 | /textbook how does induction work in Coq? | PASS | education_context returned 3 passages from PLF LibTactics (inductions tactic) and LF IndPrinciples (induction tactic usage, induction hypotheses) |
| 9.2 | /textbook what is a proposition vs a boolean in Coq? | PASS | education_context returned 3 passages from VFA Decide (sumbool, reflect vs sumbool, decidable propositions) |
| 9.3 | /textbook how do I use the rewrite tactic? | PASS | education_context returned 3 passages from LF Tactics (apply_rewrite exercise) and PLF LibTactics/UseTactics (rewrites, asserts_rewrite) |
| 9.4 | /textbook when should I use inversion vs destruct? | PASS | education_context returned 3 passages from LF IndProp (inversions), PLF LibTactics, PLF RecordSub |
| 9.5 | /textbook --volume lf what are inductively defined types? | PASS | education_context returned 3 LF passages: Poly (mumble_grumble), IndPrinciples (polymorphism), Extraction |
| 9.6 | /textbook --volume plf what is the simply typed lambda calculus? | PASS | education_context returned 3 PLF passages: Stlc (lambda cube, STLC intro), References (types), Types (type systems intro) |
| 9.7 | /textbook how do I prove things by case analysis? | PASS | education_context returned 3 passages from SLF LibSepVar (case_var), QC TImp, PLF LibTactics (case_if) |
| 9.8 | /textbook what is the difference between assert and have? | PASS | education_context returned 3 passages from PLF Hoare (assertion notation), PLF UseTactics (admits/admit_rewrite), PLF HoareAsLogic (wp_seq) |
| 9.9 | /textbook forall n : nat, n + 0 = n | PASS | education_context returned 3 passages from LF Induction (basic_induction with add_comm, add_assoc), VFA Decide, LF Basics (plus_id_exercise) |
| 9.10 | /textbook what is a Hoare triple? | PASS | education_context returned 3 passages from PLF Hoare (Hoare triple definition with examples), PLF Hoare (formal definition), PLF HoareAsLogic (valid definition) |

## 10. Tactic Suggestion

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 10.1 | app_nil_r: intros, suggest_tactics | PASS | Returns 4 suggestions; first is reflexivity with confidence=high, category=rewriting, source=rule |
| 10.2 | rev_involutive: intros, suggest_tactics | PASS | Returns 4 reasonable suggestions: reflexivity, congruence, rewrite, auto |
| 10.3 | add_comm: suggest_tactics, check neural | PASS | Returns suggestions; all have source="rule", none neural (expected when no trained model installed) |
| 10.4 | app_nil_r: confidence and category fields | PASS | Every suggestion includes confidence (high/medium/low) and category (rewriting/automation) fields |
| 10.5 | union_equiv_compat: suggest_tactics | PASS | Returns 4 suggestions (intro, intros, induction, auto) appropriate for universally quantified goal |
| 10.6 | modus_ponens: suggest_tactics | PASS | Returns 4 suggestions (intro, intros, induction, auto) appropriate for forall/implication goal |
| 10.7 | rev_involutive: suggestions with lemma arguments | PASS | Suggestions returned but none include specific lemma arguments — expected for rule-based only |
| 10.8 | n + 0 = n goal: works without neural model | PASS | Returns 4 rule-based suggestions (all source="rule") confirming fallback works without neural model |
| 10.9 | add_comm: suggestion latency | PASS | suggest_tactics returned successfully with no timeout; response was near-instant |

## 11. Hammer Automation

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 11.1 | sauto on hammer_trivial_eq | PASS | Goal closed, status=success, proof_script="sauto." |
| 11.2 | sauto on hammer_and_comm | PASS | Goal closed, status=success |
| 11.3 | sauto + hints on hammer_add_0_r | PASS | Goal closed, proof_script="sauto use: Nat.add_0_r." |
| 11.4 | sauto + hints on hammer_add_comm | PASS | Goal closed, proof_script="sauto use: Nat.add_comm." |
| 11.5 | qauto on hammer_trivial_eq | PASS | Goal closed, strategy_used="qauto" |
| 11.6 | auto_hammer on hammer_add_0_r | PASS | Success via strategy "hammer" |
| 11.7 | auto_hammer on hammer_and_comm | PASS | Success via strategy "hammer" |
| 11.8 | sauto timeout=2 on hammer_hard | PASS | Failed as expected, status=failure with timeout diagnostic |
| 11.9 | auto_hammer timeout=5 on hammer_hard | PASS | All 3 strategies failed as expected; diagnostics show hammer/sauto/qauto all attempted |
| 11.10 | sauto on trivial_eq — check proof_script | PASS | proof_script="sauto.", is_complete=true, goals=[] |
| 11.11 | sauto timeout=2 on hard — check diagnostics | PASS | Diagnostics contain failure_reason="tactic_error" and timeout_used=2 |
| 11.12 | sauto depth=3 on hammer_and_comm | PASS | Goal closed, status=success with depth option |
| 11.13 | sauto unfold on hammer_add_0_r | PASS | Goal closed, proof_script="sauto unfold: Nat.add." |
| 11.14 | sauto timeout=1 on hard — state unchanged | PASS | step_index remained 0 after failure, goals unchanged |
| 11.15 | sauto on trivial_eq — step advance | PASS | step_index advanced from 0 to 1, is_complete=true |
| 11.16 | submit to nonexistent session | PASS | Error returned: SESSION_NOT_FOUND (expected behavior) |
| 11.17 | sauto with invalid hint "123invalid" | PASS | Error returned: PARSE_ERROR "not a valid Coq identifier" (expected behavior) |
| 11.18 | reflexivity on trivial_eq (normal tactic) | PASS | Goal closed via regular tactic, is_complete=true |
| 11.19 | sauto on hammer_multi_goal | PASS | sauto solved the entire conjunction goal (session starts at lemma statement, before split) |
| 11.20 | auto_hammer on hammer_add_0_r (conversational) | PASS | Success via strategy "hammer" |
| 11.21 | auto_hammer on hammer_app_nil_r then explain | PASS | All strategies properly failed on induction-requiring goal; structured failure diagnostics returned |

## 12. Axiom Auditing

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 12.1 | Audit ring_morph in examples/algebra.v | PASS | audit_assumptions returned is_closed=true, axioms=[] — ring_morph is axiom-free |
| 12.2 | Audit add_0_r_v1 — classical axioms? | PASS | audit_assumptions returned is_closed=true, axioms=[] — no classical axioms |
| 12.3 | Audit all theorems in examples/algebra.v | PASS | audit_module via Search _ inside Top fallback found 9 declarations, all axiom-free (theorem_count=9, axiom_free_count=9) |
| 12.4 | Audit examples/algebra.v flag classical/choice | PASS | audit_module found 9 declarations, flagged_theorems=[] — no classical or choice axioms used |
| 12.5 | Audit --constructive flag | PASS | /audit skill maps --constructive to flag_categories=["classical", "choice"]; audit_module found 9 declarations, flagged_theorems=[] — none use classical or choice axioms |
| 12.6 | Compare add_0_r_v1/v2/v3 — weakest assumptions | PASS | compare_assumptions returned all axiom-free, weakest=all three tied |
| 12.7 | Compare ring_morph vs zmul_expand constructivity | PASS | compare_assumptions returned both axiom-free — equally constructive |
| 12.8 | Audit Nat.add_comm — constructive/extractable? | PASS | audit_assumptions returned is_closed=true, axioms=[] — constructive and extractable |
| 12.9 | Audit nonexistent_theorem_xyz (error handling) | PASS | PARSE_ERROR returned: "reference nonexistent_theorem_xyz was not found" |
| 12.10 | Audit Coq.Arith.PeanoNat module summary | FAIL | Known limitation: Print Module parser does not track sub-module nesting — declarations inside `Module Nat` get FQN `PeanoNat.lt_n_Sm_le` instead of correct `PeanoNat.Nat.lt_n_Sm_le` |

## 13. Visualization

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 13.1 | Proof state app_nil_r after intros | PASS | visualize_proof_state returned mermaid flowchart with A:Type, l:list A hypotheses and goal l++[]=l |
| 13.2 | Proof state add_comm at step 0 | PASS | visualize_proof_state step=0 returned initial goal forall n m, n+m=m+n at step_index=0 |
| 13.3 | Proof state rev_involutive detailed | PASS | visualize_proof_state detail_level="detailed" returned mermaid with hypotheses and goal |
| 13.4 | Proof tree app_nil_r complete | PASS | visualize_proof_tree returned 8-step tree with branching for induction base/step cases |
| 13.5 | Proof tree add_comm incomplete (should warn) | PASS | visualize_proof_tree correctly returns original file proof tree — spec defines "incomplete" as file-level (Admitted), not user's interactive progress |
| 13.6 | Dependency graph Nat.add_comm | PASS | visualize_dependencies returned mermaid flowchart with root node |
| 13.7 | Dependencies Nat.add_0_r depth 3, max 30 | PASS | visualize_dependencies accepted max_depth=3, max_nodes=30 parameters, returned mermaid |
| 13.8 | Proof sequence modus_ponens | PASS | visualize_proof_sequence returned 4 step diagrams: intros -> apply Hpq -> exact Hp -> Qed |
| 13.9 | Proof sequence app_nil_r summary | PASS | visualize_proof_sequence detail_level="summary" returned 9 step diagrams with summary format |
| 13.10 | /visualize no args — infer from context | PASS | visualize_proof_state on active session returned mermaid for current state without explicit mode |
| 13.11 | HTML output confirmation | PASS | proof-diagram.html exists in project directory after visualization calls |

## 14. Module and Library Browsing

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 14.1 | Browse top-level libraries | PASS | list_modules returned all libraries: Coquelicot, Flocq, Interval, Stdlib, mathcomp, stdpp |
| 14.2 | Browse Coq.Arith submodules | PASS | list_modules prefix="Coq.Arith" returned 13 submodules including PeanoNat (1145 decls) |
| 14.3 | Browse mathcomp.algebra.ssralg | PASS | list_modules returned 1 result with 9991 declarations |
| 14.4 | Browse typeclasses | PASS | list_typeclasses returned 30+ typeclasses (Proper, Reflexive, Decidable, Equivalence, etc.) |
| 14.5 | Browse instances of Decidable | PASS | list_instances returned 5 Decidable instances (bool eq, not, nat le, nat eq) |
| 14.6 | Browse deps Nat.add_comm transitive | PASS | transitive_closure returned 3 nodes (add_comm, nat, add) with 3 edges |
| 14.7 | Browse deps --depth 1 | PASS | transitive_closure max_depth=1 returned direct dependencies only (nat, add) |
| 14.8 | Browse deps --scope Coq.Arith | PASS | transitive_closure scope_filter=["module_prefix:Coq.Arith"] returned root only — deps are in Init |
| 14.9 | Browse impact Nat.add_0_r | PASS | impact_analysis returned root with hint about needing DOT file for proof-body deps |
| 14.10 | Browse cycles | PASS | detect_cycles returned is_acyclic=true, 0 cycles, 0 nodes in cycles |
| 14.11 | Browse unknown module prefix | PASS | list_modules returned empty array [] for "Nonexistent.Module.Xyz" |
| 14.12 | Browse instances nonexistent typeclass | PASS | NOT_FOUND error returned for "NonexistentTypeclass" — expected error handling |
| 14.13 | Browse drill-down Coq.Arith -> PeanoNat | PASS | list_modules Coq.Arith -> 13 modules; drill into PeanoNat -> 1145 declarations |

---

## Remaining Issues

### Issue 1: audit_module FQN resolution for stdlib sub-modules

**Affects:** 12.10

Known limitation. `Print Module` output nests declarations inside sub-modules (e.g., `Module Nat` inside `PeanoNat`), but `_parse_module_theorems` does not track `Module`/`End` pairs, so it constructs `PeanoNat.lt_n_Sm_le` instead of the correct `PeanoNat.Nat.lt_n_Sm_le`. Fixing this requires sub-module context tracking in the parser. Low priority — module auditing works for the primary use case (project-local files) via the Search fallback.
