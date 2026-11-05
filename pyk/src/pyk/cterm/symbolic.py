from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, final

from ..cterm import CSubst, CTerm
from ..kast.inner import KApply, KLabel, KRewrite, KToken, KVariable, Subst
from ..kast.manip import flatten_label, is_spurious_constraint, sort_ac_collections
from ..kast.prelude.k import GENERATED_TOP_CELL, K_ITEM
from ..kast.prelude.ml import mlAnd
from ..kast.pretty import PrettyPrinter
from ..konvert import kast_to_kore, kflatmodule_to_kore, kore_to_kast
from ..kore.rpc import (
    AbortedError,
    AbortedResult,
    ImpliesStatus,
    KoreClient,
    KoreExecLogFormat,
    SatResult,
    SmtSolverError,
    StopReason,
    UnknownResult,
    UnsatResult,
    kore_server,
)
from ..utils import not_none

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from typing import Any, Final

    from ..kast import KInner
    from ..kast.outer import KDefinition, KFlatModule
    from ..kore.rpc import FallbackReason, LogEntry
    from ..kore.syntax import Pattern
    from ..utils import BugReport


_LOGGER: Final = logging.getLogger(__name__)


#: Canonical default set of haskell-backend log entries to capture per request for fallback
#: diagnosis.  Spans both engines: kore entry types (resolved by the backend against its log
#: registry) and booster context tags.  Sent verbatim on the ``haskell-logging`` request field;
#: the backend skips any name it does not recognise, so this can evolve without a lockstep backend
#: release.  Override per ``CTermSymbolic`` (e.g. downstream semantics needing a different set).
HASKELL_LOGGING_ENTRIES: Final = (
    # Kore engine: equation attempt/application plus the term index that resolves their hashes.
    'DebugAttemptEquation',
    'DebugApplyEquation',
    'DebugTerm',
    # Booster: proxy/fallback decisions, detail, aborts, simplification, and rewrite steps.
    'Proxy',
    'Detail',
    'Abort',
    'Simplify',
    'Rewrite',
)


class NextState(NamedTuple):
    state: CTerm
    condition: KInner | None


class CTermExecute(NamedTuple):
    state: CTerm
    next_states: tuple[NextState, ...]
    depth: int
    vacuous: bool
    logs: tuple[LogEntry, ...]


class CTermImplies(NamedTuple):
    csubst: CSubst | None
    failing_cells: tuple[tuple[str, KInner], ...]
    remaining_implication: KInner | None
    logs: tuple[LogEntry, ...]
    # True when the backend aborted the implies (it could not decide it) — a couldn't-determine,
    # not a decisive verdict.  Recover-mode escalates on it instead of trusting `csubst is None`.
    indeterminate: bool = False


