package org.kframework.kprovex;

import com.google.inject.AbstractModule;
import com.google.inject.Provides;
import com.google.inject.multibindings.Multibinder;
import com.google.inject.name.Named;
import org.kframework.kompile.BackendModule;
import org.kframework.krun.RewriterModule;
import org.kframework.main.FrontEnd;
import org.kframework.main.GlobalOptions;
import org.kframework.main.Tool;
import org.kframework.unparser.PrintOptions;
import org.kframework.utils.inject.Options;
import org.kframework.utils.inject.RequestScoped;
import org.kframework.utils.options.BackendOptions;
import org.kframework.utils.options.DefinitionLoadingOptions;
import org.kframework.utils.options.SMTOptions;

import java.util.List;

public class KProveModule extends AbstractModule {
    @Override
    protected void configure() {
        bind(FrontEnd.class).to(KProveFrontEnd.class);
        bind(Tool.class).toInstance(Tool.KPROVE);

        install(new BackendModule());
        install(new RewriterModule());

        Multibinder<Object> optionsBinder = Multibinder.newSetBinder(binder(), Object.class, Options.class);
        optionsBinder.addBinding().to(KProveOptions.class);
    }

    @Provides @RequestScoped
    GlobalOptions globalOptions(KProveOptions options) {
        return options.global;
    }

    @Provides @RequestScoped
    PrintOptions printOptions(KProveOptions options) {
        return options.print;
    }

    @Provides
    DefinitionLoadingOptions loadingOptions(KProveOptions options) {
        return options.definitionLoading;
    }

    @Provides
    BackendOptions backendOptions(KProveOptions options) {
        return options.backend;
    }

    @Provides
    SMTOptions smtOptions(KProveOptions options) {
        return options.smt;
    }

    @Provides
    @Named("extraConcreteRuleLabels")
    List<String> extraConcreteRuleLabels(KProveOptions options) {
        return options.extraConcreteRuleLabels;
    }
}
