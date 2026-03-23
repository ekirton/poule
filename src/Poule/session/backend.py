"""Coq Proof Backend — per-session coq-lsp process wrapper.

Implements the CoqBackend protocol defined in specification/coq-proof-backend.md.
Each instance wraps a single coq-lsp process for interactive proof exploration.
Communication uses LSP JSON-RPC over stdin/stdout with Content-Length framing.
Proof interaction uses the Petanque API (petanque/start, petanque/run,
petanque/goals, petanque/premises) available in coq-lsp 0.2.x.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from Poule.session.types import (
    Goal,
    Hypothesis,
    ProofState,
)

logger = logging.getLogger(__name__)

# Regex to split a proof body into individual tactic sentences (fallback).
# A Coq sentence ends with a period followed by whitespace or end-of-string.
# Periods inside qualified names (e.g., Nat.add_comm) are NOT sentence terminators
# because they are followed by a letter/digit, not whitespace.
# NOTE: This regex cannot handle bullets, braces, comments, or numeric literals.
# The primary path uses coq/getDocument for exact sentence boundaries.
_TACTIC_RE = re.compile(r"(?:[^.]|\.(?=[a-zA-Z0-9_]))*\.\s*")


class CoqProofBackend:
    """Async wrapper around a single coq-lsp process for proof interaction.

    Implements the CoqBackend protocol from specification/coq-proof-backend.md.
    Uses the Petanque API (petanque/start, petanque/run, petanque/goals,
    petanque/premises) for stateful proof exploration.
    """

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        watchdog_timeout: Optional[float] = None,
    ) -> None:
        self._proc = proc
        self._next_id = 0
        self._notification_buffer: list[dict[str, Any]] = []
        self._doc_uri: Optional[str] = None
        self._file_path: Optional[str] = None
        self._shut_down = False
        self.original_script: list[str] = []
        self._watchdog_timeout = watchdog_timeout

        # Petanque state management
        self._petanque_state: Optional[int] = None  # current state token
        self._state_stack: list[int] = []            # for undo
        self._original_states: list[int] = []        # state at each original step

    # ------------------------------------------------------------------
    # LSP message framing (async)
    # ------------------------------------------------------------------

    async def _write_message(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)  # type: ignore[union-attr]
        await self._proc.stdin.drain()  # type: ignore[union-attr]

    async def _read_message(self) -> dict[str, Any]:
        stdout = self._proc.stdout  # type: ignore[union-attr]
        wt = self._watchdog_timeout
        try:
            headers: dict[str, str] = {}
            while True:
                if wt is not None:
                    line = await asyncio.wait_for(stdout.readline(), timeout=wt)
                else:
                    line = await stdout.readline()
                if not line:
                    raise ConnectionError("coq-lsp closed stdout unexpectedly")
                line_str = line.decode("ascii").rstrip("\r\n")
                if not line_str:
                    break
                if ":" in line_str:
                    key, val = line_str.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            content_length = int(headers.get("content-length", 0))
            if wt is not None:
                body = await asyncio.wait_for(
                    stdout.readexactly(content_length), timeout=wt,
                )
            else:
                body = await stdout.readexactly(content_length)
            return json.loads(body)
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"coq-lsp unresponsive for {wt}s"
            ) from None

    async def _send_request(
        self, method: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        await self._write_message({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })
        while True:
            msg = await self._read_message()
            if "id" in msg and msg["id"] == request_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                return msg.get("result", {})
            self._notification_buffer.append(msg)

    async def _send_notification(
        self, method: str, params: dict[str, Any],
    ) -> None:
        await self._write_message({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def _wait_for_diagnostics(self, uri: str) -> list[dict[str, Any]]:
        """Wait for diagnostics after coq-lsp finishes processing.

        coq-lsp may send multiple publishDiagnostics during processing
        (including empty intermediate ones). We wait until the server
        status goes idle, then return the last diagnostics received.
        """
        # Discard any buffered diagnostics for this URI — they're stale
        self._notification_buffer = [
            msg for msg in self._notification_buffer
            if not (
                msg.get("method") == "textDocument/publishDiagnostics"
                and msg["params"]["uri"] == uri
            )
        ]

        last_diags: list[dict[str, Any]] = []
        while True:
            msg = await self._read_message()
            if (
                msg.get("method") == "textDocument/publishDiagnostics"
                and msg["params"]["uri"] == uri
            ):
                last_diags = msg["params"]["diagnostics"]
            elif (
                msg.get("method") == "$/coq/serverStatus"
                and msg.get("params", {}).get("status") == "Idle"
            ):
                # Server is done processing — return the last diagnostics we saw
                if last_diags is not None:
                    return last_diags
                # If no diagnostics seen yet, keep waiting
            elif "id" not in msg:
                # Buffer non-diagnostic, non-status notifications
                self._notification_buffer.append(msg)

    # ------------------------------------------------------------------
    # Petanque API wrappers
    # ------------------------------------------------------------------

    async def _petanque_start(self, proof_name: str) -> int:
        """Call petanque/start and return the initial state token."""
        result = await self._send_request(
            "petanque/start",
            {"uri": self._doc_uri, "thm": proof_name},
        )
        return result["st"]

    async def _petanque_run(self, st: int, tac: str) -> dict[str, Any]:
        """Call petanque/run and return the full result dict."""
        return await self._send_request(
            "petanque/run",
            {"st": st, "tac": tac},
        )

    async def _petanque_goals(self, st: int) -> Optional[dict[str, Any]]:
        """Call petanque/goals and return the goals dict (or None if proof done)."""
        return await self._send_request(
            "petanque/goals",
            {"st": st},
        )

    async def _petanque_premises(self, st: int) -> list[dict[str, Any]]:
        """Call petanque/premises and return the list of premise dicts."""
        result = await self._send_request(
            "petanque/premises",
            {"st": st},
        )
        # result is directly a list
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    # State translation
    # ------------------------------------------------------------------

    def _translate_petanque_goals(
        self, goals_result: Optional[dict[str, Any]], step_index: int = 0
    ) -> ProofState:
        """Translate petanque/goals response to ProofState."""
        if goals_result is None:
            return ProofState(
                schema_version=1,
                session_id="",
                step_index=step_index,
                is_complete=True,
                focused_goal_index=None,
                goals=[],
            )

        raw_goals = goals_result.get("goals", [])
        goals = []
        for i, g in enumerate(raw_goals):
            hyps = []
            for h in g.get("hyps", []):
                names = h.get("names", [])
                ty = h.get("ty", "")
                body = h.get("def", None)
                for name in names:
                    hyps.append(Hypothesis(name=name, type=ty, body=body))
            goals.append(Goal(index=i, type=g.get("ty", ""), hypotheses=hyps))

        is_complete = len(goals) == 0
        return ProofState(
            schema_version=1,
            session_id="",
            step_index=step_index,
            is_complete=is_complete,
            focused_goal_index=0 if goals else None,
            goals=goals,
        )

    # ------------------------------------------------------------------
    # Document lifecycle
    # ------------------------------------------------------------------

    async def _open_document(self, uri: str, text: str) -> None:
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "coq",
                    "version": 1,
                    "text": text,
                },
            },
        )

    # ------------------------------------------------------------------
    # Document model queries
    # ------------------------------------------------------------------

    async def _get_document_sentences(self) -> list[dict[str, Any]]:
        """Query coq/getDocument for sentence spans.

        Returns a list of span dicts, each with a 'range' key containing
        LSP-style start/end positions (line, character).
        """
        if self._doc_uri is None:
            return []
        try:
            result = await self._send_request(
                "coq/getDocument",
                {"textDocument": {"uri": self._doc_uri}},
            )
            return result.get("spans", [])
        except (RuntimeError, ConnectionError):
            return []

    @staticmethod
    def _short_name(proof_name: str) -> str:
        """Extract the short (unqualified) name from a possibly FQN.

        For ``Coq.Arith.PeanoNat.Nat.add_comm`` returns ``add_comm``.
        For ``add_comm`` returns ``add_comm`` unchanged.
        """
        return proof_name.rsplit(".", 1)[-1] if "." in proof_name else proof_name

    def _extract_tactics_from_spans(
        self, text: str, spans: list[dict[str, Any]], proof_name: str,
    ) -> list[str]:
        """Extract tactic sentences from document spans for a named proof.

        Identifies the Proof./Qed. boundaries, then extracts the text of
        each span that falls within the proof body.
        """
        # The index stores fully-qualified names (e.g., Coq.Arith.PeanoNat.Nat.add_comm)
        # but source files use the short name (e.g., add_comm).
        short_name = self._short_name(proof_name)
        lines = text.split("\n")

        def span_text(span: dict[str, Any]) -> str:
            r = span.get("range", {})
            start = r.get("start", {})
            end = r.get("end", {})
            sl, sc = start.get("line", 0), start.get("character", 0)
            el, ec = end.get("line", 0), end.get("character", 0)
            if sl == el:
                return lines[sl][sc:ec] if sl < len(lines) else ""
            parts = []
            if sl < len(lines):
                parts.append(lines[sl][sc:])
            for l_idx in range(sl + 1, min(el, len(lines))):
                parts.append(lines[l_idx])
            if el < len(lines):
                parts.append(lines[el][:ec])
            return "\n".join(parts)

        # Find the Proof. and Qed./Defined./Admitted./Abort. span indices
        proof_start_idx: Optional[int] = None
        proof_end_idx: Optional[int] = None
        # First, find the declaration span containing proof_name
        decl_idx: Optional[int] = None
        for i, span in enumerate(spans):
            txt = span_text(span).strip()
            if re.search(
                rf"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|"
                rf"Fixpoint|CoFixpoint|Example|Let|Instance)\s+{re.escape(short_name)}\b",
                txt,
            ):
                decl_idx = i
                break

        if decl_idx is None:
            return []

        # Find "Proof." span after the declaration, but stop if another
        # declaration is encountered first (the Proof. would belong to it).
        for i in range(decl_idx + 1, len(spans)):
            txt = span_text(spans[i]).strip()
            if re.match(r"Proof\b", txt):
                proof_start_idx = i
                break
            if re.search(
                r"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|"
                r"Fixpoint|CoFixpoint|Example|Let|Instance)\s+\w+",
                txt,
            ):
                break  # Another declaration before Proof. — not our proof

        if proof_start_idx is None:
            return []

        # Find Qed/Defined/Admitted/Abort span after Proof.
        for i in range(proof_start_idx + 1, len(spans)):
            txt = span_text(spans[i]).strip()
            if re.match(r"(Qed|Defined|Admitted|Abort)\s*\.", txt):
                proof_end_idx = i
                break

        if proof_end_idx is None:
            return []

        # Extract tactic text from spans between Proof. and Qed.
        tactics = []
        for i in range(proof_start_idx + 1, proof_end_idx):
            txt = span_text(spans[i]).strip()
            if txt:
                tactics.append(txt)

        return tactics

    def _extract_tactics_regex(self, text: str, proof_name: str) -> list[str]:
        """Fallback: extract tactic sentences using regex splitting.

        Used when coq/getDocument is unavailable or returns no spans.
        """
        # The index stores fully-qualified names but source uses short names.
        short_name = self._short_name(proof_name)
        decl_pattern = re.compile(
            rf"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|"
            rf"Fixpoint|CoFixpoint|Example|Let|Instance)\s+{re.escape(short_name)}\b"
        )
        decl_match = decl_pattern.search(text)
        if decl_match is None:
            return []

        proof_kw_match = re.search(r"\bProof\s*\.", text[decl_match.start():])
        if proof_kw_match is None:
            return []

        # Guard: if another declaration appears between this declaration and
        # the Proof. keyword, the Proof. belongs to a different declaration.
        between_text = text[decl_match.end():decl_match.start() + proof_kw_match.start()]
        if re.search(
            r"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|"
            r"Fixpoint|CoFixpoint|Example|Let|Instance)\s+\w+",
            between_text,
        ):
            return []

        proof_kw_end = decl_match.start() + proof_kw_match.end()

        end_match = re.search(
            r"\b(Qed|Defined|Admitted|Abort)\s*\.", text[proof_kw_end:]
        )
        if end_match:
            body_text = text[proof_kw_end:proof_kw_end + end_match.start()].strip()
        else:
            body_text = ""

        if not body_text:
            return []
        tactics = _TACTIC_RE.findall(body_text)
        return [t.strip() for t in tactics if t.strip()]

    # ------------------------------------------------------------------
    # CoqBackend protocol (§4.1)
    # ------------------------------------------------------------------

    async def load_file(self, file_path: str) -> None:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self._file_path = file_path
        self._doc_uri = path.as_uri()
        doc_text = path.read_text(encoding="utf-8")

        await self._open_document(self._doc_uri, doc_text)
        diags = await self._wait_for_diagnostics(self._doc_uri)

        errors = [d for d in diags if d.get("severity") == 1]
        if errors:
            msg = "; ".join(d.get("message", "") for d in errors)
            raise RuntimeError(f"Coq check failed: {msg}")

    async def position_at_proof(self, proof_name: str) -> ProofState:
        if self._doc_uri is None:
            raise RuntimeError("No file loaded")

        # Parse the file text to extract the original proof script.
        path = Path(self._file_path)  # type: ignore[arg-type]
        text = path.read_text(encoding="utf-8")

        # Try document model first for exact tactic boundaries
        spans = await self._get_document_sentences()
        if spans:
            doc_tactics = self._extract_tactics_from_spans(text, spans, proof_name)
            if doc_tactics:
                self.original_script = doc_tactics
            else:
                # Document model didn't find the proof — fall back to regex
                self.original_script = self._extract_tactics_regex(text, proof_name)
        else:
            # No document model available — fall back to regex
            self.original_script = self._extract_tactics_regex(text, proof_name)

        # Use petanque/start to get the initial proof state
        try:
            initial_st = await self._petanque_start(proof_name)
        except RuntimeError as exc:
            raise ValueError(f"Cannot start proof '{proof_name}': {exc}") from exc

        self._petanque_state = initial_st
        self._state_stack = []

        # Build original state history by running the original script silently
        self._original_states = [initial_st]
        st = initial_st
        for tac in self.original_script:
            try:
                run_result = await self._petanque_run(st, tac)
                st = run_result["st"]
                self._original_states.append(st)
            except RuntimeError:
                # If a step fails, stop building history
                break

        # Get and return the initial proof state
        goals_result = await self._petanque_goals(initial_st)
        return self._translate_petanque_goals(goals_result, step_index=0)

    async def execute_tactic(self, tactic: str) -> ProofState:
        if self._shut_down:
            raise RuntimeError("Backend has been shut down")
        if self._petanque_state is None:
            raise RuntimeError("No proof in progress")

        run_result = await self._petanque_run(self._petanque_state, tactic)
        proof_finished = run_result.get("proof_finished", False)
        new_st = run_result["st"]

        # Push old state for undo
        self._state_stack.append(self._petanque_state)
        self._petanque_state = new_st

        if proof_finished:
            return ProofState(
                schema_version=1,
                session_id="",
                step_index=len(self._state_stack),
                is_complete=True,
                focused_goal_index=None,
                goals=[],
            )

        goals_result = await self._petanque_goals(new_st)
        return self._translate_petanque_goals(
            goals_result, step_index=len(self._state_stack)
        )

    async def get_current_state(self) -> ProofState:
        if self._petanque_state is None:
            raise RuntimeError("No proof in progress")

        goals_result = await self._petanque_goals(self._petanque_state)
        return self._translate_petanque_goals(
            goals_result, step_index=len(self._state_stack)
        )

    async def undo(self) -> None:
        if not self._state_stack:
            return
        self._petanque_state = self._state_stack.pop()

    async def get_premises_at_step(self, step: int) -> list[dict[str, str]]:
        """Return premises available at the given proof step.

        Uses petanque/premises to query the available premises at the
        state corresponding to the given step in the original proof script.
        """
        if step < 1 or step > len(self._original_states):
            return []

        # State after executing `step` tactics from the original script
        # (index 0 = before any tactic, index 1 = after tactic 1, etc.)
        state_idx = min(step, len(self._original_states) - 1)
        st = self._original_states[state_idx]

        try:
            raw_premises = await self._petanque_premises(st)
        except RuntimeError:
            return []

        premises = []
        for p in raw_premises:
            name = p.get("full_name", "")
            if not name:
                continue
            # Extract kind from info if available
            info = p.get("info")
            kind = "lemma"
            if isinstance(info, dict):
                inner = info.get("Ok", info)
                if isinstance(inner, dict):
                    kind = inner.get("kind", "lemma")
            premises.append({"name": name, "kind": kind})

        return premises

    async def execute_vernacular(self, command: str) -> str:
        """Send a vernacular command through coq-lsp and return the output.

        Creates a temporary document containing the command, opens it,
        waits for diagnostics, and returns any diagnostic messages as
        the command output.

        NOTE: coq-lsp only emits diagnostics for errors and warnings.
        Successful queries (Print, Check, About) produce no diagnostics
        and return empty strings.  For reliable output capture, callers
        should route through a coqtop subprocess instead — the session
        manager handles this automatically via _ensure_coqtop().
        """
        self._next_id += 1
        temp_uri = f"file:///tmp/poule_vernacular_{self._next_id}.v"
        text = command.rstrip()
        if not text.endswith("."):
            text += "."

        await self._open_document(temp_uri, text)
        diags = await self._wait_for_diagnostics(temp_uri)

        # Close the temporary document
        await self._send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": temp_uri}},
        )

        # Collect diagnostic messages as output
        messages = [d.get("message", "") for d in diags]
        return "\n".join(messages)

    async def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True

        if self._proc.returncode is not None:
            return

        try:
            await self._send_request("shutdown", {})
            await self._send_notification("exit", {})
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        except Exception:
            try:
                self._proc.kill()
                await self._proc.wait()
            except Exception:
                pass


# ------------------------------------------------------------------
# Factory (§4.2)
# ------------------------------------------------------------------


async def create_coq_backend(
    file_path: str,
    watchdog_timeout: Optional[float] = None,
) -> CoqProofBackend:
    """Spawn a coq-lsp process and return a connected CoqProofBackend.

    Per spec §4.2: the factory is the only way to create backend instances.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "coq-lsp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"coq-lsp not found on PATH: {exc}"
        ) from exc

    backend = CoqProofBackend(proc, watchdog_timeout=watchdog_timeout)

    # LSP initialize handshake
    await backend._send_request(
        "initialize",
        {
            "processId": os.getpid(),
            "rootUri": None,
            "capabilities": {},
        },
    )
    await backend._send_notification("initialized", {})

    return backend
