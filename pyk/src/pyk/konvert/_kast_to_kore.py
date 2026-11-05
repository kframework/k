from __future__ import annotations

import logging
from functools import reduce
from typing import TYPE_CHECKING

from ..kast import Atts
from ..kast.inner import KApply, KLabel, KRewrite, KSequence, KSort, KToken, KVariable, top_down
from ..kast.manip import bool_to_ml_pred, extract_lhs, extract_rhs, flatten_label, ml_pred_to_bool, var_occurrences
from ..kast.outer import KRule
from ..kast.prelude.bytes import BYTES, pretty_bytes_str
from ..kast.prelude.k import K_ITEM, K, inj
from ..kast.prelude.kbool import BOOL, TRUE, andBool
from ..kast.prelude.ml import mlAnd
from ..kast.prelude.string import STRING, pretty_string
from ..kore.prelude import BOOL as KORE_BOOL
from ..kore.prelude import SORT_K
from ..kore.prelude import TRUE as KORE_TRUE
from ..kore.syntax import (
    DV,
    And,
    App,
    Axiom,
    Equals,
    EVar,
    Implies,
    Import,
    In,
    MLPattern,
    MLQuant,
    Module,
    Rewrites,
    SortApp,
    SortVar,
    String,
    Top,
)
from ._utils import munge

if TYPE_CHECKING:
    from typing import Final

    from ..kast import KInner
    from ..kast.att import AttEntry
    from ..kast.outer import KDefinition, KFlatModule, KImport
    from ..kore.syntax import Pattern, Sentence, Sort

_LOGGER: Final = logging.getLogger(__name__)


ML_CONN_LABELS: Final = {
    '#Top': r'\top',
    '#Bottom': r'\bottom',
    '#Not': r'\not',
    '#And': r'\and',
    '#Or': r'\or',
    '#Implies': r'\implies',
    '#Iff': r'\iff',
}

ML_QUANT_LABELS: Final = {
    '#Exists': r'\exists',
    '#Forall': r'\forall',
}

ML_PRED_LABELS: Final = {
    '#Ceil': r'\ceil',
    '#Floor': r'\floor',
    '#Equals': r'\equals',
    '#In': r'\in',
}

ML_PATTERN_LABELS: Final = dict(
    **ML_CONN_LABELS,
    **ML_QUANT_LABELS,
    **ML_PRED_LABELS,
)


def kast_to_kore(definition: KDefinition, kast: KInner, sort: KSort | None = None) -> Pattern:
    sort = sort or K
    kast = definition.add_ksequence_under_k_productions(kast)
    kast = definition.sort_vars(kast, sort)
    kast = definition.add_cell_map_items(kast)
    kast = definition.add_sort_params(kast)
    kast = _replace_ksequence_by_kapply(definition, kast)
    kast = _add_sort_injections(definition, kast, sort)
    kore = _kast_to_kore(kast)
    return kore


def _replace_ksequence_by_kapply(definition: KDefinition, term: KInner) -> KInner:
    dotk = KApply('dotk')
    kseq = KLabel('kseq')
    append = KLabel('append')

    def kapply(x: KInner, y: KInner) -> KApply:
        return append(x, y) if definition.sort_strict(x) == K else kseq(x, y)

    def ksequence_to_kapply(term: KInner) -> KInner:
        if not isinstance(term, KSequence):
            return term

        items = term.items

        if not items:
            return dotk

        unit: KInner
        args: tuple[KInner, ...]

        last = items[-1]
        if definition.sort_strict(last) == K:
            unit = last
            args = items[:-1]
        else:
            unit = dotk
            args = items

        return reduce(lambda x, y: kapply(y, x), reversed(args), unit)

    return top_down(ksequence_to_kapply, term)


