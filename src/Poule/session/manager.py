"""Proof Session Manager.

Stateful component managing interactive proof sessions per
specification/proof-session.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

from Poule.session.errors import (
    BACKEND_CRASHED,
    FILE_NOT_FOUND,
    NO_PREVIOUS_STATE,
    PROOF_COMPLETE,
    PROOF_NOT_FOUND,
    SESSION_EXPIRED,
    SESSION_NOT_FOUND,
    STEP_OUT_OF_RANGE,
    TACTIC_ERROR,
    SessionError,
)
from Poule.session.types import (
    Goal,
    Hypothesis,
    Premise,
    PremiseAnnotation,
    ProofState,
    ProofTrace,
    Session,
    TraceStep,
)

TIMEOUT_MINUTES = 30

# Matches Require/Import/Export lines (possibly preceded by From ... ).
_IMPORT_RE = re.compile(
    r"^\s*(From\s+\S+\s+)?(Require|Import|Export)\b[^.]*\.",
    re.MULTILINE,
)


def _extract_imports(file_path: str) -> str:
    """Extract Require/Import lines from a .v file to use as coqtop prelude."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (OSError, FileNotFoundError):
        return ""
    matches = _IMPORT_RE.findall(text)
    if not matches:
        # Fall back to line-by-line scan for robustness
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"(From\s|Require\s|Import\s|Export\s)", stripped):
                lines.append(stripped)
        return "\n".join(lines)
    # Use finditer for full match strings
    return "\n".join(m.group(0) for m in _IMPORT_RE.finditer(text))


def _normalize_session_id(session_id):
    """Extract the string session ID if a tuple (id, state) was passed."""
    if isinstance(session_id, tuple):
        return session_id[0]
    return session_id


@dataclass
class _SessionState:
    """Internal per-session state (not exposed directly to callers)."""

    session_id: str
    file_path: str
    proof_name: str
    state: str  # "active" or "crashed"
    current_step: int
    total_steps: Optional[int]
    step_history: list[ProofState]
    original_script: list[str]
    coq_backend: Any  # CoqBackend protocol
    created_at: datetime
    last_active_at: datetime
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    coqtop_proc: Optional[Any] = None  # asyncio.subprocess.Process for vernacular sessions


