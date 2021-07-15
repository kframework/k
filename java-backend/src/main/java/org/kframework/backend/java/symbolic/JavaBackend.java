// Copyright (c) 2015-2019 K Team. All Rights Reserved.
package org.kframework.backend.java.symbolic;

import com.google.inject.Inject;
import org.kframework.AddConfigurationRecoveryFlags;
import org.kframework.attributes.Att;
import org.kframework.backend.Backends;
import org.kframework.builtin.KLabels;
import org.kframework.builtin.Sorts;
import org.kframework.compile.*;
import org.kframework.definition.*;
import org.kframework.definition.Module;
import org.kframework.kompile.Kompile;
import org.kframework.kompile.KompileOptions;
import org.kframework.kore.ADT;
import org.kframework.kore.KLabel;
import org.kframework.kore.KSequence;
import org.kframework.kore.VisitK;
import org.kframework.kore.K;
import org.kframework.kore.KApply;
import org.kframework.kore.KORE;
import org.kframework.kore.KVariable;
import org.kframework.kore.SortedADT;
import org.kframework.backend.java.compile.ConvertDataStructureToLookup;
import org.kframework.kore.TransformK;
import org.kframework.main.GlobalOptions;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;

import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.function.BiFunction;
import java.util.function.Function;

public class JavaBackend extends AbstractBackend {

    public static final String MAIN_AUTOMATON = "mainAutomaton";
    public static final String SPEC_AUTOMATON = "specAutomaton";

    private final KExceptionManager kem;
    private final FileUtil files;
    private final GlobalOptions globalOptions;
    private final KompileOptions kompileOptions;

    /**
     * In the Java backend, {@link KSequence}s are treated like {@link KApply}s, so tranform them.
     */
    public static K convertKSeqToKApply(K ruleBody) {
        return new TransformK() {
            public K apply(KSequence kseq) {
                return super.apply(((ADT.KSequence) kseq).kApply());
            }
        }.apply(ruleBody);
    }

    public static Sentence convertListItemToNonFunction(Module mod, Sentence sentence) {
        if (!(sentence instanceof Production)) {
            return sentence;
        }
        Production prod = (Production)sentence;
        if (prod.klabel().isDefined() && KLabels.ListItem.equals(prod.klabel().get())) {
            return prod.withAtt(prod.att().remove("function"));
        }
        return prod;
    }

    @Override
    public void accept(Backend.Holder h) {
    }

    @Inject
    public JavaBackend(KExceptionManager kem, FileUtil files, GlobalOptions globalOptions, KompileOptions kompileOptions) {
        this.kem = kem;
        this.files = files;
        this.globalOptions = globalOptions;
        this.kompileOptions = kompileOptions;
    }

    /**
     * @param the generic {@link Kompile}
     * @return the special steps for the Java backend
     */
    @Override
    public Function<Definition, Definition> steps() {
        DefinitionTransformer convertDataStructureToLookup = DefinitionTransformer.fromSentenceTransformer((m, s) -> new ConvertDataStructureToLookup(m, false).convert(s), "convert data structures to lookups");

        return d -> DefinitionTransformer.fromRuleBodyTransformer(RewriteToTop::bubbleRewriteToTopInsideCells, "bubble out rewrites below cells")
                .andThen(DefinitionTransformer.fromSentenceTransformer(JavaBackend::convertListItemToNonFunction, "remove function attribute from ListItem production"))
                .andThen(DefinitionTransformer.fromSentenceTransformer(new NormalizeAssoc(KORE.c()), "normalize assoc"))
                .andThen(DefinitionTransformer.from(AddBottomSortForListsWithIdenticalLabels.singleton(), "add bottom sorts for lists"))
                .andThen(DefinitionTransformer.from(new GenerateSortProjections(kompileOptions.coverage)::gen, "adding sort projections"))
                .andThen(d2 -> {
                  ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(d2, false);
                  return DefinitionTransformer.fromSentenceTransformer((m, s) -> new ExpandMacros(transformer, m, files, kem, kompileOptions, false).expand(s), "expand macros").apply(d2);
                })
                .andThen(DefinitionTransformer.fromSentenceTransformer(new NormalizeAssoc(KORE.c()), "normalize assoc"))
                .andThen(convertDataStructureToLookup)
                .andThen(DefinitionTransformer.fromRuleBodyTransformer(JavaBackend::ADTKVariableToSortedVariable, "ADT.KVariable to SortedVariable"))
                .andThen(DefinitionTransformer.fromRuleBodyTransformer(JavaBackend::convertKSeqToKApply, "kseq to kapply"))
                .andThen(DefinitionTransformer.fromRuleBodyTransformer(NormalizeKSeq.self()::apply, "normalize kseq"))
                .andThen(JavaBackend::markRegularRules)
                .andThen(DefinitionTransformer.fromSentenceTransformer(new AddConfigurationRecoveryFlags(), "add refers_THIS_CONFIGURATION_marker"))
                .andThen(DefinitionTransformer.fromSentenceTransformer(JavaBackend::markSingleVariables, "mark single variables"))
                .andThen(DefinitionTransformer.from(new AssocCommToAssoc(), "convert AC matching to A matching"))
                .andThen(DefinitionTransformer.from(new MergeRules(MAIN_AUTOMATON, Att.TOP_RULE()), "merge regular rules into one rule with or clauses"))
                .apply(Kompile.defaultSteps(kompileOptions, kem, files).apply(d));
             // .andThen(KoreToMiniToKore::apply) // for serialization/deserialization test
    }

