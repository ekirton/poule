"""Training data loading: JSONL parsing, tactic family extraction, file-level split.

Reads compact training data JSONL (spec §4.0.5): "s" (step) and "g"
(goal-state) records produced by the extraction pipeline.

Tactic family extraction and data loading follows specification/neural-training.md §4.1.
"""

from __future__ import annotations

import json
import random
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# Proof state text beyond this length is truncated on read.
_MAX_STMT = 4096

# Tactic family aliases: normalize variant spellings to canonical names.
_ALIASES: dict[str, str] = {
    "intro": "intros",
    "Proof": "intros",  # "Proof." is effectively a no-op; skip or map
    "now": "auto",  # 'now tac' wraps tac + auto
}


def extract_tactic_family(tactic_text: str) -> str:
    """Extract the tactic family name from raw tactic text.

    spec §4.1: Parse the first whitespace-delimited token, normalize
    SSReflect prefixes, strip trailing punctuation, apply aliases.
    """
    text = tactic_text.strip()
    if not text:
        return "other"

    # Handle SSReflect: strip 'by' prefix
    if text.startswith("by "):
        text = text[3:].strip()
        if not text:
            return "other"

    # Handle compound tactics: take the first segment before ';'
    first_segment = text.split(";")[0].strip()
    if not first_segment:
        return "other"

    # Extract the first token
    first_token = first_segment.split()[0]

    # Strip trailing punctuation
    first_token = first_token.rstrip(".,;:")

    # Strip SSReflect intro pattern operator: move=> -> move
    if first_token.endswith("=>"):
        first_token = first_token[:-2]

    # Strip SSReflect '/' suffix: apply/eqp -> apply, case/andp -> case
    slash_idx = first_token.find("/")
    if slash_idx > 0:
        first_token = first_token[:slash_idx]

    if not first_token:
        return "other"

    # Lowercase
    family = first_token.lower()

    # Apply aliases
    family = _ALIASES.get(family, family)

    # Handle SSReflect compound: move=>/rewrite/apply with modifiers
    if family in ("move", "case", "elim", "have", "suff", "wlog"):
        # These are SSReflect tactics -- keep as-is
        pass

    return family


def serialize_goals(goals: list[dict]) -> str:
    """Serialize a list of Goal dicts to a single text string.

    Canonical implementation is in Poule.extraction.output.serialize_goals.
    This re-export preserves backward compatibility.
    """
    from Poule.extraction.output import serialize_goals as _impl

    return _impl(goals)


# ---------------------------------------------------------------------------
# Structured proof state serialization (spec §4.0.8)
# ---------------------------------------------------------------------------

HEAD_CONSTRUCTORS = frozenset({
    "forall", "eq", "and", "or", "ex", "not", "True", "False",
    "le", "lt", "ge", "gt", "plus", "mult", "minus", "iff",
    "prod", "sum", "Peano.le", "Peano.lt", "other",
})

# Map Coq notations to their underlying type names
_NOTATION_TO_HEAD = {
    "=": "eq",
    "/\\": "and",
    "\\/": "or",
    "<=": "le",
    "<": "lt",
    ">=": "ge",
    ">": "gt",
    "+": "plus",
    "*": "mult",
    "-": "minus",
    "<->": "iff",
    "~": "not",
    "exists": "ex",
}

# Regex for hypothesis lines in flat format
_HYP_LINE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z_0-9']*) : (.+)$")


def extract_goal_head(goal_type_text: str) -> str:
    """Extract the head constructor from a goal type string.

    spec §4.0.8: The head is the first whitespace-delimited token after
    stripping leading '(' characters. If the head is in HEAD_CONSTRUCTORS,
    return it; otherwise return 'other'.
    """
    text = goal_type_text.strip()
    if not text:
        return "other"

    # Strip leading parens
    text = text.lstrip("(").strip()
    if not text:
        return "other"

    # Get the first token
    first_token = text.split()[0] if text.split() else ""

    # Check direct match in HEAD_CONSTRUCTORS
    if first_token in HEAD_CONSTRUCTORS:
        return first_token

    # Check if first token maps to a head via notation
    if first_token in _NOTATION_TO_HEAD:
        return _NOTATION_TO_HEAD[first_token]

    # Check infix notation mappings — lowest-precedence operators first
    # In Coq, = < /\ \/ <-> are lower precedence than + * - <= < >= >
    # So we check for them first (they are the true "head" of the expression)
    tokens_set = set(text.split())
    # Priority order: check low-precedence (outermost) notations first
    _LOW_PRECEDENCE = ["<->", "=", "/\\", "\\/"]
    for notation in _LOW_PRECEDENCE:
        if notation in tokens_set and notation in _NOTATION_TO_HEAD:
            return _NOTATION_TO_HEAD[notation]

    # Then check remaining infix notations
    tokens = text.split()
    for token in tokens[1:]:
        if token in _NOTATION_TO_HEAD:
            return _NOTATION_TO_HEAD[token]

    return "other"


