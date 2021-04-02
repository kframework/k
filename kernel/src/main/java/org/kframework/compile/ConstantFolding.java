// Copyright (c) 2021 K Team. All Rights Reserved.
package org.kframework.compile;

import org.apache.commons.lang3.StringUtils;
import org.kframework.attributes.Att;
import org.kframework.builtin.Hooks;
import org.kframework.definition.Module;
import org.kframework.definition.Rule;
import org.kframework.definition.Sentence;
import org.kframework.kore.K;
import org.kframework.kore.KApply;
import org.kframework.kore.KToken;
import org.kframework.kore.Sort;
import org.kframework.kore.TransformK;
import org.kframework.utils.errorsystem.KEMException;
import org.kframework.utils.StringUtil;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.kframework.Collections.*;
import static org.kframework.kore.KORE.*;
import static org.kframework.definition.Constructors.*;

public class ConstantFolding {

  private final List<String> hookNamespaces = Arrays.asList(Hooks.BOOL, Hooks.FLOAT, Hooks.INT, Hooks.MINT, Hooks.STRING);

  private K loc;

  public Sentence fold(Module module, Sentence sentence) {
    if (sentence instanceof Rule) {
      Rule r = (Rule)sentence;
      return Rule(fold(module, r.body(), true), fold(module, r.requires(), false), fold(module, r.ensures(), false), r.att());
    }
    return sentence;
  }

  public K fold(Module module, K body, boolean isBody) {
    return new RewriteAwareTransformer(isBody) {
      @Override
      public K apply(KApply k) {
        if (isLHS() || !isRHS()) {
          return super.apply(k);
        }
        if (module.attributesFor().get(k.klabel()).getOrElse(() -> Att()).contains(Att.HOOK())) {
          String hook = module.attributesFor().apply(k.klabel()).get(Att.HOOK());
          if (hookNamespaces.stream().anyMatch(ns -> hook.startsWith(ns + "."))) {
            List<K> args = new ArrayList<>();
            for (K arg : k.items()) {
              K expanded = apply(arg);
              if (!(expanded instanceof KToken)) {
                return super.apply(k);
              }
              args.add(expanded);
            }
            try {
              loc = k;
              return doFolding(hook, args, module.productionsFor().apply(k.klabel().head()).head().substitute(k.klabel().params()).sort(), module);
            } catch (NoSuchMethodException e) {
              throw KEMException.internalError("Missing constant-folding implementation for hook " + hook, e);
            }
          }
        }
        return super.apply(k);
      }
    }.apply(body);
  }

  private static class MIntBuiltin {
    public BigInteger i;
    public long precision;

    public MIntBuiltin(BigInteger i, long precision) {
      this.i = i;
      this.precision = precision;
    }
  }

  private Class<?> classOf(String hook) {
    switch(hook) {
      case "BOOL.Bool":
        return boolean.class;
      case "FLOAT.Float":
        return FloatBuiltin.class;
      case "INT.Int":
        return BigInteger.class;
      case "MINT.MInt":
        return MIntBuiltin.class;
      case "STRING.String":
        return String.class;
      default:
        throw KEMException.internalError("Invalid constant-folding sort");
    }
  }

  private Object unwrap(String token, String hook) {
    switch(hook) {
      case "BOOL.Bool":
        return Boolean.valueOf(token);
      case "FLOAT.Float":
        return FloatBuiltin.of(token);
      case "INT.Int":
        return new BigInteger(token);
      case "MINT.MInt":
        int idx = token.indexOf('p');
        if (idx == -1) idx = token.indexOf('P');
        return new MIntBuiltin(new BigInteger(token.substring(0, idx)), Long.valueOf(token.substring(idx+1)));
      case "STRING.String":
        return StringUtil.unquoteKString(token);
      default:
        throw KEMException.internalError("Invalid constant-folding sort");
    }
  }

  private K wrap(Object result, Sort sort) {
    if (result instanceof Boolean) {
      return KToken(result.toString(), sort);
    } else if (result instanceof FloatBuiltin) {
      return KToken(((FloatBuiltin)result).value(), sort);
    } else if (result instanceof BigInteger) {
      return KToken(result.toString(), sort);
    } else if (result instanceof MIntBuiltin) {
      return KToken(result.toString(), sort);
    } else if (result instanceof String) {
      return KToken(StringUtil.enquoteKString((String)result), sort);
    } else {
      throw KEMException.internalError("Invalid constant-folding sort");
    }
  }

