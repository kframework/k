from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Hashable, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar, final

from ..cterm import CTerm
from ..kast.inner import KApply, KSequence, KToken, KVariable, bottom_up_with_summary
from .kcfg import KCFG, NodeVariant

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..kast.inner import KInner, KLabel


A = TypeVar('A', bound=Hashable)


class OptimizedNodeStore(MutableMapping[int, KCFG.Node]):
    _nodes: dict[int, KCFG.Node]
    _optimized_terms: _Cache[_OptInner]
    _klabels: _Cache[KLabel]
    _terms: list[KInner]

    _lock: threading.Lock

    def __init__(self) -> None:
        self._nodes = {}
        self._optimized_terms = _Cache()
        self._klabels = _Cache()
        self._terms = []

        self._lock = threading.Lock()

    def __getitem__(self, key: int) -> KCFG.Node:
        return self._nodes[key]

    def __setitem__(self, key: int, node: KCFG.Node) -> None:
        # Term-dedup the canonical cterm and every variant cterm, carrying the provenance chain
        # through unchanged (variants must survive the store).
        new_variants = tuple(
            NodeVariant(variant.producer, variant.request_id, self._optimize_cterm(variant.cterm))
            for variant in node.variants
        )
        new_node = KCFG.Node(node.id, self._optimize_cterm(node.cterm), attrs=node.attrs, variants=new_variants)
        self._nodes[key] = new_node

    def _optimize_cterm(self, cterm: CTerm) -> CTerm:
        return CTerm(self._optimize(cterm.config), tuple(self._optimize(c) for c in cterm.constraints))

    def __delitem__(self, key: int) -> None:
        del self._nodes[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)

    def _optimize(self, term: KInner) -> KInner:
        def optimizer(to_optimize: KInner, children: list[int]) -> tuple[KInner, int]:
            if isinstance(to_optimize, KToken) or isinstance(to_optimize, KVariable):
                optimized_id = self._cache(_OptBasic(to_optimize))
            elif isinstance(to_optimize, KApply):
                klabel_id = self._klabels.cache(to_optimize.label)
                optimized_id = self._cache(_OptApply(klabel_id, tuple(children)))
            elif isinstance(to_optimize, KSequence):
                optimized_id = self._cache(_OptKSequence(tuple(children)))
            else:
                raise ValueError('Unknown term type: ' + str(type(to_optimize)))
            return (self._terms[optimized_id], optimized_id)

        with self._lock:
            optimized, _ = bottom_up_with_summary(optimizer, term)
        return optimized

    def _cache(self, term: _OptInner) -> int:
        id = self._optimized_terms.cache(term)
        assert id <= len(self._terms)
        if id == len(self._terms):
            self._terms.append(term.build(self._klabels, self._terms))
        return id


class _Cache(Generic[A]):
    _value_to_id: dict[A, int]
    _values: list[A]

    def __init__(self) -> None:
        self._value_to_id = {}
        self._values = []

    def cache(self, value: A) -> int:
        idx = self._value_to_id.get(value)
        if idx is not None:
            return idx
        idx = len(self._values)
        self._value_to_id[value] = idx
        self._values.append(value)
        return idx

    def get(self, idx: int) -> A:
        return self._values[idx]


class _OptInner(ABC):
    @abstractmethod
    def build(self, klabels: _Cache[KLabel], terms: list[KInner]) -> KInner: ...


@final
@dataclass(eq=True, frozen=True)
class _OptBasic(_OptInner):
    term: KInner

    def build(self, klabels: _Cache[KLabel], terms: list[KInner]) -> KInner:
        return self.term


@final
@dataclass(eq=True, frozen=True)
class _OptApply(_OptInner):
    label: int
    children: tuple[int, ...]

    def build(self, klabels: _Cache[KLabel], terms: list[KInner]) -> KInner:
        return KApply(klabels.get(self.label), tuple(terms[child] for child in self.children))


@final
@dataclass(eq=True, frozen=True)
class _OptKSequence(_OptInner):
    children: tuple[int, ...]

    def build(self, klabels: _Cache[KLabel], terms: list[KInner]) -> KInner:
        return KSequence(tuple(terms[child] for child in self.children))
