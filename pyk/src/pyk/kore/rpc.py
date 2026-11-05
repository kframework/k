from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import sys
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from signal import SIGINT
from subprocess import DEVNULL, PIPE, Popen
from threading import Thread
from time import sleep
from typing import ClassVar  # noqa: TC003
from typing import TYPE_CHECKING, ContextManager, NamedTuple, TypedDict, final

from psutil import Process

from ..utils import FrozenDict, check_dir_path, check_file_path, filter_none, run_process_2
from . import manip
from .prelude import SORT_GENERATED_TOP_CELL
from .syntax import And, Equals, EVar, kore_term

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import IO, Any, Final, TypeVar

    from typing_extensions import Required

    from ..utils import BugReport
    from .syntax import Module, Pattern

    ER = TypeVar('ER', bound='ExecuteResult')
    RR = TypeVar('RR', bound='RewriteResult')
    LE = TypeVar('LE', bound='LogEntry')

_LOGGER: Final = logging.getLogger(__name__)

# Label prefixed onto every outgoing JSON-RPC request id, so booster's per-line
# `{request: ...}` context in `kore.jsonl` self-identifies the originating claim.
# Provers should `client_label.set(proof.id)` at the start of each proof; multi-
# threaded consumers must re-`set` inside their worker entry points, since
# `ContextVar` values are not propagated by `ThreadPoolExecutor`.
client_label: ContextVar[str | None] = ContextVar('kore_rpc_client_label', default=None)


class KoreExecLogFormat(Enum):
    STANDARD = 'standard'
    ONELINE = 'oneline'
    JSON = 'json'


@final
@dataclass
class JsonRpcError(Exception):
    def __init__(self, message: str, code: int, data: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


class Transport(ContextManager['Transport'], ABC):

    def request(self, req: str, request_id: str, method_name: str) -> str:
        server_addr = self._description()
        _LOGGER.info(f'Sending request to {server_addr}: {request_id} - {method_name}')
        _LOGGER.debug(f'Sending request to {server_addr}: {req}')
        resp = self._request(req)
        _LOGGER.info(f'Received response from {server_addr}: {request_id} - {method_name}')
        _LOGGER.debug(f'Received response from {server_addr}: {resp}')
        return resp

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @abstractmethod
    def close(self) -> None: ...

    def send_interrupt(self, data: str) -> None:
        """Send `data` on the live connection without waiting for a reply.

        Used to deliver a `cancel` to a connection whose reply another thread is already
        awaiting. Default: no-op. Override only for connections that can be written to
        while a request is in flight.
        """
        ...

    @abstractmethod
    def _request(self, req: str) -> str: ...

    @abstractmethod
    def _description(self) -> str: ...


class TransportType(Enum):
    SINGLE_SOCKET = auto()
    HTTP = auto()


@final
class SingleSocketTransport(Transport):
    _host: str
    _port: int
    _timeout: int | None
    _sock: socket.socket
    _file: IO[str]

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: int | None = None,
    ):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock = self._create_connection(host, port, timeout)
        self._file = self._sock.makefile('r')

    @staticmethod
    def _create_connection(host: str, port: int, timeout: int | None) -> socket.socket:
        if timeout is not None and timeout < 0:
            raise ValueError(f'Expected nonnegative timeout value, got: {timeout}')

        _LOGGER.info(f'Connecting to host: {host}:{port}')

        timeout_datetime = datetime.now() + timedelta(milliseconds=timeout) if timeout is not None else None
        while timeout_datetime is None or datetime.now() < timeout_datetime:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, port))
                local_port = sock.getsockname()[1]
                _LOGGER.info(f'Connected to host: {host}:{port} (local port: {local_port})')
                return sock
            except ConnectionRefusedError:
                sock.close()
                sleep(0.1)

        raise RuntimeError(f'Connection timed out: {host}:{port}')

    def close(self) -> None:
        self._file.close()
        self._sock.close()

    def send_interrupt(self, data: str) -> None:
        # Write the cancel to the socket but don't read the reply: the thread already blocked in
        # `_request`'s `readline` will read the server's "cancelled" reply. The socket stays open.
        # The leading newline separates the cancel from the request bytes already on the stream.
        self._sock.sendall(b'\n' + data.encode())

    def _request(self, req: str) -> str:
        self._sock.sendall(req.encode())
        server_addr = self._description()
        _LOGGER.debug(f'Waiting for response from {server_addr}...')
        return self._file.readline().rstrip()

    def _description(self) -> str:
        return f'{self._host}:{self._port}'


@final
class HttpTransport(Transport):
    _host: str
    _port: int
    _timeout: int | None

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: int | None = None,
    ):
        self._host = host
        self._port = port
        self._timeout = timeout

    def close(self) -> None:
        pass

    def _request(self, req: str) -> str:
        connection = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        connection.request('POST', '/', body=req, headers={'Content-Type': 'application/json'})
        server_addr = self._description()
        _LOGGER.debug(f'Waiting for response from {server_addr}...')
        response = connection.getresponse()
        if response.status != 200:
            raise JsonRpcError('Internal server error', -32603)
        return response.read().decode()

    def _description(self) -> str:
        return f'{self._host}:{self._port}'


