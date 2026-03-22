# Extraction Dependency Graph

Theorem-level dependency graph extraction from premise annotations, producing structured adjacency lists for graph-based ML models.

**Architecture**: [extraction-dependency-graph.md](../doc/architecture/extraction-dependency-graph.md), [extraction-types.md](../doc/architecture/data-models/extraction-types.md)

---

## 1. Purpose

Define how theorem-level dependency graphs are derived from extraction output, how dependencies are classified, and how the graph is serialized. This is a P1 capability.

## 2. Scope

**In scope**: Dependency derivation from premise annotations, hypothesis exclusion, dependency deduplication, DependencyEntry serialization, integration modes (inline and post-hoc).

**Out of scope**: Graph neural network model training (Phase 4), cross-project dependency resolution, per-step premise extraction (owned by proof-session), visualization (owned by mermaid-renderer).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Dependency graph | A directed graph where each node is a theorem and each edge indicates that the source theorem's proof uses the target entity |
| Adjacency list | The representation of the graph: one entry per theorem, listing all entities its proof depends on |
| Hypothesis exclusion | The rule that local proof hypotheses are not included in the dependency graph |

## 4. Behavioral Requirements

### 4.1 Dependency Derivation

#### extract_dependencies(extraction_record)

- REQUIRES: `extraction_record` is a valid ExtractionRecord with per-step premise annotations.
- ENSURES: Returns a DependencyEntry containing: `theorem_name`, `source_file`, `project_id`, and a `depends_on` list of DependencyRef objects. The `depends_on` list is the union of all premises across all tactic steps, excluding premises with `kind = "hypothesis"`, deduplicated by fully qualified name.

> **Given** an ExtractionRecord for theorem `T` with steps using premises `[A(lemma), H(hypothesis), B(definition), A(lemma)]`
> **When** `extract_dependencies` is called
> **Then** the DependencyEntry has `depends_on = [A(lemma), B(definition)]` — `H` is excluded (hypothesis), `A` is deduplicated

> **Given** an ExtractionRecord where all premises are hypotheses
> **When** `extract_dependencies` is called
> **Then** the DependencyEntry has `depends_on = []`

### 4.2 Hypothesis Exclusion

The system shall exclude premises with `kind = "hypothesis"` from the dependency graph.

- MAINTAINS: Only premises with `kind` in `{"lemma", "definition", "constructor"}` appear in `depends_on`. Hypotheses are proof-internal bindings, not cross-theorem dependencies.

### 4.3 Dependency Classification

Each DependencyRef shall have a `kind` reflecting the entity type in the Coq environment:

