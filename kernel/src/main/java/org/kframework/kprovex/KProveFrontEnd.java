// Copyright (c) 2015-2019 K Team. All Rights Reserved.
package org.kframework.kprovex;

import com.google.common.collect.ImmutableList;
import com.google.inject.Inject;
import com.google.inject.Module;
import com.google.inject.Provider;
import org.kframework.main.FrontEnd;
import org.kframework.main.GlobalOptions;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;
import org.kframework.utils.file.JarInfo;
import org.kframework.utils.file.KompiledDir;
import org.kframework.utils.inject.CommonModule;
import org.kframework.utils.inject.DefinitionLoadingModule;
import org.kframework.utils.inject.DefinitionScope;
import org.kframework.utils.inject.JCommanderModule;

import java.io.File;
import java.util.List;

public class KProveFrontEnd extends FrontEnd {


    public static List<Module> getModules() {
        return ImmutableList.of(
                new KProveModule(),
                new CommonModule(),
                new JCommanderModule(),
                new DefinitionLoadingModule());
    }


    private final DefinitionScope scope;
    private final Provider<File> kompiledDir;
    private final Provider<KProve> kprove;

    @Inject
    KProveFrontEnd(
            GlobalOptions options,
            @JCommanderModule.Usage String usage,
            JarInfo jarInfo,
            DefinitionScope scope,
            @KompiledDir Provider<File> kompiledDir,
            KExceptionManager kem,
            Provider<FileUtil> files,
            Provider<KProve> kprove) {
        super(kem, options, usage, jarInfo, files);
        this.scope = scope;
        this.kompiledDir = kompiledDir;
        this.kprove = kprove;
    }

    @Override
    protected int run() {
        scope.enter(kompiledDir.get());
        try {
            return kprove.get().run();
        } finally {
            scope.exit();
        }
    }
}
