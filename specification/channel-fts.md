# Channel 3: FTS5 Full-Text Search

Lexical search over declaration names, pretty-printed statements, and module paths using SQLite's built-in FTS5 engine with BM25 ranking.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Used by: [fusion.md](fusion.md)

---

## 1. Purpose

Provide keyword-based retrieval for queries expressed as names, natural language fragments, or module paths. This channel handles `search_by_name` directly and contributes a lexical signal to `search_by_type` via RRF fusion.

---

## 2. Scope

Covers FTS5 index construction, BM25 query execution, and query preprocessing. Does not cover the schema definition for `declarations_fts` (see [storage.md](storage.md)) or how FTS5 results are fused with other channels (see [fusion.md](fusion.md)).

---

## 3. Index Construction

The FTS5 virtual table is defined in the schema (see [storage.md](storage.md)):

```sql
CREATE VIRTUAL TABLE declarations_fts USING fts5(
  name,
  statement,
  module,
  content=declarations,
  content_rowid=id,
  tokenize='porter unicode61 remove_diacritics 2'
);
```

**Tokenizer configuration**: `porter unicode61` applies Porter stemming and Unicode-aware tokenization. `remove_diacritics 2` handles accented characters. This means searching for "commut" will match "commutativity", "commutative", "Nat.add_comm", etc.

**Population** (run after all declarations are inserted):

```sql
INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild');
```

---

## 4. Online Query

```sql
SELECT d.id, d.name, d.statement, d.module, d.kind,
       bm25(declarations_fts, 10.0, 1.0, 5.0) AS score
FROM declarations_fts
JOIN declarations d ON d.id = declarations_fts.rowid
WHERE declarations_fts MATCH ?
ORDER BY score
LIMIT ?;
```

The `bm25()` weights `(10.0, 1.0, 5.0)` bias toward name matches (weight 10) over statement matches (weight 1), with module matches in between (weight 5). Tune these based on retrieval quality experiments.

---

## 5. Query Preprocessing

Before passing to FTS5 MATCH:

1. If the input looks like a qualified name (`Nat.add_comm`, `List.rev_*`), convert to an FTS5 prefix query: `"Nat" AND "add" AND "comm"` or `"List" AND "rev" AND *`.
2. If the input is a natural-language fragment, pass it as-is (FTS5 handles implicit OR).
3. Escape FTS5 special characters (`*`, `"`, `(`, `)`) when they are not intentional wildcards.

---

## 6. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Empty query string | Input error | Return empty result list (do not send empty MATCH to FTS5) |
| FTS5 MATCH syntax error (malformed query after preprocessing) | Input error | Return `PARSE_ERROR` with the FTS5 error message |
| FTS5 table not populated (rebuild not run) | State error | FTS5 returns 0 results; no crash. Log warning at startup if FTS index appears empty |
| Query contains only stop words / stemmed to nothing | Edge case | FTS5 returns 0 results; return empty list |
| Database locked during FTS5 query | Dependency error | Propagate as dependency error to caller |

---

## 7. Examples

### Example: Qualified name query

**Given**: Query string `"Nat.add_comm"`.

**When**: Query preprocessing runs.

**Then**: Detected as a qualified name (contains `.`). Split on `.` and `_`: tokens `["Nat", "add", "comm"]`. FTS5 query: `"Nat" AND "add" AND "comm"`.

BM25 results include:
1. `Coq.Arith.PeanoNat.Nat.add_comm` (strong name match, weight 10)
2. `Coq.NArith.BinNat.N.add_comm` (name match on "add" and "comm")
3. `Coq.Arith.PeanoNat.Nat.add_assoc` (partial name match on "Nat" and "add")

### Example: Natural language query

**Given**: Query string `"commutativity of addition"`.

**When**: Query preprocessing runs.

**Then**: Not a qualified name (no `.`). Passed to FTS5 as-is. FTS5 stems "commutativity" → "commut", "addition" → "addit". Implicit OR: matches declarations containing either term.

Results include declarations whose statements or names contain "commut" or "addit" stems.

### Example: Wildcard query

**Given**: Query string `"List.rev_*"`.

**When**: Query preprocessing runs.

**Then**: Detected as qualified name with wildcard. FTS5 query: `"List" AND "rev" AND *`. The `*` is an FTS5 prefix token — matches any completion of "rev".
