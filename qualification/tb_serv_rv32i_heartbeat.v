`timescale 1ns/1ps
module tb_serv_rv32i_heartbeat;
    reg clock = 0;
    reg reset = 1;
    wire pass;
    serv_rv32i_smoke dut (.clock(clock), .reset(reset), .pass(pass));
    always #20 clock = ~clock;

    integer fetches = 0;
    integer stores = 0;
    integer heartbeat_edges = 0;
    reg last_pass = 0;
    reg seen_signature = 0;
    always @(posedge clock) begin
        if (reset) begin
            last_pass = 0;
        end else begin
            if (pass != last_pass)
                heartbeat_edges = heartbeat_edges + 1;
            last_pass = pass;
            if (dut.mem_stb && dut.mem_ack) begin
                if (dut.mem_we) begin
                    stores = stores + 1;
                    if (dut.mem_dat == 32'd19)
                        seen_signature = 1;
                end else begin
                    fetches = fetches + 1;
                end
            end
        end
    end

    initial begin
        repeat (16) @(posedge clock);
        reset <= 0;
        repeat (120_000) @(posedge clock);
        if (seen_signature && heartbeat_edges >= 5 && stores >= 5 && fetches > 100)
            $display("PASS: repeated SERV success; fetches=%0d stores=%0d heartbeat_edges=%0d",
                     fetches, stores, heartbeat_edges);
        else
            $display("FAIL: signature=%b fetches=%0d stores=%0d heartbeat_edges=%0d",
                     seen_signature, fetches, stores, heartbeat_edges);
        $finish;
    end
endmodule
