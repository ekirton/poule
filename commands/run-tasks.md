You are executing the `/run-tasks` command. This command reads a task file containing slash commands, executes each one serially, and commits after each successful task.

## Determine the task file

The user may provide a file path argument after `/run-tasks`. If no argument is given, default to `todo.md` in the current working directory.

Use `Read` to open the task file. If it does not exist, tell the user: "Task file not found: `<path>`. Create it with `- [ ] /command args` entries and re-run." Stop here.

## Parse tasks

Extract all lines matching the pattern `- [ ] /...` (unchecked markdown checkboxes starting with a slash command). These are pending tasks.

Skip all other lines — headers, comments, checked items (`- [x]`), blank lines, and non-checkbox bullets.

If no unchecked tasks remain, tell the user: "All tasks in `<path>` are complete." Stop here.

Record the total count of pending tasks as **M**.

## Execute tasks serially

Set a counter **N = 0**. For each pending task line, in file order:

1. Increment **N**. Announce: **"Task N/M: `<task line>`"**

2. Parse the slash command: the skill name is the first word after `/` (e.g., `sdd` from `/sdd`). The arguments are everything after the skill name.

3. Invoke the skill using the `Skill` tool with the parsed skill name and arguments.

4. **If the skill succeeds:**

   a. Run `git status --porcelain` using `Bash` to check for changes.

   b. If there are changes (staged or unstaged, including untracked files):
      - Identify the changed files from the status output.
      - Stage them with `git add <file1> <file2> ...` — list files explicitly, do not use `git add -A` or `git add .`.
      - Commit with a message derived from the task line. Use this format:
        ```
        git commit -m "$(cat <<'EOF'
        run-tasks: /command args

        Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
        EOF
        )"
        ```

   c. If there are no changes, skip the commit. This is not an error.

   d. Check off the task in the task file: use `Edit` to replace `- [ ] /command args` with `- [x] /command args` for that specific line.

5. **If the skill fails:**

   a. Do **not** commit any partial work.

   b. Run `git status --porcelain` to check for uncommitted changes. If changes exist, warn the user: "Task failed with uncommitted changes. Review and discard or keep them manually."

   c. Report: **"Task N/M failed: `/command args`"** with the error details.

   d. Stop — do not proceed to the next task.

## Cleanup

Close all open proof sessions before finishing. Use `list_proof_sessions` to check, then `close_proof_session` for each.

## Report

When all tasks complete or after a failure, print a summary:

```
## Run-Tasks Summary

**File:** <task file path>
**Completed:** N/M tasks

### Completed
- [x] /command args → <commit short hash>
- [x] /command args → (no changes)

### Remaining (if any)
- [ ] /command args
- [ ] /command args
```

## Edge cases

- **File not found:** Report and stop (handled in step 1).
- **No unchecked tasks:** Report and stop (handled in step 2).
- **Empty task file:** Same as no unchecked tasks.
- **Non-slash-command checkboxes:** Lines like `- [ ] review the PR` are not slash commands — skip them silently.
- **Commit fails (e.g., pre-commit hook):** Treat as a task failure. Report the hook error and stop.
- **Task produces only whitespace/formatting changes:** Still commit if `git status` shows changes.
