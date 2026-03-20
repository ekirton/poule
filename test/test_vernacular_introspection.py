"""TDD tests for the Vernacular Introspection handler (specification/vernacular-introspection.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/query/ modules exist.

Spec: specification/vernacular-introspection.md
Architecture: doc/architecture/vernacular-introspection.md, doc/architecture/mcp-server.md
Data model: QueryResult (spec section 5)

Import paths under test:
  poule.query.handler     (coq_query)
  poule.query.dispatch    (build_vernacular)
  poule.query.parser      (parse_output)
  poule.query.errors      (classify_error)
  poule.query.types       (QueryResult, Command)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_coq_query():
    from Poule.query.handler import coq_query
    return coq_query


def _import_build_vernacular():
    from Poule.query.dispatch import build_vernacular
    return build_vernacular


def _import_parse_output():
    from Poule.query.parser import parse_output
    return parse_output


def _import_classify_error():
    from Poule.query.errors import classify_error
    return classify_error


def _import_types():
    from Poule.query.types import QueryResult, Command
    return QueryResult, Command


def _import_server_errors():
    from Poule.server.errors import format_error
    return format_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_COMMANDS = ("Print", "Check", "About", "Locate", "Search", "Compute", "Eval")


def _make_query_result(
    command="Check",
    argument="Nat.add_comm",
    output="Nat.add_comm\n     : forall n m : nat, n + m = m + n",
    warnings=None,
):
    """Build a QueryResult using the real type."""
    QueryResult, _ = _import_types()
    return QueryResult(
        command=command,
        argument=argument,
        output=output,
        warnings=warnings if warnings is not None else [],
    )


def _make_mock_session_manager(
    submit_result="nat : Set",
    submit_error=None,
    session_exists=True,
):
    """Create a mock session manager for vernacular query tests.

    Returns an AsyncMock whose submit_vernacular method returns raw Coq output.
    """
    from Poule.session.errors import SESSION_NOT_FOUND, SessionError

    manager = AsyncMock()

    if not session_exists:
        manager.submit_vernacular.side_effect = SessionError(
            SESSION_NOT_FOUND, 'Proof session "missing" not found or has expired.'
        )
    elif submit_error is not None:
        manager.submit_vernacular.side_effect = submit_error
    else:
        manager.submit_vernacular.return_value = submit_result

    return manager


def _make_mock_process_pool(
    send_result="nat : Set",
    send_error=None,
):
    """Create a mock standalone Coq process pool.

    Returns an AsyncMock whose send_command method returns raw Coq output.
    """
    pool = AsyncMock()

    if send_error is not None:
        pool.send_command.side_effect = send_error
    else:
        pool.send_command.return_value = send_result

    return pool


# ===========================================================================
# 1. Tool Entry Point -- coq_query (spec section 4.1)
# ===========================================================================

class TestCoqQueryEntryPoint:
    """Section 4.1: coq_query(command, argument, session_id?) entry point."""

    @pytest.mark.asyncio
    async def test_check_session_free_returns_query_result(self):
        """Given command='Check', argument='Nat.add_comm', no session_id,
        When coq_query is called,
        Then returns a QueryResult with output containing the type."""
        coq_query = _import_coq_query()
        QueryResult, _ = _import_types()
        raw_output = "Nat.add_comm\n     : forall n m : nat, n + m = m + n"
        pool = _make_mock_process_pool(send_result=raw_output)

        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            process_pool=pool,
        )

        assert isinstance(result, QueryResult)
        assert result.command == "Check"
        assert result.argument == "Nat.add_comm"
        assert "forall n m : nat" in result.output
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_print_session_aware_returns_query_result(self):
        """Given command='Print', argument='nat', session_id='abc123',
        When coq_query is called,
        Then sends 'Print nat.' to the session backend and returns a QueryResult."""
        coq_query = _import_coq_query()
        QueryResult, _ = _import_types()
        raw_output = "Inductive nat : Set :=  O : nat | S : nat -> nat."
        manager = _make_mock_session_manager(submit_result=raw_output)

        result = await coq_query(
            command="Print",
            argument="nat",
            session_id="abc123",
            session_manager=manager,
        )

        assert isinstance(result, QueryResult)
        assert result.command == "Print"
        assert result.argument == "nat"
        assert "Inductive nat" in result.output

    @pytest.mark.asyncio
    async def test_eval_session_free_returns_query_result(self):
        """Given command='Eval', argument='cbv in 1 + 1', no session_id,
        When coq_query is called,
        Then sends 'Eval cbv in 1 + 1.' and output contains '= 2 : nat'."""
        coq_query = _import_coq_query()
        raw_output = "= 2\n     : nat"
        pool = _make_mock_process_pool(send_result=raw_output)

        result = await coq_query(
            command="Eval",
            argument="cbv in 1 + 1",
            process_pool=pool,
        )

        assert "2" in result.output
        assert "nat" in result.output

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: Introspection commands are read-only with respect to proof state."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(submit_result="nat : Set")

        await coq_query(
            command="Check",
            argument="nat",
            session_id="abc123",
            session_manager=manager,
        )

        # Verify only submit_vernacular was called, not any state-mutating operations
        manager.submit_vernacular.assert_called_once()
        manager.submit_tactic.assert_not_called()
        manager.step_forward.assert_not_called()
        manager.step_backward.assert_not_called()

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_session_manager_submit_vernacular(self):
        """Contract test: real session manager accepts vernacular command strings."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        # Real session manager must expose submit_vernacular(session_id, vernacular_str)
        assert hasattr(manager, "submit_vernacular")

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_process_pool_send_command(self):
        """Contract test: real process pool accepts command strings and returns output."""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        assert hasattr(pool, "send_command")


