from __future__ import annotations

import hashlib
from dataclasses import asdict
from itertools import count
from string import Template
from typing import TYPE_CHECKING

import pytest

from pyk.kore.parser import KoreParser
from pyk.kore.prelude import (
    BOOL,
    INT,
    SORT_GENERATED_COUNTER_CELL,
    SORT_GENERATED_TOP_CELL,
    SORT_K,
    SORT_K_ITEM,
    TRUE,
    and_bool,
    eq_int,
    generated_counter,
    generated_top,
    gt_int,
    inj,
    int_dv,
    k,
    kseq,
    le_int,
)
from pyk.kore.rpc import (
    BoosterServer,
    BranchingResult,
    CutPointResult,
    DepthBoundResult,
    DuplicateModuleError,
    GetModelResult,
    ImplicationError,
    ImpliesResult,
    ImpliesStatus,
    InvalidModuleError,
    LogOrigin,
    LogRewrite,
    RewriteFailure,
    RewriteSuccess,
    SatResult,
    State,
    StuckResult,
    TerminalResult,
    TimeoutResult,
    UnknownModuleError,
    UnknownResult,
    UnsatResult,
    VacuousResult,
)
from pyk.kore.syntax import And, App, Axiom, Bottom, Equals, EVar, Implies, Import, Module, Rewrites, Top
from pyk.ktool.kompile import LLVMKompileType
from pyk.testing import KoreClientTest, ServerType

from ..utils import K_FILES

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any, Final

    from pyk.kore.rpc import BoosterServerArgs, ExecuteResult, KoreClient, LogEntry
    from pyk.kore.syntax import Pattern
    from pyk.testing import Kompiler

int_top = Top(INT)
int_bottom = Bottom(INT)
x, y = (EVar(v, INT) for v in ['x', 'y'])


def term(n: int) -> Pattern:
    template = Template(
        r"""
        Lbl'-LT-'generatedTop'-GT-'{}(
            Lbl'-LT-'k'-GT-'{}(
                kseq{}(
                    inj{SortInt{}, SortKItem{}}(
                        \dv{SortInt{}}("$n")
                    ),
                    K:SortK{}
                )
            ),
            GCC:SortGeneratedCounterCell{}
        )
        """
    )
    parser = KoreParser(template.substitute(n=n))
    pattern = parser.pattern()
    assert parser.eof
    return pattern


def state(n: int) -> State:
    return State(term=term(n))


EXECUTE_TEST_DATA: Final[tuple[tuple[str, int, Mapping[str, Any], ExecuteResult], ...]] = (
    (
        'branching',
        0,
        {},
        BranchingResult(
            state=state(2),
            depth=2,
            next_states=(
                State(
                    term=term(3),
                    rule_id='ae0c978867ef4cc5cbfbadf7be2ff55e30e59465697ceaffa1d9fd5343a21fc6',
                    rule_substitution={
                        EVar('GCC', SORT_GENERATED_COUNTER_CELL): EVar(
                            "RuleVar'Unds'DotVar0", SORT_GENERATED_COUNTER_CELL
                        ),
                        EVar('K', SORT_K): EVar("RuleVar'Unds'DotVar1", SORT_K),
                    },
                ),
                State(
                    term=term(4),
                    rule_id='37a544ff4b6da9b4fb839f86d2ad51b770bcaf3dd578b716c38cf0da33458374',
                    rule_substitution={
                        EVar('GCC', SORT_GENERATED_COUNTER_CELL): EVar(
                            "RuleVar'Unds'DotVar0", SORT_GENERATED_COUNTER_CELL
                        ),
                        EVar('K', SORT_K): EVar("RuleVar'Unds'DotVar1", SORT_K),
                    },
                ),
            ),
            logs=(),
        ),
    ),
    ('depth-bound', 0, {'max_depth': 2}, DepthBoundResult(state=state(2), depth=2, logs=())),
    ('stuck', 4, {}, StuckResult(state=state(6), depth=2, logs=())),
    (
        'cut-point',
        4,
        {'cut_point_rules': ['KORE-RPC-TEST.r56']},
        CutPointResult(state=state(5), depth=1, next_states=(state(6),), rule='KORE-RPC-TEST.r56', logs=()),
    ),
    (
        'terminal',
        4,
        {'terminal_rules': ['KORE-RPC-TEST.r56']},
        TerminalResult(state=state(6), depth=2, rule='KORE-RPC-TEST.r56', logs=()),
    ),
    ('vacuous', 3, {}, VacuousResult(state=state(3), depth=0, logs=())),
    ('timeout', 0, {'step_timeout': 0}, TimeoutResult(state=state(0), depth=0, logs=())),
)


