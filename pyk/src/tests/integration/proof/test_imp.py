from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pyk.cterm import CSubst, CTerm
from pyk.cterm.show import CTermShow
from pyk.kast.inner import KApply, KSequence, KSort, KToken, KVariable, Subst
from pyk.kast.manip import minimize_term, sort_ac_collections
from pyk.kast.prelude.kbool import BOOL, FALSE, andBool, orBool
from pyk.kast.prelude.kint import intToken
from pyk.kast.prelude.ml import mlAnd, mlBottom, mlEquals, mlEqualsFalse, mlEqualsTrue, mlTop
from pyk.kast.pretty import PrettyPrinter
from pyk.kcfg.semantics import DefaultSemantics
from pyk.kcfg.show import KCFGShow
from pyk.proof import APRProver, ProofStatus
from pyk.proof.proof import parallel_advance_proof
from pyk.proof.reachability import APRFailureInfo, APRProof
from pyk.proof.show import APRProofNodePrinter, APRProofShow
from pyk.testing import KCFGExploreTest, KProveTest, ParallelTest
from pyk.utils import single

from ..utils import K_FILES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Final

    from pytest import TempPathFactory

    from pyk.kast.inner import KInner
    from pyk.kast.outer import KDefinition
    from pyk.kcfg import KCFGExplore
    from pyk.kcfg.semantics import KCFGSemantics
    from pyk.ktool.kprint import KPrint, SymbolTable
    from pyk.ktool.kprove import KProve
    from pyk.proof import Prover

_LOGGER: Final = logging.getLogger(__name__)


@pytest.fixture(scope='function')
def proof_dir(tmp_path_factory: TempPathFactory) -> Path:
    return tmp_path_factory.mktemp('proofs')


class ImpSemantics(DefaultSemantics):
    definition: KDefinition | None

    def __init__(self, definition: KDefinition | None = None):
        super().__init__()
        self.definition = definition

    def is_terminal(self, c: CTerm) -> bool:
        k_cell = c.cell('K_CELL')
        if type(k_cell) is KSequence:
            if len(k_cell) == 0:
                return True
            if len(k_cell) == 1 and type(k_cell[0]) is KVariable:
                return True
        if type(k_cell) is KVariable:
            return True
        return False

    def is_loop(self, c: CTerm) -> bool:
        k_cell = c.cell('K_CELL')
        return (
            type(k_cell) is KSequence
            and len(k_cell) > 0
            and type(k_cell[0]) is KApply
            and k_cell[0].label.name == 'while(_)_'
        )

    def same_loop(self, c1: CTerm, c2: CTerm) -> bool:
        k_cell_1 = c1.cell('K_CELL')
        k_cell_2 = c2.cell('K_CELL')
        if k_cell_1 == k_cell_2 and type(k_cell_1) is KSequence and len(k_cell_1) > 0 and type(k_cell_1[0]) is KApply:
            return k_cell_1[0].label.name == 'while(_)_'
        return False


EMPTY_STATES: Final[list[tuple[str, str]]] = []
EXECUTE_TEST_DATA: Final = (
    (
        'step-1',
        1,
        ('int $n , $s ; $n = 3 ;', '.Map'),
        1,
        ('int $s , .Ids ; $n = 3 ; ~> .K', '$n |-> 0'),
        EMPTY_STATES,
    ),
    (
        'step-2',
        2,
        ('int $n , $s ; $n = 3 ;', '.Map'),
        2,
        ('int .Ids ; $n = 3 ; ~> .K', '$n |-> 0 $s |-> 0'),
        EMPTY_STATES,
    ),
    (
        'branch',
        4,
        ('int $n ; if (_B:Bool) { $n = 1; } else { $n = 2; }', '.Map'),
        2,
        ('if ( _B:Bool ) { $n = 1 ; } else { $n = 2 ; } ~> .K', '$n |-> 0'),
        [('{ $n = 1 ; } ~> .K', '$n |-> 0'), ('{ $n = 2 ; } ~> .K', '$n |-> 0')],
    ),
)

IMPLICATION_FAILURE_TEST_DATA: Final = (
    (
        'different-cell',
        ('int $n ; $n = 0 ;', '.Map'),
        ('int $n ; $n = 1 ;', '.Map'),
        (
            'Matching failed.\n'
            'The following cells failed matching individually (antecedent #Implies consequent):\n'
            'K_CELL: int $n , .Ids ; $n = 0 ; #Implies int $n , .Ids ; $n = 1 ;'
        ),
    ),
    (
        'different-cell-2',
        ('int $n ; $n = X:Int ;', '.Map'),
        ('int $n ; $n = 1 ;', '.Map'),
        (
            'Matching failed.\n'
            'The following cells failed matching individually (antecedent #Implies consequent):\n'
            'K_CELL: int $n , .Ids ; $n = X:Int ; #Implies int $n , .Ids ; $n = 1 ;'
        ),
    ),
    (
        'different-constraint',
        (
            'int $n ; $n = 0 ;',
            '1 |-> A:Int 2 |-> B:Int',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('A', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('B', 'Int'), KToken('2', 'Int')])),
                ]
            ),
        ),
        (
            'int $n ; $n = 0 ;',
            '1 |-> A:Int 2 |-> B:Int',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('A', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('B', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        ),
        (
            'Matching failed.\n'
            'The remaining implication is:\n'
            '{ true #Equals A:Int <Int 1 }\n'
            '#And { true #Equals B:Int <Int 2 } #Implies { true #Equals B:Int <Int 1 }'
        ),
    ),
    (
        'different-constraint-with-match',
        (
            'int $n ; $n = 0 ;',
            '1 |-> A:Int 2 |-> B:Int',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('A', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('B', 'Int'), KToken('2', 'Int')])),
                ]
            ),
        ),
        (
            'int $n ; $n = X:Int ;',
            '1 |-> A:Int 2 |-> B:Int',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('A', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('B', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        ),
        (
            'Matching failed.\n'
            'The remaining implication is:\n'
            '{ true #Equals A:Int <Int 1 }\n'
            '#And { true #Equals B:Int <Int 2 } #Implies { true #Equals B:Int <Int 1 }'
        ),
    ),
    (
        'substitution',
        ('int $n ; $n = 5 ;', '3 |-> 6'),
        ('int $n ; $n = X:Int ;', '3 |-> X:Int'),
        (
            'Matching failed.\n'
            'The following cells failed matching individually (antecedent #Implies consequent):\n'
            'STATE_CELL: 3 |-> 6 #Implies X:Int'
        ),
    ),
)

