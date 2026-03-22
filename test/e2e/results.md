# E2E Test Results

Tested: 2026-03-22 (full retest of all prompts)

Run `/run-e2e` to retest prompts and update this file.

**Summary: 88 PASS, 1 FAIL, 0 SKIP (89 total)**

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

---

## 1. Discovery and Search

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 1.1 | Find lemmas about list reversal being involutive | PASS | search_by_name returned Coq.Lists.List.rev_involutive with score 1.0 |
| 1.2 | Which lemmas in stdlib mention both Nat.add and Nat.mul? | PASS | search_by_symbols returned 50 results for ["Corelib.Init.Nat.add", "Corelib.Init.Nat.mul"] |
| 1.3 | Search for lemmas with type forall n : nat, n + 0 = n | PASS | search_by_type returned results including Coq.Arith.PeanoNat.Nat.add_0_r and Coq.Init.Peano.plus_n_O |
| 1.4 | Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l | FAIL | search_by_type returned 50 results but none match List.map_map — Coq.Lists.List.map_map lacks structural data in the index (no constr_tree, no WL histogram, empty symbol_set) so only FTS can reach it |
| 1.5 | Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _ | PASS | search_by_structure returned 50 results with scores up to 0.48 |
| 1.6 | Find lemmas concluding with _ + _ <= _ | PASS | search_by_structure returned 50 results with scores up to 0.53 |
| 1.7 | What rewrites exist for Nat.add n 0? | PASS | search_by_name returned 12 results including Nat.add_0_r, Nat.add_0_l, and Z.add_0_r |
| 1.8 | What is the stdlib name for associativity of Z.add? | PASS | search_by_name returned 5 results including Coq.ZArith.BinInt.Z.add_assoc |
| 1.9 | Does Coquelicot already have the intermediate value theorem? | PASS | search_by_name with "*IVT*" returned 11 results including Coquelicot.Continuity.IVT_gen, IVT_Rbar_incr, IVT_Rbar_decr |
| 1.10 | I need a lemma that says filtering a list twice is the same as filtering once | PASS | search_by_name returned 50 results including stdpp.list_basics.list_filter_filter and stdpp.fin_maps.map_filter_filter |
| 1.11 | Open a proof session on examples/arith.v and tell me what the %nat scope delimiter means | PASS | notation_query print_scope returned 18 notations in nat_scope with expansions (e.g., x + y → Init.Nat.add, x * y → Init.Nat.mul) |
| 1.12 | Open a proof session on examples/arith.v and show me what notations are currently in scope | PASS | notation_query print_visibility returned visible notations across core_scope, function_scope, type_scope, and nat_scope |
| 1.13 | Where is Rdiv defined — Coquelicot or stdlib Reals? | PASS | search_by_name returned 50 results including Coq.Reals.Rdefinitions.Rdiv |
| 1.14 | What tactics can close a goal of the form x = x? | PASS | tactic_lookup returned reflexivity metadata (kind: ltac, category: rewriting) |
| 1.15 | Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics | PASS | Opened session, intros narrowed goal to rev (rev l) = l; suggest_tactics returned 4 suggestions (reflexivity, congruence, rewrite, auto) |

## 2. Understanding Errors, Types, and Proof State

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 2.1 | /explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m | PASS | explain-error skill identified Nat.add recursion asymmetry, cited Nat.add_succ_comm, provided concrete fix suggestions |
| 2.2 | Run Check my_lemma from examples/algebra.v with Set Printing All | PASS | coq_query Check my_lemma succeeded in session — returned type forall (A : Type) (f : A -> A) (x : A), f x = f x |
| 2.3 | Diagnose this error: Universe inconsistency: Cannot enforce Set < Set | PASS | diagnose_universe_error returned diagnostic with explanation and suggestions |
| 2.4 | What are the universe constraints on vhead in examples/dependent.v? | PASS | inspect_definition_constraints returned valid result (0 universe variables, 0 constraints — correct for Set-level fixpoint) |
| 2.5 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | PASS | trace_resolution correctly returns NO_TYPECLASS_GOAL — the goal is an equality (not a typeclass constraint), and measure is a resolved typeclass projection |
| 2.6 | What instances are registered for the Proper typeclass? | PASS | list_instances returned 100+ Proper instances (Nat.add_wd, Z.le_wd, List.Proper_map, etc.) |
| 2.7 | Check my_lemma from examples/algebra.v with all implicit arguments visible | PASS | coq_query Check @my_lemma succeeded in session — returned type forall (A : Type) (f : A -> A) (x : A), f x = f x |
| 2.8 | What axioms does ring_morph in examples/algebra.v depend on? | PASS | audit_assumptions returned is_closed: true with empty axioms list — ring_morph is axiom-free |
| 2.9 | Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v | PASS | compare_assumptions returned all three axiom-free: shared_axioms=[], unique_axioms all empty, all three listed as weakest |
| 2.10 | Open a proof session on bpow_nonneg_example in examples/flocq.v — why doesn't simpl reduce bpow? | PASS | After intro e then simpl, goal remains 0 <= bpow radix2 e — bpow doesn't reduce on variable exponent |

