from __future__ import annotations

import json
import logging
from abc import abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import chain
from typing import TYPE_CHECKING, final, overload

from ..utils import EMPTY_FROZEN_DICT, FrozenDict
from .kast import KAst

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import Any, Final, TypeVar

    T = TypeVar('T', bound='KAst')
    KI = TypeVar('KI', bound='KInner')
    A = TypeVar('A')
    B = TypeVar('B')

_LOGGER: Final = logging.getLogger(__name__)


@final
@dataclass(frozen=True)
class KSort(KAst):
    """Represent a K sort, optionally applied to sort parameters."""

    name: str
    params: tuple[KSort, ...]

    def __init__(self, name: str, params: Iterable[KSort] = ()):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'params', tuple(params))

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KSort:
        return KSort(
            name=d['name'],
            params=(KSort.from_dict(p) for p in d.get('params', ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {'node': 'KSort', 'name': self.name, 'params': [p.to_dict() for p in self.params]}

    def let(self, *, name: str | None = None, params: Iterable[KSort] | None = None) -> KSort:
        name = name if name is not None else self.name
        params = params if params is not None else self.params
        return KSort(name=name, params=params)

    def contains(self, sort: KSort) -> bool:
        """Return whether ``sort`` appears anywhere in this sort's parameter tree (including itself)."""
        return self == sort or any(param.contains(sort) for param in self.params)


@final
@dataclass(frozen=True)
class KLabel(KAst):
    """Represents a symbol that can be applied in a K AST, potentially with sort parameters."""

    name: str
    params: tuple[KSort, ...]

    @overload
    def __init__(self, name: str, params: Iterable[str | KSort]): ...

    @overload
    def __init__(self, name: str, *params: str | KSort): ...

    # TODO Is it possible to extract a decorator?
    def __init__(self, name: str, *args: Any, **kwargs: Any):
        """Construct a new `KLabel`, with optional sort parameters."""
        if kwargs:
            bad_arg = next((arg for arg in kwargs if arg != 'params'), None)
            if bad_arg:
                raise TypeError(f'KLabel() got an unexpected keyword argument: {bad_arg}')
            if args:
                raise TypeError('KLabel() got multiple values for argument: params')
            params = kwargs['params']

        elif (
            len(args) == 1
            and isinstance(args[0], Iterable)
            and not isinstance(args[0], str)
            and not isinstance(args[0], KInner)
        ):
            params = args[0]

        else:
            params = args

        params = tuple(KSort(param) if type(param) is str else param for param in params)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'params', params)

    def __iter__(self) -> Iterator[str | KSort]:
        """Return this symbol as iterator with the name as the head and the parameters as the tail."""
        return chain([self.name], self.params)

    @overload
    def __call__(self, args: Iterable[KInner]) -> KApply: ...

    @overload
    def __call__(self, *args: KInner) -> KApply: ...

    def __call__(self, *args: Any, **kwargs: Any) -> KApply:
        return self.apply(*args, **kwargs)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KLabel:
        return KLabel(name=d['name'], params=(KSort.from_dict(param) for param in d['params']))

    def to_dict(self) -> dict[str, Any]:
        return {'node': 'KLabel', 'name': self.name, 'params': [param.to_dict() for param in self.params]}

    def let(self, *, name: str | None = None, params: Iterable[str | KSort] | None = None) -> KLabel:
        """Return a copy of this `KLabel` with potentially the name or sort parameters updated."""
        name = name if name is not None else self.name
        params = params if params is not None else self.params
        return KLabel(name=name, params=params)

    @overload
    def apply(self, args: Iterable[KInner]) -> KApply: ...

    @overload
    def apply(self, *args: KInner) -> KApply: ...

    def apply(self, *args: Any, **kwargs: Any) -> KApply:
        """Construct a `KApply` with this `KLabel` as the AST head and the supplied parameters as the arguments."""
        return KApply(self, *args, **kwargs)


class KInner(KAst):
    """Represent the AST of a given K inner term.

    This class represents the AST of a given term.
    The nodes in the AST should be coming from a given KDefinition, so that they can be checked for well-typedness.
    """

    _NODES: Final = {'KVariable', 'KToken', 'KApply', 'KAs', 'KRewrite', 'KSequence'}

    @staticmethod
    def from_json(s: str) -> KInner:
        return KInner.from_dict(json.loads(s))

    @staticmethod
    def from_dict(dct: Mapping[str, Any]) -> KInner:
        """Deserialize a given `KInner` into a more specific type from a dictionary."""
        stack: list = [dct, KInner._extract_dicts(dct), []]
        while True:
            terms = stack[-1]
            dcts = stack[-2]
            dct = stack[-3]
            idx = len(terms) - len(dcts)
            if not idx:
                stack.pop()
                stack.pop()
                stack.pop()
                cls = globals()[dct['node']]
                term = cls._from_dict(dct, terms)
                if not stack:
                    return term
                stack[-1].append(term)
            else:
                dct = dcts[idx]
                stack.append(dct)
                stack.append(KInner._extract_dicts(dct))
                stack.append([])

    @staticmethod
    def _extract_dicts(dct: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        match dct['node']:
            case 'KApply':
                return dct['args']
            case 'KSequence':
                return dct['items']
            case 'KRewrite':
                return [dct['lhs'], dct['rhs']]
            case 'KAs':
                return [dct['pattern'], dct['alias']]
            case _:
                return []

    @classmethod
    @abstractmethod
    def _from_dict(cls: type[KI], d: Mapping[str, Any], terms: list[KInner]) -> KI: ...

    @property
    @abstractmethod
    def terms(self) -> tuple[KInner, ...]:
        """Returns the children of this given `KInner`."""
        ...

    @abstractmethod
    def let_terms(self: KI, terms: Iterable[KInner]) -> KI:
        """Set children of this given `KInner`."""
        ...

    @final
    def map_inner(self: KI, f: Callable[[KInner], KInner]) -> KI:
        """Apply a transformation to all children of this given `KInner`."""
        return self.let_terms(f(term) for term in self.terms)

    @abstractmethod
    def match(self, term: KInner) -> Subst | None:
        """Perform syntactic pattern matching and return the substitution.

        Args:
            term: Term to match.

        Returns:
            A substitution instantiating `self` to `term` if one exists, ``None`` otherwise.
        """
        ...

    @staticmethod
    def _combine_matches(substs: Iterable[Subst | None]) -> Subst | None:
        def combine(subst1: Subst | None, subst2: Subst | None) -> Subst | None:
            if subst1 is None or subst2 is None:
                return None

            return subst1.union(subst2)

        unit: Subst | None = Subst()
        return reduce(combine, substs, unit)

    @final
    def to_dict(self) -> dict[str, Any]:
        stack: list = [self, []]
        while True:
            dicts = stack[-1]
            term = stack[-2]
            idx = len(dicts) - len(term.terms)
            if not idx:
                stack.pop()
                stack.pop()
                dct = term._to_dict(dicts)
                if not stack:
                    return dct
                stack[-1].append(dct)
            else:
                stack.append(term.terms[idx])
                stack.append([])

    @abstractmethod
    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]: ...


@final
@dataclass(frozen=True)
class KToken(KInner):
    """Represent a domain-value in K AST."""

    token: str
    sort: KSort

    def __init__(self, token: str, sort: str | KSort):
        """Construct a new `KToken` with a given string representation in the supplied sort."""
        if type(sort) is str:
            sort = KSort(sort)

        object.__setattr__(self, 'token', token)
        object.__setattr__(self, 'sort', sort)

    @classmethod
    def _from_dict(cls: type[KToken], dct: Mapping[str, Any], terms: list[KInner]) -> KToken:
        assert not terms
        return KToken(token=dct['token'], sort=KSort.from_dict(dct['sort']))

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        assert not terms
        return {'node': 'KToken', 'token': self.token, 'sort': self.sort.to_dict()}

    def let(self, *, token: str | None = None, sort: str | KSort | None = None) -> KToken:
        """Return a copy of the `KToken` with the token or sort potentially updated."""
        token = token if token is not None else self.token
        sort = sort if sort is not None else self.sort
        return KToken(token=token, sort=sort)

    @property
    def terms(self) -> tuple[()]:
        return ()

    def let_terms(self, terms: Iterable[KInner]) -> KToken:
        () = terms
        return self

    def match(self, term: KInner) -> Subst | None:
        if type(term) is KToken:
            return Subst() if term.token == self.token else None
        _LOGGER.debug(f'Matching failed: ({self}.match({term}))')
        return None


@final
@dataclass(frozen=True)
class KVariable(KInner):
    """Represent a logical variable in a K AST, with a name and optionally a sort."""

    name: str
    sort: KSort | None

    def __init__(self, name: str, sort: str | KSort | None = None):
        """Construct a new `KVariable` with a given name and optional sort."""
        if type(sort) is str:
            sort = KSort(sort)

        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'sort', sort)

    def __lt__(self, other: Any) -> bool:
        """Lexicographic comparison of `KVariable` based on name for sorting."""
        if not isinstance(other, KAst):
            return NotImplemented
        if type(other) is KVariable:
            if (self.sort is None or other.sort is None) and self.name == other.name:
                return self.sort is None
        return super().__lt__(other)

    @classmethod
    def _from_dict(cls: type[KVariable], dct: Mapping[str, Any], terms: list[KInner]) -> KVariable:
        assert not terms
        sort = None
        if 'sort' in dct:
            sort = KSort.from_dict(dct['sort'])
        return KVariable(name=dct['name'], sort=sort)

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        assert not terms
        _d: dict[str, Any] = {'node': 'KVariable', 'name': self.name}
        if self.sort is not None:
            _d['sort'] = self.sort.to_dict()
        return _d

    def let(self, *, name: str | None = None, sort: str | KSort | None = None) -> KVariable:
        """Return a copy of this `KVariable` with potentially the name or sort updated."""
        name = name if name is not None else self.name
        sort = sort if sort is not None else self.sort
        return KVariable(name=name, sort=sort)

    def let_sort(self, sort: KSort | None) -> KVariable:
        """Return a copy of this `KVariable` with just the sort updated."""
        return KVariable(self.name, sort=sort)

    @property
    def terms(self) -> tuple[()]:
        return ()

    def let_terms(self, terms: Iterable[KInner]) -> KVariable:
        () = terms
        return self

    def match(self, term: KInner) -> Subst:
        return Subst({self.name: term})


@final
@dataclass(frozen=True)
class KApply(KInner):
    """Represent the application of a `KLabel` in a K AST to arguments."""

    label: KLabel
    args: tuple[KInner, ...]

    @overload
    def __init__(self, label: str | KLabel, args: Iterable[KInner]): ...

    @overload
    def __init__(self, label: str | KLabel, *args: KInner): ...

    def __init__(self, label: str | KLabel, *args: Any, **kwargs: Any):
        """Construct a new `KApply` given the input `KLabel` or str, applied to arguments."""
        if type(label) is str:
            label = KLabel(label)

        if kwargs:
            bad_arg = next((arg for arg in kwargs if arg != 'args'), None)
            if bad_arg:
                raise TypeError(f'KApply() got an unexpected keyword argument: {bad_arg}')
            if args:
                raise TypeError('KApply() got multiple values for argument: args')
            _args = kwargs['args']

        elif len(args) == 1 and isinstance(args[0], Iterable) and not isinstance(args[0], KInner):
            _args = args[0]

        else:
            _args = args

        object.__setattr__(self, 'label', label)
        object.__setattr__(self, 'args', tuple(_args))

    @property
    def arity(self) -> int:
        """Return the count of the arguments."""
        return len(self.args)

    @property
    def is_cell(self) -> bool:
        """Return whether this is a cell-label application (based on heuristic about label names)."""
        return len(self.label.name) > 1 and self.label.name[0] == '<' and self.label.name[-1] == '>'

    @classmethod
    def _from_dict(cls: type[KApply], dct: Mapping[str, Any], terms: list[KInner]) -> KApply:
        return KApply(label=KLabel.from_dict(dct['label']), args=terms)

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        return {
            'node': 'KApply',
            'label': self.label.to_dict(),
            'args': terms,
            'arity': self.arity,
            'variable': False,
        }

    def let(self, *, label: str | KLabel | None = None, args: Iterable[KInner] | None = None) -> KApply:
        """Return a copy of this `KApply` with either the label or the arguments updated."""
        label = label if label is not None else self.label
        args = args if args is not None else self.args
        return KApply(label=label, args=args)

    @property
    def terms(self) -> tuple[KInner, ...]:
        return self.args

    def let_terms(self, terms: Iterable[KInner]) -> KApply:
        return self.let(args=terms)

    def match(self, term: KInner) -> Subst | None:
        if type(term) is KApply and term.label.name == self.label.name and term.arity == self.arity:
            return KInner._combine_matches(
                arg.match(term_arg) for arg, term_arg in zip(self.args, term.args, strict=True)
            )
        _LOGGER.debug(f'Matching failed: ({self}.match({term}))')
        return None


@final
@dataclass(frozen=True)
class KAs(KInner):
    """Represent a K `#as` pattern in the K AST format, with the original pattern and the variabl alias."""

    pattern: KInner
    alias: KInner

    def __init__(self, pattern: KInner, alias: KInner):
        """Construct a new `KAs` given the original pattern and the alias."""
        object.__setattr__(self, 'pattern', pattern)
        object.__setattr__(self, 'alias', alias)

    @classmethod
    def _from_dict(cls: type[KAs], dct: Mapping[str, Any], terms: list[KInner]) -> KAs:
        pattern, alias = terms
        return KAs(pattern=pattern, alias=alias)

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        pattern, alias = terms
        return {'node': 'KAs', 'pattern': pattern, 'alias': alias}

    def let(self, *, pattern: KInner | None = None, alias: KInner | None = None) -> KAs:
        """Return a copy of this `KAs` with potentially the pattern or alias updated."""
        pattern = pattern if pattern is not None else self.pattern
        alias = alias if alias is not None else self.alias
        return KAs(pattern=pattern, alias=alias)

    @property
    def terms(self) -> tuple[KInner, KInner]:
        return (self.pattern, self.alias)

    def let_terms(self, terms: Iterable[KInner]) -> KAs:
        pattern, alias = terms
        return KAs(pattern=pattern, alias=alias)

    def match(self, term: KInner) -> Subst | None:
        raise TypeError('KAs does not support pattern matching')


@final
@dataclass(frozen=True)
class KRewrite(KInner):
    """Represent a K rewrite in the K AST."""

    lhs: KInner
    rhs: KInner

    def __init__(self, lhs: KInner, rhs: KInner):
        """Construct a `KRewrite` given the LHS (left-hand-side) and RHS (right-hand-side) to use."""
        object.__setattr__(self, 'lhs', lhs)
        object.__setattr__(self, 'rhs', rhs)

    def __iter__(self) -> Iterator[KInner]:
        """Return a two-element iterator with the LHS first and RHS second."""
        return iter([self.lhs, self.rhs])

    def __call__(self, term: KInner, *, top: bool = False) -> KInner:
        if top:
            return self.apply_top(term)

        return self.apply(term)

    @classmethod
    def _from_dict(cls: type[KRewrite], dct: Mapping[str, Any], terms: list[KInner]) -> KRewrite:
        lhs, rhs = terms
        return KRewrite(lhs=lhs, rhs=rhs)

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        lhs, rhs = terms
        return {'node': 'KRewrite', 'lhs': lhs, 'rhs': rhs}

    def let(
        self,
        *,
        lhs: KInner | None = None,
        rhs: KInner | None = None,
    ) -> KRewrite:
        """Return a copy of this `KRewrite` with potentially the LHS or RHS updated."""
        lhs = lhs if lhs is not None else self.lhs
        rhs = rhs if rhs is not None else self.rhs
        return KRewrite(lhs=lhs, rhs=rhs)

    @property
    def terms(self) -> tuple[KInner, KInner]:
        return (self.lhs, self.rhs)

    def let_terms(self, terms: Iterable[KInner]) -> KRewrite:
        lhs, rhs = terms
        return KRewrite(lhs=lhs, rhs=rhs)

    def match(self, term: KInner) -> Subst | None:
        if type(term) is KRewrite:
            lhs_subst = self.lhs.match(term.lhs)
            rhs_subst = self.rhs.match(term.rhs)
            if lhs_subst is None or rhs_subst is None:
                return None
            return lhs_subst.union(rhs_subst)
        _LOGGER.debug(f'Matching failed: ({self}.match({term}))')
        return None

    def apply_top(self, term: KInner) -> KInner:
        """Rewrite a given term at the top.

        Args:
            term: Term to rewrite.

        Returns:
            The term with the rewrite applied once at the top.
        """
        subst = self.lhs.match(term)
        if subst is not None:
            return subst(self.rhs)
        return term

    def apply(self, term: KInner) -> KInner:
        """Attempt rewriting once at every position in a term bottom-up.

        Args:
            term: Term to rewrite.

        Returns:
            The term with rewrites applied at every node once starting from the bottom.
        """
        return bottom_up(self.apply_top, term)

    def replace_top(self, term: KInner) -> KInner:
        """Similar to apply_top but using exact syntactic matching instead of pattern matching."""
        if self.lhs == term:
            return self.rhs
        return term

    def replace(self, term: KInner) -> KInner:
        """Similar to apply but using exact syntactic matching instead of pattern matching."""
        return bottom_up(self.replace_top, term)


@final
@dataclass(frozen=True)
class KSequence(KInner, Sequence[KInner]):
    """Represent a associative list of `K` as a cons-list of `KItem` for sequencing computation in K AST format."""

    items: tuple[KInner, ...]

    @overload
    def __init__(self, items: Iterable[KInner]): ...

    @overload
    def __init__(self, *items: KInner): ...

    def __init__(self, *args: Any, **kwargs: Any):
        """Construct a new `KSequence` given the arguments."""
        if kwargs:
            bad_arg = next((arg for arg in kwargs if arg != 'items'), None)
            if bad_arg:
                raise TypeError(f'KSequence() got an unexpected keyword argument: {bad_arg}')
            if args:
                raise TypeError('KSequence() got multiple values for argument: items')
            items = kwargs['items']

        elif len(args) == 1 and isinstance(args[0], Iterable) and not isinstance(args[0], KInner):
            items = args[0]

        else:
            items = args

        _items: list[KInner] = []
        for i in items:
            if type(i) is KSequence:
                _items.extend(i.items)
            else:
                _items.append(i)
        items = tuple(_items)

        object.__setattr__(self, 'items', tuple(items))

    @overload
    def __getitem__(self, key: int) -> KInner: ...

    @overload
    def __getitem__(self, key: slice) -> tuple[KInner, ...]: ...

    def __getitem__(self, key: int | slice) -> KInner | tuple[KInner, ...]:
        return self.items[key]

    def __len__(self) -> int:
        return self.arity

    @property
    def arity(self) -> int:
        """Return the count of `KSequence` items."""
        return len(self.items)

    @classmethod
    def _from_dict(cls: type[KSequence], dct: Mapping[str, Any], terms: list[KInner]) -> KSequence:
        return KSequence(items=terms)

    def _to_dict(self, terms: list[KInner]) -> dict[str, Any]:
        return {'node': 'KSequence', 'items': terms, 'arity': self.arity}

    def let(self, *, items: Iterable[KInner] | None = None) -> KSequence:
        """Return a copy of this `KSequence` with the items potentially updated."""
        items = items if items is not None else self.items
        return KSequence(items=items)

    @property
    def terms(self) -> tuple[KInner, ...]:
        return self.items

    def let_terms(self, terms: Iterable[KInner]) -> KSequence:
        return KSequence(items=terms)

    def match(self, term: KInner) -> Subst | None:
        if type(term) is KSequence:
            if term.arity == self.arity:
                return KInner._combine_matches(
                    item.match(term_item) for item, term_item in zip(self.items, term.items, strict=True)
                )
            if 0 < self.arity and self.arity < term.arity and type(self.items[-1]) is KVariable:
                common_length = len(self.items) - 1
                _subst: Subst | None = Subst({self.items[-1].name: KSequence(term.items[common_length:])})
                for si, ti in zip(self.items[:common_length], term.items[:common_length], strict=True):
                    _subst = KInner._combine_matches([_subst, si.match(ti)])
                return _subst
        _LOGGER.debug(f'Matching failed: ({self}.match({term}))')
        return None


@dataclass(frozen=True)
class Subst(Mapping[str, KInner]):
    """Represents a substitution, which is a binding of variables to values of `KInner`."""

    _subst: FrozenDict[str, KInner]

    def __init__(self, subst: Mapping[str, KInner] = EMPTY_FROZEN_DICT):
        """Construct a new `Subst` given a mapping fo variable names to `KInner`."""
        object.__setattr__(self, '_subst', FrozenDict(subst))

    def __iter__(self) -> Iterator[str]:
        """Return the underlying `Subst` mapping as an iterator."""
        return iter(self._subst)

    def __len__(self) -> int:
        """Return the length of the underlying `Subst` mapping."""
        return len(self._subst)

    def __getitem__(self, key: str) -> KInner:
        """Get the `KInner` associated with the given variable name from the underlying `Subst` mapping."""
        return self._subst[key]

    def __mul__(self, other: Subst) -> Subst:
        """Overload for `Subst.compose`."""
        return self.compose(other)

    def __call__(self, term: KInner) -> KInner:
        """Overload for `Subst.apply`."""
        return self.apply(term)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Subst:
        """Deserialize a `Subst` from a given dictionary representing it."""
        return Subst({k: KInner.from_dict(v) for k, v in d.items()})

    def to_dict(self) -> dict[str, Any]:
        """Serialize a `Subst` to a dictionary representation."""
        return {k: v.to_dict() for k, v in self.items()}

    def minimize(self) -> Subst:
        """Return a new substitution with any identity items removed."""
        return Subst({k: v for k, v in self.items() if type(v) is not KVariable or v.name != k})

    def compose(self, other: Subst) -> Subst:
        """Union two substitutions together, preferring the assignments in `self` if present in both."""
        from_other = ((k, self(v)) for k, v in other.items())
        from_self = ((k, v) for k, v in self.items() if k not in other)
        return Subst(dict(chain(from_other, from_self)))

    def union(self, other: Subst) -> Subst | None:
        """Union two substitutions together, failing with `None` if there are conflicting assignments."""
        subst = dict(self)
        for v in other:
            if v in subst and subst[v] != other[v]:
                return None
            subst[v] = other[v]
        return Subst(subst)

    def apply(self, term: KInner) -> KInner:
        """Apply the given substitution to `KInner`, replacing free variable occurances with their valuations defined in this `Subst`."""

        def replace(term: KInner) -> KInner:
            if type(term) is KVariable and term.name in self:
                return self[term.name]
            return term

        return bottom_up(replace, term)

    def unapply(self, term: KInner) -> KInner:
        """Replace occurances of valuations from this `Subst` with the variables that they are assigned to."""
        new_term = term
        for var_name in self:
            lhs = self[var_name]
            rhs = KVariable(var_name)
            new_term = KRewrite(lhs, rhs).replace(new_term)
        return new_term

    @staticmethod
    def from_pred(pred: KInner) -> Subst:
        """Given a generic matching logic predicate, attempt to extract a `Subst` from it."""
        subst: dict[str, KInner] = {}
        for conjunct in flatten_label('#And', pred):
            match conjunct:
                case KApply(KLabel('#Equals'), [KVariable(var), term]):
                    subst[var] = term
                case _:
                    raise ValueError(f'Invalid substitution predicate: {conjunct}')
        return Subst(subst)

    @property
    def pred(self) -> KInner:
        """Turn this `Subst` into a boolean predicate using `_==K_` operator."""
        conjuncts = [
            KApply('_==K_', KVariable(name), val)
            for name, val in self.items()
            if type(val) is not KVariable or val.name != name
        ]
        if not conjuncts:
            return KToken('true', 'Bool')

        return reduce(KLabel('_andBool_'), conjuncts)

    @property
    def is_identity(self) -> bool:
        return len(self.minimize()) == 0


def bottom_up_with_summary(f: Callable[[KInner, list[A]], tuple[KInner, A]], kinner: KInner) -> tuple[KInner, A]:
    """Traverse a term from the bottom moving upward, collecting information about it.

    Args:
        f: Function to apply at each AST node to transform it and collect summary.
        kinner: Term to apply this transformation to.

    Returns:
        A tuple of the transformed term and the summarized results.
    """
    stack: list = [kinner, [], []]
    while True:
        summaries = stack[-1]
        terms = stack[-2]
        term = stack[-3]
        idx = len(terms) - len(term.terms)
        if not idx:
            stack.pop()
            stack.pop()
            stack.pop()
            term, summary = f(term.let_terms(terms), summaries)
            if not stack:
                return term, summary
            stack[-1].append(summary)
            stack[-2].append(term)
        else:
            stack.append(term.terms[idx])
            stack.append([])
            stack.append([])


# TODO make method of KInner
def bottom_up(f: Callable[[KInner], KInner], kinner: KInner) -> KInner:
    """Transform a term from the bottom moving upward.

    Args:
        f: Function to apply to each node in the term.
        kinner: Original term to transform.

    Returns:
        The transformed term.
    """
    stack: list = [kinner, []]
    while True:
        terms = stack[-1]
        term = stack[-2]
        idx = len(terms) - len(term.terms)
        if not idx:
            stack.pop()
            stack.pop()
            term = f(term.let_terms(terms))
            if not stack:
                return term
            stack[-1].append(term)
        else:
            stack.append(term.terms[idx])
            stack.append([])


# TODO make method of KInner
def top_down(f: Callable[[KInner], KInner], kinner: KInner) -> KInner:
    """Transform a term from the top moving downward.

    Args:
        f: Function to apply to each node in the term.
        kinner: Original term to transform.

    Returns:
        The transformed term.
    """
    stack: list = [f(kinner), []]
    while True:
        terms = stack[-1]
        term = stack[-2]
        idx = len(terms) - len(term.terms)
        if not idx:
            stack.pop()
            stack.pop()
            term = term.let_terms(terms)
            if not stack:
                return term
            stack[-1].append(term)
        else:
            stack.append(f(term.terms[idx]))
            stack.append([])


# TODO: make method of KInner
def var_occurrences(term: KInner) -> dict[str, list[KVariable]]:
    """Collect the list of occurrences of each variable in a given term.

    Args:
        term: Term to collect variables from.

    Returns:
        A dictionary with variable names as keys and the list of all occurrences of the variable as values.
    """
    _var_occurrences: dict[str, list[KVariable]] = {}

    # TODO: should treat #Exists and #Forall specially.
    def _var_occurence(_term: KInner) -> None:
        if type(_term) is KVariable:
            if _term.name not in _var_occurrences:
                _var_occurrences[_term.name] = []
            _var_occurrences[_term.name].append(_term)

    collect(_var_occurence, term)
    return _var_occurrences


def keep_vars_sorted(occurrences: dict[str, list[KVariable]]) -> dict[str, KVariable]:
    """Keep the sort of variables from the occurrences dictionary."""
    occurrences_sorted: dict[str, KVariable] = {}
    for k, vs in occurrences.items():
        sort = None
        for v in vs:
            if v.sort is not None:
                if sort is None:
                    sort = v.sort
                elif sort != v.sort:
                    sort = None
                    break
        occurrences_sorted[k] = KVariable(k, sort)
    return occurrences_sorted


def collect(callback: Callable[[KInner], None], kinner: KInner) -> None:
    """Collect information about a given term traversing it top-down using a function with side effects.

    Args:
        callback: Function with the side effect of collecting desired information at each AST node.
        kinner: The term to traverse.
    """
    subterms = [kinner]
    while subterms:
        term = subterms.pop()
        subterms.extend(reversed(term.terms))
        callback(term)


def build_assoc(unit: KInner, label: str | KLabel, terms: Iterable[KInner]) -> KInner:
    """Build an associative list.

    Args:
        unit: The empty variant of the given list type.
        label: The associative list join operator.
        terms: List (potentially empty) of terms to join in an associative list.

    Returns:
        The list of terms joined using the supplied label, or the unit element in the case of no terms.
    """
    _label = label if type(label) is KLabel else KLabel(label)
    res: KInner | None = None
    for term in reversed(list(terms)):
        if term == unit:
            continue
        if not res:
            res = term
        else:
            res = _label(term, res)
    return res or unit


def build_cons(unit: KInner, label: str | KLabel, terms: Iterable[KInner]) -> KInner:
    """Build a cons list.

    Args:
        unit: The empty variant of the given list type.
        label: The associative list join operator.
        terms: List (potentially empty) of terms to join in an associative list.

    Returns:
        The list of terms joined using the supplied label, terminated with the unit element.
    """
    it = iter(terms)
    try:
        fst = next(it)
        return KApply(label, (fst, build_cons(unit, label, it)))
    except StopIteration:
        return unit


def flatten_label(label: str, kast: KInner) -> list[KInner]:
    """Given a cons list, return a flat Python list of the elements.

    Args:
        label: The cons operator.
        kast: The cons list to flatten.

    Returns:
        Items of cons list.
    """
    flattened_args = []
    rest_of_args = [kast]  # Rest of arguments in reversed order
    while rest_of_args:
        current_arg = rest_of_args.pop()
        if isinstance(current_arg, KApply) and current_arg.label.name == label:
            rest_of_args.extend(reversed(current_arg.args))
        else:
            flattened_args.append(current_arg)
    return flattened_args