IMPLIES_TEST_DATA: Final = (
    (
        'constant-subst',
        ('int $n , $s ; $n = 3 ;', '.Map'),
        ('int $n , $s ; $n = X ;', '.Map'),
        CSubst(Subst({'X': intToken(3)})),
    ),
    (
        'variable-subst',
        ('int $n , $s ; $n = Y ;', '.Map'),
        ('int $n , $s ; $n = X ;', '.Map'),
        CSubst(Subst({'X': KVariable('Y', sort=KSort('AExp'))})),
    ),
    (
        'trivial',
        ('int $n , $s ; $n = 3 ;', '.Map'),
        ('int $n , $s ; $n = 3 ;', '.Map'),
        CSubst(Subst({})),
    ),
    (
        'consequent-constraint',
        ('int $n , $s ; $n = 3 ;', '.Map'),
        ('int $n , $s ; $n = X ;', '.Map', mlEqualsTrue(KApply('_<Int_', [KVariable('X'), intToken(3)]))),
        None,
    ),
    (
        'refutation-1',
        ('int $n ; $n = 0 ;', '.Map', mlTop()),
        (
            'int $n ; $n = 0 ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<=Int_', [intToken(0), KVariable('X')])),
                    mlEqualsTrue(KApply('_<=Int_', [intToken(3), KVariable('X')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('X'), intToken(100)])),
                ]
            ),
        ),
        CSubst(Subst({})),
    ),
    (
        'refutation-2',
        ('int $n ; $n = 0 ;', '.Map', mlTop()),
        (
            'int $n ; $n = 0 ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<=Int_', [intToken(0), KVariable('X')])),
                    mlEqualsTrue(KApply('_>Int_', [intToken(0), KVariable('Y')])),
                ]
            ),
        ),
        CSubst(Subst({})),
    ),
    (
        'refutation-3',
        ('int $n ; $n = 0 ;', '.Map', mlTop()),
        (
            'int $n ; $n = 0 ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<=Int_', [KVariable('Y'), KVariable('X')])),
                ]
            ),
        ),
        CSubst(Subst({})),
    ),
    (
        'refutation-4',
        ('int $n ; $n = 0 ;', '.Map', mlTop()),
        (
            'int $n ; $n = 0 ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('X'), KVariable('Y')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('Y'), KVariable('Z')])),
                    mlEqualsTrue(KApply('_<Int_', [KVariable('Z'), KVariable('X')])),
                ]
            ),
        ),
        None,
    ),
    (
        'antecedent-bottom',
        (
            'int $n , $s ; $n = X ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('X'), intToken(3)])),
                    mlEqualsTrue(KApply('_<Int_', [intToken(3), KVariable('X')])),
                ]
            ),
        ),
        ('int $n , $s ; $n = Y ;', '.Map'),
        CSubst(Subst({}), [mlBottom()]),
    ),
)

GET_MODEL_TEST_DATA: Final = (
    (
        'get-model-sat',
        (
            'int $n ; $n = X ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_==Int_', [KVariable('X'), intToken(3)])),
                ]
            ),
        ),
        Subst({'X': intToken(3)}),
    ),
    (
        'get-model-unsat',
        (
            'int $n ; $n = X ;',
            '.Map',
            mlAnd(
                [
                    mlEqualsTrue(KApply('_<Int_', [KVariable('X'), intToken(4)])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X'), intToken(4)])),
                ]
            ),
        ),
        None,
    ),
)

APR_PROVE_TEST_DATA: Iterable[
    tuple[str, Path, str, str, int | None, int | None, Iterable[str], bool, ProofStatus, int]
] = (
    (
        'imp-simple-addition-1',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'addition-1',
        2,
        1,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'imp-simple-addition-2',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'addition-2',
        2,
        7,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'imp-simple-addition-var',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'addition-var',
        2,
        1,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'pre-branch-proved',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'pre-branch-proved',
        2,
        100,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'while-cut-rule',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'while-cut-rule',
        2,
        1,
        ['IMP.while'],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'while-cut-rule-delayed',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'while-cut-rule-delayed',
        4,
        100,
        ['IMP.while'],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'failing-if',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'failing-if',
        10,
        1,
        [],
        True,
        ProofStatus.FAILED,
        2,
    ),
    (
        'imp-simple-sum-10',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'sum-10',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'imp-simple-sum-100',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'sum-100',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'imp-simple-long-branches',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'long-branches',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        2,
    ),
    (
        'imp-if-almost-same-plus',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC-DEPENDENCIES',
        'if-almost-same-plus',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        2,
    ),
    (
        'imp-if-almost-same-times',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'if-almost-same-times',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        2,
    ),
    (
        'imp-use-if-almost-same',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'use-if-almost-same',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        1,  # We can reuse subproofs.
    ),
    (
        'imp-use-if-almost-same-twice',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'use-if-almost-same-twice',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        1,  # We can reuse subproofs.
    ),
    (
        'imp-simple-sum-loop',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'sum-loop',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        2,
    ),
    (
        'imp-simple-sum-N',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'sum-N',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        1,
    ),
    (
        'imp-failing-circularity',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'failing-circularity',
        None,
        None,
        [],
        False,
        ProofStatus.FAILED,
        1,
    ),
    (
        'imp-dep-untrue-fail',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'dep-fail-1',
        None,
        None,
        [],
        False,
        ProofStatus.FAILED,  # because we do NOT admit the dependency
        1,
    ),
    (
        'imp-dep-untrue-admitted',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'dep-fail-1',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,  # because we DO admit the dependency, even though it is untrue
        1,
    ),
)