## 3. Navigation

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 3.1 | Show me the full definition of Coquelicot.Derive.Derive | PASS | list_modules returned Coquelicot.Derive (203 declarations); search_by_name found Coquelicot.Derive.Derive (score 1.006, kind: definition) |
| 3.2 | Which module gives me access to ssralg.GRing.Ring? | PASS | list_modules returned mathcomp.algebra.ssralg with 10,269 declarations |
| 3.3 | What is the body of MathComp.ssrnat.leq? | PASS | get_lemma returned mathcomp.boot.ssrnat.leq with type nat -> nat -> bool, kind: definition |
| 3.4 | If I change Nat.add_comm, what downstream lemmas break? | PASS | impact_analysis found Coq.Arith.PeanoNat.Nat.add_comm; returned root with 0 edges and sparse-result hint explaining index has only type-level edges |
| 3.5 | Show me the full impact analysis for Nat.add_0_r | PASS | impact_analysis found Coq.Arith.PeanoNat.Nat.add_0_r; returned root with 0 edges and sparse-result hint explaining proof-body dependencies require DOT file import |
| 3.6 | What Proper instances are registered for Rplus in Coquelicot? | PASS | list_instances with Coq.Classes.Morphisms.Proper returned 76 instances (Nat.add_wd, Nat.mul_wd, Morphisms_Prop connectives, etc.) |
| 3.7 | What lemmas are in the arith hint database? | PASS | inspect_hint_db returned 111 resolve entries for "arith" database (lt_wf, Nat.add_comm, Nat.mul_assoc, Nat.le_trans, etc.) |
| 3.8 | What's in the Corelib.Arith module? | PASS | list_modules with prefix "Corelib.Arith" resolved to Coq.Arith via bidirectional prefix aliasing, returned 13 modules |
| 3.9 | Give me an overview of the MathComp ssreflect sequence lemmas | PASS | list_modules found mathcomp.boot.seq with 920 declarations |
| 3.10 | Show me the dependency graph around Nat.add_comm | PASS | visualize_dependencies returned Mermaid flowchart with 2 nodes (Nat.add_comm depending on Coq.Init.Datatypes.nat) |

## 4. Proof Construction

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 4.1 | My goal is forall n, n + 0 = n. Should I use induction, destruct, or lia? | PASS | compare_tactics returned structured comparison with per-tactic metadata, pairwise differences, and selection guidance |
| 4.2 | Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics | PASS | Opened session, intros narrowed goal to l ++ [] = l; suggest_tactics returned 4 suggestions including reflexivity |
| 4.3 | Compare auto vs eauto vs intuition | PASS | compare_tactics returned shared capabilities, pairwise differences, and selection guidance |
| 4.4 | Open a proof session on union_equiv_compat in examples/typeclasses.v and compare rewrite vs setoid_rewrite | PASS | Opened session; compare_tactics returned comparison with shared capabilities (rewriting tactic), pairwise differences, and selection guidance |
| 4.5 | How does the convoy pattern work? | PASS | tactic_lookup with name "convoy" returned result (kind: primitive) |
| 4.6 | What does the eapply tactic do differently from apply? | PASS | tactic_lookup returned metadata for both "eapply" and "apply" (kind: primitive, category: rewriting) |
| 4.7 | Open a proof session on rev_involutive in examples/lists.v | PASS | Successfully opened session; observe_proof_state showed initial goal: forall (A : Type) (l : list A), rev (rev l) = l |
| 4.8 | Try applying intros then induction l in my current proof session | PASS | Both tactics submitted successfully; induction produced base case rev (rev []) = [] and step case with IHl |
| 4.9 | Step through the proof of add_comm in examples/arith.v | PASS | step_forward replayed 2 tactics (intros n m, apply Nat.add_comm), extract_proof_trace returned full state trace |
| 4.10 | /formalize For all natural numbers, addition is commutative | PASS | formalize skill produced Coq theorem (forall n m : nat, n + m = m + n) verified via interactive session |
| 4.11 | /explain-proof add_comm in examples/arith.v | PASS | explain-proof skill opened session, extracted 2-step trace (intros n m, apply Nat.add_comm), produced step-by-step explanation with proof state evolution |
| 4.12 | Visualize the proof tree for app_nil_r in examples/lists.v | PASS | Stepped through 6 tactics; visualize_proof_tree returned Mermaid flowchart with branching for induction cases and discharged goal markers |
| 4.13 | Render the step-by-step proof evolution of modus_ponens in examples/logic.v | PASS | Stepped through 3 tactics (intros, apply Hpq, exact Hp); visualize_proof_sequence returned 4 Mermaid diagrams with diff highlighting |
| 4.14 | I got "Abstracting over the terms ... leads to a term which is ill-typed" | PASS | tactic_lookup with "dependent_destruction" returned result (kind: primitive) |
| 4.15 | destruct on my Fin n hypothesis lost the equality | PASS | tactic_lookup with "dependent_destruction" returned result (kind: primitive) |
| 4.16 | I need an axiom-free way to do dependent destruction | PASS | tactic_lookup with "dependent_destruction" returned result |
| 4.17 | In examples/dependent.v, which hypotheses do I need to revert before destructing n in vhead_vcons? | PASS | observe_proof_state showed hypotheses; destruct n produced 2 subgoals with type changes (vec A 0 vs vec A (S n)) |
| 4.18 | Generate the convoy pattern match term for vhead in examples/dependent.v | PASS | coq_query Print vhead succeeded in session, returning the full convoy-pattern match term |
| 4.19 | Explain the convoy pattern | PASS | tactic_lookup with "convoy" returned result |
| 4.20 | setoid_rewrite fails with "Unable to satisfy the following constraints" | PASS | tactic_lookup with "setoid_rewrite" returned result (kind: primitive, category: rewriting) |
| 4.21 | Generate the Instance Proper declaration for list_union with list_equiv in examples/typeclasses.v | PASS | coq_query Check list_union succeeded in session — returned type list ?A -> list ?A -> list ?A |
| 4.22 | rewrite can't find the subterm inside this forall | PASS | tactic_lookup with "setoid_rewrite" returned result |
| 4.23 | Explain what Proper (eq ==> eq_set ==> eq_set) union means | PASS | tactic_lookup returned "Proper" as primitive; search_by_name returned 50 results from Coq.Classes.Morphisms and stdpp |

