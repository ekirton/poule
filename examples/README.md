# Examples

Concrete examples of questions you can ask Poule, organized by the recurring pain points in the Coq/Rocq community (see [doc/background/common-questions.md](doc/background/common-questions.md) for the full survey). Each example shows what you'd type into Claude Code — Poule handles the tool calls behind the scenes.

---

## 1. Discovery and Search

The single most common pain point across all proof assistant communities.

**Find lemmas by name or keyword:**
```
Find lemmas about list reversal being involutive
```

**Find lemmas by type signature (Hoogle-style):**
```
Search for lemmas with type forall n : nat, n + 0 = n
```
```
Find a lemma of type List.map f (List.map g l) = List.map (fun x => f (g x)) l
```

**Find lemmas matching a structural pattern:**
```
Find all commutativity lemmas in MathComp — anything matching _ * _ = _ * _
```
```
Find lemmas concluding with _ + _ <= _
```

**Find rewrites for a specific term:**
```
What rewrites exist for Nat.add n 0?
```

**Find the canonical name for a mathematical fact:**
```
What is the stdlib name for associativity of Z.add?
```

**Check whether a concept is already formalized:**
```
Does Coquelicot already have the intermediate value theorem?
```
```
I need a lemma that says filtering a list twice is the same as filtering once
```

**Understand notations and scopes:**
```
Open a proof session on examples/arith.v and tell me what the %nat scope delimiter means. Why does + resolve to Nat.add vs Z.add?
```
```
Open a proof session on examples/arith.v and show me what notations are currently in scope
```

**Locate where an identifier is defined:**
```
Where is Rdiv defined — Coquelicot or stdlib Reals?
```

**Get tactic suggestions for a proof situation:**
```
What tactics can close a goal of the form x = x?
```
```
Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics for the current goal
```

---

## 2. Understanding Errors, Types, and Proof State

The second most common pain point. Poule can parse and explain cryptic error messages.

**Explain a Coq error message:**
```
/explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m
```

**Reveal hidden differences when terms look identical:**
```
Run Check my_lemma from examples/algebra.v with Set Printing All so I can see the implicit arguments
```
```
Check my_lemma from examples/algebra.v with all implicit arguments visible
```

**Diagnose universe constraint errors:**
```
Diagnose this error: Universe inconsistency: Cannot enforce Set < Set
```
```
What are the universe constraints on vhead in examples/dependent.v?
```

**Debug typeclass resolution failures:**
```
Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution — which instances is Coq trying?
```
```
What instances are registered for the Proper typeclass?
```

**Audit axiom dependencies:**
```
What axioms does ring_morph in examples/algebra.v depend on? Does it use anything beyond functional_extensionality?
```

**Compare axiom profiles across proof variants:**
```
Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v
```

**Understand why a term won't reduce:**
```
Open a proof session on bpow_nonneg_example in examples/flocq.v — why doesn't simpl reduce the bpow expression? Is it opaque?
```

---

## 3. Navigation

Navigating large libraries is a persistent IDE gap that Poule addresses directly.

**Jump to a definition:**
```
Show me the full definition of Coquelicot.Derive.Derive
```

**Find which module to import:**
```
Which module gives me access to ssralg.GRing.Ring?
```

**Unfold a definition to see its body:**
```
What is the body of MathComp.ssrnat.leq?
```

**Reverse dependency — who uses a lemma:**
```
If I change Nat.add_comm, what downstream lemmas break?
```
```
Show me the full impact analysis for Nat.add_0_r
```

**Browse instances for a typeclass:**
```
What Proper instances are registered for Rplus in Coquelicot?
```

**Inspect hint databases:**
```
What lemmas are in the arith hint database?
```

**Browse module contents:**
```
What's in the Corelib.Arith module?
```
```
Give me an overview of the MathComp ssreflect sequence lemmas
```

**Visualize dependency structure:**
```
Show me the dependency graph around Nat.add_comm
```

---

## 4. Proof Construction

Tactic selection and proof building — the most common category on Stack Overflow.

**Get tactic suggestions for a goal shape:**
```
My goal is forall n, n + 0 = n. Should I use induction, destruct, or lia?
```
```
Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics for the current goal
```

**Compare tactics side-by-side:**
```
Compare auto vs eauto vs intuition — when should I use each?
```
```
Open a proof session on union_equiv_compat in examples/typeclasses.v and compare rewrite vs setoid_rewrite for the current goal
```

**Look up tactic documentation:**
```
How does the convoy pattern work? When do I need dependent destruction?
```
```
What does the eapply tactic do differently from apply?
```

**Interactive proof construction:**
```
Open a proof session on rev_involutive in examples/lists.v and show me the current goal
```
```
Try applying intros then induction l in my current proof session
```
```
Step through the proof of add_comm in examples/arith.v and explain each tactic
```

**Formalize a theorem from scratch:**
```
/formalize For all natural numbers, addition is commutative
```

**Explain an existing proof step-by-step:**
```
/explain-proof add_comm in examples/arith.v
```

**Visualize proof structure:**
```
Visualize the proof tree for app_nil_r in examples/lists.v
```
```
Render the step-by-step proof evolution of modus_ponens in examples/logic.v
```