def _add_sort_injections(definition: KDefinition, term: KInner, sort: KSort) -> KInner:
    """Add sort injections to a KAST term bottom-up.

    Maintains its own stack for an iterative implementation. Each stack frame consists of:
    - `term`: the current term
    - `sort`: the sort the current term must be injected to
    - `argument_terms`: direct subterms of the current term
    - `argument_sorts`: the sorts the respective direct subterms must be injected to
    - `done_terms`: results for direct subterms
    """
    stack: list = [term, sort, _argument_terms(definition, term), _argument_sorts(definition, term), []]
    while True:
        done_terms = stack[-1]
        argument_sorts = stack[-2]
        argument_terms = stack[-3]
        sort = stack[-4]
        term = stack[-5]

        idx = len(done_terms) - len(argument_terms)
        if not idx:
            stack.pop()
            stack.pop()
            stack.pop()
            stack.pop()
            stack.pop()
            term = _let_arguments(term, done_terms)
            term = _inject(definition, term, sort)
            if not stack:
                return term
            stack[-1].append(term)
        else:
            term = argument_terms[idx]
            stack.append(term)
            stack.append(argument_sorts[idx])
            stack.append(_argument_terms(definition, term))
            stack.append(_argument_sorts(definition, term))
            stack.append([])


def _argument_terms(definition: KDefinition, term: KInner) -> tuple[KInner, ...]:
    match term:
        case KApply(KLabel('#Exists' | '#Forall')):  # Special case: ML quantifiers
            _, term = term.args
            return (term,)
        case _:
            return term.terms


def _argument_sorts(definition: KDefinition, term: KInner) -> tuple[KSort, ...]:
    match term:
        case KToken() | KVariable():
            return ()
        case KSequence(items):
            return len(items) * (K_ITEM,)
        case KApply(KLabel(name)):
            match name:
                case 'kseq':
                    return (K_ITEM, K)
                case 'dotk':
                    return ()
                case 'append':
                    return (K, K)
                case '#Forall' | '#Exists':
                    _, argument_sorts = definition.resolve_sorts(term.label)
                    _, argument_sort = argument_sorts
                    return (argument_sort,)
                case _:
                    _, argument_sorts = definition.resolve_sorts(term.label)
                    return argument_sorts
        case _:
            raise ValueError(f'Unsupported term: {term}')


def _let_arguments(term: KInner, args: list[KInner]) -> KInner:
    match term:
        case KApply(KLabel('#Exists' | '#Forall')):  # Special case: ML quantifiers
            args = [term.args[0]] + args
            return term.let_terms(args)
        case _:
            return term.let_terms(args)


def _inject(definition: KDefinition, term: KInner, sort: KSort) -> KInner:
    actual_sort: KSort
    match term:
        case KApply(KLabel('kseq' | 'dotk' | 'append')):  # Special case: pseudo-labels
            actual_sort = K
        case _:
            actual_sort = definition.sort_strict(term)

    if actual_sort == sort:
        return term

    if actual_sort in definition.subsorts(sort):
        return inj(from_sort=actual_sort, to_sort=sort, term=term)

    raise ValueError(f'Sort {actual_sort.name} is not a subsort of {sort.name}: {term}')


