package org.kframework

import org.kframework.attributes.Att
import org.kframework.builtin.BooleanUtils
import org.kframework.builtin.KLabels
import org.kframework.builtin.Sorts
import org.kframework.compile.RewriteToTop
import org.kframework.definition.{DefinitionTransformer, ModuleTransformer, Module, Rule, Definition}
import org.kframework.kore.KORE
import org.kframework.kore.Sort
import org.kframework.kore.Unapply.{KApply, KLabel}

object Strategy {
  val strategyCellName = "<s>"
  val strategyCellLabel = KORE.KLabel(strategyCellName)

  def addStrategyRuleToMainModule(mainModuleName: String) = {
    DefinitionTransformer(
      module =>
        if (module.name != mainModuleName || !module.importedModuleNames.contains("STRATEGY$SYNTAX")) {
          module
        } else {
          Module(module.name, module.imports, module.localSentences + Rule(
            KORE.KApply(strategyCellLabel,
              KORE.KApply(KLabels.NO_DOTS),
              KORE.KRewrite(
                KORE.KVariable("S", Att.empty.add(classOf[Sort], Sorts.KItem)),
                KORE.KSequence(
                  KORE.KApply(KORE.KLabel("#STUCK")),
                  KORE.KVariable("S", Att.empty.add(classOf[Sort], Sorts.KItem)),
                )
              ),
              KORE.KApply(KLabels.DOTS)
            ),
            KORE.KApply(
              KLabels.NOT_EQUALS_K, 
              KORE.KVariable("S", Att.empty.add(classOf[Sort], Sorts.KItem)),
              KORE.KApply(KORE.KLabel("#STUCK")),
            ),
            BooleanUtils.TRUE,
            Att.empty.add("owise")
          ), module.att)
        }
    )
  }
}

class Strategy(heatCool: Boolean) {
  import Strategy._

  def addStrategyCellToRulesTransformer(defn: Definition) =
    DefinitionTransformer(
      ModuleTransformer.fromSentenceTransformer({
        (module, r) =>
          val rich = kore.Rich(module)

          import rich._
          
          if (!defn.mainModule.importedModuleNames.contains("STRATEGY$SYNTAX") || r.att.contains("anywhere") || r.att.contains("macro")) {
            r
          } else
            r match {
              case r: Rule if !r.body.contains({ case k: kore.KApply => k.klabel.name.contains("<s>") }) =>
                val newBody = RewriteToTop.toLeft(r.body) match {
                  case KApply(klabel, _) if !module.attributesFor.contains(klabel) || !module.attributesFor(klabel).contains(Att.Function) =>
                    // todo: "!module.attributesFor.contains(klabel) ||" when #1723 is fixed

                    def makeRewrite(tag: String) =
                      KORE.KSequence(
                        KORE.KRewrite(
                          KORE.KApply(KORE.KLabel("#applyRule"), KORE.KToken(tag, KORE.Sort("#RuleTag"))),
                          KORE.KApply(KORE.KLabel("#appliedRule"), KORE.KToken(tag, KORE.Sort("#RuleTag")))),
                        KORE.KVariable("SREST"))

                    val strategy =
                      if (r.att.contains("tag")) {
                        makeRewrite(r.att.get("tag"))
                      } else if (heatCool && r.att.contains(Att.heat)) {
                        makeRewrite("heat")
                      } else if (heatCool && r.att.contains(Att.cool)) {
                        makeRewrite("cool")
                      } else {
                        makeRewrite("regular")
                      }

                    KORE.KApply(KLabels.CELLS, r.body,
                      KORE.KApply(strategyCellLabel,
                        KORE.KApply(KLabels.NO_DOTS),
                        strategy,
                        KORE.KApply(KLabels.NO_DOTS)
                      ))
                  case _ => r.body
                }
                Rule(newBody, r.requires, r.ensures, r.att)
              case r => r
            }
      }, "add strategy cell to rules"))

}