| Premise `kind` | DependencyRef `kind` |
|----------------|---------------------|
| `lemma` | `"lemma"` or `"theorem"` (based on the referenced entity's declaration kind, when available; defaults to `"lemma"` when indistinguishable) |
| `definition` | `"definition"` |
| `constructor` | `"constructor"` |

- ENSURES: Every DependencyRef has a `kind` from the set `{"theorem", "lemma", "definition", "axiom", "constructor", "inductive"}`.

> **Given** a premise with `kind = "lemma"` referencing an entity declared as `Theorem`
> **When** the DependencyRef is created
> **Then** `kind` is `"theorem"`

### 4.4 Deduplication and Ordering

The system shall deduplicate `depends_on` entries by fully qualified name (keeping the first occurrence). The ordering shall be: first appearance across the proof's tactic steps, step 1 through step N, premises within each step in their original order.

- MAINTAINS: Ordering is deterministic for identical inputs.

> **Given** premise `A` appearing at step 1 and step 3, premise `B` at step 2
> **When** dependencies are deduplicated
> **Then** `depends_on` is ordered `[A, B]` (first appearance order)

### 4.5 DependencyEntry Serialization

The system shall serialize DependencyEntry as a JSON object with fields in the following order:

| Position | Field | JSON type | Source |
|----------|-------|-----------|--------|
| 1 | `theorem_name` | string | Fully qualified name |
| 2 | `source_file` | string | Path relative to project root |
| 3 | `project_id` | string | Project identifier |
| 4 | `depends_on` | array of DependencyRef | Deduplicated dependency list |

DependencyRef fields in order: `name` (string), `kind` (string).

- ENSURES: Returns a JSON object per entry. Output is JSON Lines format: one DependencyEntry per line.

### 4.6 Integration Modes

#### Post-hoc mode

```
extract_dependency_graph(extraction_output_path, output_path)
```

- REQUIRES: `extraction_output_path` is a valid JSON Lines extraction output file.
- ENSURES: Reads all ExtractionRecords from the input. Computes DependencyEntry for each. Writes DependencyEntries as JSON Lines to `output_path`.
- On ExtractionError records: skipped (no dependency entry for failed proofs).

> **Given** an extraction output with 100 ExtractionRecords and 5 ExtractionErrors
> **When** `extract_dependency_graph` is called
> **Then** the output contains 100 DependencyEntries (errors are skipped)

#### Inline mode

When the `--deps` flag is passed to the extraction CLI, the campaign orchestrator computes dependencies during extraction and writes a separate dependency graph file alongside the main output.

- ENSURES: The dependency graph file contains one DependencyEntry per successfully extracted theorem.

#### Index import mode

```
import_dependencies(dependency_graph_path, db_path, source_format=None)
```

- REQUIRES: `dependency_graph_path` is a valid dependency graph file (JSON Lines or DOT format). `db_path` is a path to an existing index database.
- ENSURES: Parses the dependency graph, resolves names to declaration IDs in the index, and inserts `(src_id, dst_id, "uses")` edges into the `dependencies` table. Existing edges are skipped (idempotent via primary key). Unresolvable names are skipped silently. Returns the count of edges inserted.
- MAINTAINS: Existing index data (declarations, WL vectors, FTS, symbol frequencies) is not modified.

Accepts two source formats:
- **JSON Lines** (`source_format="jsonl"` or `.jsonl`/`.json` extension): DependencyEntry records from extraction campaigns
- **DOT** (`source_format="dot"` or `.dot` extension): coq-dpdgraph output with directed edges between fully qualified names

> **Given** a dependency graph file and an index database both containing `Nat.add_comm` and `Nat.add_0_r`
> **When** `import_dependencies` is called with a DependencyEntry linking them
> **Then** a `"uses"` edge is inserted into the `dependencies` table

> **Given** a DOT file from coq-dpdgraph containing `"Nat.add_comm" -> "Nat.add_0_r"` and an index containing both
> **When** `import_dependencies` is called with `source_format="dot"`
> **Then** a `"uses"` edge is inserted into the `dependencies` table

See [extraction.md §4.6](extraction.md) for the full behavioral specification.

## 5. Error Specification

| Condition | Behavior |
|-----------|----------|
| ExtractionRecord with no premise annotations | DependencyEntry has `depends_on = []` |
| ExtractionError record in input | Skipped; no DependencyEntry produced |
| Input file is not valid JSON Lines | Raises `ValueError` with line number |

## 6. Non-Functional Requirements

- Post-hoc dependency graph extraction shall process a 100K-record extraction output in < 5 minutes.
- Memory usage shall be bounded by the largest single ExtractionRecord, not by the total input size.

## 7. Examples

### DependencyEntry output

```
{"theorem_name":"Coq.Arith.PeanoNat.Nat.add_comm","source_file":"theories/Arith/PeanoNat.v","project_id":"coq-stdlib","depends_on":[{"name":"Coq.Arith.PeanoNat.Nat.add_0_r","kind":"lemma"},{"name":"Coq.Arith.PeanoNat.Nat.add_succ_r","kind":"lemma"},{"name":"Coq.Init.Datatypes.nat","kind":"inductive"},{"name":"Coq.Init.Datatypes.S","kind":"constructor"}]}
```

### Theorem with no external dependencies

```
{"theorem_name":"Coq.Init.Logic.eq_refl_proof","source_file":"theories/Init/Logic.v","project_id":"coq-stdlib","depends_on":[]}
```

## 8. Language-Specific Notes (Python)

- Use a `dict` as an ordered set for deduplication (insertion order preserved in Python 3.7+).
- Read the input file line by line to avoid loading the full dataset into memory.
- Package location: `src/poule/extraction/dependency_graph.py`.