  private K doFolding(String hook, List<K> args, Sort resultSort, Module module) throws NoSuchMethodException {
    String renamedHook = hook.replace('.', '_');
    List<Class<?>> paramTypes = new ArrayList<>();
    List<Object> unwrappedArgs = new ArrayList<>();
    for (K arg : args) {
      KToken tok = (KToken)arg;
      Sort sort = tok.sort();
      String argHook = module.sortAttributesFor().apply(sort.head()).get(Att.HOOK());
      paramTypes.add(classOf(argHook));
      unwrappedArgs.add(unwrap(tok.s(), argHook));
    }
    try {
      Method m = ConstantFolding.class.getDeclaredMethod(renamedHook, paramTypes.toArray(new Class<?>[args.size()]));
      Object result = m.invoke(this, unwrappedArgs.toArray(new Object[args.size()]));
      return wrap(result, resultSort);
    } catch (IllegalAccessException e) {
      throw KEMException.internalError("Error invoking constant folding function", e);
    } catch (InvocationTargetException e) {
      if (e.getCause() instanceof KEMException) {
        throw (KEMException)e.getCause();
      } else {
        throw KEMException.internalError("Error invoking constant folding function", e);
      }
    }
  }

  private boolean BOOL_not(boolean a) {
    return ! a;
  }

  private boolean BOOL_and(boolean a, boolean b) {
    return a && b;
  }

  private boolean BOOL_andThen(boolean a, boolean b) {
    return a && b;
  }

  private boolean BOOL_xor(boolean a, boolean b) {
    return (a && !b) || (b && !a);
  }

  private boolean BOOL_or(boolean a, boolean b) {
    return a || b;
  }

  private boolean BOOL_orElse(boolean a, boolean b) {
    return a || b;
  }

  private boolean BOOL_implies(boolean a, boolean b) {
    return ! a || b;
  }

  private boolean BOOL_eq(boolean a, boolean b) {
    return a == b;
  }

  private boolean BOOL_ne(boolean a, boolean b) {
    return a != b;
  }

  private String STRING_concat(String a, String b) {
    return a + b;
  }

  private BigInteger STRING_length(String a) {
    return BigInteger.valueOf(a.length());
  }

  private String STRING_chr(BigInteger a) {
    if (a.compareTo(BigInteger.ZERO) < 0 || a.compareTo(BigInteger.valueOf(0x10ffff)) > 0) {
      throw KEMException.compilerError("Argument to hook STRING.chr out of range. Expected a number between 0 and 1114111.", loc);
    }
    int[] codePoint = new int[] { a.intValue() };
    return new String(codePoint, 0, 1);
  }

  private BigInteger STRING_ord(String a) {
    if (a.codePointCount(0, a.length()) > 1) {
      throw KEMException.compilerError("Argument to hook STRING.ord out of range. Expected a single character.");
    }
    return BigInteger.valueOf(a.codePointAt(0));
  }

  private void throwIfNotInt(BigInteger i, String hook) {
    if (i.compareTo(BigInteger.valueOf(Integer.MIN_VALUE)) < 0 || i.compareTo(BigInteger.valueOf(Integer.MAX_VALUE)) > 0) {
      throw KEMException.compilerError("Argument to hook " + hook + " out of range. Expected a 32-bit signed integer.", loc);
    }
  }

  private void throwIfNotUnsignedInt(BigInteger i, String hook) {
    if (i.compareTo(BigInteger.ZERO) < 0 || i.compareTo(BigInteger.valueOf(Integer.MAX_VALUE)) > 0) {
      throw KEMException.compilerError("Argument to hook " + hook + " out of range. Expected a 32-bit unsigned integer.", loc);
    }
  }

  private String STRING_substr(String s, BigInteger start, BigInteger end) {
    throwIfNotInt(start, "STRING.substr");
    throwIfNotInt(end, "STRING.substr");
    try {
      return s.substring(s.offsetByCodePoints(0, start.intValue()), s.offsetByCodePoints(0, end.intValue()));
    } catch (IndexOutOfBoundsException e) {
      throw KEMException.compilerError("Argument to hook STRING.substr out of range. Expected two indices >= 0 and <= the length of the string.", e, loc);
    }
  }

  private BigInteger STRING_find(String haystack, String needle, BigInteger idx) {
    throwIfNotInt(idx, "STRING.find");
    int offset = haystack.offsetByCodePoints(0, idx.intValue());
    int foundOffset = haystack.indexOf(needle, offset);
    return BigInteger.valueOf((foundOffset == -1 ? -1 : haystack.codePointCount(0, foundOffset)));
  }

  private BigInteger STRING_rfind(String haystack, String needle, BigInteger idx) {
    throwIfNotInt(idx, "STRING.rfind");
    int offset = haystack.offsetByCodePoints(0, idx.intValue());
    int foundOffset = haystack.lastIndexOf(needle, offset);
    return BigInteger.valueOf((foundOffset == -1 ? -1 : haystack.codePointCount(0, foundOffset)));
  }

