"""Search functions for the query processing pipeline."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from Poule.channels.const_jaccard import jaccard_similarity
from Poule.channels.fts import fts_query, fts_search
from Poule.channels.mepo import extract_consts, mepo_select
from Poule.models.labels import LProd
from Poule.models.responses import SearchResult
from Poule.models.tree import ExprTree, recompute_depths, assign_node_ids
from Poule.models.tree import node_count as _node_count
from Poule.channels.ted import ted_similarity
from Poule.channels.wl_kernel import wl_histogram, wl_screen
from Poule.fusion.fusion import collapse_match, rrf_fuse, weighted_rrf_fuse
from Poule.normalization.constr_node import App, Const, Lambda, Prod, Rel, Sort
from Poule.normalization.cse import cse_normalize
from Poule.normalization.errors import NormalizationError as _InternalNormalizationError
from Poule.normalization.normalize import coq_normalize
from Poule.pipeline.parser import ParseError


class NormalizationError(Exception):
    """Error during query normalization."""
    pass

logger = logging.getLogger(__name__)

# ---- FTS tokenization helpers for type expressions ----

_IDENT_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_.]*')
_COQ_KEYWORDS = frozenset({
    "forall", "fun", "match", "let", "in", "if", "then",
    "else", "return", "as", "with", "end", "fix", "cofix",
})


def _clean_type_expr_for_fts(type_expr: str) -> str:
    """Extract identifier tokens from a type expression for FTS search.

    Splits qualified names on dots (``List.map`` → ``List``, ``map``),
    filters Coq keywords and single-character tokens, deduplicates
    preserving order.  The result contains no dots, so ``fts_query``
    applies Rule 3 (whitespace-split OR) instead of Rule 1 (dot-split AND).
    """
    raw_tokens = _IDENT_RE.findall(type_expr)
    flat: list[str] = []
    for t in raw_tokens:
        flat.extend(t.split("."))
    seen: set[str] = set()
    result: list[str] = []
    for t in flat:
        low = t.lower()
        if low in _COQ_KEYWORDS or len(t) <= 1:
            continue
        if t not in seen:
            seen.add(t)
            result.append(t)
    return " ".join(result) if result else type_expr


@dataclass
class _ScoredResult:
    """Lightweight result object with decl_id and score."""
    decl_id: int
    score: float


def search_by_name(ctx: Any, pattern: str, limit: int) -> list[Any]:
    """Search declarations by name pattern using FTS5.

    Returns up to *limit* SearchResult items ranked by BM25.
    """
    query = fts_query(pattern)
    if not query:
        return []
    results = fts_search(query, limit=limit, reader=ctx.reader)
    return results[:limit]


# Legacy prefix aliases: Rocq 9.x renamed Coq stdlib from Coq.* to Corelib.*.
# Bidirectional — users may query with either prefix.
_PREFIX_ALIASES: list[tuple[str, str]] = [
    ("Coq.", "Corelib."),
]


def alias_prefix(prefix: str) -> str | None:
    """Bidirectional prefix alias: Coq.* ↔ Corelib.*.

    Returns the aliased form, or ``None`` if no alias applies.
    """
    for a, b in _PREFIX_ALIASES:
        if prefix.startswith(a):
            return b + prefix[len(a):]
        if prefix.startswith(b):
            return a + prefix[len(b):]
    return None


def _alias_symbol(sym: str) -> str | None:
    """Rewrite a symbol using known legacy prefix aliases.

    Only maps old → new (Coq.* → Corelib.*) for symbol resolution.
    Returns the aliased form, or None if no alias applies.
    """
    for old, new in _PREFIX_ALIASES:
        if sym.startswith(old):
            return new + sym[len(old):]
    return None


def _resolve_one(sym: str, ctx: Any) -> set[str]:
    """Resolve a single symbol via exact match, suffix index, or prefix alias."""
    if sym in ctx.inverted_index:
        return {sym}
    if sym in ctx.suffix_index:
        return set(ctx.suffix_index[sym])
    aliased = _alias_symbol(sym)
    if aliased is not None:
        if aliased in ctx.inverted_index:
            return {aliased}
        if aliased in ctx.suffix_index:
            return set(ctx.suffix_index[aliased])
    return set()


def _expand_suffixes(sym: str, ctx: Any) -> set[str]:
    """Collect additional index keys that are suffixes of *sym*.

    When the index stores the same constant under both a short name
    (``Nat.add``) and a Corelib FQN (``Corelib.Init.Nat.add``), an exact
    match on the FQN misses the majority of declarations that use the short
    name.  This helper finds those short-form keys so MePo can see them all.
    """
    extra: set[str] = set()
    parts = sym.split(".")
    for k in range(1, len(parts)):
        suffix = ".".join(parts[k:])
        if suffix in ctx.inverted_index:
            extra.add(suffix)
        if suffix in ctx.suffix_index:
            extra.update(ctx.suffix_index[suffix])
    return extra


def resolve_query_symbols(ctx: Any, symbols: list[str]) -> set[str]:
    """Resolve symbol names to FQNs using the suffix index.

    Resolution per symbol:
    1. Exact match in inverted_index → use directly.
    2. Suffix match via suffix_index → expand to all matching FQNs.
    3. Prefix alias (Coq.* → Corelib.*) → retry steps 1–2 with aliased form.
    4. No match → include as-is (passthrough).

    After primary resolution, qualified symbols (containing dots) are also
    expanded via their own suffixes to catch short-form index keys that refer
    to the same constant (e.g. ``Nat.add`` alongside ``Corelib.Init.Nat.add``).
    """
    resolved: set[str] = set()
    for sym in symbols:
        primary = _resolve_one(sym, ctx)
        if primary:
            resolved.update(primary)
            if "." in sym:
                resolved.update(_expand_suffixes(sym, ctx))
        else:
            # Suffix expansion fallback for qualified names (spec §4.5.1
            # step 4): when primary resolution fails and the symbol has
            # dots, try shorter suffixes to find related index keys.
            # e.g. "List.map" → suffix "map" → Coq.Lists.ListDef.map
            if "." in sym:
                expanded = _expand_suffixes(sym, ctx)
                if expanded:
                    resolved.update(expanded)
                else:
                    resolved.add(sym)  # passthrough
            else:
                resolved.add(sym)  # passthrough
    return resolved


def search_by_symbols(ctx: Any, symbols: list[str], limit: int) -> list[Any]:
    """Search declarations by symbol names using MePo relevance.

    Resolves short/partial names to FQNs before matching.
    Returns up to *limit* SearchResult items ranked by MePo relevance.
    """
    resolved = resolve_query_symbols(ctx, symbols)
    results = mepo_select(
        resolved,
        ctx.inverted_index,
        ctx.symbol_frequencies,
        ctx.declaration_symbols,
        p=0.6,
        c=2.4,
        max_rounds=5,
    )
    results = sorted(results, key=lambda r: r.score if hasattr(r, 'score') else r[1], reverse=True)
    return results[:limit]


def _ensure_parser(ctx: Any) -> None:
    """Lazily initialize the Coq parser on first use."""
    if ctx.parser is not None:
        return
    from Poule.parsing.type_expr_parser import TypeExprParser
    ctx.parser = TypeExprParser()


_COQ_KEYWORDS = frozenset({
    "forall", "fun", "match", "let", "in", "if", "then", "else",
    "return", "as", "with", "end", "fix", "cofix",
    "Prop", "Set", "Type",
})


def _is_free_variable(name: str) -> bool:
    """Return True if *name* looks like a user-intended free variable.

    Free variables are simple lowercase identifiers: no dots, not numeric,
    not a Coq keyword, and starting with a lowercase letter or underscore.
    """
    if not name:
        return False
    if "." in name:
        return False
    if name in _COQ_KEYWORDS:
        return False
    # Must start with a lowercase letter or underscore
    if not (name[0].islower() or name[0] == "_"):
        return False
    return True


def _resolve_const_name(name: str, ctx: Any) -> str | None:
    """Try to resolve a constant name to a single FQN via the suffix index.

    Returns the resolved FQN, or None if the name is already an FQN,
    ambiguous, or unresolvable.
    """
    if name in ctx.inverted_index:
        return name  # already an FQN
    if name in ctx.suffix_index:
        fqns = ctx.suffix_index[name]
        if len(fqns) == 1:
            return fqns[0] if isinstance(fqns, list) else next(iter(fqns))
    # Try prefix aliasing
    aliased = _alias_symbol(name)
    if aliased is not None:
        if aliased in ctx.inverted_index:
            return aliased
        if aliased in ctx.suffix_index:
            fqns = ctx.suffix_index[aliased]
            if len(fqns) == 1:
                return fqns[0] if isinstance(fqns, list) else next(iter(fqns))
    return None


def _resolve_consts_in_tree(node: object, ctx: Any) -> object:
    """Walk a ConstrNode tree and resolve Const names to FQNs where possible."""
    if isinstance(node, Const):
        resolved = _resolve_const_name(node.fqn, ctx)
        if resolved is not None and resolved != node.fqn:
            return Const(resolved)
        return node

    if isinstance(node, Rel) or isinstance(node, Sort):
        return node

    if isinstance(node, Prod):
        return Prod(node.name, _resolve_consts_in_tree(node.type, ctx),
                     _resolve_consts_in_tree(node.body, ctx))

    if isinstance(node, Lambda):
        return Lambda(node.name, _resolve_consts_in_tree(node.type, ctx),
                       _resolve_consts_in_tree(node.body, ctx))

    if isinstance(node, App):
        return App(_resolve_consts_in_tree(node.func, ctx),
                   [_resolve_consts_in_tree(a, ctx) for a in node.args])

    # For other node types, return as-is (they don't contain Const children
    # in typical type expressions from the parser)
    return node


def _collect_free_vars(node: object) -> list[str]:
    """Collect free variable names in left-to-right, depth-first order.

    Returns a deduplicated list preserving first-occurrence order.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _walk(n: object) -> None:
        if isinstance(n, Const) and _is_free_variable(n.fqn):
            if n.fqn not in seen:
                seen.add(n.fqn)
                result.append(n.fqn)
        elif isinstance(n, Prod):
            _walk(n.type)
            _walk(n.body)
        elif isinstance(n, Lambda):
            _walk(n.type)
            _walk(n.body)
        elif isinstance(n, App):
            _walk(n.func)
            for a in n.args:
                _walk(a)

    _walk(node)
    return result


