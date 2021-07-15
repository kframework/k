// Copyright (c) 2015-2019 K Team. All Rights Reserved.
package org.kframework.kompile;

import com.google.inject.Inject;
import org.kframework.Strategy;
import org.kframework.attributes.Att;
import org.kframework.attributes.Location;
import org.kframework.attributes.Source;
import org.kframework.backend.Backends;
import org.kframework.builtin.Sorts;
import org.kframework.compile.*;
import org.kframework.compile.checks.CheckAtt;
import org.kframework.compile.checks.CheckAnonymous;
import org.kframework.compile.checks.CheckConfigurationCells;
import org.kframework.compile.checks.CheckFunctions;
import org.kframework.compile.checks.CheckHOLE;
import org.kframework.compile.checks.CheckK;
import org.kframework.compile.checks.CheckKLabels;
import org.kframework.compile.checks.CheckLabels;
import org.kframework.compile.checks.CheckRHSVariables;
import org.kframework.compile.checks.CheckRewrite;
import org.kframework.compile.checks.CheckSortTopUniqueness;
import org.kframework.compile.checks.CheckStreams;
import org.kframework.definition.*;
import org.kframework.definition.Module;
import org.kframework.definition.Production;
import org.kframework.definition.Rule;
import org.kframework.definition.Sentence;
import org.kframework.kore.KLabel;
import org.kframework.kore.Sort;
import org.kframework.parser.InputModes;
import org.kframework.parser.KRead;
import org.kframework.parser.ParserUtils;
import org.kframework.parser.inner.generator.RuleGrammarGenerator;
import org.kframework.unparser.ToJson;
import org.kframework.utils.Stopwatch;
import org.kframework.utils.StringUtil;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.errorsystem.KException;
import org.kframework.utils.errorsystem.KException.ExceptionType;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;
import org.kframework.utils.file.JarInfo;

import scala.collection.JavaConverters;
import scala.Function1;
import scala.Option;

import java.io.File;
import java.io.IOException;
import java.io.UnsupportedEncodingException;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.UnaryOperator;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.kframework.Collections.*;
import static org.kframework.definition.Constructors.*;
import static org.kframework.kore.KORE.*;
import static org.kframework.compile.ResolveHeatCoolAttribute.Mode.*;

/**
 * The new compilation pipeline. Everything is just wired together and will need clean-up once we deside on design.
 * Tracked by #1442.
 */
public class Kompile {
    public static final File BUILTIN_DIRECTORY = JarInfo.getKIncludeDir().resolve("builtin").toFile();
    public static final String REQUIRE_PRELUDE_K = "requires \"prelude.md\"\n";

    public final KompileOptions kompileOptions;
    private final FileUtil files;
    private final KExceptionManager kem;
    private final ParserUtils parser;
    private final Stopwatch sw;
    private final DefinitionParsing definitionParsing;
    java.util.Set<KEMException> errors;

    public Kompile(KompileOptions kompileOptions, FileUtil files, KExceptionManager kem, boolean cacheParses) {
        this(kompileOptions, files, kem, new Stopwatch(kompileOptions.global), cacheParses);
    }

    public Kompile(KompileOptions kompileOptions, FileUtil files, KExceptionManager kem) {
        this(kompileOptions, files, kem, true);
    }

    @Inject
    public Kompile(KompileOptions kompileOptions, FileUtil files, KExceptionManager kem, Stopwatch sw) {
        this(kompileOptions, files, kem, sw, true);
    }

