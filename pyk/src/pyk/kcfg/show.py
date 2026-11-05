from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from graphviz import Digraph

from ..cterm.show import CTermShow
from ..kast.inner import KApply, KRewrite, top_down
from ..kast.manip import (
    flatten_label,
    inline_cell_maps,
    minimize_rule_like,
    minimize_term,
    ml_pred_to_bool,
    push_down_rewrites,
    remove_generated_cells,
    sort_ac_collections,
)
from ..kast.outer import KRule
from ..kast.prelude.k import DOTS
from ..kast.prelude.ml import mlAnd
from ..kast.pretty import PrettyPrinter
from ..utils import add_indent, ensure_dir_path
from .kcfg import KCFG

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from typing import Final

    from ..cterm import CSubst
    from ..kast import KInner
    from ..kast.outer import KDefinition, KFlatModule, KImport, KSentence
    from .kcfg import NodeIdLike

_LOGGER: Final = logging.getLogger(__name__)


class NodePrinter:
    cterm_show: CTermShow
    full_printer: bool
    minimize: bool

    def __init__(self, cterm_show: CTermShow, full_printer: bool = False):
        self.cterm_show = cterm_show
        self.full_printer = full_printer

    def print_node(self, kcfg: KCFG, node: KCFG.Node) -> list[str]:
        attrs = self.node_attrs(kcfg, node)
        attr_str = ' (' + ', '.join(attrs) + ')' if attrs else ''
        node_strs = [f'{node.id}{attr_str}']
        if self.full_printer:
            node_strs.extend('  ' + line for line in self.cterm_show.show(node.cterm))
        return node_strs

    def node_attrs(self, kcfg: KCFG, node: KCFG.Node) -> list[str]:
        attrs = []
        if kcfg.is_root(node.id):
            attrs.append('root')
        if kcfg.is_stuck(node.id):
            attrs.append('stuck')
        if kcfg.is_vacuous(node.id):
            attrs.append('vacuous')
        if kcfg.is_leaf(node.id):
            attrs.append('leaf')
        if kcfg.is_split(node.id):
            attrs.append('split')
        attrs.extend(['@' + alias for alias in sorted(kcfg.aliases(node.id))])
        return attrs


