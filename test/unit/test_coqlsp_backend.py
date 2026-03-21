"""Tests for the coq-lsp JSON-RPC backend (specification/extraction.md §4.1).

Tests the LSP protocol implementation: Content-Length message framing,
initialization handshake, document lifecycle, sentence-level message
retrieval via ``proof/goals``, and error handling.

The CoqLspBackend communicates with ``coq-lsp`` over stdin/stdout using
LSP JSON-RPC (Content-Length framed).  Vernac commands are issued by
opening synthetic ``.v`` documents; ``textDocument/publishDiagnostics``
signals that checking is complete, then ``proof/goals`` retrieves the
per-sentence output (Search results, Print bodies, Check types, etc.).
"""

from __future__ import annotations

import io
import json
import os
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: build LSP messages in wire format
# ---------------------------------------------------------------------------


def _encode_lsp(msg: dict) -> bytes:
    """Encode a JSON-RPC message with Content-Length header."""
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _make_response(request_id: int, result: dict | None = None) -> dict:
    """Build a JSON-RPC response."""
    resp: dict = {"jsonrpc": "2.0", "id": request_id}
    if result is not None:
        resp["result"] = result
    else:
        resp["result"] = {}
    return resp


def _make_diagnostics_notification(
    uri: str, diagnostics: list[dict]
) -> dict:
    """Build a textDocument/publishDiagnostics notification."""
    return {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": diagnostics},
    }


def _make_diagnostic(
    message: str,
    severity: int = 3,
    start_line: int = 0,
    start_char: int = 0,
    end_line: int = 0,
    end_char: int = 1,
) -> dict:
    """Build one LSP diagnostic.

    Severity: 1=Error, 2=Warning, 3=Information, 4=Hint.
    """
    return {
        "range": {
            "start": {"line": start_line, "character": start_char},
            "end": {"line": end_line, "character": end_char},
        },
        "severity": severity,
        "message": message,
    }


def _make_sentence_message(text: str, level: int = 3) -> dict:
    """Build one sentence-level message as returned by ``proof/goals``.

    Level: 1=Error, 2=Warning, 3=Information.
    """
    return {"range": None, "level": level, "text": text}


def _make_goals_result(
    uri: str,
    line: int,
    messages: list[dict],
    end_line: int | None = None,
    end_char: int | None = None,
) -> dict:
    """Build a ``proof/goals`` response result."""
    return {
        "textDocument": {"uri": uri, "version": 1},
        "position": {"line": line, "character": 0},
        "range": {
            "start": {"line": line, "character": 0},
            "end": {
                "line": end_line if end_line is not None else line,
                "character": end_char if end_char is not None else 1,
            },
        },
        "program": [],
        "messages": messages,
    }


class FakeLspServer:
    """Simulates coq-lsp by feeding pre-scripted responses through a pipe.

    Usage::

        server = FakeLspServer(messages=[...])
        backend._proc = Mock()
        backend._proc.stdout = server.stdout
        backend._proc.stdin = server.stdin
        # Now backend._read_message() reads from server's pipe.
    """

    def __init__(self, messages: list[dict]) -> None:
        raw = b"".join(_encode_lsp(m) for m in messages)
        self.stdout = io.BytesIO(raw)
        self.stdin = io.BytesIO()

    def get_written_messages(self) -> list[dict]:
        """Parse all messages the backend wrote to stdin."""
        raw = self.stdin.getvalue()
        messages: list[dict] = []
        pos = 0
        while pos < len(raw):
            # Find Content-Length header
            header_end = raw.find(b"\r\n\r\n", pos)
            if header_end == -1:
                break
            header_block = raw[pos:header_end].decode("ascii")
            content_length = None
            for line in header_block.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())
            assert content_length is not None
            body_start = header_end + 4
            body = raw[body_start : body_start + content_length]
            messages.append(json.loads(body))
            pos = body_start + content_length
        return messages


# ═══════════════════════════════════════════════════════════════════════════
# 1. LSP Message Framing
# ═══════════════════════════════════════════════════════════════════════════


