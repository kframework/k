from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from pyk.kore.prelude import INT, SORT_GENERATED_TOP_CELL, int_dv
from pyk.kore.rpc import (
    AbortedError,
    AbortedResult,
    DefaultError,
    ImplicationError,
    ImpliesResult,
    ImpliesStatus,
    JsonRpcClient,
    JsonRpcError,
    KoreClient,
    KoreClientError,
    ParseError,
    PatternError,
    SatResult,
    SmtSolverError,
    State,
    StuckResult,
    TransportType,
    UnknownModuleError,
    UnknownResult,
    UnsatResult,
    VacuousResult,
)
from pyk.kore.syntax import And, App, Bottom, Equals, EVar, Module, Top

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any, Final
    from unittest.mock import Mock

    from pyk.kore.rpc import ExecuteResult
    from pyk.kore.syntax import Pattern

x, y = (EVar(name, INT) for name in ['x', 'y'])
int_top = Top(INT)
int_bottom = Bottom(INT)


def kore(pattern: Pattern) -> dict[str, Any]:
    return {
        'format': 'KORE',
        'version': 1,
        'term': pattern.dict,
    }


class MockClient:
    mock: Mock

    def __init__(self, mock: Mock):
        self.mock = mock

    def assume_response(self, response: Any) -> None:
        self.mock.request.return_value = response

    def assume_raises(self, error: JsonRpcError) -> None:
        self.mock.request.side_effect = error

    def assert_request(self, method: str, **params: Any) -> None:
        self.mock.request.assert_called_with(method, **params)


@pytest.fixture
def mock_class() -> Iterator[Mock]:
    patcher = patch('pyk.kore.rpc.JsonRpcClient', spec=True)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock(mock_class: Mock) -> Mock:
    mock = mock_class.return_value
    assert isinstance(mock, JsonRpcClient)
    return mock  # type: ignore


@pytest.fixture
def rpc_client(mock: Mock) -> MockClient:
    return MockClient(mock)


@pytest.fixture
def kore_client(mock: Mock, mock_class: Mock) -> Iterator[KoreClient]:  # noqa: N803
    client = KoreClient('localhost', 3000)
    mock_class.assert_called_with(
        'localhost', 3000, timeout=None, bug_report=None, bug_report_id=None, transport=TransportType.SINGLE_SOCKET
    )
    assert client._client._default_client == mock
    yield client
    client.close()
    mock.close.assert_called()


EXECUTE_TEST_DATA: Final = (
    (
        App('IntAdd', (), (int_dv(1), int_dv(1))),
        {'state': kore(App('IntAdd', [], [int_dv(1), int_dv(1)]))},
        {
            'state': {
                'term': kore(int_dv(2)),
                'substitution': kore(
                    And(
                        SORT_GENERATED_TOP_CELL,
                        (
                            Equals(INT, SORT_GENERATED_TOP_CELL, x, int_dv(3)),
                            Equals(INT, SORT_GENERATED_TOP_CELL, y, int_dv(4)),
                        ),
                    )
                ),
                'predicate': kore(int_top),
            },
            'depth': 1,
            'reason': 'stuck',
        },
        StuckResult(State(int_dv(2), substitution={x: int_dv(3), y: int_dv(4)}, predicate=int_top), 1, logs=()),
    ),
    (
        App('IntAdd', (), (int_dv(1), int_dv(1))),
        {'state': kore(App('IntAdd', [], [int_dv(1), int_dv(1)]))},
        {
            'state': {
                'term': kore(int_dv(2)),
                'substitution': kore(Equals(INT, SORT_GENERATED_TOP_CELL, x, int_dv(3))),
            },
            'depth': 1,
            'reason': 'vacuous',
        },
        VacuousResult(State(int_dv(2), substitution={x: int_dv(3)}), 1, logs=()),
    ),
    (
        int_dv(0),
        {'state': kore(int_dv(0))},
        {
            'state': {'term': kore(int_dv(1))},
            'depth': 2,
            'unknown-predicate': kore(int_dv(3)),
            'reason': 'aborted',
        },
        AbortedResult(
            state=State(term=int_dv(1)),
            depth=2,
            unknown_predicate=int_dv(3),
            logs=(),
        ),
    ),
)