IMPLIES_TEST_DATA: Final = (
    (
        '0 -> T',
        int_dv(0),
        int_top,
        ImpliesResult(ImpliesStatus.VALID, Implies(INT, int_dv(0), int_top), int_top, int_top, ()),
    ),
    (
        '0 -> 1',
        int_dv(0),
        int_dv(1),
        ImpliesResult(ImpliesStatus.INVALID, Implies(INT, int_dv(0), int_dv(1)), None, None, ()),
    ),
    (
        'X -> 0',
        x,
        int_dv(0),
        ImpliesResult(
            ImpliesStatus.INVALID,
            Implies(INT, x, int_dv(0)),
            Equals(
                op_sort=INT,
                sort=INT,
                left=x,
                right=int_dv(0),
            ),
            int_top,
            (),
        ),
    ),
    ('X -> X', x, x, ImpliesResult(ImpliesStatus.VALID, Implies(INT, x, x), int_top, int_top, ())),
)

IMPLIES_ERROR_TEST_DATA: Final = (
    ('0 -> X', int_dv(0), x),
    ('X -> Y', x, y),
)

SIMPLIFY_TEST_DATA: Final = (('top-and-top', And(INT, (int_top, int_top)), int_top),)

GET_MODEL_TEST_DATA: Final = (
    ('unkown-config', term(0), None, UnknownResult()),
    (
        'sat-trivial',
        int_top,
        None,
        {
            ServerType.LEGACY: UnknownResult(),
            ServerType.BOOSTER: SatResult(None),
        },
    ),
    ('unsat-trivial', int_bottom, None, UnsatResult()),
    ('unsat-ineq', Equals(BOOL, INT, TRUE, and_bool(gt_int(x, int_dv(1)), le_int(x, int_dv(0)))), None, UnsatResult()),
    ('unsat-eq', Equals(BOOL, INT, TRUE, and_bool(eq_int(x, int_dv(0)), eq_int(x, int_dv(1)))), None, UnsatResult()),
    (
        'unsat-eq-ml',
        And(INT, (Equals(BOOL, INT, TRUE, eq_int(x, int_dv(0))), Equals(BOOL, INT, TRUE, eq_int(x, int_dv(1))))),
        None,
        UnsatResult(),
    ),
    (
        'sat-ineq',
        Equals(BOOL, INT, TRUE, and_bool(gt_int(x, int_dv(0)), le_int(x, int_dv(1)))),
        None,
        SatResult(Equals(INT, INT, x, int_dv(1))),
    ),
    (
        'sat-ineq-ml',
        And(INT, (Equals(BOOL, INT, TRUE, gt_int(x, int_dv(0))), Equals(BOOL, INT, TRUE, le_int(x, int_dv(1))))),
        None,
        SatResult(Equals(INT, INT, x, int_dv(1))),
    ),
    (
        'sat-eq-single-var',
        Equals(BOOL, INT, TRUE, eq_int(x, int_dv(0))),
        None,
        SatResult(Equals(INT, INT, x, int_dv(0))),
    ),
    (
        'sat-eq-two-vars',
        Equals(BOOL, INT, TRUE, and_bool(eq_int(x, int_dv(0)), eq_int(y, int_dv(1)))),
        None,
        SatResult(And(INT, (Equals(INT, INT, x, int_dv(0)), Equals(INT, INT, y, int_dv(1))))),
    ),
)

ADD_MODULE_TEST_DATA: Final = (('empty-module', Module('HELLO')),)

