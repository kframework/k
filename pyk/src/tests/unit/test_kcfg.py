from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from pyk.cterm import CSubst, CTerm
from pyk.cterm.show import CTermShow
from pyk.kast.inner import KApply, KRewrite, KToken, KVariable, Subst
from pyk.kast.manip import no_cell_rewrite_to_dots
from pyk.kast.outer import KDefinition, KFlatModule
from pyk.kast.prelude.kint import INT
from pyk.kast.prelude.ml import mlEquals, mlTop
from pyk.kast.prelude.utils import token
from pyk.kast.pretty import PrettyPrinter
from pyk.kcfg import KCFG, KCFGShow
from pyk.kcfg.kcfg import KCFGNodeAttr, NodeVariant, Producer
from pyk.kcfg.show import NodePrinter
from pyk.utils import not_none, single

from .utils import ge_ml, k, lt_ml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path
    from typing import Any

    from pyk.kast import KInner


def to_csubst_cterm(term_1: CTerm, term_2: CTerm, constraints: Iterable[KInner]) -> CSubst:
    subst = term_1.config.match(term_2.config)
    assert subst is not None
    csubst = CSubst(subst, [])
    for constraint in constraints:
        csubst = csubst.add_constraint(constraint)
    return csubst


def to_csubst_node(node_1: KCFG.Node, node_2: KCFG.Node, constraints: Iterable[KInner]) -> CSubst:
    return to_csubst_cterm(node_1.cterm, node_2.cterm, constraints)


def to_csubst_id(source_id: int, target_id: int, constraints: Iterable[KInner]) -> CSubst:
    return to_csubst_cterm(term(source_id), term(target_id), constraints)


def x_equals(i: int) -> KInner:
    return mlEquals(KVariable('X'), token(i), arg_sort=INT)


def x_config() -> KInner:
    return KApply('<top>', KVariable('X'))


def x_subst() -> CSubst:
    return CSubst(Subst({'X': KVariable('X')}))


def x_node(i: int) -> KCFG.Node:
    return node(i, config=x_config())


# over 10 is variables
def term(i: int, auto_cond: bool = False, config: KInner | None = None) -> CTerm:
    if config is None:
        inside: KInner = token(i)
        if i > 10:
            inside = KVariable('V' + str(i))
        config = KApply('<top>', [inside])
    cond = (x_equals(i),) if auto_cond else ()
    return CTerm(not_none(config), cond)


def node(i: int, auto_cond: bool = False, config: KInner | None = None) -> KCFG.Node:
    return KCFG.Node(i, term(i, auto_cond, config))


def edge(i: int, j: int) -> KCFG.Edge:
    return KCFG.Edge(node(i), node(j), 1, ())


def merged_edge(i: int, j: int, edges: Iterable[KCFG.Edge]) -> KCFG.MergedEdge:
    return KCFG.MergedEdge(node(i), node(j), tuple(edges))


def cover(i: int, j: int) -> KCFG.Cover:
    csubst = term(j).match_with_constraint(term(i))
    assert csubst is not None
    return KCFG.Cover(node(i), node(j), csubst)


def split(i: int, js: Iterable[int], config: KInner | None = None) -> KCFG.Split:
    split_substs = []
    for j in js:
        csubst = term(i, config=config).match_with_constraint(term(j, config=config))
        assert csubst is not None
        split_substs.append(csubst)
    return KCFG.Split(node(i, config=config), zip((node(j, config=config) for j in js), split_substs, strict=True))


def ndbranch(i: int, js: Iterable[int]) -> KCFG.NDBranch:
    return KCFG.NDBranch(node(i), tuple(node(j) for j in js), ())


def node_dicts(n: int, start: int = 1, auto_cond: bool = False, config: KInner | None = None) -> list[dict[str, Any]]:
    return [node(i, auto_cond, config).to_dict() for i in range(start, start + n)]


def edge_dicts(*edges: Iterable) -> list[dict[str, Any]]:
    def _make_edge_dict(i: int, j: int, depth: int = 1, rules: tuple[str, ...] = ()) -> dict[str, Any]:
        return {'source': i, 'target': j, 'depth': depth, 'rules': list(rules)}

    return [_make_edge_dict(*edge) for edge in edges]


def merged_edge_dicts(*merged_edges: Iterable) -> list[dict[str, Any]]:

    def _make_merged_edge_dict(s: int, t: int, *edges: Iterable) -> dict[str, Any]:
        return {'source': s, 'target': t, 'edges': edge_dicts(*edges)}

    return [_make_merged_edge_dict(*merged_edge) for merged_edge in merged_edges]


