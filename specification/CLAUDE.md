# Specification Writing Guidelines

## Authority

Specifications are derived from architecture documents (`doc/architecture/`).

**Before writing or editing:**

1. Read the parent architecture document.
2. Read `doc/architecture/data-models/expression-tree.md` and `doc/architecture/data-models/index-entities.md` — authoritative for all entity names, field types, constraints, node labels, and relationships.
3. Read `doc/architecture/component-boundaries.md` for boundary contracts.
4. Architecture wins over specification. Data model wins over architecture on entity structure.

**Cross-spec consistency:** verify referenced types, labels, and contracts against the defining specification.

For writing standards (document structure, EARS template, Design by Contract, interface contracts, state machines, error specification), see the `writing-specs` skill.
