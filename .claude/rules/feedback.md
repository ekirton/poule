---
globs: "**/feedback/**"
---

# Feedback Filing Rules

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
| **Severity** | `high` / `medium` / `low` (see per-layer definitions below). |
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

## Per-Layer Severity Definitions

**doc/architecture/feedback/**: high = blocks specification or causes contradictions across multiple specs; medium = forces a spec writer judgment call the architecture should have made; low = documentation clarity or future-proofing.

**specification/feedback/**: high = blocks implementation or causes incorrect behavior; medium = forces an implementer judgment call the spec should have made; low = documentation clarity, edge case coverage, or future-proofing.

**src/feedback/**: high = test fails or contract violated; medium = implementation works but diverges from spec intent; low = code quality, performance, or clarity.

**test/feedback/**: high = test cannot pass with correct implementation, or produces false passes; medium = test is fragile or underspecified; low = clarity or coverage gap.

## Resolution Paths

- **Architecture feedback:** Architecture wrong → fix to match data model or requirements. Data model wrong → fix or escalate. Requirements wrong → escalate to stakeholder.
- **Specification feedback:** Spec wrong → fix to match upstream. Architecture wrong → file in `doc/architecture/feedback/`.
- **Implementation feedback:** Implementation wrong → fix code, run tests. Test wrong → file in `test/feedback/`. Spec wrong → file in `specification/feedback/`.
- **Test feedback:** Test wrong → fix to match spec. Spec wrong → file in `specification/feedback/`. Architecture wrong → file in `doc/architecture/feedback/`.

## Lifecycle

Created when a problem is found → read by the author → issues resolved or escalated → issues removed → file deleted when empty.
