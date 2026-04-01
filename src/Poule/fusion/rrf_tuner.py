"""RRF k-parameter and per-channel weight optimization via Optuna.

Implements the optimization protocol from doc/reciprocal-rank-fusion.md §5.2:
pre-compute channel ranked lists once, then sweep k and weights by re-fusing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Poule.fusion.fusion import weighted_rrf_fuse

logger = logging.getLogger(__name__)


@dataclass
class PrecomputedQuery:
    """Cached channel results for a single evaluation query.

    Each channel field holds a ranked list of ``(name, score)`` pairs
    sorted by score descending.  All identifiers are resolved to names
    (not integer decl_ids) so they are directly comparable to
    ``ground_truth``.
    """

    structural: list[tuple[str, float]]
    mepo: list[tuple[str, float]]
    fts: list[tuple[str, float]]
    ground_truth: set[str]


@dataclass
class RRFTuningResult:
    """Result of an RRF k / weight optimization study."""

    best_k: int
    best_weights: dict[str, float]
    best_recall_32: float
    n_trials: int
    study_path: str
    all_trials: list[dict[str, Any]] = field(default_factory=list)


def extract_goal_type(proof_state_text: str) -> str:
    """Extract the focused goal's type from a serialized proof state.

    The format from ``serialize_goals`` is::

        hyp_name : hyp_type
        hyp_name : hyp_type
        goal_type

    Multiple goals are separated by a blank line.  Returns the type
    from the first goal (the last non-hypothesis line of the first
    block).
    """
    if not proof_state_text:
        return ""

    # Split into goal blocks (separated by blank lines)
    blocks = proof_state_text.split("\n\n")
    first_block = blocks[0]

    lines = first_block.split("\n")

    # Walk backwards to find the last line that is NOT a hypothesis.
    # Hypothesis lines match "name : type" where the first ' : ' separates
    # the identifier from the type.  The goal type is the last line that
    # does not follow this pattern — but since goal types can also contain
    # ' : ', we use a simpler heuristic: the last line of the block is the
    # goal type (matching serialize_goals which appends goal_type last).
    return lines[-1] if lines else ""


def evaluate_cached(
    cached: list[PrecomputedQuery],
    k: int,
    weights: dict[str, float],
    limit: int = 32,
) -> float:
    """Compute mean Recall@limit over pre-computed channel results.

    For each query, fuses channel ranked lists via weighted RRF with
    the given ``k`` and ``weights``, takes the top ``limit`` results,
    and checks whether any ground-truth premise appears.

    Returns the fraction of queries where at least one ground-truth
    premise is found in the top-``limit`` results.
    """
    if not cached:
        return 0.0

    hits = 0
    for pq in cached:
        # Assemble channels and weights in order
        channel_lists: list[list] = []
        channel_weights: list[float] = []

        channel_lists.append(pq.structural)
        channel_weights.append(weights.get("structural", 1.0))

        channel_lists.append(pq.mepo)
        channel_weights.append(weights.get("mepo", 1.0))

        channel_lists.append(pq.fts)
        channel_weights.append(weights.get("fts", 1.0))

        fused = weighted_rrf_fuse(channel_lists, channel_weights, k=k)
        top_names = {item[0] for item in fused[:limit]}

        if top_names & pq.ground_truth:
            hits += 1

    return hits / len(cached)


def precompute_channel_results(
    val_data: list[tuple[str, list[str]]],
    ctx: Any,
) -> list[PrecomputedQuery]:
    """Run all symbol channels on each val query and cache the results.

    For each ``(proof_state_text, ground_truth_names)`` pair:

    1. Extract goal type string.
    2. Try parse → normalize → WL screen → score_candidates → structural
       ranked list (empty on parse failure).
    3. Extract symbols → mepo_select → MePo ranked list.
    4. fts_query + fts_search → FTS ranked list.
    5. Resolve all decl_ids to names.

    Returns a list of ``PrecomputedQuery`` with name-based ranked lists.
    """
    from Poule.channels.fts import fts_query, fts_search
    from Poule.channels.mepo import extract_consts, mepo_select
    from Poule.channels.wl_kernel import wl_histogram, wl_screen
    from Poule.normalization.cse import cse_normalize
    from Poule.normalization.normalize import coq_normalize

    results: list[PrecomputedQuery] = []
    parse_failures = 0

    for proof_state, gt_names in val_data:
        goal_type = extract_goal_type(proof_state)
        ground_truth = set(gt_names)

        # --- Structural channel ---
        structural: list[tuple[str, float]] = []
        parsed_tree = None
        try:
            from Poule.pipeline.search import _ensure_parser
            _ensure_parser(ctx)
            constr_node = ctx.parser.parse(goal_type)
            normalized = coq_normalize(constr_node)
            cse_tree = cse_normalize(normalized)
            if cse_tree is None:
                cse_tree = normalized

            query_hist = wl_histogram(cse_tree, h=3)
            candidates = wl_screen(
                query_hist,
                cse_tree.node_count,
                ctx.wl_histograms,
                ctx.declaration_node_counts,
                n=500,
                size_ratio=2.0,
            )
            from Poule.pipeline.search import score_candidates
            scored = score_candidates(cse_tree, candidates, ctx)
            parsed_tree = cse_tree

            # Resolve decl_ids to names
            if scored:
                id_to_name = _resolve_ids(
                    [s[0] for s in scored], ctx.reader
                )
                structural = [
                    (id_to_name[s[0]], s[1])
                    for s in scored
                    if s[0] in id_to_name
                ]
        except Exception:
            parse_failures += 1

        # --- MePo channel ---
        mepo: list[tuple[str, float]] = []
        try:
            if parsed_tree is not None:
                query_symbols = extract_consts(parsed_tree)
            else:
                query_symbols = _extract_symbols_regex(goal_type)

            if query_symbols:
                mepo_raw = mepo_select(
                    query_symbols,
                    ctx.inverted_index,
                    ctx.symbol_frequencies,
                    ctx.declaration_symbols,
                    p=0.6,
                    c=2.4,
                    max_rounds=5,
                )
                if mepo_raw:
                    id_to_name = _resolve_ids(
                        [m[0] for m in mepo_raw], ctx.reader
                    )
                    mepo = [
                        (id_to_name[m[0]], m[1])
                        for m in mepo_raw
                        if m[0] in id_to_name
                    ]
        except Exception:
            pass

        # --- FTS channel ---
        fts: list[tuple[str, float]] = []
        try:
            query = fts_query(goal_type)
            if query:
                fts_results = fts_search(query, limit=500, reader=ctx.reader)
                fts = [(r.name, r.score) for r in fts_results]
        except Exception:
            pass

        results.append(PrecomputedQuery(
            structural=structural,
            mepo=mepo,
            fts=fts,
            ground_truth=ground_truth,
        ))

    if parse_failures:
        logger.info(
            "Structural channel parse failures: %d/%d (%.1f%%)",
            parse_failures, len(val_data),
            100 * parse_failures / len(val_data),
        )

    return results


def _resolve_ids(
    decl_ids: list[int], reader: Any,
) -> dict[int, str]:
    """Resolve integer declaration IDs to names via the reader."""
    try:
        rows = reader.get_declarations_by_ids(decl_ids)
        if isinstance(rows, list):
            return {row[0]: row[1] for row in rows if len(row) >= 2}
        elif isinstance(rows, dict):
            return {did: info.get("name", "") for did, info in rows.items()}
    except Exception:
        pass
    return {}


def _extract_symbols_regex(text: str) -> set[str]:
    """Regex-based symbol extraction fallback for when parsing fails.

    Finds dot-separated identifiers like Nat.add, Coq.Init.Datatypes.nat.
    """
    import re
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_.]*\.[A-Za-z_][A-Za-z0-9_.]*', text))


class RRFTuner:
    """Optuna-based optimization for RRF k and per-channel weights.

    Pre-computes channel results once, then each Optuna trial only
    re-fuses with different parameters — sub-second per trial.
    """

    @staticmethod
    def tune(
        cached_results: list[PrecomputedQuery],
        output_dir: Path,
        n_trials: int = 30,
        channel_names: list[str] | None = None,
        study_name: str = "poule-rrf-hpo",
        resume: bool = False,
    ) -> RRFTuningResult:
        """Run RRF parameter optimization.

        Args:
            cached_results: Pre-computed channel ranked lists per query.
            output_dir: Directory for the Optuna study SQLite DB.
            n_trials: Number of trials to run.
            channel_names: Channel names to optimize weights for
                (default: ["structural", "mepo", "fts"]).
            study_name: Optuna study name.
            resume: If True, resume an existing study.

        Returns:
            RRFTuningResult with best k, weights, and Recall@32.
        """
        import optuna

        if channel_names is None:
            channel_names = ["structural", "mepo", "fts"]

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        study_path = output_dir / "rrf-study.db"
        storage = f"sqlite:///{study_path}"

        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            load_if_exists=resume,
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        def objective(trial: optuna.Trial) -> float:
            k = trial.suggest_int("rrf_k", 1, 100)
            weights = {}
            for name in channel_names:
                weights[name] = trial.suggest_float(
                    f"w_{name}", 0.0, 2.0,
                )
            return evaluate_cached(cached_results, k=k, weights=weights)

        # Suppress Optuna logging during trials
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        study.optimize(objective, n_trials=n_trials)

        best = study.best_trial
        best_weights = {
            name: best.params[f"w_{name}"] for name in channel_names
        }

        all_trials = []
        for trial in study.trials:
            all_trials.append({
                "number": trial.number,
                "value": trial.value,
                "params": trial.params,
            })

        result = RRFTuningResult(
            best_k=best.params["rrf_k"],
            best_weights=best_weights,
            best_recall_32=best.value,
            n_trials=len(study.trials),
            study_path=str(study_path),
            all_trials=all_trials,
        )

        # Persist best parameters for downstream consumption
        import json

        params_path = output_dir / "best_params.json"
        params_path.write_text(json.dumps({
            "rrf_k": result.best_k,
            "weights": result.best_weights,
            "recall_32": result.best_recall_32,
            "n_trials": result.n_trials,
        }, indent=2) + "\n")

        return result
