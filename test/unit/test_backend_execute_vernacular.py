"""Unit tests for vernacular command output capture in proof sessions.

The coq-lsp backend cannot capture output of Print/Check/About commands
(it only emits diagnostics for errors/warnings).  The session manager
works around this by lazily spawning a coqtop subprocess via _ensure_coqtop()
that loads the file's imports and handles vernacular queries.

This file tests:
1. CoqProofBackend.execute_vernacular — documents the coq-lsp limitation
2. SessionManager._ensure_coqtop — lazy coqtop spawning
3. SessionManager.send_command — routing through coqtop for proof sessions
4. _extract_imports — import extraction from .v files

Spec: specification/coq-proof-backend.md
      specification/proof-session.md (§4.4 submit_command)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lsp_backend():
    """Create a CoqProofBackend with mocked LSP transport."""
    from Poule.session.backend import CoqProofBackend

    backend = CoqProofBackend.__new__(CoqProofBackend)
    backend._next_id = 0
    backend._shut_down = False
    backend._notification_buffer = []
    backend._open_document = AsyncMock()
    backend._wait_for_diagnostics = AsyncMock(return_value=[])
    backend._send_notification = AsyncMock()
    backend._send_request = AsyncMock(return_value=None)
    backend._proc = MagicMock()
    backend._proc.returncode = None
    return backend


# ---------------------------------------------------------------------------
# 1. CoqProofBackend.execute_vernacular — coq-lsp limitation
# ---------------------------------------------------------------------------

class TestExecuteVernacularCoqLspLimitation:
    """Documents that coq-lsp returns empty output for successful queries."""

    @pytest.mark.asyncio
    async def test_no_diagnostics_returns_empty(self):
        """Successful Print/Check/About produce no diagnostics → empty output."""
        backend = _make_lsp_backend()
        backend._wait_for_diagnostics.return_value = []

        result = await backend.execute_vernacular("Print nat.")

        assert result == ""

    @pytest.mark.asyncio
    async def test_error_diagnostics_returned(self):
        """Error diagnostics ARE returned as output."""
        backend = _make_lsp_backend()
        backend._wait_for_diagnostics.return_value = [
            {"message": "Error: The reference foo was not found."}
        ]

        result = await backend.execute_vernacular("Print foo.")

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_multiple_diagnostics_joined(self):
        """Multiple diagnostics are joined with newlines."""
        backend = _make_lsp_backend()
        backend._wait_for_diagnostics.return_value = [
            {"message": "Warning: deprecated"},
            {"message": "Error: type mismatch"},
        ]

        result = await backend.execute_vernacular("Check bad_term.")

        assert "deprecated" in result
        assert "type mismatch" in result

    @pytest.mark.asyncio
    async def test_appends_period_when_missing(self):
        """Command without trailing period gets one appended."""
        backend = _make_lsp_backend()
        backend._wait_for_diagnostics.return_value = []

        await backend.execute_vernacular("Check nat")

        open_call = backend._open_document.call_args
        opened_text = open_call[0][1]
        assert opened_text.endswith(".")

    @pytest.mark.asyncio
    async def test_temp_document_closed(self):
        """Temporary document is closed after query."""
        backend = _make_lsp_backend()
        backend._wait_for_diagnostics.return_value = []

        await backend.execute_vernacular("Check nat.")

        backend._send_notification.assert_called_once()
        call_args = backend._send_notification.call_args
        assert call_args[0][0] == "textDocument/didClose"


# ---------------------------------------------------------------------------
# 1b. §4.5 Vernacular Output Capture Limitation — mechanism table
# ---------------------------------------------------------------------------

class TestVernacularOutputCaptureLimitation:
    """Spec §4.5: Three coq-lsp mechanisms that do NOT capture vernacular output."""

    @pytest.mark.asyncio
    async def test_hover_returns_hover_data_not_command_output(self):
        """textDocument/hover returns type information for identifiers at cursor
        position, not the output of vernacular commands like Print or Check.

        Spec §4.5 table row 2: 'textDocument/hover | Type information for
        identifiers at cursor position | No — returns hover data, not command output'"""
        backend = _make_lsp_backend()
        # Hover returns structured data (type signature), not raw Print output
        hover_result = {
            "contents": {"kind": "plaintext", "value": "nat : Set"},
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 3}},
        }
        backend._send_request.return_value = hover_result

        # Even if we could call hover, it returns type info for a position,
        # not the output of "Print nat." which would show the full inductive def.
        # The test documents that hover ≠ vernacular output capture.
        result = await backend._send_request("textDocument/hover", {
            "textDocument": {"uri": "file:///test.v"},
            "position": {"line": 0, "character": 0},
        })

        # Hover returns structured hover data, not command output
        assert "contents" in result
        assert isinstance(result["contents"], dict)
        # This is NOT the same as "Print nat." output which would contain
        # "Inductive nat : Set := O : nat | S : nat -> nat."

    @pytest.mark.asyncio
    async def test_get_document_returns_metadata_not_content(self):
        """coq/getDocument returns document span ranges (structural metadata),
        not the textual output of vernacular commands.

        Spec §4.5 table row 3: 'coq/getDocument | Document span ranges |
        No — returns structural metadata without content'"""
        backend = _make_lsp_backend()
        # getDocument returns span/range metadata
        doc_result = {
            "spans": [
                {"range": {"start": {"line": 0, "character": 0},
                           "end": {"line": 0, "character": 10}}},
            ]
        }
        backend._send_request.return_value = doc_result

        result = await backend._send_request("coq/getDocument", {
            "textDocument": {"uri": "file:///test.v"},
        })

        # Returns structural metadata (spans), not command output text
        assert "spans" in result
        assert isinstance(result["spans"], list)

    @pytest.mark.asyncio
    async def test_session_manager_responsible_for_vernacular_capture(self):
        """Spec §4.5: The session manager is responsible for vernacular output
        capture. When a session requires vernacular command execution, the session
        manager uses a coqtop subprocess rather than the session's CoqBackend."""
        from Poule.session.manager import SessionManager

        # submit_vernacular (which routes to coqtop) exists
        assert callable(getattr(SessionManager, "submit_vernacular", None))
        # send_command exists as the underlying dispatch
        assert callable(getattr(SessionManager, "send_command", None))


