# FTS5 Full-Text Search Channel

Lexical search over declaration names, statements, and modules using SQLite FTS5.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § FTS5 Full-Text Search, [storage.md](../doc/architecture/storage.md)

---

## 1. Purpose

Define the FTS5 channel that provides lexical search capabilities, including query preprocessing for qualified name patterns and BM25-based ranking.

## 2. Scope

**In scope**: Query classification, query preprocessing (`fts_query`), FTS5 search execution, BM25 ranking with column weights.

**Out of scope**: FTS5 table creation and maintenance (owned by storage), fusion with other channels (owned by fusion/pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| FTS5 query | A search expression compatible with SQLite FTS5 MATCH syntax |
| BM25 | Best Match 25 — a term-frequency ranking function provided by FTS5 |
| Qualified name | A dot-separated identifier like `Coq.Arith.PeanoNat.Nat.add` |

## 4. Behavioral Requirements

### 4.1 Query Classification

The system shall classify each query into one of three categories based on priority:

| Priority | Rule | Condition | Example |
|----------|------|-----------|---------|
| 1 | Qualified name | Query contains `.` | `Coq.Arith.PeanoNat` |
| 2 | Identifier | Query contains `_` and no spaces | `nat_add` |
| 3 | Fallback | Everything else | `addition of natural numbers` |

Rules are evaluated in priority order. The first matching rule determines the classification.

### 4.2 Query Preprocessing

#### fts_query(raw_query)

- REQUIRES: `raw_query` is a non-empty string.
- ENSURES: Returns an FTS5-compatible query string, preprocessed according to the query classification.

**Rule 1 (qualified name)**: Split on `.`, join with `AND`. Each segment is a search term.
- Example: `"Coq.Arith.PeanoNat"` → `"Coq AND Arith AND PeanoNat"`

**Rule 2 (identifier)**: Split on `_`, join with `AND`.
- Example: `"nat_add"` → `"nat AND add"`

**Rule 3 (fallback)**: Split on whitespace, join with `OR`.
- Example: `"addition of natural numbers"` → `"addition OR of OR natural OR numbers"`

**FTS5 special character escaping**: Before splitting, escape any FTS5 special characters (`*`, `"`, `(`, `)`, `+`, `-`, `:`, `^`, `{`, `}`) by wrapping each token in double quotes if it contains special characters.

**Token limit**: Apply a 20-token safety limit uniformly to all query types. Tokens beyond 20 are dropped. For AND queries, dropping tokens makes the query less restrictive. For OR queries, dropping tokens reduces recall.

### 4.3 FTS Search Execution

#### fts_search(query, limit, reader)

- REQUIRES: `query` is a preprocessed FTS5 query string. `limit` is a positive integer. `reader` is an open `IndexReader`.
- ENSURES: Returns up to `limit` results ranked by BM25 with column weights `name=10.0, statement=1.0, module=5.0`. Scores are normalized to [0.0, 1.0].

**BM25 score normalization**: FTS5 BM25 returns negative values (lower is better). The system shall negate and normalize scores to [0, 1] by dividing by the maximum absolute score in the result set. If all scores are equal, all results receive score 1.0.

### 4.4 Rebuild Idempotency

The FTS5 `rebuild` command reconstructs the index from scratch and is idempotent. No guards against double-rebuild are needed.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Empty query string | — | Return empty result list |
| FTS5 syntax error (malformed query after preprocessing) | `StorageError` | Propagated to caller; pipeline translates to `PARSE_ERROR` |

## 6. Non-Functional Requirements

- FTS5 queries: < 10ms typical.
- Unicode tokenizer with Porter stemming for language-appropriate matching.

## 7. Examples

### Qualified name query

Given: `raw_query = "Coq.Arith.PeanoNat.Nat.add"`

When: `fts_query(raw_query)` is called

Then: Returns `"Coq AND Arith AND PeanoNat AND Nat AND add"` (Rule 1: contains `.`)

### Identifier query

Given: `raw_query = "nat_add_comm"`

When: `fts_query(raw_query)` is called

Then: Returns `"nat AND add AND comm"` (Rule 2: contains `_`, no spaces)

### Fallback query

Given: `raw_query = "addition commutative"`

When: `fts_query(raw_query)` is called

Then: Returns `"addition OR commutative"` (Rule 3: fallback)

## 8. Language-Specific Notes (Python)

- FTS5 queries are passed to `IndexReader.search_fts()` which executes the SQLite MATCH.
- Package location: `src/wily_rooster/channels/`.
