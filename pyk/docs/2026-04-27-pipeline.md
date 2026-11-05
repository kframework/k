# K Compilation Pipeline — Developer Reference

This document describes the K compilation pipeline, where pyk already participates, and the integration points for moving more of the pipeline from Java to Python.

## Overview

The pipeline has five logical stages:

```
Outer parsing → Inner parsing → 32 compilation passes → Kore emission → Backend compilation
```

The first four stages produce `definition.kore`.
The fifth stage (LLVM/Haskell backend compilation) consumes `definition.kore` and is inherently backend-specific.

## Stage 1: Outer Parsing

**What it does**: Reads `.k` and `.md` files, resolves `require` statements, and produces a `KDefinition` (a set of `KFlatModule`s with import edges but with rule bodies still as unparsed "bubbles").

**Java implementation**: JavaCC grammar at `k-frontend/src/main/javacc/Outer.jj`; entry point `DefinitionParsing.parseDefinition()`.

**Python implementation**: `pyk/src/pyk/kast/outer_parser.py` + `outer_lexer.py`; entry point `pyk.kast.utils.parse_outer()`.

**Pipeline seam**: Java `kompile` accepts `--outer-parsed-json`, which reads a pre-parsed `KDefinition` JSON from a file and skips the Java outer parsing stage entirely.
The JSON format is `{"format": "KAST", "version": 3, "term": <KDefinition.to_dict()>}`.

**`kompilex` command** (`pyk/src/pyk/__main__.py:exec_kompilex`):
1. Calls `parse_outer()` (Python outer parser)
2. Merges any `--pre-parsed-prelude` modules
3. Serialises the result to a temp JSON file
4. Calls Java `kompile --outer-parsed-json <tempfile>` for the remaining stages

## Stage 2: Inner Parsing (Bubble Resolution)

**What it does**: Parses the rule bodies ("bubbles") using the grammar generated from the user's syntax declarations.
Each bubble is a rule LHS/RHS/requires/ensures that was left as a raw token stream by the outer parser.

**Java implementation**: `k-frontend/src/main/java/org/kframework/parser/inner/` + `RuleGrammarGenerator`.
This stage runs after `--outer-parsed-json` injection, so there is currently no way to skip it from Python.

**Python implementation**: `pyk/src/pyk/kast/parser.py` + `lexer.py`.
The Python inner parser exists but is not yet wired into the pipeline as a bypass.

## Stage 3: Compilation Passes (Java)

32 ordered passes, each a pure `Definition → Definition` transformation.
They are named and can be selected individually via `--kore-backend-steps` in `KoreBackend.java`.

The full ordered list (from `KoreBackend.steps()`, lines 274–306):

| # | Pass name | What it does | External I/O? |
|---|-----------|--------------|---------------|
| 1 | `resolveComm` | Resolve commutative simplification rules | None |
| 2 | `resolveIO` | Resolve I/O stream configuration cells | None |
| 3 | `resolveFun` | Resolve `#fun` applications | None |
| 4 | `resolveFunctionWithConfig` | Resolve function calls that reference the configuration | None |
| 5 | `resolveStrict` | Expand `strict`/`seqstrict` attributes into heating/cooling rules | None |
| 6 | `resolveAnonVars` | Replace `_` anonymous variables with fresh names | None |
| 7 | `resolveContexts` | Resolve context holes and rewrites | None |
| 8 | `numberSentences1` | Assign unique integer IDs to all sentences | None |
| 9 | `resolveHeatCoolAttribute` | Expand `heat`/`cool` attributes into rules | None |
| 10 | `resolveSemanticCasts` | Resolve `#` cast operations | None |
| 11 | `subsortKItem1` | Add subsort productions: every sort is a subsort of `KItem` | None |
| 12 | `constantFolding` | Fold constant expressions (via Java-reflection-based built-in hooks) | None |
| 13 | `propagateMacroToRules` | Propagate `macro` label from production to its rules | None |
| 14 | `guardOrs` | Transform or-patterns into guarded alternatives | None |
| 15 | `resolveFreshConfigConstants` | Resolve `!Var` fresh constants in the configuration | None |
| 16 | `generateSortPredicateSyntax1` | Generate `isSort(...)` predicate productions (pass 1) | None |
| 17 | `generateSortProjections1` | Generate sort projection functions (pass 1) | None |
| 18 | `expandMacros` | Expand macro rules | Optional coverage file write |
| 19 | `addImplicitComputationCell` | Add implicit `<k>` computation cell to rules that lack it | None |
| 20 | `resolveFreshConstants` | Resolve `!Var` fresh constants in rules | None |
| 21 | `generateSortPredicateSyntax2` | Generate sort predicate productions (pass 2) | None |
| 22 | `generateSortProjections2` | Generate sort projections (pass 2) | None |
| 23 | `checkSimplificationRules` | Validate that simplification rule LHS has a function symbol | Error output |
| 24 | `subsortKItem2` | Subsort to `KItem` (pass 2) | None |
| 25 | `concretizeCells` | Concretize cell structure: `AddTopCellToRules` → `AddParentCells` → `CloseCells` → `SortCells` | None |
| 26 | `genCoverage` | Write coverage instrumentation data | Optional file write |
| 27 | `addSemanticsModule` | Add synthetic `LANGUAGE-PARSING` module | None |
| 28 | `resolveConfigVar` | Add configuration variables to rule LHS | None |
| 29 | `addCoolLikeAtt` | Add `cool-like` attribute to rules | None |
| 30 | `removeAnywhereRules` | Filter `anywhere` rules (Haskell backend only) | Warning log |
| 31 | `generateSortPredicateRules` | Generate rules implementing sort predicates | None |
| 32 | `numberSentences2` | Re-number sentences (pass 2) | None |

