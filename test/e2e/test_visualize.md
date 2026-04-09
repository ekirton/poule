# Visualization

End-to-end tests for the `/visualize` skill — proof state, proof tree, dependency graph, and proof sequence diagrams.

**Proof state — current step:**
```
Open a proof session on app_nil_r in examples/lists.v, apply intros, then visualize the proof state
```

**Proof state — at a specific step:**
```
Open a proof session on add_comm in examples/arith.v, step through 2 tactics, then visualize the proof state at step 0
```

**Proof state — detail levels:**
```
Open a proof session on rev_involutive in examples/lists.v, apply intros, then visualize the proof state with detail level "detailed"
```

**Proof tree — complete proof:**
```
Open a proof session on app_nil_r in examples/lists.v, step through the entire proof, then visualize the proof tree
```

**Proof tree — incomplete proof (should warn):**
```
Open a proof session on add_comm in examples/arith.v, apply intros only, then try to visualize the proof tree
```

**Dependency graph — default depth:**
```
Visualize the dependency graph for Nat.add_comm
```

**Dependency graph — custom depth and max nodes:**
```
Visualize dependencies for Nat.add_0_r with depth 3 and max 30 nodes
```

**Proof sequence — step-by-step evolution:**
```
Open a proof session on modus_ponens in examples/logic.v, step through the whole proof, then visualize the proof sequence
```

**Proof sequence — with detail level:**
```
Open a proof session on app_nil_r in examples/lists.v, step through the proof, then visualize the proof sequence with summary detail
```

**No arguments — infer from context:**
```
Open a proof session on add_comm in examples/arith.v, apply intros, then run /visualize with no arguments
```

**HTML output confirmation:**
```
Visualize dependencies for Nat.add_comm — confirm that proof-diagram.html was written and tell me to open it in a browser
```
