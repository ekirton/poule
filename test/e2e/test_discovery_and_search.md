# Discovery and Search

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