class JsonRpcClientFacade(ContextManager['JsonRpcClientFacade']):
    _JSON_RPC_VERSION: Final = '2.0'

    _clients: dict[str, list[JsonRpcClient]]
    _default_client: JsonRpcClient
    _last_request_id: str | None

    def __init__(
        self,
        default_host: str,
        default_port: int,
        default_transport: TransportType,
        dispatch: dict[str, list[tuple[str, int, TransportType]]],
        *,
        timeout: int | None = None,
        bug_report: BugReport | None = None,
        bug_report_id: str | None = None,
    ):
        client_cache = {}
        self._clients = {}
        self._last_request_id = None
        self._default_client = JsonRpcClient(
            default_host,
            default_port,
            timeout=timeout,
            bug_report=bug_report,
            bug_report_id=bug_report_id,
            transport=default_transport,
        )
        client_cache[(default_host, default_port)] = self._default_client
        for method, servers in dispatch.items():
            for host, port, transport in servers:
                if (host, port) in client_cache:
                    self._update_clients(method, client_cache[(host, port)])
                else:
                    new_id = None if bug_report_id is None else bug_report_id + '_' + str(transport)
                    new_client = JsonRpcClient(
                        host, port, timeout=timeout, bug_report=bug_report, bug_report_id=new_id, transport=transport
                    )
                    self._update_clients(method, new_client)
                    client_cache[(host, port)] = new_client

    def _update_clients(self, method: str, client: JsonRpcClient) -> None:
        clients = self._clients.get(method, [])
        self._clients[method] = clients
        clients.append(client)

    def __enter__(self) -> JsonRpcClientFacade:
        return self

    def __exit__(self, *args: Any) -> None:
        self._default_client.__exit__(*args)
        for clients in self._clients.values():
            for client in clients:
                client.__exit__(*args)

    def close(self) -> None:
        self._default_client.close()
        for clients in self._clients.values():
            for client in clients:
                client.close()

    @property
    def last_request_id(self) -> str | None:
        """The JSON-RPC id of the most recent request issued through this facade (``None`` if none yet)."""
        return self._last_request_id

    def interrupt(self) -> None:
        self._default_client.interrupt()
        for clients in self._clients.values():
            for client in clients:
                client.interrupt()

    def request(self, method: str, **params: Any) -> dict[str, Any]:
        if method in self._clients:
            for client in self._clients[method]:
                response = client.request(method, **params)
                self._last_request_id = client.last_request_id
                if 'error' in response:
                    return response
            return response
        else:
            response = self._default_client.request(method, **params)
            self._last_request_id = self._default_client.last_request_id
            return response


class JsonRpcClient(ContextManager['JsonRpcClient']):
    _JSON_RPC_VERSION: Final = '2.0'

    _transport: Transport
    _req_id: int
    _last_request_id: str | None

    _bug_report: BugReport | None
    _bug_report_id: str | None

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: int | None = None,
        bug_report: BugReport | None = None,
        bug_report_id: str | None = None,
        transport: TransportType = TransportType.SINGLE_SOCKET,
    ):
        self._transport = self._create_transport(transport, host=host, port=port, timeout=timeout)
        self._req_id = 1
        self._last_request_id = None
        self._bug_report_id = bug_report_id
        self._bug_report = bug_report

    @property
    def last_request_id(self) -> str | None:
        """The JSON-RPC id of the most recent request issued by this client (``None`` if none yet)."""
        return self._last_request_id

    @staticmethod
    def _create_transport(transport: TransportType, *, host: str, port: int, timeout: int | None) -> Transport:
        match transport:
            case TransportType.SINGLE_SOCKET:
                return SingleSocketTransport(host, port, timeout=timeout)
            case TransportType.HTTP:
                return HttpTransport(host, port, timeout=timeout)
            case _:
                raise AssertionError()

    def __enter__(self) -> JsonRpcClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self._transport.__exit__(*args)

    def close(self) -> None:
        self._transport.close()

    def interrupt(self) -> None:
        # Send a `cancel` so the server aborts the in-flight request. The cancel gets no reply of its
        # own; the thread awaiting that request gets a "cancelled" error instead. The id is only for
        # logs, so we derive it from the last request rather than touching the requester's `_req_id`.
        cancel_id = f'{self._last_request_id}-cancel' if self._last_request_id is not None else 'cancel'
        payload = {
            'jsonrpc': self._JSON_RPC_VERSION,
            'id': cancel_id,
            'method': 'cancel',
            'params': {},
        }
        self._transport.send_interrupt(json.dumps(payload))

    def request(self, method: str, **params: Any) -> dict[str, Any]:
        label = client_label.get()
        prefix = label if label is not None else str(id(self))
        req_id = f'{prefix}-{self._req_id:03}'
        self._req_id += 1
        self._last_request_id = req_id

        payload = {
            'jsonrpc': self._JSON_RPC_VERSION,
            'id': req_id,
            'method': method,
            'params': params,
        }

        req = json.dumps(payload)

        base_name = self._bug_report_id if self._bug_report_id is not None else 'kore_rpc'
        req_name = f'{base_name}/{id(self)}/{req_id}'
        if self._bug_report:
            bug_report_request = f'{req_name}_request.json'
            self._bug_report.add_file_contents(req, Path(bug_report_request))
            self._bug_report.add_request(f'{req_name}_request.json')

        resp = self._transport.request(req, req_id, method)
        if not resp:
            raise RuntimeError('Empty response received')

        if self._bug_report:
            bug_report_response = f'{req_name}_response.json'
            self._bug_report.add_file_contents(resp, Path(bug_report_response))
            self._bug_report.add_request(f'{req_name}_response.json')

        data = json.loads(resp)
        self._check(data)
        assert data['id'] == req_id

        return data['result']

    @staticmethod
    def _check(response: Mapping[str, Any]) -> None:
        if 'error' not in response:
            return

        assert response['error']['code'] not in {-32700, -32600}, 'Malformed JSON-RPC request'
        raise JsonRpcError(**response['error'])


class KoreClientError(Exception, ABC):
    def __init__(self, message: str):
        super().__init__(message)


@final
@dataclass
class ParseError(KoreClientError):
    error: str

    def __init__(self, error: str):
        self.error = error
        super().__init__(f'Could not parse pattern: {self.error}')


@final
@dataclass
class PatternError(KoreClientError):
    error: str
    context: tuple[str, ...]

    def __init__(self, error: str, context: Iterable[str]):
        self.error = error
        self.context = tuple(context)
        context_str = ' ;; '.join(self.context)
        super().__init__(f'Could not verify pattern: {self.error} Context: {context_str}')


@final
@dataclass
class UnknownModuleError(KoreClientError):
    module_name: str

    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__(f'Could not find module: {self.module_name}')