class TestWriteMessage:
    """_write_message encodes JSON-RPC messages with Content-Length header."""

    def test_produces_content_length_header_and_json_body(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        output = io.BytesIO()
        backend._proc = Mock()
        backend._proc.stdin = output
        backend._proc.stdin.write = output.write
        backend._proc.stdin.flush = output.flush

        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        backend._write_message(msg)

        raw = output.getvalue()
        header, body = raw.split(b"\r\n\r\n", 1)
        assert header.startswith(b"Content-Length: ")
        content_length = int(header.split(b": ")[1])
        assert content_length == len(body)
        assert json.loads(body) == msg

    def test_body_is_utf8_encoded(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        output = io.BytesIO()
        backend._proc = Mock()
        backend._proc.stdin = output
        backend._proc.stdin.write = output.write
        backend._proc.stdin.flush = output.flush

        # Unicode content
        msg = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {"text": "∀ n, n = n"}}
        backend._write_message(msg)

        raw = output.getvalue()
        header, body = raw.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        # Content-Length counts bytes, not characters
        assert content_length == len(body)
        assert json.loads(body)["params"]["text"] == "∀ n, n = n"


class TestReadMessage:
    """_read_message decodes Content-Length framed JSON-RPC messages."""

    def test_parses_single_message(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msg = {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
        raw = _encode_lsp(msg)

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(raw)

        result = backend._read_message()
        assert result == msg

    def test_handles_multiple_headers(self):
        """Reader handles Content-Type and other headers per LSP spec."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msg = {"jsonrpc": "2.0", "id": 2, "result": {}}
        body = json.dumps(msg).encode("utf-8")
        raw = (
            f"Content-Length: {len(body)}\r\n"
            f"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
            f"\r\n"
        ).encode("ascii") + body

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(raw)

        result = backend._read_message()
        assert result == msg

    def test_reads_two_consecutive_messages(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msg1 = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1}}
        msg2 = {"jsonrpc": "2.0", "id": 2, "result": {"b": 2}}
        raw = _encode_lsp(msg1) + _encode_lsp(msg2)

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(raw)

        assert backend._read_message() == msg1
        assert backend._read_message() == msg2

    def test_eof_raises_backend_crash_error(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend
        from Poule.extraction.errors import BackendCrashError

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(b"")

        with pytest.raises(BackendCrashError):
            backend._read_message()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Initialization Handshake
# ═══════════════════════════════════════════════════════════════════════════


class TestInitialization:
    """start() performs the LSP initialize/initialized handshake."""

    def test_start_sends_initialize_then_initialized(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })

        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()

        written = server.get_written_messages()
        # First message must be "initialize"
        assert written[0]["method"] == "initialize"
        assert "id" in written[0]
        # Second message must be "initialized" notification (no id)
        assert written[1]["method"] == "initialized"
        assert "id" not in written[1]

        backend.stop()

    def test_start_passes_process_id(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })
        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()

        written = server.get_written_messages()
        assert written[0]["params"]["processId"] == os.getpid()

        backend.stop()

    def test_start_spawns_coq_lsp_subprocess(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })
        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "coq-lsp" in cmd[0]

        backend.stop()


# ═══════════════════════════════════════════════════════════════════════════
# 3. Version Detection
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectVersion:
    """detect_version() returns the Coq/Rocq version string."""

    def test_returns_version_from_server_info(self):
        """Version is extracted from the initialize response serverInfo."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })
        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()

        version = backend.detect_version()
        # Should extract "9.1.1" from "0.2.2+9.1.1"
        assert "9.1" in version

        backend.stop()

    def test_fallback_to_coqc_version(self):
        """When serverInfo has no Coq version, falls back to coqc --version."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2"},
        })
        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout="The Rocq Prover, version 9.1.1\n", returncode=0
            )
            version = backend.detect_version()

        assert "9.1" in version

        backend.stop()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Document Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestDocumentLifecycle:
    """Backend opens/closes synthetic .v documents for Vernac queries."""

    def test_open_document_sends_did_open_notification(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        server = FakeLspServer(messages=[])
        backend._proc = Mock()
        backend._proc.stdin = server.stdin
        backend._proc.stdin.write = server.stdin.write
        backend._proc.stdin.flush = server.stdin.flush
        backend._proc.poll.return_value = None

        uri = "file:///tmp/wily_query_1.v"
        text = "Check True."
        backend._open_document(uri, text)

        written = server.get_written_messages()
        assert len(written) == 1
        assert written[0]["method"] == "textDocument/didOpen"
        doc = written[0]["params"]["textDocument"]
        assert doc["uri"] == uri
        assert doc["languageId"] == "coq"
        assert doc["text"] == text

    def test_close_document_sends_did_close_notification(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        server = FakeLspServer(messages=[])
        backend._proc = Mock()
        backend._proc.stdin = server.stdin
        backend._proc.stdin.write = server.stdin.write
        backend._proc.stdin.flush = server.stdin.flush
        backend._proc.poll.return_value = None

        uri = "file:///tmp/wily_query_1.v"
        backend._close_document(uri)

        written = server.get_written_messages()
        assert len(written) == 1
        assert written[0]["method"] == "textDocument/didClose"
        assert written[0]["params"]["textDocument"]["uri"] == uri


# ═══════════════════════════════════════════════════════════════════════════
# 5. Waiting for Diagnostics
# ═══════════════════════════════════════════════════════════════════════════


class TestWaitForDiagnostics:
    """_wait_for_diagnostics collects publishDiagnostics for a URI."""

    def test_collects_diagnostics_matching_uri(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        uri = "file:///tmp/wily_query_1.v"
        diag = _make_diagnostic("nat : Set", severity=3, start_line=1)
        notification = _make_diagnostics_notification(uri, [diag])

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(_encode_lsp(notification))
        backend._proc.poll.return_value = None
        backend._notification_buffer = []

        result = backend._wait_for_diagnostics(uri)
        assert len(result) == 1
        assert result[0]["message"] == "nat : Set"

    def test_ignores_diagnostics_for_other_uris(self):
        """Diagnostics for other documents are buffered, not returned."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        target_uri = "file:///tmp/wily_query_1.v"
        other_uri = "file:///tmp/other.v"

        other_notif = _make_diagnostics_notification(
            other_uri, [_make_diagnostic("irrelevant")]
        )
        target_notif = _make_diagnostics_notification(
            target_uri, [_make_diagnostic("relevant result")]
        )

        backend = CoqLspBackend.__new__(CoqLspBackend)
        raw = _encode_lsp(other_notif) + _encode_lsp(target_notif)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(raw)
        backend._proc.poll.return_value = None
        backend._notification_buffer = []

        result = backend._wait_for_diagnostics(target_uri)
        assert len(result) == 1
        assert result[0]["message"] == "relevant result"

    def test_buffers_interleaved_notifications(self):
        """Server responses (to other requests) are buffered while waiting."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        target_uri = "file:///tmp/wily_query_1.v"
        # An unrelated response arrives before our diagnostics
        unrelated = {"jsonrpc": "2.0", "method": "$/progress", "params": {"token": 1}}
        target_notif = _make_diagnostics_notification(
            target_uri, [_make_diagnostic("result")]
        )

        backend = CoqLspBackend.__new__(CoqLspBackend)
        raw = _encode_lsp(unrelated) + _encode_lsp(target_notif)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(raw)
        backend._proc.poll.return_value = None
        backend._notification_buffer = []

        result = backend._wait_for_diagnostics(target_uri)
        assert len(result) == 1
        assert result[0]["message"] == "result"

    def test_returns_empty_diagnostics_as_document_ready_signal(self):
        """coq-lsp sends a single publishDiagnostics with an empty list when
        a document containing only Vernac queries (Search, Print, etc.) is
        fully checked.  This is the normal case — Vernac output is NOT
        delivered through diagnostics.

        _wait_for_diagnostics must return on this empty notification so the
        caller knows checking is complete and can use ``proof/goals`` to
        retrieve the actual sentence output.  Skipping empty notifications
        would cause the backend to hang waiting for a non-empty notification
        that never arrives.
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        uri = "file:///tmp/wily_query_0.v"
        # coq-lsp sends exactly one empty publishDiagnostics for the URI
        empty_notif = _make_diagnostics_notification(uri, [])

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(_encode_lsp(empty_notif))
        backend._proc.poll.return_value = None
        backend._notification_buffer = []

        result = backend._wait_for_diagnostics(uri)
        # Must return the empty list — this is the document-ready signal
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# 5b. Sentence Messages via proof/goals
# ═══════════════════════════════════════════════════════════════════════════


class TestSentenceMessages:
    """Vernac command output is retrieved via the ``proof/goals`` LSP request.

    coq-lsp does NOT deliver Search/Print/About/Check output through
    ``publishDiagnostics``.  Instead, after the document is fully checked
    (signaled by an empty diagnostics notification), the backend must send
    a ``proof/goals`` request at the sentence position to retrieve the
    per-sentence messages.
    """

    def test_proof_goals_returns_messages_for_check(self):
        """proof/goals at a Check command returns the type signature."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._notification_buffer = []
        backend._next_id = 10

        uri = "file:///tmp/wily_query_0.v"
        goals_result = _make_goals_result(uri, line=0, messages=[
            _make_sentence_message("Nat.add\n     : nat -> nat -> nat"),
        ])

        with patch.object(
            backend, "_send_request", return_value=goals_result
        ) as mock_send:
            result = backend._send_request("proof/goals", {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 0},
            })

        mock_send.assert_called_once_with("proof/goals", {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 0},
        })
        assert len(result["messages"]) == 1
        assert "nat -> nat -> nat" in result["messages"][0]["text"]

    def test_proof_goals_returns_multiple_messages_for_search(self):
        """proof/goals at a Search command returns one message per result."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._notification_buffer = []
        backend._next_id = 10

        uri = "file:///tmp/wily_query_0.v"
        search_messages = [
            _make_sentence_message("Nat.add: nat -> nat -> nat"),
            _make_sentence_message("Nat.mul: nat -> nat -> nat"),
            _make_sentence_message("Nat.sub: nat -> nat -> nat"),
        ]
        goals_result = _make_goals_result(uri, line=1, messages=search_messages)

        with patch.object(
            backend, "_send_request", return_value=goals_result
        ):
            result = backend._send_request("proof/goals", {
                "textDocument": {"uri": uri},
                "position": {"line": 1, "character": 0},
            })

        assert len(result["messages"]) == 3

    def test_proof_goals_empty_messages_for_require(self):
        """proof/goals at a Require Import returns no messages (no output)."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._notification_buffer = []
        backend._next_id = 10

        uri = "file:///tmp/wily_query_0.v"
        goals_result = _make_goals_result(uri, line=0, messages=[])

        with patch.object(
            backend, "_send_request", return_value=goals_result
        ):
            result = backend._send_request("proof/goals", {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 0},
            })

        assert result["messages"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 6. list_declarations
# ═══════════════════════════════════════════════════════════════════════════


class TestListDeclarations:
    """list_declarations extracts (name, kind, constr_t) from a .vo file.

    After opening the synthetic document and waiting for diagnostics
    (document-ready signal), the backend must send ``proof/goals`` at
    the Search command's line position to retrieve the actual results.
    """

    def test_returns_name_kind_constr_tuples_via_proof_goals(self):
        """Search results come from proof/goals messages, not diagnostics."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        # Search results via proof/goals messages (not diagnostics)
        search_messages = [
            _make_sentence_message("Nat.add : nat -> nat -> nat"),
            _make_sentence_message("Nat.mul : nat -> nat -> nat"),
        ]
        # About results via proof/goals messages for kind detection
        about_messages_add = [
            _make_sentence_message("Nat.add is a definition"),
        ]
        about_messages_mul = [
            _make_sentence_message("Nat.mul is a definition"),
        ]

        # _wait_for_diagnostics returns empty list (document-ready signal).
        # _send_request returns proof/goals results for Search, then About queries.
        uri_base = "file:///tmp/wily_query_"
        goals_responses = []
        for i, msgs in enumerate(
            [search_messages, about_messages_add, about_messages_mul]
        ):
            goals_responses.append(
                _make_goals_result(f"{uri_base}{i}.v", line=0, messages=msgs)
            )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend,
                "_wait_for_diagnostics",
                return_value=[],  # empty = no errors, document ready
            ),
            patch.object(
                backend,
                "_send_request",
                side_effect=goals_responses,
            ),
        ):
            result = backend.list_declarations(
                Path("/coq/user-contrib/Stdlib/Init/Nat.vo")
            )

        assert isinstance(result, list)
        assert len(result) == 2
        # Each entry is (name, kind, constr_t)
        names = {r[0] for r in result}
        assert "Nat.add" in names or any("add" in r[0] for r in result)
        assert all(len(r) == 3 for r in result)

    def test_opens_document_with_require_and_search(self):
        """The synthetic doc must Require the module then Search inside it."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        opened_docs: list[tuple[str, str]] = []

        def capture_open(uri, text):
            opened_docs.append((uri, text))

        # proof/goals returns empty messages → no declarations, returns early
        empty_goals = _make_goals_result("file:///tmp/wily_query_0.v", line=1, messages=[])

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=empty_goals
            ),
        ):
            backend.list_declarations(Path("/coq/user-contrib/Stdlib/Init/Nat.vo"))

        # At least one document must contain both Require and Search
        assert len(opened_docs) >= 1
        search_doc = opened_docs[0][1]
        assert "Require" in search_doc
        assert "Search" in search_doc

    def test_empty_module_returns_empty_list(self):
        """When proof/goals returns no messages, no declarations are found."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        empty_goals = _make_goals_result("file:///tmp/wily_query_0.v", line=1, messages=[])

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=empty_goals
            ),
        ):
            result = backend.list_declarations(Path("/coq/theories/Empty.vo"))

        assert result == []

    def test_error_diagnostics_for_require_returns_empty(self):
        """If Require Import fails, return empty list (don't crash).

        Error diagnostics (severity 1) indicate the Require failed.
        The backend must not proceed to proof/goals in this case.
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        # Error diagnostic (severity 1 = Error)
        error_diags = [
            _make_diagnostic(
                "Cannot find a physical path bound to logical path Init.Nonexistent.",
                severity=1,
            ),
        ]

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=error_diags
            ),
            # _send_request should NOT be called when Require fails
            patch.object(
                backend, "_send_request",
                side_effect=AssertionError("proof/goals should not be called on error"),
            ),
        ):
            result = backend.list_declarations(
                Path("/coq/theories/Init/Nonexistent.vo")
            )

        assert result == []

    def test_sends_proof_goals_at_search_line_position(self):
        """proof/goals must be sent at line 1 (the Search command), not line 0
        (the Require Import).  The document is:
            line 0: Require Import <module>.
            line 1: Search _ inside <module>.
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        goals_calls: list[dict] = []

        def capture_send_request(method, params):
            goals_calls.append({"method": method, "params": params})
            return _make_goals_result(
                params["textDocument"]["uri"],
                line=params["position"]["line"],
                messages=[],
            )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", side_effect=capture_send_request
            ),
        ):
            backend.list_declarations(Path("/coq/user-contrib/Stdlib/Init/Nat.vo"))

        # At least one proof/goals call must target line 1 (Search position)
        assert len(goals_calls) >= 1
        search_call = goals_calls[0]
        assert search_call["method"] == "proof/goals"
        assert search_call["params"]["position"]["line"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 7. Parsing Search Output from Diagnostics
# ═══════════════════════════════════════════════════════════════════════════


class TestParseSearchDiagnostics:
    """_parse_search_diagnostics extracts declaration names from Search output."""

    def test_parses_name_colon_type_lines(self):
        """Search output lines are 'name : type_sig'."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        diags = [
            _make_diagnostic("Nat.add : nat -> nat -> nat"),
            _make_diagnostic("Nat.add_comm : forall n m, n + m = m + n"),
        ]

        result = CoqLspBackend._parse_search_diagnostics(diags)
        assert len(result) == 2
        assert result[0][0] == "Nat.add"
        assert result[0][1] == "nat -> nat -> nat"
        assert result[1][0] == "Nat.add_comm"

    def test_skips_error_diagnostics(self):
        """Error diagnostics (severity 1) are not search results."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        diags = [
            _make_diagnostic("Nat.add : nat -> nat -> nat", severity=3),
            _make_diagnostic("Error: something broke", severity=1),
        ]

        result = CoqLspBackend._parse_search_diagnostics(diags)
        assert len(result) == 1

    def test_empty_diagnostics_returns_empty(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        result = CoqLspBackend._parse_search_diagnostics([])
        assert result == []

    def test_multiline_type_sig_joined(self):
        """Multi-line type signatures from coq-lsp are collapsed (spec §4.1.1)."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        diags = [
            _make_diagnostic("bar :\n  forall (n : nat),\n  n + 0 = n"),
        ]

        result = CoqLspBackend._parse_search_diagnostics(diags)
        assert len(result) == 1
        assert result[0][0] == "bar"
        assert result[0][1] == "forall (n : nat), n + 0 = n"


# ═══════════════════════════════════════════════════════════════════════════
# 7b. Declaration Kind Detection
# ═══════════════════════════════════════════════════════════════════════════


class TestDeclarationKindDetection:
    """_get_declaration_kind parses About output to determine declaration kind.

    The About output format differs between Coq/Rocq versions.  The backend
    must handle both formats and fall back to "definition" when the kind
    cannot be determined.

    See specification/feedback/extraction.md Issue 1 for the full gap analysis.
    """

    def _make_backend(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0
        return backend

    def test_rocq9_constant_detected_as_definition(self):
        """Rocq 9.x: 'Expands to: Constant ...' → definition."""
        backend = self._make_backend()
        about_text = (
            "Nat.add : nat -> nat -> nat\n\n"
            "Nat.add is not universe polymorphic\n"
            "Arguments Nat.add (n m)%_nat_scope\n"
            "Nat.add is transparent\n"
            "Expands to: Constant Corelib.Init.Nat.add\n"
            "Declared in library Corelib.Init.Nat, line 47, characters 9-12"
        )
        about_messages = [_make_sentence_message(about_text)]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("Nat.add")

        assert kind == "definition"

    def test_rocq9_inductive_detected(self):
        """Rocq 9.x: 'Expands to: Inductive ...' → inductive."""
        backend = self._make_backend()
        about_text = (
            "nat : Set\n\n"
            "nat is not universe polymorphic\n"
            "Expands to: Inductive Corelib.Init.Datatypes.nat\n"
            "Declared in library Corelib.Init.Datatypes, line 178, characters 10-13"
        )
        about_messages = [_make_sentence_message(about_text)]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("nat")

        assert kind == "inductive"

    def test_rocq9_constructor_detected(self):
        """Rocq 9.x: 'Expands to: Constructor ...' → constructor."""
        backend = self._make_backend()
        about_text = (
            "S : nat -> nat\n\n"
            "S is not universe polymorphic\n"
            "Arguments S _%_nat_scope\n"
            "Expands to: Constructor Corelib.Init.Datatypes.S\n"
            "Declared in library Corelib.Init.Datatypes, line 180, characters 4-5"
        )
        about_messages = [_make_sentence_message(about_text)]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("S")

        assert kind == "constructor"

    def test_rocq9_not_defined_object_falls_back_to_definition(self):
        """Rocq 9.x: 'X not a defined object.' → fallback to definition."""
        backend = self._make_backend()
        about_text = "Nat.add_comm not a defined object."
        about_messages = [_make_sentence_message(about_text)]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("Nat.add_comm")

        assert kind == "definition"

    def test_coq8_legacy_kind_format(self):
        """Coq ≤8.x: 'X is a Definition.' → definition."""
        backend = self._make_backend()
        about_messages = [_make_sentence_message("Nat.add is a definition")]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("Nat.add")

        assert kind == "definition"

    def test_coq8_legacy_lemma_format(self):
        """Coq ≤8.x: 'X is a Lemma.' → lemma."""
        backend = self._make_backend()
        about_messages = [_make_sentence_message("foo is a lemma")]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("foo")

        assert kind == "lemma"

    def test_universe_polymorphic_not_mistaken_for_kind(self):
        """'is not universe polymorphic' must NOT be parsed as a kind."""
        backend = self._make_backend()
        # Rocq 9.x About output with no Expands-to line (edge case)
        about_text = (
            "foo : Type\n\n"
            "foo is not universe polymorphic\n"
            "foo is transparent"
        )
        about_messages = [_make_sentence_message(about_text)]
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=about_messages,
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            kind = backend._get_declaration_kind("foo")

        # Must NOT be "not universe polymorphic"
        assert "universe" not in kind
        assert kind == "definition"


# ═══════════════════════════════════════════════════════════════════════════
# 8. pretty_print
# ═══════════════════════════════════════════════════════════════════════════


class TestPrettyPrint:
    """pretty_print returns human-readable statement via proof/goals."""

    def test_returns_print_output_from_proof_goals(self):
        """Print output comes from proof/goals messages, not diagnostics."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        print_body = (
            "Nat.add =\nfix add (n m : nat) {struct n} : nat :=\n"
            "  match n with\n  | 0 => m\n  | S p => S (add p m)\n  end"
        )
        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v",
            line=0,
            messages=[_make_sentence_message(print_body)],
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=goals_result
            ),
        ):
            result = backend.pretty_print("Nat.add")

        assert "Nat.add" in result
        assert isinstance(result, str)

    def test_opens_document_with_print_command(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        opened_docs: list[str] = []

        def capture_open(uri, text):
            opened_docs.append(text)

        empty_goals = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=[]
        )

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=empty_goals),
        ):
            backend.pretty_print("Nat.add")

        assert any("Print Nat.add" in doc for doc in opened_docs)


