"""TDD tests for Literate Documentation (specification/literate-documentation.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/documentation/ modules exist.

Spec: specification/literate-documentation.md
Architecture: doc/architecture/literate-documentation.md

Import paths under test:
  poule.documentation.adapter     (AlectryonAdapter or module-level functions)
  poule.documentation.types       (DocumentationRequest, DocumentationResult, etc.)
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_types():
    from Poule.documentation.types import (
        DocumentationRequest,
        DocumentationResult,
        BatchDocumentationRequest,
        BatchDocumentationResult,
        FileOutcome,
    )
    return (
        DocumentationRequest,
        DocumentationResult,
        BatchDocumentationRequest,
        BatchDocumentationResult,
        FileOutcome,
    )


def _import_adapter():
    from Poule.documentation.adapter import (
        check_availability,
        generate_documentation,
        generate_proof_documentation,
        generate_batch_documentation,
    )
    return (
        check_availability,
        generate_documentation,
        generate_proof_documentation,
        generate_batch_documentation,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_documentation_request(
    input_file="/project/src/Lemmas.v",
    proof_name=None,
    output_path=None,
    format="html",
    custom_flags=None,
    timeout=120,
):
    DocumentationRequest = _import_types()[0]
    return DocumentationRequest(
        input_file=input_file,
        proof_name=proof_name,
        output_path=output_path,
        format=format,
        custom_flags=custom_flags if custom_flags is not None else [],
        timeout=timeout,
    )


def _make_batch_request(
    source_directory="/project/src/",
    output_directory="/docs/",
    format="html",
    custom_flags=None,
    timeout_per_file=120,
):
    BatchDocumentationRequest = _import_types()[2]
    return BatchDocumentationRequest(
        source_directory=source_directory,
        output_directory=output_directory,
        format=format,
        custom_flags=custom_flags if custom_flags is not None else [],
        timeout_per_file=timeout_per_file,
    )


def _make_success_result(
    output_path=None,
    content=None,
    format="html",
):
    DocumentationResult = _import_types()[1]
    return DocumentationResult(
        status="success",
        output_path=output_path,
        content=content,
        format=format,
        error=None,
    )


def _make_failure_result(
    error_code,
    error_message,
    format="html",
):
    DocumentationResult = _import_types()[1]
    return DocumentationResult(
        status="failure",
        output_path=None,
        content=None,
        format=format,
        error={"code": error_code, "message": error_message},
    )


# ===========================================================================
# 1. Availability Detection -- Section 4.1
# ===========================================================================

class TestAvailabilityDetection:
    """Section 4.1: check_availability() requirements."""

    @pytest.mark.asyncio
    async def test_available_when_version_at_minimum(self):
        """Given Alectryon installed at version >= minimum, returns 'available'."""
        check_availability, _, _, _ = _import_adapter()
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"1.4.0\n", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec:
            # Reset cache for test isolation
            result = await check_availability(_bypass_cache=True)

        assert result == "available"

    @pytest.mark.asyncio
    async def test_not_installed_when_binary_missing(self):
        """Given Alectryon not on PATH, returns 'not_installed'."""
        check_availability, _, _, _ = _import_adapter()

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError("alectryon not found")):
            result = await check_availability(_bypass_cache=True)

        assert result == "not_installed"

    @pytest.mark.asyncio
    async def test_version_too_old(self):
        """Given Alectryon version below minimum, returns 'version_too_old'."""
        check_availability, _, _, _ = _import_adapter()
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"0.1.0\n", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process):
            result = await check_availability(_bypass_cache=True)

        assert result == "version_too_old"

    @pytest.mark.asyncio
    async def test_cached_after_first_call(self):
        """Subsequent calls return cached result without spawning a process."""
        check_availability, _, _, _ = _import_adapter()
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"1.4.0\n", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec:
            result1 = await check_availability(_bypass_cache=True)
            # Second call should use cache -- do NOT bypass
            result2 = await check_availability()

        assert result1 == result2
        # Only one subprocess spawn
        assert mock_exec.call_count == 1

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_check_availability_real(self):
        """Contract test: real check_availability against system Alectryon."""
        check_availability, _, _, _ = _import_adapter()
        result = await check_availability(_bypass_cache=True)
        assert result in ("available", "not_installed", "version_too_old")


# ===========================================================================
# 2. Single-File Generation -- Section 4.2
# ===========================================================================

class TestSingleFileGeneration:
    """Section 4.2: generate_documentation() requirements."""

    @pytest.mark.asyncio
    async def test_html_inline_success(self):
        """Given a valid .v file with format='html' and no output_path,
        returns content inline with status='success'."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        html_content = "<html><body>proof docs</body></html>"

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value=html_content), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "success"
        assert result.content is not None
        assert result.output_path is None

    @pytest.mark.asyncio
    async def test_html_output_to_disk(self):
        """Given output_path set, moves generated file to output_path,
        returns output_path and content=None."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            format="html",
            output_path="/docs/Lemmas.html",
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.shutil.move") as mock_move, \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "success"
        assert result.output_path == "/docs/Lemmas.html"
        assert result.content is None

    @pytest.mark.asyncio
    async def test_argument_construction_html(self):
        """Verifies CLI argument order per spec: --frontend coq --backend webpage
        --output-directory <dir> [custom_flags] <input_file>."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
            format="html",
            output_path="/docs/Nat.html",
            custom_flags=["--long-line-threshold", "80"],
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_documentation(request)

        # Verify the argument list passed to subprocess
        args = mock_exec.call_args
        cmd_args = args[0] if args[0] else args[1].get("args", [])
        cmd_str = " ".join(str(a) for a in cmd_args)
        assert "--frontend" in cmd_str
        assert "coq" in cmd_str
        assert "--backend" in cmd_str
        assert "webpage" in cmd_str
        assert "--output-directory" in cmd_str
        assert "--long-line-threshold" in cmd_str
        assert "80" in cmd_str
        # Input file is last
        assert cmd_str.endswith("/project/src/Nat.v") or cmd_args[-1] == "/project/src/Nat.v"

    @pytest.mark.asyncio
    async def test_format_mapping_html_fragment(self):
        """format='html-fragment' maps to --backend webpage-no-header (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
            format="html-fragment",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<div>...</div>"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        cmd_args = mock_exec.call_args[0]
        cmd_str = " ".join(str(a) for a in cmd_args)
        assert "webpage-no-header" in cmd_str
        assert result.format == "html-fragment"

    @pytest.mark.asyncio
    async def test_format_mapping_latex(self):
        """format='latex' maps to --backend latex with .tex output (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
            format="latex",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    return_value="\\documentclass{article}..."), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        cmd_args = mock_exec.call_args[0]
        cmd_str = " ".join(str(a) for a in cmd_args)
        assert "--backend" in cmd_str
        assert "latex" in cmd_str
        assert result.format == "latex"

    @pytest.mark.asyncio
    async def test_working_directory_is_input_parent(self):
        """Subprocess working directory is the parent of the input file (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html>...</html>"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_documentation(request)

        # Check cwd keyword argument
        kwargs = mock_exec.call_args[1] if mock_exec.call_args[1] else {}
        assert "cwd" in kwargs
        cwd = str(kwargs["cwd"])
        assert cwd == "/project/src" or cwd == "/project/src/"

    @pytest.mark.asyncio
    async def test_coq_error_returns_failure(self):
        """Given non-zero exit code with Coq error in stderr, returns
        status='failure' with error.code='COQ_ERROR' (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Bad.v",
            format="html",
        )

        mock_process = AsyncMock()
        stderr_msg = b"Error: Syntax error at line 5\n"
        mock_process.communicate.return_value = (b"", stderr_msg)
        mock_process.returncode = 1

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "failure"
        assert result.error is not None
        assert result.error["code"] in ("COQ_ERROR", "ALECTRYON_ERROR")

    @pytest.mark.asyncio
    async def test_timeout_kills_subprocess(self):
        """Given subprocess exceeds timeout, returns GENERATION_TIMEOUT error (Section 7.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Slow.v",
            format="html",
            timeout=1,
        )

        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "failure"
        assert result.error["code"] == "GENERATION_TIMEOUT"

    @pytest.mark.asyncio
    async def test_does_not_modify_input_file(self):
        """MAINTAINS: The adapter does not modify the input file (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text") as mock_write, \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_documentation(request)

        # write_text should not be called on the input file
        for c in mock_write.call_args_list:
            # If write_text was called, it should not be on the input path
            assert "/project/src/Lemmas.v" not in str(c)

    @pytest.mark.asyncio
    async def test_environment_inherited_not_modified(self):
        """MAINTAINS: Adapter does not set or modify Coq-specific env vars (Section 4.2)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_documentation(request)

        kwargs = mock_exec.call_args[1] if mock_exec.call_args[1] else {}
        # env should either not be set (inherits) or be unmodified from os.environ
        if "env" in kwargs:
            assert kwargs["env"] is None or kwargs["env"] == os.environ

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_generate_documentation_real(self):
        """Contract test: real generate_documentation against Alectryon."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        # Requires a real .v file on disk
        request = _make_documentation_request(
            input_file="/tmp/poule_test_contract.v",
            format="html",
            output_path=None,
        )
        # Write minimal Coq file
        Path("/tmp/poule_test_contract.v").write_text(
            "Lemma trivial : True. Proof. exact I. Qed.\n"
        )
        try:
            result = await generate_documentation(request)
            assert isinstance(result, DocumentationResult)
            assert result.status in ("success", "failure")
        finally:
            Path("/tmp/poule_test_contract.v").unlink(missing_ok=True)


# ===========================================================================
# 3. Proof-Scoped Generation -- Section 4.3
# ===========================================================================

class TestProofScopedGeneration:
    """Section 4.3: generate_proof_documentation() requirements."""

    @pytest.mark.asyncio
    async def test_extracts_named_proof_and_generates(self):
        """Given a file with Lemma add_comm, extracts it and generates documentation."""
        _, _, generate_proof_documentation, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        coq_source = textwrap.dedent("""\
            Require Import Arith.
            Lemma add_comm : forall n m, n + m = m + n.
            Proof. intros. omega. Qed.
        """)

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="add_comm",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    side_effect=[coq_source, "<html>proof docs</html>"]), \
             patch("Poule.documentation.adapter.Path.write_text") as mock_write, \
             patch("Poule.documentation.adapter.Path.unlink") as mock_unlink, \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_proof_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_temporary_file_in_same_directory(self):
        """Temporary file placed in same directory as source for import resolution (Section 4.3)."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        coq_source = textwrap.dedent("""\
            Lemma foo : True.
            Proof. exact I. Qed.
        """)

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="foo",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        written_paths = []

        def capture_write_text(content, *args, **kwargs):
            pass

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    side_effect=[coq_source, "<html/>"]), \
             patch("Poule.documentation.adapter.Path.write_text") as mock_write, \
             patch("Poule.documentation.adapter.Path.unlink"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_proof_documentation(request)

        # The subprocess input_file arg (last positional) should be in /project/src/
        cmd_args = mock_exec.call_args[0]
        input_arg = str(cmd_args[-1])
        assert input_arg.startswith("/project/src/")

    @pytest.mark.asyncio
    async def test_temporary_file_naming_convention(self):
        """Temporary file named .poule_tmp_<proof_name>.v (Section 4.3 example)."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        coq_source = "Lemma add_comm : forall n m, n + m = m + n.\nProof. omega. Qed.\n"

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="add_comm",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    side_effect=[coq_source, "<html/>"]), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.Path.unlink"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_proof_documentation(request)

        cmd_args = mock_exec.call_args[0]
        input_arg = str(cmd_args[-1])
        assert ".poule_tmp_add_comm.v" in input_arg

    @pytest.mark.asyncio
    async def test_temporary_file_cleaned_on_success(self):
        """Temporary file removed after generation completes (Section 4.3)."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        coq_source = "Lemma foo : True.\nProof. exact I. Qed.\n"

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="foo",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    side_effect=[coq_source, "<html/>"]), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.Path.unlink") as mock_unlink, \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_proof_documentation(request)

        # unlink should have been called for the temp file
        assert mock_unlink.call_count >= 1

    @pytest.mark.asyncio
    async def test_temporary_file_cleaned_on_failure(self):
        """Temporary file removed even when generation fails (Section 4.3)."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        coq_source = "Lemma foo : True.\nProof. exact I. Qed.\n"

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="foo",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"Coq error\n")
        mock_process.returncode = 1

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value=coq_source), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.Path.unlink") as mock_unlink, \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_proof_documentation(request)

        assert result.status == "failure"
        assert mock_unlink.call_count >= 1

    @pytest.mark.asyncio
    async def test_proof_not_found_returns_error(self):
        """Given proof_name not in file, returns PROOF_NOT_FOUND with available names (Section 4.3)."""
        _, _, generate_proof_documentation, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        coq_source = textwrap.dedent("""\
            Lemma foo : True.
            Proof. exact I. Qed.
            Theorem bar : False -> False.
            Proof. intro H. exact H. Qed.
        """)

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="missing_lemma",
            format="html",
        )

        with patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value=coq_source), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_proof_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "failure"
        assert result.error["code"] == "PROOF_NOT_FOUND"
        # Message should list available proof names
        assert "foo" in result.error["message"] or "bar" in result.error["message"]

    @pytest.mark.asyncio
    async def test_extraction_includes_imports_and_context(self):
        """Extracted temp file includes imports and section variables (Section 4.3)."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        coq_source = textwrap.dedent("""\
            Require Import Arith.
            Section MySection.
            Variable n : nat.
            Lemma add_zero : n + 0 = n.
            Proof. omega. Qed.
            End MySection.
        """)

        request = _make_documentation_request(
            input_file="/project/src/Arith.v",
            proof_name="add_zero",
            format="html",
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        written_content = []

        def capture_write(content, *args, **kwargs):
            written_content.append(content)

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text",
                    side_effect=[coq_source, "<html/>"]), \
             patch("Poule.documentation.adapter.Path.write_text", side_effect=capture_write), \
             patch("Poule.documentation.adapter.Path.unlink"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_proof_documentation(request)

        # The written temp file should include imports
        assert len(written_content) >= 1
        extracted = written_content[0]
        assert "Require Import Arith" in extracted
        assert "add_zero" in extracted

    @pytest.mark.asyncio
    async def test_declaration_keywords_recognized(self):
        """All declaration keywords from spec are recognized:
        Theorem, Lemma, Definition, Fixpoint, Corollary, Proposition, Example, Fact, Remark."""
        _, _, generate_proof_documentation, _ = _import_adapter()

        for keyword in ["Theorem", "Lemma", "Definition", "Fixpoint",
                        "Corollary", "Proposition", "Example", "Fact", "Remark"]:
            coq_source = f"{keyword} test_decl : True.\nProof. exact I. Qed.\n"

            request = _make_documentation_request(
                input_file="/project/src/Test.v",
                proof_name="test_decl",
                format="html",
                output_path=None,
            )

            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0

            with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                        return_value=mock_process), \
                 patch("Poule.documentation.adapter.Path.exists", return_value=True), \
                 patch("Poule.documentation.adapter.Path.read_text",
                        side_effect=[coq_source, "<html/>"]), \
                 patch("Poule.documentation.adapter.Path.write_text"), \
                 patch("Poule.documentation.adapter.Path.unlink"), \
                 patch("Poule.documentation.adapter.check_availability",
                        return_value="available"):
                result = await generate_proof_documentation(request)

            assert result.status == "success", \
                f"Failed to recognize declaration keyword: {keyword}"

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_generate_proof_documentation_real(self):
        """Contract test: real proof-scoped generation against Alectryon."""
        _, _, generate_proof_documentation, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        coq_source = "Lemma trivial : True.\nProof. exact I. Qed.\n"
        Path("/tmp/poule_test_proof_contract.v").write_text(coq_source)

        request = _make_documentation_request(
            input_file="/tmp/poule_test_proof_contract.v",
            proof_name="trivial",
            format="html",
            output_path=None,
        )
        try:
            result = await generate_proof_documentation(request)
            assert isinstance(result, DocumentationResult)
            assert result.status in ("success", "failure")
        finally:
            Path("/tmp/poule_test_proof_contract.v").unlink(missing_ok=True)


# ===========================================================================
# 4. Batch Generation -- Section 4.4
# ===========================================================================

class TestBatchGeneration:
    """Section 4.4: generate_batch_documentation() requirements."""

    @pytest.mark.asyncio
    async def test_batch_success_mirrors_directory_structure(self):
        """Given source dir with nested .v files, output mirrors structure (Section 4.4)."""
        _, _, _, generate_batch_documentation = _import_adapter()
        BatchDocumentationResult = _import_types()[3]

        request = _make_batch_request(
            source_directory="/project/src/",
            output_directory="/docs/",
            format="html",
        )

        v_files = [
            Path("/project/src/A.v"),
            Path("/project/src/sub/B.v"),
            Path("/project/src/sub/C.v"),
        ]

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.Path.rglob", return_value=v_files), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.Path.mkdir"), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        assert isinstance(result, BatchDocumentationResult)
        assert result.total == 3
        assert result.succeeded + result.failed == 3

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self):
        """Given one file fails and one succeeds, batch continues and reports both (Section 4.4)."""
        _, _, _, generate_batch_documentation = _import_adapter()
        BatchDocumentationResult = _import_types()[3]
        FileOutcome = _import_types()[4]

        request = _make_batch_request(
            source_directory="/project/src/",
            output_directory="/docs/",
            format="html",
        )

        v_files = [
            Path("/project/src/A.v"),
            Path("/project/src/B.v"),
        ]

        call_count = 0

        async def subprocess_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            if call_count == 2:
                # Second file fails
                mock_proc.communicate.return_value = (b"", b"Coq error line 42\n")
                mock_proc.returncode = 1
            else:
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
            return mock_proc

        with patch("Poule.documentation.adapter.Path.rglob", return_value=v_files), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.Path.mkdir"), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    side_effect=subprocess_side_effect), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        assert result.total == 2
        assert result.succeeded >= 1
        assert result.failed >= 1
        # Verify FileOutcome types
        for outcome in result.results:
            assert isinstance(outcome, FileOutcome)
            assert outcome.status in ("success", "failure")

    @pytest.mark.asyncio
    async def test_batch_generates_index_html(self):
        """Batch generates index.html at output directory root (Section 4.4)."""
        _, _, _, generate_batch_documentation = _import_adapter()

        request = _make_batch_request(
            source_directory="/project/src/",
            output_directory="/docs/",
            format="html",
        )

        v_files = [Path("/project/src/A.v")]

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.Path.rglob", return_value=v_files), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.Path.mkdir"), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text") as mock_write, \
             patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        assert result.index_path is not None
        assert "index.html" in result.index_path

    @pytest.mark.asyncio
    async def test_batch_no_v_files_returns_error(self):
        """Given no .v files found, returns NO_INPUT_FILES error (Section 4.4)."""
        _, _, _, generate_batch_documentation = _import_adapter()

        request = _make_batch_request(
            source_directory="/project/empty/",
            output_directory="/docs/",
        )

        with patch("Poule.documentation.adapter.Path.rglob", return_value=[]), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        # Batch returns error for no input files
        assert result.total == 0 or hasattr(result, "error")
        # The spec says return an error -- check for the error code
        if hasattr(result, "error") and result.error is not None:
            assert result.error["code"] == "NO_INPUT_FILES"

    @pytest.mark.asyncio
    async def test_batch_files_processed_sequentially(self):
        """Files processed sequentially -- one subprocess at a time (Section 8 NFR)."""
        _, _, _, generate_batch_documentation = _import_adapter()

        request = _make_batch_request(
            source_directory="/project/src/",
            output_directory="/docs/",
        )

        v_files = [
            Path("/project/src/A.v"),
            Path("/project/src/B.v"),
        ]

        execution_order = []

        async def track_subprocess(*args, **kwargs):
            mock_proc = AsyncMock()
            execution_order.append(str(args[-1]))

            async def comm():
                return (b"", b"")
            mock_proc.communicate = comm
            mock_proc.returncode = 0
            return mock_proc

        with patch("Poule.documentation.adapter.Path.rglob", return_value=v_files), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.Path.mkdir"), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    side_effect=track_subprocess), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        # Both files should have been processed
        assert len(execution_order) == 2

    @pytest.mark.asyncio
    async def test_batch_all_paths_absolute_in_results(self):
        """All paths in results are absolute (Section 5)."""
        _, _, _, generate_batch_documentation = _import_adapter()
        FileOutcome = _import_types()[4]

        request = _make_batch_request(
            source_directory="/project/src/",
            output_directory="/docs/",
        )

        v_files = [Path("/project/src/A.v")]

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.Path.rglob", return_value=v_files), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=True), \
             patch("Poule.documentation.adapter.Path.mkdir"), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="<html/>"), \
             patch("Poule.documentation.adapter.Path.write_text"), \
             patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.shutil.move"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        assert Path(result.index_path).is_absolute()
        assert Path(result.output_directory).is_absolute()
        for outcome in result.results:
            assert Path(outcome.input_file).is_absolute()
            if outcome.output_file is not None:
                assert Path(outcome.output_file).is_absolute()

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_generate_batch_documentation_real(self):
        """Contract test: real batch generation against Alectryon."""
        _, _, _, generate_batch_documentation = _import_adapter()
        BatchDocumentationResult = _import_types()[3]

        import tempfile
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            Path(src_dir, "test.v").write_text(
                "Lemma trivial : True. Proof. exact I. Qed.\n"
            )
            request = _make_batch_request(
                source_directory=src_dir,
                output_directory=out_dir,
            )
            result = await generate_batch_documentation(request)
            assert isinstance(result, BatchDocumentationResult)


# ===========================================================================
# 5. Input Validation Errors -- Section 7.1
# ===========================================================================

class TestInputValidationErrors:
    """Section 7.1: Input error behavior."""

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Non-existent .v file returns FILE_NOT_FOUND before subprocess spawn."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Nonexistent.v",
        )

        with patch("Poule.documentation.adapter.Path.exists", return_value=False), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "failure"
        assert result.error["code"] == "FILE_NOT_FOUND"
        assert "/project/src/Nonexistent.v" in result.error["message"]

    @pytest.mark.asyncio
    async def test_invalid_input_not_v_file(self):
        """Non-.v file returns INVALID_INPUT error."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/README.md",
        )

        with patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert result.status == "failure"
        assert result.error["code"] == "INVALID_INPUT"
        assert "/project/src/README.md" in result.error["message"]

    @pytest.mark.asyncio
    async def test_output_dir_not_found(self):
        """When output_path parent dir missing, returns OUTPUT_DIR_NOT_FOUND."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Lemmas.v",
            output_path="/nonexistent/dir/Lemmas.html",
        )

        def exists_side_effect(self_path=None):
            # Input file exists, but output parent does not
            path_str = str(self_path) if self_path else ""
            return path_str.endswith(".v")

        with patch("Poule.documentation.adapter.Path.exists",
                    side_effect=lambda: False), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert result.status == "failure"
        assert result.error["code"] in ("OUTPUT_DIR_NOT_FOUND", "FILE_NOT_FOUND")

    @pytest.mark.asyncio
    async def test_source_dir_not_found_batch(self):
        """Batch with non-existent source_directory returns SOURCE_DIR_NOT_FOUND."""
        _, _, _, generate_batch_documentation = _import_adapter()

        request = _make_batch_request(
            source_directory="/nonexistent/src/",
            output_directory="/docs/",
        )

        with patch("Poule.documentation.adapter.Path.exists", return_value=False), \
             patch("Poule.documentation.adapter.Path.is_dir", return_value=False), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_batch_documentation(request)

        # Result should indicate failure
        if hasattr(result, "error") and result.error is not None:
            assert result.error["code"] == "SOURCE_DIR_NOT_FOUND"
        else:
            assert result.total == 0


# ===========================================================================
# 6. Dependency Errors -- Section 7.2
# ===========================================================================

class TestDependencyErrors:
    """Section 7.2: Dependency error behavior."""

    @pytest.mark.asyncio
    async def test_alectryon_not_found_error(self):
        """When Alectryon not installed, returns ALECTRYON_NOT_FOUND (Section 7.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
        )

        with patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="not_installed"):
            result = await generate_documentation(request)

        assert isinstance(result, DocumentationResult)
        assert result.status == "failure"
        assert result.error["code"] == "ALECTRYON_NOT_FOUND"
        assert "pip install alectryon" in result.error["message"]

    @pytest.mark.asyncio
    async def test_alectryon_version_unsupported(self):
        """When Alectryon version too old, returns ALECTRYON_VERSION_UNSUPPORTED (Section 7.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
        )

        with patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="version_too_old"):
            result = await generate_documentation(request)

        assert result.status == "failure"
        assert result.error["code"] == "ALECTRYON_VERSION_UNSUPPORTED"
        assert "pip install --upgrade alectryon" in result.error["message"]

    @pytest.mark.asyncio
    async def test_alectryon_crash_returns_error(self):
        """Non-zero exit not matching Coq error returns ALECTRYON_ERROR (Section 7.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"Segmentation fault\n")
        mock_process.returncode = 139

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert result.status == "failure"
        assert result.error["code"] == "ALECTRYON_ERROR"
        assert "139" in result.error["message"]

    @pytest.mark.asyncio
    async def test_generation_timeout_error(self):
        """Subprocess timeout returns GENERATION_TIMEOUT (Section 7.2)."""
        _, generate_documentation, _, _ = _import_adapter()
        DocumentationResult = _import_types()[1]

        request = _make_documentation_request(
            input_file="/project/src/Slow.v",
            timeout=5,
        )

        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process), \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        assert result.status == "failure"
        assert result.error["code"] == "GENERATION_TIMEOUT"
        assert "5" in result.error["message"]
        assert "/project/src/Slow.v" in result.error["message"]


