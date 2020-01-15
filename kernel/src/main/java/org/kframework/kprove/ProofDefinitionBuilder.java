package org.kframework.kprove;

import com.google.inject.Inject;
import org.apache.commons.io.FilenameUtils;
import org.kframework.compile.Backend;
import org.kframework.definition.Definition;
import org.kframework.definition.Module;
import org.kframework.kompile.CompiledDefinition;
import org.kframework.kompile.DefinitionAndCache;
import org.kframework.kompile.DefinitionStorage;
import org.kframework.kompile.Kompile;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.file.FileUtil;
import scala.Option;
import scala.Tuple2;

import java.io.File;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * @author Denis Bogdanas
 * Created on 07-Nov-19.
 */
public class ProofDefinitionBuilder {

    private static Map<Definition, Definition>
            cache = Collections.synchronizedMap(new LinkedHashMap<Definition, Definition>() {
        @Override
        protected boolean removeEldestEntry(Map.Entry entry) {
            return size() > 10;
        }
    });


    private final CompiledDefinition compiledDefinition;
    private final Backend backend;
    private final Kompile kompile;
    private final FileUtil files;
    private final DefinitionStorage definitionStorage;
    private final DefinitionAndCache definitionAndCache;

    @Inject
    public ProofDefinitionBuilder(Backend backend, Kompile kompile,
                                  FileUtil files, DefinitionStorage definitionStorage,
                                  DefinitionAndCache definitionAndCache) {
        this.compiledDefinition = definitionAndCache.compiledDefinition;
        this.backend = backend;
        this.kompile = kompile;
        this.files = files;
        this.definitionStorage = definitionStorage;
        this.definitionAndCache = definitionAndCache;
    }

    /**
     * @param specFile       File containing specification rules to prove. Not part of definition.
     * @param defModuleName  Name of main module of extended definition - that is compiled definition + extra
     *                       modules required by proofs, usually abstractions for symbolic execution and lemmas.
     * @param specModuleName Module containing specifications to prove
     */
    public Tuple2<Definition, Module> build(File specFile, String defModuleName, String specModuleName) {
        String defModuleNameUpdated =
                defModuleName == null ? compiledDefinition.kompiledDefinition.mainModule().name() : defModuleName;
        String specModuleNameUpdated =
                specModuleName == null ? FilenameUtils.getBaseName(specFile.getName()).toUpperCase() : specModuleName;
        File absSpecFile = files.resolveWorkingDirectory(specFile).getAbsoluteFile();

        Set<Module> modules = kompile.parseModules(compiledDefinition, defModuleNameUpdated, absSpecFile,
                backend.excludedModuleTags());
        definitionStorage.save(definitionAndCache);

        Map<String, Module> modulesMap = modules.stream().collect(Collectors.toMap(Module::name, m -> m));
        Definition parsedDefinition = compiledDefinition.getParsedDefinition();
        Module defModule = getModule(defModuleNameUpdated, modulesMap, parsedDefinition);
        Definition rawExtendedDef = Definition.apply(defModule, parsedDefinition.entryModules(),
                parsedDefinition.att());
        Definition compiledExtendedDef = compileDefinition(backend, rawExtendedDef); //also resolves imports

        Module specModule = getModule(specModuleNameUpdated, modulesMap, parsedDefinition);
        specModule = backend.specificationSteps(compiledDefinition.kompiledDefinition).apply(specModule);

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

    private static Definition compileDefinition(Backend backend, Definition combinedDef) {
        Definition compiled = cache.get(combinedDef);
        if (compiled == null) {
            compiled = backend.steps().apply(combinedDef);
            cache.put(combinedDef, compiled);
        }
        return compiled;
    }
}