    public Kompile(KompileOptions kompileOptions, FileUtil files, KExceptionManager kem, Stopwatch sw, boolean cacheParses) {
        this.kompileOptions = kompileOptions;
        this.files = files;
        this.kem = kem;
        this.errors = new HashSet<>();
        this.parser = new ParserUtils(files, kem, kem.options, kompileOptions.outerParsing);
        List<File> lookupDirectories = kompileOptions.outerParsing.includes.stream().map(files::resolveWorkingDirectory).collect(Collectors.toList());
        // these directories should be relative to the current working directory if we refer to them later after the WD has changed.
        kompileOptions.outerParsing.includes = lookupDirectories.stream().map(File::getAbsolutePath).collect(Collectors.toList());
        File cacheFile = kompileOptions.cacheFile != null
                ? files.resolveWorkingDirectory(kompileOptions.cacheFile) : files.resolveKompiled("cache.bin");
        this.definitionParsing = new DefinitionParsing(
                lookupDirectories, kompileOptions, kem, files,
                parser, cacheParses, cacheFile, sw);
        this.sw = sw;

        if (kompileOptions.backend.equals("ocaml")) {
            kem.registerCriticalWarning(ExceptionType.FUTURE_ERROR, "The OCaml backend is in the process of being deprecated (final date May 31, 2020). Please switch to the LLVM backend.");
        }
    }

    /**
     * Executes the Kompile tool. This tool accesses a
     *
     * @param definitionFile
     * @param mainModuleName
     * @param mainProgramsModuleName
     * @param programStartSymbol
     * @return
     */
    public CompiledDefinition run(File definitionFile, String mainModuleName, String mainProgramsModuleName, Function<Definition, Definition> pipeline, Set<String> excludedModuleTags) {
        files.resolveKompiled(".").mkdirs();

        if (kompileOptions.profileRules) {
            for (File f : files.resolveKompiled(".").listFiles()) {
                if (f.getName().matches("timing[0-9]+\\.log")) {
                    f.delete();
                }
            }
        }
        Definition parsedDef = parseDefinition(definitionFile, mainModuleName, mainProgramsModuleName, excludedModuleTags);

        files.saveToKompiled("parsed.txt", parsedDef.toString());
        checkDefinition(parsedDef, excludedModuleTags);
        sw.printIntermediate("Validate definition");

        Definition kompiledDefinition = pipeline.apply(parsedDef);
        files.saveToKompiled("compiled.txt", kompiledDefinition.toString());
        sw.printIntermediate("Apply compile pipeline");

        files.saveToKompiled("allRules.txt", ruleSourceMap(kompiledDefinition));

        if (kompileOptions.emitJson) {
            try {
                files.saveToKompiled("parsed.json",   new String(ToJson.apply(parsedDef),          "UTF-8"));
                files.saveToKompiled("compiled.json", new String(ToJson.apply(kompiledDefinition), "UTF-8"));
            } catch (UnsupportedEncodingException e) {
                throw KEMException.criticalError("Unsupported encoding `UTF-8` when saving JSON definition.");
            }
        }

        ConfigurationInfoFromModule configInfo = new ConfigurationInfoFromModule(kompiledDefinition.mainModule());

        boolean isKast = excludedModuleTags.contains(Att.KORE());
        Sort rootCell;
        if (isKast) {
          rootCell = configInfo.getRootCell();
        } else {
          rootCell = Sorts.GeneratedTopCell();
        }
        CompiledDefinition def = new CompiledDefinition(kompileOptions, parsedDef, kompiledDefinition, files, kem, configInfo.getDefaultCell(rootCell).klabel());

        if (kompileOptions.genBisonParser || kompileOptions.genGlrBisonParser) {
            if (def.configurationVariableDefaultSorts.containsKey("$PGM")) {
                String filename = "parser_" + def.programStartSymbol.name() + "_" + def.mainSyntaxModuleName();
                File outputFile = files.resolveKompiled(filename);
                File linkFile = files.resolveKompiled("parser_PGM");
                new KRead(kem, files, InputModes.PROGRAM).createBisonParser(def.programParsingModuleFor(def.mainSyntaxModuleName(), kem).get(), def.programStartSymbol, outputFile, kompileOptions.genGlrBisonParser, kompileOptions.bisonFile, kompileOptions.bisonStackMaxDepth);
                try {
                    linkFile.delete();
                    Files.createSymbolicLink(linkFile.toPath(), files.resolveKompiled(".").toPath().relativize(outputFile.toPath()));
                } catch (IOException e) {
                    throw KEMException.internalError("Cannot write to kompiled directory.", e);
                }
            }
            for (Production prod : iterable(kompiledDefinition.mainModule().productions())) {
                if (prod.att().contains("cell") && prod.att().contains("parser")) {
                    String att = prod.att().get("parser");
                    String[][] parts = StringUtil.splitTwoDimensionalAtt(att);
                    for (String[] part : parts) {
                        if (part.length != 2) {
                            throw KEMException.compilerError("Invalid value for parser attribute: " + att, prod);
                        }
                        String name = part[0];
                        String module = part[1];
                        Option<Module> mod = def.programParsingModuleFor(module, kem);
                        if (!mod.isDefined()) {
                            throw KEMException.compilerError("Could not find module referenced by parser attribute: " + module, prod);
                        }
                        Sort sort = def.configurationVariableDefaultSorts.getOrDefault("$" + name, Sorts.K());
                        String filename = "parser_" + sort.name() + "_" + module;
                        File outputFile = files.resolveKompiled(filename);
                        File linkFile = files.resolveKompiled("parser_" + name);
                        new KRead(kem, files, InputModes.PROGRAM).createBisonParser(mod.get(), sort, outputFile, kompileOptions.genGlrBisonParser, null, kompileOptions.bisonStackMaxDepth);
                        try {
                            linkFile.delete();
                            Files.createSymbolicLink(linkFile.toPath(), files.resolveKompiled(".").toPath().relativize(outputFile.toPath()));
                        } catch (IOException e) {
                            throw KEMException.internalError("Cannot write to kompiled directory.", e);
                        }
                    }
                }
            }
        }

        return def;
    }

