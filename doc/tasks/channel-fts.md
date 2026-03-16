# Task: FTS5 Full-Text Search Channel

Implements the FTS5 full-text search retrieval channel as specified in [specification/channel-fts.md](../../specification/channel-fts.md).

---

## 1. Overview

This task implements keyword-based retrieval over Coq declarations using SQLite FTS5. The channel serves two purposes:

1. **Primary channel** for `search_by_name` -- the only channel invoked for name-based queries.
2. **Lexical signal** for `search_by_type` -- contributes a ranked list to RRF fusion alongside WL and MePo channels.

The implementation covers three concerns: query preprocessing (converting user input into valid FTS5 MATCH expressions), query execution (running the MATCH query with BM25 column weights), and error handling (gracefully handling malformed queries and edge cases).

---

## 2. Dependencies

### Must Be Implemented First

| Dependency | Specification | Reason |
|-----------|---------------|--------|
| Storage schema | [specification/storage.md](../../specification/storage.md) | The `declarations` table and `declarations_fts` virtual table must exist before FTS queries can run |
| Data structures | [specification/data-structures.md](../../specification/data-structures.md) | `ScoredResult` dataclass is the output type |

### Must Be Implemented Concurrently or After

| Dependency | Specification | Reason |
|-----------|---------------|--------|
| Pipeline orchestration | [specification/pipeline.md](../../specification/pipeline.md) | Calls the FTS channel; defines how results flow to fusion or directly to the MCP server |
| Fusion | [specification/fusion.md](../../specification/fusion.md) | Consumes FTS ranked lists for `search_by_type` RRF fusion |
| MCP server | [specification/mcp-server.md](../../specification/mcp-server.md) | Validates input before dispatching to the pipeline |

### External Dependencies

| Dependency | Notes |
|-----------|-------|
| Python `sqlite3` (stdlib) | FTS5 support depends on the SQLite version bundled with the Python build. Python 3.9+ on most platforms ships SQLite >= 3.35 which includes FTS5. See Risks section. |

---

## 3. Module Structure

```
src/
  coq_search/
    channels/
      __init__.py
      fts.py              # FTS5 channel: preprocessing + query execution
    models.py             # ScoredResult and other shared types (from data-structures spec)
```

The FTS channel is a single module `coq_search.channels.fts` containing:

- `FtsChannel` class -- owns a database connection reference, executes FTS queries
- `preprocess_query(raw: str) -> str` -- converts user input to FTS5 MATCH expression
- Internal helpers for qualified name detection, token splitting, and escaping

---

## 4. Implementation Steps

### Step 1: FTS5 Availability Check

At module import or channel initialization, verify that the SQLite library linked into Python supports FTS5:

```python
def _check_fts5_available(conn: sqlite3.Connection) -> bool:
    """Return True if FTS5 is available in this SQLite build."""
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(x)")
        conn.execute("DROP TABLE _fts5_test")
        return True
    except sqlite3.OperationalError:
        return False
```

For the read-only production path (database already created), instead check by querying the existing `declarations_fts` table:

```python
try:
    conn.execute("SELECT * FROM declarations_fts LIMIT 0")
except sqlite3.OperationalError as e:
    # FTS5 not available or table missing
```

Log a clear error message if FTS5 is unavailable, since this is a hard requirement.

### Step 2: Query Preprocessing

The preprocessor transforms raw user input into a valid FTS5 MATCH expression. There are three distinct paths:

#### 2a: Empty Query Detection

If the input string is empty or contains only whitespace, return `None` (or a sentinel) to signal that no FTS query should be executed. The caller returns an empty result list.

```python
def preprocess_query(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None
    ...
```

#### 2b: Qualified Name Detection and Splitting

A query is classified as a qualified name if it contains a `.` (dot) character. This is the heuristic specified.

When a qualified name is detected:

1. Split on `.` to get segments: `"Nat.add_comm"` -> `["Nat", "add_comm"]`
2. Split each segment on `_` to get tokens: `["Nat", "add_comm"]` -> `["Nat", "add", "comm"]`
3. Filter out empty tokens (from leading/trailing/consecutive separators)
4. Check for trailing `*` wildcard: if the original input ends with `*`, the last token becomes a prefix token

