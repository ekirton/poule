"""Error parser for setoid rewriting assistant."""

from __future__ import annotations

import re
from typing import Any

from .types import ParsedError, RelationSlot


class ErrorParser:
    """Classifies and parses rewriting error messages."""

    def parse(self, error_message: str, goal: str = "") -> ParsedError:
        """Parse an error message into a ParsedError."""
        # Pattern 1: Missing Proper constraint
        if "Proper" in error_message and ("setoid rewrite failed" in error_message
                                           or "Unable to satisfy" in error_message):
            return self._parse_missing_proper(error_message)

        # Pattern 2: Rewrite under binder
        match = re.search(r'Found no subterm matching "([^"]+)"', error_message)
        if match:
            pattern = match.group(1)
            return self._parse_binder_rewrite(error_message, pattern, goal)

        # Unrecognized
        return ParsedError(
            error_class="_unrecognized",
            raw_error=error_message,
        )

    def _parse_missing_proper(self, error_message: str) -> ParsedError:
        """Parse Pattern 1: Missing Proper constraint from evar dump."""
        # Extract Proper constraints from evar list
        # Pattern: ?X42==[... |- Proper (R1 ==> R2 ==> ... ==> Rout) function_name]
        proper_match = re.search(
            r'\|-\s*Proper\s*\(([^)]+)\)\s+([^\]\s]+)\]',
            error_message,
        )

        function_name = None
        slots: list[RelationSlot] = []

        if proper_match:
            sig_str = proper_match.group(1)
            function_name = proper_match.group(2).strip()

            # Parse the ==> chain
            # Split on ==>
            parts = re.split(r'\s*==>\s*', sig_str)
            for i, part in enumerate(parts):
                part = part.strip()
                # Check if it's an evar (starts with ?)
                relation = None if part.startswith('?') else part
                slots.append(
                    RelationSlot(
                        position=i,
                        relation=relation,
                        argument_type="",
                        variance="covariant",
                    )
                )

        return ParsedError(
            error_class="missing_proper",
            function_name=function_name,
            partial_signature=slots,
            binder_type=None,
            rewrite_target=None,
            raw_error=error_message,
        )

    def _parse_binder_rewrite(
        self, error_message: str, pattern: str, goal: str
    ) -> ParsedError:
        """Parse Pattern 2: Rewrite under binder."""
        # Check if the pattern appears under a binder in the goal
        binder_type = self._detect_binder(pattern, goal)

        if binder_type:
            return ParsedError(
                error_class="binder_rewrite",
                function_name=None,
                partial_signature=[],
                binder_type=binder_type,
                rewrite_target=pattern,
                raw_error=error_message,
            )
        else:
            return ParsedError(
                error_class="pattern_not_found",
                function_name=None,
                partial_signature=[],
                binder_type=None,
                rewrite_target=pattern,
                raw_error=error_message,
            )

    def _detect_binder(self, pattern: str, goal: str) -> str | None:
        """Detect if pattern appears under a binder in the goal."""
        if not goal:
            return None

        # Extract first token of pattern for matching
        pattern_tokens = pattern.split()
        if not pattern_tokens:
            return None

        # Check for forall
        if re.search(r'\bforall\b', goal) and self._pattern_under_binder(pattern, goal, "forall"):
            return "forall"

        # Check for exists
        if re.search(r'\bexists\b', goal) and self._pattern_under_binder(pattern, goal, "exists"):
            return "exists"

        # Check for fun
        if re.search(r'\bfun\b', goal) and self._pattern_under_binder(pattern, goal, "fun"):
            return "fun"

        return None

    def _pattern_under_binder(self, pattern: str, goal: str, binder: str) -> bool:
        """Check if pattern could appear under the given binder."""
        # Simple heuristic: the binder appears before any occurrence of pattern's key term
        # Extract the main identifier from pattern
        main_id = pattern.split()[0]

        binder_pos = goal.find(binder)
        if binder_pos < 0:
            return False

        # Check if the main_id appears after the binder
        after_binder = goal[binder_pos:]
        return main_id in after_binder