def cover_dicts(*edges: tuple[int, int]) -> list[dict[str, Any]]:
    covers = []
    for i, j in edges:
        csubst = term(j).match_with_constraint(term(i))
        assert csubst is not None
        covers.append({'source': i, 'target': j, 'csubst': csubst.to_dict()})
    return covers


def split_dicts(*edges: tuple[int, Iterable[tuple[int, KInner]]], csubst: CSubst | None = None) -> list[dict[str, Any]]:
    return [
        {
            'source': source_id,
            'targets': [
                {
                    'target': target_id,
                    'csubst': (
                        to_csubst_id(source_id, target_id, [constraint]).to_dict()
                        if csubst is None
                        else csubst.add_constraint(constraint).to_dict()
                    ),
                }
                for target_id, constraint in targets
            ],
        }
        for source_id, targets in edges
    ]


def ndbranch_dicts(*edges: tuple[int, Iterable[tuple[int, bool]]]) -> list[dict[str, Any]]:
    return [
        {
            'source': source_id,
            'targets': [target_id for target_id, _ in target_ids],
            'rules': [],
        }
        for source_id, target_ids in edges
    ]


def test_from_dict_single_node() -> None:
    # Given
    d = {'next': 2, 'nodes': node_dicts(1)}

    # When
    cfg = KCFG.from_dict(d)

    # Then
    assert set(cfg.nodes) == {node(1)}
    assert cfg.to_dict() == d


def test_from_dict_two_nodes() -> None:
    # Given
    d = {'next': 3, 'nodes': node_dicts(2)}

    # When
    cfg = KCFG.from_dict(d)

    # Then
    assert set(cfg.nodes) == {node(1), node(2)}
    assert cfg.to_dict() == d


def test_from_dict_loop_edge() -> None:
    # Given
    d = {'next': 3, 'nodes': node_dicts(2), 'edges': edge_dicts((1, 2), (2, 1))}

    # When
    cfg = KCFG.from_dict(d)

    # Then
    assert set(cfg.nodes) == {node(1), node(2)}
    assert set(cfg.edges()) == {edge(1, 2), edge(2, 1)}
    assert cfg.edge(1, 2) == edge(1, 2)
    assert cfg.edge(2, 1) == edge(2, 1)
    assert cfg.to_dict() == d


def test_from_dict_simple_edge() -> None:
    # Given
    d = {'nodes': node_dicts(2), 'edges': edge_dicts((1, 2))}

    # When
    cfg = KCFG.from_dict(d)

    # Then
    assert set(cfg.nodes) == {node(1), node(2)}
    assert set(cfg.edges()) == {edge(1, 2)}
    assert cfg.edge(1, 2) == edge(1, 2)


def test_to_dict() -> None:
    # Given
    d = {'nodes': node_dicts(2), 'edges': edge_dicts((1, 2)), 'next': 3}

    # When
    cfg = KCFG.from_dict(d)
    cfg_dict = cfg.to_dict()

    # Then
    assert cfg_dict == d


def test_to_dict_repeated() -> None:
    # Given
    d = {'nodes': node_dicts(2), 'edges': edge_dicts((1, 2)), 'next': 3}

    # When
    cfg = KCFG.from_dict(d)
    cfg_dict1 = cfg.to_dict()
    cfg_dict2 = cfg.to_dict()

    # Then
    assert cfg_dict1 == cfg_dict2


def test_create_node() -> None:
    # Given
    cfg = KCFG()

    # When
    new_node = cfg.create_node(term(1))

    # Then
    assert new_node == node(1)
    assert set(cfg.nodes) == {node(1)}
    assert not cfg.is_stuck(new_node.id)


_NODE_ROUNDTRIP_DATA: tuple[tuple[str, KCFG.Node], ...] = (
    ('bare', KCFG.Node(1, term(1))),
    (
        'with-variants',
        KCFG.Node(
            1,
            term(2),
            variants=[
                NodeVariant(Producer.INIT, None, term(1)),
                NodeVariant(Producer.BOOSTER_SIMPLIFY, 'r-1', term(2)),
            ],
        ),
    ),
    ('with-attrs', KCFG.Node(1, term(1), attrs=[KCFGNodeAttr.BOOSTER_TRIED, KCFGNodeAttr.SUBSUME_INDETERMINATE])),
)