@final
@dataclass
class CTermSMTError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CTermSymbolic:
    _kore_client: KoreClient
    _definition: KDefinition
    _log_succ_rewrites: bool
    _log_fail_rewrites: bool
    _booster_only_simplify: bool
    _haskell_log_entries: tuple[str, ...]
    _haskell_log_dir: Path | None

    def __init__(
        self,
        kore_client: KoreClient,
        definition: KDefinition,
        *,
        log_succ_rewrites: bool = True,
        log_fail_rewrites: bool = False,
        booster_only_simplify: bool = False,
        haskell_log_entries: Iterable[str] = HASKELL_LOGGING_ENTRIES,
        haskell_log_dir: Path | None = None,
    ):
        self._kore_client = kore_client
        self._definition = definition
        self._log_succ_rewrites = log_succ_rewrites
        self._log_fail_rewrites = log_fail_rewrites
        self._booster_only_simplify = booster_only_simplify
        # *Which* entries to request when logging is on; this populated default is not itself a
        # switch — logging stays off until `haskell_log_dir` is set (or a per-call flag enables it).
        # Overridable so downstream callers can tailor the set.
        self._haskell_log_entries = tuple(haskell_log_entries)
        # The switch: when set, every RPC requests the per-request `haskell-logging` bundle and the
        # captured entries are written to `<haskell_log_dir>/<request_id>.jsonl` (one JSON value per line).
        self._haskell_log_dir = haskell_log_dir

    def kast_to_kore(self, kinner: KInner) -> Pattern:
        return kast_to_kore(self._definition, kinner, sort=GENERATED_TOP_CELL)

    def kore_to_kast(self, pattern: Pattern) -> KInner:
        return kore_to_kast(self._definition, pattern)

    def interrupt(self) -> None:
        """Abort a backend request currently in flight on another thread; see `KoreClient.interrupt`."""
        self._kore_client.interrupt()

    def _haskell_logging_request(self, haskell_logging: bool | None) -> tuple[str, ...] | None:
        """Resolve the per-call on/off flag to the list of log entries to request.

        An explicit per-call value wins; otherwise logging is on exactly when a ``haskell_log_dir``
        is configured (so the captured bundle has somewhere to land).  When on, the configured entry
        set is requested; when off — or the set is empty — the wire field is omitted (``None``).
        """
        enabled = haskell_logging if haskell_logging is not None else self._haskell_log_dir is not None
        return self._haskell_log_entries if enabled and self._haskell_log_entries else None

    def _capture_haskell_log(self, entries: tuple[Any, ...] | None) -> None:
        """Write a response's ``haskell-log-entries`` bundle to its own file.

        No-op unless a ``haskell_log_dir`` is configured and ``entries`` is non-empty.  Each entry
        is one JSON value per line (jsonl), in a file named for the request id (taken from the
        backing client) so concurrent proof workers never collide.
        """
        if self._haskell_log_dir is None or not entries:
            return
        request_id = self._kore_client.last_request_id
        if request_id is None:
            return
        self._haskell_log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._haskell_log_dir / f'{request_id}.jsonl'
        log_file.write_text('\n'.join(json.dumps(entry) for entry in entries) + '\n')

    @property
    def last_request_id(self) -> str | None:
        """JSON-RPC id of the most recent RPC issued by the backing client (see `KoreClient.last_request_id`).

        Recover-mode snapshots this immediately after a simplify to key the `KoreHandoff` to that
        request, so a handoff can be correlated with the per-request log file that the configured
        `haskell_log_dir` writer (see `_capture_haskell_log`) emits for the same id.
        """
        return self._kore_client.last_request_id

    def execute(
        self,
        cterm: CTerm,
        depth: int | None = None,
        cut_point_rules: Iterable[str] | None = None,
        terminal_rules: Iterable[str] | None = None,
        module_name: str | None = None,
        booster_only_simplify: bool | None = None,
        haskell_logging: bool | None = None,
        raise_on_aborted: bool = True,
    ) -> CTermExecute:

        _LOGGER.debug(f'Executing: {cterm}')
        kore = self.kast_to_kore(cterm.kast)
        try:
            response = self._kore_client.execute(
                kore,
                max_depth=depth,
                cut_point_rules=cut_point_rules,
                terminal_rules=terminal_rules,
                module_name=module_name,
                log_successful_rewrites=self._log_succ_rewrites,
                log_failed_rewrites=self._log_succ_rewrites and self._log_fail_rewrites,
                booster_only_simplify=(
                    booster_only_simplify if booster_only_simplify is not None else self._booster_only_simplify
                ),
                haskell_logging=self._haskell_logging_request(haskell_logging),
            )
        except SmtSolverError as err:
            raise self._smt_solver_error(err) from err
        self._capture_haskell_log(response.haskell_log_entries)

        # Under booster-only execution, an `AbortedResult` is the expected signal that the booster
        # could make no further progress (it is what drives the recover-mode ladder).  Callers that
        # expect aborts pass `raise_on_aborted=False`; the `AbortedResult.reason`/`next_states`
        # class attributes let the rest of this body proceed unchanged, and a no-progress abort
        # surfaces as a depth-0 result.
        if raise_on_aborted and isinstance(response, AbortedResult):
            unknown_predicate = response.unknown_predicate.text if response.unknown_predicate else None
            raise ValueError(f'Backend responded with aborted state. Unknown predicate: {unknown_predicate}')

        state = CTerm.from_kast(self.kore_to_kast(response.state.kore))
        resp_next_states = response.next_states or ()
        branching_constraints = tuple(
            self.kore_to_kast(not_none(s.rule_predicate)) if s.rule_predicate is not None else None
            for s in resp_next_states
        )
        next_states = tuple(
            NextState(CTerm.from_kast(self.kore_to_kast(ns.kore)), c)
            for ns, c in zip(resp_next_states, branching_constraints, strict=True)
        )

        assert all(not cterm.is_bottom for cterm, _ in next_states)
        assert len(next_states) != 1 or response.reason is StopReason.CUT_POINT_RULE

        return CTermExecute(
            state=state,
            next_states=next_states,
            depth=response.depth,
            vacuous=response.reason is StopReason.VACUOUS,
            logs=response.logs,
        )

    def simplify(
        self,
        cterm: CTerm,
        module_name: str | None = None,
        booster_only_simplify: bool | None = None,
        haskell_logging: bool | None = None,
    ) -> tuple[CTerm, tuple[LogEntry, ...]]:
        _LOGGER.debug(f'Simplifying: {cterm}')
        kast_simplified, logs = self.kast_simplify(
            cterm.kast,
            module_name=module_name,
            booster_only_simplify=booster_only_simplify,
            haskell_logging=haskell_logging,
        )
        return CTerm.from_kast(kast_simplified), logs

    def kast_simplify(
        self,
        kast: KInner,
        module_name: str | None = None,
        booster_only_simplify: bool | None = None,
        haskell_logging: bool | None = None,
    ) -> tuple[KInner, tuple[LogEntry, ...]]:
        _LOGGER.debug(f'Simplifying: {kast}')
        kore = self.kast_to_kore(kast)
        try:
            kore_simplified, logs, entries = self._kore_client.simplify(
                kore,
                module_name=module_name,
                booster_only_simplify=(
                    booster_only_simplify if booster_only_simplify is not None else self._booster_only_simplify
                ),
                haskell_logging=self._haskell_logging_request(haskell_logging),
            )
        except SmtSolverError as err:
            raise self._smt_solver_error(err) from err
        self._capture_haskell_log(entries)

        kast_simplified = self.kore_to_kast(kore_simplified)
        return kast_simplified, logs

    def get_model(self, cterm: CTerm, module_name: str | None = None) -> Subst | None:
        _LOGGER.debug(f'Getting model: {cterm}')
        kore = self.kast_to_kore(cterm.kast)
        try:
            result = self._kore_client.get_model(kore, module_name=module_name)
        except SmtSolverError as err:
            raise self._smt_solver_error(err) from err

        if type(result) is UnknownResult:
            _LOGGER.debug('Result is Unknown')
            return None
        elif type(result) is UnsatResult:
            _LOGGER.debug('Result is UNSAT')
            return None
        elif type(result) is SatResult:
            _LOGGER.debug('Result is SAT')
            if not result.model:
                return Subst({})
            model_subst = self.kore_to_kast(result.model)
            try:
                return Subst.from_pred(model_subst)
            except ValueError as err:
                raise AssertionError(f'Received a non-substitution from get-model endpoint: {model_subst}') from err

        else:
            raise AssertionError('Received an invalid response from get-model endpoint')

    def implies(
        self,
        antecedent: CTerm,
        consequent: CTerm,
        bind_universally: bool = False,
        failure_reason: bool = False,
        module_name: str | None = None,
        assume_defined: bool = False,
        booster_only_simplify: bool | None = None,
        haskell_logging: bool | None = None,
    ) -> CTermImplies:
        _LOGGER.debug(f'Checking implication: {antecedent} #Implies {consequent}')
        _consequent = consequent.kast
        unbound_consequent = [v for v in consequent.free_vars if v not in antecedent.free_vars]
        if len(unbound_consequent) > 0:
            bind_text, bind_label = ('existentially', '#Exists')
            if bind_universally:
                bind_text, bind_label = ('universally', '#Forall')
            _LOGGER.debug(f'Binding variables in consequent {bind_text}: {unbound_consequent}')
            for uc in unbound_consequent:
                # Setting Sort1 to KItem in #Exists to avoid inferring the type of each uc.
                # This should not have any effect on the resulting KORE pattern (\exists only has Sort2 as sort variable).
                _consequent = KApply(KLabel(bind_label, [K_ITEM, GENERATED_TOP_CELL]), [KVariable(uc), _consequent])
        antecedent_kore = self.kast_to_kore(antecedent.kast)
        consequent_kore = self.kast_to_kore(_consequent)
        try:
            result = self._kore_client.implies(
                antecedent_kore,
                consequent_kore,
                module_name=module_name,
                assume_defined=assume_defined,
                booster_only_simplify=(
                    booster_only_simplify if booster_only_simplify is not None else self._booster_only_simplify
                ),
                haskell_logging=self._haskell_logging_request(haskell_logging),
            )
        except SmtSolverError as err:
            raise self._smt_solver_error(err) from err
        except AbortedError as err:
            # The backend aborted because it could not decide the implication (e.g. constraints
            # the engine cannot discharge).  Surface it as an indeterminate, not-subsumed result,
            # so callers (notably recover-mode's TRY_KORE escalation, which calls kore-implies
            # directly and so sees the raw abort the proxy would otherwise absorb) treat it as
            # "unknown" instead of crashing.
            _LOGGER.warning(f'implies aborted, treating as indeterminate: {err.data}')
            return CTermImplies(None, (), None, (), indeterminate=True)
        self._capture_haskell_log(result.haskell_log_entries)

        if result.status is ImpliesStatus.INDETERMINATE:
            # The backend could not decide the subsumption (booster's indeterminate-match or
            # SMT-unknown path, which replaced the old hard AbortedError on some non-decisive
            # outcomes). Surface as indeterminate so recover-mode escalates to a kore implies,
            # mirroring the AbortedError catch above. The decisive failing-cell /
            # remaining-implication computation below is meaningless here.
            _LOGGER.debug('implies returned indeterminate, treating as indeterminate')
            return CTermImplies(None, (), None, result.logs, indeterminate=True)

        if result.status is ImpliesStatus.INVALID:
            if result.substitution is not None:
                _LOGGER.debug(f'Received a non-empty substitution for falsifiable implication: {result.substitution}')
            if result.predicate is not None:
                _LOGGER.debug(f'Received a non-empty predicate for falsifiable implication: {result.predicate}')
            failing_cells: list[tuple[str, KInner]] = []
            remaining_implication: KInner | None = None
            if failure_reason:
                _config_match = self.implies(
                    CTerm.from_kast(antecedent.config),
                    CTerm.from_kast(consequent.config),
                    bind_universally=bind_universally,
                    failure_reason=False,
                    module_name=module_name,
                    assume_defined=assume_defined,
                    booster_only_simplify=booster_only_simplify,
                    haskell_logging=haskell_logging,
                )
                config_match = _config_match.csubst
                if config_match is None:
                    curr_cell_match = Subst({})
                    for cell in antecedent.cells:
                        antecedent_cell = sort_ac_collections(antecedent.cell(cell))

                        if cell not in consequent.cells:
                            failing_cells.append((cell, KRewrite(antecedent_cell, KToken('.K', sort='KItem'))))
                        else:
                            consequent_cell = sort_ac_collections(consequent.cell(cell))
                            cell_match = consequent_cell.match(antecedent_cell)
                            if cell_match is not None:
                                _curr_cell_match = curr_cell_match.union(cell_match)
                                if _curr_cell_match is not None:
                                    curr_cell_match = _curr_cell_match
                                    continue
                            failing_cells.append((cell, KRewrite(antecedent_cell, consequent_cell)))
                else:
                    consequent_constraints = list(
                        filter(
                            lambda x: not is_spurious_constraint(x),
                            map(config_match.subst, consequent.constraints),
                        )
                    )
                    remaining_implication = CTerm._ml_impl(antecedent.constraints, consequent_constraints)
            return CTermImplies(None, tuple(failing_cells), remaining_implication, result.logs)

        if result.substitution is None:
            raise ValueError('Received empty substutition for valid implication.')
        if result.predicate is None:
            raise ValueError('Received empty predicate for valid implication.')
        ml_subst = self.kore_to_kast(result.substitution)
        ml_pred = self.kore_to_kast(result.predicate)
        ml_subst_pred = mlAnd(flatten_label('#And', ml_subst) + flatten_label('#And', ml_pred))
        csubst = CSubst.from_pred(ml_subst_pred)
        return CTermImplies(csubst, (), None, result.logs)

    def assume_defined(
        self, cterm: CTerm, module_name: str | None = None, booster_only_simplify: bool = False
    ) -> CTerm:
        _LOGGER.debug(f'Computing definedness condition for: {cterm}')
        cterm_simplified, logs = self.simplify(
            cterm, module_name=module_name, booster_only_simplify=booster_only_simplify
        )
        kast = KApply(KLabel('#Ceil', [GENERATED_TOP_CELL, GENERATED_TOP_CELL]), [cterm_simplified.config])
        kast_simplified, logs = self.kast_simplify(
            kast, module_name=module_name, booster_only_simplify=booster_only_simplify
        )
        _LOGGER.debug(f'Definedness condition computed: {kast_simplified}')
        return cterm.add_constraint(kast_simplified)

    def add_module(self, module: KFlatModule, name_as_id: bool = False) -> str:
        _kore_module = kflatmodule_to_kore(self._definition, module)
        return self._kore_client.add_module(_kore_module, name_as_id=name_as_id)

    def _smt_solver_error(self, err: SmtSolverError) -> CTermSMTError:
        kast = self.kore_to_kast(err.pattern)
        pretty_pattern = PrettyPrinter(self._definition).print(kast)
        return CTermSMTError(pretty_pattern)


