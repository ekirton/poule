## Product Requirements Documents (PRD)

**Layer:** 1 — Stakeholder Intent

**Location:** `doc/requirements/<product-or-initiative>.md`

**Authority:** PRDs are the **top-level authority** for project scope, goals, and priorities. All downstream documents — features, architecture, specifications, and tasks — must be traceable to PRD requirements. PRDs are not derived from any other project document.

**When writing or editing PRDs:**

- Write in business domain language with no technical details.
- Capture: product goals, success metrics, target user segments, competitive context, and scope boundaries.
- Classify requirements by priority: P0 (must-have), P1 (should-have), P2+ (nice-to-have).
- State what is explicitly **out of scope**.
- PRDs are not consumed by the LLM spec-extraction pipeline directly — their content flows through feature and architecture documents.

**One per:** product initiative or major capability

## Backlog

**Location:** `doc/requirements/backlog.md` (singleton)

- A planning artifact, not a specification artifact.
- Reference feature documents by pointer — do not duplicate their content.
- Track: prioritized ordering, status (proposed/ready/in-progress/done), dependencies, and iteration assignment.
- Changes to the backlog do not trigger specification regeneration.