    private static String ruleSourceMap(Definition def) {
        List<String> ruleLocs = new ArrayList<String>();
        for (Sentence s: JavaConverters.setAsJavaSet(def.mainModule().sentences())) {
            if (s instanceof RuleOrClaim) {
                Optional<Source>   optFile = s.att().getOptional(Source.class);
                Optional<Location> optLine = s.att().getOptional(Location.class);
                Optional<Location> optCol  = s.att().getOptional(Location.class);
                Optional<String>   optId   = s.att().getOptional(Att.UNIQUE_ID());
                if (optFile.isPresent() && optLine.isPresent() && optCol.isPresent() && optId.isPresent()) {
                    String file = optFile.get().source();
                    int line    = optLine.get().startLine();
                    int col     = optCol.get().startColumn();
                    String loc  = file + ":" + line + ":" + col;
                    String id   = optId.get();
                    ruleLocs.add(id + " " + loc);
                }
            }
        }
        return String.join("\n", ruleLocs);
    }

    public Definition parseDefinition(File definitionFile, String mainModuleName, String mainProgramsModule, Set<String> excludedModuleTags) {
        return definitionParsing.parseDefinitionAndResolveBubbles(definitionFile, mainModuleName, mainProgramsModule, excludedModuleTags);
    }

    private static Module filterStreamModules(Module input) {
        if (input.name().equals("STDIN-STREAM") || input.name().equals("STDOUT-STREAM")) {
            return Module(input.name(), Set(), Set(), input.att());
        }
        return input;
    }

    public static Definition resolveIOStreams(KExceptionManager kem,Definition d) {
        return DefinitionTransformer.from(new ResolveIOStreams(d, kem)::resolve, "resolving io streams")
                .andThen(DefinitionTransformer.from(Kompile::filterStreamModules, "resolving io streams"))
                .apply(d);
    }

    private static Module excludeModulesByTag(Set<String> excludedModuleTags, Module mod) {
        Set<Module> newImports = stream(mod.imports()).filter(_import -> excludedModuleTags.stream().noneMatch(tag -> _import.att().contains(tag))).collect(Collectors.toSet());
        return Module(mod.name(), immutable(newImports), mod.localSentences(), mod.att());
    }

    public static Function1<Definition, Definition> excludeModulesByTag(Set<String> excludedModuleTags) {
        DefinitionTransformer dt = DefinitionTransformer.from(mod -> excludeModulesByTag(excludedModuleTags, mod), "remove modules based on attributes");
        return dt.andThen(d -> Definition(d.mainModule(), immutable(stream(d.entryModules()).filter(mod -> excludedModuleTags.stream().noneMatch(tag -> mod.att().contains(tag))).collect(Collectors.toSet())), d.att()));
    }