def serialize_structured(
    state_text: str,
    prev_tactic: str | None = None,
    depth: int = 0,
    ngoals: int = 1,
    max_body_tokens: int = 32,
) -> str:
    """Convert a flat proof state string to structured format with markers.

    spec §4.0.8: Adds context prefix tokens and structural markers.
    The output is suitable for BPE tokenization (no [CLS]/[SEP]).

    Args:
        state_text: Flat proof state (output of serialize_goals).
        prev_tactic: Previous tactic family name, or None for first step.
        depth: Number of tactics applied so far in the proof.
        ngoals: Number of goals in the proof state.
        max_body_tokens: Max whitespace-delimited tokens for [BODY] content.
    """
    # Parse goals from flat text
    goals_text = state_text.split("\n\n") if state_text.strip() else []

    parsed_goals: list[dict] = []
    for goal_block in goals_text:
        lines = goal_block.split("\n")
        hyps: list[dict] = []
        goal_line = ""
        for line in lines:
            m = _HYP_LINE_RE.match(line)
            if m:
                name = m.group(1)
                type_and_body = m.group(2)
                # Check for let-binding body (:= separator)
                if " := " in type_and_body:
                    hyp_type, body = type_and_body.split(" := ", 1)
                    hyps.append({"name": name, "type": hyp_type, "body": body})
                else:
                    hyps.append({"name": name, "type": type_and_body})
            else:
                goal_line = line
        parsed_goals.append({"hypotheses": hyps, "type": goal_line})

    # Extract goal head from first goal
    first_goal_type = parsed_goals[0]["type"] if parsed_goals else ""
    head = extract_goal_head(first_goal_type)

    # Build context prefix
    prev_str = prev_tactic if prev_tactic is not None else "none"
    depth_str = "10+" if depth >= 10 else str(min(depth, 10))
    ngoals_str = "5+" if ngoals >= 5 else str(min(ngoals, 5))

    prefix = f"[PREV={prev_str}] [DEPTH={depth_str}] [NGOALS={ngoals_str}] [HEAD={head}]"

    # Build body with structural markers
    body_parts: list[str] = []
    for i, goal in enumerate(parsed_goals):
        if i > 0:
            body_parts.append("[GOALSEP]")
        for hyp in goal["hypotheses"]:
            if "body" in hyp and hyp["body"]:
                body_tokens = hyp["body"].split()
                truncated_body = " ".join(body_tokens[:max_body_tokens])
                body_parts.append(
                    f"[HYP] {hyp['name']} [TYPE] {hyp['type']} [BODY] {truncated_body}"
                )
            else:
                body_parts.append(f"[HYP] {hyp['name']} [TYPE] {hyp['type']}")
        if goal["type"]:
            body_parts.append(f"[GOAL] {goal['type']}")

    if body_parts:
        return f"{prefix} {' '.join(body_parts)}"
    return prefix


@dataclass
class TacticDataset:
    """Holds train/val/test splits of (proof_state_text, category_idx, within_idx) triples.

    Hierarchical classification: each sample has a category label and a
    within-category tactic label.
    """

    train_pairs: list[tuple[str, int, int]]
    val_pairs: list[tuple[str, int, int]]
    test_pairs: list[tuple[str, int, int]]
    label_map: dict[str, int]
    label_names: list[str]
    family_counts: dict[str, int]
    train_files: list[str] = field(default_factory=list)
    val_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    # Hierarchical fields
    category_names: list[str] = field(default_factory=list)
    per_category_label_maps: dict[str, dict[str, int]] = field(default_factory=dict)
    per_category_label_names: dict[str, list[str]] = field(default_factory=dict)
    per_category_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def num_classes(self) -> int:
        return len(self.label_names)

    @property
    def num_categories(self) -> int:
        return len(self.category_names)

    @property
    def per_category_sizes(self) -> dict[str, int]:
        """Number of tactic families per category."""
        return {
            cat: len(names)
            for cat, names in self.per_category_label_names.items()
        }


