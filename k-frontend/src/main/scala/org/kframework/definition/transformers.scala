// Copyright (c) Runtime Verification, Inc. All Rights Reserved.

package org.kframework.definition

import java.util.function.BiFunction
import java.util.Optional
import org.kframework.attributes.Location
import org.kframework.attributes.Source
import org.kframework.definition
import org.kframework.kore.AttCompare
import org.kframework.kore.K
import org.kframework.kore.KApply
import org.kframework.kore.KToken
import org.kframework.utils.errorsystem.KEMException

object ModuleTransformer {
  def from(f: java.util.function.UnaryOperator[Module], name: String): ModuleTransformer =
    ModuleTransformer(f(_), name)

  def fromSentenceTransformer(
      f: java.util.function.UnaryOperator[Sentence],
      name: String
  ): ModuleTransformer =
    fromSentenceTransformer((m: Module, s: Sentence) => f(s), name)

  def fromSentenceTransformer(f: (Module, Sentence) => Sentence, name: String): ModuleTransformer =
    ModuleTransformer(
      m => {
        val newSentences = m.localSentences.map { s =>
          try
            f(m, s)
          catch {
            case e: KEMException =>
              val extraInfo = Optional
                .of(" on sentence at")
                .flatMap[String](prefix =>
                  s.source.map[String](src => prefix + "\n\t" + src.toString)
                )
                .flatMap[String](prefix =>
                  s.location.map[String](loc => prefix + "\n\t" + loc.toString)
                )
                .orElse("")

              e.exception.addTraceFrame("while executing phase \"" + name + "\"" + extraInfo)
              throw e
          }
        }
        // TODO(compare attributes)
        if (newSentences != m.localSentences)
          Module(m.name, m.imports, newSentences, m.att)
        else
          m
      },
      name
    )

  def fromRuleBodyTransformer(f: K => K, name: String): ModuleTransformer =
    fromRuleBodyTransformerWithRule((rule, k) => f(k), name)

  def fromRuleBodyTransformerWithRule(f: (RuleOrClaim, K) => K, name: String): ModuleTransformer =
    fromSentenceTransformer(
      _ match {
        case r: Rule  => r.copy(body = f(r, r.body));
        case c: Claim => c.copy(body = f(c, c.body));
        case s        => s
      },
      name
    )

  def fromKTransformerWithModuleInfo(ff: (Module, K) => K, name: String): ModuleTransformer =
    fromSentenceTransformer(
      (module, sentence) =>
        sentence match {
          case r: Rule =>
            Rule.apply(ff(module, r.body), ff(module, r.requires), ff(module, r.ensures), r.att)
          case c: Claim =>
            Claim.apply(ff(module, c.body), ff(module, c.requires), ff(module, c.ensures), c.att)
          case c: Context => Context.apply(ff(module, c.body), ff(module, c.requires), c.att)
          case c: ContextAlias =>
            ContextAlias.apply(ff(module, c.body), ff(module, c.requires), c.att)
          case o => o
        },
      name
    )

  def fromKTransformer(f: K => K, name: String): ModuleTransformer =
    fromKTransformerWithModuleInfo((mod, k) => f(k), name)

  def apply(f: Module => Module, name: String): ModuleTransformer = f match {
    case f: ModuleTransformer => f
    case _                    => new ModuleTransformer(f, name)
  }
}

/**
 * Transform all modules, transforming each module after its imports. The f function take a module
 * with all the imported modules already transformed, and changes the current module. Modules for
 * which `skip` holds are returned unchanged, and so are their imports.
 */
class ModuleTransformer(
    f: Module => Module,
    name: String,
    skip: java.util.function.Predicate[Module]
) extends (Module => Module) {
  def this(f: Module => Module, name: String) = this(f, name, _ => false)

  /** This transformation, but leaving the modules for which `p` holds (and their imports) as is. */
  def skipping(p: java.util.function.Predicate[Module]): ModuleTransformer =
    new ModuleTransformer(f, name, p)

  val memoization = collection.concurrent.TrieMap[Module, Module]()

  override def apply(input: Module): Module =
    if (skip.test(input)) input
    else
      memoization.getOrElseUpdate(
        input, {
          var newImports = input.imports.map(i => Import(this(i.module), i.isPublic))
          if (newImports != input.imports)
            f(Module(input.name, newImports, input.localSentences, input.att))
          else
            f(input)
        }
      )
}

object DefinitionTransformer {
  def fromSentenceTransformer(
      f: java.util.function.UnaryOperator[Sentence],
      name: String
  ): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromSentenceTransformer(f, name))

  def fromSentenceTransformer(
      f: (Module, Sentence) => Sentence,
      name: String
  ): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromSentenceTransformer(f, name))

  def fromRuleBodyTransformer(f: K => K, name: String): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromRuleBodyTransformer(f, name))

  def fromRuleBodyTransformerWithRule(
      f: (RuleOrClaim, K) => K,
      name: String
  ): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromRuleBodyTransformerWithRule(f, name))

  def fromKTransformer(f: K => K, name: String): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromKTransformer(f, name))

  def fromKTransformerWithModuleInfo(f: (Module, K) => K, name: String): DefinitionTransformer =
    DefinitionTransformer(ModuleTransformer.fromKTransformerWithModuleInfo(f, name))

  def from(f: Module => Module, name: String): DefinitionTransformer =
    DefinitionTransformer(f, name)

  def apply(f: Module => Module): DefinitionTransformer = new DefinitionTransformer(f)

  def apply(f: Module => Module, name: String): DefinitionTransformer = new DefinitionTransformer(
    ModuleTransformer(f, name)
  )
}

class DefinitionTransformer(moduleTransformer: Module => Module)
    extends (Definition => Definition) {
  override def apply(d: Definition): Definition =
    definition.Definition(
      moduleTransformer(d.mainModule),
      d.entryModules.map(moduleTransformer),
      d.att
    )
}

object KViz {
  def from(f: java.util.function.UnaryOperator[K], name: String): KViz = KViz(f(_), name)

  def apply(f: K => K, name: String): KViz = f match {
    case f: KViz => f
    case _       => new KViz(f, name)
  }
}

class KViz(f: K => K, name: String) extends (K => K) {
  override def apply(input: K): K =
    input match {
      case c: KToken => f(c)
      case tc: KApply =>
        f(tc)
        tc.items.forEach(apply)
        tc
      case _ =>
        throw new AssertionError("Not expected downed term in visitor " + name + " term: " + input)
    }
}
