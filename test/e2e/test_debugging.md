# Debugging and Diagnosing Unexpected Behavior

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
```
Open a proof session on double_2 in examples/automation.v — what databases and transparency settings are in effect for auto?
```

**Compare automation variants:**
```
Compare auto, eauto, and typeclasses eauto on my current goal — which succeeds and why?
```
```
Open a proof session on add_comm_test in examples/automation.v — auto solved the goal but which lemma did it use? Show me the proof path and why it preferred that hint
```

**Inspect hint databases:**
```
Inspect the core hint database to see if my lemma is registered
```
```
Open a proof session on double_2 in examples/automation.v — what hints are in scope for the goal's head symbol?
```

**Trace typeclass resolution:**
```
Open a proof session on measure_app_length in examples/typeclasses.v and trace typeclass resolution — show me which instances were tried and why they failed
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
