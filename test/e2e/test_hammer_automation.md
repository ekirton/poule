# Hammer Automation (`try_automation`)

End-to-end tests for CoqHammer integration through the `try_automation` tool. This is a solver tool — it attempts to close goals without human involvement. Distinct from `suggest_tactics`, which provides explained hints for teaching. All prompts use `examples/hammer_goals.v` unless otherwise noted.

**Single strategy — sauto solves a trivial goal:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then use try_automation with strategy="sauto" to try solving the goal automatically
```
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then use try_automation with sauto to try to prove it
```

**Single strategy — sauto with hints:**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then use try_automation with strategy="sauto" and hints ["Nat.add_0_r"]
```
```
Open a proof session on hammer_add_comm in examples/hammer_goals.v, then use try_automation with strategy="sauto" and hints ["Nat.add_comm"]
```

**Single strategy — qauto:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then use try_automation with strategy="qauto" to prove it
```

**Multi-strategy fallback (auto_hammer):**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then use try_automation to try all strategies automatically
```
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then use try_automation with auto_hammer. Which strategy succeeded?
```

**Timeout behavior — short timeout on a hard goal:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, then use try_automation with strategy="sauto" and a 2-second timeout. What does the failure diagnostic say?
```
```
Open a proof session on hammer_hard in examples/hammer_goals.v, then use try_automation with a 5-second total timeout. How many strategies were attempted before the budget ran out?
```

**Success returns a verified proof script:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, use try_automation with sauto, and show me the proof script that was returned. Is the goal now closed?
```

**Failure returns structured diagnostics:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, use try_automation with strategy="sauto" and a 2-second timeout. Show me the failure_reason and timeout_used from the diagnostics.
```

**Options — sauto depth:**
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then use try_automation with strategy="sauto" and depth 3
```

**Options — unfold hints:**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then use try_automation with strategy="sauto" and unfold ["Nat.add"]
```

**Session state unchanged on failure:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, observe the proof state, then use try_automation with strategy="sauto" and a 1-second timeout. Observe the proof state again — is it unchanged?
```

**Session state advances on success:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, note the step index, use try_automation with sauto, then observe the proof state. Did the step index advance and is the proof complete?
```

**Error handling — no active session:**
```
Use try_automation on session ID "nonexistent_session_12345". What error do you get?
```

**Error handling — invalid hint name:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then use try_automation with strategy="hammer" and hints ["123invalid"]. What error do you get?
```

**Non-hammer tactics still work via submit_tactic:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then submit the tactic "reflexivity." — does it work as a normal tactic submission?
```

**Multi-goal proof — automation targets focused goal:**
```
Open a proof session on hammer_multi_goal in examples/hammer_goals.v, then use try_automation with sauto. Does it close the focused subgoal?
```

**Using automation as part of a conversation — solver then fallback to teaching:**
```
I'm trying to prove that n + 0 = n. Can you try to prove it automatically? Open a session on hammer_add_0_r in examples/hammer_goals.v and use try_automation.
```
```
Open a proof session on hammer_app_nil_r in examples/hammer_goals.v. Try try_automation first. If it fails, use suggest_tactics to get hints and explain what I should try instead.
```

**Distinguish suggest_tactics (hints) from try_automation (solver):**
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v. First use suggest_tactics — what hints does it give and why? Then use try_automation — does it solve the goal directly? Compare the two experiences.
```
