module ag32_uart_tx #(
    parameter integer CLOCKS_PER_BIT = 217
) (
    input  wire       clock,
    input  wire       reset_n,
    input  wire       start,
    input  wire [7:0] data,
    output wire       tx,
    output reg        busy,
    output reg        done
);
    reg [31:0] divider;
    reg [3:0] bit_number;
    reg [9:0] frame;

    assign tx = busy ? frame[0] : 1'b1;

    always @(posedge clock) begin
        if (!reset_n) begin
            divider <= 0;
            bit_number <= 0;
            frame <= 10'h3ff;
            busy <= 0;
            done <= 0;
        end else begin
            done <= 0;
            if (!busy) begin
                if (start) begin
                    frame <= {1'b1, data, 1'b0};
                    divider <= 0;
                    bit_number <= 0;
                    busy <= 1;
                end
            end else if (divider == CLOCKS_PER_BIT - 1) begin
                divider <= 0;
                if (bit_number == 9) begin
                    busy <= 0;
                    done <= 1;
                end else begin
                    frame <= {1'b1, frame[9:1]};
                    bit_number <= bit_number + 1'b1;
                end
            end else
                divider <= divider + 1'b1;
        end
    end
endmodule