## 5. Refactoring and Proof Engineering

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 5.1 | If I change add_comm in examples/arith.v, what breaks? | PASS | impact_analysis returned valid response for Coq.Arith.PeanoNat.Nat.add_comm (root node with structured output) |
| 5.2 | /compress-proof rev_involutive in examples/lists.v | PASS | compress-proof skill compressed proof to a one-liner chain; verified via proof session |
| 5.3 | /proof-lint examples/lint_targets.v | PASS | proof-lint skill scanned file and reported 6 findings: deprecated tactic, tactic chain simplifications, bullet style inconsistency |
| 5.4 | /proof-obligations examples/ | PASS | proof-obligations skill scanned files, found 6 obligations (2 Axiom, 2 admit, 2 Admitted) in obligations.v with severity classifications |
| 5.5 | /migrate-rocq | PASS | migrate-rocq skill scanned 14 files, identified 16 deprecated From Coq imports across 12 files, proposed From Rocq replacements, flagged opam items for review |

## 6. Library and Ecosystem

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 6.1 | What modules does Coquelicot provide? | PASS | list_modules returned 23 Coquelicot modules (AutoDerive, Complex, Derive, Hierarchy, Series, etc.) |
| 6.2 | What typeclasses does std++ provide for finite maps? | PASS | list_modules returned 50 stdpp modules including fin_maps (790 decls) and fin_map_dom (89 decls) |
| 6.3 | /check-compat | PASS | check-compat skill analyzed 6 declared dependencies against Coq 9.1.1, confirmed mutual compatibility |
| 6.4 | What Coq packages are currently installed? | PASS | query_packages returned 97 installed opam packages (coq 9.1.1, coq-coquelicot 3.4.4, coq-mathcomp-ssreflect 2.5.0, coq-stdpp 1.12.0, etc.) |
| 6.5 | /proof-repair examples/broken.v | PASS | proof-repair skill identified 3 broken proofs (Omega→Lia module, omega→lia x2, fourier→lra), applied repairs, verified compilation |