APR_PROVE_WITH_KCFG_OPTIMS_TEST_DATA: Iterable[
    tuple[str, Path, str, str, int | None, int | None, Iterable[str], bool, ProofStatus, int]
] = (
    (
        'imp-simple-sum-100',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'sum-100',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        3,
    ),
    (
        'imp-simple-long-branches',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'long-branches',
        None,
        None,
        [],
        True,
        ProofStatus.PASSED,
        7,
    ),
)

PATH_CONSTRAINTS_TEST_DATA: Iterable[
    tuple[str, Path, str, str, int | None, int | None, Iterable[str], Iterable[str], str]
] = (
    (
        'imp-simple-fail-branch',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'fail-branch',
        None,
        1,
        [],
        [],
        '{ false #Equals _S:Int <=Int 123 }',
    ),
)


APRBMC_PROVE_TEST_DATA: Iterable[
    tuple[str, Path, str, str, int | None, int | None, int, Iterable[str], Iterable[str], ProofStatus, int]
] = (
    (
        'bmc-loop-concrete-1',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-concrete',
        20,
        20,
        0,
        [],
        ['IMP.while'],
        ProofStatus.PASSED,
        1,
    ),
    (
        'bmc-loop-concrete-2',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-concrete',
        20,
        20,
        1,
        [],
        ['IMP.while'],
        ProofStatus.PASSED,
        1,
    ),
    (
        'bmc-loop-concrete-3',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-concrete',
        20,
        20,
        2,
        [],
        ['IMP.while'],
        ProofStatus.FAILED,
        1,
    ),
    (
        'bmc-loop-symbolic-1',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-symbolic',
        20,
        20,
        0,
        [],
        ['IMP.while'],
        ProofStatus.PASSED,
        2,
    ),
    (
        'bmc-loop-symbolic-2',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-symbolic',
        20,
        20,
        1,
        [],
        ['IMP.while'],
        ProofStatus.FAILED,
        3,
    ),
    (
        'bmc-loop-symbolic-3',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-loop-symbolic',
        20,
        20,
        2,
        [],
        ['IMP.while'],
        ProofStatus.FAILED,
        3,
    ),
    (
        'bmc-two-loops-symbolic-1',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-two-loops-symbolic',
        20,
        20,
        0,
        [],
        ['IMP.while'],
        ProofStatus.PASSED,
        3,
    ),
    (
        'bmc-two-loops-symbolic-2',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'bmc-two-loops-symbolic',
        50,
        20,
        1,
        [],
        ['IMP.while'],
        ProofStatus.FAILED,
        7,
    ),
)

FAILURE_INFO_TEST_DATA: Iterable[tuple[str, Path, str, str, int, int, tuple[KInner], bool]] = (
    (
        'failing-if',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'failing-if',
        0,
        1,
        (mlEquals(KVariable('_B', 'Bool'), FALSE, arg_sort=BOOL),),
        False,
    ),
    (
        'fail-branch',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'fail-branch',
        0,
        1,
        (mlEqualsFalse(KApply('_<=Int_', [KVariable('_S', 'Int'), KToken('123', '')])),),
        False,
    ),
    (
        'fail-fast',
        K_FILES / 'imp-simple-spec.k',
        'IMP-SIMPLE-SPEC',
        'fail-early',
        1,
        1,
        (mlEqualsTrue(KApply('_<=Int_', [KVariable('N', 'Int'), KToken('1', '')])),),
        True,
    ),
)


def leaf_number(proof: APRProof) -> int:
    non_target_leaves = [nd for nd in proof.kcfg.leaves if not proof.is_target(nd.id)]
    return len(non_target_leaves) + len(proof.kcfg.predecessors(proof.target))


