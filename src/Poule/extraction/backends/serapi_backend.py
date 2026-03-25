"""SerAPI (sertop) backend for Coq library extraction.

Communicates with ``sertop --printer=sertop`` over stdio using
S-expression commands and responses.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from ..errors import BackendCrashError, ExtractionError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight S-expression parser
# ---------------------------------------------------------------------------

def parse_sexp(text: str) -> Any:
    """Parse an S-expression string into nested Python lists/strings.

    Atoms are returned as plain strings.  Lists become Python lists.
    Quoted strings have their quotes stripped.

    Returns a single value if the input contains one top-level expression,
    or a list of top-level expressions if there are multiple.
    """
    tokens = _tokenize(text)
    results: list[Any] = []
    pos = 0
    while pos < len(tokens):
        value, pos = _parse_tokens(tokens, pos)
        results.append(value)
    if len(results) == 1:
        return results[0]
    return results


def _tokenize(text: str) -> list[str]:
    """Tokenize an S-expression string into a list of tokens."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
        elif c == "(":
            tokens.append("(")
            i += 1
        elif c == ")":
            tokens.append(")")
            i += 1
        elif c == '"':
            # Quoted string — find matching close quote
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            tokens.append(text[i : j + 1])
            i = j + 1
        else:
            # Atom — read until whitespace or paren
            j = i
            while j < n and text[j] not in " \t\n\r()\"":
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse_tokens(tokens: list[str], pos: int) -> tuple[Any, int]:
    """Parse one value from the token list starting at *pos*."""
    if pos >= len(tokens):
        raise ExtractionError("Unexpected end of S-expression")

    tok = tokens[pos]
    if tok == "(":
        items: list[Any] = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ")":
            val, pos = _parse_tokens(tokens, pos)
            items.append(val)
        if pos >= len(tokens):
            raise ExtractionError("Unmatched opening parenthesis in S-expression")
        pos += 1  # skip ')'
        return items, pos
    elif tok == ")":
        raise ExtractionError("Unexpected closing parenthesis in S-expression")
    elif tok.startswith('"') and tok.endswith('"'):
        # Strip quotes and unescape
        inner = tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return inner, pos + 1
    else:
        return tok, pos + 1


# ---------------------------------------------------------------------------
# SerAPI Backend
# ---------------------------------------------------------------------------

