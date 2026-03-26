"""TDD tests for the Notation Inspection module (specification/notation-inspection.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/notation/ modules exist.

Spec: specification/notation-inspection.md
Architecture: doc/architecture/notation-inspection.md

Import paths under test:
  poule.notation.normalize    (normalize_notation)
  poule.notation.types        (NotationInfo, ScopeInfo, NotationAmbiguity, NotationInterpretation)
  poule.notation.parsers      (parse_print_notation, parse_locate_notation,
                                parse_print_scope, parse_print_visibility)
  poule.notation.dispatcher   (dispatch_notation_query, resolve_ambiguity, two_step_resolve)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_normalize():
    from Poule.notation.normalize import normalize_notation
    return normalize_notation


def _import_types():
    from Poule.notation.types import (
        NotationInfo,
        ScopeInfo,
        NotationAmbiguity,
        NotationInterpretation,
    )
    return NotationInfo, ScopeInfo, NotationAmbiguity, NotationInterpretation


def _import_parsers():
    from Poule.notation.parsers import (
        parse_print_notation,
        parse_locate_notation,
        parse_print_scope,
        parse_print_visibility,
    )
    return (
        parse_print_notation,
        parse_locate_notation,
        parse_print_scope,
        parse_print_visibility,
    )


def _import_dispatcher():
    from Poule.notation.dispatcher import (
        dispatch_notation_query,
        resolve_ambiguity,
        two_step_resolve,
    )
    return dispatch_notation_query, resolve_ambiguity, two_step_resolve


def _import_session_errors():
    from Poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError


def _import_server_errors():
    from Poule.server.errors import PARSE_ERROR
    return PARSE_ERROR


# ---------------------------------------------------------------------------
# Helpers — construct real data types for mock return values
# ---------------------------------------------------------------------------

def _make_notation_info(
    notation_string="_ ++ _",
    expansion="app (A:=?A) ?l ?m",
    level=60,
    associativity="right",
    arg_levels=None,
    fmt=None,
    scope="list_scope",
    defining_module="Stdlib.Lists.List",
    only_parsing=False,
    only_printing=False,
):
    NotationInfo, _, _, _ = _import_types()
    if arg_levels is None:
        arg_levels = [("x", 59), ("y", 60)]
    return NotationInfo(
        notation_string=notation_string,
        expansion=expansion,
        level=level,
        associativity=associativity,
        arg_levels=arg_levels,
        format=fmt,
        scope=scope,
        defining_module=defining_module,
        only_parsing=only_parsing,
        only_printing=only_printing,
    )


def _make_notation_interpretation(
    expansion="Nat.add ?n ?m",
    scope="nat_scope",
    defining_module="Stdlib.Init.Nat",
    priority_rank=0,
    is_default=True,
):
    _, _, _, NotationInterpretation = _import_types()
    return NotationInterpretation(
        expansion=expansion,
        scope=scope,
        defining_module=defining_module,
        priority_rank=priority_rank,
        is_default=is_default,
    )


def _make_scope_info(
    scope_name="nat_scope",
    bound_type="nat",
    notations=None,
):
    _, ScopeInfo, _, _ = _import_types()
    if notations is None:
        notations = []
    return ScopeInfo(
        scope_name=scope_name,
        bound_type=bound_type,
        notations=notations,
    )


def _make_notation_ambiguity(
    notation_string="_ + _",
    interpretations=None,
    active_index=0,
    resolution_reason="highest-priority open scope",
):
    _, _, NotationAmbiguity, _ = _import_types()
    if interpretations is None:
        interpretations = [
            _make_notation_interpretation(
                expansion="Nat.add ?n ?m",
                scope="nat_scope",
                defining_module="Stdlib.Init.Nat",
                priority_rank=0,
                is_default=True,
            ),
            _make_notation_interpretation(
                expansion="Z.add ?n ?m",
                scope="Z_scope",
                defining_module="Stdlib.ZArith.BinIntDef",
                priority_rank=1,
                is_default=False,
            ),
        ]
    return NotationAmbiguity(
        notation_string=notation_string,
        interpretations=interpretations,
        active_index=active_index,
        resolution_reason=resolution_reason,
    )


def _make_mock_session_manager(responses=None):
    """Create a mock session manager that returns canned textual responses.

    responses: dict mapping vernacular command string to raw textual output.
    """
    manager = AsyncMock()
    responses = responses or {}

    async def _submit_command(session_id, command):
        if command in responses:
            return responses[command]
        return ""

    manager.submit_command.side_effect = _submit_command
    return manager


# ===========================================================================
# 1. Input Normalization — §4.1
# ===========================================================================

class TestNormalizeNotation:
    """§4.1: normalize_notation behavioral requirements."""

    def test_infix_without_underscores_gets_placeholders(self):
        """Given raw input `++`, result is `"_ ++ _"` (underscores inserted, quotes added)."""
        normalize_notation = _import_normalize()
        result = normalize_notation("++")
        assert result == '"_ ++ _"'

    def test_infix_with_underscores_only_adds_quotes(self):
        """Given raw input `_ ++ _`, result is `"_ ++ _"` (quotes added, placeholders unchanged)."""
        normalize_notation = _import_normalize()
        result = normalize_notation("_ ++ _")
        assert result == '"_ ++ _"'

    def test_whitespace_stripped_and_collapsed(self):
        """Given `  x  +  y  `, whitespace is stripped and collapsed before further processing."""
        normalize_notation = _import_normalize()
        result = normalize_notation("  x  +  y  ")
        # Leading/trailing stripped, internal collapsed to single spaces
        assert "  " not in result.strip('"')

    def test_internal_quotes_escaped_by_doubling(self):
        """Internal double quotes are escaped by doubling."""
        normalize_notation = _import_normalize()
        result = normalize_notation('_ "test" _')
        # The result should have doubled internal quotes
        # Strip outer quotes to inspect content
        inner = result[1:-1]
        assert '""test""' in inner

    def test_empty_string_raises_error(self):
        """§7.1: Empty notation string raises a PARSE_ERROR."""
        normalize_notation = _import_normalize()
        with pytest.raises(Exception) as exc_info:
            normalize_notation("")
        # The error should indicate empty input; exact type depends on implementation
        assert "empty" in str(exc_info.value).lower()

    def test_whitespace_only_raises_error(self):
        """String that collapses to empty after whitespace normalization is treated as empty."""
        normalize_notation = _import_normalize()
        with pytest.raises(Exception):
            normalize_notation("   ")

    def test_single_operator_gets_prefix_placeholder(self):
        """Single prefix/postfix operator like `!` gets placeholder insertion."""
        normalize_notation = _import_normalize()
        result = normalize_notation("!")
        # Should have at least one underscore placeholder after normalization
        inner = result.strip('"')
        assert "_" in inner

    def test_result_wrapped_in_double_quotes(self):
        """Result is always wrapped in double quotes for Coq command construction."""
        normalize_notation = _import_normalize()
        result = normalize_notation("_ + _")
        assert result.startswith('"')
        assert result.endswith('"')

    def test_preserves_existing_underscores(self):
        """Existing underscore placeholders are not modified."""
        normalize_notation = _import_normalize()
        result = normalize_notation("_ :: _")
        inner = result.strip('"')
        assert inner == "_ :: _"


# ===========================================================================
# 2. Print Notation — §4.2
# ===========================================================================

class TestPrintNotation:
    """§4.2: coq_query(command="print_notation") behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_notation_info_for_known_notation(self):
        """Given a known notation, returns a NotationInfo with all required fields."""
        dispatch, _, _ = _import_dispatcher()
        NotationInfo, _, _, _ = _import_types()
        raw_output = (
            '"_ ++ _" := app (A:=?A) ?l ?m\n'
            "  (at level 60, x at level 59, y at level 60, right associativity)\n"
            "  : list_scope"
        )
        manager = _make_mock_session_manager({
            'Print Notation "_ ++ _".': raw_output,
        })
        result = await dispatch(
            command="print_notation",
            session_id="abc123",
            session_manager=manager,
            notation="_ ++ _",
        )
        assert isinstance(result, NotationInfo)
        assert result.notation_string == "_ ++ _"
        assert result.expansion != ""
        assert 0 <= result.level <= 200
        assert result.associativity in ("left", "right", "none")
        assert result.scope == "list_scope"

    @pytest.mark.asyncio
    async def test_notation_not_found_returns_error(self):
        """Given a notation not in scope, a NOTATION_NOT_FOUND error is returned."""
        dispatch, _, _ = _import_dispatcher()
        manager = _make_mock_session_manager({
            'Print Notation "_ ??? _".': "Error: Unknown notation",
        })
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="abc123",
                session_manager=manager,
                notation="???",
            )
        assert "NOTATION_NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOTATION_NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_session_not_found_raises_error(self):
        """§7.2: No active Coq session raises SESSION_NOT_FOUND."""
        dispatch, _, _ = _import_dispatcher()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.submit_command.side_effect = SessionError(
            SESSION_NOT_FOUND, "No active Coq session. Load a file first."
        )
        with pytest.raises(SessionError) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="nonexistent",
                session_manager=manager,
                notation="_ + _",
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_backend_crash_raises_error(self):
        """§7.2: Backend crash during command raises BACKEND_CRASHED."""
        dispatch, _, _ = _import_dispatcher()
        BACKEND_CRASHED, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.submit_command.side_effect = SessionError(
            BACKEND_CRASHED, "The Coq backend has crashed."
        )
        with pytest.raises(SessionError) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="abc123",
                session_manager=manager,
                notation="_ + _",
            )
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_empty_notation_raises_parse_error(self):
        """§7.1: Empty notation string raises PARSE_ERROR."""
        dispatch, _, _ = _import_dispatcher()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="abc123",
                session_manager=manager,
                notation="",
            )
        error_str = str(exc_info.value)
        assert "empty" in error_str.lower() or "PARSE_ERROR" in error_str