class KCFGShow:
    pretty_printer: PrettyPrinter
    node_printer: NodePrinter

    def __init__(self, defn: KDefinition, node_printer: NodePrinter | None = None):
        self.pretty_printer = PrettyPrinter(defn)
        self.node_printer = node_printer if node_printer else NodePrinter(CTermShow(self.pretty_printer.print))

    def node_short_info(self, kcfg: KCFG, node: KCFG.Node) -> list[str]:
        return self.node_printer.print_node(kcfg, node)

    @staticmethod
    def hide_cells(term: KInner, omit_cells: Iterable[str]) -> KInner:
        def _hide_cells(_k: KInner) -> KInner:
            if type(_k) == KApply and _k.label.name in omit_cells:
                return DOTS
            return _k

        if omit_cells:
            return top_down(_hide_cells, term)
        return term

    @staticmethod
    def simplify_config(config: KInner, omit_cells: Iterable[str]) -> KInner:
        config = inline_cell_maps(config)
        config = sort_ac_collections(config)
        config = KCFGShow.hide_cells(config, omit_cells)
        return config

    @staticmethod
    def make_unique_segments(segments: Iterable[tuple[str, Iterable[str]]]) -> Iterable[tuple[str, Iterable[str]]]:
        _segments = []
        used_ids = []
        for id, seg_lines in segments:
            suffix = ''
            counter = 0
            while f'{id}{suffix}' in used_ids:
                suffix = f'_{counter}'
                counter += 1
            new_id = f'{id}{suffix}'
            used_ids.append(new_id)
            _segments.append((f'{new_id}', [l.rstrip() for l in seg_lines]))
        return _segments

    def pretty_segments(self, kcfg: KCFG, minimize: bool = True) -> Iterable[tuple[str, Iterable[str]]]:
        """Return a pretty version of the KCFG in segments.

        Each segment is a tuple of an identifier and a list of lines to be printed for that segment (Tuple[str, Iterable[str]).
        The identifier tells you whether that segment is for a given node, edge, or just pretty spacing ('unknown').
        This is useful for applications which want to pretty print in chunks, so that they can know which printed region corresponds to each node/edge.
        """
        processed_nodes: list[KCFG.Node] = []
        ret_lines: list[tuple[str, list[str]]] = []

        def _multi_line_print(label: str, lines: list[str], default: str = 'None', indent: int = 4) -> list[str]:
            ret_lines = []
            if len(lines) == 0:
                ret_lines.append(f'{label}: {default}')
            else:
                ret_lines.append(f'{label}:')
                ret_lines.extend([f'{indent * " "}{line}' for line in lines])
            return ret_lines

        def _print_csubst(
            csubst: CSubst, subst_first: bool = False, indent: int = 4, minimize: bool = False
        ) -> list[str]:
            _constraint_strs = [
                self.pretty_printer.print(ml_pred_to_bool(constraint, abstract_unsafe=True))
                for constraint in csubst.constraints
            ]
            constraint_strs = _multi_line_print('constraint', _constraint_strs, 'true')
            if len(csubst.subst.minimize()) > 0 and minimize:
                subst_strs = ['subst: ...']
            else:
                _subst_strs = [
                    line
                    for k, v in csubst.subst.minimize().items()
                    for line in f'{k} <- {self.pretty_printer.print(v)}'.split('\n')
                ]
                subst_strs = _multi_line_print('subst', _subst_strs, '.Subst')
            if subst_first:
                return subst_strs + constraint_strs
            return constraint_strs + subst_strs

        def _print_node(node: KCFG.Node) -> list[str]:
            return self.node_short_info(kcfg, node)

        def _print_edge(edge: KCFG.Edge) -> list[str]:
            if edge.depth == 1:
                return ['(' + str(edge.depth) + ' step)']
            else:
                return ['(' + str(edge.depth) + ' steps)']

        def _print_merged_edge(merged_edge: KCFG.MergedEdge) -> list[str]:
            res = '('
            for edge in merged_edge.edges:
                res += f'{edge.depth}|'
            res = res[:-1] + ' steps)'
            return [res] if len(res) < 78 else ['(merged edge)']

        def _print_cover(cover: KCFG.Cover) -> Iterable[str]:
            return _print_csubst(cover.csubst, subst_first=False, indent=4, minimize=minimize)

        def _print_split_edge(split: KCFG.Split, target_id: int) -> list[str]:
            return _print_csubst(split.splits[target_id], subst_first=True, indent=4, minimize=minimize)

        def _print_subgraph(indent: str, curr_node: KCFG.Node, prior_on_trace: list[KCFG.Node]) -> None:
            processed = curr_node in processed_nodes
            processed_nodes.append(curr_node)
            successors = list(kcfg.successors(curr_node.id))

            curr_node_strs = _print_node(curr_node)

            ret_node_lines = []
            suffix = []
            elbow = '├─'
            node_indent = '│   '
            if kcfg.is_root(curr_node.id):
                elbow = '┌─'
            elif processed or not successors:
                elbow = '└─'
                node_indent = '    '
                if curr_node in prior_on_trace:
                    suffix = ['(looped back)', '']
                elif processed and not kcfg.is_leaf(curr_node.id):
                    suffix = ['(continues as previously)', '']
                else:
                    suffix = ['']
            ret_node_lines.append(indent + elbow + ' ' + curr_node_strs[0])
            ret_node_lines.extend(add_indent(indent + node_indent, curr_node_strs[1:]))
            ret_node_lines.extend(add_indent(indent + '   ', suffix))
            ret_lines.append((f'node_{curr_node.id}', ret_node_lines))

            if processed or not successors:
                return
            successor = successors[0]

            if isinstance(successor, KCFG.MultiEdge):
                ret_lines.append(('unknown', [f'{indent}┃']))
                multiedge_label = '1 step' if type(successor) is KCFG.NDBranch else 'branch'
                multiedge_id = 'ndbranch' if type(successor) is KCFG.NDBranch else 'split'
                ret_lines.append(('unknown', [f'{indent}┃ ({multiedge_label})']))

                for target in successor.targets[:-1]:
                    if type(successor) is KCFG.Split:
                        ret_edge_lines = _print_split_edge(successor, target.id)
                        ret_edge_lines = [indent + '┣━━┓ ' + ret_edge_lines[0]] + add_indent(
                            indent + '┃  ┃ ', ret_edge_lines[1:]
                        )
                    elif type(successor) is KCFG.NDBranch:
                        ret_edge_lines = [indent + '┣━━┓ ']
                    else:
                        raise AssertionError()
                    ret_edge_lines.append(indent + '┃  │')
                    ret_lines.append((f'{multiedge_id}_{curr_node.id}_{target.id}', ret_edge_lines))
                    _print_subgraph(indent + '┃  ', target, prior_on_trace + [curr_node])
                target = successor.targets[-1]
                if type(successor) is KCFG.Split:
                    ret_edge_lines = _print_split_edge(successor, target.id)
                    ret_edge_lines = [indent + '┗━━┓ ' + ret_edge_lines[0]] + add_indent(
                        indent + '   ┃ ', ret_edge_lines[1:]
                    )
                elif type(successor) is KCFG.NDBranch:
                    ret_edge_lines = [indent + '┗━━┓ ']
                else:
                    raise AssertionError()
                ret_edge_lines.append(indent + '   │')
                ret_lines.append((f'{multiedge_id}_{curr_node.id}_{target.id}', ret_edge_lines))
                _print_subgraph(indent + '   ', target, prior_on_trace + [curr_node])

            elif isinstance(successor, KCFG.EdgeLike):
                ret_lines.append(('unknown', [f'{indent}│']))

                if type(successor) is KCFG.Edge:
                    ret_edge_lines = []
                    ret_edge_lines.extend(add_indent(indent + '│  ', _print_edge(successor)))
                    ret_lines.append((f'edge_{successor.source.id}_{successor.target.id}', ret_edge_lines))

                elif type(successor) is KCFG.MergedEdge:
                    ret_edge_lines = []
                    ret_edge_lines.extend(add_indent(indent + '│  ', _print_merged_edge(successor)))
                    ret_lines.append((f'merged_edge_{successor.source.id}_{successor.target.id}', ret_edge_lines))

                elif type(successor) is KCFG.Cover:
                    ret_edge_lines = []
                    ret_edge_lines.extend(add_indent(indent + '┊  ', _print_cover(successor)))
                    ret_lines.append((f'cover_{successor.source.id}_{successor.target.id}', ret_edge_lines))

                _print_subgraph(indent, successor.target, prior_on_trace + [curr_node])

        def _sorted_init_nodes() -> tuple[list[KCFG.Node], list[KCFG.Node]]:
            sorted_init_nodes = sorted(node for node in kcfg.nodes if node not in processed_nodes)
            init_nodes = []
            init_leaf_nodes = []
            remaining_nodes = []
            for node in sorted_init_nodes:
                if kcfg.is_root(node.id):
                    if kcfg.is_leaf(node.id):
                        init_leaf_nodes.append(node)
                    else:
                        init_nodes.append(node)
                else:
                    remaining_nodes.append(node)
            return (init_nodes + init_leaf_nodes, remaining_nodes)

        init, _ = _sorted_init_nodes()
        while init:
            ret_lines.append(('unknown', ['']))
            _print_subgraph('', init[0], [])
            init, _ = _sorted_init_nodes()
        _, remaining = _sorted_init_nodes()
        if remaining:
            ret_lines.append(('unknown', ['', 'Remaining Nodes:']))
            for node in remaining:
                ret_node_lines = [''] + _print_node(node)
                ret_lines.append((f'node_{node.id}', ret_node_lines))

        return KCFGShow.make_unique_segments(ret_lines)

    def pretty(
        self,
        kcfg: KCFG,
        minimize: bool = True,
    ) -> Iterable[str]:
        return (line for _, seg_lines in self.pretty_segments(kcfg, minimize=minimize) for line in seg_lines)

    def to_module(
        self,
        cfg: KCFG,
        module_name: str | None = None,
        omit_cells: Iterable[str] = (),
        parseable_output: bool = True,
        defunc_with: KDefinition | None = None,
        imports: Iterable[KImport] = (),
    ) -> KFlatModule:
        def _process_sentence(sent: KSentence) -> KSentence:
            if type(sent) is KRule:
                sent = sent.let(body=KCFGShow.hide_cells(sent.body, omit_cells))
                if parseable_output:
                    sent = sent.let(body=remove_generated_cells(sent.body))
                    sent = minimize_rule_like(sent)
            return sent

        module = cfg.to_module(module_name, defunc_with=defunc_with, imports=imports)
        return module.let(sentences=[_process_sentence(sent) for sent in module.sentences])

    def show(
        self,
        cfg: KCFG,
        nodes: Iterable[NodeIdLike] = (),
        node_deltas: Iterable[tuple[NodeIdLike, NodeIdLike]] = (),
        to_module: bool = False,
        minimize: bool = True,
        omit_cells: Iterable[str] = (),
        module_name: str | None = None,
    ) -> list[str]:
        return list(
            self.show_iter(
                cfg,
                nodes=nodes,
                node_deltas=node_deltas,
                to_module=to_module,
                minimize=minimize,
                omit_cells=omit_cells,
                module_name=module_name,
            )
        )

    def show_iter(
        self,
        cfg: KCFG,
        nodes: Iterable[NodeIdLike] = (),
        node_deltas: Iterable[tuple[NodeIdLike, NodeIdLike]] = (),
        to_module: bool = False,
        minimize: bool = True,
        omit_cells: Iterable[str] = (),
        module_name: str | None = None,
    ) -> Iterator[str]:
        """Yield proof show output line-by-line, avoiding memory accumulation."""
        yield from self.pretty(cfg, minimize=minimize)

        nodes_printed = False

        for node_id in nodes:
            nodes_printed = True
            kast = cfg.node(node_id).cterm.kast
            kast = KCFGShow.hide_cells(kast, omit_cells)
            if minimize:
                kast = minimize_term(kast)
            yield ''
            yield ''
            yield f'Node {node_id}:'
            yield ''
            yield self.pretty_printer.print(kast)
            yield ''

        for node_id_1, node_id_2 in node_deltas:
            nodes_printed = True
            config_1 = KCFGShow.simplify_config(cfg.node(node_id_1).cterm.config, omit_cells)
            config_2 = KCFGShow.simplify_config(cfg.node(node_id_2).cterm.config, omit_cells)
            config_delta = push_down_rewrites(KRewrite(config_1, config_2))
            if minimize:
                config_delta = minimize_term(config_delta)
            yield ''
            yield ''
            yield f'State Delta {node_id_1} => {node_id_2}:'
            yield ''
            yield self.pretty_printer.print(config_delta)
            yield ''

        if not nodes_printed:
            yield ''
        yield ''
        yield ''

        if to_module:
            module = self.to_module(cfg, module_name, omit_cells=omit_cells)
            yield self.pretty_printer.print(module)

    def dot(self, kcfg: KCFG) -> Digraph:
        def _short_label(label: str) -> str:
            return '\n'.join(
                [
                    label_line if len(label_line) < 100 else (label_line[0:100] + ' ...')
                    for label_line in label.split('\n')
                ]
            )

        graph = Digraph()

        for node in kcfg.nodes:
            label = '\n'.join(self.node_short_info(kcfg, node))
            class_attrs = ' '.join(self.node_printer.node_attrs(kcfg, node))
            attrs = {'class': class_attrs} if class_attrs else {}
            graph.node(name=node.id, label=label, **attrs)

        for edge in kcfg.edges():
            depth = edge.depth
            label = f'{depth} steps'
            graph.edge(tail_name=edge.source.id, head_name=edge.target.id, label=f'  {label}        ')

        for cover in kcfg.covers():
            label = ', '.join(
                f'{k} |-> {self.pretty_printer.print(v)}' for k, v in cover.csubst.subst.minimize().items()
            )
            label = _short_label(label)
            attrs = {'class': 'abstraction', 'style': 'dashed'}
            graph.edge(tail_name=cover.source.id, head_name=cover.target.id, label=f'  {label}        ', **attrs)

        for split in kcfg.splits():
            for target_id, csubst in split.splits.items():
                label = '\n#And'.join(
                    f'{self.pretty_printer.print(v)}' for v in split.source.cterm.constraints + csubst.constraints
                )
                graph.edge(tail_name=split.source.id, head_name=target_id, label=f'  {label}        ')

        for ndbranch in kcfg.ndbranches():
            for target in ndbranch.target_ids:
                label = '1 step'
                graph.edge(tail_name=ndbranch.source.id, head_name=target, label=f'  {label}        ')

        return graph

    def dump(self, cfgid: str, cfg: KCFG, dump_dir: Path, dot: bool = False) -> None:
        ensure_dir_path(dump_dir)

        cfg_file = dump_dir / f'{cfgid}.json'
        cfg_file.write_text(cfg.to_json())
        _LOGGER.info(f'Wrote CFG file {cfgid}: {cfg_file}')

        if dot:
            cfg_dot = self.dot(cfg)
            dot_file = dump_dir / f'{cfgid}.dot'
            dot_file.write_text(cfg_dot.source)
            _LOGGER.info(f'Wrote DOT file {cfgid}: {dot_file}')

        nodes_dir = dump_dir / 'nodes'
        ensure_dir_path(nodes_dir)
        for node in cfg.nodes:
            node_file = nodes_dir / f'config_{node.id}.txt'
            node_minimized_file = nodes_dir / f'config_minimized_{node.id}.txt'
            node_constraint_file = nodes_dir / f'constraint_{node.id}.txt'

            config = node.cterm.config
            if not node_file.exists():
                node_file.write_text(self.pretty_printer.print(config))
                _LOGGER.info(f'Wrote node file {cfgid}: {node_file}')
            config = minimize_term(config)
            if not node_minimized_file.exists():
                node_minimized_file.write_text(self.pretty_printer.print(config))
                _LOGGER.info(f'Wrote node file {cfgid}: {node_minimized_file}')
            if not node_constraint_file.exists():
                constraint = mlAnd(node.cterm.constraints)
                node_constraint_file.write_text(self.pretty_printer.print(constraint))
                _LOGGER.info(f'Wrote node file {cfgid}: {node_constraint_file}')

        edges_dir = dump_dir / 'edges'
        ensure_dir_path(edges_dir)
        for edge in cfg.edges():
            edge_file = edges_dir / f'config_{edge.source.id}_{edge.target.id}.txt'
            edge_minimized_file = edges_dir / f'config_minimized_{edge.source.id}_{edge.target.id}.txt'

            config = push_down_rewrites(KRewrite(edge.source.cterm.config, edge.target.cterm.config))
            if not edge_file.exists():
                edge_file.write_text(self.pretty_printer.print(config))
                _LOGGER.info(f'Wrote edge file {cfgid}: {edge_file}')
            config = minimize_term(config)
            if not edge_minimized_file.exists():
                edge_minimized_file.write_text(self.pretty_printer.print(config))
                _LOGGER.info(f'Wrote edge file {cfgid}: {edge_minimized_file}')

        covers_dir = dump_dir / 'covers'
        ensure_dir_path(covers_dir)
        for cover in cfg.covers():
            cover_file = covers_dir / f'config_{cover.source.id}_{cover.target.id}.txt'
            cover_constraint_file = covers_dir / f'constraint_{cover.source.id}_{cover.target.id}.txt'

            subst_equalities = flatten_label(
                '#And', cover.csubst.pred(sort_with=self.pretty_printer.definition, constraints=False)
            )

            if not cover_file.exists():
                cover_file.write_text('\n'.join(self.pretty_printer.print(se) for se in subst_equalities))
                _LOGGER.info(f'Wrote cover file {cfgid}: {cover_file}')
            if not cover_constraint_file.exists():
                cover_constraint_file.write_text(self.pretty_printer.print(cover.csubst.constraint))
                _LOGGER.info(f'Wrote cover file {cfgid}: {cover_constraint_file}')