# ---------------------------------------------------------------------------
# 2. _extract_imports
# ---------------------------------------------------------------------------

class TestExtractImports:
    """_extract_imports extracts Require/Import lines from .v files."""

    def test_extracts_from_require_import(self, tmp_path):
        from Poule.session.manager import _extract_imports

        v_file = tmp_path / "test.v"
        v_file.write_text(
            "From Coq Require Import PeanoNat.\n"
            "From mathcomp Require Import ssreflect ssrnat.\n"
            "\n"
            "Lemma foo : True.\nProof. exact I. Qed.\n"
        )

        result = _extract_imports(str(v_file))

        assert "From Coq Require Import PeanoNat." in result
        assert "From mathcomp Require Import ssreflect ssrnat." in result
        assert "Lemma" not in result

    def test_extracts_plain_require(self, tmp_path):
        from Poule.session.manager import _extract_imports

        v_file = tmp_path / "test.v"
        v_file.write_text("Require Import Arith.\nLemma x : True. Proof. exact I. Qed.\n")

        result = _extract_imports(str(v_file))

        assert "Require Import Arith." in result

    def test_file_not_found_returns_empty(self):
        from Poule.session.manager import _extract_imports

        result = _extract_imports("/nonexistent/path.v")

        assert result == ""

    def test_no_imports_returns_empty(self, tmp_path):
        from Poule.session.manager import _extract_imports

        v_file = tmp_path / "test.v"
        v_file.write_text("Lemma foo : True. Proof. exact I. Qed.\n")

        result = _extract_imports(str(v_file))

        assert result == ""


