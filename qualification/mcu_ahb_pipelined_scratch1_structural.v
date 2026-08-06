// Structural placement discriminator for the authorized posted-write AHB
// boundary. The four pipeline/state stages occupy the qualified X14Y11
// slice4:7 pool so the registered write token reaches the scratch consumer
// through the strict graph instead of the dead slice4-Q assignment.
module top;
  wire hclk, htrans1, hwrite, hwdata0;
  wire hreadyout;
  wire hresp = 1'b0;
  wire write_data_q;
  wire write_pending_q;
  wire write_commit_q;
  wire write_apply_q;
  wire write_ready_f;
  wire scratch_f, scratch_q;

`ifdef SCRATCH1_ONE_CYCLE_WAIT
  assign hreadyout = write_ready_f;
`else
  assign hreadyout = 1'b1;
`endif

`ifdef SCRATCH1_FORCE_COMMIT
  wire scratch_commit = 1'b1;
`elsif SCRATCH1_POST_COMPLETION_COMMIT
  wire scratch_commit = write_apply_q;
`elsif SCRATCH1_SINGLE_TOKEN_STAGE
  wire scratch_commit = write_pending_q;
`else
  wire scratch_commit = write_commit_q;
`endif
`ifdef SCRATCH1_FORCE_DATA_ONE
  wire scratch_data = 1'b1;
`else
  wire scratch_data = write_data_q;
`endif

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(scratch_f));

  // Unconditional HWDATA capture: the hard input has one fabric consumer.
  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_data_stage(.CLK(hclk), .I({3'b000, hwdata0}),
                     .F(), .Q(write_data_q));

  // Address-phase write intent, then one registered delay to align with the
  // captured write-data phase.
  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    write_pending_stage(.CLK(hclk), .I({2'b00, hwrite, htrans1}),
                        .F(), .Q(write_pending_q));
`ifndef SCRATCH1_SINGLE_TOKEN_STAGE
`ifdef SCRATCH1_ONE_CYCLE_WAIT
  // Two-state wait controller. Idle is (commit_q,apply_q)=(1,0). A write
  // enters (0,0) for HWDATA capture, then (0,1) for the apply/second-wait
  // cycle, and returns ready while scratch commits at that completion edge.
  // F and Q use the qualified distinct outputs of the slice6 footprint.
  (* keep, BEL="X14Y11_SLICE6", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h3130), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk),
                       .I({write_commit_q, write_apply_q, 1'b0,
                           write_pending_q}),
                       .F(write_ready_f), .Q(write_commit_q));
`else
  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk), .I({3'b000, write_pending_q}),
                       .F(), .Q(write_commit_q));
`endif
`endif

`ifdef SCRATCH1_POST_COMPLETION_COMMIT
  // Ordinary registered apply state at slice14. It intentionally has no
  // own-Q feedback: apply_next = !write_commit_q.  The scratch LUT gates the
  // resulting two-cycle-high level with !write_commit_q, producing exactly
  // one commit at the HREADYOUT completion edge.
  (* keep, BEL="X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5555), .FF_USED(1'b1))
    write_apply_stage(.CLK(hclk),
                      .I({3'b000, write_commit_q}),
                      .F(), .Q(write_apply_q));
`endif

  // I[3] is the qualified direct-Q self-feedback branch. I[0] is the
  // registered commit token, I[1] the captured data, and I[2] reset (held low
  // in this first protocol oracle). INIT implements reset ? 0 :
  // commit ? data : scratch.
  (* keep, BEL="X14Y11_SLICE7", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4),
`ifdef SCRATCH1_ONE_CYCLE_WAIT
`ifdef SCRATCH1_POST_COMPLETION_COMMIT
`ifdef SCRATCH1_APPLY_EDGE_ONLY
                  .INIT(16'h0E04),
`else
                  .INIT(16'hEF40),
`endif
`else
                  .INIT(16'h0E04),
`endif
`else
                  .INIT(16'h0D08),
`endif
                  .FF_USED(1'b1))
    scratch_stage(.CLK(hclk),
`ifdef SCRATCH1_POST_COMPLETION_COMMIT
`ifdef SCRATCH1_APPLY_EDGE_ONLY
                  .I({scratch_q, 1'b0, scratch_data, write_commit_q}),
`else
                  .I({scratch_q, write_apply_q, scratch_data,
                      write_commit_q}),
`endif
`else
                  .I({scratch_q, 1'b0, scratch_data, scratch_commit}),
`endif
                  .F(scratch_f), .Q(scratch_q));

endmodule