Construct the FTS5 expression by AND-joining quoted tokens:

- Without wildcard: `"Nat" AND "add" AND "comm"`
- With wildcard (e.g., `List.rev_*`): `"List" AND "rev"*`  -- note the FTS5 prefix syntax is `"token"*`

Implementation:

```python
import re

_QUALIFIED_NAME_RE = re.compile(r'[A-Za-z0-9_]+(\.[A-Za-z0-9_*]+)+')

def _is_qualified_name(query: str) -> bool:
    """A query looks like a qualified name if it contains a dot."""
    return '.' in query

def _split_qualified_name(query: str) -> tuple[list[str], bool]:
    """Split a qualified name into tokens and detect trailing wildcard.

    Returns (tokens, has_wildcard).
    """
    has_wildcard = query.endswith('*')
    # Remove trailing wildcard before splitting
    clean = query.rstrip('*')
    # Split on dots and underscores
    tokens = re.split(r'[._]', clean)
    # Filter empty tokens
    tokens = [t for t in tokens if t]
    return tokens, has_wildcard
```

#### 2c: Natural Language Pass-Through

If the query does not look like a qualified name, it is treated as a natural language fragment. FTS5 handles implicit OR for space-separated terms.

Before passing through, escape FTS5 special characters that the user likely did not intend as query syntax. The special characters in FTS5 are: `"`, `*`, `(`, `)`, `NEAR`, `AND`, `OR`, `NOT` (as operators), and column filter syntax (`column:`).

Escaping strategy:
- Wrap individual tokens in double quotes to prevent FTS5 operator interpretation
- But do NOT wrap the entire string (that would make it a phrase query requiring adjacency)
- Strip any `*` characters that are not at the end of a token (mid-word wildcards are not supported by FTS5)

Simpler approach for natural language: tokenize on whitespace, quote each token, join with spaces (implicit OR in FTS5):

```python
def _escape_natural_language(query: str) -> str:
    """Escape a natural language query for safe FTS5 execution.

    Each token is quoted to prevent interpretation as FTS5 operators.
    Trailing * on a token is preserved as an FTS5 prefix query.
    """
    tokens = query.split()
    escaped = []
    for token in tokens:
        if token.endswith('*'):
            # Prefix query: quote the stem, append *
            stem = token.rstrip('*')
            if stem:
                escaped_stem = stem.replace('"', '""')
                escaped.append(f'"{escaped_stem}"*')
        else:
            escaped_token = token.replace('"', '""')
            escaped.append(f'"{escaped_token}"')
    return ' '.join(escaped)
```

#### 2d: Assembling the Preprocessor

```python
def preprocess_query(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None

    if _is_qualified_name(stripped):
        tokens, has_wildcard = _split_qualified_name(stripped)
        if not tokens:
            return None
        parts = [f'"{t}"' for t in tokens]
        if has_wildcard:
            # Last token gets prefix syntax
            last = parts[-1]  # e.g., '"rev"'
            parts[-1] = last + '*'  # e.g., '"rev"*'
        return ' AND '.join(parts)
    else:
        return _escape_natural_language(stripped)
```

### Step 3: FTS5 Query Execution

The channel class holds a reference to the database connection (opened read-only by the server at startup) and executes the BM25-weighted FTS5 query.

```python
_FTS_QUERY = """
SELECT d.id, d.name, d.statement, d.module, d.kind,
       bm25(declarations_fts, 10.0, 1.0, 5.0) AS score
FROM declarations_fts
JOIN declarations d ON d.id = declarations_fts.rowid
WHERE declarations_fts MATCH ?
ORDER BY score
LIMIT ?
"""

class FtsChannel:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def search(self, query: str, limit: int = 50) -> list[ScoredResult]:
        fts_query = preprocess_query(query)
        if fts_query is None:
            return []

        try:
            rows = self._conn.execute(_FTS_QUERY, (fts_query, limit)).fetchall()
        except sqlite3.OperationalError as e:
            error_msg = str(e)
            if 'fts5' in error_msg.lower() or 'syntax' in error_msg.lower():
                raise FtsParseError(f"FTS5 query syntax error: {error_msg}") from e
            raise  # Re-raise non-FTS errors (e.g., database locked)

        results = []
        for rank, row in enumerate(rows, start=1):
            results.append(ScoredResult(
                decl_id=row[0],
                channel='fts',
                rank=rank,
                raw_score=row[5],  # BM25 score (negative; lower = better)
            ))
        return results
```

