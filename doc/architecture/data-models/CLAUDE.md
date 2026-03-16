### 6. Data Model Documents

**Layer:** 3 — Design Specification

**Location:** `doc/architecture/data-models/<domain-or-component>.md`

**Purpose:** Defines the canonical data entities, their relationships, validation rules, and schema versioning semantics for a domain or component. Data model documents are extracted from architecture documents when the data model is shared across multiple components or is complex enough to warrant standalone treatment.

**Authority:** Data model documents are the **single source of truth** for entity structure. All downstream documents — architecture documents, specifications, and task breakdowns — must use the exact entity names, node label names, field names, types, and constraints defined here. If any other document contradicts a data model document on entity structure, the data model document wins.

**Authoritative for:**
- Entity definitions (fields, types, constraints, required/optional)
- Entity relationships (cardinality, directionality, referential integrity rules)
- Validation rules and domain constraints (ranges, formats, uniqueness)
- Schema versioning and migration semantics
- Canonical field names and type mappings
- **Canonical node label names** (e.g., `LAbs`, `LLet`, `LPrimitive` — not alternative names like `LLambda`, `LLetIn`, `LInt`)

**Relationship to other types:** Data model documents are referenced by architecture documents that share the same entities. They are consumed by the LLM spec-extraction pipeline alongside architecture documents. When an entity is defined in both a data model document and an architecture document, the data model document is authoritative for the entity's structure, and the architecture document is authoritative for how that entity is used within the component.

**Before writing or editing data model documents:** These are upstream authorities — changes here cascade to all downstream documents. Verify that any name or constraint change is intentional and update the architecture documents that reference the affected entities.

**One per:** domain area or shared data concern

**Standards**

For each entity, specify:

* The entity name and its purpose (one sentence)
* Its fields, with types expressed as domain concepts, not language-specific types
* Validation rules and constraints on each field
* Relationships to other entities. State relationships in terms of cardinality and ownership.
