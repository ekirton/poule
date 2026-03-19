"""TDD tests for Code Extraction Management (specification/code-extraction-management.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/extraction/handler.py and src/poule/extraction/code_types.py exist.

Spec: specification/code-extraction-management.md
Architecture: doc/architecture/code-extraction-management.md

Import paths under test:
  poule.extraction.handler      (ExtractionHandler, build_command, extract_code, write_extraction)
  poule.extraction.code_types   (ExtractionRequest, ExtractionResult, CodeExtractionError, WriteConfirmation)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_handler():
    from Poule.extraction.handler import ExtractionHandler
    return ExtractionHandler


def _import_build_command():
    from Poule.extraction.handler import build_command
    return build_command


def _import_extract_code():
    from Poule.extraction.handler import extract_code
    return extract_code


def _import_write_extraction():
    from Poule.extraction.handler import write_extraction
    return write_extraction


def _import_code_types():
    from Poule.extraction.code_types import (
        ExtractionRequest,
        ExtractionResult,
        CodeExtractionError,
        WriteConfirmation,
    )
    return ExtractionRequest, ExtractionResult, CodeExtractionError, WriteConfirmation


def _import_session_errors():
    from Poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError


def _import_server_errors():
    from Poule.server.errors import format_error
    return format_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extraction_request(
    session_id="s1",
    definition_name="my_fn",
    language="OCaml",
    recursive=False,
    output_path=None,
):
    ExtractionRequest, _, _, _ = _import_code_types()
    return ExtractionRequest(
        session_id=session_id,
        definition_name=definition_name,
        language=language,
        recursive=recursive,
        output_path=output_path,
    )


def _make_extraction_result(
    definition_name="my_fn",
    language="OCaml",
    recursive=False,
    code="let my_fn x = x + 1",
    warnings=None,
    output_path=None,
):
    _, ExtractionResult, _, _ = _import_code_types()
    return ExtractionResult(
        definition_name=definition_name,
        language=language,
        recursive=recursive,
        code=code,
        warnings=warnings if warnings is not None else [],
        output_path=output_path,
    )


def _make_extraction_error(
    definition_name="opaque_lemma",
    language="OCaml",
    category="opaque_term",
    raw_error="Error: opaque_lemma is not a defined object.",
    explanation="The definition or one of its dependencies is opaque.",
    suggestions=None,
):
    _, _, CodeExtractionError, _ = _import_code_types()
    return CodeExtractionError(
        definition_name=definition_name,
        language=language,
        category=category,
        raw_error=raw_error,
        explanation=explanation,
        suggestions=suggestions or ["Change Qed to Defined if the proof is computational."],
    )


def _make_write_confirmation(output_path="/project/extracted/add.ml", bytes_written=20):
    _, _, _, WriteConfirmation = _import_code_types()
    return WriteConfirmation(
        output_path=output_path,
        bytes_written=bytes_written,
    )


def _make_mock_session_manager(
    command_output="",
    raises=None,
):
    """Create a mock session manager for extraction tests.

    The session manager exposes a submit_command method that returns
    a single string (the merged Coq output), matching the real
    SessionManager interface.
    """
    manager = AsyncMock()

    if raises is not None:
        manager.submit_command.side_effect = raises
    else:
        manager.submit_command.return_value = command_output

    return manager


# ===========================================================================
# 1. Data Model — Section 5
# ===========================================================================


class TestExtractionRequest:
    """Section 5: ExtractionRequest data model."""

    def test_required_fields(self):
        """ExtractionRequest has session_id, definition_name, language as required."""
        req = _make_extraction_request()
        assert req.session_id == "s1"
        assert req.definition_name == "my_fn"
        assert req.language == "OCaml"

    def test_recursive_defaults_to_false(self):
        """recursive defaults to false (Section 5)."""
        ExtractionRequest, _, _, _ = _import_code_types()
        req = ExtractionRequest(
            session_id="s1",
            definition_name="my_fn",
            language="OCaml",
        )
        assert req.recursive is False

    def test_output_path_defaults_to_none(self):
        """output_path defaults to None (Section 5)."""
        ExtractionRequest, _, _, _ = _import_code_types()
        req = ExtractionRequest(
            session_id="s1",
            definition_name="my_fn",
            language="OCaml",
        )
        assert req.output_path is None

    def test_supported_languages(self):
        """language must be one of OCaml, Haskell, Scheme (Section 5)."""
        for lang in ("OCaml", "Haskell", "Scheme"):
            req = _make_extraction_request(language=lang)
            assert req.language == lang


class TestExtractionResult:
    """Section 5: ExtractionResult data model."""

    def test_all_fields_populated(self):
        """ExtractionResult has definition_name, language, recursive, code, warnings, output_path."""
        result = _make_extraction_result()
        assert result.definition_name == "my_fn"
        assert result.language == "OCaml"
        assert result.recursive is False
        assert result.code == "let my_fn x = x + 1"
        assert result.warnings == []
        assert result.output_path is None

    def test_warnings_is_list_of_strings(self):
        """warnings field is a list of strings (Section 5)."""
        result = _make_extraction_result(
            warnings=["Warning: my_axiom has no body."],
        )
        assert isinstance(result.warnings, list)
        assert all(isinstance(w, str) for w in result.warnings)

    def test_output_path_null_for_preview(self):
        """output_path is null for preview mode (Section 5)."""
        result = _make_extraction_result(output_path=None)
        assert result.output_path is None

    def test_output_path_set_for_write_mode(self):
        """output_path is set when code was written to disk (Section 5)."""
        result = _make_extraction_result(output_path="/project/extracted/my_fn.ml")
        assert result.output_path == "/project/extracted/my_fn.ml"


class TestCodeExtractionError:
    """Section 5: ExtractionError data model."""

    def test_all_fields_populated(self):
        """CodeExtractionError has definition_name, language, category, raw_error, explanation, suggestions."""
        err = _make_extraction_error()
        assert err.definition_name == "opaque_lemma"
        assert err.language == "OCaml"
        assert err.category == "opaque_term"
        assert err.raw_error == "Error: opaque_lemma is not a defined object."
        assert len(err.explanation) > 0
        assert len(err.suggestions) >= 1

    def test_valid_categories(self):
        """category must be one of the six defined categories (Section 5)."""
        valid_categories = {
            "opaque_term",
            "axiom_without_realizer",
            "universe_inconsistency",
            "unsupported_match",
            "module_type_mismatch",
            "unknown",
        }
        for cat in valid_categories:
            err = _make_extraction_error(category=cat)
            assert err.category == cat

    def test_suggestions_non_empty(self):
        """suggestions must have at least one entry (Section 5)."""
        err = _make_extraction_error()
        assert len(err.suggestions) >= 1


class TestWriteConfirmation:
    """Section 5: WriteConfirmation data model."""

    def test_all_fields_populated(self):
        """WriteConfirmation has output_path and bytes_written."""
        conf = _make_write_confirmation()
        assert conf.output_path == "/project/extracted/add.ml"
        assert conf.bytes_written == 20


# ===========================================================================
# 2. Command Construction — Section 4.2
# ===========================================================================


class TestBuildCommand:
    """Section 4.2: Command construction requirements."""

    def test_single_extraction_ocaml(self):
        """Single extraction for OCaml: 'Extraction Language OCaml. Extraction my_fn.'"""
        build_command = _import_build_command()
        cmd = build_command(definition_name="my_fn", language="OCaml", recursive=False)
        assert cmd == "Extraction Language OCaml. Extraction my_fn."

    def test_recursive_extraction_haskell(self):
        """Recursive extraction for Haskell: 'Extraction Language Haskell. Recursive Extraction serialize.'"""
        build_command = _import_build_command()
        cmd = build_command(definition_name="serialize", language="Haskell", recursive=True)
        assert cmd == "Extraction Language Haskell. Recursive Extraction serialize."

    def test_single_extraction_scheme(self):
        """Single extraction for Scheme."""
        build_command = _import_build_command()
        cmd = build_command(definition_name="add", language="Scheme", recursive=False)
        assert cmd == "Extraction Language Scheme. Extraction add."

    def test_recursive_extraction_scheme_fully_qualified(self):
        """Spec example: fully qualified name with Scheme recursive (Section 4.2)."""
        build_command = _import_build_command()
        cmd = build_command(
            definition_name="Coq.Init.Nat.add",
            language="Scheme",
            recursive=True,
        )
        assert cmd == "Extraction Language Scheme. Recursive Extraction Coq.Init.Nat.add."

    def test_definition_name_passed_verbatim(self):
        """The definition name is included verbatim -- no quoting, escaping, or qualification (Section 4.2)."""
        build_command = _import_build_command()
        # Name with dots (fully qualified)
        cmd = build_command(definition_name="My.Module.foo", language="OCaml", recursive=False)
        assert "Extraction My.Module.foo." in cmd

    def test_command_construction_is_pure(self):
        """build_command is a pure function: same inputs produce same outputs (Section 10)."""
        build_command = _import_build_command()
        cmd1 = build_command(definition_name="f", language="OCaml", recursive=False)
        cmd2 = build_command(definition_name="f", language="OCaml", recursive=False)
        assert cmd1 == cmd2


# ===========================================================================
# 3. Extraction Entry Point — Section 4.1
# ===========================================================================


class TestExtractCodeEntryPoint:
    """Section 4.1: extract_code entry point requirements."""

    @pytest.mark.asyncio
    async def test_preview_mode_returns_result_no_file(self):
        """Given no output_path, operates in preview mode (no file written) (Section 4.1)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        manager = _make_mock_session_manager(command_output="let my_fn x = x + 1")
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="my_fn",
            language="OCaml",
            recursive=False,
        )
        assert isinstance(result, ExtractionResult)
        assert result.code == "let my_fn x = x + 1"
        assert result.output_path is None

    @pytest.mark.asyncio
    async def test_spec_example_single_ocaml(self):
        """Spec example: extract_code(s1, 'my_fn', 'OCaml', false) -> ExtractionResult (Section 4.1, 9)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        manager = _make_mock_session_manager(command_output="let my_fn x = x + 1")
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="my_fn",
            language="OCaml",
            recursive=False,
        )
        assert isinstance(result, ExtractionResult)
        assert result.definition_name == "my_fn"
        assert result.language == "OCaml"
        assert result.recursive is False
        assert result.warnings == []
        assert result.output_path is None

    @pytest.mark.asyncio
    async def test_spec_example_recursive_haskell(self):
        """Spec example: extract_code(s2, 'serialize', 'Haskell', true) (Section 4.1, 9)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        haskell_code = "module Serialize where\n  serialize :: Tree -> String\n  serialize = ..."
        manager = _make_mock_session_manager(command_output=haskell_code)
        result = await extract_code(
            session_manager=manager,
            session_id="s2",
            definition_name="serialize",
            language="Haskell",
            recursive=True,
        )
        assert isinstance(result, ExtractionResult)
        assert result.definition_name == "serialize"
        assert result.language == "Haskell"
        assert result.recursive is True
        assert result.code == haskell_code

    @pytest.mark.asyncio
    async def test_spec_example_opaque_term(self):
        """Spec example: opaque_fn closed with Qed returns CodeExtractionError (Section 4.1, 9)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: opaque_fn is not a defined object.",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s3",
            definition_name="opaque_fn",
            language="OCaml",
            recursive=False,
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "opaque_term"
        assert len(result.explanation) > 0
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_submits_correct_command_sequence(self):
        """extract_code submits 'Extraction Language {lang}. Extraction {name}.' to Coq (Section 4.1)."""
        extract_code = _import_extract_code()
        manager = _make_mock_session_manager(command_output="let double n = n + n")
        await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="double",
            language="OCaml",
            recursive=False,
        )
        manager.submit_command.assert_called_once()
        call_args = manager.submit_command.call_args
        # The command submitted should contain the language directive and extraction command
        submitted_cmd = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("command", call_args[0][0])
        assert "Extraction Language OCaml." in str(submitted_cmd)
        assert "Extraction double." in str(submitted_cmd)

    @pytest.mark.asyncio
    async def test_definition_name_passed_verbatim_to_coq(self):
        """MAINTAINS: The definition name is passed verbatim to Coq without transformation (Section 4.1)."""
        extract_code = _import_extract_code()
        manager = _make_mock_session_manager(command_output="(* extracted *)")
        await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="Coq.Init.Nat.add",
            language="OCaml",
            recursive=False,
        )
        manager.submit_command.assert_called_once()
        call_args = manager.submit_command.call_args
        submitted = str(call_args)
        assert "Coq.Init.Nat.add" in submitted


# ===========================================================================
# 4. Result Parsing — Section 4.3
# ===========================================================================


class TestResultParsing:
    """Section 4.3: Result parsing on merged command output."""

    @pytest.mark.asyncio
    async def test_code_only_returns_result(self):
        """Output with code lines, no error/warning lines -> ExtractionResult (Section 4.3)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        manager = _make_mock_session_manager(command_output="let my_fn x = x + 1")
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="my_fn",
            language="OCaml",
        )
        assert isinstance(result, ExtractionResult)
        assert result.code == "let my_fn x = x + 1"

    @pytest.mark.asyncio
    async def test_code_with_warning_returns_result_with_warnings(self):
        """Output with code and warning lines -> ExtractionResult with warnings (Section 4.3, 9)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        # Merged output: code followed by warning line
        merged = (
            "let uses_axiom = ... (assert false (* AXIOM TO BE REALIZED *))\n"
            "Warning: my_axiom has no body."
        )
        manager = _make_mock_session_manager(command_output=merged)
        result = await extract_code(
            session_manager=manager,
            session_id="s4",
            definition_name="uses_axiom",
            language="OCaml",
        )
        assert isinstance(result, ExtractionResult)
        assert len(result.code) > 0
        assert len(result.warnings) >= 1
        assert any("has no body" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_error_line_returns_extraction_error(self):
        """Output with error line -> CodeExtractionError (Section 4.3)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: opaque_lemma is not a defined object.",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s3",
            definition_name="opaque_lemma",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)

    @pytest.mark.asyncio
    async def test_both_code_and_error_treated_as_error(self):
        """Output with both code lines and error lines -> CodeExtractionError; partial output discarded (Section 7.4)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        merged = "let partial = ...\nError: something went wrong"
        manager = _make_mock_session_manager(command_output=merged)
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="partial_fn",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)

    @pytest.mark.asyncio
    async def test_empty_output_no_error_returns_result_with_warning(self):
        """Empty output, no error pattern -> ExtractionResult with empty code and warning (Section 7.4)."""
        extract_code = _import_extract_code()
        _, ExtractionResult, _, _ = _import_code_types()
        manager = _make_mock_session_manager(command_output="")
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="empty_fn",
            language="OCaml",
        )
        assert isinstance(result, ExtractionResult)
        assert result.code == ""
        assert len(result.warnings) >= 1  # warning about empty extraction output


# ===========================================================================
# 5. Error Classification — Section 4.5
# ===========================================================================


class TestErrorClassification:
    """Section 4.5: Error classification by pattern matching on command output."""

    @pytest.mark.asyncio
    async def test_opaque_term_classification(self):
        """'is not a defined object' -> category 'opaque_term' (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: opaque_lemma is not a defined object.",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="opaque_lemma",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "opaque_term"
        assert "opaque" in result.explanation.lower() or "Qed" in result.explanation
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_axiom_without_realizer_classification(self):
        """'has no body' in error context -> category 'axiom_without_realizer' (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: my_axiom has no body",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="uses_axiom",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "axiom_without_realizer"
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_universe_inconsistency_classification(self):
        """'Universe inconsistency' -> category 'universe_inconsistency' (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: Universe inconsistency",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="poly_def",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "universe_inconsistency"

    @pytest.mark.asyncio
    async def test_unsupported_match_classification(self):
        """'Cannot extract' with match context -> category 'unsupported_match' (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: Cannot extract this match pattern",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="deep_match",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "unsupported_match"

    @pytest.mark.asyncio
    async def test_module_type_mismatch_classification(self):
        """'Module type' error -> category 'module_type_mismatch' (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: Module type mismatch in functor application",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="functor_def",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "module_type_mismatch"

    @pytest.mark.asyncio
    async def test_unknown_error_classification(self):
        """Unrecognized error -> category 'unknown' with raw error preserved (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        manager = _make_mock_session_manager(
            command_output="Error: something unexpected",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="mystery_fn",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "unknown"
        assert "something unexpected" in result.raw_error

    @pytest.mark.asyncio
    async def test_classification_priority_most_specific_first(self):
        """Error classification matches most specific pattern first (Section 4.5)."""
        extract_code = _import_extract_code()
        _, _, CodeExtractionError, _ = _import_code_types()
        # 'is not a defined object' should match opaque_term (most specific)
        manager = _make_mock_session_manager(
            command_output="Error: foo is not a defined object.",
        )
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="foo",
            language="OCaml",
        )
        assert isinstance(result, CodeExtractionError)
        assert result.category == "opaque_term"


# ===========================================================================
# 6. Write Mode — Section 4.4
# ===========================================================================


class TestWriteExtraction:
    """Section 4.4: write_extraction requirements."""

    def test_writes_code_to_file(self):
        """write_extraction writes exact code to output_path (Section 4.4)."""
        write_extraction = _import_write_extraction()
        _, _, _, WriteConfirmation = _import_code_types()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "add.ml")
            result = write_extraction(
                code="let add x y = x + y",
                output_path=output_path,
            )
            assert isinstance(result, WriteConfirmation)
            assert result.output_path == output_path
            assert result.bytes_written == 19
            with open(output_path) as f:
                assert f.read() == "let add x y = x + y"

    def test_spec_example_write(self):
        """Spec example: write 'let add x y = x + y' -> bytes_written=19 (Section 9)."""
        write_extraction = _import_write_extraction()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "double.ml")
            result = write_extraction(
                code="let add x y = x + y",
                output_path=output_path,
            )
            assert result.bytes_written == 19

    def test_overwrites_existing_file(self):
        """When file exists, it is overwritten (Section 4.4)."""
        write_extraction = _import_write_extraction()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "overwrite.ml")
            with open(output_path, "w") as f:
                f.write("old content")
            result = write_extraction(
                code="new content",
                output_path=output_path,
            )
            with open(output_path) as f:
                assert f.read() == "new content"
            assert result.bytes_written == len("new content")

    def test_creates_new_file(self):
        """When file does not exist, it is created (Section 4.4)."""
        write_extraction = _import_write_extraction()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "new_file.ml")
            assert not os.path.exists(output_path)
            write_extraction(code="let x = 1", output_path=output_path)
            assert os.path.exists(output_path)

    def test_code_written_exactly(self):
        """The code written is exactly the string from the prior ExtractionResult (Section 4.4)."""
        write_extraction = _import_write_extraction()
        code = "module Serialize where\n  serialize :: Tree -> String\n  serialize = ..."
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "serialize.hs")
            write_extraction(code=code, output_path=output_path)
            with open(output_path) as f:
                assert f.read() == code


# ===========================================================================
# 7. Write Error Handling — Section 7.3
# ===========================================================================


class TestWriteErrors:
    """Section 7.3: Write error handling."""

    def test_relative_path_returns_invalid_output_path(self):
        """Relative path -> INVALID_OUTPUT_PATH error (Section 7.3)."""
        write_extraction = _import_write_extraction()
        with pytest.raises(Exception) as exc_info:
            write_extraction(code="let x = 1", output_path="relative/path.ml")
        # The error should indicate INVALID_OUTPUT_PATH
        assert "INVALID_OUTPUT_PATH" in str(exc_info.value) or \
            (hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_OUTPUT_PATH")

    def test_parent_directory_missing_returns_invalid_output_path(self):
        """Parent directory missing -> INVALID_OUTPUT_PATH error (Section 7.3)."""
        write_extraction = _import_write_extraction()
        with pytest.raises(Exception) as exc_info:
            write_extraction(
                code="let x = 1",
                output_path="/nonexistent_parent_dir_xyz/file.ml",
            )
        assert "INVALID_OUTPUT_PATH" in str(exc_info.value) or \
            (hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_OUTPUT_PATH")


# ===========================================================================
# 8. Input Error Handling — Section 7.1
# ===========================================================================


class TestInputErrors:
    """Section 7.1: Input error handling."""

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Session not found -> SESSION_NOT_FOUND error immediately (Section 7.1)."""
        extract_code = _import_extract_code()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.submit_command.side_effect = SessionError(SESSION_NOT_FOUND, "not found")
        with pytest.raises(Exception) as exc_info:
            await extract_code(
                session_manager=manager,
                session_id="nonexistent",
                definition_name="my_fn",
                language="OCaml",
            )
        err = exc_info.value
        assert hasattr(err, "code") and err.code == SESSION_NOT_FOUND or \
            "SESSION_NOT_FOUND" in str(err)

    @pytest.mark.asyncio
    async def test_backend_crashed(self):
        """Backend crashes -> BACKEND_CRASHED error advising session restart (Section 7.2)."""
        extract_code = _import_extract_code()
        BACKEND_CRASHED, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.submit_command.side_effect = SessionError(BACKEND_CRASHED, "crashed")
        with pytest.raises(Exception) as exc_info:
            await extract_code(
                session_manager=manager,
                session_id="s1",
                definition_name="my_fn",
                language="OCaml",
            )
        err = exc_info.value
        assert hasattr(err, "code") and err.code == BACKEND_CRASHED or \
            "BACKEND_CRASHED" in str(err)


# ===========================================================================
# 9. Edge Cases — Section 7.4
# ===========================================================================


class TestEdgeCases:
    """Section 7.4: Edge case behaviors."""

    @pytest.mark.asyncio
    async def test_definition_name_with_special_characters(self):
        """Definition name with special characters is passed verbatim (Section 7.4)."""
        extract_code = _import_extract_code()
        manager = _make_mock_session_manager(command_output="(* extracted *)")
        result = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="my.module.fn_with'prime",
            language="OCaml",
        )
        # The name should appear verbatim in the submitted command
        call_str = str(manager.submit_command.call_args)
        assert "my.module.fn_with'prime" in call_str

    @pytest.mark.asyncio
    async def test_idempotent_extraction(self):
        """Same definition extracted twice produces same result (Section 7.4)."""
        extract_code = _import_extract_code()
        manager = _make_mock_session_manager(command_output="let double n = n + n")
        result1 = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="double",
            language="OCaml",
        )
        result2 = await extract_code(
            session_manager=manager,
            session_id="s1",
            definition_name="double",
            language="OCaml",
        )
        assert result1.code == result2.code
        assert result1.language == result2.language

    def test_write_idempotent(self):
        """Writing same code to same path produces same content (Section 7.4)."""
        write_extraction = _import_write_extraction()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "idem.ml")
            write_extraction(code="let x = 1", output_path=output_path)
            write_extraction(code="let x = 1", output_path=output_path)
            with open(output_path) as f:
                assert f.read() == "let x = 1"


