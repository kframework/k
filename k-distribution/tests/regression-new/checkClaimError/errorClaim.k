// Copyright (c) 2021 K Team. All Rights Reserved.

module ERRORCLAIM-SYNTAX
    imports INT

    syntax Int ::= "foo"
    rule foo => 3 [macro]

    syntax Pgm ::= doIt ( Int )
    syntax Pgm ::= addCounter ( Int )
endmodule

module ERRORCLAIM
    imports ERRORCLAIM-SYNTAX

    configuration <k> $PGM:Pgm </k> <counter> 1 </counter> <sum> 0 </sum>

    rule <k> addCounter(0) => . ... </k>
    rule  <k> addCounter(Times:Int => Times -Int 1) ...</k>
          <counter> C:Int => C +Int 1 </counter>
          <sum> S:Int => S +Int C </sum>
      requires Times >Int 0

    rule <k> doIt(I => I -Int 1) ... </k> requires I >Int 0
endmodule