@pytest.mark.parametrize('pattern,params,response,expected', EXECUTE_TEST_DATA, ids=count())
def test_execute(
    kore_client: KoreClient,
    rpc_client: MockClient,
    pattern: Pattern,
    params: dict[str, Any],
    response: dict[str, Any],
    expected: ExecuteResult,
) -> None:
    # Given
    rpc_client.assume_response(response)

    # When
    actual = kore_client.execute(pattern)

    # Then
    rpc_client.assert_request('execute', **params)
    assert actual == expected


IMPLIES_TEST_DATA: Final = (
    (
        int_bottom,
        int_top,
        {'antecedent': kore(int_bottom), 'consequent': kore(int_top), 'assume-defined': False},
        {'status': 'valid', 'implication': kore(int_top)},
        ImpliesResult(ImpliesStatus.VALID, int_top, None, None, ()),
    ),
)


@pytest.mark.parametrize('antecedent,consequent,params,response,expected', IMPLIES_TEST_DATA, ids=count())
def test_implies(
    kore_client: KoreClient,
    rpc_client: MockClient,
    antecedent: Pattern,
    consequent: Pattern,
    params: dict[str, Any],
    response: dict[str, Any],
    expected: ImpliesResult,
) -> None:
    # Given
    rpc_client.assume_response(response)

    # When
    actual = kore_client.implies(antecedent, consequent)

    # Then
    rpc_client.assert_request('implies', **params)
    assert actual == expected


SIMPLIFY_TEST_DATA: Final = (
    (
        And(INT, (int_top, int_top)),
        {'state': kore(And(INT, (int_top, int_top)))},
        {'state': kore(int_top)},
        int_top,
    ),
)


@pytest.mark.parametrize('pattern,params,response,expected', SIMPLIFY_TEST_DATA, ids=count())
def test_simplify(
    kore_client: KoreClient,
    rpc_client: MockClient,
    pattern: Pattern,
    params: dict[str, Any],
    response: dict[str, Any],
    expected: Pattern,
) -> None:
    # Given
    rpc_client.assume_response(response)

    # When
    actual, _logs, _entries = kore_client.simplify(pattern)

    # Then
    rpc_client.assert_request('simplify', **params)
    assert actual == expected


GET_MODEL_TEST_DATA: Final = (
    (
        int_dv(0),
        None,
        {'state': kore(int_dv(0))},
        {'satisfiable': 'Unknown'},
        UnknownResult(),
    ),
    (
        int_dv(1),
        'TEST-MODULE',
        {'state': kore(int_dv(1)), 'module': 'TEST-MODULE'},
        {'satisfiable': 'Unknown'},
        UnknownResult(),
    ),
    (
        int_dv(2),
        None,
        {'state': kore(int_dv(2))},
        {'satisfiable': 'Unsat'},
        UnsatResult(),
    ),
    (
        int_dv(3),
        None,
        {'state': kore(int_dv(3))},
        {'satisfiable': 'Sat', 'substitution': kore(int_dv(0))},
        SatResult(int_dv(0)),
    ),
)


@pytest.mark.parametrize('pattern,module_name,params,response,expected', GET_MODEL_TEST_DATA, ids=count())
def test_get_model(
    kore_client: KoreClient,
    rpc_client: MockClient,
    pattern: Pattern,
    module_name: str | None,
    params: dict[str, Any],
    response: dict[str, Any],
    expected: Pattern,
) -> None:
    # Given
    rpc_client.assume_response(response)

    # When
    actual = kore_client.get_model(pattern, module_name)

    # Then
    rpc_client.assert_request('get-model', **params)
    assert actual == expected


ADD_MODULE_TEST_DATA: Final = (
    (
        Module('HELLO'),
        {'module': 'module HELLO\nendmodule []'},
    ),
)


