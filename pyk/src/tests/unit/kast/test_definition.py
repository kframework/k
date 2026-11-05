from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from pyk.kast.att import Atts, KAtt
from pyk.kast.inner import KApply, KAs, KLabel, KSequence, KSort, KToken, KVariable
from pyk.kast.outer import (
    KDefinition,
    KFlatModule,
    KNonTerminal,
    KProduction,
    KTerminal,
    _match_sort_params,
)
from pyk.kast.prelude.k import GENERATED_TOP_CELL

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Final

    from pyk.kast.inner import KInner


# ---------------------------------------------------------------------------
# Minimal test definition
#
# bar:    syntax N       ::= bar(N)           -- result sort is the param directly
# foo:    syntax MInt{N} ::= foo(MInt{N})     -- result/arg sorts nest the param
# #Equals: syntax S2     ::= #Equals{S1,S2}(S1, S1)  -- ML pred, result sort context-dependent
# #Ceil:  syntax S2      ::= #Ceil{S1,S2}(S1)         -- ML pred, S2 is the free result sort
# #And:   syntax {S} S   ::= #And{S}(S, S)            -- homogeneous ML connective (S arg-bound)
# pair:   syntax Pair{S1,S2} ::= pair(S1)     -- user label; S2 is return-only
#
# Subsorts:
#   syntax Int    ::= MInt{Int}  -- MInt{Int} <: Int (enables subsort-aware matching)
#   syntax Number ::= Int        -- Int <: Number
#   syntax Number ::= Float      -- Float <: Number  (Int, Float incomparable; LUB is Number)
#
# Cell map fragment:
#   AccountCellMap ::= AccountCellMap AccountCellMap  [cellCollection, element(AccountCellMapItem), wrapElement(<account>)]
#   AccountCellMap ::= AccountCellMapItem(Int, AccountCell)
#   AccountCell    ::= <account>(Int, Int)
#   AccountCell    ::= getEntry(AccountCell)           -- takes element sort, NOT map sort
# ---------------------------------------------------------------------------

INT: Final = KSort('Int')
BOOL: Final = KSort('Bool')
FLOAT: Final = KSort('Float')
NUMBER: Final = KSort('Number')
N: Final = KSort('N')
S: Final = KSort('S')
S1: Final = KSort('S1')
S2: Final = KSort('S2')
S3: Final = KSort('S3')
MINT_N: Final = KSort('MInt', (N,))
MINT_INT: Final = KSort('MInt', (INT,))
MINT_BOOL: Final = KSort('MInt', (BOOL,))
ACCOUNT_CELL_MAP: Final = KSort('AccountCellMap')
ACCOUNT_CELL: Final = KSort('AccountCell')

_BAR_PROD: Final = KProduction(
    sort=N,
    items=[KTerminal('bar'), KTerminal('('), KNonTerminal(N), KTerminal(')')],
    params=[N],
    klabel='bar',
)

_FOO_PROD: Final = KProduction(
    sort=MINT_N,
    items=[KTerminal('foo'), KTerminal('('), KNonTerminal(MINT_N), KTerminal(')')],
    params=[N],
    klabel='foo',
)

_EQUALS_PROD: Final = KProduction(
    sort=S2,
    items=[KNonTerminal(S1), KNonTerminal(S1)],
    params=[S1, S2],
    klabel='#Equals',
)

# Hypothetical 3-param #Equals. S1 is inferred from arguments; S2 (result) and S3 (occurring
# nowhere) are independent free sorts, so add_sort_params gives each a distinct fresh sort var.
_EQUALS3_PROD: Final = KProduction(
    sort=S2,
    items=[KNonTerminal(S1), KNonTerminal(S1)],
    params=[S1, S2, S3],
    klabel='#Equals',
)

# User-defined label whose S2 occurs only in the result sort (not in any argument).  With no
# expected sort it becomes a fresh sort variable; with a matching expected sort it resolves.
_PAIR_PROD: Final = KProduction(
    sort=KSort('Pair', (S1, S2)),
    items=[KTerminal('pair'), KTerminal('('), KNonTerminal(S1), KTerminal(')')],
    params=[S1, S2],
    klabel='pair',
)

