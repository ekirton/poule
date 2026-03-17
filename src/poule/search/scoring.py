"""Scoring function for search nodes.

Spec: specification/proof-search-engine.md §4.7
"""

from __future__ import annotations

from poule.search.types import SearchNode
from poule.session.types import ProofState

# Provisional weights (spec §4.7)
_GOAL_REDUCTION_WEIGHT = 0.7
_DEPTH_PENALTY_WEIGHT = 0.3


def score_node(node: SearchNode, root_state: ProofState) -> float:
    """Score a search node relative to the root state.

    score = goal_reduction_weight * goal_progress + depth_penalty_weight * (1 / (1 + depth))

    Where:
    - goal_progress = (root_goal_count - node_goal_count) / root_goal_count
    - When root_goal_count = 0, goal_progress = 1.0
    """
    root_goal_count = len(root_state.goals)
    node_goal_count = len(node.proof_state.goals)

    if root_goal_count == 0:
        goal_progress = 1.0
    else:
        goal_progress = (root_goal_count - node_goal_count) / root_goal_count

    depth_factor = 1.0 / (1.0 + node.depth)

    return _GOAL_REDUCTION_WEIGHT * goal_progress + _DEPTH_PENALTY_WEIGHT * depth_factor
