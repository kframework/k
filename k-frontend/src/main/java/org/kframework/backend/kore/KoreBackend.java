// Copyright (c) Runtime Verification, Inc. All Rights Reserved.
package org.kframework.backend.kore;

import static java.util.Map.entry;
import static org.kframework.Collections.*;

import com.google.inject.Inject;
import java.io.File;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import org.apache.commons.io.FilenameUtils;
import org.kframework.attributes.Att;
import org.kframework.backend.Backends;
import org.kframework.compile.*;
import org.kframework.definition.*;
import org.kframework.definition.Module;
import org.kframework.kompile.CompiledDefinition;
import org.kframework.kompile.Kompile;
import org.kframework.kompile.KompileOptions;
import org.kframework.kore.KLabel;
import org.kframework.main.Tool;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.errorsystem.KException;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;
import scala.Function1;

public class KoreBackend implements Backend {

  private final KompileOptions kompileOptions;
  protected final FileUtil files;
  private final KExceptionManager kem;
  protected final boolean heatCoolEquations;
  private final Tool tool;

  @Inject
  public KoreBackend(
      KompileOptions kompileOptions, FileUtil files, KExceptionManager kem, Tool tool) {
    this(kompileOptions, files, kem, false, tool);
  }

  public KoreBackend(
      KompileOptions kompileOptions,
      FileUtil files,
      KExceptionManager kem,
      boolean heatCoolEquations,
      Tool tool) {
    this.kompileOptions = kompileOptions;
    this.files = files;
    this.kem = kem;
    this.heatCoolEquations = heatCoolEquations;
    this.tool = tool;
  }

  @Override
  public void accept(Backend.Holder h) {
    CompiledDefinition def = h.def;
    String kore = getKompiledString(def, true);
    File defFile = kompileOptions.outerParsing.mainDefinitionFile(files);
    String name = defFile.getName();
    String basename = FilenameUtils.removeExtension(name);
    files.saveToDefinitionDirectory(basename + ".kore", kore);
  }

  /**
   * Convert a CompiledDefinition to a String of a KORE definition.
   *
   * @param hasAnd whether the backend in question supports and-patterns during pattern matching.
   */
  protected String getKompiledString(
      CompiledDefinition def, @SuppressWarnings("unused") boolean hasAnd) {
    Module mainModule = getKompiledModule(def.kompiledDefinition.mainModule(), hasAnd);
    ModuleToKORE converter =
        new ModuleToKORE(mainModule, def.topCellInitializer, def.kompileOptions);
    return getKompiledString(converter, files, heatCoolEquations, tool);
  }

  public static String getKompiledString(
      ModuleToKORE converter, FileUtil files, boolean heatCoolEquations, Tool t) {
    StringBuilder sb = new StringBuilder();
    String kompiledString =
        getKompiledStringAndWriteSyntaxMacros(converter, files, heatCoolEquations, sb, t);
    return kompiledString;
  }

  public static String getKompiledStringAndWriteSyntaxMacros(
      ModuleToKORE converter, FileUtil files, boolean heatCoolEq, StringBuilder sb, Tool t) {
    StringBuilder semantics = new StringBuilder();
    StringBuilder syntax = new StringBuilder();
    StringBuilder macros = new StringBuilder();
    String prelude = files.loadFromKIncludeDir("kore/prelude.kore");
    converter.convert(heatCoolEq, prelude, semantics, syntax, macros);
    if (t == Tool.KOMPILE) {
      files.saveToKompiled("syntaxDefinition.kore", syntax.toString());
      files.saveToKompiled("macros.kore", macros.toString());
    }
    return semantics.toString();
  }

  public static Module getKompiledModule(Module mainModule, boolean hasAnd) {
    mainModule =
        ModuleTransformer.fromSentenceTransformer(
                new AddSortInjections(mainModule)::addInjections, "Add sort injections")
            .apply(mainModule);
    mainModule =
        ModuleTransformer.from(new RemoveUnit()::apply, "Remove unit applications for collections")
            .apply(mainModule);
    if (hasAnd) {
      mainModule =
          ModuleTransformer.fromSentenceTransformer(
                  new MinimizeTermConstruction(mainModule)::resolve, "Minimize term construction")
              .apply(mainModule);
    }
    return mainModule;
  }