def _replace_free_vars(node: object, var_map: dict[str, int], depth: int) -> object:
    """Replace free variable Const nodes with Rel nodes.

    *var_map* maps variable name → binding depth (0-based, outermost = 0).
    *depth* is the current binder depth (incremented when entering Prod/Lambda).
    """
    if isinstance(node, Const):
        if node.fqn in var_map:
            binding_depth = var_map[node.fqn]
            # de Bruijn index = distance from current depth to binding depth + 1
            return Rel(depth - binding_depth)
        return node

    if isinstance(node, Rel) or isinstance(node, Sort):
        return node

    if isinstance(node, Prod):
        return Prod(
            node.name,
            _replace_free_vars(node.type, var_map, depth),
            _replace_free_vars(node.body, var_map, depth + 1),
        )

    if isinstance(node, Lambda):
        return Lambda(
            node.name,
            _replace_free_vars(node.type, var_map, depth),
            _replace_free_vars(node.body, var_map, depth + 1),
        )

    if isinstance(node, App):
        return App(
            _replace_free_vars(node.func, var_map, depth),
            [_replace_free_vars(a, var_map, depth) for a in node.args],
        )

    return node


def _peel_n_prods(tree: ExprTree, n: int) -> ExprTree:
    """Strip up to *n* leading ``LProd`` layers, returning the body subtree.

    Follows ``children[1]`` (body) at each ``LProd`` node.  Stops early if
    the current root is not ``LProd`` or has fewer than 2 children.
    Returns a new ``ExprTree`` with recomputed depths, IDs, and node count.
    """
    if n <= 0:
        return tree
    current = tree.root
    peeled = 0
    while peeled < n and isinstance(current.label, LProd) and len(current.children) == 2:
        current = current.children[1]
        peeled += 1
    if peeled == 0:
        return tree
    nc = _node_count(current)
    body_tree = ExprTree(root=current, node_count=nc)
    recompute_depths(body_tree)
    assign_node_ids(body_tree)
    return body_tree


