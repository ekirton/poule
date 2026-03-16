"""Enumerations for the wily-rooster data model."""

from __future__ import annotations

import enum


class SortKind(enum.Enum):
    PROP = "prop"
    SET = "set"
    TYPE_UNIV = "type_univ"


class DeclKind(enum.Enum):
    LEMMA = "lemma"
    THEOREM = "theorem"
    DEFINITION = "definition"
    INSTANCE = "instance"
    INDUCTIVE = "inductive"
    CONSTRUCTOR = "constructor"
    AXIOM = "axiom"
