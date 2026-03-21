Switch to TESTS phase: $ARGUMENTS

Steps:
1. Run: echo "tests" > .claude/sdd-layer
2. Read the relevant specification before writing tests.
3. Only create or modify files in test/
4. Derive all test expectations from the specification — not intuition.
5. Do not change specifications. If a problem is discovered, write to specification/feedback/ instead.
6. Run tests to confirm they fail (if testing unimplemented behavior) or pass.
7. When done, tell the user to invoke /implementation or /free
