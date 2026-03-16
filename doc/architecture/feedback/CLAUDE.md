# Architecture Feedback Writing Guidelines

## Authority

Architecture feedback is informed by the authority chain: data model documents (`doc/architecture/data-models/`) → architecture documents (`doc/architecture/`) → requirements and features (`doc/requirements/`, `doc/features/`). When filing feedback, verify the issue against the authoritative source before reporting it.

**Before writing feedback:** Read the relevant data model documents (`doc/architecture/data-models/expression-tree.md`, `doc/architecture/data-models/index-entities.md`) and any related architecture documents. An apparent issue may already be resolved in a higher-authority source — in that case, cite that source and recommend aligning the architecture document with it.

## Purpose

Feedback documents capture issues, ambiguities, contradictions, and gaps discovered in architecture documents during specification writing, implementation planning, or code generation. They exist to inform the architect — not to fix the architecture directly.

## File Naming

One feedback file per architecture document. Name matches the source:

```
doc/architecture/feedback/<doc-name>.md
```

Example: feedback for `doc/architecture/retrieval-pipeline.md` goes in `doc/architecture/feedback/retrieval-pipeline.md`.

## Document Structure

```markdown
# Architecture Feedback: <document title>

**Source:** [doc/architecture/<name>.md](../<name>.md)
**Date:** <YYYY-MM-DD of last update>
**Reviewer:** <role or context, e.g., "Specification writer (channel-mepo spec)">

---

## Issue <N>: <Short descriptive title>

**Severity:** <high | medium | low>
**Section:** <document section number and name>

**Problem:** <What is wrong, ambiguous, or missing. State the conflict precisely — quote the document where helpful.>

**Impact:** <What breaks or diverges downstream if this is not resolved. Frame in terms of specification or implementation consequences.>

**Suggested resolution:** <Concrete recommendation. If multiple options exist, list them with trade-offs. Label your preferred option.>

---
```

## Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| **Source** | yes | Relative link to the architecture document this feedback targets. |
| **Date** | yes | Date of last update (absolute, YYYY-MM-DD). Update when issues are added or removed. |
| **Reviewer** | yes | Who or what produced the feedback. |
| **Severity** | yes | `high` = blocks specification or causes contradictions across multiple specs. `medium` = forces a spec writer judgment call the architecture should have made. `low` = documentation clarity or future-proofing. |
| **Section** | yes | Document section number and name where the issue originates. If it spans sections, list the primary one and mention others in the problem description. |
| **Problem** | yes | The issue. Be specific: quote the conflicting text, name the contradicting document, or describe the missing information. |
| **Impact** | yes | What happens downstream if this is not resolved. |
| **Suggested resolution** | yes | At least one concrete fix. |

## Writing Rules

- **One issue per heading.** Do not combine multiple problems into a single issue.
- **Reference cross-document conflicts explicitly.** If two architecture documents or a data model and an architecture document disagree, name both files and quote both passages.
- **Use absolute section references** (e.g., "Section 3.2, `dependencies` table"), not relative ones (e.g., "the section above").
- **No fixes in feedback files.** Feedback describes what is wrong and suggests a resolution. The architect decides.
- **Remove resolved issues.** When the architect resolves an issue, delete it from the feedback file. Do not mark it as resolved — remove it entirely.
- **Delete empty feedback files.** When all issues in a feedback file are resolved and removed, delete the file. No empty feedback files.
- **Number issues sequentially.** Renumber after deletions to keep the sequence contiguous.

## Resolving Feedback

When asked to resolve a feedback file, follow this workflow for each issue:

1. **Read the feedback issue.** Understand the claimed problem, the affected section, and the suggested resolution.
2. **Read the upstream authority.** Read the data model documents and any related requirements or feature documents. Identify the authoritative definition for the design element in question.
3. **Determine the root cause:**
   - **Architecture document is wrong:** The document conflicts with the data model or misinterprets the requirements. The upstream authority is correct. Fix the architecture document to match the upstream authority.
   - **Data model is wrong:** The conflict originates in a data model document. The architecture document's intent is correct but the data model is ambiguous or contradictory. Fix the data model document if you are the data model owner. Otherwise, escalate to the data model owner.
   - **Requirements are wrong or ambiguous:** The conflict originates upstream of architecture. Do not change the requirements. Escalate to the relevant stakeholder.
4. **Remove the resolved issue** from the feedback file. Do not mark it as resolved — delete it entirely.
5. **Delete the feedback file** if all issues have been removed. No empty feedback files.

## Lifecycle

1. **Created** during specification writing or implementation planning when an architecture problem is found.
2. **Read** by the architect during the next architecture revision pass.
3. **Issues resolved** by fixing the architecture document or escalating to the upstream authority owner.
4. **Issues removed** from the feedback file after resolution. Do not mark as resolved — delete entirely.
5. **File deleted** when all issues are resolved and removed (no empty feedback files).
