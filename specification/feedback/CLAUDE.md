# Specification Feedback Writing Guidelines

## Authority

Feedback documents are informed by the authority chain: data model documents (`doc/architecture/data-models/`) → architecture documents (`doc/architecture/`) → specifications (`specification/`). When filing feedback, verify the issue against the authoritative source before reporting it.

**Before writing feedback:** Read the specification's parent architecture document and the relevant data model documents (`doc/architecture/data-models/expression-tree.md`, `doc/architecture/data-models/index-entities.md`). An apparent spec issue may already be resolved in the authoritative source — in that case, the feedback should cite the authoritative source and recommend aligning the spec with it.

## Purpose

Feedback documents capture issues, ambiguities, and gaps discovered in specification files during implementation planning or code generation. They exist to inform the specifier — not to fix the spec directly.

## File Naming

One feedback file per specification file. Name matches the source:

```
specification/feedback/<spec-name>.md
```

Example: feedback for `specification/storage.md` goes in `specification/feedback/storage.md`.

## Document Structure

```markdown
# Specification Feedback: <spec title>

**Source:** [specification/<name>.md](../<name>.md)
**Date:** <YYYY-MM-DD of last update>
**Reviewer:** <role or context, e.g., "Implementation planner (task decomposition pass)">

---

## Issue <N>: <Short descriptive title>

**Severity:** <high | medium | low>
**Section:** <spec section number and name>

**Problem:** <What is wrong, ambiguous, or missing. State the conflict precisely — quote the spec where helpful.>

**Impact:** <What breaks, diverges, or becomes ambiguous for the implementer if this is not resolved.>

**Suggested resolution:** <Concrete recommendation. If multiple options exist, list them with trade-offs. Label your preferred option.>

---
```

## Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| **Source** | yes | Relative link to the specification file this feedback targets. Always use `[specification/<name>.md](../<name>.md)` format. |
| **Date** | yes | Date of last update (absolute, YYYY-MM-DD). Update when issues are added or removed. |
| **Reviewer** | yes | Who or what produced the feedback (e.g., "Implementation planner", "Code generation pass", human name). |
| **Severity** | yes | `high` = blocks implementation or causes incorrect behavior. `medium` = forces an implementer judgment call the spec should have made. `low` = documentation clarity, edge case coverage, or future-proofing. |
| **Section** | yes | Spec section number and name where the issue originates. If it spans sections, list the primary one and mention others in the problem description. |
| **Problem** | yes | The issue. Be specific: quote the conflicting text, name the contradicting spec, or describe the missing information. |
| **Impact** | yes | What happens if this is not resolved. Frame in terms of implementation consequences (wrong behavior, ambiguous API, divergent implementations). |
| **Suggested resolution** | yes | At least one concrete fix. For ambiguities, present the options and label your recommendation. |

## Writing Rules

- **One issue per heading.** Do not combine multiple problems into a single issue.
- **Reference cross-spec conflicts explicitly.** If two specs disagree, name both files and quote both passages.
- **Use absolute section references** (e.g., "Section 3.2, `dependencies` table"), not relative ones (e.g., "the section above").
- **No fixes in feedback files.** Feedback describes what is wrong and suggests a resolution. The specifier decides.
- **Delete resolved issues.** When the specifier resolves an issue, remove it from the feedback file. Delete empty feedback files entirely.
- **Number issues sequentially.** Renumber after deletions to keep the sequence contiguous.

## Lifecycle

1. **Created** during implementation planning or code generation when a spec problem is found.
2. **Read** by the specifier during the next specification revision pass.
3. **Issues removed** as the specifier resolves them in the source specification.
4. **File deleted** when all issues are resolved (no empty feedback files).
