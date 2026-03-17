"""Coq Proof Backend — per-session coq-lsp process wrapper.

Implements the CoqBackend protocol defined in specification/coq-proof-backend.md.
Each instance wraps a single coq-lsp process for interactive proof exploration.
Communication uses LSP JSON-RPC over stdin/stdout with Content-Length framing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from wily_rooster.session.types import (
    Goal,
    Hypothesis,
    ProofState,
)

logger = logging.getLogger(__name__)

# Regex to split a proof body into individual tactic sentences.
# A Coq sentence ends with a period followed by whitespace or end-of-string.
# Periods inside qualified names (e.g., Nat.add_comm) are NOT sentence terminators
# because they are followed by a letter/digit, not whitespace.
_TACTIC_RE = re.compile(r"(?:[^.]|\.(?=[a-zA-Z0-9_]))*\.\s*")

# Proof-opening keywords in Coq/Rocq.
_PROOF_START_RE = re.compile(
    r"^\s*(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|Fixpoint|"
    r"CoFixpoint|Example|Let|Instance|Program\s+\w+)\s+",
    re.MULTILINE,
)

# Match the "Proof." keyword (or "Proof with ...") on its own line.
_PROOF_KW_RE = re.compile(r"^\s*Proof\b", re.MULTILINE)

# Match Qed., Defined., Admitted., Abort. to find proof end.
_PROOF_END_RE = re.compile(r"^\s*(Qed|Defined|Admitted|Abort)\s*\.", re.MULTILINE)


class CoqProofBackend:
    """Async wrapper around a single coq-lsp process for proof interaction.

    Implements the CoqBackend protocol from specification/coq-proof-backend.md.
    """

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self._next_id = 0
        self._notification_buffer: list[dict[str, Any]] = []
        self._doc_uri: Optional[str] = None
        self._doc_version = 0
        self._doc_text = ""
        self._file_path: Optional[str] = None
        self._proof_start_line: Optional[int] = None
        self._proof_body_start_line: Optional[int] = None
        self._tactic_count = 0
        self._current_goals: Optional[dict] = None
        self._shut_down = False
        self.original_script: list[str] = []

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
        headers: dict[str, str] = {}
        while True:
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
        body = await stdout.readexactly(content_length)
        return json.loads(body)

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
    # Document lifecycle
    # ------------------------------------------------------------------

    async def _open_document(self, uri: str, text: str) -> None:
        self._doc_version = 1
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "coq",
                    "version": self._doc_version,
                    "text": text,
                },
            },
        )

    async def _change_document(self, uri: str, new_text: str) -> None:
        self._doc_version += 1
        await self._send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": self._doc_version},
                "contentChanges": [{"text": new_text}],
            },
        )

    async def _close_document(self, uri: str) -> None:
        await self._send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}},
        )

    # ------------------------------------------------------------------
    # proof/goals query
    # ------------------------------------------------------------------

    async def _get_goals_at(self, line: int, character: int = 0) -> dict[str, Any]:
        result = await self._send_request(
            "proof/goals",
            {
                "textDocument": {"uri": self._doc_uri},
                "position": {"line": line, "character": character},
            },
        )
        return result

    # ------------------------------------------------------------------
    # State translation (§4.3)
    # ------------------------------------------------------------------

    def _translate_goals(self, goals_data: dict[str, Any]) -> ProofState:
        """Translate coq-lsp goals response to ProofState."""
        raw_goals = goals_data.get("goals", [])
        goals = []
        for i, g in enumerate(raw_goals):
            hyps = []
            for h in g.get("hyps", []):
                names = h.get("names", [])
                ty = h.get("ty", "")
                body = h.get("def", None)
                # coq-lsp may return multiple names for one hyp binding
                for name in names:
                    hyps.append(Hypothesis(name=name, type=ty, body=body))
            goals.append(Goal(index=i, type=g.get("ty", ""), hypotheses=hyps))

        is_complete = len(goals) == 0
        return ProofState(
            schema_version=1,
            session_id="",
            step_index=0,
            is_complete=is_complete,
            focused_goal_index=0 if goals else None,
            goals=goals,
        )

    # ------------------------------------------------------------------
    # CoqBackend protocol (§4.1)
    # ------------------------------------------------------------------

    async def load_file(self, file_path: str) -> None:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self._file_path = file_path
        self._doc_uri = path.as_uri()
        self._doc_text = path.read_text(encoding="utf-8")

        await self._open_document(self._doc_uri, self._doc_text)
        diags = await self._wait_for_diagnostics(self._doc_uri)

        errors = [d for d in diags if d.get("severity") == 1]
        if errors:
            msg = "; ".join(d.get("message", "") for d in errors)
            raise RuntimeError(f"Coq check failed: {msg}")

    async def position_at_proof(self, proof_name: str) -> ProofState:
        if self._doc_text is None:
            raise RuntimeError("No file loaded")

        # Parse the file text to find the proof and extract its structure.
        # We work on the full text (not lines) to handle inline proofs like:
        #   "Lemma x : T. Proof. tactic1. tactic2. Qed."
        text = self._doc_text

        # Find the proof declaration
        decl_pattern = re.compile(
            rf"\b(Lemma|Theorem|Proposition|Corollary|Fact|Remark|Definition|"
            rf"Fixpoint|CoFixpoint|Example|Let|Instance)\s+{re.escape(proof_name)}\b"
        )
        decl_match = decl_pattern.search(text)
        if decl_match is None:
            raise ValueError(f"Proof not found: {proof_name}")

        # Find "Proof." after the declaration
        proof_kw_match = re.search(r"\bProof\s*\.", text[decl_match.start():])
        if proof_kw_match is None:
            raise ValueError(f"No 'Proof.' found for {proof_name}")
        proof_kw_end = decl_match.start() + proof_kw_match.end()

        # Find Qed/Defined/Admitted/Abort after Proof.
        end_match = re.search(r"\b(Qed|Defined|Admitted|Abort)\s*\.", text[proof_kw_end:])
        if end_match:
            body_text = text[proof_kw_end:proof_kw_end + end_match.start()].strip()
        else:
            body_text = ""

        # Extract original tactic script from body
        self.original_script = []
        if body_text:
            tactics = _TACTIC_RE.findall(body_text)
            self.original_script = [t.strip() for t in tactics if t.strip()]

        # Build a normalized preamble for the working document.
        # Everything before the proof's Proof. keyword, plus "Proof." on its own line.
        # This ensures coq-lsp processes the preamble correctly regardless of
        # the original file's line structure.
        preamble_text = text[:decl_match.start() + proof_kw_match.end()].rstrip()
        # Ensure Proof. is on its own line for clean positioning
        # Split at the Proof. boundary to normalize
        pre_proof = text[:decl_match.start() + proof_kw_match.start()].rstrip()
        self._working_preamble = pre_proof + "\nProof."
        self._working_tactics: list[str] = []
        self._tactic_count = 0

        # Update document to just the preamble (no tactics yet)
        new_text = self._working_preamble + "\n"
        await self._change_document(self._doc_uri, new_text)
        self._doc_text = new_text
        await self._wait_for_diagnostics(self._doc_uri)

        # Get initial proof state — query at the "Proof." line
        preamble_lines = self._working_preamble.splitlines()
        proof_line = len(preamble_lines) - 1
        # Query at end of "Proof." to get state after it
        char_pos = len("Proof.")
        goals_result = await self._get_goals_at(proof_line, char_pos)

        goals_data = goals_result.get("goals")
        if goals_data is None:
            raise ValueError(f"No proof state at {proof_name} — proof may not be active")

        state = self._translate_goals(goals_data)
        return state

    async def execute_tactic(self, tactic: str) -> ProofState:
        if self._shut_down:
            raise RuntimeError("Backend has been shut down")

        # Append the tactic to the working document
        self._working_tactics.append(tactic)
        new_text = self._working_preamble + "\n" + "\n".join(self._working_tactics) + "\n"
        await self._change_document(self._doc_uri, new_text)
        self._doc_text = new_text
        diags = await self._wait_for_diagnostics(self._doc_uri)

        # Check for errors — any error diagnostic means the tactic failed
        tactic_line = len(self._working_preamble.splitlines()) + len(self._working_tactics) - 1
        tactic_errors = [d for d in diags if d.get("severity") == 1]

        if tactic_errors:
            # Revert — remove the failed tactic
            self._working_tactics.pop()
            revert_text = self._working_preamble + "\n"
            if self._working_tactics:
                revert_text += "\n".join(self._working_tactics) + "\n"
            await self._change_document(self._doc_uri, revert_text)
            self._doc_text = revert_text
            await self._wait_for_diagnostics(self._doc_uri)

            msg = "; ".join(d.get("message", "") for d in tactic_errors)
            raise RuntimeError(f"Tactic failed: {msg}")

        self._tactic_count += 1

        # Get the proof state after the tactic
        char_pos = len(tactic)
        goals_result = await self._get_goals_at(tactic_line, char_pos)

        goals_data = goals_result.get("goals")
        if goals_data is None:
            # Proof might be complete — no goals field means Qed-like state
            return ProofState(
                schema_version=1,
                session_id="",
                step_index=0,
                is_complete=True,
                focused_goal_index=None,
                goals=[],
            )

        return self._translate_goals(goals_data)

    async def get_current_state(self) -> ProofState:
        if not self._working_tactics:
            # At initial state — query after preamble
            preamble_lines = self._working_preamble.splitlines()
            query_line = len(preamble_lines) - 1
            char_pos = len(preamble_lines[-1]) if preamble_lines else 0
        else:
            # Query after last tactic
            tactic_line = len(self._working_preamble.splitlines()) + len(self._working_tactics) - 1
            query_line = tactic_line
            char_pos = len(self._working_tactics[-1])

        goals_result = await self._get_goals_at(query_line, char_pos)
        goals_data = goals_result.get("goals")
        if goals_data is None:
            return ProofState(
                schema_version=1, session_id="", step_index=0,
                is_complete=True, focused_goal_index=None, goals=[],
            )
        return self._translate_goals(goals_data)

    async def undo(self) -> None:
        if not self._working_tactics:
            return

        self._working_tactics.pop()
        self._tactic_count = max(0, self._tactic_count - 1)

        new_text = self._working_preamble + "\n"
        if self._working_tactics:
            new_text += "\n".join(self._working_tactics) + "\n"
        await self._change_document(self._doc_uri, new_text)
        self._doc_text = new_text
        await self._wait_for_diagnostics(self._doc_uri)

    async def get_premises_at_step(self, step: int) -> list[dict[str, str]]:
        """Extract premises used at a tactic step.

        Uses a heuristic approach: run the proof up to the step, then
        use Coq's 'Show Proof.' to get the partial proof term and diff
        against the previous step's proof term.

        For now, uses a simpler approach: examine the tactic string for
        referenced lemma names and classify them via About queries.
        """
        if step < 1 or step > len(self.original_script):
            return []

        tactic = self.original_script[step - 1]

        # Build document up to step, add "Show Proof." to get term info
        tactics_up_to = self.original_script[:step]
        show_proof_doc = (
            self._working_preamble + "\n"
            + "\n".join(tactics_up_to) + "\n"
            + "Show Proof.\n"
        )

        # Use a separate synthetic document for premise queries
        query_uri = f"file:///tmp/wily_premise_query_{step}.v"
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": query_uri,
                    "languageId": "coq",
                    "version": 1,
                    "text": show_proof_doc,
                },
            },
        )
        await self._wait_for_diagnostics(query_uri)

        # Get the Show Proof output (messages at the Show Proof line)
        show_line = len(self._working_preamble.splitlines()) + len(tactics_up_to)
        goals_result = await self._send_request(
            "proof/goals",
            {
                "textDocument": {"uri": query_uri},
                "position": {"line": show_line, "character": 0},
            },
        )

        # Also get the previous step's proof term for diffing
        prev_terms: set[str] = set()
        if step > 1:
            prev_doc = (
                self._working_preamble + "\n"
                + "\n".join(self.original_script[:step - 1]) + "\n"
                + "Show Proof.\n"
            )
            prev_uri = f"file:///tmp/wily_premise_prev_{step}.v"
            await self._send_notification(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": prev_uri,
                        "languageId": "coq",
                        "version": 1,
                        "text": prev_doc,
                    },
                },
            )
            await self._wait_for_diagnostics(prev_uri)
            prev_show_line = len(self._working_preamble.splitlines()) + step - 1
            prev_result = await self._send_request(
                "proof/goals",
                {
                    "textDocument": {"uri": prev_uri},
                    "position": {"line": prev_show_line, "character": 0},
                },
            )
            prev_messages = prev_result.get("messages", [])
            for m in prev_messages:
                if m.get("level", 3) != 1:
                    prev_terms.update(_extract_qualified_names(m.get("text", "")))
            await self._send_notification(
                "textDocument/didClose",
                {"textDocument": {"uri": prev_uri}},
            )

        # Extract premises from Show Proof output
        messages = goals_result.get("messages", [])
        current_terms: set[str] = set()
        for m in messages:
            if m.get("level", 3) != 1:
                current_terms.update(_extract_qualified_names(m.get("text", "")))

        # New terms = premises introduced by this tactic
        new_terms = current_terms - prev_terms

        # Also parse the tactic itself for explicit references
        tactic_refs = _extract_qualified_names(tactic)
        new_terms.update(tactic_refs)

        await self._send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": query_uri}},
        )

        # Classify each premise
        premises = []
        for name in sorted(new_terms):
            # Skip common non-premise names
            if name in ("Proof", "Qed", "Defined", "Admitted"):
                continue
            kind = await self._classify_premise(name)
            if kind:
                premises.append({"name": name, "kind": kind})

        return premises

    async def _classify_premise(self, name: str) -> Optional[str]:
        """Classify a premise name via About query.

        Uses the working preamble (which includes Require Import lines)
        so that short names like Nat.add_comm resolve correctly.
        """
        query_uri = f"file:///tmp/wily_about_{id(name)}.v"
        # Include the preamble up to (but not including) Proof. so that
        # Require Import statements are in scope for the About query.
        preamble_lines = self._working_preamble.splitlines()
        # Remove the trailing "Proof." line to avoid opening a proof context
        context_lines = [l for l in preamble_lines if not re.match(r"\s*Proof\b", l)]
        text = "\n".join(context_lines) + f"\nAbout {name}."
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": query_uri,
                    "languageId": "coq",
                    "version": 1,
                    "text": text,
                },
            },
        )
        diags = await self._wait_for_diagnostics(query_uri)

        # Get About output — at the last line (where the About command is)
        about_line = len(text.splitlines()) - 1
        result = await self._send_request(
            "proof/goals",
            {
                "textDocument": {"uri": query_uri},
                "position": {"line": about_line, "character": 0},
            },
        )

        await self._send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": query_uri}},
        )

        # Check for errors
        if any(d.get("severity") == 1 for d in diags):
            return None

        messages = result.get("messages", [])
        about_text = "\n".join(m.get("text", "") for m in messages if m.get("level", 3) != 1)

        # Rocq 9.x: "Expands to: Constant ..."
        if "Constant" in about_text:
            # Check if it's a lemma/theorem vs definition
            if any(kw in about_text.lower() for kw in ("lemma", "theorem", "proposition", "corollary")):
                return "lemma"
            return "lemma"  # Most constants used as premises are lemmas
        if "Inductive" in about_text:
            return "constructor"

        # Coq <=8.x: "X is a Lemma/Definition/..."
        about_lower = about_text.lower()
        if "lemma" in about_lower or "theorem" in about_lower:
            return "lemma"
        if "definition" in about_lower:
            return "definition"
        if "constructor" in about_lower:
            return "constructor"

        # Default for known names
        if about_text:
            return "lemma"
        return None

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
# Utility functions
# ------------------------------------------------------------------

# Regex for qualified Coq names (e.g., Coq.Arith.PeanoNat.Nat.add_comm)
_QUALIFIED_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b")


def _extract_qualified_names(text: str) -> set[str]:
    """Extract fully qualified Coq names from text."""
    return set(_QUALIFIED_NAME_RE.findall(text))


# ------------------------------------------------------------------
# Factory (§4.2)
# ------------------------------------------------------------------


async def create_coq_backend(file_path: str) -> CoqProofBackend:
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

    backend = CoqProofBackend(proc)

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