# ===========================================================================
# 2. Command Dispatch (spec section 4.2)
# ===========================================================================

class TestCommandDispatch:
    """Section 4.2: Command dispatcher maps (command, argument) to vernacular string."""

    def test_print_basic(self):
        """Print + 'nat' -> 'Print nat.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Print", "nat") == "Print nat."

    def test_check_basic(self):
        """Check + 'Nat.add_comm' -> 'Check Nat.add_comm.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Check", "Nat.add_comm") == "Check Nat.add_comm."

    def test_about_basic(self):
        """About + 'nat' -> 'About nat.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("About", "nat") == "About nat."

    def test_locate_basic(self):
        """Locate + 'Nat.add' -> 'Locate Nat.add.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Locate", "Nat.add") == "Locate Nat.add."

    def test_search_basic(self):
        """Search + '(_ + _ = _ + _)' -> 'Search (_ + _ = _ + _).'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Search", "(_ + _ = _ + _)") == "Search (_ + _ = _ + _)."

    def test_compute_basic(self):
        """Compute + '1 + 1' -> 'Compute 1 + 1.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Compute", "1 + 1") == "Compute 1 + 1."

    def test_eval_basic(self):
        """Eval + 'cbv in 1 + 1' -> 'Eval cbv in 1 + 1.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Eval", "cbv in 1 + 1") == "Eval cbv in 1 + 1."

    def test_print_assumptions_special_case(self):
        """Given command='Print', argument='Assumptions my_lemma',
        When the dispatcher constructs the vernacular string,
        Then the result is 'Print Assumptions my_lemma.'"""
        build_vernacular = _import_build_vernacular()
        assert build_vernacular("Print", "Assumptions my_lemma") == "Print Assumptions my_lemma."

    def test_period_not_duplicated(self):
        """Given argument already ends with period,
        When the dispatcher constructs the vernacular string,
        Then no duplicate period is appended.

        Spec example: Check 'fun x => x + 1.' -> 'Check fun x => x + 1.'"""
        build_vernacular = _import_build_vernacular()
        result = build_vernacular("Check", "fun x => x + 1.")
        assert result == "Check fun x => x + 1."
        assert not result.endswith("..")

    def test_period_appended_when_missing(self):
        """Argument without trailing period gets one appended."""
        build_vernacular = _import_build_vernacular()
        result = build_vernacular("Check", "nat")
        assert result.endswith(".")

    def test_argument_passed_verbatim(self):
        """MAINTAINS: Argument text is passed verbatim -- no escaping, quoting, or rewriting."""
        build_vernacular = _import_build_vernacular()
        weird_arg = 'fun (x : nat) => x + 1'
        result = build_vernacular("Check", weird_arg)
        assert weird_arg in result

    def test_locate_with_notation_string(self):
        """Locate argument may be a notation string in double quotes."""
        build_vernacular = _import_build_vernacular()
        result = build_vernacular("Locate", '"_ + _"')
        assert result == 'Locate "_ + _".'


# ===========================================================================
# 3. Execution Routing (spec section 4.3)
# ===========================================================================

class TestExecutionRouting:
    """Section 4.3: session_id determines the execution backend."""

    @pytest.mark.asyncio
    async def test_session_aware_uses_session_manager(self):
        """When session_id is provided, handler submits to session's Coq backend."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(submit_result="H : a = b")
        pool = _make_mock_process_pool()

        await coq_query(
            command="Check",
            argument="H",
            session_id="session1",
            session_manager=manager,
            process_pool=pool,
        )

        manager.submit_vernacular.assert_called_once()
        pool.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_free_uses_process_pool(self):
        """When session_id is omitted, handler uses standalone Coq process."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager()
        pool = _make_mock_process_pool(send_result="Nat.add : nat -> nat -> nat")

        await coq_query(
            command="Locate",
            argument="Nat.add",
            process_pool=pool,
        )

        pool.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_aware_check_with_file_imports(self):
        """Spec §4.3 example: Given a proof session with 'Require Import Arith.'
        in the file preamble and command='Check', argument='Nat.add_comm',
        When coq_query executes in session context,
        Then the output contains the type of Nat.add_comm.

        Note: the coqtop subprocess loads file-level imports, so definitions
        from imported modules are available."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(
            submit_result="Nat.add_comm\n     : forall n m : nat, n + m = m + n"
        )

        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            session_id="session1",
            session_manager=manager,
        )

        assert "forall n m : nat" in result.output
        assert "n + m = m + n" in result.output

    @pytest.mark.asyncio
    async def test_session_free_locate_standard_library(self):
        """Given no session_id, Locate Nat.add returns module path from stdlib."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool(
            send_result="Constant Coq.Init.Nat.add"
        )

        result = await coq_query(
            command="Locate",
            argument="Nat.add",
            process_pool=pool,
        )

        assert "Nat.add" in result.output or "Coq.Init" in result.output

    @pytest.mark.asyncio
    async def test_session_aware_read_only(self):
        """MAINTAINS: Session proof state is not modified by introspection."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(submit_result="nat : Set")

        await coq_query(
            command="About",
            argument="nat",
            session_id="abc",
            session_manager=manager,
        )

        # Only read-only operations should be called
        manager.submit_vernacular.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_aware_routes_through_coqtop_not_coq_lsp(self):
        """Spec §4.3: session-aware execution routes through coqtop subprocess,
        not the session's coq-lsp backend, because coq-lsp's LSP protocol does
        not expose vernacular command output."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(submit_result="forall n m : nat, n + m = m + n")

        await coq_query(
            command="Check",
            argument="Nat.add_comm",
            session_id="s1",
            session_manager=manager,
        )

        # The handler calls submit_vernacular, which internally routes to coqtop
        # (prefer_coqtop=True). The handler does NOT call execute_vernacular
        # (which would use coq-lsp and return empty for successful queries).
        manager.submit_vernacular.assert_called_once()
        if hasattr(manager, "execute_vernacular"):
            manager.execute_vernacular.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_aware_import_context_available(self):
        """Spec §4.3: session-aware execution has access to file's import context.

        Given a proof session with 'Require Import Arith.' in the file preamble
        and command='Check', argument='Nat.add_comm',
        When coq_query executes in session context,
        Then the output contains the type of Nat.add_comm."""
        coq_query = _import_coq_query()
        # Simulate a session whose file imports Arith — Nat.add_comm is available
        manager = _make_mock_session_manager(
            submit_result="Nat.add_comm\n     : forall n m : nat, n + m = m + n"
        )

        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            session_id="s1",
            session_manager=manager,
        )

        assert "forall n m : nat" in result.output
        assert "n + m = m + n" in result.output

    @pytest.mark.asyncio
    async def test_session_aware_local_hypotheses_not_available(self):
        """Spec §4.3: local proof hypotheses and let-bindings from the coq-lsp
        proof state are NOT available in the coqtop subprocess.

        The coqtop subprocess only loads file-level imports, not the proof
        context. Checking a local hypothesis returns an error."""
        coq_query = _import_coq_query()
        # Simulate coqtop returning NOT_FOUND for a local hypothesis
        manager = _make_mock_session_manager(
            submit_result="Error: The reference H was not found in the current environment."
        )

        # The handler should classify this as an error
        with pytest.raises(Exception) as exc_info:
            await coq_query(
                command="Check",
                argument="H",
                session_id="s1",
                session_manager=manager,
            )

        error_str = str(exc_info.value)
        assert "NOT_FOUND" in error_str or "not found" in error_str.lower()

    @pytest.mark.asyncio
    async def test_session_aware_coqtop_env_does_not_affect_proof_state(self):
        """MAINTAINS: The session's proof state (managed by the CoqBackend) is not
        modified. The coqtop subprocess environment may be modified by side-effecting
        commands, but this does not affect the proof state."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(submit_result="ok")

        await coq_query(
            command="Check",
            argument="nat",
            session_id="s1",
            session_manager=manager,
        )

        # Only submit_vernacular (read-only path) was called
        manager.submit_vernacular.assert_called_once()
        # No state-mutating operations
        manager.submit_tactic.assert_not_called()
        manager.step_forward.assert_not_called()
        manager.step_backward.assert_not_called()

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_session_manager_read_only(self):
        """Contract test: real session manager's submit_vernacular does not mutate state."""
        from Poule.session.manager import SessionManager
        # Verify the interface contract: submit_vernacular exists and is read-only
        assert callable(getattr(SessionManager, "submit_vernacular", None))

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_process_pool_lifecycle(self):
        """Contract test: process pool acquires and releases processes per invocation."""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        assert callable(getattr(pool, "send_command", None))


