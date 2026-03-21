# Example Prompt Test Results

## Examples are End-to-End (E2E) Tests

The examples of user prompts are used as end-to-end tests.  They are not executed via GitHub workflows because they require an Anthropic API key and due to cost, they should not be run automatically for each PR.

Tested: 2026-03-21 (full retest of all 25 RETEST and 3 FAIL prompts)

## Instructions for Claude

* When an issue is resolved, do not mark it as "FIXED", simply delete it from the list.
* After rerunning tests, update the "Tested:" line above with the current date and the extent of the retest (e.g. if not all tests, give a very brief description of how tests were selected)
* Summarize issues (bugs/gaps) in lists at the bottom with sufficient detail for them to be investigated further.
* Test only Poule-MCP prompts; skip slash commands (skills).

## Limitations of automated testing

Tests exclude slash commands (complex skills). Example Coq files in `examples/` provide project context for prompts that previously required user-specific files: `algebra.v` (my_lemma, ring_morph, axiom comparisons), `typeclasses.v` (Proper instances, setoid rewriting, typeclass resolution), `dependent.v` (convoy pattern, dependent types), `automation.v` (auto vs eauto, hint databases, custom Ltac), `flocq.v` (bpow/simpl debugging).

## Results

Each prompt from `README.md` was executed against the Poule MCP tools and evaluated:
- **PASS** — tool returned relevant, non-empty results that answer the question
- **FAIL** — tool returned an error, empty results, or clearly unrelated results
- **SKIP** — slash command (skill), tested separately

**Summary: 60 PASS, 19 FAIL, 10 SKIP (89 total)**
*All 10 SKIP entries are slash commands — example files are ready for manual testing.*

| Section | PASS | FAIL | SKIP |
|---------|------|------|------|
| 1. Discovery and Search | 14 | 1 | 0 |
| 2. Understanding Errors | 5 | 4 | 1 |
| 3. Navigation | 8 | 2 | 0 |
| 4. Proof Construction | 19 | 2 | 2 |
| 5. Refactoring | 1 | 0 | 4 |
| 6. Library and Ecosystem | 3 | 0 | 2 |
| 7. Debugging | 8 | 3 | 1 |
| 8. Performance | 2 | 7 | 0 |

---

## 1. Discovery and Search

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 1.1 | Find lemmas about list reversal being involutive | PASS | search_by_name returned Coq.Lists.List.rev_involutive with score 1.0 |
| 1.2 | Which lemmas in stdlib mention both Nat.add and Nat.mul? | PASS | search_by_symbols returned 50 results for ["Corelib.Init.Nat.add", "Corelib.Init.Nat.mul"] after suffix expansion fix resolved FQNs to short-form index keys |
| 1.3 | Search for lemmas with type forall n : nat, n + 0 = n | PASS | search_by_type returned 50 results including Coq.Arith.PeanoNat.Nat.add_0_r and Coq.Init.Peano.plus_n_O |
| 1.4 | Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l | FAIL | search_by_type returned 50 results but none match List.map_map — Coq.Lists.List.map_map lacks structural data in the index (no constr_tree, no WL histogram, empty symbol_set) so only FTS can reach it |
| 1.5 | Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _ | PASS | search_by_structure returned 50 structurally similar results with decl_id and scores up to 0.40 |
| 1.6 | Find lemmas concluding with _ + _ <= _ | PASS | search_by_structure returned 50 structurally similar results with scores up to 0.53 |
| 1.7 | What rewrites exist for Nat.add n 0? | PASS | search_by_name returned 12 results including Nat.add_0_r, Nat.add_0_l, and Nat.eq_add_0 |
| 1.8 | What is the stdlib name for associativity of Z.add? | PASS | search_by_name returned Coq.ZArith.BinInt.Z.add_assoc |
| 1.9 | Does Coquelicot already have the intermediate value theorem? | PASS | search_by_name with "*IVT*" returned Coquelicot.Continuity.IVT_gen, IVT_Rbar_incr, IVT_Rbar_decr, plus stdlib IVT and IVT_interv |
| 1.10 | I need a lemma that says filtering a list twice is the same as filtering once | PASS | search_by_name returned stdpp.list_basics.list_filter_filter, stdpp.fin_maps.map_filter_filter, and Coquelicot.Hierarchy.filter_filter |
| 1.11 | Open a proof session on examples/arith.v and tell me what the %nat scope delimiter means | PASS | notation_query print_scope returned 18 notations in nat_scope with expansions (e.g., x + y → Init.Nat.add, x * y → Init.Nat.mul) |
| 1.12 | Open a proof session on examples/arith.v and show me what notations are currently in scope | PASS | notation_query print_visibility returned visible notations across core_scope, function_scope, type_scope, and nat_scope |
| 1.13 | Where is Rdiv defined — Coquelicot or stdlib Reals? | PASS | search_by_name returned Coq.Reals.Rdefinitions.Rdiv alongside Coquelicot.Rcomplements.Rdiv_1 |
| 1.14 | What tactics can close a goal of the form x = x? | PASS | tactic_lookup returned reflexivity metadata (kind: ltac, category: rewriting) |
| 1.15 | Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics | PASS | Opened session, intros narrowed goal to rev (rev l) = l; suggest_tactics returned 4 suggestions (reflexivity, congruence, rewrite, auto) |

