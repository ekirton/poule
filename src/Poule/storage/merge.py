"""Index merging — combine per-library SQLite indexes into one."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .writer import _SCHEMA_SQL


def merge_indexes(sources: list[tuple[str, Path]], dest: Path) -> dict:
    """Merge per-library SQLite databases into a single index.db at *dest*.

    Parameters
    ----------
    sources : list of (library_name, path) tuples
        Each path points to a per-library SQLite index.
    dest : Path
        Output path for the merged database.

    Returns
    -------
    dict with keys: total_declarations, total_dependencies,
    dropped_dependencies, libraries.
    """
    # 1. Delete dest if it already exists.
    if dest.exists():
        os.remove(dest)

    # 2. Read and validate metadata across all sources.
    schema_version: str | None = None
    coq_version: str | None = None
    library_versions: dict[str, str] = {}

    for lib_name, src_path in sources:
        conn = sqlite3.connect(str(src_path))
        sv = _meta_value(conn, "schema_version")
        cv = _meta_value(conn, "coq_version")
        lv_json = _meta_value(conn, "library_versions")
        lv_single = _meta_value(conn, "library_version")
        conn.close()

        if schema_version is None:
            schema_version = sv
        elif sv != schema_version:
            raise Exception(
                f"Schema version mismatch: expected {schema_version!r}, "
                f"got {sv!r} in {src_path}"
            )

        if coq_version is None:
            coq_version = cv
        elif cv != coq_version:
            raise Exception(
                f"Coq version mismatch: expected {coq_version!r}, "
                f"got {cv!r} in {src_path}"
            )

        if lv_json:
            lv = json.loads(lv_json)
            library_versions.update(lv)
        if lib_name not in library_versions:
            if lv_single:
                library_versions[lib_name] = lv_single
            else:
                library_versions[lib_name] = "unknown"

    # 3. Create fresh dest DB with the canonical schema.
    dest_conn = sqlite3.connect(str(dest))
    dest_conn.execute("PRAGMA foreign_keys = OFF")
    dest_conn.execute("PRAGMA synchronous = OFF")
    dest_conn.execute("PRAGMA journal_mode = MEMORY")
    dest_conn.executescript(_SCHEMA_SQL)

    # 4-6. Copy data from each source, remapping IDs.
    # Global name → new_id mapping (for cross-library dep resolution).
    global_name_to_id: dict[str, int] = {}
    # Per-source old_id → new_id mapping.
    all_id_maps: list[dict[int, int]] = []
    library_names: list[str] = []
    total_declarations = 0

    for lib_name, src_path in sources:
        library_names.append(lib_name)
        src_conn = sqlite3.connect(str(src_path))
        old_to_new: dict[int, int] = {}

        # 4a. Copy declarations.
        rows = src_conn.execute(
            "SELECT id, name, module, kind, statement, type_expr, "
            "constr_tree, node_count, symbol_set FROM declarations"
        ).fetchall()

        for row in rows:
            old_id = row[0]
            name, module, kind, statement = row[1], row[2], row[3], row[4]
            type_expr, constr_tree, node_count, symbol_set = (
                row[5], row[6], row[7], row[8],
            )
            cursor = dest_conn.execute(
                "INSERT INTO declarations "
                "(name, module, kind, statement, type_expr, constr_tree, "
                "node_count, symbol_set) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, module, kind, statement, type_expr, constr_tree,
                 node_count, symbol_set),
            )
            new_id = cursor.lastrowid
            old_to_new[old_id] = new_id
            global_name_to_id[name] = new_id
            total_declarations += 1

        all_id_maps.append(old_to_new)
        src_conn.close()

    dest_conn.commit()

    # 5. Copy dependencies, remapping IDs.
    total_dependencies = 0
    dropped_dependencies = 0

    for (lib_name, src_path), old_to_new in zip(sources, all_id_maps):
        src_conn = sqlite3.connect(str(src_path))
        dep_rows = src_conn.execute(
            "SELECT src, dst, relation FROM dependencies"
        ).fetchall()
        src_conn.close()

        for old_src, old_dst, relation in dep_rows:
            new_src = old_to_new.get(old_src)
            new_dst = old_to_new.get(old_dst)
            if new_src is None or new_dst is None:
                dropped_dependencies += 1
                continue
            dest_conn.execute(
                "INSERT OR IGNORE INTO dependencies (src, dst, relation) "
                "VALUES (?, ?, ?)",
                (new_src, new_dst, relation),
            )
            total_dependencies += 1

    dest_conn.commit()

    # 5b. Resolve cross-library dependencies from symbol_set entries.
    # Build a suffix reverse-lookup table from all FQNs in the global map.
    suffix_to_fqn: dict[str, str | None] = {}
    for fqn in global_name_to_id:
        parts = fqn.split(".")
        for k in range(1, len(parts)):
            suffix = ".".join(parts[k:])
            if suffix in suffix_to_fqn:
                if suffix_to_fqn[suffix] != fqn:
                    suffix_to_fqn[suffix] = None  # ambiguous
            else:
                suffix_to_fqn[suffix] = fqn

    def _resolve(sym: str) -> int | None:
        """Multi-strategy name resolution: exact, Coq. prefix, suffix."""
        dst_id = global_name_to_id.get(sym)
        if dst_id is not None:
            return dst_id
        coq_name = "Coq." + sym
        dst_id = global_name_to_id.get(coq_name)
        if dst_id is not None:
            return dst_id
        resolved_fqn = suffix_to_fqn.get(sym)
        if resolved_fqn is not None:
            return global_name_to_id.get(resolved_fqn)
        return None

    # For each declaration, resolve symbol_set entries against the global map.
    sym_decl_rows = dest_conn.execute(
        "SELECT id, name, symbol_set FROM declarations"
    ).fetchall()
    for decl_id, decl_name, symbol_set_json in sym_decl_rows:
        symbols = json.loads(symbol_set_json)
        for sym in symbols:
            dst_id = _resolve(sym)
            if dst_id is None or dst_id == decl_id:
                continue
            try:
                dest_conn.execute(
                    "INSERT OR IGNORE INTO dependencies (src, dst, relation) "
                    "VALUES (?, ?, ?)",
                    (decl_id, dst_id, "uses"),
                )
                total_dependencies += 1
            except sqlite3.IntegrityError:
                pass  # duplicate — already counted

    dest_conn.commit()

    # 6. Copy WL vectors, remapping decl_id.
    for (lib_name, src_path), old_to_new in zip(sources, all_id_maps):
        src_conn = sqlite3.connect(str(src_path))
        wl_rows = src_conn.execute(
            "SELECT decl_id, h, histogram FROM wl_vectors"
        ).fetchall()
        src_conn.close()

        for old_decl_id, h, histogram in wl_rows:
            new_decl_id = old_to_new.get(old_decl_id)
            if new_decl_id is not None:
                dest_conn.execute(
                    "INSERT INTO wl_vectors (decl_id, h, histogram) "
                    "VALUES (?, ?, ?)",
                    (new_decl_id, h, histogram),
                )

    dest_conn.commit()

    # 6b. Copy embeddings, remapping decl_id.
    for (lib_name, src_path), old_to_new in zip(sources, all_id_maps):
        src_conn = sqlite3.connect(str(src_path))
        try:
            emb_rows = src_conn.execute(
                "SELECT decl_id, vector FROM embeddings"
            ).fetchall()
        except sqlite3.OperationalError:
            emb_rows = []  # No embeddings table in this source
        src_conn.close()

        for old_decl_id, vector in emb_rows:
            new_decl_id = old_to_new.get(old_decl_id)
            if new_decl_id is not None:
                dest_conn.execute(
                    "INSERT OR IGNORE INTO embeddings (decl_id, vector) "
                    "VALUES (?, ?)",
                    (new_decl_id, vector),
                )

    dest_conn.commit()

    # 6c. Copy neural_model_hash if all sources agree on it.
    model_hashes = set()
    for lib_name, src_path in sources:
        src_conn = sqlite3.connect(str(src_path))
        h = _meta_value(src_conn, "neural_model_hash")
        src_conn.close()
        if h is not None:
            model_hashes.add(h)
    if len(model_hashes) == 1:
        dest_conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("neural_model_hash", model_hashes.pop()),
        )
        dest_conn.commit()

    # 7. Rebuild FTS5 from all merged declarations.
    fts_rows = dest_conn.execute(
        "SELECT id, name, statement, module FROM declarations"
    ).fetchall()
    for row in fts_rows:
        dest_conn.execute(
            "INSERT INTO declarations_fts(rowid, name, statement, module) "
            "VALUES (?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3]),
        )
    dest_conn.commit()

    # 8. Recompute symbol frequencies.
    freq: dict[str, int] = {}
    sym_rows = dest_conn.execute(
        "SELECT symbol_set FROM declarations"
    ).fetchall()
    for (symbol_set_json,) in sym_rows:
        symbols = json.loads(symbol_set_json)
        for sym in symbols:
            freq[sym] = freq.get(sym, 0) + 1

    dest_conn.executemany(
        "INSERT INTO symbol_freq (symbol, freq) VALUES (?, ?)",
        list(freq.items()),
    )
    dest_conn.commit()

    # 9. Write index_meta.
    meta = {
        "schema_version": schema_version or "1",
        "coq_version": coq_version or "unknown",
        "libraries": json.dumps(library_names),
        "library_versions": json.dumps(library_versions),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for key, value in meta.items():
        dest_conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
    dest_conn.commit()
    dest_conn.close()

    # 10. Return summary.
    return {
        "total_declarations": total_declarations,
        "total_dependencies": total_dependencies,
        "dropped_dependencies": dropped_dependencies,
        "libraries": library_names,
    }


def _meta_value(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM index_meta WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None
