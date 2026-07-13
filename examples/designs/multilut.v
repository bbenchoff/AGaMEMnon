// Deliberately preserved three-LUT dependency chain for physical placement/routing validation.
// The explicit LUT cells make this a backend acceptance test; ordinary RTL mapping is tested once
// the placer/router can carry both inter-LUT nets reliably.
module top(input a, input b, input c, input d, output o);
  wire ab_xor;
  wire cd_xor;

  (* keep *) LUT #(.K(4), .INIT(16'h6666)) u_ab (
    .I({2'b00, b, a}), .Q(ab_xor));
  (* keep *) LUT #(.K(4), .INIT(16'h6666)) u_cd (
    .I({2'b00, d, c}), .Q(cd_xor));
  (* keep *) LUT #(.K(4), .INIT(16'h8888)) u_both (
    .I({2'b00, cd_xor, ab_xor}), .Q(o));
endmodule
