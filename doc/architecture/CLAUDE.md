# Before You Start

1. Read `component-boundaries.md` for the system-level boundary graph.
2. Read `data-models/expression-tree.md` and `data-models/index-entities.md` — authoritative for all entity names, node labels (e.g., `LAbs` not `LLambda`, `LLet` not `LLetIn`, `LPrimitive` not `LInt`), field types, and constraints.
3. Data model documents are authoritative for entity structure; architecture documents are authoritative for usage.

## Upstream Authority Is Immutable

Do not modify `doc/features/` or `doc/requirements/` when writing architecture documents. File feedback with the relevant stakeholder if upstream is ambiguous or contradictory.

## Data Model Authority

Do not modify `data-models/`. If an architecture document conflicts with a data model, file feedback in `doc/architecture/feedback/` per `doc/architecture/feedback/CLAUDE.md`.

## Architecture Documents

**Layer:** 3 — Design Specification
**Location:** `doc/architecture/<component-or-concern>.md`
**Derived from:** `doc/features/`
**Authoritative for:** `specification/`

- Open each document with a pointer to the corresponding feature document.
- Describe **how** — pipelines, data flows, component responsibilities, boundary contracts. Do not re-state **what** (that belongs in the feature document).
- Keep content language-agnostic. Platform-specific statements go in Language-Specific Notes.
- Declare component boundaries and inter-component contracts explicitly.
- Cross-check all entity names, node labels, and field names against `data-models/` before finalizing.

**One per:** component, pipeline, or cross-cutting concern

## Component Boundary Document

**Location:** `doc/architecture/component-boundaries.md` (singleton)

Summary derived from architecture documents — not a source of truth. Architecture documents win on disagreement. Maintains: component taxonomy, dependency graph, boundary contracts, source-to-specification mapping.

## Data Model Documents

**Location:** `doc/architecture/data-models/<domain-or-component>.md`

Extract when entities are shared across components or complex enough to warrant standalone treatment. Define entities with domain-level types, constraints, validation rules, and relationships with cardinality.