@pytest.mark.parametrize('test_id,node', _NODE_ROUNDTRIP_DATA, ids=[d[0] for d in _NODE_ROUNDTRIP_DATA])
def test_node_serialisation_roundtrip(test_id: str, node: KCFG.Node) -> None:
    # Node.to_dict/from_dict round-trips attrs and the variant chain; node equality ignores variants,
    # so the chain is compared explicitly.
    restored = KCFG.Node.from_dict(node.to_dict())
    assert restored == node
    assert restored.variants == node.variants


def test_serialisation_omits_empty_recover_keys() -> None:
    # Additive/back-compat: recover-mode keys are absent when empty, so legacy readers are unaffected.
    assert 'variants' not in KCFG.Node(1, term(1)).to_dict()
    cfg = KCFG()
    cfg.create_node(term(1))
    assert 'kore_handoffs' not in cfg.to_dict()
    assert 'kore_handoffs' not in cfg.to_dict_no_nodes()


def test_add_variant_chains_and_updates_cterm() -> None:
    # Given a fresh node at rung 0
    cfg = KCFG()
    n = cfg.create_node(term(1))

    # When a booster-simplify variant is appended
    cfg.add_variant(n.id, Producer.BOOSTER_SIMPLIFY, term(2), request_id='claim-001')
    updated = cfg.node(n.id)

    # Then the canonical cterm advances and the chain seeds INIT then records the step
    assert updated.cterm == term(2)
    assert [v.producer for v in updated.variants] == [Producer.INIT, Producer.BOOSTER_SIMPLIFY]
    assert updated.variants[0].cterm == term(1)
    assert updated.variants[-1].cterm == term(2)
    assert updated.variants[-1].request_id == 'claim-001'

    # When a second (kore-simplify) variant is appended, INIT is not re-seeded
    cfg.add_variant(n.id, Producer.KORE_SIMPLIFY, term(3), request_id='claim-002')
    updated = cfg.node(n.id)
    assert updated.cterm == term(3)
    assert [v.producer for v in updated.variants] == [
        Producer.INIT,
        Producer.BOOSTER_SIMPLIFY,
        Producer.KORE_SIMPLIFY,
    ]


def test_node_equality_ignores_variants() -> None:
    # Given two nodes identical but for their variant chains
    bare = KCFG.Node(1, term(1))
    with_variants = KCFG.Node(1, term(1), variants=[NodeVariant(Producer.INIT, None, term(1))])

    # Then they compare equal and hash equal (variants is metadata)
    assert bare == with_variants
    assert hash(bare) == hash(with_variants)


def test_kore_handoffs_add_and_roundtrip() -> None:
    from pyk.kcfg.kcfg import HandoffFlavour, KoreHandoff

    # Given a kcfg with two recorded handoffs
    cfg = KCFG()
    cfg.create_node(term(1))
    cfg.add_kore_handoff(KoreHandoff(source=1, target=2, flavour=HandoffFlavour.EXECUTE, request_id='claim-003'))
    cfg.add_kore_handoff(KoreHandoff(source=2, target=2, flavour=HandoffFlavour.IMPLIES, request_id='claim-004'))

    # Then the accessor returns them and they round-trip through to_dict/from_dict
    assert len(cfg.kore_handoffs) == 2
    restored = KCFG.from_dict(cfg.to_dict())
    assert restored.kore_handoffs == cfg.kore_handoffs


def test_remove_unknown_node() -> None:
    # Given
    cfg = KCFG()

    # Then
    with pytest.raises(ValueError):
        # When
        cfg.remove_node(0)


def test_remove_node() -> None:
    # Given
    d = {'nodes': node_dicts(3), 'edges': edge_dicts((1, 2), (2, 3))}
    cfg = KCFG.from_dict(d)

    # When
    cfg.remove_node(2)

    # Then
    assert set(cfg.nodes) == {node(1), node(3)}
    assert set(cfg.edges()) == set()
    assert not cfg.is_stuck(1)
    with pytest.raises(ValueError):
        cfg.node(2)
    with pytest.raises(ValueError):
        cfg.edge(1, 2)
    with pytest.raises(ValueError):
        cfg.edge(2, 3)


