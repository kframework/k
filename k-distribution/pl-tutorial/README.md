# K PL Tutorial

Here you will learn how to use the K tool to define languages by means of a series of screencast movies. It is recommended to do these in the indicated order, because K features already discussed in a previous language definition will likely not be rediscussed in latter definitions. The screencasts follow quite closely the structure of the files under the [tutorial folder](https://github.com/kframework/k/tree/master/k-distribution/pl-tutorial) in the K tool distribution. If you'd rather follow the instructions there and do the tutorial exercises yourself, then go back to https://kframework.org and download the K tool, if you have not done it already. Or, you can first watch the screencasts below and then do the exercises, or do them in parallel.

## K Overview

Make sure you watch the K overview video before you do the K tutorial:

- [9'59"] [K Overview](../../overview.md)

## Learning K

### [34'46"]   Part 1: Defining LAMBDA

Here you will learn how to define a very simple functional language in K and the basics of how to use the K tool. The language is a call-by-value variant of lambda calculus with builtins and mu, and its definition is based on substitution.

- [04'07"]   [Lesson 1, LAMBDA: Syntax Modules and Basic K Commands](./1_k/1_lambda/lesson_1/README.md)
- [04'03"]   [Lesson 2, LAMBDA: Module Importing, Rules, Variables](./1_k/1_lambda/lesson_2/README.md)
- [02'20"]   [Lesson 3, LAMBDA: Evaluation Strategies using Strictness](./1_k/1_lambda/lesson_3/README.md)
- [03'13"]   [Lesson 4, LAMBDA: Generating Documentation; Latex Attributes](./1_k/1_lambda/lesson_4/README.md)
- [04'52"]   [Lesson 5, LAMBDA: Adding Builtins; Side Conditions](./1_k/1_lambda/lesson_5/README.md)
- [02'14"]   [Lesson 6, LAMBDA: Selective Strictness; Anonymous Variables](./1_k/1_lambda/lesson_6/README.md)
- [05'10"]   [Lesson 7, LAMBDA: Derived Constructs; Extending Predefined Syntax](./1_k/1_lambda/lesson_7/README.md)
- [02'40"]   [Lesson 8, LAMBDA: Multiple Binding Constructs](./1_k/1_lambda/lesson_8/README.md) (uncommented)
- [06'07"]   [Lesson 9, LAMBDA: A Complete and Commented Definition](./1_k/1_lambda/lesson_9/README.md) (commented)

###  [37'07"]   Part 2: Defining IMP

Here you will learn how to define a very simple, prototypical textbook C-like imperative language, called IMP, and several new features of the K tool.

- [09'15"]   [Lesson 1, IMP: Defining a More Complex Syntax](./1_k/2_imp/lesson_1/README.md)
- [04'21"]   [Lesson 2, IMP: Defining a Configuration](./1_k/2_imp/lesson_2/README.md)
- [10'30"]   [Lesson 3, IMP: Computations, Results, Strictness; Rules Involving Cells](./1_k/2_imp/lesson_3/README.md)
- [09'16"]   [Lesson 4, IMP: Configuration Abstraction, Part 1; Types of Rules](./1_k/2_imp/lesson_4/README.md)
- [03'45"]   [Lesson 5, IMP: Completing and Documenting IMP](./1_k/2_imp/lesson_5/README.md)

### [33'10"]   Part 3: Defining LAMBDA++

Here you will learn how to define constructs which abruptly change the execution control, as well as how to define functional languages using environments and closures. LAMBDA++ extends the LAMBDA language above with a callcc construct.

- [06'28"]   [Lesson 1, LAMBDA++: Abrupt Changes of Control](./1_k/3_lambda++/lesson_1/README.md) (substitution-based, uncommented)
- [08'02"]   [Lesson 2, LAMBDA++: Semantic (Non-Syntactic) Computation Items](./1_k/3_lambda++/lesson_2/README.md)
- [03'21"]   [Lesson 3, LAMBDA++: Reusing Existing Semantics](./1_k/3_lambda++/lesson_3/README.md)
- [03'37"]   [Lesson 4, LAMBDA++: Do Not Reuse Blindly!](./1_k/3_lambda++/lesson_4/README.md)
- [05'19"]   [Lesson 5, LAMBDA++: More Semantic Computation Items](./1_k/3_lambda++/lesson_5/README.md)
- [06'23"]   [Lesson 6, LAMBDA++: Wrapping Up and Documenting LAMBDA++ (environment-based)](./1_k/3_lambda++/lesson_6/README.md)


### [46'46"]   Part 4: Defining IMP++

Here you will learn how to refine configurations, how to generate fresh elements, how to tag syntactic constructs and rules, how to exhaustively search the space of non-deterministic or concurrent program executions, etc. IMP++ extends the IMP language above with increment, blocks and locals, dynamic threads, input/output, and abrupt termination.

- [07'47"]   [Lesson 1, IMP++: Extending/Changing an Existing Language Syntax](./1_k/4_imp++/lesson_1/README.md)
- [04'06"]   [Lesson 2, IMP++: Configuration Refinement; Freshness](./1_k/4_imp++/lesson_2/README.md)
- [06'56"]   [Lesson 3, IMP++: Tagging; Superheat/Supercool Kompilation Options](./1_k/4_imp++/lesson_3/README.md)
- [05'21"]   [Lesson 4, IMP++: Semantic Lists; Input/Output Streaming](./1_k/4_imp++/lesson_4/README.md)
- [04'30"]   [Lesson 5, IMP++: Deleting, Saving and Restoring Cell Contents](./1_k/4_imp++/lesson_5/README.md)
- [11'40"]   [Lesson 6, IMP++: Adding/Deleting Cells Dynamically; Configuration Abstraction, Part 2](./1_k/4_imp++/lesson_6/README.md)
- [??'??"]   [Lesson 7, IMP++: Everything Changes: Syntax, Configuration, Semantics](./1_k/4_imp++/lesson_7/README.md)
- [06'26"]   [Lesson 8, IMP++: Wrapping up Larger Languages](./1_k/4_imp++/lesson_8/README.md)

### [17'03"]   Part 5: Defining Type Systems

Here you will learn how to define various kinds of type systems following various approaches or styles using K.

- [10'11"]   [Lesson 1, Type Systems: Imperative, Environment-Based Type Systems](./1_k/5_types/lesson_1/README.md) (IMP++ type checker)
- [06'52"]   [Lesson 2, Type Systems: Substitution-Based Higher-Order Type Systems](./1_k/5_types/lesson_2/README.md) (LAMBDA type checker, substitution, uncommented)
- [??'??"]   [Lesson 3, Type Systems: Environment-Based Higher-Order Type Systems](./1_k/5_types/lesson_3/README.md) (LAMBDA type checker, environment, uncommented)
- [??'??"]   [Lesson 4, Type Systems: A Naive Substitution-Based Type Inferencer](./1_k/5_types/lesson_4/README.md) (for LAMBDA, uncommented)
- [??'??"]   [Lesson 5, Type Systems: A Naive Environment-Based Type Inferencer](./1_k/5_types/lesson_5/README.md) (for LAMBDA, uncommented)
- [??'??"]   [Lesson 6, Type Systems: Parallel Type Checkers/Inferencers](./1_k/5_types/lesson_6/README.md) (for LAMBDA, uncommented)
- [??'??"]   [Lesson 7, Type Systems: A Naive Substitution-based Polymorphic Type Inferencer](./1_k/5_types/lesson_7/README.md) (for LAMBDA, uncommented)
- [??'??"]   [Lesson 8, Type Systems: A Naive Environment-based Polymorphic Type Inferencer](./1_k/5_types/lesson_8/README.md) (for LAMBDA, uncommented)
- [??'??"]   [Lesson 9, Type Systems: Let-Polymorphic Type Inferencer (Damas-Hindley-Milner)](./1_k/5_types/lesson_9/README.md) (for LAMBDA, uncommented)

### [??'??"]   Part 6: Miscellaneous Other K Features

Here you will learn a few other K features, and better understand how features that you have already seen work.

- [??'??"]   ...

## Learning Language Design and Semantics using K

### [??'??"]   Part 7: SIMPLE: Designing Imperative Programming Languages

Here you will learn how to design imperative programming languages using K. SIMPLE is an imperative language with functions, threads, pointers, exceptions, multi-dimensional arrays, etc. We first define an untyped version of SIMPLE, then a typed version. For the typed version, we define both a static and a dynamic semantics.

- [??'??"]   [Lesson 1, SIMPLE untyped](./2_languages/1_simple/1_untyped/simple-untyped.md)
- [??'??"]   [Lesson 2, SIMPLE typed static](./2_languages/1_simple/2_typed/1_static/simple-typed-static.md)
- [??'??"]   [Lesson 3, SIMPLE typed dynamic](./2_languages/1_simple/2_typed/2_dynamic/simple-typed-dynamic.md)

###  [??'??"]   Part 8: KOOL: Designing Object-Oriented Programming Languages

Here woul will learn how to design object-oriented programming languages using K. KOOL is an object-oriented language that extends SIMPLE with classes and objects. We first define an untyped version of KOOL, then a typed version, with both a dynamic and a static semantics.

- [??'??"]   [Lesson 1, KOOL untyped](./2_languages/2_kool/1_untyped/kool-untyped.md)
- [??'??"]   [Lesson 2, KOOL typed dynamic](./2_languages/2_kool/2_typed/1_dynamic/kool-typed-dynamic.md)
- [??'??"]   [Lesson 3, KOOL typed static](./2_languages/2_kool/2_typed/2_static/kool-typed-static.md)

### [??'??"]   Part 9: FUN: Designing Functional Programming Languages
H
ere woul will learn how to design functional programming languages using K. FUN is a higher-order functional language with general let, letrec, pattern matching, references, lists, callcc, etc. We first define an untyped version of FUN, then a let-polymorphic type inferencer.

- [??'??"]   [Lesson 1, FUN untyped, Environment-Based](./2_languages/3_fun/1_untyped/1_environment/fun-untyped.md)
- [??'??"]   [Lesson 2, FUN untyped, Substitution-Based](./2_languages/3_fun/1_untyped/2_substitution/fun-untyped.md)
- [??'??"]   Lesson 3, FUN polymorphic type inferencer

### [??'??"]   Part 10: LOGIK: Designing Logic Programming Languages

Here you will learn how to design a logic programming language using K.

- [??'??"]   [Lesson 1, LOGIK](./2_languages/4_logik/basic/logik.md)
