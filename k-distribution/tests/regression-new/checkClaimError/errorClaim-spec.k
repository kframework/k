// Copyright (c) 2020 K Team. All Rights Reserved.

module ERRORCLAIM-SPEC
    imports ERRORCLAIM

    rule <k> doIt(foo) => doIt(0) ... </k>
endmodule