GET_MODEL_WITH_SMT_TEST_DATA: Final = (
    (
        'sat-chop-single-int',
        # chop(x) == x && x == 1
        And(
            INT,
            (
                Equals(
                    BOOL,
                    INT,
                    TRUE,
                    eq_int(App('Lblchop', (), (EVar('x', INT),)), EVar('x', INT)),
                ),
                Equals(BOOL, INT, TRUE, eq_int(EVar('x', INT), int_dv(1))),
            ),
        ),
        None,
        # x == 1
        SatResult(Equals(INT, INT, x, int_dv(1))),
    ),
    (
        'sat-chop-sub-ints',
        # chop(1 - x) == 0 && x == 1
        And(
            INT,
            (
                Equals(
                    BOOL,
                    INT,
                    TRUE,
                    eq_int(
                        App(
                            'Lblchop',
                            (),
                            (
                                App(
                                    "Lbl'Unds'-Int'Unds'",
                                    (),
                                    (
                                        int_dv(1),
                                        EVar('x', INT),
                                    ),
                                ),
                            ),
                        ),
                        int_dv(0),
                    ),
                ),
                Equals(BOOL, INT, TRUE, eq_int(EVar('x', INT), int_dv(1))),
            ),
        ),
        None,
        # x == 1
        SatResult(Equals(INT, INT, x, int_dv(1))),
    ),
)


def assert_execute_result_equals(actual: ExecuteResult, expected: ExecuteResult) -> None:
    assert type(actual) == type(expected)

    actual_dict = asdict(actual)  # type: ignore
    expected_dict = asdict(expected)  # type: ignore
    if 'next_states' in actual_dict and actual.next_states is not None:
        actual_dict['next_states'] = set(actual.next_states)
    if 'next_states' in expected_dict and expected.next_states is not None:
        expected_dict['next_states'] = set(expected.next_states)

    assert actual_dict == expected_dict


class TestKoreClient(KoreClientTest):
    KOMPILE_DEFINITION = """
        module KORE-RPC-TEST
            imports BOOL
            imports INT

            rule [r01]: 0 => 1
            rule [r12]: 1 => 2
            rule [r23]: 2 => 3
            rule [r24]: 2 => 4
            rule [r34]: 3 => 4 ensures false
            rule [r45]: 4 => 5
            rule [r56]: 5 => 6
        endmodule
    """
    KOMPILE_MAIN_MODULE = 'KORE-RPC-TEST'
    KOMPILE_ARGS = {'syntax_module': 'KORE-RPC-TEST'}
    LLVM_ARGS = {'syntax_module': 'KORE-RPC-TEST'}

    @pytest.mark.parametrize(
        'test_id,n,params,expected',
        EXECUTE_TEST_DATA,
        ids=[test_id for test_id, *_ in EXECUTE_TEST_DATA],
    )
    def test_execute(
        self,
        kore_client: KoreClient,
        test_id: str,
        n: int,
        params: Mapping[str, Any],
        expected: ExecuteResult,
    ) -> None:
        # When
        actual = kore_client.execute(term(n), **params)

        # Then
        assert_execute_result_equals(actual, expected)

    @pytest.mark.parametrize(
        'test_id,antecedent,consequent,expected',
        IMPLIES_TEST_DATA,
        ids=[test_id for test_id, *_ in IMPLIES_TEST_DATA],
    )
    def test_implies(
        self,
        kore_client: KoreClient,
        test_id: str,
        antecedent: Pattern,
        consequent: Pattern,
        expected: ImpliesResult,
    ) -> None:
        # When
        actual = kore_client.implies(antecedent, consequent)

        # Then
        assert actual == expected

    @pytest.mark.parametrize(
        'test_id,antecedent,consequent',
        IMPLIES_ERROR_TEST_DATA,
        ids=[test_id for test_id, *_ in IMPLIES_ERROR_TEST_DATA],
    )
    def test_implies_error(
        self,
        kore_client: KoreClient,
        test_id: str,
        antecedent: Pattern,
        consequent: Pattern,
    ) -> None:
        # Then
        with pytest.raises(ImplicationError):
            # When
            kore_client.implies(antecedent, consequent)

    @pytest.mark.parametrize(
        'test_id,pattern,expected',
        SIMPLIFY_TEST_DATA,
        ids=[test_id for test_id, *_ in SIMPLIFY_TEST_DATA],
    )
    def test_simplify(
        self,
        kore_client: KoreClient,
        test_id: str,
        pattern: Pattern,
        expected: Pattern,
    ) -> None:
        # When
        actual, _logs, _entries = kore_client.simplify(pattern)

        # Then
        assert actual == expected

    @pytest.mark.parametrize(
        'test_id,pattern,module_name,expected',
        GET_MODEL_TEST_DATA,
        ids=[test_id for test_id, *_ in GET_MODEL_TEST_DATA],
    )
    def test_get_model(
        self,
        kore_client: KoreClient,
        test_id: str,
        pattern: Pattern,
        module_name: str | None,
        server_type: ServerType,
        expected: GetModelResult | Mapping[ServerType, GetModelResult],
    ) -> None:
        # When
        actual = kore_client.get_model(pattern, module_name)

        # Then
        if isinstance(expected, GetModelResult):
            assert actual == expected
        else:
            assert actual == expected[server_type]

    @pytest.mark.parametrize(
        'test_id,module',
        ADD_MODULE_TEST_DATA,
        ids=[test_id for test_id, *_ in ADD_MODULE_TEST_DATA],
    )
    def test_add_module(
        self,
        kore_client: KoreClient,
        test_id: str,
        module: Module,
    ) -> None:
        # Given
        module_hash = hashlib.sha256(module.text.encode()).hexdigest()
        expected = f'm{module_hash}'

        # When
        actual = kore_client.add_module(module)

        # Then
        assert actual == expected


