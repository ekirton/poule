# Before You Start

**Before writing or editing any architecture document:**

1. Read `component-boundaries.md` for the system-level boundary graph and dependency map.
2. Read `data-models/expression-tree.md` and `data-models/index-entities.md` — these are **authoritative** for all entity names, node label names (e.g., `LAbs` not `LLambda`, `LLet` not `LLetIn`, `LPrimitive` not `LInt`), field types, constraints, and relationships. Architecture documents must use the exact names defined in the data model documents.
3. When an entity appears in both a data model document and an architecture document, the data model document is authoritative for structure; the architecture document is authoritative for usage.

## Architecture Documents (Component Specifications)

**Layer:** 3 — Design Specification

**Location:** `doc/architecture/<component-or-concern>.md`

**Authority:** Architecture documents are **derived from** feature documents (`doc/features/`) and user stories (`doc/requirements/stories/`). They are authoritative for downstream specifications (`specification/`). Data model documents (`data-models/`) are authoritative for entity structure — architecture documents must not contradict them on entity names, field types, or constraints.

**When writing or editing architecture documents:**

- Follow the specification document structure from `specification/CLAUDE.md` (Purpose, Scope, Definitions, Behavioral Requirements, Data Model, Interface Contracts, State and Lifecycle, Error Specification, NFRs, Examples, Language-Specific Notes). Omit empty sections for small components.
- Open each document with a pointer to the corresponding feature document in `doc/features/`.
- Describe **how** a feature is implemented at the design level — pipelines, data flows, component responsibilities, boundary contracts. Do not re-state **what** the feature does (that belongs in the feature document).
- Keep content language-agnostic. If a platform migration would invalidate a statement, move it to Language-Specific Notes.
- Declare component boundaries and inter-component contracts explicitly — these are the primary input to the LLM spec-extraction pipeline that produces `specification/` artifacts.
- **Verify consistency**: Before finalizing, cross-check all entity names, node labels, and field names against `data-models/` documents. A naming mismatch between architecture and data model is a defect.

**One per:** component, pipeline, or cross-cutting concern

## Component Boundary Document

**Location:** `doc/architecture/component-boundaries.md` (singleton)

- This is a **summary derived from** architecture documents — not a source of truth for boundary design.
- When this document and an architecture document disagree, the architecture document wins.
- Maintain: component taxonomy, dependency graph, boundary contracts (direction + guarantees), and source-to-specification mapping.

## Data Model Documents

**Location:** `doc/architecture/data-models/<domain-or-component>.md`

- Extract a standalone data model document when entities are shared across multiple components or are complex enough to warrant it.
- Define entities with domain-level types, all constraints, validation rules, and relationships with cardinality.
- When an entity appears in both a data model document and an architecture document, the data model document is authoritative for structure; the architecture document is authoritative for usage.