@final
@dataclass
class InvalidModuleError(KoreClientError):
    error: str
    context: tuple[str, ...] | None

    def __init__(self, error: str, context: Iterable[str] | None):
        self.error = error
        self.context = tuple(context) if context else None
        context_str = ' Context: ' + ' ;; '.join(self.context) if self.context else ''
        super().__init__(f'Could not verify module: {self.error}{context_str}')


@final
@dataclass
class DuplicateModuleError(KoreClientError):
    module_name: str

    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__(f'Duplicate module name: {self.module_name}')


@final
@dataclass
class ImplicationError(KoreClientError):
    error: str
    context: tuple[str, ...]

    def __init__(self, error: str, context: Iterable[str]):
        self.error = error
        self.context = tuple(context)
        context_str = ' ;; '.join(self.context)
        super().__init__(f'Implication check error: {self.error} Context: {context_str}')


@final
@dataclass
class SmtSolverError(KoreClientError):
    error: str
    pattern: Pattern

    def __init__(self, error: str, pattern: Pattern):
        self.error = error
        self.pattern = pattern
        super().__init__(f'SMT solver error: {self.error} Pattern: {self.pattern.text}')


@final
@dataclass
class AbortedError(KoreClientError):
    """A backend engine aborted the request because it could not decide it (JSON-RPC ``code: 6``).

    The backend raises this when a request carried something the engine does not know how to
    process — e.g. an ``implies`` whose constraints it cannot discharge.  It is a "couldn't
    determine," not a decisive verdict, so callers should treat it as indeterminate rather than as
    a definite answer.  ``data`` is the abort-reason text (e.g. ``"unknown constraints"``).
    """

    data: str

    def __init__(self, data: str):
        self.data = data
        super().__init__(f'Backend aborted: {self.data}')


@final
@dataclass
class DefaultError(KoreClientError):
    message: str
    code: int
    data: Any

    def __init__(self, message: str, code: int, data: Any = None):
        self.message = message
        self.code = code
        self.data = data
        message = f'{self.message} | code: {self.code}' + (f' | data: {self.data}' if data is not None else '')
        super().__init__(message)


class StopReason(str, Enum):
    STUCK = 'stuck'
    DEPTH_BOUND = 'depth-bound'
    TIMEOUT = 'timeout'
    BRANCHING = 'branching'
    CUT_POINT_RULE = 'cut-point-rule'
    TERMINAL_RULE = 'terminal-rule'
    VACUOUS = 'vacuous'
    ABORTED = 'aborted'


@final
@dataclass(frozen=True)
class State:
    term: Pattern
    substitution: FrozenDict[EVar, Pattern] | None
    predicate: Pattern | None
    rule_id: str | None
    rule_substitution: FrozenDict[EVar, Pattern] | None
    rule_predicate: Pattern | None

    def __init__(
        self,
        term: Pattern,
        *,
        substitution: Mapping[EVar, Pattern] | None = None,
        predicate: Pattern | None = None,
        rule_id: str | None = None,
        rule_substitution: Mapping[EVar, Pattern] | None = None,
        rule_predicate: Pattern | None = None,
    ):
        substitution = FrozenDict(substitution) if substitution is not None else None
        rule_substitution = FrozenDict(rule_substitution) if rule_substitution is not None else None
        object.__setattr__(self, 'term', term)
        object.__setattr__(self, 'substitution', substitution)
        object.__setattr__(self, 'predicate', predicate)
        object.__setattr__(self, 'rule_id', rule_id)
        object.__setattr__(self, 'rule_substitution', rule_substitution)
        object.__setattr__(self, 'rule_predicate', rule_predicate)

    @staticmethod
    def from_dict(dct: Mapping[str, Any]) -> State:
        return State(
            term=kore_term(dct['term']),
            substitution=State._subst_to_dict(kore_term(dct['substitution'])) if 'substitution' in dct else None,
            predicate=kore_term(dct['predicate']) if 'predicate' in dct else None,
            rule_id=dct.get('rule-id'),
            rule_substitution=(
                State._subst_to_dict(kore_term(dct['rule-substitution'])) if 'rule-substitution' in dct else None
            ),
            rule_predicate=kore_term(dct['rule-predicate']) if 'rule-predicate' in dct else None,
        )

    @staticmethod
    def _subst_to_dict(pattern: Pattern) -> dict[EVar, Pattern]:
        def extract_entry(pattern: Pattern) -> tuple[EVar, Pattern]:
            if not isinstance(pattern, Equals):
                raise ValueError(fr'Expected \equals as substituion entry, got: {pattern.text}')
            if pattern.sort != SORT_GENERATED_TOP_CELL:
                raise ValueError(
                    f'Expected {SORT_GENERATED_TOP_CELL.text} as substitution entry sort, got: {pattern.sort.text}'
                )
            if not isinstance(pattern.left, EVar):
                raise ValueError(f'Expected EVar as substitution entry key, got: {pattern.left.text}')
            if pattern.left.sort != pattern.op_sort:
                raise ValueError(
                    f'Mismatch between substitution entry and key sort: {pattern.op_sort.text} and {pattern.left.sort.text}'
                )
            return pattern.left, pattern.right

        res: dict[EVar, Pattern] = {}
        for conjunct in manip.conjuncts(pattern):
            key, value = extract_entry(conjunct)
            if key in res:
                raise ValueError(f'Duplicate substitution entry key: {key.text} -> {[res[key].text, value.text]}')
            res[key] = value
        return res

    @staticmethod
    def _dict_to_subst(dct: Mapping[EVar, Pattern]) -> And:
        return And(
            SORT_GENERATED_TOP_CELL,
            tuple(Equals(var.sort, SORT_GENERATED_TOP_CELL, var, val) for var, val in dct.items()),
        )

    @property
    def kore(self) -> Pattern:
        _kore = self.term
        if self.substitution is not None:
            _kore = And(SORT_GENERATED_TOP_CELL, (_kore,) + self._dict_to_subst(self.substitution).ops)
        if self.predicate is not None:
            _kore = And(SORT_GENERATED_TOP_CELL, (_kore, self.predicate))
        return _kore


