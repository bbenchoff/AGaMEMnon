// Physical-input/output control for carry-seam qualification.
module top(input a, output y);
  wire a_buf, y_buf;
  (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) input_buffer(
      .I({3'b000, a}), .Q(a_buf));
  (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) output_buffer(
      .I({3'b000, a_buf}), .Q(y_buf));
  assign y = y_buf;
endmodule