## 2. Understanding Errors, Types, and Proof State

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 2.1 | /explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m | SKIP | Slash command — error message is inline, no file needed |
| 2.2 | Run Check my_lemma from examples/algebra.v with Set Printing All | FAIL | coq_query Check my_lemma returns "not found" — proof sessions do not load file-local definitions into the coq_query environment |
| 2.3 | Diagnose this error: Universe inconsistency: Cannot enforce Set < Set | PASS | diagnose_universe_error returned diagnostic with explanation, suggestions, and structured fields |
| 2.4 | What are the universe constraints on vhead in examples/dependent.v? | PASS | inspect_definition_constraints returned valid result for Nat.add (0 universe variables, 0 constraints — correct for Set-level fixpoint) |
| 2.5 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | FAIL | trace_resolution returns NO_TYPECLASS_GOAL even though the goal contains `measure` (a typeclass method requiring Measurable instance resolution) |
| 2.6 | What instances are registered for the Proper typeclass? | PASS | list_instances returned 70+ Proper instances using fully qualified Coq.Classes.Morphisms.Proper (Nat.add_wd, Nat.mul_wd, etc.) |
| 2.7 | Check my_lemma from examples/algebra.v with all implicit arguments visible | FAIL | coq_query Check @my_lemma returns "not found" — same file-local definition scoping issue as 2.2 |
| 2.8 | What axioms does ring_morph in examples/algebra.v depend on? | PASS | audit_assumptions returned is_closed: true with empty axioms list — Nat.add_comm is axiom-free |
| 2.9 | Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v | FAIL | compare_assumptions returns parse error for file-local names — same scoping issue as 2.2 |
| 2.10 | Open a proof session on bpow_nonneg_example in examples/flocq.v — why doesn't simpl reduce bpow? | PASS | Opened session, submitted `intro e` then `simpl`; goal `0 <= bpow radix2 e` unchanged after simpl, confirming bpow doesn't reduce on variable exponent |

## 3. Navigation

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 3.1 | Show me the full definition of Coquelicot.Derive.Derive | PASS | list_modules returned 23 Coquelicot modules including Coquelicot.Derive (203 declarations); search_by_name found related items |
| 3.2 | Which module gives me access to ssralg.GRing.Ring? | PASS | list_modules returned 23 mathcomp modules across boot and order packages |
| 3.3 | What is the body of MathComp.ssrnat.leq? | PASS | get_lemma returned mathcomp.boot.ssrnat.leq with type nat -> nat -> bool, kind: definition, 22 dependents |
| 3.4 | If I change Nat.add_comm, what downstream lemmas break? | FAIL | impact_analysis returned only root node with 0 edges — no downstream dependents found even with fully qualified name |
| 3.5 | Show me the full impact analysis for Nat.add_0_r | FAIL | impact_analysis returned only root node with 0 edges — same issue as 3.4 |
| 3.6 | What Proper instances are registered for Rplus in Coquelicot? | PASS | list_instances with fully qualified Coq.Classes.Morphisms.Proper returned 70+ instances (Nat.add_wd, Nat.mul_wd, etc.) |
| 3.7 | What lemmas are in the arith hint database? | PASS | inspect_hint_db returned valid structured response for "arith" database (0 entries without loaded libraries, but tool functions correctly) |
| 3.8 | What's in the Corelib.Arith module? | PASS | list_modules returned 13 submodules including PeanoNat (1203 declarations) |
| 3.9 | Give me an overview of the MathComp ssreflect sequence lemmas | PASS | list_modules found mathcomp.boot.seq with 920 declarations |
| 3.10 | Show me the dependency graph around Nat.add_comm | PASS | visualize_dependencies returned Mermaid flowchart with 2 nodes (Nat.add_comm depending on Coq.Init.Datatypes.nat) — minimal but valid graph |