# syntax Int ::= MInt{Int}  — subsort declaration: MInt{Int} <: Int
# Enables the subsort-aware matching path (Java AddSortInjections.match step 3).
_MINT_INT_SUBSORT: Final = KProduction(sort=INT, items=[KNonTerminal(MINT_INT)])

# Subsort lattice with two incomparable subsorts sharing a common supersort:
#   syntax Number ::= Int   and   syntax Number ::= Float
# LUB(Int, Float) = Number, exercising set-based (not pairwise-chain) lub computation.
_NUMBER_INT_SUBSORT: Final = KProduction(sort=NUMBER, items=[KNonTerminal(INT)])
_NUMBER_FLOAT_SUBSORT: Final = KProduction(sort=NUMBER, items=[KNonTerminal(FLOAT)])

# #Ceil: syntax S2 ::= #Ceil{S1,S2}(S1)  -- ML pred, like #Equals (S2 is the free result sort)
_CEIL_PROD: Final = KProduction(
    sort=S2,
    items=[KNonTerminal(S1)],
    params=[S1, S2],
    klabel='#Ceil',
)

# #And: syntax S ::= #And{S}(S, S)  -- homogeneous ML connective (S is arg-bound and the result)
_AND_PROD: Final = KProduction(
    sort=S,
    items=[KNonTerminal(S), KNonTerminal(S)],
    params=[S],
    klabel='#And',
)


def _sp(n: int) -> KSort:
    """The n-th fresh #SortParam sort variable (`#SortParam{Qn}`) the algorithm allocates."""
    return KSort('#SortParam', (KSort(f'Q{n}'),))


_ACCT_MAP_CONCAT: Final = KProduction(
    sort=ACCOUNT_CELL_MAP,
    items=[KNonTerminal(ACCOUNT_CELL_MAP), KNonTerminal(ACCOUNT_CELL_MAP)],
    klabel='_AccountCellMap_',
    att=KAtt(entries=[Atts.CELL_COLLECTION(None), Atts.ELEMENT('AccountCellMapItem'), Atts.WRAP_ELEMENT('<account>')]),
)

_ACCT_MAP_ITEM: Final = KProduction(
    sort=ACCOUNT_CELL_MAP,
    items=[
        KTerminal('AccountCellMapItem'),
        KTerminal('('),
        KNonTerminal(INT),
        KTerminal(','),
        KNonTerminal(ACCOUNT_CELL),
        KTerminal(')'),
    ],
    klabel='AccountCellMapItem',
)

_ACCOUNT_CELL: Final = KProduction(
    sort=ACCOUNT_CELL,
    items=[
        KTerminal('<account>'),
        KTerminal('('),
        KNonTerminal(INT),
        KTerminal(','),
        KNonTerminal(INT),
        KTerminal(')'),
    ],
    klabel='<account>',
)

_GET_ENTRY: Final = KProduction(
    sort=ACCOUNT_CELL,
    items=[KTerminal('getEntry'), KTerminal('('), KNonTerminal(ACCOUNT_CELL), KTerminal(')')],
    klabel='getEntry',
)

DEFN: Final = KDefinition(
    'TEST',
    [
        KFlatModule(
            'TEST',
            [
                _BAR_PROD,
                _FOO_PROD,
                _EQUALS_PROD,
                _CEIL_PROD,
                _AND_PROD,
                _MINT_INT_SUBSORT,
                _NUMBER_INT_SUBSORT,
                _NUMBER_FLOAT_SUBSORT,
                _ACCT_MAP_CONCAT,
                _ACCT_MAP_ITEM,
                _ACCOUNT_CELL,
                _GET_ENTRY,
            ],
        )
    ],
)

# Definition used only to verify the multi-unbound-param guard in add_sort_params.
DEFN3: Final = KDefinition('TEST3', [KFlatModule('TEST3', [_EQUALS3_PROD])])

# Definition used only to verify the unresolvable-user-label warning path.
DEFN_PAIR: Final = KDefinition('TEST_PAIR', [KFlatModule('TEST_PAIR', [_PAIR_PROD])])


