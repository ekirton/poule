# User Stories: Training Data Extraction

Derived from [doc/requirements/training-data-extraction.md](../training-data-extraction.md).

---

## Epic 1: Project-Level Extraction

### 1.1 Extract Proof Traces from a Single Project

**As an** AI researcher,
**I want to** run a CLI command on a Coq project directory and receive structured proof traces for all provable theorems,
**so that** I can build training datasets without writing custom extraction scripts.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq project directory that builds successfully WHEN the extraction command is run on it THEN one structured proof trace record is produced per provable theorem
- GIVEN a Coq project directory WHEN the extraction command is run THEN it does not require a GPU, external API keys, or network access beyond what Coq itself needs to build the project
- GIVEN a project with N provable theorems WHEN extraction completes THEN the output contains exactly one record per successfully extracted theorem

**Traces to:** R3-P0-1, R3-P0-10, R3-P0-12

### 1.2 Extract Proof Traces Across Multiple Projects

**As an** AI researcher building large-scale datasets,
**I want to** run extraction across multiple Coq projects in a single campaign,
**so that** I can produce a unified dataset without manually merging outputs.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a list of Coq project directories WHEN the extraction command is run with the list THEN it processes each project and produces a unified dataset
- GIVEN a multi-project extraction WHEN the output is inspected THEN each record includes project-level metadata identifying which project it came from
- GIVEN a multi-project extraction WHEN one project fails entirely THEN the remaining projects are still extracted
- GIVEN the Coq standard library, MathComp, and at least two additional Coq projects WHEN a multi-project extraction completes THEN the total extracted theorem count is ≥ 100,000

**Traces to:** R3-P0-9, R3-P0-10

### 1.3 CLI Interface

**As an** AI researcher or script author,
**I want to** invoke extraction as a CLI command that accepts a project directory or a list of project directories,
**so that** I can integrate extraction into automated pipelines and scripts.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a single project directory WHEN the extraction CLI is invoked with that directory THEN extraction proceeds on that project
- GIVEN a list of project directories WHEN the extraction CLI is invoked with the list THEN extraction proceeds on each project in turn
- GIVEN missing required arguments WHEN the CLI is invoked THEN it exits with a usage error and nonzero exit code

**Traces to:** R3-P0-10

---

## Epic 2: Proof Trace Record Structure

### 2.1 Per-Step Proof State and Tactic Capture

**As an** AI researcher training tactic prediction models,
**I want** each proof trace record to include per-step proof states (goals, hypotheses, local context) and per-step tactic text,
**so that** I can train models on (state, tactic) pairs at every step of the proof.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof of N tactic steps WHEN the trace record is inspected THEN it contains N+1 proof states and N tactic texts, one per step
- GIVEN a proof state at step k WHEN it is inspected THEN it includes all open goals, hypotheses, and local context at that step
- GIVEN a proof trace record WHEN it is inspected THEN it includes the theorem's fully qualified name and source file path

**Traces to:** R3-P0-2

### 2.2 Per-Step Premise Annotations

**As an** AI researcher training premise selection models,
**I want** each tactic step to include annotations identifying which lemmas, hypotheses, constructors, and definitions that tactic used,
**so that** I can construct (goal, premises_used) training pairs.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof trace record WHEN the premise annotations are inspected THEN each tactic step includes a list of premises used by that tactic
- GIVEN a premise annotation WHEN it is inspected THEN each premise includes its fully qualified name and kind (lemma, hypothesis, constructor, or definition)
- GIVEN the premise annotations for a validation set of ≥ 100 proofs WHEN compared against hand-curated ground truth THEN they match the ground truth

**Traces to:** R3-P0-2

### 2.3 Proof State Diffs

**As an** AI researcher analyzing proof evolution,
**I want** the output to include diffs showing what changed between consecutive tactic steps,
**so that** I can study the effect of individual tactics without diffing full states myself.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN consecutive proof states at steps k and k+1 WHEN the diff is inspected THEN it includes goals added, goals removed, goals changed, hypotheses added, hypotheses removed, and hypotheses changed
- GIVEN the diffs in a proof trace WHEN they are inspected alongside full proof state snapshots THEN both representations are present in the output

**Traces to:** R3-P1-6

---

## Epic 3: Output Format and Schema

### 3.1 JSON Lines Output

**As an** AI researcher consuming extraction output,
**I want** the output in JSON Lines format (one JSON object per line, one proof per record),
**so that** I can stream and process records in parallel without loading the entire dataset into memory.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed extraction WHEN the output file is inspected THEN each line is a valid JSON object representing one proof trace
- GIVEN the output WHEN it is inspected THEN it includes a declared schema version field in each record
- GIVEN the output WHEN it is processed line by line THEN each line is independently parseable without reference to other lines

**Traces to:** R3-P0-3

### 3.2 Provenance Metadata