    public static Function<Definition, Definition> defaultSteps(KompileOptions kompileOptions, KExceptionManager kem, FileUtil files) {
        Function1<Definition, Definition> resolveStrict = d -> DefinitionTransformer.from(new ResolveStrict(kompileOptions, d)::resolve, "resolving strict and seqstrict attributes").apply(d);
        DefinitionTransformer resolveHeatCoolAttribute = DefinitionTransformer.fromSentenceTransformer(new ResolveHeatCoolAttribute(new HashSet<>(kompileOptions.transition), EnumSet.of(HEAT_RESULT, COOL_RESULT_CONDITION, COOL_RESULT_INJECTION))::resolve, "resolving heat and cool attributes");
        DefinitionTransformer resolveAnonVars = DefinitionTransformer.fromSentenceTransformer(new ResolveAnonVar()::resolve, "resolving \"_\" vars");
        DefinitionTransformer guardOrs = DefinitionTransformer.fromSentenceTransformer(new GuardOrPatterns(false)::resolve, "resolving or patterns");
        DefinitionTransformer resolveSemanticCasts =
                DefinitionTransformer.fromSentenceTransformer(new ResolveSemanticCasts(kompileOptions.backend.equals(Backends.JAVA))::resolve, "resolving semantic casts");
        DefinitionTransformer resolveFun = DefinitionTransformer.from(new ResolveFun(false)::resolve, "resolving #fun");
        Function1<Definition, Definition> resolveFunctionWithConfig = d -> DefinitionTransformer.fromSentenceTransformer(new ResolveFunctionWithConfig(d, false)::resolve, "resolving functions with config context").apply(d);
        DefinitionTransformer generateSortPredicateSyntax = DefinitionTransformer.from(new GenerateSortPredicateSyntax()::gen, "adding sort predicate productions");
        DefinitionTransformer generateSortProjections = DefinitionTransformer.from(new GenerateSortProjections(kompileOptions.coverage)::gen, "adding sort projections");
        DefinitionTransformer subsortKItem = DefinitionTransformer.from(Kompile::subsortKItem, "subsort all sorts to KItem");
        Function1<Definition, Definition> expandMacros = d -> {
          ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(d, false);
          return DefinitionTransformer.fromSentenceTransformer((m, s) -> new ExpandMacros(transformer, m, files, kem, kompileOptions, false).expand(s), "expand macros").apply(d);
        };
        GenerateCoverage cov = new GenerateCoverage(kompileOptions.coverage, files);
        Function1<Definition, Definition> genCoverage = d -> DefinitionTransformer.fromRuleBodyTransformerWithRule((r, body) -> cov.gen(r, body, d.mainModule()), "generate coverage instrumentation").apply(d);
        DefinitionTransformer numberSentences = DefinitionTransformer.fromSentenceTransformer(NumberSentences::number, "number sentences uniquely");
        Function1<Definition, Definition> resolveConfigVar = d -> DefinitionTransformer.fromSentenceTransformer(new ResolveFunctionWithConfig(d, false)::resolveConfigVar, "Adding configuration variable to lhs").apply(d);
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
                .andThen(expandMacros)
                .andThen(guardOrs)
                .andThen(Kompile::resolveFreshConstants)
                .andThen(generateSortPredicateSyntax)
                .andThen(generateSortProjections)
                .andThen(AddImplicitComputationCell::transformDefinition)
                .andThen(d -> new Strategy().addStrategyCellToRulesTransformer(d).apply(d))
                .andThen(d -> ConcretizeCells.transformDefinition(d, false))
                .andThen(genCoverage)
                .andThen(Kompile::addSemanticsModule)
                .andThen(resolveConfigVar)
                .apply(def);
    }

    public static Sentence removePolyKLabels(Sentence s) {
      if (s instanceof Production) {
        Production p = (Production)s;
        if (!p.isSyntacticSubsort() && p.params().nonEmpty()) {
            p = p.substitute(immutable(Collections.nCopies(p.params().size(), Sorts.K())));
            return Production(p.klabel().map(KLabel::head), Seq(), p.sort(), p.items(), p.att());
        }
      }
      return s;
    }

