"""Two-pass extraction pipeline for Coq library indexing."""

from __future__ import annotations

import json
import logging
import os
import pickle
import random
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .backends.coqlsp_backend import CoqLspBackend
from .errors import ExtractionError
from .kind_mapping import map_kind
from .version_detection import detect_library_version, detect_mathcomp_version

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

# Maximum RSS (bytes) before restarting coq-lsp to reclaim memory.
# Modules that stay under this threshold skip the restart overhead.
# Override with POULE_LSP_RSS_LIMIT env var (in bytes).
_LSP_RSS_RESTART_THRESHOLD = int(
    os.environ.get("POULE_LSP_RSS_LIMIT", 5 * 1024 * 1024 * 1024)  # 5 GiB
)


# Module-level singleton for text-based type parsing
_type_parser_instance = None


def _get_type_parser():
    """Return a shared TypeExprParser instance (lazy singleton)."""
    global _type_parser_instance
    if _type_parser_instance is None:
        from Poule.parsing.type_expr_parser import TypeExprParser
        _type_parser_instance = TypeExprParser()
    return _type_parser_instance


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
    has_proof_body: int = 0


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
                "has_proof_body": getattr(r, "has_proof_body", 0),
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

        Name resolution strategy (for ``Print Assumptions`` output that
        may return short names instead of fully-qualified names):

        1. Exact match in *name_to_id*.
        2. Try prefixing with ``Coq.`` (e.g. ``Init.Nat.add`` →
           ``Coq.Init.Nat.add``).
        3. Suffix match — find any FQN in *name_to_id* that ends with
           ``.<short_name>``.

        Tree-based ``uses`` edges (from ``LConst`` nodes) are pre-merged
        into ``dependency_names`` by ``process_declaration`` during Pass 1.
        """
        # Build a reverse lookup: short suffix → FQN for efficient
        # suffix matching.  For each FQN like "Coq.Init.Nat.add", we
        # index all suffixes: "Init.Nat.add", "Nat.add", "add".
        # If a suffix maps to multiple FQNs we store None to signal
        # ambiguity (and skip it).
        suffix_to_fqn: dict[str, str | None] = {}
        for fqn in name_to_id:
            parts = fqn.split(".")
            for k in range(1, len(parts)):
                suffix = ".".join(parts[k:])
                if suffix in suffix_to_fqn:
                    # Mark ambiguous — don't use this suffix
                    if suffix_to_fqn[suffix] != fqn:
                        suffix_to_fqn[suffix] = None
                else:
                    suffix_to_fqn[suffix] = fqn

        def _resolve(target_name: str) -> int | None:
            """Try to resolve a dependency name to a declaration ID."""
            # 1. Exact match
            dst_id = name_to_id.get(target_name)
            if dst_id is not None:
                return dst_id
            # 2. Try Coq. prefix
            coq_name = "Coq." + target_name
            dst_id = name_to_id.get(coq_name)
            if dst_id is not None:
                return dst_id
            # 3. Suffix match via reverse lookup
            fqn = suffix_to_fqn.get(target_name)
            if fqn is not None:
                return name_to_id.get(fqn)
            return None

        edges: list[dict] = []
        seen_edges: set[tuple[int, int, str]] = set()

        for r in all_results:
            src_id = name_to_id.get(r.name)
            if src_id is None:
                continue

            # Collect dependency pairs (Print Assumptions + tree deps,
            # pre-merged by process_declaration).
            dep_names: list[tuple[str, str]] = getattr(r, "dependency_names", []) or []

            for target_name, relation in dep_names:
                dst_id = _resolve(target_name)
                if dst_id is None:
                    continue
                if src_id == dst_id:
                    continue
                edge_key = (src_id, dst_id, relation)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({
                    "src": src_id,
                    "dst": dst_id,
                    "relation": relation,
                })

        # Symbol-set cross-referencing (spec §4.5): generate "uses" edges
        # from symbol-set overlap.  For each symbol in a declaration's
        # symbol_set, resolve it using the same multi-strategy resolution
        # (exact, Coq. prefix, suffix) used for dependency names.  This
        # captures theorem-to-theorem relationships that Print Assumptions
        # misses, because symbol sets reference the definitions and theorems
        # used in the type signature.
        for r in all_results:
            src_id = name_to_id.get(r.name)
            if src_id is None:
                continue
            symbol_set = getattr(r, "symbol_set", None)
            if not symbol_set:
                continue
            for sym in symbol_set:
                dst_id = _resolve(sym)
                if dst_id is None:
                    continue
                if src_id == dst_id:
                    continue
                edge_key = (src_id, dst_id, "uses")
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({
                    "src": src_id,
                    "dst": dst_id,
                    "relation": "uses",
                })

        if edges:
            self._writer.insert_dependencies(edges)

        return len(edges)

    def insert_symbol_freq(self, entries: dict[str, int]) -> None:
        """Delegate to IndexWriter.insert_symbol_freq()."""
        self._writer.insert_symbol_freq(entries)

    def insert_re_export_aliases(self, aliases: dict[str, str]) -> None:
        """Delegate to IndexWriter.insert_re_export_aliases()."""
        self._writer.insert_re_export_aliases(aliases)

    def write_metadata(self, **kwargs: Any) -> None:
        """Write each metadata key-value pair via IndexWriter.write_meta()."""
        for key, value in kwargs.items():
            if value is not None:
                self._writer.write_meta(key, str(value))

    def finalize(self) -> None:
        """Delegate to IndexWriter.finalize()."""
        self._writer.finalize()


# ---------------------------------------------------------------------------
# Symbol FQN resolution
# ---------------------------------------------------------------------------


def resolve_symbols(
    raw_symbols: set[str],
    backend: Any,
    cache: dict[str, str | list[str] | None] | None = None,
) -> set[str]:
    """Resolve short display names to FQNs via backend Locate queries.

    Parameters
    ----------
    raw_symbols:
        Set of short symbol names extracted from an expression tree.
    backend:
        The extraction backend (must have a ``locate`` method).
    cache:
        Optional shared cache ``short_name → result`` to avoid redundant
        queries across declarations within the same indexing run.

    Returns a set of fully qualified kernel names.  Unresolvable names
    are included as-is.
    """
    if not raw_symbols:
        return set()

    if cache is None:
        cache = {}

    resolved: set[str] = set()
    for sym in raw_symbols:
        if sym in cache:
            cached = cache[sym]
        else:
            cached = backend.locate(sym)
            cache[sym] = cached

        if cached is None:
            resolved.add(sym)
        elif isinstance(cached, list):
            resolved.update(cached)
        else:
            resolved.add(cached)

    return resolved


# ---------------------------------------------------------------------------
# Stubs / factory functions (patched in tests)
# ---------------------------------------------------------------------------

def create_backend() -> Any:
    """Create and return a Backend instance (coq-lsp or SerAPI)."""
    from .backend_factory import create_coq_backend
    return create_coq_backend()


def create_writer(db_path: Path) -> Any:
    """Create and return an IndexWriter for the given database path."""
    from Poule.storage.writer import IndexWriter
    index_writer = IndexWriter.create(db_path)
    return PipelineWriter(index_writer)


# Vernacular keywords that always enter proof mode — a declaration starting
# with one of these always has a tactic proof body.
_PROOF_REQUIRING_KEYWORDS = frozenset({
    "Lemma", "Theorem", "Proposition", "Corollary", "Fact", "Remark",
})

# Regex for Vernacular keyword at the start of a line (possibly indented).
_VERNAC_KEYWORD_RE = re.compile(
    r"^\s*(\w+)\b", re.MULTILINE
)

# Declaration keywords that are ambiguous — may use := or Proof mode.
_AMBIGUOUS_KEYWORDS = frozenset({
    "Definition", "Instance", "Fixpoint", "CoFixpoint", "Example", "Let",
})

# Declaration keywords (all) — used to bound forward scanning.
_ALL_DECL_KEYWORDS = _PROOF_REQUIRING_KEYWORDS | _AMBIGUOUS_KEYWORDS | frozenset({
    "Inductive", "Record", "Class", "Axiom", "Parameter", "Conjecture",
    "Module", "Section", "End",
})


# LRU cache for .v file text.  Declarations from the same .vo file
# reference the same .v source, and processing moves through .vo files
# sequentially, so a small cache captures nearly all hits.  The cache
# is cleared in the run_extraction() finally block via
# ``_get_v_text.cache_clear()``.
@lru_cache(maxsize=16)
def _get_v_text(v_path: Path) -> str | None:
    """Read a .v source file, with bounded LRU caching."""
    try:
        return v_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _resolve_v_path(
    declared_library: str | None,
    lib_root: Path | None,
) -> Path | None:
    """Resolve the .v source file path from the declared library name."""
    if not declared_library or not lib_root:
        return None
    # Convert "Stdlib.Arith.PeanoNat" → lib_root / "Stdlib/Arith/PeanoNat.v"
    rel = declared_library.replace(".", "/") + ".v"
    candidate = lib_root / rel
    if candidate.exists():
        return candidate
    # Also try without the first component (e.g., Corelib.Init.Nat → Init/Nat.v)
    parts = declared_library.split(".", 1)
    if len(parts) == 2:
        rel2 = parts[1].replace(".", "/") + ".v"
        candidate2 = lib_root / rel2
        if candidate2.exists():
            return candidate2
    return None


def _check_line_anchored(v_text: str, declared_line: int) -> bool:
    """Check if the declaration at *declared_line* has a proof body.

    1. If the line starts with a proof-requiring keyword (Lemma, Theorem, etc.),
       return True immediately — these always enter proof mode.
    2. If the line starts with an ambiguous keyword (Definition, Instance, etc.),
       scan forward for a ``Proof`` keyword before the next declaration.
    3. Otherwise return False.
    """
    lines = v_text.splitlines()
    if declared_line < 1 or declared_line > len(lines):
        return False
    line = lines[declared_line - 1]  # 1-based → 0-based

    m = _VERNAC_KEYWORD_RE.match(line)
    if m is None:
        return False
    keyword = m.group(1)

    if keyword in _PROOF_REQUIRING_KEYWORDS:
        return True

    if keyword not in _AMBIGUOUS_KEYWORDS:
        return False

    # Scan forward from declared_line for "Proof" before next declaration.
    for scan_line in lines[declared_line:]:  # lines after declared_line
        stripped = scan_line.strip()
        if not stripped:
            continue
        sm = _VERNAC_KEYWORD_RE.match(scan_line)
        if sm:
            scan_kw = sm.group(1)
            if scan_kw == "Proof":
                return True
            if scan_kw in _ALL_DECL_KEYWORDS:
                return False  # hit next declaration without finding Proof
    return False


def detect_proof_body(
    name: str,
    kind: str,
    *,
    opacity: str | None = None,
    declared_line: int | None = None,
    declared_library: str | None = None,
    lib_root: Path | None = None,
) -> int:
    """Return 1 if *name* has a tactic proof body, else 0.

    Uses three signals evaluated in order:

    1. **Opacity** (About metadata): ``"opaque"`` → 1.
    2. **Vernacular kind** (Coq ≤8.x): ``"lemma"``/``"theorem"`` → 1.
    3. **Line-anchored .v check**: read the source line at *declared_line*
       and check the Vernacular keyword.

    Only checks declarations with kind in {lemma, theorem, definition, instance}.
    """
    if kind not in ("lemma", "theorem", "definition", "instance"):
        return 0

    # Signal 1: opaque declarations always have tactic proof bodies.
    if opacity == "opaque":
        return 1

    # Signal 2: Coq ≤8.x preserves Vernacular kind; these always enter proof mode.
    if kind in ("lemma", "theorem"):
        return 1

    # Signal 3: line-anchored .v source check for transparent definitions/instances.
    if declared_line is not None:
        v_path = _resolve_v_path(declared_library, lib_root)
        if v_path is not None:
            v_text = _get_v_text(v_path)
            if v_text is not None:
                return 1 if _check_line_anchored(v_text, declared_line) else 0

    return 0


def process_declaration(
    name: str,
    kind: str,
    constr_t: Any,
    backend: Any,
    module_path: str,
    *,
    statement: str | None = None,
    dependency_names: list[tuple[str, str]] | None = None,
    resolve_cache: dict[str, str | list[str] | None] | None = None,
    vo_path: Path | None = None,
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
    resolve_cache:
        Shared cache for symbol FQN resolution across declarations.
    """
    from Poule.channels.const_jaccard import extract_consts
    from Poule.channels.wl_kernel import wl_histogram
    from Poule.normalization.cse import cse_normalize
    from Poule.normalization.normalize import coq_normalize

    storage_kind = map_kind(kind)
    if storage_kind is None:
        return None

    # Normalization pipeline — failures produce partial results.
    # When constr_t is a metadata dict (e.g., coq-lsp Search output),
    # skip normalization — there is no kernel term to normalize.
    tree = None
    symbol_set: list[str] = []
    wl_vector: dict[str, int] = {}

    if not isinstance(constr_t, dict):
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
    else:
        # Metadata-only: parse type_signature text → ConstrNode → normalize
        type_sig = constr_t.get("type_signature")
        if type_sig:
            try:
                constr_node = _get_type_parser().parse(type_sig)
                tree = coq_normalize(constr_node)
                cse_normalize(tree)
                symbol_set = list(extract_consts(tree))
                wl_vector = wl_histogram(tree, h=3)
            except Exception:
                logger.debug(
                    "Text-based normalization failed for %s, storing partial result",
                    name, exc_info=True,
                )

    # Resolve short display names to FQNs if backend supports locate()
    if symbol_set and hasattr(backend, "locate"):
        try:
            symbol_set = list(resolve_symbols(
                set(symbol_set), backend, cache=resolve_cache,
            ))
        except Exception:
            logger.debug(
                "Symbol FQN resolution failed for %s, keeping short names",
                name, exc_info=True,
            )

    # Type expression: prefer constr_t["type_signature"] from Search output,
    # fall back to pretty_print_type() per spec §4.4 step 8.
    type_expr = None
    if isinstance(constr_t, dict):
        type_expr = constr_t.get("type_signature")
    if type_expr is None:
        try:
            type_expr = backend.pretty_print_type(name)
        except Exception:
            logger.debug("pretty_print_type failed for %s", name, exc_info=True)

    # Display data: use pre-fetched or fall back to per-declaration queries
    if statement is None:
        statement = backend.pretty_print(name)
    if not statement:
        # Print returned empty — synthesize from Search type_signature
        type_sig = constr_t.get("type_signature") if isinstance(constr_t, dict) else None
        if type_sig:
            short_name = name.rsplit(".", 1)[-1]
            statement = f"{short_name} : {type_sig}"
        else:
            statement = name
    if dependency_names is None:
        dependency_names = backend.get_dependencies(name)

    # Pre-compute tree-based dependencies while the tree is still available.
    # extract_dependencies is a pure function of (tree, decl_name) — same
    # result regardless of when it runs.  Existing dedup in
    # resolve_and_insert_dependencies via seen_edges handles overlap with
    # Print Assumptions edges.
    if tree is not None:
        try:
            from .dependency_extraction import extract_dependencies
            tree_deps = extract_dependencies(tree, name)
            dependency_names = list(dependency_names or []) + tree_deps
        except Exception:
            logger.debug("Tree dep extraction failed for %s", name, exc_info=True)

    # Extract About metadata from constr_t if available (coq-lsp path).
    about_opacity = constr_t.get("opacity") if isinstance(constr_t, dict) else None
    about_declared_lib = constr_t.get("declared_library") if isinstance(constr_t, dict) else None
    about_declared_line = constr_t.get("declared_line") if isinstance(constr_t, dict) else None

    # Derive lib_root from vo_path for declared_library resolution.
    lib_root = None
    if vo_path is not None:
        # Walk up from .vo path to find the library root (parent of user-contrib/).
        for parent in vo_path.parents:
            if parent.name in ("user-contrib", "theories"):
                lib_root = parent
                break

    has_body = detect_proof_body(
        name, storage_kind,
        opacity=about_opacity,
        declared_line=about_declared_line,
        declared_library=about_declared_lib,
        lib_root=lib_root,
    )

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
        has_proof_body=has_body,
    )


