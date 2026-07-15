// Protocol-valid full-width HRDATA qualification.  During an AHB read the
// address remains stable, so 26 independent address bits can drive 32 read
// sinks with an exact expected value.  This mirrors vendor-ahbraddr32.
module top;
  wire [31:0] haddr;
  wire [31:0] source_data;
  wire [31:0] hrdata;

  (* keep *) MCU_DIN mcu_haddr2 (.DIN(haddr[2]));
  (* keep *) MCU_DIN mcu_haddr3 (.DIN(haddr[3]));
  (* keep *) MCU_DIN mcu_haddr4 (.DIN(haddr[4]));
  (* keep *) MCU_DIN mcu_haddr5 (.DIN(haddr[5]));
  (* keep *) MCU_DIN mcu_haddr6 (.DIN(haddr[6]));
  (* keep *) MCU_DIN mcu_haddr7 (.DIN(haddr[7]));
  (* keep *) MCU_DIN mcu_haddr8 (.DIN(haddr[8]));
  (* keep *) MCU_DIN mcu_haddr9 (.DIN(haddr[9]));
  (* keep *) MCU_DIN mcu_haddr10(.DIN(haddr[10]));
  (* keep *) MCU_DIN mcu_haddr11(.DIN(haddr[11]));
  (* keep *) MCU_DIN mcu_haddr12(.DIN(haddr[12]));
  (* keep *) MCU_DIN mcu_haddr13(.DIN(haddr[13]));
  (* keep *) MCU_DIN mcu_haddr14(.DIN(haddr[14]));
  (* keep *) MCU_DIN mcu_haddr15(.DIN(haddr[15]));
  (* keep *) MCU_DIN mcu_haddr16(.DIN(haddr[16]));
  (* keep *) MCU_DIN mcu_haddr17(.DIN(haddr[17]));
  (* keep *) MCU_DIN mcu_haddr18(.DIN(haddr[18]));
  (* keep *) MCU_DIN mcu_haddr19(.DIN(haddr[19]));
  (* keep *) MCU_DIN mcu_haddr20(.DIN(haddr[20]));
  (* keep *) MCU_DIN mcu_haddr21(.DIN(haddr[21]));
  (* keep *) MCU_DIN mcu_haddr22(.DIN(haddr[22]));
  (* keep *) MCU_DIN mcu_haddr23(.DIN(haddr[23]));
  (* keep *) MCU_DIN mcu_haddr24(.DIN(haddr[24]));
  (* keep *) MCU_DIN mcu_haddr25(.DIN(haddr[25]));
  (* keep *) MCU_DIN mcu_haddr26(.DIN(haddr[26]));
  (* keep *) MCU_DIN mcu_haddr27(.DIN(haddr[27]));

  assign source_data = {haddr[7:2], haddr[27:2]};
  genvar i;
  generate
    for (i = 0; i < 32; i = i + 1) begin: route_shape
      if (i == 9 || i == 15) begin: buffered
        (* keep *) LUT #(.K(4), .INIT(16'hff00)) identity
          (.I({source_data[i], 3'b000}), .Q(hrdata[i]));
      end else begin: direct
        assign hrdata[i] = source_data[i];
      end
    end
  endgenerate

  (* keep *) MCU_DOUT mcu_h0 (.DOUT(hrdata[0]));
  (* keep *) MCU_DOUT mcu_h1 (.DOUT(hrdata[1]));
  (* keep *) MCU_DOUT mcu_h2 (.DOUT(hrdata[2]));
  (* keep *) MCU_DOUT mcu_h3 (.DOUT(hrdata[3]));
  (* keep *) MCU_DOUT mcu_h4 (.DOUT(hrdata[4]));
  (* keep *) MCU_DOUT mcu_h5 (.DOUT(hrdata[5]));
  (* keep *) MCU_DOUT mcu_h6 (.DOUT(hrdata[6]));
  (* keep *) MCU_DOUT mcu_h7 (.DOUT(hrdata[7]));
  (* keep *) MCU_DOUT mcu_h8 (.DOUT(hrdata[8]));
  (* keep *) MCU_DOUT mcu_h9 (.DOUT(hrdata[9]));
  (* keep *) MCU_DOUT mcu_h10(.DOUT(hrdata[10]));
  (* keep *) MCU_DOUT mcu_h11(.DOUT(hrdata[11]));
  (* keep *) MCU_DOUT mcu_h12(.DOUT(hrdata[12]));
  (* keep *) MCU_DOUT mcu_h13(.DOUT(hrdata[13]));
  (* keep *) MCU_DOUT mcu_h14(.DOUT(hrdata[14]));
  (* keep *) MCU_DOUT mcu_h15(.DOUT(hrdata[15]));
  (* keep *) MCU_DOUT mcu_h16(.DOUT(hrdata[16]));
  (* keep *) MCU_DOUT mcu_h17(.DOUT(hrdata[17]));
  (* keep *) MCU_DOUT mcu_h18(.DOUT(hrdata[18]));
  (* keep *) MCU_DOUT mcu_h19(.DOUT(hrdata[19]));
  (* keep *) MCU_DOUT mcu_h20(.DOUT(hrdata[20]));
  (* keep *) MCU_DOUT mcu_h21(.DOUT(hrdata[21]));
  (* keep *) MCU_DOUT mcu_h22(.DOUT(hrdata[22]));
  (* keep *) MCU_DOUT mcu_h23(.DOUT(hrdata[23]));
  (* keep *) MCU_DOUT mcu_h24(.DOUT(hrdata[24]));
  (* keep *) MCU_DOUT mcu_h25(.DOUT(hrdata[25]));
  (* keep *) MCU_DOUT mcu_h26(.DOUT(hrdata[26]));
  (* keep *) MCU_DOUT mcu_h27(.DOUT(hrdata[27]));
  (* keep *) MCU_DOUT mcu_h28(.DOUT(hrdata[28]));
  (* keep *) MCU_DOUT mcu_h29(.DOUT(hrdata[29]));
  (* keep *) MCU_DOUT mcu_h30(.DOUT(hrdata[30]));
  (* keep *) MCU_DOUT mcu_h31(.DOUT(hrdata[31]));
endmodule