# ---------------------------------------------------------------------------
# KDefinition.sort
# ---------------------------------------------------------------------------

SORT_DATA: Final = (
    # Basic leaf terms
    ('ktoken', KToken('42', INT), INT),
    ('kvariable_with_sort', KVariable('X', sort=INT), INT),
    ('ksequence', KSequence([]), KSort('K')),
    # KApply: result sort substituted directly from param
    ('kapply_direct_result', KApply(KLabel('bar', [INT]), [KVariable('X', sort=INT)]), INT),
    # KApply: result sort nests the param (MInt{N} with N→Int → MInt{Int})
    ('kapply_nested_result', KApply(KLabel('foo', [INT]), [KVariable('X', sort=MINT_INT)]), MINT_INT),
    # KApply with unfilled sort params: sort() returns None rather than raising
    ('kapply_unfilled_params', KApply(KLabel('foo'), [KVariable('X', sort=MINT_INT)]), None),
    # KApply with unknown label: KeyError from symbols lookup → None
    ('kapply_unknown_label', KApply(KLabel('nonexistent'), []), None),
    # KAs: sort of the alias variable
    ('kas_sorted_alias', KAs(KVariable('X', sort=MINT_INT), KVariable('Y', sort=MINT_INT)), MINT_INT),
    # KAs whose alias has no sort annotation: returns None
    ('kas_unsorted_alias', KAs(KVariable('X', sort=MINT_INT), KVariable('Y')), None),
)


@pytest.mark.parametrize(
    'test_id,term,expected',
    SORT_DATA,
    ids=[test_id for test_id, *_ in SORT_DATA],
)
def test_sort(test_id: str, term: KInner, expected: KSort | None) -> None:
    assert DEFN.sort(term) == expected


# ---------------------------------------------------------------------------
# KDefinition.resolve_sorts
# ---------------------------------------------------------------------------

RESOLVE_SORTS_DATA: Final = (
    # Direct substitution: result sort IS the param (N → Int)
    ('direct_bar', KLabel('bar', [INT]), INT, (INT,)),
    # Recursive substitution: result/arg sort nests the param (MInt{N} with N → Int → MInt{Int})
    ('nested_foo', KLabel('foo', [INT]), MINT_INT, (MINT_INT,)),
)


@pytest.mark.parametrize(
    'test_id,label,expected_result,expected_args',
    RESOLVE_SORTS_DATA,
    ids=[test_id for test_id, *_ in RESOLVE_SORTS_DATA],
)
def test_resolve_sorts(test_id: str, label: KLabel, expected_result: KSort, expected_args: tuple[KSort, ...]) -> None:
    result, args = DEFN.resolve_sorts(label)
    assert result == expected_result
    assert args == expected_args


# ---------------------------------------------------------------------------
# KDefinition.add_sort_params
# ---------------------------------------------------------------------------

ADD_SORT_PARAMS_DATA: Final = (
    # Label already has params filled: leave unchanged
    (
        'already_filled',
        KApply(KLabel('bar', [INT]), [KVariable('X', sort=INT)]),
        KApply(KLabel('bar', [INT]), [KVariable('X', sort=INT)]),
    ),
    # Direct sort param: psort IS the param (N ~ Int → N=Int)
    (
        'direct_param',
        KApply(KLabel('bar'), [KVariable('X', sort=INT)]),
        KApply(KLabel('bar', [INT]), [KVariable('X', sort=INT)]),
    ),
    # Nested sort param: psort = MInt{N}, asort = MInt{Int} → N=Int via unification
    (
        'nested_param',
        KApply(KLabel('foo'), [KVariable('X', sort=MINT_INT)]),
        KApply(KLabel('foo', [INT]), [KVariable('X', sort=MINT_INT)]),
    ),
    # ML pred, no expected sort: S1 inferred from args, S2 (result sort) becomes a fresh sort var.
    (
        'ml_pred_sentinel',
        KApply('#Equals', [KVariable('X', sort=INT), KVariable('Y', sort=INT)]),
        KApply(KLabel('#Equals', [INT, _sp(0)]), [KVariable('X', sort=INT), KVariable('Y', sort=INT)]),
    ),
    # Unsortable argument (no sort annotation): cannot fill params, term returned unchanged
    (
        'unsortable_arg_unchanged',
        KApply(KLabel('foo'), [KVariable('X')]),
        KApply(KLabel('foo'), [KVariable('X')]),
    ),
    # Subsort-aware: arg sort is Int, but MInt{Int} <: Int in DEFN, so N=Int via subsort match
    # (this case would fail with structural-only unification since Int ≠ MInt{N}).
    # Note: X keeps sort Int even though the resolved production argument sort is MInt{Int}.
    # add_sort_params only fills KLabel sort params; it does not check or modify variable sorts.
    (
        'subsort_aware',
        KApply(KLabel('foo'), [KVariable('X', sort=INT)]),
        KApply(KLabel('foo', [INT]), [KVariable('X', sort=INT)]),
    ),
)