  @Override
  public Function<Definition, Definition> steps() {
    DefinitionTransformer resolveComm =
        DefinitionTransformer.from(
            new ResolveComm(kem)::resolve, "resolve comm simplification rules");
    Function1<Definition, Definition> resolveStrict =
        d ->
            DefinitionTransformer.from(
                    new ResolveStrict(d)::resolve, "resolving strict and seqstrict attributes")
                .apply(d);
    DefinitionTransformer resolveHeatCoolAttribute =
        DefinitionTransformer.fromSentenceTransformer(
            ResolveHeatCoolAttribute::resolve, "resolving heat and cool attributes");
    DefinitionTransformer resolveAnonVars =
        DefinitionTransformer.fromSentenceTransformer(
            new ResolveAnonVar()::resolve, "resolving \"_\" vars");
    DefinitionTransformer guardOrs =
        DefinitionTransformer.fromSentenceTransformer(
            new GuardOrPatterns()::resolve, "resolving or patterns");
    DefinitionTransformer resolveSemanticCasts =
        DefinitionTransformer.fromSentenceTransformer(
            new ResolveSemanticCasts(true)::resolve, "resolving semantic casts");
    DefinitionTransformer resolveFun =
        DefinitionTransformer.from(new ResolveFun()::resolve, "resolving #fun");
    Function1<Definition, Definition> resolveFunctionWithConfig =
        d ->
            DefinitionTransformer.from(
                    new ResolveFunctionWithConfig(d)::moduleResolve,
                    "resolving functions with config context")
                .apply(d);
    DefinitionTransformer generateSortPredicateSyntax =
        DefinitionTransformer.from(
            new GenerateSortPredicateSyntax()::gen, "adding sort predicate productions");
    DefinitionTransformer generateSortPredicateRules =
        DefinitionTransformer.from(
            new GenerateSortPredicateRules()::gen, "adding sort predicate rules");
    Function1<Definition, Definition> generateSortProjections =
        d ->
            DefinitionTransformer.from(
                    new GenerateSortProjections(kompileOptions.coverage, d.mainModule())::gen,
                    "adding sort projections")
                .apply(d);
    DefinitionTransformer subsortKItem =
        DefinitionTransformer.from(Kompile::subsortKItem, "subsort all sorts to KItem");
    Function1<Definition, Definition> addCoolLikeAtt =
        d ->
            DefinitionTransformer.fromSentenceTransformer(
                    new AddCoolLikeAtt(d.mainModule())::add, "add cool-like attribute")
                .apply(d);
    Function1<Definition, Definition> propagateMacroToRules =
        d ->
            DefinitionTransformer.fromSentenceTransformer(
                    (m, s) -> new PropagateMacro(m).propagate(s),
                    "propagate macro labels from production to rules")
                .apply(d);
    Function1<Definition, Definition> expandMacros =
        d -> {
          ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(d);
          return DefinitionTransformer.fromSentenceTransformer(
                  (m, s) ->
                      new ExpandMacros(transformer, m, files, kem, kompileOptions, false).expand(s),
                  "expand macros")
              .apply(d);
        };
    Function1<Definition, Definition> checkSimplificationRules =
        d ->
            DefinitionTransformer.from(
                    m -> {
                      m.localRules().foreach(r -> checkSimpIsFunc(m, r));
                      return m;
                    },
                    "Check simplification rules")
                .apply(d);
    DefinitionTransformer constantFolding =
        DefinitionTransformer.fromSentenceTransformer(
            new ConstantFolding()::fold, "constant expression folding");
    ResolveFreshConfigConstants freshConfigResolver = new ResolveFreshConfigConstants();
    Function1<Definition, Definition> resolveFreshConfigConstants =
        d ->
            DefinitionTransformer.from(
                    m -> freshConfigResolver.resolve(m), "resolving !Var config variables")
                .apply(d);
    Function1<Definition, Definition> resolveFreshConstants =
        d ->
            DefinitionTransformer.from(
                    m ->
                        new ResolveFreshConstants(
                                kem,
                                d,
                                kompileOptions.topCell,
                                files,
                                freshConfigResolver.getCurrentFresh())
                            .resolve(m),
                    "resolving !Var variables")
                .apply(d);
    Function1<Definition, Definition> genCoverage =
        kompileOptions.coverage ? d -> GenerateCoverage.gen(d, files) : d -> d;
    DefinitionTransformer numberSentences =
        DefinitionTransformer.fromSentenceTransformer(
            NumberSentences::number, "number sentences uniquely");
    Function1<Definition, Definition> resolveConfigVar =
        d ->
            DefinitionTransformer.fromSentenceTransformer(
                    new ResolveFunctionWithConfig(d)::resolveConfigVar,
                    "Adding configuration variable to lhs")
                .apply(d);
    Function1<Definition, Definition> resolveIO = (d -> Kompile.resolveIOStreams(kem, d));
    Function1<Definition, Definition> removeAnywhereRules =
        d ->
            DefinitionTransformer.from(
                    this::removeAnywhereRules, "removing anywhere rules for the Haskell backend")
                .apply(d);

    Map<String, Function1<Definition, Definition>> namedStages =
        Map.ofEntries(
            entry("resolveComm", resolveComm),
            entry("resolveIO", resolveIO),
            entry("resolveFun", resolveFun),
            entry("resolveFunctionWithConfig", resolveFunctionWithConfig),
            entry("resolveStrict", resolveStrict),
            entry("resolveAnonVars", resolveAnonVars),
            entry("resolveContexts", d -> new ResolveContexts().resolve(d)),
            entry("numberSentences1", numberSentences),
            entry("resolveHeatCoolAttribute", resolveHeatCoolAttribute),
            entry("resolveSemanticCasts", resolveSemanticCasts),
            entry("subsortKItem1", subsortKItem),
            entry("constantFolding", constantFolding),
            entry("propagateMacroToRules", propagateMacroToRules),
            entry("guardOrs", guardOrs),
            entry("resolveFreshConfigConstants", resolveFreshConfigConstants),
            entry("generateSortPredicateSyntax1", generateSortPredicateSyntax),
            entry("generateSortProjections1", generateSortProjections),
            entry("expandMacros", expandMacros),
            entry("addImplicitComputationCell", AddImplicitComputationCell::transformDefinition),
            entry("resolveFreshConstants", resolveFreshConstants),
            entry("generateSortPredicateSyntax2", generateSortPredicateSyntax),
            entry("generateSortProjections2", generateSortProjections),
            entry("checkSimplificationRules", checkSimplificationRules),
            entry("subsortKItem2", subsortKItem),
            entry("concretizeCells", d -> ConcretizeCells.transformDefinition(d)),
            entry("genCoverage", genCoverage),
            entry("addSemanticsModule", Kompile::addSemanticsModule),
            entry("resolveConfigVar", resolveConfigVar),
            entry("addCoolLikeAtt", addCoolLikeAtt),
            entry("removeAnywhereRules", removeAnywhereRules),
            entry("generateSortPredicateRules", generateSortPredicateRules),
            entry("numberSentences2", numberSentences));

    List<String> stepOrdering;
    if (kompileOptions.koreBackendSteps != null) {
      stepOrdering = List.of(kompileOptions.koreBackendSteps.split(","));
    } else {
      stepOrdering =
          List.of(
              "resolveComm",
              "resolveIO",
              "resolveFun",
              "resolveFunctionWithConfig",
              "resolveStrict",
              "resolveAnonVars",
              "resolveContexts",
              "numberSentences1",
              "resolveHeatCoolAttribute",
              "resolveSemanticCasts",
              "subsortKItem1",
              "constantFolding",
              "propagateMacroToRules",
              "guardOrs",
              "resolveFreshConfigConstants",
              "generateSortPredicateSyntax1",
              "generateSortProjections1",
              "expandMacros",
              "addImplicitComputationCell",
              "resolveFreshConstants",
              "generateSortPredicateSyntax2",
              "generateSortProjections2",
              "checkSimplificationRules",
              "subsortKItem2",
              "concretizeCells",
              "genCoverage",
              "addSemanticsModule",
              "resolveConfigVar",
              "addCoolLikeAtt",
              "removeAnywhereRules",
              "generateSortPredicateRules",
              "numberSentences2");
    }

    Function1<Definition, Definition> applyPipeline =
        stepOrdering.stream()
            .peek(
                name -> {
                  if (!namedStages.containsKey(name))
                    throw KEMException.compilerError(
                        "Step doesn't exist for --kore-backend-steps: " + name);
                })
            .map(name -> namedStages.get(name))
            .reduce(d -> d, (f, g) -> f.andThen(g));

    return d -> applyPipeline.apply(d);
  }

