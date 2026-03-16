"""Two-pass extraction pipeline for Coq library indexing."""

from __future__ import annotations

import logging
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
# Stubs / factory functions (patched in tests)
# ---------------------------------------------------------------------------

def create_backend() -> Any:
    """Create and return a Backend instance (coq-lsp or SerAPI)."""
    raise NotImplementedError("create_backend must be provided or patched")


def create_writer(db_path: Path) -> Any:
    """Create and return an IndexWriter for the given database path."""
    raise NotImplementedError("create_writer must be provided or patched")


def process_declaration(
    name: str,
    kind: str,
    constr_t: Any,
    backend: Any,
    module_path: str,
) -> DeclarationResult | None:
    """Process a single declaration through the normalization pipeline.

    Returns a :class:`DeclarationResult` on success (possibly with partial
    normalization data), or ``None`` if the declaration kind is excluded.
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

    # Backend queries for display data
    statement = backend.pretty_print(name)
    type_expr = backend.pretty_print_type(name)

    # Dependencies (for pass 2)
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
        search_dir = base_dir / "theories"
    elif target == "mathcomp":
        search_dir = base_dir / "user-contrib" / "mathcomp"
    else:
        search_dir = Path(target)

    vo_files = sorted(search_dir.rglob("*.vo"))

    if not vo_files:
        raise ExtractionError(
            f"No .vo files found for target '{target}' in {search_dir}"
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

    # Create backend and writer
    backend = create_backend()
    writer = create_writer(db_path)

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

        try:
            result = process_declaration(
                name, kind, constr_t, backend, module_path
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


def _cleanup_db(db_path: Path) -> None:
    """Delete a partial database file if it exists."""
    try:
        if db_path.exists():
            db_path.unlink()
    except OSError:
        logger.warning("Failed to clean up partial database at %s", db_path)