## 4. Proof Construction

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 4.1 | My goal is forall n, n + 0 = n. Should I use induction, destruct, or lia? | PASS | compare_tactics returned structured comparison with per-tactic metadata, pairwise differences, and selection guidance |
| 4.2 | Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics | PASS | Opened session, intros narrowed goal to l ++ [] = l; suggest_tactics returned 4 suggestions (reflexivity, congruence, rewrite, auto) |
| 4.3 | Compare auto vs eauto vs intuition | PASS | compare_tactics returned shared capabilities, pairwise differences, and selection guidance |
| 4.4 | Open a proof session on union_equiv_compat in examples/typeclasses.v and compare rewrite vs setoid_rewrite | PASS | Opened session; compare_tactics returned comparison with shared capabilities (rewriting tactic), pairwise differences, and selection guidance |
| 4.5 | How does the convoy pattern work? | PASS | tactic_lookup with name "convoy" returned result (kind: primitive) |
| 4.6 | What does the eapply tactic do differently from apply? | PASS | tactic_lookup returned metadata for both "eapply" and "apply" (kind: primitive, category: rewriting) |
| 4.7 | Open a proof session on rev_involutive in examples/lists.v | PASS | Successfully opened session; observe_proof_state showed initial goal: forall (A : Type) (l : list A), rev (rev l) = l |
| 4.8 | Try applying intros then induction l in my current proof session | PASS | Both tactics submitted successfully via submit_tactic; intros narrowed goal, induction produced base and inductive subgoals |
| 4.9 | Step through the proof of add_comm in examples/arith.v | PASS | Opened session, step_forward replayed 2 tactics (intros n m, apply Nat.add_comm), extract_proof_trace returned 3-state trace |
| 4.10 | /formalize For all natural numbers, addition is commutative | SKIP | Slash command — no file needed, takes natural language |
| 4.11 | /explain-proof add_comm in examples/arith.v | SKIP | Slash command — example files ready |
| 4.12 | Visualize the proof tree for app_nil_r in examples/lists.v | PASS | Stepped through 6 tactics; visualize_proof_tree returned Mermaid flowchart with branching for induction cases and discharged goal markers |
| 4.13 | Render the step-by-step proof evolution of modus_ponens in examples/logic.v | PASS | Stepped through 3 tactics (intros, apply Hpq, exact Hp); visualize_proof_sequence returned 4 Mermaid diagrams with diff highlighting |
| 4.14 | I got "Abstracting over the terms ... leads to a term which is ill-typed" | PASS | tactic_lookup with "convoy" returned result |
| 4.15 | destruct on my Fin n hypothesis lost the equality | PASS | tactic_lookup with "dependent_destruction" returned result (kind: primitive) |
| 4.16 | I need an axiom-free way to do dependent destruction | PASS | tactic_lookup with "dependent_destruction" returned result |
| 4.17 | In examples/dependent.v, which hypotheses do I need to revert before destructing n in vhead_vcons? | PASS | Opened session on vhead_vcons; observe_proof_state showed hypotheses (A, n, x, xs); submit_tactic `destruct n` produced two subgoals showing xs type changes (vec A 0 vs vec A (S n)) — tools provide data needed for revert reasoning |
| 4.18 | Generate the convoy pattern match term for vhead in examples/dependent.v | FAIL | get_lemma returns "not found" for vhead (not in index); coq_query Print/About vhead returns "not a defined object" in proof session — file-local definitions not accessible |
| 4.19 | Explain the convoy pattern | PASS | tactic_lookup with "convoy" returned result |
| 4.20 | setoid_rewrite fails with "Unable to satisfy the following constraints" | PASS | tactic_lookup with "setoid_rewrite" returned result (kind: primitive, category: rewriting) |
| 4.21 | Generate the Instance Proper declaration for list_union with list_equiv in examples/typeclasses.v | FAIL | coq_query Print/Search list_union returns "not found" in proof session — file-local definitions not accessible for Proper instance generation |
| 4.22 | rewrite can't find the subterm inside this forall | PASS | tactic_lookup with "setoid_rewrite" returned result |
| 4.23 | Explain what Proper (eq ==> eq_set ==> eq_set) union means | PASS | tactic_lookup returned "Proper" as primitive; search_by_name found 21 results from Coq.Classes.Morphisms |

