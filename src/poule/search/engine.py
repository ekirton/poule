"""Proof search engine: best-first tree search over tactic candidates.

Spec: specification/proof-search-engine.md
"""

from __future__ import annotations

import heapq
import time
from typing import Any, Optional

from poule.search.diversity import filter_candidates
from poule.search.scoring import score_node
from poule.search.state_cache import hash_proof_state
from poule.search.types import ProofStep, SearchNode, SearchResult
from poule.session.errors import (
    BACKEND_CRASHED,
    SESSION_EXPIRED,
    SESSION_NOT_FOUND,
    TACTIC_ERROR,
    SessionError,
)
from poule.session.types import ProofState

# Solver tactics in the order specified by spec §4.3
_SOLVER_TACTICS: list[str] = [
    "auto",
    "eauto",
    "omega",
    "lia",
    "intuition",
    "tauto",
    "congruence",
    "reflexivity",
    "assumption",
    "trivial",
]


def generate_candidates(
    proof_state: ProofState,
    premises: Optional[list[Any]] = None,
    few_shot_examples: Optional[list[tuple[str, str]]] = None,
) -> list[str]:
    """Generate tactic candidates for a proof state.

    Solver tactics appear first in the specified order (spec §4.3),
    followed by LLM-generated tactics (when available).
    """
    candidates = list(_SOLVER_TACTICS)

    # LLM candidates would be appended here when the Claude API
    # is configured. For now, solver-only mode.
    # Future: call Claude API with proof_state, premises, few_shot_examples

    return candidates


def _ensure_dot(tactic: str) -> str:
    """Ensure a tactic string ends with a period (Coq convention)."""
    t = tactic.strip()
    if not t.endswith("."):
        return t + "."
    return t


# Module-level premise cache keyed by (pipeline_id, goal_type)
_premise_cache: dict[tuple[int, str], list[Any]] = {}


async def retrieve_premises(
    proof_state: ProofState,
    retrieval_pipeline: Optional[Any] = None,
) -> list[Any]:
    """Retrieve relevant premises for the focused goal.

    When the retrieval pipeline is unavailable, returns an empty list.
    Results are cached per unique goal type string and pipeline instance.
    """
    if retrieval_pipeline is None:
        return []

    if not proof_state.goals:
        return []

    goal_type = proof_state.goals[proof_state.focused_goal_index or 0].type
    cache_key = (id(retrieval_pipeline), goal_type)

    if cache_key in _premise_cache:
        return _premise_cache[cache_key]

    try:
        type_results = await retrieval_pipeline.search_by_type(goal_type, limit=20)
    except Exception:
        type_results = []

    try:
        # Extract symbols from goal type (simple tokenization)
        symbols = [t for t in goal_type.split() if t[0].isupper() or "." in t]
        if symbols:
            sym_results = await retrieval_pipeline.search_by_symbols(symbols, limit=20)
        else:
            sym_results = []
    except Exception:
        sym_results = []

    # Deduplicate by name, keep max score
    seen: dict[str, Any] = {}
    for item in type_results + sym_results:
        name = item.get("name", item) if isinstance(item, dict) else getattr(item, "name", str(item))
        if name not in seen:
            seen[name] = item
        else:
            existing = seen[name]
            existing_score = existing.get("score", 0) if isinstance(existing, dict) else getattr(existing, "score", 0)
            new_score = item.get("score", 0) if isinstance(item, dict) else getattr(item, "score", 0)
            if new_score > existing_score:
                seen[name] = item

    result = list(seen.values())[:20]
    _premise_cache[cache_key] = result
    return result


