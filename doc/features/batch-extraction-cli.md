# Batch Extraction CLI

A CLI command that processes one or more Coq project directories and extracts proof traces for all provable theorems, with deterministic output and graceful degradation on failure.

---

## Problem

AI researchers who want to train models on Coq proof data must currently write custom extraction scripts per project. There is no standard tool that walks a Coq project, extracts proof traces with premise annotations, and handles the inevitable failures that occur at scale (timeouts, unsupported tactics, backend crashes). Each research group solves this independently, producing incompatible datasets that cannot be compared or reproduced.

## Solution

A CLI command that accepts one or more Coq project directories and produces a structured dataset of proof traces. The command:

- Processes each project's .v files, extracting proof traces for every provable theorem
- Produces one structured record per proof in a streaming output format
- Skips failed proofs with a structured error record and continues extraction
- Reports summary statistics after each run (total found, extracted, failed, skipped, per-file breakdown)
- Produces byte-identical output for identical inputs across runs

For multi-project campaigns, the output includes project-level metadata so records can be attributed to their source project.

## Design Rationale

### Why CLI-first, not MCP

Batch extraction is a pipeline operation — process a directory, emit a dataset, exit. There is no conversational state, no interactive feedback loop, and no benefit from LLM mediation. A CLI command integrates naturally with shell scripts, CI pipelines, and job schedulers. MCP exposure would add protocol overhead without value.

### Why graceful degradation is P0

At extraction scale (tens of thousands of proofs across multiple projects), some proofs will fail — timeouts, unsupported tactic extensions, version-specific kernel behavior. If one failure aborts the entire run, extraction becomes impractical. CoqGym handled this with per-proof isolation; LeanDojo does the same. Structured error records let researchers analyze failure patterns and improve coverage iteratively.

### Why byte-identical determinism

ML experiment reproducibility requires exact dataset reproducibility. If extraction produces different output on repeated runs (due to nondeterministic ordering, floating timestamps in the output, or hash-map iteration order), researchers cannot verify that a dataset was produced from claimed inputs. Byte-identical output also enables simple integrity checking via checksums.

### Why multi-project campaigns in a single invocation

Researchers building large datasets (100K+ theorems) combine proofs from stdlib, MathComp, and additional projects. A single-invocation campaign avoids manual output merging, ensures consistent provenance metadata, and enables cross-project deduplication in later phases.

### Why no GPU, API keys, or network access

Extraction must run in constrained environments — university compute clusters, CI runners, air-gapped machines. The only external dependency is Coq itself and whatever Coq needs to build the project (typically opam packages). This constraint ensures the tool is accessible to any researcher with a Coq installation.

## Scope Boundaries

The batch extraction CLI provides:

- Project-level extraction across one or more directories
- Deterministic, reproducible output
- Graceful skip-and-continue on per-proof failures
- Summary statistics with per-file and per-project breakdowns

It does **not** provide:

- Interactive proof exploration (that is MCP-mediated, Phase 2)
- Single-proof extraction (use Phase 2's `replay-proof` CLI)
- Dataset post-processing (quality reports, benchmarks, export — separate features)
- Real-time extraction during editing

## Acceptance Criteria

### Single-Project Extraction

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project directory that builds successfully WHEN the extraction command is run on it THEN one structured proof trace record is produced per provable theorem
- GIVEN a Coq project directory WHEN the extraction command is run THEN it does not require a GPU, external API keys, or network access beyond what Coq itself needs to build the project
- GIVEN a project with N provable theorems WHEN extraction completes THEN the output contains exactly one record per successfully extracted theorem

**Traces to:** R3-P0-1, R3-P0-10, R3-P0-12

### Multi-Project Extraction

**Priority:** P0
**Stability:** Stable

- GIVEN a list of Coq project directories WHEN the extraction command is run with the list THEN it processes each project and produces a unified dataset
- GIVEN a multi-project extraction WHEN the output is inspected THEN each record includes project-level metadata identifying which project it came from
- GIVEN a multi-project extraction WHEN one project fails entirely THEN the remaining projects are still extracted
- GIVEN the Coq standard library, MathComp, and at least two additional Coq projects WHEN a multi-project extraction completes THEN the total extracted theorem count is ≥ 100,000

**Traces to:** R3-P0-9, R3-P0-10

### CLI Interface

**Priority:** P0
**Stability:** Stable

- GIVEN a single project directory WHEN the extraction CLI is invoked with that directory THEN extraction proceeds on that project
- GIVEN a list of project directories WHEN the extraction CLI is invoked with the list THEN extraction proceeds on each project in turn
- GIVEN missing required arguments WHEN the CLI is invoked THEN it exits with a usage error and nonzero exit code

**Traces to:** R3-P0-10

### Byte-Identical Output

**Priority:** P0
**Stability:** Stable

- GIVEN the same project directory at the same commit WHEN extraction is run twice THEN the two output files are byte-identical
- GIVEN the same set of projects WHEN a multi-project extraction is run twice THEN the two output files are byte-identical
- GIVEN a deterministic extraction WHEN the output is diffed across runs THEN there are zero differences (no timestamps, random orderings, or nondeterministic serialization)

**Traces to:** R3-P0-4

### Skip Failed Proofs

**Priority:** P0
**Stability:** Stable

- GIVEN a project where proof P fails to extract WHEN extraction runs THEN a structured error record is emitted for P and extraction continues for all remaining proofs in the file and project
- GIVEN a structured error record WHEN it is inspected THEN it includes the theorem name, file path, and a description of the failure
- GIVEN a project with 100 proofs where 3 fail WHEN extraction completes THEN the output contains 97 successful trace records and 3 error records

**Traces to:** R3-P0-5

### Extraction Summary Statistics

**Priority:** P0
**Stability:** Stable

- GIVEN a completed extraction WHEN the summary is inspected THEN it includes total theorems found, successfully extracted, failed, and skipped counts
- GIVEN a completed extraction WHEN the summary is inspected THEN it includes a per-file breakdown of the same counts
- GIVEN a multi-project extraction WHEN the summary is inspected THEN it includes per-project rollups

**Traces to:** R3-P0-6
