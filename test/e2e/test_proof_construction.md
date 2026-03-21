# Proof Construction

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