**Diagnose dependent pattern matching failures:**
```
I got "Abstracting over the terms ... leads to a term which is ill-typed" — what does this mean?
```
```
destruct on my Fin n hypothesis lost the equality between n and S m — how do I fix this?
```
```
I need an axiom-free way to do dependent destruction on this indexed type
```

**Get convoy pattern assistance:**
```
In examples/dependent.v, which hypotheses do I need to revert before destructing n in vhead_vcons?
```
```
Generate the convoy pattern match term with the correct return clause for vhead in examples/dependent.v
```
```
Explain the convoy pattern — why doesn't Coq automatically refine hypothesis types during case analysis?
```

**Fix setoid rewriting errors:**
```
setoid_rewrite fails with "Unable to satisfy the following constraints" — which Proper instance am I missing?
```
```
Generate the Instance Proper declaration for list_union with list_equiv in examples/typeclasses.v
```
```
rewrite can't find the subterm inside this forall — what should I do instead?
```
```
Explain what Proper (eq ==> eq_set ==> eq_set) union means in plain English
```

---

## 5. Refactoring and Proof Engineering

**Assess refactoring blast radius:**
```
If I change add_comm in examples/arith.v, what breaks? Show me the full impact analysis
```

**Compress a verbose proof:**
```
/compress-proof rev_involutive in examples/lists.v
```

**Lint proof scripts for issues:**
```
/proof-lint examples/lint_targets.v
```

**Scan for incomplete proofs:**
```
/proof-obligations examples/
```

**Migrate deprecated names:**
```
/migrate-rocq
```

---

## 6. Library and Ecosystem

**Browse available libraries:**
```
What modules does Coquelicot provide?
```
```
What typeclasses does std++ provide for finite maps?
```

**Check library compatibility:**
```
/check-compat
```

**List installed packages:**
```
What Coq packages are currently installed?
```

**Fix proofs after a Coq version upgrade:**
```
/proof-repair examples/broken.v
```

---

## 7. Debugging and Diagnosing Unexpected Behavior

**Diagnose why auto/eauto failed:**
```
Open a proof session on eauto_needed in examples/automation.v — why doesn't auto solve this goal? Show me which hints were tried
```
```
Why wasn't bpow_ge_0 used by auto? I registered it with Hint Resolve
```
```
auto fails but eauto succeeds — what's the difference on this goal?
```

**Compare automation variants:**
```
Compare auto, eauto, and typeclasses eauto on my current goal — which succeeds and why?
```
```
Open a proof session on add_comm_test in examples/automation.v — auto solved the goal but which lemma did it use? Show me the proof path and why it preferred that hint
```

**Trace typeclass resolution:**
```
Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution — show me which instances were tried and why they failed
```

**Inspect hint databases:**
```
Inspect the core hint database to see if my lemma is registered
```
```
Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect for auto?
```
```
Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol?
```

**Diagnose tactic failures:**
```
/explain-error rewrite Nat.add_comm fails with "unable to unify"
```
```
Why does apply Z.add_le_mono fail here?
```

**Compare tactic behavior:**
```
Compare simpl vs cbn vs lazy — why does simpl unfold too much here?
```

---

## 8. Performance and Profiling

Identify and fix proof performance bottlenecks without manually instrumenting code.

**Profile a specific proof:**
```
Profile the proof of ring_morph in examples/algebra.v — which tactic is the bottleneck?
```
```
Profile the proof of zmul_expand in examples/algebra.v — is the time spent in tactics or kernel re-checking?
```

**Profile an entire file and find slowest lemmas:**
```
Profile examples/algebra.v and show me the top 5 slowest lemmas
```
```
Which sentences in examples/algebra.v take the most compilation time?
```

**Profile all files in a project:**
```
Profile all .v files in examples/ and show me the slowest files and lemmas
```

**Compare timing before and after:**
```
Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings. Did the verbose version regress?
```

**Profile Ltac tactics:**
```
Show me the Ltac call-tree breakdown for my_crush in examples/automation.v — which sub-tactic is expensive?
```

**Get optimization suggestions:**
```
simpl in * is taking 15 seconds — why is it slow and what should I use instead?
```
```
Typeclass resolution is the bottleneck — how do I speed it up?
```

---

## 9. Textbook / Education RAG

Retrieve and explain Coq concepts using passages from Software Foundations.

**Ask about a core concept:**
```
/textbook how does induction work in Coq?
```
```
/textbook what is a proposition vs a boolean in Coq?
```

**Look up a specific tactic:**
```
/textbook how do I use the rewrite tactic?
```
```
/textbook when should I use inversion vs destruct?
```

**Query with a volume filter:**
```
/textbook --volume lf what are inductively defined types?
```
```
/textbook --volume plf what is the simply typed lambda calculus?
```

**Ask about proof techniques:**
```
/textbook how do I prove things by case analysis?
```
```
/textbook what is the difference between assert and have?
```

**Search for Coq expressions:**
```
/textbook forall n : nat, n + 0 = n
```

**Cross-volume concept:**
```
/textbook what is a Hoare triple?
```