@pytest.mark.parametrize(
    'test_id,term,expected',
    ADD_SORT_PARAMS_DATA,
    ids=[test_id for test_id, *_ in ADD_SORT_PARAMS_DATA],
)
def test_add_sort_params(test_id: str, term: KInner, expected: KInner) -> None:
    assert DEFN.add_sort_params(term) == expected


def test_add_sort_params_multi_unbound_distinct_sentinels() -> None:
    # #Equals with 3 sort params and no expected sort: S1 is inferred from the arguments; S2 (the
    # result sort) and S3 (a parameter occurring nowhere) are independent free sorts and so get
    # distinct fresh sort variables — the single-sentinel scheme could not distinguish them.
    term = KApply('#Equals', [KVariable('X', sort=INT), KVariable('Y', sort=INT)])
    result = DEFN3.add_sort_params(term)
    assert isinstance(result, KApply)
    assert result.label.params == (INT, _sp(0), _sp(1))


def test_add_sort_params_user_label_free_return_sort() -> None:
    # pair{S1,S2}(S1): S1 is bound from the argument; S2 occurs only in the result sort and has
    # no determining context, so it becomes a fresh sort variable (best-effort).
    term = KApply(KLabel('pair'), [KVariable('X', sort=INT)])
    result = DEFN_PAIR.add_sort_params(term)
    assert isinstance(result, KApply)
    assert result.label.name == 'pair'
    assert result.label.params[0] == INT
    assert result.label.params[1].name == '#SortParam'


def test_add_sort_params_conflicting_ml_pred_args_warns(caplog: pytest.LogCaptureFixture) -> None:
    # #Equals(X:Int, Y:Bool) has a genuine sort mismatch in its shared S1 argument positions (Int
    # and Bool have no common supersort).  A sort *conflict* must be reported as a warning with
    # the label left unfilled (best-effort), not papered over with a sort variable.
    term = KApply('#Equals', [KVariable('X', sort=INT), KVariable('Y', sort=BOOL)])
    with caplog.at_level(logging.WARNING):
        result = DEFN.add_sort_params(term)
    assert result == term


# ---------------------------------------------------------------------------
# KDefinition.add_sort_params with an expected sort (top-down resolution)
# ---------------------------------------------------------------------------

_EQ_ARGS: Final = [KVariable('X', sort=INT), KVariable('Y', sort=INT)]
_CEIL_ARGS: Final = [KVariable('Z', sort=INT)]

