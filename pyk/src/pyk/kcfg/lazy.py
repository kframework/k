"""Stubs for memory-efficient proof display.

LazyCSubst defers CSubst parsing until accessed.
APRProofStub answers proof-level queries from proof.json metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from ..cterm import CSubst
    from ..kast.inner import KInner
    from .kcfg import KCFG


class APRProofStub:
    """Lightweight stub for APRProof — answers proof-level queries without loading the full proof.

    Duck-types enough of APRProof for APRProofNodePrinter.node_attrs() to work.
    Uses proof.json metadata + the KCFG for graph queries.
    """

    def __init__(self, proof_dict: dict[str, Any], kcfg: KCFG) -> None:
        self.init = int(proof_dict['init'])
        self.target = int(proof_dict['target'])
        self._terminal_ids = set(proof_dict.get('terminal') or [])
        self._bounded_ids = set(proof_dict.get('bounded') or [])
        self._refuted_ids = {int(k) for k in (proof_dict.get('node_refutations') or {}).keys()}
        self.kcfg = kcfg

    def _resolve(self, node_id: int) -> int:
        return node_id

    def is_init(self, node_id: int) -> bool:
        return node_id == self.init

    def is_target(self, node_id: int) -> bool:
        return node_id == self.target

    def is_terminal(self, node_id: int) -> bool:
        return node_id in self._terminal_ids

    def is_explorable(self, node_id: int) -> bool:
        return (
            self.kcfg.is_leaf(node_id)
            and not self.is_terminal(node_id)
            and not self.kcfg.is_stuck(node_id)
            and not self.kcfg.is_vacuous(node_id)
        )

    def is_pending(self, node_id: int) -> bool:
        return (
            self.is_explorable(node_id)
            and not self.is_target(node_id)
            and not self.is_refuted(node_id)
            and not self.is_bounded(node_id)
        )

    def is_refuted(self, node_id: int) -> bool:
        return node_id in self._refuted_ids

    def is_bounded(self, node_id: int) -> bool:
        return node_id in self._bounded_ids


class LazyCSubst:
    """Duck-types CSubst. Loads from a JSON dict on first access."""

    _raw: dict[str, Any]
    _csubst: CSubst | None

    def __init__(self, raw_dict: dict[str, Any]) -> None:
        self._raw: dict[str, Any] = raw_dict
        self._csubst = None

    def _load(self) -> CSubst:
        if self._csubst is None:
            from ..cterm import CSubst

            self._csubst = CSubst.from_dict(self._raw)
        return self._csubst

    @property
    def constraints(self) -> tuple:
        return self._load().constraints

    @property
    def subst(self) -> object:
        return self._load().subst

    def pred(self, *args: Any, **kwargs: Any) -> KInner:
        return self._load().pred(*args, **kwargs)

    def to_dict(self) -> dict:
        return self._load().to_dict()

    def evict(self) -> None:
        """Release the loaded CSubst from memory, keep raw dict for reload."""
        self._csubst = None