  /**
   * The passes applied to a spec module and its imports. The modules of the kompiled definition
   * {@code def} are replaced by their kompiled versions afterwards, so only the passes that prepare
   * macro expansion (and the functions that need the configuration) are applied to them. The other
   * passes are applied only to the modules that are not part of {@code def}.
   */
  @Override
  public Function<Module, Module> specificationSteps(Definition def) {
    Set<String> definitionModules =
        stream(def.modules()).map(Module::name).collect(Collectors.toSet());
    Predicate<Module> inDefinition = m -> definitionModules.contains(m.name());
    ModuleTransformer resolveComm =
        ModuleTransformer.from(new ResolveComm(kem)::resolve, "resolve comm simplification rules");
    Module mod = def.mainModule();
    ConfigurationInfoFromModule configInfo = new ConfigurationInfoFromModule(mod);
    LabelInfo labelInfo = new LabelInfoFromModule(mod);
    SortInfo sortInfo = SortInfo.fromModule(mod);
    ModuleTransformer resolveAnonVars =
        ModuleTransformer.fromSentenceTransformer(
            new ResolveAnonVar()::resolve, "resolving \"_\" vars");
    ModuleTransformer numberSentences =
        ModuleTransformer.fromSentenceTransformer(
            NumberSentences::number, "number sentences uniquely");
    ModuleTransformer resolveSemanticCasts =
        ModuleTransformer.fromSentenceTransformer(
            new ResolveSemanticCasts(true)::resolve, "resolving semantic casts");
    Function1<Module, Module> propagateMacroToRules =
        m ->
            ModuleTransformer.fromSentenceTransformer(
                    (m2, s) -> new PropagateMacro(m2).propagate(s),
                    "propagate macro labels from production to rules")
                .apply(m);
    Function1<Module, Module> expandMacros =
        m -> {
          ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(m);
          return ModuleTransformer.fromSentenceTransformer(
                  (m2, s) ->
                      new ExpandMacros(transformer, m2, files, kem, kompileOptions, false)
                          .expand(s),
                  "expand macros")
              .skipping(inDefinition)
              .apply(m);
        };
    Function1<Module, Module> checkSimplificationRules =
        ModuleTransformer.from(
            m -> {
              m.localRules().foreach(r -> checkSimpIsFunc(m, r));
              return m;
            },
            "Check simplification rules")
            .skipping(inDefinition);
    ModuleTransformer subsortKItem =
        ModuleTransformer.from(Kompile::subsortKItem, "subsort all sorts to KItem")
            .skipping(inDefinition);
    ModuleTransformer addImplicitComputationCell =
        ModuleTransformer.fromSentenceTransformer(
            new AddImplicitComputationCell(configInfo, labelInfo)::apply,
            "concretizing configuration")
            .skipping(inDefinition);
    Function1<Module, Module> resolveFreshConstants =
        d ->
            ModuleTransformer.from(
                    new ResolveFreshConstants(kem, def, kompileOptions.topCell, files)::resolve,
                    "resolving !Var variables")
                .skipping(inDefinition)
                .apply(d);
    Function1<Module, Module> addImplicitCounterCell =
        ModuleTransformer.fromSentenceTransformer(
            new AddImplicitCounterCell()::apply,
            "adding <generatedCounter> to claims if necessary");
    ModuleTransformer concretizeCells =
        ModuleTransformer.fromSentenceTransformer(
            new ConcretizeCells(configInfo, labelInfo, sortInfo, mod)::concretize,
            "concretizing configuration")
            .skipping(inDefinition);
    Function1<Module, Module> generateSortProjections =
        m ->
            ModuleTransformer.from(
                    new GenerateSortProjections(false, m)::gen, "adding sort projections")
                .apply(m);

    ModuleTransformer numberSpecSentences = numberSentences.skipping(inDefinition);

    // Up to macro expansion, the passes are applied to the definition modules too: macro expansion
    // and ResolveFunctionWithConfig read the macro rules and function rules in the form these
    // passes give them, which differs from their kompiled form (e.g. after constant folding, or
    // after the configuration argument has been added). The definition modules are then replaced
    // by their kompiled versions, and the remaining passes transform only the spec's own modules.
    return m ->
        resolveComm
            .andThen(addImplicitCounterCell)
            .andThen(resolveAnonVars)
            .andThen(numberSentences)
            .andThen(resolveSemanticCasts)
            .andThen(generateSortProjections)
            .andThen(propagateMacroToRules)
            .andThen(expandMacros)
            .andThen(restoreDefinitionModulesTransformer(def))
            .andThen(checkSimplificationRules)
            .andThen(addImplicitComputationCell)
            .andThen(resolveFreshConstants)
            .andThen(concretizeCells)
            .andThen(subsortKItem)
            .andThen(numberSpecSentences)
            .apply(m);
  }