class TestKoreClientWithSMTLemmas(KoreClientTest):
    KOMPILE_DEFINITION = """
        module SMT
            imports INT
            imports BOOL

            syntax Pgm ::= Bool | Int
            syntax Int ::= chop ( Int ) [function, total, symbol(chop), smtlib(chop)]
            syntax Int ::= "pow256"     [alias] /* 2 ^Int 256 */

            configuration <k> $PGM:Pgm </k>

            rule pow256 => 115792089237316195423570985008687907853269984665640564039457584007913129639936
            rule chop ( I:Int ) => I modInt pow256 [concrete, smt-lemma]
        endmodule
    """
    KOMPILE_MAIN_MODULE = 'SMT'
    KOMPILE_ARGS = {'syntax_module': 'SMT'}
    LLVM_ARGS = {'syntax_module': 'SMT'}

    @pytest.mark.parametrize(
        'test_id,pattern,module_name,expected',
        GET_MODEL_WITH_SMT_TEST_DATA,
        ids=[test_id for test_id, *_ in GET_MODEL_WITH_SMT_TEST_DATA],
    )
    def test_get_model_with_smt(
        self,
        kore_client: KoreClient,
        test_id: str,
        pattern: Pattern,
        module_name: str | None,
        expected: GetModelResult,
    ) -> None:
        # When
        actual = kore_client.get_model(pattern, module_name)

        # Then
        assert actual == expected