# ---------------------------------------------------------------------------
# 2b. _extract_file_prelude
# ---------------------------------------------------------------------------

class TestExtractFilePrelude:
    """_extract_file_prelude loads the entire .v file content.

    Spec §4.4.1 step 2: The subprocess loads the session's file context —
    all vernacular commands from the entire .v file — so that vernacular
    introspection commands can reference any definition in the file.
    """

    def test_loads_entire_file_including_proof_target_and_beyond(self, tmp_path):
        from Poule.session.manager import _extract_file_prelude

        v_file = tmp_path / "test.v"
        v_file.write_text(
            "From Coq Require Import PeanoNat.\n"
            "\n"
            "Lemma helper : forall n, n + 0 = n.\n"
            "Proof. intros n. lia. Qed.\n"
            "\n"
            "Definition double (n : nat) := n + n.\n"
            "\n"
            "Lemma target : forall n, n = n.\n"
            "Proof.\n"
            "  reflexivity.\n"
            "Qed.\n"
            "\n"
            "Lemma after_target : True.\n"
            "Proof. exact I. Qed.\n"
        )

        result = _extract_file_prelude(str(v_file), "target")

        assert "From Coq Require Import PeanoNat." in result
        assert "Lemma helper" in result
        assert "Definition double" in result
        # Proof target and definitions after it are included
        assert "Lemma target" in result
        assert "Lemma after_target" in result

    def test_includes_all_definitions_for_multi_theorem_files(self, tmp_path):
        """Ensures compare_assumptions can see all file-local theorems."""
        from Poule.session.manager import _extract_file_prelude

        v_file = tmp_path / "test.v"
        v_file.write_text(
            "Lemma first : True.\n"
            "Proof. exact I. Qed.\n"
            "\n"
            "Lemma second : True.\n"
            "Proof. exact I. Qed.\n"
            "\n"
            "Lemma third : True.\n"
            "Proof. exact I. Qed.\n"
        )

        result = _extract_file_prelude(str(v_file), "first")

        assert "Lemma first" in result
        assert "Lemma second" in result
        assert "Lemma third" in result

    def test_no_proof_name_returns_imports_only(self, tmp_path):
        from Poule.session.manager import _extract_file_prelude

        v_file = tmp_path / "test.v"
        v_file.write_text(
            "From Coq Require Import PeanoNat.\n"
            "Definition foo := 1.\n"
            "Lemma bar : True. Proof. exact I. Qed.\n"
        )

        result = _extract_file_prelude(str(v_file), "")

        assert "From Coq Require Import PeanoNat." in result
        assert "Definition foo" not in result

    def test_proof_name_not_found_returns_all_content(self, tmp_path):
        from Poule.session.manager import _extract_file_prelude

        v_file = tmp_path / "test.v"
        v_file.write_text(
            "From Coq Require Import PeanoNat.\n"
            "Definition foo := 1.\n"
        )

        result = _extract_file_prelude(str(v_file), "nonexistent")

        # If proof name is not found, return everything (safe fallback)
        assert "From Coq Require Import PeanoNat." in result
        assert "Definition foo" in result

    def test_file_not_found_returns_empty(self):
        from Poule.session.manager import _extract_file_prelude

        result = _extract_file_prelude("/nonexistent/path.v", "anything")

        assert result == ""

    def test_loads_entire_file_for_any_keyword(self, tmp_path):
        """All proof-starting keywords load the full file."""
        from Poule.session.manager import _extract_file_prelude

        for keyword in ["Lemma", "Theorem", "Proposition", "Corollary",
                         "Example", "Fact", "Remark"]:
            v_file = tmp_path / f"test_{keyword}.v"
            v_file.write_text(
                "Definition setup := 42.\n"
                f"{keyword} target : True.\n"
                "Proof. exact I. Qed.\n"
                "Definition after := 99.\n"
            )

            result = _extract_file_prelude(str(v_file), "target")

            assert "Definition setup" in result, f"Failed for keyword {keyword}"
            assert f"{keyword} target" in result, f"Failed for keyword {keyword}"
            assert "Definition after" in result, f"Failed for keyword {keyword}"