class SessionManager:
    """Manages interactive proof sessions."""

    def __init__(self, backend_factory: Callable | None = None) -> None:
        if backend_factory is None:
            from Poule.session.backend import create_coq_backend
            backend_factory = create_coq_backend
        self._backend_factory = backend_factory
        self._registry: dict[str, _SessionState] = {}
        self._registry_lock = asyncio.Lock()
        self._expired_ids: set[str] = set()

    # -------------------------------------------------------------------
    # §4.1 Session Registry
    # -------------------------------------------------------------------

    async def create_session(
        self, file_path: str, proof_name: str,
    ) -> tuple[str, ProofState]:
        backend = await self._backend_factory(file_path)
        try:
            await backend.load_file(file_path)
        except (FileNotFoundError, OSError):
            await backend.shutdown()
            raise SessionError(FILE_NOT_FOUND, f"File not found: {file_path}")

        try:
            initial_state = await backend.position_at_proof(proof_name)
        except (ValueError, KeyError, LookupError):
            await backend.shutdown()
            raise SessionError(PROOF_NOT_FOUND, f"Proof not found: {proof_name}")

        session_id = uuid.uuid4().hex
        original_script = getattr(backend, "original_script", []) or []
        total_steps = len(original_script) if original_script else None
        now = datetime.now(timezone.utc)

        # Stamp the session_id onto the initial state
        initial_state = ProofState(
            schema_version=initial_state.schema_version,
            session_id=session_id,
            step_index=initial_state.step_index,
            is_complete=initial_state.is_complete,
            focused_goal_index=initial_state.focused_goal_index,
            goals=initial_state.goals,
        )

        ss = _SessionState(
            session_id=session_id,
            file_path=file_path,
            proof_name=proof_name,
            state="active",
            current_step=0,
            total_steps=total_steps,
            step_history=[initial_state],
            original_script=original_script,
            coq_backend=backend,
            created_at=now,
            last_active_at=now,
        )

        async with self._registry_lock:
            self._registry[session_id] = ss

        return session_id, initial_state

    async def close_session(self, session_id: str) -> None:
        session_id = _normalize_session_id(session_id)
        async with self._registry_lock:
            ss = self._registry.pop(session_id, None)
        if ss is None:
            raise SessionError(SESSION_NOT_FOUND, session_id)
        if ss.state == "active" and ss.coq_backend is not None:
            await ss.coq_backend.shutdown()
        if ss.coqtop_proc is not None:
            try:
                ss.coqtop_proc.stdin.close()  # type: ignore[union-attr]
                ss.coqtop_proc.kill()
                await ss.coqtop_proc.wait()
            except Exception:
                pass

    async def list_sessions(self) -> list[Session]:
        result = []
        for ss in list(self._registry.values()):
            if ss.state != "active":
                continue
            result.append(Session(
                session_id=ss.session_id,
                file_path=ss.file_path,
                proof_name=ss.proof_name,
                current_step=ss.current_step,
                total_steps=ss.total_steps,
                created_at=ss.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                last_active_at=ss.last_active_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ))
        return result

    async def lookup_session(self, session_id: str) -> _SessionState:
        session_id = _normalize_session_id(session_id)
        if session_id in self._expired_ids:
            raise SessionError(SESSION_EXPIRED, session_id)
        ss = self._registry.get(session_id)
        if ss is None:
            raise SessionError(SESSION_NOT_FOUND, session_id)
        if ss.state == "crashed":
            raise SessionError(BACKEND_CRASHED, session_id)
        ss.last_active_at = datetime.now(timezone.utc)
        return ss

    # -------------------------------------------------------------------
    # §4.2 State Observation
    # -------------------------------------------------------------------

    async def observe_state(self, session_id: str) -> ProofState:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            return ss.step_history[ss.current_step]

    async def get_state_at_step(self, session_id: str, step: int) -> ProofState:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            return await self._get_state_at_step_locked(ss, step)

    async def _get_state_at_step_locked(
        self, ss: _SessionState, step: int,
    ) -> ProofState:
        max_step = ss.total_steps if ss.total_steps is not None else ss.current_step
        if step < 0 or step > max_step:
            raise SessionError(
                STEP_OUT_OF_RANGE,
                f"Step {step} out of range [0, {max_step}]",
            )
        # Replay if needed
        await self._materialize_through(ss, step)
        return ss.step_history[step]

    async def _materialize_through(self, ss: _SessionState, step: int) -> None:
        """Ensure step_history is populated through the given step."""
        while len(ss.step_history) <= step:
            next_idx = len(ss.step_history)
            if next_idx > len(ss.original_script):
                break
            tactic = ss.original_script[next_idx - 1]
            new_state = await ss.coq_backend.execute_tactic(tactic)
            new_state = ProofState(
                schema_version=new_state.schema_version,
                session_id=ss.session_id,
                step_index=next_idx,
                is_complete=new_state.is_complete,
                focused_goal_index=new_state.focused_goal_index,
                goals=new_state.goals,
            )
            ss.step_history.append(new_state)

    async def extract_trace(self, session_id: str) -> ProofTrace:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            if ss.total_steps is None:
                raise SessionError(
                    STEP_OUT_OF_RANGE,
                    "No original script to trace",
                )
            await self._materialize_through(ss, ss.total_steps)
            steps = []
            for i in range(ss.total_steps + 1):
                tactic = None if i == 0 else ss.original_script[i - 1]
                steps.append(TraceStep(
                    step_index=i,
                    tactic=tactic,
                    state=ss.step_history[i],
                ))
            return ProofTrace(
                schema_version=1,
                session_id=ss.session_id,
                proof_name=ss.proof_name,
                file_path=ss.file_path,
                total_steps=ss.total_steps,
                steps=steps,
            )

    # -------------------------------------------------------------------
    # §4.3 Tactic Dispatch
    # -------------------------------------------------------------------

    async def submit_tactic(self, session_id: str, tactic: str) -> ProofState:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            # Petanque/run requires tactic sentences to end with a period.
            tac = tactic.rstrip()
            if not tac.endswith("."):
                tac += "."
            try:
                new_state = await ss.coq_backend.execute_tactic(tac)
            except Exception as e:
                raise SessionError(TACTIC_ERROR, str(e))

            # Truncate forward history
            ss.step_history = ss.step_history[: ss.current_step + 1]
            ss.current_step += 1
            new_state = ProofState(
                schema_version=new_state.schema_version,
                session_id=ss.session_id,
                step_index=ss.current_step,
                is_complete=new_state.is_complete,
                focused_goal_index=new_state.focused_goal_index,
                goals=new_state.goals,
            )
            ss.step_history.append(new_state)
            return new_state

    async def step_forward(self, session_id: str) -> tuple[str, ProofState]:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            if ss.total_steps is None or ss.current_step >= ss.total_steps:
                raise SessionError(PROOF_COMPLETE, "No more steps")

            tactic = ss.original_script[ss.current_step]
            new_state = await ss.coq_backend.execute_tactic(tactic)
            ss.current_step += 1
            new_state = ProofState(
                schema_version=new_state.schema_version,
                session_id=ss.session_id,
                step_index=ss.current_step,
                is_complete=new_state.is_complete,
                focused_goal_index=new_state.focused_goal_index,
                goals=new_state.goals,
            )
            # Extend step_history if needed
            if len(ss.step_history) <= ss.current_step:
                ss.step_history.append(new_state)
            else:
                ss.step_history[ss.current_step] = new_state
            return tactic, new_state

    async def step_backward(self, session_id: str) -> ProofState:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            if ss.current_step == 0:
                raise SessionError(NO_PREVIOUS_STATE, "Already at initial state")
            ss.current_step -= 1
            try:
                await ss.coq_backend.undo()
            except Exception:
                pass  # Backend-dependent; best-effort
            return ss.step_history[ss.current_step]

    async def submit_tactic_batch(
        self, session_id: str, tactics: list[str],
    ) -> list[dict]:
        if not tactics:
            return []
        ss = await self.lookup_session(session_id)
        results: list[dict] = []
        async with ss.lock:
            for tactic in tactics:
                try:
                    new_state = await ss.coq_backend.execute_tactic(tactic)
                except Exception as e:
                    results.append({
                        "tactic": tactic,
                        "error": str(e),
                        "state": None,
                    })
                    break

                ss.step_history = ss.step_history[: ss.current_step + 1]
                ss.current_step += 1
                new_state = ProofState(
                    schema_version=new_state.schema_version,
                    session_id=ss.session_id,
                    step_index=ss.current_step,
                    is_complete=new_state.is_complete,
                    focused_goal_index=new_state.focused_goal_index,
                    goals=new_state.goals,
                )
                ss.step_history.append(new_state)
                results.append({
                    "tactic": tactic,
                    "state": new_state,
                    "error": None,
                })
                if new_state.is_complete:
                    break
        return results

    # -------------------------------------------------------------------
    # §4.4 Premise Extraction
    # -------------------------------------------------------------------

    async def get_premises(self, session_id: str) -> list[PremiseAnnotation]:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            if ss.total_steps is None:
                raise SessionError(
                    STEP_OUT_OF_RANGE,
                    "No original script for premise extraction",
                )
            await self._materialize_through(ss, ss.total_steps)
            annotations = []
            for k in range(1, ss.total_steps + 1):
                raw = await ss.coq_backend.get_premises_at_step(k)
                premises = [
                    Premise(name=p["name"], kind=p["kind"]) for p in raw
                ]
                annotations.append(PremiseAnnotation(
                    step_index=k,
                    tactic=ss.original_script[k - 1],
                    premises=premises,
                ))
            return annotations

    async def get_step_premises(
        self, session_id: str, step: int,
    ) -> PremiseAnnotation:
        ss = await self.lookup_session(session_id)
        async with ss.lock:
            if ss.total_steps is None:
                raise SessionError(STEP_OUT_OF_RANGE, "No original script")
            if step < 1 or step > ss.total_steps:
                raise SessionError(
                    STEP_OUT_OF_RANGE,
                    f"Premise step {step} out of range [1, {ss.total_steps}]",
                )
            await self._materialize_through(ss, step)
            raw = await ss.coq_backend.get_premises_at_step(step)
            premises = [
                Premise(name=p["name"], kind=p["kind"]) for p in raw
            ]
            return PremiseAnnotation(
                step_index=step,
                tactic=ss.original_script[step - 1],
                premises=premises,
            )

    # -------------------------------------------------------------------
    # §4.5 Session Timeout
    # -------------------------------------------------------------------

    async def _sweep_timeouts(self) -> None:
        now = datetime.now(timezone.utc)
        to_remove = []
        for sid, ss in list(self._registry.items()):
            if now - ss.last_active_at > timedelta(minutes=TIMEOUT_MINUTES):
                to_remove.append(sid)
        async with self._registry_lock:
            for sid in to_remove:
                ss = self._registry.pop(sid, None)
                if ss is not None:
                    idle_duration = now - ss.last_active_at
                    logger.info(
                        "Session timed out: session_id=%s proof_name=%s idle_duration=%s",
                        sid,
                        ss.proof_name,
                        idle_duration,
                    )
                    self._expired_ids.add(sid)
                    if ss.coq_backend is not None and ss.state == "active":
                        await ss.coq_backend.shutdown()
                    if ss.coqtop_proc is not None:
                        try:
                            ss.coqtop_proc.kill()
                            await ss.coqtop_proc.wait()
                        except Exception:
                            pass

    # -------------------------------------------------------------------
    # §4.6 Crash Detection (test helpers)
    # -------------------------------------------------------------------

    def _mark_crashed(self, session_id: str) -> None:
        ss = self._registry.get(session_id)
        if ss is not None:
            ss.state = "crashed"
            ss.coq_backend = None

    async def _on_backend_crash(
        self,
        session_id: str,
        exit_code: int | None = None,
        signal: int | None = None,
    ) -> None:
        """Record a backend crash: mark session crashed and log required fields.

        Spec §4.7: Log session ID, exit code, and signal (if available).
        """
        logger.warning(
            "Backend crashed: session_id=%s exit_code=%s signal=%s",
            session_id,
            exit_code,
            signal,
        )
        self._mark_crashed(session_id)

    def _set_last_active(self, session_id: str, dt: datetime) -> None:
        ss = self._registry.get(session_id)
        if ss is not None:
            ss.last_active_at = dt

    # -------------------------------------------------------------------
    # §4.7 Vernacular / Interactive Sessions
    # -------------------------------------------------------------------

    _SENTINEL = "__POULE_SENTINEL_END__"

    async def open_session(self, name: str) -> str:
        """Open a coqtop-based interactive session for arbitrary vernacular commands.

        Returns a session_id. The session is backed by a persistent coqtop
        subprocess (not coq-lsp), suitable for commands like Print Assumptions,
        About, Require Import, etc.
        """
        proc = await asyncio.create_subprocess_exec(
            "coqtop", "-quiet",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Read any initial output from coqtop (it may print a welcome line
        # even with -quiet in some versions). Use sentinel to drain.
        sentinel_cmd = f'Check {self._SENTINEL}.\n'
        proc.stdin.write(sentinel_cmd.encode("utf-8"))  # type: ignore[union-attr]
        await proc.stdin.drain()  # type: ignore[union-attr]
        await self._read_until_sentinel(proc)

        session_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        ss = _SessionState(
            session_id=session_id,
            file_path="",
            proof_name="",
            state="active",
            current_step=0,
            total_steps=None,
            step_history=[],
            original_script=[],
            coq_backend=None,
            created_at=now,
            last_active_at=now,
            coqtop_proc=proc,
        )

        async with self._registry_lock:
            self._registry[session_id] = ss

        return session_id

    async def _read_until_sentinel(
        self, proc: Any, timeout: float = 30.0,
    ) -> str:
        """Read coqtop stdout until the sentinel string appears.

        Returns everything before the sentinel error block.  The sentinel
        is triggered by ``Check <SENTINEL>.`` which produces a multi-line
        error.  We strip the entire error block (starting from the
        ``Toplevel input`` line that references the Check command).
        """
        output_lines: list[str] = []
        stdout = proc.stdout  # type: ignore[union-attr]
        try:
            while True:
                line_bytes = await asyncio.wait_for(
                    stdout.readline(), timeout=timeout,
                )
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                if self._SENTINEL in line:
                    # Consume remaining lines of the error block
                    # (the "Error:" line and any trailing blank / prompt lines).
                    try:
                        while True:
                            rest = await asyncio.wait_for(
                                stdout.readline(), timeout=2.0,
                            )
                            if not rest:
                                break
                            rest_s = rest.decode("utf-8", errors="replace")
                            # Stop once we hit the next prompt or EOF
                            if rest_s.strip() == "" or rest_s.strip().endswith("<"):
                                break
                    except asyncio.TimeoutError:
                        pass
                    break
                output_lines.append(line)
        except asyncio.TimeoutError:
            pass
        # Strip any trailing sentinel error preamble lines that appeared
        # before the sentinel name itself (e.g. "Toplevel input, ..." and
        # the caret line).
        while output_lines and (
            "Toplevel input" in output_lines[-1]
            or output_lines[-1].strip().startswith(">")
            or output_lines[-1].strip().startswith("^")
        ):
            output_lines.pop()
        return "".join(output_lines).strip()

    async def _ensure_coqtop(self, ss: _SessionState) -> Any:
        """Lazily spawn a coqtop process for vernacular commands.

        For proof sessions backed by coq-lsp, coq-lsp cannot capture
        the output of Print/Check/About commands (it only exposes
        diagnostics, not query results).  We spawn a coqtop subprocess
        on first use, loading the file's imports so queries execute in
        the correct context.
        """
        if ss.coqtop_proc is not None:
            return ss.coqtop_proc

        proc = await asyncio.create_subprocess_exec(
            "coqtop", "-quiet",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Drain any welcome output
        sentinel_cmd = f'Check {self._SENTINEL}.\n'
        proc.stdin.write(sentinel_cmd.encode("utf-8"))  # type: ignore[union-attr]
        await proc.stdin.drain()  # type: ignore[union-attr]
        await self._read_until_sentinel(proc)

        # Load the file's imports so queries have the right context.
        if ss.file_path:
            prelude = _extract_imports(ss.file_path)
            if prelude:
                proc.stdin.write((prelude + "\n").encode("utf-8"))  # type: ignore[union-attr]
                proc.stdin.write(sentinel_cmd.encode("utf-8"))  # type: ignore[union-attr]
                await proc.stdin.drain()  # type: ignore[union-attr]
                await self._read_until_sentinel(proc)

        ss.coqtop_proc = proc
        return proc

    async def send_command(
        self, session_id: str, command: str, *, prefer_coqtop: bool = False,
    ) -> str:
        """Send a vernacular command to a session and return the output.

        Args:
            session_id: Target session.
            command: Vernacular command string.
            prefer_coqtop: If True and the session is backed by coq-lsp,
                lazily spawn a coqtop process for this command.  coq-lsp
                cannot capture output of Print/Check/About, so callers
                that need introspection output should set this flag.
        """
        ss = await self.lookup_session(session_id)

        async with ss.lock:
            if prefer_coqtop and ss.coqtop_proc is None and ss.coq_backend is not None:
                try:
                    await self._ensure_coqtop(ss)
                except (OSError, FileNotFoundError):
                    logger.warning("coqtop not available, falling back to coq-lsp")
                    return await ss.coq_backend.execute_vernacular(command)

            proc = ss.coqtop_proc
            if proc is None:
                # Fall back to coq_backend if available
                if ss.coq_backend is not None:
                    return await ss.coq_backend.execute_vernacular(command)
                raise SessionError(
                    BACKEND_CRASHED,
                    "Session has no interactive backend",
                )

            # Send the user command followed by a sentinel
            cmd_text = command.rstrip()
            if not cmd_text.endswith("."):
                cmd_text += "."
            sentinel_cmd = f'Check {self._SENTINEL}.\n'

            proc.stdin.write((cmd_text + "\n").encode("utf-8"))  # type: ignore[union-attr]
            proc.stdin.write(sentinel_cmd.encode("utf-8"))  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]

            output = await self._read_until_sentinel(proc)
            return output

    async def submit_vernacular(self, session_id: str, vernacular: str) -> str:
        """Send a vernacular introspection command, preferring coqtop for output capture.

        Used by coq_query handler.  coq-lsp cannot capture Print/Check/About
        output, so this method prefers coqtop when available.
        """
        return await self.send_command(session_id, vernacular, prefer_coqtop=True)

    async def execute_vernacular(self, session_id: str, command: str) -> str:
        """Alias for send_command. Used by poule.typeclass.debugging."""
        return await self.send_command(session_id, command)

    async def submit_command(self, session_id: str, command: str) -> str:
        """Send a vernacular command, routing through coqtop for output capture.

        Spec §4.4: submit_command routes through a coqtop subprocess
        (not the session's CoqBackend) because coq-lsp cannot capture
        vernacular output. See §4.4.1.
        """
        return await self.send_command(session_id, command, prefer_coqtop=True)

    async def coq_query(self, session_id: str, command: str) -> str:
        """Alias for send_command. Used by poule.universe modules."""
        return await self.send_command(session_id, command)

    async def query_declaration_kind(self, session_id: str, name: str) -> str:
        """Execute ``About <name>.`` and parse the output to extract the declaration kind.

        Returns one of: "Axiom", "Parameter", "Lemma", "Theorem",
        "Definition", "Opaque", "Transparent", etc.
        """
        output = await self.send_command(session_id, f"About {name}.", prefer_coqtop=True)

        # coqtop About output examples:
        #   "classic : forall P : Prop, P \/ ~ P\n\nclassic is an axiom"
        #   "trivial_lemma : True\n\ntrivial_lemma is defined"  (with Qed -> opaque)
        #   "Nat.add : nat -> nat -> nat\n\nNat.add is recursively defined"
        lower = output.lower()

        # Check for "is an axiom" / "is a parameter"
        if re.search(r"\bis an axiom\b", lower):
            return "Axiom"
        if re.search(r"\bis a parameter\b", lower):
            return "Parameter"

        # "is defined" with opacity check
        # Opaque = proved with Qed (no body visible)
        if re.search(r"\bis defined\b", lower):
            # Check if About says it's opaque
            if "opaque" in lower:
                return "Opaque"
            return "Definition"

        # "is transparent" or "is not universe polymorphic"
        if "transparent" in lower:
            return "Transparent"

        # "X is a ... (opaque)" pattern
        if "opaque" in lower:
            return "Opaque"

        # Coq 8.19+: "Expands to: <Kind> <path>" line
        if "expands to: constant" in lower:
            # Reached here means no opacity/transparency markers → axiom
            return "Axiom"
        if "expands to: inductive" in lower:
            return "Inductive"

        # Coq 8.18+ / Rocq: "About" output may say things like:
        # "trivial_lemma is a lemma." or use different wording.
        # Try to match "is a <kind>" (require article to avoid "is not ...")
        kind_match = re.search(r"\bis (?:a |an )(\w+)", lower)
        if kind_match:
            kind_word = kind_match.group(1)
            kind_map = {
                "axiom": "Axiom",
                "parameter": "Parameter",
                "lemma": "Lemma",
                "theorem": "Theorem",
                "definition": "Definition",
                "corollary": "Corollary",
                "proposition": "Proposition",
                "fact": "Fact",
                "remark": "Remark",
                "instance": "Instance",
                "fixpoint": "Fixpoint",
                "cofixpoint": "CoFixpoint",
            }
            return kind_map.get(kind_word, kind_word.capitalize())

        return "Unknown"

    async def observe_proof_state(self, session_id: str) -> ProofState:
        """Alias for observe_state. Used by poule.hammer.engine."""
        return await self.observe_state(session_id)


# Alias used by some component tests.
ProofSessionManager = SessionManager
