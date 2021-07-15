// Copyright (c) 2018-2019 K Team. All Rights Reserved.
package org.kframework.backend.kore;

import com.google.inject.Inject;
import org.apache.commons.io.FilenameUtils;
import org.kframework.compile.AbstractBackend;
import org.kframework.compile.AddCoolLikeAtt;
import org.kframework.compile.AddImplicitComputationCell;
import org.kframework.compile.AddSortInjections;
import org.kframework.compile.Backend;
import org.kframework.compile.ConcretizeCells;
import org.kframework.compile.ConfigurationInfoFromModule;
import org.kframework.compile.ConstantFolding;
import org.kframework.compile.ExpandMacros;
import org.kframework.compile.GenerateCoverage;
import org.kframework.compile.GeneratedTopFormat;
import org.kframework.compile.GenerateSortPredicateRules;
import org.kframework.compile.GenerateSortPredicateSyntax;
import org.kframework.compile.GenerateSortProjections;
import org.kframework.compile.GuardOrPatterns;
import org.kframework.compile.LabelInfo;
import org.kframework.compile.LabelInfoFromModule;
import org.kframework.compile.MinimizeTermConstruction;
import org.kframework.compile.NumberSentences;
import org.kframework.compile.ResolveAnonVar;
import org.kframework.compile.ResolveContexts;
import org.kframework.compile.ResolveFreshConstants;
import org.kframework.compile.ResolveFun;
import org.kframework.compile.ResolveFunctionWithConfig;
import org.kframework.compile.ResolveHeatCoolAttribute;
import org.kframework.compile.ResolveSemanticCasts;
import org.kframework.compile.ResolveStrict;
import org.kframework.compile.SortInfo;
import org.kframework.definition.Definition;
import org.kframework.definition.DefinitionTransformer;
import org.kframework.definition.Module;
import org.kframework.definition.ModuleTransformer;
import org.kframework.kompile.CompiledDefinition;
import org.kframework.kompile.Kompile;
import org.kframework.kompile.KompileOptions;
import org.kframework.main.Tool;
import org.kframework.Strategy;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;

import scala.Function1;

import java.io.File;
import java.util.Collections;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.Set;
import java.util.function.Function;

import static org.kframework.compile.ResolveHeatCoolAttribute.Mode.*;

public class KoreBackend extends AbstractBackend {

    private final KompileOptions kompileOptions;
    protected final FileUtil files;
    private final KExceptionManager kem;
    private final EnumSet<ResolveHeatCoolAttribute.Mode> heatCoolConditions;
    private final boolean heatCoolEquations;
    private final Tool tool;

    @Inject
    public KoreBackend(
            KompileOptions kompileOptions,
            FileUtil files,
            KExceptionManager kem,
            Tool tool) {
        this(kompileOptions, files, kem, kompileOptions.optimize2 || kompileOptions.optimize3 ? EnumSet.of(HEAT_RESULT) : EnumSet.of(HEAT_RESULT, COOL_RESULT_CONDITION), false, tool);
    }

    public KoreBackend(KompileOptions kompileOptions, FileUtil files, KExceptionManager kem, EnumSet<ResolveHeatCoolAttribute.Mode> heatCoolConditions, boolean heatCoolEquations, Tool tool) {
        this.kompileOptions = kompileOptions;
        this.files = files;
        this.kem = kem;
        this.heatCoolConditions = heatCoolConditions;
        this.heatCoolEquations = heatCoolEquations;
        this.tool = tool;
    }

    @Override
    public void accept(Backend.Holder h) {
        CompiledDefinition def = h.def;
        String kore = getKompiledString(def);
        File defFile = kompileOptions.outerParsing.mainDefinitionFile(files);
        String name = defFile.getName();
        String basename = FilenameUtils.removeExtension(name);
        files.saveToDefinitionDirectory(basename + ".kore", kore);
    }

    protected String getKompiledString(CompiledDefinition def) {
        Module mainModule = getKompiledModule(def.kompiledDefinition.mainModule());
        ModuleToKORE converter = new ModuleToKORE(mainModule, def.topCellInitializer, def.kompileOptions);
        return getKompiledString(converter, files, heatCoolEquations, tool);
    }

    public static String getKompiledString(ModuleToKORE converter, FileUtil files, boolean heatCoolEquations, Tool t) {
        StringBuilder sb = new StringBuilder();
        String kompiledString = getKompiledStringAndWriteSyntaxMacros(converter, files, heatCoolEquations, sb, t);
        return kompiledString;
    }

