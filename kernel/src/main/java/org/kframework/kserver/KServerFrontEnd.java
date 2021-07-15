// Copyright (c) 2015-2019 K Team. All Rights Reserved.
package org.kframework.kserver;
import com.google.common.collect.ImmutableList;
import com.google.inject.Inject;
import com.google.inject.Injector;
import com.google.inject.Module;
import com.google.inject.Provider;
import com.martiansoftware.nailgun.NGContext;
import com.martiansoftware.nailgun.NGListeningAddress;
import com.martiansoftware.nailgun.NGServer;
import com.martiansoftware.nailgun.ThreadLocalPrintStream;
import org.fusesource.jansi.AnsiOutputStream;
import org.kframework.main.FrontEnd;
import org.kframework.main.Main;
import org.kframework.utils.OS;
import org.kframework.utils.errorsystem.KExceptionManager;
import org.kframework.utils.file.FileUtil;
import org.kframework.utils.file.JarInfo;
import org.kframework.utils.file.TTYInfo;
import org.kframework.utils.inject.CommonModule;
import org.kframework.utils.inject.JCommanderModule;
import org.kframework.utils.inject.JCommanderModule.ExperimentalUsage;
import org.kframework.utils.inject.JCommanderModule.Usage;
import org.kframework.utils.inject.SimpleScope;

import java.io.File;
import java.io.PrintStream;
import java.net.InetAddress;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.locks.ReadWriteLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;


public class KServerFrontEnd extends FrontEnd {

    public static List<Module> getModules() {
        List<Module> modules = new ArrayList<>();
        modules.add(new KServerModule());
        modules.add(new JCommanderModule());
        modules.add(new CommonModule());
        return modules;
    }

    @Inject
    public KServerFrontEnd(
            KExceptionManager kem,
            KServerOptions options,
            @Usage String usage,
            JarInfo jarInfo,
            Provider<FileUtil> files) {
        super(kem, options.global, usage, jarInfo, files);
        this.options = options;
    }

    private static KServerFrontEnd instance;
    private static Thread threadInstance;
    private static final ImmutableList<String> tools = ImmutableList.of("-kompile", "-krun", "-kast",
            "-kdep", "-keq", "-kprove", "-kprovex", "-kbmc", "-kserver");

    private final KServerOptions options;
    private final Map<String, Injector> injectors = new HashMap<>();
    private final ReadWriteLock lock = new ReentrantReadWriteLock();

    @Override
    protected int run() {
        for (String tool : tools) {
            injectors.put(tool, Main.getInjector(tool));
        }
        NGServer server;
        File dir = null;
        if (isLocal()) {
            // can use more secure unix domain sockets
            // we use HOME variable to get home on linux because user.home does not match HOME variable when run with sudo
            // unless run with sudo -H, and we want to ensure that the installer works correctly.
            String dirpath = options.socket;
            if (dirpath == null) {
                String home = OS.current() == OS.LINUX ? System.getenv("HOME") : System.getProperty("user.home");
                dirpath = home + File.separatorChar + ".kserver";
            }
            dir = new File(dirpath);
            dir.mkdirs();
            dir.setReadable(false, false);
            dir.setReadable(true, true);
            dir.setWritable(false, false);
            dir.setWritable(true, true);
            dir.setExecutable(false, false);
            dir.setExecutable(true, true);
            File socket = new File(dir, "socket");
            socket.deleteOnExit();
            if (socket.exists()) {
                System.out.println("Warning: K server already started.");
                socket.delete();
            }
            server = new NGServer(new NGListeningAddress(socket.getAbsolutePath()), 10, 10000);
        } else {
            server = new NGServer(InetAddress.getLoopbackAddress(), options.port);
        }
        Thread t = new Thread(server);
        instance = this;
        threadInstance = t;
        t.start();

        if (isLocal()) {
            System.out.println("K server started using IPC at " + dir.getAbsolutePath());
        } else {
            int runningPort = server.getPort();
            while (runningPort == 0) {
                try {
                    Thread.sleep(50L);
                } catch (InterruptedException e) {
                }
                runningPort = server.getPort();
            }
            System.out.println("K server started on 127.0.0.1:" + options.port);
        }

        try {
            t.join();
            return 0;
        } catch (InterruptedException e) {
            //application is about to die
            return 0;
        }
    }

    public static KServerFrontEnd instance() {
        return instance;
    }

    public int run(String tool, String[] args, File workingDir, Map<String, String> env, long startTime) {
        ThreadLocalPrintStream system_out = (ThreadLocalPrintStream) System.out;
        ThreadLocalPrintStream system_err = (ThreadLocalPrintStream) System.err;

        Injector injector;

        lock.readLock().lock();
        try {
            injector = injectors.get(tool);
        } finally {
            lock.readLock().unlock();
        }

        Main launcher = injector.getInstance(Main.class);
        SimpleScope requestScope = launcher.getRequestScope();
        try {
            requestScope.enter();
            Main.seedInjector(requestScope, tool, args, workingDir, env, startTime);
            TTYInfo tty = injector.getInstance(TTYInfo.class);
            if (!tty.stdout) {
                system_out.init(new PrintStream(new AnsiOutputStream(system_out.getPrintStream())));
            }
            if (!tty.stderr) {
                system_err.init(new PrintStream(new AnsiOutputStream(system_err.getPrintStream())));
            }

            int result = launcher.runApplication();
            System.out.flush();
            System.err.flush();
            return result;
        } finally {
            requestScope.exit();
        }
    }

    public static void nailMain(NGContext context) {
        KServerFrontEnd kserver = KServerFrontEnd.instance();
        if (!kserver.isLocal()) {
            context.assertLoopbackClient();
        }
        if (context.getArgs()[0].equals("shutdown")) {
            System.setSecurityManager(null);
            context.getNGServer().shutdown(true);
        } else if (context.getArgs()[0].equals("reset")) {
            kserver.lock.writeLock().lock();
            try {
                kserver.injectors.clear();
                for (String tool : tools) {
                    kserver.injectors.put(tool, Main.getInjector(tool));
                }
            } finally {
                kserver.lock.writeLock().unlock();
            }
            System.gc();
        }
    }

    public boolean isLocal() {
        return (OS.current() != OS.WINDOWS) || (options.socket != null);
    }
}