def test_cover_then_remove() -> None:
    # Given
    cfg = KCFG()

    # When
    node1 = cfg.create_node(CTerm(KApply('<top>', token(1))))
    node2 = cfg.create_node(CTerm(KApply('<top>', KVariable('X'))))
    cover = cfg.create_cover(node1.id, node2.id)

    # Then
    assert cfg.is_covered(node1.id)
    assert not cfg.is_covered(node2.id)
    assert dict(cover.csubst.subst) == {'X': token(1)}
    assert cfg.covers() == [cover]

    # When
    cfg.remove_cover(node1.id, node2.id)

    # Then
    assert not cfg.is_covered(node1.id)
    assert not cfg.is_covered(node2.id)
    assert cfg.covers() == []


def test_insert_simple_edge() -> None:
    # Given
    d = {'nodes': node_dicts(2)}
    cfg = KCFG.from_dict(d)

    # When
    new_edge = cfg.create_edge(1, 2, 1)

    # Then
    assert new_edge == edge(1, 2)
    assert set(cfg.nodes) == {node(1), node(2)}
    assert set(cfg.edges()) == {edge(1, 2)}


def test_get_successors() -> None:
    d = {
        'next': 19,
        'nodes': node_dicts(18),
        'edges': edge_dicts((11, 12)),
        'merged_edges': merged_edge_dicts((17, 18, (14, 15))),
        'splits': split_dicts((12, [(13, mlTop()), (14, mlTop())])),
        'covers': cover_dicts((14, 11)),
        'ndbranches': ndbranch_dicts((13, [(16, False), (17, False)])),
    }
    cfg = KCFG.from_dict(d)

    # When
    edges = set(cfg.edges(source_id=11))
    merged_edges = set(cfg.merged_edges(source_id=17))
    covers = set(cfg.covers(source_id=14))
    splits = sorted(cfg.splits(source_id=12))
    ndbranches = set(cfg.ndbranches(source_id=13))

    # Then
    assert edges == {edge(11, 12)}
    assert merged_edges == {merged_edge(17, 18, [edge(14, 15)])}
    assert covers == {cover(14, 11)}
    assert splits == [split(12, [13, 14])]
    assert ndbranches == {ndbranch(13, [16, 17])}
    assert cfg.to_dict() == d


def test_get_predecessors() -> None:
    d = {'nodes': node_dicts(3), 'edges': edge_dicts((1, 3), (2, 3))}
    cfg = KCFG.from_dict(d)

    # When
    preds = set(cfg.edges(target_id=3))

    # Then
    assert preds == {edge(1, 3), edge(2, 3)}


def test_reachable_nodes() -> None:
    # Given
    d = {
        'nodes': node_dicts(21),
        'edges': edge_dicts((13, 15), (14, 15), (15, 12)),
        'merged_edges': merged_edge_dicts((20, 21, (12, 13))),
        'covers': cover_dicts((12, 13)),
        'splits': split_dicts(
            (16, [(12, mlTop()), (13, mlTop()), (17, mlTop())]), (17, [(12, mlTop()), (18, mlTop())])
        ),
        'ndbranches': ndbranch_dicts((18, [(19, False), (20, False)])),
    }
    cfg = KCFG.from_dict(d)

    # When
    nodes_2 = cfg.reachable_nodes(12)
    nodes_3 = cfg.reachable_nodes(16)
    nodes_4 = cfg.reachable_nodes(13, reverse=True)
    nodes_5 = cfg.reachable_nodes(19, reverse=True)

    # Then
    assert nodes_2 == {node(12), node(13), node(15)}
    assert nodes_3 == {node(16), node(12), node(13), node(17), node(18), node(15), node(19), node(20), node(21)}
    assert nodes_4 == {node(13), node(16), node(12), node(15), node(17), node(14)}
    assert nodes_5 == {node(19), node(18), node(17), node(16)}


def test_paths_between() -> None:
    # Given
    d = {
        'nodes': node_dicts(21),
        'edges': edge_dicts((13, 15), (14, 15), (15, 12)),
        'merged_edges': merged_edge_dicts((20, 21, (12, 13))),
        'covers': cover_dicts((12, 13)),
        'splits': split_dicts(
            (16, [(12, mlTop()), (13, mlTop()), (17, mlTop())]), (17, [(12, mlTop()), (18, mlTop())])
        ),
        'ndbranches': ndbranch_dicts((18, [(19, False), (20, False)])),
    }
    cfg = KCFG.from_dict(d)

    # When
    paths = sorted(cfg.paths_between(16, 15))

    # Then
    assert paths == [
        (split(16, [12]), cover(12, 13), edge(13, 15)),
        (split(16, [13]), edge(13, 15)),
        (split(16, [17]), split(17, [12]), cover(12, 13), edge(13, 15)),
    ]

    # When
    paths = sorted(cfg.paths_between(17, 21))

    # Then
    assert paths == [
        (split(17, [18]), ndbranch(18, [20]), merged_edge(20, 21, [edge(12, 13)])),
    ]