class TestImpProof(KCFGExploreTest, KProveTest):
    KOMPILE_MAIN_FILE = K_FILES / 'imp-verification.k'

    def semantics(self, definition: KDefinition) -> KCFGSemantics:
        return ImpSemantics(definition)

    @staticmethod
    def _update_symbol_table(symbol_table: SymbolTable) -> None:
        symbol_table['.List{"_,_"}_Ids'] = lambda: '.Ids'

    @staticmethod
    def config(kprint: KPrint, k: str, state: str, constraint: KInner | None = None) -> CTerm:
        k_parsed = kprint.parse_token(KToken(k, 'Pgm'), as_rule=True)
        state_parsed = kprint.parse_token(KToken(state, 'Map'), as_rule=True)
        _config = CTerm(
            KApply(
                '<generatedTop>',
                KApply(
                    '<T>',
                    (
                        KApply('<k>', KSequence(k_parsed)),
                        KApply('<state>', state_parsed),
                    ),
                ),
                KVariable('GENERATED_COUNTER_CELL'),
            ),
        )
        if constraint is not None:
            _config = _config.add_constraint(constraint)
        return _config

    @pytest.mark.parametrize(
        'test_id,depth,pre,expected_depth,expected_post,expected_next_states',
        EXECUTE_TEST_DATA,
        ids=[test_id for test_id, *_ in EXECUTE_TEST_DATA],
    )
    def test_execute(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        depth: int,
        pre: tuple[str, str],
        expected_depth: int,
        expected_post: tuple[str, str],
        expected_next_states: Iterable[tuple[str, str]],
    ) -> None:
        # Given
        k, state = pre
        expected_k, expected_state = expected_post

        # When
        exec_res = kcfg_explore.cterm_symbolic.execute(self.config(kprove, k, state), depth=depth)
        actual_k = kcfg_explore.pretty_print(exec_res.state.cell('K_CELL'))
        actual_state = kcfg_explore.pretty_print(sort_ac_collections(exec_res.state.cell('STATE_CELL')))
        actual_depth = exec_res.depth

        actual_next_states = [
            (
                kcfg_explore.pretty_print(s.cell('K_CELL')),
                kcfg_explore.pretty_print(s.cell('STATE_CELL')),
            )
            for s, _ in exec_res.next_states
        ]

        # Then
        assert actual_k == expected_k
        assert actual_state == expected_state
        assert actual_depth == expected_depth
        assert set(actual_next_states) == set(expected_next_states)

    @pytest.mark.parametrize(
        'test_id,cterm,expected',
        GET_MODEL_TEST_DATA,
        ids=[test_id for test_id, *_ in GET_MODEL_TEST_DATA],
    )
    def test_get_model(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        cterm: CTerm,
        test_id: str,
        expected: Subst | None,
    ) -> None:
        # Given
        cterm_term = self.config(kprove, *cterm)

        # When
        actual = kcfg_explore.cterm_symbolic.get_model(cterm_term)

        # Then
        assert actual == expected

    @pytest.mark.parametrize(
        'test_id,antecedent,consequent,expected',
        IMPLIES_TEST_DATA,
        ids=[test_id for test_id, *_ in IMPLIES_TEST_DATA],
    )
    def test_implies(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        antecedent: tuple[str, str] | tuple[str, str, KInner],
        consequent: tuple[str, str] | tuple[str, str, KInner],
        expected: CSubst | None,
    ) -> None:
        if test_id in ['refutation-2']:
            pytest.skip()

        # Given
        antecedent_term = self.config(kprove, *antecedent)
        consequent_term = self.config(kprove, *consequent)

        # When
        actual = kcfg_explore.cterm_symbolic.implies(antecedent_term, consequent_term)

        # Then
        assert actual.csubst == expected

    def test_assume_defined(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
    ) -> None:
        # Given
        k, state = ('PGM', '( $n |-> 0 ) MAP')
        config = self.config(kprove, k, state)

        constraint = mlEqualsFalse(
            KApply('_in_keys(_)_MAP_Bool_KItem_Map', KToken('$n', 'Id'), KVariable('MAP', 'Map'))
        )
        expected = config.add_constraint(constraint)

        # When
        actual = kcfg_explore.cterm_symbolic.assume_defined(config)

        # Then
        assert actual == expected

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,max_iterations,max_depth,cut_rules,admit_deps,proof_status,expected_leaf_number',
        APR_PROVE_TEST_DATA,
        ids=[test_id for test_id, *_ in APR_PROVE_TEST_DATA],
    )
    def test_all_path_reachability_prove(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        max_iterations: int | None,
        max_depth: int | None,
        cut_rules: Iterable[str],
        admit_deps: bool,
        proof_status: ProofStatus,
        expected_leaf_number: int,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        proof_dir = tmp_path_factory.mktemp(f'apr_tmp_proofs-{test_id}')
        spec_modules = kprove.parse_modules(Path(spec_file), module_name=spec_module)
        spec_label = f'{spec_module}.{claim_id}'
        proofs = APRProof.from_spec_modules(
            kprove.definition,
            spec_modules,
            spec_labels=[spec_label],
            logs={},
            proof_dir=proof_dir,
        )
        proof = single([p for p in proofs if p.id == spec_label])
        if admit_deps:
            for subproof in proof.subproofs:
                subproof.admit()
                subproof.write_proof_data()

        prover = APRProver(kcfg_explore=kcfg_explore, execute_depth=max_depth, cut_point_rules=cut_rules)
        prover.advance_proof(proof, max_iterations=max_iterations)

        kcfg_show = KCFGShow(
            kprove.definition,
            node_printer=APRProofNodePrinter(
                proof, CTermShow(PrettyPrinter(kprove.definition).print), full_printer=True
            ),
        )
        cfg_lines = kcfg_show.show(proof.kcfg)
        _LOGGER.info('\n'.join(cfg_lines))

        # Verify show_iter_from_disk produces identical output
        apr_show = APRProofShow(kprove.definition, node_printer=kcfg_show.node_printer)
        disk_lines = list(apr_show.show_iter_from_disk(proof_dir, proof.id))
        assert cfg_lines == disk_lines, 'show_iter_from_disk output differs from show'

        assert proof.status == proof_status
        assert leaf_number(proof) == expected_leaf_number

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,max_iterations,max_depth,cut_rules,admit_deps,proof_status,expected_nodes',
        APR_PROVE_WITH_KCFG_OPTIMS_TEST_DATA,
        ids=[test_id for test_id, *_ in APR_PROVE_WITH_KCFG_OPTIMS_TEST_DATA],
    )
    def test_all_path_reachability_prove_with_kcfg_optims(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        max_iterations: int | None,
        max_depth: int | None,
        cut_rules: Iterable[str],
        admit_deps: bool,
        proof_status: ProofStatus,
        expected_nodes: int,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        proof_dir = tmp_path_factory.mktemp(f'apr_tmp_proofs-{test_id}')
        spec_modules = kprove.parse_modules(Path(spec_file), module_name=spec_module)
        spec_label = f'{spec_module}.{claim_id}'
        proofs = APRProof.from_spec_modules(
            kprove.definition,
            spec_modules,
            spec_labels=[spec_label],
            logs={},
            proof_dir=proof_dir,
        )
        proof = single([p for p in proofs if p.id == spec_label])
        if admit_deps:
            for subproof in proof.subproofs:
                subproof.admit()
                subproof.write_proof_data()

        prover = APRProver(
            kcfg_explore=kcfg_explore, execute_depth=max_depth, cut_point_rules=cut_rules, optimize_kcfg=True
        )
        prover.advance_proof(proof, max_iterations=max_iterations)

        kcfg_show = KCFGShow(
            kprove.definition,
            node_printer=APRProofNodePrinter(
                proof, CTermShow(PrettyPrinter(kprove.definition).print), full_printer=True
            ),
        )
        cfg_lines = kcfg_show.show(proof.kcfg)
        _LOGGER.info('\n'.join(cfg_lines))

        # Verify show_iter_from_disk produces identical output
        apr_show = APRProofShow(kprove.definition, node_printer=kcfg_show.node_printer)
        disk_lines = list(apr_show.show_iter_from_disk(proof_dir, proof.id))
        assert cfg_lines == disk_lines, 'show_iter_from_disk output differs from show'

        assert proof.status == proof_status
        assert len(proof.kcfg._nodes) == expected_nodes

    def test_terminal_node_subsumption(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        test_id: str = 'imp-terminal-node-subsumption'
        spec_file: Path = K_FILES / 'imp-simple-spec.k'
        spec_module: str = 'IMP-SIMPLE-SPEC'
        claim_id: str = 'terminal-node-subsumption'
        cut_rules: Iterable[str] = []
        proof_dir = tmp_path_factory.mktemp(f'apr_tmp_proofs-{test_id}')
        spec_modules = kprove.parse_modules(Path(spec_file), module_name=spec_module)
        spec_label = f'{spec_module}.{claim_id}'
        proofs = APRProof.from_spec_modules(
            kprove.definition,
            spec_modules,
            spec_labels=[spec_label],
            logs={},
            proof_dir=proof_dir,
        )
        proof = single([p for p in proofs if p.id == spec_label])
        prover = APRProver(kcfg_explore=kcfg_explore, execute_depth=7, cut_point_rules=cut_rules)
        prover.advance_proof(proof, max_iterations=1)
        # We have reached a terminal node, but not yet checked subsumption
        assert proof.status != ProofStatus.PASSED
        # The next advance only checks subsumption
        prover.advance_proof(proof, max_iterations=1)
        assert proof.status == ProofStatus.PASSED

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,max_iterations,max_depth,terminal_rules,cut_rules,expected_constraint',
        PATH_CONSTRAINTS_TEST_DATA,
        ids=[test_id for test_id, *_ in PATH_CONSTRAINTS_TEST_DATA],
    )
    def test_collect_path_constraints(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        proof_dir: Path,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        max_iterations: int | None,
        max_depth: int | None,
        terminal_rules: Iterable[str],
        cut_rules: Iterable[str],
        expected_constraint: str,
    ) -> None:
        def _node_printer(cterm: CTerm) -> list[str]:
            _kast = minimize_term(cterm.kast)
            return kcfg_explore.pretty_print(_kast).split('\n')

        claim = single(
            kprove.get_claims(Path(spec_file), spec_module_name=spec_module, claim_labels=[f'{spec_module}.{claim_id}'])
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir)
        prover = APRProver(
            kcfg_explore=kcfg_explore,
            execute_depth=max_depth,
            terminal_rules=terminal_rules,
            cut_point_rules=cut_rules,
        )
        prover.advance_proof(proof, max_iterations=max_iterations)

        assert len(proof.failing) == 1
        path_constraint = proof.path_constraints(proof.failing[0].id)
        actual_constraint = kcfg_explore.pretty_print(path_constraint).replace('\n', ' ')
        assert actual_constraint == expected_constraint

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,max_iterations,max_depth,bmc_depth,terminal_rules,cut_rules,proof_status,expected_leaf_number',
        APRBMC_PROVE_TEST_DATA,
        ids=[test_id for test_id, *_ in APRBMC_PROVE_TEST_DATA],
    )
    def test_all_path_bmc_reachability_prove(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        max_iterations: int | None,
        max_depth: int | None,
        bmc_depth: int,
        terminal_rules: Iterable[str],
        cut_rules: Iterable[str],
        proof_status: ProofStatus,
        expected_leaf_number: int,
    ) -> None:
        claim = single(
            kprove.get_claims(Path(spec_file), spec_module_name=spec_module, claim_labels=[f'{spec_module}.{claim_id}'])
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, bmc_depth=bmc_depth)
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(
            kcfg_explore=kcfg_explore,
            execute_depth=max_depth,
            terminal_rules=terminal_rules,
            cut_point_rules=cut_rules,
        )
        prover.advance_proof(proof, max_iterations=max_iterations)

        kcfg_show = KCFGShow(
            kprove.definition,
            node_printer=APRProofNodePrinter(
                proof, CTermShow(PrettyPrinter(kprove.definition).print), full_printer=True
            ),
        )
        cfg_lines = kcfg_show.show(proof.kcfg)
        _LOGGER.info('\n'.join(cfg_lines))

        assert proof.status == proof_status
        assert leaf_number(proof) == expected_leaf_number

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,expected_pending,expected_failing,path_conditions,fail_fast',
        FAILURE_INFO_TEST_DATA,
        ids=[test_id for test_id, *_ in FAILURE_INFO_TEST_DATA],
    )
    def test_failure_info(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        expected_pending: int,
        expected_failing: int,
        path_conditions: tuple[KInner],
        fail_fast: bool,
    ) -> None:
        claim = single(
            kprove.get_claims(Path(spec_file), spec_module_name=spec_module, claim_labels=[f'{spec_module}.{claim_id}'])
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={})
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=fail_fast)

        failure_info = prover.failure_info(proof)
        assert isinstance(failure_info, APRFailureInfo)

        actual_pending = len(failure_info.pending_nodes)
        actual_failing = len(failure_info.failing_nodes)

        assert expected_pending == actual_pending
        assert expected_failing == actual_failing

        actual_path_conds = set({path_condition for _, path_condition in failure_info.path_conditions.items()})
        expected_path_conds = set({kprove.pretty_print(condition) for condition in path_conditions})

        assert actual_path_conds == expected_path_conds

    def test_proof_no_progress_on_reload(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        proof_dir: Path,
    ) -> None:

        spec_file = K_FILES / 'imp-simple-spec.k'
        spec_module = 'IMP-SIMPLE-SPEC'
        claim_id = 'fail-early'
        expected_pending = 1
        expected_failing = 1

        claim = single(
            kprove.get_claims(Path(spec_file), spec_module_name=spec_module, claim_labels=[f'{spec_module}.{claim_id}'])
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir)
        proof_id = proof.id
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=True)

        initial_failure_info = proof.failure_info
        assert isinstance(initial_failure_info, APRFailureInfo)

        # reload proof from disk
        proof = APRProof.read_proof_data(proof_dir, proof_id)
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=True)

        final_failure_info = proof.failure_info
        assert isinstance(final_failure_info, APRFailureInfo)

        assert expected_pending == len(final_failure_info.pending_nodes)
        assert expected_failing == len(final_failure_info.failing_nodes)

        assert initial_failure_info == final_failure_info

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,expected_pending,expected_failing,path_conditions,fail_fast',
        FAILURE_INFO_TEST_DATA,
        ids=[test_id for test_id, *_ in FAILURE_INFO_TEST_DATA],
    )
    def test_failure_info_recomputed_on_proof_reinit(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        expected_pending: int,
        expected_failing: int,
        path_conditions: tuple[KInner],
        proof_dir: Path,
        fail_fast: bool,
    ) -> None:
        claim = single(
            kprove.get_claims(Path(spec_file), spec_module_name=spec_module, claim_labels=[f'{spec_module}.{claim_id}'])
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir)
        proof_id = proof.id
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=fail_fast)

        # reload proof from disk
        proof = APRProof.read_proof_data(proof_dir, proof_id)
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=fail_fast)

        failure_info = proof.failure_info
        assert isinstance(failure_info, APRFailureInfo)

        actual_pending = len(failure_info.pending_nodes)
        actual_failing = len(failure_info.failing_nodes)

        assert expected_pending == actual_pending
        assert expected_failing == actual_failing

        actual_path_conds = set({path_condition for _, path_condition in failure_info.path_conditions.items()})
        expected_path_conds = set({kprove.pretty_print(condition) for condition in path_conditions})

        assert actual_path_conds == expected_path_conds

    def test_apr_prove_read_write_node_data(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        proof_dir: Path,
    ) -> None:
        claim = single(
            kprove.get_claims(
                Path(K_FILES / 'imp-simple-spec.k'),
                spec_module_name='IMP-SIMPLE-SPEC',
                claim_labels=['IMP-SIMPLE-SPEC.addition-1'],
            )
        )
        proofs_dir = proof_dir

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proofs_dir)
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover.advance_proof(proof)

        proof_from_disk = APRProof.read_proof_data(proof_dir=proofs_dir, id=proof.id)

        assert proof.dict == proof_from_disk.dict
        assert proof.kcfg.nodes == proof_from_disk.kcfg.nodes

    def test_aprbmc_prove_read_write_node_data(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        proof_dir: Path,
    ) -> None:
        claim = single(
            kprove.get_claims(
                Path(K_FILES / 'imp-simple-spec.k'),
                spec_module_name='IMP-SIMPLE-SPEC',
                claim_labels=['IMP-SIMPLE-SPEC.addition-1'],
            )
        )
        proofs_dir = proof_dir

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proofs_dir, bmc_depth=3)
        kcfg_explore.simplify(proof.kcfg, {})
        prover = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover.advance_proof(proof)

        proof_from_disk = APRProof.read_proof_data(proof_dir=proofs_dir, id=proof.id)

        assert proof.dict == proof_from_disk.dict
        assert proof.kcfg.nodes == proof_from_disk.kcfg.nodes

    def test_apr_prove_auto_evict(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        claim = single(
            kprove.get_claims(
                Path(K_FILES / 'imp-simple-spec.k'),
                spec_module_name='IMP-SIMPLE-SPEC',
                claim_labels=['IMP-SIMPLE-SPEC.addition-1'],
            )
        )

        # Run without auto_evict
        proof_dir_base = tmp_path_factory.mktemp('apr_auto_evict_base')
        proof_base = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir_base)
        kcfg_explore.simplify(proof_base.kcfg, {})
        prover_base = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover_base.advance_proof(proof_base)

        # Run with auto_evict
        proof_dir_evict = tmp_path_factory.mktemp('apr_auto_evict_evict')
        proof_evict = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir_evict, auto_evict=True)
        kcfg_explore.simplify(proof_evict.kcfg, {})
        prover_evict = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover_evict.advance_proof(proof_evict)

        # Verify eviction actually happened
        evicted = [n for n in proof_evict.kcfg.nodes if n._cterm is None]
        assert len(evicted) > 0, 'Expected at least one evicted node'

        assert proof_base.status == proof_evict.status
        assert proof_base.dict == proof_evict.dict

    def test_apr_prove_auto_evict_resume(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        claim = single(
            kprove.get_claims(
                Path(K_FILES / 'imp-simple-spec.k'),
                spec_module_name='IMP-SIMPLE-SPEC',
                claim_labels=['IMP-SIMPLE-SPEC.addition-2'],
            )
        )

        # Run baseline to completion
        proof_dir_base = tmp_path_factory.mktemp('apr_auto_evict_resume_base')
        proof_base = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir_base)
        kcfg_explore.simplify(proof_base.kcfg, {})
        prover_base = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover_base.advance_proof(proof_base)

        # Run partial proof (1 iteration), save to disk
        proof_dir_resume = tmp_path_factory.mktemp('apr_auto_evict_resume')
        proof_partial = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir_resume)
        kcfg_explore.simplify(proof_partial.kcfg, {})
        prover_partial = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover_partial.advance_proof(proof_partial, max_iterations=1)
        proof_partial.write_proof_data()

        # Resume from disk with auto_evict=True
        proof_resumed = APRProof.read_proof_data(proof_dir_resume, proof_partial.id, auto_evict=True)
        prover_resumed = APRProver(kcfg_explore=kcfg_explore, execute_depth=1)
        prover_resumed.advance_proof(proof_resumed)

        # Verify eviction actually happened
        evicted = [n for n in proof_resumed.kcfg.nodes if n._cterm is None]
        assert len(evicted) > 0, 'Expected at least one evicted node'

        assert proof_base.status == proof_resumed.status
        assert proof_base.dict == proof_resumed.dict

    def test_fail_fast(
        self,
        kprove: KProve,
        kcfg_explore: KCFGExplore,
        proof_dir: Path,
    ) -> None:
        claim = single(
            kprove.get_claims(
                K_FILES / 'imp-simple-spec.k',
                spec_module_name='IMP-SIMPLE-SPEC',
                claim_labels=['IMP-SIMPLE-SPEC.fail-early'],
            )
        )

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir)
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=False)

        # Both branches will be checked and fail (fail_fast=False)
        assert len(proof.kcfg.leaves) == 3
        assert len(proof.pending) == 0
        assert len(proof.terminal_ids) == 3
        assert len(proof.failing) == 2

        proof = APRProof.from_claim(kprove.definition, claim, logs={}, proof_dir=proof_dir)
        prover = APRProver(kcfg_explore=kcfg_explore)
        prover.advance_proof(proof, fail_fast=True)

        # First branch will be reached first and terminate the proof, leaving the second long branch pending (fail_fast=True)
        assert len(proof.kcfg.leaves) == 3
        assert len(proof.pending) == 1
        assert len(proof.terminal_ids) == 2
        assert len(proof.failing) == 1

    def test_anti_unify_forget_values(
        self,
        kcfg_explore: KCFGExplore,
        kprove: KProve,
    ) -> None:
        cterm1 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> X:Int',
            constraint=mlAnd(
                [
                    mlEqualsTrue(KApply('_>Int_', [KVariable('K', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('Y', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        )
        cterm2 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> Y:Int',
            constraint=mlAnd(
                [
                    mlEqualsTrue(KApply('_>Int_', [KVariable('K', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('Y', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        )

        anti_unifier, subst1, subst2 = cterm1.anti_unify(cterm2, keep_values=False, kdef=kprove.definition)

        k_cell = anti_unifier.cell('STATE_CELL')
        assert type(k_cell) is KApply
        assert k_cell.label.name == '_|->_'
        assert type(k_cell.args[1]) is KVariable
        abstracted_var: KVariable = k_cell.args[1]

        expected_anti_unifier = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state=f'N |-> {abstracted_var.name}:Int',
            constraint=mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
        )

        assert anti_unifier == expected_anti_unifier

    def test_anti_unify_keep_values(
        self,
        kcfg_explore: KCFGExplore,
        kprove: KProve,
    ) -> None:
        cterm1 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> X:Int',
            constraint=mlAnd(
                [
                    mlEqualsTrue(KApply('_>Int_', [KVariable('K', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('Y', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('R', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        )
        cterm2 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> Y:Int',
            constraint=mlAnd(
                [
                    mlEqualsTrue(KApply('_>Int_', [KVariable('K', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('Y', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_<=Int_', [KVariable('R', 'Int'), KToken('1', 'Int')])),
                ]
            ),
        )

        anti_unifier, subst1, subst2 = cterm1.anti_unify(cterm2, keep_values=True, kdef=kprove.definition)

        k_cell = anti_unifier.cell('STATE_CELL')
        assert type(k_cell) is KApply
        assert k_cell.label.name == '_|->_'
        assert type(k_cell.args[1]) is KVariable
        abstracted_var: KVariable = k_cell.args[1]

        expected_anti_unifier = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state=f'N |-> {abstracted_var.name}:Int',
            constraint=mlAnd(
                [
                    mlEqualsTrue(KApply('_>Int_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('X', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(KApply('_>Int_', [KVariable('Y', 'Int'), KToken('1', 'Int')])),
                    mlEqualsTrue(
                        orBool(
                            [
                                andBool(
                                    [
                                        KApply('_==K_', [KVariable(name=abstracted_var.name), KVariable('X', 'Int')]),
                                        KApply('_>Int_', [KVariable('R', 'Int'), KToken('1', 'Int')]),
                                    ]
                                ),
                                andBool(
                                    [
                                        KApply('_==K_', [KVariable(name=abstracted_var.name), KVariable('Y', 'Int')]),
                                        KApply('_<=Int_', [KVariable('R', 'Int'), KToken('1', 'Int')]),
                                    ]
                                ),
                            ]
                        )
                    ),
                ]
            ),
        )

        assert anti_unifier == expected_anti_unifier

    def test_anti_unify_subst_true(
        self,
        kcfg_explore: KCFGExplore,
        kprove: KProve,
    ) -> None:
        cterm1 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> 0',
            constraint=mlEqualsTrue(KApply('_==K_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
        )
        cterm2 = self.config(
            kprint=kprove,
            k='int $n ; { }',
            state='N |-> 0',
            constraint=mlEqualsTrue(KApply('_==K_', [KVariable('N', 'Int'), KToken('1', 'Int')])),
        )

        anti_unifier, _, _ = cterm1.anti_unify(cterm2, keep_values=True, kdef=kprove.definition)

        assert anti_unifier == cterm1

    @pytest.mark.parametrize(
        'test_id,antecedent,consequent,expected',
        IMPLICATION_FAILURE_TEST_DATA,
        ids=[test_id for test_id, *_ in IMPLICATION_FAILURE_TEST_DATA],
    )
    def test_implication_failure_reason(
        self,
        kcfg_explore: KCFGExplore,
        kprove: KProve,
        test_id: str,
        antecedent: tuple[str, str] | tuple[str, str, KInner],
        consequent: tuple[str, str] | tuple[str, str, KInner],
        expected: str,
    ) -> None:
        antecedent_term = self.config(kprove, *antecedent)
        consequent_term = self.config(kprove, *consequent)

        passed, actual = kcfg_explore.implication_failure_reason(antecedent_term, consequent_term)

        assert not passed
        assert actual == expected


class TestImpParallelProof(ParallelTest, KProveTest):
    KOMPILE_MAIN_FILE = K_FILES / 'imp-verification.k'

    def semantics(self, definition: KDefinition) -> KCFGSemantics:
        return ImpSemantics(definition)

    @pytest.mark.parametrize(
        'test_id,spec_file,spec_module,claim_id,max_iterations,max_depth,cut_rules,admit_deps,proof_status,expected_leaf_number',
        APR_PROVE_TEST_DATA,
        ids=[test_id for test_id, *_ in APR_PROVE_TEST_DATA],
    )
    def test_all_path_reachability_prove_parallel(
        self,
        kprove: KProve,
        test_id: str,
        spec_file: str,
        spec_module: str,
        claim_id: str,
        max_iterations: int | None,
        max_depth: int | None,
        cut_rules: Iterable[str],
        admit_deps: bool,
        proof_status: ProofStatus,
        expected_leaf_number: int,
        tmp_path_factory: TempPathFactory,
        create_prover: Callable[[int | None, Iterable[str]], Prover],
    ) -> None:
        proof_dir = tmp_path_factory.mktemp(f'apr_tmp_proofs-{test_id}')
        spec_modules = kprove.parse_modules(Path(spec_file), module_name=spec_module)
        spec_label = f'{spec_module}.{claim_id}'
        proofs = APRProof.from_spec_modules(
            kprove.definition,
            spec_modules,
            spec_labels=[spec_label],
            logs={},
            proof_dir=proof_dir,
        )
        proof = single([p for p in proofs if p.id == spec_label])
        if admit_deps:
            for subproof in proof.subproofs:
                subproof.admit()
                subproof.write_proof_data()

        _create_prover = partial(create_prover, max_depth, cut_rules)

        parallel_advance_proof(proof=proof, max_iterations=max_iterations, create_prover=_create_prover, max_workers=2)

        kcfg_show = KCFGShow(
            kprove.definition,
            node_printer=APRProofNodePrinter(
                proof, CTermShow(PrettyPrinter(kprove.definition).print), full_printer=True
            ),
        )
        cfg_lines = kcfg_show.show(proof.kcfg)
        _LOGGER.info('\n'.join(cfg_lines))

        # Verify show_iter_from_disk produces identical output
        apr_show = APRProofShow(kprove.definition, node_printer=kcfg_show.node_printer)
        disk_lines = list(apr_show.show_iter_from_disk(proof_dir, proof.id))
        assert cfg_lines == disk_lines, 'show_iter_from_disk output differs from show'

        assert proof.status == proof_status
        assert leaf_number(proof) == expected_leaf_number

    def test_all_path_reachability_prove_parallel_resources(
        self,
        kprove: KProve,
        tmp_path_factory: TempPathFactory,
        create_prover: Callable[[int, Iterable[str]], Prover],
    ) -> None:

        test_id = 'imp-simple-addition-1'
        spec_file = K_FILES / 'imp-simple-spec.k'
        spec_module = 'IMP-SIMPLE-SPEC'
        claim_id = 'addition-1'

        proof_dir = tmp_path_factory.mktemp(f'apr_tmp_proofs-{test_id}')
        spec_modules = kprove.parse_modules(Path(spec_file), module_name=spec_module)
        spec_label = f'{spec_module}.{claim_id}'
        proofs = APRProof.from_spec_modules(
            kprove.definition,
            spec_modules,
            spec_labels=[spec_label],
            logs={},
            proof_dir=proof_dir,
        )
        proof = single([p for p in proofs if p.id == spec_label])

        _create_prover = partial(create_prover, 1, [])

        provers_created = 0

        class MyAPRProver(APRProver):
            provers_closed: int = 0

            def close(self) -> None:
                MyAPRProver.provers_closed += 1
                super().close()

        def create_prover_res_counter() -> APRProver:
            nonlocal provers_created
            provers_created += 1
            prover = _create_prover()
            prover.__class__ = MyAPRProver
            assert type(prover) is MyAPRProver
            return prover

        parallel_advance_proof(proof=proof, max_iterations=2, create_prover=create_prover_res_counter, max_workers=2)

        assert provers_created == MyAPRProver.provers_closed
