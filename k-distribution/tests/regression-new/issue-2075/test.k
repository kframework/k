module TEST
  imports INT

  configuration <k> $PGM:K </k>
                <foo> 0 </foo>

  configuration <bar> 1 </bar>

  rule <k> I:Int => initBarCell ...</k>
       <foo> I </foo>
endmodule