def undersample_train(
    dataset: TacticDataset,
    cap: int = 2000,
    seed: int = 42,
    min_count: int | None = None,
) -> TacticDataset:
    """Cap dominant tactic families and drop rare ones from training.

    spec §4.1: Groups training pairs by tactic family, randomly samples
    at most `cap` examples per family, drops families with fewer than
    `min_count` training examples, and returns a new TacticDataset
    with the reduced training split. Validation and test splits are unchanged.

    When `min_count` is None, defaults to 5% of `cap`.
    """
    from Poule.neural.training.taxonomy import (
        CATEGORY_NAMES,
        TACTIC_CATEGORIES,
    )

    if min_count is None:
        min_count = max(1, int(cap * 0.05))

    # Group train pairs + files by family
    family_groups: dict[str, list[int]] = {}
    for idx, (_, cat_idx, within_idx) in enumerate(dataset.train_pairs):
        cat_name = dataset.category_names[cat_idx]
        family = dataset.per_category_label_names[cat_name][within_idx]
        family_groups.setdefault(family, []).append(idx)

    # Undersample: cap each family, drop those below min_count
    rng = random.Random(seed)
    selected_indices: list[int] = []
    for family, indices in family_groups.items():
        if len(indices) < min_count:
            continue
        if len(indices) > cap:
            selected_indices.extend(rng.sample(indices, cap))
        else:
            selected_indices.extend(indices)

    # Preserve per-family ordering for determinism
    selected_indices.sort()

    new_train_pairs = [dataset.train_pairs[i] for i in selected_indices]
    new_train_files = [dataset.train_files[i] for i in selected_indices]

    # Recompute family_counts from undersampled train + unchanged val/test
    new_family_counts: Counter[str] = Counter()
    for pairs in (new_train_pairs, dataset.val_pairs, dataset.test_pairs):
        for _, cat_idx, within_idx in pairs:
            cat_name = dataset.category_names[cat_idx]
            family = dataset.per_category_label_names[cat_name][within_idx]
            new_family_counts[family] += 1

    # Recompute per_category_counts
    new_per_category_counts: dict[str, dict[str, int]] = {}
    for cat in dataset.category_names:
        cat_counts: dict[str, int] = {}
        for tac in dataset.per_category_label_names[cat]:
            count = new_family_counts.get(tac, 0)
            if count > 0:
                cat_counts[tac] = count
        new_per_category_counts[cat] = cat_counts

    return TacticDataset(
        train_pairs=new_train_pairs,
        val_pairs=dataset.val_pairs,
        test_pairs=dataset.test_pairs,
        label_map=dataset.label_map,
        label_names=dataset.label_names,
        family_counts=dict(new_family_counts),
        train_files=new_train_files,
        val_files=dataset.val_files,
        test_files=dataset.test_files,
        category_names=dataset.category_names,
        per_category_label_maps=dataset.per_category_label_maps,
        per_category_label_names=dataset.per_category_label_names,
        per_category_counts=new_per_category_counts,
    )


# Regex for identifying hypothesis lines: "identifier : rest"
_HYP_RE = re.compile(r"^[a-zA-Z_][a-zA-Z_0-9']* : ")

# Pool of synthetic variable names for identifier renaming.
_SYNTHETIC_NAMES = [f"v{i}" for i in range(200)]


def perturb_proof_state(state_text: str, rng: random.Random) -> str:
    """Apply label-preserving perturbations to a serialized proof state.

    spec §4.1: Applies hypothesis shuffling and identifier renaming.
    Both perturbations are provably label-preserving.

    Handles both structured format (with [HYP]/[TYPE]/[GOAL] markers)
    and flat format (newline-separated).
    """
    if "[HYP]" in state_text or "[GOAL]" in state_text:
        return _perturb_structured(state_text, rng)
    return _perturb_flat(state_text, rng)