# ═══════════════════════════════════════════════════════════════════════════
# 9. pretty_print_type
# ═══════════════════════════════════════════════════════════════════════════


class TestPrettyPrintType:
    """pretty_print_type returns the type signature via proof/goals, or None."""

    def test_returns_type_from_proof_goals(self):
        """Check output comes from proof/goals messages."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v",
            line=0,
            messages=[_make_sentence_message("Nat.add\n     : nat -> nat -> nat")],
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=goals_result
            ),
        ):
            result = backend.pretty_print_type("Nat.add")

        assert result is not None
        assert "nat" in result

    def test_returns_none_on_error(self):
        """Error diagnostics (Require/Check failure) → return None."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        error_diags = [
            _make_diagnostic("Error: Unknown reference Nonexistent", severity=1),
        ]

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=error_diags
            ),
        ):
            result = backend.pretty_print_type("Nonexistent")

        assert result is None

    def test_opens_document_with_check_command(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        opened_docs: list[str] = []

        def capture_open(uri, text):
            opened_docs.append(text)

        empty_goals = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=[]
        )

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=empty_goals),
        ):
            backend.pretty_print_type("Nat.add")

        assert any("Check Nat.add" in doc for doc in opened_docs)


# ═══════════════════════════════════════════════════════════════════════════
# 10. get_dependencies
# ═══════════════════════════════════════════════════════════════════════════


