# Understanding Errors, Types, and Proof State

The second most common pain point. Poule can parse and explain cryptic error messages.

**Explain a Coq error message:**
```
/explain-error Unable to unify Nat.add ?n (S ?m) with Nat.add (S ?n) ?m
```

**Reveal hidden differences when terms look identical:**
```
Run Check my_lemma from examples/algebra.v with Set Printing All so I can see the implicit arguments
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

**Inspect implicit arguments and coercions:**
```
Check my_lemma from examples/algebra.v with all implicit arguments visible
```

**Audit axiom dependencies:**
```
What axioms does ring_morph in examples/algebra.v depend on? Does it use anything beyond functional_extensionality?
```
```
Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v
```

**Understand why a term won't reduce:**
```
Open a proof session on bpow_nonneg_example in examples/flocq.v — why doesn't simpl reduce the bpow expression? Is it opaque?
```
