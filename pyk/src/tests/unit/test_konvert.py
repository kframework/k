from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pyk.kast.inner import KSort
from pyk.kast.prelude.k import SORT_PARAM_SENTINEL
from pyk.konvert import munge, unmunge
from pyk.konvert._kast_to_kore import _ksort_to_kore
from pyk.kore.syntax import SortApp

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Final


def munge_test_data_reader() -> Iterator[tuple[str, str]]:
    test_data_file = Path(__file__).parent / 'test-data/munge-tests'
    with open(test_data_file) as f:
        while True:
            try:
                label = next(f)
                symbol = next(f)
            except StopIteration:
                raise AssertionError('Malformed test data') from None

            yield label.rstrip('\n'), symbol.rstrip('\n')

            try:
                next(f)
            except StopIteration:
                return


MUNGE_TEST_DATA: Final = tuple(munge_test_data_reader())


@pytest.mark.parametrize('label,expected', MUNGE_TEST_DATA, ids=[label for label, _ in MUNGE_TEST_DATA])
def test_munge(label: str, expected: str) -> None:
    # When
    actual = munge(label)

    # Then
    assert actual == expected


@pytest.mark.parametrize('expected,symbol', MUNGE_TEST_DATA, ids=[symbol for _, symbol in MUNGE_TEST_DATA])
def test_unmunge(symbol: str, expected: str) -> None:
    # When
    actual = unmunge(symbol)

    # Then
    assert actual == expected


def test_ksort_to_kore_ordinary_sort() -> None:
    assert _ksort_to_kore(KSort('Int')) == SortApp('SortInt')


@pytest.mark.parametrize(
    'sentinel',
    (
        SORT_PARAM_SENTINEL,  # bare sentinel
        KSort(SORT_PARAM_SENTINEL.name, (KSort('Q0'),)),  # uniquely-named family member
    ),
    ids=['bare', 'parametric'],
)
def test_ksort_to_kore_rejects_sortparam_sentinel(sentinel: KSort) -> None:
    # The #SortParam sentinel family cannot yet be emitted to Kore (it needs an axiom-level sort
    # variable); _ksort_to_kore must fail with a clear, actionable error rather than building the
    # invalid identifier `Sort#SortParam`.  See pyk/docs/2026-06-01-sortparam-kore-emission.md.
    with pytest.raises(ValueError, match=SORT_PARAM_SENTINEL.name):
        _ksort_to_kore(sentinel)
