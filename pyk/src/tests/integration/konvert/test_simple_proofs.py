from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pyk.kast import Atts
from pyk.kast.inner import KApply, KLabel, KRewrite, KSequence, KSort, KToken, KVariable
from pyk.kast.outer import KRule
from pyk.kast.prelude.bytes import bytesToken
from pyk.kast.prelude.kbool import BOOL, TRUE
from pyk.kast.prelude.kint import INT, intToken
from pyk.kast.prelude.ml import mlBottom, mlImplies, mlTop
from pyk.kast.prelude.string import STRING, stringToken
from pyk.konvert import kast_to_kore, kore_to_kast, krule_to_kore
from pyk.kore.parser import KoreParser
from pyk.testing import KPrintTest
from pyk.utils import single

from ..utils import K_FILES, TEST_DATA_DIR

if TYPE_CHECKING:
    from typing import Final

    from pyk.kast import KInner
    from pyk.kast.outer import KDefinition
    from pyk.ktool.kprint import KPrint


BIDIRECTIONAL_TEST_DATA: Final = (
    (
        'domain-value-int',
        INT,
        r'\dv{SortInt{}}("3")',
        intToken(3),
    ),
    (
        'domain-value-string',
        STRING,
        r'\dv{SortString{}}("foobar\n")',
        stringToken('foobar\n'),
    ),
    (
        'domain-value-bytes',
        KSort('Bytes'),
        r'\dv{SortBytes{}}("\x00<`\xf5")',
        bytesToken(b'\x00\x3c\x60\xf5'),
    ),
    (
        'domain-value-other',
        KSort('Foo'),
        r'\dv{SortFoo{}}("hello\\n")',
        KToken('hello\\n', 'Foo'),
    ),
    (
        'ml-top',
        KSort('GeneratedTopCell'),
        r'\top{SortGeneratedTopCell{}}()',
        mlTop(),
    ),
    (
        'ml-bottom',
        KSort('GeneratedTopCell'),
        r'\bottom{SortGeneratedTopCell{}}()',
        mlBottom(),
    ),
    (
        'ml-implies',
        KSort('GeneratedTopCell'),
        r"""
        \implies{SortGeneratedTopCell{}}(
            VarX : SortGeneratedTopCell{},
            VarY : SortGeneratedTopCell{}
        )
        """,
        mlImplies(
            KVariable('X', sort=KSort('GeneratedTopCell')),
            KVariable('Y', sort=KSort('GeneratedTopCell')),
            sort=KSort('GeneratedTopCell'),
        ),
    ),
    (
        'variable-with-sort',
        INT,
        'VarX : SortInt{}',
        KVariable('X', sort=INT),
    ),
    (
        'variable-with-super-sort',
        KSort('Bar'),
        'inj{SortBaz{}, SortBar{}}(VarX : SortBaz{})',
        KVariable('X', sort=KSort('Baz')),
    ),
    (
        'variable-with-underscore',
        INT,
        "VarX'Unds'Y : SortInt{}",
        KVariable('X_Y', sort=INT),
    ),
    (
        'issue:k/2762',
        KSort('Bool'),
        r'Lblpred1{}(\dv{SortInt{}}("3"))',
        KApply('pred1', [intToken(3)]),
    ),
    (
        'cells-conversion',
        KSort('KCell'),
        "Lbl'-LT-'k'-GT-'{}(dotk{}())",
        KApply('<k>', [KSequence()]),
    ),
    (
        'constrained-term',
        KSort('KCell'),
        r"""
        \and{SortKCell{}}(
            Lbl'-LT-'k'-GT-'{}(dotk{}()),
            VarX : SortKCell{}
        )
        """,
        KApply(
            KLabel('#And', params=[KSort('KCell')]),
            [KApply('<k>', [KSequence()]), KVariable('X', sort=KSort('KCell'))],
        ),
    ),
    (
        'ml-equals',
        KSort('GeneratedTopCell'),
        r"""
        \equals{SortBool{}, SortGeneratedTopCell{}}(
            VarX : SortBool{},
            \dv{SortBool{}}("true")
        )
        """,
        KApply(
            KLabel('#Equals', [KSort('Bool'), KSort('GeneratedTopCell')]),
            [KVariable('X', sort=KSort('Bool')), TRUE],
        ),
    ),
    (
        'ml-ceil',
        KSort('GeneratedTopCell'),
        r'\ceil{SortBool{}, SortGeneratedTopCell{}}(VarX : SortBool{})',
        KApply(
            KLabel('#Ceil', [KSort('Bool'), KSort('GeneratedTopCell')]),
            [KVariable('X', sort=KSort('Bool'))],
        ),
    ),
    (
        'ml-exists',
        KSort('Bool'),
        r'\exists{SortBool{}}(VarX : SortBool{}, VarX : SortBool{})',
        KApply(
            KLabel('#Exists', [KSort('Bool'), KSort('Bool')]),
            [
                KVariable('X', sort=KSort('Bool')),
                KVariable('X', sort=KSort('Bool')),
            ],
        ),
    ),
    (
        'ml-not',
        KSort('Bool'),
        r'\not{SortBool{}}(VarX : SortBool{})',
        KApply(
            KLabel('#Not', [KSort('Bool')]),
            [KVariable('X', sort=KSort('Bool'))],
        ),
    ),
    (
        'simple-injection',
        KSort('Foo'),
        'Lblfoo{}(inj{SortBaz{}, SortBar{}}(Lblbaz{}()))',
        KApply('foo', [KApply('baz')]),
    ),
    (
        'cells-conversion',
        KSort('KItem'),
        "inj{SortKCell{}, SortKItem{}}(Lbl'-LT-'k'-GT-'{}(dotk{}()))",
        KApply('<k>', [KSequence()]),
    ),
    (
        'munging-problem',
        KSort('Baz'),
        r"Lblfoo-bar'Unds'SIMPLE-PROOFS'Unds'Baz{}()",
        KApply('foo-bar_SIMPLE-PROOFS_Baz', []),
    ),
    (
        'kseq-empty',
        KSort('K'),
        'dotk{}()',
        KSequence([]),
    ),
    (
        'kseq-singleton',
        KSort('K'),
        "kseq{}(inj{SortBaz{}, SortKItem{}}(Lblfoo-bar'Unds'SIMPLE-PROOFS'Unds'Baz{}()), dotk{}())",
        KSequence([KApply('foo-bar_SIMPLE-PROOFS_Baz')]),
    ),
    (
        'kseq-two-element',
        KSort('K'),
        """
        kseq{}(
            Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(),
            kseq{}(
                inj{SortBaz{}, SortKItem{}}(Lblfoo-bar'Unds'SIMPLE-PROOFS'Unds'Baz{}()),
                dotk{}()
            )
        )
        """,
        KSequence([KApply('foo_SIMPLE-PROOFS_KItem'), KApply('foo-bar_SIMPLE-PROOFS_Baz')]),
    ),
    (
        'kseq-with-k-head',
        KSort('K'),
        r'append{}(VarX : SortK{}, kseq{}(inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("1")), dotk{}()))',
        KSequence(KVariable('X', 'K'), intToken(1)),
    ),
    (
        'kseq-with-k-middle',
        KSort('K'),
        r"""
        kseq{}(
            inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("1")),
            append{}(
                VarX : SortK{},
                kseq{}(
                    inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("2")),
                    dotk{}()
                )
            )
        )
        """,
        KSequence(intToken(1), KVariable('X', 'K'), intToken(2)),
    ),
    (
        'kseq-with-multiple-ks',
        KSort('K'),
        r"""
        kseq{}(
            inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("1")),
            append{}(
                VarX1 : SortK{},
                append{}(
                    VarX2 : SortK{},
                    append{}(
                        VarX3 : SortK{},
                        kseq{}(
                            inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("2")),
                            VarX4 : SortK{}
                        )
                    )
                )
            )
        )
        """,
        KSequence(
            intToken(1),
            KVariable('X1', 'K'),
            KVariable('X2', 'K'),
            KVariable('X3', 'K'),
            intToken(2),
            KVariable('X4', 'K'),
        ),
    ),
    (
        'if-then-else',
        KSort('K'),
        r'Lblite{SortK{}}(VarC : SortBool{}, VarB1 : SortK{}, VarB2 : SortK {})',
        KApply(
            KLabel('ite', [KSort('K')]),
            [
                KVariable('C', sort=KSort('Bool')),
                KVariable('B1', sort=KSort('K')),
                KVariable('B2', sort=KSort('K')),
            ],
        ),
    ),
)

