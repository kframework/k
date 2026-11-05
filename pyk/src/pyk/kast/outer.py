from __future__ import annotations

import json
import logging
import re
from abc import abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import InitVar  # noqa: TC003
from dataclasses import dataclass
from enum import Enum
from functools import cached_property, reduce
from itertools import pairwise, product
from typing import TYPE_CHECKING, final, overload

from ..utils import FrozenDict, POSet, filter_none, not_none, single, unique
from .att import EMPTY_ATT, Atts, Format, KAst, KAtt, WithKAtt
from .inner import (
    KApply,
    KAs,
    KInner,
    KLabel,
    KRewrite,
    KSequence,
    KSort,
    KToken,
    KVariable,
    Subst,
    bottom_up,
    bottom_up_with_summary,
    top_down,
)
from .kast import kast_term
from .prelude.k import K_ITEM, SORT_PARAM_SENTINEL, K
from .rewrite import indexed_rewrite

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from os import PathLike
    from typing import Any, Final, TypeVar

    S = TypeVar('S', bound='KSentence')
    RL = TypeVar('RL', bound='KRuleLike')

_LOGGER: Final = logging.getLogger(__name__)


_BOOL: Final = KSort('Bool')
_TRUE: Final = KToken('true', _BOOL)


class KOuter(KAst):
    """Represents K definitions in KAST format.

    Outer syntax is K specific datastructures, including modules, definitions, imports, user-syntax declarations, rules, contexts, and claims.
    """

    ...


class KProductionItem(KOuter):
    """Represents the elements used to declare components of productions in EBNF style."""

    _NODES: Final = {'KTerminal', 'KRegexTerminal', 'KNonTerminal'}

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KProductionItem:
        node = d['node']
        if node not in KProductionItem._NODES:
            raise ValueError(f'Invalid KProductionItem node: {node!r}')
        cls = globals()[node]
        return cls._from_dict(d)


@final
@dataclass(frozen=True)
class KRegexTerminal(KProductionItem):
    """Represents a regular-expression terminal in EBNF production, to be matched against input text."""

    regex: str

    def __init__(self, regex: str):
        object.__setattr__(self, 'regex', regex)

    @classmethod
    def _from_dict(cls: type[KRegexTerminal], d: Mapping[str, Any]) -> KRegexTerminal:
        return KRegexTerminal(regex=d['regex'])

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KRegexTerminal',
            'regex': self.regex,
        }

    def let(self, *, regex: str | None = None) -> KRegexTerminal:
        regex = regex if regex is not None else self.regex
        return KRegexTerminal(regex=regex)


@final
@dataclass(frozen=True)
class KNonTerminal(KProductionItem):
    """Represents a non-terminal of a given sort in EBNF productions, for defining arguments to to production."""

    sort: KSort
    name: str | None

    def __init__(self, sort: KSort, name: str | None = None):
        object.__setattr__(self, 'sort', sort)
        object.__setattr__(self, 'name', name)

    @classmethod
    def _from_dict(cls: type[KNonTerminal], d: Mapping[str, Any]) -> KNonTerminal:
        name = d['name'] if 'name' in d else None
        return KNonTerminal(sort=KSort.from_dict(d['sort']), name=name)

    def to_dict(self) -> dict[str, Any]:
        d = {'node': 'KNonTerminal', 'sort': self.sort.to_dict()}
        if self.name is not None:
            d['name'] = self.name
        return d

    def let(self, *, sort: KSort | None = None, name: str | None = None) -> KNonTerminal:
        sort = sort or self.sort
        name = name or self.name
        return KNonTerminal(sort=sort, name=name)


@final
@dataclass(frozen=True)
class KTerminal(KProductionItem):
    """Represents a string literal component of a production in EBNF grammar."""

    value: str

    def __init__(self, value: str):
        object.__setattr__(self, 'value', value)

    @classmethod
    def _from_dict(cls: type[KTerminal], d: Mapping[str, Any]) -> KTerminal:
        return KTerminal(value=d['value'])

    def to_dict(self) -> dict[str, Any]:
        return {'node': 'KTerminal', 'value': self.value}

    def let(self, *, value: str | None = None) -> KTerminal:
        value = value if value is not None else self.value
        return KTerminal(value=value)