    @Override
    public Function<Module, Module> specificationSteps(Definition def) {
        BiFunction<Module, K, K> convertCellCollections = (Module m, K k) -> new ConvertDataStructureToLookup(m, false).convert(k);

        ModuleTransformer convertDataStructureToLookup = ModuleTransformer.fromSentenceTransformer((m, s) -> new ConvertDataStructureToLookup(m, false).convert(s), "convert data structures to lookups");

        //Commented steps are (possibly) required for spec automaton generation.
        return m -> ModuleTransformer.fromSentenceTransformer(Kompile::removePolyKLabels, "remove poly klabels")
                .andThen(ModuleTransformer.fromSentenceTransformer(new ResolveAnonVar()::resolve, "resolve anonymous varaibles"))
                .andThen(ModuleTransformer.fromSentenceTransformer(s -> new ResolveSemanticCasts(kompileOptions.backend.equals(Backends.JAVA)).resolve(s), "resolve semantic casts"))
                //.andThen(ModuleTransformer.fromSentenceTransformer(new NormalizeAssoc(KORE.c()), "normalize assoc"))
                .andThen(AddBottomSortForListsWithIdenticalLabels.singleton())
                .andThen(ModuleTransformer.from(new GenerateSortProjections(false)::gen, "adding sort projections"))
                .andThen(m2 -> {
                  ResolveFunctionWithConfig transformer = new ResolveFunctionWithConfig(m2, false);
                  return ModuleTransformer.fromSentenceTransformer((mod, s) -> new ExpandMacros(transformer, mod, files, kem, kompileOptions, false).expand(s), "expand macros").apply(m2);
                })
                .andThen(AddImplicitComputationCell::transformModule)
                .andThen(d -> ConcretizeCells.transformModule(d, false))
                .andThen(ModuleTransformer.fromRuleBodyTransformer(RewriteToTop::bubbleRewriteToTopInsideCells, "bubble out rewrites below cells"))
                //.andThen(ModuleTransformer.fromSentenceTransformer(new NormalizeAssoc(KORE.c()), "normalize assoc"))

                //A subset of convertDataStructureToLookup. Does not simplify _Map_ terms.
                .andThen(ModuleTransformer.fromKTransformerWithModuleInfo(convertCellCollections::apply, "convert cell to the underlying collections"))
                //Point where implementation of spec automaton got stuck.
                //Candidate for spec automaton generation. Simplifies _Map_, but introduces map lookup side conditions that cannot be evaluated in current term.
                //thus we possibly need lookups for automaton building, but not for spec rules to be proved/applied.
                //.andThen(convertDataStructureToLookup)

                .andThen(ModuleTransformer.fromRuleBodyTransformer(JavaBackend::ADTKVariableToSortedVariable, "ADT.KVariable to SortedVariable"))
                .andThen(ModuleTransformer.fromRuleBodyTransformer(JavaBackend::convertKSeqToKApply, "kseq to kapply"))
                .andThen(ModuleTransformer.fromRuleBodyTransformer(NormalizeKSeq.self(), "normalize kseq"))
                // TODO: remove marking step?
                .andThen(JavaBackend::markSpecRules)
                .andThen(ModuleTransformer.fromSentenceTransformer(new AddConfigurationRecoveryFlags()::apply, "add refers_THIS_CONFIGURATION_marker"))
                //.andThen(ModuleTransformer.fromSentenceTransformer(JavaBackend::markSingleVariables, "mark single variables"))
                //.andThen(ModuleTransformer.from(new AssocCommToAssoc()::apply, "convert AC matching to A matching"))
                .andThen(restoreDefinitionModulesTransformer(def))
                //.andThen(ModuleTransformer.from(new MergeRules(SPEC_AUTOMATON, Att.SPECIFICATION())::apply, "merge spec rules into one rule with or clauses"))
                .apply(m);
    }