    public static Module subsortKItem(Module module) {
        java.util.Set<Sentence> prods = new HashSet<>();
        for (Sort srt : iterable(module.allSorts())) {
            if (!RuleGrammarGenerator.isParserSort(srt)) {
                // KItem ::= Sort
                Production prod = Production(Seq(), Sorts.KItem(), Seq(NonTerminal(srt)), Att());
                if (!module.sentences().contains(prod)) {
                    prods.add(prod);
                }
            }
        }
        if (prods.isEmpty()) {
            return module;
        } else {
            return Module(module.name(), module.imports(), Stream.concat(stream(module.localSentences()), prods.stream())
                    .collect(org.kframework.Collections.toSet()), module.att());
        }
    }

    public Rule parseAndCompileRule(CompiledDefinition compiledDef, String contents, Source source, Optional<Rule> parsedRule) {
        Rule parsed = parsedRule.orElse(parseRule(compiledDef, contents, source));
        return compileRule(compiledDef.kompiledDefinition, parsed);
    }

    public Rule parseRule(CompiledDefinition compiledDef, String contents, Source source) {
        return definitionParsing.parseRule(compiledDef, contents, source);
    }

    private void checkDefinition(Definition parsedDef, Set<String> excludedModuleTags) {
        scala.collection.Set<Module> modules = parsedDef.modules();
        Module mainModule = parsedDef.mainModule();
        Option<Module> kModule = parsedDef.getModule("K");
        definitionChecks(stream(modules).collect(Collectors.toSet()));
        structuralChecks(modules, mainModule, kModule, excludedModuleTags);
    }

    // checks that are not verified in the prover
    public void definitionChecks(Set<Module> modules) {
        modules.forEach(m -> stream(m.localSentences()).forEach(s -> {
            // Check that the `claim` keyword is not used in the definition.
            if (s instanceof Claim)
                errors.add(KEMException.compilerError("Claims are not allowed in the definition.", s));
        }));
    }

    // Extra checks just for the prover specification.
    public Module proverChecks(Module specModule, Module mainDefModule) {
        // check rogue syntax in spec module
        Set<Sentence> toCheck = mutable(specModule.sentences().$minus$minus(mainDefModule.sentences()));
        for (Sentence s : toCheck)
            if (s.isSyntax())
                kem.registerCompilerWarning(ExceptionType.FUTURE_ERROR, errors,
                        "Found syntax declaration in proof module. This will not be visible from the main module.", s);

        // TODO: remove once transition to claim rules is done
        // transform rules into claims if
        // - they are in the spec modules but not in the definition modules
        // - they don't contain the `simplification` attribute
        ModuleTransformer mt = ModuleTransformer.fromSentenceTransformer((m, s) -> {
            if (m.name().equals(mainDefModule.name()) || mainDefModule.importedModuleNames().contains(m.name()))
                return s;
            if (s instanceof Rule && !s.att().contains(Att.SIMPLIFICATION())) {
                kem.registerCompilerWarning(KException.ExceptionType.FUTURE_ERROR, errors, "Deprecated: use claim instead of rule to specify proof objectives.", s);
                return new Claim(((Rule) s).body(), ((Rule) s).requires(), ((Rule) s).ensures(), s.att());
            }
            return s;
        }, "rules to claim");
        return mt.apply(specModule);
    }

    public void structuralChecks(scala.collection.Set<Module> modules, Module mainModule, Option<Module> kModule, Set<String> excludedModuleTags) {
        boolean isSymbolic = excludedModuleTags.contains(Att.CONCRETE());
        boolean isKast = excludedModuleTags.contains(Att.KORE());
        CheckRHSVariables checkRHSVariables = new CheckRHSVariables(errors, !isSymbolic);
        stream(modules).forEach(m -> stream(m.localSentences()).forEach(checkRHSVariables::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckAtt(errors, mainModule, isSymbolic && isKast)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckConfigurationCells(errors, m, isSymbolic && isKast)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckSortTopUniqueness(errors, m)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckStreams(errors, m)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckRewrite(errors, m)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckHOLE(errors, m)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckK(errors)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(
              new CheckFunctions(errors, m)::check));

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckAnonymous(errors, m, kem)::check));

