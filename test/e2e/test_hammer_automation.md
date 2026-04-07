# Hammer Automation

End-to-end tests for CoqHammer integration through `submit_tactic`. All prompts use `examples/hammer_goals.v` unless otherwise noted.

**Single strategy — sauto solves a trivial goal:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then submit the tactic "sauto" to try solving the goal automatically
```
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then use sauto to try to prove it
```

**Single strategy — sauto with hints:**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then submit sauto with hints ["Nat.add_0_r"]
```
```
Open a proof session on hammer_add_comm in examples/hammer_goals.v, then submit sauto with hints ["Nat.add_comm"]
```

**Single strategy — qauto:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then submit qauto to prove it
```

**Multi-strategy fallback (auto_hammer):**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then submit auto_hammer to try all strategies automatically
```
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then use auto_hammer to prove it. Which strategy succeeded?
```

**Timeout behavior — short timeout on a hard goal:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, then submit sauto with a 2-second timeout. What does the failure diagnostic say?
```
```
Open a proof session on hammer_hard in examples/hammer_goals.v, then submit auto_hammer with a 5-second total timeout. How many strategies were attempted before the budget ran out?
```

**Success returns a verified proof script:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, submit sauto, and show me the proof script that was returned. Is the goal now closed?
```

**Failure returns structured diagnostics:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, submit sauto with a 2-second timeout. Show me the failure_reason and timeout_used from the diagnostics.
```

**Options — sauto depth:**
```
Open a proof session on hammer_and_comm in examples/hammer_goals.v, then submit sauto with depth 3
```

**Options — unfold hints:**
```
Open a proof session on hammer_add_0_r in examples/hammer_goals.v, then submit sauto with unfold ["Nat.add"]
```

**Session state unchanged on failure:**
```
Open a proof session on hammer_hard in examples/hammer_goals.v, observe the proof state, then submit sauto with a 1-second timeout. Observe the proof state again — is it unchanged?
```

**Session state advances on success:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, note the step index, submit sauto, then observe the proof state. Did the step index advance and is the proof complete?
```

**Error handling — no active session:**
```
Submit the tactic "sauto" to session ID "nonexistent_session_12345". What error do you get?
```

**Error handling — invalid hint name:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then submit hammer with hints ["123invalid"]. What error do you get?
```

**Non-hammer tactics still work normally:**
```
Open a proof session on hammer_trivial_eq in examples/hammer_goals.v, then submit the tactic "reflexivity." — does it work as a normal tactic submission?
```

**Multi-goal proof — hammer targets focused goal:**
```
Open a proof session on hammer_multi_goal in examples/hammer_goals.v, then submit sauto. Does it close the focused subgoal?
```

**Using hammer as part of a conversation:**
```
I'm trying to prove that n + 0 = n. Can you try to prove it automatically? Open a session on hammer_add_0_r in examples/hammer_goals.v and use automation.
```
```
Open a proof session on hammer_app_nil_r in examples/hammer_goals.v. Can you try auto_hammer first, and if it fails, explain what I should try instead?
```
