# Proof Serialization

Cross-cutting concern: how proof interaction data types are serialized to JSON for MCP responses and trace export.

**Feature**: [Proof Trace Serialization](../features/proof-trace-serialization.md), [Proof Interaction MCP Tools](../features/proof-mcp-tools.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Serialization Scope

This document covers the JSON serialization of all proof interaction types defined in [proof-types.md](data-models/proof-types.md). The same serialization is used for:

1. **MCP tool responses** — inline in MCP `content` blocks
2. **Proof trace export** — the output of `extract_proof_trace`
3. **Proof state diff output** — the output of the diff tool

## Schema Version

Every serialized ProofState and ProofTrace includes a `schema_version` field as a positive integer at the top level. This version identifies the structure of the JSON — field names, nesting, types, and semantics.

**Version increment policy**: The schema version is incremented when any backward-incompatible change is made:
- Field renamed or removed
- Field type changed
- Nesting structure changed
- Semantic meaning of a field changed

Additive changes (new optional fields) do not require a version increment.

The initial schema version is `1`.

## JSON Field Mapping

### ProofState

```json
{
  "schema_version": 1,
  "session_id": "abc-123",
  "step_index": 3,
  "is_complete": false,
  "focused_goal_index": 0,
  "goals": [
    {
      "index": 0,
      "type": "n + m = m + n",
      "hypotheses": [
        {"name": "n", "type": "nat", "body": null},
        {"name": "m", "type": "nat", "body": null},
        {"name": "IHn", "type": "n + m = m + n", "body": null}
      ]
    }
  ]
}
```

### ProofTrace

```json
{
  "schema_version": 1,
  "session_id": "abc-123",
  "proof_name": "Nat.add_comm",
  "file_path": "/path/to/Nat.v",
  "total_steps": 5,
  "steps": [
    {"step_index": 0, "tactic": null, "state": { "..." : "ProofState" }},
    {"step_index": 1, "tactic": "induction n.", "state": { "..." : "ProofState" }},
    {"step_index": 2, "tactic": "- simpl. reflexivity.", "state": { "..." : "ProofState" }}
  ]
}
```

### PremiseAnnotation

```json
{
  "step_index": 1,
  "tactic": "rewrite Nat.add_comm.",
  "premises": [
    {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "kind": "lemma"},
    {"name": "H", "kind": "hypothesis"}
  ]
}
```

### ProofStateDiff

```json
{
  "from_step": 2,
  "to_step": 3,
  "goals_added": [],
  "goals_removed": [{"index": 1, "type": "0 + m = m + 0", "hypotheses": []}],
  "goals_changed": [{"index": 0, "before": "S n + m = m + S n", "after": "S (n + m) = m + S n"}],
  "hypotheses_added": [{"name": "IHn", "type": "n + m = m + n", "body": null}],
  "hypotheses_removed": [],
  "hypotheses_changed": []
}
```

## Determinism Requirements

Identical input must produce byte-identical output. This requires:

1. **Field ordering**: Fields are emitted in the order defined by the data model (not alphabetical, not hash-map iteration order)
2. **List ordering**: Goals ordered by index, hypotheses ordered as Coq presents them, premises ordered by appearance in the tactic trace
3. **String representation**: Coq expressions are rendered as strings by the backend's pretty-printer; the same backend version on the same input must produce the same string
4. **Null handling**: Null fields are explicitly present (`"body": null`), not omitted
5. **Number formatting**: Integers serialized without leading zeros or decimal points

## Diff Computation (P1)

Proof state diff is a P1 (should-have) capability. The types (`ProofStateDiff`, `GoalChange`, `HypothesisChange`) are defined in [proof-types.md](data-models/proof-types.md) alongside P0 types for completeness.

The diff is computed by the session manager from two consecutive ProofState snapshots. The algorithm:

### Goal Matching

Goals are matched by index position. For each goal index present in both states:
- If the type differs → `goals_changed`
- If the type is identical → unchanged (not reported)

Goals present only in the earlier state → `goals_removed`.
Goals present only in the later state → `goals_added`.

### Hypothesis Matching

Hypotheses are matched by name within the focused goal. For each hypothesis name present in both states:
- If type or body differs → `hypotheses_changed`
- If both are identical → unchanged

Hypotheses present only in the earlier state → `hypotheses_removed`.
Hypotheses present only in the later state → `hypotheses_added`.

When goals are added or removed, their hypotheses are reported in `goals_added` / `goals_removed`, not in the hypothesis-level diff lists. The hypothesis-level diff tracks changes within goals that exist in both states.

## Design Rationale

### Why explicit field ordering rather than alphabetical

Alphabetical ordering is fragile — renaming a field changes its position, which changes the serialization of every record. Fixed ordering based on the data model is stable under field additions and produces output that reads naturally (schema_version first, then identifiers, then content).

### Why null fields are explicit

Omitting null fields creates ambiguity: does the absence of `body` mean null or that the serializer omitted it? Explicit nulls make the schema self-describing — every field in the data model appears in every serialized record. This simplifies client parsers (no need for "field present?" checks) and ensures deterministic output (no conditional field inclusion).

### Why diff matches goals by index rather than by content

Matching by content (structural similarity) would be more robust to goal reordering, but Coq's goal ordering is deterministic — the same tactic on the same state always produces goals in the same order. Index-based matching is simpler, O(N), and handles the common cases (goals closed, goals split, goals unchanged). Content-based matching can be added later if tactic-induced reordering proves to be a practical problem.