# 'krule' should have sorts on variables
def krule_to_kore(definition: KDefinition, krule: KRule) -> Axiom:
    krule_body = krule.body
    krule_lhs_config = extract_lhs(krule_body)
    krule_rhs_config = extract_rhs(krule_body)

    is_functional = isinstance(krule_lhs_config, KApply) and krule_lhs_config.label.name in definition.function_labels

    top_level_k_sort = KSort('GeneratedTopCell') if not is_functional else definition.sort_strict(krule_lhs_config)
    top_level_kore_sort = _ksort_to_kore(top_level_k_sort)

    # Do sort inference on the entire rule at once
    kast_lhs = mlAnd(
        [krule_lhs_config]
        + [
            bool_to_ml_pred(constraint, sort=top_level_k_sort)
            for constraint in flatten_label('_andBool_', krule.requires)
            if not constraint == TRUE
        ],
        sort=top_level_k_sort,
    )
    kast_rhs = mlAnd(
        [krule_rhs_config]
        + [
            bool_to_ml_pred(constraint, sort=top_level_k_sort)
            for constraint in flatten_label('_andBool_', krule.ensures)
            if not constraint == TRUE
        ],
        sort=top_level_k_sort,
    )
    kast_rule_sorted = definition.sort_vars(KRewrite(kast_lhs, kast_rhs))

    kast_lhs_body, *kast_lhs_constraints = flatten_label('#And', extract_lhs(kast_rule_sorted))
    kast_rhs_body, *kast_rhs_constraints = flatten_label('#And', extract_rhs(kast_rule_sorted))
    kore_lhs_body = kast_to_kore(definition, kast_lhs_body, sort=top_level_k_sort)
    kore_rhs_body = kast_to_kore(definition, kast_rhs_body, sort=top_level_k_sort)

    axiom_vars: tuple[SortVar, ...] = ()
    kore_axiom: Pattern
    if not is_functional:
        kore_lhs_constraints = [
            kast_to_kore(definition, kast_lhs_constraint, sort=top_level_k_sort)
            for kast_lhs_constraint in kast_lhs_constraints
        ]
        kore_rhs_constraints = [
            kast_to_kore(definition, kast_rhs_constraint, sort=top_level_k_sort)
            for kast_rhs_constraint in kast_rhs_constraints
        ]
        kore_lhs_constraint: Pattern = Top(top_level_kore_sort)
        if len(kore_lhs_constraints) == 1:
            kore_lhs_constraint = kore_lhs_constraints[0]
        elif len(kore_lhs_constraints) > 1:
            kore_lhs_constraint = And(top_level_kore_sort, kore_lhs_constraints)
        kore_lhs = And(top_level_kore_sort, [kore_lhs_body, kore_lhs_constraint])
        kore_rhs = (
            kore_rhs_body
            if not kore_rhs_constraints
            else And(top_level_kore_sort, [kore_rhs_body] + kore_rhs_constraints)
        )
        kore_axiom = Rewrites(sort=top_level_kore_sort, left=kore_lhs, right=kore_rhs)
    elif Atts.SIMPLIFICATION in krule.att:
        # Canonical shape of a simplification equation
        # \implies(
        #   requires,
        #   \equals(
        #     lhs,
        #     \and(rhs, ensures)
        # )
        axiom_sort = SortVar('R')
        axiom_vars = (axiom_sort,)
        kast_lhs_constraints_bool = [
            ml_pred_to_bool(kast_lhs_constraint) for kast_lhs_constraint in kast_lhs_constraints
        ]
        kore_antecedent = Equals(
            KORE_BOOL, axiom_sort, kast_to_kore(definition, andBool(kast_lhs_constraints_bool), sort=BOOL), KORE_TRUE
        )
        kore_ensures: Pattern = Top(top_level_kore_sort)
        if kast_rhs_constraints:
            kast_rhs_constraints_bool = [
                ml_pred_to_bool(kast_rhs_constraint) for kast_rhs_constraint in kast_rhs_constraints
            ]
            kore_ensures = Equals(
                KORE_BOOL,
                top_level_kore_sort,
                kast_to_kore(definition, andBool(kast_rhs_constraints_bool), sort=BOOL),
                KORE_TRUE,
            )
        kore_consequent = Equals(
            top_level_kore_sort, axiom_sort, kore_lhs_body, And(top_level_kore_sort, [kore_rhs_body, kore_ensures])
        )
        kore_axiom = Implies(axiom_sort, kore_antecedent, kore_consequent)
    else:  # i.e., is_functional and not a simplification
        # canonical shape of a function equation (not simplification!)
        # \implies(
        #   \and(requires, argument_predicates),
        #   \equals(lhs_with_args_replaced, \and(rhs, ensures))
        # )
        # arg.predicates are \and chains of \in(VAR, ARG) ending in \top
        # the actual arg.s are replaced by VAR_1..n in the LHS's function application
        # requires and ensures are \\top if empty or \and-ed \equals(.., \dv("true"))
        axiom_sort = SortVar('R')
        axiom_vars = (axiom_sort,)
        kast_lhs_constraints_bool = [
            ml_pred_to_bool(kast_lhs_constraint) for kast_lhs_constraint in kast_lhs_constraints
        ]
        assert isinstance(kast_lhs_body, KApply)
        kore_requires_antecedent: Pattern = Top(top_level_kore_sort)
        if kast_lhs_constraints_bool is not None:
            kore_requires_antecedent = Equals(
                KORE_BOOL,
                axiom_sort,
                kast_to_kore(definition, andBool(kast_lhs_constraints_bool), sort=BOOL),
                KORE_TRUE,
            )
        # make argument predicates
        if not kast_lhs_body.args:
            kore_fct_antecedent: Pattern = kore_requires_antecedent
        else:
            kore_arg_predicates, new_kore_app = _mangle_app(definition, top_level_kore_sort, kast_lhs_body)
            kore_fct_antecedent = And(
                axiom_sort,
                (
                    kore_requires_antecedent,
                    kore_arg_predicates,
                ),
            )
            kore_lhs_body = new_kore_app

        kore_ensures = Top(top_level_kore_sort)
        if kast_rhs_constraints:
            kast_rhs_constraints_bool = [
                ml_pred_to_bool(kast_rhs_constraint) for kast_rhs_constraint in kast_rhs_constraints
            ]
            kore_ensures = Equals(
                KORE_BOOL,
                top_level_kore_sort,
                kast_to_kore(definition, andBool(kast_rhs_constraints_bool), sort=BOOL),
                KORE_TRUE,
            )
        kore_consequent = Equals(
            top_level_kore_sort, axiom_sort, kore_lhs_body, And(top_level_kore_sort, [kore_rhs_body, kore_ensures])
        )
        kore_axiom = Implies(axiom_sort, kore_fct_antecedent, kore_consequent)

    # Make adjustments to Rule attributes
    att = krule.att.discard([Atts.PRODUCTION, Atts.UNIQUE_ID, Atts.SOURCE, Atts.LOCATION])
    if Atts.PRIORITY not in att:
        if Atts.OWISE in att:
            att = att.update([Atts.PRIORITY(200)])
            att = att.discard([Atts.OWISE])
        elif Atts.SIMPLIFICATION not in att:
            att = att.update([Atts.PRIORITY(50)])

    attrs = [
        _krule_att_to_kore(att_entry, var_occurrences(kast_rule_sorted))
        for att_entry in sorted(att.entries(), key=(lambda a: a.key.name))
    ]

    return Axiom(vars=axiom_vars, pattern=kore_axiom, attrs=attrs)


