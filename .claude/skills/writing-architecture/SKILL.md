---
name: writing-architecture
description: Architecture document standards — document format, component boundaries, data model documents. Use when creating or editing doc/architecture/ files.
---

# Architecture Document Standards

## Architecture Documents

**Layer:** 3 -- Design Specification
**Location:** `doc/architecture/<component-or-concern>.md`
**Derived from:** `doc/features/`
**Authoritative for:** `specification/`

- Open each document with a pointer to the corresponding feature document.
- Describe **how** -- pipelines, data flows, component responsibilities, boundary contracts. Do not re-state **what** (that belongs in the feature document).
- Keep content language-agnostic. Platform-specific statements go in Language-Specific Notes.
- Declare component boundaries and inter-component contracts explicitly.
- Cross-check all entity names, node labels, and field names against `data-models/` before finalizing.

**One per:** component, pipeline, or cross-cutting concern

## Component Boundary Document

**Location:** `doc/architecture/component-boundaries.md` (singleton)

Summary derived from architecture documents -- not a source of truth. Architecture documents win on disagreement. Maintains: component taxonomy, dependency graph, boundary contracts, source-to-specification mapping.

## Data Model Documents

**Location:** `doc/architecture/data-models/<domain-or-component>.md`

Extract when entities are shared across components or complex enough to warrant standalone treatment. Define entities with domain-level types, constraints, validation rules, and relationships with cardinality.
