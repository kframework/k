from __future__ import annotations

import json
from itertools import count
from typing import TYPE_CHECKING

import pytest

from pyk.cterm import CTerm
from pyk.kast.inner import KApply, KSequence
from pyk.kast.prelude.utils import token
from pyk.kcfg.kcfg import KCFG, HandoffFlavour, KCFGNodeAttr, KoreHandoff, Producer
from pyk.kcfg.store import OptimizedNodeStore, _Cache

from ..utils import a, b, c, f

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Final

    from pyk.kast import KInner


EQUAL_TEST_DATA: Final[tuple[tuple[KInner, KInner], ...]] = (
    (token(1), token(1)),
    (token('a'), token('a')),
    (a, a),
    (f(a), f(a)),
    (KSequence([a, b]), KSequence([a, b])),
)


@pytest.mark.parametrize('term1,term2', EQUAL_TEST_DATA, ids=count())
def test_use_cached(term1: KInner, term2: KInner) -> None:
    # Given
    cached_values: _Cache[KInner] = _Cache()

    # When
    id1 = cached_values.cache(term1)
    id2 = cached_values.cache(term2)

    # Then
    assert id1 == id2


NOT_EQUAL_TEST_DATA: Final[tuple[tuple[KInner, KInner], ...]] = (
    (token(1), token(2)),
    (token(1), token('1')),
    (a, b),
    (f(a), f(b)),
    (KSequence([a, b]), KSequence([a, c])),
)


@pytest.mark.parametrize('term1,term2', NOT_EQUAL_TEST_DATA, ids=count())
def test_not_use_cached(term1: KInner, term2: KInner) -> None:
    # Given
    cached_values: _Cache[KInner] = _Cache()

    # When
    id1 = cached_values.cache(term1)
    id2 = cached_values.cache(term2)

    # Then
    assert term1 != term2
    assert id1 != id2


OPTIMIZE_TEST_DATA: Final[tuple[KInner, ...]] = (
    token(1),
    token('a'),
    a,
    f(a),
    KSequence([a, token(3)]),
)


def test_optimized_store() -> None:
    store = OptimizedNodeStore()

    for idx, item in zip(range(0, len(OPTIMIZE_TEST_DATA)), OPTIMIZE_TEST_DATA, strict=True):
        store[idx] = KCFG.Node(idx, CTerm(KApply('<cell>', item), ()))

    for idx, item in zip(range(0, len(OPTIMIZE_TEST_DATA)), OPTIMIZE_TEST_DATA, strict=True):
        assert KCFG.Node(idx, CTerm(KApply('<cell>', item), ())) == store[idx]


def _cell(i: int) -> CTerm:
    return CTerm(KApply('<cell>', token(i)))


def test_kcfg_store_roundtrip_preserves_attrs_variants_handoffs(tmp_path: Path) -> None:
    # Given a kcfg (on disk) carrying new attrs, a variant chain, and a handoff
    cfg = KCFG(tmp_path / 'kcfg')
    n1 = cfg.create_node(_cell(1))
    n2 = cfg.create_node(_cell(2))
    cfg.add_attr(n1.id, KCFGNodeAttr.BOOSTER_TRIED)
    cfg.add_attr(n1.id, KCFGNodeAttr.SUBSUME_INDETERMINATE)
    cfg.add_attr(n2.id, KCFGNodeAttr.STUCK)
    cfg.add_attr(n2.id, KCFGNodeAttr.BOTH_BACKENDS_FAILED)
    cfg.add_variant(n1.id, Producer.BOOSTER_SIMPLIFY, _cell(3), request_id='r-1')
    cfg.add_kore_handoff(KoreHandoff(source=n1.id, target=n2.id, flavour=HandoffFlavour.EXECUTE, request_id='r-2'))

    # When written and read back through KCFGStore
    cfg.write_cfg_data()
    restored = KCFG.read_cfg_data(tmp_path / 'kcfg')

    # Then attrs, the variant chain (and canonical cterm), and handoffs all survive
    rn1 = restored.node(n1.id)
    assert KCFGNodeAttr.BOOSTER_TRIED in rn1.attrs
    assert KCFGNodeAttr.SUBSUME_INDETERMINATE in rn1.attrs
    assert rn1.cterm == _cell(3)
    assert [v.producer for v in rn1.variants] == [Producer.INIT, Producer.BOOSTER_SIMPLIFY]
    rn2 = restored.node(n2.id)
    assert KCFGNodeAttr.STUCK in rn2.attrs
    assert KCFGNodeAttr.BOTH_BACKENDS_FAILED in rn2.attrs
    assert restored.kore_handoffs == [
        KoreHandoff(source=n1.id, target=n2.id, flavour=HandoffFlavour.EXECUTE, request_id='r-2')
    ]


def test_kcfg_store_loads_legacy_without_new_keys(tmp_path: Path) -> None:
    # Given a store written, then downgraded to look like an old one (new side-list keys removed)
    cfg = KCFG(tmp_path / 'kcfg')
    n = cfg.create_node(_cell(1))
    cfg.add_attr(n.id, KCFGNodeAttr.STUCK)
    cfg.write_cfg_data()

    kcfg_json = tmp_path / 'kcfg' / 'kcfg.json'
    dct = json.loads(kcfg_json.read_text())
    for key in ['booster_tried', 'kore_tried', 'subsume_indeterminate', 'both_backends_failed', 'kore_handoffs']:
        dct.pop(key, None)
    kcfg_json.write_text(json.dumps(dct))

    # When read back, the legacy store still loads and the pre-existing attr survives
    restored = KCFG.read_cfg_data(tmp_path / 'kcfg')
    assert restored.node(n.id).cterm == _cell(1)
    assert KCFGNodeAttr.STUCK in restored.node(n.id).attrs
    assert restored.kore_handoffs == []