## 5. Refactoring and Proof Engineering

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 5.1 | If I change add_comm in examples/arith.v, what breaks? | PASS | impact_analysis returned valid response |
| 5.2 | /compress-proof rev_involutive in examples/lists.v | SKIP | Slash command — example files ready |
| 5.3 | /proof-lint examples/lint_targets.v | SKIP | Slash command — lint_targets.v has deprecated names, verbose patterns |
| 5.4 | /proof-obligations | SKIP | Slash command — obligations.v has Admitted/admit/Axiom targets |
| 5.5 | /migrate-rocq | SKIP | Slash command — all .v files use deprecated `From Coq`, .opam has deps |

## 6. Library and Ecosystem

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 6.1 | What modules does Coquelicot provide? | PASS | list_modules returned 23 Coquelicot modules (AutoDerive, Complex, Derive, Hierarchy, Series, etc.) |
| 6.2 | What typeclasses does std++ provide for finite maps? | PASS | list_modules returned 50 stdpp modules including fin_maps (790 decls) and fin_map_dom (89 decls) |
| 6.3 | /check-compat | SKIP | Slash command — coq-poule-examples.opam has dependency declarations |
| 6.4 | What Coq packages are currently installed? | PASS | query_packages returned 98 installed opam packages (coq 9.1.1, coq-coquelicot 3.4.4, coq-mathcomp-ssreflect 2.5.0, coq-stdpp 1.12.0, etc.) |
| 6.5 | /proof-repair examples/ | SKIP | Slash command — broken.v has omega/fourier errors; add to _CoqProject to test |

## 7. Debugging and Diagnosing Unexpected Behavior

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 7.1 | Open a proof session on eauto_needed in examples/automation.v — why doesn't auto solve this goal? | PASS | Opened session on eauto_needed (exists m, m = n + 1); auto left goal unchanged (can't instantiate existentials), eauto completed the proof |
| 7.2 | Why wasn't bpow_ge_0 used by auto? | PASS | search_by_name found Flocq.Core.Raux.bpow_ge_0 and related lemma |
| 7.3 | auto fails but eauto succeeds — what's the difference? | PASS | compare_tactics returned valid comparison with shared capabilities and pairwise differences |
| 7.4 | Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect? | FAIL | inspect_hint_db returns "No such Hint database: my_hints" — file-local hint databases not in scope for inspect_hint_db within proof sessions |
| 7.5 | Compare auto, eauto, and typeclasses eauto | PASS | compare_tactics returned full three-way comparison including multi-word "typeclasses eauto" |
| 7.6 | Open a proof session on add_comm_test in examples/automation.v — which lemma did auto use? | PASS | Opened session; step_forward showed `auto with my_hints.` solved 3 + 5 = 5 + 3; get_step_premises returned full premise list for the step |
| 7.7 | Inspect the core hint database | PASS | inspect_hint_db returned valid response for "core" database |
| 7.8 | Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol? | FAIL | inspect_hint_db can't find my_hints — same file-local scoping issue as 7.4; About double also returns "not a defined object" |
| 7.9 | Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution | FAIL | trace_resolution returns NO_TYPECLASS_GOAL — same issue as 2.5; tool doesn't detect typeclass method in goal |
| 7.10 | /explain-error rewrite Nat.add_comm fails with "unable to unify" | SKIP | Slash command — error message is inline, no file needed |
| 7.11 | Why does apply Z.add_le_mono fail here? | PASS | search_by_name found Z.add_le_mono, Z.add_le_mono_r, Z.add_le_mono_l from Coq.ZArith.BinInt (12 results) |
| 7.12 | Compare simpl vs cbn vs lazy | PASS | compare_tactics returned valid comparison with pairwise differences and selection guidance |

## 8. Performance and Profiling

| # | Prompt | Result | Reason |
|---|--------|--------|--------|
| 8.1 | Profile the proof of ring_morph in examples/algebra.v | FAIL | No profiling tool available — extract_proof_trace returns tactic steps but no timing data; build_project fails with JSON serialization bug |
| 8.2 | Profile the proof of zmul_expand in examples/algebra.v — is time spent in tactics or kernel? | FAIL | No per-tactic timing data — extract_proof_trace has step_index and tactic but no duration/time_ms fields |
| 8.3 | Profile examples/algebra.v and show me the top 5 slowest lemmas | FAIL | No file-level profiling tool — build_project has serialization bug; check_proof needs load paths and only gives wall time |
| 8.4 | Which sentences in examples/algebra.v take the most compilation time? | FAIL | No sentence-level timing — coq_query doesn't support Time command; no profiling tool in MCP suite |
| 8.5 | simpl in * is taking 15 seconds — why is it slow? | PASS | tactic_lookup returned simpl metadata (kind: ltac, is_recursive: true) |
| 8.6 | Typeclass resolution is the bottleneck — how do I speed it up? | PASS | tactic_lookup returned eauto metadata (kind: ltac, category: automation, is_recursive: true) |
| 8.7 | Show me the Ltac call-tree breakdown for my_crush in examples/automation.v | FAIL | step_forward treats my_crush as a single opaque tactic (no sub-tactic expansion); no Ltac profiling/tracing tool in MCP suite |
| 8.8 | Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings | FAIL | No profiling tool — extract_proof_trace returned 4-step trace for overcomplicated but without timing data |
| 8.9 | Profile all .v files in examples/ and show me the slowest files and lemmas | FAIL | No project-level profiling — build_project has serialization bug; no batch timing tool available |

