---
copyright: Copyright (c) Runtime Verification, Inc. All Rights Reserved.
---

# Lesson 1.5: Modules, Imports, and Requires

In this lesson you will learn how K definitions can be broken into separate 
modules and files and how these distinct components combine into a complete K 
definition.

## K's outer syntax

Recall from [Lesson 1.3](../03_parsing/README.md) that K's grammar is composed
of two parts: **outer syntax** and **inner syntax**. Outer syntax, as 
previously mentioned, consists of **requires**, **modules**, **imports**, and 
**sentences**. A K semantics is expressed by the set of sentences contained in 
the definition. The scope of what is considered contained in that definition 
is determined both by the **main semantics module** of a K definition, as well 
as the **requires** and **imports** present in the file that contains that 
module.

## Basic module syntax

The basic unit of grouping sentences in K is the module. A module consists
of a **module name**, and optionally, a list of **attributes**, a list of
**imports**, or a list of **sentences**.

A module name consists of one or more groups of letters, numbers, or
underscores, separated by a hyphen. Here are some valid module names: `FOO`,
`FOO-BAR`, `foo0`, `foo0_bar-Baz9`. Here are some invalid module names: `-`,
`-FOO`, `BAR-`, `FOO--BAR`. Stylistically, modules names are usually all
uppercase with hyphens separating words, but this is not strictly enforced.

Some module examples include:

* an empty module:

```k
module LESSON-05-A

endmodule
```

* a module with some attributes:

```k
module LESSON-05-B [group(attr1,attr2), private]

endmodule
```

* a module with some sentences:

```k
module LESSON-05-C

  syntax Boolean ::= "true" | "false"
  syntax Boolean ::= "not" Boolean [function]

  rule not true => false
  rule not false => true

endmodule
```

TODO: We will discuss the new concepts in due time ...

## Imports

Thus far we have only seen definitions containing a single module.
However, definitions in K can also contain multiple modules, in which one 
module imports others.

An import in K appears after the module name and prior to any sentences. It 
is specified with the `imports` keyword, followed by a module name.

For example, below we have a definition with two modules (`lesson-05-d.k`):

```k
module LESSON-05-D-1

  syntax Boolean ::= "true" | "false"
  syntax Boolean ::= "not" Boolean [function]

endmodule

module LESSON-05-D

  imports LESSON-05-D-1

  rule not true => false
  rule not false => true

endmodule
```

Modules can be written in any order, it is not a requirement that the imported 
modules be specified before other modules importing them. What it is
required is that the module provided to attribute `--main-module` is not
imported by any other module.

Let's return to the K definition in `lesson-05-d.k` above. Note that it is
equivalent to the definition expressed by the single module `LESSON-05-C`.
Essentially, by importing module `A` into module `B`, we include all sentences
in module `A` into module `B`. Note that K distinguishes between importing a 
module and simply including its sentences in another module directly. We 
will discuss these differences in Lesson [XYZ]().
For now, you can think of modules as a way of conceptually grouping sentences 
in a larger K definition.

### Exercise

Modify `lesson-05-d.k` to include four modules: one containing the syntax, two
with one rule each that imports the first module, and a final module
`LESSON-05-D` containing no sentences that imports the second and third module.
Make sure the definition still compiles and that you can still evaluate the 
`not` function.

## Parsing multiple modules

As you may have noticed, each module in a definition can express a **distinct** 
set of syntax. When parsing the sentences in a module, we use the syntax
**of that module**, enriched with the basic syntax of K. For example, the 
following definition is a parser error (`lesson-05-e.k`):

```{.k .error}
module LESSON-05-E-1

  rule not true => false
  rule not false => true

endmodule

module LESSON-05-E-2

  syntax Boolean ::= "true" | "false"
  syntax Boolean ::= "not" Boolean [function]

endmodule
```

This is because the syntax referenced in module `LESSON-05-E-1`, namely, `not`,
`true`, and `false`, is not imported by that module. You can solve this problem
by simply importing the modules containing the syntax you want to use in your
sentences.

## Main syntax and semantics modules

