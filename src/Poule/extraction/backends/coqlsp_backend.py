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
import tempfile
from pathlib import Path
from collections.abc import Callable
from typing import Any, NamedTuple

from Poule.extraction.errors import BackendCrashError, ExtractionError

logger = logging.getLogger(__name__)

# Regex for parsing ``Search`` output.
# Each result looks like ``name : type_signature`` where the type signature
# may span multiple lines with indentation (coq-lsp breaks long types).
# re.DOTALL lets ``.`` match newlines so multi-line signatures are captured.
_SEARCH_LINE_RE = re.compile(r"^(\S+)\s*:\s*(.+)$", re.DOTALL)

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
    "notation": "notation",
}

# Rocq 9.x: "Ltac Corelib.Init.Ltac.reflexivity" (tactic definition)
_LTAC_RE = re.compile(r"^Ltac\s", re.MULTILINE)

# Rocq 9.x: "Module Corelib.Init.Decimal" (module declaration)
_MODULE_RE = re.compile(r"^Module\s", re.MULTILINE)

# Regex for parsing ``Print Assumptions`` output.
_ASSUMPTION_RE = re.compile(r"^\s*(\S+)\s*:\s*(.+)$", re.MULTILINE)

# Regex for the coqc version string.
_VERSION_RE = re.compile(r"version\s+([\d.]+)")

# Regex for opacity from About output: "<name> is opaque" / "<name> is transparent"
_OPACITY_RE = re.compile(r"^\S+\s+is\s+(opaque|transparent)\s*$", re.MULTILINE)

# Regex for declared library and line from About output:
# "Declared in library <lib>, line <n>[, characters <range>]"
_DECLARED_LIB_RE = re.compile(
    r"^Declared in library\s+([\w.]+),\s*line\s+(\d+)", re.MULTILINE
)

# Prefix emitted by coq-lsp when loading opaque proof bodies from disk.
# This is a level-3 (information) diagnostic, not Vernacular output.
_DIAGNOSTIC_PREFIXES = ("Fetching opaque proofs from disk",)


def _extract_vernac_text(messages: list[dict[str, Any]]) -> str:
    """Join Vernacular output messages, excluding errors and known diagnostics."""
    texts = [
        m["text"]
        for m in messages
        if m.get("level", 3) != 1
        and not any(m["text"].startswith(p) for p in _DIAGNOSTIC_PREFIXES)
    ]
    return "\n".join(texts).strip()


