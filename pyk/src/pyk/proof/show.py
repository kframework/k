from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..kcfg.show import KCFGShow, NodePrinter
from ..utils import ensure_dir_path

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from typing import Final

    from graphviz import Digraph

    from ..cterm.show import CTermShow
    from ..kast.outer import KDefinition
    from ..kcfg import KCFG
    from ..kcfg.kcfg import NodeIdLike
    from .reachability import APRProof

_LOGGER: Final = logging.getLogger(__name__)


class APRProofNodePrinter(NodePrinter):
    proof: APRProof

    def __init__(self, proof: APRProof, cterm_show: CTermShow, full_printer: bool = False):
        super().__init__(cterm_show, full_printer=full_printer)
        self.proof = proof

    def node_attrs(self, kcfg: KCFG, node: KCFG.Node) -> list[str]:
        attrs = super().node_attrs(kcfg, node)
        if self.proof.is_init(node.id):
            attrs.append('init')
        if self.proof.is_target(node.id):
            attrs.append('target')
        if self.proof.is_pending(node.id):
            attrs.append('pending')
        if self.proof.is_refuted(node.id):
            attrs.append('refuted')
        if self.proof.is_terminal(node.id):
            attrs.append('terminal')
            if 'stuck' in attrs:
                attrs.remove('stuck')
        if self.proof.is_bounded(node.id):
            attrs.append('bounded')
            if 'stuck' in attrs:
                attrs.remove('stuck')
        return attrs


class APRProofShow:
    kcfg_show: KCFGShow

    def __init__(self, definition: KDefinition, node_printer: NodePrinter | None = None):
        self.kcfg_show = KCFGShow(definition, node_printer=node_printer)

    def pretty_segments(self, proof: APRProof, minimize: bool = True) -> Iterable[tuple[str, Iterable[str]]]:
        ret_lines = list(self.kcfg_show.pretty_segments(proof.kcfg, minimize=minimize))
        if len(proof.pending) > 0:
            target_node_lines = ['', 'Target Node:']
            target_node_lines += self.kcfg_show.node_printer.print_node(proof.kcfg, proof.kcfg.node(proof.target))
            ret_lines.append((f'node_{proof.target}', target_node_lines))
        return KCFGShow.make_unique_segments(ret_lines)

    def pretty(self, proof: APRProof, minimize: bool = True) -> Iterable[str]:
        return (line for _, seg_lines in self.pretty_segments(proof, minimize=minimize) for line in seg_lines)

    def show(
        self,
        proof: APRProof,
        nodes: Iterable[NodeIdLike] = (),
        node_deltas: Iterable[tuple[NodeIdLike, NodeIdLike]] = (),
        to_module: bool = False,
        minimize: bool = True,
        omit_cells: Iterable[str] = (),
    ) -> list[str]:
        return list(
            self.show_iter(
                proof,
                nodes=nodes,
                node_deltas=node_deltas,
                to_module=to_module,
                minimize=minimize,
                omit_cells=omit_cells,
            )
        )

    def show_iter(
        self,
        proof: APRProof,
        nodes: Iterable[NodeIdLike] = (),
        node_deltas: Iterable[tuple[NodeIdLike, NodeIdLike]] = (),
        to_module: bool = False,
        minimize: bool = True,
        omit_cells: Iterable[str] = (),
    ) -> Iterator[str]:
        """Yield proof show output line-by-line, avoiding memory accumulation."""
        yield from self.kcfg_show.show_iter(
            proof.kcfg,
            nodes=nodes,
            node_deltas=node_deltas,
            to_module=to_module,
            minimize=minimize,
            omit_cells=omit_cells,
            module_name=f'SUMMARY-{proof.id.upper().replace("_", "-")}',
        )

    def show_iter_from_disk(
        self,
        proof_dir: Path,
        proof_id: str,
        minimize: bool = True,
    ) -> Iterator[str]:
        """Yield proof show output line-by-line, loading data from disk on demand.

        Unlike show/show_iter, this does not load the entire proof into memory.
        Node CTerms and cover CSubsts are loaded lazily when accessed for printing.
        """
        import json

        from ..kcfg.kcfg import KCFG
        from ..kcfg.lazy import APRProofStub

        proof_subdir = proof_dir / proof_id
        cfg_dir = proof_subdir / 'kcfg'

        # Load KCFG with lazy stubs
        kcfg = KCFG.read_cfg_data_lazy(cfg_dir)

        # If the node_printer is proof-aware, swap in a lightweight stub
        _original_proof = getattr(self.kcfg_show.node_printer, 'proof', None)
        if _original_proof is not None:
            proof_dict = json.loads((proof_subdir / 'proof.json').read_text())
            proof_stub = APRProofStub(proof_dict, kcfg)
            object.__setattr__(self.kcfg_show.node_printer, 'proof', proof_stub)

        # Use existing show_iter with the lazy KCFG
        yield from self.kcfg_show.show_iter(
            kcfg,
            minimize=minimize,
        )

        # Restore original proof if swapped
        if _original_proof is not None:
            object.__setattr__(self.kcfg_show.node_printer, 'proof', _original_proof)

    def dot(self, proof: APRProof) -> Digraph:
        graph = self.kcfg_show.dot(proof.kcfg)
        attrs = {'class': 'target', 'style': 'solid'}
        for node in proof.pending:
            graph.edge(tail_name=node.id, head_name=proof.target, label=' ???', **attrs)
        for node in proof.kcfg.stuck:
            graph.edge(tail_name=node.id, head_name=proof.target, label=' false', **attrs)
        return graph

    def dump(self, proof: APRProof, dump_dir: Path, dot: bool = False) -> None:
        ensure_dir_path(dump_dir)

        proof_file = dump_dir / f'{proof.id}.json'
        proof_file.write_text(proof.json)
        _LOGGER.info(f'Wrote CFG file {proof.id}: {proof_file}')

        if dot:
            proof_dot = self.dot(proof)
            dot_file = dump_dir / f'{proof.id}.dot'
            dot_file.write_text(proof_dot.source)
            _LOGGER.info(f'Wrote DOT file {proof.id}: {dot_file}')

        self.kcfg_show.dump(f'{proof.id}_cfg', proof.kcfg, dump_dir, dot=False)