    private static Sentence markRegularRules(Definition d, ConfigurationInfoFromModule configInfo, Sentence s, String att) {
        if (s instanceof org.kframework.definition.Rule) {
            org.kframework.definition.Rule r = (org.kframework.definition.Rule) s;
            if (r.body() instanceof KApply) {
                KLabel klabel = ((KApply) r.body()).klabel();
                if (d.mainModule().sortFor().contains(klabel) //is false for rules in specification modules not part of semantics
                        && d.mainModule().sortFor().apply(klabel).equals(configInfo.getRootCell())) {
                    return Rule.apply(r.body(), r.requires(), r.ensures(), r.att().add(att));
                }
            }
        }
        return s;
    }

    private static Module markSpecRules(Module mod) {
        return ModuleTransformer.fromSentenceTransformer(s -> {
                    if (s instanceof Claim) {
                        Claim c = (Claim) s;
                        return Claim.apply(c.body(), c.requires(), c.ensures(), c.att().add(Att.SPECIFICATION()));
                    }
                    return s;
                }, "mark specification rules").apply(mod);
    }

        /**
         * Put a marker on the "regular" (i.e. non function/macro/etc.) rules that we can use later.
         */
    private static Definition markRegularRules(Definition d) {
        ConfigurationInfoFromModule configInfo = new ConfigurationInfoFromModule(d.mainModule());
        return DefinitionTransformer.fromSentenceTransformer((mod, s) -> markRegularRules(d, configInfo, s, Att.TOP_RULE()), "mark regular rules").apply(d);
    }

    /**
     * The Java backend expects sorted variables, so transform them to the sorted flavor.
     */
    public static K ADTKVariableToSortedVariable(K ruleBody) {
        return new TransformK() {
            public K apply(KVariable kvar) {
                return new SortedADT.SortedKVariable(kvar.name(), kvar.att());
            }
        }.apply(ruleBody);
    }

    /**
     * Replace variables which only appear once in the pattern and have no side condition on them (including no sorting),
     * with a special marker called THE_VARIABLE which the backend uses for special speed optimisations.
     */
    private static Sentence markSingleVariables(Sentence s) {
        if (s instanceof RuleOrClaim) {
            RuleOrClaim r = (RuleOrClaim) s;

            if (!r.att().contains(Att.TOP_RULE()))
                return r;

            Map<KVariable, Integer> varCount = new HashMap<>();
            VisitK markerVisitor = new VisitK() {
                public void apply(KVariable kvar) {
                    varCount.put(kvar, varCount.getOrDefault(kvar, 0) + 1);
                }
            };
            markerVisitor.apply(r.body());
            markerVisitor.apply(r.requires());
            markerVisitor.apply(r.ensures());

            TransformK markerAdder = new TransformK() {
                public K apply(KVariable kvar) {
                    if (kvar instanceof SortedADT.SortedKVariable && ((SortedADT.SortedKVariable) kvar).sort().equals(Sorts.K()) && varCount.get(kvar) == 1
                            && !kvar.name().equals(KLabels.THIS_CONFIGURATION)) {
                        return new SortedADT.SortedKVariable("THE_VARIABLE", Att.empty());
                    } else {
                        return kvar;
                    }
                }
            };
            return ((RuleOrClaim) s).newInstance(markerAdder.apply(r.body()), markerAdder.apply(r.requires()), markerAdder.apply(r.ensures()), r.att());
        } else {
            return s;
        }
    }

    @Override
    public Set<String> excludedModuleTags() {
        return new HashSet<>(Arrays.asList(Att.CONCRETE(), "kore"));
    }
}