# ---------------------------------------------------------------------------
# Library discovery
# ---------------------------------------------------------------------------

_KNOWN_TARGETS = {"stdlib", "mathcomp", "stdpp", "flocq", "coquelicot", "coqinterval"}

_LIBRARY_CONTRIB_DIRS = {
    "stdpp": "stdpp",
    "flocq": "Flocq",
    "coquelicot": "Coquelicot",
    "coqinterval": "Interval",
}


def discover_libraries(target: str) -> list[Path]:
    """Find ``.vo`` files for the requested target libraries.

    Parameters
    ----------
    target:
        One of ``"stdlib"``, ``"mathcomp"``, ``"stdpp"``, ``"flocq"``,
        ``"coquelicot"``, ``"coqinterval"``, or a filesystem path to a
        user project.

    Returns
    -------
    list[Path]
        Paths to all discovered ``.vo`` files.

    Raises
    ------
    ExtractionError
        If the Coq toolchain is not installed, no ``.vo`` files are
        found for the target, or the target is not a recognised library
        identifier and does not exist as a filesystem path.
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
    elif target in _LIBRARY_CONTRIB_DIRS:
        contrib_name = _LIBRARY_CONTRIB_DIRS[target]
        search_dir = base_dir / "user-contrib" / contrib_name
        vo_files = sorted(search_dir.rglob("*.vo"))
    else:
        # Treat as a filesystem path; reject if it doesn't exist.
        search_dir = Path(target)
        if not search_dir.is_dir():
            valid = ", ".join(sorted(_KNOWN_TARGETS))
            raise ExtractionError(
                f"Unknown target '{target}'. "
                f"Valid library identifiers: {valid}"
            )
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
    max_files: int | None = None,
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
    max_files:
        If set, randomly sample at most this many ``.vo`` files from the
        full discovery list.  Useful for fast smoke tests that need
        representative coverage across the whole library tree.

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
    if progress_callback is not None:
        progress_callback("Discovering libraries...")
    all_vo_files: list[Path] = []
    for t in targets:
        all_vo_files.extend(discover_libraries(t))
    if progress_callback is not None:
        progress_callback(f"Discovered {len(all_vo_files)} .vo files")

    # Randomly sample if --max-files is set and smaller than total
    if max_files is not None and max_files < len(all_vo_files):
        all_vo_files = sorted(random.sample(all_vo_files, max_files))
        if progress_callback is not None:
            progress_callback(f"Sampled {len(all_vo_files)} .vo files (--max-files {max_files})")

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

        # Collect all declarations across all .vo files.
        # Each Require Import permanently loads the module into the Coq
        # process.  Restart coq-lsp when RSS exceeds the threshold to
        # reclaim memory without restarting after every lightweight file.
        all_declarations: list[tuple[str, str, Any, Path]] = []
        try:
            for idx, vo_path in enumerate(all_vo_files, 1):
                if progress_callback is not None:
                    progress_callback(
                        f"Collecting declarations [{idx}/{len(all_vo_files)}]"
                    )
                raw_decls = backend.list_declarations(vo_path)
                for name, kind, constr_t in raw_decls:
                    all_declarations.append((name, kind, constr_t, vo_path))
                # Restart when RSS exceeds threshold to reclaim memory.
                rss = backend._get_child_rss_bytes()
                if rss > _LSP_RSS_RESTART_THRESHOLD:
                    logger.debug(
                        "Restarting coq-lsp after file %d/%d (RSS=%.0f MiB)",
                        idx, len(all_vo_files), rss / (1024 * 1024),
                    )
                    backend.stop()
                    backend.start()
        except ExtractionError:
            # Backend crash — clean up and re-raise
            _cleanup_db(db_path)
            raise

        # Deduplicate declarations by name (keep first occurrence).
        # The same name can appear in multiple .vo files via re-exports.
        # Capture re-export aliases: when a duplicate comes from a different
        # module, record the re-export module path + short name as an alias.
        seen_names: dict[str, Path] = {}  # name -> first .vo path
        unique_declarations: list[tuple[str, str, Any, Path]] = []
        re_export_aliases: dict[str, str] = {}
        for decl in all_declarations:
            name, _kind, _constr_t, vo_path = decl
            if name not in seen_names:
                seen_names[name] = vo_path
                unique_declarations.append(decl)
            else:
                # Duplicate — derive re-export alias if from a different module
                first_module = CoqLspBackend._vo_to_canonical_module(seen_names[name])
                dup_module = CoqLspBackend._vo_to_canonical_module(vo_path)
                if dup_module != first_module:
                    short_name = name.rsplit(".", 1)[-1]
                    alias_fqn = f"{dup_module}.{short_name}"
                    if alias_fqn != name:
                        re_export_aliases[alias_fqn] = name
        all_declarations = unique_declarations
        del seen_names  # free dedup lookup; no longer needed

        total_decls = len(all_declarations)

        # ------------------------------------------------------------------
        # Batch Print + Print Assumptions queries
        # ------------------------------------------------------------------
        # Group declarations by import path.  Each Require Import
        # permanently loads the module; restart coq-lsp only when RSS
        # exceeds the threshold to reclaim memory.
        decl_data: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        _query_fn = getattr(backend, "query_declaration_data", None)
        if _query_fn is not None:
            import_groups: dict[str, list[str]] = {}
            for name, _kind, _constr_t, vo in all_declarations:
                imp = CoqLspBackend._vo_to_logical_path(vo)
                import_groups.setdefault(imp, []).append(name)

            group_items = list(import_groups.items())
            num_groups = len(group_items)
            del import_groups  # free the dict; we iterate group_items

            # Flatten groups into batch-sized chunks so we can check RSS
            # between batches, not just between groups.  Each chunk is a
            # (import_path, chunk_names) pair that query_declaration_data
            # processes as an independent document.
            _QUERY_BATCH_SIZE = 50  # matches query_declaration_data internal batch
            all_chunks: list[tuple[str, list[str]]] = []
            for import_path, group_names in group_items:
                for i in range(0, len(group_names), _QUERY_BATCH_SIZE):
                    all_chunks.append(
                        (import_path, group_names[i : i + _QUERY_BATCH_SIZE])
                    )
            num_chunks = len(all_chunks)

            try:
                for chunk_idx, (import_path, chunk_names) in enumerate(all_chunks, 1):
                    if progress_callback is not None:
                        progress_callback(
                            f"Querying declaration data [{chunk_idx}/{num_chunks}]..."
                        )
                    name_to_import = {n: import_path for n in chunk_names}
                    batch_result = _query_fn(
                        chunk_names, name_to_import=name_to_import,
                    )
                    if isinstance(batch_result, dict):
                        decl_data.update(batch_result)

                    # Restart backend when RSS exceeds threshold.
                    if chunk_idx < num_chunks:
                        rss = backend._get_child_rss_bytes()
                        if rss > _LSP_RSS_RESTART_THRESHOLD:
                            logger.debug(
                                "Restarting coq-lsp after chunk %d/%d "
                                "(RSS=%.0f MiB)",
                                chunk_idx, num_chunks, rss / (1024 * 1024),
                            )
                            backend.stop()
                            backend.start()
            except ExtractionError:
                _cleanup_db(db_path)
                raise
            except Exception:
                logger.debug("query_declaration_data not available, using per-declaration queries")

            del group_items  # free group names list

        # ------------------------------------------------------------------
        # Pass 1: Per-declaration processing with batching
        # ------------------------------------------------------------------
        name_to_id: dict[str, int] = {}
        all_results: list[Any] = []
        batch: list[Any] = []
        # Shared cache for symbol FQN resolution (Locate queries) across
        # all declarations — avoids redundant backend round-trips.
        resolve_cache: dict[str, str | list[str] | None] = {}

        for idx, (name, kind, constr_t, vo_path) in enumerate(all_declarations, 1):
            if progress_callback is not None:
                progress_callback(
                    f"Extracting declarations [{idx}/{total_decls}]"
                )

            module_path = CoqLspBackend._vo_to_canonical_module(vo_path)

            # Use pre-fetched data if available
            prefetched = decl_data.get(name)
            stmt = prefetched[0] if prefetched else None
            deps = prefetched[1] if prefetched else None

            try:
                result = process_declaration(
                    name, kind, constr_t, backend, module_path,
                    statement=stmt, dependency_names=deps,
                    resolve_cache=resolve_cache,
                    vo_path=vo_path,
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
                for r in batch:
                    # Free fields already written to SQLite that are not
                    # needed in Phase 2 (dependency resolution only uses
                    # name, dependency_names, and symbol_set).
                    r.tree = None
                    r.kind = None
                    r.module = None
                    r.statement = None
                    r.type_expr = None
                    r.wl_vector = None
                    r.has_proof_body = None
                batch = []

            # Check RSS every 50 declarations, independent of batch flush.
            # process_declaration calls backend.locate() per uncached symbol,
            # so coq-lsp RSS can grow rapidly between batch boundaries.
            if idx % 50 == 0:
                rss = backend._get_child_rss_bytes()
                if rss > _LSP_RSS_RESTART_THRESHOLD:
                    logger.debug(
                        "Restarting coq-lsp during Pass 1 at decl %d/%d "
                        "(RSS=%.0f MiB)",
                        idx, total_decls, rss / (1024 * 1024),
                    )
                    backend.stop()
                    backend.start()

        # Flush remaining batch
        if batch:
            ids = writer.batch_insert(batch)
            if ids:
                name_to_id.update(ids)
            for r in batch:
                r.tree = None
                r.kind = None
                r.module = None
                r.statement = None
                r.type_expr = None
                r.wl_vector = None
                r.has_proof_body = None

        # Free Pass 1 intermediates no longer needed.
        del all_declarations
        decl_data.clear()
        resolve_cache.clear()

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
        if progress_callback is not None:
            progress_callback("Computing symbol frequencies...")
        # Compute symbol frequencies
        symbol_counts: Counter[str] = Counter()
        for result in all_results:
            symbols = getattr(result, "symbol_set", None)
            if isinstance(symbols, (list, set, frozenset, tuple)):
                for sym in symbols:
                    symbol_counts[sym] += 1

        writer.insert_symbol_freq(dict(symbol_counts))

        # Store re-export aliases captured during deduplication
        writer.insert_re_export_aliases(re_export_aliases)

        if progress_callback is not None:
            progress_callback("Finalizing index...")
        # Write metadata
        metadata: dict[str, Any] = {
            "schema_version": "1",
            "coq_version": coq_version,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "declarations": str(len(all_results)),
        }

        if len(targets) == 1 and targets[0] in _KNOWN_TARGETS:
            metadata["library"] = targets[0]
            metadata["library_version"] = detect_library_version(targets[0])
        else:
            # Multiple targets — write mathcomp_version for backward compat
            metadata["mathcomp_version"] = detect_mathcomp_version()

        writer.write_metadata(**metadata)

        # Finalize
        writer.finalize()

        return {
            "declarations_indexed": len(all_results),
            "coq_version": coq_version,
        }
    finally:
        if hasattr(backend, "stop"):
            backend.stop()
        _get_v_text.cache_clear()


def _cleanup_db(db_path: Path) -> None:
    """Delete a partial database file if it exists."""
    try:
        if db_path.exists():
            db_path.unlink()
    except OSError:
        logger.warning("Failed to clean up partial database at %s", db_path)
