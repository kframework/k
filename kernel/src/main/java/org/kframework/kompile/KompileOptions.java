// Copyright (c) 2014-2019 K Team. All Rights Reserved.
package org.kframework.kompile;

import com.beust.jcommander.Parameter;
import com.beust.jcommander.ParametersDelegate;
import org.apache.commons.io.FilenameUtils;

import org.kframework.backend.Backends;
import org.kframework.main.GlobalOptions;
import org.kframework.unparser.OutputModes;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.file.FileUtil;
import org.kframework.utils.inject.RequestScoped;
import org.kframework.utils.options.OuterParsingOptions;
import org.kframework.utils.options.SMTOptions;
import org.kframework.utils.options.BaseEnumConverter;
import org.kframework.utils.options.StringListConverter;

import java.io.Serializable;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

@RequestScoped
public class KompileOptions implements Serializable {


    /**
     * WARNING: this field will be non-null in kompile tool, but null when KompileOption is deserialized,
     * as part of CompiledDefinition, in any other tool. usability depends on context.
     */
    @ParametersDelegate
    public transient GlobalOptions global = new GlobalOptions();

    @ParametersDelegate
    public OuterParsingOptions outerParsing = new OuterParsingOptions();

    // Common options
    @Parameter(names="--backend", description="Choose a backend. <backend> is one of [llvm|haskell|kore|java|ocaml]. Each creates the kompiled K definition.")
    public String backend = Backends.LLVM;

    private boolean kore;

    @Parameter(names="--main-module", description="Specify main module in which a program starts to execute. This information is used by 'krun'. The default is the name of the given K definition file without the extension (.k).")
    private String mainModule;

    public String mainModule(FileUtil files) {
        if (mainModule == null) {
            return FilenameUtils.getBaseName(outerParsing.mainDefinitionFile(files).getName()).toUpperCase();
        }
        return mainModule;
    }

    @Parameter(names="--syntax-module", description="Specify main module for syntax. This information is used by 'krun'. (Default: <main-module>-SYNTAX).")
    private String syntaxModule;

    public String syntaxModule(FileUtil files) {
        if (syntaxModule == null) {
            return mainModule(files) + "-SYNTAX";
        }
        return syntaxModule;
    }

    @Parameter(names="--non-strict", description="Do not add runtime sort checks for every variable's inferred sort. Only has an effect with `--backend ocaml`.")
    private boolean nonStrict;

    public boolean strict() {
        if (nonStrict && ! backend.equals("ocaml")) {
            throw KEMException.criticalError("Option `--non-strict` only makes sense for `--backend ocaml`.");
        }
        return !nonStrict;
    }

    @Parameter(names="--coverage", description="Generate coverage data when executing semantics.")
    public boolean coverage;

    @Parameter(names="--profile-rule-parsing", description="Generate time in seconds to parse each rule in the semantics. Found in -kompiled directory under timing.log.")
    public boolean profileRules;

    @Parameter(names="--hook-namespaces", listConverter=StringListConverter.class, description="<string> is a whitespace-separated list of namespaces to include in the hooks defined in the definition")
    public List<String> hookNamespaces = Collections.emptyList();

    @Parameter(names="-O1", description="Optimize in ways that improve performance and code size, but interfere with debugging and increase compilation time slightly.")
    public boolean optimize1;

    @Parameter(names="-O2", description="Optimize further in ways that improve performance and code size, but interfere with debugging more and increase compilation time somewhat.")
    public boolean optimize2;

    @Parameter(names="-O3", description="Optimize aggressively in ways that significantly improve performance, but interfere with debugging significantly and also increase compilation time and code size substantially.")
    public boolean optimize3;

    @Parameter(names="-E", description="Perform outer parsing and then stop and pretty print the definition to standard output. Useful for converting a K definition into a completely self-contained file when reporting a bug.")
    public boolean preprocess;

    @Parameter(names="--bison-lists", description="Make List and NeList left associative. This is useful for creating Bison parsers that use bounded stack space.")
    public boolean bisonLists;

    @Parameter(names="--read-only-kompiled-directory", description="Files in the generated kompiled directory should be read-only to other frontend tools.")
    public boolean readOnlyKompiledDirectory = false;

    public boolean isKore() {
        return backend.equals("kore") || backend.equals("haskell") || backend.equals("llvm");
    }

    @ParametersDelegate
    public SMTOptions smt = new SMTOptions();

    @Parameter(names="--cache-file", description="Location of parse cache file. Default is $KOMPILED_DIR/cache.bin.")
    public String cacheFile;

    @Parameter(names="--emit-json", description="Emit JSON serialized version of parsed and kompiled definitions.")
    public boolean emitJson = false;

    @Parameter(names="--gen-bison-parser", description="Emit bison parser for the PGM configuration variable within the syntax module of your definition into the kompiled definition.")
    public boolean genBisonParser;

    @Parameter(names="--gen-glr-bison-parser", description="Emit GLR bison parser for the PGM configuration variable within the syntax module of your definition into the kompiled definition.")
    public boolean genGlrBisonParser;

    @Parameter(names="--bison-file", description="C file containing functions to link into bison parser.")
    public String bisonFile;

    @Parameter(names="--bison-stack-max-depth", description="Maximum size of bison parsing stack (default: 10000).")
    public long bisonStackMaxDepth = 10000;

    @Parameter(names="--transition", listConverter=StringListConverter.class, description="[DEPRECATED: java backend only] <string> is a whitespace-separated list of tags designating rules to become transitions.")
    public List<String> transition = Collections.singletonList(DEFAULT_TRANSITION);

    public static final String DEFAULT_TRANSITION = "transition";

    @Parameter(names="--top-cell", description="Choose the top configuration cell when more than one is provided. Does nothing if only one top cell exists.")
    public String topCell;
}