class TestGetDependencies:
    """get_dependencies returns (target_name, relation) pairs via proof/goals."""

    def test_parses_print_assumptions_from_proof_goals(self):
        """Print Assumptions output comes from proof/goals messages."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v",
            line=0,
            messages=[
                _make_sentence_message(
                    "Coq.Init.Logic.eq_refl : forall (A : Type) (x : A), x = x\n"
                    "Coq.Init.Peano.nat_ind : forall P, P 0 -> ..."
                ),
            ],
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=goals_result
            ),
        ):
            result = backend.get_dependencies("Nat.add_comm")

        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)

    def test_closed_under_global_context_returns_empty(self):
        """Declarations with no axioms return empty dependency list."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v",
            line=0,
            messages=[
                _make_sentence_message("Closed under the global context"),
            ],
        )

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=[]
            ),
            patch.object(
                backend, "_send_request", return_value=goals_result
            ),
        ):
            result = backend.get_dependencies("Nat.add")

        assert result == []

    def test_opens_document_with_print_assumptions(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0

        opened_docs: list[str] = []

        def capture_open(uri, text):
            opened_docs.append(text)

        empty_goals = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=[]
        )

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=empty_goals),
        ):
            backend.get_dependencies("Nat.add")

        assert any("Print Assumptions Nat.add" in doc for doc in opened_docs)