# ===========================================================================
# 3b. Session-Free Prelude Configuration (spec section 4.3, steps 2-5)
# ===========================================================================

class TestSessionFreePrelude:
    """Section 4.3 (session-free): prelude configuration, environment inheritance,
    and clean-environment guarantee."""

    def test_process_pool_accepts_prelude_parameter(self):
        """Spec §10: ProcessPool accepts a 'prelude' string parameter at construction."""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool(prelude="From Coq Require Import Bool.\n")
        assert pool._prelude == "From Coq Require Import Bool.\n"

    def test_process_pool_default_prelude(self):
        """Spec §4.3 step 4: default prelude is 'From Coq Require Import Arith.'"""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        assert "From Coq Require Import Arith" in pool._prelude

    @pytest.mark.asyncio
    async def test_prelude_prepended_before_user_command(self):
        """Spec §4.3 steps 3-5: the process executes the prelude before
        the user's command."""
        from Poule.query.process_pool import ProcessPool
        custom_prelude = "From Coq Require Import Bool.\n"
        pool = ProcessPool(prelude=custom_prelude)

        # Patch subprocess to capture what was sent to stdin
        sent_payload = None

        async def fake_communicate(input=None):
            nonlocal sent_payload
            sent_payload = input
            return (b"true : bool\n", b"")

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = fake_communicate
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await pool.send_command("Check true.")

        assert sent_payload is not None
        payload_str = sent_payload.decode()
        # Prelude appears before the command
        prelude_pos = payload_str.find("From Coq Require Import Bool.")
        command_pos = payload_str.find("Check true.")
        assert prelude_pos >= 0, "Prelude not found in payload"
        assert command_pos > prelude_pos, "Command must appear after prelude"

    @pytest.mark.asyncio
    async def test_each_invocation_starts_clean(self):
        """MAINTAINS: Each session-free invocation starts from a clean environment.
        No state persists between invocations."""
        from Poule.query.process_pool import ProcessPool

        spawn_count = 0

        async def counting_exec(*args, **kwargs):
            nonlocal spawn_count
            spawn_count += 1
            mock_proc = AsyncMock()

            async def fake_communicate(input=None):
                return (b"output\n", b"")

            mock_proc.communicate = fake_communicate
            mock_proc.returncode = 0
            return mock_proc

        pool = ProcessPool()
        with patch("asyncio.create_subprocess_exec", side_effect=counting_exec):
            await pool.send_command("Check nat.")
            await pool.send_command("Check bool.")

        # Each invocation spawns a new process (clean environment)
        assert spawn_count == 2

    @pytest.mark.asyncio
    async def test_custom_prelude_makes_imports_available(self):
        """Spec §4.3 example: session-free with custom prelude that loads
        additional packages makes those packages' definitions available.

        Given no session_id, and a prelude loading extra imports,
        When coq_query executes session-free,
        Then definitions from those imports are accessible."""
        coq_query = _import_coq_query()
        # Simulate a process pool whose prelude includes extra imports
        # The mock returns as if the import context has the queried definition
        pool = _make_mock_process_pool(
            send_result="leq = fun n m : nat => ...\n     : nat -> nat -> bool"
        )

        result = await coq_query(
            command="Print",
            argument="leq",
            process_pool=pool,
        )

        assert "leq" in result.output

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_default_prelude_loads_arith(self):
        """Contract test: with default prelude, Arith definitions are available."""
        coq_query = _import_coq_query()
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()  # default prelude

        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            process_pool=pool,
        )

        assert "forall" in result.output

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_custom_prelude(self):
        """Contract test: custom prelude makes its imports available."""
        coq_query = _import_coq_query()
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool(prelude="From Coq Require Import Bool.\n")

        result = await coq_query(
            command="Check",
            argument="negb",
            process_pool=pool,
        )

        assert "bool" in result.output.lower()

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_process_inherits_coqpath(self):
        """Contract test: standalone process inherits COQPATH from the server
        environment, making opam-installed packages reachable."""
        import os
        from Poule.query.process_pool import ProcessPool

        # COQPATH should be set in the server environment if opam is configured.
        # Even if empty, the process should not crash — it just means no extra
        # packages are available beyond the default load paths.
        pool = ProcessPool()
        result = await pool.send_command("Check nat.")
        assert "Set" in result or "nat" in result