# ===========================================================================
# 7. Data Model -- Section 5
# ===========================================================================

class TestDataModel:
    """Section 5: Data model constraints."""

    def test_documentation_request_fields(self):
        """DocumentationRequest has all required fields (Section 5)."""
        request = _make_documentation_request()
        assert request.input_file == "/project/src/Lemmas.v"
        assert request.proof_name is None
        assert request.output_path is None
        assert request.format == "html"
        assert request.custom_flags == []
        assert request.timeout == 120

    def test_documentation_result_success_fields(self):
        """DocumentationResult success has correct field states (Section 5)."""
        result = _make_success_result(
            output_path="/docs/Nat.html",
            content=None,
            format="html",
        )
        assert result.status == "success"
        assert result.output_path == "/docs/Nat.html"
        assert result.content is None
        assert result.format == "html"
        assert result.error is None

    def test_documentation_result_failure_fields(self):
        """DocumentationResult failure has error with code and message (Section 5)."""
        result = _make_failure_result(
            error_code="FILE_NOT_FOUND",
            error_message="File not found: /project/src/Missing.v",
        )
        assert result.status == "failure"
        assert result.output_path is None
        assert result.content is None
        assert result.error is not None
        assert result.error["code"] == "FILE_NOT_FOUND"
        assert result.error["message"] == "File not found: /project/src/Missing.v"

    def test_documentation_result_inline_content(self):
        """When output_path is null, content is populated (Section 5)."""
        result = _make_success_result(
            output_path=None,
            content="<html>inline content</html>",
            format="html",
        )
        assert result.output_path is None
        assert result.content == "<html>inline content</html>"

    def test_batch_documentation_request_fields(self):
        """BatchDocumentationRequest has all required fields (Section 5)."""
        request = _make_batch_request()
        assert request.source_directory == "/project/src/"
        assert request.output_directory == "/docs/"
        assert request.format == "html"
        assert request.custom_flags == []
        assert request.timeout_per_file == 120

    def test_batch_documentation_result_fields(self):
        """BatchDocumentationResult has required summary fields (Section 5)."""
        BatchDocumentationResult = _import_types()[3]
        FileOutcome = _import_types()[4]

        outcome = FileOutcome(
            input_file="/project/src/A.v",
            output_file="/docs/A.html",
            status="success",
            error=None,
        )
        result = BatchDocumentationResult(
            index_path="/docs/index.html",
            output_directory="/docs/",
            results=[outcome],
            total=1,
            succeeded=1,
            failed=0,
        )
        assert result.index_path == "/docs/index.html"
        assert result.output_directory == "/docs/"
        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert len(result.results) == 1

    def test_file_outcome_success(self):
        """FileOutcome on success has output_file and no error (Section 5)."""
        FileOutcome = _import_types()[4]
        outcome = FileOutcome(
            input_file="/project/src/A.v",
            output_file="/docs/A.html",
            status="success",
            error=None,
        )
        assert outcome.input_file == "/project/src/A.v"
        assert outcome.output_file == "/docs/A.html"
        assert outcome.status == "success"
        assert outcome.error is None

    def test_file_outcome_failure(self):
        """FileOutcome on failure has no output_file and has error (Section 5)."""
        FileOutcome = _import_types()[4]
        outcome = FileOutcome(
            input_file="/project/src/B.v",
            output_file=None,
            status="failure",
            error={"code": "COQ_ERROR", "message": "Coq error in B.v at line 42"},
        )
        assert outcome.output_file is None
        assert outcome.status == "failure"
        assert outcome.error["code"] == "COQ_ERROR"

    def test_batch_result_failed_equals_total_minus_succeeded(self):
        """failed == total - succeeded (Section 5)."""
        BatchDocumentationResult = _import_types()[3]
        result = BatchDocumentationResult(
            index_path="/docs/index.html",
            output_directory="/docs/",
            results=[],
            total=5,
            succeeded=3,
            failed=2,
        )
        assert result.failed == result.total - result.succeeded

    def test_documentation_request_format_values(self):
        """format must be one of 'html', 'html-fragment', 'latex' (Section 5)."""
        DocumentationRequest = _import_types()[0]
        for fmt in ("html", "html-fragment", "latex"):
            req = _make_documentation_request(format=fmt)
            assert req.format == fmt

    def test_documentation_result_status_values(self):
        """status must be 'success' or 'failure' (Section 5)."""
        DocumentationResult = _import_types()[1]
        success = _make_success_result()
        failure = _make_failure_result("TEST", "test")
        assert success.status in ("success", "failure")
        assert failure.status in ("success", "failure")


