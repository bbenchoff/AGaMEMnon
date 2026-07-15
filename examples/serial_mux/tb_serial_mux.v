`timescale 1ns/1ps
module tb_serial_mux;
    localparam integer RX_BAUD = 9_600;
    localparam integer TX_BAUD = 115_200;
    localparam integer RX_BIT_NS = 1_000_000_000 / RX_BAUD;
    localparam integer TX_BIT_NS = 1_000_000_000 / TX_BAUD;
    localparam integer ROUNDS = 8;

    reg clock = 0;
    always #20 clock = ~clock;
    reg rx_a = 1, rx_b = 1, rx_c = 1;
    wire tx;
    serial_mux dut (.clock(clock), .rx_a(rx_a), .rx_b(rx_b), .rx_c(rx_c), .tx(tx));

    task send_a; input [7:0] value; integer k; begin
        rx_a=0; #(RX_BIT_NS); for(k=0;k<8;k=k+1) begin rx_a=value[k]; #(RX_BIT_NS); end
        rx_a=1; #(RX_BIT_NS);
    end endtask
    task send_b; input [7:0] value; integer k; begin
        rx_b=0; #(RX_BIT_NS); for(k=0;k<8;k=k+1) begin rx_b=value[k]; #(RX_BIT_NS); end
        rx_b=1; #(RX_BIT_NS);
    end endtask
    task send_c; input [7:0] value; integer k; begin
        rx_c=0; #(RX_BIT_NS); for(k=0;k<8;k=k+1) begin rx_c=value[k]; #(RX_BIT_NS); end
        rx_c=1; #(RX_BIT_NS);
    end endtask

    integer got_count = 0;
    reg [7:0] got [0:63];
    initial begin : monitor
        integer k; reg [7:0] value;
        forever begin
            @(negedge tx); #(TX_BIT_NS/2);
            if (!tx) begin
                for(k=0;k<8;k=k+1) begin #(TX_BIT_NS); value[k]=tx; end
                #(TX_BIT_NS);
                if (!tx) begin $display("FAIL: bad TX stop bit"); $finish; end
                got[got_count]=value; got_count=got_count+1;
            end
        end
    end

    integer round;
    initial begin
        #10000;
        for(round=0; round<ROUNDS; round=round+1) fork
            send_a("A"); send_b("B"); send_c("C");
        join
    end

    integer i; integer mismatch;
    initial begin
        #(RX_BIT_NS * 10 * (ROUNDS+2));
        mismatch=0;
        $write("muxed: ");
        for(i=0;i<got_count;i=i+1) begin
            $write("%c",got[i]);
            if (got[i] !== (i%3==0 ? "A" : (i%3==1 ? "B" : "C"))) mismatch=1;
        end
        $write("\n");
        if (got_count == 3*ROUNDS && !mismatch && !dut.overflow)
            $display("PASS: %0d overlapping input frames buffered in round-robin order",got_count);
        else
            $display("FAIL: got=%0d expected=%0d mismatch=%0d overflow=%0d",
                     got_count,3*ROUNDS,mismatch,dut.overflow);
        $finish;
    end
endmodule
