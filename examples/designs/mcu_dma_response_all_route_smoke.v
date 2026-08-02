// Hardware-free strict smoke for all DMA clear/terminal-count response lanes.
// It only observes MCU-driven inputs and cannot request a transfer.
module top;
  wire dma_clear0, dma_clear1, dma_clear2, dma_clear3;
  wire dma_tc0, dma_tc1, dma_tc2, dma_tc3;
  (* keep *) MCU_DMA_CLR0 dma_clear0_source(.DIN(dma_clear0));
  (* keep *) MCU_DMA_CLR1 dma_clear1_source(.DIN(dma_clear1));
  (* keep *) MCU_DMA_CLR2 dma_clear2_source(.DIN(dma_clear2));
  (* keep *) MCU_DMA_CLR3 dma_clear3_source(.DIN(dma_clear3));
  (* keep *) MCU_DMA_TC0 dma_tc0_source(.DIN(dma_tc0));
  (* keep *) MCU_DMA_TC1 dma_tc1_source(.DIN(dma_tc1));
  (* keep *) MCU_DMA_TC2 dma_tc2_source(.DIN(dma_tc2));
  (* keep *) MCU_DMA_TC3 dma_tc3_source(.DIN(dma_tc3));

  (* keep *) wire retained_probe0, retained_probe1, retained_probe2, retained_probe3;
  (* keep, BEL="X1Y4_SLICE8" *)
  LUT #(.K(4), .INIT(16'h0ff0)) probe0(
    .I({dma_clear0, dma_tc0, 2'b00}), .Q(retained_probe0));
  (* keep, BEL="X1Y4_SLICE12" *)
  LUT #(.K(4), .INIT(16'h0ff0)) probe1(
    .I({dma_clear1, dma_tc1, 2'b00}), .Q(retained_probe1));
  (* keep, BEL="X1Y4_SLICE4" *)
  LUT #(.K(4), .INIT(16'h0ff0)) probe2(
    .I({dma_clear2, dma_tc2, 2'b00}), .Q(retained_probe2));
  (* keep, BEL="X1Y4_SLICE2" *)
  LUT #(.K(4), .INIT(16'h0ff0)) probe3(
    .I({dma_clear3, dma_tc3, 2'b00}), .Q(retained_probe3));
endmodule