class KSentence(KOuter, WithKAtt):
    """Represents an individual declaration in a K module."""

    _NODES: Final = {
        'KProduction',
        'KSyntaxSort',
        'KSortSynonym',
        'KSyntaxLexical',
        'KSyntaxAssociativity',
        'KSyntaxPriority',
        'KBubble',
        'KRule',
        'KClaim',
        'KContext',
    }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KSentence:
        node = d['node']
        if node not in KSentence._NODES:
            raise ValueError(f'Invalid KSentence node: {node!r}')
        cls = globals()[node]
        return cls._from_dict(d)

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID assigned to this sentence, or None."""
        return self.att.get(Atts.UNIQUE_ID)

    @property
    def source(self) -> str | None:
        """Return the source assigned to this sentence, or None."""
        if Atts.SOURCE in self.att and Atts.LOCATION in self.att:
            return f'{self.att[Atts.SOURCE]}:{self.att[Atts.LOCATION]}'
        return None

    @property
    def label(self) -> str:
        """Return a (hopefully) unique label associated with the given `KSentence`.

        :return: Unique label for the given sentence, either (in order):
          - User supplied `label` attribute (or supplied in rule label),or
          - Unique identifier computed and inserted by the frontend.
        """
        label = self.att.get(Atts.LABEL, self.unique_id)
        if label is None:
            raise ValueError(f'Found sentence without label or UNIQUE_ID: {self}')
        return label


@final
@dataclass(frozen=True)
class KProduction(KSentence):
    """Represents a production in K's EBNF grammar definitions, as a sequence of ProductionItem."""

    # TODO Order in Java implementation: klabel, params, sort, items, att
    sort: KSort
    items: tuple[KProductionItem, ...]
    params: tuple[KSort, ...]
    klabel: KLabel | None
    att: KAtt

    def __init__(
        self,
        sort: str | KSort,
        items: Iterable[KProductionItem] = (),
        params: Iterable[str | KSort] = (),
        klabel: str | KLabel | None = None,
        att: KAtt = EMPTY_ATT,
    ):
        if type(sort) is str:
            sort = KSort(sort)
        if type(klabel) is str:
            klabel = KLabel(klabel)

        params = tuple(KSort(param) if type(param) is str else param for param in params)

        object.__setattr__(self, 'sort', sort)
        object.__setattr__(self, 'items', tuple(items))
        object.__setattr__(self, 'params', params)
        object.__setattr__(self, 'klabel', klabel)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KProduction], d: Mapping[str, Any]) -> KProduction:
        return KProduction(
            sort=KSort.from_dict(d['sort']),
            items=(KProductionItem.from_dict(item) for item in d['productionItems']),
            params=(KSort.from_dict(param) for param in d['params']),
            klabel=KLabel.from_dict(d['klabel']) if d.get('klabel') else None,
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return filter_none(
            {
                'node': 'KProduction',
                'sort': self.sort.to_dict(),
                'productionItems': [item.to_dict() for item in self.items],
                'params': [param.to_dict() for param in self.params],
                'klabel': self.klabel.to_dict() if self.klabel else None,
                'att': self.att.to_dict(),
            }
        )

    def let(
        self,
        *,
        sort: str | KSort | None = None,
        items: Iterable[KProductionItem] | None = None,
        params: Iterable[str | KSort] | None = None,
        klabel: str | KLabel | None = None,
        att: KAtt | None = None,
    ) -> KProduction:
        sort = sort if sort is not None else self.sort
        items = items if items is not None else self.items
        params = params if params is not None else self.params
        klabel = klabel if klabel is not None else self.klabel  # TODO figure out a way to set klabel to None
        att = att if att is not None else self.att
        return KProduction(sort=sort, items=items, params=params, klabel=klabel, att=att)

    def let_att(self, att: KAtt) -> KProduction:
        return self.let(att=att)

    @cached_property
    def as_subsort(self) -> tuple[KSort, KSort] | None:
        """Return a pair `(supersort, subsort)` if `self` is a subsort production, and `None` otherwise."""
        if self.klabel:
            return None
        if len(self.items) != 1:
            return None
        item = self.items[0]
        if not isinstance(item, KNonTerminal):
            return None
        assert not self.klabel
        return self.sort, item.sort

    @cached_property
    def non_terminals(self) -> tuple[KNonTerminal, ...]:
        """Return the non-terminals of the production."""
        return tuple(item for item in self.items if isinstance(item, KNonTerminal))

    @property
    def argument_sorts(self) -> list[KSort]:
        """Return the sorts of the non-terminal positions of the productions."""
        return [knt.sort for knt in self.non_terminals]

    @cached_property
    def is_prefix(self) -> bool:
        """The production is of the form ``t* "(" (n ("," n)*)? ")"``.

        Here, ``t`` is a terminal other than ``"("``, ``","`` or ``")"``, and ``n`` a non-terminal.

        Example: ``syntax Int ::= "mul" "(" Int "," Int ")"``
        """

        def encode(item: KProductionItem) -> str:
            match item:
                case KTerminal(value):
                    if value in ['(', ',', ')']:
                        return value
                    return 't'
                case KNonTerminal():
                    return 'n'
                case KRegexTerminal():
                    return 'r'
                case _:
                    raise AssertionError()

        string = ''.join(encode(item) for item in self.items)
        pattern = r't*\((n(,n)*)?\)'
        return bool(re.fullmatch(pattern, string))

    @cached_property
    def is_record(self) -> bool:
        """The production is prefix with labelled nonterminals."""
        return bool(self.is_prefix and self.non_terminals and all(item.name is not None for item in self.non_terminals))

    @property
    def default_format(self) -> Format:
        format_str: str
        if self.is_record:
            tokens = []
            for i, item in enumerate(self.items):
                match item:
                    case KTerminal('('):
                        tokens.append(f'%{i + 1}...')
                    case KTerminal(_):
                        tokens.append(f'%{i + 1}')
                    case KNonTerminal(_, name):
                        assert name is not None
                        tokens.append(f'{name}:')
                        tokens.append(f'%{i + 1}')
                    case KRegexTerminal():
                        raise ValueError('Default format is not supported for productions with regex terminals')
                    case _:
                        raise AssertionError()
            format_str = ' '.join(tokens)
        else:
            format_str = ' '.join(f'%{i}' for i in range(1, len(self.items) + 1))

        return Format.parse(format_str)


@final
@dataclass(frozen=True)
class KSyntaxSort(KSentence):
    """Represents a sort declaration, potentially parametric."""

    sort: KSort
    params: tuple[KSort, ...]
    att: KAtt

    def __init__(self, sort: KSort, params: Iterable[str | KSort] = (), att: KAtt = EMPTY_ATT):
        params = tuple(KSort(param) if type(param) is str else param for param in params)
        object.__setattr__(self, 'sort', sort)
        object.__setattr__(self, 'params', params)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KSyntaxSort], d: Mapping[str, Any]) -> KSyntaxSort:
        return KSyntaxSort(
            sort=KSort.from_dict(d['sort']),
            params=(KSort.from_dict(param) for param in d['params']),
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KSyntaxSort',
            'sort': self.sort.to_dict(),
            'params': [param.to_dict() for param in self.params],
            'att': self.att.to_dict(),
        }

    def let(
        self,
        *,
        sort: KSort | None = None,
        params: Iterable[str | KSort] | None = None,
        att: KAtt | None = None,
    ) -> KSyntaxSort:
        sort = sort or self.sort
        params = params if params is not None else self.params
        att = att if att is not None else self.att
        return KSyntaxSort(sort=sort, params=params, att=att)

    def let_att(self, att: KAtt) -> KSyntaxSort:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KSortSynonym(KSentence):
    """Represents a sort synonym, allowing declaring a new name for a given sort."""

    new_sort: KSort
    old_sort: KSort
    att: KAtt

    def __init__(self, new_sort: KSort, old_sort: KSort, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'new_sort', new_sort)
        object.__setattr__(self, 'old_sort', old_sort)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KSortSynonym], d: Mapping[str, Any]) -> KSortSynonym:
        return KSortSynonym(
            new_sort=KSort.from_dict(d['newSort']),
            old_sort=KSort.from_dict(d['oldSort']),
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KSortSynonym',
            'newSort': self.new_sort.to_dict(),
            'oldSort': self.old_sort.to_dict(),
            'att': self.att.to_dict(),
        }

    def let(
        self, *, old_sort: KSort | None = None, new_sort: KSort | None = None, att: KAtt | None = None
    ) -> KSortSynonym:
        new_sort = new_sort or self.new_sort
        old_sort = old_sort or self.old_sort
        att = att if att is not None else self.att
        return KSortSynonym(new_sort=new_sort, old_sort=old_sort, att=att)

    def let_att(self, att: KAtt) -> KSortSynonym:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KSyntaxLexical(KSentence):
    """Represents a named piece of lexical syntax, definable as a regular expression."""

    name: str
    regex: str
    att: KAtt

    def __init__(self, name: str, regex: str, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'regex', regex)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KSyntaxLexical], d: Mapping[str, Any]) -> KSyntaxLexical:
        return KSyntaxLexical(
            name=d['name'],
            regex=d['regex'],
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KSyntaxLexcial',
            'name': self.name,
            'regex': self.regex,
            'att': self.att.to_dict(),
        }

    def let(self, *, name: str | None = None, regex: str | None = None, att: KAtt | None = None) -> KSyntaxLexical:
        name = name if name is not None else self.name
        regex = regex if regex is not None else self.regex
        att = att if att is not None else self.att
        return KSyntaxLexical(name=name, regex=regex, att=att)

    def let_att(self, att: KAtt) -> KSyntaxLexical:
        return self.let(att=att)


class KAssoc(Enum):
    LEFT = 'Left'
    RIGHT = 'Right'
    NON_ASSOC = 'NonAssoc'


@final
@dataclass(frozen=True)
class KSyntaxAssociativity(KSentence):
    """Represents a standalone declaration of operator associativity for tagged productions."""

    assoc: KAssoc
    tags: frozenset[str]
    att: KAtt

    def __init__(self, assoc: KAssoc, tags: Iterable[str] = frozenset(), att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'assoc', assoc)
        object.__setattr__(self, 'tags', frozenset(tags))
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KSyntaxAssociativity], d: Mapping[str, Any]) -> KSyntaxAssociativity:
        return KSyntaxAssociativity(
            assoc=KAssoc(d['assoc']),
            tags=d['tags'],
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KSyntaxAssociativity',
            'assoc': self.assoc.value,
            'tags': list(self.tags),
            'att': self.att.to_dict(),
        }

    def let(
        self, *, assoc: KAssoc | None = None, tags: Iterable[str] | None = None, att: KAtt | None = None
    ) -> KSyntaxAssociativity:
        assoc = assoc or self.assoc
        tags = tags if tags is not None else self.tags
        att = att if att is not None else self.att
        return KSyntaxAssociativity(assoc=assoc, tags=tags, att=att)

    def let_att(self, att: KAtt) -> KSyntaxAssociativity:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KSyntaxPriority(KSentence):
    """Represents a standalone declaration of syntax priorities, using productions tags."""

    priorities: tuple[frozenset[str], ...]
    att: KAtt

    def __init__(self, priorities: Iterable[Iterable[str]] = (), att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'priorities', tuple(frozenset(group) for group in priorities))
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KSyntaxPriority], d: Mapping[str, Any]) -> KSyntaxPriority:
        return KSyntaxPriority(
            priorities=d['priorities'],
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KSyntaxPriority',
            'priorities': [list(group) for group in self.priorities],
            'att': self.att.to_dict(),
        }

    def let(self, *, priorities: Iterable[Iterable[str]] | None = None, att: KAtt | None = None) -> KSyntaxPriority:
        priorities = priorities if priorities is not None else self.priorities
        att = att if att is not None else self.att
        return KSyntaxPriority(priorities=priorities, att=att)

    def let_att(self, att: KAtt) -> KSyntaxPriority:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KBubble(KSentence):
    """Represents an unparsed chunk of AST in user-defined syntax."""

    sentence_type: str
    contents: str
    att: KAtt

    def __init__(self, sentence_type: str, contents: str, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'sentence_type', sentence_type)
        object.__setattr__(self, 'contents', contents)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KBubble], d: Mapping[str, Any]) -> KBubble:
        return KBubble(
            sentence_type=d['sentenceType'],
            contents=d['contents'],
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KBubble',
            'sentenceType': self.sentence_type,
            'contents': self.contents,
            'att': self.att.to_dict(),
        }

    def let(self, *, sentence_type: str | None = None, contents: str | None = None, att: KAtt | None = None) -> KBubble:
        sentence_type = sentence_type if sentence_type is not None else self.sentence_type
        contents = contents if contents is not None else self.contents
        att = att if att is not None else self.att
        return KBubble(sentence_type=sentence_type, contents=contents, att=att)

    def let_att(self, att: KAtt) -> KBubble:
        return self.let(att=att)