def _perturb_flat(state_text: str, rng: random.Random) -> str:
    """Perturb a flat (newline-separated) proof state."""
    blocks = state_text.split("\n\n")
    shuffled_blocks = []

    for block in blocks:
        lines = block.split("\n")
        hyp_lines = []
        goal_lines = []
        for line in lines:
            if _HYP_RE.match(line):
                hyp_lines.append(line)
            else:
                goal_lines.append(line)

        if not hyp_lines:
            shuffled_blocks.append(block)
            continue

        rng.shuffle(hyp_lines)
        shuffled_blocks.append("\n".join(hyp_lines + goal_lines))

    shuffled_state = "\n\n".join(shuffled_blocks)

    # Identifier renaming: collect all hypothesis names across all blocks
    all_names: list[str] = []
    seen: set[str] = set()
    for block in shuffled_state.split("\n\n"):
        for line in block.split("\n"):
            if _HYP_RE.match(line):
                name = line.split(" : ", 1)[0]
                if name not in seen:
                    all_names.append(name)
                    seen.add(name)

    if not all_names:
        return shuffled_state

    # Build name mapping: original -> synthetic
    pool = list(_SYNTHETIC_NAMES)
    rng.shuffle(pool)
    name_map = {orig: pool[i] for i, orig in enumerate(all_names)}

    # Apply all replacements simultaneously using word-boundary-aware regex.
    sorted_names = sorted(name_map.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"(?<![a-zA-Z_0-9'])("
        + "|".join(re.escape(n) for n in sorted_names)
        + r")(?![a-zA-Z_0-9'])"
    )
    result = pattern.sub(lambda m: name_map[m.group(1)], shuffled_state)
    return result


# Regex to split structured text into hypothesis segments
_STRUCT_HYP_RE = re.compile(r"\[HYP\] ")


def _perturb_structured(state_text: str, rng: random.Random) -> str:
    """Perturb a structured proof state (with [HYP]/[TYPE]/[GOAL] markers).

    spec §4.1: Preserves context prefix, shuffles hypothesis segments
    within each goal block, renames identifiers in the body only.
    """
    # Split context prefix from body
    # Context prefix ends after [HEAD=...]
    head_match = re.search(r"\[HEAD=[^\]]+\]", state_text)
    if not head_match:
        return state_text
    prefix_end = head_match.end()
    prefix = state_text[:prefix_end]
    body = state_text[prefix_end:].strip()

    if not body:
        return state_text

    # Split body into goal blocks by [GOALSEP]
    goal_blocks = re.split(r"\s*\[GOALSEP\]\s*", body)

    shuffled_blocks: list[str] = []
    all_names: list[str] = []
    seen: set[str] = set()

    for block in goal_blocks:
        # Parse hypothesis segments and goal segment
        # Each hypothesis: [HYP] name [TYPE] type [BODY] body (optional)
        # Goal: [GOAL] ...
        hyp_segments: list[str] = []
        goal_segment = ""

        # Split on [GOAL] to separate hypotheses from goal
        goal_split = re.split(r"\s*(\[GOAL\]\s*.*)$", block.strip())
        hyp_part = goal_split[0].strip() if goal_split else ""
        if len(goal_split) > 1:
            goal_segment = goal_split[1].strip()

        # Parse individual hypothesis segments from hyp_part
        if hyp_part:
            # Split on [HYP] boundaries
            parts = re.split(r"\[HYP\]\s*", hyp_part)
            for part in parts:
                part = part.strip()
                if part:
                    hyp_segments.append(f"[HYP] {part}")
                    # Extract hypothesis name (token after [HYP])
                    name = part.split()[0] if part.split() else ""
                    if name and name not in seen:
                        all_names.append(name)
                        seen.add(name)

        # Shuffle hypotheses
        if hyp_segments:
            rng.shuffle(hyp_segments)

        # Reconstruct block
        block_parts = hyp_segments[:]
        if goal_segment:
            block_parts.append(goal_segment)
        shuffled_blocks.append(" ".join(block_parts))

    # Rejoin with [GOALSEP]
    shuffled_body = " [GOALSEP] ".join(shuffled_blocks)

    if not all_names:
        return f"{prefix} {shuffled_body}"

    # Identifier renaming (on body only, not prefix)
    pool = list(_SYNTHETIC_NAMES)
    rng.shuffle(pool)
    name_map = {orig: pool[i] for i, orig in enumerate(all_names)}

    sorted_names = sorted(name_map.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"(?<![a-zA-Z_0-9'])("
        + "|".join(re.escape(n) for n in sorted_names)
        + r")(?![a-zA-Z_0-9'])"
    )
    renamed_body = pattern.sub(lambda m: name_map[m.group(1)], shuffled_body)
    return f"{prefix} {renamed_body}"