        Set<String> moduleNames = new HashSet<>();
        stream(modules).forEach(m -> {
            if (moduleNames.contains(m.name())) {
                errors.add(KEMException.compilerError("Found multiple modules with name: " + m.name()));
            }
            moduleNames.add(m.name());
        });

        CheckKLabels checkKLabels = new CheckKLabels(errors, kem, kompileOptions.isKore(), files);
        Set<String> checkedModules = new HashSet<>();
        // only check imported modules because otherwise we might have false positives
        Consumer<Module> checkModuleKLabels = m -> {
            if (!checkedModules.contains(m.name())) {
                stream(m.localSentences()).forEach(s -> checkKLabels.check(s, m));
            }
            checkedModules.add(m.name());
        };

        if (kModule.nonEmpty()) {
            stream(kModule.get().importedModules()).forEach(checkModuleKLabels);
            checkModuleKLabels.accept(kModule.get());
        }
        stream(mainModule.importedModules()).forEach(checkModuleKLabels);
        checkModuleKLabels.accept(mainModule);
        checkKLabels.check(mainModule);

        stream(modules).forEach(m -> stream(m.localSentences()).forEach(new CheckLabels(errors)::check));

        if (!errors.isEmpty()) {
            kem.addAllKException(errors.stream().map(e -> e.exception).collect(Collectors.toList()));
            throw KEMException.compilerError("Had " + errors.size() + " structural errors.");
        }
    }

    public static Definition addSemanticsModule(Definition d) {
        java.util.Set<Module> allModules = mutable(d.modules());

        Module languageParsingModule = Constructors.Module("LANGUAGE-PARSING",
                Set(d.mainModule(),
                        d.getModule(d.att().get(Att.SYNTAX_MODULE())).get(),
                        d.getModule("K-TERM").get(),
                        d.getModule(RuleGrammarGenerator.ID_PROGRAM_PARSING).get()), Set(), Att());
        allModules.add(languageParsingModule);
        return Constructors.Definition(d.mainModule(), immutable(allModules), d.att());
    }

    public static Definition resolveFreshConstants(Definition input) {
        return DefinitionTransformer.from(m -> GeneratedTopFormat.resolve(new ResolveFreshConstants(input, false, null).resolve(m)), "resolving !Var variables")
                .apply(input);
    }

    public Rule compileRule(Definition compiledDef, Rule parsedRule) {
        return (Rule) UnaryOperator.<Sentence>identity()
                .andThen(new ResolveAnonVar()::resolve)
                .andThen(new ResolveSemanticCasts(kompileOptions.backend.equals(Backends.JAVA))::resolve)
                .andThen(s -> concretizeSentence(s, compiledDef))
                .apply(parsedRule);
    }

    public Set<Module> parseModules(CompiledDefinition definition, String mainModule, String entryPointModule, File definitionFile, Set<String> excludeModules) {
        return parseModules(definition, mainModule, entryPointModule, definitionFile, excludeModules, false);
    }

    public Set<Module> parseModules(CompiledDefinition definition, String mainModule, String entryPointModule, File definitionFile, Set<String> excludeModules, boolean readOnlyCache) {
        Set<Module> modules = definitionParsing.parseModules(definition, mainModule, entryPointModule, definitionFile, excludeModules, readOnlyCache);
        int totalBubbles = definitionParsing.parsedBubbles.get() + definitionParsing.cachedBubbles.get();
        sw.printIntermediate("Parse spec modules [" + definitionParsing.parsedBubbles.get() + "/" + totalBubbles + " rules]");
        return modules;
    }

    private Sentence concretizeSentence(Sentence s, Definition input) {
        ConfigurationInfoFromModule configInfo = new ConfigurationInfoFromModule(input.mainModule());
        LabelInfo labelInfo = new LabelInfoFromModule(input.mainModule());
        SortInfo sortInfo = SortInfo.fromModule(input.mainModule());
        return new ConcretizeCells(configInfo, labelInfo, sortInfo, input.mainModule(), kompileOptions.isKore()).concretize(input.mainModule(), s);
    }
}