When we are compiling a K definition, we need to know where to start. We
designate two specific **entry point modules**: the **main syntax module**
and the **main semantics module**. The main syntax module, together with all 
the modules it imports recursively, are used to generate the parser you execute
with `kast`. The main semantics module, together with all the modules it 
imports recursively, are used to generate the interpreter you execute with 
`krun`. Take for example, the definition in `lesson-05-d.k`. If the main 
semantics module is module `LESSON-05-D-1`, then `not` is an uninterpreted 
function (i.e., has no rules associated with it) as the rules in module 
`LESSON-05-D` are not included.

You can specify the entry point modules explicitly by passing the flags
`--main-module` (for the main semantics module) and `--syntax-module` (for the 
main syntax module) to `kompile`. However, by default, if you run 
`kompile foo.k`, then the main semantics module will be `FOO` and the
main syntax module will be `FOO-SYNTAX`. This is the explanation behind the
warning you get when running `kompile` with no flags specified.

TODO: Order of imports doesn't matter accross a single-file K definition.
It is a requirement that the main module is not imported by any other module.

## Splitting a definition into multiple files

So far, we have discussed ways to split definitions into separate conceptual 
components&mdash;modules. However, K also provides a mechanism for combining
multiple files into a single K definition, namely, through the **requires** 
directive.

In K, the `requires` keyword has two meanings. The first is represented by the 
**requires** statement which appears at the top of a K file, prior to any 
module declarations. It consists of the keyword `requires` followed by a 
double-quoted string. The second meaning of the `requires` keyword relates to
side conditioning in rules and you will learn more about it in
[Lesson 1.7](../07_side_conditions/README.md).

The double quoted string passed to the **requires** statement contains a 
filename. When you run `kompile` on a file, it will look at all of the 
`requires` statements in that file, search those files on disk, parse them, 
and then recursively process all the **requires** statements in those files. 
It then combines all the modules in all of those files together, and uses 
them collectively as the set of modules to which `imports` statements can 
refer.

## Putting it all together

Recall the definition in file `lesson-02-c.k` from 
[Lesson 1.2](../02_basics/README.md). One way of splitting it into multiple 
files and modules is the following:

- `colors.k`:

```k
module COLORS

  syntax Color ::= Yellow()
                 | Blue()

endmodule
```

- `fruits.k`:

```k
module FRUITS

  syntax Fruit ::= Banana()
                 | Blueberry()

endmodule
```

- `colorOf.k`:

```{.k .exclude}
requires "fruits.k"
requires "colors.k"

module COLOROF-SYNTAX

  imports COLORS
  imports FRUITS

  syntax Color ::= colorOf(Fruit) [function]

endmodule

module COLOROF

  imports COLOROF-SYNTAX

  rule colorOf(Banana()) => Yellow()
  rule colorOf(Blueberry()) => Blue()

endmodule
```

You would then compile this definition with `kompile colorOf.k` and use it the
same way as the original, single-module definition.

### Exercise

Modify the name of the `COLOROF` module, and then recompile the definition.
Try to understand why you now get a compiler error. Then, resolve this compiler
error by passing the `--main-module` and `--syntax-module` flags to `kompile`.

## Include path

Paths specified for `requires` statements can be absolute or relative. If the 
path is absolute, that exact file is imported. If the path is relative, a 
matching file is searched within all the **include directories** specified to 
the compiler. By default, the include directories comprise the current working
directory, followed by the `include/kframework/builtin` directory within your 
installation of K. You can also pass one or more directories to `kompile` via 
the `-I` flag, in which case these directories are prepended to the beginning 
of the list.

## Exercises

1. Take the solution to Exercise 2 in Lesson 1.4 which included the explicit
priority and associativity declarations, and modify the definition so that
the syntax of integers and brackets is in one module, the syntax of addition,
subtraction, and unary negation is in another module, and the syntax of
multiplication and division is in a third module. Make sure you can still parse
the same set of expressions as before. Place priority declarations in the main
module.

2. Modify `lesson-02-d.k` from Lesson 1.2 so that the rules and syntax are in
separate modules in separate files.

3. Place the file containing the syntax from Exercise 2 in another directory,
then recompile the definition. Observe why a compilation error occurs. Then
fix the compiler error by passing `-I` to `kompile`.

## Next lesson

Once you have completed the above exercises, you can continue to
[Lesson 1.6: Integers and Booleans](../06_ints_and_bools/README.md).
