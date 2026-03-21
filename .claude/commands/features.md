Switch to FEATURES phase: $ARGUMENTS

Steps:
1. Run: echo "features" > .claude/sdd-layer
2. Read the upstream PRD this feature traces to.
3. Only create or modify files in doc/features/
4. Describe the feature from the user's perspective — what it does, why it exists.
5. Include acceptance criteria with GIVEN/WHEN/THEN entries tracing to PRD requirement IDs.
6. When done, tell the user to invoke /architecture or /free