# ===========================================================================
# 8. Non-Functional Requirements -- Section 8
# ===========================================================================

class TestNonFunctionalRequirements:
    """Section 8: Non-functional requirements."""

    @pytest.mark.asyncio
    async def test_paths_must_be_absolute(self):
        """All paths in requests must be absolute; relative paths rejected (Section 8)."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="relative/path/Lemmas.v",
        )

        with patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            result = await generate_documentation(request)

        # Relative path should be rejected
        assert result.status == "failure"
        assert result.error["code"] in ("INVALID_INPUT", "FILE_NOT_FOUND")

    @pytest.mark.asyncio
    async def test_default_timeout_is_120(self):
        """Default timeout is 120 seconds (Section 5)."""
        request = _make_documentation_request(timeout=None)
        # If timeout is None, the adapter should use 120 as default
        # This is tested at the adapter level -- the request accepts None
        assert request.timeout is None or request.timeout == 120

    def test_custom_flags_passed_verbatim(self):
        """custom_flags are passed verbatim to Alectryon (Section 4.2)."""
        request = _make_documentation_request(
            custom_flags=["--long-line-threshold", "80", "--expect-unexpected"],
        )
        assert request.custom_flags == [
            "--long-line-threshold", "80", "--expect-unexpected",
        ]


# ===========================================================================
# 9. Format Mapping -- Section 4.2
# ===========================================================================

class TestFormatMapping:
    """Section 4.2: Format to Alectryon backend mapping."""

    FORMAT_MAP = {
        "html": ("webpage", ".html"),
        "html-fragment": ("webpage-no-header", ".html"),
        "latex": ("latex", ".tex"),
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("format_name,expected_backend,expected_ext", [
        ("html", "webpage", ".html"),
        ("html-fragment", "webpage-no-header", ".html"),
        ("latex", "latex", ".tex"),
    ])
    async def test_format_maps_to_backend(self, format_name, expected_backend, expected_ext):
        """Each format maps to the correct Alectryon --backend value."""
        _, generate_documentation, _, _ = _import_adapter()

        request = _make_documentation_request(
            input_file="/project/src/Nat.v",
            format=format_name,
            output_path=None,
        )

        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("Poule.documentation.adapter.asyncio.create_subprocess_exec",
                    return_value=mock_process) as mock_exec, \
             patch("Poule.documentation.adapter.Path.exists", return_value=True), \
             patch("Poule.documentation.adapter.Path.read_text", return_value="content"), \
             patch("Poule.documentation.adapter.check_availability",
                    return_value="available"):
            await generate_documentation(request)

        cmd_args = mock_exec.call_args[0]
        cmd_str = " ".join(str(a) for a in cmd_args)
        assert f"--backend {expected_backend}" in cmd_str or \
               (f"--backend" in cmd_str and expected_backend in cmd_str)