**As an** AI researcher reproducing experiments,
**I want** the output to include provenance metadata: Coq version, project commit hash, extraction tool version, and extraction timestamp,
**so that** I can precisely identify how a dataset was produced.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the Coq version used to build the project
- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the project's git commit hash
- GIVEN a completed extraction WHEN the output metadata is inspected THEN it includes the extraction tool version and extraction timestamp

**Traces to:** R3-P0-11

---

## Epic 4: Determinism and Reproducibility

### 4.1 Byte-Identical Output

**As an** AI researcher comparing experiment runs,
**I want** identical inputs to produce byte-identical output across runs,
**so that** I can verify dataset integrity and ensure reproducibility of ML experiments.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the same project directory at the same commit WHEN extraction is run twice THEN the two output files are byte-identical
- GIVEN the same set of projects WHEN a multi-project extraction is run twice THEN the two output files are byte-identical
- GIVEN a deterministic extraction WHEN the output is diffed across runs THEN there are zero differences (no timestamps, random orderings, or nondeterministic serialization)

**Traces to:** R3-P0-4

---

## Epic 5: Graceful Degradation and Reporting

### 5.1 Skip Failed Proofs

**As an** AI researcher running extraction at scale,
**I want** a single proof failure to result in a structured error record while extraction continues for all remaining proofs,
**so that** one broken proof does not block dataset construction for an entire project.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project where proof P fails to extract WHEN extraction runs THEN a structured error record is emitted for P and extraction continues for all remaining proofs in the file and project
- GIVEN a structured error record WHEN it is inspected THEN it includes the theorem name, file path, and a description of the failure
- GIVEN a project with 100 proofs where 3 fail WHEN extraction completes THEN the output contains 97 successful trace records and 3 error records

**Traces to:** R3-P0-5

### 5.2 Extraction Summary Statistics

**As an** AI researcher evaluating extraction quality,
**I want** a summary report after each run showing total theorems found, successfully extracted, failed, and skipped, with per-file breakdown,
**so that** I can assess coverage and identify problematic files.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed extraction WHEN the summary is inspected THEN it includes total theorems found, successfully extracted, failed, and skipped counts
- GIVEN a completed extraction WHEN the summary is inspected THEN it includes a per-file breakdown of the same counts
- GIVEN a multi-project extraction WHEN the summary is inspected THEN it includes per-project rollups

**Traces to:** R3-P0-6

---

## Epic 6: Library Coverage

### 6.1 Coq Standard Library Extraction

**As an** AI researcher,
**I want to** extract proof traces from the Coq standard library with ≥ 95% success rate,
**so that** I can use the foundational Coq library as a reliable training data source.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the Coq standard library WHEN extraction is run THEN ≥ 95% of provable theorems produce successful proof trace records
- GIVEN the extraction output WHEN theorem names are inspected THEN they are fully qualified and match the standard library's module structure
- GIVEN the Coq standard library WHEN extraction is run on a single machine without GPU THEN extraction completes in under 1 hour

**Traces to:** R3-P0-7

### 6.2 MathComp Extraction

**As an** AI researcher working with advanced algebraic proofs,
**I want to** extract proof traces from MathComp with ≥ 90% success rate,
**so that** I can include ssreflect-style proofs in training data.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the MathComp library WHEN extraction is run THEN ≥ 90% of provable theorems produce successful proof trace records
- GIVEN MathComp proofs that use ssreflect tactics WHEN they are extracted THEN the per-step tactic text and proof states are correctly captured

**Traces to:** R3-P0-8

### 6.3 Arbitrary Opam-Installable Projects

**As an** AI researcher expanding dataset coverage,
**I want to** extract proof traces from arbitrary opam-installable Coq projects,
**so that** I can include diverse proof styles and domains in training data.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an opam-installable Coq project that builds successfully WHEN extraction is run THEN proof traces are produced for provable theorems in that project
- GIVEN at least two standard-Ltac projects (e.g., Flocq, stdpp) WHEN extraction is run THEN proof traces are successfully produced
- GIVEN at least two ssreflect-based projects (e.g., MathComp satellites) WHEN extraction is run THEN proof traces are successfully produced

**Traces to:** R3-P1-7

---

## Epic 7: Incremental Extraction and Resumption

### 7.1 Incremental Re-Extraction

**As an** AI researcher iterating on a Coq project,
**I want to** re-extract only the proofs affected by changed source files and merge results with the prior extraction,
**so that** I can efficiently update training data after incremental edits.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project previously extracted WHEN a subset of .v files have changed THEN only the affected proofs are re-extracted
- GIVEN an incremental re-extraction WHEN it completes THEN the resulting dataset is identical to what a full re-extraction would produce
- GIVEN an incremental re-extraction WHEN it runs THEN it completes faster than a full extraction

**Traces to:** R3-P1-1

### 7.2 Resume Interrupted Extraction

**As an** AI researcher running long extraction campaigns,
**I want to** resume a partially completed extraction from the point of interruption,
**so that** a crash or timeout does not force me to start over from scratch.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an extraction that was interrupted mid-campaign WHEN the extraction command is resumed THEN it continues from the last completed proof without re-extracting already-completed proofs
- GIVEN a resumed extraction WHEN it completes THEN the output is identical to what an uninterrupted extraction would produce