    public static String getKompiledStringAndWriteSyntaxMacros(ModuleToKORE converter, FileUtil files, boolean heatCoolEq, StringBuilder sb, Tool t) {
        StringBuilder semantics = new StringBuilder();
        StringBuilder syntax    = new StringBuilder();
        StringBuilder macros    = new StringBuilder();
        String prelude = files.loadFromKIncludeDir("kore/prelude.kore");
        converter.convert(heatCoolEq, prelude, semantics, syntax, macros);
        if (t == Tool.KOMPILE) {
            files.saveToKompiled("syntaxDefinition.kore", syntax.toString());
            files.saveToKompiled("macros.kore", macros.toString());
        }
        return semantics.toString();
    }

    public static Module getKompiledModule(Module mainModule) {
        mainModule = new GenerateSortPredicateRules(true).gen(mainModule);
        mainModule = ModuleTransformer.fromSentenceTransformer(new AddSortInjections(mainModule)::addInjections, "Add sort injections").apply(mainModule);
        mainModule = ModuleTransformer.fromSentenceTransformer(new MinimizeTermConstruction(mainModule)::resolve, "Minimize term construction").apply(mainModule);
        return mainModule;
    }

    @Override
    public Function<Definition, Definition> steps() {
        Function1<Definition, Definition> resolveStrict = d -> DefinitionTransformer.from(new ResolveStrict(kompileOptions, d)::resolve, "resolving strict and seqstrict attributes").apply(d);
        DefinitionTransformer resolveHeatCoolAttribute = DefinitionTransformer.fromSentenceTransformer(new ResolveHeatCoolAttribute(new HashSet<>(kompileOptions.transition), heatCoolConditions)::resolve, "resolving heat and cool attributes");
        DefinitionTransformer resolveAnonVars = DefinitionTransformer.fromSentenceTransformer(new ResolveAnonVar()::resolve, "resolving \"_\" vars");
        DefinitionTransformer guardOrs = DefinitionTransformer.fromSentenceTransformer(new GuardOrPatterns(true)::resolve, "resolving or patterns");
        DefinitionTransformer resolveSemanticCasts =
                DefinitionTransformer.fromSentenceTransformer(new ResolveSemanticCasts(true)::resolve, "resolving semantic casts");
        DefinitionTransformer resolveFun = DefinitionTransformer.from(new ResolveFun(true)::resolve, "resolving #fun");
        Function1<Definition, Definition> resolveFunctionWithConfig = d -> DefinitionTransformer.fromSentenceTransformer(new ResolveFunctionWithConfig(d, true)::resolve, "resolving functions with config context").apply(d);
        DefinitionTransformer generateSortPredicateSyntax = DefinitionTransformer.from(new GenerateSortPredicateSyntax()::gen, "adding sort predicate productions");
        DefinitionTransformer generateSortProjections = DefinitionTransformer.from(new GenerateSortProjections(kompileOptions.coverage)::gen, "adding sort projections");
        DefinitionTransformer subsortKItem = DefinitionTransformer.from(Kompile::subsortKItem, "subsort all sorts to KItem");
        Function1<Definition, Definition> addCoolLikeAtt = d -> DefinitionTransformer.fromSentenceTransformer(new AddCoolLikeAtt(d.mainModule())::add, "add cool-like attribute").apply(d);
        Function1<Definition, Definition> expandMacros = d -> {
          ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(d, true);
          return DefinitionTransformer.fromSentenceTransformer((m, s) -> new ExpandMacros(transformer, m, files, kem, kompileOptions, false).expand(s), "expand macros").apply(d);
        };
        DefinitionTransformer constantFolding = DefinitionTransformer.fromSentenceTransformer(new ConstantFolding()::fold, "constant expression folding");
        Function1<Definition, Definition> resolveFreshConstants = d -> DefinitionTransformer.from(m -> GeneratedTopFormat.resolve(new ResolveFreshConstants(d, true, kompileOptions.topCell).resolve(m)), "resolving !Var variables").apply(d);
        GenerateCoverage cov = new GenerateCoverage(kompileOptions.coverage, files);
        Function1<Definition, Definition> genCoverage = d -> DefinitionTransformer.fromRuleBodyTransformerWithRule((r, body) -> cov.gen(r, body, d.mainModule()), "generate coverage instrumentation").apply(d);
        DefinitionTransformer numberSentences = DefinitionTransformer.fromSentenceTransformer(NumberSentences::number, "number sentences uniquely");
        Function1<Definition, Definition> resolveConfigVar = d -> DefinitionTransformer.fromSentenceTransformer(new ResolveFunctionWithConfig(d, true)::resolveConfigVar, "Adding configuration variable to lhs").apply(d);
        Function1<Definition, Definition> resolveIO = (d -> Kompile.resolveIOStreams(kem, d));

        return def -> resolveIO
                .andThen(resolveFun)
                .andThen(resolveFunctionWithConfig)
                .andThen(resolveStrict)
                .andThen(resolveAnonVars)
                .andThen(d -> new ResolveContexts(kompileOptions).resolve(d))
                .andThen(numberSentences)
                .andThen(resolveHeatCoolAttribute)
                .andThen(resolveSemanticCasts)
                .andThen(subsortKItem)
                .andThen(generateSortPredicateSyntax)
                .andThen(generateSortProjections)
                .andThen(constantFolding)
                .andThen(expandMacros)
                .andThen(guardOrs)
                .andThen(AddImplicitComputationCell::transformDefinition)
                .andThen(resolveFreshConstants)
                .andThen(generateSortPredicateSyntax)
                .andThen(generateSortProjections)
                .andThen(subsortKItem)
                .andThen(d -> new Strategy().addStrategyCellToRulesTransformer(d).apply(d))
                .andThen(d -> Strategy.addStrategyRuleToMainModule(def.mainModule().name()).apply(d))
                .andThen(d -> ConcretizeCells.transformDefinition(d, true))
                .andThen(genCoverage)
                .andThen(Kompile::addSemanticsModule)
                .andThen(resolveConfigVar)
                .andThen(addCoolLikeAtt)
                .apply(def);
    }