def oversample_train(
    dataset: TacticDataset,
    floor: int = 500,
    seed: int = 42,
) -> TacticDataset:
    """Augment minority families up to a floor count in training.

    spec §4.1: Groups training pairs by tactic family, and for families
    with fewer than `floor` examples, samples source examples with
    replacement and applies label-preserving perturbations to create
    augmented examples, bringing the total to `floor`. Families at or
    above `floor` are unchanged. Validation and test splits are unchanged.
    """
    # Group train pairs + files by family
    family_groups: dict[str, list[int]] = {}
    for idx, (_, cat_idx, within_idx) in enumerate(dataset.train_pairs):
        cat_name = dataset.category_names[cat_idx]
        family = dataset.per_category_label_names[cat_name][within_idx]
        family_groups.setdefault(family, []).append(idx)

    rng = random.Random(seed)
    new_train_pairs = list(dataset.train_pairs)
    new_train_files = list(dataset.train_files)

    for family, indices in family_groups.items():
        if len(indices) >= floor:
            continue
        # Sample source indices with replacement to reach floor
        extra_count = floor - len(indices)
        extra_indices = rng.choices(indices, k=extra_count)
        for i in extra_indices:
            state, cat_idx, within_idx = dataset.train_pairs[i]
            perturbed = perturb_proof_state(state, rng)
            new_train_pairs.append((perturbed, cat_idx, within_idx))
            new_train_files.append(dataset.train_files[i])

    # Recompute family_counts from oversampled train + unchanged val/test
    new_family_counts: Counter[str] = Counter()
    for pairs in (new_train_pairs, dataset.val_pairs, dataset.test_pairs):
        for _, cat_idx, within_idx in pairs:
            cat_name = dataset.category_names[cat_idx]
            family = dataset.per_category_label_names[cat_name][within_idx]
            new_family_counts[family] += 1

    # Recompute per_category_counts
    new_per_category_counts: dict[str, dict[str, int]] = {}
    for cat in dataset.category_names:
        cat_counts: dict[str, int] = {}
        for tac in dataset.per_category_label_names[cat]:
            count = new_family_counts.get(tac, 0)
            if count > 0:
                cat_counts[tac] = count
        new_per_category_counts[cat] = cat_counts

    return TacticDataset(
        train_pairs=new_train_pairs,
        val_pairs=dataset.val_pairs,
        test_pairs=dataset.test_pairs,
        label_map=dataset.label_map,
        label_names=dataset.label_names,
        family_counts=dict(new_family_counts),
        train_files=new_train_files,
        val_files=dataset.val_files,
        test_files=dataset.test_files,
        category_names=dataset.category_names,
        per_category_label_maps=dataset.per_category_label_maps,
        per_category_label_names=dataset.per_category_label_names,
        per_category_counts=new_per_category_counts,
    )