def normalize_type_query(ctx: Any, constr_node: object) -> tuple[object, int]:
    """Normalize a parsed type query for search_by_type.

    1. Resolve constant names to FQNs via the suffix index.
    2. Detect free variables (unresolved simple lowercase identifiers).
    3. Wrap in forall binders, converting free variable Const nodes to Rel.

    Returns ``(transformed_constr_node, auto_binder_count)`` where
    *auto_binder_count* is the number of forall binders that were
    auto-generated (0 when no wrapping occurred).
    """
    # Step 1: Resolve constants to FQNs
    resolved = _resolve_consts_in_tree(constr_node, ctx)

    # Step 2: Detect free variables
    free_vars = _collect_free_vars(resolved)
    if not free_vars:
        return resolved, 0

    # Step 3: Skip wrapping if outermost node is already Prod (user wrote forall)
    if isinstance(resolved, Prod):
        return resolved, 0

    # Build var_map: maps each free var name to its binding depth (0-based)
    # Outermost binder is depth 0, next is depth 1, etc.
    var_map: dict[str, int] = {}
    for i, name in enumerate(free_vars):
        var_map[name] = i

    # Replace free var references with Rel nodes
    # The body starts at depth = len(free_vars) (after all the Prod binders)
    body = _replace_free_vars(resolved, var_map, len(free_vars))

    # Wrap in Prod binders: innermost last, so build from right to left
    result = body
    for name in reversed(free_vars):
        result = Prod(name, Sort("Type"), result)

    return result, len(free_vars)