  // check that simplification rules have a functional symbol on the LHS
  public Sentence checkSimpIsFunc(Module m, Sentence s) {
    // need to check after macro expansion
    if (s instanceof Rule && (s.att().contains(Att.SIMPLIFICATION()))) {
      KLabel kl = m.matchKLabel((Rule) s);
      Att atts = m.attributesFor().get(kl).getOrElse(Att::empty);
      if (!(atts.contains(Att.FUNCTION())
          || atts.contains(Att.FUNCTIONAL())
          || atts.contains(Att.ML_OP())))
        throw KEMException.compilerError(
            "Simplification rules expect function/functional/mlOp symbols at the top of the left"
                + " hand side term.",
            s);
    }
    return s;
  }

  /**
   * If a user guarantees that their semantics will never _dynamically_ try to rewrite an anywhere
   * rule on the Haskell backend (with the --allow-anywhere-haskell flag), but cannot prove this
   * statically, we allow them to strip out all those rules before sending the definition to the
   * backend. If this transformation is applied unsoundly (i.e. an anywhere rule would have been
   * attempted if it had not been stripped), the behaviour of the Haskell backend on that program is
   * essentially undefined.
   */
  private Module removeAnywhereRules(Module m) {
    java.util.Set<Sentence> sentences = mutable(m.localSentences());

    if (kompileOptions.backend.equals(Backends.HASKELL)
        && kompileOptions.allowAnywhereRulesHaskell) {
      java.util.Set<Sentence> filtered = new HashSet<Sentence>();

      for (var s : sentences) {
        if (s instanceof Rule && s.att().contains(Att.ANYWHERE())) {
          kem.registerCompilerWarning(
              KException.ExceptionType.REMOVED_ANYWHERE,
              "Removed anywhere rule for Haskell backend execution; this may change the behavior of"
                  + " your code.",
              s);
        } else {
          filtered.add(s);
        }
      }

      sentences = filtered;
    }
    return new Module(m.name(), m.imports(), immutable(sentences), m.att());
  }

  @Override
  public Set<Att.Key> excludedModuleTags() {
    return Collections.singleton(Att.SYMBOLIC());
  }
}