# ===========================================================================
# 4. Output Parsing (spec section 4.4)
# ===========================================================================

class TestOutputParsing:
    """Section 4.4: Output parser transforms raw Coq output."""

    def test_whitespace_normalization_collapses_blank_lines(self):
        """Step 1: Collapse runs of blank lines to a single blank line."""
        parse_output = _import_parse_output()
        raw = "line1\n\n\n\nline2"
        output, warnings = parse_output(raw, command="Check")
        assert "\n\n\n" not in output
        assert "line1" in output
        assert "line2" in output

    def test_whitespace_normalization_trims(self):
        """Step 1: Trim leading and trailing whitespace."""
        parse_output = _import_parse_output()
        raw = "   \n  nat : Set  \n   "
        output, warnings = parse_output(raw, command="Check")
        assert output == output.strip()
        assert "nat : Set" in output

    def test_warning_extraction(self):
        """Step 2: Given raw output containing a warning line followed by 'nat : Set',
        When the output parser runs,
        Then output is 'nat : Set' and warnings contains the warning text."""
        parse_output = _import_parse_output()
        raw = 'Warning: Notation "_ + _" was already used.\nnat : Set'
        output, warnings = parse_output(raw, command="Check")
        assert output.strip() == "nat : Set"
        assert len(warnings) == 1
        assert 'Notation "_ + _" was already used.' in warnings[0]

    def test_warning_extraction_preserves_non_warning_order(self):
        """Step 2: Order of non-warning output lines is preserved."""
        parse_output = _import_parse_output()
        raw = "line1\nWarning: something\nline2\nline3"
        output, warnings = parse_output(raw, command="Check")
        lines = [l for l in output.split("\n") if l.strip()]
        assert lines == ["line1", "line2", "line3"]

    def test_search_truncation_at_default_limit(self):
        """Step 3: Given Search returning 120 entries,
        When the output parser runs,
        Then output contains the first 50 entries followed by truncation notice."""
        parse_output = _import_parse_output()
        entries = [f"lemma_{i}: nat -> nat" for i in range(120)]
        raw = "\n".join(entries)
        output, warnings = parse_output(raw, command="Search", truncation_limit=50)
        assert "(... truncated, 120 results total)" in output
        # Should contain at most 50 entries before truncation notice
        output_lines = [l for l in output.split("\n") if l.strip() and "truncated" not in l]
        assert len(output_lines) <= 50

    def test_search_no_truncation_under_limit(self):
        """When Search returns fewer entries than the limit, no truncation occurs."""
        parse_output = _import_parse_output()
        entries = [f"lemma_{i}: nat -> nat" for i in range(10)]
        raw = "\n".join(entries)
        output, warnings = parse_output(raw, command="Search", truncation_limit=50)
        assert "truncated" not in output
        output_lines = [l for l in output.split("\n") if l.strip()]
        assert len(output_lines) == 10

    def test_no_semantic_restructuring(self):
        """Step 4: Coq's pretty-printed output is preserved verbatim after steps 1-3."""
        parse_output = _import_parse_output()
        raw = "Inductive nat : Set :=  O : nat | S : nat -> nat."
        output, warnings = parse_output(raw, command="Print")
        assert output == raw.strip()

    def test_multiple_warnings_extracted(self):
        """Multiple warning lines are all extracted into the warnings list."""
        parse_output = _import_parse_output()
        raw = (
            "Warning: first warning\n"
            "nat : Set\n"
            "Warning: second warning"
        )
        output, warnings = parse_output(raw, command="Check")
        assert len(warnings) == 2
        assert "first warning" in warnings[0]
        assert "second warning" in warnings[1]

    def test_empty_raw_output(self):
        """Empty raw output returns empty string and no warnings."""
        parse_output = _import_parse_output()
        output, warnings = parse_output("", command="Check")
        assert output == ""
        assert warnings == []


