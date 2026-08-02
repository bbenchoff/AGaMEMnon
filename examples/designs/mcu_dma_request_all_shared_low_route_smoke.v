// Hardware-free strict smoke for all sixteen DMA request sinks.
// The recovered vendor oracle used one shared source, so this test deliberately
// proves only a shared safe-low route and not independently routable nets.
module top;
  (* keep *) wire dma_request_low;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) dma_request_source(
    .I(4'b0000), .Q(dma_request_low));

  (* keep *) MCU_DMA_BREQ0 dma_breq0_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_BREQ1 dma_breq1_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_BREQ2 dma_breq2_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_BREQ3 dma_breq3_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LBREQ0 dma_lbreq0_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LBREQ1 dma_lbreq1_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LBREQ2 dma_lbreq2_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LBREQ3 dma_lbreq3_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_SREQ0 dma_sreq0_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_SREQ1 dma_sreq1_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_SREQ2 dma_sreq2_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_SREQ3 dma_sreq3_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LSREQ0 dma_lsreq0_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LSREQ1 dma_lsreq1_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LSREQ2 dma_lsreq2_sink(.DOUT(dma_request_low));
  (* keep *) MCU_DMA_LSREQ3 dma_lsreq3_sink(.DOUT(dma_request_low));
endmodule