class LogEntry(ABC):
    @classmethod
    def from_dict(cls: type[LE], dct: Mapping[str, Any]) -> LE:
        match dct['tag']:
            case 'rewrite':
                return LogRewrite.from_dict(dct)  # type: ignore
            case _:
                raise ValueError(f'Unsupported LogEntry tag: {dct["tag"]!r}')

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...


@final
@dataclass(frozen=True)
class LogRewrite(LogEntry):
    origin: LogOrigin
    result: RewriteResult

    @classmethod
    def from_dict(cls: type[LogRewrite], dct: Mapping[str, Any]) -> LogRewrite:
        return LogRewrite(
            origin=LogOrigin(dct['origin']),
            result=RewriteResult.from_dict(dct['result']),
        )

    def to_dict(self) -> dict[str, Any]:
        return {'tag': 'rewrite', 'origin': self.origin.value, 'result': self.result.to_dict()}


class LogOrigin(str, Enum):
    KORE_RPC = 'kore-rpc'
    BOOSTER = 'booster'
    PROXY = 'proxy'
    LLVM = 'llvm'


class RewriteResult(ABC):
    rule_id: str | None

    @classmethod
    def from_dict(cls: type[RR], dct: Mapping[str, Any]) -> RR:
        if dct['tag'] == 'success':
            return globals()['RewriteSuccess'].from_dict(dct)
        elif dct['tag'] == 'failure':
            return globals()['RewriteFailure'].from_dict(dct)
        else:
            raise ValueError(f"Expected {dct['tag']} as 'success'/'failure'")

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...


@final
@dataclass(frozen=True)
class RewriteSuccess(RewriteResult):
    rule_id: str
    rewritten_term: Pattern | None = None

    @classmethod
    def from_dict(cls: type[RewriteSuccess], dct: Mapping[str, Any]) -> RewriteSuccess:
        return RewriteSuccess(
            rule_id=dct['rule-id'],
            rewritten_term=kore_term(dct['rewritten-term']) if 'rewritten-term' in dct else None,
        )

    def to_dict(self) -> dict[str, Any]:
        rewritten_term = {'rewritten-term': KoreClient._state(self.rewritten_term)} if self.rewritten_term else {}
        return {'tag': 'success', 'rule-id': self.rule_id} | rewritten_term


@final
@dataclass(frozen=True)
class RewriteFailure(RewriteResult):
    rule_id: str | None
    reason: str

    @classmethod
    def from_dict(cls: type[RewriteFailure], dct: Mapping[str, Any]) -> RewriteFailure:
        return RewriteFailure(rule_id=dct.get('rule-id'), reason=dct['reason'])

    def to_dict(self) -> dict[str, Any]:
        return {'tag': 'failure', 'rule-id': self.rule_id, 'reason': self.reason}


