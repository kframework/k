from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from pyk.cterm.symbolic import CTermSymbolic
from pyk.kast.prelude.ml import mlTop
from pyk.kore.prelude import int_dv
from pyk.kore.rpc import AbortedError, AbortedResult, State, StuckResult

if TYPE_CHECKING:
    from pyk.cterm import CTerm


def _cterm_symbolic(response: object) -> CTermSymbolic:
    """Build a `CTermSymbolic` whose backend returns ``response`` and whose Kast<->Kore
    conversions are stubbed, so ``execute`` can be exercised without a real ``KDefinition``.
    """
    kore_client = Mock()
    kore_client.execute.return_value = response
    cts = CTermSymbolic(kore_client, Mock())
    # The conversions need a real definition; stub them. ``kore_to_kast`` returns ML-top so
    # ``CTerm.from_kast`` yields ``CTerm.top()`` (no config cell required).
    cts.kast_to_kore = Mock(return_value=Mock())  # type: ignore[method-assign]
    cts.kore_to_kast = Mock(return_value=mlTop())  # type: ignore[method-assign]
    return cts


def test_execute_raises_on_abort_by_default() -> None:
    # Given
    cts = _cterm_symbolic(AbortedResult(state=State(term=int_dv(1)), depth=0, unknown_predicate=None, logs=()))
    dummy: CTerm = Mock()

    # Then
    with pytest.raises(ValueError, match='aborted state'):
        cts.execute(dummy)


_ABORT_SURFACE_DATA = (
    ('aborted', AbortedResult(state=State(term=int_dv(1)), depth=3, unknown_predicate=None, logs=()), 3),
    ('normal', StuckResult(state=State(term=int_dv(2)), depth=1, logs=()), 1),
)


@pytest.mark.parametrize(
    'test_id,response,expected_depth', _ABORT_SURFACE_DATA, ids=[d[0] for d in _ABORT_SURFACE_DATA]
)
def test_execute_tolerates_abort_when_not_raising(test_id: str, response: object, expected_depth: int) -> None:
    # With raise_on_aborted=False, an aborted response is not fatal and surfaces as an ordinary
    # result (a no-progress abort comes back as depth 0).
    cts = _cterm_symbolic(response)

    result = cts.execute(Mock(), raise_on_aborted=False)

    assert result.depth == expected_depth
    assert not result.vacuous


def test_implies_aborted_treated_as_indeterminate() -> None:
    # Given a backend whose implies aborts (kore-rpc `code: 6`, e.g. recover-mode's direct
    # kore-implies call hitting "unknown constraints" the proxy would otherwise absorb)
    kore_client = Mock()
    kore_client.implies.side_effect = AbortedError(data='unknown constraints')
    cts = CTermSymbolic(kore_client, Mock())
    cts.kast_to_kore = Mock(return_value=Mock())  # type: ignore[method-assign]
    antecedent: CTerm = Mock(free_vars=frozenset())
    consequent: CTerm = Mock(free_vars=frozenset())

    # When
    result = cts.implies(antecedent, consequent)

    # Then the abort is surfaced as an indeterminate, not-subsumed result rather than crashing
    assert result.csubst is None
    assert result.indeterminate is True