    @Override
    public Function<Module, Module> specificationSteps(Definition def) {
        Module mod = def.mainModule();
        ConfigurationInfoFromModule configInfo = new ConfigurationInfoFromModule(mod);
        LabelInfo labelInfo = new LabelInfoFromModule(mod);
        SortInfo sortInfo = SortInfo.fromModule(mod);
        ModuleTransformer resolveAnonVars = ModuleTransformer.fromSentenceTransformer(
                new ResolveAnonVar()::resolve,
                "resolving \"_\" vars");
        ModuleTransformer resolveSemanticCasts = ModuleTransformer.fromSentenceTransformer(
                new ResolveSemanticCasts(true)::resolve,
                "resolving semantic casts");
        Function1<Module, Module> expandMacros = m -> {
          ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(m, true);
          return ModuleTransformer.fromSentenceTransformer((m2, s) -> new ExpandMacros(transformer, m2, files, kem, kompileOptions, false).expand(s), "expand macros").apply(m);
        };
        ModuleTransformer subsortKItem = ModuleTransformer.from(Kompile::subsortKItem, "subsort all sorts to KItem");
        ModuleTransformer addImplicitComputationCell = ModuleTransformer.fromSentenceTransformer(
                new AddImplicitComputationCell(configInfo, labelInfo)::apply,
                "concretizing configuration");
        Function1<Module, Module> resolveFreshConstants = d -> ModuleTransformer.from(new ResolveFreshConstants(def, true, kompileOptions.topCell)::resolve, "resolving !Var variables").apply(d);
        ModuleTransformer concretizeCells = ModuleTransformer.fromSentenceTransformer(
                new ConcretizeCells(configInfo, labelInfo, sortInfo, mod, true)::concretize,
                "concretizing configuration");
        ModuleTransformer generateSortProjections = ModuleTransformer.from(new GenerateSortProjections(false)::gen, "adding sort projections");

        return m -> resolveAnonVars
                .andThen(resolveSemanticCasts)
                .andThen(generateSortProjections)
                .andThen(expandMacros)
                .andThen(addImplicitComputationCell)
                .andThen(resolveFreshConstants)
                .andThen(concretizeCells)
                .andThen(subsortKItem)
                .andThen(restoreDefinitionModulesTransformer(def))
                .apply(m);
    }

    @Override
    public Set<String> excludedModuleTags() {
        return Collections.singleton("symbolic");
    }
}