def _parse_haskell_log_entries(dct: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Parse the optional per-request ``haskell-log-entries`` bundle (arbitrary JSON values).

    Present only when the request set a non-empty ``haskell-logging`` entry list; absent ⇒ ``None``.
    Entries are kept as raw JSON in ``--log-format json`` shape so they feed straight into ``parse_kore_log``.
    """
    entries = dct.get('haskell-log-entries')
    return tuple(entries) if entries is not None else None


class ExecuteResult(ABC):
    _TYPES: Mapping[StopReason, str] = {
        StopReason.STUCK: 'StuckResult',
        StopReason.DEPTH_BOUND: 'DepthBoundResult',
        StopReason.TIMEOUT: 'TimeoutResult',
        StopReason.BRANCHING: 'BranchingResult',
        StopReason.CUT_POINT_RULE: 'CutPointResult',
        StopReason.TERMINAL_RULE: 'TerminalResult',
        StopReason.VACUOUS: 'VacuousResult',
        StopReason.ABORTED: 'AbortedResult',
    }

    reason: ClassVar[StopReason]

    state: State
    depth: int
    next_states: tuple[State, ...] | None
    rule: str | None
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None

    @classmethod
    def from_dict(cls: type[ER], dct: Mapping[str, Any]) -> ER:
        return globals()[ExecuteResult._TYPES[StopReason(dct['reason'])]].from_dict(dct)  # type: ignore

    @classmethod
    def _check_reason(cls: type[ER], dct: Mapping[str, Any]) -> None:
        reason = StopReason(dct['reason'])
        if reason is not cls.reason:
            raise AssertionError(f"Expected {cls.reason} as 'reason', found: {reason}")


@final
@dataclass(frozen=True)
class StuckResult(ExecuteResult):
    # These fields should be Final, but it makes mypy crash
    # https://github.com/python/mypy/issues/10090
    reason = StopReason.STUCK
    next_states = None
    rule = None

    state: State
    depth: int
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[StuckResult], dct: Mapping[str, Any]) -> StuckResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return StuckResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class DepthBoundResult(ExecuteResult):
    reason = StopReason.DEPTH_BOUND
    next_states = None
    rule = None

    state: State
    depth: int
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[DepthBoundResult], dct: Mapping[str, Any]) -> DepthBoundResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return DepthBoundResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class TimeoutResult(ExecuteResult):
    reason = StopReason.TIMEOUT
    next_states = None
    rule = None

    state: State
    depth: int
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[TimeoutResult], dct: Mapping[str, Any]) -> TimeoutResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return TimeoutResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class BranchingResult(ExecuteResult):
    reason = StopReason.BRANCHING
    rule = None

    state: State
    depth: int
    next_states: tuple[State, ...]
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[BranchingResult], dct: Mapping[str, Any]) -> BranchingResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return BranchingResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            next_states=tuple(State.from_dict(next_state) for next_state in dct['next-states']),
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class CutPointResult(ExecuteResult):
    reason = StopReason.CUT_POINT_RULE

    state: State
    depth: int
    next_states: tuple[State, ...]
    rule: str
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[CutPointResult], dct: Mapping[str, Any]) -> CutPointResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return CutPointResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            next_states=tuple(State.from_dict(next_state) for next_state in dct['next-states']),
            rule=dct['rule'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class TerminalResult(ExecuteResult):
    reason = StopReason.TERMINAL_RULE
    next_states = None

    state: State
    depth: int
    rule: str
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[TerminalResult], dct: Mapping[str, Any]) -> TerminalResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return TerminalResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            rule=dct['rule'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class VacuousResult(ExecuteResult):
    reason = StopReason.VACUOUS
    next_states = None
    rule = None

    state: State
    depth: int
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[VacuousResult], dct: Mapping[str, Any]) -> VacuousResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return VacuousResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


@final
@dataclass(frozen=True)
class AbortedResult(ExecuteResult):
    reason = StopReason.ABORTED
    next_states = None
    rule = None

    state: State
    depth: int
    unknown_predicate: Pattern | None
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @classmethod
    def from_dict(cls: type[AbortedResult], dct: Mapping[str, Any]) -> AbortedResult:
        cls._check_reason(dct)
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return AbortedResult(
            state=State.from_dict(dct['state']),
            depth=dct['depth'],
            unknown_predicate=kore_term(dct['unknown-predicate']) if dct.get('unknown-predicate') else None,
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


class ImpliesStatus(Enum):
    """Tri-state verdict of an `implies` (subsumption) check, as reported on the wire.

    `INDETERMINATE` is booster's "could not decide" signal (an indeterminate match or an
    SMT-unknown obligation).  The kore-rpc proxy escalates it to a decisive kore verdict on
    every path except booster-only mode, so it only reaches a client that opted out of kore;
    such a client decides whether to trust it or escalate (recover-mode escalates to a kore
    implies; binary consumers treat it as the conservative not-implied `INVALID`).
    """

    VALID = 'valid'
    INVALID = 'invalid'
    INDETERMINATE = 'indeterminate'


@final
@dataclass(frozen=True)
class ImpliesResult:
    status: ImpliesStatus
    implication: Pattern
    substitution: Pattern | None
    predicate: Pattern | None
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None = None

    @staticmethod
    def from_dict(dct: Mapping[str, Any]) -> ImpliesResult:
        substitution = dct.get('condition', {}).get('substitution')
        predicate = dct.get('condition', {}).get('predicate')
        logs = tuple(LogEntry.from_dict(l) for l in dct['logs']) if 'logs' in dct else ()
        return ImpliesResult(
            status=ImpliesStatus(dct['status']),
            implication=kore_term(dct['implication']),
            substitution=kore_term(substitution) if substitution is not None else None,
            predicate=kore_term(predicate) if predicate is not None else None,
            logs=logs,
            haskell_log_entries=_parse_haskell_log_entries(dct),
        )


class SimplifyResult(NamedTuple):
    """Result of a ``simplify`` call.

    A ``NamedTuple`` (not a bare tuple) so the optional ``haskell_log_entries`` bundle can be
    carried alongside the simplified ``state`` and ``logs`` without losing positional ergonomics.
    """

    state: Pattern
    logs: tuple[LogEntry, ...]
    haskell_log_entries: tuple[Any, ...] | None


class GetModelResult(ABC):  # noqa: B024
    haskell_log_entries: tuple[Any, ...] | None

    @staticmethod
    def from_dict(dct: Mapping[str, Any]) -> GetModelResult:
        status = dct['satisfiable']
        entries = _parse_haskell_log_entries(dct)
        match status:
            case 'Unknown':
                return UnknownResult(haskell_log_entries=entries)
            case 'Unsat':
                return UnsatResult(haskell_log_entries=entries)
            case 'Sat':
                substitution = dct.get('substitution')
                return SatResult(
                    model=kore_term(substitution) if substitution else None,
                    haskell_log_entries=entries,
                )
            case _:
                raise ValueError(f'Unknown status: {status}')


@final
@dataclass(frozen=True)
class UnknownResult(GetModelResult):
    haskell_log_entries: tuple[Any, ...] | None = None


@final
@dataclass(frozen=True)
class UnsatResult(GetModelResult):
    haskell_log_entries: tuple[Any, ...] | None = None


@final
@dataclass(frozen=True)
class SatResult(GetModelResult):
    model: Pattern | None
    haskell_log_entries: tuple[Any, ...] | None = None


class KoreClient(ContextManager['KoreClient']):
    _KORE_JSON_VERSION: Final = 1

    port: int
    _client: JsonRpcClientFacade

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: int | None = None,
        bug_report: BugReport | None = None,
        bug_report_id: str | None = None,
        transport: TransportType = TransportType.SINGLE_SOCKET,
        dispatch: dict[str, list[tuple[str, int, TransportType]]] | None = None,
    ):
        if dispatch is None:
            dispatch = {}
        self.port = port
        self._client = JsonRpcClientFacade(
            host,
            port,
            transport,
            timeout=timeout,
            bug_report=bug_report,
            bug_report_id=bug_report_id,
            dispatch=dispatch,
        )

    def __enter__(self) -> KoreClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self._client.__exit__(*args)

    def close(self) -> None:
        self._client.close()

    @property
    def last_request_id(self) -> str | None:
        """The JSON-RPC id of the most recent request issued by this client.

        ``None`` before any request has been made.  Snapshot it immediately after a call
        (e.g. ``execute``/``implies``/``simplify``) to key per-request data (logs, handoff
        metadata) to that exact request.  Each proof worker drives its own ``KoreClient``
        (see ``_ProverPool``), so this needs no cross-thread synchronization.
        """
        return self._client.last_request_id

    def interrupt(self) -> None:
        """Abort an `execute`/`simplify`/… request running on another thread.

        Sends a `cancel` so the server stops computing; the interrupted call raises a
        "cancelled" error and the connection stays usable. Works on the single-socket
        transport only; a no-op for HTTP (one connection per request, nothing to cancel).
        """
        self._client.interrupt()

    def _request(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            return self._client.request(method, **params)
        except JsonRpcError as err:
            raise self._error(err) from err

    def _error(self, err: JsonRpcError) -> KoreClientError:
        assert err.code not in {-32601, -32602}, 'Malformed Kore-RPC request'
        match err.code:
            case 1:
                return ParseError(error=err.data)
            case 2:
                return PatternError(error=err.data['error'], context=err.data['context'])
            case 3:
                return UnknownModuleError(module_name=err.data)
            case 4:
                return ImplicationError(error=err.data['error'], context=err.data['context'])
            case 5:
                return SmtSolverError(error=err.data['error'], pattern=kore_term(err.data['term']))
            case 6:
                return AbortedError(data=err.data)
            case 8:
                return InvalidModuleError(error=err.data['error'], context=err.data.get('context'))
            case 9:
                return DuplicateModuleError(module_name=err.data)
            case _:
                return DefaultError(message=err.message, code=err.code, data=err.data)

    @staticmethod
    def _state(pattern: Pattern) -> dict[str, Any]:
        return {
            'format': 'KORE',
            'version': KoreClient._KORE_JSON_VERSION,
            'term': pattern.dict,
        }

    def execute(
        self,
        pattern: Pattern,
        *,
        max_depth: int | None = None,
        assume_state_defined: bool | None = None,
        cut_point_rules: Iterable[str] | None = None,
        terminal_rules: Iterable[str] | None = None,
        moving_average_step_timeout: bool | None = None,
        step_timeout: int | None = None,
        module_name: str | None = None,
        log_successful_rewrites: bool | None = None,
        log_failed_rewrites: bool | None = None,
        booster_only_simplify: bool | None = None,
        haskell_logging: Iterable[str] | None = None,
    ) -> ExecuteResult:
        params = filter_none(
            {
                'max-depth': max_depth,
                'assume-state-defined': assume_state_defined,
                'cut-point-rules': list(cut_point_rules) if cut_point_rules is not None else None,
                'terminal-rules': list(terminal_rules) if terminal_rules is not None else None,
                'moving-average-step-timeout': moving_average_step_timeout,
                'step-timeout': step_timeout,
                'module': module_name,
                'state': self._state(pattern),
                'log-successful-rewrites': log_successful_rewrites,
                'log-failed-rewrites': log_failed_rewrites,
                'booster-only': booster_only_simplify,
                'haskell-logging': list(haskell_logging) if haskell_logging is not None else None,
            }
        )

        result = self._request('execute', **params)
        return ExecuteResult.from_dict(result)

    def implies(
        self,
        antecedent: Pattern,
        consequent: Pattern,
        *,
        module_name: str | None = None,
        assume_defined: bool = False,
        booster_only_simplify: bool | None = None,
        haskell_logging: Iterable[str] | None = None,
    ) -> ImpliesResult:
        params = filter_none(
            {
                'antecedent': self._state(antecedent),
                'consequent': self._state(consequent),
                'module': module_name,
                'assume-defined': assume_defined,
                'booster-only': booster_only_simplify,
                'haskell-logging': list(haskell_logging) if haskell_logging is not None else None,
            }
        )

        result = self._request('implies', **params)
        return ImpliesResult.from_dict(result)

    def simplify(
        self,
        pattern: Pattern,
        *,
        module_name: str | None = None,
        booster_only_simplify: bool | None = None,
        haskell_logging: Iterable[str] | None = None,
    ) -> SimplifyResult:
        params = filter_none(
            {
                'state': self._state(pattern),
                'module': module_name,
                'booster-only': booster_only_simplify,
                'haskell-logging': list(haskell_logging) if haskell_logging is not None else None,
            }
        )

        result = self._request('simplify', **params)
        logs = tuple(LogEntry.from_dict(l) for l in result['logs']) if 'logs' in result else ()
        return SimplifyResult(kore_term(result['state']), logs, _parse_haskell_log_entries(result))

    def get_model(
        self,
        pattern: Pattern,
        module_name: str | None = None,
        haskell_logging: Iterable[str] | None = None,
    ) -> GetModelResult:
        params = filter_none(
            {
                'state': self._state(pattern),
                'module': module_name,
                'haskell-logging': list(haskell_logging) if haskell_logging is not None else None,
            }
        )

        result = self._request('get-model', **params)
        return GetModelResult.from_dict(result)

    def add_module(
        self,
        module: Module,
        *,
        name_as_id: bool | None = None,
        haskell_logging: Iterable[str] | None = None,
    ) -> str:
        params = filter_none(
            {
                'module': module.text,
                'name-as-id': name_as_id,
                'haskell-logging': list(haskell_logging) if haskell_logging is not None else None,
            }
        )
        result = self._request('add-module', **params)
        return result['module']


class KoreServerArgs(TypedDict, total=False):
    kompiled_dir: Required[str | Path]
    module_name: Required[str]
    port: int | None
    command: str | Iterable[str] | None
    smt_timeout: int | None
    smt_retry_limit: int | None
    smt_reset_interval: int | None
    smt_tactic: str | None
    log_axioms_file: Path | None
    haskell_log_format: KoreExecLogFormat | None
    haskell_log_entries: Iterable[str] | None
    bug_report: BugReport | None
    haskell_threads: int | None


class KoreServerInfo(NamedTuple):
    pid: int
    host: str
    port: int


class KoreServer(ContextManager['KoreServer']):
    _proc: Popen
    _stdout_reader: Thread
    _stderr_reader: Thread
    _info: KoreServerInfo

    _kompiled_dir: Path
    _definition_file: Path
    _module_name: str
    _port: int
    _command: list[str]
    _smt_timeout: int | None
    _smt_retry_limit: int | None
    _smt_reset_interval: int | None
    _smt_tactic: str | None
    _log_axioms_file: Path | None
    _haskell_log_format: KoreExecLogFormat
    _haskell_log_entries: list[str]
    _haskell_threads: int | None

    _bug_report: BugReport | None

    def __init__(self, args: KoreServerArgs):
        self._kompiled_dir = Path(args['kompiled_dir'])
        self._definition_file = self._kompiled_dir / 'definition.kore'
        self._module_name = args['module_name']
        self._port = args.get('port') or 0

        if not (command := args.get('command')):
            self._command = ['kore-rpc']
        elif type(command) is str:
            self._command = command.split()
        else:
            self._command = list(command)

        self._smt_timeout = args.get('smt_timeout')
        self._smt_retry_limit = args.get('smt_retry_limit')
        self._smt_reset_interval = args.get('smt_reset_interval')
        self._smt_tactic = args.get('smt_tactic')
        self._log_axioms_file = args.get('log_axioms_file')

        self._haskell_log_format = args.get('haskell_log_format') or KoreExecLogFormat.ONELINE

        if haskell_log_entries := args.get('haskell_log_entries'):
            self._haskell_log_entries = list(haskell_log_entries)
        else:
            self._haskell_log_entries = []

        self._haskell_threads = args.get('haskell_threads') or 1

        self._bug_report = args.get('bug_report')

        self._validate()
        self.start()

    @property
    def pid(self) -> int:
        return self._info.pid

    @property
    def host(self) -> str:
        return self._info.host

    @property
    def port(self) -> int:
        return self._info.port

    def __enter__(self) -> KoreServer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._bug_report:
            self._populate_bug_report(self._bug_report)

        cli_args = self._cli_args()

        new_env = os.environ.copy()
        new_env['GHCRTS'] = ' '.join(
            part
            for part in [
                f'-N{self._haskell_threads}',
                new_env.get('GHCRTS'),
            ]
            if part
        )

        _LOGGER.info(f'Starting KoreServer: {" ".join(cli_args)}')
        self._proc, self._stdout_reader, self._stderr_reader = self._create_proc(cli_args, new_env)
        pid = self._proc.pid
        host, port = self._get_host_and_port(pid)
        if self._port:
            assert port == self._port
        self._info = KoreServerInfo(pid=pid, host=host, port=port)
        _LOGGER.info(f'KoreServer started: {self.host}:{self.port}, pid={self.pid}')

    @staticmethod
    def _create_proc(args: list[str], env: dict[str, str]) -> tuple[Popen, Thread, Thread]:
        popen = Popen(args, env=env, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, text=True)

        def reader(fh: IO[str], prefix: str) -> None:
            for line in fh:
                _LOGGER.info(f'[PID={popen.pid}][{prefix}] {line.rstrip()}')

        stdout_reader = Thread(target=reader, args=(popen.stdout, 'stdo'))
        stdout_reader.daemon = True
        stdout_reader.start()

        stderr_reader = Thread(target=reader, args=(popen.stderr, 'stde'))
        stderr_reader.daemon = True
        stderr_reader.start()

        return popen, stdout_reader, stderr_reader

    def close(self) -> None:
        _LOGGER.info(f'Stopping KoreServer: {self.host}:{self.port}, pid={self.pid}')
        if '--solver-transcript' in self._command:
            self._proc.send_signal(SIGINT)
        else:
            self._proc.terminate()
        self._proc.wait()
        self._stdout_reader.join()
        self._stderr_reader.join()
        _LOGGER.info(f'KoreServer stopped: {self.host}:{self.port}, pid={self.pid}')

    def _validate(self) -> None:
        def _check_none_or_positive(n: int | None, param_name: str) -> None:
            if n is not None and n <= 0:
                raise ValueError(f'Expected positive integer for: {param_name}, got: {n}')

        def _check_none_or_nonnegative(n: int | None, param_name: str) -> None:
            if n is not None and n < 0:
                raise ValueError(f'Expected non-negative integer for: {param_name}, got: {n}')

        check_dir_path(self._kompiled_dir)
        check_file_path(self._definition_file)
        _check_none_or_positive(self._smt_timeout, 'smt_timeout')
        _check_none_or_nonnegative(self._smt_retry_limit, 'smt_retry_limit')
        _check_none_or_positive(self._smt_reset_interval, 'smt_reset_interval')

    def _cli_args(self) -> list[str]:
        server_args = ['--module', self._module_name, '--server-port', str(self._port)]
        res = list(self._command)
        res += [str(self._definition_file)]
        res += server_args
        res += self._extra_args()
        return res

    def _extra_args(self) -> list[str]:
        """Command line arguments that are intended to be included in the bug report."""
        smt_server_args = []
        if self._smt_timeout is not None:
            smt_server_args += ['--smt-timeout', str(self._smt_timeout)]
        if self._smt_retry_limit is not None:
            smt_server_args += ['--smt-retry-limit', str(self._smt_retry_limit)]
        if self._smt_reset_interval is not None:
            smt_server_args += ['--smt-reset-interval', str(self._smt_reset_interval)]
        if self._smt_tactic is not None:
            smt_server_args += ['--smt-tactic', self._smt_tactic]

        return smt_server_args + self._haskell_log_cli_args()

    def _haskell_log_cli_args(self) -> list[str]:
        # kore-rpc form: `--log FILE`, `--log-entries A,B,C`.  Booster overrides for `--log-file FILE` and repeated `-l`.
        if self._log_axioms_file is None:
            return []
        return [
            '--log',
            str(self._log_axioms_file),
            '--log-format',
            self._haskell_log_format.value,
            '--log-entries',
            ','.join(self._haskell_log_entries),
        ]

    def _populate_bug_report(self, bug_report: BugReport) -> None:
        prog_name = self._command[0]
        bug_report.add_file(self._definition_file, Path('definition.kore'))
        version_info = run_process_2((prog_name, '--version'), logger=_LOGGER).stdout.strip()
        bug_report.add_file_contents(version_info, Path('server_version.txt'))
        server_instance = {
            'exe': prog_name,
            'module': self._module_name,
            'extra_args': self._command[1:] + self._extra_args(),
        }
        bug_report.add_file_contents(json.dumps(server_instance), Path('server_instance.json'))

    @staticmethod
    def _get_host_and_port(pid: int) -> tuple[str, int]:
        proc = Process(pid)
        while not proc.connections():
            sleep(0.01)
        conns = proc.connections()
        assert len(conns) == 1
        conn = conns[0]
        return conn.laddr


class FallbackReason(Enum):
    BRANCHING = 'Branching'
    STUCK = 'Stuck'
    ABORTED = 'Aborted'


class BoosterServerArgs(KoreServerArgs, total=False):
    llvm_kompiled_dir: Required[str | Path]
    fallback_on: Iterable[str | FallbackReason] | None
    interim_simplification: int | None
    simplify_each: int | None
    no_post_exec_simplify: bool | None
    log_context: Iterable[str] | None
    not_log_context: Iterable[str] | None


class BoosterServer(KoreServer):
    _llvm_kompiled_dir: Path
    _dylib: Path
    _llvm_definition: Path
    _llvm_dt: Path

    _fallback_on: list[FallbackReason] | None
    _interim_simplification: int | None
    _simplify_each: int | None
    _no_post_exec_simplify: bool
    _log_context: list[str]
    _not_log_context: list[str]

    def __init__(self, args: BoosterServerArgs):
        self._llvm_kompiled_dir = Path(args['llvm_kompiled_dir'])

        ext: str
        match sys.platform:
            case 'linux':
                ext = 'so'
            case 'darwin':
                ext = 'dylib'
            case _:
                raise ValueError('Unsupported platform: {sys.platform}')

        self._dylib = self._llvm_kompiled_dir / f'interpreter.{ext}'
        self._llvm_definition = self._llvm_kompiled_dir / 'definition.kore'
        self._llvm_dt = self._llvm_kompiled_dir / 'dt'

        if fallback_on := args.get('fallback_on'):
            self._fallback_on = [FallbackReason(reason) for reason in fallback_on]
        else:
            self._fallback_on = None

        self._interim_simplification = args.get('interim_simplification')
        self._simplify_each = args.get('simplify_each')
        self._no_post_exec_simplify = bool(args.get('no_post_exec_simplify'))
        self._log_context = list(args.get('log_context') or [])
        self._not_log_context = list(args.get('not_log_context') or [])

        if not args.get('command'):
            args['command'] = 'kore-rpc-booster'

        super().__init__(args)

    def _validate(self) -> None:
        check_dir_path(self._llvm_kompiled_dir)
        check_file_path(self._dylib)
        check_file_path(self._llvm_definition)
        check_dir_path(self._llvm_dt)

        if self._fallback_on is not None and not self._fallback_on:
            raise ValueError("'fallback_on' must not be empty")

        if self._interim_simplification and self._interim_simplification < 0:
            raise ValueError(f"'interim_simplification' must not be negative, got: {self._interim_simplification}")

        if self._simplify_each and self._simplify_each < 0:
            raise ValueError(f"'simplify_each' must not be negative, got: {self._simplify_each}")

        super()._validate()

    def _extra_args(self) -> list[str]:
        res = super()._extra_args()
        res += ['--llvm-backend-library', str(self._dylib)]
        if self._fallback_on is not None:
            res += ['--fallback-on', ','.join(reason.value for reason in self._fallback_on)]
        if self._interim_simplification is not None:
            res += ['--interim-simplification', str(self._interim_simplification)]
        if self._simplify_each is not None:
            res += ['--simplify-each', str(self._simplify_each)]
        if self._no_post_exec_simplify:
            res += ['--no-post-exec-simplify']
        res += [arg for glob in self._log_context for arg in ['--log-context', glob]]
        res += [arg for glob in self._not_log_context for arg in ['--not-log-context', glob]]
        return res

    def _haskell_log_cli_args(self) -> list[str]:
        # kore-rpc-booster diverged from kore-rpc: `--log-file FILE` (not `--log FILE`),
        # and repeated `-l ENTRY` (not `--log-entries A,B,C`).
        if self._log_axioms_file is None:
            return []
        args = [
            '--log-file',
            str(self._log_axioms_file),
            '--log-format',
            self._haskell_log_format.value,
        ]
        for entry in self._haskell_log_entries:
            args += ['-l', entry]
        return args

    def _populate_bug_report(self, bug_report: BugReport) -> None:
        super()._populate_bug_report(bug_report)
        bug_report.add_file(self._llvm_definition, Path('llvm_definition/definition.kore'))
        llvm_version = run_process_2('llvm-backend-version', logger=_LOGGER).stdout.strip()
        bug_report.add_file_contents(llvm_version, Path('llvm_version.txt'))


def kore_server(
    definition_dir: str | Path,
    module_name: str,
    *,
    port: int | None = None,
    command: str | Iterable[str] | None = None,
    smt_timeout: int | None = None,
    smt_retry_limit: int | None = None,
    smt_tactic: str | None = None,
    log_axioms_file: Path | None = None,
    haskell_log_format: KoreExecLogFormat | None = None,
    haskell_log_entries: Iterable[str] | None = None,
    haskell_threads: int | None = None,
    # booster
    llvm_definition_dir: Path | None = None,
    fallback_on: Iterable[str | FallbackReason] | None = None,
    interim_simplification: int | None = None,
    simplify_each: int | None = None,
    no_post_exec_simplify: bool | None = None,
    # ---
    bug_report: BugReport | None = None,
) -> KoreServer:
    kore_args: KoreServerArgs = {
        'kompiled_dir': definition_dir,
        'module_name': module_name,
        'port': port,
        'command': command,
        'smt_timeout': smt_timeout,
        'smt_retry_limit': smt_retry_limit,
        'log_axioms_file': log_axioms_file,
        'smt_tactic': smt_tactic,
        'haskell_log_format': haskell_log_format,
        'haskell_log_entries': haskell_log_entries,
        'haskell_threads': haskell_threads,
        'bug_report': bug_report,
    }
    if llvm_definition_dir:
        booster_args: BoosterServerArgs = {
            'llvm_kompiled_dir': llvm_definition_dir,
            'fallback_on': fallback_on,
            'interim_simplification': interim_simplification,
            'simplify_each': simplify_each,
            'no_post_exec_simplify': no_post_exec_simplify,
            **kore_args,
        }
        return BoosterServer(booster_args)
    return KoreServer(kore_args)
