from __future__ import annotations

from typing import TYPE_CHECKING

from ..inner import KApply, KLabel, KSort, KToken

if TYPE_CHECKING:
    from typing import Final

    from .. import KInner


K: Final = KSort('K')
K_ITEM: Final = KSort('KItem')
GENERATED_TOP_CELL: Final = KSort('GeneratedTopCell')

# Sentinel sort marking an ML-predicate result sort that could not be inferred from arguments
# (introduced by KDefinition.add_sort_params).  The family also covers uniquely-named variants
# such as `#SortParam{Q0}` once those are generated.  This sort cannot yet be emitted to Kore;
# see pyk/docs/2026-06-01-sortparam-kore-emission.md.
SORT_PARAM_SENTINEL: Final = KSort('#SortParam')

DOTS: Final = KToken('...', K)


def inj(from_sort: KSort, to_sort: KSort, term: KInner) -> KInner:
    return KApply(KLabel('inj', (from_sort, to_sort)), (term,))