**BM25 score note**: SQLite's `bm25()` returns negative values where more negative means more relevant. The `ORDER BY score` (ascending) puts the most relevant results first. The `raw_score` field stores this negative value; the pipeline/fusion layer should be aware of the sign convention. If normalization is needed for fusion, the pipeline can negate or re-rank.

### Step 4: Error Handling

Define a channel-specific exception:

```python
class FtsParseError(Exception):
    """Raised when an FTS5 MATCH query has invalid syntax after preprocessing."""
    pass
```

Error handling matrix (from spec section 6):

| Condition | Implementation |
|-----------|---------------|
| Empty query string | `preprocess_query` returns `None`; `search` returns `[]` |
| FTS5 MATCH syntax error | Catch `sqlite3.OperationalError`, raise `FtsParseError` |
| FTS5 table not populated | FTS5 returns 0 rows; `search` returns `[]`. Log warning at startup (see step 5) |
| Query contains only stop words | FTS5 returns 0 rows; `search` returns `[]` |
| Database locked | `sqlite3.OperationalError` without FTS5 keywords; re-raise for the pipeline to handle |

### Step 5: Startup Validation

When the FTS channel is initialized (during server startup), check that the FTS index is populated:

```python
def _warn_if_fts_empty(self) -> None:
    row = self._conn.execute(
        "SELECT COUNT(*) FROM declarations_fts"
    ).fetchone()
    if row and row[0] == 0:
        import logging
        logging.getLogger(__name__).warning(
            "declarations_fts is empty — FTS5 'rebuild' may not have been run"
        )
```

Call this from `__init__` or from a dedicated `validate()` method invoked during server startup.

### Step 6: Index Population Support (Write Path)

Although the FTS channel is primarily a read-path component, provide a utility function for the extraction pipeline to trigger the FTS rebuild after populating `declarations`:

```python
def rebuild_fts_index(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 index from the declarations table.

    Call this after all declarations have been inserted.
    """
    conn.execute(
        "INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')"
    )
    conn.commit()
```

This is a simple wrapper but centralizes the FTS rebuild logic in the FTS module.

---

## 5. Testing Plan

### Unit Tests: Query Preprocessing

Location: `test/channels/test_fts_preprocessing.py`

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| Empty string | `""` | `None` |
| Whitespace only | `"   "` | `None` |
| Simple qualified name | `"Nat.add_comm"` | `'"Nat" AND "add" AND "comm"'` |
| Qualified name with single segment after dot | `"Coq.Init"` | `'"Coq" AND "Init"'` |
| Deeply nested qualified name | `"Coq.Arith.PeanoNat.Nat.add_comm"` | `'"Coq" AND "Arith" AND "PeanoNat" AND "Nat" AND "add" AND "comm"'` |
| Wildcard qualified name | `"List.rev_*"` | `'"List" AND "rev"*'` |
| Natural language | `"commutativity of addition"` | `'"commutativity" "of" "addition"'` |
| Natural language with FTS operator words | `"NOT a theorem AND proof"` | Each token quoted to prevent operator interpretation |
| Token with embedded quotes | `'say "hello"'` | Quotes escaped with `""` inside FTS5 quoting |
| Single token, no dot | `"add_comm"` | Treated as natural language: `'"add_comm"'` (no dot, so not qualified) |

### Unit Tests: Qualified Name Detection

| Test Case | Input | Expected |
|-----------|-------|----------|
| Has dot | `"Nat.add"` | `True` |
| No dot, has underscore | `"add_comm"` | `False` |
| No dot, no underscore | `"commutativity"` | `False` |
| Leading dot | `".add"` | `True` |
| Trailing dot | `"Nat."` | `True` |

