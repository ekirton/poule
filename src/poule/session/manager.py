"""Proof Session Manager.

Stateful component managing interactive proof sessions per
specification/proof-session.md.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Coroutine, Optional

from poule.session.errors import (
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
from poule.session.types import (
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


class SessionManager:
    """Manages interactive proof sessions."""

    def __init__(self, backend_factory: Callable) -> None:
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
        async with self._registry_lock:
            ss = self._registry.pop(session_id, None)
        if ss is None:
            raise SessionError(SESSION_NOT_FOUND, session_id)
        if ss.state == "active" and ss.coq_backend is not None:
            await ss.coq_backend.shutdown()

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
            try:
                new_state = await ss.coq_backend.execute_tactic(tactic)
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
                    self._expired_ids.add(sid)
                    if ss.coq_backend is not None and ss.state == "active":
                        await ss.coq_backend.shutdown()

    # -------------------------------------------------------------------
    # §4.6 Crash Detection (test helpers)
    # -------------------------------------------------------------------

    def _mark_crashed(self, session_id: str) -> None:
        ss = self._registry.get(session_id)
        if ss is not None:
            ss.state = "crashed"
            ss.coq_backend = None

    def _set_last_active(self, session_id: str, dt: datetime) -> None:
        ss = self._registry.get(session_id)
        if ss is not None:
            ss.last_active_at = dt


# Alias used by some component tests.
ProofSessionManager = SessionManager