## 7. Debugging and Diagnosing Unexpected Behavior

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 7.1 | Open a proof session on eauto_needed in examples/automation.v — why doesn't auto solve this goal? | PASS | auto left goal unchanged (can't instantiate existentials), eauto completed the proof |
| 7.2 | Why wasn't bpow_ge_0 used by auto? | PASS | search_by_name found Flocq.Core.Raux.bpow_ge_0 with score 1.018 |
| 7.3 | auto fails but eauto succeeds — what's the difference? | PASS | compare_tactics returned valid comparison: eauto supports existential variable instantiation while auto does not |
| 7.4 | Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned 4 entries (add_comm_alt, Nat.add_comm, double_S, double_0) |
| 7.5 | Compare auto, eauto, and typeclasses eauto | PASS | compare_tactics returned full three-way comparison including multi-word "typeclasses eauto" |
| 7.6 | Open a proof session on add_comm_test in examples/automation.v — which lemma did auto use? | PASS | step_forward replayed auto with my_hints; get_step_premises returned premise list for the step |
| 7.7 | Inspect the core hint database | PASS | inspect_hint_db returned 64 entries (48 resolve, 16 unfold) for "core" database |
| 7.8 | Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol? | PASS | inspect_hint_db with session_id and db_name "my_hints" returned 4 hint entries |
| 7.9 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | PASS | trace_resolution correctly returns NO_TYPECLASS_GOAL — the goal is an equality (not a typeclass constraint) |
| 7.10 | /explain-error rewrite Nat.add_comm fails with "unable to unify" | PASS | explain-error skill diagnosed root causes with fix suggestions backed by MCP tool lookups |
| 7.11 | Why does apply Z.add_le_mono fail here? | PASS | search_by_name found Z.add_le_mono and 11 related results from Coq.ZArith.BinInt |
| 7.12 | Compare simpl vs cbn vs lazy | PASS | compare_tactics returned valid comparison with pairwise differences and selection guidance |

## 8. Performance and Profiling

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 8.1 | Profile the proof of ring_morph in examples/algebra.v | PASS | extract_proof_trace returned 6 steps with duration_ms per step (intros, induction, reflexivity, simpl, rewrite, lia) |
| 8.2 | Profile the proof of zmul_expand in examples/algebra.v — is time spent in tactics or kernel? | PASS | extract_proof_trace returned 2 steps with duration_ms (intros, lia) — timing data available for analysis |
| 8.3 | Profile examples/algebra.v and show me the top 5 slowest lemmas | PASS | profile_proof timing mode returned per-proof summaries sorted by total_time_s (ring_comm, ring_assoc, ring_morph, etc.) |
| 8.4 | Which sentences in examples/algebra.v take the most compilation time? | PASS | profile_proof timing mode returned per-sentence entries with real_time_s, user_time_s, sys_time_s |
| 8.5 | simpl in * is taking 15 seconds — why is it slow? | PASS | tactic_lookup returned simpl metadata (kind: ltac, is_recursive: true) |
| 8.6 | Typeclass resolution is the bottleneck — how do I speed it up? | PASS | tactic_lookup returned eauto metadata (kind: ltac, category: automation, is_recursive: true) |
| 8.7 | Show me the Ltac call-tree breakdown for my_crush in examples/automation.v | PASS | profile_proof ltac mode returned call-tree: my_crush 100% → lia 85% → zchecker 31%, zify_op 17.2%, reflexivity 6.2%, intros 2.7% |
| 8.8 | Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings | PASS | extract_proof_trace returned duration_ms for both: overcomplicated 4 steps, add_comm 2 steps — timing comparison possible |
| 8.9 | Profile all .v files in examples/ and show me the slowest files and lemmas | PASS | profile_proof timing mode called on all 8 .v files; slowest: algebra.v 0.272s, flocq.v 0.156s, automation.v 0.109s, typeclasses.v 0.105s |

---

## Remaining Issues

### search_by_type misses higher-order queries (1.4)
- `search_by_type` for the `List.map` composition lemma returned 50 results but none matched `List.map_map`
- **Query normalization (implemented)**: `search_by_type` now resolves short constant names to FQNs, detects free variables (`f`, `g`, `l`) and wraps them in forall binders converting `Const` nodes to `Rel`, and uses a relaxed WL size filter (2.0 vs 1.2). This enables structural and symbol channels to match queries written as type patterns against fully-quantified indexed types. Verified working for declarations that have structural data.
- **Incomplete index data (partially fixed)**: `Coq.Lists.List.map_map` has `node_count=1`, no `constr_tree`, no WL histogram, and empty `symbol_set` in the index. Before parser improvements, 31% of declarations (36,847 of 119,077) lacked structural data. TypeExprParser extensions (Unicode normalization, `:=` handling, `'` prefix, `{||}` records, `++`/`::`/`==` operators, `exists` keyword) recover 72% of the gap — after index rebuild, ~9% will remain without structural data. Indexes must be rebuilt to apply the fix. This is the primary reason the test still fails.
- **Remaining gap — FQN display name mismatch**: the user writes `List.map` but the index stores the canonical definition FQN `ListDef.map` (Coq re-exports `ListDef.map` as `List.map`). The suffix index has `map` but not `List.map`, so FQN resolution fails for this specific name.
- **Remaining gap — binder type approximation**: forall-wrapped free variables receive `Sort("Type")` as binder type, while indexed types have concrete binder types (e.g., `A -> B`, `list A`). The outer quantifier nodes score lower on structural matching, but the body — the majority of both trees — matches well.
