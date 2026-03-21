---
globs: "doc/architecture/data-models/**"
---
- Data model documents are the single source of truth for entity structure.
- All downstream documents must use the exact entity names, node labels, field names, types, and constraints defined here.
- Before editing: changes cascade to all downstream documents. Verify changes are intentional.
- For each entity, specify: name and purpose, fields with domain-level types, validation rules, constraints, and relationships with cardinality.