async def proof_search(
    session_manager: Any,
    session_id: str,
    timeout: float = 30,
    max_depth: int = 10,
    max_breadth: int = 20,
    retrieval_pipeline: Optional[Any] = None,
    training_data_path: Optional[str] = None,
) -> SearchResult:
    """Execute best-first tree search for a proof (spec §4.1–§4.2).

    Raises SessionError for SESSION_NOT_FOUND and SESSION_EXPIRED.
    Returns SearchResult for all other outcomes.
    """
    # Clamp inputs (spec §7.1)
    if timeout <= 0:
        timeout = 1
    if max_depth <= 0:
        max_depth = 1
    if max_breadth <= 0:
        max_breadth = 1

    start_time = time.monotonic()
    states_explored = 0
    state_cache: set[bytes] = set()

    # Observe initial state — may raise SESSION_NOT_FOUND / SESSION_EXPIRED
    initial_state = await session_manager.observe_state(session_id)

    # Already complete? Return immediately (spec §4.1)
    if initial_state.is_complete:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return SearchResult(
            status="success",
            proof_script=[],
            best_partial=None,
            states_explored=0,
            unique_states=0,
            wall_time_ms=elapsed_ms,
            llm_unavailable=False,
        )

    # Initialize root node
    root_hash = hash_proof_state(initial_state)
    state_cache.add(root_hash)
    root_node = SearchNode(
        proof_state=initial_state,
        state_hash=root_hash,
        tactic_path=[],
        depth=0,
        score=1.0,
        parent=None,
    )

    # Priority queue: (neg_score, counter, node) — heapq is a min-heap
    counter = 0
    frontier: list[tuple[float, int, SearchNode]] = []
    heapq.heappush(frontier, (-root_node.score, counter, root_node))
    counter += 1

    best_partial_node: Optional[SearchNode] = None
    best_partial_depth = -1

    deadline = start_time + timeout

    while frontier:
        # Check deadline
        if time.monotonic() >= deadline:
            break

        _, _, node = heapq.heappop(frontier)
        states_explored += 1

        # Skip nodes at max_depth (spec §4.2 step 3)
        if node.depth >= max_depth:
            continue

        # Track best partial
        if node.depth > best_partial_depth:
            best_partial_depth = node.depth
            best_partial_node = node

        # Generate candidates (spec §4.3)
        candidates = generate_candidates(node.proof_state)

        # Filter candidates (spec §4.5)
        candidates = filter_candidates(candidates)

        # Limit to max_breadth (spec §4.2 step 6)
        candidates = candidates[:max_breadth]

        # Navigate to node position (spec §4.8)
        try:
            await session_manager.step_backward(session_id)
            for tactic in node.tactic_path:
                await session_manager.submit_tactic(session_id, tactic)
        except SessionError as exc:
            if exc.code in (SESSION_NOT_FOUND, SESSION_EXPIRED):
                raise
            if exc.code == BACKEND_CRASHED:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return SearchResult(
                    status="failure",
                    proof_script=None,
                    best_partial=_build_partial_steps(best_partial_node),
                    states_explored=states_explored,
                    unique_states=len(state_cache),
                    wall_time_ms=elapsed_ms,
                    llm_unavailable=False,
                )
            # Other errors during replay — skip this node
            continue

        # Try each candidate (spec §4.2 steps 7–10)
        for raw_tactic in candidates:
            if time.monotonic() >= deadline:
                break

            tactic = _ensure_dot(raw_tactic)
            try:
                new_state = await session_manager.submit_tactic(session_id, tactic)
            except SessionError as exc:
                if exc.code == TACTIC_ERROR:
                    continue  # Discard failed tactic
                if exc.code == BACKEND_CRASHED:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    return SearchResult(
                        status="failure",
                        proof_script=None,
                        best_partial=_build_partial_steps(best_partial_node),
                        states_explored=states_explored,
                        unique_states=len(state_cache),
                        wall_time_ms=elapsed_ms,
                        llm_unavailable=False,
                    )
                if exc.code in (SESSION_NOT_FOUND, SESSION_EXPIRED):
                    raise
                continue

            new_tactic_path = node.tactic_path + [tactic]

            # Check completion (spec §4.2 step 8)
            if new_state.is_complete:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                steps = _build_proof_steps(
                    node, tactic, new_state, initial_state, session_manager, session_id,
                )
                return SearchResult(
                    status="success",
                    proof_script=steps,
                    best_partial=None,
                    states_explored=states_explored,
                    unique_states=len(state_cache),
                    wall_time_ms=elapsed_ms,
                    llm_unavailable=False,
                )

            # Check state cache (spec §4.2 step 9)
            new_hash = hash_proof_state(new_state)
            if new_hash in state_cache:
                # Navigate back for next candidate
                try:
                    await session_manager.step_backward(session_id)
                    for t in node.tactic_path:
                        await session_manager.submit_tactic(session_id, t)
                except SessionError:
                    pass
                continue

            state_cache.add(new_hash)

            child_node = SearchNode(
                proof_state=new_state,
                state_hash=new_hash,
                tactic_path=new_tactic_path,
                depth=node.depth + 1,
                score=score_node(
                    SearchNode(
                        proof_state=new_state,
                        state_hash=new_hash,
                        tactic_path=new_tactic_path,
                        depth=node.depth + 1,
                        score=0,
                        parent=node,
                    ),
                    initial_state,
                ),
                parent=node,
            )

            heapq.heappush(frontier, (-child_node.score, counter, child_node))
            counter += 1

            # Navigate back for next candidate
            try:
                await session_manager.step_backward(session_id)
                for t in node.tactic_path:
                    await session_manager.submit_tactic(session_id, t)
            except SessionError:
                pass

    # Search exhausted or timed out
    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return SearchResult(
        status="failure",
        proof_script=None,
        best_partial=_build_partial_steps(best_partial_node),
        states_explored=states_explored,
        unique_states=len(state_cache),
        wall_time_ms=elapsed_ms,
        llm_unavailable=False,
    )