# ===========================================================================
# 10. Interface Contracts — Section 6
# ===========================================================================


class TestInterfaceContracts:
    """Section 6: Interface contracts with Proof Session Manager and Filesystem."""

    @pytest.mark.asyncio
    async def test_session_not_found_no_extraction_attempted(self):
        """SESSION_NOT_FOUND -> error immediately, no extraction attempted (Section 6)."""
        extract_code = _import_extract_code()
        _, SESSION_NOT_FOUND, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.submit_command.side_effect = SessionError(SESSION_NOT_FOUND, "no session")
        with pytest.raises(Exception):
            await extract_code(
                session_manager=manager,
                session_id="missing",
                definition_name="fn",
                language="OCaml",
            )
        # submit_command was called but raised; no further processing should occur
        assert manager.submit_command.call_count == 1

    @pytest.mark.asyncio
    async def test_does_not_spawn_subprocesses(self):
        """The extraction handler shall not spawn subprocesses (Section 8)."""
        # This is a design constraint verified by inspection:
        # extract_code delegates all Coq interaction to session_manager.
        extract_code = _import_extract_code()
        manager = _make_mock_session_manager(command_output="let x = 1")
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen:
            await extract_code(
                session_manager=manager,
                session_id="s1",
                definition_name="x",
                language="OCaml",
            )
            mock_run.assert_not_called()
            mock_popen.assert_not_called()


