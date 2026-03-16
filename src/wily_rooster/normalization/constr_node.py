"""ConstrNode variant types — intermediate representation of Coq's Constr.t."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rel:
    n: int


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Sort:
    sort: str


@dataclass(frozen=True)
class Cast:
    term: object  # ConstrNode
    type: object  # ConstrNode


@dataclass(frozen=True)
class Prod:
    name: str
    type: object  # ConstrNode
    body: object  # ConstrNode


@dataclass(frozen=True)
class Lambda:
    name: str
    type: object  # ConstrNode
    body: object  # ConstrNode


@dataclass(frozen=True)
class LetIn:
    name: str
    value: object  # ConstrNode
    type: object  # ConstrNode
    body: object  # ConstrNode


@dataclass(frozen=True)
class App:
    func: object  # ConstrNode
    args: list  # list[ConstrNode]


@dataclass(frozen=True)
class Const:
    fqn: str


@dataclass(frozen=True)
class Ind:
    fqn: str


@dataclass(frozen=True)
class Construct:
    fqn: str
    index: int


@dataclass(frozen=True)
class Case:
    ind_name: str
    scrutinee: object  # ConstrNode
    branches: list  # list[ConstrNode]


@dataclass(frozen=True)
class Fix:
    index: int
    bodies: list  # list[ConstrNode]


@dataclass(frozen=True)
class CoFix:
    index: int
    bodies: list  # list[ConstrNode]


@dataclass(frozen=True)
class Proj:
    name: str
    term: object  # ConstrNode


@dataclass(frozen=True)
class Int:
    value: int


@dataclass(frozen=True)
class Float:
    value: float