def test_resolve() -> None:
    # Given
    d = {
        'nodes': node_dicts(4),
    }
    cfg = KCFG.from_dict(d)

    assert node(1) == cfg.node(1)


def test_vacuous() -> None:
    # Given
    d = {
        'nodes': node_dicts(4),
        'edges': edge_dicts((1, 2), (2, 3)),
        'aliases': {'foo': 2},
    }

    cfg = KCFG.from_dict(d)
    cfg.add_vacuous(3)
    assert cfg.vacuous, node(3)


def test_let_node() -> None:
    # Given
    d = {
        'nodes': node_dicts(4),
        'edges': edge_dicts((1, 2), (2, 3)),
    }

    cfg = KCFG.from_dict(d)
    cfg.let_node(2, cterm=term(5))

    node = cfg.node(2)
    assert node is not None
    assert node.cterm == term(5)

    first_edge = cfg.edge(1, 2)
    assert first_edge is not None
    assert first_edge.target.cterm == term(5)

    second_edge = cfg.edge(2, 3)
    assert second_edge is not None
    assert second_edge.source.cterm == term(5)


def test_aliases() -> None:
    # Given
    d = {
        'nodes': node_dicts(4),
        'edges': edge_dicts((1, 2), (2, 3)),
        'aliases': {'foo': 2},
    }

    cfg = KCFG.from_dict(d)
    assert cfg.node('@foo'), node(2)

    cfg.add_alias('bar', 1)
    cfg.add_alias('bar2', 1)
    assert cfg.node('@bar'), node(1)
    assert cfg.node('@bar2'), node(1)
    cfg.remove_alias('bar')
    with pytest.raises(ValueError, match='Unknown alias: @bar'):
        cfg.node('@bar')

    with pytest.raises(ValueError, match='Duplicate alias: bar2'):
        cfg.add_alias('bar2', 2)
    with pytest.raises(ValueError, match='Alias may not contain "@"'):
        cfg.add_alias('@buzz', 2)
    with pytest.raises(ValueError, match='Unknown node: 10'):
        cfg.add_alias('buzz', 10)


def test_split_csubsts() -> None:
    cfg = KCFG()
    cfg.create_node(term(11))
    cfg.split_on_constraints(1, [x_equals(10), x_equals(20)])
    # The target substitutions are identities, with the appropriate constraints
    split = single(cfg.splits())
    assert split.source == KCFG.Node(1, term(11))
    assert split._targets[0][1] == CSubst(Subst({'V11': KVariable('V11')}), [x_equals(10)])
    assert split._targets[1][1] == CSubst(Subst({'V11': KVariable('V11')}), [x_equals(20)])


def test_write_cfg_data(tmp_path: Path) -> None:
    def _written_nodes() -> set[str]:
        return {nd_path.name for nd_path in (tmp_path / 'nodes').iterdir()}

    kcfg = KCFG(cfg_dir=tmp_path)

    kcfg.add_node(node(1))
    kcfg.add_node(node(2))
    kcfg.add_node(node(3))

    assert _written_nodes() == set()

    kcfg.write_cfg_data()

    assert _written_nodes() == {'1.json', '2.json', '3.json'}

    kcfg.add_node(node(4))
    kcfg.remove_node(1)
    kcfg.remove_node(2)
    kcfg.let_node(3, cterm=node(3).cterm)
    kcfg.add_node(node(2))

    assert _written_nodes() == {'1.json', '2.json', '3.json'}

    kcfg.write_cfg_data()

    assert _written_nodes() == {'2.json', '3.json', '4.json'}


def test_read_write_cfg_data(tmp_path: Path) -> None:

    kcfg = KCFG(cfg_dir=tmp_path)

    kcfg.add_node(node(1))
    kcfg.add_node(node(2))
    kcfg.add_node(node(3))
    kcfg.add_attr(1, KCFGNodeAttr.VACUOUS)
    kcfg.add_attr(2, KCFGNodeAttr.STUCK)

    kcfg.write_cfg_data()
    read_kcfg = KCFG.read_cfg_data(tmp_path)

    assert set(kcfg.nodes) == set(read_kcfg.nodes)


