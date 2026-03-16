# Test Feedback: test_storage.py

## TestWriterCreate.test_foreign_keys_enabled (line 263)

**Issue**: The test opens a *separate* `sqlite3.connect()` to the same database file and checks `PRAGMA foreign_keys`. However, `PRAGMA foreign_keys` is a per-connection setting in SQLite -- it is never persisted to the database file. A newly opened connection will always return 0.

**Suggested fix**: Verify FK enforcement via the writer's own connection, e.g. by attempting an invalid FK insert and checking for an error.

**SQLite docs**: "Foreign key constraints are disabled by default (for backwards compatibility), so must be enabled separately for each database connection." -- https://www.sqlite.org/foreignkeys.html

## TestWriterCreate.test_write_pragmas_set (line 270)

**Issue**: Same root cause. The test opens a separate connection to check `PRAGMA synchronous` and `PRAGMA journal_mode`. Both are per-connection settings that do not persist to the database file. `synchronous` always defaults to 2 (FULL) and `journal_mode` defaults to "delete" on a new connection. `journal_mode=MEMORY` specifically does not persist (unlike `journal_mode=WAL` which does).

**Suggested fix**: Expose the writer's connection for testing, or verify pragmas through the writer object itself.
