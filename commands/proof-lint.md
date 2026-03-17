You are executing the `/proof-lint` command. This command scans Coq proof scripts for deprecated tactics, inconsistent bullet style, and unnecessarily complex tactic chains. It reports findings grouped by category with file:line locations and suggested fixes. When the user requests auto-fix, it applies changes and verifies each one through a proof session.

## Determine scope

The user may provide a scope argument after `/proof-lint`:
- A specific `.v` file path: lint that file only.
- A directory path: lint all `.v` files under that directory.
- No argument: lint the entire project (all `.v` files reachable from the project root).

Use `Glob` with the pattern `**/*.v` (scoped to the appropriate directory) to collect the list of files to analyze.

If a `.proof-lint.yml` or `.proof-lint.json` config file exists in the project root, read it. It may specify:
- `bullet_style`: the enforced bullet convention (e.g., `"bullets"`, `"braces"`, or a specific nesting order like `["-", "+", "*"]`).
- `ignore_deprecated`: a list of deprecated tactics to skip (intentionally retained).
- `ignore_patterns`: file globs to exclude from scanning.

If no config file exists, infer the dominant bullet style from the codebase during analysis.

## Lint checks

Run these checks on every file in scope. Use `Grep` for pattern-based scanning and `Read` for inspecting surrounding context when needed.

### 1. Deprecated tactics

Scan for tactics deprecated in modern Coq versions. Key patterns to detect:

| Deprecated | Replacement | Notes |
|---|---|---|
| `omega` | `lia` | Removed in Coq 8.14+ |
| `romega` | `lia` | Removed in Coq 8.14+ |
| `fourier` | `lra` | Removed in Coq 8.14+ |
| `auto with *` (with hint databases) | `typeclasses eauto` or explicit `auto with db1 db2` | Overly broad hint resolution |
| `intuition` | `intuition auto` or `tauto` depending on use | Deprecated default behavior changed |
| `firstorder` with no solver | `firstorder auto` | Default solver changed |
| `assert ... by (exact ...)` | `pose proof ...` | Stylistic modernization |
| `replace ... with ... by ...` where `congruence` suffices | `congruence` | Simplification |
| `simpl; trivial` | `easy` or `now simpl` | Chain simplification |
| `Proof.` without matching `Qed.`, `Defined.`, or `Admitted.` | Flag as unclosed proof | Structural error |

Use `Grep` to find occurrences of each deprecated pattern across the file set. Record file path, line number, the matched text, and the recommended replacement.

Skip any tactics listed in the config's `ignore_deprecated` list.

### 2. Bullet style inconsistency

Scan for bullet markers (`-`, `+`, `*`) and brace pairs (`{` / `}`) used for subgoal structuring within proof blocks (between `Proof.` and `Qed.`/`Defined.`).

For each file, determine which bullet convention is used. At project scope, determine the dominant convention across all files.

Flag:
- Files that mix bullet styles within a single proof.
- Files that use a different convention than the project-dominant style (or the configured style).
- Mismatched brace nesting.

If no config specifies a preferred style, infer it: count the frequency of each style across all scanned files and treat the most common as the project standard.

### 3. Unnecessarily complex tactic chains

Scan for tactic sequences that have simpler equivalents:

| Pattern | Suggested replacement |
|---|---|
| `simpl; reflexivity` | `auto` or `easy` |
| `intros; auto` | `auto` (auto already intros) |
| `intros X; exact X` | `assumption` or `exact` with appropriate term |
| Multiple consecutive `rewrite` with lemmas from the same hint database | `autorewrite with <db>` |
| `destruct ...; [tac \| tac]` where both branches are identical | `destruct ...; tac` |
| `try solve [auto]` | `auto` (auto already does not fail) |
| `repeat (simpl; auto)` | `simpl; auto` if one pass suffices |
| Long `match goal` blocks where `solve [eauto]` works | `eauto` |

Use `Grep` to find candidate patterns, then `Read` to inspect surrounding context and confirm the pattern is a genuine simplification opportunity.

## Build the report

Organize findings into a structured report with these sections:

### Summary
- Total files scanned
- Total issues found, broken down by category (deprecated tactics, bullet style, tactic chains)
- Top files by issue count

### Deprecated Tactics
Group by tactic name. For each:
```
[deprecated] file/path.v:42 — `omega` is deprecated since Coq 8.14; use `lia`
```

### Bullet Style Issues
Group by file. For each:
```
[style] file/path.v:87 — Mixed bullet styles in proof of `my_lemma`: uses `-` and `{` in same proof
```

### Tactic Chain Simplifications
Group by pattern type. For each:
```
[simplify] file/path.v:103 — `simpl; reflexivity` can be replaced with `easy`
```

Present the full report to the user. Ask whether they want to auto-fix any or all categories.

## Auto-fix workflow

If the user requests auto-fix (for all issues or a specific category), apply changes one at a time with verification.

For each fix:

1. **Open a proof session** on the file using `open_proof_session`. If one is already open for that file, reuse it.

2. **Navigate to the proof** containing the issue. Use `observe_proof_state` and `step_forward`/`step_backward` to reach the tactic in question.

3. **Apply the replacement.** Use `Edit` to modify the source file with the suggested replacement.

4. **Verify the fix.** Use `submit_tactic` with the replacement tactic to confirm it closes the same goal. Alternatively, step through the modified proof to confirm it reaches `Qed.` without errors.

5. **If verification succeeds:** keep the change and move to the next issue. Report the fix as applied.

6. **If verification fails:** revert the change using `Edit` to restore the original text. Report that the fix could not be applied automatically and requires manual intervention. Close and reopen the proof session if needed to reset state.

7. **Close proof sessions** with `close_proof_session` when done with each file.

After all fixes are attempted, print a summary:
- Number of fixes applied successfully
- Number of fixes that failed verification (with file:line for manual review)
- Any files that could not be processed (e.g., parse errors)

## Important constraints

- Never apply a fix without verifying it through a proof session. A syntactically valid replacement may fail to close the goal.
- Never modify a proof's mathematical content. Only style-preserving refactorings are in scope.
- If a file fails to parse or load in a proof session, skip it and report the error. Do not attempt fixes on files that cannot be loaded.
- Process fixes within a file in reverse line order so that line numbers remain valid for subsequent edits.
- When multiple issues overlap on the same tactic expression, apply only one fix and re-scan if needed.
