# Performance and Profiling

Identify and fix proof performance bottlenecks without manually instrumenting code.

**Profile a specific proof:**
```
Profile the proof of ring_morph in examples/algebra.v — which tactic is the bottleneck?
```
```
Profile the proof of zmul_expand in examples/algebra.v — is the time spent in tactics or kernel re-checking?
```

**Profile an entire file:**
```
Profile examples/algebra.v and show me the top 5 slowest lemmas
```
```
Which sentences in examples/algebra.v take the most compilation time?
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
Show me the Ltac call-tree breakdown for my_crush in examples/automation.v — which sub-tactic is expensive?
```

**Compare timing before and after:**
```
Profile overcomplicated in examples/lint_targets.v, then profile Nat.add_comm — compare the timings. Did the verbose version regress?
```

**Project-wide profiling:**
```
Profile all .v files in examples/ and show me the slowest files and lemmas
```