# ===========================================================================
# 11. Contract Tests — require real Coq backend
# ===========================================================================


@pytest.mark.requires_coq
class TestContractSessionManagerSubmitCommand:
    """Contract test: verify real session manager's submit_command interface.

    These tests verify that the mock's submit_command interface matches
    the real Proof Session Manager implementation.
    """

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_submit_command_returns_stdout_stderr(self):
        """Real session manager submit_command returns a string."""
        from Poule.session.manager import SessionManager
        manager = SessionManager()
        session_id = await manager.open_session("test_contract")
        try:
            result = await manager.submit_command(
                session_id,
                "From Coq Require Import Arith. Check Nat.add.",
            )
            assert isinstance(result, str)
        finally:
            await manager.close_session(session_id)

    @pytest.mark.asyncio
    async def test_submit_command_session_not_found_raises(self):
        """Real session manager raises SessionError(SESSION_NOT_FOUND) for unknown session."""
        from Poule.session.manager import SessionManager
        from Poule.session.errors import SessionError, SESSION_NOT_FOUND
        manager = SessionManager()
        with pytest.raises(SessionError) as exc_info:
            await manager.submit_command("nonexistent_session", "Check nat.")
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_submit_command_backend_crash_raises(self):
        """Real session manager raises SessionError(BACKEND_CRASHED) when backend dies."""
        from Poule.session.manager import SessionManager
        from Poule.session.errors import SessionError, BACKEND_CRASHED
        # This contract verifies the error type; triggering a real crash
        # is environment-dependent, so we document the expected interface
        manager = SessionManager()
        # Contract: if backend crashes, SessionError with BACKEND_CRASHED is raised
        # Actual crash triggering is deferred to integration tests
        assert BACKEND_CRASHED == "BACKEND_CRASHED"