class KRuleLike(KSentence):
    """Represents something with rule-like structure (with body, requires, and ensures clauses)."""

    body: KInner
    requires: KInner
    ensures: KInner

    @abstractmethod
    def let(
        self: RL,
        *,
        body: KInner | None = None,
        requires: KInner | None = None,
        ensures: KInner | None = None,
        att: KAtt | None = None,
    ) -> RL: ...


@final
@dataclass(frozen=True)
class KRule(KRuleLike):
    """Represents a K rule definition, typically a conditional rewrite/transition."""

    body: KInner
    requires: KInner
    ensures: KInner
    att: KAtt

    def __init__(self, body: KInner, requires: KInner = _TRUE, ensures: KInner = _TRUE, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'body', body)
        object.__setattr__(self, 'requires', requires)
        object.__setattr__(self, 'ensures', ensures)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KRule], d: Mapping[str, Any]) -> KRule:
        return KRule(
            body=KInner.from_dict(d['body']),
            requires=KInner.from_dict(d['requires']) if d.get('requires') else _TRUE,
            ensures=KInner.from_dict(d['ensures']) if d.get('ensures') else _TRUE,
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KRule',
            'body': self.body.to_dict(),
            'requires': self.requires.to_dict(),
            'ensures': self.ensures.to_dict(),
            'att': self.att.to_dict(),
        }

    def let(
        self,
        *,
        body: KInner | None = None,
        requires: KInner | None = None,
        ensures: KInner | None = None,
        att: KAtt | None = None,
    ) -> KRule:
        body = body if body is not None else self.body
        requires = requires if requires is not None else self.requires
        ensures = ensures if ensures is not None else self.ensures
        att = att if att is not None else self.att
        return KRule(body=body, requires=requires, ensures=ensures, att=att)

    def let_att(self, att: KAtt) -> KRule:
        return self.let(att=att)

    @property
    def priority(self) -> int:
        return self.att.get(Atts.PRIORITY, 200 if Atts.OWISE in self.att else 50)


@final
@dataclass(frozen=True)
class KClaim(KRuleLike):
    """Represents a K claim, typically a transition with pre/post-conditions."""

    body: KInner
    requires: KInner
    ensures: KInner
    att: KAtt

    def __init__(self, body: KInner, requires: KInner = _TRUE, ensures: KInner = _TRUE, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'body', body)
        object.__setattr__(self, 'requires', requires)
        object.__setattr__(self, 'ensures', ensures)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KClaim], d: Mapping[str, Any]) -> KClaim:
        return KClaim(
            body=KInner.from_dict(d['body']),
            requires=KInner.from_dict(d['requires']) if d.get('requires') else _TRUE,
            ensures=KInner.from_dict(d['ensures']) if d.get('ensures') else _TRUE,
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KClaim',
            'body': self.body.to_dict(),
            'requires': self.requires.to_dict(),
            'ensures': self.ensures.to_dict(),
            'att': self.att.to_dict(),
        }

    def let(
        self,
        *,
        body: KInner | None = None,
        requires: KInner | None = None,
        ensures: KInner | None = None,
        att: KAtt | None = None,
    ) -> KClaim:
        body = body if body is not None else self.body
        requires = requires if requires is not None else self.requires
        ensures = ensures if ensures is not None else self.ensures
        att = att if att is not None else self.att
        return KClaim(body=body, requires=requires, ensures=ensures, att=att)

    def let_att(self, att: KAtt) -> KClaim:
        return self.let(att=att)

    @property
    def is_circularity(self) -> bool:
        """Return whether this claim is a circularity (must be used coinductively to prove itself)."""
        return Atts.CIRCULARITY in self.att

    @property
    def is_trusted(self) -> bool:
        """Return whether this claim is trusted (does not need to be proven to be considered true)."""
        return Atts.TRUSTED in self.att

    @property
    def dependencies(self) -> list[str]:
        """Return the dependencies of this claim (list of other claims needed to help prove this one or speed up this ones proof)."""
        deps = self.att.get(Atts.DEPENDS)
        if deps is None:
            return []
        return [x.strip() for x in deps.split(',')]


@final
@dataclass(frozen=True)
class KContext(KSentence):
    """Represents a K evaluation context, used for isolating chunks of computation and focusing on them."""

    body: KInner
    requires: KInner
    att: KAtt

    def __init__(self, body: KInner, requires: KInner = _TRUE, att: KAtt = EMPTY_ATT):
        object.__setattr__(self, 'body', body)
        object.__setattr__(self, 'requires', requires)
        object.__setattr__(self, 'att', att)

    @classmethod
    def _from_dict(cls: type[KContext], d: Mapping[str, Any]) -> KContext:
        return KContext(
            body=KInner.from_dict(d['body']),
            requires=KInner.from_dict(d['requires']) if d.get('requires') else _TRUE,
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KContext',
            'body': self.body.to_dict(),
            'requires': self.requires.to_dict(),
            'att': self.att.to_dict(),
        }

    def let(self, *, body: KInner | None = None, requires: KInner | None = None, att: KAtt | None = None) -> KContext:
        body = body if body is not None else self.body
        requires = requires if requires is not None else self.requires
        att = att if att is not None else self.att
        return KContext(body=body, requires=requires, att=att)

    def let_att(self, att: KAtt) -> KContext:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KImport(KOuter):
    """Represents a K module import, used for inheriting all the sentences of the imported module into this one."""

    name: str
    public: bool

    def __init__(self, name: str, public: bool = True):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'public', public)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KImport:
        return KImport(name=d['name'], public=d['isPublic'])

    def to_dict(self) -> dict[str, Any]:
        return {'node': 'KImport', 'name': self.name, 'isPublic': self.public}

    def let(self, *, name: str | None = None, public: bool | None = None) -> KImport:
        name = name if name is not None else self.name
        public = public if public is not None else self.public
        return KImport(name=name, public=public)


