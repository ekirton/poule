"""CoqLspBackend — extraction backend using coq-lsp over LSP JSON-RPC.

Communicates with ``coq-lsp`` over stdin/stdout using the Language Server
Protocol (Content-Length framed JSON-RPC).  Vernac commands are issued by
opening synthetic ``.v`` documents; ``textDocument/publishDiagnostics``
signals that checking is complete, then ``proof/goals`` retrieves the
per-sentence output (Search results, Print bodies, Check types, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from wily_rooster.extraction.errors import BackendCrashError, ExtractionError

logger = logging.getLogger(__name__)

# Regex for parsing ``Search`` output lines.
# Each result looks like: ``name : type_signature``
_SEARCH_LINE_RE = re.compile(r"^(\S+)\s*:\s*(.+)$")

# Regex for parsing ``About`` output to extract the declaration kind.
# Coq ≤8.x: "Nat.add is a Definition."
_ABOUT_KIND_RE = re.compile(
    r"^(\S+)\s+is\s+(?:a\s+)?(.+?)(?:\.|$)", re.MULTILINE
)

# Rocq 9.x: "Expands to: Constant Corelib.Init.Nat.add"
_EXPANDS_TO_RE = re.compile(r"^Expands to:\s+(\w+)\s", re.MULTILINE)

# Map from Rocq 9.x "Expands to:" category to kind.
_EXPANDS_TO_KIND: dict[str, str] = {
    "constant": "definition",
    "inductive": "inductive",
    "constructor": "constructor",
}

# Regex for parsing ``Print Assumptions`` output.
_ASSUMPTION_RE = re.compile(r"^\s*(\S+)\s*:\s*(.+)$", re.MULTILINE)

# Regex for the coqc version string.
_VERSION_RE = re.compile(r"version\s+([\d.]+)")

# Kind normalization map for About output.
_KIND_MAP: dict[str, str] = {
    "lemma": "lemma",
    "theorem": "theorem",
    "definition": "definition",
    "inductive": "inductive",
    "record": "record",
    "class": "class",
    "constructor": "constructor",
    "instance": "instance",
    "axiom": "axiom",
    "parameter": "parameter",
    "conjecture": "conjecture",
    "coercion": "coercion",
    "canonical structure": "canonical structure",
    "notation": "notation",
    "abbreviation": "abbreviation",
    "section variable": "section variable",
}


class CoqLspBackend:
    """Extraction backend that communicates with ``coq-lsp`` via LSP JSON-RPC.

    Lifecycle
    ---------
    1. Call :meth:`start` to spawn ``coq-lsp`` and perform the LSP handshake.
    2. Use the query methods (:meth:`list_declarations`, etc.).
    3. Call :meth:`stop` to shut down the server gracefully.

    The class also works as a context manager::

        with CoqLspBackend() as backend:
            decls = backend.list_declarations(vo_path)
    """

    _next_id: int = 0
    _next_uri_id: int = 0

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._server_info: dict[str, Any] = {}
        self._notification_buffer: list[dict[str, Any]] = []
        self._next_id = 0
        self._next_uri_id = 0

    # ------------------------------------------------------------------
    # LSP message framing
    # ------------------------------------------------------------------

    def _write_message(self, msg: dict[str, Any]) -> None:
        """Encode and write a JSON-RPC message with Content-Length header."""
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)  # type: ignore[union-attr]
        self._proc.stdin.flush()  # type: ignore[union-attr]

    def _read_message(self) -> dict[str, Any]:
        """Read one Content-Length framed JSON-RPC message from stdout."""
        stdout = self._proc.stdout  # type: ignore[union-attr]
        headers: dict[str, str] = {}
        while True:
            line = stdout.readline()
            if not line:
                raise BackendCrashError(
                    "coq-lsp closed stdout unexpectedly (process may have crashed)"
                )
            line_str = line.decode("ascii").rstrip("\r\n")
            if not line_str:
                break
            if ":" in line_str:
                key, val = line_str.split(":", 1)
                headers[key.strip().lower()] = val.strip()

        if "content-length" not in headers:
            raise BackendCrashError(
                "Missing Content-Length header from coq-lsp"
            )

        content_length = int(headers["content-length"])
        body = stdout.read(content_length)
        return json.loads(body)

    # ------------------------------------------------------------------
    # JSON-RPC request/notification helpers
    # ------------------------------------------------------------------

    def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the matching response."""
        self._next_id += 1
        request_id = self._next_id
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._write_message(request)

        while True:
            msg = self._read_message()
            if "id" in msg and msg["id"] == request_id:
                if "error" in msg:
                    raise ExtractionError(msg["error"]["message"])
                return msg.get("result", {})
            # Buffer notifications and other messages
            self._notification_buffer.append(msg)

    def _send_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(notification)

    # ------------------------------------------------------------------
    # Document lifecycle
    # ------------------------------------------------------------------

    def _open_document(self, uri: str, text: str) -> None:
        """Send textDocument/didOpen notification."""
        self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "coq",
                    "version": 1,
                    "text": text,
                }
            },
        )

    def _close_document(self, uri: str) -> None:
        """Send textDocument/didClose notification."""
        self._send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}},
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _wait_for_diagnostics(self, uri: str) -> list[dict[str, Any]]:
        """Read messages until publishDiagnostics arrives for *uri*.

        coq-lsp sends exactly one ``publishDiagnostics`` per document.  For
        documents containing only Vernac queries (Search, Print, etc.) the
        diagnostics list is empty — this is the normal document-ready signal.
        The actual command output is retrieved via ``proof/goals`` afterwards.
        """
        # Check buffer first
        remaining: list[dict[str, Any]] = []
        for msg in self._notification_buffer:
            if (
                msg.get("method") == "textDocument/publishDiagnostics"
                and msg["params"]["uri"] == uri
            ):
                self._notification_buffer = remaining
                return msg["params"]["diagnostics"]
            remaining.append(msg)
        self._notification_buffer = remaining

        # Read from the wire
        while True:
            msg = self._read_message()
            if (
                msg.get("method") == "textDocument/publishDiagnostics"
                and msg["params"]["uri"] == uri
            ):
                return msg["params"]["diagnostics"]
            self._notification_buffer.append(msg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn ``coq-lsp`` and perform the LSP initialize handshake."""
        if self._proc is not None:
            return
        try:
            self._proc = subprocess.Popen(
                ["coq-lsp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ExtractionError(
                f"coq-lsp not found on PATH: {exc}"
            ) from exc

        # LSP initialize request
        result = self._send_request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": None,
                "capabilities": {},
            },
        )
        self._server_info = result.get("serverInfo", {})

        # LSP initialized notification
        self._send_notification("initialized", {})

    def stop(self) -> None:
        """Shut down ``coq-lsp`` with the LSP shutdown/exit sequence."""
        if self._proc is None:
            return
        try:
            self._send_request("shutdown", {})
            self._send_notification("exit", {})
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
            self._proc.wait(timeout=5)
        finally:
            self._proc = None

    def __enter__(self) -> CoqLspBackend:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_alive(self) -> None:
        """Raise if the subprocess is not running."""
        if self._proc is None:
            raise ExtractionError("CoqLspBackend has not been started")
        if self._proc.poll() is not None:
            exit_code = self._proc.returncode
            stderr = ""
            if self._proc.stderr:
                try:
                    raw = self._proc.stderr.read()
                    stderr = (
                        raw.decode("utf-8", errors="replace")
                        if isinstance(raw, bytes)
                        else raw
                    )
                except Exception:
                    pass
            self._proc = None
            raise BackendCrashError(
                f"coq-lsp exited unexpectedly (exit code {exit_code}). "
                f"stderr: {stderr!r}"
            )

    def _next_uri(self) -> str:
        """Generate a unique URI for a synthetic query document."""
        uri = f"file:///tmp/wily_query_{self._next_uri_id}.v"
        self._next_uri_id += 1
        return uri

    def _run_vernac_query(
        self, text: str, query_line: int = 0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Open a synthetic document, wait for diagnostics, get proof/goals messages.

        Returns ``(diagnostics, messages)``.  Diagnostics are used for error
        detection (severity 1 = error); messages from ``proof/goals`` contain
        the actual Vernac command output.
        """
        uri = self._next_uri()
        self._open_document(uri, text)
        diags = self._wait_for_diagnostics(uri)

        # Get sentence messages via proof/goals (skip if error diagnostics)
        messages: list[dict[str, Any]] = []
        if not any(d.get("severity") == 1 for d in diags):
            goals_result = self._send_request(
                "proof/goals",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": query_line, "character": 0},
                },
            )
            messages = goals_result.get("messages", [])

        self._close_document(uri)
        return diags, messages

    def _get_declaration_kind(self, name: str) -> str:
        """Use ``About`` to determine the kind of a declaration."""
        _diags, messages = self._run_vernac_query(f"About {name}.")
        all_text = "\n".join(
            m["text"] for m in messages if m.get("level", 3) != 1
        )

        # Rocq 9.x: parse "Expands to: Constant/Inductive/Constructor ..."
        expands_match = _EXPANDS_TO_RE.search(all_text)
        if expands_match:
            category = expands_match.group(1).lower()
            if category in _EXPANDS_TO_KIND:
                return _EXPANDS_TO_KIND[category]

        # Coq ≤8.x: parse "X is a Definition/Lemma/Theorem."
        match = _ABOUT_KIND_RE.search(all_text)
        if match:
            raw_kind = match.group(2).strip().lower()
            # Skip non-kind matches like "not universe polymorphic"
            if "universe" not in raw_kind and "transparent" not in raw_kind:
                for key, value in _KIND_MAP.items():
                    if key in raw_kind:
                        return value
                logger.warning(
                    "Unknown declaration kind for %s: %r", name, raw_kind
                )
                return raw_kind

        if "not a defined object" in all_text:
            logger.debug("About failed for %s (not a defined object)", name)
        else:
            logger.warning(
                "Could not determine kind for %s from About output", name
            )
        return "definition"

    # ------------------------------------------------------------------
    # Module path derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _vo_to_logical_path(vo_path: Path) -> str:
        """Derive a candidate logical path from a ``.vo`` file path.

        This is a heuristic: it takes the stem parts after a ``theories`` or
        ``user-contrib`` directory and joins them with dots.  For user
        projects it falls back to the file stem.
        """
        parts = vo_path.parts
        for marker_idx, part in enumerate(parts):
            if part == "theories":
                relevant = parts[marker_idx + 1 :]
                break
            if part == "user-contrib":
                relevant = parts[marker_idx + 1 :]
                # Rocq 9.x stdlib lives at user-contrib/Stdlib/. The logical
                # path for Search must omit the "Stdlib" prefix — e.g.
                # user-contrib/Stdlib/Init/Nat.vo → Init.Nat, not Stdlib.Init.Nat.
                if relevant and relevant[0] == "Stdlib":
                    relevant = relevant[1:]
                break
        else:
            relevant = parts[-2:] if len(parts) >= 2 else parts

        module_parts = [
            p[: -len(".vo")] if p.endswith(".vo") else p for p in relevant
        ]
        return ".".join(module_parts)

    # ------------------------------------------------------------------
    # Search diagnostics parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_search_diagnostics(
        diags: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Extract ``(name, type_sig)`` pairs from Search diagnostic output.

        Skips error diagnostics (severity 1).
        """
        results: list[tuple[str, str]] = []
        for d in diags:
            if d.get("severity") == 1:
                continue
            msg = d["message"]
            match = _SEARCH_LINE_RE.match(msg)
            if match:
                results.append((match.group(1), match.group(2)))
        return results

    @staticmethod
    def _parse_search_messages(
        messages: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Extract ``(name, type_sig)`` pairs from proof/goals messages.

        Each message has ``{"text": "name : type_sig", "level": int}``.
        Skips error messages (level 1).
        """
        results: list[tuple[str, str]] = []
        for m in messages:
            if m.get("level") == 1:
                continue
            text = m["text"]
            match = _SEARCH_LINE_RE.match(text)
            if match:
                results.append((match.group(1), match.group(2)))
        return results

    # ------------------------------------------------------------------
    # Backend protocol
    # ------------------------------------------------------------------

    def detect_version(self) -> str:
        """Return the Coq version string (e.g. ``"9.1.1"``)."""
        # Try extracting from serverInfo (e.g. "0.2.2+9.1.1")
        version_str = self._server_info.get("version", "")
        if "+" in version_str:
            coq_version = version_str.split("+", 1)[1]
            if re.match(r"\d+\.\d+", coq_version):
                return coq_version

        match = _VERSION_RE.search(version_str)
        if match:
            return match.group(1)

        # Fallback: coqc --version
        try:
            result = subprocess.run(
                ["coqc", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as exc:
            raise ExtractionError(
                f"coqc not found on PATH: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"coqc --version timed out: {exc}"
            ) from exc

        match = _VERSION_RE.search(result.stdout)
        if match:
            return match.group(1)

        first_line = (
            result.stdout.strip().splitlines()[0]
            if result.stdout.strip()
            else ""
        )
        if first_line:
            return first_line
        raise ExtractionError(
            f"Could not parse Coq version from coqc output: {result.stdout!r}"
        )

    def list_declarations(
        self, vo_path: Path
    ) -> list[tuple[str, str, Any]]:
        """List declarations from a compiled ``.vo`` file.

        Returns a list of ``(name, kind, constr_t)`` tuples.  The Search
        command is on line 1 of the synthetic document, so ``proof/goals``
        must target line 1.
        """
        self._ensure_alive()

        logical_path = self._vo_to_logical_path(vo_path)
        text = (
            f"Require Import {logical_path}.\n"
            f"Search _ inside {logical_path}."
        )
        diags, messages = self._run_vernac_query(text, query_line=1)

        # If there are error diagnostics, the Require likely failed
        if any(d.get("severity") == 1 for d in diags):
            return []

        search_results = self._parse_search_messages(messages)
        if not search_results:
            return []

        declarations: list[tuple[str, str, Any]] = []
        for name, type_sig in search_results:
            kind = self._get_declaration_kind(name)
            constr_t: dict[str, Any] = {
                "name": name,
                "type_signature": type_sig,
                "source": "coq-lsp",
            }
            declarations.append((name, kind, constr_t))

        return declarations

    def pretty_print(self, name: str) -> str:
        """Return the human-readable statement of a declaration."""
        self._ensure_alive()
        _diags, messages = self._run_vernac_query(f"Print {name}.")
        texts = [
            m["text"] for m in messages if m.get("level", 3) != 1
        ]
        return "\n".join(texts).strip()

    def pretty_print_type(self, name: str) -> str | None:
        """Return the type signature of a declaration, or ``None``."""
        self._ensure_alive()
        diags, messages = self._run_vernac_query(f"Check {name}.")
        if any(d.get("severity") == 1 for d in diags):
            logger.warning("pretty_print_type failed for %s", name)
            return None
        texts = [
            m["text"] for m in messages if m.get("level", 3) != 1
        ]
        if not texts:
            return None
        return "\n".join(texts).strip() or None

    def get_dependencies(
        self, name: str
    ) -> list[tuple[str, str]]:
        """Return dependency pairs ``(target_name, relation)``."""
        self._ensure_alive()
        _diags, messages = self._run_vernac_query(f"Print Assumptions {name}.")
        all_text = "\n".join(
            m["text"] for m in messages if m.get("level", 3) != 1
        )

        if "Closed under the global context" in all_text:
            return []

        deps: list[tuple[str, str]] = []
        for match in _ASSUMPTION_RE.finditer(all_text):
            dep_name = match.group(1)
            deps.append((dep_name, "assumes"))
        return deps
