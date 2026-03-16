# Specification Writing Guidelines

## Authority

Specifications are **derived from** architecture documents (`doc/architecture/`) — they are Layer 4 artifacts that decompose Layer 3 design into implementable units.

**Before writing or editing any specification:**

1. Read the parent architecture document referenced at the top of the spec.
2. Read `doc/architecture/data-models/expression-tree.md` and `doc/architecture/data-models/index-entities.md` — these are **authoritative** for all entity names, field types, constraints, node label names, and relationships. If a specification names an entity, field, node label, or constraint, it **must** match the data model documents exactly.
3. Read `doc/architecture/component-boundaries.md` for the dependency graph and boundary contracts.
4. When a specification and an architecture document disagree, the architecture document wins. When an architecture document and a data model document disagree on entity structure, the data model document wins.

**Cross-spec consistency:** When referencing types, labels, or contracts defined in another specification, read that specification to verify the names and signatures match. Do not assume — check.

## Upstream Authority Is Immutable

Architecture documents (`doc/architecture/`) and data model documents (`doc/architecture/data-models/`) **must not be modified** when writing specifications. Specifications are derived from these sources — not the other way around.

- If an architecture document appears ambiguous, contradictory, or incomplete, file feedback in `doc/architecture/feedback/` — do not change the architecture document.
- If a data model document conflicts with an architecture document, file feedback in `doc/architecture/feedback/` citing both sources.
- Follow the feedback standards defined in `doc/architecture/feedback/CLAUDE.md`.

## Core Principle

Specification misunderstanding — not model capability — is the primary cause of code generation failure. Every sentence must earn its place by adding information the implementer needs to make a decision. Noise actively degrades output quality.

## Document Structure

Follow this anatomy (omit empty sections for small components):

```
1. Purpose                  [required]
2. Scope                    [required]
3. Definitions              [if domain terms used]
4. Behavioral Requirements  [required]
5. Data Model               [if component owns/transforms data]
6. Interface Contracts      [if component has boundaries]
7. State and Lifecycle      [if behavior depends on history]
8. Error Specification      [required]
9. Non-Functional Reqs      [if applicable]
10. Examples                [required for complex behaviors]
11. Language-Specific Notes [separate section or file]
```

Order content critical-first: happy path → errors/edges → NFRs → nice-to-haves. Within components: inputs → outputs → errors → internals.

## Abstraction Level

- Describe **what** and **why**, with enough **how** to constrain — not dictate — the solution.
- A well-written spec admits at least two valid implementations. If only one implementation is possible, it's pseudo-code.
- Use domain language ("calculate total order price"), not solution language ("iterate array and sum item.price * quantity").
- Be precise at **boundaries** (inputs, outputs, errors, state transitions). Be abstract about **internal logic**.
- If a platform migration would invalidate a statement, it belongs in language-specific notes, not the core spec.

## Writing Requirements

Each requirement must be **atomic** (one behavior), **testable** (describable test exists), and **unambiguous** (one interpretation).

**Banned vague terms** — replace with measurable specifics: robust, efficient, user-friendly, flexible, reliable, secure, fast, scalable, appropriate, various, quickly, "in a timely manner."

**Fix ambiguity:** replace pronouns with nouns, use active voice with explicit actors, split compound "and" statements, clarify "or" (inclusive vs exclusive).

**EARS template** for unambiguous requirements:
```
[When <trigger>] [while <precondition>] the <system> shall <action> [the <object>]
```

## Behavioral Specs

Use **Design by Contract** for each operation:

| Element | Definition |
|---------|-----------|
| **REQUIRES** | What must be true before (caller's obligation) |
| **ENSURES** | What must be true after (implementer's obligation) |
| **MAINTAINS** | What is always true (both sides) |

Prioritize DbC for complex, multi-method, stateful components. Simple pure functions need less.

Include **2–3 concrete examples** per behavior in Given/When/Then format. Place examples immediately after the requirement they illustrate. Do not exceed 3 examples unless unusual edge cases exist.

## Data Model

- Define entities with domain-level types (e.g., "unique identifier" not "UUID", "monetary amount" not "f64").
- State all constraints, validation rules, and relationships with cardinality.

## Interface Contracts

For each boundary operation, specify: **Input**, **Output**, **Guarantees**, **Error strategy**, **Concurrency**, **Idempotency** (required for retriable operations).

A contract is complete when either side (caller or callee) can be implemented without reading the other's internals.

## State Machines

When an entity has a status/lifecycle, **always provide an explicit transition table** — never describe state behavior narratively.

```
| Current State | Event | Guard | Action | Next State |
```

Every non-terminal state needs at least one outbound transition. Every event must be accounted for in every non-terminal state.

## Error Specification

Classify errors per operation: **input error**, **state error**, **dependency error**, **invariant violation**. Specify the outcome for each.

Enumerate edge cases explicitly: empty input, boundary values, null/missing, duplicates, concurrent access, partial failure, repeated invocation. Every edge case must have a specified outcome.

## Signal Quality

- Target ≤ 3,000 tokens per section. Split longer sections.
- Prefer tables over prose for structured content (state transitions, error classifications, validation rules, data constraints).
- No TBD/TODO markers — make provisional decisions explicitly marked as such.
- No aspirational prose ("it is important that..."), redundant restatements, or narrative data flows spanning multiple components.
- Front-load critical requirements (LLMs attend more strongly to early content).

## Language Separation

Keep language-agnostic content (behaviors, contracts, data models, state machines, errors, examples) separate from language-specific content (framework choices, project structure, build commands, code style snippets). The agnostic layer must survive a technology migration unchanged.
