package org.kframework.kprovex;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.apache.commons.io.FilenameUtils;
import org.kframework.compile.Backend;
import org.kframework.definition.Definition;
import org.kframework.definition.Module;
import org.kframework.kompile.CompiledDefinition;
import org.kframework.kompile.Kompile;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.file.FileUtil;
import scala.Option;
import scala.Tuple2;

import java.io.File;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.kframework.Collections.*;

public class ProofDefinitionBuilder {

    private final CompiledDefinition compiledDefinition;
    private final Backend backend;
    private final Kompile kompile;
    private final FileUtil files;
    @Inject(optional = true)
    @Named("extraConcreteRuleLabels")
    private List<String> extraConcreteRuleLabels = null;

    @Inject
    public ProofDefinitionBuilder(CompiledDefinition compiledDefinition, Backend backend, Kompile kompile,
                                  FileUtil files) {
        this.compiledDefinition = compiledDefinition;
        this.backend = backend;
        this.kompile = kompile;
        this.files = files;
    }

    /**
     * @param specFile       File containing specification rules to prove. Not part of definition.
     * @param specModuleName Module containing specifications to prove
     */
    public Tuple2<Definition, Module> build(File specFile, String specModuleName, boolean readOnlyCache) {
        String defModuleNameUpdated = compiledDefinition.kompiledDefinition.mainModule().name();
        String specModuleNameUpdated =
                specModuleName == null ? FilenameUtils.getBaseName(specFile.getName()).toUpperCase() : specModuleName;
        File absSpecFile = files.resolveWorkingDirectory(specFile).getAbsoluteFile();

        Set<Module> modules = kompile.parseModules(compiledDefinition, defModuleNameUpdated, specModuleNameUpdated, absSpecFile,
                backend.excludedModuleTags(), readOnlyCache);
        Map<String, Module> modulesMap = modules.stream().collect(Collectors.toMap(Module::name, m -> m));
        Definition parsedDefinition = compiledDefinition.getParsedDefinition();
        Module specModule = getModule(specModuleNameUpdated, modulesMap, parsedDefinition);
        kompile.proverChecksX(specModule, modulesMap.get(defModuleNameUpdated));
        kompile.structuralChecks(immutable(modules), specModule, Option.empty(), backend.excludedModuleTags());
        specModule = backend.specificationSteps(compiledDefinition.kompiledDefinition).apply(specModule);

        Definition compiledExtendedDef = backend.proofDefinitionNonCachedSteps(extraConcreteRuleLabels).apply(compiledDefinition.kompiledDefinition);
        return Tuple2.apply(compiledExtendedDef, specModule);
    }

    private static Module getModule(String defModule, Map<String, Module> modules, Definition parsedDefinition) {
        if (modules.containsKey(defModule))
            return modules.get(defModule);
        Option<Module> mod = parsedDefinition.getModule(defModule);
        if (mod.isDefined()) {
            return mod.get();
        }
        throw KEMException.criticalError("Module " + defModule + " does not exist.");
    }
}