ADD_SORT_PARAMS_EXPECTED_DATA: Final = (
    # ML pred with a concrete expected sort: the free result sort resolves to it (no sort var).
    (
        'ml_pred_expected',
        KApply('#Equals', _EQ_ARGS),
        GENERATED_TOP_CELL,
        KApply(KLabel('#Equals', [INT, GENERATED_TOP_CELL]), _EQ_ARGS),
    ),
    # #Ceil similarly resolves its result sort from the expected sort.
    (
        'ceil_expected',
        KApply('#Ceil', _CEIL_ARGS),
        GENERATED_TOP_CELL,
        KApply(KLabel('#Ceil', [INT, GENERATED_TOP_CELL]), _CEIL_ARGS),
    ),
    # An argument-bound parameter is taken from the argument, never from the expected sort:
    # N occurs in foo's argument sort MInt{N}, so the conflicting expected sort MInt{Bool} is
    # ignored and N resolves to Int (the expected-sort match only applies to return-only params).
    (
        'expected_ignored_for_argbound',
        KApply(KLabel('foo'), [KVariable('X', sort=MINT_INT)]),
        MINT_BOOL,
        KApply(KLabel('foo', [INT]), [KVariable('X', sort=MINT_INT)]),
    ),
    # Spine: the expected sort threads down through the #And connective so every conjunct's
    # result sort resolves to the same concrete sort.
    (
        'spine_concrete',
        KApply('#And', [KApply('#Equals', _EQ_ARGS), KApply('#Ceil', _CEIL_ARGS)]),
        GENERATED_TOP_CELL,
        KApply(
            KLabel('#And', [GENERATED_TOP_CELL]),
            [
                KApply(KLabel('#Equals', [INT, GENERATED_TOP_CELL]), _EQ_ARGS),
                KApply(KLabel('#Ceil', [INT, GENERATED_TOP_CELL]), _CEIL_ARGS),
            ],
        ),
    ),
)


@pytest.mark.parametrize(
    'test_id,term,sort,expected',
    ADD_SORT_PARAMS_EXPECTED_DATA,
    ids=[test_id for test_id, *_ in ADD_SORT_PARAMS_EXPECTED_DATA],
)
def test_add_sort_params_expected(test_id: str, term: KInner, sort: KSort, expected: KInner) -> None:
    assert DEFN.add_sort_params(term, sort) == expected


def test_add_sort_params_spine_shares_one_sort_variable() -> None:
    # No expected sort: a fresh sort variable is synthesized at the top and threads down the
    # #And spine, so every conjunct's free result sort is the *same* variable (Q0).
    term = KApply('#And', [KApply('#Equals', _EQ_ARGS), KApply('#Ceil', _CEIL_ARGS)])
    expected = KApply(
        KLabel('#And', [_sp(0)]),
        [
            KApply(KLabel('#Equals', [INT, _sp(0)]), _EQ_ARGS),
            KApply(KLabel('#Ceil', [INT, _sp(0)]), _CEIL_ARGS),
        ],
    )
    assert DEFN.add_sort_params(term) == expected


def test_add_sort_params_expected_pair_resolves_return_sort() -> None:
    # A user parametric symbol's return-only param resolves from a concrete expected sort.
    term = KApply(KLabel('pair'), [KVariable('X', sort=INT)])
    expected = KApply(KLabel('pair', [INT, BOOL]), [KVariable('X', sort=INT)])
    assert DEFN_PAIR.add_sort_params(term, KSort('Pair', (INT, BOOL))) == expected


def test_add_sort_params_spine_violation_asserts() -> None:
    # A parametric return sort in a position expecting a concrete sort it cannot satisfy (pair,
    # whose result Pair{S1,S2} cannot match GeneratedTopCell) is off the spine — an ill-formed
    # term that the spine assertion must reject.
    term = KApply(KLabel('pair'), [KVariable('X', sort=INT)])
    with pytest.raises(AssertionError, match='off the spine'):
        DEFN_PAIR.add_sort_params(term, GENERATED_TOP_CELL)


# ---------------------------------------------------------------------------
# KDefinition.least_upper_bound
# ---------------------------------------------------------------------------

LEAST_UPPER_BOUND_DATA: Final[tuple[tuple[str, tuple[KSort, ...], KSort | None], ...]] = (
    ('singleton', (INT,), INT),
    # Comparable: Int <: Number, so the bound is the larger sort.
    ('comparable', (INT, NUMBER), NUMBER),
    # Siblings with a common supersort: Int and Float are incomparable but both <: Number.
    # A pairwise-chain lub would fail here; the set-based one resolves to Number.
    ('siblings_common_supersort', (INT, FLOAT), NUMBER),
    # Order independence: the same candidate set resolves to Number regardless of order — a
    # pairwise fold would succeed for one order and fail for the other.
    ('order_independent_a', (INT, NUMBER, FLOAT), NUMBER),
    ('order_independent_b', (INT, FLOAT, NUMBER), NUMBER),
    # No common supersort: Bool shares no supersort with Int.
    ('no_common_supersort', (INT, BOOL), None),
)


