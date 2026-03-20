# Examples

Concrete examples of questions you can ask Poule, organized by the recurring pain points in the Coq/Rocq community (see [doc/background/common-questions.md](doc/background/common-questions.md) for the full survey). Each example shows what you'd type into Claude Code — Poule handles the tool calls behind the scenes.

---

## 1. Discovery and Search

The single most common pain point across all proof assistant communities.

**Find lemmas by name or keyword:**
```
Find lemmas about list reversal being involutive
```
```
Which lemmas in stdlib mention both Nat.add and Nat.mul?
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
What does the %nat scope delimiter mean? Why does + resolve to Nat.add vs Z.add?
```
```
What notations are currently in scope?
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
Suggest tactics for my current goal
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
Run Check my_lemma with Set Printing All so I can see the implicit arguments
```

**Diagnose universe constraint errors:**
```
Diagnose this error: Universe inconsistency: Cannot enforce Set < Set
```
```
What are the universe constraints on my_definition?
```

**Debug typeclass resolution failures:**
```
Trace typeclass resolution for my current goal — which instances is Coq trying?
```
```
What instances are registered for the Proper typeclass?
```

**Inspect implicit arguments and coercions:**
```
Check my_lemma with all implicit arguments visible
```

**Audit axiom dependencies:**
```
What axioms does my proof of ring_morph depend on? Does it use anything beyond functional_extensionality?
```
```
Compare the axiom profiles of these three alternative proofs
```

**Understand why a term won't reduce:**
```
Why doesn't simpl simplify this expression involving bpow? Is it opaque?
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
What's in the Coq.Arith module?
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
Suggest tactics for my current proof state
```

**Compare tactics side-by-side:**
```
Compare auto vs eauto vs intuition — when should I use each?
```
```
Compare rewrite and setoid_rewrite for my current goal
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
Try applying intros then induction n in my current proof session
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
/explain-proof Nat.add_comm
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
Which hypotheses do I need to revert before destructing x?
```
```
Generate the convoy pattern match term with the correct return clause for this match
```
```
Explain the convoy pattern — why doesn't Coq automatically refine hypothesis types during case analysis?
```

**Fix setoid rewriting errors:**
```
setoid_rewrite fails with "Unable to satisfy the following constraints" — which Proper instance am I missing?
```
```
Generate the Instance Proper declaration I need for my union function with eq_set
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
If I rename my_add_comm, what breaks? Show me the full impact analysis
```

**Compress a verbose proof:**
```
/compress-proof rev_involutive in src/Lists.v
```

**Lint proof scripts for issues:**
```
/proof-lint src/Core.v
```

**Scan for incomplete proofs:**
```
/proof-obligations
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
/proof-repair
```

---

## 7. Debugging and Diagnosing Unexpected Behavior

**Diagnose why auto/eauto failed:**
```
Why doesn't auto solve this goal? Show me which hints were tried and why each was rejected
```
```
Why wasn't bpow_ge_0 used by auto? I registered it with Hint Resolve
```
```
auto fails but eauto succeeds — what's the difference on this goal?
```
```
What databases and transparency settings are in effect for my auto invocation?
```

**Compare automation variants:**
```
Compare auto, eauto, and typeclasses eauto on my current goal — which succeeds and why?
```
```
auto solved the goal but used the wrong lemma — show me the proof path it took and why it preferred that hint
```

**Inspect hint databases:**
```
Inspect the core hint database to see if my lemma is registered
```
```
What hints are in scope for this goal's head symbol?
```

**Trace typeclass resolution:**
```
Trace typeclass resolution for my current goal — show me which instances were tried and why they failed
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
Profile the proof of ring_morph in src/Algebra.v — which tactic is the bottleneck?
```
```
Why is Qed taking 30 seconds on this proof? Is it the tactics or the kernel re-checking?
```

**Profile an entire file:**
```
Profile src/Core.v and show me the top 5 slowest lemmas
```
```
Which sentences in this file take the most compilation time?
```

**Get optimization suggestions:**
```
simpl in * is taking 15 seconds — why is it slow and what should I use instead?
```
```
Typeclass resolution is the bottleneck — how do I speed it up?
```

**Profile Ltac tactics:**
```
Show me the Ltac call-tree breakdown for my_custom_tactic — which sub-tactic is expensive?
```

**Compare timing before and after:**
```
Compare profiling results before and after my optimization — did anything regress?
```

**Project-wide profiling:**
```
Profile all files in my project and show me the slowest files and lemmas
```

