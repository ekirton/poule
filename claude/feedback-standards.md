# Feedback File Standards

Shared standards for all `feedback/CLAUDE.md` files. Each layer's feedback CLAUDE.md references this file and adds only its layer-specific overrides.

## File Naming

One feedback file per source file. Name matches the source (without prefixes like `test_`).

## Document Structure

```markdown
# <Layer> Feedback: <source title>

**Source:** [<relative link to source>]
**Date:** <YYYY-MM-DD of last update>
**Reviewer:** <role or context>

---

## Issue <N>: <Short descriptive title>

**Severity:** <high | medium | low>
**Location:** <section, function, test method, or line reference>

**Problem:** <What is wrong. Quote the source and the authority where helpful.>

**Impact:** <What breaks if unresolved.>

**Suggested resolution:** <Concrete recommendation.>

---
```

## Required Fields

| Field | Description |
|-------|-------------|
| **Source** | Relative link to the file this feedback targets. |
| **Date** | Absolute date (YYYY-MM-DD). Update when issues change. |
| **Reviewer** | Who or what produced the feedback. |
| **Severity** | `high` / `medium` / `low` (layer-specific definitions in each feedback CLAUDE.md). |
| **Location** | Where the issue originates (section number, function name, test method + line). |
| **Problem** | The issue. Be specific: quote text, name sources, show math. |
| **Impact** | Downstream consequences if unresolved. |
| **Suggested resolution** | At least one concrete fix. |

## Writing Rules

- One issue per heading.
- Cite the authoritative source (spec section, architecture doc, data model).
- Reference cross-document conflicts explicitly — name both files, quote both passages.
- Use absolute section references, not relative ("Section 3.2", not "the section above").
- No fixes in feedback files — describe the problem and suggest a resolution.
- Remove resolved issues entirely (do not mark as resolved).
- Delete empty feedback files.
- Number issues sequentially; renumber after deletions.

## Resolving Feedback

1. Read the feedback issue.
2. Read the upstream authority for the behavior in question.
3. Determine root cause:
   - **Source file is wrong:** fix it to match the upstream authority.
   - **Upstream authority is wrong:** do not change it. File feedback in the upstream layer's feedback folder.
4. Remove the resolved issue entirely.
5. Delete the feedback file if all issues are removed.

## Lifecycle

Created when a problem is found → read by the author → issues resolved or escalated → issues removed → file deleted when empty.