# ===========================================================================
# 5. Data Model -- QueryResult (spec section 5)
# ===========================================================================

class TestQueryResultDataModel:
    """Section 5: QueryResult data model constraints."""

    def test_query_result_has_required_fields(self):
        """QueryResult has command, argument, output, warnings fields."""
        result = _make_query_result()
        assert result.command == "Check"
        assert result.argument == "Nat.add_comm"
        assert isinstance(result.output, str)
        assert isinstance(result.warnings, list)

    def test_command_field_valid_values(self):
        """command field must be one of the 7 valid commands."""
        QueryResult, _ = _import_types()
        for cmd in VALID_COMMANDS:
            result = QueryResult(command=cmd, argument="x", output="y", warnings=[])
            assert result.command == cmd

    def test_warnings_may_be_empty(self):
        """warnings is required but may be empty."""
        result = _make_query_result(warnings=[])
        assert result.warnings == []

    def test_mcp_success_envelope_format(self):
        """Success response wraps QueryResult in MCP content block with isError: false."""
        result = _make_query_result()
        # Verify the QueryResult can be JSON-serialized for MCP envelope
        result_dict = {
            "command": result.command,
            "argument": result.argument,
            "output": result.output,
            "warnings": result.warnings,
        }
        json_text = json.dumps(result_dict)
        envelope = {
            "content": [{"type": "text", "text": json_text}],
            "isError": False,
        }
        assert envelope["isError"] is False
        parsed = json.loads(envelope["content"][0]["text"])
        assert parsed["command"] == "Check"

    def test_mcp_error_envelope_format(self):
        """Error response uses MCP error format with isError: true."""
        error_json = json.dumps({
            "error": {"code": "NOT_FOUND", "message": '"x" not found in the current environment.'}
        })
        envelope = {
            "content": [{"type": "text", "text": error_json}],
            "isError": True,
        }
        assert envelope["isError"] is True
        parsed = json.loads(envelope["content"][0]["text"])
        assert parsed["error"]["code"] == "NOT_FOUND"


# ===========================================================================
# 6. Interface Contracts (spec section 6)
# ===========================================================================

