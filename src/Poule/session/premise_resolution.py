"""Premise resolution via proof term diffing.

Extracts the constants (lemmas, definitions, constructors) that each
tactic step actually referenced by diffing partial proof terms obtained
from Coq's `Show Proof.` command.

See specification/coq-proof-backend.md §4.1 and
doc/architecture/extraction-campaign.md (Premise Resolution section).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)


# Match global constant references in Show Proof. output (with Set Printing All):
# - @Qualified.Name (e.g., @Nat.add_comm)
# - @name (e.g., @eq_refl — unqualified but @ marks it as global)
# The @ prefix is required to distinguish globals from local variables.
_CONST_PATTERN = re.compile(r"@([A-Za-z_][A-Za-z0-9_.']*)")


def extract_constants_from_proof_term(proof_term_text: str) -> set[str]:
    """Extract fully qualified constant names from a Show Proof. output.

    Returns a set of names like {"Nat.add_comm", "Coq.Init.Logic.eq_refl"}.
    Local variables, de Bruijn indices, and ?Goal placeholders are excluded.
    """
    if not proof_term_text:
        return set()
    return set(_CONST_PATTERN.findall(proof_term_text))


def resolve_step_premises(
    step: int,
    previous_constants: set[str],
    current_proof_term_text: str,
) -> list[dict[str, str]]:
    """Determine which constants a tactic step introduced.

    Diffs the constants in the current proof term against those from
    the previous step. New constants are the premises this tactic used.

    Returns a list of {"name": str, "kind": "lemma"} dicts.
    """
    current_constants = extract_constants_from_proof_term(current_proof_term_text)
    new_constants = current_constants - previous_constants
    return [{"name": name, "kind": "lemma"} for name in sorted(new_constants)]


# ---------------------------------------------------------------------------
# ProofTermResolver — coqtop subprocess for Show Proof. queries
# ---------------------------------------------------------------------------

_SENTINEL = "__POULE_PREMISE_SENTINEL__"


class ProofTermResolver:
    """Manages a coqtop subprocess for proof-term-based premise resolution.

    Spawned once per source file (alongside the coq-lsp backend). For each
    proof, replays tactics and queries `Show Proof.` after each step to
    capture the partial proof term. Constants are extracted and diffed to
    determine which premises each tactic step introduced.
    """

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._loaded_file: str | None = None

    async def start(self, load_paths: list[tuple[str, str]] | None = None):
        """Spawn a coqtop subprocess."""
        args = ["coqtop", "-quiet"]
        for directory, prefix in (load_paths or []):
            args.extend(["-R", directory, prefix])
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        # Drain any startup output (deprecation warnings, etc.)
        # Send sentinel directly (not via _send_and_read which adds another)
        self._proc.stdin.write(f"Check {_SENTINEL}.\n".encode("utf-8"))
        await self._proc.stdin.drain()
        await self._read_until_sentinel()
        # Set Printing All makes all global references explicit with @
        await self._send_and_read("Set Printing All.")

    async def load_file(self, file_path: str, proof_name: str):
        """Load file context into coqtop up to the target proof.

        Sends all Require/Import lines plus definitions preceding the
        proof, so the proof's context is available.
        """
        if self._proc is None:
            return
        prelude = _extract_prelude_up_to_proof(file_path, proof_name)
        if prelude:
            await self._send_and_read(prelude)
        self._loaded_file = file_path

    async def enter_proof(self, proof_name: str):
        """Enter proof mode for the named theorem.

        Sends the theorem statement followed by 'Proof.' to coqtop.
        """
        if self._proc is None:
            return
        # The prelude already loaded everything up to (but not including)
        # the proof. Now we need to send the theorem statement + Proof.
        stmt = _extract_theorem_statement(self._loaded_file or "", proof_name)
        if stmt:
            await self._send_and_read(stmt)
            await self._send_and_read("Proof.")

    async def get_proof_term(self) -> str:
        """Execute Show Proof. and return the proof term text."""
        if self._proc is None:
            return ""
        return await self._send_and_read("Show Proof.")

    async def execute_tactic(self, tactic: str) -> bool:
        """Execute a tactic in coqtop. Returns True on success."""
        if self._proc is None:
            return False
        result = await self._send_and_read(tactic)
        # coqtop prints "Error:" on failure
        return "Error:" not in result

    async def abort_proof(self):
        """Abort the current proof to prepare for the next one."""
        if self._proc is None:
            return
        await self._send_and_read("Abort.")

    async def resolve_proof_premises(
        self, proof_name: str, tactic_script: list[str],
        goal_type: str | None = None,
    ) -> list[list[dict[str, str]]]:
        """Resolve per-step premises for an entire proof.

        Args:
            proof_name: Theorem name (for logging).
            tactic_script: List of tactic strings to replay.
            goal_type: The initial goal type. If provided, enters proof mode
                via `Goal <type>. Proof.` instead of finding the theorem statement.

        Returns a list aligned with tactic_script: element i contains
        the premises tactic i introduced (typically 1-5 items).
        On failure, returns empty lists for remaining steps.
        """
        if self._proc is None:
            return [[] for _ in tactic_script]

        try:
            if goal_type:
                await self._send_and_read(f"Goal {goal_type}.")
                await self._send_and_read("Proof.")
            else:
                await self.enter_proof(proof_name)
        except Exception:
            logger.debug("Failed to enter proof %s in coqtop", proof_name)
            return [[] for _ in tactic_script]

        # Get initial proof term (before any tactic)
        initial_term = await self.get_proof_term()
        prev_constants = extract_constants_from_proof_term(initial_term)

        per_step_premises: list[list[dict[str, str]]] = []
        for i, tactic in enumerate(tactic_script):
            success = await self.execute_tactic(tactic)
            if not success:
                logger.debug(
                    "Tactic %d failed in coqtop for %s: %s",
                    i + 1, proof_name, tactic[:80],
                )
                # Fill remaining with empty
                per_step_premises.extend(
                    [] for _ in range(len(tactic_script) - i)
                )
                break

            current_term = await self.get_proof_term()
            current_constants = extract_constants_from_proof_term(current_term)
            new_constants = current_constants - prev_constants
            per_step_premises.append(
                [{"name": n, "kind": "lemma"} for n in sorted(new_constants)]
            )
            prev_constants = current_constants

        try:
            await self.abort_proof()
        except Exception:
            pass

        return per_step_premises

    async def shutdown(self):
        """Kill the coqtop subprocess."""
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.kill()
                await self._proc.wait()
            except Exception:
                pass
            self._proc = None

    async def _send_and_read(self, command: str) -> str:
        """Send a command to coqtop and read output until sentinel.

        Writes to stdin without awaiting drain(), then reads stdout.
        The event loop flushes the stdin write buffer while we await
        readline(), preventing pipe deadlocks on large commands.
        """
        if self._proc is None or self._proc.stdin is None:
            return ""
        sentinel_cmd = f"Check {_SENTINEL}.\n"
        if not command.endswith("\n"):
            command = command + "\n"
        self._proc.stdin.write(
            (command + sentinel_cmd).encode("utf-8")
        )
        # Do NOT await drain() — the event loop flushes stdin while we
        # read stdout below, preventing pipe deadlocks on large commands.
        return await self._read_until_sentinel()

    async def _read_until_sentinel(
        self, timeout: float = 30.0, max_wait: float = 300.0,
    ) -> str:
        """Read coqtop stdout until the sentinel appears.

        coqtop prefixes output with prompts like 'Rocq < ' or 'name < '.
        We strip these prefixes and collect the actual content.

        Args:
            timeout: Per-readline timeout in seconds.
            max_wait: Maximum total wall-clock time in seconds. Prevents
                infinite loops when coqtop produces slow but steady output.
        """
        output_lines: list[str] = []
        stdout = self._proc.stdout
        deadline = time.monotonic() + max_wait
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning(
                        "coqtop read exceeded max_wait of %.0fs", max_wait,
                    )
                    break
                line_bytes = await asyncio.wait_for(
                    stdout.readline(), timeout=min(timeout, remaining),
                )
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                if _SENTINEL in line:
                    # Drain the rest of the sentinel error block
                    try:
                        while True:
                            rest = await asyncio.wait_for(
                                stdout.readline(), timeout=2.0,
                            )
                            if not rest or rest.decode("utf-8", errors="replace").strip() == "":
                                break
                    except asyncio.TimeoutError:
                        pass
                    break
                # Strip coqtop prompt prefixes (e.g., "Rocq < ", "name < ")
                stripped = re.sub(r"^[A-Za-z_][A-Za-z0-9_.']* < ", "", line)
                output_lines.append(stripped)
        except asyncio.TimeoutError:
            logger.warning("coqtop read timed out after %.0fs", timeout)
        # Strip trailing sentinel preamble
        while output_lines and (
            "Toplevel input" in output_lines[-1]
            or output_lines[-1].strip().startswith(">")
            or output_lines[-1].strip().startswith("^")
        ):
            output_lines.pop()
        return "".join(output_lines).strip()


# ---------------------------------------------------------------------------
# File prelude extraction helpers
# ---------------------------------------------------------------------------

_PROOF_START_RE = re.compile(
    r"^[ \t]*(?:Lemma|Theorem|Proposition|Corollary|Example|Fact|Remark|"
    r"Definition|Fixpoint|CoFixpoint|Program\s+\w+)\s+"
    r"(\S+)",
    re.MULTILINE,
)


def _extract_prelude_up_to_proof(file_path: str, proof_name: str) -> str:
    """Extract file content up to (but not including) the target proof.

    When proof_name is empty, returns content up to the first proof
    definition (imports and definitions only). This avoids sending
    entire large files to coqtop.
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return ""

    if not proof_name:
        # No specific proof — return content before the first proof definition
        first_match = _PROOF_START_RE.search(text)
        if first_match:
            return text[:first_match.start()].rstrip()
        return text.rstrip()

    for m in _PROOF_START_RE.finditer(text):
        name = m.group(1).rstrip(".")
        if name == proof_name or proof_name.endswith("." + name):
            return text[:m.start()].rstrip()

    # Proof not found — return full file as fallback
    return text.rstrip()


def _extract_theorem_statement(file_path: str, proof_name: str) -> str:
    """Extract the theorem statement (from 'Lemma' to the first '.')."""
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return ""

    for m in _PROOF_START_RE.finditer(text):
        name = m.group(1).rstrip(".")
        if name == proof_name or proof_name.endswith("." + name):
            # Find the first period that ends the statement
            rest = text[m.start():]
            # The statement ends at the first ". " or ".\n" or ".$"
            dot_end = re.search(r"\.\s", rest)
            if dot_end:
                return rest[:dot_end.start() + 1]
            return rest

    return ""