@final
@dataclass(frozen=True)
class KFlatModule(KOuter, WithKAtt, Iterable[KSentence]):
    """Represents a K module, with a name, list of imports, and list of sentences."""

    name: str
    sentences: tuple[KSentence, ...]
    imports: tuple[KImport, ...]
    att: KAtt

    def __init__(
        self, name: str, sentences: Iterable[KSentence] = (), imports: Iterable[KImport] = (), att: KAtt = EMPTY_ATT
    ):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'sentences', tuple(sentences))
        object.__setattr__(self, 'imports', tuple(imports))
        object.__setattr__(self, 'att', att)

    def __iter__(self) -> Iterator[KSentence]:
        return iter(self.sentences)

    @cached_property
    def productions(self) -> tuple[KProduction, ...]:
        """Return all the `KProduction` sentences from this module."""
        return tuple(sentence for sentence in self if type(sentence) is KProduction)

    @cached_property
    def syntax_productions(self) -> tuple[KProduction, ...]:
        """Return all the `KProduction` sentences from this module that contain `KLabel` (are EBNF syntax declarations)."""
        return tuple(prod for prod in self.productions if prod.klabel)

    @cached_property
    def functions(self) -> tuple[KProduction, ...]:
        """Return all the `KProduction` sentences from this module that are function declarations."""
        return tuple(prod for prod in self.syntax_productions if self._is_function(prod))

    @cached_property
    def constructors(self) -> tuple[KProduction, ...]:
        """Return all the `KProduction` sentences from this module that are constructor declarations."""
        return tuple(prod for prod in self.syntax_productions if not self._is_function(prod))

    @cached_property
    def cell_collection_productions(self) -> tuple[KProduction, ...]:
        """Return all the `KProduction` sentences from this module that are cell collection declarations."""
        return tuple(prod for prod in self.syntax_productions if Atts.CELL_COLLECTION in prod.att)

    @staticmethod
    def _is_function(prod: KProduction) -> bool:
        def is_not_actually_function(label: str) -> bool:
            is_cell_map_constructor = label.endswith('CellMapItem') or label.endswith('CellMap_')
            is_builtin_data_constructor = label in {
                '_Set_',
                '_List_',
                '_Map_',
                '_RangeMap_',
                '.Set',
                '.List',
                '.Map',
                '.RangeMap',
                'SetItem',
                'ListItem',
                '_|->_',
                '_r|->_',
            }
            return is_cell_map_constructor or is_builtin_data_constructor

        return (Atts.FUNCTION in prod.att or Atts.FUNCTIONAL in prod.att) and not (
            prod.klabel and is_not_actually_function(prod.klabel.name)
        )

    @cached_property
    def syntax_sorts(self) -> tuple[KSyntaxSort, ...]:
        """Return all the `KSyntaxSort` sentences from this module."""
        return tuple(sentence for sentence in self if isinstance(sentence, KSyntaxSort))

    @cached_property
    def rules(self) -> tuple[KRule, ...]:
        """Return all the `KRule` declared in this module."""
        return tuple(sentence for sentence in self if type(sentence) is KRule)

    @cached_property
    def claims(self) -> tuple[KClaim, ...]:
        """Return all the `KClaim` declared in this module."""
        return tuple(sentence for sentence in self if type(sentence) is KClaim)

    @cached_property
    def sentence_by_unique_id(self) -> dict[str, KSentence]:
        return {sent.unique_id: sent for sent in self.sentences if sent.unique_id is not None}

    @overload
    def map_sentences(self, f: Callable[[S], S], *, of_type: type[S]) -> KFlatModule: ...

    @overload
    def map_sentences(self, f: Callable[[KSentence], KSentence], *, of_type: None = None) -> KFlatModule: ...

    # Uses overload instead of default argument as a workaround: https://github.com/python/mypy/issues/3737
    def map_sentences(self, f: Callable, *, of_type: Any = None) -> KFlatModule:
        if of_type is None:
            of_type = KSentence
        return self.let(sentences=tuple(f(sent) if isinstance(sent, of_type) else sent for sent in self.sentences))

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KFlatModule:
        return KFlatModule(
            name=d['name'],
            sentences=(KSentence.from_dict(sentence) for sentence in d['localSentences']),
            imports=(KImport.from_dict(imp) for imp in d['imports']),
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KFlatModule',
            'name': self.name,
            'localSentences': [sentence.to_dict() for sentence in self.sentences],
            'imports': [imp.to_dict() for imp in self.imports],
            'att': self.att.to_dict(),
        }

    def let(
        self,
        *,
        name: str | None = None,
        sentences: Iterable[KSentence] | None = None,
        imports: Iterable[KImport] | None = None,
        att: KAtt | None = None,
    ) -> KFlatModule:
        name = name if name is not None else self.name
        sentences = sentences if sentences is not None else self.sentences
        imports = imports if imports is not None else self.imports
        att = att if att is not None else self.att
        return KFlatModule(name=name, imports=imports, sentences=sentences, att=att)

    def let_att(self, att: KAtt) -> KFlatModule:
        return self.let(att=att)


@final
@dataclass(frozen=True)
class KFlatModuleList(KOuter):
    """Represents a list of K modules, as returned by the prover parser for example, with a given module called out as the main module."""

    main_module: str
    modules: tuple[KFlatModule, ...]

    def __init__(self, main_module: str, modules: Iterable[KFlatModule]):
        object.__setattr__(self, 'main_module', main_module)
        object.__setattr__(self, 'modules', tuple(modules))

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KFlatModuleList:
        return KFlatModuleList(main_module=d['mainModule'], modules=(KFlatModule.from_dict(kfm) for kfm in d['term']))

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KFlatModuleList',
            'mainModule': self.main_module,
            'term': [mod.to_dict() for mod in self.modules],
        }

    def let(self, *, main_module: str | None = None, modules: Iterable[KFlatModule] | None = None) -> KFlatModuleList:
        main_module = main_module if main_module is not None else self.main_module
        modules = modules if modules is not None else self.modules
        return KFlatModuleList(main_module=main_module, modules=modules)


@final
@dataclass(frozen=True)
class KRequire(KOuter):
    """Represents a K file import of another file."""

    require: str

    def __init__(self, require: str):
        object.__setattr__(self, 'require', require)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KRequire:
        return KRequire(require=d['require'])

    def to_dict(self) -> dict[str, Any]:
        return {'node': 'KRequire', 'require': self.require}

    def let(self, *, require: str | None = None) -> KRequire:
        require = require if require is not None else self.require
        return KRequire(require=require)


def _match_sort_params(
    parametric: KSort,
    actual: KSort,
    params: frozenset[KSort],
    subsorts_fn: Callable[[KSort], frozenset[KSort]] | None = None,
) -> dict[KSort, list[KSort]]:
    """Match ``parametric`` sort against ``actual``, collecting candidate bindings per sort param.

    Three matching strategies, mirroring Java ``AddSortInjections.match()``:

    1. Direct: ``parametric`` is itself a sort param — bind it to ``actual``.
    2. Structural: same constructor head — recurse on sub-params.
    3. Subsort-aware: iterate subsorts ``s ≤ actual`` with same head as ``parametric``,
       collecting additional candidates for LUB resolution.
    """
    if parametric in params:
        return {parametric: [actual]}
    if parametric.name == actual.name and len(parametric.params) == len(actual.params):
        result: dict[KSort, list[KSort]] = {}
        for p_sub, a_sub in zip(parametric.params, actual.params, strict=True):
            for k, vs in _match_sort_params(p_sub, a_sub, params, subsorts_fn).items():
                result.setdefault(k, []).extend(vs)
        return result
    if parametric.params and subsorts_fn is not None:
        result = {}
        for s in subsorts_fn(actual):
            if s.name == parametric.name and len(s.params) == len(parametric.params):
                for p_sub, a_sub in zip(parametric.params, s.params, strict=True):
                    for k, vs in _match_sort_params(p_sub, a_sub, params).items():
                        result.setdefault(k, []).extend(vs)
        return result
    return {}