  private BigInteger STRING_findChar(String haystack, String needles, BigInteger idx) {
    throwIfNotInt(idx, "STRING.findChar");
    int offset = haystack.offsetByCodePoints(0, idx.intValue());
    int foundOffset = StringUtil.indexOfAny(haystack, needles, offset);
    return BigInteger.valueOf((foundOffset == -1 ? -1 : haystack.codePointCount(0, foundOffset)));
  }

  private BigInteger STRING_rfindChar(String haystack, String needles, BigInteger idx) {
    throwIfNotInt(idx, "STRING.findChar");
    int offset = haystack.offsetByCodePoints(0, idx.intValue());
    int foundOffset = StringUtil.lastIndexOfAny(haystack, needles, offset);
    return BigInteger.valueOf((foundOffset == -1 ? -1 : haystack.codePointCount(0, foundOffset)));
  }

  private String STRING_float2string(FloatBuiltin f) {
    return FloatBuiltin.printKFloat(f.bigFloatValue(), f.bigFloatValue()::toString);
  }

  private String STRING_floatFormat(FloatBuiltin f, String format) {
    return FloatBuiltin.printKFloat(f.bigFloatValue(), () -> f.bigFloatValue().toString(format));
  }
  
  private FloatBuiltin STRING_string2float(String s) {
    try {
      return FloatBuiltin.of(s);
    } catch (NumberFormatException e) {
      throw KEMException.compilerError("Argument to hook STRING.string2float invalid. Expected a valid floating point nuwber.", e, loc);
    }
  }

  private BigInteger STRING_string2int(String s) {
    try {
      return new BigInteger(s, 10);
    } catch (NumberFormatException e) {
      throw KEMException.compilerError("Argument to hook STRING.string2int invalid. Expected a valid integer.", e, loc);
    }
  }

  private String STRING_int2string(BigInteger i) {
    return i.toString();
  }

  private BigInteger STRING_string2base(String s, BigInteger base) {
    if (base.compareTo(BigInteger.valueOf(2)) < 0 || base.compareTo(BigInteger.valueOf(36)) > 0) {
      throw KEMException.compilerError("Argument to hook STRING.string2base out of range. Expected a number between 2 and 36.", loc);
    }
    try {
      return new BigInteger(s, base.intValue());
    } catch (NumberFormatException e) {
      throw KEMException.compilerError("Argument to hook STRING.string2base invalid. Expected a valid integer in base " + base.intValue() + ".", e, loc);
    }
  }
  
  private String STRING_base2string(BigInteger i, BigInteger base) {
    if (base.compareTo(BigInteger.valueOf(2)) < 0 || base.compareTo(BigInteger.valueOf(36)) > 0) {
      throw KEMException.compilerError("Argument to hook STRING.string2base out of range. Expected a number between 2 and 36.", loc);
    }
    return i.toString(base.intValue());
  }

  private String STRING_replaceAll(String haystack, String needle, String replacement) {
    return StringUtils.replace(haystack, needle, replacement);
  }

  private String STRING_replace(String haystack, String needle, String replacement, BigInteger times) {
    throwIfNotInt(times, "STRING.replace");
    return StringUtils.replace(haystack, needle, replacement, times.intValue());
  }

  private String STRING_replaceFirst(String haystack, String needle, String replacement) {
    return StringUtils.replaceOnce(haystack, needle, replacement);
  }

  private BigInteger STRING_countAllOccurrences(String haystack, String needle) {
    return BigInteger.valueOf(StringUtils.countMatches(haystack, needle));
  }

  private boolean STRING_eq(String a, String b) {
    return a.equals(b);
  }

  private boolean STRING_ne(String a, String b) {
    return !a.equals(b);
  }

  private boolean STRING_lt(String a, String b) {
    return a.compareTo(b) < 0;
  }

  private boolean STRING_gt(String a, String b) {
    return a.compareTo(b) > 0;
  }

  private boolean STRING_le(String a, String b) {
    return a.compareTo(b) <= 0;
  }

  private boolean STRING_ge(String a, String b) {
    return a.compareTo(b) >= 0;
  }

  private BigInteger INT_not(BigInteger a) {
    return a.not();
  }

  private BigInteger INT_pow(BigInteger a, BigInteger b) {
    throwIfNotUnsignedInt(b, "INT.pow");
    return a.pow(b.intValue());
  }

  private BigInteger INT_powmod(BigInteger a, BigInteger b, BigInteger c) {
    try {
      return a.modPow(b, c);
    } catch(ArithmeticException e) {
      throw KEMException.compilerError("Argument to hook INT.powmod is invalid. Modulus must be positive and negative exponents are only allowed when value and modulus are relatively prime.", e, loc);
    }
  }