def test_pretty_print() -> None:
    nodes = node_dicts(15, start=10) + node_dicts(1, start=25, auto_cond=True)
    nodes_dict = {node['id']: node for node in nodes}
    nodes_dict[23]['attrs'] = [KCFGNodeAttr.STUCK.value]
    nodes_dict[17]['attrs'] = [KCFGNodeAttr.VACUOUS.value]
    nodes = list(nodes_dict.values())

    d = {
        'nodes': nodes,
        'aliases': {'foo': 14, 'bar': 14},
        'edges': edge_dicts((12, 13, 5), (13, 14), (15, 16), (16, 13), (18, 17), (22, 19)),
        'merged_edges': merged_edge_dicts((21, 12, (21, 12), (21, 13))),
        'covers': cover_dicts((19, 22)),
        'splits': split_dicts(
            (
                14,
                [
                    (15, x_equals(15)),
                    (16, x_equals(16)),
                    (17, x_equals(17)),
                    (18, x_equals(18)),
                    (20, x_equals(20)),
                    (23, x_equals(23)),
                    (22, x_equals(22)),
                ],
            )
        ),
        'ndbranches': ndbranch_dicts((20, [(24, False), (25, True)])),
        'stuck': [23],
        'vacuous': [17],
    }
    cfg = KCFG.from_dict(d)

    expected = (
        '\n'
        '┌─ 21 (root)\n'
        '│\n'
        '│  (1|1 steps)\n'
        '├─ 12\n'
        '│\n'
        '│  (5 steps)\n'
        '├─ 13\n'
        '│\n'
        '│  (1 step)\n'
        '├─ 14 (split, @bar, @foo)\n'
        '┃\n'
        '┃ (branch)\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 15 )\n'
        '┃  │\n'
        '┃  ├─ 15\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  ├─ 16\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  └─ 13\n'
        '┃     (looped back)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 16 )\n'
        '┃  │\n'
        '┃  └─ 16\n'
        '┃     (continues as previously)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 17 )\n'
        '┃  │\n'
        '┃  └─ 17 (vacuous, leaf)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 18 )\n'
        '┃  │\n'
        '┃  ├─ 18\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  └─ 17 (vacuous, leaf)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 20 )\n'
        '┃  │\n'
        '┃  ├─ 20\n'
        '┃  ┃\n'
        '┃  ┃ (1 step)\n'
        '┃  ┣━━┓\n'
        '┃  ┃  │\n'
        '┃  ┃  └─ 24 (leaf)\n'
        '┃  ┃\n'
        '┃  ┗━━┓\n'
        '┃     │\n'
        '┃     └─ 25 (leaf)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 23 )\n'
        '┃  │\n'
        '┃  └─ 23 (stuck, leaf)\n'
        '┃\n'
        '┗━━┓ subst: ...\n'
        '   ┃ constraint:\n'
        '   ┃     _==K_ ( X , 22 )\n'
        '   │\n'
        '   ├─ 22\n'
        '   │\n'
        '   │  (1 step)\n'
        '   ├─ 19\n'
        '   │\n'
        '   ┊  constraint: true\n'
        '   ┊  subst: ...\n'
        '   └─ 22\n'
        '      (looped back)\n'
        '\n'
        '\n'
        '┌─ 10 (root, leaf)\n'
        '\n'
        '┌─ 11 (root, leaf)\n'
    )

    expected_full_printer = (
        '\n'
        '┌─ 21 (root)\n'
        '│     <top>\n'
        '│       V21\n'
        '│     </top>\n'
        '│\n'
        '│  (1|1 steps)\n'
        '├─ 12\n'
        '│     <top>\n'
        '│       V12\n'
        '│     </top>\n'
        '│\n'
        '│  (5 steps)\n'
        '├─ 13\n'
        '│     <top>\n'
        '│       V13\n'
        '│     </top>\n'
        '│\n'
        '│  (1 step)\n'
        '├─ 14 (split, @bar, @foo)\n'
        '│     <top>\n'
        '│       V14\n'
        '│     </top>\n'
        '┃\n'
        '┃ (branch)\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 15 )\n'
        '┃  │\n'
        '┃  ├─ 15\n'
        '┃  │     <top>\n'
        '┃  │       V15\n'
        '┃  │     </top>\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  ├─ 16\n'
        '┃  │     <top>\n'
        '┃  │       V16\n'
        '┃  │     </top>\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  └─ 13\n'
        '┃        <top>\n'
        '┃          V13\n'
        '┃        </top>\n'
        '┃     (looped back)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 16 )\n'
        '┃  │\n'
        '┃  └─ 16\n'
        '┃        <top>\n'
        '┃          V16\n'
        '┃        </top>\n'
        '┃     (continues as previously)\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 17 )\n'
        '┃  │\n'
        '┃  └─ 17 (vacuous, leaf)\n'
        '┃        <top>\n'
        '┃          V17\n'
        '┃        </top>\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 18 )\n'
        '┃  │\n'
        '┃  ├─ 18\n'
        '┃  │     <top>\n'
        '┃  │       V18\n'
        '┃  │     </top>\n'
        '┃  │\n'
        '┃  │  (1 step)\n'
        '┃  └─ 17 (vacuous, leaf)\n'
        '┃        <top>\n'
        '┃          V17\n'
        '┃        </top>\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 20 )\n'
        '┃  │\n'
        '┃  ├─ 20\n'
        '┃  │     <top>\n'
        '┃  │       V20\n'
        '┃  │     </top>\n'
        '┃  ┃\n'
        '┃  ┃ (1 step)\n'
        '┃  ┣━━┓\n'
        '┃  ┃  │\n'
        '┃  ┃  └─ 24 (leaf)\n'
        '┃  ┃        <top>\n'
        '┃  ┃          V24\n'
        '┃  ┃        </top>\n'
        '┃  ┃\n'
        '┃  ┗━━┓\n'
        '┃     │\n'
        '┃     └─ 25 (leaf)\n'
        '┃           <top>\n'
        '┃             V25\n'
        '┃           </top>\n'
        '┃           #And #Equals ( X , 25 )\n'
        '┃\n'
        '┣━━┓ subst: ...\n'
        '┃  ┃ constraint:\n'
        '┃  ┃     _==K_ ( X , 23 )\n'
        '┃  │\n'
        '┃  └─ 23 (stuck, leaf)\n'
        '┃        <top>\n'
        '┃          V23\n'
        '┃        </top>\n'
        '┃\n'
        '┗━━┓ subst: ...\n'
        '   ┃ constraint:\n'
        '   ┃     _==K_ ( X , 22 )\n'
        '   │\n'
        '   ├─ 22\n'
        '   │     <top>\n'
        '   │       V22\n'
        '   │     </top>\n'
        '   │\n'
        '   │  (1 step)\n'
        '   ├─ 19\n'
        '   │     <top>\n'
        '   │       V19\n'
        '   │     </top>\n'
        '   │\n'
        '   ┊  constraint: true\n'
        '   ┊  subst: ...\n'
        '   └─ 22\n'
        '         <top>\n'
        '           V22\n'
        '         </top>\n'
        '      (looped back)\n'
        '\n'
        '\n'
        '┌─ 10 (root, leaf)\n'
        '│     <top>\n'
        '│       10\n'
        '│     </top>\n'
        '\n'
        '┌─ 11 (root, leaf)\n'
        '│     <top>\n'
        '│       V11\n'
        '│     </top>\n'
    )

    # When
    definition = KDefinition('MOCK', [KFlatModule('MOCK', [])], [])
    cterm_show = CTermShow(PrettyPrinter(definition).print, minimize=False)
    kcfg_show = KCFGShow(definition, node_printer=NodePrinter(cterm_show))
    kcfg_show_full_printer = KCFGShow(definition, node_printer=NodePrinter(cterm_show, full_printer=True))
    actual = '\n'.join(kcfg_show.pretty(cfg)) + '\n'
    actual_full_printer = '\n'.join(kcfg_show_full_printer.pretty(cfg)) + '\n'

    # Then
    assert actual == expected
    assert actual_full_printer == expected_full_printer


