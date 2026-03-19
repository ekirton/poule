"""TDD tests for the standalone CLI search commands.

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/cli/ modules exist.

Spec: specification/cli.md
Architecture: doc/architecture/cli.md

Import paths under test:
  poule.cli.commands
  poule.cli.formatting
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from Poule.models.responses import LemmaDetail, Module, SearchResult


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


def _sr(
    name: str = "Coq.Arith.PeanoNat.Nat.add_comm",
    statement: str = "forall n m : nat, n + m = m + n",
    type_: str = "forall n m : nat, n + m = m + n",
    module: str = "Coq.Arith.PeanoNat",
    kind: str = "lemma",
    score: float = 0.95,
) -> SearchResult:
    return SearchResult(
        name=name,
        statement=statement,
        type=type_,
        module=module,
        kind=kind,
        score=score,
    )


def _ld(
    name: str = "Coq.Arith.PeanoNat.Nat.add_comm",
    statement: str = "forall n m : nat, n + m = m + n",
    type_: str = "forall n m : nat, n + m = m + n",
    module: str = "Coq.Arith.PeanoNat",
    kind: str = "lemma",
    score: float = 1.0,
    dependencies: list[str] | None = None,
    dependents: list[str] | None = None,
    symbols: list[str] | None = None,
    node_count: int = 5,
) -> LemmaDetail:
    return LemmaDetail(
        name=name,
        statement=statement,
        type=type_,
        module=module,
        kind=kind,
        score=score,
        dependencies=dependencies or [],
        dependents=dependents or [],
        proof_sketch="",
        symbols=symbols or [],
        node_count=node_count,
    )


def _mod(name: str = "Coq.Arith.PeanoNat", decl_count: int = 42) -> Module:
    return Module(name=name, decl_count=decl_count)


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------


def _import_cli():
    from Poule.cli.commands import cli

    return cli


def _import_formatting():
    from Poule.cli.formatting import (
        format_lemma_detail,
        format_modules,
        format_search_results,
    )

    return format_search_results, format_lemma_detail, format_modules


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_db(tmp_path):
    """Create a fake db file so path existence checks pass."""
    db = tmp_path / "index.db"
    db.write_text("")
    return str(db)


def _patch_context_and_search(search_fn_name, return_value):
    """Return a dict of patches for create_context and a search function.

    Usage:
        with _apply_patches(patches):
            result = runner.invoke(cli, [...])
    """
    ctx_mock = MagicMock()
    patches = {
        "context": patch(
            "Poule.cli.commands.create_context", return_value=ctx_mock
        ),
        "search": patch(
            f"Poule.cli.commands.{search_fn_name}",
            return_value=return_value,
        ),
    }
    return patches, ctx_mock


# ===========================================================================
# 1. Formatting — format_search_results
# ===========================================================================


class TestFormatSearchResults:
    """format_search_results: human-readable and JSON output."""

    def test_human_readable_single_result(self):
        format_search_results, _, _ = _import_formatting()
        results = [_sr()]
        output = format_search_results(results, json_mode=False)
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in output
        assert "lemma" in output
        assert "0.9500" in output
        assert "forall n m : nat, n + m = m + n" in output
        assert "module: Coq.Arith.PeanoNat" in output

    def test_human_readable_multiple_results_separated_by_blank_lines(self):
        format_search_results, _, _ = _import_formatting()
        results = [_sr(name="A", score=0.9), _sr(name="B", score=0.8)]
        output = format_search_results(results, json_mode=False)
        assert "A" in output
        assert "B" in output
        # Results separated by blank lines
        assert "\n\n" in output

    def test_human_readable_empty_results(self):
        format_search_results, _, _ = _import_formatting()
        output = format_search_results([], json_mode=False)
        assert output == ""

    def test_json_mode_single_result(self):
        format_search_results, _, _ = _import_formatting()
        results = [_sr()]
        output = format_search_results(results, json_mode=True)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"
        assert parsed[0]["score"] == 0.95

    def test_json_mode_empty_results(self):
        format_search_results, _, _ = _import_formatting()
        output = format_search_results([], json_mode=True)
        assert json.loads(output) == []

    def test_json_mode_has_all_search_result_fields(self):
        format_search_results, _, _ = _import_formatting()
        results = [_sr()]
        output = format_search_results(results, json_mode=True)
        parsed = json.loads(output)
        required_fields = {"name", "statement", "type", "module", "kind", "score"}
        assert required_fields.issubset(set(parsed[0].keys()))


# ===========================================================================
# 2. Formatting — format_lemma_detail
# ===========================================================================


class TestFormatLemmaDetail:
    """format_lemma_detail: human-readable and JSON output."""

    def test_human_readable(self):
        _, format_lemma_detail, _ = _import_formatting()
        detail = _ld(dependencies=["Nat.add"], dependents=["Thm.foo"], symbols=["Nat.add"], node_count=15)
        output = format_lemma_detail(detail, json_mode=False)
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in output
        assert "(lemma)" in output
        assert "forall n m : nat, n + m = m + n" in output
        assert "module:" in output
        assert "dependencies:" in output
        assert "dependents:" in output
        assert "symbols:" in output
        assert "node_count:" in output

    def test_json_mode(self):
        _, format_lemma_detail, _ = _import_formatting()
        detail = _ld()
        output = format_lemma_detail(detail, json_mode=True)
        parsed = json.loads(output)
        assert parsed["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"
        required_fields = {
            "name", "statement", "type", "module", "kind", "score",
            "dependencies", "dependents", "proof_sketch", "symbols", "node_count",
        }
        assert required_fields.issubset(set(parsed.keys()))


# ===========================================================================
# 3. Formatting — format_modules
# ===========================================================================


class TestFormatModules:
    """format_modules: human-readable and JSON output."""

    def test_human_readable(self):
        _, _, format_modules = _import_formatting()
        modules = [_mod(name="Coq.Arith.PeanoNat", decl_count=42)]
        output = format_modules(modules, json_mode=False)
        assert "Coq.Arith.PeanoNat" in output
        assert "42" in output
        assert "declarations" in output

    def test_human_readable_empty(self):
        _, _, format_modules = _import_formatting()
        output = format_modules([], json_mode=False)
        assert output == ""

    def test_json_mode(self):
        _, _, format_modules = _import_formatting()
        modules = [_mod()]
        output = format_modules(modules, json_mode=True)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat"
        assert parsed[0]["decl_count"] == 42

    def test_json_mode_empty(self):
        _, _, format_modules = _import_formatting()
        output = format_modules([], json_mode=True)
        assert json.loads(output) == []


# ===========================================================================
# 4. search-by-name subcommand
# ===========================================================================


class TestSearchByNameCommand:
    """CLI search-by-name subcommand."""

    def test_happy_path_human_readable(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx, \
             patch("Poule.cli.commands.search_by_name", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "Nat.add_comm"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result.output

    def test_happy_path_json(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_name", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "--json", "Nat.add_comm"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"

    def test_custom_limit(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_name", return_value=[]) as mock_search:
            runner.invoke(cli, ["search-by-name", "--db", tmp_db, "--limit", "10", "foo"])
        _, kwargs = mock_search.call_args
        assert kwargs.get("limit") == 10 or mock_search.call_args[0][2] == 10

    def test_limit_clamped_high(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_name", return_value=[]) as mock_search:
            runner.invoke(cli, ["search-by-name", "--db", tmp_db, "--limit", "999", "foo"])
        # limit argument passed to pipeline should be <= 200
        args = mock_search.call_args
        limit_val = args[0][2] if len(args[0]) > 2 else args[1].get("limit", 999)
        assert limit_val <= 200

    def test_empty_results_exit_0(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_name", return_value=[]):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "nonexistent"])
        assert result.exit_code == 0

    def test_empty_results_json_outputs_empty_array(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_name", return_value=[]):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "--json", "nonexistent"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_missing_pattern_exits_with_usage_error(self, runner, tmp_db):
        cli = _import_cli()
        result = runner.invoke(cli, ["search-by-name", "--db", tmp_db])
        assert result.exit_code == 2


# ===========================================================================
# 5. search-by-type subcommand
# ===========================================================================


class TestSearchByTypeCommand:
    """CLI search-by-type subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_type", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-type", "--db", tmp_db, "nat -> nat -> nat"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result.output

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_type", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-type", "--db", tmp_db, "--json", "nat -> nat"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)

    def test_parse_error_exits_1(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.pipeline.parser import ParseError
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_type", side_effect=ParseError("bad syntax")):
            result = runner.invoke(cli, ["search-by-type", "--db", tmp_db, "bad(((syntax"])
        assert result.exit_code == 1
        assert "parse" in result.output.lower() or "parse" in (result.output + getattr(result, 'stderr', '')).lower()


# ===========================================================================
# 6. search-by-structure subcommand
# ===========================================================================


class TestSearchByStructureCommand:
    """CLI search-by-structure subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_structure", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-structure", "--db", tmp_db, "forall n, n = n"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result.output

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_structure", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-structure", "--db", tmp_db, "--json", "forall n, n = n"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)

    def test_parse_error_exits_1(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.pipeline.parser import ParseError
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_structure", side_effect=ParseError("bad")):
            result = runner.invoke(cli, ["search-by-structure", "--db", tmp_db, "bad((("])
        assert result.exit_code == 1


# ===========================================================================
# 7. search-by-symbols subcommand
# ===========================================================================


class TestSearchBySymbolsCommand:
    """CLI search-by-symbols subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_symbols", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-symbols", "--db", tmp_db, "Nat.add", "Nat.mul"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result.output

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context"), \
             patch("Poule.cli.commands.search_by_symbols", return_value=[_sr()]):
            result = runner.invoke(cli, ["search-by-symbols", "--db", tmp_db, "--json", "Nat.add"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)

    def test_missing_symbols_exits_usage_error(self, runner, tmp_db):
        cli = _import_cli()
        result = runner.invoke(cli, ["search-by-symbols", "--db", tmp_db])
        assert result.exit_code == 2


# ===========================================================================
# 8. get-lemma subcommand
# ===========================================================================


class TestGetLemmaCommand:
    """CLI get-lemma subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = {
                "id": 1,
                "name": "Coq.Arith.PeanoNat.Nat.add_comm",
                "statement": "forall n m : nat, n + m = m + n",
                "type_expr": "forall n m : nat, n + m = m + n",
                "module": "Coq.Arith.PeanoNat",
                "kind": "lemma",
                "node_count": 15,
                "symbol_set": '["Nat.add"]',
            }
            mock_ctx.reader.get_dependencies.return_value = []
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["get-lemma", "--db", tmp_db, "Coq.Arith.PeanoNat.Nat.add_comm"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in result.output

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = {
                "id": 1,
                "name": "Coq.Arith.PeanoNat.Nat.add_comm",
                "statement": "forall n m : nat, n + m = m + n",
                "type_expr": "forall n m : nat, n + m = m + n",
                "module": "Coq.Arith.PeanoNat",
                "kind": "lemma",
                "node_count": 15,
                "symbol_set": '["Nat.add"]',
            }
            mock_ctx.reader.get_dependencies.return_value = []
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["get-lemma", "--db", tmp_db, "--json", "Coq.Arith.PeanoNat.Nat.add_comm"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["name"] == "Coq.Arith.PeanoNat.Nat.add_comm"
        required_fields = {
            "name", "statement", "type", "module", "kind", "score",
            "dependencies", "dependents", "proof_sketch", "symbols", "node_count",
        }
        assert required_fields.issubset(set(parsed.keys()))

    def test_not_found_exits_1(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = None
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["get-lemma", "--db", tmp_db, "nonexistent.decl"])
        assert result.exit_code == 1

    def test_missing_name_exits_usage_error(self, runner, tmp_db):
        cli = _import_cli()
        result = runner.invoke(cli, ["get-lemma", "--db", tmp_db])
        assert result.exit_code == 2


# ===========================================================================
# 9. find-related subcommand
# ===========================================================================


class TestFindRelatedCommand:
    """CLI find-related subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = {
                "id": 1, "name": "A", "module": "Coq.Init",
                "statement": "stmt", "type_expr": "ty",
                "kind": "lemma", "node_count": 5, "symbol_set": "[]",
            }
            mock_ctx.reader.get_dependencies.return_value = [
                {"target_name": "B", "src": 1, "dst": 2, "relation": "uses"}
            ]
            mock_ctx.reader.get_declarations_by_ids.return_value = [{
                "id": 2, "name": "B", "module": "Coq.Init",
                "statement": "stmt_b", "type_expr": "ty_b",
                "kind": "lemma", "node_count": 3, "symbol_set": "[]",
            }]
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["find-related", "--db", tmp_db, "--relation", "uses", "A"])
        assert result.exit_code == 0

    def test_invalid_relation_exits_usage_error(self, runner, tmp_db):
        cli = _import_cli()
        result = runner.invoke(cli, ["find-related", "--db", tmp_db, "--relation", "invalid", "A"])
        assert result.exit_code == 2

    @pytest.mark.parametrize("relation", ["uses", "used_by", "same_module", "same_typeclass"])
    def test_valid_relations_accepted(self, runner, tmp_db, relation):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = {
                "id": 1, "name": "A", "module": "Coq.Init",
                "statement": "s", "type_expr": "t",
                "kind": "lemma", "node_count": 1, "symbol_set": "[]",
            }
            mock_ctx.reader.get_dependencies.return_value = []
            mock_ctx.reader.get_declarations_by_module.return_value = []
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["find-related", "--db", tmp_db, "--relation", relation, "A"])
        assert result.exit_code == 0

    def test_not_found_exits_1(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = None
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["find-related", "--db", tmp_db, "--relation", "uses", "nonexistent"])
        assert result.exit_code == 1

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.get_declaration.return_value = {
                "id": 1, "name": "A", "module": "M",
                "statement": "s", "type_expr": "t",
                "kind": "lemma", "node_count": 1, "symbol_set": "[]",
            }
            mock_ctx.reader.get_dependencies.return_value = []
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["find-related", "--db", tmp_db, "--relation", "uses", "--json", "A"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)