def search_by_structure(ctx: Any, expression: str, limit: int) -> list[Any]:
    """Search declarations by structural similarity.

    Returns up to *limit* result items ranked by structural score.
    """
    # Step 1: Parse expression (ParseError propagates)
    _ensure_parser(ctx)
    constr_node = ctx.parser.parse(expression)

    # Steps 2-3: Normalize (NormalizationError -> empty results)
    try:
        normalized_tree = coq_normalize(constr_node)
        cse_tree = cse_normalize(normalized_tree)
    except (NormalizationError, _InternalNormalizationError) as exc:
        logger.warning(
            "Normalization failed for expression %r: %s", expression, exc
        )
        return []

    # If cse_normalize returns None (in-place mutation), use normalized_tree
    if cse_tree is None:
        cse_tree = normalized_tree

    # Step 4: WL histogram
    query_histogram = wl_histogram(cse_tree, h=3)

    # Step 5: WL screening
    candidates_with_wl = wl_screen(
        query_histogram,
        cse_tree.node_count,
        ctx.wl_histograms,
        ctx.declaration_node_counts,
        n=500,
    )

    # Step 6: Structural scoring
    scored = score_candidates(cse_tree, candidates_with_wl, ctx)

    # Step 7: Sort by score descending, take top limit
    scored.sort(key=lambda x: x[1], reverse=True)
    scored = scored[:limit]

    # Step 8: Construct result objects
    results = [_ScoredResult(decl_id=decl_id, score=score) for decl_id, score in scored]
    return results