class SerAPIBackend:
    """Backend that communicates with SerAPI's ``sertop`` process.

    Usage::

        backend = SerAPIBackend()
        backend.start()
        try:
            decls = backend.list_declarations(vo_path)
            ...
        finally:
            backend.stop()
    """

    def __init__(self, sertop_path: str = "sertop") -> None:
        self._sertop_path = sertop_path
        self._process: subprocess.Popen[str] | None = None
        self._tag: int = 0

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Spawn the ``sertop`` subprocess."""
        try:
            self._process = subprocess.Popen(
                [self._sertop_path, "--printer=sertop"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError as exc:
            raise ExtractionError(
                f"sertop not found at '{self._sertop_path}': {exc}"
            ) from exc

        # Read the initial greeting/ready prompt (if any) — sertop may emit
        # feedback lines on startup.
        self._read_until_ready()

    def stop(self) -> None:
        """Send ``(Quit)`` and terminate the subprocess."""
        if self._process is None:
            return
        try:
            if self._process.poll() is None:
                self._send_raw("(Quit)\n")
                self._process.wait(timeout=5)
        except Exception:
            logger.warning("Error during sertop shutdown, killing process")
            self._process.kill()
        finally:
            self._process = None

    def _ensure_alive(self) -> None:
        """Raise ``BackendCrashError`` if the process has exited."""
        if self._process is None:
            raise BackendCrashError("sertop process is not running")
        rc = self._process.poll()
        if rc is not None:
            stderr = ""
            if self._process.stderr:
                try:
                    stderr = self._process.stderr.read()
                except Exception:
                    pass
            self._process = None
            raise BackendCrashError(
                f"sertop exited unexpectedly with code {rc}. stderr: {stderr}"
            )

    # -- Low-level communication --------------------------------------------

    def _next_tag(self) -> int:
        self._tag += 1
        return self._tag

    def _send_raw(self, text: str) -> None:
        """Write raw text to sertop's stdin."""
        assert self._process is not None
        assert self._process.stdin is not None
        self._process.stdin.write(text)
        self._process.stdin.flush()

    def _send_command(self, command: str) -> tuple[int, list[Any]]:
        """Send a tagged command and collect responses until ``Completed``.

        Returns ``(tag, answer_payloads)`` where *answer_payloads* is a list
        of the non-Completed Answer bodies.

        Raises ``ExtractionError`` if a ``CoqExn`` is received.
        """
        self._ensure_alive()
        tag = self._next_tag()
        full_cmd = f"({command})\n"
        self._send_raw(full_cmd)
        return tag, self._collect_responses(tag)

    def _collect_responses(self, tag: int) -> list[Any]:
        """Read stdout lines until ``(Answer <tag> Completed)``."""
        assert self._process is not None
        assert self._process.stdout is not None

        payloads: list[Any] = []
        tag_str = str(tag)

        while True:
            line = self._process.stdout.readline()
            if not line:
                # EOF — process died
                self._ensure_alive()
                raise BackendCrashError("sertop stdout closed unexpectedly")

            line = line.strip()
            if not line:
                continue

            try:
                sexp = parse_sexp(line)
            except ExtractionError:
                logger.warning("Failed to parse sertop output: %s", line)
                continue

            if not isinstance(sexp, list) or len(sexp) < 2:
                # Feedback or other non-answer line
                continue

            head = sexp[0]

            if head == "Feedback":
                # Skip feedback messages
                continue

            if head == "Answer" and str(sexp[1]) == tag_str:
                body = sexp[2] if len(sexp) > 2 else None

                if body == "Completed":
                    return payloads

                # Check for CoqExn
                if isinstance(body, list) and len(body) > 0 and body[0] == "CoqExn":
                    msg = self._extract_exn_message(body)
                    raise ExtractionError(f"Coq exception: {msg}")

                payloads.append(body)

    def _read_until_ready(self) -> None:
        """Consume initial sertop output until we see a ready state.

        After startup sertop may emit feedback lines. We read until we see
        a line that looks like a completed answer or until no more data is
        immediately available.
        """
        if self._process is None or self._process.stdout is None:
            return
        # Send a no-op command to synchronize
        tag = self._next_tag()
        self._send_raw(f"(Noop)\n")
        try:
            self._collect_responses(tag)
        except ExtractionError:
            # Some sertop versions may not support Noop — that's fine
            pass

    @staticmethod
    def _extract_exn_message(body: list[Any]) -> str:
        """Extract a human-readable message from a CoqExn body."""
        # CoqExn structure varies; try to pull out a string
        def _find_strings(obj: Any) -> list[str]:
            if isinstance(obj, str) and len(obj) > 3:
                return [obj]
            if isinstance(obj, list):
                result: list[str] = []
                for item in obj:
                    result.extend(_find_strings(item))
                return result
            return []

        strings = _find_strings(body)
        return "; ".join(strings) if strings else str(body)

    # -- Extraction helpers -------------------------------------------------

    def _module_name_from_vo(self, vo_path: Path) -> str:
        """Derive a Coq module name from a ``.vo`` file path.

        Uses ``coqc -where`` to find the Coq lib root, then computes the
        logical path relative to it. Falls back to the stem if resolution
        fails.
        """
        vo_path = vo_path.resolve()
        stem = vo_path.stem

        try:
            result = subprocess.run(
                ["coqc", "-where"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            coq_root = Path(result.stdout.strip()).resolve()
        except Exception:
            return stem

        # Try to find relative path under theories/ or user-contrib/
        for sub in ("theories", "user-contrib"):
            base = coq_root / sub
            try:
                rel = vo_path.relative_to(base)
                parts = list(rel.with_suffix("").parts)
                return ".".join(parts)
            except ValueError:
                continue

        # Direct child of coq root
        try:
            rel = vo_path.relative_to(coq_root)
            parts = list(rel.with_suffix("").parts)
            return ".".join(parts)
        except ValueError:
            return stem

    def _vernac_query(self, vernac: str, pp_format: str = "PpStr") -> list[str]:
        """Run a Vernac command via Query and return string results.

        Parameters
        ----------
        vernac:
            The Vernac command string (without trailing period handling —
            caller should include it if needed).
        pp_format:
            ``"PpStr"`` for human-readable or ``"PpSer"`` for kernel terms.

        Returns
        -------
        list[str]
            The string payloads from ``ObjList`` answers.
        """
        cmd = f'Query ((pp ((pp_format {pp_format})))) (Vernac "{vernac}")'
        _tag, payloads = self._send_command(cmd)
        return self._extract_obj_strings(payloads)

    @staticmethod
    def _extract_obj_strings(payloads: list[Any]) -> list[str]:
        """Pull string values out of ``ObjList`` answer payloads."""
        results: list[str] = []
        for payload in payloads:
            if not isinstance(payload, list):
                continue
            if len(payload) >= 1 and payload[0] == "ObjList":
                for obj in payload[1:]:
                    if isinstance(obj, list):
                        for item in obj:
                            s = _deep_find_string(item)
                            if s is not None:
                                results.append(s)
                    elif isinstance(obj, str):
                        results.append(obj)
        return results

    # -- Public API (Backend protocol) --------------------------------------

    def list_declarations(self, vo_path: Path, **kwargs: Any) -> list[tuple[str, str, Any]]:
        """Load a ``.vo`` file and return its declarations.

        Returns a list of ``(name, kind, constr_t)`` tuples.
        """
        self._ensure_alive()
        module_name = self._module_name_from_vo(vo_path)

        # Step 1: Load the module
        add_cmd = f'Add () "Require Import {module_name}."'
        tag, payloads = self._send_command(add_cmd)

        # Extract the sentence id from the Add response
        sid = self._extract_sid(payloads)
        if sid is not None:
            self._send_command(f"Exec {sid}")

        # Step 2: Query for declarations in the module
        search_results = self._vernac_query(
            f"Print Module {module_name}.", "PpStr"
        )

        declarations: list[tuple[str, str, Any]] = []

        # Parse the Print Module output to extract declaration names and kinds
        for text in search_results:
            parsed = self._parse_module_output(text, module_name)
            declarations.extend(parsed)

        # Step 3: For each declaration, get the Constr.t via PpSer
        enriched: list[tuple[str, str, Any]] = []
        for name, kind, _ in declarations:
            constr_t = self._get_constr_t(name)
            enriched.append((name, kind, constr_t))

        return enriched

    def pretty_print(self, name: str) -> str:
        """Return the human-readable statement for *name*."""
        self._ensure_alive()
        results = self._vernac_query(f"Print {name}.", "PpStr")
        return "\n".join(results) if results else ""

    def pretty_print_type(self, name: str) -> str | None:
        """Return the human-readable type signature for *name*, or None."""
        self._ensure_alive()
        try:
            results = self._vernac_query(f"Check {name}.", "PpStr")
            return "\n".join(results) if results else None
        except ExtractionError:
            logger.warning("Failed to get type for %s", name)
            return None

    def get_dependencies(self, name: str) -> list[tuple[str, str]]:
        """Return dependency pairs ``(target_name, relation)`` for *name*."""
        self._ensure_alive()
        try:
            results = self._vernac_query(f"Print Assumptions {name}.", "PpStr")
        except ExtractionError:
            logger.warning("Failed to get dependencies for %s", name)
            return []

        deps: list[tuple[str, str]] = []
        for text in results:
            deps.extend(self._parse_assumptions(text))
        return deps

    def detect_version(self) -> str:
        """Detect the installed Coq version by running ``coqc --version``."""
        try:
            result = subprocess.run(
                ["coqc", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as exc:
            raise ExtractionError(
                f"coqc not found: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"coqc --version timed out: {exc}"
            ) from exc

        output = result.stdout.strip()
        # Parse version from output like "The Coq Proof Assistant, version 8.19.0"
        # or "The Rocq Prover, version 9.0.0"
        match = re.search(r"version\s+(\S+)", output)
        if match:
            return match.group(1)

        # Fallback: return first line
        return output.split("\n")[0] if output else "unknown"

    # -- Internal parsing helpers -------------------------------------------

    @staticmethod
    def _extract_sid(payloads: list[Any]) -> str | None:
        """Extract the sentence id from an Add command response."""
        for payload in payloads:
            if isinstance(payload, list) and len(payload) >= 2:
                if payload[0] == "Added":
                    return str(payload[1])
        return None

    def _get_constr_t(self, name: str) -> Any:
        """Get the kernel term (Constr.t) for a declaration via PpSer."""
        try:
            cmd = f'Query ((pp ((pp_format PpSer)))) (Vernac "Check {name}.")'
            _tag, payloads = self._send_command(cmd)
            strings = self._extract_obj_strings(payloads)
            if strings:
                try:
                    return parse_sexp(strings[0])
                except ExtractionError:
                    logger.warning(
                        "Failed to parse Constr.t for %s", name
                    )
                    return strings[0]
            return None
        except ExtractionError:
            logger.warning("Failed to get Constr.t for %s", name)
            return None

    @staticmethod
    def _parse_module_output(
        text: str, module_name: str
    ) -> list[tuple[str, str, Any]]:
        """Parse the output of ``Print Module`` to extract declarations.

        Returns ``(fully_qualified_name, kind, None)`` triples. The
        ``constr_t`` is filled in later by ``_get_constr_t``.
        """
        declarations: list[tuple[str, str, Any]] = []

        # Patterns for different declaration kinds in Print Module output
        patterns = [
            (r"(?:Theorem|Lemma)\s+([\w.']+)", "Lemma"),
            (r"Definition\s+([\w.']+)", "Definition"),
            (r"Inductive\s+([\w.']+)", "Inductive"),
            (r"Record\s+([\w.']+)", "Record"),
            (r"Class\s+([\w.']+)", "Class"),
            (r"Instance\s+([\w.']+)", "Instance"),
            (r"Axiom\s+([\w.']+)", "Axiom"),
            (r"Parameter\s+([\w.']+)", "Parameter"),
            (r"Canonical\s+Structure\s+([\w.']+)", "Canonical Structure"),
            (r"Coercion\s+([\w.']+)", "Coercion"),
            (r"Let\s+([\w.']+)", "Let"),
            (r"Conjecture\s+([\w.']+)", "Conjecture"),
            (r"Constructor\s+([\w.']+)", "Constructor"),
        ]

        for pattern, kind in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                # Qualify name with module if not already qualified
                if "." not in name:
                    name = f"{module_name}.{name}"
                declarations.append((name, kind, None))

        return declarations

    @staticmethod
    def _parse_assumptions(text: str) -> list[tuple[str, str]]:
        """Parse ``Print Assumptions`` output into dependency pairs.

        The output typically lists assumptions like:
            ``Coq.Init.Logic.eq_refl : forall ...``
            ``Closed under the global context``

        Returns ``(target_name, "axiom")`` for each listed assumption.
        """
        deps: list[tuple[str, str]] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("Closed under"):
                continue
            # Each line is typically "name : type"
            parts = line.split(":", 1)
            if parts:
                dep_name = parts[0].strip()
                if dep_name and re.match(r"[\w.]+$", dep_name):
                    deps.append((dep_name, "axiom"))
        return deps


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _deep_find_string(obj: Any) -> str | None:
    """Recursively find the first substantial string in a nested structure."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        for item in obj:
            result = _deep_find_string(item)
            if result is not None:
                return result
    return None