# ===========================================================================
# 3. Locate Notation — §4.3
# ===========================================================================

class TestLocateNotation:
    """§4.3: coq_query(command="locate_notation") behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_list_of_interpretations(self):
        """Given a notation with multiple scopes, returns list of NotationInterpretation."""
        dispatch, _, _ = _import_dispatcher()
        _, _, _, NotationInterpretation = _import_types()
        raw_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        manager = _make_mock_session_manager({
            'Locate "_ + _".': raw_output,
        })
        result = await dispatch(
            command="locate_notation",
            session_id="abc123",
            session_manager=manager,
            notation="+",
        )
        assert isinstance(result, list)
        assert len(result) >= 2
        assert all(isinstance(r, NotationInterpretation) for r in result)
        # Exactly one is_default=True
        defaults = [r for r in result if r.is_default]
        assert len(defaults) == 1

    @pytest.mark.asyncio
    async def test_single_interpretation_is_default(self):
        """Given a notation with a single interpretation, it is marked is_default=True."""
        dispatch, _, _ = _import_dispatcher()
        _, _, _, NotationInterpretation = _import_types()
        raw_output = (
            'Notation "_ :: _" := cons ?x ?l : list_scope\n'
            "  (default interpretation)\n"
        )
        manager = _make_mock_session_manager({
            'Locate "_ :: _".': raw_output,
        })
        result = await dispatch(
            command="locate_notation",
            session_id="abc123",
            session_manager=manager,
            notation="_ :: _",
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].is_default is True

    @pytest.mark.asyncio
    async def test_each_interpretation_has_required_fields(self):
        """Each NotationInterpretation has expansion, scope, defining_module, priority_rank, is_default."""
        dispatch, _, _ = _import_dispatcher()
        raw_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
        )
        manager = _make_mock_session_manager({
            'Locate "_ + _".': raw_output,
        })
        result = await dispatch(
            command="locate_notation",
            session_id="abc123",
            session_manager=manager,
            notation="+",
        )
        for interp in result:
            assert hasattr(interp, "expansion")
            assert hasattr(interp, "scope")
            assert hasattr(interp, "defining_module")
            assert hasattr(interp, "priority_rank")
            assert hasattr(interp, "is_default")
            assert interp.priority_rank >= 0


# ===========================================================================
# 4. Print Scope — §4.4
# ===========================================================================

class TestPrintScope:
    """§4.4: coq_query(command="print_scope") behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_scope_info_for_known_scope(self):
        """Given a known scope, returns a ScopeInfo with scope_name and notations list."""
        dispatch, _, _ = _import_dispatcher()
        _, ScopeInfo, _, _ = _import_types()
        raw_output = (
            "nat_scope\n"
            '"_ + _" := Nat.add ?n ?m\n'
            '"_ * _" := Nat.mul ?n ?m\n'
        )
        manager = _make_mock_session_manager({
            "Print Scope nat_scope.": raw_output,
        })
        result = await dispatch(
            command="print_scope",
            session_id="abc123",
            session_manager=manager,
            scope_name="nat_scope",
        )
        assert isinstance(result, ScopeInfo)
        assert result.scope_name == "nat_scope"
        assert isinstance(result.notations, list)
        assert len(result.notations) > 0

    @pytest.mark.asyncio
    async def test_scope_not_found_returns_error(self):
        """Given an unknown scope, a SCOPE_NOT_FOUND error is returned."""
        dispatch, _, _ = _import_dispatcher()
        manager = _make_mock_session_manager({
            "Print Scope nonexistent_scope.": "Error: Unknown scope",
        })
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_scope",
                session_id="abc123",
                session_manager=manager,
                scope_name="nonexistent_scope",
            )
        assert "SCOPE_NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "SCOPE_NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_scope_name_raises_parse_error(self):
        """§7.1: Empty scope_name raises PARSE_ERROR."""
        dispatch, _, _ = _import_dispatcher()
        manager = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_scope",
                session_id="abc123",
                session_manager=manager,
                scope_name="",
            )
        error_str = str(exc_info.value)
        assert "empty" in error_str.lower() or "PARSE_ERROR" in error_str

    @pytest.mark.asyncio
    async def test_scope_info_has_bound_type(self):
        """ScopeInfo includes bound_type (string or null)."""
        dispatch, _, _ = _import_dispatcher()
        _, ScopeInfo, _, _ = _import_types()
        raw_output = (
            "nat_scope\n"
            '"_ + _" := Nat.add ?n ?m\n'
        )
        manager = _make_mock_session_manager({
            "Print Scope nat_scope.": raw_output,
        })
        result = await dispatch(
            command="print_scope",
            session_id="abc123",
            session_manager=manager,
            scope_name="nat_scope",
        )
        assert isinstance(result, ScopeInfo)
        assert hasattr(result, "bound_type")
        # bound_type may be string or None