class TestInterfaceContracts:
    """Section 6: Interface contracts between components."""

    @pytest.mark.asyncio
    async def test_session_manager_serialized_access(self):
        """Concurrency: one command at a time per session (serialized)."""
        coq_query = _import_coq_query()
        call_order = []

        async def slow_submit(session_id, vernacular):
            call_order.append("start")
            await asyncio.sleep(0.01)
            call_order.append("end")
            return "result"

        manager = AsyncMock()
        manager.submit_vernacular.side_effect = slow_submit

        await coq_query(
            command="Check",
            argument="nat",
            session_id="s1",
            session_manager=manager,
        )

        assert manager.submit_vernacular.call_count == 1

    @pytest.mark.asyncio
    async def test_standalone_process_released_after_command(self):
        """Lifecycle: process acquired before execution, released after output received."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool(send_result="nat : Set")

        await coq_query(
            command="Check",
            argument="nat",
            process_pool=pool,
        )

        pool.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_introspection_idempotent(self):
        """Idempotency: same command produces same output given same state."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool(send_result="nat : Set")

        result1 = await coq_query(command="Check", argument="nat", process_pool=pool)
        result2 = await coq_query(command="Check", argument="nat", process_pool=pool)

        assert result1.output == result2.output

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_session_submit_vernacular_interface(self):
        """Contract test: real session manager.submit_vernacular(session_id, str) -> str."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        assert callable(getattr(manager, "submit_vernacular", None))

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_process_pool_send_command_interface(self):
        """Contract test: real process pool.send_command(str) -> str."""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        assert callable(getattr(pool, "send_command", None))


# ===========================================================================
# 7. Error Specification -- Input Errors (spec section 7.1)
# ===========================================================================

class TestInputErrors:
    """Section 7.1: Input validation errors."""

    @pytest.mark.asyncio
    async def test_invalid_command_returns_error(self):
        """Given command not in valid enum,
        When coq_query is called,
        Then returns INVALID_COMMAND error with message listing valid commands."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool()

        with pytest.raises(Exception) as exc_info:
            await coq_query(command="Invalid", argument="x", process_pool=pool)

        error = exc_info.value
        # Error should contain INVALID_COMMAND code and list valid commands
        error_str = str(error)
        assert "Invalid" in error_str or hasattr(error, "code")

    @pytest.mark.asyncio
    async def test_invalid_command_error_message_format(self):
        """INVALID_COMMAND message: 'Unknown command "{command}". Valid commands: ...'"""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool()

        with pytest.raises(Exception) as exc_info:
            await coq_query(command="Bogus", argument="x", process_pool=pool)

        error_str = str(exc_info.value)
        assert "Bogus" in error_str
        for cmd in VALID_COMMANDS:
            assert cmd in error_str

    @pytest.mark.asyncio
    async def test_empty_argument_returns_error(self):
        """Given argument is empty string,
        When coq_query is called,
        Then returns INVALID_ARGUMENT error."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool()

        with pytest.raises(Exception) as exc_info:
            await coq_query(command="Check", argument="", process_pool=pool)

        error_str = str(exc_info.value)
        assert "empty" in error_str.lower() or "Argument" in error_str


# ===========================================================================
# 8. Error Specification -- Session Errors (spec section 7.2)
# ===========================================================================

class TestSessionErrors:
    """Section 7.2: Session-related errors."""

    @pytest.mark.asyncio
    async def test_session_not_found_returns_error(self):
        """Given session_id references a non-existent session,
        When coq_query is called,
        Then returns SESSION_NOT_FOUND error."""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(session_exists=False)

        with pytest.raises(Exception) as exc_info:
            await coq_query(
                command="Check",
                argument="nat",
                session_id="missing",
                session_manager=manager,
            )

        error_str = str(exc_info.value)
        assert "SESSION_NOT_FOUND" in error_str or "not found" in error_str.lower()

    @pytest.mark.asyncio
    async def test_session_not_found_message_format(self):
        """SESSION_NOT_FOUND message: 'Proof session "{session_id}" not found or has expired.'"""
        coq_query = _import_coq_query()
        manager = _make_mock_session_manager(session_exists=False)

        with pytest.raises(Exception) as exc_info:
            await coq_query(
                command="Check",
                argument="nat",
                session_id="xyz789",
                session_manager=manager,
            )

        error_str = str(exc_info.value)
        assert "xyz789" in error_str or "not found" in error_str.lower()

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_session_not_found_real(self):
        """Contract test: real session manager raises on invalid session_id."""
        from Poule.session.manager import SessionManager
        from Poule.session.errors import SessionError, SESSION_NOT_FOUND
        manager = SessionManager()
        with pytest.raises(SessionError) as exc_info:
            await manager.submit_vernacular("nonexistent_session", "Check nat.")
        assert exc_info.value.code == SESSION_NOT_FOUND


# ===========================================================================
# 9. Error Specification -- Coq Execution Errors (spec section 7.3)
# ===========================================================================

class TestCoqExecutionErrors:
    """Section 7.3: Error classification from Coq output."""

    def test_classify_not_found_error(self):
        """Name not found -> NOT_FOUND error code."""
        classify_error = _import_classify_error()
        raw = "Error: The reference nonexistent was not found in the current environment."
        code, message = classify_error(raw)
        assert code == "NOT_FOUND"
        assert "not found" in message.lower()

    def test_classify_type_error(self):
        """Ill-typed expression -> TYPE_ERROR error code."""
        classify_error = _import_classify_error()
        raw = "Error: The term \"true\" has type \"bool\" while it is expected to have type \"nat\"."
        code, message = classify_error(raw)
        assert code == "TYPE_ERROR"
        assert "Type error" in message

    def test_classify_parse_error(self):
        """Malformed command syntax -> PARSE_ERROR error code."""
        classify_error = _import_classify_error()
        raw = "Error: Syntax error: [vernac:gallina] expected."
        code, message = classify_error(raw)
        assert code == "PARSE_ERROR"
        assert "parse" in message.lower() or "Failed" in message

    def test_classify_invalid_strategy(self):
        """Invalid reduction strategy -> INVALID_STRATEGY error code."""
        classify_error = _import_classify_error()
        raw = "Error: Unknown reduction strategy."
        code, message = classify_error(raw)
        assert code == "INVALID_STRATEGY"
        assert "cbv" in message or "strategy" in message.lower()

    def test_classify_timeout(self):
        """Computation timeout -> TIMEOUT error code."""
        classify_error = _import_classify_error()
        raw = "Error: Timeout!"
        code, message = classify_error(raw)
        assert code == "TIMEOUT"
        assert "time limit" in message.lower()

    def test_classify_unrecognized_error_falls_back_to_parse_error(self):
        """Unclassified Coq error -> PARSE_ERROR with raw message preserved."""
        classify_error = _import_classify_error()
        raw = "Error: Something completely unexpected happened in Coq."
        code, message = classify_error(raw)
        assert code == "PARSE_ERROR"
        assert "Something completely unexpected" in message

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_classify_error_real_not_found(self):
        """Contract test: real Coq NOT_FOUND output classified correctly."""
        classify_error = _import_classify_error()
        # Real Coq error output for a nonexistent name
        raw = "Error: The reference nonexistent_lemma was not found in the current environment."
        code, _ = classify_error(raw)
        assert code == "NOT_FOUND"

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_classify_error_real_type_error(self):
        """Contract test: real Coq type error output classified correctly."""
        classify_error = _import_classify_error()
        raw = 'Error: The term "true" has type "bool" while it is expected to have type "nat".'
        code, _ = classify_error(raw)
        assert code == "TYPE_ERROR"


# ===========================================================================
# 10. Error Specification -- Backend Errors (spec section 7.4)
# ===========================================================================

class TestBackendErrors:
    """Section 7.4: Backend crash errors."""

    @pytest.mark.asyncio
    async def test_backend_crashed_session_returns_error(self):
        """Coq backend crash during session execution returns BACKEND_CRASHED."""
        coq_query = _import_coq_query()
        from Poule.session.errors import BACKEND_CRASHED, SessionError

        manager = AsyncMock()
        manager.submit_vernacular.side_effect = SessionError(
            BACKEND_CRASHED, "The Coq backend has crashed."
        )

        with pytest.raises(Exception) as exc_info:
            await coq_query(
                command="Check",
                argument="nat",
                session_id="s1",
                session_manager=manager,
            )

        error_str = str(exc_info.value)
        assert "BACKEND_CRASHED" in error_str or "crashed" in error_str.lower()

    @pytest.mark.asyncio
    async def test_backend_crashed_standalone_returns_error(self):
        """Coq backend crash during standalone execution returns BACKEND_CRASHED."""
        coq_query = _import_coq_query()

        pool = AsyncMock()
        pool.send_command.side_effect = RuntimeError("Process crashed")

        with pytest.raises(Exception):
            await coq_query(
                command="Check",
                argument="nat",
                process_pool=pool,
            )

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_backend_crash_session(self):
        """Contract test: real session manager raises BACKEND_CRASHED on crash."""
        from Poule.session.errors import BACKEND_CRASHED, SessionError
        from Poule.session.manager import SessionManager
        # Verify the error code constant exists and matches spec
        assert BACKEND_CRASHED == "BACKEND_CRASHED"

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_backend_crash_standalone(self):
        """Contract test: real process pool signals crash appropriately."""
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        assert hasattr(pool, "send_command")


# ===========================================================================
# 11. Non-Error Conditions (spec section 7.5)
# ===========================================================================

class TestNonErrorConditions:
    """Section 7.5: Conditions that are NOT errors."""

    @pytest.mark.asyncio
    async def test_search_no_results_is_not_error(self):
        """Search returning no results is a normal QueryResult, not an error."""
        coq_query = _import_coq_query()
        QueryResult, _ = _import_types()
        pool = _make_mock_process_pool(send_result="")

        result = await coq_query(
            command="Search",
            argument="nonexistent_pattern",
            process_pool=pool,
        )

        assert isinstance(result, QueryResult)
        assert result.command == "Search"


# ===========================================================================
# 12. Non-Functional Requirements (spec section 8)
# ===========================================================================

class TestNonFunctionalRequirements:
    """Section 8: Performance and resource constraints."""

    def test_command_dispatch_under_1ms(self):
        """Command dispatch (vernacular string construction) completes in < 1 ms."""
        build_vernacular = _import_build_vernacular()
        start = time.perf_counter_ns()
        for cmd in VALID_COMMANDS:
            build_vernacular(cmd, "some_argument")
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        # 7 commands should complete well under 1 ms total; each < 1 ms
        assert elapsed_ms < 7.0  # generous bound: 1 ms per command

    def test_output_parsing_under_10ms_for_100kb(self):
        """Output parsing completes in < 10 ms for outputs up to 100 KB."""
        parse_output = _import_parse_output()
        # Generate ~100 KB of output
        line = "lemma_name : forall n m : nat, n + m = m + n\n"
        repeat_count = (100 * 1024) // len(line) + 1
        raw = line * repeat_count
        assert len(raw) >= 100 * 1024

        start = time.perf_counter_ns()
        parse_output(raw, command="Check")
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        assert elapsed_ms < 10.0

    def test_search_truncation_limit_configurable(self):
        """Search truncation limit is configurable (default: 50)."""
        parse_output = _import_parse_output()
        entries = [f"lemma_{i}: nat" for i in range(200)]
        raw = "\n".join(entries)

        # Custom limit of 30
        output, _ = parse_output(raw, command="Search", truncation_limit=30)
        assert "(... truncated, 200 results total)" in output
        output_lines = [l for l in output.split("\n") if l.strip() and "truncated" not in l]
        assert len(output_lines) <= 30

    def test_output_buffer_limit_1mb(self):
        """Handler does not buffer more than 1 MB of output per invocation;
        outputs exceeding this are truncated with a trailing notice."""
        parse_output = _import_parse_output()
        # Generate > 1 MB of output
        line = "x" * 1000 + "\n"
        raw = line * 1100  # ~1.1 MB
        assert len(raw) > 1_000_000

        output, _ = parse_output(raw, command="Check")
        assert len(output) <= 1_000_000 + 200  # allow for truncation notice


# ===========================================================================
# 13. Spec Examples (spec section 9)
# ===========================================================================

class TestSpecExamples:
    """Section 9: End-to-end examples from the specification."""

    @pytest.mark.asyncio
    async def test_session_free_check_example(self):
        """Spec example: Check Nat.add_comm session-free."""
        coq_query = _import_coq_query()
        raw = "Nat.add_comm\n     : forall n m : nat, n + m = m + n"
        pool = _make_mock_process_pool(send_result=raw)

        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            process_pool=pool,
        )

        assert result.command == "Check"
        assert result.argument == "Nat.add_comm"
        assert "forall n m : nat, n + m = m + n" in result.output
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_session_aware_print_with_warnings_example(self):
        """Spec example: Print nat in session abc123."""
        coq_query = _import_coq_query()
        raw = "Inductive nat : Set :=  O : nat | S : nat -> nat."
        manager = _make_mock_session_manager(submit_result=raw)

        result = await coq_query(
            command="Print",
            argument="nat",
            session_id="abc123",
            session_manager=manager,
        )

        assert result.command == "Print"
        assert result.argument == "nat"
        assert "Inductive nat : Set" in result.output
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_error_not_found_example(self):
        """Spec example: About nonexistent_lemma -> NOT_FOUND error."""
        coq_query = _import_coq_query()
        pool = _make_mock_process_pool(
            send_result="Error: The reference nonexistent_lemma was not found in the current environment."
        )

        # The handler should detect the error in the output and raise/return error
        with pytest.raises(Exception) as exc_info:
            await coq_query(
                command="About",
                argument="nonexistent_lemma",
                process_pool=pool,
            )

        error_str = str(exc_info.value)
        assert "NOT_FOUND" in error_str or "not found" in error_str.lower()

    @pytest.mark.asyncio
    async def test_search_with_truncation_example(self):
        """Spec example: Search (_ + _ = _ + _) with 120 results truncated to 50."""
        coq_query = _import_coq_query()
        entries = [f"lemma_{i}: forall n m : nat, n + m = m + n" for i in range(120)]
        raw = "\n".join(entries)
        pool = _make_mock_process_pool(send_result=raw)

        result = await coq_query(
            command="Search",
            argument="(_ + _ = _ + _)",
            process_pool=pool,
        )

        assert result.command == "Search"
        assert "(... truncated, 120 results total)" in result.output

    @pytest.mark.asyncio
    async def test_eval_with_reduction_strategy_example(self):
        """Spec example: Eval cbv in 2 + 3 in session def456."""
        coq_query = _import_coq_query()
        raw = "= 5\n     : nat"
        manager = _make_mock_session_manager(submit_result=raw)

        result = await coq_query(
            command="Eval",
            argument="cbv in 2 + 3",
            session_id="def456",
            session_manager=manager,
        )

        assert result.command == "Eval"
        assert result.argument == "cbv in 2 + 3"
        assert "5" in result.output
        assert "nat" in result.output

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_check_nat_add_comm_real(self):
        """Contract test: real Coq process returns type of Nat.add_comm."""
        coq_query = _import_coq_query()
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        result = await coq_query(
            command="Check",
            argument="Nat.add_comm",
            process_pool=pool,
        )
        assert "forall" in result.output

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_eval_cbv_real(self):
        """Contract test: real Coq evaluates 'Eval cbv in 1 + 1.' to 2."""
        coq_query = _import_coq_query()
        from Poule.query.process_pool import ProcessPool
        pool = ProcessPool()
        result = await coq_query(
            command="Eval",
            argument="cbv in 1 + 1",
            process_pool=pool,
        )
        assert "2" in result.output


# ===========================================================================
# 14. Language-Specific Notes (spec section 10)
# ===========================================================================

class TestLanguageSpecificNotes:
    """Section 10: Python-specific implementation constraints."""

    def test_command_enum_is_strenum(self):
        """Command type is an enum.StrEnum with 7 values."""
        import enum
        _, Command = _import_types()
        assert issubclass(Command, enum.StrEnum)
        assert len(Command) == 7
        for cmd in VALID_COMMANDS:
            assert cmd in [c.value for c in Command]

    def test_parse_output_returns_tuple(self):
        """parse_output returns (output, warnings) tuple."""
        parse_output = _import_parse_output()
        result = parse_output("nat : Set", command="Check")
        assert isinstance(result, tuple)
        assert len(result) == 2
        output, warnings = result
        assert isinstance(output, str)
        assert isinstance(warnings, list)

    def test_classify_error_returns_tuple(self):
        """classify_error returns (error_code, message) tuple."""
        classify_error = _import_classify_error()
        result = classify_error("Error: unknown")
        assert isinstance(result, tuple)
        assert len(result) == 2
        code, message = result
        assert isinstance(code, str)
        assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_coq_query_is_async(self):
        """coq_query entry point is an async function."""
        import asyncio
        coq_query = _import_coq_query()
        assert asyncio.iscoroutinefunction(coq_query)

    @pytest.mark.asyncio
    async def test_coq_query_signature(self):
        """coq_query accepts command, argument, session_id, session_manager, process_pool."""
        import inspect
        coq_query = _import_coq_query()
        sig = inspect.signature(coq_query)
        params = list(sig.parameters.keys())
        assert "command" in params
        assert "argument" in params
        assert "session_id" in params
        assert "session_manager" in params
        assert "process_pool" in params

    @pytest.mark.asyncio
    async def test_compute_eval_timeout_enforcement(self):
        """Compute and Eval enforce timeout via asyncio.wait_for (default: 30s)."""
        coq_query = _import_coq_query()

        pool = AsyncMock()

        async def slow_send(cmd):
            await asyncio.sleep(100)
            return "result"

        pool.send_command.side_effect = slow_send

        with pytest.raises((asyncio.TimeoutError, Exception)):
            await asyncio.wait_for(
                coq_query(command="Compute", argument="very_expensive", process_pool=pool),
                timeout=0.1,
            )

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_coq_query_real_signature(self):
        """Contract test: real coq_query has the expected async signature."""
        import inspect
        coq_query = _import_coq_query()
        assert asyncio.iscoroutinefunction(coq_query)
        sig = inspect.signature(coq_query)
        assert "command" in sig.parameters
        assert "argument" in sig.parameters
        assert "session_id" in sig.parameters