# ---------------------------------------------------------------------------
# 3. SessionManager.send_command routes through coqtop
# ---------------------------------------------------------------------------

class TestSendCommandCoqtopFallback:
    """send_command lazily spawns coqtop for proof sessions with coq-lsp backend."""

    @pytest.mark.asyncio
    async def test_submit_vernacular_lazily_spawns_coqtop(self):
        """submit_vernacular (prefer_coqtop=True) calls _ensure_coqtop."""
        from Poule.session.manager import SessionManager

        backend = MagicMock()
        backend.load_file = AsyncMock()
        backend.position_at_proof = AsyncMock(return_value=MagicMock(
            schema_version=1,
            session_id="",
            step_index=0,
            is_complete=False,
            focused_goal_index=0,
            goals=[],
        ))
        backend.shutdown = AsyncMock()
        backend.original_script = []

        mgr = SessionManager(backend_factory=AsyncMock(return_value=backend))
        sid, _ = await mgr.create_session("/file.v", "proof1")

        ss = mgr._registry[sid]
        assert ss.coqtop_proc is None
        assert ss.coq_backend is not None

        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdin.write = MagicMock()
        fake_proc.stdin.drain = AsyncMock()

        async def fake_ensure(session_state):
            session_state.coqtop_proc = fake_proc
            return fake_proc

        with patch.object(mgr, '_ensure_coqtop', side_effect=fake_ensure) as mock_ensure:
            with patch.object(mgr, '_read_until_sentinel', new_callable=AsyncMock, return_value="nat : Set"):
                result = await mgr.submit_vernacular(sid, "Check nat.")

        mock_ensure.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command_without_prefer_coqtop_uses_backend(self):
        """send_command (default, prefer_coqtop=False) uses coq_backend.execute_vernacular."""
        from Poule.session.manager import SessionManager

        backend = MagicMock()
        backend.load_file = AsyncMock()
        backend.position_at_proof = AsyncMock(return_value=MagicMock(
            schema_version=1,
            session_id="",
            step_index=0,
            is_complete=False,
            focused_goal_index=0,
            goals=[],
        ))
        backend.shutdown = AsyncMock()
        backend.original_script = []
        backend.execute_vernacular = AsyncMock(return_value="some output")

        mgr = SessionManager(backend_factory=AsyncMock(return_value=backend))
        sid, _ = await mgr.create_session("/file.v", "proof1")

        result = await mgr.send_command(sid, "Check nat.")

        backend.execute_vernacular.assert_called_once()
        assert result == "some output"

    @pytest.mark.asyncio
    async def test_coqtop_proc_reused_on_second_call(self):
        """Once coqtop is spawned, subsequent submit_vernacular calls reuse it."""
        from Poule.session.manager import SessionManager

        backend = MagicMock()
        backend.load_file = AsyncMock()
        backend.position_at_proof = AsyncMock(return_value=MagicMock(
            schema_version=1,
            session_id="",
            step_index=0,
            is_complete=False,
            focused_goal_index=0,
            goals=[],
        ))
        backend.shutdown = AsyncMock()
        backend.original_script = []

        mgr = SessionManager(backend_factory=AsyncMock(return_value=backend))
        sid, _ = await mgr.create_session("/file.v", "proof1")

        # Pre-set a coqtop_proc
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdin.write = MagicMock()
        fake_proc.stdin.drain = AsyncMock()
        ss = mgr._registry[sid]
        ss.coqtop_proc = fake_proc

        with patch.object(mgr, '_ensure_coqtop', new_callable=AsyncMock) as mock_ensure:
            with patch.object(mgr, '_read_until_sentinel', new_callable=AsyncMock, return_value="output"):
                await mgr.submit_vernacular(sid, "Check nat.")

        mock_ensure.assert_not_called()