def _mangle_app(definition: KDefinition, sort: Sort, app: KApply) -> tuple[Pattern, Pattern]:

    ksorts = _argument_sorts(definition, app)
    assert len(ksorts) == len(app.args)
    var_names = [f'F-ARG-{i}' for i in range(1, 42)]  # arbitrary limit
    assert len(ksorts) <= len(var_names)  # fail if too many arguments

    preds = [
        In(
            _ksort_to_kore(ksort),
            sort,
            EVar(name, _ksort_to_kore(ksort)),
            kast_to_kore(definition, arg, ksort),
        )
        for (arg, ksort, name) in zip(app.args, ksorts, var_names, strict=False)
    ]

    new_app = kast_to_kore(
        definition,
        KApply(
            app.label,
            [KVariable(name, sort) for (sort, name) in zip(ksorts, var_names, strict=False)],
        ),
    )

    return (And(sort, preds), new_app)


def kflatmodule_to_kore(definition: KDefinition, kflatmodule: KFlatModule) -> Module:
    kore_axioms: list[Sentence] = []
    for sent in kflatmodule.sentences:
        if type(sent) is not KRule:
            raise ValueError(f'Cannot convert sentence to Kore: {sent}')
        kore_axioms.append(krule_to_kore(definition, sent))
    imports: list[Sentence] = [_kimport_to_kore(kimport) for kimport in kflatmodule.imports]
    return Module(name=kflatmodule.name, sentences=(imports + kore_axioms))