EXECUTE_LOGGING_TEST_DATA = (
    # value, log_successful_rewrites, log_failed_rewrites, expected
    (
        0,
        False,
        False,
        {
            ServerType.LEGACY: (),
            ServerType.BOOSTER: (),
        },
    ),
    (
        0,
        True,
        False,
        {
            ServerType.LEGACY: (
                LogRewrite(
                    origin=LogOrigin.KORE_RPC,
                    result=RewriteSuccess(
                        rule_id='911c8f0f2589faf6074f703e8d93e4215bf26a376abe919d2c8cd41ff17fc532',
                    ),
                ),
            ),
            ServerType.BOOSTER: (
                LogRewrite(
                    origin=LogOrigin.BOOSTER,
                    result=RewriteSuccess(
                        rule_id='911c8f0f2589faf6074f703e8d93e4215bf26a376abe919d2c8cd41ff17fc532',
                    ),
                ),
            ),
        },
    ),
    (
        0,
        False,
        True,
        {
            ServerType.LEGACY: (),
            ServerType.BOOSTER: 2
            * (
                LogRewrite(
                    origin=LogOrigin.BOOSTER,
                    result=RewriteFailure(
                        rule_id=None,
                        reason='No applicable rules found',
                    ),
                ),
            ),
        },
    ),
    (
        0,
        True,
        True,
        {
            ServerType.LEGACY: (
                LogRewrite(
                    origin=LogOrigin.KORE_RPC,
                    result=RewriteSuccess(
                        rule_id='911c8f0f2589faf6074f703e8d93e4215bf26a376abe919d2c8cd41ff17fc532',
                    ),
                ),
            ),
            ServerType.BOOSTER: (
                LogRewrite(
                    origin=LogOrigin.BOOSTER,
                    result=RewriteSuccess(
                        rule_id='911c8f0f2589faf6074f703e8d93e4215bf26a376abe919d2c8cd41ff17fc532',
                    ),
                ),
                LogRewrite(
                    origin=LogOrigin.BOOSTER,
                    result=RewriteFailure(
                        rule_id=None,
                        reason='No applicable rules found',
                    ),
                ),
                LogRewrite(
                    origin=LogOrigin.BOOSTER,
                    result=RewriteFailure(
                        rule_id=None,
                        reason='No applicable rules found',
                    ),
                ),
            ),
        },
    ),
)


class TestExecuteLogging(KoreClientTest):
    KOMPILE_DEFINITION = """
        module LOGGING-TEST
            imports INT

            syntax Res ::= "#even" [symbol(even)]
                         | "#odd"  [symbol(odd) ]
            syntax Pgm ::= Int | Res

            configuration <k> $PGM:Pgm </k>
            rule <k> X:Int => #even ... </k> requires X %Int 2  ==Int 0
            rule <k> X:Int => #odd  ... </k> requires X %Int 2 =/=Int 0
        endmodule
    """
    KOMPILE_MAIN_MODULE = 'LOGGING-TEST'
    KOMPILE_ARGS = {'syntax_module': 'LOGGING-TEST'}
    LLVM_ARGS = KOMPILE_ARGS

    @staticmethod
    def config(i: int) -> Pattern:
        return generated_top((k(kseq((inj(INT, SORT_K_ITEM, int_dv(i)),))), generated_counter(int_dv(0))))

    @pytest.mark.parametrize(
        'value,log_successful_rewrites,log_failed_rewrites,expected',
        EXECUTE_LOGGING_TEST_DATA,
        ids=count(),
    )
    def test(
        self,
        server_type: ServerType,
        kore_client: KoreClient,
        value: int,
        log_successful_rewrites: bool,
        log_failed_rewrites: bool,
        expected: Mapping[ServerType, tuple[LogEntry, ...]],
    ) -> None:
        # Given
        config = self.config(value)

        # When
        response = kore_client.execute(
            config,
            log_successful_rewrites=log_successful_rewrites,
            log_failed_rewrites=log_failed_rewrites,
        )
        actual = response.logs

        # Then
        assert actual == expected[server_type]