# ===========================================================================
# 5. Print Visibility — §4.5
# ===========================================================================

class TestPrintVisibility:
    """§4.5: coq_query(command="print_visibility") behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_ordered_scope_list(self):
        """Returns an ordered list of (scope_name, bound_type_or_null) pairs."""
        dispatch, _, _ = _import_dispatcher()
        raw_output = (
            "list_scope\n"
            "nat_scope (bound to nat)\n"
            "core_scope\n"
        )
        manager = _make_mock_session_manager({
            "Print Visibility.": raw_output,
        })
        result = await dispatch(
            command="print_visibility",
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, list)
        assert len(result) >= 1
        # Each entry is a (scope_name, bound_type_or_null) pair
        for entry in result:
            assert len(entry) == 2
            scope_name, bound_type = entry
            assert isinstance(scope_name, str)
            assert bound_type is None or isinstance(bound_type, str)

    @pytest.mark.asyncio
    async def test_priority_order_highest_first(self):
        """Index 0 = highest priority (§4.5)."""
        dispatch, _, _ = _import_dispatcher()
        raw_output = (
            "list_scope\n"
            "nat_scope (bound to nat)\n"
        )
        manager = _make_mock_session_manager({
            "Print Visibility.": raw_output,
        })
        result = await dispatch(
            command="print_visibility",
            session_id="abc123",
            session_manager=manager,
        )
        # First entry should be the highest-priority scope
        assert result[0][0] == "list_scope"
        assert result[1][0] == "nat_scope"

    @pytest.mark.asyncio
    async def test_bound_type_parsed_when_present(self):
        """Scopes with '(bound to <type>)' have bound_type set."""
        dispatch, _, _ = _import_dispatcher()
        raw_output = "nat_scope (bound to nat)\ncore_scope\n"
        manager = _make_mock_session_manager({
            "Print Visibility.": raw_output,
        })
        result = await dispatch(
            command="print_visibility",
            session_id="abc123",
            session_manager=manager,
        )
        nat_entry = [e for e in result if e[0] == "nat_scope"]
        assert len(nat_entry) == 1
        assert nat_entry[0][1] == "nat"
        core_entry = [e for e in result if e[0] == "core_scope"]
        assert len(core_entry) == 1
        assert core_entry[0][1] is None

    @pytest.mark.asyncio
    async def test_default_scopes_returned_when_no_explicit_openings(self):
        """Even with no explicit scope openings, default Coq scopes are returned."""
        dispatch, _, _ = _import_dispatcher()
        raw_output = "core_scope\n"
        manager = _make_mock_session_manager({
            "Print Visibility.": raw_output,
        })
        result = await dispatch(
            command="print_visibility",
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, list)
        assert len(result) >= 1


# ===========================================================================
# 6. Ambiguity Resolution — §4.6
# ===========================================================================

class TestAmbiguityResolution:
    """§4.6: Ambiguity resolution behavioral requirements."""

    @pytest.mark.asyncio
    async def test_returns_notation_ambiguity_for_multi_scope(self):
        """Given a notation with 2+ interpretations, returns NotationAmbiguity."""
        _, resolve, _ = _import_dispatcher()
        _, _, NotationAmbiguity, _ = _import_types()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        visibility_output = "nat_scope (bound to nat)\nZ_scope (bound to Z)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, NotationAmbiguity)
        assert result.notation_string == "_ + _"
        assert len(result.interpretations) >= 2
        assert 0 <= result.active_index < len(result.interpretations)

    @pytest.mark.asyncio
    async def test_active_index_points_to_highest_priority(self):
        """active_index references the highest-priority open scope interpretation."""
        _, resolve, _ = _import_dispatcher()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        visibility_output = "nat_scope (bound to nat)\nZ_scope (bound to Z)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
        )
        assert result.active_index == 0
        assert result.resolution_reason == "highest-priority open scope"

    @pytest.mark.asyncio
    async def test_interpretations_in_priority_order(self):
        """Interpretations are ordered by priority rank ascending."""
        _, resolve, _ = _import_dispatcher()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        visibility_output = "nat_scope (bound to nat)\nZ_scope (bound to Z)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
        )
        ranks = [interp.priority_rank for interp in result.interpretations]
        assert ranks == sorted(ranks)
        # Priority ranks are unique
        assert len(set(ranks)) == len(ranks)

    @pytest.mark.asyncio
    async def test_type_directed_binding_resolution(self):
        """§4.6: When type-directed binding applies, resolution_reason reflects it."""
        _, resolve, _ = _import_dispatcher()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
            "  (default interpretation)\n"
        )
        # Z_scope has higher priority here and is bound to Z
        visibility_output = "Z_scope (bound to Z)\nnat_scope (bound to nat)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
            expected_type="Z",
        )
        # When expected_type matches Z_scope's bound type, type-directed binding applies
        assert "type-directed binding" in result.resolution_reason
        assert "Z" in result.resolution_reason

    @pytest.mark.asyncio
    async def test_resolution_reason_is_valid_string(self):
        """§5: resolution_reason is one of the two valid forms."""
        _, resolve, _ = _import_dispatcher()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        visibility_output = "nat_scope (bound to nat)\nZ_scope (bound to Z)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
        )
        valid_prefixes = ("highest-priority open scope", "type-directed binding on ")
        assert any(result.resolution_reason.startswith(p) for p in valid_prefixes)


# ===========================================================================
# 7. Two-Step Resolution — §4.7
# ===========================================================================

class TestTwoStepResolution:
    """§4.7: Two-step resolution for term-based queries."""

    @pytest.mark.asyncio
    async def test_term_input_resolves_to_notation_info(self):
        """Given a Coq term like `3 + 4`, resolves to NotationInfo for `_ + _`."""
        _, _, two_step = _import_dispatcher()
        NotationInfo, _, _, _ = _import_types()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
        )
        print_output = (
            '"_ + _" := Nat.add ?n ?m\n'
            "  (at level 50, x at level 49, left associativity)\n"
            "  : nat_scope"
        )
        manager = _make_mock_session_manager({
            'Locate "3 + 4".': locate_output,
            'Print Notation "_ + _".': print_output,
        })
        result = await two_step(
            term="3 + 4",
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, NotationInfo)
        assert result.notation_string == "_ + _"

    @pytest.mark.asyncio
    async def test_two_step_transparent_to_caller(self):
        """§4.7 MAINTAINS: Resolution is transparent — caller receives NotationInfo."""
        dispatch, _, _ = _import_dispatcher()
        NotationInfo, _, _, _ = _import_types()
        # When dispatch gets a term-like input, it should internally do two-step
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
        )
        print_output = (
            '"_ + _" := Nat.add ?n ?m\n'
            "  (at level 50, x at level 49, left associativity)\n"
            "  : nat_scope"
        )
        manager = _make_mock_session_manager({
            'Locate "3 + 4".': locate_output,
            'Print Notation "_ + _".': print_output,
        })
        result = await dispatch(
            command="print_notation",
            session_id="abc123",
            session_manager=manager,
            notation="3 + 4",
        )
        # The caller receives a NotationInfo (or NotationAmbiguity), not an error
        assert isinstance(result, NotationInfo)
        assert result.notation_string == "_ + _"


# ===========================================================================
# 8. Output Parsers — §10 (Language-Specific Notes)
# ===========================================================================

class TestParsePrintNotation:
    """Output parser for Print Notation raw output."""

    def test_parses_standard_output(self):
        """Parses the standard Print Notation output format (Coq 8.19+)."""
        parse_print_notation, _, _, _ = _import_parsers()
        NotationInfo, _, _, _ = _import_types()
        raw = (
            '"_ ++ _" := app (A:=?A) ?l ?m\n'
            "  (at level 60, x at level 59, y at level 60, right associativity)\n"
            "  : list_scope"
        )
        result = parse_print_notation(raw)
        assert isinstance(result, NotationInfo)
        assert result.notation_string == "_ ++ _"
        assert result.expansion == "app (A:=?A) ?l ?m"
        assert result.level == 60
        assert result.associativity == "right"
        assert result.scope == "list_scope"
        assert result.arg_levels == [("x", 59), ("y", 60)]

    def test_parses_left_associativity(self):
        """Correctly parses left associativity."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ + _" := Nat.add ?n ?m\n'
            "  (at level 50, x at level 49, left associativity)\n"
            "  : nat_scope"
        )
        result = parse_print_notation(raw)
        assert result.associativity == "left"

    def test_parses_no_associativity(self):
        """Correctly parses 'no associativity' as 'none'."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ = _" := eq ?x ?y\n'
            "  (at level 70, no associativity)\n"
            "  : type_scope"
        )
        result = parse_print_notation(raw)
        assert result.associativity == "none"

    def test_parses_only_parsing_flag(self):
        """Detects (only parsing) flag."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ ≤ _" := le ?n ?m\n'
            "  (at level 70, no associativity, only parsing)\n"
            "  : nat_scope"
        )
        result = parse_print_notation(raw)
        assert result.only_parsing is True
        assert result.only_printing is False

    def test_parses_only_printing_flag(self):
        """Detects (only printing) flag."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ ≤ _" := le ?n ?m\n'
            "  (at level 70, no associativity, only printing)\n"
            "  : nat_scope"
        )
        result = parse_print_notation(raw)
        assert result.only_parsing is False
        assert result.only_printing is True

    def test_format_null_when_absent(self):
        """format is null when no format directive is defined (§5)."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ ++ _" := app (A:=?A) ?l ?m\n'
            "  (at level 60, right associativity)\n"
            "  : list_scope"
        )
        result = parse_print_notation(raw)
        assert result.format is None

    def test_raises_parse_error_on_malformed_output(self):
        """§7.3: Raises ParseError with raw output when format is not recognized."""
        parse_print_notation, _, _, _ = _import_parsers()
        with pytest.raises(Exception) as exc_info:
            parse_print_notation("completely unparseable garbage")
        error_str = str(exc_info.value)
        assert "parse" in error_str.lower() or "PARSE_ERROR" in error_str

    def test_empty_arg_levels(self):
        """arg_levels may be empty when notation has no per-placeholder levels."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = (
            '"_ = _" := eq ?x ?y\n'
            "  (at level 70, no associativity)\n"
            "  : type_scope"
        )
        result = parse_print_notation(raw)
        assert isinstance(result.arg_levels, list)


class TestParseLocateNotation:
    """Output parser for Locate Notation raw output."""

    def test_parses_multiple_interpretations(self):
        """Parses output with multiple scope interpretations."""
        _, parse_locate, _, _ = _import_parsers()
        _, _, _, NotationInterpretation = _import_types()
        raw = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        result = parse_locate(raw)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, NotationInterpretation) for r in result)

    def test_identifies_default_interpretation(self):
        """Marks exactly one entry as is_default=True."""
        _, parse_locate, _, _ = _import_parsers()
        raw = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        result = parse_locate(raw)
        defaults = [r for r in result if r.is_default]
        assert len(defaults) == 1
        assert defaults[0].scope == "nat_scope"

    def test_raises_parse_error_on_malformed_output(self):
        """§7.3: Raises ParseError on unrecognized output format."""
        _, parse_locate, _, _ = _import_parsers()
        with pytest.raises(Exception):
            parse_locate("completely unparseable garbage")


class TestParsePrintScope:
    """Output parser for Print Scope raw output."""

    def test_parses_scope_with_notations(self):
        """Parses scope name and notation entries."""
        _, _, parse_scope, _ = _import_parsers()
        _, ScopeInfo, _, _ = _import_types()
        raw = (
            "nat_scope\n"
            '"_ + _" := Nat.add ?n ?m\n'
            '"_ * _" := Nat.mul ?n ?m\n'
        )
        result = parse_scope(raw)
        assert isinstance(result, ScopeInfo)
        assert result.scope_name == "nat_scope"
        assert len(result.notations) == 2

    def test_raises_parse_error_on_malformed_output(self):
        """§7.3: Raises ParseError on unrecognized output format."""
        _, _, parse_scope, _ = _import_parsers()
        with pytest.raises(Exception):
            parse_scope("")


class TestParsePrintVisibility:
    """Output parser for Print Visibility raw output."""

    def test_parses_scope_list_with_bindings(self):
        """Parses ordered scope list with optional type bindings."""
        _, _, _, parse_visibility = _import_parsers()
        raw = "nat_scope (bound to nat)\nlist_scope\ncore_scope\n"
        result = parse_visibility(raw)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == ("nat_scope", "nat")
        assert result[1] == ("list_scope", None)
        assert result[2] == ("core_scope", None)

    def test_raises_parse_error_on_malformed_output(self):
        """§7.3: Raises ParseError on unrecognized output format."""
        _, _, _, parse_visibility = _import_parsers()
        with pytest.raises(Exception):
            parse_visibility("")


# ===========================================================================
# 9. Data Model Constraints — §5
# ===========================================================================

class TestDataModel:
    """§5: Data model field types and constraints."""

    def test_notation_info_required_fields(self):
        """NotationInfo has all required fields from §5."""
        info = _make_notation_info()
        assert isinstance(info.notation_string, str)
        assert isinstance(info.expansion, str)
        assert isinstance(info.level, int)
        assert 0 <= info.level <= 200
        assert info.associativity in ("left", "right", "none")
        assert isinstance(info.arg_levels, list)
        assert info.format is None or isinstance(info.format, str)
        assert isinstance(info.scope, str)
        assert info.defining_module is None or isinstance(info.defining_module, str)
        assert isinstance(info.only_parsing, bool)
        assert isinstance(info.only_printing, bool)

    def test_scope_info_required_fields(self):
        """ScopeInfo has all required fields from §5."""
        scope = _make_scope_info()
        assert isinstance(scope.scope_name, str)
        assert scope.bound_type is None or isinstance(scope.bound_type, str)
        assert isinstance(scope.notations, list)

    def test_notation_ambiguity_required_fields(self):
        """NotationAmbiguity has all required fields from §5."""
        ambiguity = _make_notation_ambiguity()
        assert isinstance(ambiguity.notation_string, str)
        assert isinstance(ambiguity.interpretations, list)
        assert len(ambiguity.interpretations) >= 2
        assert isinstance(ambiguity.active_index, int)
        assert ambiguity.active_index >= 0
        assert ambiguity.active_index < len(ambiguity.interpretations)
        assert isinstance(ambiguity.resolution_reason, str)

    def test_notation_interpretation_required_fields(self):
        """NotationInterpretation has all required fields from §5."""
        interp = _make_notation_interpretation()
        assert isinstance(interp.expansion, str)
        assert isinstance(interp.scope, str)
        assert interp.defining_module is None or isinstance(interp.defining_module, str)
        assert isinstance(interp.priority_rank, int)
        assert interp.priority_rank >= 0
        assert isinstance(interp.is_default, bool)

    def test_notation_info_level_range(self):
        """§5: level is 0--200 inclusive."""
        NotationInfo, _, _, _ = _import_types()
        # Valid boundary values
        info_0 = _make_notation_info(level=0)
        assert info_0.level == 0
        info_200 = _make_notation_info(level=200)
        assert info_200.level == 200

    def test_notation_ambiguity_interpretations_min_length(self):
        """§5: interpretations list has length >= 2."""
        ambiguity = _make_notation_ambiguity()
        assert len(ambiguity.interpretations) >= 2

    def test_interpretation_priority_ranks_unique(self):
        """§5: priority_rank is unique within a NotationAmbiguity."""
        ambiguity = _make_notation_ambiguity()
        ranks = [i.priority_rank for i in ambiguity.interpretations]
        assert len(set(ranks)) == len(ranks)


# ===========================================================================
# 10. Version Compatibility — §7.4
# ===========================================================================

class TestVersionCompatibility:
    """§7.4: Version compatibility error handling."""

    @pytest.mark.asyncio
    async def test_unsupported_command_error_for_old_coq(self):
        """§7.4: Print Notation on Coq < 8.19 returns UNSUPPORTED_COMMAND."""
        dispatch, _, _ = _import_dispatcher()
        # Simulate Coq backend returning an error for Print Notation
        manager = _make_mock_session_manager({
            'Print Notation "_ + _".': "Error: Unknown command",
        })
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="abc123",
                session_manager=manager,
                notation="_ + _",
                coq_version="8.18",
            )
        error_str = str(exc_info.value)
        assert "UNSUPPORTED_COMMAND" in error_str or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "UNSUPPORTED_COMMAND"
        )


# ===========================================================================
# 11. Output Parse Error Handling — §7.3
# ===========================================================================

class TestOutputParseErrors:
    """§7.3: Output parsing error handling."""

    def test_parse_error_includes_raw_output(self):
        """§7.3: ParseError message includes the raw output for diagnosis."""
        parse_print_notation, _, _, _ = _import_parsers()
        raw = "unexpected format with no structure"
        try:
            parse_print_notation(raw)
            pytest.fail("Expected ParseError to be raised")
        except Exception as e:
            error_str = str(e)
            # Error message should reference the command and include raw output
            assert "print_notation" in error_str.lower() or raw in error_str

    def test_parse_error_includes_command_name(self):
        """§7.3: ParseError message includes the command name."""
        _, parse_locate, _, _ = _import_parsers()
        raw = "not valid locate output"
        try:
            parse_locate(raw)
            pytest.fail("Expected ParseError to be raised")
        except Exception as e:
            error_str = str(e)
            # Should reference locate_notation or Locate
            assert "locate" in error_str.lower() or "PARSE_ERROR" in error_str


# ===========================================================================
# 12. Spec Example Tests — §9
# ===========================================================================

class TestSpecExamples:
    """§9: Tests derived directly from specification examples."""

    @pytest.mark.asyncio
    async def test_print_notation_example(self):
        """§9 Example 1: Print Notation for ++ returns expected structure."""
        dispatch, _, _ = _import_dispatcher()
        NotationInfo, _, _, _ = _import_types()
        raw_output = (
            '"_ ++ _" := app (A:=?A) ?l ?m\n'
            "  (at level 60, x at level 59, y at level 60, right associativity)\n"
            "  : list_scope"
        )
        manager = _make_mock_session_manager({
            'Print Notation "_ ++ _".': raw_output,
        })
        result = await dispatch(
            command="print_notation",
            session_id="abc123",
            session_manager=manager,
            notation="++",
        )
        assert isinstance(result, NotationInfo)
        assert result.notation_string == "_ ++ _"
        assert result.level == 60
        assert result.associativity == "right"
        assert result.scope == "list_scope"
        assert result.only_parsing is False
        assert result.only_printing is False

    @pytest.mark.asyncio
    async def test_locate_notation_example(self):
        """§9 Example 2: Locate Notation for + returns two interpretations."""
        dispatch, _, _ = _import_dispatcher()
        _, _, _, NotationInterpretation = _import_types()
        raw_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        manager = _make_mock_session_manager({
            'Locate "_ + _".': raw_output,
        })
        result = await dispatch(
            command="locate_notation",
            session_id="abc123",
            session_manager=manager,
            notation="+",
        )
        assert isinstance(result, list)
        assert len(result) == 2
        nat_interp = [r for r in result if r.scope == "nat_scope"][0]
        assert nat_interp.expansion == "Nat.add ?n ?m"
        assert nat_interp.is_default is True
        z_interp = [r for r in result if r.scope == "Z_scope"][0]
        assert z_interp.is_default is False

    @pytest.mark.asyncio
    async def test_ambiguity_resolution_example(self):
        """§9 Example 4: Ambiguity resolution for + with nat_scope at rank 0."""
        _, resolve, _ = _import_dispatcher()
        _, _, NotationAmbiguity, _ = _import_types()
        locate_output = (
            'Notation "_ + _" := Nat.add ?n ?m : nat_scope\n'
            "  (default interpretation)\n"
            'Notation "_ + _" := Z.add ?n ?m : Z_scope\n'
        )
        visibility_output = "nat_scope (bound to nat)\nZ_scope (bound to Z)\n"
        manager = _make_mock_session_manager({
            'Locate "_ + _".': locate_output,
            "Print Visibility.": visibility_output,
        })
        result = await resolve(
            notation_string="_ + _",
            session_id="abc123",
            session_manager=manager,
        )
        assert isinstance(result, NotationAmbiguity)
        assert result.active_index == 0
        assert result.resolution_reason == "highest-priority open scope"
        assert result.interpretations[0].scope == "nat_scope"
        assert result.interpretations[1].scope == "Z_scope"

    @pytest.mark.asyncio
    async def test_error_notation_not_found_example(self):
        """§9 Example 5: Error for unknown notation @@@."""
        dispatch, _, _ = _import_dispatcher()
        manager = _make_mock_session_manager({
            'Print Notation "_ @@@ _".': "Error: Unknown notation",
        })
        with pytest.raises(Exception) as exc_info:
            await dispatch(
                command="print_notation",
                session_id="abc123",
                session_manager=manager,
                notation="@@@",
            )
        error_str = str(exc_info.value)
        assert "NOTATION_NOT_FOUND" in error_str or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOTATION_NOT_FOUND"
        )