@contextmanager
def cterm_symbolic(
    definition: KDefinition,
    definition_dir: Path,
    *,
    id: str | None = None,
    port: int | None = None,
    kore_rpc_command: str | Iterable[str] | None = None,
    llvm_definition_dir: Path | None = None,
    smt_timeout: int | None = None,
    smt_retry_limit: int | None = None,
    smt_tactic: str | None = None,
    bug_report: BugReport | None = None,
    haskell_log_format: KoreExecLogFormat = KoreExecLogFormat.ONELINE,
    haskell_log_entries: Iterable[str] = (),
    log_axioms_file: Path | None = None,
    log_succ_rewrites: bool = True,
    log_fail_rewrites: bool = False,
    booster_only_simplify: bool = False,
    haskell_log_dir: Path | None = None,
    start_server: bool = True,
    fallback_on: Iterable[FallbackReason] | None = None,
    interim_simplification: int | None = None,
    simplify_each: int | None = None,
    no_post_exec_simplify: bool = False,
) -> Iterator[CTermSymbolic]:
    # `haskell_log_entries` feeds both the legacy server-side `-l` file logging and the new
    # per-request capture set.  For the latter, fall back to the canonical default when the caller
    # leaves it unset, so the per-request bundle works out of the box while still letting clients
    # override which entries to request here.
    request_log_entries = tuple(haskell_log_entries) or HASKELL_LOGGING_ENTRIES
    if start_server:
        # Old way of handling KoreServer, to be removed
        with kore_server(
            definition_dir=definition_dir,
            llvm_definition_dir=llvm_definition_dir,
            module_name=definition.main_module_name,
            port=port,
            command=kore_rpc_command,
            bug_report=bug_report,
            smt_timeout=smt_timeout,
            smt_retry_limit=smt_retry_limit,
            smt_tactic=smt_tactic,
            haskell_log_format=haskell_log_format,
            haskell_log_entries=haskell_log_entries,
            log_axioms_file=log_axioms_file,
            fallback_on=fallback_on,
            interim_simplification=interim_simplification,
            simplify_each=simplify_each,
            no_post_exec_simplify=no_post_exec_simplify,
        ) as server:
            with KoreClient('localhost', server.port, bug_report=bug_report, bug_report_id=id) as client:
                yield CTermSymbolic(
                    client,
                    definition,
                    log_succ_rewrites=log_succ_rewrites,
                    log_fail_rewrites=log_fail_rewrites,
                    booster_only_simplify=booster_only_simplify,
                    haskell_log_entries=request_log_entries,
                    haskell_log_dir=haskell_log_dir,
                )
    else:
        if port is None:
            raise ValueError('Missing port with start_server=False')
        with KoreClient('localhost', port, bug_report=bug_report, bug_report_id=id) as client:
            yield CTermSymbolic(
                client,
                definition,
                log_succ_rewrites=log_succ_rewrites,
                log_fail_rewrites=log_fail_rewrites,
                haskell_log_entries=request_log_entries,
                haskell_log_dir=haskell_log_dir,
            )
