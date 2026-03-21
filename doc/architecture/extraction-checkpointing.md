# Extraction Checkpointing

How the extraction pipeline supports incremental re-extraction of changed files and resumption of interrupted campaigns.

**Feature**: [Incremental Extraction](../features/incremental-extraction.md)
**Data models**: [extraction-types.md](data-models/extraction-types.md)

---

## Overview

Checkpointing serves two related but distinct use cases:

1. **Incremental re-extraction** — source files changed; re-extract only affected proofs and merge with prior results
2. **Campaign resumption** — extraction was interrupted; continue from the last completed proof

Both use cases share a checkpoint file that records extraction progress. The checkpoint is a sidecar file alongside the output — never embedded in the output stream.

## Checkpoint File

```
<output_path>.checkpoint
```

The checkpoint file is a JSON file (not JSON Lines) that records:

| Field | Type | Purpose |
|-------|------|---------|
| `schema_version` | positive integer | Checkpoint format version |
| `campaign_metadata` | CampaignMetadata | The campaign's provenance (projects, versions) |
| `completed_proofs` | map of theorem_name → file hash | Which proofs have been successfully extracted |
| `completed_files` | map of source_file → content hash | Which files have been fully processed |
| `last_position` | object | Project index, file index, theorem index at interruption |

### Content Hashing

File content hashes are computed from the .v source file contents. The hash algorithm is implementation-defined but must be deterministic. The hash serves two purposes:

- **Change detection** for incremental extraction: if a file's hash differs from the checkpoint, its proofs are re-extracted
- **Consistency verification** for resumption: if a file's hash differs, the checkpoint is stale and the file is re-extracted

## Incremental Re-Extraction Pipeline

```
incremental_extract(project_dirs[], output_path, options)
  │
  ├─ Load checkpoint from <output_path>.checkpoint
  │    If checkpoint does not exist → fall through to full extraction
  │
  ├─ Validate checkpoint consistency:
  │    Campaign metadata (project list, Coq versions) must match
  │    If mismatch → discard checkpoint, full extraction
  │
  ├─ Build campaign plan (same as full extraction)
  │
  ├─ Classify each file:
  │    File hash matches checkpoint → unchanged (skip all proofs)
  │    File hash differs → changed (re-extract all proofs in file)
  │    File not in checkpoint → new (extract all proofs)
  │    File in checkpoint but not in plan → removed (drop from output)
  │
  ├─ Load prior extraction output for unchanged proofs
  │
  ├─ Extract proofs from changed and new files (same per-proof pipeline)
  │
  ├─ Merge: prior results for unchanged files + new results for changed/new files
  │    Merge order: deterministic (same ordering as full extraction)
  │
  ├─ Write merged output (replaces prior output file)
  │
  └─ Update checkpoint file
```

### File-Level Granularity

Change detection operates at the file level, not the proof level. If any proof in a file changes, all proofs in that file are re-extracted. This simplification avoids the complexity of proof-level change detection (which would require parsing Coq source to identify proof boundaries and their dependencies) while still providing significant speedup — most files in a project do not change between runs.

### Output Equivalence

The merged output must be byte-identical to what a full extraction would produce. This means:

- Record ordering follows the same deterministic rules (project order, file order, declaration order)
- Records from unchanged files use the exact bytes from the prior extraction (not re-serialized)
- CampaignMetadata is regenerated (timestamp changes; tool version may change)

Exception: The `extraction_timestamp` in CampaignMetadata will differ between incremental and full runs. This is the only permitted difference. The timestamp reflects when extraction ran, not what was extracted.

## Campaign Resumption Pipeline

```
resume_extract(output_path)
  │
  ├─ Load checkpoint from <output_path>.checkpoint
  │    If checkpoint does not exist → error (nothing to resume)
  │
  ├─ Validate checkpoint consistency
  │    Project directories must still exist
  │    Coq versions must match
  │
  ├─ Rebuild campaign plan
  │
  ├─ Seek to last_position in the plan
  │
  ├─ Continue extraction from that position
  │    Output is appended to existing output file
  │
  ├─ When complete, rewrite output file with correct CampaignMetadata
  │    and ExtractionSummary (first and last records updated)
  │
  └─ Update checkpoint file
```

### Append-then-Rewrite

During resumption, new records are appended to the existing output file (which already contains the metadata and prior records). When extraction completes, the output file is rewritten to update the CampaignMetadata timestamp and to emit the ExtractionSummary. The rewrite ensures the final output has the correct structure (metadata first, summary last).

## Checkpoint Updates

The checkpoint file is updated after each proof is extracted (not after each file or project). This bounds the re-work on resumption to at most one proof.

The checkpoint write is not atomic — a crash during checkpoint update may corrupt the checkpoint. In that case, the next resumption attempt detects the corruption (invalid JSON) and falls back to full extraction. This is acceptable because checkpoint loss means re-extracting, which is correct (just slower).

## Design Rationale

### Why file-level rather than proof-level change detection

Proof-level change detection requires parsing Coq source to identify proof boundaries, tracking dependencies between proofs (a change to a helper lemma may affect proofs that use it), and handling proof reordering. File-level detection avoids all of this complexity. The cost is that a one-line change to a file re-extracts all proofs in that file — typically tens to hundreds of proofs, taking seconds to minutes. This is acceptable for the intended use case (iterative development on a project).

### Why a sidecar checkpoint file rather than embedded state

Embedding checkpoint state in the output stream would complicate the JSON Lines format (checkpoint records interleaved with proof records) and make the output format dependent on the checkpointing mechanism. A sidecar file keeps the output format clean and allows the checkpoint to be deleted independently of the output.

### Why non-atomic checkpoint writes

Atomic file writes (write to temp, rename) add platform-dependent complexity. The consequence of a corrupted checkpoint is a full re-extraction, which is always correct. For the intended scale (hours, not days), this tradeoff is acceptable.