def _build_proof_steps(
    parent_node: SearchNode,
    final_tactic: str,
    final_state: ProofState,
    initial_state: ProofState,
    session_manager: Any,
    session_id: str,
) -> list[ProofStep]:
    """Build the complete proof script from root to success."""
    # Reconstruct states along the path
    steps: list[ProofStep] = []

    # Walk up the parent chain to get all nodes
    nodes: list[SearchNode] = []
    current: Optional[SearchNode] = parent_node
    while current is not None:
        nodes.append(current)
        current = current.parent
    nodes.reverse()

    # Build steps from each transition
    for i, node in enumerate(nodes):
        if i == 0 and not node.tactic_path:
            # Root node — no tactic to record
            continue
        if node.tactic_path:
            tactic = node.tactic_path[-1]
            prev_node = nodes[i - 1] if i > 0 else None
            state_before = prev_node.proof_state if prev_node else initial_state
            steps.append(ProofStep(
                tactic=tactic,
                state_before=state_before,
                state_after=node.proof_state,
            ))

    # Add the final successful tactic
    steps.append(ProofStep(
        tactic=final_tactic,
        state_before=parent_node.proof_state,
        state_after=final_state,
    ))

    return steps


def _build_partial_steps(node: Optional[SearchNode]) -> Optional[list[ProofStep]]:
    """Build partial proof steps from the deepest node."""
    if node is None or not node.tactic_path:
        return None

    # Walk up the chain
    nodes: list[SearchNode] = []
    current: Optional[SearchNode] = node
    while current is not None:
        nodes.append(current)
        current = current.parent
    nodes.reverse()

    steps: list[ProofStep] = []
    for i in range(1, len(nodes)):
        prev = nodes[i - 1]
        curr = nodes[i]
        tactic = curr.tactic_path[-1] if curr.tactic_path else ""
        steps.append(ProofStep(
            tactic=tactic,
            state_before=prev.proof_state,
            state_after=curr.proof_state,
        ))

    return steps if steps else None
