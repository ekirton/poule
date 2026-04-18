"""Unit tests for the SerAPI backend's Print Module parser.

Covers fully qualified name derivation when ``Print Module`` output
contains nested ``Module <Name> ... End`` blocks. See
``specification/extraction.md`` §4.1.2 (FQN derivation) and
``doc/architecture/coq-extraction.md`` (Module path derivation).
"""

from __future__ import annotations

from Poule.extraction.backends.serapi_backend import SerAPIBackend


class TestParseModuleOutputFlat:
    """Declarations in a flat (non-nested) module get the module prefix."""

    def test_definition_extracted_with_module_prefix(self):
        output = (
            "Module\nInit.Nat\n:= Struct\n"
            "     Definition add : nat -> nat -> nat.\n"
            "     Definition mul : nat -> nat -> nat.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "Init.Nat")
        names = [fqn for fqn, _kind, _ct in result]
        assert "Init.Nat.add" in names
        assert "Init.Nat.mul" in names

    def test_theorem_and_lemma_both_map_to_lemma_kind(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Theorem foo_thm : True.\n"
            "     Lemma bar_lem : True.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        by_name = {fqn: kind for fqn, kind, _ in result}
        assert by_name["MyLib.foo_thm"] == "Lemma"
        assert by_name["MyLib.bar_lem"] == "Lemma"

    def test_empty_module_yields_no_declarations(self):
        output = "Module\nEmpty\n:= Struct\n   End"
        assert SerAPIBackend._parse_module_output(output, "Empty") == []


class TestParseModuleOutputNested:
    """Declarations inside a sub-module must be qualified with the sub-module path."""

    def test_single_level_submodule_qualifies_declarations(self):
        output = (
            "Module\nPeanoNat\n:= Struct\n"
            "     Module Nat\n"
            "     Definition lt_n_Sm_le : forall n m : nat, n < S m -> n <= m.\n"
            "     End Nat\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "PeanoNat")
        names = [fqn for fqn, _kind, _ct in result]
        assert "PeanoNat.Nat.lt_n_Sm_le" in names
        assert "PeanoNat.lt_n_Sm_le" not in names

    def test_two_level_nesting_builds_full_path(self):
        output = (
            "Module\nOuter\n:= Struct\n"
            "     Module Mid\n"
            "     Module Inner\n"
            "     Definition deep_thm : nat.\n"
            "     End Inner\n"
            "     End Mid\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "Outer")
        names = [fqn for fqn, _kind, _ in result]
        assert names == ["Outer.Mid.Inner.deep_thm"]

    def test_declarations_in_parent_and_submodule_differ(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Definition parent_thm : nat.\n"
            "     Module Sub\n"
            "     Definition child_thm : nat.\n"
            "     End Sub\n"
            "     Definition sibling_thm : nat.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        names = [fqn for fqn, _kind, _ in result]
        assert "MyLib.parent_thm" in names
        assert "MyLib.Sub.child_thm" in names
        assert "MyLib.sibling_thm" in names
        assert "MyLib.child_thm" not in names

    def test_bare_end_pops_innermost(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Module Sub\n"
            "     Definition inside_thm : nat.\n"
            "     End\n"
            "     Definition after_sub : nat.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        names = [fqn for fqn, _kind, _ in result]
        assert "MyLib.Sub.inside_thm" in names
        assert "MyLib.after_sub" in names

    def test_functor_application_does_not_push(self):
        """``Module M := F(X).`` opens no body — nothing to push."""
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Module AppliedFunctor := F(X).\n"
            "     Definition not_inside_functor : nat.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        names = [fqn for fqn, _kind, _ in result]
        assert "MyLib.not_inside_functor" in names
        assert "MyLib.AppliedFunctor.not_inside_functor" not in names


class TestParseModuleOutputKinds:
    """All declaration kinds are preserved and qualified through nesting."""

    def test_inductive_and_record_extracted_with_kinds(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Inductive color : Set.\n"
            "     Record point : Set.\n"
            "     Module Inner\n"
            "     Inductive nested_ind : Set.\n"
            "     End Inner\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        by_name = {fqn: kind for fqn, kind, _ in result}
        assert by_name["MyLib.color"] == "Inductive"
        assert by_name["MyLib.point"] == "Record"
        assert by_name["MyLib.Inner.nested_ind"] == "Inductive"

    def test_parameter_and_axiom_extracted(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Parameter my_param : nat.\n"
            "     Axiom my_axiom : True.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        by_name = {fqn: kind for fqn, kind, _ in result}
        assert by_name["MyLib.my_param"] == "Parameter"
        assert by_name["MyLib.my_axiom"] == "Axiom"

    def test_canonical_structure_kept_as_canonical_structure(self):
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Canonical Structure my_canon : T.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        by_name = {fqn: kind for fqn, kind, _ in result}
        assert by_name["MyLib.my_canon"] == "Canonical Structure"

    def test_primed_identifiers_captured(self):
        """Coq allows primes in names (e.g., ``foo'``)."""
        output = (
            "Module\nMyLib\n:= Struct\n"
            "     Definition foo' : nat.\n"
            "   End"
        )
        result = SerAPIBackend._parse_module_output(output, "MyLib")
        names = [fqn for fqn, _kind, _ in result]
        assert "MyLib.foo'" in names