  private BigInteger INT_mul(BigInteger a, BigInteger b) {
    return a.multiply(b);
  }

  private BigInteger INT_tdiv(BigInteger a, BigInteger b) {
    if (b.compareTo(BigInteger.ZERO) == 0) {
      throw KEMException.compilerError("Division by zero.", loc);
    }
    return a.divide(b);
  }

  private BigInteger INT_tmod(BigInteger a, BigInteger b) {
    if (b.compareTo(BigInteger.ZERO) == 0) {
      throw KEMException.compilerError("Modulus by zero.", loc);
    }
    return a.remainder(b);
  }

  private BigInteger INT_ediv(BigInteger a, BigInteger b) {
    return a.subtract(a.mod(b)).divide(b);
  }

  private BigInteger INT_emod(BigInteger a, BigInteger b) {
    return a.mod(b);
  }

  private BigInteger INT_add(BigInteger a, BigInteger b) {
    return a.add(b);
  }

  private BigInteger INT_sub(BigInteger a, BigInteger b) {
    return a.subtract(b);
  }

  private BigInteger INT_shr(BigInteger a, BigInteger b) {
    throwIfNotUnsignedInt(b, "INT.shr");
    return a.shiftRight(b.intValue());
  }

  private BigInteger INT_shl(BigInteger a, BigInteger b) {
    throwIfNotUnsignedInt(b, "INT.shl");
    return a.shiftLeft(b.intValue());
  }

  private BigInteger INT_and(BigInteger a, BigInteger b) {
    return a.and(b);
  }

  private BigInteger INT_xor(BigInteger a, BigInteger b) {
    return a.xor(b);
  }

  private BigInteger INT_or(BigInteger a, BigInteger b) {
    return a.or(b);
  }

  private BigInteger INT_min(BigInteger a, BigInteger b) {
    return a.min(b);
  }

  private BigInteger INT_max(BigInteger a, BigInteger b) {
    return a.max(b);
  }

  private BigInteger INT_abs(BigInteger a) {
    return a.abs();
  }

  private BigInteger INT_log2(BigInteger a) {
    if (a.compareTo(BigInteger.ZERO) <= 0) {
      throw KEMException.compilerError("Argument to hook INT.log2 out of range. Expected a positive integer.", loc);
    }
    int log2 = 0;
    while (a.compareTo(BigInteger.ONE) > 0) {
      a = a.shiftRight(1);
      log2++;
    }
    return BigInteger.valueOf(log2);
  }

  private BigInteger INT_bitRange(BigInteger i, BigInteger index, BigInteger length) {
    throwIfNotUnsignedInt(index, "INT.bitRange");
    throwIfNotUnsignedInt(length, "INT.bitRange");
    byte[] twosComplement = i.toByteArray();
    BigInteger positive = new BigInteger(1, twosComplement);
    for (int j = 0; j < index.intValue(); j++) {
      i = i.clearBit(j);
    }
    for (int j = index.intValue() + length.intValue(); j < twosComplement.length * 8; j++) {
      i = i.clearBit(j);
    }
    return i;
  }

  private BigInteger INT_signExtendBitRange(BigInteger i, BigInteger index, BigInteger length) {
    throwIfNotUnsignedInt(index, "INT.signExtendBitRange");
    throwIfNotUnsignedInt(length, "INT.signExtendBitRange");
    if (length.intValue() == 0) {
      return BigInteger.ZERO;
    }
    if (i.testBit(index.intValue() + length.intValue() - 1)) {
      BigInteger max = BigInteger.ONE.shiftLeft(length.intValue() - 1);
      BigInteger tmp = INT_bitRange(i, index, length);
      tmp = tmp.add(max);
      tmp = INT_bitRange(tmp, BigInteger.ZERO, length);
      tmp = tmp.subtract(max);
      return tmp;
    } else {
      return INT_bitRange(i, index, length);
    }
  }

  private boolean INT_lt(BigInteger a, BigInteger b) {
    return a.compareTo(b) < 0;
  }

  private boolean INT_gt(BigInteger a, BigInteger b) {
    return a.compareTo(b) > 0;
  }

  private boolean INT_le(BigInteger a, BigInteger b) {
    return a.compareTo(b) <= 0;
  }

  private boolean INT_ge(BigInteger a, BigInteger b) {
    return a.compareTo(b) >= 0;
  }

  private boolean INT_eq(BigInteger a, BigInteger b) {
    return a.equals(b);
  }

  private boolean INT_ne(BigInteger a, BigInteger b) {
    return !a.equals(b);
  }

}