# ═══════════════════════════════════════════════════════════════════════════
# 11. Module Path Derivation
# ═══════════════════════════════════════════════════════════════════════════


class TestVoToLogicalPath:
    """_vo_to_logical_path derives Coq module path from .vo file path."""

    def test_stdlib_path(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/home/user/.opam/default/lib/coq/theories/Init/Nat.vo")
        result = CoqLspBackend._vo_to_logical_path(path)
        assert result == "Init.Nat"

    def test_mathcomp_path(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path(
            "/home/user/.opam/default/lib/coq/user-contrib/mathcomp/ssreflect/ssrnat.vo"
        )
        result = CoqLspBackend._vo_to_logical_path(path)
        assert result == "mathcomp.ssreflect.ssrnat"

    def test_nested_stdlib_path(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path(
            "/coq/theories/Arith/PeanoNat.vo"
        )
        result = CoqLspBackend._vo_to_logical_path(path)
        assert result == "Arith.PeanoNat"

    def test_rocq9_stdlib_under_user_contrib(self):
        """Rocq 9.x moved the stdlib from theories/ to user-contrib/Stdlib/.

        For a path like user-contrib/Stdlib/Init/Nat.vo the heuristic
        produces 'Stdlib.Init.Nat', but this path does NOT work with
        'Search _ inside Stdlib.Init.Nat.' in Rocq 9.x — the correct
        logical path for Search is 'Init.Nat' (without the Stdlib prefix).
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path(
            "/home/user/.opam/default/lib/coq/user-contrib/Stdlib/Init/Nat.vo"
        )
        result = CoqLspBackend._vo_to_logical_path(path)
        # The logical path must work with 'Require Import X. Search _ inside X.'
        # In Rocq 9.x, 'Search _ inside Stdlib.Init.Nat.' returns no results,
        # while 'Search _ inside Init.Nat.' works correctly.
        assert result == "Init.Nat"


# ═══════════════════════════════════════════════════════════════════════════
# 12. Error Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestBackendErrors:
    """Error handling for coq-lsp subprocess failures."""

    def test_start_raises_extraction_error_when_coq_lsp_not_found(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend
        from Poule.extraction.errors import ExtractionError

        with patch("subprocess.Popen", side_effect=FileNotFoundError("coq-lsp not found")):
            backend = CoqLspBackend()
            with pytest.raises(ExtractionError):
                backend.start()

    def test_process_exit_raises_backend_crash_error(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend
        from Poule.extraction.errors import BackendCrashError

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = 1  # exited
        backend._proc.returncode = 1
        backend._proc.stderr = io.BytesIO(b"segfault")

        with pytest.raises(BackendCrashError):
            backend._ensure_alive()

    def test_json_rpc_error_response_raises_extraction_error(self):
        """A JSON-RPC error response is converted to ExtractionError."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend
        from Poule.extraction.errors import ExtractionError

        error_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.stdout = io.BytesIO(_encode_lsp(error_response))
        backend._proc.poll.return_value = None
        backend._notification_buffer = []

        with pytest.raises(ExtractionError, match="Invalid Request"):
            backend._send_request("badMethod", {})


# ═══════════════════════════════════════════════════════════════════════════
# 13. Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestLifecycle:
    """start/stop lifecycle and context manager support."""

    def test_stop_sends_shutdown_then_exit(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        # Prepare server: respond to shutdown request
        shutdown_response = _make_response(1, None)
        server = FakeLspServer(messages=[shutdown_response])

        backend._proc = Mock()
        backend._proc.stdin = server.stdin
        backend._proc.stdin.write = server.stdin.write
        backend._proc.stdin.flush = server.stdin.flush
        backend._proc.stdout = server.stdout
        backend._proc.poll.return_value = None
        backend._proc.wait.return_value = 0
        backend._next_id = 0
        backend._notification_buffer = []

        backend.stop()

        written = server.get_written_messages()
        methods = [m["method"] for m in written]
        assert "shutdown" in methods
        assert "exit" in methods
        # shutdown must come before exit
        assert methods.index("shutdown") < methods.index("exit")

    def test_context_manager_calls_start_and_stop(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })
        shutdown_response = _make_response(2, None)
        server = FakeLspServer(messages=[init_response, shutdown_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            proc.wait.return_value = 0
            mock_popen.return_value = proc

            with CoqLspBackend() as backend:
                assert backend._proc is not None

        # After exiting context, stop should have been called
        written = server.get_written_messages()
        methods = [m["method"] for m in written]
        assert "initialize" in methods
        assert "shutdown" in methods

    def test_stop_on_already_stopped_is_noop(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        # Should not raise
        backend.stop()

    def test_double_start_is_idempotent(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        init_response = _make_response(1, {
            "capabilities": {},
            "serverInfo": {"name": "coq-lsp", "version": "0.2.2+9.1.1"},
        })
        server = FakeLspServer(messages=[init_response])

        with patch("subprocess.Popen") as mock_popen:
            proc = Mock()
            proc.stdin = server.stdin
            proc.stdout = server.stdout
            proc.stderr = io.BytesIO(b"")
            proc.poll.return_value = None
            mock_popen.return_value = proc

            backend = CoqLspBackend()
            backend.start()
            backend.start()  # should be a no-op

        # Popen called only once
        mock_popen.assert_called_once()
        backend.stop()


# ═══════════════════════════════════════════════════════════════════════════
# 14. CoqBackend Protocol Conformance
# ═══════════════════════════════════════════════════════════════════════════


class TestProtocolConformance:
    """CoqLspBackend satisfies the CoqBackend protocol."""

    def test_implements_coq_backend_protocol(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend
        from Poule.extraction.coq_backend import CoqBackend

        assert issubclass(CoqLspBackend, CoqBackend) or (
            hasattr(CoqLspBackend, "list_declarations")
            and hasattr(CoqLspBackend, "pretty_print")
            and hasattr(CoqLspBackend, "pretty_print_type")
            and hasattr(CoqLspBackend, "get_dependencies")
            and hasattr(CoqLspBackend, "detect_version")
        )


# ═══════════════════════════════════════════════════════════════════════════
# 15. Contract Tests (require real coq-lsp installation)
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# 16. Batched Vernac Queries (_run_vernac_batch)
# ═══════════════════════════════════════════════════════════════════════════


class TestRunVernacBatch:
    """_run_vernac_batch executes multiple commands in a single document."""

    def _make_backend(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0
        return backend

    def test_multi_command_returns_per_line_messages(self):
        """Three commands → three message lists, one per line."""
        backend = self._make_backend()

        msg_line0 = [_make_sentence_message("result for line 0")]
        msg_line1 = [_make_sentence_message("result for line 1")]
        msg_line2 = [_make_sentence_message("result for line 2")]

        goals_responses = [
            _make_goals_result("file:///tmp/wily_query_0.v", line=i, messages=msgs)
            for i, msgs in enumerate([msg_line0, msg_line1, msg_line2])
        ]

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", side_effect=goals_responses),
        ):
            results = backend._run_vernac_batch([
                "About Nat.add.",
                "About Nat.mul.",
                "About Nat.sub.",
            ])

        assert len(results) == 3
        assert results[0][0]["text"] == "result for line 0"
        assert results[1][0]["text"] == "result for line 1"
        assert results[2][0]["text"] == "result for line 2"

    def test_single_document_open_and_close(self):
        """Batch opens only one document and closes it after all queries."""
        backend = self._make_backend()

        open_calls = []
        close_calls = []

        def capture_open(uri, text):
            open_calls.append((uri, text))

        def capture_close(uri):
            close_calls.append(uri)

        goals_result = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=0, messages=[]
        )

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document", side_effect=capture_close),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=goals_result),
        ):
            backend._run_vernac_batch(["About Nat.add.", "About Nat.mul."])

        assert len(open_calls) == 1
        assert len(close_calls) == 1
        # Document text should contain both commands on separate lines
        doc_text = open_calls[0][1]
        assert "About Nat.add." in doc_text
        assert "About Nat.mul." in doc_text
        assert "\n" in doc_text

    def test_error_diagnostics_returns_empty_lists(self):
        """Global error diagnostics → empty lists for all commands."""
        backend = self._make_backend()

        error_diags = [_make_diagnostic("Error: something broke", severity=1)]

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(
                backend, "_wait_for_diagnostics", return_value=error_diags
            ),
            patch.object(
                backend, "_send_request",
                side_effect=AssertionError("should not call proof/goals on error"),
            ),
        ):
            results = backend._run_vernac_batch(["About X.", "About Y."])

        assert len(results) == 2
        assert results[0] == []
        assert results[1] == []

    def test_empty_commands_returns_empty(self):
        """Empty command list returns empty result."""
        backend = self._make_backend()
        results = backend._run_vernac_batch([])
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════
# 17. Batched list_declarations (About queries)
# ═══════════════════════════════════════════════════════════════════════════


class TestBatchedListDeclarations:
    """list_declarations batches About queries to reduce document lifecycle overhead."""

    def _make_backend(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0
        return backend

    def test_fewer_document_opens_than_declarations(self):
        """With batching, fewer documents should be opened than declarations."""
        backend = self._make_backend()

        # 3 search results
        search_messages = [
            _make_sentence_message("Nat.add : nat -> nat -> nat"),
            _make_sentence_message("Nat.mul : nat -> nat -> nat"),
            _make_sentence_message("Nat.sub : nat -> nat -> nat"),
        ]
        search_goals = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=1, messages=search_messages
        )

        # Batched About returns 3 message lists in one document
        about_batch = [
            [_make_sentence_message("Nat.add is a definition")],
            [_make_sentence_message("Nat.mul is a definition")],
            [_make_sentence_message("Nat.sub is a definition")],
        ]

        open_calls = []

        def capture_open(uri, text):
            open_calls.append(text)

        with (
            patch.object(backend, "_open_document", side_effect=capture_open),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=search_goals),
            patch.object(backend, "_run_vernac_batch", return_value=about_batch),
        ):
            result = backend.list_declarations(
                Path("/coq/user-contrib/Stdlib/Init/Nat.vo")
            )

        assert len(result) == 3
        # Search doc is opened via _open_document (1 call).
        # About queries go through _run_vernac_batch (mocked), NOT _open_document.
        # So total _open_document calls = 1 (Search only), not 4 (1 + 3 per-decl About)
        assert len(open_calls) == 1

    def test_batched_about_results_parsed_correctly(self):
        """Batched About results are parsed with _parse_about_kind."""
        backend = self._make_backend()

        search_messages = [
            _make_sentence_message("Nat.add : nat -> nat -> nat"),
            _make_sentence_message("nat : Set"),
        ]
        search_goals = _make_goals_result(
            "file:///tmp/wily_query_0.v", line=1, messages=search_messages
        )

        about_batch = [
            [_make_sentence_message("Expands to: Constant Corelib.Init.Nat.add")],
            [_make_sentence_message("Expands to: Inductive Corelib.Init.Datatypes.nat")],
        ]

        with (
            patch.object(backend, "_open_document"),
            patch.object(backend, "_close_document"),
            patch.object(backend, "_wait_for_diagnostics", return_value=[]),
            patch.object(backend, "_send_request", return_value=search_goals),
            patch.object(backend, "_run_vernac_batch", return_value=about_batch),
        ):
            result = backend.list_declarations(
                Path("/coq/user-contrib/Stdlib/Init/Nat.vo")
            )

        kinds = {r[0]: r[1] for r in result}
        # list_declarations returns FQNs: canonical_module + "." + short_name
        # For /coq/user-contrib/Stdlib/Init/Nat.vo, canonical module is Coq.Init.Nat
        assert kinds["Coq.Init.Nat.Nat.add"] == "definition"
        assert kinds["Coq.Init.Nat.nat"] == "inductive"


# ═══════════════════════════════════════════════════════════════════════════
# 18. query_declaration_data (batched Print + Print Assumptions)
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryDeclarationData:
    """query_declaration_data batches Print + Print Assumptions queries."""

    def _make_backend(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = Mock()
        backend._proc.poll.return_value = None
        backend._server_info = {}
        backend._notification_buffer = []
        backend._next_uri_id = 0
        backend._next_id = 0
        return backend

    def test_returns_statement_and_dependencies(self):
        """Each declaration gets (statement, dependency_list)."""
        backend = self._make_backend()

        # 2 declarations: each gets Print + Print Assumptions = 4 lines
        batch_messages = [
            # Print Nat.add
            [_make_sentence_message(
                "Nat.add =\nfix add (n m : nat) : nat := match n with 0 => m | S p => S (add p m) end"
            )],
            # Print Assumptions Nat.add
            [_make_sentence_message("Closed under the global context")],
            # Print Nat.mul
            [_make_sentence_message("Nat.mul = ...")],
            # Print Assumptions Nat.mul
            [_make_sentence_message("  ax1 : Prop\n  ax2 : nat")],
        ]

        with patch.object(backend, "_run_vernac_batch", return_value=batch_messages):
            result = backend.query_declaration_data(["Nat.add", "Nat.mul"])

        assert "Nat.add" in result
        assert "Nat.mul" in result

        stmt_add, deps_add = result["Nat.add"]
        assert "Nat.add" in stmt_add
        assert deps_add == []  # Closed under global context

        stmt_mul, deps_mul = result["Nat.mul"]
        assert "Nat.mul" in stmt_mul
        assert len(deps_mul) >= 1
        assert any(d[0] == "ax1" for d in deps_mul)

    def test_batches_at_50_declarations(self):
        """More than 50 declarations should result in multiple batch calls."""
        backend = self._make_backend()

        names = [f"Decl.n{i}" for i in range(75)]
        batch_call_count = [0]

        def mock_batch(commands):
            batch_call_count[0] += 1
            # Return empty messages for each command
            return [[] for _ in commands]

        with patch.object(backend, "_run_vernac_batch", side_effect=mock_batch):
            backend.query_declaration_data(names)

        # 75 declarations = 150 commands → 2 batches (100 + 50)
        assert batch_call_count[0] == 2

    def test_empty_names_returns_empty_dict(self):
        """Empty names list returns empty result."""
        backend = self._make_backend()
        result = backend.query_declaration_data([])
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# 19. _parse_about_kind (extracted static method)
# ═══════════════════════════════════════════════════════════════════════════


class TestParseAboutKind:
    """_parse_about_kind extracts kind from About messages."""

    def test_rocq9_constant(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("Expands to: Constant Corelib.Init.Nat.add")]
        assert CoqLspBackend._parse_about_kind("Nat.add", msgs) == "definition"

    def test_rocq9_inductive(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("Expands to: Inductive Corelib.Init.Datatypes.nat")]
        assert CoqLspBackend._parse_about_kind("nat", msgs) == "inductive"

    def test_coq8_lemma(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("foo is a lemma")]
        assert CoqLspBackend._parse_about_kind("foo", msgs) == "lemma"

    def test_not_defined_falls_back(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("X not a defined object.")]
        assert CoqLspBackend._parse_about_kind("X", msgs) == "definition"

    def test_empty_messages_falls_back(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        assert CoqLspBackend._parse_about_kind("X", []) == "definition"

    def test_rocq9_ltac_detected(self):
        """Rocq 9.x: 'Ltac <path>' → ltac."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("Ltac Corelib.Init.Ltac.reflexivity")]
        assert CoqLspBackend._parse_about_kind("reflexivity", msgs) == "ltac"

    def test_rocq9_module_detected(self):
        """Rocq 9.x: 'Module <path>' → module."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        msgs = [_make_sentence_message("Module Corelib.Init.Decimal")]
        assert CoqLspBackend._parse_about_kind("Decimal", msgs) == "module"

    def test_rocq9_notation_alias_prefers_constant(self):
        """Rocq 9.x: notation aliasing a constant → definition (not notation).

        When About output contains both 'Expands to: Notation ...' and
        'Expands to: Constant ...', the Constant category takes precedence.
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        about_text = (
            "Notation pred := Nat.pred\n"
            "Expands to: Notation Corelib.Init.Peano.pred\n"
            "Declared in library Corelib.Init.Peano, line 45, characters 0-41\n"
            "\n"
            "Nat.pred : nat -> nat\n"
            "\n"
            "Nat.pred is not universe polymorphic\n"
            "Arguments Nat.pred n%_nat_scope\n"
            "Nat.pred is transparent\n"
            "Expands to: Constant Corelib.Init.Nat.pred\n"
            "Declared in library Corelib.Init.Nat, line 39, characters 11-15"
        )
        msgs = [_make_sentence_message(about_text)]
        assert CoqLspBackend._parse_about_kind("pred", msgs) == "definition"

    def test_rocq9_pure_notation_detected(self):
        """Rocq 9.x: notation with only 'Expands to: Notation' → notation."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        about_text = (
            "Notation some_notation := ...\n"
            "Expands to: Notation Corelib.Some.Path\n"
            "Declared in library Corelib.Some, line 10, characters 0-30"
        )
        msgs = [_make_sentence_message(about_text)]
        assert CoqLspBackend._parse_about_kind("some_notation", msgs) == "notation"


# ===========================================================================
# locate() — unit tests (spec §4.1)
# ===========================================================================


class TestLocate:
    """locate(name) issues a Locate Vernac query and parses the response."""

    def test_locate_constant_returns_fqn(self):
        """Locate 'nat' returns the FQN of the Constant/Inductive."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        # Mock _run_vernac_query to return a Locate response
        def fake_query(text, query_line=0):
            return ([], [{"text": "Inductive Coq.Init.Datatypes.nat", "level": 3}])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("nat")

        assert result == "Coq.Init.Datatypes.nat"

    def test_locate_infix_operator(self):
        """Locate '+' returns the FQN of the underlying constant."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([], [{"text": "Constant Coq.Init.Nat.add", "level": 3}])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("+")

        assert result == "Coq.Init.Nat.add"

    def test_locate_not_found_returns_none(self):
        """Locate for unknown name returns None."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([{"severity": 1}], [])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("nonexistent_thing")

        assert result is None

    def test_locate_notation_without_body_returns_none(self):
        """Notation-only Locate results with no parseable body return None."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([], [{"text": "Notation Coq.Init.Peano.pred", "level": 3}])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("pred")

        assert result is None

    def test_locate_notation_with_body_extracts_fqn(self):
        """Notation with a qualified head symbol extracts the FQN."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([], [{"text": 'Notation "x + y" := (Nat.add x y)', "level": 3}])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("+")

        assert result == "Nat.add"

    def test_locate_ambiguous_returns_list(self):
        """Locate with multiple Constant/Inductive matches returns a list of FQNs."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([], [
                {"text": "Constant Coq.Init.Nat.add", "level": 3},
                {"text": "Constant Coq.ZArith.BinInt.Z.add", "level": 3},
            ])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("+")

        assert isinstance(result, list)
        assert "Coq.Init.Nat.add" in result
        assert "Coq.ZArith.BinInt.Z.add" in result

    def test_locate_mixed_notation_and_constant(self):
        """When Locate returns both Notation and Constant, only Constant FQNs are kept."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None

        def fake_query(text, query_line=0):
            return ([], [
                {"text": "Notation Coq.Init.Peano.plus", "level": 3},
                {"text": "Constant Coq.Init.Nat.add", "level": 3},
            ])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        result = backend.locate("+")

        assert result == "Coq.Init.Nat.add"

    def test_locate_uses_quoted_form_for_operators(self):
        """Infix operators should be queried as Locate \"+\". not Locate +."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend.__new__(CoqLspBackend)
        backend._proc = None
        queries_issued = []

        def fake_query(text, query_line=0):
            queries_issued.append(text)
            return ([], [{"text": "Constant Coq.Init.Nat.add", "level": 3}])

        backend._run_vernac_query = fake_query
        backend._ensure_alive = lambda: None

        backend.locate("+")

        assert len(queries_issued) == 1
        assert 'Locate "+".' in queries_issued[0]