KAST_TO_KORE_TEST_DATA: Final = BIDIRECTIONAL_TEST_DATA + (
    (
        'kitem-function-k-arg',
        KSort('Bool'),
        """
        Lbl'UndsEqlsEqls'K'Unds'{}(
          VarX:SortK{},
          VarY:SortK{},
        )
        """,
        KApply('_==K_', [KVariable('X', 'K'), KVariable('Y', 'K')]),
    ),
    (
        'kitem-function-k-arg-2',
        KSort('Bool'),
        """
        Lbl'UndsEqlsEqls'K'Unds'{}(
          VarX:SortK{},
          VarY:SortK{},
        )
        """,
        KApply('_==K_', [KVariable('X'), KVariable('Y')]),
    ),
    (
        'kitem-function',
        KSort('Foo'),
        """
        Lblabcd{}(kseq{}(
            VarX:SortKItem{},
            dotk{}()
        ))
        """,
        KApply('abcd', [KVariable('X', 'KItem')]),
    ),
    (
        'equals-k-encoding',
        KSort('KItem'),
        """
        inj{SortBool{}, SortKItem{}}(
        Lbl'UndsEqlsEqls'K'Unds'{}(
          kseq{}(
            inj{SortInt{}, SortKItem{}}(VarX:SortInt{}),
            dotk{}()
          ),
          kseq{}(
            inj{SortInt{}, SortKItem{}}(\\dv{SortInt{}}("0")),
            dotk{}()
          )
        ))
        """,
        KApply('_==K_', [KVariable('X', 'Int'), KToken('0', 'Int')]),
    ),
    (
        'ksequence-under-kequal-not-reapplied',
        KSort('KItem'),
        """
        inj{SortBool{}, SortKItem{}}(
        Lbl'UndsEqlsEqls'K'Unds'{}(
          kseq{}(
            inj{SortInt{}, SortKItem{}}(VarX:SortInt{}),
            dotk{}()
          ),
          kseq{}(
            inj{SortInt{}, SortKItem{}}(\\dv{SortInt{}}("0")),
            dotk{}()
          )
        ))
        """,
        KApply('_==K_', [KSequence((KVariable('X', 'Int'),)), KSequence((KToken('0', 'Int'),))]),
    ),
    (
        'k-under-kequal',
        KSort('KItem'),
        """
        inj{SortBool{}, SortKItem{}}(
        Lbl'UndsEqlsEqls'K'Unds'{}(
            VarX:SortK{},
            VarY:SortK{},
        ))
        """,
        KApply('_==K_', [KVariable('X', 'K'), KVariable('Y', 'K')]),
    ),
    (
        'empty-ksequence-under-kequal',
        KSort('KItem'),
        """
        inj{SortBool{}, SortKItem{}}(
        Lbl'UndsEqlsEqls'K'Unds'{}(
            dotk{}(),
            dotk{}(),
        ))
        """,
        KApply('_==K_', [KSequence([]), KSequence([])]),
    ),
    (
        'multi-ksequence-under-kequal',
        KSort('KItem'),
        """
        inj{SortBool{}, SortKItem{}}(
        Lbl'UndsEqlsEqls'K'Unds'{}(
          kseq{}(
            inj{SortInt{}, SortKItem{}}(VarX:SortInt{}),
            kseq{}(
              inj{SortInt{}, SortKItem{}}(VarY:SortInt{}),
              dotk{}()
            )
          ),
          kseq{}(
            inj{SortInt{}, SortKItem{}}(\\dv{SortInt{}}("0")),
            kseq{}(
              inj{SortInt{}, SortKItem{}}(\\dv{SortInt{}}("1")),
              dotk{}()
            )
          )
        ))
        """,
        KApply(
            '_==K_',
            [
                KSequence((KVariable('X', 'Int'), KVariable('Y', 'Int'))),
                KSequence((KToken('0', 'Int'), KToken('1', 'Int'))),
            ],
        ),
    ),
    (
        'variable-without-sort',
        KSort('Bar'),
        'VarX : SortBar{}',
        KVariable('X'),
    ),
    (
        'variable-different-sorts',
        KSort('BarHolder'),
        """
        Lblbarholder{}(
            Lblfoo{}(inj{SortBaz{}, SortBar{}}(VarB : SortBaz{})),
            inj{SortBaz{}, SortBar{}}(VarB : SortBaz{})
        )
        """,
        KApply('barholder', [KApply('foo', [KVariable('B', sort=KSort('Baz'))]), KVariable('B')]),
    ),
    (
        'variable-with-multi-sort',
        KSort('BarHolder'),
        'Lblbarholder2{}(inj{SortBaz{}, SortBar{}}(VarX : SortBaz{}), VarX : SortBaz{})',
        KApply('barholder2', [KVariable('X', sort=KSort('Baz')), KVariable('X', sort=KSort('Bar'))]),
    ),
    (
        'ml-exists-var-inference',
        KSort('Foo'),
        r'\exists{SortFoo{}}(VarX : SortBar{}, Lblfoo{}(VarX : SortBar{}))',
        KApply(KLabel('#Exists', [KSort('Bar'), KSort('Foo')]), [KVariable('X'), KApply('foo', [KVariable('X')])]),
    ),
    (
        'ml-multiple-exists-var-inference',
        KSort('Foo'),
        r"""\and{SortFoo{}}(
          \exists{SortFoo{}}(VarX : SortK{}, \equals{SortK{}, SortFoo{}}(VarX : SortK{}, VarX:SortK{})),
          \exists{SortFoo{}}(VarX : SortBar{}, Lblfoo{}(VarX : SortBar{}))
        )""",
        KApply(
            KLabel('#And', [KSort('Foo')]),
            [
                KApply(
                    KLabel('#Exists', [KSort('K'), KSort('Foo')]),
                    [
                        KVariable('X'),
                        KApply(
                            KLabel('#Equals', [KSort('K'), KSort('Foo')]),
                            [KVariable('X'), KSequence([KVariable('X')])],
                        ),
                    ],
                ),
                KApply(
                    KLabel('#Exists', [KSort('Bar'), KSort('Foo')]), [KVariable('X'), KApply('foo', [KVariable('X')])]
                ),
            ],
        ),
    ),
    (
        'ksequence-empty',
        KSort('K'),
        'dotk{}()',
        KSequence([]),
    ),
    (
        'ksequence-singleton-var',
        KSort('K'),
        'VarCONT : SortK{}',
        KSequence([KVariable('CONT')]),
    ),
    (
        'ksequence-duo-var-1',
        KSort('K'),
        'kseq{}(VarELEM : SortKItem{}, VarCONT : SortK{})',
        KSequence([KVariable('ELEM'), KVariable('CONT')]),
    ),
    (
        'ksequence-duo-var-2',
        KSort('K'),
        'kseq{}(VarELEM1 : SortKItem{}, kseq{}(VarELEM2 : SortKItem{}, dotk{}()))',
        KSequence([KVariable('ELEM1', sort=KSort('KItem')), KVariable('ELEM2', sort=KSort('KItem'))]),
    ),
    (
        'if-then-else-no-sort-param-k',
        KSort('K'),
        r'Lblite{SortK{}}(VarC : SortBool{}, VarB1 : SortK{}, VarB2 : SortK {})',
        KApply(
            KLabel('ite', []),
            [
                KVariable('C', sort=KSort('Bool')),
                KVariable('B1', sort=KSort('K')),
                KVariable('B2', sort=KSort('K')),
            ],
        ),
    ),
    (
        'if-then-else-no-sort-param-int',
        KSort('Int'),
        r"""
        Lbl'UndsPlus'Int'Unds'{}(
            VarA : SortInt{},
            Lblite{SortInt{}}(VarC : SortBool{}, VarI1 : SortInt{}, VarI2 : SortInt {})
        )
        """,
        KApply(
            '_+Int_',
            [
                KVariable('A', sort=KSort('Int')),
                KApply(
                    KLabel('ite', []),
                    [
                        KVariable('C', sort=KSort('Bool')),
                        KVariable('I1', sort=KSort('Int')),
                        KVariable('I2', sort=KSort('Int')),
                    ],
                ),
            ],
        ),
    ),
    (
        'if-then-else-no-sort-param-nested',
        KSort('Int'),
        r"""
        Lblite{SortInt{}}(
            VarC1 : SortBool{},
            Lblite{SortInt{}}(
                VarC2 : SortBool{}, VarI1 : SortInt{} , VarI2 : SortInt{}
            ),
            VarI3 : SortInt{}
        )
        """,
        KApply(
            KLabel('ite', []),
            [
                KVariable('C1', sort=KSort('Bool')),
                KApply(
                    KLabel('ite', []),
                    [
                        KVariable('C2', sort=KSort('Bool')),
                        KVariable('I1', sort=KSort('Int')),
                        KVariable('I2', sort=KSort('Int')),
                    ],
                ),
                KVariable('I3', sort=KSort('Int')),
            ],
        ),
    ),
)

