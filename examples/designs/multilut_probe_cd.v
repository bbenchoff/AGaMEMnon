module top(input a, input b, input c, input d, output o);
  wire ab_xor, cd_xor;
  (* keep *) LUT #(.K(4), .INIT(16'h6666)) u_ab (.I({2'b00, b, a}), .Q(ab_xor));
  (* keep *) LUT #(.K(4), .INIT(16'h6666)) u_cd (.I({2'b00, d, c}), .Q(cd_xor));
  // Keep both upstream legs routed, but observe the slice4 -> slice0 leg alone.
  (* keep *) LUT #(.K(4), .INIT(16'hCCCC)) u_both (.I({2'b00, cd_xor, ab_xor}), .Q(o));
endmodule