**Traces to:** R3-P1-5

---

## Epic 8: Dependency Graph Extraction

### 8.1 Theorem Dependency Graph

**As an** AI researcher training graph-based premise selection models,
**I want to** extract the theorem dependency graph showing which theorems, definitions, and axioms each proof depends on,
**so that** I can leverage graph structure for retrieval signal.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq project WHEN dependency graph extraction is run THEN it produces a structured adjacency list of theorem-level dependencies
- GIVEN a dependency graph entry for theorem T WHEN it is inspected THEN it lists the theorems, definitions, and axioms that T's proof depends on, each with a fully qualified name
- GIVEN the dependency graph WHEN it is serialized THEN it uses a structured format consistent with the extraction output schema

**Traces to:** R3-P1-2

---

## Epic 9: Dataset Quality and Filtering

### 9.1 Dataset Quality Reports

**As an** AI researcher assessing dataset fitness,
**I want** quality reports showing premise annotation coverage, proof length distributions, tactic vocabulary frequency, and per-project breakdowns,
**so that** I can identify gaps and biases in the training data.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed extraction WHEN the quality report is generated THEN it includes premise annotation coverage (percentage of tactic steps with at least one annotated premise)
- GIVEN a completed extraction WHEN the quality report is generated THEN it includes distribution of proof lengths and tactic vocabulary frequency
- GIVEN a multi-project extraction WHEN the quality report is generated THEN it includes per-project breakdowns of all metrics

**Traces to:** R3-P1-3

### 9.2 Configurable Extraction Scope

**As an** AI researcher building domain-specific datasets,
**I want to** configure extraction to include only proofs matching a name pattern or in specified modules,
**so that** I can build focused datasets without extracting and then filtering an entire project.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an extraction with a name pattern filter WHEN extraction runs THEN only proofs whose fully qualified names match the pattern are extracted
- GIVEN an extraction with a module filter WHEN extraction runs THEN only proofs in the specified modules are extracted
- GIVEN no filter is specified WHEN extraction runs THEN all provable theorems are extracted (default behavior)

**Traces to:** R3-P1-4

---

## Epic 10: Advanced Extraction and Export

### 10.1 Custom Proof Mode Support

**As an** AI researcher working with industrial Coq projects,
**I want** extraction to handle projects that use custom proof modes or domain-specific tactic frameworks,
**so that** I can include proofs from projects like Iris and CompCert in training data.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a project using custom proof modes (e.g., Iris iProofMode) WHEN extraction is run THEN proof traces are produced with best-effort premise annotations
- GIVEN a custom tactic that wraps standard Coq tactics WHEN extraction encounters it THEN the output accepts reduced premise annotation granularity rather than failing

**Traces to:** R3-P2-1

### 10.2 Benchmark Subset Generation

**As an** AI researcher designing evaluation benchmarks,
**I want to** generate benchmark subsets from extracted data split by difficulty, domain, or project,
**so that** I can evaluate models on controlled, reproducible benchmark slices.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an extracted dataset WHEN benchmark generation is run with a difficulty split THEN it produces subsets stratified by proof length and tactic diversity
- GIVEN an extracted dataset WHEN benchmark generation is run with a domain split THEN it produces subsets categorized by domain (arithmetic, algebra, logic)
- GIVEN an extracted dataset WHEN benchmark generation is run with a project split THEN it produces per-project subsets

**Traces to:** R3-P2-2

### 10.3 ML Framework Export

**As an** AI researcher using standard ML tooling,
**I want to** export extracted data to common ML framework formats (HuggingFace Datasets, PyTorch-compatible),
**so that** I can load training data directly into my training pipeline without format conversion.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an extracted dataset WHEN export to HuggingFace Datasets format is run THEN the output is loadable by the `datasets` library
- GIVEN an exported dataset WHEN it is loaded THEN the schema preserves all fields from the JSON Lines format

**Traces to:** R3-P2-3

### 10.4 Proof Trace Validation by Replay

**As an** AI researcher verifying dataset correctness,
**I want to** validate extracted proof traces by replaying tactic sequences against Coq,
**so that** I can confirm the extracted data faithfully represents the original proofs.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an extracted proof trace WHEN it is replayed against Coq THEN the replayed tactic sequence reproduces the original proof
- GIVEN a replay validation run WHEN it completes THEN it reports how many traces replayed successfully and how many failed

**Traces to:** R3-P2-4

### 10.5 Dataset Deduplication

**As an** AI researcher training on multi-project datasets,
**I want to** identify and flag semantically equivalent proofs across projects,
**so that** I can avoid training data leakage between train and test splits.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a multi-project dataset WHEN deduplication is run THEN semantically equivalent proofs across projects are identified and flagged
- GIVEN a flagged duplicate WHEN it is inspected THEN it includes references to all equivalent proofs

**Traces to:** R3-P2-5
