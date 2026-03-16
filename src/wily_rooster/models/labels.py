"""Node label types for expression trees.

Defines an abstract NodeLabel base and 15 concrete frozen dataclass subtypes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from wily_rooster.models.enums import SortKind


class NodeLabel(abc.ABC):
    """Abstract base for all node labels. Equality-comparable and hashable."""

    @abc.abstractmethod
    def __init__(self) -> None: ...  # pragma: no cover


# --- Leaf labels ---

@dataclass(frozen=True)
class LConst(NodeLabel):
    name: str

@dataclass(frozen=True)
class LInd(NodeLabel):
    name: str

@dataclass(frozen=True)
class LConstruct(NodeLabel):
    name: str
    index: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("constructor index must be non-negative")

@dataclass(frozen=True)
class LCseVar(NodeLabel):
    id: int

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError("CSE variable ID must be non-negative")

@dataclass(frozen=True)
class LRel(NodeLabel):
    index: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("de Bruijn index must be non-negative")

@dataclass(frozen=True)
class LSort(NodeLabel):
    kind: SortKind

@dataclass(frozen=True)
class LPrimitive(NodeLabel):
    value: int | float


# --- Interior labels ---

@dataclass(frozen=True)
class LApp(NodeLabel):
    pass

@dataclass(frozen=True)
class LAbs(NodeLabel):
    pass

@dataclass(frozen=True)
class LLet(NodeLabel):
    pass

@dataclass(frozen=True)
class LProj(NodeLabel):
    name: str

@dataclass(frozen=True)
class LCase(NodeLabel):
    ind_name: str

@dataclass(frozen=True)
class LProd(NodeLabel):
    pass

@dataclass(frozen=True)
class LFix(NodeLabel):
    mutual_index: int

    def __post_init__(self) -> None:
        if self.mutual_index < 0:
            raise ValueError("mutual index must be non-negative")

@dataclass(frozen=True)
class LCoFix(NodeLabel):
    mutual_index: int

    def __post_init__(self) -> None:
        if self.mutual_index < 0:
            raise ValueError("mutual index must be non-negative")