def test_no_cell_rewrite_to_dots() -> None:
    term = KApply(
        '<accounts>',
        [
            KRewrite(
                lhs=KApply(
                    '_AccountCellMap_',
                    [
                        KApply(
                            '<account>',
                            [
                                KApply(
                                    '<acctID>',
                                    [KToken('645326474426547203313410069153905908525362434349', 'Int')],
                                ),
                            ],
                        ),
                        KApply(
                            '<account>',
                            [
                                KApply(
                                    '<acctID>',
                                    [KToken('728815563385977040452943777879061427756277306518', 'Int')],
                                ),
                            ],
                        ),
                    ],
                ),
                rhs=KVariable('ACCOUNTS_FINAL', 'AccountCellMap'),
            )
        ],
    )

    result = no_cell_rewrite_to_dots(term)
    assert result == term


CREATE_SPLIT_BY_NODES_TEST_DATA: Final = (
    (CTerm.bottom(), [CTerm.top(), CTerm.bottom()], None),
    (CTerm.top(), [CTerm.top(), CTerm.bottom()], None),
    (
        CTerm.top(),
        [CTerm(k(KVariable('X'))), CTerm(k(KVariable('Y')))],
        None,  # todo: support split from top, because top means anything can be matched
    ),
    # not mutually exclusive
    (
        CTerm.top(),
        [CTerm.top(), CTerm.top()],
        KCFG.Split(
            KCFG.Node(1, CTerm.top()), [(KCFG.Node(2, CTerm.top()), CSubst()), (KCFG.Node(3, CTerm.top()), CSubst())]
        ),
    ),
    # not mutually exclusive
    (
        CTerm(k(KVariable('X'))),
        [CTerm(k(KVariable('X'))), CTerm(k(KVariable('Y'))), CTerm(k(KVariable('Z')))],
        KCFG.Split(
            KCFG.Node(1, CTerm(k(KVariable('X')))),
            [
                (KCFG.Node(2, CTerm(k(KVariable('X')))), CSubst(Subst({'X': KVariable('X')}))),
                (KCFG.Node(3, CTerm(k(KVariable('Y')))), CSubst(Subst({'X': KVariable('Y')}))),
                (KCFG.Node(4, CTerm(k(KVariable('Z')))), CSubst(Subst({'X': KVariable('Z')}))),
            ],
        ),
    ),
    (CTerm(k(KVariable('X'))), [CTerm(k(KVariable('Y'))), CTerm(KApply('<bot>', [KVariable('Z')]))], None),
    # not mutually exclusive
    # this target doesn't meet the implication relationship with source.
    # So the CTerm of target and CSubst.apply(target) are not logically equal.
    # But source -> CSubst.apply(target) can always be true.
    (
        CTerm(k(KVariable('X')), [ge_ml('X', 0), lt_ml('X', 10)]),
        [CTerm(k(KVariable('Y')), [ge_ml('Y', 0)]), CTerm(k(KVariable('Z')), [ge_ml('Z', 5)])],
        KCFG.Split(
            KCFG.Node(1, CTerm(k(KVariable('X')), [ge_ml('X', 0), lt_ml('X', 10)])),
            [
                (
                    KCFG.Node(2, CTerm(k(KVariable('Y')), [ge_ml('Y', 0)])),
                    CSubst(Subst({'X': KVariable('Y')}), []),
                ),
                (
                    KCFG.Node(3, CTerm(k(KVariable('Z')), [ge_ml('Z', 5)])),
                    CSubst(
                        Subst({'X': KVariable('Z')}),
                        [
                            ge_ml('Z', 5),
                        ],
                    ),
                ),
            ],
        ),
    ),
    (
        CTerm(k(KVariable('X')), [ge_ml('X', 0), lt_ml('X', 10)]),
        [
            CTerm(k(KVariable('Y')), [ge_ml('Y', 0), lt_ml('Y', 5)]),
            CTerm(k(KVariable('Z')), [ge_ml('Z', 5), lt_ml('Z', 10)]),
        ],
        KCFG.Split(
            KCFG.Node(1, CTerm(k(KVariable('X')), [ge_ml('X', 0), lt_ml('X', 10)])),
            [
                (
                    KCFG.Node(2, CTerm(k(KVariable('Y')), [ge_ml('Y', 0), lt_ml('Y', 5)])),
                    CSubst(Subst({'X': KVariable('Y')}), [lt_ml('Y', 5)]),
                ),
                (
                    KCFG.Node(3, CTerm(k(KVariable('Z')), [ge_ml('Z', 5), lt_ml('Z', 10)])),
                    CSubst(Subst({'X': KVariable('Z')}), [ge_ml('Z', 5)]),
                ),
            ],
        ),
    ),
)


@pytest.mark.parametrize('source,targets,expected', CREATE_SPLIT_BY_NODES_TEST_DATA)
def test_create_split_by_nodes(source: CTerm, targets: Iterable[CTerm], expected: KCFG.Split | None) -> None:
    # Given
    cfg = KCFG()
    source_node = cfg.create_node(source)
    target_nodes = [cfg.create_node(target) for target in targets]

    # When
    actual = cfg.create_split_by_nodes(source_node.id, [n.id for n in target_nodes])

    # Then
    assert actual == expected
