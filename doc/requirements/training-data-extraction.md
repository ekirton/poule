# Training Data Extraction for Coq/Rocq — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context and initiative sequencing.

Lineage: The Proof Interaction Protocol identified proof trace export (R2-P2-1) and benchmark generation (R2-P2-2) as deferred capabilities. This initiative promotes and expands those capabilities into a complete extraction pipeline.

## 1. Business Goals

Coq/Rocq has no modern training data extraction infrastructure. CoqGym is frozen at 71K theorems on Coq 8.9 (2019). LeanDojo v2 provides 122K+ theorems with per-tactic premise annotations, incremental tracing, and continuously updated benchmarks for Lean 4. This infrastructure gap is the root cause of Coq's AI tooling lag: every Coq-focused AI project must independently solve the data problem, leading to duplicated effort, incompatible datasets, and results that cannot be reproduced or compared.

This initiative delivers a training data extraction pipeline for Coq/Rocq that processes proof developments at project scale, producing structured, versioned datasets of proof traces with premise annotations. It builds on the Proof Interaction Protocol and establishes the data foundation required by the LLM Copilot and Neural Premise Selection initiatives.

**Success metrics:**
- Successfully extract proof traces for ≥ 95% of provable theorems in the Coq standard library
- Successfully extract proof traces for ≥ 90% of provable theorems in MathComp
- Total extracted theorem count ≥ 100K across standard library, MathComp, and at least two additional Coq projects
- Premise annotation accuracy matches hand-curated ground truth on a validation set of ≥ 100 proofs
- Reproducibility: identical inputs produce byte-identical output across runs
- Extraction throughput sufficient to process the Coq standard library in under 1 hour on a single machine without GPU

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| AI researchers | Large-scale, structured proof trace datasets with premise annotations for training tactic prediction, premise selection, and proof synthesis models | Primary |
| LLM Copilot, Neural Premise Selection | Proof traces for fine-tuning and few-shot prompting; (goal, premises_used) pairs for training retrieval models | Primary |
| Tool builders | Reproducible, versioned datasets for benchmarking and evaluation of Coq-focused AI tools | Secondary |
| Coq library maintainers | Dataset quality reports identifying proofs that fail extraction, enabling library hygiene improvements | Tertiary |

---

## 3. Competitive Context

Cross-references:
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)
- [Premise selection and retrieval survey](../background/coq-premise-retrieval.md)

**Lean ecosystem (comparative baseline):**
- LeanDojo v2: proof states at every tactic step, per-tactic premise annotations, incremental tracing, 122K+ theorems, continuously updated benchmarks, gym-like interactive environment
- lean-training-data: additional extraction tooling for Lean 4
- Multiple downstream consumers (ReProver, LeanHammer, REAL-Prover) all built on this shared data infrastructure

**Coq ecosystem (current state):**
- CoqGym: 71K theorems from 123 projects, frozen at Coq 8.9 (2019), no premise annotations, no incremental tracing
- SerAPI: deep serialization but version-locked, requires OCaml expertise, no premise annotations
- coq-lsp: IDE-focused, not designed as an ML pipeline tool
- No dataset versioning, no quality reporting, no reproducibility guarantees

