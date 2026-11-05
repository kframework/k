---
copyright: Copyright (c) Runtime Verification, Inc. All Rights Reserved.
---

# Lesson 1.7: Side Conditions and Rule Priority

In this lesson you will learn how to write conditional rules in K and how to 
control the order in which rules are tried.

## Side conditions

So far, all rules we have discussed have been **unconditional**: if the 
left-hand side of the rule matches the arguments to the function, the
rule applies _always_. However, K allows to specify **conditional rules**,
which also apply when the left-hand side of the rule matches the function 
arguments, but _only_ if the condition specified within is met.  You can 
think of **conditional rules** as cases of 
[piecewise functions](https://en.wikipedia.org/wiki/Piecewise_function), or
[patterns](https://www.haskell.org/tutorial/patterns.html) in Haskell.
They consist of a **rule body** containing the patterns to match, and a 
**side condition** representing a Boolean expression that must evaluate to 
`true` in order for the rule to apply.

Consider the following definition (`lesson-07-a.k`):

```k
module LESSON-07-A

  imports BOOL
  imports INT

  syntax Grade ::= "letter-A"
                 | "letter-B"
                 | "letter-C"
                 | "letter-D"
                 | "letter-F"
                 | gradeFromPercentile(Int) [function]

  rule gradeFromPercentile(I) => letter-A requires I >=Int 90

endmodule
```

In the code above, the `gradeFromPercentile` function takes a single integer
argument and evaluates to `letter-A` only if the argument passed is greater 
than or equal to 90: side condition `I >=Int 90`. 

Side conditions in K are introduced via the `requires` keyword immediately
following the rule body. Recall from [Lesson 1.5](../05_modules/README.md)
that `requires` has an additional meaning when used within a module.

As expected, the side condition is a Boolean expression on variables that 
appear on the left-hand side of the rule. Additionally, variables appearing 
in the side condition evaluate to the same value as variables appearing on 
the right-hand side. There are no surprises in the way conditioned rules are 
evaluated either: if the patterns on the left-hand side of the rule match the 
term being evaluated _and_ if the function in the side condition evaluates to 
`true`, then the rule applies.

### Exercise

Write a rule that evaluates `gradeFromPercentile` to `letter-B` if the 
argument to the function is in the range [80,90). Test that the function 
correctly evaluates various numbers between 80 and 100.

## Rule priority

By default, K does not enforce an order in which the rules of a function are 
tried, as all are assigned internally the same **priority**. It might not 
come yet obvious to why this is the case since we have only discussed 
functions so far in K, and a function is considered not well-defined if 
multiple rules for evaluating it are capable of evaluating the same arguments 
to different results. Yet, there is a reasoning behind this. In future 
lessons we will introduce other types of rules in K, some of which can be 
**non-deterministic**. It is because of this potential for nondeterminism 
that we don't enforce a strict order in which rules are attempted to be 
applied.

You may have noticed that this is different than how pattern matching is 
done, e.g., in Haskell. There, function evaluation proceeds in the syntactic 
order of the patterns. Patterns specified first are tried first. In K, this 
is not the case, and in certain situations, we may want a similar behavior. 
It is convenient to express an order on rule trial or even that a particular 
rule applies if no other rules for that function are applicable. We do the 
latter with `owise` rule attribute, and the former by setting rule priorities 
through `priority` attribute.

### `owise` attribute

As we mentioned above, K assigns by default all rules the same priority. 
That's why rules can be executed in any order and not in the syntactic order
they are introduced. However, by adding attribute `owise` to a rule, 
we express the fact that that particular rule can apply if no other rules 
could have been applied. Under the hood, K assigns `owise` rules a lower
priority and this makes them to be tried only after all the other, 
higher-priority rules have been tried and failed.

Take again the exercise above, handling `letter-B` grades. You probably 
solved it by adding a side condition containing _two_ Boolean checks 
`I >=Int 80` and `I <Int 90`, comparing yet again the percentile 
to 90, as we did in the rule for `letter-A` grades. We can more efficiently 
and more idiomatically write the `letter-B` case by using the `owise` 
attribute (`lesson-07-b.k`):

```k
module LESSON-07-B

  imports BOOL
  imports INT

  syntax Grade ::= "letter-A"
                 | "letter-B"
                 | "letter-C"
                 | "letter-D"
                 | "letter-F"
                 | gradeFromPercentile(Int) [function]

  rule gradeFromPercentile(I) => letter-A requires I >=Int 90
  rule gradeFromPercentile(I) => letter-B requires I >=Int 80 [owise]

endmodule
```

This rule is saying, "if all the other rules do not apply, then the grade is a
B if the percentile is greater than or equal to 80." Note here that we use both
a side condition and an `owise` attribute on the same rule. This is not
required (as we will see later), but it is allowed. What this means is that the
side condition is only tried if the other rules did not apply **and** the
left-hand side of the rule matched. You can even use more complex matching on
the left-hand side than simply a variable. More generally, you can also have
multiple higher-priority rules, or multiple `owise` rules. What this means in
practice is that all of the non-`owise` rules are tried first, in any order,
followed by all the `owise` rules, in any order.

#### Exercise

The grades `D` and `F` correspond to the percentile ranges [60, 70) and [0, 60)
respectively. Write another implementation of `gradeFromPercentile` which
handles only these cases, and uses the `owise` attribute to avoid redundant
Boolean comparisons. Test that various percentiles in the range [0, 70) are
evaluated correctly.

### `priority` attribute

As it happens, the `owise` attribute is a specific case of a more general
concept we call **rule priority**. 

Priorities in K are assigned an integer value. By default, rules are assigned
priority 50. `owise` rules, which are a specific case of this concept we
call **rule priority**, are given priority 200. However, it is also possible
to directly assign a numerical priority to a rule via the `priority` 
attribute, in which case any non-negative integer is valid.

Rules are tried in _increasing_ order of priority, starting with a rule with 
priority zero, and trying each increasing numerical value successively. 

Consider the code in `lesson-07-c.k` below depicting an alternative way of 
expressing the same two rules in the `gradeFromPercentile` function by means
of `priority` atttribute:

```k
module LESSON-07-C

  imports BOOL
  imports INT

  syntax Grade ::= "letter-A"
                 | "letter-B"
                 | "letter-C"
                 | "letter-D"
                 | "letter-F"
                 | gradeFromPercentile(Int) [function]

  rule gradeFromPercentile(I) => letter-A requires I >=Int 90 [priority(50)]
  rule gradeFromPercentile(I) => letter-B requires I >=Int 80 [priority(200)]

endmodule
```

Similarly, we can handle all grades only by means of `priority` attribute 
(`lesson-07-d.k`):

```k
module LESSON-07-D

  imports BOOL
  imports INT

  syntax Grade ::= "letter-A"
                 | "letter-B"
                 | "letter-C"
                 | "letter-D"
                 | "letter-F"
                 | gradeFromPercentile(Int) [function]

  rule gradeFromPercentile(I) => letter-A requires I >=Int 90 [priority(50)]
  rule gradeFromPercentile(I) => letter-B requires I >=Int 80 [priority(51)]
  rule gradeFromPercentile(I) => letter-C requires I >=Int 70 [priority(52)]
  rule gradeFromPercentile(I) => letter-D requires I >=Int 60 [priority(53)]
  rule gradeFromPercentile(_) => letter-F                     [priority(54)]

endmodule
```

or, by using `owise` as well:

```k
module LESSON-07-E

  ...

  rule gradeFromPercentile(I) => letter-A requires I >=Int 90 [priority(50)]
  rule gradeFromPercentile(I) => letter-B requires I >=Int 80 [priority(51)]
  rule gradeFromPercentile(I) => letter-C requires I >=Int 70 [priority(52)]
  rule gradeFromPercentile(I) => letter-D requires I >=Int 60 [priority(53)]
  rule gradeFromPercentile(_) => letter-F                     [owise]

endmodule
```

Note that we used `owise` without a side condition. As we said above, both
usages are allowed in K.

Note also that we have introduced a new piece of syntax&mdash;variable placeholder
`_`. As in Haskell or other functional languages, `_` does not bind a value 
that can be used on the right-hand side of the rule, or in a side condition,
it simply means "I don't care about this term."

In module `LESSON-07-E`, we have explicitly expressed the order in which the 
rules of function `gradeFromPercentile` are tried. Since they are tried in 
increasing numerical priority, we first try the rule with priority 50, then 
51, then 52, 53, and finally 54.

Because the rules have explicit priorities, their syntactic order does not 
matter, only the ascending order of their priority values. Also, priorities 
with same value are tried in any order. E.g., if we have two rules with 
priority 52, first rule with priority 50 is tried, then rule with priority 
51, then any of the rules with priority 52, then the other rule with priority 
52, and finally the other rules in ascending order of priorities.

As a final note, remember that if you assign a rule a priority higher than 200,
it will be tried **after** a rule with the `owise` attribute, and if you assign
a rule a priority less than 50, it will be tried **before** a rule with no
explicit priority.

## Exercises

1. Write a function `isEven` that returns whether an integer is an even number.
Use two rules and one side condition. The right-hand side of the rules should
be Boolean literals. Refer to
[domains.md](../../../include/kframework/builtin/domains.md) for the relevant
integer operations.

2. Modify the calculator application from Lesson 1.6, Exercise 2, so that 
division by zero will no longer make `krun` crash with a "Divison by zero" 
exception. Instead, make sure the `/` function does not match any of its rules 
if the denominator is zero.

3. Write your own implementation of `==`, `<`, `<=`, `>`, `>=` for integers and 
modify your solution from Exercise 2 to use it. You can use any arithmetic 
operations in the `INT` module, but do not use any built-in boolean functions 
for comparing integers.

    Hint: Use pattern matching and recursive definitions with rule priorities.

## Next lesson

Once you have completed the above exercises, you can continue to
[Lesson 1.8: Literate Programming with Markdown](../08_literate_programming/README.md).