def _resolve_fused_results(
    fused_pairs: list, reader: Any,
) -> list[SearchResult]:
    """Resolve RRF-fused (key, score) pairs into SearchResult objects.

    Keys may be integer decl_ids (from structural/MePo channels) or string
    names (from FTS channel).  Both are resolved via the reader.
    """
    if not fused_pairs or not isinstance(fused_pairs[0], tuple):
        return list(fused_pairs)

    int_ids = [k for k, _ in fused_pairs if isinstance(k, int)]
    str_names = [k for k, _ in fused_pairs if isinstance(k, str)]

    decl_map: dict = {}

    # Batch-lookup integer decl_ids
    if int_ids:
        try:
            rows = reader.get_declarations_by_ids(int_ids)
            if isinstance(rows, list):
                for d in rows:
                    if isinstance(d, dict) and "id" in d:
                        decl_map[d["id"]] = d
        except (TypeError, KeyError):
            pass

    # Lookup string names individually
    for name in str_names:
        try:
            d = reader.get_declaration(name)
            if isinstance(d, dict):
                decl_map[name] = d
        except (TypeError, KeyError):
            pass

    if not decl_map:
        return list(fused_pairs)

    results: list[SearchResult] = []
    for key, score in fused_pairs:
        decl = decl_map.get(key)
        if decl is None:
            continue
        results.append(SearchResult(
            name=decl.get("name", ""),
            statement=decl.get("statement", ""),
            type=decl.get("type_expr", ""),
            module=decl.get("module", ""),
            kind=decl.get("kind", ""),
            score=score,
        ))
    return results if results else list(fused_pairs)


def search_by_type(ctx: Any, type_expr: str, limit: int) -> list[Any]:
    """Search declarations by type expression using multi-channel fusion.

    Returns up to *limit* result items ranked by RRF-fused score.
    """
    # Step 1: Parse expression (ParseError propagates)
    _ensure_parser(ctx)
    constr_node = ctx.parser.parse(type_expr)

    # Step 2: Query-time type normalization (FQN resolution + free var wrapping)
    constr_node, auto_binder_count = normalize_type_query(ctx, constr_node)

    # Step 3: Normalize (NormalizationError -> empty results)
    try:
        normalized_tree = coq_normalize(constr_node)
        cse_tree = cse_normalize(normalized_tree)
    except (NormalizationError, _InternalNormalizationError) as exc:
        logger.warning(
            "Normalization failed for type expression %r: %s", type_expr, exc
        )
        return []

    # If cse_normalize returns None (in-place mutation), use normalized_tree
    if cse_tree is None:
        cse_tree = normalized_tree

    # WL histogram + screening with relaxed size ratio for type queries
    query_histogram = wl_histogram(cse_tree, h=3)
    candidates_with_wl = wl_screen(
        query_histogram,
        cse_tree.node_count,
        ctx.wl_histograms,
        ctx.declaration_node_counts,
        n=500,
        size_ratio=2.0,
    )
    structural_scored = score_candidates(
        cse_tree, candidates_with_wl, ctx,
        auto_binder_count=auto_binder_count,
    )

    # Step 3: Symbol channel via MePo — resolve extracted symbols to FQNs
    # before passing to MePo (spec §4.4 step 7). This handles qualified
    # names like "List.map" that extract_consts preserves literally but
    # that aren't keys in the inverted index.
    raw_query_symbols = extract_consts(cse_tree)
    query_symbols = resolve_query_symbols(ctx, list(raw_query_symbols))
    mepo_results = mepo_select(
        query_symbols,
        ctx.inverted_index,
        ctx.symbol_frequencies,
        ctx.declaration_symbols,
        p=0.6,
        c=2.4,
        max_rounds=5,
    )

    # Step 4: Lexical channel via FTS — extract identifier tokens from the
    # type expression and flatten dots so fts_query applies Rule 3 (OR join)
    # instead of Rule 1 (dot-split AND) which produces garbage for type
    # expressions containing qualified names like "List.map".
    fts_input = _clean_type_expr_for_fts(type_expr)
    query = fts_query(fts_input)
    fts_results = fts_search(query, limit=limit, reader=ctx.reader)
    # Convert SearchResult objects to (name, score) pairs for RRF
    fts_pairs = [(r.name, r.score) for r in fts_results]

    # Step 5: RRF fusion
    ranked_lists = [structural_scored, mepo_results, fts_pairs]
    if ctx.rrf_weights is not None:
        channel_names = ["structural", "mepo", "fts"]
        weights = [ctx.rrf_weights.get(name, 1.0) for name in channel_names]
        fused = weighted_rrf_fuse(ranked_lists, weights, k=ctx.rrf_k)
    else:
        fused = rrf_fuse(ranked_lists, k=ctx.rrf_k)

    # Step 6: Sort by RRF score descending, take top limit
    fused = sorted(
        fused,
        key=lambda r: r[1] if isinstance(r, tuple) else r.score,
        reverse=True,
    )
    top = fused[:limit]

    # Step 7: Resolve to SearchResult objects (spec §4.4 step 7)
    return _resolve_fused_results(top, ctx.reader)