@final
@dataclass(frozen=True)
class KDefinition(KOuter, WithKAtt, Iterable[KFlatModule]):
    """Represents an entire K definition, with file imports and modules in place, and a given module called out as main module."""

    main_module_name: str
    all_modules: tuple[KFlatModule, ...]
    requires: tuple[KRequire, ...]
    att: KAtt

    main_module: InitVar[KFlatModule]

    _init_config: dict[KSort, KInner]
    _empty_config: dict[KSort, KInner]

    def __init__(
        self,
        main_module_name: str,
        all_modules: Iterable[KFlatModule],
        requires: Iterable[KRequire] = (),
        att: KAtt = EMPTY_ATT,
    ):
        all_modules = tuple(all_modules)
        main_modules = [module for module in all_modules if module.name == main_module_name]

        if not main_modules:
            raise ValueError(f'Module not found: {main_module_name}')
        if len(main_modules) > 1:
            raise ValueError(f'Module is not unique: {main_module_name}')

        main_module = main_modules[0]

        object.__setattr__(self, 'main_module_name', main_module_name)
        object.__setattr__(self, 'all_modules', tuple(all_modules))
        object.__setattr__(self, 'requires', tuple(requires))
        object.__setattr__(self, 'att', att)
        object.__setattr__(self, 'main_module', main_module)
        object.__setattr__(self, '_init_config', {})
        object.__setattr__(self, '_empty_config', {})

    def __iter__(self) -> Iterator[KFlatModule]:
        return iter(self.all_modules)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> KDefinition:
        return KDefinition(
            main_module_name=d['mainModule'],
            all_modules=(KFlatModule.from_dict(module) for module in d['modules']),
            requires=(KRequire.from_dict(require) for require in d['requires']) if d.get('requires') else (),
            att=KAtt.from_dict(d['att']) if d.get('att') else EMPTY_ATT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'node': 'KDefinition',
            'mainModule': self.main_module_name,
            'modules': [module.to_dict() for module in self.all_modules],
            'requires': [require.to_dict() for require in self.requires],
            'att': self.att.to_dict(),
        }

    def let(
        self,
        *,
        main_module_name: str | None = None,
        all_modules: Iterable[KFlatModule] | None = None,
        requires: Iterable[KRequire] | None = None,
        att: KAtt | None = None,
    ) -> KDefinition:
        main_module_name = main_module_name if main_module_name is not None else self.main_module_name
        all_modules = all_modules if all_modules is not None else self.all_modules
        requires = requires if requires is not None else self.requires
        att = att if att is not None else self.att
        return KDefinition(main_module_name=main_module_name, all_modules=all_modules, requires=requires, att=att)

    def let_att(self, att: KAtt) -> KDefinition:
        return self.let(att=att)

    @cached_property
    def all_module_names(self) -> tuple[str, ...]:
        """Return the name of all modules in this `KDefinition`."""
        return tuple(module.name for module in self.all_modules)

    @cached_property
    def module_names(self) -> tuple[str, ...]:
        """Return the list of module names transitively imported by the main module of this definition."""
        module_names = [self.main_module_name]
        seen_modules = []
        while len(module_names) > 0:
            mname = module_names.pop(0)
            if mname not in seen_modules:
                seen_modules.append(mname)
                module_names.extend([i.name for i in self.all_modules_dict[mname].imports])
        return tuple(seen_modules)

    @cached_property
    def all_modules_dict(self) -> dict[str, KFlatModule]:
        """Returns a dictionary of all the modules (with names as keys) defined in this definition."""
        return {m.name: m for m in self.all_modules}

    @cached_property
    def modules(self) -> tuple[KFlatModule, ...]:
        """Returns the list of modules transitively imported by th emain module of this definition."""
        return tuple(self.all_modules_dict[mname] for mname in self.module_names)

    @cached_property
    def productions(self) -> tuple[KProduction, ...]:
        """Returns the `KProduction` transitively imported by the main module of this definition."""
        return tuple(prod for module in self.modules for prod in module.productions)

    @cached_property
    def syntax_productions(self) -> tuple[KProduction, ...]:
        """Returns the `KProduction` which are syntax declarations transitively imported by the main module of this definition."""
        return tuple(prod for module in self.modules for prod in module.syntax_productions)

    @cached_property
    def functions(self) -> tuple[KProduction, ...]:
        """Returns the `KProduction` which are function declarations transitively imported by the main module of this definition."""
        return tuple(func for module in self.modules for func in module.functions)

    @cached_property
    def function_labels(self) -> tuple[str, ...]:
        """Returns the label names of all the `KProduction` which are function symbols for all modules in this definition."""
        return tuple(not_none(func.klabel).name for func in self.functions)

    @cached_property
    def constructors(self) -> tuple[KProduction, ...]:
        """Returns the `KProduction` which are constructor declarations transitively imported by the main module of this definition."""
        return tuple(ctor for module in self.modules for ctor in module.constructors)

    @cached_property
    def cell_collection_productions(self) -> tuple[KProduction, ...]:
        """Returns the `KProduction` which are cell collection declarations transitively imported by the main module of this definition."""
        return tuple(prod for module in self.modules for prod in module.cell_collection_productions)

    @cached_property
    def cell_map_item_info(self) -> dict[str, tuple[str, KSort]]:
        """Map from cell label to (element-constructor label, cell-map sort).

        Derived from cell-collection productions that carry both ``ELEMENT`` and ``WRAP_ELEMENT`` attributes and whose element constructor is a known symbol.

        Example:
            syntax AccountCellMap [cellCollection, hook(MAP.Map)]
            syntax AccountCellMap ::= AccountCellMap AccountCellMap [assoc, avoid, cellCollection, comm, element(AccountCellMapItem), function, hook(MAP.concat), unit(.AccountCellMap), wrapElement(<account>)]
        """
        result: dict[str, tuple[str, KSort]] = {}
        for ccp in self.cell_collection_productions:
            if Atts.ELEMENT in ccp.att and Atts.WRAP_ELEMENT in ccp.att:
                cell_label = ccp.att[Atts.WRAP_ELEMENT]
                element_ctor = ccp.att[Atts.ELEMENT]
                if element_ctor in self.symbols:
                    result[cell_label] = (element_ctor, self.symbols[element_ctor].sort)
        return result

    @cached_property
    def rules(self) -> tuple[KRule, ...]:
        """Returns the `KRule` sentences transitively imported by the main module of this definition."""
        return tuple(rule for module in self.modules for rule in module.rules)

    @cached_property
    def alias_rules(self) -> tuple[KRule, ...]:
        """Returns the `KRule` sentences which are `alias` transitively imported by the main module of this definition."""
        return tuple(rule for rule in self.rules if Atts.ALIAS in rule.att)

    @cached_property
    def macro_rules(self) -> tuple[KRule, ...]:
        """Returns the `KRule` sentences which are `alias` or `macro` transitively imported by the main module of this definition."""
        return tuple(rule for rule in self.rules if Atts.MACRO in rule.att) + self.alias_rules

    @cached_property
    def semantic_rules(self) -> tuple[KRule, ...]:
        """Returns the `KRule` sentences which are topmost transitively imported by the main module of this definition."""

        def is_semantic(rule: KRule) -> bool:
            return (type(rule.body) is KApply and rule.body.label.name == '<generatedTop>') or (
                type(rule.body) is KRewrite
                and type(rule.body.lhs) is KApply
                and rule.body.lhs.label.name == '<generatedTop>'
            )

        return tuple(rule for rule in self.rules if is_semantic(rule))

    @cached_property
    def sentence_by_unique_id(self) -> dict[str, KSentence]:
        unique_id_map: dict[str, KSentence] = {}
        for module in self.all_modules:
            for unique_id, sent in module.sentence_by_unique_id.items():
                if unique_id in unique_id_map and sent != unique_id_map[unique_id]:
                    _LOGGER.debug(
                        f'Same UNIQUE_ID found for two different sentences: {(sent, unique_id_map[unique_id])}'
                    )
                else:
                    unique_id_map[unique_id] = sent
        return unique_id_map

    def production_for_cell_sort(self, sort: KSort) -> KProduction:
        """Return the production for a given cell-declaration syntax from the cell's declared sort."""
        # Typical cell production has 3 productions:
        #     syntax KCell ::= "project:KCell" "(" K ")" [function, projection]
        #     syntax KCell ::= "initKCell" "(" Map ")" [function, initializer, noThread]
        #     syntax KCell ::= "<k>" K "</k>" [cell, cellName(k), format(%1%i%n%2%d%n%3), maincell, org.kframework.definition.Production(syntax #RuleContent ::= #RuleBody [klabel(#ruleNoConditions), symbol])]
        # And it may have a 4th:
        #     syntax GeneratedCounterCell ::= "getGeneratedCounterCell" "(" GeneratedTopCell ")" [function]
        # We want the actual label one (3rd one in the list).
        if not sort.name.endswith('Cell'):
            raise ValueError(
                f'Method production_for_cell_sort only intended to be called on sorts ending in "Cell", not: {sort}'
            )
        try:
            return single(prod for prod in self.productions if prod.sort == sort and Atts.CELL in prod.att)
        except ValueError as err:
            raise ValueError(f'Expected a single cell production for sort {sort}') from err

    def module(self, name: str) -> KFlatModule:
        """Return the module associated with a given name."""
        return self.all_modules_dict[name]

    @cached_property
    def subsort_table(self) -> FrozenDict[KSort, frozenset[KSort]]:
        """Return a mapping from sorts to all their proper subsorts."""
        poset = POSet(subsort for prod in self.productions if (subsort := prod.as_subsort) is not None)
        return poset.image

    def subsorts(self, sort: KSort) -> frozenset[KSort]:
        """Return all subsorts of a given `KSort` by inspecting the definition."""
        return self.subsort_table.get(sort, frozenset())

    @cached_property
    def brackets(self) -> FrozenDict[KSort, KProduction]:
        brackets: dict[KSort, KProduction] = {}
        for prod in self.productions:
            if Atts.BRACKET in prod.att:
                assert not prod.klabel
                sort = prod.sort
                if sort in brackets:
                    raise ValueError(f'Multiple bracket productions for sort: {sort.name}')
                brackets[sort] = prod
        return FrozenDict(brackets)

    @cached_property
    def symbols(self) -> FrozenDict[str, KProduction]:
        symbols: dict[str, KProduction] = {}
        for prod in self.productions:
            if not prod.klabel:
                continue
            symbol = prod.klabel.name
            if symbol in symbols:  # Check if duplicate
                other = symbols[symbol]
                if prod.let(att=prod.att.drop_source()) != other.let(att=prod.att.drop_source()):
                    prods = [other, prod]
                    raise AssertionError(f'Found multiple productions for {symbol}: {prods}')
                continue
            symbols[symbol] = prod
        return FrozenDict(symbols)

    @cached_property
    def syntax_symbols(self) -> FrozenDict[str, KProduction]:
        brackets: dict[str, KProduction] = {
            prod.att[Atts.BRACKET_LABEL]['name']: prod for _, prod in self.brackets.items()
        }
        return FrozenDict({**self.symbols, **brackets})

    @cached_property
    def overloads(self) -> FrozenDict[str, frozenset[str]]:
        """Return a mapping from symbols to the sets of symbols that overload them."""

        def lt(overloader: KProduction, overloaded: KProduction) -> bool:
            assert overloader.klabel
            assert overloaded.klabel
            assert overloader.klabel.name != overloaded.klabel.name
            assert Atts.OVERLOAD in overloader.att
            assert Atts.OVERLOAD in overloaded.att
            assert overloader.att[Atts.OVERLOAD] == overloaded.att[Atts.OVERLOAD]
            overloader_sorts = [overloader.sort] + overloader.argument_sorts
            overloaded_sorts = [overloaded.sort] + overloaded.argument_sorts
            if len(overloader_sorts) != len(overloaded_sorts):
                return False
            less = False
            for overloader_sort, overloaded_sort in zip(overloader_sorts, overloaded_sorts, strict=True):
                if overloader_sort == overloaded_sort:
                    continue
                if overloader_sort in self.subsorts(overloaded_sort):
                    less = True
                    continue
                return False
            return less

        symbols_by_overload: dict[str, list[str]] = {}
        for symbol in self.symbols:
            prod = self.symbols[symbol]
            if Atts.OVERLOAD in prod.att:
                symbols_by_overload.setdefault(prod.att[Atts.OVERLOAD], []).append(symbol)

        overloads: dict[str, list[str]] = {}
        for _, symbols in symbols_by_overload.items():
            for overloader in symbols:
                for overloaded in symbols:
                    if overloader == overloaded:
                        continue
                    if lt(overloader=self.symbols[overloader], overloaded=self.symbols[overloaded]):
                        # Index by overloaded symbol, this way it is easy to look them up
                        overloads.setdefault(overloaded, []).append(overloader)
        return FrozenDict({key: frozenset(values) for key, values in overloads.items()})

    @cached_property
    def priorities(self) -> FrozenDict[str, frozenset[str]]:
        """Return a mapping from symbols to the sets of symbols with lower priority."""
        syntax_priorities = (
            sent for module in self.modules for sent in module.sentences if isinstance(sent, KSyntaxPriority)
        )
        relation = tuple(
            pair
            for syntax_priority in syntax_priorities
            for highers, lowers in pairwise(syntax_priority.priorities)
            for pair in product(highers, lowers)
        )
        return POSet(relation).image

    @cached_property
    def left_assocs(self) -> FrozenDict[str, frozenset[str]]:
        return FrozenDict({key: frozenset(value) for key, value in self._assocs(KAssoc.LEFT).items()})

    @cached_property
    def right_assocs(self) -> FrozenDict[str, frozenset[str]]:
        return FrozenDict({key: frozenset(value) for key, value in self._assocs(KAssoc.RIGHT).items()})

    def _assocs(self, assoc: KAssoc) -> dict[str, set[str]]:
        sents = (
            sent
            for module in self.modules
            for sent in module.sentences
            if isinstance(sent, KSyntaxAssociativity) and sent.assoc in (assoc, KAssoc.NON_ASSOC)
        )
        pairs = (pair for sent in sents for pair in product(sent.tags, sent.tags))

        def insert(dct: dict[str, set[str]], *, key: str, value: str) -> dict[str, set[str]]:
            dct.setdefault(key, set()).add(value)
            return dct

        return reduce(lambda res, pair: insert(res, key=pair[0], value=pair[1]), pairs, {})

    def sort(self, kast: KInner) -> KSort | None:
        """Compute the sort of a given term using best-effort simple sorting algorithm, returns `None` on algorithm failure."""
        match kast:
            case KToken(_, sort) | KVariable(_, sort):
                return sort
            case KAs(alias=KVariable(sort=sort)):
                return sort
            case KRewrite(lhs, rhs):
                lhs_sort = self.sort(lhs)
                rhs_sort = self.sort(rhs)
                if lhs_sort and rhs_sort:
                    return self.least_common_supersort(lhs_sort, rhs_sort)
                return None
            case KSequence(_):
                return KSort('K')
            case KApply(label, _):
                try:
                    sort, _ = self.resolve_sorts(label)
                    return sort
                except (KeyError, ValueError):
                    return None
            case _:
                return None

    def sort_strict(self, kast: KInner) -> KSort:
        """Compute the sort of a given term using best-effort simple sorting algorithm, dies on algorithm failure."""
        sort = self.sort(kast)
        if sort is None:
            raise ValueError(f'Could not determine sort of term: {kast}')
        return sort

    def resolve_sorts(self, label: KLabel) -> tuple[KSort, tuple[KSort, ...]]:
        """Compute the result and argument sorts for a given production based on a `KLabel`."""
        prod = self.symbols[label.name]
        sorts = dict(zip(prod.params, label.params, strict=True))

        def resolve(sort: KSort) -> KSort:
            # Direct match: sort IS one of the sort parameters.
            if sort in sorts:
                return sorts[sort]
            # Recursive substitution: sort params may appear nested (e.g. MInt{Width} → MInt{8}).
            if sort.params:
                return KSort(sort.name, tuple(resolve(p) for p in sort.params))
            return sort

        return resolve(prod.sort), tuple(resolve(sort) for sort in prod.argument_sorts)

    def least_common_supersort(self, sort1: KSort, sort2: KSort) -> KSort | None:
        """Compute the lowest-upper-bound of two sorts in the sort lattice using very simple approach, returning `None` on failure (not necessarily meaning there isn't a lub)."""
        if sort1 == sort2:
            return sort1
        if sort1 in self.subsorts(sort2):
            return sort2
        if sort2 in self.subsorts(sort1):
            return sort1
        # Computing least common supersort is not currently supported if sort1 is not a subsort of sort2 or
        # vice versa. In that case there may be more than one LCS.
        return None

    def least_upper_bound(self, sorts: Iterable[KSort]) -> KSort | None:
        """Compute the least upper bound of a set of sorts in the subsort lattice.

        Returns the unique minimal common supersort, or `None` when none exists or the bound is
        ambiguous (several incomparable minimal upper bounds).  Unlike `least_common_supersort`,
        this examines the whole lattice rather than only the pairwise subsort relation, so it is
        order-independent and resolves siblings that share a common supersort (e.g. the LUB of
        `Int` and `Float` is `Number` when both are subsorts of `Number`).  Mirrors the set-based
        `AddSortInjections.lub` in the Java frontend.
        """
        sort_set = set(sorts)
        if not sort_set:
            return None
        if len(sort_set) == 1:
            return single(sort_set)

        def is_supersort(upper: KSort, lower: KSort) -> bool:
            return upper == lower or lower in self.subsorts(upper)

        # Every proper supersort of some sort appears as a key in the subsort table; the sorts
        # themselves are included to cover a candidate that is already an upper bound of the rest.
        universe = set(self.subsort_table.keys()) | sort_set
        upper_bounds = {u for u in universe if all(is_supersort(u, s) for s in sort_set)}
        minimal = {u for u in upper_bounds if not any(o != u and is_supersort(u, o) for o in upper_bounds)}
        if len(minimal) == 1:
            return single(minimal)
        return None

    def greatest_common_subsort(self, sort1: KSort, sort2: KSort) -> KSort | None:
        """Compute the greatest-lower-bound of two sorts in the sort lattice using very simple approach, returning `None` on failure (not necessarily meaning there isn't a glb)."""
        if sort1 == sort2:
            return sort1
        if sort1 in self.subsorts(sort2):
            return sort1
        if sort2 in self.subsorts(sort1):
            return sort2
        # Computing greatest common subsort is not currently supported if sort1 is not a subsort of sort2 or
        # vice versa. In that case there may be more than one GCS.
        return None

    # Sorts like Int cannot be injected directly into sort K so they are embedded in a KSequence.
    def add_ksequence_under_k_productions(self, kast: KInner) -> KInner:
        """Inject a `KSequence` under the given term if it's a subsort of `K` and is being used somewhere that sort `K` is expected (determined by inspecting the definition)."""

        def _add_ksequence_under_k_productions(_kast: KInner) -> KInner:
            if type(_kast) is not KApply:
                return _kast

            prod = self.symbols[_kast.label.name]
            return KApply(
                _kast.label,
                [
                    KSequence(arg) if sort.name == 'K' and not self.sort(arg) == KSort('K') else arg
                    for arg, sort in zip(_kast.args, prod.argument_sorts, strict=True)
                ],
            )

        return top_down(_add_ksequence_under_k_productions, kast)

    def sort_vars(self, kast: KInner, sort: KSort | None = None) -> KInner:
        """Return the original term with all the variables having the sorts added or specialized, failing if recieving conflicting sorts for a given variable."""
        ml_quantifiers = {'#Exists', '#Forall'}

        if type(kast) is KVariable and kast.sort is None and sort is not None:
            return kast.let(sort=sort)

        def get_quantifier_variable(q: KApply) -> KVariable:
            if q.arity != 2:
                raise ValueError(f'Expected a quantifier to have 2 children, got {q.arity}.')
            var = q.args[0]
            if not isinstance(var, KVariable):
                raise ValueError(f"Expected a quantifier's first child to be a variable, got {type(var)}.")
            return var

        def merge_variables(
            term: KInner, occurrences_list: list[dict[str, list[KVariable]]]
        ) -> dict[str, list[KVariable]]:
            result: dict[str, list[KVariable]] = defaultdict(list)
            for occurrences in occurrences_list:
                assert isinstance(occurrences, dict), type(occurrences)
                for key, value in occurrences.items():
                    result[key] += value
            if isinstance(term, KVariable):
                result[term.name].append(term)
            elif isinstance(term, KApply):
                if term.label.name in ml_quantifiers:
                    var = get_quantifier_variable(term)
                    result[var.name].append(var)
            return result

        def add_var_to_subst(vname: str, vars: list[KVariable], subst: dict[str, KVariable]) -> None:
            vsorts = list(unique(v.sort for v in vars if v.sort is not None))
            if len(vsorts) > 0:
                vsort = vsorts[0]
                for s in vsorts[1:]:
                    _vsort = self.greatest_common_subsort(vsort, s)
                    if _vsort is None:
                        raise ValueError(f'Cannot compute greatest common subsort of {vname}: {(vsort, s)}')
                    vsort = _vsort
                subst[vname] = KVariable(vname, sort=vsort)

        def transform(
            term: KInner, child_variables: list[dict[str, list[KVariable]]]
        ) -> tuple[KInner, dict[str, list[KVariable]]]:
            occurrences = merge_variables(term, child_variables)

            if isinstance(term, KApply):
                if term.label.name in ml_quantifiers:
                    var = get_quantifier_variable(term)
                    subst: dict[str, KVariable] = {}
                    add_var_to_subst(var.name, occurrences[var.name], subst)
                    del occurrences[var.name]
                    return (Subst(subst)(term), occurrences)
                else:
                    prod = self.symbols[term.label.name]
                    if len(prod.params) == 0:
                        for t, a in zip(prod.argument_sorts, term.args, strict=True):
                            if type(a) is KVariable:
                                occurrences[a.name].append(a.let_sort(t))
            elif isinstance(term, KSequence):
                for i, item in enumerate(term.items):
                    if isinstance(item, KVariable):
                        if item.sort is not None:
                            occurrences[item.name].append(item)
                        elif i == term.arity - 1:
                            occurrences[item.name].append(item.let_sort(K))
                        else:
                            occurrences[item.name].append(item.let_sort(K_ITEM))
            return (term, occurrences)

        (new_term, var_occurrences) = bottom_up_with_summary(transform, kast)

        subst: dict[str, KVariable] = {}
        for vname, occurrences in var_occurrences.items():
            add_var_to_subst(vname, occurrences, subst)

        return Subst(subst)(new_term)

    # Best-effort addition of sort parameters to klabels
    def add_sort_params(self, kast: KInner, sort: KSort | None = None) -> KInner:
        """Return ``kast`` with missing sort parameters filled in on every parametric ``KLabel``, best effort.

        The frontend often leaves the sort parameters off a parametric ``KLabel``.  This fills
        them with a single recursive sweep that threads an *expected* sort downwards — so a
        parametric **return** sort is taken from its context — and resolves the remaining
        parameters from the argument sorts coming back up, mirroring ``AddSortInjections`` in the
        Java frontend.

        ``sort`` is the expected sort of the whole term (e.g. ``GeneratedTopCell`` for a rule
        body).  When omitted, a fresh sort variable is used at the top, so the algorithm still
        runs but a parametric return sort that cannot be pinned from context becomes a fresh
        ``#SortParam{Qn}`` sort variable.

        Each parameter is either *argument-bound* (occurs in some argument sort, resolved
        bottom-up) or *return-only* (resolved top-down from the expected sort).  ``#SortParam``
        sentinels act as low-priority placeholders, so a real sort always wins when one is
        available.  The implementation is one interleaved sweep (``_go``); a future split into
        explicit passes can reuse the same per-node logic.

        It is asserted that every parametric return sort lives on the "spine" of the term: a
        return-only parameter is only allowed to stay free when its expected sort is itself free
        — a concrete expected sort it cannot satisfy means the term is ill-formed.
        """
        counter = [0]

        def _fresh() -> KSort:
            param = KSort(SORT_PARAM_SENTINEL.name, (KSort(f'Q{counter[0]}'),))
            counter[0] += 1
            return param

        def _is_sentinel(s: KSort | None) -> bool:
            return s is not None and s.name == SORT_PARAM_SENTINEL.name

        def _subst_sort(subst: dict[KSort, KSort], s: KSort) -> KSort:
            if s in subst:
                return subst[s]
            if s.params:
                return KSort(s.name, tuple(_subst_sort(subst, p) for p in s.params))
            return s

        def _lub(candidates: list[KSort]) -> KSort | None:
            # Sentinels are placeholders; a real sort always wins (as Java's lub filters out
            # #SortParam).  Only when every candidate is a sentinel do we keep one.
            real = [c for c in candidates if not _is_sentinel(c)]
            if real:
                return self.least_upper_bound(real)
            return candidates[0] if candidates else None

        def _go(term: KInner, expected: KSort) -> KInner:
            if isinstance(term, KRewrite):
                return KRewrite(_go(term.lhs, expected), _go(term.rhs, expected))
            if isinstance(term, KAs):
                return KAs(_go(term.pattern, expected), _go(term.alias, expected))
            if isinstance(term, KSequence):
                return KSequence([_go(item, SORT_PARAM_SENTINEL) for item in term.items])
            if not isinstance(term, KApply):
                return term

            prod = self.symbols.get(term.label.name)
            if prod is None:
                return term

            # Already-applied or non-parametric: thread the expected sort into the children using
            # the known bindings, then recurse.
            if len(prod.params) == 0 or len(term.label.params) == len(prod.params):
                subst = dict(zip(prod.params, term.label.params, strict=True)) if prod.params else {}
                child_expected = [_subst_sort(subst, asort) for asort in prod.argument_sorts]
                return term.let(args=[_go(arg, e) for arg, e in zip(term.args, child_expected, strict=True)])

            params = list(prod.params)
            param_set = frozenset(params)

            # Mirror Java's `fresh`: the parameter that IS the whole result sort takes the
            # expected sort (so it propagates into the children, sharing one sort variable down
            # the spine); the rest take a bare sentinel placeholder.  Used to type the children.
            fresh_subst = {p: (expected if p == prod.sort else SORT_PARAM_SENTINEL) for p in params}
            child_expected = [_subst_sort(fresh_subst, asort) for asort in prod.argument_sorts]
            new_args = [_go(arg, e) for arg, e in zip(term.args, child_expected, strict=True)]
            child_sorts = [self.sort(arg) for arg in new_args]

            # Bottom-up: argument-bound parameters, from the actual child sorts.
            candidates: dict[KSort, list[KSort]] = {}
            for psort, asort in zip(prod.argument_sorts, child_sorts, strict=True):
                if asort is None or _is_sentinel(asort):
                    continue
                for k, vs in _match_sort_params(psort, asort, param_set, self.subsorts).items():
                    candidates.setdefault(k, []).extend(vs)

            # Top-down: return-only parameters, from the expected sort (only when it is concrete).
            return_only = frozenset(
                p
                for p in params
                if prod.sort.contains(p) and not any(asort.contains(p) for asort in prod.argument_sorts)
            )
            if return_only and not _is_sentinel(expected):
                for k, vs in _match_sort_params(prod.sort, expected, return_only).items():
                    candidates.setdefault(k, []).extend(vs)

            bindings: dict[KSort, KSort] = {}
            unsortable: list[KSort] = []
            for p in params:
                value = _lub(candidates.get(p, []) + [fresh_subst[p]])
                if value is None:
                    _LOGGER.warning(f'Failed to add sort parameter, conflicting sorts for sort parameter: {(prod, p)}')
                    return term.let(args=new_args)
                if not _is_sentinel(value) or value.params:
                    # A concrete sort, or an already-named sort variable propagated from the
                    # expected sort (e.g. one shared down the spine) — keep it as is.
                    bindings[p] = value
                elif any(asort.contains(p) for asort in prod.argument_sorts):
                    # Bare sentinel for an argument-bound parameter: the argument was unsortable.
                    unsortable.append(p)
                else:
                    # Bare sentinel for a return-only or phantom parameter: a fresh, free sort
                    # variable.  A return sort is only allowed to stay free on the spine — i.e.
                    # when its own expected sort is itself free.
                    assert not prod.sort.contains(p) or _is_sentinel(expected), (
                        f'parametric return sort {p.name} of {term.label.name!r} occurs off the spine, '
                        f'in a position expecting concrete sort {expected.name}'
                    )
                    bindings[p] = _fresh()

            if unsortable:
                _LOGGER.warning(
                    f'Failed to add sort parameter, unable to determine sort for argument: {(prod, unsortable)}'
                )
                return term.let(args=new_args)

            label = KLabel(term.label.name, [bindings[p] for p in params])
            return term.let(label=label, args=new_args)

        return _go(kast, sort if sort is not None else _fresh())

    def add_cell_map_items(self, kast: KInner) -> KInner:
        """Wrap cell-map items in the syntactical wrapper that the frontend generates for them.

        See :func:`KDefinition.remove_cell_map_items`.

        Note:
            Wrapping is correct only when the parent production expects the cell MAP sort (e.g. ``EntryCellMap``), not when it expects the individual cell element sort (e.g. ``EntryCell``).

        Example:
            ``EntryCellMapKey(<entry>(...))``: takes ``EntryCell``, ``<entry>`` must NOT be wrapped
            ``_EntryCellMap_(<entry>(...), ...)``: expects ``EntryCellMap``, wrapping is needed
        """

        def _wrap_elements(_k: KInner) -> KInner:
            if not isinstance(_k, KApply) or _k.label.name not in self.symbols:
                return _k
            arg_sorts = self.symbols[_k.label.name].argument_sorts
            if not any(isinstance(arg, KApply) and arg.label.name in self.cell_map_item_info for arg in _k.args):
                return _k
            new_args: list[KInner] = []
            for arg_sort, arg in zip(arg_sorts, _k.args, strict=True):
                new_arg = arg
                if isinstance(arg, KApply):
                    if arg.label.name in self.cell_map_item_info:
                        element_ctor, element_ctor_sort = self.cell_map_item_info[arg.label.name]
                        if arg_sort == element_ctor_sort:
                            new_arg = KApply(element_ctor, [arg.args[0], arg])
                new_args.append(new_arg)
            return _k.let(args=new_args)

        # To ensure we don't get duplicate wrappers.
        _kast = self.remove_cell_map_items(kast)
        return bottom_up(_wrap_elements, _kast)

    def remove_cell_map_items(self, kast: KInner) -> KInner:
        """Remove cell-map syntactical wrapper items that the frontend generates (see `KDefinition.add_cell_map_items`)."""
        cell_wrappers = {ctor: label for label, (ctor, _) in self.cell_map_item_info.items()}

        def _unwrap_elements(_k: KInner) -> KInner:
            if (
                type(_k) is KApply
                and _k.label.name in cell_wrappers
                and len(_k.args) == 2
                and type(_k.args[1]) is KApply
                and _k.args[1].label.name == cell_wrappers[_k.label.name]
            ):
                return _k.args[1]
            return _k

        return bottom_up(_unwrap_elements, kast)

    def empty_config(self, sort: KSort) -> KInner:
        """Given a cell-sort, compute an "empty" configuration for it (all the constructor structure of the configuration in place, but variables in cell positions)."""
        if sort not in self._empty_config:
            self._empty_config[sort] = self._compute_empty_config(sort)
        return self._empty_config[sort]

    def _compute_empty_config(self, sort: KSort) -> KInner:
        def _kdefinition_empty_config(_sort: KSort) -> KApply:
            cell_prod = self.production_for_cell_sort(_sort)
            cell_klabel = cell_prod.klabel
            assert cell_klabel is not None
            production = self.symbols[cell_klabel.name]
            args: list[KInner] = []
            num_nonterminals = 0
            num_freshvars = 0
            for p_item in production.items:
                if type(p_item) is KNonTerminal:
                    num_nonterminals += 1
                    if p_item.sort.name.endswith('Cell'):
                        args.append(_kdefinition_empty_config(p_item.sort))
                    else:
                        num_freshvars += 1
                        args.append(KVariable(_sort.name[0:-4].upper() + '_CELL'))
            if num_nonterminals > 1 and num_freshvars > 0:
                raise ValueError(f'Found mixed cell and non-cell arguments to cell constructor for: {sort}')
            return KApply(cell_klabel, args)

        return _kdefinition_empty_config(sort)

    def instantiate_cell_vars(self, term: KInner) -> KInner:
        """Given a partially-complete configuration, find positions where there could be more cell structure but instead there are variables and instantiate more cell structure."""

        def _cell_vars_to_labels(_kast: KInner) -> KInner:
            if type(_kast) is KApply and _kast.is_cell:
                production = self.symbols[_kast.label.name]
                production_arity = [item.sort for item in production.non_terminals]
                new_args = []
                for sort, arg in zip(production_arity, _kast.args, strict=True):
                    if sort.name.endswith('Cell') and type(arg) is KVariable:
                        new_args.append(self.empty_config(sort))
                    else:
                        new_args.append(arg)
                return KApply(_kast.label, new_args)
            return _kast

        return bottom_up(_cell_vars_to_labels, term)

    def init_config(self, sort: KSort) -> KInner:
        """Return an initialized configuration as the user declares it in the semantics, complete with configuration variables in place."""
        if sort not in self._init_config:
            self._init_config[sort] = self._compute_init_config(sort)
        return self._init_config[sort]

    def _compute_init_config(self, sort: KSort) -> KInner:
        config_var_map = KVariable('__###CONFIG_VAR_MAP###__')

        def _remove_config_var_lookups(_kast: KInner) -> KInner:
            if type(_kast) is KApply and _kast.label.name.startswith('project:') and len(_kast.args) == 1:
                _term = _kast.args[0]
                if type(_term) is KApply and _term.label == KLabel('Map:lookup') and _term.args[0] == config_var_map:
                    _token_var = _term.args[1]
                    if type(_token_var) is KToken and _token_var.sort == KSort('KConfigVar'):
                        return KVariable(_token_var.token)
            return _kast

        init_prods = (prod for prod in self.syntax_productions if Atts.INITIALIZER in prod.att)
        try:
            init_prod = single(prod for prod in init_prods if prod.sort == sort)
        except ValueError as err:
            raise ValueError(f'Did not find unique initializer for sort: {sort}') from err

        prod_klabel = init_prod.klabel
        assert prod_klabel is not None
        arg_sorts = [nt.sort for nt in init_prod.items if type(nt) is KNonTerminal]
        init_config: KInner
        if len(arg_sorts) == 0:
            init_config = KApply(prod_klabel)
        elif len(arg_sorts) == 1 and arg_sorts[0] == KSort('Map'):
            init_config = KApply(prod_klabel, [config_var_map])
        else:
            raise ValueError(f'Cannot handle initializer for label: {prod_klabel}')

        init_rewrites = [
            rule.body for rule in self.rules if Atts.INITIALIZER in rule.att and type(rule.body) is KRewrite
        ]
        init_config = indexed_rewrite(init_config, init_rewrites)
        init_config = top_down(_remove_config_var_lookups, init_config)

        return init_config


def read_kast_definition(path: str | PathLike) -> KDefinition:
    """Read a `KDefinition` from disk, failing if it's not actually a `KDefinition`."""
    with open(path) as f:
        _LOGGER.info(f'Loading JSON definition: {path}')
        json_defn = json.load(f)
        _LOGGER.info(f'Converting JSON definition to Kast: {path}')
        return KDefinition.from_dict(kast_term(json_defn))