@pytest.mark.parametrize(
    'test_id,sorts,expected',
    LEAST_UPPER_BOUND_DATA,
    ids=[test_id for test_id, *_ in LEAST_UPPER_BOUND_DATA],
)
def test_least_upper_bound(test_id: str, sorts: tuple[KSort, ...], expected: KSort | None) -> None:
    assert DEFN.least_upper_bound(sorts) == expected


# ---------------------------------------------------------------------------
# _match_sort_params (module-level helper)
# ---------------------------------------------------------------------------
#
# Directly tests the three matching strategies described in the docstring.


MATCH_SORT_PARAMS_DATA: Final[
    tuple[
        tuple[
            str, KSort, KSort, frozenset[KSort], Callable[[KSort], frozenset[KSort]] | None, dict[KSort, list[KSort]]
        ],
        ...,
    ]
] = (
    # Case 1 – direct: parametric IS a sort param
    ('direct', N, INT, frozenset({N}), None, {N: [INT]}),
    # Case 2 – structural: same head, recurse on sub-params
    ('structural', MINT_N, MINT_INT, frozenset({N}), None, {N: [INT]}),
    # Case 2 fails (different heads), no subsorts_fn → empty
    ('structural_no_match_no_subsorts', MINT_N, INT, frozenset({N}), None, {}),
    # Case 3 – subsort-aware: MInt{N} vs Int; DEFN.subsorts yields MInt{Int} → N=Int
    ('subsort_aware', MINT_N, INT, frozenset({N}), DEFN.subsorts, {N: [INT]}),
    # No match in any case
    ('no_match', INT, BOOL, frozenset({N}), None, {}),
)


@pytest.mark.parametrize(
    'test_id,parametric,actual,params,subsorts_fn,expected',
    MATCH_SORT_PARAMS_DATA,
    ids=[test_id for test_id, *_ in MATCH_SORT_PARAMS_DATA],
)
def test_match_sort_params(
    test_id: str,
    parametric: KSort,
    actual: KSort,
    params: frozenset[KSort],
    subsorts_fn: Callable[[KSort], frozenset[KSort]] | None,
    expected: dict[KSort, list[KSort]],
) -> None:
    assert _match_sort_params(parametric, actual, params, subsorts_fn) == expected


# ---------------------------------------------------------------------------
# KDefinition.add_cell_map_items
# ---------------------------------------------------------------------------

_ACCT_1: Final = KApply('<account>', [KVariable('X', sort=INT), KVariable('Y', sort=INT)])
_ACCT_2: Final = KApply('<account>', [KVariable('A', sort=INT), KVariable('B', sort=INT)])

ADD_CELL_MAP_ITEMS_DATA: Final = (
    # Parent expects AccountCellMap (the map sort) — children are wrapped in AccountCellMapItem.
    (
        'wraps_when_parent_expects_cell_map_sort',
        KApply('_AccountCellMap_', [_ACCT_1, _ACCT_2]),
        KApply(
            '_AccountCellMap_',
            [
                KApply('AccountCellMapItem', [KVariable('X', sort=INT), _ACCT_1]),
                KApply('AccountCellMapItem', [KVariable('A', sort=INT), _ACCT_2]),
            ],
        ),
    ),
    # Parent expects AccountCell (the element sort) — the <account> child must NOT be wrapped.
    # Before the guard fix, _wrap_elements would incorrectly wrap here too.
    (
        'no_wrap_when_parent_expects_cell_element_sort',
        KApply('getEntry', [_ACCT_1]),
        KApply('getEntry', [_ACCT_1]),
    ),
)


@pytest.mark.parametrize(
    'test_id,term,expected',
    ADD_CELL_MAP_ITEMS_DATA,
    ids=[test_id for test_id, *_ in ADD_CELL_MAP_ITEMS_DATA],
)
def test_add_cell_map_items(test_id: str, term: KInner, expected: KInner) -> None:
    assert DEFN.add_cell_map_items(term) == expected
