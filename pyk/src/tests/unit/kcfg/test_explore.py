from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from pyk.cterm.symbolic import CTermExecute
from pyk.kcfg.explore import KCFGExplore
from pyk.kcfg.kcfg import NoProgress, Step

from ..test_kcfg import term

if TYPE_CHECKING:
    from pyk.kcfg.kcfg import KCFGExtendResult


def _explore(exec_result: CTermExecute) -> KCFGExplore:
    cterm_symbolic = Mock()
    cterm_symbolic.execute.return_value = exec_result
    # DefaultSemantics: custom_step → None, abstract_node → identity, so extend_cterm reaches execute.
    return KCFGExplore(cterm_symbolic)


# A zero-depth no-op execute yields the neutral NoProgress (never Stuck — the coordinator decides);
# a progressing execute yields a basic-block Step (unchanged behaviour).
_EXTEND_DATA: tuple[tuple[str, CTermExecute, type[KCFGExtendResult]], ...] = (
    (
        'no-progress',
        CTermExecute(state=term(1), next_states=(), depth=0, vacuous=False, logs=()),
        NoProgress,
    ),
    ('progress', CTermExecute(state=term(2), next_states=(), depth=3, vacuous=False, logs=()), Step),
)


@pytest.mark.parametrize('test_id,exec_result,expected', _EXTEND_DATA, ids=[d[0] for d in _EXTEND_DATA])
def test_extend_cterm_classifies_execute_result(
    test_id: str, exec_result: CTermExecute, expected: type[KCFGExtendResult]
) -> None:
    explore = _explore(exec_result)
    results = explore.extend_cterm(term(1), node_id=1)
    assert len(results) == 1
    assert isinstance(results[0], expected)