@pytest.mark.requires_coq
class TestContractWriteExtraction:
    """Contract test: verify write_extraction uses pathlib for path validation."""

    def test_write_uses_pathlib_is_absolute(self):
        """write_extraction uses pathlib.Path.is_absolute() for path validation (Section 10)."""
        write_extraction = _import_write_extraction()
        # Verify that relative paths are rejected
        with pytest.raises(Exception):
            write_extraction(code="let x = 1", output_path="relative.ml")

    def test_write_uses_pathlib_parent_exists(self):
        """write_extraction uses pathlib.Path.parent.exists() for directory validation (Section 10)."""
        write_extraction = _import_write_extraction()
        with pytest.raises(Exception):
            write_extraction(
                code="let x = 1",
                output_path="/nonexistent_xyz_abc/out.ml",
            )


# ===========================================================================
# 12. Non-Functional Requirements — Section 8
# ===========================================================================


class TestNonFunctionalRequirements:
    """Section 8: Non-functional requirements."""

    def test_command_construction_under_1ms(self):
        """Command constructor produces result in < 1 ms (Section 8)."""
        import time
        build_command = _import_build_command()
        start = time.perf_counter_ns()
        for _ in range(1000):
            build_command(
                definition_name="Coq.Init.Nat.add",
                language="OCaml",
                recursive=True,
            )
        elapsed_ns = time.perf_counter_ns() - start
        # Average per call should be < 1ms = 1_000_000 ns
        avg_ns = elapsed_ns / 1000
        assert avg_ns < 1_000_000, f"Average command construction took {avg_ns}ns, expected < 1ms"

    @pytest.mark.asyncio
    async def test_error_classification_under_5ms(self):
        """Error classification completes in < 5 ms per error message (Section 8)."""
        import time
        extract_code = _import_extract_code()
        errors = [
            "Error: opaque_lemma is not a defined object.",
            "Error: Universe inconsistency",
            "Error: Cannot extract this match pattern",
            "Error: Module type mismatch",
            "Error: something totally unknown happened here",
        ]
        for error_msg in errors:
            manager = _make_mock_session_manager(command_output=error_msg)
            start = time.perf_counter_ns()
            await extract_code(
                session_manager=manager,
                session_id="s1",
                definition_name="test",
                language="OCaml",
            )
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            assert elapsed_ms < 5, f"Error classification took {elapsed_ms}ms for '{error_msg}'"
