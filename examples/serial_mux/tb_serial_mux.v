// Simulation-only check for serial_mux: three senders schedule non-overlapping
// framed bytes and a same-rate monitor decodes tx. Passes only when the exact
// ABCABC... sequence arrives. Run:
//   iverilog -o tb_serial_mux.vvp tb_serial_mux.v serial_mux.v && vvp tb_serial_mux.vvp
`timescale 1ns/1ps
module LUT #(parameter integer K = 4, parameter [15:0] INIT = 16'h0000)(
    input wire [K-1:0] I, output wire Q
);
    assign Q = INIT[I];
endmodule

module tb_serial_mux;
    localparam integer CLK_HZ  = 25_000_000;
    localparam integer RX_BAUD = 24414;
    localparam integer TX_BAUD = 24414;
    localparam integer RX_BIT_NS = 1_000_000_000 / RX_BAUD;
    localparam integer TX_BIT_NS = 1_000_000_000 / TX_BAUD;
    localparam integer BYTES_PER_CH = 4;

    reg clock = 0;
    always #20 clock = ~clock;                       // 25 MHz

    reg rx_a = 1, rx_b = 1, rx_c = 1;
    wire tx;

    serial_mux dut (.clock(clock), .rx_a(rx_a), .rx_b(rx_b), .rx_c(rx_c), .tx(tx));

    // Per-line senders use fixed slots: A, then B, then C, with no overlap.
    integer got_count = 0;
    reg [7:0] got [0:31];

    // TX monitor: wait for start edge, sample mid-bit.
    initial begin : monitor
        integer k;
        reg [7:0] b;
        forever begin
            @(negedge tx);
            #(TX_BIT_NS/2);
            if (tx === 1'b0) begin                   // confirmed start bit
                for (k = 0; k < 8; k = k + 1) begin
                    #(TX_BIT_NS);
                    b[k] = tx;
                end
                #(TX_BIT_NS);                        // stop bit
                if (tx !== 1'b1) $display("FAIL: bad stop bit");
                got[got_count] = b;
                got_count = got_count + 1;
            end
        end
    end

    integer ia, ib, ic;
    initial begin : sender_a
        #1000;
        for (ia = 0; ia < BYTES_PER_CH; ia = ia + 1) begin : fa
            integer k;
            rx_a = 0; #(RX_BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rx_a = ("A" >> k) & 1; #(RX_BIT_NS);
            end
            rx_a = 1; #(RX_BIT_NS);
            #(RX_BIT_NS * 20);
        end
    end
    initial begin : sender_b
        #(1000 + RX_BIT_NS * 10);
        for (ib = 0; ib < BYTES_PER_CH; ib = ib + 1) begin : fb
            integer k;
            rx_b = 0; #(RX_BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rx_b = ("B" >> k) & 1; #(RX_BIT_NS);
            end
            rx_b = 1; #(RX_BIT_NS);
            #(RX_BIT_NS * 20);
        end
    end
    initial begin : sender_c
        #(1000 + RX_BIT_NS * 20);
        for (ic = 0; ic < BYTES_PER_CH; ic = ic + 1) begin : fc
            integer k;
            rx_c = 0; #(RX_BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rx_c = ("C" >> k) & 1; #(RX_BIT_NS);
            end
            rx_c = 1; #(RX_BIT_NS);
            #(RX_BIT_NS * 20);
        end
    end

    integer i, na, nb, nc, mismatch;
    initial begin
        // Twelve input frames plus enough time to drain the 4x-rate output.
        #(RX_BIT_NS * 10 * (BYTES_PER_CH + 2) + TX_BIT_NS * 10 * 16);
        na = 0; nb = 0; nc = 0; mismatch = 0;
        $write("muxed: ");
        for (i = 0; i < got_count; i = i + 1) begin
            $write("%c", got[i]);
            case (got[i])
                "A": na = na + 1;
                "B": nb = nb + 1;
                "C": nc = nc + 1;
                default: begin $display("\nFAIL: unexpected byte %02x", got[i]); $finish; end
            endcase
            if (got[i] !== (i % 3 == 0 ? "A" : (i % 3 == 1 ? "B" : "C")))
                mismatch = 1;
        end
        $write("\n");
        if (got_count == 3*BYTES_PER_CH && !mismatch &&
            na == BYTES_PER_CH && nb == BYTES_PER_CH && nc == BYTES_PER_CH)
            $display("PASS: %0d bytes, %0d per channel", got_count, BYTES_PER_CH);
        else
            $display("FAIL: counts A=%0d B=%0d C=%0d (expected %0d each)", na, nb, nc, BYTES_PER_CH);
        $finish;
    end
endmodule