@dataclass
class SplitReport:
    """Diagnostic report on train/val/test split distributions.

    spec §4.1: Generated from a populated TacticDataset to diagnose
    distribution shift between splits.
    """

    train_files: int
    val_files: int
    test_files: int
    train_steps: int
    val_steps: int
    test_steps: int
    num_classes: int
    family_distribution: list[tuple[str, int]]
    train_top_families: list[tuple[str, int]]
    val_top_families: list[tuple[str, int]]
    test_top_families: list[tuple[str, int]]
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def generate(dataset: TacticDataset) -> SplitReport:
        """Generate a split diagnostic report from a populated dataset."""

        def _family_counter(
            pairs, label_names: list[str],
        ) -> Counter:
            c: Counter[str] = Counter()
            for item in pairs:
                if len(item) == 3 and dataset.category_names:
                    # Hierarchical triple: (state, category_idx, within_idx)
                    cat_idx = item[1]
                    if cat_idx < len(dataset.category_names):
                        cat_name = dataset.category_names[cat_idx]
                        within_idx = item[2]
                        within_names = dataset.per_category_label_names.get(cat_name, [])
                        if within_idx < len(within_names):
                            c[within_names[within_idx]] += 1
                        else:
                            c[cat_name] += 1
                    else:
                        c["unknown"] += 1
                elif len(item) >= 2:
                    # Flat pair: (state, label_idx)
                    label_idx = item[1]
                    if label_idx < len(label_names):
                        c[label_names[label_idx]] += 1
                    else:
                        c["unknown"] += 1
            return c

        train_counter = _family_counter(dataset.train_pairs, dataset.label_names)
        val_counter = _family_counter(dataset.val_pairs, dataset.label_names)
        test_counter = _family_counter(dataset.test_pairs, dataset.label_names)

        total_counter = train_counter + val_counter + test_counter

        # Unique file counts
        train_file_set = set(dataset.train_files)
        val_file_set = set(dataset.val_files)
        test_file_set = set(dataset.test_files)

        # Warnings
        warnings: list[str] = []
        if len(dataset.test_pairs) < 100:
            warnings.append(
                "Test split has fewer than 100 steps -- metrics will be noisy"
            )
        if len(dataset.val_pairs) < 100:
            warnings.append(
                "Validation split has fewer than 100 steps -- metrics will be noisy"
            )
        # Check for dominant class
        if total_counter:
            top_family, top_count = total_counter.most_common(1)[0]
            total = sum(total_counter.values())
            if total > 0 and top_count / total > 0.30:
                warnings.append(
                    f"Dominant tactic family '{top_family}' accounts for "
                    f"{top_count / total:.0%} of all steps"
                )

        return SplitReport(
            train_files=len(train_file_set),
            val_files=len(val_file_set),
            test_files=len(test_file_set),
            train_steps=len(dataset.train_pairs),
            val_steps=len(dataset.val_pairs),
            test_steps=len(dataset.test_pairs),
            num_classes=dataset.num_classes,
            family_distribution=total_counter.most_common(),
            train_top_families=train_counter.most_common(10),
            val_top_families=val_counter.most_common(10),
            test_top_families=test_counter.most_common(10),
            warnings=warnings,
        )

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        d = {}
        for fld in self.__dataclass_fields__:
            val = getattr(self, fld)
            if isinstance(val, list) and val and isinstance(val[0], tuple):
                val = [[name, count] for name, count in val]
            d[fld] = val
        return d


# ---------------------------------------------------------------------------
# Data loading (spec §4.1)
# ---------------------------------------------------------------------------