@pytest.mark.parametrize('module,params', ADD_MODULE_TEST_DATA, ids=count())
def test_add_module(
    kore_client: KoreClient,
    rpc_client: MockClient,
    module: Module,
    params: dict[str, Any],
) -> None:
    # Given
    expected = 'm0123456789abcdef'
    rpc_client.assume_response({'module': 'm0123456789abcdef'})

    # When
    actual = kore_client.add_module(module)

    # Then
    rpc_client.assert_request('add-module', **params)
    assert actual == expected


ERROR_TEST_DATA: Final = (
    (
        'parse-error',
        JsonRpcError(message='foo', code=1, data=':21:286: unexpected token TokenIdent "hasDomainValues"'),
        ParseError(error=':21:286: unexpected token TokenIdent "hasDomainValues"'),
        'Could not parse pattern: :21:286: unexpected token TokenIdent "hasDomainValues"',
    ),
    (
        'pattern-error',
        JsonRpcError(
            message='foo',
            code=2,
            data={
                'error': "Sort 'IntSort' not defined.",
                'context': [
                    r'\top (<unknown location>)',
                    "sort 'IntSort' (<unknown location>)",
                    '(<unknown location>)',
                ],
            },
        ),
        PatternError(
            error="Sort 'IntSort' not defined.",
            context=(
                r'\top (<unknown location>)',
                "sort 'IntSort' (<unknown location>)",
                '(<unknown location>)',
            ),
        ),
        r"Could not verify pattern: Sort 'IntSort' not defined. Context: \top (<unknown location>) ;; sort 'IntSort' (<unknown location>) ;; (<unknown location>)",
    ),
    (
        'module-error',
        JsonRpcError(message='foo', code=3, data='MODULE-NAME'),
        UnknownModuleError(module_name='MODULE-NAME'),
        'Could not find module: MODULE-NAME',
    ),
    (
        'implication-error',
        JsonRpcError(
            message='foo',
            code=4,
            data={
                'error': 'The check implication step expects the antecedent term to be function-like.',
                'context': [r'/* Sfa */ \mu{}( Config@A:SortK{}, /* Sfa */ Config@A:SortK{} )'],
            },
        ),
        ImplicationError(
            error='The check implication step expects the antecedent term to be function-like.',
            context=(r'/* Sfa */ \mu{}( Config@A:SortK{}, /* Sfa */ Config@A:SortK{} )',),
        ),
        r'Implication check error: The check implication step expects the antecedent term to be function-like. Context: /* Sfa */ \mu{}( Config@A:SortK{}, /* Sfa */ Config@A:SortK{} )',
    ),
    (
        'smt-solver-error',
        JsonRpcError(
            message='foo',
            code=5,
            data={
                'error': 'Failed to decide predicate.',
                'term': kore(int_dv(0)),
            },
        ),
        SmtSolverError('Failed to decide predicate.', int_dv(0)),
        r'SMT solver error: Failed to decide predicate. Pattern: \dv{SortInt{}}("0")',
    ),
    (
        'aborted-error',
        JsonRpcError(message='Aborted', code=6, data='unknown constraints'),
        AbortedError(data='unknown constraints'),
        'Backend aborted: unknown constraints',
    ),
    (
        'default-error',
        JsonRpcError(message='foo', code=100, data={'bar': 1, 'baz': [2, 3]}),
        DefaultError(message='foo', code=100, data={'bar': 1, 'baz': [2, 3]}),
        "foo | code: 100 | data: {'bar': 1, 'baz': [2, 3]}",
    ),
)


@pytest.mark.parametrize(
    'test_id,rpc_err,expected_err,expected_str',
    ERROR_TEST_DATA,
    ids=[test_id for test_id, *_ in ERROR_TEST_DATA],
)
def test_error(
    kore_client: KoreClient,
    rpc_client: MockClient,
    test_id: str,
    rpc_err: JsonRpcError,
    expected_err: KoreClientError,
    expected_str: str,
) -> None:
    # Given
    rpc_client.assume_raises(rpc_err)

    # Then
    with pytest.raises(KoreClientError) as excinfo:
        # When
        kore_client.simplify(int_top)  # Transport is mocked, could be anything

    actual_err = excinfo.value
    actual_str = str(actual_err)

    # Then
    assert actual_err == expected_err
    assert actual_str == expected_str
