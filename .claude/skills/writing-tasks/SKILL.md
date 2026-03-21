---
name: writing-tasks
description: Task breakdown standards — task structure template, completion marking, file lifecycle. Use when creating or editing tasks/ files.
---

# Task Breakdown Standards

## Task Structure

```
- [ ] **Task name** -- Brief description
  - **Traces to:** [story or requirement reference]
  - **Depends on:** [prior task references, if any]
  - **Produces:** [files or modules]
  - **Done when:** [completion criteria]
```

**One per:** feature or cohesive implementation unit

## Marking Tasks Complete

- When a task is implemented, update its checkbox from `- [ ]` to `- [x]`.
- When **all** tasks in a file are complete, delete the file entirely.
- Tasks are disposable LLM artifacts. They are regenerated when upstream specs change.
