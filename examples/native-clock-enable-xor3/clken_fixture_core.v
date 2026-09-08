// Scratch consumes high8 MCU data; native data consumes low8.
// Clock-enable encoding fixture, second attempt.
//
// Built by taking area_b_regbank16_user -- the design that passes on silicon
// through this exact flow -- and changing only what is needed to expose a gated
// register and an advancing ungated neighbour. The read mux, the scratch path,
// the address/data pipeline, word 0 and word 2 are the reference verbatim.
//
// The first fixture invented its own readback and failed on silicon at its
// canary, with six MCU read lanes sharing one net where the reference shares
// none. Whether that sharing CAUSED the failure is not established -- it is a
// candidate cause. This design avoids the difference rather than relying on the
// explanation being right.
// Basic zero-wait AHB register bank.  Address/control are captured in the
// address phase; write data is consumed one cycle later in the data phase.
module area_x_clken_fixture_core(
 input clock,input reset_async,input hready,input htrans1,input hwrite,
 input[3:0]haddr,input[1:0]hsize,input[15:0]hwdata,
 output reg[31:0]hrdata);
 reg reset_meta,reset_sync,write_pending;
 reg[3:0]pending_addr;
 reg[1:0]pending_size; wire[1:0]read_word;
 reg[15:0]scratch;
 reg gate;
 wire transfer=hready&&htrans1;
 wire pending_word=(pending_size==2'b10);
 wire pending_half=(pending_size==2'b01);
 wire pending_byte=(pending_size==2'b00);
 wire low_lane=pending_word||
   (pending_half&&(pending_addr[1:0]==2'b00))||
   (pending_byte&&(pending_addr[1:0]==2'b00));
 wire high_lane=pending_word||
   (pending_half&&(pending_addr[1:0]==2'b00))||
   (pending_byte&&(pending_addr[1:0]==2'b01));
 wire scratch_write=write_pending&&(pending_addr[3:2]==2'b01);
 wire command_write=write_pending&&(pending_addr[3:2]==2'b10);
 always@(posedge clock)begin
  reset_meta<=reset_async;
  reset_sync<=reset_meta;
  if(reset_sync)begin
   write_pending<=0;pending_addr<=0;pending_size<=0;
   scratch<=0;gate<=1'b0;
  end else begin
   if(scratch_write&&low_lane)scratch[7:0]<=hwdata[15:8];
   if(scratch_write&&high_lane)scratch[15:8]<=~hwdata[15:8];
   if(write_pending&&(pending_addr[3:2]==2'b11))gate<=hwdata[0];
   write_pending<=transfer&&hwrite;
   if(transfer&&hwrite)begin pending_addr<=haddr;pending_size<=hsize;end
  end
  // Reads remain available while reset is held so reset-state contents can
  // be observed without allowing writes to retire.
  // Read selection is implemented by ordinary DFFs below.
 end

 // Keep only the observation path in ordinary data-feedback logic.
 // DFF is the existing public primitive; this is not a BEL or route constraint.
 DFF read_select0(.CLK(clock), .D((transfer&&!hwrite)?haddr[2]:read_word[0]), .Q(read_word[0]));
 DFF read_select1(.CLK(clock), .D((transfer&&!hwrite)?haddr[3]:read_word[1]), .Q(read_word[1]));

 // ---- the only functional change from the reference -------------------------
 // last_command's sixteen readback lanes are re-purposed: the low eight become
 // a free-running counter that nothing gates, the high eight become the gated
 // register. Both keep one distinct variable net per MCU read lane, which is
 // the reference's shape and the property the previous fixture lost.
 //
 // Reset-free on purpose: a synchronous reset makes yosys infer $_SDFFE_*,
 // which dffunmap lowers into a mux on D, removing the thing under test. `gate`
 // itself stays inside the reset block, so it lowers and costs no control set.
 // Exactly one control set exists in this design.
 reg[7:0]gated;
 always@(posedge clock)if(command_write&&gate)gated<=hwdata[7:0]^{hwdata[6:0],hwdata[7]}^{hwdata[4:0],hwdata[7:5]};

 // A shift register with inverted XOR feedback, not a counter. An 8-bit
 // incrementer is a carry chain, and the design then stops placing -- the same
 // "Unable to find legal placement for cell ... of type GENERIC_SLICE" wall
 // every added-logic variant of the reference hits. The inversion matters: a
 // plain LFSR seeded at zero, which is what a reset-free register powers up to,
 // never leaves zero and would look like a stopped neighbour.
 reg[7:0]freerun;
 always@(posedge clock)
  freerun<={freerun[6:0],~(freerun[7]^freerun[5]^freerun[4]^freerun[3])};

 wire[15:0]last_command={gated,freerun};

 always@*begin
  case(read_word)
   2'b00:hrdata=32'h0000a632;
   2'b01:hrdata={16'h0000,scratch};
   2'b10:hrdata=32'h00000000;
   default:hrdata={16'h0000,last_command};
  endcase
 end
endmodule
