"""Two-pass extraction pipeline for Coq library indexing."""

from __future__ import annotations

import json
import logging
import pickle
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import ExtractionError
from .kind_mapping import map_kind

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# Result dataclass for processed declarations
# ---------------------------------------------------------------------------

@dataclass
class DeclarationResult:
    """Result of processing a single declaration."""

    name: str
    kind: str
    module: str
    statement: str
    type_expr: str | None
    tree: Any | None = None
    symbol_set: list[str] = field(default_factory=list)
    wl_vector: dict[str, int] = field(default_factory=dict)
    dependency_names: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PipelineWriter adapter
# ---------------------------------------------------------------------------

class PipelineWriter:
    """Adapter that wraps :class:`IndexWriter` with the API the pipeline expects."""

    def __init__(self, index_writer: Any) -> None:
        self._writer = index_writer

    def batch_insert(self, results: list[Any]) -> dict[str, int]:
        """Convert DeclarationResult objects to dicts and insert.

        Calls ``insert_declarations()`` and ``insert_wl_vectors()`` on the
        underlying IndexWriter.  Returns a name-to-id mapping.
        """
        decl_dicts: list[dict] = []
        for r in results:
            # Serialize tree with pickle protocol 5 for constr_tree blob
            constr_tree: bytes | None = None
            node_count = 1  # default if tree is None
            tree = getattr(r, "tree", None)
            if tree is not None:
                constr_tree = pickle.dumps(tree, protocol=5)
                # Compute node_count from tree if it has the attribute
                nc = getattr(tree, "node_count", None)
                if nc is not None:
                    node_count = nc
                else:
                    node_count = 1

            decl_dicts.append({
                "name": r.name,
                "module": r.module,
                "kind": r.kind,
                "statement": r.statement,
                "type_expr": getattr(r, "type_expr", None),
                "constr_tree": constr_tree,
                "node_count": node_count,
                "symbol_set": getattr(r, "symbol_set", []),
            })

        name_to_id = self._writer.insert_declarations(decl_dicts)

        # Insert WL vectors
        wl_rows: list[dict] = []
        for r in results:
            decl_id = name_to_id.get(r.name)
            if decl_id is None:
                continue
            wl_vector = getattr(r, "wl_vector", None)
            if wl_vector:
                wl_rows.append({
                    "decl_id": decl_id,
                    "h": 3,
                    "histogram": wl_vector,
                })

        if wl_rows:
            self._writer.insert_wl_vectors(wl_rows)

        return name_to_id

    def resolve_and_insert_dependencies(
        self,
        all_results: list[Any],
        name_to_id: dict[str, int],
    ) -> int:
        """Resolve dependency names to IDs and insert edges.

        Skips unresolved targets and self-references.
        """
        edges: list[dict] = []
        for r in all_results:
            src_id = name_to_id.get(r.name)
            if src_id is None:
                continue
            dep_names = getattr(r, "dependency_names", [])
            for target_name, relation in dep_names:
                dst_id = name_to_id.get(target_name)
                if dst_id is None:
                    continue
                if src_id == dst_id:
                    continue
                edges.append({
                    "src": src_id,
                    "dst": dst_id,
                    "relation": relation,
                })

        if edges:
            self._writer.insert_dependencies(edges)

        return len(edges)

    def insert_symbol_freq(self, entries: dict[str, int]) -> None:
        """Delegate to IndexWriter.insert_symbol_freq()."""
        self._writer.insert_symbol_freq(entries)

    def write_metadata(self, **kwargs: Any) -> None:
        """Write each metadata key-value pair via IndexWriter.write_meta()."""
        for key, value in kwargs.items():
            if value is not None:
                self._writer.write_meta(key, str(value))

    def finalize(self) -> None:
        """Delegate to IndexWriter.finalize()."""
        self._writer.finalize()


# ---------------------------------------------------------------------------
# Stubs / factory functions (patched in tests)
# ---------------------------------------------------------------------------

def create_backend() -> Any:
    """Create and return a Backend instance (coq-lsp or SerAPI)."""
    from .backend_factory import create_coq_backend
    return create_coq_backend()


def create_writer(db_path: Path) -> Any:
    """Create and return an IndexWriter for the given database path."""
    from wily_rooster.storage.writer import IndexWriter
    index_writer = IndexWriter.create(db_path)
    return PipelineWriter(index_writer)