KORE_TO_KAST_TEST_DATA: Final = BIDIRECTIONAL_TEST_DATA + (
    (
        'left-assoc',
        KSort('Map'),
        r"\left-assoc{}(Lbl'Unds'Map'Unds'{}(VarX : SortMap{}, VarY : SortMap{}, VarZ : SortMap{}))",
        KApply(
            '_Map_',
            [
                KApply('_Map_', [KVariable('X', sort=KSort('Map')), KVariable('Y', sort=KSort('Map'))]),
                KVariable('Z', sort=KSort('Map')),
            ],
        ),
    ),
    (
        'right-assoc',
        KSort('Map'),
        r"\right-assoc{}(Lbl'Unds'Map'Unds'{}(VarX : SortMap{}, VarY : SortMap{}, VarZ : SortMap{}))",
        KApply(
            '_Map_',
            [
                KVariable('X', sort=KSort('Map')),
                KApply('_Map_', [KVariable('Y', sort=KSort('Map')), KVariable('Z', sort=KSort('Map'))]),
            ],
        ),
    ),
)

KRULE_TO_KORE_DATA: Final = (
    (
        'SIMPLE-PROOFS.foo-to-bar',
        r"""axiom{} \rewrites{SortGeneratedTopCell{}}(\and{SortGeneratedTopCell{}}(Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'DotVar1 : SortK{})), Lbl'-LT-'state'-GT-'{}(Lbl'Unds'Map'Unds'{}(Lbl'UndsPipe'-'-GT-Unds'{}(inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("3")), inj{SortInt{}, SortKItem{}}(VarN : SortInt{})), Var'Unds'DotVar2 : SortMap{})), Var'Unds'DotVar0 : SortGeneratedCounterCell{}), \equals{SortBool{}, SortGeneratedTopCell{}}(\dv{SortBool{}}("true"), Lblpred1{}(VarN : SortInt{}))), Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(Lblbar'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'DotVar1 : SortK{})), Lbl'-LT-'state'-GT-'{}(Lbl'Unds'Map'Unds'{}(Lbl'UndsPipe'-'-GT-Unds'{}(inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("3")), inj{SortInt{}, SortKItem{}}(VarN : SortInt{})), Var'Unds'DotVar2 : SortMap{})), Var'Unds'DotVar0 : SortGeneratedCounterCell{})) [label{}("SIMPLE-PROOFS.foo-to-bar"), priority{}("50")]""",
    ),
    (
        'SIMPLE-PROOFS.foo-to-bar-false',
        r"""axiom{} \rewrites{SortGeneratedTopCell{}}(\and{SortGeneratedTopCell{}}(Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'RestK : SortK{})), Lbl'-LT-'state'-GT-'{}(Lbl'Unds'Map'Unds'{}(Lbl'UndsPipe'-'-GT-Unds'{}(inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("3")), inj{SortInt{}, SortKItem{}}(VarN : SortInt{})), Var'Unds'RestState : SortMap{})), Var'Unds'DotVar0 : SortGeneratedCounterCell{}), \and{SortGeneratedTopCell{}}(\equals{SortBool{}, SortGeneratedTopCell{}}(\dv{SortBool{}}("true"), Lblpred1{}(VarN : SortInt{})), \bottom{SortGeneratedTopCell{}}())), Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(Lblbar'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'RestK : SortK{})), Lbl'-LT-'state'-GT-'{}(Lbl'Unds'Map'Unds'{}(Lbl'UndsPipe'-'-GT-Unds'{}(inj{SortInt{}, SortKItem{}}(\dv{SortInt{}}("3")), inj{SortInt{}, SortKItem{}}(VarN : SortInt{})), Var'Unds'RestState : SortMap{})), Var'Unds'DotVar0 : SortGeneratedCounterCell{})) [label{}("SIMPLE-PROOFS.foo-to-bar-false"), priority{}("30")]""",
    ),
    (
        'SIMPLE-PROOFS.foo-to-baz-owise',
        r"""axiom{} \rewrites{SortGeneratedTopCell{}}(\and{SortGeneratedTopCell{}}(Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'DotVar1 : SortK{})))), Var'Unds'Gen0 : SortStateCell{}, Var'Unds'Gen1 : SortGeneratedCounterCell{}), \top{SortGeneratedTopCell{}}()), Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(inj{SortBaz{}, SortKItem{}}(Lblbaz{}()), kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), kseq{}(Lblfoo'Unds'SIMPLE-PROOFS'Unds'KItem{}(), Var'Unds'DotVar1 : SortK{})))), Var'Unds'Gen0 : SortStateCell{}, Var'Unds'Gen1 : SortGeneratedCounterCell{})) [label{}("SIMPLE-PROOFS.foo-to-baz-owise"), priority{}("200")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func',
        r"""axiom{R} \implies{R}(\and{R}(\top{R}(), \top{R}()), \equals{SortInt{}, R}(LblsimpleFunc{}(), \and{SortInt{}}(\dv{SortInt{}}("3"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func"), priority{}("50")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-req-1',
        r"""axiom{R} \implies{R}(\and{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-Eqls'Int'Unds'{}(VarX:SortInt{}, \dv{SortInt{}}("0")), \dv{SortBool{}}("true")), \and{R}(\in{SortInt{}, R}(X0:SortInt{}, VarX:SortInt{}), \top{R}())), \equals{SortInt{},R}(LblleqZero{}(X0:SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("0"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func-req-1"), priority{}("50")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(LblleqZero{}(VarX : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func-simplification"), simplification{}("")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-prio',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(LblleqZero{}(VarX : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func-simplification-prio"), simplification{}("38")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-concrete-noarg',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(LblleqZero{}(VarX : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [concrete{}(), label{}("SIMPLE-PROOFS.simple-func-simplification-concrete-noarg"), simplification{}("")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-concrete',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(LblleqZero{}(VarX : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [concrete{}(VarX : SortInt{}), label{}("SIMPLE-PROOFS.simple-func-simplification-concrete"), simplification{}("")]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-symbolic',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(LblleqZero{}(VarX : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func-simplification-symbolic"), simplification{}(""), symbolic{}(VarX : SortInt{})]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-symbolic-2vars',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(Lbl'Unds-LT-'Int'Unds'{}(\dv{SortInt{}}("0"), VarX : SortInt{}), \dv{SortBool{}}("true")), \equals{SortInt{}, R}(Lblleq{}(VarX : SortInt{}, Var'Unds'Y : SortInt{}), \and{SortInt{}}(\dv{SortInt{}}("1"), \top{SortInt{}}()))) [label{}("SIMPLE-PROOFS.simple-func-simplification-symbolic-2vars"), simplification{}(""), symbolic{}(VarX : SortInt{}, Var'Unds'Y : SortInt{})]""",
    ),
    (
        'SIMPLE-PROOFS.simple-func-simplification-smt-lemma',
        r"""axiom{R} \implies{R}(\equals{SortBool{}, R}(\dv{SortBool{}}("true"), \dv{SortBool{}}("true")), \equals{SortBool{}, R}(Lbl'UndsEqlsEqls'Int'Unds'{}(Lblleq{}(Var'Unds'Gen0 : SortInt{}, Var'Unds'Gen1 : SortInt{}), \dv{SortInt{}}("0")), \and{SortBool{}}(\dv{SortBool{}}("false"), \top{SortBool{}}()))) [label{}("SIMPLE-PROOFS.simple-func-simplification-smt-lemma"), simplification{}(""), smt-lemma{}()]""",
    ),
)

KRULE_TO_KORE_EXPLICIT_DATA: Final = (
    (
        'unsorted variable in requires',
        KRule(
            body=KRewrite(
                KApply(
                    '<generatedTop>',
                    (
                        KApply('<k>', (KSequence([KApply('pred1', (KVariable('U', INT),))]),)),
                        KApply('<state>', (KApply('.Map', ()),)),
                        KVariable('Counter', KSort('GeneratedCounterCell')),
                    ),
                ),
                KApply(
                    '<generatedTop>',
                    (
                        KApply('<k>', (KSequence([]),)),
                        KApply('<state>', (KApply('.Map', ()),)),
                        KVariable('Counter', KSort('GeneratedCounterCell')),
                    ),
                ),
            ),
            requires=KApply(
                KLabel('#And', params=(BOOL,)),
                (
                    TRUE,
                    KApply(KLabel('#Equals', params=(BOOL, BOOL)), (TRUE, KApply('pred1', KVariable('V')))),
                ),
            ),
        ),
        r"""axiom{} \rewrites{SortGeneratedTopCell{}}(\and{SortGeneratedTopCell{}}(Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(kseq{}(inj{SortBool{}, SortKItem{}}(Lblpred1{}(VarU : SortInt{})), dotk{}())), Lbl'-LT-'state'-GT-'{}(Lbl'Stop'Map{}()), VarCounter : SortGeneratedCounterCell{}), \equals{SortBool{}, SortGeneratedTopCell{}}(\dv{SortBool{}}("true"), \and{SortBool{}}(\dv{SortBool{}}("true"), \equals{SortBool{}, SortBool{}}(\dv{SortBool{}}("true"), Lblpred1{}(VarV : SortInt{}))))), Lbl'-LT-'generatedTop'-GT-'{}(Lbl'-LT-'k'-GT-'{}(dotk{}()), Lbl'-LT-'state'-GT-'{}(Lbl'Stop'Map{}()), VarCounter : SortGeneratedCounterCell{})) [priority{}("50")]""",
    ),
)

SORT_TERM_DATA: Final = (
    (
        'variable-int',
        KVariable('X', 'Int'),
        KSort('Int'),
    ),
    (
        'variable-bool',
        KVariable('X', 'Bool'),
        KSort('Bool'),
    ),
    (
        'variable-k',
        KVariable('X', 'K'),
        KSort('K'),
    ),
    (
        'variable-kitem',
        KVariable('X', 'KItem'),
        KSort('KItem'),
    ),
    (
        'int-token',
        intToken(1),
        KSort('Int'),
    ),
    (
        'bool-token',
        KToken('true', 'Bool'),
        KSort('Bool'),
    ),
    (
        'ksequence',
        KSequence((intToken(0), intToken(1), intToken(2))),
        KSort('K'),
    ),
    (
        'krewrite-same-sort',
        KRewrite(lhs=intToken(0), rhs=intToken(1)),
        KSort('Int'),
    ),
    (
        'krewrite-direct-supersort-lhs',
        KRewrite(lhs=intToken(0), rhs=KVariable('X', 'KItem')),
        KSort('KItem'),
    ),
    (
        'krewrite-direct-supersort-rhs',
        KRewrite(rhs=intToken(0), lhs=KVariable('X', 'KItem')),
        KSort('KItem'),
    ),
    (
        'sort-parametric-int',
        KApply(
            KLabel('ite', [KSort('Int')]),
            [KToken('true', 'Bool'), intToken(1), intToken(2)],
        ),
        KSort('Int'),
    ),
    (
        'sort-parametric-bool',
        KApply(
            KLabel('ite', [KSort('Bool')]),
            [KToken('true', 'Bool'), KToken('true', 'Bool'), KToken('false', 'Bool')],
        ),
        KSort('Bool'),
    ),
)


SKIPPED_FRONTEND_COMP_TESTS: Final = set((TEST_DATA_DIR / 'frontend-comp-skip').read_text().splitlines())


class TestKonvertSimpleProofs(KPrintTest):
    KOMPILE_MAIN_FILE = K_FILES / 'simple-proofs.k'
    KOMPILE_ARGS = {'syntax_module': 'SIMPLE-PROOFS'}

    @pytest.mark.parametrize(
        'test_id,sort,kore_text,kast',
        KAST_TO_KORE_TEST_DATA,
        ids=[test_id for test_id, *_ in KAST_TO_KORE_TEST_DATA],
    )
    def test_kast_to_kore(
        self,
        definition: KDefinition,
        test_id: str,
        sort: KSort,
        kore_text: str,
        kast: KInner,
    ) -> None:
        # Given
        expected_kore = KoreParser(kore_text).pattern()

        # When
        actual_kore = kast_to_kore(definition, kast, sort=sort)

        # Then
        assert actual_kore == expected_kore

    @pytest.mark.parametrize(
        'test_id,sort,kore_text,kast',
        KAST_TO_KORE_TEST_DATA,
        ids=[test_id for test_id, *_ in KAST_TO_KORE_TEST_DATA],
    )
    def test_kast_to_kore_frontend(
        self,
        definition: KDefinition,
        test_id: str,
        sort: KSort,
        kore_text: str,
        kast: KInner,
        kprint: KPrint,
    ) -> None:
        if test_id in SKIPPED_FRONTEND_COMP_TESTS:
            pytest.skip()

        # Given
        expected_kore = KoreParser(kore_text).pattern()

        # When
        actual_kore = kprint.kast_to_kore(kast=kast, sort=sort, force_kast=True)

        # Then
        assert actual_kore == expected_kore

    @pytest.mark.parametrize(
        'test_id,_sort,kore_text,kast',
        KORE_TO_KAST_TEST_DATA,
        ids=[test_id for test_id, *_ in KORE_TO_KAST_TEST_DATA],
    )
    def test_kore_to_kast(
        self,
        definition: KDefinition,
        test_id: str,
        _sort: KSort,
        kore_text: str,
        kast: KInner,
    ) -> None:
        # Given
        kore = KoreParser(kore_text).pattern()

        # When
        actual_kast = kore_to_kast(definition, kore)

        # Then
        assert actual_kast == kast

    @pytest.mark.parametrize(
        'rule_id,kore_text',
        KRULE_TO_KORE_DATA,
        ids=[rule_id for rule_id, *_ in KRULE_TO_KORE_DATA],
    )
    def test_krule_to_kore(
        self,
        definition: KDefinition,
        rule_id: str,
        kore_text: str,
    ) -> None:
        main_module = definition.all_modules_dict[definition.main_module_name]
        rule = single(r for r in main_module.rules if Atts.LABEL in r.att and r.att[Atts.LABEL] == rule_id)

        # When
        actual_kore_text = krule_to_kore(definition, rule).text

        # Then
        assert actual_kore_text == kore_text

    @pytest.mark.parametrize(
        'test_id,rule,kore_text',
        KRULE_TO_KORE_EXPLICIT_DATA,
        ids=[test_id for test_id, *_ in KRULE_TO_KORE_EXPLICIT_DATA],
    )
    def test_explicit_krule_to_kore(
        self,
        definition: KDefinition,
        test_id: str,
        rule: KRule,
        kore_text: str,
    ) -> None:
        # When
        actual_kore_text = krule_to_kore(definition, rule).text

        # Then
        assert actual_kore_text == kore_text

    @pytest.mark.parametrize(
        'test_id,kast,expected_sort',
        SORT_TERM_DATA,
        ids=[test_id for test_id, *_ in SORT_TERM_DATA],
    )
    def test_sort_term(
        self,
        definition: KDefinition,
        test_id: str,
        kast: KInner,
        expected_sort: KSort,
    ) -> None:
        # When
        actual_sort = definition.sort(kast)

        # Then
        assert actual_sort == expected_sort