def _krule_att_to_kore(att_entry: AttEntry, kast_rule_vars: dict[str, list[KVariable]]) -> App:
    match att_entry.key:
        case Atts.LABEL | Atts.PRIORITY | Atts.SIMPLIFICATION:
            return App(symbol=att_entry.key.name, sorts=(), args=(String(str(att_entry.value)),))
        case Atts.SYMBOLIC | Atts.CONCRETE:
            if not att_entry.value:
                return App(symbol=att_entry.key.name, sorts=(), args=())
            kore_vars = []
            for var_name in att_entry.value.split(','):
                if var_name not in kast_rule_vars:
                    raise ValueError(f'Variable in {att_entry.key} not present in rule: {var_name}')
                kore_vars.append(_kvariable_to_kore(kast_rule_vars[var_name][0]))
            return App(symbol=att_entry.key.name, sorts=(), args=tuple(kore_vars))
        case Atts.SMTLEMMA:
            return App(symbol=att_entry.key.name, sorts=(), args=())
        case _:
            raise ValueError(f'Do not know how to convert AttEntry to Kore: {att_entry}')


def _kimport_to_kore(kimport: KImport) -> Import:
    return Import(module_name=kimport.name, attrs=())


def _ksort_to_kore(ksort: KSort) -> SortApp:
    return SortApp('Sort' + ksort.name)


def _kast_to_kore(term: KInner) -> Pattern:
    stack: list = [term, []]
    while True:
        patterns = stack[-1]
        term = stack[-2]
        idx = len(patterns) - len(term.terms)
        if not idx:
            stack.pop()
            stack.pop()
            pattern = _kinner_to_kore(term, patterns)
            if not stack:
                return pattern
            stack[-1].append(pattern)
        else:
            stack.append(term.terms[idx])
            stack.append([])


def _kinner_to_kore(kinner: KInner, patterns: list[Pattern]) -> Pattern:
    match kinner:
        case KToken():
            assert not patterns
            return _ktoken_to_kore(kinner)
        case KVariable():
            assert not patterns
            return _kvariable_to_kore(kinner)
        case KApply():
            return _kapply_to_kore(kinner, patterns)
        case _:
            raise ValueError(f'Unsupported KInner: {kinner}')


def _ktoken_to_kore(ktoken: KToken) -> DV:
    value: String
    if ktoken.sort == STRING:
        value = String(pretty_string(ktoken))
    elif ktoken.sort == BYTES:
        value = String(pretty_bytes_str(ktoken))
    else:
        value = String(ktoken.token)

    sort = _ksort_to_kore(ktoken.sort)

    return DV(sort, value)


def _kvariable_to_kore(kvar: KVariable) -> EVar:
    sort: Sort
    if kvar.sort:
        sort = _ksort_to_kore(kvar.sort)
    else:
        sort = SORT_K
    return EVar('Var' + munge(kvar.name), sort)


def _kapply_to_kore(kapply: KApply, patterns: list[Pattern]) -> Pattern:
    if kapply.label.name in ML_QUANT_LABELS:
        return _kapply_to_ml_quant(kapply, patterns)

    return _kapply_to_pattern(kapply, patterns)


def _kapply_to_ml_quant(kapply: KApply, patterns: list[Pattern]) -> MLQuant:
    label = kapply.label
    symbol = ML_QUANT_LABELS[label.name]
    _, ksort = label.params
    sort = _ksort_to_kore(ksort)
    return MLQuant.of(symbol, (sort,), patterns)


def _kapply_to_pattern(kapply: KApply, patterns: list[Pattern]) -> Pattern:
    label = kapply.label
    symbol = _label_to_kore(label.name)
    sorts = tuple(_ksort_to_kore(ksort) for ksort in label.params)

    if label.name in ML_PATTERN_LABELS:
        return MLPattern.of(symbol, sorts, patterns)

    return App(symbol, sorts, patterns)


def _label_to_kore(label: str) -> str:
    if label in ['inj', 'kseq', 'dotk', 'append']:  # pseudo-labels introduced during KAST-to-KORE tranformation
        return label

    if label in ML_PATTERN_LABELS:
        return ML_PATTERN_LABELS[label]

    return 'Lbl' + munge(label)