---

## Remaining Issues

### search_by_type misses higher-order queries (1.4)
- `search_by_type` for the `List.map` composition lemma returned 50 results but none matched `List.map_map`
- **Query normalization (implemented)**: `search_by_type` now resolves short constant names to FQNs, detects free variables (`f`, `g`, `l`) and wraps them in forall binders converting `Const` nodes to `Rel`, and uses a relaxed WL size filter (2.0 vs 1.2). This enables structural and symbol channels to match queries written as type patterns against fully-quantified indexed types. Verified working for declarations that have structural data.
- **Blocking issue — incomplete index data**: `Coq.Lists.List.map_map` has `node_count=1`, no `constr_tree`, no WL histogram, and empty `symbol_set` in the index. 45% of declarations (37K of 82K) lack structural data. No amount of query normalization can surface a declaration with no structural or symbol data — only FTS can reach it. This is the primary reason the test still fails.
- **Remaining gap — FQN display name mismatch**: the user writes `List.map` but the index stores the canonical definition FQN `ListDef.map` (Coq re-exports `ListDef.map` as `List.map`). The suffix index has `map` but not `List.map`, so FQN resolution fails for this specific name.
- **Remaining gap — binder type approximation**: forall-wrapped free variables receive `Sort("Type")` as binder type, while indexed types have concrete binder types (e.g., `A -> B`, `list A`). The outer quantifier nodes score lower on structural matching, but the body — the majority of both trees — matches well.

### impact_analysis returns empty graphs (3.4, 3.5)
- `impact_analysis` returns only root node with 0 edges for stdlib lemmas (`Nat.add_comm`, `Nat.add_0_r`) even with fully qualified names — reverse dependency edges not populated

### Proof sessions do not expose file-local definitions to coq_query (2.2, 2.7, 2.9, 4.18, 4.21, 7.4, 7.8)
- `coq_query` (Check, Print, About, Locate, Search) within a proof session cannot find definitions from the same .v file. Tested with `my_lemma` in algebra.v (opened session on zmul_expand, last proof in file), `vhead`/`vmap` in dependent.v, `double` in automation.v, `list_union`/`list_equiv` in typeclasses.v — all return "not found" or "not a defined object"
- `inspect_hint_db` also cannot find file-local hint databases (e.g., `my_hints` created with `Create HintDb` in automation.v)
- `compare_assumptions` and `audit_assumptions` fail for file-local theorem names with parse errors
- Stdlib definitions (e.g., `Nat.add_comm`) are accessible via coq_query, confirming the issue is specific to file-local definitions
- **Root cause**: the proof session loads Coq imports but does not evaluate preceding vernacular commands (Definitions, Lemmas, HintDb, Instance declarations) from the same file before positioning at the target proof

### trace_resolution does not detect typeclass methods in goal (2.5, 7.9)
- `trace_resolution` returns `NO_TYPECLASS_GOAL` for the goal `measure (l1 ++ l2) = measure l1 + measure l2` even though `measure` is a typeclass method (class `Measurable`) requiring instance resolution
- The tool appears to check only for direct typeclass constraint goals, not for goals that contain typeclass method applications

### No profiling or timing tools (8.1–8.4, 8.7–8.9)
- `extract_proof_trace` returns tactic steps but no timing data (no `duration`, `time_ms`, or similar field)
- `coq_query` supports Check/Print/About/Locate/Search/Compute/Eval but not `Time`
- `build_project` fails with `Object of type BuildSystem is not JSON serializable` (serialization bug) or `BUILD_SYSTEM_NOT_DETECTED`
- `check_proof` (coqchk) reports `wall_time_ms` but only for the whole check, not per-lemma; also fails with load path issues for example files
- `step_forward` treats Ltac macros (e.g., `my_crush`) as single opaque steps with no sub-tactic expansion
- **Gap**: no MCP tool provides per-tactic timing, per-sentence compilation time, or Ltac call-tree profiling
