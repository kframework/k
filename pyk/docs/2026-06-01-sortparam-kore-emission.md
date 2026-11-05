# Emitting the `#SortParam` sentinel to Kore

## Status

Not implemented.
`_ksort_to_kore` raises a clear error when it encounters the sentinel, rather than producing invalid Kore.
This document describes the full fix so it can be implemented and validated against real Kore output later.

## Background

Some ML-predicate productions have a result sort that cannot be inferred from their arguments.
The canonical example is `#Equals{S1, S2}(S1, S1)`: `S1` is determined by the arguments, but `S2` (the result sort) is context-dependent.
When `KDefinition.add_sort_params` fills in a partially-applied ML-predicate label, it can determine `S1` but not `S2`, so it fills `S2` with the sentinel sort `KSort('#SortParam')` (see `add_sort_params` in `src/pyk/kast/outer.py`).

The Java frontend (`org.kframework.compile.AddSortInjections`) does the same thing, but with two differences that matter for Kore emission:

- It generates a *fresh, uniquely named* sentinel per unresolved position: `#SortParam{Q0}`, `#SortParam{Q1}`, ….
- It collects those `Qn` names during the traversal and declares them as universally-quantified sort variables on the resulting axiom (surfaced in the `sortParams(...)` rule attribute, and as sort parameters on the Kore `axiom{...}`).

## The problem in pyk

`_ksort_to_kore` (in `src/pyk/konvert/_kast_to_kore.py`) is a context-free, term-level converter: it maps every `KSort` to `SortApp('Sort' + name)`.
For the sentinel this yields `SortApp('Sort#SortParam')`, which is doubly wrong:

- `#` is not a legal Kore identifier character, so the `SortApp`/`Id` constructor raises `ValueError: Expected identifier`.
- Even if it were constructible, a bare sort application referencing a sort that exists in no definition is not what the sentinel means — it must be a *bound sort variable*.

`krule_to_kore` builds an axiom by calling `kast_to_kore` several independent times (lhs body, rhs body, each constraint), and sets the axiom's sort variables (`Axiom.vars`) to `()` for ordinary rules or `(SortVar('R'),)` for functional rules.
There is no mechanism to (a) emit the sentinel as a sort variable, (b) give it a unique name, or (c) collect it back up and bind it on the axiom.

## Reachability

In the normal pyk flow this path is rarely hit.
ML predicates constructed through the prelude (`mlEquals`, `mlEqualsTrue`, `bool_to_ml_pred`, …) always pass explicit sort params (e.g. `KLabel('#Equals', arg_sort, sort)`), so they hit the early return in `add_sort_params` and never produce the sentinel.
The sentinel only arises for ML predicates that reach `add_sort_params` with *missing* sort params (e.g. frontend-loaded or hand-constructed terms) and whose result sort cannot be inferred.

## Proposed fix

The goal is to mirror the Java behaviour: each unresolved result sort becomes a uniquely-named, universally-quantified Kore sort variable on the enclosing axiom.

1. **Unique sentinels.**
   Replace the single bare `KSort('#SortParam')` with parametric sentinels `KSort('#SortParam', (KSort('Q0'),))`, `KSort('#SortParam', (KSort('Q1'),))`, ….
   This removes the current "at most one unbound param" restriction (the `NotImplementedError` guard in `add_sort_params`) and lets distinct unresolved positions stay distinct.
   Generating fresh names requires a counter; since `add_sort_params` runs per `kast_to_kore` call, the counter must be threaded from `krule_to_kore` (or `add_sort_params` must accept a starting index and return the names it used) so that names are unique *across* the several `kast_to_kore` calls that make up one axiom.

2. **Emit sentinels as sort variables.**
   Teach `_ksort_to_kore` (or the `_kapply_to_pattern` sort-emission path) to map `#SortParam{Qn}` to `SortVar('Qn')` instead of a `SortApp`.

3. **Bind them on the axiom.**
   `krule_to_kore` collects every `SortVar` emitted from a sentinel across all of its `kast_to_kore` calls and adds them to `Axiom.vars` (alongside `R` for functional rules), and to the `sortParams(...)` attribute, matching the Java output.

## Validation

This change alters Kore axiom output and must be validated end-to-end, not just at the unit level:

- The konvert integration tests (`src/tests/integration/konvert/`), which require the K toolchain.
- The pyk regression suite (`pyk/regression-new/`), comparing emitted Kore against the Java backend for a definition that actually exercises an uninferable ML-predicate result sort.

A minimal repro to build first: a rule (loaded from a compiled definition, not constructed via the prelude) containing an ML predicate whose result sort is not determined by its arguments, asserting the emitted axiom binds a sort variable rather than referencing `Sort#SortParam`.
