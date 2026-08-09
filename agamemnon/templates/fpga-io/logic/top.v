(* top *) module top(output wire [3:0] led);
    // Preserve four physical LUT drivers so the cold build exercises every
    // qualified onboard LED corridor. This deliberately has no state: generic
    // wide counters exceed the release's four exact direct-D sites.
    (* keep *) LUT #(.K(4), .INIT(16'hFFFF)) led0(.I(4'b0000), .Q(led[0]));
    (* keep *) LUT #(.K(4), .INIT(16'h0000)) led1(.I(4'b0000), .Q(led[1]));
    (* keep *) LUT #(.K(4), .INIT(16'hFFFF)) led2(.I(4'b0000), .Q(led[2]));
    (* keep *) LUT #(.K(4), .INIT(16'h0000)) led3(.I(4'b0000), .Q(led[3]));
endmodule