**Key research findings informing requirements:**
- Graph structure encodes 25–34% additional retrieval signal (Graph2Tac, RGCN), motivating dependency graph extraction alongside proof traces
- Domain-specific tokenization improves retrieval 30%+, motivating rich structured output rather than flat text
- Retrieval from curated libraries is more valuable than dynamic lemma generation (LEGO-Prover), motivating comprehensive extraction from established Coq libraries
- Explicit retrieval provides ~12pp improvement even for large LLMs (REAL-Prover), confirming the value of premise annotation data
- Coq's unique value for training data lies in industrial verification projects (CompCert, Fiat-Crypto, Iris) that have no Lean equivalent

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R3-P0-1 | Process a Coq project directory and extract proof traces for all provable theorems, producing one structured record per proof |
| R3-P0-2 | Each proof trace record includes: theorem name (fully qualified), source file path, per-step proof states (goals, hypotheses, local context), per-step tactic text, and per-step premise annotations (which lemmas, hypotheses, constructors, and definitions each tactic used) |
| R3-P0-3 | Output extraction results in JSON Lines format (one JSON object per line, one proof per record) with a declared schema version |
| R3-P0-4 | Identical inputs produce byte-identical output across runs (deterministic extraction) |
| R3-P0-5 | When a single proof fails to extract, skip it with a structured error record and continue extracting remaining proofs in the file and project (graceful degradation) |
| R3-P0-6 | Report extraction summary statistics after each run: total theorems found, successfully extracted, failed, and skipped, with per-file breakdown |
| R3-P0-7 | Extract proof traces from the Coq standard library with ≥ 95% success rate |
| R3-P0-8 | Extract proof traces from MathComp with ≥ 90% success rate |
| R3-P0-9 | Support extraction across multiple Coq projects in a single campaign, producing a unified dataset with project-level metadata |
| R3-P0-10 | Expose extraction as a CLI command that operates on a project directory or a list of project directories |
| R3-P0-11 | Record provenance metadata in the output: Coq version, project commit hash, extraction tool version, and extraction timestamp |
| R3-P0-12 | Extraction must not require a GPU, external API keys, or network access beyond what Coq itself needs to build the project |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R3-P1-1 | Incremental extraction: when a project has been previously extracted and only some source files have changed, re-extract only the affected proofs and merge results with the prior extraction |
| R3-P1-2 | Extract the theorem dependency graph for each project: which theorems, definitions, and axioms each proof depends on, output as a structured adjacency list |
| R3-P1-3 | Produce dataset quality reports: premise annotation coverage (percentage of tactic steps with at least one annotated premise), distribution of proof lengths, tactic vocabulary frequency, and per-project breakdowns |
| R3-P1-4 | Support configurable extraction scope: extract all proofs, only proofs matching a name pattern, or only proofs in specified modules |
| R3-P1-5 | Resume a partially completed extraction campaign from the point of interruption without re-extracting already-completed proofs |
| R3-P1-6 | Include proof state diffs (what changed between consecutive tactic steps) alongside full proof state snapshots in the output |
| R3-P1-7 | Support extraction from arbitrary opam-installable Coq projects, validated on at least two standard-Ltac projects (e.g., Flocq, stdpp) and two ssreflect-based projects (e.g., MathComp satellites) |
| R3-P1-8 | Produce extraction error analysis reports from completed extraction output: aggregate errors by error kind and by source module, identify successful proofs near the timeout threshold, and report the overall error distribution to guide extraction improvements |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R3-P2-1 | Support extraction from projects that use custom proof modes or domain-specific tactic frameworks (e.g., Iris iProofMode, CompCert decision procedures), accepting reduced premise annotation granularity where custom tactics wrap standard Coq tactics |
| R3-P2-2 | Generate benchmark subsets from extracted data: split by difficulty (proof length, tactic diversity), by domain (arithmetic, algebra, logic), or by project |
| R3-P2-3 | Export extracted data to common ML framework formats (HuggingFace Datasets, PyTorch-compatible) |
| R3-P2-4 | Validate extracted proof traces by replaying tactic sequences and confirming they reproduce the original proof |
| R3-P2-5 | Provide dataset deduplication: identify and flag semantically equivalent proofs across projects |

---

## 5. Scope Boundaries

**In scope:**
- Batch extraction of proof traces with premise annotations from Coq projects
- Structured, versioned output format (JSON Lines) with provenance metadata
- CLI-driven extraction campaigns across one or more projects
- Extraction summary statistics and quality reporting
- Incremental re-extraction for changed files
- Dependency graph extraction at the theorem level
- Support for standard-Ltac and ssreflect-based Coq projects

**Out of scope:**
- Model training, fine-tuning, or evaluation
- Tokenizer or embedding development for extracted data
- Real-time extraction during editing or interactive proof development
- Proof synthesis or automated theorem proving
- Web interface or API server for dataset access
- Neural premise selection model development
- Tactic suggestion or auto-completion
- Cross-language extraction (Lean, Isabelle)
- MCP server exposure (extraction is a batch pipeline, not an interactive tool)
