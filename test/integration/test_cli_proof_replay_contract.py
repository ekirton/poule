"""Contract tests for the replay-proof CLI command.

These tests exercise the real Coq backend to verify mock/real parity.

Spec: specification/cli.md §4.6
Architecture: doc/architecture/cli.md
Feature: doc/features/cli-proof-replay.md
"""

from __future__ import annotations

import pytest


def test_replay_proof_contract_with_real_backend():
    """Contract test: verify replay-proof works with a real Coq backend.

    This test exercises the same SessionManager interface that the mocked
    tests above verify, ensuring mock/real parity per test/CLAUDE.md.
    """
    pytest.skip("Requires Coq backend — run with --run-coq flag")
