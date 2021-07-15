// Copyright (c) 2015-2019 K Team. All Rights Reserved.
package org.kframework.compile;

import org.kframework.attributes.Att;
import org.kframework.builtin.KLabels;
import org.kframework.backend.kore.ConstructorChecks;
import org.kframework.definition.Context;
import org.kframework.definition.Module;
import org.kframework.definition.Production;
import org.kframework.definition.RuleOrClaim;
import org.kframework.definition.Sentence;
import org.kframework.kore.K;
import org.kframework.kore.KApply;
import org.kframework.kore.KLabel;
import org.kframework.kore.KRewrite;
import org.kframework.kore.Sort;

import java.util.ArrayList;
import java.util.List;

import static org.kframework.Collections.*;
import static org.kframework.kore.KORE.*;

/**
 * This pass adds the implicit top and k cells to
 * the bodies of rules and contexts.
 * A K cell is added only if the body is a single item,
 * which is not already a cell or a rewrite on cells.
 * The top cell is added unless the body is already an
 * instance of the top cell.
 * Rules with the anywhere attribute are not modified.
 */
// TODO: rules defining functions shouldn't be wrapped
public class AddTopCellToRules {

    private final ConfigurationInfo cfg;
    private final LabelInfo labelInfo;
    private final boolean kore;

    public AddTopCellToRules(ConfigurationInfo cfg, LabelInfo labelInfo, boolean kore) {
        this.cfg = cfg;
        this.labelInfo = labelInfo;
        this.kore = kore;
    }

    public K addImplicitCells(K term, Module m) {
        if (m.isFunction(term)) return term;
        return addRootCell(term);
    }

    protected K addRootCell(K term) {
        KLabel root;
        if (kore) {
            root = KLabels.GENERATED_TOP_CELL;
        } else {
            root = cfg.getCellLabel(cfg.getRootCell());
        }

        // KApply instance
        if (term instanceof KApply) {
            KLabel kLabel = ((KApply) term).klabel();
            if (ConstructorChecks.isBuiltinLabel(kLabel)) {
                // builtin-labels (ML connectives)
                Production prod = labelInfo.getProduction(kLabel.name());
                if(prod.params().nonEmpty()) {
                    for (Sort param : iterable(prod.params())) {
                        if (prod.sort().equals(param)) {
                            if (stream(prod.nonterminals()).anyMatch(nt -> nt.sort().equals(param))) {
                                // recursively call addRoot on the children whose type is the same as the return type
                                List<K> oldChildren = ((KApply) term).klist().items();
                                List<K> newChildren = new ArrayList<>();
                                for (int i = 0; i < oldChildren.size(); i++) {
                                    if (prod.nonterminals().apply(i).sort().equals(param)) {
                                        newChildren.add(addRootCell(oldChildren.get(i)));
                                    } else {
                                        newChildren.add(oldChildren.get(i));
                                    }

                                }
                                return KApply(kLabel, KList(newChildren));
                            } else {
                                // only one group can contain 0
                                return term;
                            }
                        }
                    }
                    // if 0 doesn't appear in the poly attribute
                    return term;
                } else {
                    // connectives that don't have poly attribute
                    return term;
                }
            } else {
                if (kLabel.equals(root)) {
                    return term;
                }
            }
        }

        // KRewrite instance
        if (term instanceof KRewrite) {
            KRewrite rew = (KRewrite) term;
            K left = addRootCell(rew.left());
            if (left == rew.left()) {
                return KRewrite(rew.left(), rew.right());
            } else {
                return IncompleteCellUtils.make(root, true, term, true);
            }
        }

        // default
        return IncompleteCellUtils.make(root, true, term, true);
    }

    public RuleOrClaim addImplicitCells(RuleOrClaim rule, Module m) {
        return rule.newInstance(
                addImplicitCells(rule.body(), m),
                rule.requires(),
                rule.ensures(),
                rule.att());
    }

    public Context addImplicitCells(Context context, Module m) {
        return new Context(
                addImplicitCells(context.body(), m),
                context.requires(),
                context.att());
    }

    public Sentence addImplicitCells(Sentence s, Module m) {
        if (skipSentence(s)) {
            return s;
        }
        if (s instanceof RuleOrClaim) {
            return addImplicitCells((RuleOrClaim) s, m);
        } else if (s instanceof Context) {
            return addImplicitCells((Context) s, m);
        } else {
            return s;
        }
    }

    private boolean skipSentence(Sentence s) {
        return ExpandMacros.isMacro(s)
                || s.att().contains(Att.ANYWHERE())
                || s.att().contains(Att.SIMPLIFICATION());
    }
}
