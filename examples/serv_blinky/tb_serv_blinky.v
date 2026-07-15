// Simulation-only check for serv_blinky: require repeated instruction fetches and
// multiple transitions of the CPU's program-counter bit. Run:
//   iverilog -g2005 -o tb_serv_blinky.vvp tb_serv_blinky.v serv_blinky.v && vvp tb_serv_blinky.vvp
`timescale 1ns/1ps
module tb_serv_blinky;
    reg clock = 0;
    reg reset = 1;
    wire led;

    serv_blinky #(.BLINK_ADDRESS_BIT(10)) dut (.clock(clock), .reset(reset), .led(led));

    always #20 clock = ~clock;                       // 25 MHz

    integer fetches = 0;
    integer stores = 0;
    always @(posedge clock)
        if (!reset && dut.mem_stb && dut.mem_ack) begin
            if (dut.mem_we) stores = stores + 1;
            else fetches = fetches + 1;
        end

    integer transitions = 0;
    always @(led) if (!reset) begin
        transitions = transitions + 1;
        if (transitions <= 4)
            $display("led=%b after %0d fetches", led, fetches);
    end

    initial begin
        repeat (16) @(posedge clock);
        reset <= 0;
        repeat (400_000) @(posedge clock);
        if (transitions >= 16 && fetches >= 1000 && stores >= 1000)
            $display("PASS: %0d PC-bit LED toggles from %0d fetches and %0d stores",
                     transitions, fetches, stores);
        else
            $display("FAIL: transitions=%0d fetches=%0d stores=%0d",
                     transitions, fetches, stores);
        $finish;
    end
endmodule
