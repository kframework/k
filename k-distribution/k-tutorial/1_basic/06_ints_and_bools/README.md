---
copyright: Copyright (c) Runtime Verification, Inc. All Rights Reserved.
---

# Lesson 1.6: Integers and Booleans

In this lesson you will learn about the two most basic types of built-in
sorts in K: `Int` and `Bool`, representing **arbitrary-precision integers** 
and **Boolean algebra**, respectively. You will also learn how to look up 
more detailed knowledge in K's documentation.

## Built-in sorts in K

K provides built-in sorts for the most common types. You can find the full 
list of definitions in file
[domains.md](../../../include/kframework/builtin/domains.md) within the
`include/kframework/builtin` directory of your K installation. Note that 
the file is defined via a 
[Literate programming](https://en.wikipedia.org/wiki/Literate_programming)
style that you will learn more about in 
[Lesson 1.8](../08_literate_programming/README.md). 
In this lesson, we won't cover all the sorts presented in `domains.md`,
but focus instead on two: integers and Booleans.


## Booleans in K

The most basic built-in sort K provides is the `Bool` sort, representing
Boolean values (i.e., `true` and `false`). You have already seen how we can
define this type ourselves using K's parsing and disambiguation features. 
However, most of the time, we prefer instead to use the version of Boolean 
algebra defined by K itself. It resides in module `BOOL` and you can simply 
import it in your definition when you need it. Consider, for example, the 
code in `lesson-06-a.k` below:

```k
module LESSON-06-A

  imports BOOL

  syntax Fruit ::= Blueberry() | Banana()
  syntax Bool ::= isBlue(Fruit) [function]

  rule isBlue(Blueberry()) => true
  rule isBlue(Banana()) => false

endmodule
```

Here we define a simple **predicate**, i.e., a function returning a Boolean 
value, called `isBlue`. The function takes a `Fruit` constructor and returns
`true` or `false`. Now, we are able to perform the usual Boolean operations 
of AND, OR, and NOT over these values. For example (`lesson-06-b.k`):

```k
module LESSON-06-B

  imports BOOL

  syntax Fruit ::= Blueberry() | Banana()
  syntax Bool ::= isBlue(Fruit) [function]

  rule isBlue(Blueberry()) => true
  rule isBlue(Banana()) => false

  syntax Bool ::= isYellow(Fruit) [function]
                | isBlueOrYellow(Fruit) [function]

  rule isYellow(Banana()) => true
  rule isYellow(Blueberry()) => false

  rule isBlueOrYellow(F) => isBlue(F) orBool isYellow(F)

endmodule
```

In this definition, Boolean OR is performed via the `orBool` function, which is 
defined in the `BOOL` module. 

In general, functions over built-in sorts in K are suffixed with the name of 
the primary sort over which those functions are defined, e.g., `orBool` for 
Boolean OR and `+Int` for integer addition. This convention is used to prevent 
the syntax of K from conflicting with the syntax of other programming 
languages. Without it, defining those programming languages in K would be 
harder.

### Exercise

Write a function `isBlueAndNotYellow` which computes the appropriate Boolean
expression. If you are unsure about the appropriate syntax, you can refer to 
the `BOOL` module in
[domains.md](../../../include/kframework/builtin/domains.md). Add a term of
sort `Fruit` for which `isBlue` and `isYellow` both return true, and test that
the `isBlueAndNotYellow` function behaves as expected on all three `Fruit`s.

### Syntax modules

For most sorts in `domains.md`, K defines more than one module that can be
imported by users. For example, for the `Bool` sort, K defines the `BOOL`
module that we have previously discussed, but also provides the `BOOL-SYNTAX` 
module. This module, unlike the `BOOL` module, only declares values `true` 
and `false`, but none of the functions that operate over the `Bool` sort. 
The rationale is that you may want to import this module into the main syntax 
module of your definition in some cases, whereas you generally do
not want to do this with the version of the module that includes _all_ the
functions over the `Bool` sort. For example, if you were defining the semantics
of C++, you might import `BOOL-SYNTAX` into the syntax module of your
definition, because `true` and `false` are part of the grammar of C++, but
you would only import the `BOOL` module into the main semantics module, because
C++ defines its own syntax for AND, OR, and NOT that is different from the
syntax defined in the `BOOL` module.

Check the code in `lesson-06-c.k` below which redefines the Boolean expression
calculator from [Lesson 1.3](../03_parsing/README.md) to use the predefined 
`Bool` sort:

```k
module LESSON-06-C-SYNTAX

  imports BOOL-SYNTAX

  syntax Bool ::= "(" Bool ")" [bracket]
                > "!" Bool [function]
                > left:
                  Bool "&&" Bool [function]
                | Bool "^" Bool [function]
                | Bool "||" Bool [function]

endmodule

module LESSON-06-C

  imports LESSON-06-C-SYNTAX
  imports BOOL

  rule ! B => notBool B
  rule A && B => A andBool B
  rule A ^ B => A xorBool B
  rule A || B => A orBool B

endmodule
```

Note the syntax encapsulation: the `LESSON-06-C-SYNTAX` module imports only
module `BOOL-SYNTAX` and it contains exactly the syntax of our Boolean 
expressions, and no more. Any other syntax needed to implement those 
functions is defined in the `LESSON-06-C` module instead. Here, we import  
module `BOOL` because we use the predefined Boolean operations to define the
ones in our syntax.

#### Exercise

Add a function for Boolean IMPLIES to the expression calculator above using 
the `->` symbol to represent implication. You can look up K's built-in 
IMPLIES function in the `BOOL` module in `domains.md`.

## Integers in K

In most programming languages, the most basic integer type is a 
fixed-precision integer type. However, in K, the most commonly used integer
sort is the `Int` sort, which represents the **mathematical** integers, i.e.,
arbitrary-precision integers.

K provides three main modules for the `Int` sort:
- `INT` module contains the whole syntax of integers, as well as all 
  functions over integers.
- `INT-SYNTAX` module provides just the syntax over integer literals.
- `UNSIGNED-INT-SYNTAX` module only provides the syntax of **non-negative
  integers**, i.e., natural numbers.

The use of a separate module for natural numbers may seem redundant. However,
the reasons for it involve lexical ambiguity. In most programming languages,
`-1` is not a literal _per se_, but a literal to which the unary negation 
operator is applied. Thus, by having a separate `UNSIGNED-INT-SYNTAX` module,
K facilitates specifying the syntax of such languages.

For detailed information about the functions available over the `Int` sort,
you can refer to `domains.md`. Note again how we append `Int` to the end of 
most of the integer operations, e.g., `+Int` or `-Int`, to ensure they do not 
collide with the syntax of other programming languages.

## Exercises

1. Extend your solution from Lesson 1.4, Exercise 2 to implement the rules
that define the behavior of addition, subtraction, multiplication, and
division. Do not worry about the case when the user tries to divide by zero
at this time. Use `/Int` to implement division. Test your new calculator
implementation by executing the arithmetic expressions you wrote as part of
Lesson 1.3, Exercise 2. Check to make sure each computes the value you 
expected.

2. Combine the Boolean expression calculator from this lesson with your
solution to Exercise 1, and then extend the combined calculator with the `<`,
`<=`, `>`, `>=`, `==`, and `!=` expressions. Write some Boolean expressions
that combine integer and Boolean operations, and test to ensure that these
expressions return the expected truth value.

3. Compute the following expressions using your solution from Exercise 2:
`7 / 3`, `7 / -3`, `-7 / 3`, `-7 / -3`. Then replace the `/Int` function in
your definition with `divInt` instead, and observe how the value of the above
expressions changes. Why does this occur?

## Next lesson

Once you have completed the above exercises, you can continue to
[Lesson 1.7: Side Conditions and Rule Priority](../07_side_conditions/README.md).