class AboutResult(NamedTuple):
    """Result of parsing an About response: kind, opacity, declared library, and line."""

    kind: str
    opacity: str | None  # "opaque", "transparent", or None
    declared_library: str | None  # e.g. "Stdlib.Numbers.NatInt.NZAdd"
    declared_line: int | None  # 1-based source line number


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
        self._stderr_file: Any = None  # temp file for coq-lsp stderr
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
            # Redirect stderr to a temp file instead of a pipe to avoid
            # deadlock when the OS pipe buffer fills (coq-lsp writes
            # diagnostic/logging output to stderr continuously).  The
            # file is read on crash for error diagnostics.
            self._stderr_file = tempfile.TemporaryFile(mode="w+b")
            self._proc = subprocess.Popen(
                ["coq-lsp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
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
            if self._stderr_file is not None:
                try:
                    self._stderr_file.close()
                except Exception:
                    pass
                self._stderr_file = None
            self._notification_buffer.clear()

    def _get_child_rss_bytes(self) -> int:
        """Return total RSS in bytes for coq-lsp and all its descendants.

        Walks ``/proc/<pid>/task/../children`` recursively to capture
        rocqworker sub-processes that coq-lsp spawns internally.
        """
        if self._proc is None or self._proc.pid is None:
            return 0

        def _descendant_pids(pid: int) -> list[int]:
            """Return *pid* plus all descendant PIDs via /proc children files."""
            pids = [pid]
            try:
                with open(f"/proc/{pid}/task/{pid}/children") as f:
                    for child_pid in f.read().split():
                        pids.extend(_descendant_pids(int(child_pid)))
            except (OSError, ValueError):
                pass
            return pids

        total = 0
        for pid in _descendant_pids(self._proc.pid):
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1]) * 1024  # kB → bytes
                            break
            except (OSError, ValueError):
                pass
        return total

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
            if self._stderr_file is not None:
                try:
                    self._stderr_file.seek(0)
                    raw = self._stderr_file.read()
                    stderr = (
                        raw.decode("utf-8", errors="replace")
                        if isinstance(raw, bytes)
                        else raw
                    )
                except Exception:
                    pass
            self._proc = None
            if self._stderr_file is not None:
                try:
                    self._stderr_file.close()
                except Exception:
                    pass
                self._stderr_file = None
            raise BackendCrashError(
                f"coq-lsp exited unexpectedly (exit code {exit_code}). "
                f"stderr: {stderr!r}"
            )

    def _next_uri(self) -> str:
        """Generate a unique URI for a synthetic query document."""
        uri = f"file:///tmp/poule_query_{self._next_uri_id}.v"
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
        # Drain buffered notifications ($/progress, etc.) to prevent
        # unbounded memory growth over many document lifecycles.
        self._notification_buffer.clear()
        return diags, messages

    @staticmethod
    def _parse_about_kind(name: str, messages: list[dict[str, Any]]) -> AboutResult:
        """Parse ``About`` output messages to determine kind, opacity, declared library, and line.

        Returns an :class:`AboutResult` namedtuple with ``kind``, ``opacity``,
        ``declared_library``, and ``declared_line`` fields.  Callers that only
        need the kind can access ``result.kind``.
        """
        all_text = _extract_vernac_text(messages)
        logger.debug("About output for %s: %r", name, all_text)

        # Extract opacity and declared_library/declared_line from the full text.
        opacity_match = _OPACITY_RE.search(all_text)
        opacity: str | None = opacity_match.group(1) if opacity_match else None

        # Take the *last* Declared-in-library line — when a notation aliases
        # a constant the About output may include two Declared-in lines; the
        # second one describes the underlying constant.
        declared_library: str | None = None
        declared_line: int | None = None
        for dl_match in _DECLARED_LIB_RE.finditer(all_text):
            declared_library = dl_match.group(1)
            declared_line = int(dl_match.group(2))

        # --- Kind detection (unchanged logic) ---

        # Rocq 9.x: detect Ltac and Module formats before Expands-to
        if _LTAC_RE.search(all_text):
            return AboutResult("ltac", opacity, declared_library, declared_line)
        if _MODULE_RE.search(all_text):
            return AboutResult("module", opacity, declared_library, declared_line)

        # Rocq 9.x: parse all "Expands to: <Category> ..." lines.
        # Prefer Constant/Inductive/Constructor over Notation when both
        # are present (notation aliasing a real constant).
        expands_matches = _EXPANDS_TO_RE.findall(all_text)
        if expands_matches:
            notation_seen = False
            for category_raw in expands_matches:
                category = category_raw.lower()
                kind = _EXPANDS_TO_KIND.get(category)
                if kind and kind != "notation":
                    return AboutResult(kind, opacity, declared_library, declared_line)
                if kind == "notation":
                    notation_seen = True
            if notation_seen:
                return AboutResult("notation", opacity, declared_library, declared_line)

        # Coq ≤8.x: parse "X is a Definition/Lemma/Theorem."
        match = _ABOUT_KIND_RE.search(all_text)
        if match:
            raw_kind = match.group(2).strip().lower()
            # Skip non-kind matches like "not universe polymorphic"
            if "universe" not in raw_kind and "transparent" not in raw_kind:
                for key, value in _KIND_MAP.items():
                    if key in raw_kind:
                        return AboutResult(value, opacity, declared_library, declared_line)
                logger.warning(
                    "Unknown declaration kind for %s: %r", name, raw_kind
                )
                return AboutResult(raw_kind, opacity, declared_library, declared_line)

        if "not a defined object" in all_text:
            logger.debug("About failed for %s (not a defined object)", name)
        else:
            logger.warning(
                "Could not determine kind for %s from About output", name
            )
        return AboutResult("definition", opacity, declared_library, declared_line)

    def _get_declaration_kind(self, name: str) -> AboutResult:
        """Use ``About`` to determine the kind of a declaration."""
        _diags, messages = self._run_vernac_query(f"About {name}.")
        return self._parse_about_kind(name, messages)

    # ------------------------------------------------------------------
    # Batched Vernac queries
    # ------------------------------------------------------------------

    _VERNAC_BATCH_SIZE = 100

    def _run_vernac_batch(
        self, commands: list[str]
    ) -> list[list[dict[str, Any]]]:
        """Execute multiple Vernac commands in a single document.

        Builds one document with one command per line, opens it once, waits
        for diagnostics once, then issues ``proof/goals`` for each line.

        Returns a list of message lists — one per command.  On global error
        diagnostics (all severity-1), returns empty lists for all commands.
        """
        if not commands:
            return []

        self._ensure_alive()
        text = "\n".join(commands)
        uri = self._next_uri()
        self._open_document(uri, text)
        diags = self._wait_for_diagnostics(uri)

        # On global errors, return empty results for all commands
        if any(d.get("severity") == 1 for d in diags):
            self._close_document(uri)
            return [[] for _ in commands]

        results: list[list[dict[str, Any]]] = []
        for line_idx in range(len(commands)):
            goals_result = self._send_request(
                "proof/goals",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line_idx, "character": 0},
                },
            )
            results.append(goals_result.get("messages", []))

        self._close_document(uri)
        # Drain buffered notifications ($/progress, etc.) to prevent
        # unbounded memory growth over many document lifecycles.
        self._notification_buffer.clear()
        return results

    def query_declaration_data(
        self,
        names: list[str],
        *,
        name_to_import: dict[str, str] | None = None,
    ) -> dict[str, tuple[str, list[tuple[str, str]]]]:
        """Batch Print + Print Assumptions queries for multiple declarations.

        For each name, issues ``Print <name>.`` and ``Print Assumptions <name>.``
        in shared documents (≤50 declarations = ≤100 lines per document).

        When *name_to_import* is provided, names are grouped by their import
        path and each batch document begins with
        ``Require Import <import_path>.`` so that declaration names are in
        scope.  The result for this preamble line is discarded.

        Returns a dict mapping name → ``(statement, dependency_pairs)``.
        """
        self._ensure_alive()
        result: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        batch_size = 50  # 50 declarations = 100 lines (Print + Print Assumptions)

        if name_to_import:
            # Group names by import path so each group shares one preamble.
            groups: dict[str, list[str]] = {}
            for name in names:
                imp = name_to_import.get(name, "")
                groups.setdefault(imp, []).append(name)
            ordered_groups = list(groups.items())
        else:
            ordered_groups = [("", names)]

        for import_path, group_names in ordered_groups:
            for i in range(0, len(group_names), batch_size):
                batch_names = group_names[i : i + batch_size]
                commands: list[str] = []
                if import_path:
                    commands.append(f"Require Import {import_path}.")
                for name in batch_names:
                    commands.append(f"Print {name}.")
                    commands.append(f"Print Assumptions {name}.")

                all_messages = self._run_vernac_batch(commands)

                # Skip preamble result if import was prepended.
                offset = 1 if import_path else 0

                for j, name in enumerate(batch_names):
                    idx = offset + j * 2
                    print_msgs = all_messages[idx] if idx < len(all_messages) else []
                    assumptions_msgs = all_messages[idx + 1] if idx + 1 < len(all_messages) else []

                    # Parse Print output → statement
                    statement = _extract_vernac_text(print_msgs)

                    # Parse Print Assumptions output → dependencies
                    all_text = _extract_vernac_text(assumptions_msgs)
                    deps: list[tuple[str, str]] = []
                    if "Closed under the global context" not in all_text:
                        for match in _ASSUMPTION_RE.finditer(all_text):
                            dep_name = match.group(1)
                            deps.append((dep_name, "uses"))

                    result[name] = (statement, deps)

        return result

    # ------------------------------------------------------------------
    # Module path derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _vo_to_logical_path(vo_path: Path) -> str:
        """Derive a candidate logical path from a ``.vo`` file path.

        This is a heuristic: it takes the stem parts after a ``theories`` or
        ``user-contrib`` directory and joins them with dots.  For user
        projects it falls back to the file stem.

        The returned path is suitable for ``Require Import`` and
        ``Search _ inside`` Vernac commands.  For the canonical module
        name used in storage, see :meth:`_vo_to_canonical_module`.
        """
        parts = vo_path.parts
        for marker_idx, part in enumerate(parts):
            if part == "theories":
                relevant = parts[marker_idx + 1 :]
                break
            if part == "user-contrib":
                relevant = parts[marker_idx + 1 :]
                # Rocq 9.x: omit "Stdlib" prefix for import paths —
                # 'Search _ inside Stdlib.Init.Nat.' does not work,
                # 'Search _ inside Init.Nat.' does.
                if relevant and relevant[0] == "Stdlib":
                    relevant = relevant[1:]
                break
        else:
            relevant = parts[-2:] if len(parts) >= 2 else parts

        module_parts = [
            p[: -len(".vo")] if p.endswith(".vo") else p for p in relevant
        ]
        return ".".join(module_parts)

    @staticmethod
    def _vo_to_canonical_module(vo_path: Path) -> str:
        """Derive the canonical module name for storage from a ``.vo`` path.

        For Rocq 9.x stdlib (``user-contrib/Stdlib/``), the ``Stdlib``
        prefix is kept as the canonical namespace — e.g.
        ``user-contrib/Stdlib/Init/Nat.vo`` → ``Stdlib.Init.Nat``.

        For other packages (e.g. MathComp), the canonical module is
        the same as the import path.
        """
        parts = vo_path.parts
        for marker_idx, part in enumerate(parts):
            if part == "theories":
                relevant = parts[marker_idx + 1 :]
                break
            if part == "user-contrib":
                relevant = parts[marker_idx + 1 :]
                # Keep Stdlib prefix as-is for canonical names
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
    def _normalize_type_sig(raw: str) -> str:
        """Collapse multi-line type signatures into a single line.

        coq-lsp breaks long type signatures across lines with leading
        whitespace.  Per spec §4.1.1, continuation lines are joined into
        the full type signature with newlines and surrounding whitespace
        collapsed to a single space.
        """
        return re.sub(r"\s*\n\s*", " ", raw).strip()

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
                type_sig = CoqLspBackend._normalize_type_sig(match.group(2))
                results.append((match.group(1), type_sig))
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
                type_sig = CoqLspBackend._normalize_type_sig(match.group(2))
                results.append((match.group(1), type_sig))
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
        self, vo_path: Path, *, rss_check: Callable[[], None] | None = None,
    ) -> list[tuple[str, str, Any]]:
        """List declarations from a compiled ``.vo`` file.

        Returns a list of ``(name, kind, constr_t)`` tuples.  The Search
        command is on line 1 of the synthetic document, so ``proof/goals``
        must target line 1.

        About queries for kind detection are batched into documents of
        ≤100 commands each to reduce document lifecycle overhead.
        """
        self._ensure_alive()

        import_path = self._vo_to_logical_path(vo_path)
        canonical_module = self._vo_to_canonical_module(vo_path)
        text = (
            f"Require Import {import_path}.\n"
            f"Search _ inside {import_path}."
        )
        diags, messages = self._run_vernac_query(text, query_line=1)

        # If there are error diagnostics, the Require likely failed
        if any(d.get("severity") == 1 for d in diags):
            return []

        search_results = self._parse_search_messages(messages)
        if not search_results:
            return []

        # Check RSS after Search (the Require Import may have loaded a
        # large transitive dependency tree) before starting About batches.
        if rss_check is not None:
            rss_check()

        # Batch About queries for kind detection + metadata
        names = [name for name, _type_sig in search_results]
        about_results = self._batch_get_about_metadata(
            names, import_path=import_path, rss_check=rss_check,
        )

        declarations: list[tuple[str, str, Any]] = []
        for (short_name, type_sig), about in zip(search_results, about_results):
            fqn = f"{canonical_module}.{short_name}"
            constr_t: dict[str, Any] = {
                "name": fqn,
                "type_signature": type_sig,
                "source": "coq-lsp",
                "opacity": about.opacity,
                "declared_library": about.declared_library,
                "declared_line": about.declared_line,
            }
            declarations.append((fqn, about.kind, constr_t))

        return declarations

    def _batch_get_about_metadata(
        self, names: list[str], *, import_path: str | None = None,
        rss_check: Callable[[], None] | None = None,
    ) -> list[AboutResult]:
        """Batch About queries and parse kind + metadata for declaration names.

        When *import_path* is provided, each batch document begins with
        ``Require Import <import_path>.`` so that short declaration names
        (from Search output) are in scope.  The result for this preamble
        line is discarded.
        """
        results: list[AboutResult] = []
        batch_size = self._VERNAC_BATCH_SIZE

        for i in range(0, len(names), batch_size):
            batch_names = names[i : i + batch_size]
            commands = [f"About {name}." for name in batch_names]
            if import_path:
                commands = [f"Require Import {import_path}."] + commands
            all_messages = self._run_vernac_batch(commands)
            if import_path:
                all_messages = all_messages[1:]  # discard Require Import result

            for name, messages in zip(batch_names, all_messages):
                results.append(self._parse_about_kind(name, messages))

            # Check RSS between batches (skip after final batch).
            if rss_check is not None and i + batch_size < len(names):
                rss_check()

        return results

    def pretty_print(self, name: str) -> str:
        """Return the human-readable statement of a declaration."""
        self._ensure_alive()
        _diags, messages = self._run_vernac_query(f"Print {name}.")
        return _extract_vernac_text(messages)

    def pretty_print_type(self, name: str) -> str | None:
        """Return the type signature of a declaration, or ``None``."""
        self._ensure_alive()
        diags, messages = self._run_vernac_query(f"Check {name}.")
        if any(d.get("severity") == 1 for d in diags):
            logger.warning("pretty_print_type failed for %s", name)
            return None
        result = _extract_vernac_text(messages)
        return result or None

    # Patterns for parsing Locate output
    _LOCATE_CATEGORIES = frozenset({"Constant", "Inductive", "Constructor", "Class", "Instance"})
    # Pattern to extract FQN from notation body: Notation "x + y" := (Nat.add x y)
    _NOTATION_BODY_RE = __import__("re").compile(
        r'Notation\b.*?:=\s*\((\S+)'
    )

    def locate(self, name: str) -> str | list[str] | None:
        """Resolve a short name to its FQN(s) via ``Locate``.

        Returns a single FQN string, a list of FQNs (ambiguous), or None.
        """
        self._ensure_alive()

        # Infix operators need quoted form: Locate "+".
        if name and not name[0].isalpha() and not name.startswith("_"):
            query = f'Locate "{name}".'
        else:
            query = f"Locate {name}."

        diags, messages = self._run_vernac_query(query)

        # Error diagnostics → unresolvable
        if any(d.get("severity") == 1 for d in diags):
            return None

        # Parse response lines
        fqns: list[str] = []
        notation_fqns: list[str] = []
        for msg in messages:
            text = msg.get("text", "")
            for line in text.splitlines():
                line = line.strip()
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0] in self._LOCATE_CATEGORIES:
                    fqns.append(parts[1])
                elif line.startswith("Notation"):
                    # Extract the head symbol from notation body
                    m = self._NOTATION_BODY_RE.match(line)
                    if m:
                        head = m.group(1)
                        # Only keep qualified names (contain a dot)
                        if "." in head:
                            notation_fqns.append(head)

        # Prefer Constant/Inductive/Constructor over Notation
        if fqns:
            if len(fqns) == 1:
                return fqns[0]
            return fqns

        # Fall back to notation-derived FQNs
        if notation_fqns:
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique: list[str] = []
            for f in notation_fqns:
                if f not in seen:
                    seen.add(f)
                    unique.append(f)
            if len(unique) == 1:
                return unique[0]
            return unique

        return None

    def get_dependencies(
        self, name: str
    ) -> list[tuple[str, str]]:
        """Return dependency pairs ``(target_name, relation)``."""
        self._ensure_alive()
        _diags, messages = self._run_vernac_query(f"Print Assumptions {name}.")
        all_text = _extract_vernac_text(messages)

        if "Closed under the global context" in all_text:
            return []

        deps: list[tuple[str, str]] = []
        for match in _ASSUMPTION_RE.finditer(all_text):
            dep_name = match.group(1)
            deps.append((dep_name, "uses"))
        return deps