### Integration Tests: FTS5 Query Execution

Location: `test/channels/test_fts_integration.py`

These tests require an in-memory SQLite database with the `declarations` table and `declarations_fts` virtual table populated with test data.

**Test fixture**: Create an in-memory database with sample declarations:

```python
SAMPLE_DECLARATIONS = [
    (1, "Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat", "Lemma",
     "forall n m : nat, n + m = m + n"),
    (2, "Coq.NArith.BinNat.N.add_comm", "Coq.NArith.BinNat", "Lemma",
     "forall n m : N, n + m = m + n"),
    (3, "Coq.Arith.PeanoNat.Nat.add_assoc", "Coq.Arith.PeanoNat", "Lemma",
     "forall n m p : nat, n + (m + p) = (n + m) + p"),
    (4, "Coq.Lists.List.rev_involutive", "Coq.Lists.List", "Lemma",
     "forall (A : Type) (l : list A), rev (rev l) = l"),
    (5, "Coq.Lists.List.rev_append", "Coq.Lists.List", "Lemma",
     "forall (A : Type) (l l' : list A), rev (l ++ l') = rev l' ++ rev l"),
]
```

| Test Case | Query | Assertions |
|-----------|-------|------------|
| Qualified name: `Nat.add_comm` | `"Nat.add_comm"` | Results include decl_id 1 and 2; decl_id 1 ranks higher (exact name match with weight 10) |
| Natural language: `commutativity of addition` | `"commutativity of addition"` | Returns results (FTS5 stemming matches "commut" in statement text if present; at minimum does not error) |
| Wildcard: `List.rev_*` | `"List.rev_*"` | Results include decl_id 4 and 5 (both have "List" and "rev" prefix) |
| Empty query | `""` | Returns empty list, no exception |
| Syntax error resilience | (Construct a query that would be syntactically invalid for FTS5) | Raises `FtsParseError` with message |
| BM25 ordering | `"add"` | Results ordered by BM25 score (verify score values are negative and ascending) |
| Limit parameter | `"Nat"`, limit=2 | Returns at most 2 results |
| No results | `"xyznonexistent"` | Returns empty list |

### Integration Tests: FTS5 Availability

| Test Case | Scenario | Assertion |
|-----------|----------|-----------|
| FTS5 available | Normal Python build | Channel initializes without error |
| Empty FTS index | `declarations` populated but rebuild not run | Warning logged, queries return empty |

### Spec Example Verification Tests

These tests directly verify the three examples from the specification (section 7):

1. **Example 1 -- Qualified name query**: Input `"Nat.add_comm"` produces FTS5 query `"Nat" AND "add" AND "comm"`. BM25 results include `Coq.Arith.PeanoNat.Nat.add_comm` ranked highest.

2. **Example 2 -- Natural language query**: Input `"commutativity of addition"` is passed through (not rewritten as AND). FTS5 handles stemming.

3. **Example 3 -- Wildcard query**: Input `"List.rev_*"` produces FTS5 query `"List" AND "rev"*`.

---

## 6. Acceptance Criteria

- [ ] `preprocess_query` correctly classifies and transforms qualified names, natural language, and wildcard queries as specified in section 5 of the spec
- [ ] FTS5 MATCH query executes with BM25 weights `(10.0, 1.0, 5.0)` for `(name, statement, module)` columns
- [ ] Empty queries return an empty result list without sending a MATCH to FTS5
- [ ] FTS5 syntax errors are caught and raised as `FtsParseError` with the original error message
- [ ] Database locked errors propagate as-is (not swallowed or misclassified)
- [ ] Results are returned as `ScoredResult` instances with channel set to `"fts"`, ranks assigned 1-based, and raw_score set to the BM25 value
- [ ] All three spec examples (qualified name, natural language, wildcard) produce the specified FTS5 query strings
- [ ] Startup validation warns when the FTS index is empty
- [ ] All unit and integration tests pass
- [ ] The module has no dependencies beyond Python stdlib (`sqlite3`, `re`, `logging`, `dataclasses`)

---