def process_declaration(
    name: str,
    kind: str,
    constr_t: Any,
    backend: Any,
    module_path: str,
    *,
    statement: str | None = None,
    dependency_names: list[tuple[str, str]] | None = None,
) -> DeclarationResult | None:
    """Process a single declaration through the normalization pipeline.

    Returns a :class:`DeclarationResult` on success (possibly with partial
    normalization data), or ``None`` if the declaration kind is excluded.

    Parameters
    ----------
    statement:
        Pre-fetched statement from batched queries.  Falls back to
        ``backend.pretty_print(name)`` if ``None``.
    dependency_names:
        Pre-fetched dependency pairs from batched queries.  Falls back to
        ``backend.get_dependencies(name)`` if ``None``.
    """
    from wily_rooster.channels.const_jaccard import extract_consts
    from wily_rooster.channels.wl_kernel import wl_histogram
    from wily_rooster.normalization.cse import cse_normalize
    from wily_rooster.normalization.normalize import coq_normalize

    storage_kind = map_kind(kind)
    if storage_kind is None:
        return None

    # Normalization pipeline — failures produce partial results
    tree = None
    symbol_set: list[str] = []
    wl_vector: dict[str, int] = {}

    try:
        tree = coq_normalize(constr_t)
        cse_normalize(tree)
        symbol_set = list(extract_consts(tree))
        wl_vector = wl_histogram(tree, h=3)
    except Exception:
        logger.warning(
            "Normalization failed for %s, storing partial result", name,
            exc_info=True,
        )

    # Type expression: prefer constr_t["type_signature"] from Search output
    type_expr = None
    if isinstance(constr_t, dict):
        type_expr = constr_t.get("type_signature")

    # Display data: use pre-fetched or fall back to per-declaration queries
    if statement is None:
        statement = backend.pretty_print(name)
    if dependency_names is None:
        dependency_names = backend.get_dependencies(name)

    return DeclarationResult(
        name=name,
        kind=storage_kind,
        module=module_path,
        statement=statement,
        type_expr=type_expr,
        tree=tree,
        symbol_set=symbol_set,
        wl_vector=wl_vector,
        dependency_names=dependency_names,
    )


# ---------------------------------------------------------------------------
# Library discovery
# ---------------------------------------------------------------------------