# ===========================================================================
# 10. list-modules subcommand
# ===========================================================================


class TestListModulesCommand:
    """CLI list-modules subcommand."""

    def test_happy_path(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.list_modules.return_value = [
                {"module": "Coq.Arith.PeanoNat", "count": 42},
            ]
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["list-modules", "--db", tmp_db, "Coq.Arith"])
        assert result.exit_code == 0
        assert "Coq.Arith.PeanoNat" in result.output
        assert "42" in result.output

    def test_no_prefix_lists_all(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.list_modules.return_value = [
                {"module": "Coq.Arith", "count": 10},
                {"module": "Coq.Init", "count": 20},
            ]
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["list-modules", "--db", tmp_db])
        assert result.exit_code == 0
        assert "Coq.Arith" in result.output
        assert "Coq.Init" in result.output

    def test_json_output(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.list_modules.return_value = [
                {"module": "Coq.Arith.PeanoNat", "count": 42},
            ]
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["list-modules", "--db", tmp_db, "--json", "Coq.Arith"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "Coq.Arith.PeanoNat"
        assert parsed[0]["decl_count"] == 42

    def test_empty_result(self, runner, tmp_db):
        cli = _import_cli()
        with patch("Poule.cli.commands.create_context") as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx.reader.list_modules.return_value = []
            mock_ctx_fn.return_value = mock_ctx
            result = runner.invoke(cli, ["list-modules", "--db", tmp_db, "nonexistent"])
        assert result.exit_code == 0


# ===========================================================================
# 11. Index missing → all subcommands return error
# ===========================================================================


class TestIndexMissing:
    """When the index database file is missing, all commands exit 1."""

    def test_search_by_name_missing_db(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.storage.errors import IndexNotFoundError
        with patch(
            "Poule.cli.commands.create_context",
            side_effect=IndexNotFoundError("Database not found: /nonexistent/path.db"),
        ):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "foo"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_get_lemma_missing_db(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.storage.errors import IndexNotFoundError
        with patch(
            "Poule.cli.commands.create_context",
            side_effect=IndexNotFoundError("Database not found"),
        ):
            result = runner.invoke(cli, ["get-lemma", "--db", tmp_db, "foo"])
        assert result.exit_code == 1

    def test_list_modules_missing_db(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.storage.errors import IndexNotFoundError
        with patch(
            "Poule.cli.commands.create_context",
            side_effect=IndexNotFoundError("Database not found"),
        ):
            result = runner.invoke(cli, ["list-modules", "--db", tmp_db])
        assert result.exit_code == 1


# ===========================================================================
# 12. Schema version mismatch
# ===========================================================================


class TestSchemaVersionMismatch:
    """When schema version mismatches, commands exit 1."""

    def test_version_mismatch_exits_1(self, runner, tmp_db):
        cli = _import_cli()
        from Poule.storage.errors import IndexVersionError
        with patch(
            "Poule.cli.commands.create_context",
            side_effect=IndexVersionError(found="0", expected="1"),
        ):
            result = runner.invoke(cli, ["search-by-name", "--db", tmp_db, "foo"])
        assert result.exit_code == 1
        assert "version" in result.output.lower() or "schema" in result.output.lower()


# ===========================================================================
# 13. Shared --db option required
# ===========================================================================


class TestDbOptionDefault:
    """--db defaults to /data/index.db when not specified."""

    @pytest.mark.parametrize("subcmd", [
        ["search-by-name", "foo"],
        ["search-by-type", "nat"],
        ["search-by-structure", "forall n, n = n"],
        ["search-by-symbols", "Nat.add"],
        ["get-lemma", "Nat.add_comm"],
        ["find-related", "--relation", "uses", "Nat.add_comm"],
        ["list-modules"],
    ])
    def test_missing_db_does_not_exit_usage_error(self, runner, subcmd):
        """Without --db, commands use the default path — no usage error (exit 2)."""
        cli = _import_cli()
        result = runner.invoke(cli, subcmd)
        assert result.exit_code != 2


# ===========================================================================
# 14. extract subcommand (§4.7)
# ===========================================================================


class TestExtractSubcommand:
    """extract: batch proof trace extraction from Coq project directories."""

    def test_successful_extraction_exits_0(self, runner, tmp_path):
        """Given valid project dirs, extract succeeds with exit code 0."""
        cli = _import_cli()
        project_dir = tmp_path / "stdlib"
        project_dir.mkdir()
        output_path = tmp_path / "output.jsonl"
        # Contract test: real ExtractionCampaignOrchestrator tested in test_extraction_campaign.py
        with patch(
            "Poule.cli.commands.run_campaign",
        ) as mock_run:
            from Poule.extraction.types import ExtractionSummary
            mock_run.return_value = ExtractionSummary(
                schema_version=1, record_type="extraction_summary",
                total_theorems_found=10, total_extracted=10,
                total_failed=0, total_skipped=0, per_project=[],
            )
            result = runner.invoke(cli, [
                "extract", str(project_dir), "--output", str(output_path),
            ])
        assert result.exit_code == 0

    def test_missing_project_dir_exits_1(self, runner, tmp_path):
        """Given a nonexistent project directory, exit code is 1."""
        cli = _import_cli()
        result = runner.invoke(cli, [
            "extract", "/nonexistent/path", "--output", str(tmp_path / "out.jsonl"),
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "not found" in (result.stderr or "").lower()

    def test_output_option_required(self, runner, tmp_path):
        """--output is required; omitting it exits with code 2."""
        cli = _import_cli()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        result = runner.invoke(cli, ["extract", str(project_dir)])
        assert result.exit_code == 2

    def test_incremental_and_resume_mutually_exclusive(self, runner, tmp_path):
        """--incremental and --resume cannot be used together."""
        cli = _import_cli()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        result = runner.invoke(cli, [
            "extract", str(project_dir),
            "--output", str(tmp_path / "out.jsonl"),
            "--incremental", "--resume",
        ])
        assert result.exit_code == 2

    def test_all_failures_exits_1(self, runner, tmp_path):
        """When all proofs fail, exit code is 1."""
        cli = _import_cli()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # Contract test: real orchestrator tested in test_extraction_campaign.py
        with patch(
            "Poule.cli.commands.run_campaign",
        ) as mock_run:
            from Poule.extraction.types import ExtractionSummary
            mock_run.return_value = ExtractionSummary(
                schema_version=1, record_type="extraction_summary",
                total_theorems_found=10, total_extracted=0,
                total_failed=10, total_skipped=0, per_project=[],
            )
            result = runner.invoke(cli, [
                "extract", str(project_dir), "--output", str(tmp_path / "out.jsonl"),
            ])
        assert result.exit_code == 1

    def test_partial_failures_exits_0(self, runner, tmp_path):
        """When some proofs fail but some succeed, exit code is 0 (partial success)."""
        cli = _import_cli()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # Contract test: real orchestrator tested in test_extraction_campaign.py
        with patch(
            "Poule.cli.commands.run_campaign",
        ) as mock_run:
            from Poule.extraction.types import ExtractionSummary
            mock_run.return_value = ExtractionSummary(
                schema_version=1, record_type="extraction_summary",
                total_theorems_found=10, total_extracted=8,
                total_failed=2, total_skipped=0, per_project=[],
            )
            result = runner.invoke(cli, [
                "extract", str(project_dir), "--output", str(tmp_path / "out.jsonl"),
            ])
        assert result.exit_code == 0

    def test_multiple_project_dirs(self, runner, tmp_path):
        """extract accepts multiple project directories."""
        cli = _import_cli()
        dir1 = tmp_path / "stdlib"
        dir2 = tmp_path / "mathcomp"
        dir1.mkdir()
        dir2.mkdir()
        # Contract test: real orchestrator tested in test_extraction_campaign.py
        with patch(
            "Poule.cli.commands.run_campaign",
        ) as mock_run:
            from Poule.extraction.types import ExtractionSummary
            mock_run.return_value = ExtractionSummary(
                schema_version=1, record_type="extraction_summary",
                total_theorems_found=0, total_extracted=0,
                total_failed=0, total_skipped=0, per_project=[],
            )
            result = runner.invoke(cli, [
                "extract", str(dir1), str(dir2),
                "--output", str(tmp_path / "out.jsonl"),
            ])
        assert result.exit_code == 0
        # Verify both dirs were passed to run_campaign
        call_args = mock_run.call_args
        assert str(dir1) in str(call_args) and str(dir2) in str(call_args)

    def test_timeout_option(self, runner, tmp_path):
        """--timeout sets per-proof timeout."""
        cli = _import_cli()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # Contract test: real orchestrator tested in test_extraction_campaign.py
        with patch(
            "Poule.cli.commands.run_campaign",
        ) as mock_run:
            from Poule.extraction.types import ExtractionSummary
            mock_run.return_value = ExtractionSummary(
                schema_version=1, record_type="extraction_summary",
                total_theorems_found=0, total_extracted=0,
                total_failed=0, total_skipped=0, per_project=[],
            )
            result = runner.invoke(cli, [
                "extract", str(project_dir),
                "--output", str(tmp_path / "out.jsonl"),
                "--timeout", "120",
            ])
        assert result.exit_code == 0


# ===========================================================================
# 15. extract-deps subcommand (§4.8)
# ===========================================================================


class TestExtractDepsSubcommand:
    """extract-deps: post-hoc dependency graph extraction."""

    def test_successful_extraction_exits_0(self, runner, tmp_path):
        cli = _import_cli()
        input_file = tmp_path / "extraction.jsonl"
        input_file.write_text("{}\n")
        output_file = tmp_path / "deps.jsonl"
        # Contract test: real extract_dependency_graph tested in test_extraction_dependency_graph.py
        with patch(
            "Poule.cli.commands.extract_dependency_graph",
        ):
            result = runner.invoke(cli, [
                "extract-deps", str(input_file), "--output", str(output_file),
            ])
        assert result.exit_code == 0

    def test_invalid_input_exits_1(self, runner, tmp_path):
        cli = _import_cli()
        result = runner.invoke(cli, [
            "extract-deps", "/nonexistent/file.jsonl",
            "--output", str(tmp_path / "deps.jsonl"),
        ])
        assert result.exit_code == 1


# ===========================================================================
# 16. quality-report subcommand (§4.9)
# ===========================================================================


class TestQualityReportSubcommand:
    """quality-report: dataset quality report generation."""

    def test_human_readable_output_exits_0(self, runner, tmp_path):
        cli = _import_cli()
        input_file = tmp_path / "extraction.jsonl"
        input_file.write_text("{}\n")
        # Contract test: real generate_quality_report tested in test_extraction_reporting.py
        with patch(
            "Poule.cli.commands.generate_quality_report",
        ) as mock_report:
            from Poule.extraction.types import (
                DistributionStats, QualityReport, TacticFrequency,
            )
            mock_report.return_value = QualityReport(
                premise_coverage=0.87,
                proof_length_distribution=DistributionStats(
                    min=1, max=100, mean=12.0, median=8.0,
                    p25=4.0, p75=16.0, p95=45.0,
                ),
                tactic_vocabulary=[TacticFrequency(tactic="apply", count=100)],
                per_project=[],
            )
            result = runner.invoke(cli, ["quality-report", str(input_file)])
        assert result.exit_code == 0
        assert "premise coverage" in result.output.lower() or "87" in result.output

    def test_json_output(self, runner, tmp_path):
        cli = _import_cli()
        input_file = tmp_path / "extraction.jsonl"
        input_file.write_text("{}\n")
        # Contract test: real generate_quality_report tested in test_extraction_reporting.py
        with patch(
            "Poule.cli.commands.generate_quality_report",
        ) as mock_report:
            from Poule.extraction.types import (
                DistributionStats, QualityReport, TacticFrequency,
            )
            mock_report.return_value = QualityReport(
                premise_coverage=0.87,
                proof_length_distribution=DistributionStats(
                    min=1, max=100, mean=12.0, median=8.0,
                    p25=4.0, p75=16.0, p95=45.0,
                ),
                tactic_vocabulary=[TacticFrequency(tactic="apply", count=100)],
                per_project=[],
            )
            result = runner.invoke(cli, ["quality-report", str(input_file), "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "premise_coverage" in parsed

    def test_invalid_input_exits_1(self, runner, tmp_path):
        cli = _import_cli()
        result = runner.invoke(cli, [
            "quality-report", "/nonexistent/file.jsonl",
        ])
        assert result.exit_code == 1

    def test_output_to_file(self, runner, tmp_path):
        cli = _import_cli()
        input_file = tmp_path / "extraction.jsonl"
        input_file.write_text("{}\n")
        output_file = tmp_path / "report.json"
        # Contract test: real generate_quality_report tested in test_extraction_reporting.py
        with patch(
            "Poule.cli.commands.generate_quality_report",
        ) as mock_report:
            from Poule.extraction.types import (
                DistributionStats, QualityReport, TacticFrequency,
            )
            mock_report.return_value = QualityReport(
                premise_coverage=0.87,
                proof_length_distribution=DistributionStats(
                    min=1, max=100, mean=12.0, median=8.0,
                    p25=4.0, p75=16.0, p95=45.0,
                ),
                tactic_vocabulary=[TacticFrequency(tactic="apply", count=100)],
                per_project=[],
            )
            result = runner.invoke(cli, [
                "quality-report", str(input_file),
                "--output", str(output_file),
            ])
        assert result.exit_code == 0