## 7. Risks and Mitigations

### Risk 1: FTS5 Not Available in Python's sqlite3

**Likelihood**: Low on modern platforms, moderate on minimal Docker images or older Linux distributions.

**Impact**: The FTS channel is completely non-functional. `search_by_name` returns errors; `search_by_type` loses its lexical signal.

**Detection**: The startup validation in Step 5 will catch this immediately.

**Mitigation**:
- Document the minimum SQLite version requirement (3.9.0 for FTS5, but practically 3.35+ for all features used).
- Check FTS5 availability at startup and emit a clear, actionable error: "FTS5 is not available in this Python build. Rebuild Python with a newer SQLite or install the `pysqlite3` package."
- As a fallback, the `pysqlite3-binary` PyPI package provides a statically-linked recent SQLite with FTS5 guaranteed. This can be used as a drop-in replacement: `import pysqlite3 as sqlite3`.

### Risk 2: FTS5 Query Syntax Errors from Preprocessing

**Likelihood**: Medium. Edge cases in user input (unbalanced quotes, stray parentheses, Unicode edge cases) could produce invalid FTS5 MATCH expressions even after preprocessing.

**Impact**: Individual queries fail with `FtsParseError`. No data corruption.

**Mitigation**:
- The escaping strategy (quoting individual tokens) neutralizes most FTS5 special characters.
- Catch all `sqlite3.OperationalError` from FTS5 execution and classify appropriately.
- Consider a two-pass strategy: if the preprocessed query fails, retry with a more aggressively escaped version (quote the entire input as a phrase query). This trades precision for robustness.

### Risk 3: Porter Stemming Causes Unexpected Matches or Misses

**Likelihood**: Medium. Coq identifiers like `Nat`, `Bool`, `Prop` are not English words and may stem unexpectedly.

**Impact**: Retrieval quality degradation, not functional failure.

**Mitigation**:
- The BM25 weight of 10.0 on the `name` column means exact name token matches dominate.
- Qualified name queries use exact quoted tokens (`"Nat"`) which match the stemmed form.
- Monitor retrieval quality during development and consider switching to `unicode61` without Porter stemming if Coq identifiers are systematically mis-stemmed.

### Risk 4: BM25 Score Sign Convention Causes Ranking Bugs

**Likelihood**: Medium. SQLite's `bm25()` returns negative values (lower = more relevant), which is counterintuitive.

**Impact**: Results sorted in wrong order if the sign convention is misunderstood by the fusion layer.

**Mitigation**:
- Document the sign convention clearly in the channel's docstrings and in `ScoredResult.raw_score`.
- The SQL query uses `ORDER BY score` (ascending), which correctly puts the most relevant results first.
- The fusion layer (RRF) uses rank position, not raw scores, so the sign convention does not affect RRF. Only the ordering matters.

### Risk 5: Content-Synced Virtual Table Becomes Stale

**Likelihood**: Low in production (database is read-only during serving). Could occur during development if declarations are modified without rebuilding FTS.

**Impact**: FTS returns stale or missing results.

**Mitigation**:
- The spec mandates a full `rebuild` after all declarations are inserted. The write path (Step 6) enforces this.
- The storage spec (section 5.1) defines the write procedure as: insert all declarations, then rebuild FTS.
- The content-sync mechanism (`content=declarations`) means FTS reads from the declarations table at query time for content retrieval. Stale FTS metadata would cause incorrect ranking but not missing content.

### Risk 6: Ambiguity in Spec for `add_comm` Without Dot

**Likelihood**: Certain. The spec examples show `"Nat.add_comm"` as a qualified name, but a user might type just `"add_comm"` (no dot).

**Impact**: `"add_comm"` would be treated as natural language (no dot detected), producing `'"add_comm"'` as a single quoted token rather than splitting on underscore into `'"add" AND "comm"'`.

**Mitigation**: This is flagged as spec feedback. The current implementation follows the spec literally (dot required for qualified name detection). If underscore-only splitting is desired for non-dotted inputs, the detection heuristic should be updated. See [specification/feedback/channel-fts.md](../../specification/feedback/channel-fts.md).
