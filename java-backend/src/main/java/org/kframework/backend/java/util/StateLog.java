// Copyright (c) 2018 K Team. All Rights Reserved.
package org.kframework.backend.java.util;

import org.kframework.backend.java.symbolic.JavaExecutionOptions;
import org.kframework.definition.Module;
import org.kframework.kore.K;
import org.kframework.krun.KRun;
import org.kframework.parser.concrete2kore.generator.RuleGrammarGenerator;
import org.kframework.unparser.KPrint;
import org.kframework.unparser.OutputModes;
import org.kframework.utils.file.FileUtil;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.PrintWriter;
import java.io.OutputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import org.apache.commons.io.output.WriterOutputStream;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Set;
import java.util.ArrayList;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import java.lang.Math;

public class StateLog {

    // *ALL* `public` methods *MUST* return `void` and have their first line be `if (! this.loggingOn) return;`
    private final boolean loggingOn;
    private final File    loggingPath;
    private final File    blobsDir;

    private String      sessionId;
    private PrintWriter sessionLog;

    private long   startTime;
    private String currentTerm;
    private String currentRule;
    private String currentMatchRule;
    private String currentQuery;
    private String currentImplication;

    public StateLog() {
        this.loggingOn   = false;
        this.loggingPath = null;
        this.blobsDir    = null;
    }

    public StateLog(JavaExecutionOptions javaExecutionOptions, FileUtil files) {
        this.loggingOn = javaExecutionOptions.stateLog;

        this.loggingPath = javaExecutionOptions.stateLogPath == null
                         ? files.resolveKompiled("stateLog")
                         : new File(javaExecutionOptions.stateLogPath);

        if (javaExecutionOptions.stateLogId != null) this.sessionId = javaExecutionOptions.stateLogId;

        this.blobsDir = new File(loggingPath, "blobs/");
        this.blobsDir.mkdirs();

        this.currentImplication = "NOTERM";
        this.currentTerm        = "NOTERM";
        this.currentRule        = "NORULE";
        this.currentMatchRule   = "NORULE";
        this.currentQuery       = "NOQUERY";
    }

    public void init(String defaultSessionId) {
        if (! this.loggingOn) return;
        if (this.sessionId == null) this.sessionId = defaultSessionId;
        File logFile = new File(this.loggingPath, this.sessionId + ".log");
        PrintWriter sessionLog;
        try {
            this.sessionLog = new PrintWriter(logFile);
            System.err.println("StateLog: " + logFile);
        } catch (FileNotFoundException e) {
            e.printStackTrace();
        }
        this.startTime = System.currentTimeMillis();
    }

    public void setTarget(boolean b) {
        if (! this.loggingOn) return;
        if(b) {
            this.currentMatchRule = "IMPLIESTARGET";
        } else {
            this.currentMatchRule = "NORULE";
        }
    }

    public static enum LogEvent {
        INIT, TARGET, IMPLIESTARGET, NODE, MARKEDNODE, RULE, SRSTEP, BRANCH, IMPLICATION, Z3QUERY, Z3RESULT, STEP, RSTEP, CRASH, MATCHRULE, CLOSE
    }

    public void resetMatchrule() {
        if (! this.loggingOn) return;
        currentMatchRule = "NORULE";
    }

    public void log(String logItem) {
        if (! this.loggingOn) return;
        this.sessionLog.println((System.currentTimeMillis() - this.startTime) + " " + logItem);
        this.sessionLog.flush();
    }

    public void log(LogEvent logCode, K... terms) {
        if (! this.loggingOn) return;
        ArrayList<String> nodeIds = new ArrayList<String>();
        for (K term: terms) {
            nodeIds.add(writeNode(term));
        }
        String nodeId = String.join("_", nodeIds);
        String logPrefix = "";
        switch(logCode) {
            case INIT:
                currentTerm = nodeId;
                logPrefix = "init";
                break;
            case TARGET:
                logPrefix = "target";
                break;
            case IMPLIESTARGET:
                logPrefix = "finished";
                break;
            case NODE:
                currentTerm = nodeId;
                logPrefix = "node";
                break;
            case MARKEDNODE:
                currentTerm = nodeId;
                logPrefix = "markednode";
                break;
            case RULE:
                currentRule = nodeId;
                logPrefix = "rule";
                break;
            case MATCHRULE:
                currentMatchRule = nodeId;
                logPrefix = "matchrule";
                break;
            case SRSTEP:
                logPrefix = "srstep " + currentRule;
                break;
            case RSTEP:
                logPrefix = "rstep " + currentRule;
                break;
            case BRANCH:
                logPrefix = "branch";
                break;
            case IMPLICATION:
                currentImplication = nodeId;
                logPrefix = "implication";
                break;
            case Z3QUERY:
                currentQuery = nodeId;
                logPrefix = "z3query";
                break;
            case Z3RESULT:
                logPrefix = "z3result " + currentQuery + " " + currentMatchRule + " " + currentImplication;
                break;
            case STEP:
                logPrefix = "step";
                break;
            case CRASH:
                logPrefix = "crash";
                break;
            case CLOSE:
                logPrefix = "close";
                break;
        }
        this.log(logPrefix + " " + currentTerm + " " + nodeId);
    }

    public void close() {
        if (! this.loggingOn) return;
        this.log(LogEvent.CLOSE);
        this.sessionLog.close();
    }

    private static String hash(K in) {
        MessageDigest m = null;
        String hashtext = "__";
        try {
            m = MessageDigest.getInstance("MD5");
            m.reset();
            m.update(KPrint.serialize(in, OutputModes.KAST));
            byte[] digest = m.digest();
            BigInteger bigInt = new BigInteger(1,digest);
            hashtext = bigInt.toString(16);
        } catch (NoSuchAlgorithmException e) {
            e.printStackTrace();
        }
        return hashtext;
    }

    private String writeNode(K contents) {
        String fileCode   = hash(contents);
        File   outputFile = new File(this.blobsDir, fileCode + "." + OutputModes.JSON.ext());
        if (! outputFile.exists()) {
            try {
                String out = new String(KPrint.serialize(contents, OutputModes.JSON), StandardCharsets.UTF_8);
                PrintWriter fOut = new PrintWriter(outputFile);
                fOut.println(out);
                fOut.close();
            } catch (FileNotFoundException e) {
                System.err.println("Could not open node output file: " + outputFile.getAbsolutePath());
                e.printStackTrace();
            }
        }
        return fileCode;
    }
}
