# Tactic Suggestion

Quality and behavior of the `suggest_tactics` MCP tool — a pedagogical tool that provides explained tactic hints to help students learn proof strategy. Distinct from `try_automation`, which is a solver.

**Rule-based fallback (no model files present):**
```
Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics for the current goal
```
```
Open a proof session on rev_involutive in examples/lists.v, apply intros, then suggest tactics
```

**Neural predictions with confidence and category metadata:**
```
Open a proof session on add_comm in examples/arith.v and suggest tactics — are any marked as neural predictions?
```
```
Open a proof session on app_nil_r in examples/lists.v, apply intros, and suggest tactics. Show the confidence level and category for each suggestion.
```

**Neural predictions for different goal shapes:**
```
Open a proof session on union_equiv_compat in examples/typeclasses.v and suggest tactics for the current goal
```
```
Open a proof session on modus_ponens in examples/logic.v and suggest tactics
```

**Argument-enriched suggestions (neural + retrieval):**
```
Open a proof session on rev_involutive in examples/lists.v, apply intros, and suggest tactics. Do any suggestions include specific lemma arguments?
```

**Graceful degradation when model files are missing:**
```
Suggest tactics for a goal of the form n + 0 = n — does it still work if the neural model is not installed?
```

**Prediction latency:**
```
Open a proof session on add_comm in examples/arith.v, apply intros, and suggest tactics. How long did the suggestion take?
```

**Pedagogical use case — explained suggestions with textbook references:**
```
Open a proof session on add_comm in examples/arith.v, apply intros, and suggest tactics. For each suggestion, explain why that tactic makes sense for this proof state and link to relevant textbook material.
```
```
I'm a student learning Coq. Open a proof session on app_nil_r in examples/lists.v, suggest tactics, and teach me which one to try and why.
```

**Distinguish from try_automation — suggest_tactics is for learning, not solving:**
```
Open a proof session on add_comm in examples/arith.v. First use suggest_tactics to get hints with explanations. Then use try_automation to see if automation can solve it directly. Compare the two experiences.
```