26 of 32 passes are completely pure (no I/O).
The remaining 6 have conditional or minor I/O that can be trivially gated.

**Output**: Java writes the post-pipeline KAST to `<kompiled-dir>/compiled.json` (and `compiled.txt`).
This is the **second pipeline seam**: Python can read `compiled.json` and take over from here.

## Stage 4: Kore Emission

**What it does**: Converts the compiled KAST (`compiled.json`) into Kore syntax and writes `definition.kore` and `syntaxDefinition.kore`.

**Java implementation**: `k-frontend/src/main/java/org/kframework/backend/kore/ModuleToKORE.java`.
Uses `StringBuilder` string concatenation throughout; no intermediate structured Kore AST.

**Python implementation** (partially complete):

- `pyk/src/pyk/konvert/_module_to_kore.py` — `module_to_kore(definition)` generates:
  - Sort declarations
  - Symbol declarations
  - Structural axioms: subsort, assoc, idem, unit, functional, no-confusion, no-junk, overload
  - **Not yet**: rule axioms, macro rule separation, `Definition` wrapper, prelude imports, top-cell initializer

- `pyk/src/pyk/konvert/_kast_to_kore.py` — `krule_to_kore(definition, krule)` converts a single K rule to a Kore `Axiom`.
  This exists but is not yet called from `module_to_kore()`.

**Gaps to close for full Python Kore emission**:
1. Call `krule_to_kore()` inside `module_to_kore()` to emit rule axioms
2. Separate macro rules into their own section (matching Java's output structure)
3. Add a `kdef_to_kore(definition)` wrapper that produces a `Definition` with prelude modules (BASIC-K, KSEQ, INJ, K) and the top-cell initializer attribute
4. Write the result to `definition.kore` and `syntaxDefinition.kore`

## Stage 5: Backend Compilation

LLVM or Haskell compilation of `definition.kore` into a binary or compiled artifact.
This is inherently backend-specific and will remain in the respective backend tools.

## What pyk Currently Wires Together

| Mechanism | What it does |
|-----------|-------------|
| `pyk kompile` | Thin wrapper — delegates entirely to Java `kompile` |
| `pyk kompilex` | Python outer parse → JSON → Java `kompile --outer-parsed-json` |
| `pyk/regression-new/include/ktest.mak` | Uses `pyk kompile` (not yet `kompilex`) |

## Planned Integration Points

1. **Outer parsing**: switch `pyk/regression-new/include/ktest.mak` from `pyk kompile` to `pyk kompilex` so all regression tests exercise Python outer parsing.

2. **Kore emission**: extend `_module_to_kore.py` with rule emission, add `kdef_to_kore()` wrapper, add a validation tool (`pyk emit-kore`) that reads `compiled.json` and diffs against `definition.kore`, then wire into `kompilex`.

3. **Compilation passes**: once outer parsing and Kore emission are in Python, individual passes can be ported one at a time, replacing Java sub-steps without changing the overall pipeline interface.

## Key Files

| Path | Role |
|------|------|
| `k-frontend/src/main/javacc/Outer.jj` | Java outer parser grammar |
| `k-frontend/src/main/java/org/kframework/kompile/KompileOptions.java` | `--outer-parsed-json` flag |
| `k-frontend/src/main/java/org/kframework/kompile/DefinitionParsing.java:305` | Outer parsing bypass entry point |
| `k-frontend/src/main/java/org/kframework/backend/kore/KoreBackend.java:122` | `steps()` — ordered pass list |
| `k-frontend/src/main/java/org/kframework/backend/kore/ModuleToKORE.java` | Java Kore emission |
| `pyk/src/pyk/kast/outer_parser.py` | Python outer parser |
| `pyk/src/pyk/kast/utils.py` | `parse_outer()` — outer parse entry point |
| `pyk/src/pyk/__main__.py:exec_kompilex` | `kompilex` pipeline driver |
| `pyk/src/pyk/ktool/kompile.py` | `kompile()` — Java subprocess wrapper |
| `pyk/src/pyk/konvert/_module_to_kore.py` | `module_to_kore()` — partial Kore emission |
| `pyk/src/pyk/konvert/_kast_to_kore.py` | `krule_to_kore()` — rule → Kore axiom |
| `pyk/src/pyk/kore/syntax.py` | Kore AST types |
| `pyk/regression-new/include/ktest.mak` | Regression test kompile invocation |
| `pyk/regression-new/skipped` | 113 currently skipped tests |