class TrainingDataLoader:
    """Loads and splits training data from compact JSONL."""

    @staticmethod
    def load(
        jsonl_paths: list[Path],
    ) -> TacticDataset:
        """Load training steps from compact training data JSONL files.

        Hierarchical labels: each sample is a triple
        (proof_state_text, category_idx, within_category_idx).

        Proof structure tokens are excluded. Every tactic maps to a
        known category -- there is no "other" catch-all.
        """
        from Poule.neural.training.taxonomy import (
            CATEGORY_NAMES,
            EXCLUDED_TOKENS,
            TACTIC_CATEGORIES,
            TACTIC_TO_CATEGORY,
        )

        # Build per-category label maps
        per_category_label_maps: dict[str, dict[str, int]] = {}
        per_category_label_names: dict[str, list[str]] = {}
        for cat in CATEGORY_NAMES:
            tactics = TACTIC_CATEGORIES[cat]
            per_category_label_names[cat] = list(tactics)
            per_category_label_maps[cat] = {t: i for i, t in enumerate(tactics)}

        category_index = {cat: i for i, cat in enumerate(CATEGORY_NAMES)}

        # Build a flat label map (for backward compat / reporting)
        flat_label_names: list[str] = []
        flat_label_map: dict[str, int] = {}
        for cat in CATEGORY_NAMES:
            for tac in TACTIC_CATEGORIES[cat]:
                flat_label_map[tac] = len(flat_label_names)
                flat_label_names.append(tac)

        # Phase 1: Read all steps
        file_steps: dict[str, list[tuple[str, str]]] = {}
        raw_family_counts: Counter[str] = Counter()

        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if '"t":"s"' not in line[:25] and '"t": "s"' not in line[:25]:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("t") != "s":
                        continue

                    source_file = record["f"]
                    state_text = record["s"]
                    tactic_text = record.get("c", "")
                    if not tactic_text:
                        continue

                    if len(state_text) > _MAX_STMT:
                        state_text = state_text[:_MAX_STMT]

                    family = extract_tactic_family(tactic_text)

                    # Skip excluded tokens (proof structure)
                    if family in EXCLUDED_TOKENS:
                        continue

                    # Skip tactics not in the taxonomy
                    if family not in TACTIC_TO_CATEGORY:
                        continue

                    raw_family_counts[family] += 1

                    if source_file not in file_steps:
                        file_steps[source_file] = []
                    file_steps[source_file].append((state_text, family))

        # Return freed JSON-parse memory to the OS.
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        # Build per-category counts
        per_category_counts: dict[str, dict[str, int]] = {}
        for cat in CATEGORY_NAMES:
            cat_counts: dict[str, int] = {}
            for tac in TACTIC_CATEGORIES[cat]:
                count = raw_family_counts.get(tac, 0)
                if count > 0:
                    cat_counts[tac] = count
            per_category_counts[cat] = cat_counts

        # Phase 2: File-level deterministic split (spec §4.1)
        sorted_files = sorted(file_steps.keys())

        train_pairs: list[tuple[str, int, int]] = []
        val_pairs: list[tuple[str, int, int]] = []
        test_pairs: list[tuple[str, int, int]] = []
        train_files: list[str] = []
        val_files: list[str] = []
        test_files: list[str] = []

        for position, filepath in enumerate(sorted_files):
            steps = file_steps[filepath]
            labeled_steps: list[tuple[str, int, int]] = []
            prev_tactic: str | None = None
            for depth, (state, family) in enumerate(steps):
                # Count goal blocks in the flat state text
                ngoals = len(state.split("\n\n")) if state.strip() else 1
                # Apply structured serialization with context features
                structured = serialize_structured(
                    state, prev_tactic, depth, ngoals,
                )
                cat = TACTIC_TO_CATEGORY[family]
                cat_idx = category_index[cat]
                within_idx = per_category_label_maps[cat][family]
                labeled_steps.append((structured, cat_idx, within_idx))
                prev_tactic = family

            mod = position % 10
            if mod == 8:
                val_pairs.extend(labeled_steps)
                val_files.extend([filepath] * len(labeled_steps))
            elif mod == 9:
                test_pairs.extend(labeled_steps)
                test_files.extend([filepath] * len(labeled_steps))
            else:
                train_pairs.extend(labeled_steps)
                train_files.extend([filepath] * len(labeled_steps))

        del file_steps

        return TacticDataset(
            train_pairs=train_pairs,
            val_pairs=val_pairs,
            test_pairs=test_pairs,
            label_map=flat_label_map,
            label_names=flat_label_names,
            family_counts=dict(raw_family_counts),
            train_files=train_files,
            val_files=val_files,
            test_files=test_files,
            category_names=list(CATEGORY_NAMES),
            per_category_label_maps=per_category_label_maps,
            per_category_label_names=per_category_label_names,
            per_category_counts=per_category_counts,
        )

    @staticmethod
    def load_by_library(
        library_paths: dict[str, list[Path]],
        held_out_library: str,
        val_fraction: float = 0.1,
        seed: int = 42,
        always_train_libraries: list[str] | None = None,
    ) -> TacticDataset:
        """Load training data with a library-level split.

        spec §4.1: Holds out one library entirely as the test set.
        Remaining libraries' files are shuffled and split into
        train/val by ``val_fraction``.

        Libraries in ``always_train_libraries`` are always placed in the
        training split, never in validation or test, regardless of the
        held-out library.
        """
        import math

        from Poule.neural.training.taxonomy import (
            CATEGORY_NAMES,
            EXCLUDED_TOKENS,
            TACTIC_CATEGORIES,
            TACTIC_TO_CATEGORY,
        )

        # Build per-category label maps (same as load())
        per_category_label_maps: dict[str, dict[str, int]] = {}
        per_category_label_names: dict[str, list[str]] = {}
        for cat in CATEGORY_NAMES:
            tactics = TACTIC_CATEGORIES[cat]
            per_category_label_names[cat] = list(tactics)
            per_category_label_maps[cat] = {t: i for i, t in enumerate(tactics)}

        category_index = {cat: i for i, cat in enumerate(CATEGORY_NAMES)}

        flat_label_names: list[str] = []
        flat_label_map: dict[str, int] = {}
        for cat in CATEGORY_NAMES:
            for tac in TACTIC_CATEGORIES[cat]:
                flat_label_map[tac] = len(flat_label_names)
                flat_label_names.append(tac)

        # Phase 1: Read all steps, tagged by library
        # file_steps[filepath] = (library_name, [(state_text, family), ...])
        file_steps: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        raw_family_counts: Counter[str] = Counter()

        for lib_name, paths in library_paths.items():
            for path in paths:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        if (
                            '"t":"s"' not in line[:25]
                            and '"t": "s"' not in line[:25]
                        ):
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if record.get("t") != "s":
                            continue

                        source_file = record["f"]
                        state_text = record["s"]
                        tactic_text = record.get("c", "")
                        if not tactic_text:
                            continue

                        if len(state_text) > _MAX_STMT:
                            state_text = state_text[:_MAX_STMT]

                        family = extract_tactic_family(tactic_text)

                        if family in EXCLUDED_TOKENS:
                            continue
                        if family not in TACTIC_TO_CATEGORY:
                            continue

                        raw_family_counts[family] += 1

                        if source_file not in file_steps:
                            file_steps[source_file] = (lib_name, [])
                        file_steps[source_file][1].append((state_text, family))

        # Phase 2: Split by library membership
        always_train = set(always_train_libraries or [])
        held_out_files: list[str] = []
        always_train_files: list[str] = []
        remaining_files: list[str] = []

        for filepath, (lib_name, _steps) in file_steps.items():
            if lib_name == held_out_library:
                held_out_files.append(filepath)
            elif lib_name in always_train:
                always_train_files.append(filepath)
            else:
                remaining_files.append(filepath)

        held_out_files.sort()
        always_train_files.sort()
        remaining_files.sort()

        # Shuffle remaining files and split into train/val
        rng = random.Random(seed)
        shuffled = list(remaining_files)
        rng.shuffle(shuffled)

        split_idx = math.ceil(len(shuffled) * (1 - val_fraction))
        train_file_set = set(shuffled[:split_idx]) | set(always_train_files)
        val_file_set = set(shuffled[split_idx:])

        # Build per-category counts
        per_category_counts: dict[str, dict[str, int]] = {}
        for cat in CATEGORY_NAMES:
            cat_counts: dict[str, int] = {}
            for tac in TACTIC_CATEGORIES[cat]:
                count = raw_family_counts.get(tac, 0)
                if count > 0:
                    cat_counts[tac] = count
            per_category_counts[cat] = cat_counts

        # Phase 3: Assign steps to splits
        train_pairs: list[tuple[str, int, int]] = []
        val_pairs: list[tuple[str, int, int]] = []
        test_pairs: list[tuple[str, int, int]] = []
        train_files_list: list[str] = []
        val_files_list: list[str] = []
        test_files_list: list[str] = []

        for filepath in sorted(file_steps.keys()):
            _lib_name, steps = file_steps[filepath]
            labeled_steps: list[tuple[str, int, int]] = []
            for state, family in steps:
                cat = TACTIC_TO_CATEGORY[family]
                cat_idx = category_index[cat]
                within_idx = per_category_label_maps[cat][family]
                labeled_steps.append((state, cat_idx, within_idx))

            if filepath in train_file_set:
                train_pairs.extend(labeled_steps)
                train_files_list.extend([filepath] * len(labeled_steps))
            elif filepath in val_file_set:
                val_pairs.extend(labeled_steps)
                val_files_list.extend([filepath] * len(labeled_steps))
            else:
                # Held-out library
                test_pairs.extend(labeled_steps)
                test_files_list.extend([filepath] * len(labeled_steps))

        del file_steps

        return TacticDataset(
            train_pairs=train_pairs,
            val_pairs=val_pairs,
            test_pairs=test_pairs,
            label_map=flat_label_map,
            label_names=flat_label_names,
            family_counts=dict(raw_family_counts),
            train_files=train_files_list,
            val_files=val_files_list,
            test_files=test_files_list,
            category_names=list(CATEGORY_NAMES),
            per_category_label_maps=per_category_label_maps,
            per_category_label_names=per_category_label_names,
            per_category_counts=per_category_counts,
        )