def discover_libraries(target: str) -> list[Path]:
    """Find ``.vo`` files for the requested target libraries.

    Parameters
    ----------
    target:
        One of ``"stdlib"``, ``"mathcomp"``, or a filesystem path to a
        user project.

    Returns
    -------
    list[Path]
        Paths to all discovered ``.vo`` files.

    Raises
    ------
    ExtractionError
        If the Coq toolchain is not installed or no ``.vo`` files are
        found for the target.
    """
    try:
        result = subprocess.run(
            ["coqc", "-where"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ExtractionError(
            f"Coq toolchain not found: {exc}"
        ) from exc

    base_dir = Path(result.stdout.strip())

    if target == "stdlib":
        # Rocq 9.x moved the stdlib from theories/ to user-contrib/Stdlib/.
        # Search both locations and use whichever yields more .vo files,
        # since the legacy theories/ may contain only a small subset.
        theories_dir = base_dir / "theories"
        user_contrib_dir = base_dir / "user-contrib" / "Stdlib"
        theories_vos = sorted(theories_dir.rglob("*.vo")) if theories_dir.is_dir() else []
        contrib_vos = sorted(user_contrib_dir.rglob("*.vo")) if user_contrib_dir.is_dir() else []
        vo_files = contrib_vos if len(contrib_vos) > len(theories_vos) else theories_vos
    elif target == "mathcomp":
        search_dir = base_dir / "user-contrib" / "mathcomp"
        vo_files = sorted(search_dir.rglob("*.vo"))
    else:
        search_dir = Path(target)
        vo_files = sorted(search_dir.rglob("*.vo"))

    if not vo_files:
        raise ExtractionError(
            f"No .vo files found for target '{target}' in {base_dir}"
        )

    return vo_files


# ---------------------------------------------------------------------------
# Main extraction pipeline
# ---------------------------------------------------------------------------

def run_extraction(
    *,
    targets: list[str],
    db_path: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the two-pass extraction pipeline.

    Parameters
    ----------
    targets:
        Library targets to index (e.g. ``["stdlib"]``).
    db_path:
        Path where the SQLite index database will be created.
    progress_callback:
        Optional callable invoked with progress messages.

    Returns
    -------
    dict
        A summary report of the extraction run.

    Raises
    ------
    ExtractionError
        On fatal errors (backend crash, missing backend, etc.).
        Partial database files are deleted on fatal errors.
    """
    # Discover libraries
    all_vo_files: list[Path] = []
    for t in targets:
        all_vo_files.extend(discover_libraries(t))

    # Delete existing database file if present (idempotent re-indexing)
    if db_path.exists():
        db_path.unlink()

    # Create backend and writer
    backend = create_backend()
    writer = create_writer(db_path)

    # Start the backend subprocess (e.g. coqtop)
    if hasattr(backend, "start"):
        backend.start()

    try:
        coq_version = backend.detect_version()

        # Collect all declarations across all .vo files
        all_declarations: list[tuple[str, str, Any, Path]] = []
        try:
            for vo_path in all_vo_files:
                raw_decls = backend.list_declarations(vo_path)
                for name, kind, constr_t in raw_decls:
                    all_declarations.append((name, kind, constr_t, vo_path))
        except ExtractionError:
            # Backend crash — clean up and re-raise
            _cleanup_db(db_path)
            raise

        total_decls = len(all_declarations)

        # ------------------------------------------------------------------
        # Batch Print + Print Assumptions queries
        # ------------------------------------------------------------------
        decl_data: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        _query_fn = getattr(backend, "query_declaration_data", None)
        if _query_fn is not None:
            decl_names = [name for name, _kind, _constr_t, _vo in all_declarations]
            try:
                batch_result = _query_fn(decl_names)
                # Validate result is a real dict (not a Mock artifact)
                if isinstance(batch_result, dict):
                    decl_data = batch_result
            except ExtractionError:
                _cleanup_db(db_path)
                raise
            except Exception:
                logger.debug("query_declaration_data not available, using per-declaration queries")

        # ------------------------------------------------------------------
        # Pass 1: Per-declaration processing with batching
        # ------------------------------------------------------------------
        name_to_id: dict[str, int] = {}
        all_results: list[Any] = []
        batch: list[Any] = []

        for idx, (name, kind, constr_t, vo_path) in enumerate(all_declarations, 1):
            if progress_callback is not None:
                progress_callback(
                    f"Extracting declarations [{idx}/{total_decls}]"
                )

            module_path = str(vo_path)

            # Use pre-fetched data if available
            prefetched = decl_data.get(name)
            stmt = prefetched[0] if prefetched else None
            deps = prefetched[1] if prefetched else None

            try:
                result = process_declaration(
                    name, kind, constr_t, backend, module_path,
                    statement=stmt, dependency_names=deps,
                )
            except Exception:
                logger.warning("Failed to process declaration %s", name, exc_info=True)
                result = None

            if result is None:
                continue

            batch.append(result)
            all_results.append(result)

            if len(batch) >= BATCH_SIZE:
                ids = writer.batch_insert(batch)
                if ids:
                    name_to_id.update(ids)
                batch = []

        # Flush remaining batch
        if batch:
            ids = writer.batch_insert(batch)
            if ids:
                name_to_id.update(ids)

        # ------------------------------------------------------------------
        # Pass 2: Dependency resolution
        # ------------------------------------------------------------------
        for idx, result in enumerate(all_results, 1):
            if progress_callback is not None:
                progress_callback(
                    f"Resolving dependencies [{idx}/{len(all_results)}]"
                )

        writer.resolve_and_insert_dependencies(all_results, name_to_id)

        # ------------------------------------------------------------------
        # Post-processing
        # ------------------------------------------------------------------
        # Compute symbol frequencies
        symbol_counts: Counter[str] = Counter()
        for result in all_results:
            symbols = getattr(result, "symbol_set", None)
            if isinstance(symbols, (list, set, frozenset, tuple)):
                for sym in symbols:
                    symbol_counts[sym] += 1

        writer.insert_symbol_freq(dict(symbol_counts))

        # Write metadata
        writer.write_metadata(
            schema_version="1",
            coq_version=coq_version,
            mathcomp_version=None,
            created_at=None,
        )

        # Finalize
        writer.finalize()

        return {
            "declarations_indexed": len(all_results),
            "coq_version": coq_version,
        }
    finally:
        if hasattr(backend, "stop"):
            backend.stop()


def _cleanup_db(db_path: Path) -> None:
    """Delete a partial database file if it exists."""
    try:
        if db_path.exists():
            db_path.unlink()
    except OSError:
        logger.warning("Failed to clean up partial database at %s", db_path)
