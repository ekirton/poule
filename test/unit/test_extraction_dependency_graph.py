"""TDD tests for extraction dependency graph (specification/extraction-dependency-graph.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/extraction/.

Covers: dependency derivation, hypothesis exclusion, dependency classification,
deduplication and ordering, DependencyEntry serialization, integration modes,
index import, and error cases.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_premise(name: str, kind: str) -> dict:
    """Build a Premise dict matching extraction output format."""
    return {"name": name, "kind": kind}


def _make_extraction_step(step_index: int, tactic: str | None, premises: list[dict]) -> dict:
    """Build an ExtractionStep dict with premise annotations."""
    return {
        "step_index": step_index,
        "tactic": tactic,
        "goals": [],
        "focused_goal_index": None,
        "premises": premises,
        "diff": None,
    }


def _make_extraction_record(
    theorem_name: str = "Coq.Arith.PeanoNat.Nat.add_comm",
    source_file: str = "theories/Arith/PeanoNat.v",
    project_id: str = "coq-stdlib",
    steps: list[dict] | None = None,
) -> dict:
    """Build an ExtractionRecord dict with per-step premise annotations.

    If *steps* is None, creates a single initial step with no premises.
    """
    if steps is None:
        steps = [_make_extraction_step(0, None, [])]
    total_steps = len(steps) - 1  # step 0 is initial state
    return {
        "schema_version": 1,
        "record_type": "proof_trace",
        "theorem_name": theorem_name,
        "source_file": source_file,
        "project_id": project_id,
        "total_steps": total_steps,
        "steps": steps,
    }


def _make_extraction_error(
    theorem_name: str = "Coq.Init.Logic.broken",
    source_file: str = "theories/Init/Logic.v",
    project_id: str = "coq-stdlib",
    error_kind: str = "tactic_failure",
    error_message: str = "Tactic failed",
) -> dict:
    """Build an ExtractionError dict."""
    return {
        "schema_version": 1,
        "record_type": "extraction_error",
        "theorem_name": theorem_name,
        "source_file": source_file,
        "project_id": project_id,
        "error_kind": error_kind,
        "error_message": error_message,
    }


def _spec_example_record() -> dict:
    """Build the specification §4.1 example: premises [A(lemma), H(hypothesis), B(definition), A(lemma)].

    Expected depends_on: [A(lemma), B(definition)] — H excluded (hypothesis), second A deduplicated.
    """
    steps = [
        _make_extraction_step(0, None, []),
        _make_extraction_step(1, "apply A.", [
            _make_premise("Coq.Arith.A", "lemma"),
            _make_premise("H", "hypothesis"),
        ]),
        _make_extraction_step(2, "unfold B.", [
            _make_premise("Coq.Arith.B", "definition"),
            _make_premise("Coq.Arith.A", "lemma"),
        ]),
    ]
    return _make_extraction_record(
        theorem_name="Coq.Arith.PeanoNat.Nat.add_comm",
        steps=steps,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. Dependency Derivation (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractDependenciesBasic:
    """extract_dependencies returns a DependencyEntry from an ExtractionRecord."""

    def test_returns_dependency_entry_with_theorem_name(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _make_extraction_record(theorem_name="Coq.Init.Logic.eq_refl")
        entry = extract_dependencies(record)
        assert entry.theorem_name == "Coq.Init.Logic.eq_refl"

    def test_returns_dependency_entry_with_source_file(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _make_extraction_record(source_file="theories/Init/Logic.v")
        entry = extract_dependencies(record)
        assert entry.source_file == "theories/Init/Logic.v"

    def test_returns_dependency_entry_with_project_id(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _make_extraction_record(project_id="coq-stdlib")
        entry = extract_dependencies(record)
        assert entry.project_id == "coq-stdlib"

    def test_depends_on_is_union_of_all_premises_across_steps(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "apply X.", [
                _make_premise("Coq.X", "lemma"),
            ]),
            _make_extraction_step(2, "apply Y.", [
                _make_premise("Coq.Y", "definition"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        names = [ref.name for ref in entry.depends_on]
        assert "Coq.X" in names
        assert "Coq.Y" in names

    def test_spec_example_excludes_hypothesis_and_deduplicates(self):
        """Spec §4.1 example: [A(lemma), H(hyp), B(def), A(lemma)] → [A(lemma), B(definition)]."""
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _spec_example_record()
        entry = extract_dependencies(record)
        assert len(entry.depends_on) == 2
        assert entry.depends_on[0].name == "Coq.Arith.A"
        assert entry.depends_on[0].kind == "lemma"
        assert entry.depends_on[1].name == "Coq.Arith.B"
        assert entry.depends_on[1].kind == "definition"


class TestExtractDependenciesAllHypotheses:
    """When all premises are hypotheses, depends_on is empty (§4.1)."""

    def test_all_hypotheses_yields_empty_depends_on(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "intro H1.", [
                _make_premise("H1", "hypothesis"),
            ]),
            _make_extraction_step(2, "exact H2.", [
                _make_premise("H2", "hypothesis"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert entry.depends_on == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Hypothesis Exclusion (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisExclusion:
    """Premises with kind='hypothesis' are excluded from depends_on."""

    def test_hypothesis_premises_excluded(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "rewrite H.", [
                _make_premise("H", "hypothesis"),
                _make_premise("Coq.Init.Logic.eq_sym", "lemma"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        names = [ref.name for ref in entry.depends_on]
        assert "H" not in names
        assert "Coq.Init.Logic.eq_sym" in names

    @pytest.mark.parametrize("allowed_kind", ["lemma", "definition", "constructor"])
    def test_allowed_kinds_appear_in_depends_on(self, allowed_kind):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "tac.", [
                _make_premise("Coq.Some.Entity", allowed_kind),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert len(entry.depends_on) == 1
        assert entry.depends_on[0].name == "Coq.Some.Entity"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Dependency Classification (§4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestDependencyClassification:
    """DependencyRef kind reflects the entity type in the Coq environment."""

    def test_premise_lemma_maps_to_lemma_by_default(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "apply L.", [
                _make_premise("Coq.Some.Lemma", "lemma"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert entry.depends_on[0].kind == "lemma"

    def test_premise_definition_maps_to_definition(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "unfold D.", [
                _make_premise("Coq.Some.Def", "definition"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert entry.depends_on[0].kind == "definition"

    def test_premise_constructor_maps_to_constructor(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "exact S.", [
                _make_premise("Coq.Init.Datatypes.S", "constructor"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert entry.depends_on[0].kind == "constructor"

    def test_dependency_ref_kind_in_valid_set(self):
        """Every DependencyRef kind must be from the valid set (§4.3)."""
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "apply X.", [
                _make_premise("Coq.A", "lemma"),
                _make_premise("Coq.B", "definition"),
                _make_premise("Coq.C", "constructor"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        valid_kinds = {"theorem", "lemma", "definition", "axiom", "constructor", "inductive"}
        for ref in entry.depends_on:
            assert ref.kind in valid_kinds, f"kind {ref.kind!r} not in valid set"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Deduplication and Ordering (§4.4)
# ═══════════════════════════════════════════════════════════════════════════


class TestDeduplicationAndOrdering:
    """Deduplicate by FQN, keep first occurrence, first-appearance order."""

    def test_duplicate_premises_deduplicated_by_fqn(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "apply A.", [
                _make_premise("Coq.A", "lemma"),
            ]),
            _make_extraction_step(2, "apply A.", [
                _make_premise("Coq.A", "lemma"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert len(entry.depends_on) == 1
        assert entry.depends_on[0].name == "Coq.A"

    def test_first_appearance_order_across_steps(self):
        """§4.4 example: A at step 1 and 3, B at step 2 → order [A, B]."""
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "apply A.", [
                _make_premise("Coq.A", "lemma"),
            ]),
            _make_extraction_step(2, "unfold B.", [
                _make_premise("Coq.B", "definition"),
            ]),
            _make_extraction_step(3, "apply A.", [
                _make_premise("Coq.A", "lemma"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert [ref.name for ref in entry.depends_on] == ["Coq.A", "Coq.B"]

    def test_within_step_ordering_preserved(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "tac.", [
                _make_premise("Coq.Z", "lemma"),
                _make_premise("Coq.M", "definition"),
                _make_premise("Coq.A", "constructor"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert [ref.name for ref in entry.depends_on] == ["Coq.Z", "Coq.M", "Coq.A"]

    def test_ordering_is_deterministic(self):
        """Identical inputs produce identical ordering (§4.4)."""
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "tac.", [
                _make_premise("Coq.B", "definition"),
                _make_premise("Coq.A", "lemma"),
            ]),
            _make_extraction_step(2, "tac2.", [
                _make_premise("Coq.C", "constructor"),
                _make_premise("Coq.A", "lemma"),
            ]),
        ]
        record = _make_extraction_record(steps=steps)
        entry1 = extract_dependencies(record)
        entry2 = extract_dependencies(record)
        assert [ref.name for ref in entry1.depends_on] == [ref.name for ref in entry2.depends_on]


# ═══════════════════════════════════════════════════════════════════════════
# 5. DependencyEntry Serialization (§4.5)
# ═══════════════════════════════════════════════════════════════════════════


class TestDependencyEntrySerialization:
    """DependencyEntry serializes as JSON with fields in specified order."""

    def test_json_field_order(self):
        from Poule.extraction.dependency_graph import extract_dependencies
        from Poule.extraction.types import DependencyEntry

        record = _spec_example_record()
        entry = extract_dependencies(record)
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        keys = list(parsed.keys())
        assert keys == ["theorem_name", "source_file", "project_id", "depends_on"]

    def test_dependency_ref_field_order(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _spec_example_record()
        entry = extract_dependencies(record)
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        for dep_ref in parsed["depends_on"]:
            keys = list(dep_ref.keys())
            assert keys == ["name", "kind"]

    def test_spec_example_serialization(self):
        """The spec §7 example output for add_comm."""
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "induction n.", [
                _make_premise("Coq.Arith.PeanoNat.Nat.add_0_r", "lemma"),
                _make_premise("Coq.Arith.PeanoNat.Nat.add_succ_r", "lemma"),
            ]),
            _make_extraction_step(2, "constructor.", [
                _make_premise("Coq.Init.Datatypes.nat", "inductive"),
                _make_premise("Coq.Init.Datatypes.S", "constructor"),
            ]),
        ]
        record = _make_extraction_record(
            theorem_name="Coq.Arith.PeanoNat.Nat.add_comm",
            source_file="theories/Arith/PeanoNat.v",
            project_id="coq-stdlib",
            steps=steps,
        )
        entry = extract_dependencies(record)
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        assert parsed["theorem_name"] == "Coq.Arith.PeanoNat.Nat.add_comm"
        assert parsed["source_file"] == "theories/Arith/PeanoNat.v"
        assert parsed["project_id"] == "coq-stdlib"
        assert len(parsed["depends_on"]) == 4
        assert parsed["depends_on"][0] == {"name": "Coq.Arith.PeanoNat.Nat.add_0_r", "kind": "lemma"}
        assert parsed["depends_on"][3] == {"name": "Coq.Init.Datatypes.S", "kind": "constructor"}

    def test_empty_depends_on_serialization(self):
        """Theorem with no external dependencies (§7 second example)."""
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _make_extraction_record(
            theorem_name="Coq.Init.Logic.eq_refl_proof",
            source_file="theories/Init/Logic.v",
            project_id="coq-stdlib",
        )
        entry = extract_dependencies(record)
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        assert parsed["depends_on"] == []


class TestJsonLinesFormat:
    """Output is JSON Lines format: one DependencyEntry per line (§4.5)."""

    def test_to_json_produces_single_line(self):
        from Poule.extraction.dependency_graph import extract_dependencies

        record = _spec_example_record()
        entry = extract_dependencies(record)
        json_str = entry.to_json()
        assert "\n" not in json_str


# ═══════════════════════════════════════════════════════════════════════════
# 6. Integration Modes (§4.6)
# ═══════════════════════════════════════════════════════════════════════════


class TestPostHocMode:
    """Post-hoc mode reads extraction output, writes dependency graph."""

    def test_reads_extraction_output_and_writes_dependency_graph(self):
        from Poule.extraction.dependency_graph import extract_dependency_graph

        record1 = _make_extraction_record(theorem_name="Coq.T1")
        record2 = _make_extraction_record(theorem_name="Coq.T2")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as inp:
            inp.write(json.dumps(record1) + "\n")
            inp.write(json.dumps(record2) + "\n")
            input_path = Path(inp.name)

        output_path = Path(tempfile.mktemp(suffix=".jsonl"))

        try:
            extract_dependency_graph(input_path, output_path)

            lines = output_path.read_text().strip().split("\n")
            assert len(lines) == 2
            entry1 = json.loads(lines[0])
            entry2 = json.loads(lines[1])
            assert entry1["theorem_name"] == "Coq.T1"
            assert entry2["theorem_name"] == "Coq.T2"
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def test_skips_extraction_error_records(self):
        """ExtractionError records are skipped; no dependency entry produced (§4.6)."""
        from Poule.extraction.dependency_graph import extract_dependency_graph

        record = _make_extraction_record(theorem_name="Coq.Good")
        error = _make_extraction_error(theorem_name="Coq.Bad")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as inp:
            inp.write(json.dumps(record) + "\n")
            inp.write(json.dumps(error) + "\n")
            input_path = Path(inp.name)

        output_path = Path(tempfile.mktemp(suffix=".jsonl"))

        try:
            extract_dependency_graph(input_path, output_path)

            lines = output_path.read_text().strip().split("\n")
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["theorem_name"] == "Coq.Good"
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def test_skips_errors_count_matches(self):
        """§4.6 example: 100 records + 5 errors → 100 dependency entries."""
        from Poule.extraction.dependency_graph import extract_dependency_graph

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as inp:
            for i in range(100):
                record = _make_extraction_record(theorem_name=f"Coq.T{i}")
                inp.write(json.dumps(record) + "\n")
            for i in range(5):
                error = _make_extraction_error(theorem_name=f"Coq.E{i}")
                inp.write(json.dumps(error) + "\n")
            input_path = Path(inp.name)

        output_path = Path(tempfile.mktemp(suffix=".jsonl"))

        try:
            extract_dependency_graph(input_path, output_path)

            lines = output_path.read_text().strip().split("\n")
            assert len(lines) == 100
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Error Cases (§5)
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorCases:
    """Error conditions defined in §5."""

    def test_no_premises_yields_empty_depends_on(self):
        """ExtractionRecord with no premise annotations → depends_on = []."""
        from Poule.extraction.dependency_graph import extract_dependencies

        steps = [
            _make_extraction_step(0, None, []),
            _make_extraction_step(1, "reflexivity.", []),
            _make_extraction_step(2, "trivial.", []),
        ]
        record = _make_extraction_record(steps=steps)
        entry = extract_dependencies(record)
        assert entry.depends_on == []

    def test_extraction_error_skipped_in_post_hoc(self):
        """ExtractionError record in input → skipped, no DependencyEntry produced."""
        from Poule.extraction.dependency_graph import extract_dependency_graph

        error = _make_extraction_error()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as inp:
            inp.write(json.dumps(error) + "\n")
            input_path = Path(inp.name)

        output_path = Path(tempfile.mktemp(suffix=".jsonl"))

        try:
            extract_dependency_graph(input_path, output_path)

            content = output_path.read_text().strip()
            assert content == ""
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def test_invalid_json_lines_raises_value_error(self):
        """Invalid JSON Lines input raises ValueError with line number."""
        from Poule.extraction.dependency_graph import extract_dependency_graph

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as inp:
            record = _make_extraction_record(theorem_name="Coq.Good")
            inp.write(json.dumps(record) + "\n")
            inp.write("this is not valid json\n")
            input_path = Path(inp.name)

        output_path = Path(tempfile.mktemp(suffix=".jsonl"))

        try:
            with pytest.raises(ValueError, match=r"line"):
                extract_dependency_graph(input_path, output_path)
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Types (DependencyEntry, DependencyRef)
# ═══════════════════════════════════════════════════════════════════════════


class TestDependencyTypes:
    """DependencyEntry and DependencyRef types exist in extraction.types."""

    def test_dependency_ref_has_name_and_kind(self):
        from Poule.extraction.types import DependencyRef

        ref = DependencyRef(name="Coq.A", kind="lemma")
        assert ref.name == "Coq.A"
        assert ref.kind == "lemma"

    def test_dependency_entry_has_required_fields(self):
        from Poule.extraction.types import DependencyEntry, DependencyRef

        entry = DependencyEntry(
            theorem_name="Coq.T",
            source_file="theories/T.v",
            project_id="proj",
            depends_on=[DependencyRef(name="Coq.A", kind="lemma")],
        )
        assert entry.theorem_name == "Coq.T"
        assert entry.source_file == "theories/T.v"
        assert entry.project_id == "proj"
        assert len(entry.depends_on) == 1

    def test_dependency_entry_has_to_json_method(self):
        from Poule.extraction.types import DependencyEntry

        entry = DependencyEntry(
            theorem_name="Coq.T",
            source_file="theories/T.v",
            project_id="proj",
            depends_on=[],
        )
        assert callable(getattr(entry, "to_json", None))


# ═══════════════════════════════════════════════════════════════════════════
# import_dependencies tests (specification/extraction.md §4.6)
# ═══════════════════════════════════════════════════════════════════════════


def _create_test_index(db_path: Path, declarations: list[tuple[str, str]]) -> None:
    """Create a minimal index database with declarations for import testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE declarations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            module TEXT NOT NULL,
            kind TEXT NOT NULL,
            statement TEXT NOT NULL,
            type_expr TEXT,
            constr_tree BLOB,
            node_count INTEGER NOT NULL CHECK(node_count > 0),
            symbol_set TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE dependencies (
            src INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
            dst INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            PRIMARY KEY (src, dst, relation)
        )
    """)
    for name, module in declarations:
        conn.execute(
            "INSERT INTO declarations (name, module, kind, statement, node_count, symbol_set) "
            "VALUES (?, ?, 'definition', '', 1, '[]')",
            (name, module),
        )
    conn.commit()
    conn.close()


def _write_dep_graph(path: Path, entries: list[dict]) -> None:
    """Write DependencyEntry dicts as JSON Lines."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestImportDependencies:
    """Tests for import_dependencies (spec §4.6)."""

    def test_import_inserts_edges(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat"),
            ("Coq.Arith.PeanoNat.Nat.add_0_r", "Coq.Arith.PeanoNat"),
            ("Coq.Init.Datatypes.nat", "Coq.Init.Datatypes"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.Arith.PeanoNat.Nat.add_comm",
            "source_file": "theories/Arith/PeanoNat.v",
            "project_id": "coq-stdlib",
            "depends_on": [
                {"name": "Coq.Arith.PeanoNat.Nat.add_0_r", "kind": "lemma"},
                {"name": "Coq.Init.Datatypes.nat", "kind": "inductive"},
            ],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 2

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM dependencies").fetchone()
        assert rows[0] == 2
        conn.close()

    def test_import_skips_unresolvable_names(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.Arith.PeanoNat.Nat.add_comm",
            "source_file": "theories/Arith/PeanoNat.v",
            "project_id": "coq-stdlib",
            "depends_on": [
                {"name": "MyProject.unknown_lemma", "kind": "lemma"},
            ],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 0

    def test_import_is_idempotent(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.A",
            "source_file": "A.v",
            "project_id": "test",
            "depends_on": [{"name": "Coq.B", "kind": "definition"}],
        }])

        import_dependencies(deps_path, db_path)
        # Second import should not fail or duplicate
        import_dependencies(deps_path, db_path)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM dependencies").fetchone()
        assert rows[0] == 1
        conn.close()

    def test_import_uses_suffix_resolution(self, tmp_path):
        """Spec §4.6: same multi-strategy resolver as Pass 2."""
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat"),
            ("Coq.Arith.PeanoNat.Nat.add_0_r", "Coq.Arith.PeanoNat"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        # Use short name that should resolve via suffix match
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.Arith.PeanoNat.Nat.add_comm",
            "source_file": "PeanoNat.v",
            "project_id": "test",
            "depends_on": [{"name": "Nat.add_0_r", "kind": "lemma"}],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 1

    def test_import_skips_self_loops(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.A",
            "source_file": "A.v",
            "project_id": "test",
            "depends_on": [{"name": "Coq.A", "kind": "definition"}],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 0


# ═══════════════════════════════════════════════════════════════════════════
# DOT format import (specification/extraction.md §4.6 — DOT format)
# ═══════════════════════════════════════════════════════════════════════════


def _write_dot_file(path: Path, edges: list[tuple[str, str]]) -> None:
    """Write a coq-dpdgraph-style DOT file."""
    with open(path, "w") as f:
        f.write("digraph dependencies {\n")
        for src, dst in edges:
            f.write(f'  "{src}" -> "{dst}";\n')
        f.write("}\n")


class TestImportDependenciesDotFormat:
    """Tests for DOT format import (spec §4.6 — DOT format)."""

    def test_dot_import_inserts_edges(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.Arith.PeanoNat.Nat.add_assoc", "Coq.Arith.PeanoNat"),
            ("Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [
            ("Coq.Arith.PeanoNat.Nat.add_assoc", "Coq.Arith.PeanoNat.Nat.add_comm"),
        ])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 1

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT src, dst, relation FROM dependencies"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "uses"
        conn.close()

    def test_dot_import_auto_detects_format_from_extension(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [("Coq.A", "Coq.B")])

        inserted = import_dependencies(dot_path, db_path)
        assert inserted == 1

    def test_dot_import_skips_unresolvable_endpoints(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [
            ("Coq.A", "Unknown.B"),
            ("Unknown.C", "Coq.A"),
        ])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 0

    def test_dot_import_handles_multiple_edges(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
            ("Coq.C", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [
            ("Coq.A", "Coq.B"),
            ("Coq.A", "Coq.C"),
            ("Coq.B", "Coq.C"),
        ])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 3

    def test_dot_import_is_idempotent(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [("Coq.A", "Coq.B")])

        import_dependencies(dot_path, db_path, source_format="dot")
        import_dependencies(dot_path, db_path, source_format="dot")

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM dependencies").fetchone()
        assert rows[0] == 1
        conn.close()

    def test_dot_import_skips_self_loops(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [("Coq.A", "Coq")])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [("Coq.A", "Coq.A")])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 0

    def test_dot_import_ignores_non_edge_lines(self, tmp_path):
        """DOT files may contain node declarations, attributes, comments."""
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        with open(dot_path, "w") as f:
            f.write("digraph dependencies {\n")
            f.write("  // This is a comment\n")
            f.write('  "Coq.A" [label="A"];\n')
            f.write('  "Coq.A" -> "Coq.B";\n')
            f.write("  rankdir=LR;\n")
            f.write("}\n")

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 1

    def test_dot_import_uses_suffix_resolution(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.Arith.PeanoNat.Nat.add_comm", "Coq.Arith.PeanoNat"),
            ("Coq.Arith.PeanoNat.Nat.add_0_r", "Coq.Arith.PeanoNat"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [
            ("Nat.add_comm", "Nat.add_0_r"),
        ])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 1

    def test_dot_import_returns_count(self, tmp_path):
        """Spec §4.6: returns count of edges inserted."""
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
            ("Coq.C", "Coq"),
        ])
        dot_path = tmp_path / "deps.dot"
        _write_dot_file(dot_path, [
            ("Coq.A", "Coq.B"),
            ("Coq.A", "Unknown"),  # unresolvable — skipped
            ("Coq.B", "Coq.C"),
        ])

        inserted = import_dependencies(dot_path, db_path, source_format="dot")
        assert inserted == 2


class TestImportDependenciesFormatDetection:
    """Tests for source format auto-detection (spec §4.6)."""

    def test_jsonl_extension_detected(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        deps_path = tmp_path / "deps.jsonl"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.A",
            "source_file": "A.v",
            "project_id": "test",
            "depends_on": [{"name": "Coq.B", "kind": "definition"}],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 1

    def test_json_extension_detected_as_jsonl(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [
            ("Coq.A", "Coq"),
            ("Coq.B", "Coq"),
        ])
        deps_path = tmp_path / "deps.json"
        _write_dep_graph(deps_path, [{
            "theorem_name": "Coq.A",
            "source_file": "A.v",
            "project_id": "test",
            "depends_on": [{"name": "Coq.B", "kind": "definition"}],
        }])

        inserted = import_dependencies(deps_path, db_path)
        assert inserted == 1

    def test_unrecognized_extension_raises_error(self, tmp_path):
        from Poule.extraction.dependency_graph import import_dependencies

        db_path = tmp_path / "index.db"
        _create_test_index(db_path, [("Coq.A", "Coq")])
        deps_path = tmp_path / "deps.xyz"
        deps_path.write_text("")

        with pytest.raises(ValueError, match="Unrecognized"):
            import_dependencies(deps_path, db_path)