class TestAddModule(KoreClientTest):
    KOMPILE_DEFINITION = """
        module INT-CONFIG
          imports INT-SYNTAX
          configuration <k> $PGM:Int </k>
        endmodule
    """
    KOMPILE_MAIN_MODULE = 'INT-CONFIG'
    KOMPILE_ARGS = {'syntax_module': 'INT-CONFIG'}
    LLVM_ARGS = {'syntax_module': 'INT-CONFIG'}

    @staticmethod
    def config(i: int) -> Pattern:
        return generated_top((k(kseq((inj(INT, SORT_K_ITEM, int_dv(i)),))), generated_counter(int_dv(0))))

    @staticmethod
    def rule(lhs: int, rhs: int) -> Axiom:
        return Axiom(
            (),
            Rewrites(
                SORT_GENERATED_TOP_CELL,
                And(SORT_GENERATED_TOP_CELL, (TestAddModule.config(lhs), Top(SORT_GENERATED_TOP_CELL))),
                And(SORT_GENERATED_TOP_CELL, (TestAddModule.config(rhs), Top(SORT_GENERATED_TOP_CELL))),
            ),
        )

    def test_base_module(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        expected = StuckResult(State(term=config), depth=0, logs=())

        # When
        actual = kore_client.execute(config)

        # Then
        assert actual == expected

    def test_base_module_explicitly(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        expected = StuckResult(State(term=config), depth=0, logs=())

        # When
        actual = kore_client.execute(config, module_name=self.KOMPILE_MAIN_MODULE)

        # Then
        assert actual == expected

    def test_add_a_single_module(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module)
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

    def test_add_a_single_module_but_dont_use_it(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(0)), depth=0, logs=())

        # When
        kore_client.add_module(module)
        actual = kore_client.execute(config)

        # Then
        assert actual == expected

    def test_name_as_id(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        kore_client.add_module(module, name_as_id=True)
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected

    def test_without_name_as_id_fails(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))

        # When + Then
        kore_client.add_module(module)
        with pytest.raises(UnknownModuleError):
            kore_client.execute(config, module_name='A')

    def test_add_module_twice(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module)
        module_id_2 = kore_client.add_module(module)

        # Then
        assert module_id == module_id_2

        # And when
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

    def test_add_module_twice_with_name(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module, name_as_id=True)
        module_id_2 = kore_client.add_module(module, name_as_id=True)

        # Then
        assert module_id == module_id_2

        # And when
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

    def test_add_module_without_name_then_with_name(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module)
        module_id_2 = kore_client.add_module(module, name_as_id=True)

        # Then
        assert module_id == module_id_2

        # And when
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

        # And when
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected

    def test_add_module_with_name_then_without_name(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(1)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module, name_as_id=True)
        module_id_2 = kore_client.add_module(module)

        # Then
        assert module_id == module_id_2

        # And when
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected

        # And when
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected

        # And when
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

    def test_add_different_modules_with_same_name_as_id_fails(self, kore_client: KoreClient) -> None:
        # Given
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))

        # When-Then
        kore_client.add_module(module_1, name_as_id=True)
        with pytest.raises(DuplicateModuleError):
            kore_client.add_module(module_2, name_as_id=True)

    def test_add_two_modules_second_with_same_name_as_id(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))
        expected_1 = StuckResult(State(term=self.config(1)), depth=1, logs=())
        expected_2 = StuckResult(State(term=self.config(2)), depth=1, logs=())

        # When
        module_id = kore_client.add_module(module_1)
        kore_client.add_module(module_2, name_as_id=True)
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected_1

        # And when
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected_2

    def test_add_two_modules_first_with_same_name_as_id(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))
        expected_1 = StuckResult(State(term=self.config(1)), depth=1, logs=())
        expected_2 = StuckResult(State(term=self.config(2)), depth=1, logs=())

        # When
        kore_client.add_module(module_1, name_as_id=True)
        module_id = kore_client.add_module(module_2)
        actual = kore_client.execute(config, module_name='A')

        # Then
        assert actual == expected_1

        # And when
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected_2

    def test_add_module_with_import(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        expected = StuckResult(State(term=self.config(2)), depth=2, logs=())

        # When
        module_1_id = kore_client.add_module(module_1)
        module_2 = Module('B', sentences=(Import(module_1_id), self.rule(1, 2)))
        module_2_id = kore_client.add_module(module_2)
        actual = kore_client.execute(config, module_name=module_2_id)

        # Then
        assert actual == expected

    def test_add_module_with_named_import(self, kore_client: KoreClient) -> None:
        # Given
        config = self.config(0)
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('B', sentences=(Import('A'), self.rule(1, 2)))
        expected = StuckResult(State(term=self.config(2)), depth=2, logs=())

        # When
        kore_client.add_module(module_1, name_as_id=True)
        module_id = kore_client.add_module(module_2)
        actual = kore_client.execute(config, module_name=module_id)

        # Then
        assert actual == expected

    def test_add_module_with_unknown_import_fails(self, kore_client: KoreClient) -> None:
        # Given
        module = Module('B', sentences=(Import('A'), self.rule(0, 1)))

        # Then
        with pytest.raises(InvalidModuleError):
            # When
            kore_client.add_module(module)

    def test_add_module_with_unknown_named_import_fails(self, kore_client: KoreClient) -> None:
        # Given
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))

        # When-Then
        kore_client.add_module(module_1)
        module_2 = Module('B', sentences=(Import('A'), self.rule(1, 2)))
        with pytest.raises(InvalidModuleError):
            kore_client.add_module(module_2)

    def test_add_module_with_hash_name_not_as_id_first(self, kore_client: KoreClient) -> None:
        # Given
        expected_module_2_id = 'mb2dcdc14b22cf840e6270ac0ebd1d9448dad1a64f04413c20c1c87d687ac28c9'
        module_1 = Module(expected_module_2_id, sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))

        # When
        kore_client.add_module(module_1)
        actual_module_2_id = kore_client.add_module(module_2)

        # Then
        assert actual_module_2_id == expected_module_2_id

    def test_add_module_with_hash_name_as_id_first_fails(self, kore_client: KoreClient) -> None:
        # Given
        module_2_id = 'mb2dcdc14b22cf840e6270ac0ebd1d9448dad1a64f04413c20c1c87d687ac28c9'
        module_1 = Module(module_2_id, sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))

        # When-Then
        kore_client.add_module(module_1, name_as_id=True)
        with pytest.raises(DuplicateModuleError):
            kore_client.add_module(module_2)

    def test_add_module_with_hash_name_not_as_id_second(self, kore_client: KoreClient) -> None:
        # Given
        expected_module_1_id = 'm33a3f42dd93f20505f7b1132dadc18fb4adc9882e0d55d9661cc1d77ad549b97'
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module(expected_module_1_id, sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))

        # When
        actual_module_1_id = kore_client.add_module(module_1)
        kore_client.add_module(module_2)

        # Then
        assert actual_module_1_id == expected_module_1_id

    def test_add_module_with_hash_name_as_id_second_fails(self, kore_client: KoreClient) -> None:
        # Given
        module_1_id = 'm33a3f42dd93f20505f7b1132dadc18fb4adc9882e0d55d9661cc1d77ad549b97'
        module_1 = Module('A', sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 1)))
        module_2 = Module(module_1_id, sentences=(Import(self.KOMPILE_MAIN_MODULE), self.rule(0, 2)))

        # When-Then
        kore_client.add_module(module_1)
        with pytest.raises(DuplicateModuleError):
            kore_client.add_module(module_2, name_as_id=True)


START_BOOSTER_SERVER_TEST_DATA: Final[tuple[dict[str, Any], ...]] = (
    {},
    {'fallback_on': ['Aborted', 'Stuck']},
    {'interim_simplification': 3},
    {'simplify_each': 5},
    {'no_post_exec_simpify': True},
    {'log_context': ['booster*']},
    {'log_context': ['kore*', '!detail']},
)


@pytest.fixture(scope='module')
def imp_dir(kompile: Kompiler) -> Path:
    return kompile(main_file=K_FILES / 'imp.k', backend='haskell')


@pytest.fixture(scope='module')
def imp_llvm_dir(kompile: Kompiler) -> Path:
    return kompile(main_file=K_FILES / 'imp.k', backend='llvm', llvm_kompile_type=LLVMKompileType.C)


@pytest.mark.parametrize('args', START_BOOSTER_SERVER_TEST_DATA, ids=count())
def test_start_booster_server(imp_dir: Path, imp_llvm_dir: Path, args: dict) -> None:
    # Given
    booster_args: BoosterServerArgs = {
        'kompiled_dir': imp_dir,
        'llvm_kompiled_dir': imp_llvm_dir,
        'module_name': 'IMP',
        **args,
    }

    # When
    with BoosterServer(booster_args):
        pass
