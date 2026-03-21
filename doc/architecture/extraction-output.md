# Extraction Output Format

How extracted proof traces are serialized to JSON Lines, how provenance metadata is structured, and how the output stream is organized.

**Feature**: [Extraction Trace Format](../features/extraction-trace-format.md)
**Data models**: [extraction-types.md](data-models/extraction-types.md)

---

## Output Stream Structure

The extraction output is a single JSON Lines file. Each line is one self-contained JSON object with a `record_type` discriminator field. The stream has a fixed structure:

```
Line 1:     CampaignMetadata    (exactly one)
Lines 2–N:  ExtractionRecord    (one per successfully extracted proof)
            or ExtractionError  (one per failed proof)
Line N+1:   ExtractionSummary   (exactly one)
```

Records between the metadata and summary are emitted in deterministic order: projects in command-line order, files in sorted path order within each project, theorems in declaration order within each file. Error records appear in the same position as the proof that failed — they are not deferred to the end.

### Record Type Discrimination

Every JSON object in the output contains a `record_type` field as a top-level string. Consumers dispatch on this field:

| `record_type` | Type | Frequency |
|----------------|------|-----------|
| `"campaign_metadata"` | CampaignMetadata | Exactly once (first line) |
| `"proof_trace"` | ExtractionRecord | Zero or more |
| `"extraction_error"` | ExtractionError | Zero or more |
| `"extraction_summary"` | ExtractionSummary | Exactly once (last line) |

### Schema Version

All records share the same `schema_version` field, incremented on backward-incompatible changes to any record type. The version increment policy follows [proof-serialization.md](proof-serialization.md) § Schema Version.

## ExtractionRecord Serialization

```json
{
  "schema_version": 1,
  "record_type": "proof_trace",
  "theorem_name": "Coq.Arith.PeanoNat.Nat.add_comm",
  "source_file": "theories/Arith/PeanoNat.v",
  "project_id": "coq-stdlib",
  "total_steps": 5,
  "steps": [
    {
      "step_index": 0,
      "tactic": null,
      "goals": [
        {
          "index": 0,
          "type": "forall n m : nat, n + m = m + n",
          "hypotheses": []
        }
      ],
      "focused_goal_index": 0,
      "premises": [],
      "diff": null
    },
    {
      "step_index": 1,
      "tactic": "intros n m.",
      "goals": [
        {
          "index": 0,
          "type": "n + m = m + n",
          "hypotheses": [
            {"name": "n", "type": "nat", "body": null},
            {"name": "m", "type": "nat", "body": null}
          ]
        }
      ],
      "focused_goal_index": 0,
      "premises": [],
      "diff": {
        "goals_added": [],
        "goals_removed": [],
        "goals_changed": [{"index": 0, "before": "forall n m : nat, n + m = m + n", "after": "n + m = m + n"}],
        "hypotheses_added": [
          {"name": "n", "type": "nat", "body": null},
          {"name": "m", "type": "nat", "body": null}
        ],
        "hypotheses_removed": [],
        "hypotheses_changed": []
      }
    }
  ]
}
```

### Differences from Phase 2 ProofTrace

The ExtractionRecord differs from Phase 2's ProofTrace serialization in several ways:

| Aspect | Phase 2 ProofTrace | Phase 3 ExtractionRecord |
|--------|-------------------|--------------------------|
| Session ID | Included (`session_id` field) | Omitted (ephemeral, breaks determinism) |
| Premises | Separate PremiseAnnotation list | Embedded per-step in `premises` field |
| Diffs | Separate ProofStateDiff query | Embedded per-step in `diff` field (P1) |
| Project context | Not applicable (single-proof) | `project_id`, `source_file` relative to project root |
| Record type | Not present | `record_type: "proof_trace"` discriminator |

These changes reflect the shift from interactive (stateful session) to batch (self-contained record) consumption. Each ExtractionRecord is independently parseable without session context.

## ExtractionError Serialization

```json
{
  "schema_version": 1,
  "record_type": "extraction_error",
  "theorem_name": "Coq.Arith.PeanoNat.Nat.sub_diag",
  "source_file": "theories/Arith/PeanoNat.v",
  "project_id": "coq-stdlib",
  "error_kind": "timeout",
  "error_message": "Proof extraction exceeded 60s time limit"
}
```

Error messages use fixed templates with interpolated values to maintain determinism. The `error_kind` field enables programmatic filtering (e.g., "show me all backend crashes").

## CampaignMetadata Serialization

```json
{
  "schema_version": 1,
  "record_type": "campaign_metadata",
  "extraction_tool_version": "0.3.0",
  "extraction_timestamp": "2026-03-17T14:30:00Z",
  "projects": [
    {
      "project_id": "coq-stdlib",
      "project_path": "/home/user/.opam/default/lib/coq/theories",
      "coq_version": "8.19.1",
      "commit_hash": null
    },
    {
      "project_id": "mathcomp",
      "project_path": "/home/user/mathcomp",
      "coq_version": "8.19.1",
      "commit_hash": "a1b2c3d4e5f6"
    }
  ]
}
```

### Project ID Derivation

The `project_id` is derived from the project directory's basename. If multiple projects share the same basename, a numeric suffix is appended (`project`, `project-2`, `project-3`). The mapping is recorded in CampaignMetadata and applied consistently to all records.

### Timestamp Handling

The `extraction_timestamp` in CampaignMetadata is the only timestamp in the output. It is recorded once at campaign start. Individual ExtractionRecords do not carry timestamps — this avoids a source of nondeterminism (proof extraction durations vary across runs) and reduces per-record size.

## Determinism Contract

The output satisfies the byte-identical determinism requirement specified in [extraction-campaign.md](extraction-campaign.md) § Determinism. The output format contributes:

1. **Fixed field ordering**: Fields are emitted in the order defined in [extraction-types.md](data-models/extraction-types.md), not alphabetical or hash-map order
2. **Explicit nulls**: Null fields are present (`"diff": null`), not omitted
3. **Compact JSON**: No optional whitespace, one JSON object per line, newline-terminated
4. **UTF-8 encoding**: All output is UTF-8 without BOM

## Streaming Writes

Records are written to the output stream as they are produced — the orchestrator does not buffer the entire dataset in memory. This means:

- Output is available for inspection during long extraction campaigns
- A crash loses at most the in-progress proof, not the entire dataset
- Memory usage is bounded by the largest single proof's trace, not the total dataset size

The tradeoff: the output file cannot be a valid JSON array (which requires knowing all elements before writing the closing bracket). JSON Lines is chosen specifically because it supports streaming writes.

## Design Rationale

### Why embed premises and diffs in ExtractionStep rather than separate lists

Phase 2 returns premises and diffs as separate queries because the interactive model supports selective access (inspect one step's premises without fetching the full trace). In batch extraction, every record includes everything — there is no selective access. Embedding premises and diffs per-step makes each record self-contained and avoids the need for consumers to align separate lists by step index.

### Why a single output file rather than one file per project or per proof

A single JSON Lines file is the simplest output format for downstream consumption — one path to open, one stream to process. Per-project files add file management overhead without benefit (the `project_id` field enables programmatic filtering). Per-proof files would produce tens of thousands of small files, which is hostile to filesystem performance and downstream tooling.

### Why record_type discriminator rather than separate output streams

Interleaving proof traces and error records in declaration order preserves locality — a consumer processing the output sequentially sees errors in context. Separating errors into a different file (or deferring them to the end) loses this locality and forces consumers to cross-reference two streams by position.