def score_candidates(
    query_tree: Any,
    candidates_with_wl: list[tuple[int, float]],
    ctx: Any,
    *,
    auto_binder_count: int = 0,
) -> list[tuple[int, float]]:
    """Compute structural scores for candidates.

    When *auto_binder_count* > 0, peels that many leading ``LProd`` layers
    from both query and candidate trees before computing collapse_match and
    ted_similarity.  WL cosine and const_jaccard use the full (unpeeled) trees.

    Returns (decl_id, structural_score) pairs.
    """
    if not candidates_with_wl:
        return []

    # Extract query constants (uses full tree)
    query_consts = extract_consts(query_tree)

    # Peel query tree once (outside loop) if auto binders were generated
    if auto_binder_count > 0:
        peeled_query = _peel_n_prods(query_tree, auto_binder_count)
    else:
        peeled_query = query_tree

    # Fetch candidate trees in batch
    candidate_ids = [decl_id for decl_id, _ in candidates_with_wl]
    candidate_trees = ctx.reader.get_constr_trees(candidate_ids)

    results: list[tuple[int, float]] = []
    for decl_id, wl_cosine in candidates_with_wl:
        candidate_tree = candidate_trees.get(decl_id)
        if candidate_tree is None:
            continue

        # Compute const jaccard using pre-computed declaration symbols (full tree)
        candidate_consts = ctx.declaration_symbols.get(decl_id, set())
        cj = jaccard_similarity(query_consts, candidate_consts)

        # Peel candidate tree for structural comparison
        if auto_binder_count > 0:
            peeled_candidate = _peel_n_prods(candidate_tree, auto_binder_count)
        else:
            peeled_candidate = candidate_tree

        # Compute collapse match on peeled trees
        cm = collapse_match(peeled_query, peeled_candidate)

        # Determine if TED should be computed (size check on peeled trees)
        use_ted = (peeled_query.node_count <= 50 and peeled_candidate.node_count <= 50)

        if use_ted:
            ted_sim = ted_similarity(peeled_query, peeled_candidate)
            # Weights: 0.15 * wl + 0.40 * ted + 0.30 * collapse + 0.15 * jaccard
            structural = 0.15 * wl_cosine + 0.40 * ted_sim + 0.30 * cm + 0.15 * cj
        else:
            # Weights: 0.25 * wl + 0.50 * collapse + 0.25 * jaccard
            structural = 0.25 * wl_cosine + 0.50 * cm + 0.25 * cj

        results.append((decl_id, float(structural)))

    return results
